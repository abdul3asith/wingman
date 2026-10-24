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
Extract exactly one person (the one they talked to), their role and role_class, their company (guess the domain
from the name if obvious, else null), 3-6 short lowercase topic tags (e.g. "gpu inference", "cold starts"), and every
promise: by="me" when {user} promised something, by="them" when the other person did. Spoken emails like
"maya at parallaxlabs dot ai" become maya@parallaxlabs.ai. The summary is 1-2 sentences.

TRANSCRIPT:
{transcript}"""

MOCK_EXTRACT = _ExtractOut(
    summary="Met Maya Lindqvist (ML engineer, Parallax Labs). Deep-dived speculative decoding and CUDA graph capture; she offered a referral for their inference engineer role.",
    person=_PersonOut(name="Maya Lindqvist", role="ML Engineer", role_class="engineer", email="maya@parallaxlabs.ai"),
    company=_CompanyOut(name="Parallax Labs", domain="parallaxlabs.ai"),
    topics=["speculative decoding", "gpu inference", "cuda"],
    promises=[
        _PromiseOut(by="them", text="Send the speculative decoding blog post"),
        _PromiseOut(by="me", text="Send my CUDA benchmark repo"),
    ],
)


def extract(session_id: str, transcript: str, started_at: str | None = None) -> SessionExtract:
    if settings.MOCK_MODE:
        out = MOCK_EXTRACT
    else:
        out = llm.parse(PROMPT.format(user=settings.USER_NAME, event=settings.EVENT_NAME, transcript=transcript), _ExtractOut)
    return SessionExtract(
        session_id=session_id,
        started_at=started_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        transcript=transcript,
        summary=out.summary,
        person=Person(**out.person.model_dump()),
        company=Company(**out.company.model_dump()) if out.company else None,
        topics=[t.strip().lower() for t in out.topics if t.strip()],
        promises=[Promise(**p.model_dump()) for p in out.promises],
    )
