"""The voice agent: one conversation, tools over the graph, Bright Data, drafts and email. OWNER: Person A.

talk(conversation_id, text) -> {reply, ui: [events]}. Each tool result also becomes a UI event so the page can
animate cards in while the agent speaks a short summary.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import llm
from app.agent import intel, segment, store
from app.asks import drafts as drafts_mod
from app.asks import send as send_mod
from app.config import settings
from app.ingest import graph_bridge as graph

TZ = ZoneInfo("America/Los_Angeles")
MAX_STEPS = 6
_conversations: dict[str, list[dict]] = {}

SYSTEM = """You are Wingman, a voice-first networking agent for {user} at {event}. You speak out loud, so:
- Reply in 1-3 short spoken sentences, max 45 words. Plain prose only: no markdown, no bullets, no numbered lists,
  never read URLs aloud. Mention at most 3 names; the cards show the rest.
- The screen shows rich cards for every tool result, so summarize ("Three people fit your job search, Priya looks strongest") instead of reading data out.

{user} is the founder of {startup}, {pitch} ({stage}, hiring {hiring}). At the conference they meet investors,
accelerator partners, fellow founders and potential hires. Their goals: {goals}.

What you can do (use tools, don't guess): list who they met, group people by goal, research people live on the web
with Bright Data (LinkedIn profile + posts, their company's page and updates, and for investors/accelerators their
portfolio from Crunchbase), find warm intros (an investor whose fund backs a company where {user} met someone), show
common ground, draft follow-ups, explain why a draft says what it says, and schedule or send emails.

Rules:
- Goals are fixed for this demo; if {user} restates them, acknowledge and carry on.
- Sending is irreversible. ALWAYS call schedule_followups with confirmed=false first, tell {user} who gets what and when,
  and only call it with confirmed=true after an explicit yes.
- Resolve times like "Monday 9am" to ISO 8601 with offset in America/Los_Angeles using this calendar
  (never compute dates yourself): now is {now}. Upcoming days: {calendar}.
- A preview (confirmed=false) has NOT sent anything: say "Ready to schedule…" and ask for a yes, never "I've scheduled".
- If {user} names a goal ("the investors", "my job search"), pass it as `goal`; if they name people, pass `names`.
- Never invent people, posts or emails. If a tool returns an error, say what's missing in one sentence."""

TOOLS = [
    {"type": "function", "function": {"name": "warm_intros", "description": "Warm-intro paths from the graph: investors/accelerators the user met whose fund backs a company where the user also met someone.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "who_did_i_meet", "description": "Everyone the user met, with role, company, topics.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "group_by_goals", "description": "Sort the people met into the user's goals, with the right ask for each.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "research_people", "description": "Live web research with Bright Data: LinkedIn profile + recent posts, company news this week.",
        "parameters": {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}, "goal": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "common_ground", "description": "Topics the user discussed that the person's company has published about, with sources.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "draft_followups", "description": "Draft follow-up emails (one per person) for names, a goal group, or everyone.",
        "parameters": {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}, "goal": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "explain_draft", "description": "Why a person's draft says what it says: the path through the graph.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "schedule_followups",
        "description": "Send or schedule pending drafts. confirmed=false returns a preview; confirmed=true actually sends. send_at null = now.",
        "parameters": {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}, "goal": {"type": "string"},
                       "send_at": {"type": ["string", "null"]}, "confirmed": {"type": "boolean"}}, "required": ["confirmed"]}}},
]


# ---------------------------------------------------------------- helpers


def _people() -> list[dict]:
    return graph.people(settings.USER_ID)


def _resolve(names: list[str] | None, goal: str | None) -> list[str]:
    everyone = [p["name"] for p in _people()]
    if names:
        out = []
        for n in names:  # tolerate first names / casing from speech
            hit = next((e for e in everyone if e.lower() == n.lower()), None) or next(
                (e for e in everyone if n.lower() in e.lower()), None)
            if hit:
                out.append(hit)
        return list(dict.fromkeys(out))
    if goal:
        groups = store.segments()
        g = goal.lower()
        best = max(groups, key=lambda gr: len(set(g.split()) & set(gr["intent"].lower().split())), default=None)
        if best and set(g.split()) & set(best["intent"].lower().split()):
            return [p["person"] for p in best["people"]]
        return []
    return everyone


def _draft_card(d) -> dict:
    return {"id": d.id, "person": d.person, "email": d.email, "ask_type": d.ask_type, "subject": d.subject,
            "body": d.body, "status": d.status, "because": d.because}


