"""Read queries. Everything user-facing is scoped to (:User {id:$uid})."""
from app.config import settings
from app.contract import CommonGround, Draft
from app.graph.db import run, scalar

# ---------------------------------------------------------------- headline


def common_ground(uid: str = settings.USER_ID, person: str | None = None) -> list[CommonGround]:
    rows = run(
        """
        MATCH (u:User {id:$uid})-[:HAD]->(s:Session)-[:WITH]->(p:Person)-[:WORKS_AT]->(c:Company)
              -[:PUBLISHED]->(d:WebDoc)-[:MENTIONS]->(t:Topic)<-[:DISCUSSED]-(s)
        WHERE $person IS NULL OR p.name = $person
        RETURN DISTINCT p.name AS person, c.name AS company, t.name AS topic,
               d.title AS doc_title, d.url AS doc_url, d.kind AS doc_kind, d.published_at AS published_at
        ORDER BY d.published_at DESC
        """,
        {"uid": uid, "person": person},
    )
    return [CommonGround(**{k: v for k, v in r.items() if k != "published_at"}) for r in rows]


def referral_radar(uid: str = settings.USER_ID) -> list[dict]:
    """Engineers you met at companies with open roles that need skills you have."""
    return run(
        """
        MATCH (u:User {id:$uid})-[:HAD]->(:Session)-[:WITH]->(p:Person {role_class:'engineer'})
              -[:WORKS_AT]->(c:Company)-[:HIRING]->(j:Job)-[:NEEDS]->(sk:Skill)<-[:HAS_SKILL]-(u)
        WITH p, c, j, collect(DISTINCT sk.name) AS matched
        RETURN p.name AS person, p.email AS email, c.name AS company,
               j.title AS job_title, j.url AS job_url, j.req_id AS req_id, matched AS matched_skills
        ORDER BY size(matched) DESC, c.name
        """,
        {"uid": uid},
    )


def segment(uid: str = settings.USER_ID, sector: str | None = None, stage: str | None = None, role_class: str | None = None) -> list[dict]:
    """People you met, filtered by company sector / stage / their role class."""
    return run(
        """
        MATCH (u:User {id:$uid})-[:HAD]->(s:Session)-[:WITH]->(p:Person)
        OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
        OPTIONAL MATCH (c)-[:IN_SPACE]->(sec:Sector)
        WITH p, c, sec, count(DISTINCT s) AS sessions
        WHERE ($sector IS NULL OR toLower(sec.name) = toLower($sector))
          AND ($stage IS NULL OR toLower(c.stage) = toLower($stage))
          AND ($role_class IS NULL OR p.role_class = $role_class)
        RETURN p.name AS person, p.role AS role, p.role_class AS role_class, p.email AS email,
               c.name AS company, c.stage AS stage, sec.name AS sector, sessions
        ORDER BY c.name, p.name
        """,
        {"uid": uid, "sector": sector, "stage": stage, "role_class": role_class},
    )


