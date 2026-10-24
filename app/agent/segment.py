"""Group the people we met by the user's conference intents. OWNER: Person A.
One LLM call assigns each person to at most one intent + the ask that serves it; MOCK_MODE uses keyword rules."""
from typing import Literal

from pydantic import BaseModel

from app import llm
from app.agent import store
from app.config import settings
from app.ingest import graph_bridge as graph

AskType = Literal["referral", "technical_followup", "resume", "coffee_partnership", "update", "feedback_collab", "thank_you"]


class _Assign(BaseModel):
    person: str
    intent: str | None
    reason: str
    ask_type: AskType


class _Out(BaseModel):
    assignments: list[_Assign]


PROMPT = """{user} went to {event} with these goals:
{intents}

People they met (name | role | role_class | company | topics | summary):
{people}

Assign each person to the ONE goal they can clearly help with (copy the goal text exactly), or null if the fit is
weak. Be strict: a product lead at a healthcare company does not help an inference job search; a recruiter or
engineer at a company hiring for the user's skills ({skills}) does.
reason: one short clause a human would say ("staff engineer at a company hiring for CUDA").
ask_type: the follow-up that serves that goal — referral (engineer at a company that's hiring), resume (recruiter),
update (investor), coffee_partnership (founder), feedback_collab (product/design), technical_followup (engineer, no
hiring signal), thank_you (no goal fits)."""

_KEYWORDS = {
    "job": {"engineer": "referral", "recruiter": "resume"},
    "hire": {"engineer": "referral", "recruiter": "resume"},
    "role": {"engineer": "referral", "recruiter": "resume"},
    "career": {"engineer": "referral", "recruiter": "resume"},
    "invest": {"investor": "update", "founder": "coffee_partnership"},
    "fund": {"investor": "update", "founder": "coffee_partnership"},
    "raise": {"investor": "update"},
    "partner": {"founder": "coffee_partnership", "pm_design": "feedback_collab"},
    "customer": {"founder": "coffee_partnership", "pm_design": "feedback_collab"},
    "feedback": {"pm_design": "feedback_collab", "founder": "coffee_partnership"},
    "learn": {"engineer": "technical_followup"},
}


def run(uid: str = settings.USER_ID) -> dict:
    intents = store.get_intents(uid)
    if not intents:
        return {"error": "no goals saved yet — tell me what you want out of the conference first", "groups": []}
    people = graph.people(uid)
    assignments = _mock(intents, people) if settings.MOCK_MODE else _llm(intents, people)
    valid = set(intents)
    for a in assignments:
        if a["intent"] not in valid:
            a["intent"] = None
    store.save_segments(assignments)
    groups = store.segments(uid)
    unassigned = [a["person"] for a in assignments if not a["intent"]]
    return {"groups": groups, "unassigned": unassigned}


def _llm(intents: list[str], people: list[dict]) -> list[dict]:
    lines = "\n".join(
        f"- {p['name']} | {p.get('role') or '?'} | {p['role_class']} | {p.get('company') or '?'} | {', '.join(p.get('topics') or [])}"
        for p in people
    )
    out = llm.parse(
        PROMPT.format(user=settings.USER_NAME, event=settings.EVENT_NAME, intents="\n".join(f"- {i}" for i in intents),
                      people=lines, skills=", ".join(settings.USER_SKILLS)),
        _Out,
    )
    names = {p["name"] for p in people}
    return [a.model_dump() for a in out.assignments if a.person in names]


def _mock(intents: list[str], people: list[dict]) -> list[dict]:
    out = []
    for p in people:
        best = None
        for intent in intents:
            low = intent.lower()
            for kw, roles in _KEYWORDS.items():
                if kw in low and p["role_class"] in roles:
                    best = (intent, roles[p["role_class"]])
                    break
            if best:
                break
        out.append({
            "person": p["name"], "intent": best[0] if best else None,
            "reason": f"{p.get('role') or p['role_class']} at {p.get('company') or 'unknown'}",
            "ask_type": best[1] if best else "thank_you",
        })
    return out