# ---------------------------------------------------------------- tools


def t_warm_intros() -> tuple[dict, dict]:
    paths = store.warm_paths()
    brief = [f"{w['investor']} ({w['fund']}) backs {w['company']}, where you met {w['person']}" for w in paths]
    return {"count": len(paths), "paths": brief[:8]}, {"type": "warm_paths", "paths": paths}


def t_who_did_i_meet() -> tuple[dict, dict]:
    ppl = _people()
    brief = [{"name": p["name"], "role": p.get("role"), "company": p.get("company"), "has_email": bool(p.get("email"))} for p in ppl]
    return {"count": len(ppl), "people": brief}, {"type": "people", "people": ppl}


def t_group_by_goals() -> tuple[dict, dict]:
    out = segment.run()
    if out.get("error"):
        return out, {"type": "error", "message": out["error"]}
    brief = {g["intent"]: [p["person"] for p in g["people"]] for g in out["groups"]}
    return {"groups": brief, "unassigned": out["unassigned"]}, {"type": "groups", **out}


def t_research_people(names: list[str] | None = None, goal: str | None = None) -> tuple[dict, dict]:
    who = _resolve(names, goal)[:8]
    if not who:
        return {"error": "nobody matched"}, {"type": "error", "message": "nobody matched"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(intel.research, who))
    brief = [{"name": r["person"], "persona": r.get("persona"), "posts": len(r.get("posts", [])),
              "latest_post": (r.get("posts") or [{}])[0].get("text", "")[:120],
              "company_about": ((r.get("company_profile") or {}).get("about") or "")[:160],
              "portfolio": [p["name"] for p in r.get("portfolio", [])][:6], "portfolio_status": r.get("portfolio_status")}
             for r in results]
    return {"researched": brief, "bright_data": intel.status()}, {"type": "intel", "results": results, "bright_data": intel.status()}


def t_common_ground(name: str | None = None) -> tuple[dict, dict]:
    who = _resolve([name], None)[0] if name and _resolve([name], None) else None
    rows = graph.common_ground(settings.USER_ID, who)
    brief = [{"person": r.person, "topic": r.topic, "doc": r.doc_title} for r in rows[:8]]
    return {"count": len(rows), "top": brief}, {"type": "common_ground", "rows": [r.model_dump() for r in rows]}


def t_draft_followups(names: list[str] | None = None, goal: str | None = None) -> tuple[dict, dict]:
    who = _resolve(names, goal)
    if not who:
        return {"error": "nobody matched — group by goals first or name people"}, {"type": "error", "message": "nobody matched"}
    ds = drafts_mod.generate(names=who)
    brief = [{"person": d.person, "ask": d.ask_type, "subject": d.subject, "has_email": bool(d.email)} for d in ds]
    return {"drafted": brief}, {"type": "drafts", "drafts": [_draft_card(d) for d in ds]}


def t_explain_draft(name: str) -> tuple[dict, dict]:
    from app.agent import why as why_mod  # full path: graph why_path + facts, post, portfolio, goal

    who = _resolve([name], None)
    if not who:
        return {"error": f"no one called {name}"}, {"type": "error", "message": f"no one called {name}"}
    d = next((x for x in graph.draft_queue(None) if x.person == who[0]), None)
    if not d:
        return {"error": f"no draft for {who[0]} yet"}, {"type": "error", "message": f"no draft for {who[0]} yet"}
    w = why_mod.why(d.id)
    intel_now = store.person_intel(who[0])
    return {"hops": w.get("hops", [])[:6]}, {"type": "why", "draft": _draft_card(d), "why": w, "intel": intel_now}


def t_schedule_followups(confirmed: bool, names: list[str] | None = None, goal: str | None = None,
                         send_at: str | None = None) -> tuple[dict, dict]:
    who = set(_resolve(names, goal))
    pending = [d for d in graph.draft_queue("pending") if d.person in who]
    if not pending:
        return {"error": "no pending drafts for those people — draft them first"}, {"type": "error", "message": "no pending drafts"}
    missing = [d.person for d in pending if not (d.email or settings.SEND_TEST_TO)]
    ready = [d for d in pending if d.person not in missing]
    plan = [{"person": d.person, "subject": d.subject, "to": settings.SEND_TEST_TO or d.email} for d in ready]
    if not confirmed:
        return ({"status": "NOT SENT YET - preview only", "preview": plan, "no_email": missing, "send_at": send_at or "now",
                 "next": "ask the user to confirm"},
                {"type": "schedule_preview", "plan": plan, "no_email": missing, "send_at": send_at})
    done = []
    for d in ready:
        send_mod.send(d, send_at)
        graph.set_draft_status(d.id, "sent")
        store.set_scheduled(d.id, send_at)
        done.append({"person": d.person, "subject": d.subject, "id": d.id})
    return ({"sent": len(done), "send_at": send_at or "now", "skipped_no_email": missing},
            {"type": "scheduled", "sent": done, "send_at": send_at, "no_email": missing})


