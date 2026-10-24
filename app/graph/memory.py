"""Event-memory writes: Goal, Recording, per-conversation Session extras, Facts and ADVANCES links.

Session/Person/Company/Topic/Promise go through `writes.ingest_session` so recorded people show up in the
existing People, Common Ground and draft flows. Everything here MERGEs on ids, so re-running a recording
updates nodes instead of duplicating them. Transcripts never reach this module.
"""
from app.contract import SessionExtract
from app.graph import writes
from app.graph.db import run

GOAL_ID = "goal"


def write_goal(uid: str, text: str, embedding: list[float]) -> None:
    """MERGE the single Goal node; text and embedding follow USER_GOAL when it changes."""
    run(
        """
        MERGE (u:User {id:$uid})
        MERGE (g:Goal {id:$gid})
        SET g.text=$text, g.embedding=vecf32($vec)
        MERGE (u)-[:WANTS]->(g)
        """,
        {"uid": uid, "gid": GOAL_ID, "text": text, "vec": embedding},
    )


def write_recording(uid: str, rid: str, started_at: str, duration_s: float | None, conversations: int) -> None:
    run(
        """
        MERGE (u:User {id:$uid})
        MERGE (r:Recording {id:$rid})
        SET r.started_at=$started_at, r.duration_s=$duration_s, r.conversations=$n
        MERGE (u)-[:RECORDED]->(r)
        """,
        {"uid": uid, "rid": rid, "started_at": started_at, "duration_s": duration_s, "n": conversations},
    )


def write_conversation(
    uid: str,
    rid: str,
    sx: SessionExtract,
    *,
    category: str,
    context: str,
    start: float | None,
    end: float | None,
    embedding: list[float],
    facts: list[dict],
    link: dict | None,
) -> None:
    """Write one conversation. `facts` items are {id, kind, text, embedding}; `link` is
    {similarity, relevance, reason} when the conversation advances the goal, else None."""
    writes.ingest_session(uid, sx)
    sid = sx.session_id
    run(
        """
        MATCH (r:Recording {id:$rid})
        MATCH (s:Session {id:$sid})
        SET s.category=$category, s.context=$context, s.start=$start, s.end=$end, s.recording_id=$rid,
            s.embedding=vecf32($vec)
        MERGE (r)-[:CONTAINS]->(s)
        """,
        {"rid": rid, "sid": sid, "category": category, "context": context, "start": start, "end": end, "vec": embedding},
    )
    # Drop facts a previous run wrote for this session that this run no longer produced, then upsert in one query.
    run(
        "MATCH (s:Session {id:$sid})-[:LEARNED]->(f:Fact) WHERE NOT f.id IN $ids DETACH DELETE f",
        {"sid": sid, "ids": [f["id"] for f in facts]},
    )
    if facts:
        run(
            """
            MATCH (s:Session {id:$sid})
            UNWIND $facts AS f
            MERGE (x:Fact {id:f.id})
            SET x.kind=f.kind, x.text=f.text, x.session_id=$sid, x.embedding=vecf32(f.embedding)
            MERGE (s)-[:LEARNED]->(x)
            """,
            {"sid": sid, "facts": facts},
        )
    _write_links(sid, sx.person.name, link)


def _write_links(sid: str, person: str, link: dict | None) -> None:
    # Clear this session's links first so a re-run that scores below the threshold leaves no stale edge.
    run("MATCH (:Session {id:$sid})-[a:ADVANCES]->(:Goal) DELETE a", {"sid": sid})
    run("MATCH (:Person)-[a:ADVANCES {session_id:$sid}]->(:Goal) DELETE a", {"sid": sid})
    if link is None:
        return
    params = {"sid": sid, "gid": GOAL_ID, "pname": person, **link}
    run(
        """
        MATCH (s:Session {id:$sid}) MATCH (g:Goal {id:$gid})
        MERGE (s)-[a:ADVANCES]->(g)
        SET a.similarity=$similarity, a.relevance=$relevance, a.reason=$reason
        """,
        params,
    )
    # One Person->Goal edge per person, carrying the highest-relevance session seen so far.
    run(
        """
        MATCH (p:Person {name:$pname}) MATCH (g:Goal {id:$gid})
        MERGE (p)-[a:ADVANCES]->(g)
        WITH a WHERE a.relevance IS NULL OR $relevance >= a.relevance
        SET a.similarity=$similarity, a.relevance=$relevance, a.reason=$reason, a.session_id=$sid
        """,
        params,
    )
