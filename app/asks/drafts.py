"""Draft generation. OWNER: Person A.
Each draft opens with the Common Ground hook (topic + doc title + source link) and is role-aware via rules.pick().
LLM drafts are checked against the rules below; one retry, then the template, so a bad draft never reaches the queue."""
import re

from pydantic import BaseModel

from app import llm
from app.asks import rules
from app.config import settings
from app.contract import CommonGround, Draft
from app.ingest import graph_bridge as graph

MAX_WORDS = 120
HOOK_KIND_RANK = {"blog": 0, "news": 1, "repo": 2, "site": 3, "job": 4}
BANNED = ("hope this finds you well", "hope you're doing well", "hope you are doing well", "i hope this email")


class _DraftOut(BaseModel):
    subject: str
    body: str
    because: list[str]


SYSTEM = "You write short, specific, human follow-up emails. Use only facts given in the prompt. Never invent links."

PROMPT = """Write a plain-text follow-up email from {user} to {person} ({role} at {company}). They met at {event}.

{user} is the founder of {startup}, {pitch} ({stage}; hiring {hiring}).

ASK TYPE: {ask_type}
{ask_instruction}
{user}'S GOAL WITH THIS PERSON: {intent}
WHY NOW (if present, reference it in the second sentence with its URL): {fresh}
THEIR PORTFOLIO (investors/accelerators: if present, name this company in one clause to show you did your homework): {portfolio}

HARD RULES
- Under {max_words} words including greeting and sign-off. Exactly one clear ask.
- The FIRST sentence after the greeting must {hook_rule}
- {fulfilment_rule}
- No flattery filler, no "I hope this finds you well", no markdown, no placeholders like [link].
- Greeting "Hi {first}," and sign off with "{user}".
- because: list exactly the reference strings you used, copied from REFS.

REFS (the only things you may cite)
{refs}"""

ASK_INSTRUCTIONS = {
    "referral": 'Ask for a referral to the "{job_title}" role ({job_url}). Mention the matching skills: {matched}. Link the resume: {attachment}',
    "technical_followup": "Propose a 20-minute call to keep going on the technical thread. No attachment.",
    "resume": "Share the resume ({attachment}) for roles that fit and ask what the next step is.",
    "coffee_partnership": "Propose coffee to explore a concrete partnership. Link the deck: {attachment}",
    "update": "Share the deck ({attachment}), offer to send short progress updates, and ask for a 20-minute call.",
    "feedback_collab": "Ask for 20 minutes of product feedback on what you're building. Link the demo: {attachment}",
    "thank_you": "Just say thanks and keep the door open. No ask beyond staying in touch.",
    # founder persona
    "pitch": "Investor: one line on {startup} and traction, link the deck ({attachment}), ask for a 30-minute meeting about the round.",
    "accelerator": "Accelerator partner: say you're applying, link the deck ({attachment}), ask for 15 minutes of office hours before the deadline.",
    "founder_coffee": "Fellow founder: propose coffee to swap notes and look for a concrete way to help each other (intro, integration, shared customers).",
    "recruit": "Potential hire: say what {startup} is building, that you're hiring {hiring}, and ask for a no-pressure 20-minute chat.",
}


