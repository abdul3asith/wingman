"""Transcript -> SessionExtract (contract). OWNER: Person A."""
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


class _CompanyOut(BaseModel):
    name: str
    domain: str | None


class _PromiseOut(BaseModel):
    by: Literal["me", "them"]
    text: str


class _ExtractOut(BaseModel):
    summary: str
    person: _PersonOut
    company: _CompanyOut | None
    topics: list[str]
    promises: list[_PromiseOut]


PROMPT = """You are reading a voice debrief recorded by {user} right after a conversation at {event}.
The speaker is the user ("me"). Extract the OTHER person only.

Rules:
- person.role: a short normalized title ("ML Engineer", "Technical Recruiter"). role_class is exactly one of
  engineer | recruiter | founder | investor | pm_design | other.
- company: the name as spoken, best-effort spelling (it is resolved against the web later). domain only if it was
  said or is unambiguous, else null.
- topics: 2-4 short lowercase noun phrases, no duplicates, specific over generic ("kv cache", "inference serving",
  not "ai" or "tech").
- promises: anything either side committed to. by="me" when {user} promised it, by="them" when the other person did.
  Phrase each as a short imperative ("Send the cold start blog post").
- summary: one factual sentence.
- email: only if it was explicitly said; spoken forms like "maya at parallaxlabs dot ai" become maya@parallaxlabs.ai.
  NEVER guess or construct an email. Any unknown field is null.

TRANSCRIPT:
{transcript}"""

MAX_TOPICS = 4

MOCK_EXTRACT = _ExtractOut(
    summary="Met Maya Lindqvist, an ML engineer at Parallax Labs, to talk speculative decoding and CUDA graphs; she offered a referral for their inference engineer role.",
    person=_PersonOut(name="Maya Lindqvist", role="ML Engineer", role_class="engineer", email="maya@parallaxlabs.ai"),
    company=_CompanyOut(name="Parallax Labs", domain="parallaxlabs.ai"),
    topics=["speculative decoding", "gpu inference", "cuda"],
    promises=[
        _PromiseOut(by="them", text="Send the speculative decoding blog post"),
        _PromiseOut(by="me", text="Send my CUDA benchmark repo"),
    ],
)


def _email_was_said(email: str | None, transcript: str) -> bool:
    """Guardrail: keep an email only if its local part actually appears in the transcript."""
    if not email or "@" not in email:
        return False
    return email.split("@")[0].lower().replace(".", " ") in transcript.lower().replace(".", " ")


def extract(session_id: str, transcript: str, started_at: str | None = None) -> SessionExtract:
    if settings.MOCK_MODE:
        out = MOCK_EXTRACT
    else:
        out = llm.parse(PROMPT.format(user=settings.USER_NAME, event=settings.EVENT_NAME, transcript=transcript), _ExtractOut)
        if not _email_was_said(out.person.email, transcript):
            out.person.email = None
    return SessionExtract(
        session_id=session_id,
        started_at=started_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        transcript=transcript,
        summary=out.summary,
        person=Person(**out.person.model_dump()),
        company=Company(**out.company.model_dump()) if out.company else None,
        topics=list(dict.fromkeys(t.strip().lower() for t in out.topics if t.strip()))[:MAX_TOPICS],
        promises=[Promise(**p.model_dump()) for p in out.promises],
    )
