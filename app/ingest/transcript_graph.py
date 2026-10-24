"""Speaker-labeled transcript -> graph. OWNER: Person A.

convert(): one conversation -> our extraction (person, persona, promises, facts…) -> Session/Person/Company/Topic/
Promise via graph_bridge, plus LinkedIn handle and persona.

build_recording(): one recording -> conversations (teammate's splitter in app.memory.segment) -> convert() each ->
event memory via the teammate's writer (app.graph.memory): Recording-[:CONTAINS]->Session-[:LEARNED]->Fact and
Session/Person-[:ADVANCES]->Goal. The goal link comes from the founder persona (investor, accelerator, founder and
candidate all advance the founder's goal). The route saves the raw transcript first, so a failure never loses it.
"""
from datetime import datetime, timezone

from app import llm
from app.agent import store
from app.config import settings
from app.contract import SessionExtract
from app.graph import memory as graph_memory
from app.ingest import extract as extract_mod
from app.ingest import graph_bridge
from app.ingest.turns import Turn, to_text
from app.memory.build import cosine
from app.memory.segment import identify_me, split_conversations

# How strongly each persona advances the founder goal (ADVANCES.relevance); "other" gets no link.
PERSONA_RELEVANCE = {"investor": 0.9, "accelerator": 0.9, "candidate": 0.8, "founder": 0.7}


def convert(session_id: str, transcript: str) -> tuple[str, SessionExtract | None]:
    """Return (graph_status, extract). Status: "built", "no_person" (nobody identifiable), or "failed: …"."""
    try:
        x = extract_mod.extract(session_id, transcript)
    except extract_mod.NoPersonFound:
        return "no_person", None
    except Exception as e:  # extraction is an LLM call; keep the transcript even if it fails
        return f"failed: {str(e)[:120]}", None
    graph_bridge.ingest_session(x)
    if linkedin := extract_mod.LINKEDIN.pop(session_id, None):
        store.set_linkedin(x.person.name, linkedin)
    if persona := extract_mod.PERSONA.pop(session_id, None):
        store.set_persona(x.person.name, persona)
    return "built", x


def build(session_id: str, transcript: str) -> str:
    """Graph status only (kept for callers that don't need the extract)."""
    return convert(session_id, transcript)[0]


def build_recording(rid: str, turns: list[Turn]) -> list[dict]:
    """Split a recording into conversations and build each into the graph. Returns one dict per conversation:
    {session_id, start, end, graph_status, extract, category, context, facts, advances_goal}."""
    if not turns:
        return []
    timed = all(t.start is not None for t in turns)
    # Untimed turns (pasted text, OpenAI fallback) can't be split reliably: treat them as one conversation.
    convs = split_conversations(turns, identify_me(turns)) if timed and len({t.speaker for t in turns}) > 1 else None
    pieces = [(c.turns, c.start, c.end) for c in convs] if convs else [(turns, turns[0].start, turns[-1].end)]

    uid = settings.USER_ID
    goal_vec = llm.embed(settings.USER_GOAL)
    graph_memory.write_goal(uid, settings.USER_GOAL, goal_vec)
    graph_memory.write_recording(uid, rid, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 (turns[-1].end - turns[0].start) if timed else None, len(pieces))
    out = []
    for i, (conv_turns, start, end) in enumerate(pieces, 1):
        sid = rid if len(pieces) == 1 else f"{rid}-c{i}"
        status, x = convert(sid, to_text(conv_turns))
        mem = extract_mod.MEMORY.pop(sid, {"category": "other", "context": "", "facts": []})
        linked = False
        if x:
            linked = _write_memory(uid, rid, sid, x, mem, start, end, goal_vec)
        out.append({"session_id": sid, "start": start, "end": end, "graph_status": status,
                    "extract": x.model_dump() if x else None, "category": mem["category"], "context": mem["context"],
                    "facts": mem["facts"], "advances_goal": linked, "transcript": to_text(conv_turns)})
    return out


def _write_memory(uid: str, rid: str, sid: str, x: SessionExtract, mem: dict, start, end, goal_vec) -> bool:
    profile = f"{x.person.role or ''} at {x.company.name if x.company else ''}. {mem['context']} Topics: {', '.join(x.topics)}"
    vecs = llm.embed_many([profile] + [f["text"] for f in mem["facts"]])
    facts = [{"id": f"{sid}-f{i}", "kind": f["kind"], "text": f["text"], "embedding": v}
             for i, (f, v) in enumerate(zip(mem["facts"], vecs[1:]), 1)]
    persona = store.personas().get(x.person.name, "other")
    rel = PERSONA_RELEVANCE.get(persona)
    link = {"similarity": round(cosine(vecs[0], goal_vec), 3), "relevance": rel,
            "reason": f"{persona}: {store.PERSONA_INTENTS.get(persona, '')}"} if rel else None
    graph_memory.write_conversation(uid, rid, x, category=mem["category"], context=mem["context"], start=start,
                                    end=end, embedding=vecs[0], facts=facts, link=link)
    return link is not None
