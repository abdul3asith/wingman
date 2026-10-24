"""Transcript -> SessionExtract (contract). OWNER: Person A."""
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from app import llm
from app.config import settings
from app.contract import Company, Person, Promise, SessionExtract


# LLM-facing models: no defaults (OpenAI strict schema), assembled into the contract afterwards.
class _PersonOut(BaseModel):
    name: str
    role: str | None
    role_class: Literal["engineer", "recruiter", "founder", "investor", "pm_design", "other"]
    email: str | None
    linkedin: str | None  # not in the frozen contract; kept in LINKEDIN below and written by the agent store
    persona: Literal["investor", "accelerator", "founder", "candidate", "other"]  # who they are to a founder


# Side channels keyed by session_id (SessionExtract is frozen): LinkedIn URL said, and persona.
LINKEDIN: dict[str, str] = {}
PERSONA: dict[str, str] = {}
MEMORY: dict[str, dict] = {}  # session_id -> {category, context, facts: [{kind, text}]}


def _linkedin_url(handle: str | None) -> str | None:
    if not handle:
        return None
    m = re.search(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)", handle)
    h = m.group(1) if m else re.sub(r"[^a-z0-9\-]", "", handle.lower().lstrip("@"))
    return f"https://www.linkedin.com/in/{h}" if h else None


class _CompanyOut(BaseModel):
    name: str
    domain: str | None


class _PromiseOut(BaseModel):
    by: Literal["me", "them"]
    text: str
    doer_speaker: str | None  # "Speaker N" who will DO it (labeled transcripts); code derives `by` from it


class _FactOut(BaseModel):
    kind: Literal["job", "opportunity", "advice", "contact", "next_step", "personal", "other"]
    text: str


class _ExtractOut(BaseModel):
    me_speaker: str | None  # which "Speaker N" is the user; null for a solo debrief
    summary: str
    person: _PersonOut
    company: _CompanyOut | None
    topics: list[str]
    promises: list[_PromiseOut]
    # event memory (teammate's graph: Session-[:LEARNED]->Fact), kept in MEMORY below
    category: Literal["hiring", "technical", "partnership", "fundraising", "customer", "social", "other"]
    context: str
    facts: list[_FactOut]


# Speaker attribution is the hardest part of extraction and everything downstream (fulfilment lines, drafts)
# depends on it, so this one call uses a stronger model than the rest of the app.
EXTRACT_MODEL = "gpt-4o"


PROMPT = """You are reading a transcript recorded by {user} at {event}. It is one of two kinds:

1. A speaker-labeled recording of a conversation ("Speaker 0: ...", "Speaker 1: ...") between {user} and
   someone else. {user} is the person holding the recorder and may never say their own name. Work in two steps.
   Step 1: decide which label is {user} (call it ME) and which is the other person (call it THEM), using
   introductions ("I'm ..."), who is asking about whom, and {user}'s background ({skills}). THEM is usually the
   one who states their company, hands over their email, or offers a referral or job; ME is usually the one asking
   about them and collecting the contact. Extract THEM as `person`; ME is never `person`.
   Put ME's label in me_speaker (e.g. "Speaker 1").
   Step 2: for every promise, set doer_speaker to the label of the person who will DO the thing — not
   necessarily who said the line. Examples, with Speaker 0 = THEM and Speaker 1 = ME:
     "Speaker 0: I'll send you the blog post"                     -> doer_speaker "Speaker 0", "Send the blog post"
     "Speaker 0: Send me your repo." / "Speaker 1: Will do."       -> doer_speaker "Speaker 1", "Send my repo"
     "Speaker 1: Could you intro me to your CTO?" / "Speaker 0: Sure" -> doer_speaker "Speaker 0", "Intro to their CTO"
   If more than two speakers appear, THEM is the person {user} talked with the most.
2. A solo voice debrief spoken by {user} about a conversation they just had. The speaker is {user} ("me");
   extract the person they describe; by="me" for what {user} promised, by="them" for what that person promised.
   me_speaker and every doer_speaker are null.

In both cases return exactly one person (the OTHER person, never {user}) with:
- role: a short normalized job title ("ML Engineer", "Head of Platform Engineering"). role_class is exactly one of
  engineer | recruiter | founder | investor | pm_design | other, from their actual job: an engineering leader is
  "engineer", not "recruiter", even if they offered a referral.
- company: the name as spoken, best-effort spelling (it is resolved against the web later). domain only if it was
  said or is unambiguous, else null.
- topics: 2-4 short lowercase noun phrases, no duplicates, specific over generic ("kv cache", "inference serving",
  not "ai" or "tech").
- promises: every commitment either side made, each as a short imperative naming the thing ("Send my benchmark
  repo"), never "it". A request plus its acceptance is ONE promise. A request nobody agreed to is not a promise.
  `by` is "me" if {user} will do it, else "them".
- summary: one factual sentence.
- email: only if it was explicitly said; spoken forms like "maya at parallaxlabs dot ai" become maya@parallaxlabs.ai.
  NEVER guess or construct an email. Any unknown field is null.
- linkedin: the handle or URL only if THEM said it ("find me on LinkedIn, sarahchen" -> "sarahchen"), else null.
- category: hiring, technical, partnership, fundraising, customer, social or other.
- context: one sentence on what this conversation was about.
- facts: 1-5 atomic, specific things {user} learned from THEM ("Foundry Lane's winter batch closes Nov 15",
  "Lattice is hiring backend engineers, remote, Python and Go"), each with a kind: job, opportunity, advice,
  contact, next_step, personal or other. Never restate the promises as facts.
- persona: who THEM is to {user}, a startup founder: "investor" (VC, angel, fund partner/associate),
  "accelerator" (partner/staff at an accelerator or incubator program, e.g. YC, Techstars), "founder" (founder or
  co-founder of their own company), "candidate" (someone {user} could hire: engineer, designer, PM, operator not
  founding their own company), else "other".

TRANSCRIPT:
{transcript}"""

