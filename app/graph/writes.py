"""All graph mutations. Person A calls ingest_session() and write_draft(); everything else is internal."""
from datetime import datetime, timezone

from app import llm
from app.config import settings
from app.contract import Draft, EnrichResult, SessionExtract
from app.graph.db import run, scalar

TOPIC_MERGE_DISTANCE = 0.12  # cosine distance under which two topic strings are treated as the same node


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def ensure_user(uid: str = settings.USER_ID, name: str = settings.USER_NAME, skills: list[str] | None = None) -> None:
    run("MERGE (u:User {id:$uid}) SET u.name=$name", {"uid": uid, "name": name})
    for skill in skills if skills is not None else settings.USER_SKILLS:
        run(
            "MATCH (u:User {id:$uid}) MERGE (s:Skill {name:$skill}) MERGE (u)-[:HAS_SKILL]->(s)",
            {"uid": uid, "skill": norm(skill)},
        )


def merge_topic(name: str) -> str:
    """MERGE a Topic, reusing an existing node if its embedding is near-identical. Returns canonical name."""
    name = norm(name)
    if not name:
        return name
    existing = scalar("MATCH (t:Topic {name:$name}) RETURN t.name", {"name": name})
    if existing:
        return existing
    vec = llm.embed(name)
    try:
        # TODO(workshop): confirm `score` is a cosine *distance* (0 = identical) for this FalkorDB version.
        rows = run(
            "CALL db.idx.vector.queryNodes('Topic', 'embedding', 1, vecf32($vec)) "
            "YIELD node, score RETURN node.name AS name, score",
            {"vec": vec},
        )
        if rows and rows[0]["score"] is not None and rows[0]["score"] < TOPIC_MERGE_DISTANCE:
            return rows[0]["name"]
    except Exception:
        pass  # vector index missing or empty; fall through to plain MERGE
    run("MERGE (t:Topic {name:$name}) ON CREATE SET t.embedding = vecf32($vec)", {"name": name, "vec": vec})
    return name


def ingest_session(uid: str, x: SessionExtract) -> None:
    run(
        """
        MERGE (u:User {id:$uid})
        MERGE (s:Session {id:$sid})
        SET s.started_at=$started_at, s.summary=$summary, s.transcript=$transcript
        MERGE (u)-[:HAD]->(s)
        MERGE (p:Person {name:$pname})
        SET p.role=coalesce($role, p.role), p.role_class=$role_class, p.email=coalesce($email, p.email)
        MERGE (s)-[:WITH]->(p)
        """,
        {
            "uid": uid, "sid": x.session_id, "started_at": x.started_at, "summary": x.summary,
            "transcript": x.transcript, "pname": x.person.name, "role": x.person.role,
            "role_class": x.person.role_class, "email": x.person.email,
        },
    )
    if x.company:
        run(
            """
            MATCH (p:Person {name:$pname})
            MERGE (c:Company {name:$cname}) SET c.domain=coalesce($domain, c.domain)
            MERGE (p)-[:WORKS_AT]->(c)
            """,
            {"pname": x.person.name, "cname": x.company.name, "domain": x.company.domain},
        )
    for topic in x.topics:
        canonical = merge_topic(topic)
        if canonical:
            run(
                "MATCH (s:Session {id:$sid}) MATCH (t:Topic {name:$t}) MERGE (s)-[:DISCUSSED]->(t)",
                {"sid": x.session_id, "t": canonical},
            )
    for pr in x.promises:
        run(
            """
            MATCH (s:Session {id:$sid})
            MERGE (pr:Promise {text:$text, session_id:$sid}) ON CREATE SET pr.done=false
            MERGE (s)-[:PROMISED {by:$by}]->(pr)
            """,
            {"sid": x.session_id, "text": pr.text, "by": pr.by},
        )


def write_webdocs(r: EnrichResult) -> None:
    run(
        "MERGE (c:Company {name:$cname}) SET c.domain=coalesce($domain, c.domain), c.stage=coalesce($stage, c.stage)",
        {"cname": r.company, "domain": r.domain, "stage": r.stage},
    )
    if r.sector:
        run(
            "MATCH (c:Company {name:$cname}) MERGE (sec:Sector {name:$sector}) MERGE (c)-[:IN_SPACE]->(sec)",
            {"cname": r.company, "sector": r.sector},
        )
    now = _now()
    for d in r.webdocs:
        run(
            """
            MATCH (c:Company {name:$cname})
            MERGE (d:WebDoc {url:$url})
            SET d.title=$title, d.kind=$kind, d.published_at=$published_at, d.scraped_at=$now
            MERGE (c)-[:PUBLISHED]->(d)
            """,
            {"cname": r.company, "url": d.url, "title": d.title, "kind": d.kind, "published_at": d.published_at, "now": now},
        )
        for topic in d.topics:
            canonical = merge_topic(topic)
            if canonical:
                run(
                    "MATCH (d:WebDoc {url:$url}) MATCH (t:Topic {name:$t}) MERGE (d)-[:MENTIONS]->(t)",
                    {"url": d.url, "t": canonical},
                )
    for j in r.jobs:
        run(
            """
            MATCH (c:Company {name:$cname})
            MERGE (j:Job {url:$url}) SET j.title=$title, j.req_id=$req_id
            MERGE (c)-[:HIRING]->(j)
            """,
            {"cname": r.company, "url": j.url, "title": j.title, "req_id": j.req_id},
        )
        run("MATCH (j:Job {url:$url}) MATCH (d:WebDoc {url:$url}) MERGE (j)-[:SOURCED_FROM]->(d)", {"url": j.url})
        for skill in j.skills:
            run(
                "MATCH (j:Job {url:$url}) MERGE (s:Skill {name:$skill}) MERGE (j)-[:NEEDS]->(s)",
                {"url": j.url, "skill": norm(skill)},
            )


def write_draft(d: Draft) -> None:
    """Upsert a Draft and link it FOR the person and BECAUSE each evidence item (url / topic / job title / promise text)."""
    run(
        """
        MERGE (d:Draft {id:$id})
        SET d.ask_type=$ask_type, d.subject=$subject, d.body=$body, d.status=$status, d.created_at=coalesce(d.created_at, $now)
        WITH d MATCH (p:Person {name:$person}) MERGE (d)-[:FOR]->(p)
        """,
        {"id": d.id, "ask_type": d.ask_type, "subject": d.subject, "body": d.body, "status": d.status, "now": _now(), "person": d.person},
    )
    run("MATCH (d:Draft {id:$id})-[r:BECAUSE]->() DELETE r", {"id": d.id})
    for item in d.because:
        for label, prop in (("WebDoc", "url"), ("Job", "title"), ("Job", "url"), ("Topic", "name"), ("Promise", "text")):
            run(
                f"MATCH (d:Draft {{id:$id}}) MATCH (x:{label} {{{prop}:$v}}) MERGE (d)-[:BECAUSE]->(x)",
                {"id": d.id, "v": item if label != "Topic" else norm(item)},
            )


def set_draft_status(draft_id: str, status: str) -> None:
    run("MATCH (d:Draft {id:$id}) SET d.status=$status, d.updated_at=$now", {"id": draft_id, "status": status, "now": _now()})


def set_promise_done(text: str, session_id: str, done: bool = True) -> None:
    run("MATCH (pr:Promise {text:$text, session_id:$sid}) SET pr.done=$done", {"text": text, "sid": session_id, "done": done})
