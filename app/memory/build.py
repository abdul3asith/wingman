"""Recording turns -> event memory in FalkorDB.

segment (who is "me", where conversations start) -> one extraction per conversation -> one batched embedding
call (goal, conversation profiles, facts) -> graph writes. The full transcript never goes into the graph; each
conversation's text is returned to the caller for display only.
"""
import math
from datetime import datetime, timedelta, timezone

from app import llm
from app.config import settings
from app.contract import Company, Person, Promise, SessionExtract
from app.graph import memory as graph_memory
from app.ingest.turns import Turn, to_text
from app.memory.extract import ConversationExtract, LLMError, scrub_error, extract
from app.memory.segment import Conversation, identify_me, main_partner, split_conversations

GOAL_LINK_MIN = 0.5  # LLM goal relevance (0..1) at or above which a conversation gets an ADVANCES edge


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def goal_link(relevance: float) -> bool:
    return relevance >= GOAL_LINK_MIN


def profile_text(x: ConversationExtract) -> str:
    """What a conversation is 'about', as one string to embed and compare against the goal."""
    p = x.person
    who = " at ".join(v for v in (p.role, p.company) if v)
    parts = [f"Category: {x.category}.", x.context]
    if who:
        parts.append(f"Talked with: {who}.")
    if x.topics:
        parts.append(f"Topics: {', '.join(x.topics)}.")
    parts += [f.text for f in x.facts]
    return " ".join(parts)


def _person_name(x: ConversationExtract, conv: Conversation, me: int, rid: str) -> str:
    if x.person.name:
        return x.person.name
    partner = main_partner(conv, me)
    label = x.person.role or x.person.company or (f"Speaker {partner}" if partner is not None else "someone")
    return f"Unknown · {label} · {rid}-c{conv.seq}"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def build(rid: str, turns: list[Turn], uploaded_at: datetime | None = None) -> dict:
    """Segment, extract, embed and write one recording. Raises LLMError when extraction or embedding fails."""
    me = identify_me(turns)
    convs = split_conversations(turns, me)
    extracts = [extract(c, me) for c in convs]

    goal = settings.USER_GOAL
    profiles = [profile_text(x) for x in extracts]
    fact_texts = [f.text for x in extracts for f in x.facts]
    try:
        vecs = llm.embed_many([goal, *profiles, *fact_texts])
    except Exception as e:
        raise LLMError(f"embedding failed: {scrub_error(e)}") from e
    goal_vec, prof_vecs, fact_vecs = vecs[0], vecs[1:1 + len(profiles)], vecs[1 + len(profiles):]

    ends = [t.end for t in turns if t.end is not None]
    duration = round(max(ends), 2) if ends else None
    # The browser uploads right after Stop, so the recording started roughly `duration` before the upload.
    rec_start = (uploaded_at or datetime.now(timezone.utc)) - timedelta(seconds=duration or 0)

    uid = settings.USER_ID
    graph_memory.write_goal(uid, goal, goal_vec)
    graph_memory.write_recording(uid, rid, _iso(rec_start), duration, len(convs))

    out_convs, fi = [], 0
    for conv, x, pvec in zip(convs, extracts, prof_vecs):
        sid = f"{rid}-c{conv.seq}"
        relevance = round(x.goal_relevance.score, 3)
        similarity = round(cosine(pvec, goal_vec), 3)
        linked = goal_link(relevance)
        name = _person_name(x, conv, me, rid)
        facts = []
        for i, f in enumerate(x.facts):
            facts.append({"id": f"{sid}-f{i + 1}", "kind": f.kind, "text": f.text, "embedding": fact_vecs[fi]})
            fi += 1
        sx = SessionExtract(
            session_id=sid,
            started_at=_iso(rec_start + timedelta(seconds=conv.start or 0)),
            transcript="",  # transcripts stay in cache/transcripts/, never in the graph
            summary=x.context,
            person=Person(name=name, role=x.person.role, role_class=x.person.role_class, email=x.person.email),
            company=Company(name=x.person.company, domain=x.person.domain) if x.person.company else None,
            topics=x.topics,
            promises=[Promise(by=p.by, text=p.text) for p in x.promises],
        )
        graph_memory.write_conversation(
            uid, rid, sx, category=x.category, context=x.context, start=conv.start, end=conv.end,
            embedding=pvec, facts=facts,
            link={"similarity": similarity, "relevance": relevance, "reason": x.goal_relevance.reason} if linked else None,
        )
        out_convs.append({
            "id": sid,
            "seq": conv.seq,
            "start": conv.start,
            "end": conv.end,
            "partners": conv.partners,
            "person": {**x.person.model_dump(), "name": name},
            "category": x.category,
            "context": x.context,
            "topics": x.topics,
            "facts": [{"kind": f.kind, "text": f.text} for f in x.facts],
            "promises": [p.model_dump() for p in x.promises],
            "goal": {"relevance": relevance, "similarity": similarity, "reason": x.goal_relevance.reason, "linked": linked},
            "transcript": to_text(conv.turns, me=me),
        })
    return {"session_id": rid, "me_speaker": me, "goal": goal, "conversations": out_convs}
