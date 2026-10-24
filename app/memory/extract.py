"""One conversation -> structured memory (person, category, context, topics, facts, promises, goal relevance).

One `llm.parse` structured-output call per conversation. MOCK_MODE returns canned extractions that match the
mock recording in `app.ingest.transcribe.MOCK_TURNS`.
"""
import re
from typing import Literal

from pydantic import BaseModel

from app import llm
from app.config import settings
from app.contract import RoleClass
from app.ingest.turns import to_text
from app.memory.segment import Conversation

Category = Literal["hiring", "technical", "partnership", "fundraising", "customer", "social", "other"]
FactKind = Literal["job", "opportunity", "advice", "contact", "next_step", "personal", "other"]


class LLMError(RuntimeError):
    """An extraction or embedding call failed. The route turns this into a 502 and keeps the upload pending."""


# LLM-facing models: no defaults anywhere, because OpenAI's strict structured-output schema forbids them.
class PersonOut(BaseModel):
    name: str | None
    role: str | None
    role_class: RoleClass
    company: str | None
    domain: str | None
    email: str | None


class FactOut(BaseModel):
    kind: FactKind
    text: str


class PromiseOut(BaseModel):
    by: Literal["me", "them"]
    text: str


class GoalRelevanceOut(BaseModel):
    score: float
    reason: str


class ConversationExtract(BaseModel):
    person: PersonOut
    category: Category
    context: str
    topics: list[str]
    facts: list[FactOut]
    promises: list[PromiseOut]
    goal_relevance: GoalRelevanceOut


PROMPT = """{user} recorded this conversation at {event}. Lines labeled "You:" are {user}; "Speaker N:" lines are
other people. {user}'s skills: {skills}. {user}'s goal: "{goal}".

Return:
- person: the main other person. name is null if it was never said (never invent a name). role, company and
  domain (the company's website domain such as "parallaxlabs.ai", not its industry; guess it or return null),
  email (only if spoken; else null). role_class is one of engineer, recruiter, founder,
  investor, pm_design, other.
- category: hiring, technical, partnership, fundraising, customer, social or other.
- context: ONE sentence on what the conversation was about. Not a summary.
- topics: 2-5 short lowercase tags (e.g. "gpu inference", "seed round").
- facts: short, atomic, self-contained statements {user} learned, each understandable without the transcript.
  Name the company or person in each fact. kind is job, opportunity, advice, contact, next_step, personal or
  other. Keep every job detail (title, team, remote/onsite, location, stack, interview rounds, compensation,
  links) as job facts, e.g. "Lattice Compute is hiring backend and inference engineers; remote; Python and Go;
  3 interview rounds." Spoken emails like "maya at parallaxlabs dot ai" become maya@parallaxlabs.ai; never
  invent an email address.
- promises: by "me" when {user} promised something, by "them" when the other person did.
- goal_relevance: score from 0 to 1 for how much this conversation helps {user}'s goal, and a one-sentence
  reason saying how it helps or why it doesn't.

CONVERSATION:
{transcript}"""

MOCK_MAYA = ConversationExtract(
    person=PersonOut(name="Maya Lindqvist", role="ML Engineer", role_class="engineer", company="Parallax Labs",
                     domain="parallaxlabs.ai", email="maya@parallaxlabs.ai"),
    category="technical",
    context="Swapped notes on speculative decoding and CUDA graph capture with an ML engineer at Parallax Labs.",
    topics=["speculative decoding", "gpu inference", "cuda"],
    facts=[
        FactOut(kind="opportunity", text="Parallax Labs is hiring an inference engineer; Maya Lindqvist offered to refer you."),
        FactOut(kind="advice", text="Parallax Labs runs a small draft model in front of the large one for speculative decoding and got about a 2x speedup."),
        FactOut(kind="contact", text="Maya Lindqvist's email is maya@parallaxlabs.ai."),
    ],
    promises=[PromiseOut(by="them", text="Send the speculative decoding blog post"),
              PromiseOut(by="me", text="Send my CUDA benchmark repo")],
    goal_relevance=GoalRelevanceOut(score=0.55, reason="Mostly a technical chat, but her referral offer for Parallax Labs' inference engineer role is a possible path to getting hired."),
)

MOCK_JORDAN = ConversationExtract(
    person=PersonOut(name="Jordan Reyes", role="Technical Recruiter", role_class="recruiter", company="Lattice Compute",
                     domain="latticecompute.ai", email=None),
    category="hiring",
    context="A technical recruiter at Lattice Compute pitched their open backend and inference engineer roles.",
    topics=["hiring", "backend engineering", "inference", "remote work"],
    facts=[
        FactOut(kind="job", text="Lattice Compute is hiring backend and inference engineers; remote; Python and Go; 3 interview rounds."),
        FactOut(kind="job", text="Lattice Compute's interview rounds are a recruiter screen, a technical systems deep dive and a final round with the team."),
        FactOut(kind="next_step", text="Jordan Reyes will send the Lattice Compute job link today."),
    ],
    promises=[PromiseOut(by="them", text="Send the job link"), PromiseOut(by="me", text="Email my resume tonight")],
    goal_relevance=GoalRelevanceOut(score=0.9, reason="A recruiter with open backend and inference engineer roles that match your goal of getting hired as a software engineer."),
)

MOCK_OTHER = ConversationExtract(
    person=PersonOut(name=None, role=None, role_class="other", company=None, domain=None, email=None),
    category="other",
    context="A short exchange with no clear topic.",
    topics=["small talk", "networking"],
    facts=[],
    promises=[],
    goal_relevance=GoalRelevanceOut(score=0.1, reason="Nothing in this exchange relates to the goal."),
)

_KEY = re.compile(r"sk-[A-Za-z0-9_\-*]{4,}")


def scrub_error(e: Exception) -> str:
    """Error text for the API response, with anything that looks like an OpenAI key masked."""
    return _KEY.sub("sk-***", f"{type(e).__name__}: {e}")[:400]


def _mock(conv: Conversation) -> ConversationExtract:
    text = " ".join(t.text for t in conv.turns).lower()
    if "jordan" in text or "recruiter" in text:
        return MOCK_JORDAN
    if "maya" in text or "parallax" in text:
        return MOCK_MAYA
    return MOCK_OTHER


def _clean(x: ConversationExtract) -> ConversationExtract:
    x.topics = [" ".join(t.lower().split()) for t in x.topics if t.strip()][:5]
    x.facts = [f for f in x.facts if f.text.strip()]
    x.goal_relevance.score = max(0.0, min(1.0, float(x.goal_relevance.score)))
    if x.person.name is not None and not x.person.name.strip():
        x.person.name = None
    return x


def extract(conv: Conversation, me: int) -> ConversationExtract:
    if settings.MOCK_MODE:
        return _mock(conv).model_copy(deep=True)
    prompt = PROMPT.format(
        user=settings.USER_NAME, event=settings.EVENT_NAME, skills=", ".join(settings.USER_SKILLS),
        goal=settings.USER_GOAL, transcript=to_text(conv.turns, me=me),
    )
    try:
        return _clean(llm.parse(prompt, ConversationExtract))
    except Exception as e:  # openai errors, refusals, missing key: all surface as a 502
        raise LLMError(f"extraction failed for conversation {conv.seq}: {scrub_error(e)}") from e