def why_path(draft_id: str) -> dict:
    """Explain a draft as hops through the graph. Returns hops (strings) plus a tiny node/edge list for the UI."""
    head = run(
        """
        MATCH (d:Draft {id:$id})-[:FOR]->(p:Person)
        OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
        OPTIONAL MATCH (s:Session)-[:WITH]->(p)
        RETURN d.id AS id, d.ask_type AS ask_type, d.subject AS subject, p.name AS person, p.role AS role,
               p.role_class AS role_class, c.name AS company, collect(DISTINCT s.id) AS sessions
        """,
        {"id": draft_id},
    )
    if not head:
        return {}
    h = head[0]
    because = run(
        """
        MATCH (d:Draft {id:$id})-[:BECAUSE]->(x)
        RETURN labels(x)[0] AS kind, coalesce(x.title, x.name, x.text) AS label, x.url AS url
        """,
        {"id": draft_id},
    )
    person, company = h["person"], h["company"]
    nodes = [{"id": "you", "label": settings.USER_NAME, "kind": "User"}, {"id": person, "label": person, "kind": "Person"}]
    edges = [{"from": "you", "to": person, "type": "MET"}]
    hops = [f"You met {person} ({h['role'] or h['role_class']}){' at ' + company if company else ''} — session {', '.join(h['sessions'])}"]
    if company:
        nodes.append({"id": company, "label": company, "kind": "Company"})
        edges.append({"from": person, "to": company, "type": "WORKS_AT"})

    for b in because:
        kind, label, url = b["kind"], b["label"], b["url"]
        if kind == "Topic":
            docs = run(
                """
                MATCH (s:Session)-[:WITH]->(p:Person {name:$p})-[:WORKS_AT]->(c:Company)
                MATCH (s)-[:DISCUSSED]->(t:Topic {name:$t})<-[:MENTIONS]-(d:WebDoc)<-[:PUBLISHED]-(c)
                RETURN DISTINCT d.title AS title, d.url AS url, c.name AS company
                """,
                {"p": person, "t": label},
            )
            nodes.append({"id": f"topic:{label}", "label": label, "kind": "Topic"})
            edges.append({"from": person, "to": f"topic:{label}", "type": "DISCUSSED"})
            for d in docs:
                hops.append(f"You discussed “{label}” → {d['company']} published “{d['title']}” ({d['url']})")
                nodes.append({"id": d["url"], "label": d["title"], "kind": "WebDoc"})
                edges.append({"from": f"topic:{label}", "to": d["url"], "type": "MENTIONED_IN"})
            if not docs:
                hops.append(f"You discussed “{label}”")
        elif kind == "WebDoc":
            hops.append(f"Source: “{label}” ({url})")
            if not any(n["id"] == url for n in nodes):
                nodes.append({"id": url, "label": label, "kind": "WebDoc"})
                edges.append({"from": company or person, "to": url, "type": "PUBLISHED"})
        elif kind == "Job":
            skills = run(
                "MATCH (j:Job {title:$t})-[:NEEDS]->(s:Skill)<-[:HAS_SKILL]-(u:User) RETURN collect(DISTINCT s.name) AS matched",
                {"t": label},
            )
            matched = skills[0]["matched"] if skills else []
            hops.append(f"{company} is hiring “{label}” ({url}) — needs {', '.join(matched) or 'skills'} you have")
            nodes.append({"id": f"job:{label}", "label": label, "kind": "Job"})
            edges.append({"from": company or person, "to": f"job:{label}", "type": "HIRING"})
        elif kind == "Promise":
            hops.append(f"Open promise: “{label}”")
            nodes.append({"id": f"promise:{label}", "label": label, "kind": "Promise"})
            edges.append({"from": person, "to": f"promise:{label}", "type": "PROMISED"})
    nodes.append({"id": draft_id, "label": h["subject"], "kind": "Draft"})
    edges.append({"from": draft_id, "to": person, "type": "FOR"})
    hops.append(f"→ Draft “{h['subject']}” ({h['ask_type']})")
    return {"draft_id": draft_id, "ask_type": h["ask_type"], "person": person, "company": company, "hops": hops, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------- building blocks used by asks/ and the UI


def people(uid: str = settings.USER_ID) -> list[dict]:
    return run(
        """
        MATCH (u:User {id:$uid})-[:HAD]->(s:Session)-[:WITH]->(p:Person)
        OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
        OPTIONAL MATCH (s)-[:DISCUSSED]->(t:Topic)
        RETURN p.name AS name, p.role AS role, p.role_class AS role_class, p.email AS email,
               c.name AS company, c.domain AS domain, collect(DISTINCT t.name) AS topics,
               collect(DISTINCT s.id) AS sessions, max(s.started_at) AS last_met
        ORDER BY last_met DESC
        """,
        {"uid": uid},
    )


def sessions(uid: str = settings.USER_ID) -> list[dict]:
    return run(
        """
        MATCH (u:User {id:$uid})-[:HAD]->(s:Session)-[:WITH]->(p:Person)
        OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
        OPTIONAL MATCH (s)-[:DISCUSSED]->(t:Topic)
        RETURN s.id AS session_id, s.started_at AS started_at, s.summary AS summary,
               p.name AS person, p.role AS role, p.role_class AS role_class, c.name AS company,
               collect(DISTINCT t.name) AS topics
        ORDER BY s.started_at DESC
        """,
        {"uid": uid},
    )


def session_detail(uid: str, session_id: str) -> dict | None:
    rows = run(
        """
        MATCH (u:User {id:$uid})-[:HAD]->(s:Session {id:$sid})-[:WITH]->(p:Person)
        OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
        OPTIONAL MATCH (s)-[:DISCUSSED]->(t:Topic)
        RETURN s.id AS session_id, s.started_at AS started_at, s.summary AS summary, s.transcript AS transcript,
               p.name AS person, p.role AS role, p.role_class AS role_class, p.email AS email,
               c.name AS company, c.domain AS domain, collect(DISTINCT t.name) AS topics
        """,
        {"uid": uid, "sid": session_id},
    )
    if not rows:
        return None
    out = rows[0]
    out["promises"] = run(
        "MATCH (s:Session {id:$sid})-[r:PROMISED]->(pr:Promise) RETURN r.by AS by, pr.text AS text, pr.done AS done",
        {"sid": session_id},
    )
    return out


def open_promises(uid: str = settings.USER_ID) -> list[dict]:
    return run(
        """
        MATCH (u:User {id:$uid})-[:HAD]->(s:Session)-[:WITH]->(p:Person)
        MATCH (s)-[r:PROMISED]->(pr:Promise) WHERE pr.done = false
        RETURN p.name AS person, r.by AS by, pr.text AS text, s.id AS session_id
        ORDER BY s.started_at DESC
        """,
        {"uid": uid},
    )


def jobs_for_company(company: str) -> list[dict]:
    return run(
        """
        MATCH (c:Company {name:$c})-[:HIRING]->(j:Job)
        OPTIONAL MATCH (j)-[:NEEDS]->(s:Skill)
        RETURN j.title AS title, j.url AS url, j.req_id AS req_id, collect(DISTINCT s.name) AS skills
        """,
        {"c": company},
    )


def _row_to_draft(r: dict) -> Draft:
    return Draft(
        id=r["id"], person=r["person"], email=r["email"], ask_type=r["ask_type"], subject=r["subject"],
        body=r["body"], status=r["status"], because=[b for b in (r.get("because") or []) if b],
    )


def draft_queue(status: str | None = "pending") -> list[Draft]:
    rows = run(
        """
        MATCH (d:Draft)-[:FOR]->(p:Person)
        WHERE $status IS NULL OR d.status = $status
        OPTIONAL MATCH (d)-[:BECAUSE]->(x)
        RETURN d.id AS id, p.name AS person, p.email AS email, d.ask_type AS ask_type, d.subject AS subject,
               d.body AS body, d.status AS status, collect(DISTINCT coalesce(x.url, x.title, x.name, x.text)) AS because,
               d.created_at AS created_at
        ORDER BY created_at DESC
        """,
        {"status": status},
    )
    return [_row_to_draft(r) for r in rows]


def get_draft(draft_id: str) -> Draft | None:
    rows = run(
        """
        MATCH (d:Draft {id:$id})-[:FOR]->(p:Person)
        OPTIONAL MATCH (d)-[:BECAUSE]->(x)
        RETURN d.id AS id, p.name AS person, p.email AS email, d.ask_type AS ask_type, d.subject AS subject,
               d.body AS body, d.status AS status, collect(DISTINCT coalesce(x.url, x.title, x.name, x.text)) AS because
        """,
        {"id": draft_id},
    )
    return _row_to_draft(rows[0]) if rows else None


def goal_map(uid: str = settings.USER_ID) -> list[dict]:
    """People whose conversation advances the user's goal, most relevant first, with what you learned from them."""
    rows = run(
        """
        MATCH (u:User {id:$uid})-[:WANTS]->(g:Goal)<-[a:ADVANCES]-(p:Person)
        MATCH (s:Session)-[:WITH]->(p) WHERE s.id = a.session_id
        OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
        OPTIONAL MATCH (s)-[:LEARNED]->(f:Fact)
        RETURN p.name AS name, p.role AS role, c.name AS company, p.role_class AS role_class,
               s.category AS category, a.relevance AS relevance, a.similarity AS similarity, a.reason AS reason,
               s.id AS session_id, collect(DISTINCT [f.id, f.kind, f.text]) AS facts
        ORDER BY relevance DESC
        """,
        {"uid": uid},
    )
    for r in rows:
        facts = sorted(f for f in r["facts"] if f and f[0] is not None)
        r["facts"] = [{"kind": kind, "text": text} for _, kind, text in facts]
    return rows


def stats() -> dict:
    out = {}
    for label in ("User", "Session", "Person", "Company", "WebDoc", "Topic", "Job", "Promise", "Draft", "Recording", "Fact", "Goal"):
        out[label] = scalar(f"MATCH (n:{label}) RETURN count(n)", default=0)
    return out


# ---------------------------------------------------------------- presets (for the Graph tab / demo)

PRESETS: dict[str, dict] = {
    "common_ground": {
        "description": "Topics you discussed that the company has published about",
        "cypher": """
            MATCH (u:User {id:$uid})-[:HAD]->(s:Session)-[:WITH]->(p:Person)-[:WORKS_AT]->(c:Company)
                  -[:PUBLISHED]->(d:WebDoc)-[:MENTIONS]->(t:Topic)<-[:DISCUSSED]-(s)
            RETURN p.name AS person, c.name AS company, t.name AS topic, d.title AS doc, d.kind AS kind
            ORDER BY d.published_at DESC""",
    },
    "referral_radar": {
        "description": "Engineers at companies hiring for your skills",
        "cypher": """
            MATCH (u:User {id:$uid})-[:HAD]->(:Session)-[:WITH]->(p:Person {role_class:'engineer'})
                  -[:WORKS_AT]->(c:Company)-[:HIRING]->(j:Job)-[:NEEDS]->(sk:Skill)<-[:HAS_SKILL]-(u)
            RETURN p.name AS person, c.name AS company, j.title AS job, collect(DISTINCT sk.name) AS matched_skills""",
    },
    "open_promises": {
        "description": "Promises made in either direction that are still open",
        "cypher": """
            MATCH (u:User {id:$uid})-[:HAD]->(s:Session)-[:WITH]->(p:Person)
            MATCH (s)-[r:PROMISED]->(pr:Promise) WHERE pr.done = false
            RETURN p.name AS person, r.by AS by, pr.text AS promise""",
    },
    "hot_topics": {
        "description": "Topics you discussed most, with how many companies publish about them",
        "cypher": """
            MATCH (u:User {id:$uid})-[:HAD]->(s:Session)-[:DISCUSSED]->(t:Topic)
            OPTIONAL MATCH (t)<-[:MENTIONS]-(:WebDoc)<-[:PUBLISHED]-(c:Company)
            RETURN t.name AS topic, count(DISTINCT s) AS conversations, count(DISTINCT c) AS companies_publishing
            ORDER BY conversations DESC, companies_publishing DESC LIMIT 15""",
    },
    "companies_by_sector": {
        "description": "Who you met, grouped by sector and stage",
        "cypher": """
            MATCH (u:User {id:$uid})-[:HAD]->(:Session)-[:WITH]->(p:Person)-[:WORKS_AT]->(c:Company)
            OPTIONAL MATCH (c)-[:IN_SPACE]->(sec:Sector)
            RETURN sec.name AS sector, c.stage AS stage, c.name AS company, collect(DISTINCT p.name) AS people
            ORDER BY sector, company""",
    },
    "goal_map": {
        "description": "People whose conversation advances your goal, with what they told you",
        "cypher": """
            MATCH (u:User {id:$uid})-[:WANTS]->(g:Goal)<-[a:ADVANCES]-(p:Person)
            OPTIONAL MATCH (s:Session)-[:LEARNED]->(f:Fact) WHERE s.id = a.session_id
            RETURN p.name AS person, a.relevance AS relevance, a.reason AS reason,
                   collect(f.kind + ': ' + f.text) AS facts
            ORDER BY relevance DESC""",
    },
    "draft_evidence": {
        "description": "Every draft with the evidence nodes it was built from",
        "cypher": """
            MATCH (d:Draft)-[:FOR]->(p:Person)
            OPTIONAL MATCH (d)-[:BECAUSE]->(x)
            RETURN d.id AS draft, p.name AS person, d.ask_type AS ask_type, d.status AS status,
                   collect(DISTINCT coalesce(x.title, x.name, x.text)) AS because""",
    },
}


def run_preset(name: str, uid: str = settings.USER_ID) -> list[dict]:
    preset = PRESETS[name]
    return run(preset["cypher"], {"uid": uid})
