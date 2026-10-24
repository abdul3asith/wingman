"""Group the people met by the founder persona's audiences. OWNER: Person A.

Demo persona: a startup founder. Everyone lands in one of three goals by who they are to a founder (persona set at
extraction): investors & accelerators -> raise, fellow founders -> partner, potential hires -> hire. Deterministic on
purpose: the extraction step already did the judgment, so grouping is instant and repeatable on stage.
"""
from app.agent import store
from app.config import settings
from app.ingest import graph_bridge as graph

# Older sessions (before persona extraction) fall back to role_class.
_ROLE_FALLBACK = {"investor": "investor", "founder": "founder", "engineer": "candidate", "pm_design": "candidate"}


def persona_of(p: dict, personas: dict[str, str]) -> str:
    return personas.get(p["name"]) or _ROLE_FALLBACK.get(p.get("role_class") or "", "other")


def run(uid: str = settings.USER_ID) -> dict:
    store.ensure_persona(uid)
    personas = store.personas()
    portfolio_by_fund = {w["fund"]: w for w in store.warm_paths(uid)}
    assignments = []
    for p in graph.people(uid):
        persona = persona_of(p, personas)
        where = f"{p.get('role') or p['role_class']} at {p.get('company') or 'unknown'}"
        reason = {
            "investor": f"{where}; can lead or join the round",
            "accelerator": f"{where}; accelerator program for {settings.STARTUP_NAME}",
            "founder": f"{where}; fellow founder: notes, intros, partnership",
            "candidate": f"{where}; could join as one of our {settings.HIRING_FOR}",
        }.get(persona, where)
        if p.get("company") in portfolio_by_fund:
            reason += f"; their fund backs {portfolio_by_fund[p['company']]['company']}, where you met {portfolio_by_fund[p['company']]['person']}"
        assignments.append({"person": p["name"], "intent": store.PERSONA_INTENTS.get(persona), "persona": persona,
                            "reason": reason, "ask_type": store.PERSONA_ASK.get(persona, "thank_you")})
    store.save_segments(assignments)
    return {"groups": store.segments(uid), "unassigned": [a["person"] for a in assignments if not a["intent"]],
            "warm_paths": store.warm_paths(uid)}
