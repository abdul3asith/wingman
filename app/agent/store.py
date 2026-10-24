"""Graph reads/writes for the voice agent's own concepts. OWNER: Person A.
Uses the teammate's FalkorDB helper (app.graph.db.run); adds nodes the base schema doesn't have:

(:User)-[:HAS_INTENT]->(:Intent {text})
(:Person)-[:FITS {reason, ask_type}]->(:Intent)          # segmentation result
(:Person {linkedin, headline})-[:POSTED]->(:Post {url, text, posted_at, source})
(:Company)-[:IN_NEWS]->(:News {url, title, published_at})
(:Draft {scheduled_at})
(:Person {persona})                                       # investor | accelerator | founder | candidate | other
(:Company {about, website, industry, size, linkedin})-[:INVESTED_IN]->(:Company)   # portfolio (Crunchbase)
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


# ---------------------------------------------------------------- founder persona

# The demo persona's three audiences; each is an Intent so grouping, FITS edges and drafts reuse one path.
PERSONA_INTENTS = {
    "investor": "Raise from investors & accelerators",
    "accelerator": "Raise from investors & accelerators",
    "founder": "Partner with fellow founders",
    "candidate": "Hire our founding team",
}
PERSONA_ASK = {"investor": "pitch", "accelerator": "accelerator", "founder": "founder_coffee", "candidate": "recruit"}


def set_persona(person: str, persona: str) -> None:
    run("MATCH (p:Person {name:$p}) SET p.persona=$x", {"p": person, "x": persona})


def personas() -> dict[str, str]:
    return {r["n"]: r["x"] for r in run("MATCH (p:Person) WHERE p.persona IS NOT NULL RETURN p.name AS n, p.persona AS x")}


def ensure_persona(uid: str = UID) -> None:
    """Founder persona: the three audience intents, and personas for seed people (seed/intel/personas.json)."""
    if get_intents(uid) != list(dict.fromkeys(PERSONA_INTENTS.values())):
        set_intents(list(dict.fromkeys(PERSONA_INTENTS.values())), uid)
    path = settings.SEED_DIR / "intel" / "personas.json"
    if path.exists():
        import json

        known = personas()
        for name, persona in json.loads(path.read_text()).items():
            if name not in known:
                set_persona(name, persona)


# ---------------------------------------------------------------- company intel (Bright Data)


def save_company(company: str, profile: dict, updates: list[dict]) -> None:
    run(
        """MERGE (c:Company {name:$c}) SET c.about=coalesce($about, c.about), c.website=coalesce($web, c.website),
           c.industry=coalesce($ind, c.industry), c.size=coalesce($size, c.size), c.linkedin=coalesce($li, c.linkedin),
           c.intel_at=$now""",
        {"c": company, "about": profile.get("about"), "web": profile.get("website"), "ind": profile.get("industry"),
         "size": profile.get("size"), "li": profile.get("linkedin"), "now": _now()},
    )
    for u in updates:
        run(
            """MERGE (c:Company {name:$c}) MERGE (x:News {url:$url})
               SET x.title=$title, x.published_at=$at, x.kind='update', x.scraped_at=$now MERGE (c)-[:IN_NEWS]->(x)""",
            {"c": company, "url": u["url"], "title": u["title"], "at": u.get("published_at"), "now": _now()},
        )


def save_portfolio(investor_company: str, items: list[dict]) -> None:
    """items: [{name, round?, date?, url?}] -> (:Company)-[:INVESTED_IN {round, date}]->(:Company)."""
    for it in items:
        run(
            """MERGE (f:Company {name:$f}) MERGE (c:Company {name:$c})
               MERGE (f)-[r:INVESTED_IN]->(c) SET r.round=$round, r.date=$date, c.crunchbase=coalesce($url, c.crunchbase)""",
            {"f": investor_company, "c": it["name"], "round": it.get("round"), "date": it.get("date"), "url": it.get("url")},
        )


def set_company_job(company: str, snapshot_id: str | None, status: str) -> None:
    run("MERGE (c:Company {name:$c}) SET c.portfolio_job=$s, c.portfolio_status=$st", {"c": company, "s": snapshot_id, "st": status})


def company_intel(company: str) -> dict:
    rows = run(
        """MATCH (c:Company {name:$c})
           OPTIONAL MATCH (c)-[r:INVESTED_IN]->(pc:Company)
           OPTIONAL MATCH (pc)<-[:WORKS_AT]-(met:Person)
           WITH c, pc, r, collect(DISTINCT met.name) AS met
           RETURN c.about AS about, c.website AS website, c.industry AS industry, c.size AS size, c.linkedin AS linkedin,
                  c.portfolio_status AS portfolio_status,
                  collect(CASE WHEN pc IS NULL THEN NULL ELSE {name: pc.name, round: r.round, date: r.date, people_you_met: met} END) AS portfolio""",
        {"c": company},
    )
    out = rows[0] if rows else {}
    out["portfolio"] = [p for p in out.get("portfolio") or [] if p]
    return out


def set_company_jobs(company: str, status: str) -> None:
    run("MERGE (c:Company {name:$c}) SET c.jobs_status=$s", {"c": company, "s": status})


def company_jobs(company: str) -> dict:
    rows = run(
        """MATCH (c:Company {name:$c})
           OPTIONAL MATCH (c)-[:HIRING]->(j:Job) OPTIONAL MATCH (j)-[:SOURCED_FROM]->(d:WebDoc)
           RETURN c.jobs_status AS status, collect(DISTINCT {title: j.title, url: j.url, posted: d.published_at}) AS jobs""",
        {"c": company},
    )
    r = rows[0] if rows else {"status": None, "jobs": []}
    jobs = sorted([j for j in r["jobs"] if j.get("title")], key=lambda j: j.get("posted") or "", reverse=True)
    return {"status": r["status"], "jobs": jobs}


def find_company(name: str) -> dict | None:
    """Case-insensitive company lookup; exact name first, then contains."""
    rows = run(
        """MATCH (c:Company) WHERE toLower(c.name) = toLower($n) OR toLower(c.name) CONTAINS toLower($n)
           OPTIONAL MATCH (c)<-[:WORKS_AT]-(p:Person)
           RETURN c.name AS name, c.domain AS domain, c.about AS about, c.linkedin AS linkedin,
                  collect(DISTINCT p.name) AS people ORDER BY size(c.name) LIMIT 1""",
        {"n": name.strip()},
    )
    return rows[0] if rows else None


def warm_paths(uid: str = UID) -> list[dict]:
    """Investors you met whose fund backs a company where you also met someone: the graph's warm-intro paths."""
    return run(
        """MATCH (:User {id:$uid})-[:HAD]->(:Session)-[:WITH]->(inv:Person)-[:WORKS_AT]->(f:Company)-[:INVESTED_IN]->(c:Company)
           MATCH (:User {id:$uid})-[:HAD]->(:Session)-[:WITH]->(p:Person)-[:WORKS_AT]->(c)
           WHERE p <> inv
           RETURN DISTINCT inv.name AS investor, f.name AS fund, c.name AS company, p.name AS person""",
        {"uid": uid},
    )


# ---------------------------------------------------------------- scheduling


def set_scheduled(draft_id: str, send_at: str | None) -> None:
    run("MATCH (d:Draft {id:$id}) SET d.scheduled_at=$at", {"id": draft_id, "at": send_at})


def scheduled_map() -> dict[str, str]:
    rows = run("MATCH (d:Draft) WHERE d.scheduled_at IS NOT NULL RETURN d.id AS id, d.scheduled_at AS at")
    return {r["id"]: r["at"] for r in rows}
