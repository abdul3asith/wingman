"""Draft generation. OWNER: Person A.
Each draft opens with the Common Ground hook (topic + source link) and is role-aware via rules.pick()."""
import re

from pydantic import BaseModel

from app import llm
from app.asks import rules
from app.config import settings
from app.contract import CommonGround, Draft
from app.graph import queries, writes


class _DraftOut(BaseModel):
    subject: str
    body: str


PROMPT = """Write a short, warm follow-up email (under 150 words) from {user} to {person} ({role} at {company}),
whom they met at {event}. Ask type: {ask_type}.

Open with the common-ground hook: they discussed "{topic}" and {company} published "{doc_title}" ({doc_url}) —
reference it naturally with the link. Then make the ask:
- referral: ask for a referral to the "{job}" role, link resume {attachment}
- intro_chat: suggest a 20-min chat to continue the conversation
- resume: attach resume {attachment} for the relevant role
- collab: propose a concrete collaboration/pilot and link the deck {attachment}
- deck: share the deck {attachment} and ask for a 20-min call
- feedback_call: ask for 20 minutes of product feedback
- thank_you: just say thanks and keep the door open
Close any promises: {promises}. Sign off as {user}. No placeholders, no markdown."""


HOOK_KIND_RANK = {"blog": 0, "news": 1, "repo": 2, "site": 3, "job": 4}


def _first(name: str) -> str:
    return name.split()[0]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def generate(person_filter: str | None = None, uid: str = settings.USER_ID) -> list[Draft]:
    people = queries.people(uid)
    cg_all = queries.common_ground(uid)
    radar = queries.referral_radar(uid)
    promises = queries.open_promises(uid)
    drafts: list[Draft] = []
    for p in people:
        if person_filter and p["name"] != person_filter:
            continue
        # Prefer substantive content for the hook; a job page or homepage is a weak opener.
        cg = sorted((c for c in cg_all if c.person == p["name"]), key=lambda c: HOOK_KIND_RANK.get(c.doc_kind, 9))
        jobs = [r for r in radar if r["person"] == p["name"]]
        proms = [pr for pr in promises if pr["person"] == p["name"]]
        drafts.append(_build(p, cg[0] if cg else None, jobs[0] if jobs else None, proms))
    for d in drafts:
        writes.write_draft(d)
    return drafts


def _build(p: dict, hook: CommonGround | None, job: dict | None, proms: list[dict]) -> Draft:
    ask_type, attachment = rules.pick(p["role_class"], job is not None)
    company = p["company"] or "your company"
    topic = hook.topic if hook else (p["topics"][0] if p["topics"] else "our conversation")
    promise_lines = [
        (f"As promised, I'll {pr['text'][0].lower() + pr['text'][1:]}." if pr["by"] == "me" else f"I'd love to take you up on: {pr['text'].lower()}.")
        for pr in proms
    ]
    if settings.MOCK_MODE:
        subject, body = _template(p, hook, job, ask_type, attachment, company, topic, promise_lines)
    else:
        out = llm.parse(
            PROMPT.format(
                user=settings.USER_NAME, person=p["name"], role=p["role"] or p["role_class"], company=company,
                event=settings.EVENT_NAME, ask_type=ask_type, topic=topic,
                doc_title=hook.doc_title if hook else "(no common-ground doc found — skip the hook)",
                doc_url=hook.doc_url if hook else "", job=job["job_title"] if job else "",
                attachment=attachment or "", promises="; ".join(promise_lines) or "none",
            ),
            _DraftOut,
            system="You write concise, specific, human follow-up emails. Never invent facts beyond the prompt.",
        )
        subject, body = out.subject, out.body
    because: list[str] = []
    if hook:
        because += [hook.doc_url, hook.topic]
    if job:
        because.append(job["job_title"])
    because += [pr["text"] for pr in proms]
    return Draft(id=f"d_{_slug(p['name'])}", person=p["name"], email=p["email"], ask_type=ask_type, subject=subject, body=body, because=because)


def _template(p, hook, job, ask_type, attachment, company, topic, promise_lines) -> tuple[str, str]:
    first, me, event = _first(p["name"]), settings.USER_NAME, settings.EVENT_NAME
    opener = (
        f"Great meeting you at {event}. After we talked about {topic}, I read \"{hook.doc_title}\" that {company} published "
        f"({hook.doc_url}) — really sharp, and it lines up with a lot of what we discussed."
        if hook else f"Great meeting you at {event} — I really enjoyed our conversation about {topic}."
    )
    asks = {
        "referral": (
            f"Quick ask re: {job['job_title'] if job else 'roles'} at {company}",
            f"I noticed {company} is hiring for the {job['job_title'] if job else 'open'} role"
            + (f" ({', '.join(job['matched_skills'])} are exactly my background)" if job and job.get("matched_skills") else "")
            + f". Would you be open to referring me? Resume: {attachment}",
        ),
        "intro_chat": (f"Continuing our {topic} conversation", "Would you be up for a 20-minute call in the next couple of weeks to keep the thread going?"),
        "resume": (f"{me} — following up from {event}", f"Attaching my resume for the roles we discussed: {attachment}. Happy to talk through fit whenever is convenient."),
        "collab": (f"Idea for {company} from {event}", f"I think there's a concrete way we could work together on {topic}. Deck here: {attachment} — would love 20 minutes to walk you through it."),
        "deck": (f"{me} — deck as promised", f"Here's the deck: {attachment}. If it resonates, I'd love 20 minutes to get your read on it."),
        "feedback_call": (f"20 minutes of your feedback?", f"Would you be open to a short call? I'd value your product perspective on what I'm building around {topic}."),
        "thank_you": (f"Thanks for the chat at {event}", "No ask here — just wanted to say thanks and keep in touch."),
    }
    subject, ask = asks.get(ask_type, asks["thank_you"])
    parts = [f"Hi {first},", "", opener, "", ask]
    if promise_lines:
        parts += ["", " ".join(promise_lines)]
    parts += ["", f"Best,\n{me}"]
    return subject, "\n".join(parts)
