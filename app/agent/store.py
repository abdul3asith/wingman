"""Graph reads/writes for the voice agent's own concepts. OWNER: Person A.
Uses the teammate's FalkorDB helper (app.graph.db.run); adds nodes the base schema doesn't have:

(:User)-[:HAS_INTENT]->(:Intent {text})
(:Person)-[:FITS {reason, ask_type}]->(:Intent)          # segmentation result
(:Person {linkedin, headline})-[:POSTED]->(:Post {url, text, posted_at, source})
(:Company)-[:IN_NEWS]->(:News {url, title, published_at})
(:Draft {scheduled_at})
"""
from datetime import datetime, timezone

from app.config import settings
from app.graph.db import run

UID = settings.USER_ID


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- intents


def set_intents(intents: list[str], uid: str = UID) -> list[str]:
    clean = [i.strip() for i in intents if i and i.strip()]
    run("MERGE (u:User {id:$uid}) WITH u OPTIONAL MATCH (u)-[r:HAS_INTENT]->() DELETE r", {"uid": uid})
    for text in clean:
        run("MATCH (u:User {id:$uid}) MERGE (i:Intent {text:$t}) MERGE (u)-[:HAS_INTENT]->(i)", {"uid": uid, "t": text})
    return clean


def get_intents(uid: str = UID) -> list[str]:
    return [r["text"] for r in run("MATCH (:User {id:$uid})-[:HAS_INTENT]->(i:Intent) RETURN i.text AS text", {"uid": uid})]


# ---------------------------------------------------------------- segmentation


def save_segments(assignments: list[dict]) -> None:
    """assignments: [{person, intent, reason, ask_type}]; replaces previous FITS edges."""
    run("MATCH (:Person)-[r:FITS]->(:Intent) DELETE r")
    for a in assignments:
        if not a.get("intent"):
            continue
        run(
            "MATCH (p:Person {name:$p}) MATCH (i:Intent {text:$i}) MERGE (p)-[f:FITS]->(i) SET f.reason=$reason, f.ask_type=$ask",
            {"p": a["person"], "i": a["intent"], "reason": a.get("reason", ""), "ask": a.get("ask_type")},
        )


def segments(uid: str = UID) -> list[dict]:
    rows = run(
        """
        MATCH (:User {id:$uid})-[:HAS_INTENT]->(i:Intent)
        OPTIONAL MATCH (p:Person)-[f:FITS]->(i)
        OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
        RETURN i.text AS intent, collect(CASE WHEN p IS NULL THEN NULL ELSE
               {person: p.name, role: p.role, role_class: p.role_class, company: c.name, reason: f.reason, ask_type: f.ask_type} END) AS people
        """,
        {"uid": uid},
    )
    return [{"intent": r["intent"], "people": [x for x in r["people"] if x]} for r in rows]


def ask_overrides() -> dict[str, dict]:
    """person -> {intent, ask_type} from the last segmentation."""
    rows = run("MATCH (p:Person)-[f:FITS]->(i:Intent) RETURN p.name AS person, i.text AS intent, f.ask_type AS ask_type, f.reason AS reason")
    return {r["person"]: r for r in rows}


# ---------------------------------------------------------------- people intel (Bright Data results)


def set_linkedin(person: str, url: str) -> None:
    run("MATCH (p:Person {name:$p}) SET p.linkedin=$url", {"p": person, "url": url})


def save_intel(person: str, company: str | None, profile: dict | None, posts: list[dict], news: list[dict]) -> None:
    now = _now()
    if profile:
        run(
            "MATCH (p:Person {name:$p}) SET p.headline=coalesce($h, p.headline), p.linkedin=coalesce($url, p.linkedin), p.intel_at=$now",
            {"p": person, "h": profile.get("headline"), "url": profile.get("url"), "now": now},
        )
    for post in posts:
        run(
            """MATCH (p:Person {name:$p}) MERGE (x:Post {url:$url})
               SET x.text=$text, x.posted_at=$at, x.source=$src, x.scraped_at=$now MERGE (p)-[:POSTED]->(x)""",
            {"p": person, "url": post["url"], "text": post["text"], "at": post.get("posted_at"), "src": post.get("source", "linkedin"), "now": now},
        )
    if company:
        for n in news:
            run(
                """MERGE (c:Company {name:$c}) MERGE (x:News {url:$url})
                   SET x.title=$title, x.published_at=$at, x.scraped_at=$now MERGE (c)-[:IN_NEWS]->(x)""",
                {"c": company, "url": n["url"], "title": n["title"], "at": n.get("published_at"), "now": now},
            )


def person_intel(person: str) -> dict:
    rows = run(
        """
        MATCH (p:Person {name:$p})
        OPTIONAL MATCH (p)-[:POSTED]->(x:Post)
        OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
        WITH p, c, x ORDER BY x.posted_at DESC
        WITH p, c, collect(x {.url, .text, .posted_at, .source})[0..3] AS posts
        OPTIONAL MATCH (c)-[:IN_NEWS]->(n:News)
        WITH p, c, posts, n ORDER BY n.published_at DESC
        RETURN p.linkedin AS linkedin, p.headline AS headline, c.name AS company, posts,
               collect(n {.url, .title, .published_at})[0..3] AS news
        """,
        {"p": person},
    )
    return rows[0] if rows else {"linkedin": None, "headline": None, "company": None, "posts": [], "news": []}


# ---------------------------------------------------------------- scheduling


def set_scheduled(draft_id: str, send_at: str | None) -> None:
    run("MATCH (d:Draft {id:$id}) SET d.scheduled_at=$at", {"id": draft_id, "at": send_at})


def scheduled_map() -> dict[str, str]:
    rows = run("MATCH (d:Draft) WHERE d.scheduled_at IS NOT NULL RETURN d.id AS id, d.scheduled_at AS at")
    return {r["id"]: r["at"] for r in rows}