def _first(name: str) -> str:
    return name.split()[0]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def words(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------- orchestration


def generate(person_filter: str | None = None, uid: str = settings.USER_ID, names: list[str] | None = None) -> list[Draft]:
    """One draft per person met (or per `person_filter` / `names`). Intent segmentation, when it has run,
    decides the ask; Bright Data intel (recent post / this week's news) supplies the 'why now' line."""
    from app.agent import store  # local import: agent layer sits on top of asks

    people = graph.people(uid)
    cg_all = graph.common_ground(uid)
    radar = graph.referral_radar(uid)
    promises = graph.open_promises(uid)
    overrides = store.ask_overrides()
    personas = store.personas()
    wanted = set(names or []) | ({person_filter} if person_filter else set())
    drafts: list[Draft] = []
    for p in people:
        if wanted and p["name"] not in wanted:
            continue
        # Prefer substantive content for the hook; a job page or homepage is a weak opener.
        cg = sorted((c for c in cg_all if c.person == p["name"]), key=lambda c: HOOK_KIND_RANK.get(c.doc_kind, 9))
        jobs = [r for r in radar if r["person"] == p["name"]]
        # Same promise can come from several sessions with one person; fulfil it once.
        mine = list({pr["text"].lower(): pr for pr in promises if pr["person"] == p["name"] and pr["by"] == "me"}.values())
        intel = store.person_intel(p["name"])
        fresh = (intel["posts"] or [None])[0] or _news_as_fresh((intel["news"] or [None])[0])
        persona = personas.get(p["name"])
        override = overrides.get(p["name"]) or (
            {"ask_type": store.PERSONA_ASK[persona], "intent": store.PERSONA_INTENTS[persona]} if persona in store.PERSONA_ASK else None)
        portfolio = _portfolio_line(p.get("company")) if persona in ("investor", "accelerator") else ""
        d = build(p, cg[0] if cg else None, jobs[0] if jobs else None, mine, override, fresh, portfolio)
        graph.write_draft(d, uid)
        if fresh and fresh.get("node") == "Post":
            store.run("MATCH (d:Draft {id:$id}) MATCH (x:Post {url:$u}) MERGE (d)-[:BECAUSE]->(x)", {"id": d.id, "u": fresh["url"]})
        drafts.append(d)
    return drafts


def _portfolio_line(company: str | None) -> str:
    """'Foundry Lane backs Driftwood AI (Pre-Seed)' — prefer a portfolio company where we met someone."""
    from app.agent import store

    if not company:
        return ""
    pf = store.company_intel(company).get("portfolio") or []
    pf.sort(key=lambda x: -len(x.get("people_you_met") or []))
    if not pf:
        return ""
    top = pf[0]
    met = f", where you also met {top['people_you_met'][0]}" if top.get("people_you_met") else ""
    return f"{company} backs {top['name']}" + (f" ({top['round']})" if top.get("round") else "") + met


def _news_as_fresh(n: dict | None) -> dict | None:
    return {"url": n["url"], "text": n["title"], "node": "News", "label": "the news this week"} if n else None


def _short(text: str, n: int = 14) -> str:
    first = re.split(r"(?<=[.!?])\s", text.strip())[0]
    w = first.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def build(p: dict, hook: CommonGround | None, job: dict | None, my_promises: list[dict],
          override: dict | None = None, fresh: dict | None = None, portfolio: str = "") -> Draft:
    if override and override.get("ask_type"):
        ask_type = override["ask_type"]
        if ask_type == "referral" and not job:
            ask_type = "technical_followup"  # never ask for a referral without a real open role
        attachment = rules.attachment_for(ask_type)
    else:
        ask_type, attachment = rules.pick(p["role_class"], job is not None)
    if fresh and "node" not in fresh:
        fresh = {**fresh, "node": "Post", "label": "your post this week"}
    if not hook and fresh:
        # No Common Ground doc: their own recent post/news becomes the opening hook.
        hook = CommonGround(person=p["name"], company=p.get("company") or "", topic=_short(fresh["text"], 8),
                            doc_title=_short(fresh["text"]), doc_url=fresh["url"], doc_kind=fresh["label"])
        fresh = None
    ctx = {
        "startup": settings.STARTUP_NAME, "pitch": settings.STARTUP_PITCH, "stage": settings.STARTUP_STAGE,
        "hiring": settings.HIRING_FOR, "portfolio": portfolio,
        "intent": (override or {}).get("intent") or "",
        "fresh": f'{fresh["label"]}: "{_short(fresh["text"])}" ({fresh["url"]})' if fresh else "",
        "fresh_url": fresh["url"] if fresh else "",
        "user": settings.USER_NAME, "event": settings.EVENT_NAME, "person": p["name"], "first": _first(p["name"]),
        "role": p.get("role") or p["role_class"], "company": p.get("company") or "your company",
        "topic": (hook.topic if hook and hook.doc_kind in HOOK_KIND_RANK
                  else (p["topics"][0] if p.get("topics") else "our conversation")),
        "post_hook": bool(hook and hook.doc_kind not in HOOK_KIND_RANK),
        "ask_type": ask_type, "attachment": attachment or "",
        "job_title": job["job_title"] if job else "", "job_url": job["job_url"] if job else "",
        "matched": ", ".join(job["matched"]) if job else "",
        "fulfil": [rules.fulfilment_line(pr["text"]) for pr in my_promises],
        "promise_texts": [pr["text"] for pr in my_promises],
    }
    refs = _refs(hook, job, my_promises, p) + ([fresh["url"]] if fresh else [])
    subject = body = None
    because: list[str] = []
    if not settings.MOCK_MODE:
        subject, body, because = _llm_draft(ctx, hook, refs)
    if body is None:
        subject, body = _template(ctx, hook, job)
        because = _template_because(hook, job, my_promises) + ([fresh["url"]] if fresh else [])
    return Draft(id=f"d_{_slug(p['name'])}", person=p["name"], email=p.get("email"), ask_type=ask_type,
                 subject=subject, body=body, because=because)


def _refs(hook, job, my_promises, p) -> list[str]:
    refs = []
    if hook:
        refs += [hook.topic, hook.doc_url]
    refs += [t for t in p.get("topics", []) if t not in refs]
    if job:
        refs.append(job["job_title"])
    refs += [pr["text"] for pr in my_promises]
    return refs


# ---------------------------------------------------------------- LLM path


def problems(body: str, hook: CommonGround | None, fulfil: list[str], topic: str | None = None) -> list[str]:
    """Rule check shared by the LLM path and tests. Empty list = draft is OK."""
    issues = []
    if words(body) > MAX_WORDS:
        issues.append(f"too long ({words(body)} words, max {MAX_WORDS})")
    low = body.lower()
    if any(b in low for b in BANNED):
        issues.append("contains filler like 'hope this finds you well'")
    if "[" in body and "]" in body:
        issues.append("contains a placeholder in brackets")
    opening = " ".join(body.split("\n", 2)[1:])[:400] if body.lower().startswith("hi ") else body[:400]
    if hook and hook.doc_url not in opening:
        issues.append(f"first sentence must cite {hook.doc_url}")
    if hook and topic and topic.lower() not in opening.lower():
        issues.append(f'first sentence must mention the topic "{topic}"')
    for line in fulfil:
        url = re.search(r"https?://\S+", line)
        if url and url.group(0).rstrip(".") not in body:
            issues.append(f"missing promised link {url.group(0)}")
    return issues


def _llm_draft(ctx: dict, hook: CommonGround | None, refs: list[str]) -> tuple[str | None, str | None, list[str]]:
    prompt = PROMPT.format(
        **ctx, max_words=MAX_WORDS,
        ask_instruction=ASK_INSTRUCTIONS.get(ctx["ask_type"], ASK_INSTRUCTIONS["thank_you"]).format(**ctx),
        hook_rule=(
            f'reference {hook.doc_kind} "{hook.doc_title}" with its URL {hook.doc_url}.' if ctx["post_hook"]
            else f'mention the topic "{ctx["topic"]}" AND the {ctx["company"]} {hook.doc_kind} "{hook.doc_title}" with its URL {hook.doc_url}.' if hook
            else f'mention the topic "{ctx["topic"]}".'
        ),
        fulfilment_rule=("Include these promise fulfilment lines (keep the links): " + " | ".join(ctx["fulfil"])) if ctx["fulfil"] else "No promises to fulfil.",
        refs="\n".join(f"- {r}" for r in refs) or "- (none)",
    )
    for attempt in range(2):
        try:
            out = llm.parse(prompt, _DraftOut, system=SYSTEM)
        except Exception as e:
            print(f"[drafts] LLM failed for {ctx['person']}: {e}; using template")
            return None, None, []
        issues = problems(out.body, hook, ctx["fulfil"], None if ctx["post_hook"] else ctx["topic"])
        if not issues:
            # Things the rules force into the body are always evidence; the model may add other refs it used.
            forced = ([hook.topic, hook.doc_url] if hook else []) + ([ctx["job_title"]] if ctx["ask_type"] == "referral" else [])
            forced += ctx["promise_texts"] + ([ctx["fresh_url"]] if ctx["fresh_url"] and ctx["fresh_url"] in out.body else [])
            because = list(dict.fromkeys([*forced, *(b for b in out.because if b in refs)]))
            return out.subject, out.body.strip(), because
        print(f"[drafts] {ctx['person']} attempt {attempt + 1} rejected: {issues}")
        prompt += "\n\nYour previous draft broke these rules, fix them: " + "; ".join(issues)
    return None, None, []


# ---------------------------------------------------------------- template path (MOCK_MODE and fallback)


def _template(ctx: dict, hook: CommonGround | None, job: dict | None) -> tuple[str, str]:
    c, topic, att = ctx["company"], ctx["topic"], ctx["attachment"]
    if ctx["post_hook"]:
        opener = f'Saw {hook.doc_kind} ("{hook.doc_title}", {hook.doc_url}) and it picked up right where our chat at {ctx["event"]} left off.'
    elif hook:
        opener = f'After our chat about {topic} at {ctx["event"]}, I read "{hook.doc_title}" from {c} ({hook.doc_url}).'
    else:
        opener = f'Great talking {topic} with you at {ctx["event"]}.'
    if ctx["fresh"]:
        opener += f" Also saw {ctx['fresh']}."
    asks = {
        "referral": (
            f"Referral for {ctx['job_title']} at {c}?",
            f"I saw {c} is hiring for {ctx['job_title']} ({ctx['job_url']}), and my {ctx['matched']} background lines up closely. "
            f"Would you be open to referring me? Resume: {att}",
        ),
        "technical_followup": (f"More on {topic}", "Would you be up for a 20-minute call next week to keep comparing notes?"),
        "resume": (f"{ctx['user']}: resume from {ctx['event']}", f"Here's my resume as discussed: {att}. What's the best next step?"),
        "coffee_partnership": (f"Coffee + a partnership idea for {c}?", f"I think there's a concrete partnership angle around {topic}. Deck: {att}. Coffee this week or next?"),
        "update": (f"{ctx['user']}: deck + updates", f"Here's the deck: {att}. Happy to send short progress updates; open to a 20-minute call?"),
        "feedback_collab": (f"Your take on {topic}?", f"I'd value your product read on what I'm building. Quick demo: {att}. Open to a 20-minute feedback session?"),
        "thank_you": (f"Thanks for the chat at {ctx['event']}", "Thanks again for the conversation; let's stay in touch."),
        # founder persona
        "pitch": (f"{ctx['startup']}: {ctx['stage']}",
                  (f"I saw {ctx['portfolio']}. " if ctx["portfolio"] else "")
                  + f"We're building {ctx['startup']}, {ctx['pitch']}, and {ctx['stage']}. Deck: {att}. Open to 30 minutes next week?"),
        "accelerator": (f"{ctx['startup']} applying to {c}",
                        (f"I saw {ctx['portfolio']}. " if ctx["portfolio"] else "")
                        + f"We're applying with {ctx['startup']}, {ctx['pitch']}. Deck: {att}. Could I grab 15 minutes of office hours before the deadline?"),
        "founder_coffee": (f"Founder coffee: {ctx['startup']} x {c}",
                           f"I'm building {ctx['startup']}, {ctx['pitch']}. Coffee next week to swap notes and see where we can help each other?"),
        "recruit": (f"Building {ctx['startup']}: coffee?",
                    f"We're building {ctx['startup']}, {ctx['pitch']}, and hiring {ctx['hiring']}. Up for a no-pressure 20-minute chat?"),
    }
    subject, ask = asks.get(ctx["ask_type"], asks["thank_you"])
    parts = [f"Hi {ctx['first']},", "", opener, "", ask]
    if ctx["fulfil"]:
        parts += ["", " ".join(ctx["fulfil"])]
    parts += ["", f"Best,\n{ctx['user']}"]
    return subject, "\n".join(parts)


def _template_because(hook, job, my_promises) -> list[str]:
    because = [hook.topic, hook.doc_url] if hook else []
    if job:
        because.append(job["job_title"])
    return because + [pr["text"] for pr in my_promises]