DISPATCH = {
    "warm_intros": t_warm_intros, "who_did_i_meet": t_who_did_i_meet, "group_by_goals": t_group_by_goals,
    "research_people": t_research_people, "common_ground": t_common_ground, "draft_followups": t_draft_followups,
    "explain_draft": t_explain_draft, "schedule_followups": t_schedule_followups,
}


# ---------------------------------------------------------------- loop


def _window(msgs: list[dict], n: int = 24) -> list[dict]:
    """Last n messages, starting at a user turn so no tool reply is orphaned from its tool_calls."""
    w = msgs[-n:]
    while w and w[0]["role"] != "user":
        w = w[1:]
    return w


def _spoken(text: str) -> str:
    """Models still slip into markdown; strip it so the voice and the caption read naturally."""
    text = re.sub(r"\*\*|__|`|#+ ", "", text)
    text = re.sub(r"^\s*(?:[-*•]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"\(?https?://\S+\)?", "", text)
    return re.sub(r"\s*\n+\s*", " ", text).strip()


def talk(conversation_id: str, text: str) -> dict:
    msgs = _conversations.setdefault(conversation_id, [])
    now = datetime.now(TZ)
    calendar = ", ".join(f"{(now + timedelta(days=i)):%A %Y-%m-%d}" for i in range(1, 8))
    store.ensure_persona()
    system = SYSTEM.format(user=settings.USER_NAME, event=settings.EVENT_NAME,
                           now=f"{now:%A %Y-%m-%d %H:%M} ({now:%z})", calendar=calendar,
                           startup=settings.STARTUP_NAME, pitch=settings.STARTUP_PITCH, stage=settings.STARTUP_STAGE,
                           hiring=settings.HIRING_FOR, goals="; ".join(store.get_intents()))
    msgs.append({"role": "user", "content": text})
    ui: list[dict] = []
    for _ in range(MAX_STEPS):
        res = llm.client().chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL, messages=[{"role": "system", "content": system}, *_window(msgs)], tools=TOOLS,
        )
        m = res.choices[0].message
        if not m.tool_calls:
            reply = _spoken(m.content or "Done.")
            msgs.append({"role": "assistant", "content": reply})
            return {"reply": reply, "ui": ui}
        msgs.append({"role": "assistant", "content": m.content, "tool_calls": [tc.model_dump() for tc in m.tool_calls]})
        for tc in m.tool_calls:
            fn = DISPATCH.get(tc.function.name)
            try:
                args = json.loads(tc.function.arguments or "{}")
                result, event = fn(**args) if fn else ({"error": "unknown tool"}, None)
            except Exception as e:  # tool failures are spoken, not raised
                print(f"[agent] {tc.function.name} failed: {e}")
                result, event = {"error": str(e)[:200]}, {"type": "error", "message": str(e)[:200]}
            if event:
                ui.append({**event, "tool": tc.function.name})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)[:6000]})
    return {"reply": "I did what I could; take a look at the screen.", "ui": ui}


def _warm_seed_portfolios() -> None:
    """Seed investors/accelerators: load their cached portfolios once (instant, no network) so warm intros work after a reset."""
    for name, persona in store.personas().items():
        if persona in ("investor", "accelerator") and intel._is_seed(name):
            company = next((p.get("company") for p in _people() if p["name"] == name), None)
            if company and not store.company_intel(company).get("portfolio_status"):
                intel.research(name)


def state() -> dict:
    """Everything the page needs on load."""
    store.ensure_persona()
    _warm_seed_portfolios()
    return {"goals": store.get_intents(), "persona_goal": settings.PERSONA_GOAL, "startup": settings.STARTUP_NAME,
            "groups": store.segments(), "people": _people(), "bright_data": intel.status(),
            "pending": len(graph.draft_queue("pending")), "user": settings.USER_NAME, "event": settings.EVENT_NAME}
