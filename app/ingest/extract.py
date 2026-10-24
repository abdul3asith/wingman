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


PROMPT = """You are reading a transcript recorded by {user} at {event}. It is one of two kinds:

1. A speaker-labeled recording of a conversation ("Speaker 0: ...", "Speaker 1: ...") between {user} and
   someone else. {user} is the person holding the recorder and may never say their own name. Work in two steps.
   Step 1: decide which label is {user} (call it ME) and which is the other person (call it THEM), using
   introductions ("I'm ..."), who is asking about whom, and {user}'s background ({skills}). THEM is usually the
   one who states their company, hands over their email, or offers a referral or job; ME is usually the one asking
   about them and collecting the contact. Extract THEM as `person`; ME is never `person`.
   Step 2: for every promise, look at the label on the line where it was said. Label THEM -> by="them".
   Label ME -> by="me". Example: if Speaker 1 is ME and Speaker 0 is THEM, then "Speaker 0: I'll send you the
   blog post" gives by="them", and "Speaker 1: I'll send my repo" gives by="me".
   If more than two speakers appear, THEM is the person {user} talked with the most.
2. A solo voice debrief spoken by {user} about a conversation they just had. The speaker is {user} ("me");
   extract the person they describe; by="me" for what {user} promised, by="them" for what that person promised.

In both cases return exactly one person (the OTHER person, never {user}) with:
- role: a short normalized job title ("ML Engineer", "Head of Platform Engineering"). role_class is exactly one of
  engineer | recruiter | founder | investor | pm_design | other, from their actual job: an engineering leader is
  "engineer", not "recruiter", even if they offered a referral.
- company: the name as spoken, best-effort spelling (it is resolved against the web later). domain only if it was
  said or is unambiguous, else null.
- topics: 2-4 short lowercase noun phrases, no duplicates, specific over generic ("kv cache", "inference serving",
  not "ai" or "tech").
- promises: every promise either side made, each as a short imperative ("Send the cold starts blog post").
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
        prompt = PROMPT.format(
            user=settings.USER_NAME, event=settings.EVENT_NAME, skills=", ".join(settings.USER_SKILLS), transcript=transcript
        )
        out = llm.parse(prompt, _ExtractOut)
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