MAX_TOPICS = 4

MOCK_EXTRACT = _ExtractOut(
    me_speaker="Speaker 1",
    summary="Met Maya Lindqvist, an ML engineer at Parallax Labs, to talk speculative decoding and CUDA graphs; she offered a referral for their inference engineer role.",
    person=_PersonOut(name="Maya Lindqvist", role="ML Engineer", role_class="engineer", email="maya@parallaxlabs.ai",
                      linkedin="maya-lindqvist-demo", persona="candidate"),
    company=_CompanyOut(name="Parallax Labs", domain="parallaxlabs.ai"),
    topics=["speculative decoding", "gpu inference", "cuda"],
    category="technical",
    context="Compared notes on speculative decoding and CUDA benchmarking; Parallax Labs is hiring an inference engineer.",
    facts=[_FactOut(kind="job", text="Parallax Labs is hiring an inference engineer; Maya can refer."),
           _FactOut(kind="advice", text="A small draft model in front of the big one gave Parallax about a 2x speedup.")],
    promises=[
        _PromiseOut(by="them", text="Send the speculative decoding blog post", doer_speaker="Speaker 0"),
        _PromiseOut(by="me", text="Send my CUDA benchmark repo", doer_speaker="Speaker 1"),
    ],
)


def _email_was_said(email: str | None, transcript: str) -> bool:
    """Guardrail: keep an email only if its local part actually appears in the transcript."""
    if not email or "@" not in email:
        return False
    return email.split("@")[0].lower().replace(".", " ") in transcript.lower().replace(".", " ")


class NoPersonFound(ValueError):
    """The transcript doesn't say who was met; routes turn this into a 422 instead of writing a junk Person."""


_JUNK_NAMES = {"", "null", "none", "unknown", "n/a", "na", "them", "the person", "speaker", "speaker 0", "speaker 1"}


def _attribute_promises(out: _ExtractOut) -> None:
    """Labeled transcripts: `by` comes from the speaker labels, not the model's own me/them guess."""
    norm = lambda s: (s or "").strip().lower()  # noqa: E731
    me = norm(out.me_speaker)
    if not me:
        return
    for p in out.promises:
        if norm(p.doer_speaker):
            p.by = "me" if norm(p.doer_speaker) == me else "them"


def _name_was_said(name: str | None, transcript: str) -> bool:
    """Guardrail against invented people ("John Doe"): some part of the name must appear in the transcript."""
    low = transcript.lower()
    return any(len(part) >= 3 and part in low for part in (name or "").lower().split())


def extract(session_id: str, transcript: str, started_at: str | None = None) -> SessionExtract:
    if settings.MOCK_MODE:
        out = MOCK_EXTRACT
    else:
        prompt = PROMPT.format(
            user=settings.USER_NAME, event=settings.EVENT_NAME, skills=", ".join(settings.USER_SKILLS), transcript=transcript
        )
        try:
            out = llm.parse(prompt, _ExtractOut, model=EXTRACT_MODEL)
        except Exception as e:
            print(f"[extract] {EXTRACT_MODEL} failed ({e}); retrying with {settings.OPENAI_CHAT_MODEL}")
            out = llm.parse(prompt, _ExtractOut)
        _attribute_promises(out)
        if not _email_was_said(out.person.email, transcript):
            out.person.email = None
        if out.company and out.company.name.strip().lower() in _JUNK_NAMES:
            out.company = None
    if (out.person.name or "").strip().lower() in _JUNK_NAMES or not _name_was_said(out.person.name, transcript):
        raise NoPersonFound("couldn't tell who you met — say their name and try again")
    if url := _linkedin_url(out.person.linkedin):
        LINKEDIN[session_id] = url
    PERSONA[session_id] = out.person.persona
    MEMORY[session_id] = {"category": out.category, "context": out.context,
                          "facts": [f.model_dump() for f in out.facts if f.text.strip()][:5]}
    return SessionExtract(
        session_id=session_id,
        started_at=started_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        transcript=transcript,
        summary=out.summary,
        person=Person(**out.person.model_dump(exclude={"linkedin", "persona"})),
        company=Company(**out.company.model_dump()) if out.company else None,
        topics=list(dict.fromkeys(t.strip().lower() for t in out.topics if t.strip()))[:MAX_TOPICS],
        promises=[Promise(**p.model_dump()) for p in out.promises],
    )
