"""Graph views for Wingman's own graph card (the bundled FalkorDB Browser can't read this FalkorDB version).
OWNER: Person A.

Each view runs Cypher on FalkorDB that returns only scalar columns (names, ids, titles) — never whole nodes with
embedding vectors — and turns the rows into {nodes, edges}. The Cypher is returned too, so the UI can show it.
"""
from app.config import settings
from app.graph.db import run

UID = settings.USER_ID

OVERVIEW = """MATCH (u:User {id:$uid})-[:HAD]->(:Session)-[:WITH]->(p:Person)
OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
OPTIONAL MATCH (p)-[:FITS]->(i:Intent)
RETURN DISTINCT p.name AS person, p.persona AS persona, c.name AS company, i.text AS goal"""

WARM = """MATCH (:User {id:$uid})-[:HAD]->(:Session)-[:WITH]->(inv:Person)-[:WORKS_AT]->(f:Company)
      -[r:INVESTED_IN]->(c:Company)<-[:WORKS_AT]-(p:Person)<-[:WITH]-(:Session)<-[:HAD]-(:User {id:$uid})
WHERE p <> inv
RETURN DISTINCT inv.name AS investor, f.name AS fund, r.round AS round, c.name AS company, p.name AS person"""

PERSON = """MATCH (p:Person {name:$name})
OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
OPTIONAL MATCH (s:Session)-[:WITH]->(p)
OPTIONAL MATCH (s)-[:LEARNED]->(f:Fact)
OPTIONAL MATCH (s)-[:DISCUSSED]->(t:Topic)
OPTIONAL MATCH (c)-[:PUBLISHED]->(d:WebDoc)-[:MENTIONS]->(t)
OPTIONAL MATCH (c)-[r:INVESTED_IN]->(pc:Company)
OPTIONAL MATCH (p)-[:FITS]->(i:Intent)
RETURN p.name AS person, p.persona AS persona, c.name AS company, collect(DISTINCT f.text) AS facts,
       collect(DISTINCT t.name) AS topics, collect(DISTINCT [t.name, d.title, d.url]) AS common_ground,
       collect(DISTINCT pc.name) AS portfolio, collect(DISTINCT i.text) AS goals"""


class _G:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple, dict] = {}

    def node(self, kind: str, label: str | None, url: str | None = None) -> str | None:
        if not label:
            return None
        nid = f"{kind}:{label}"
        self.nodes.setdefault(nid, {"id": nid, "label": label, "kind": kind, **({"url": url} if url else {})})
        return nid

    def edge(self, a: str | None, b: str | None, rel: str) -> None:
        if a and b:
            self.edges.setdefault((a, b, rel), {"from": a, "to": b, "type": rel})

    def out(self, view: str, cypher: str, **extra) -> dict:
        return {"view": view, "cypher": cypher, "nodes": list(self.nodes.values()), "edges": list(self.edges.values()), **extra}


def overview() -> dict:
    g = _G()
    you = g.node("You", settings.USER_NAME)
    for r in run(OVERVIEW, {"uid": UID}):
        p = g.node("Person", r["person"])
        g.edge(you, p, "MET")
        g.edge(p, g.node("Company", r["company"]), "WORKS_AT")
        g.edge(p, g.node("Goal", r["goal"]), "FITS")
    return g.out("overview", OVERVIEW)


def warm_intros() -> dict:
    g = _G()
    you = g.node("You", settings.USER_NAME)
    for r in run(WARM, {"uid": UID}):
        inv, fund, comp, person = (g.node("Person", r["investor"]), g.node("Company", r["fund"]),
                                   g.node("Company", r["company"]), g.node("Person", r["person"]))
        g.edge(you, inv, "MET")
        g.edge(you, person, "MET")
        g.edge(inv, fund, "WORKS_AT")
        g.edge(fund, comp, "INVESTED_IN" + (f" · {r['round']}" if r.get("round") else ""))
        g.edge(person, comp, "WORKS_AT")
    return g.out("warm_intros", WARM)


def person(name: str) -> dict:
    rows = run(PERSON, {"name": name})
    g = _G()
    if not rows or not rows[0]["person"]:
        return g.out("person", PERSON, error=f"no one called {name}")
    r = rows[0]
    you = g.node("You", settings.USER_NAME)
    p = g.node("Person", r["person"])
    c = g.node("Company", r["company"])
    g.edge(you, p, "MET")
    g.edge(p, c, "WORKS_AT")
    for goal in r["goals"]:
        g.edge(p, g.node("Goal", goal), "FITS")
    for f in r["facts"][:5]:
        g.edge(p, g.node("Fact", f), "TOLD_YOU")
    for t in r["topics"][:6]:
        g.edge(p, g.node("Topic", t), "DISCUSSED")
    for t, title, url in [cg for cg in r["common_ground"] if cg and cg[1]][:5]:
        doc = g.node("WebDoc", title[:80], url)
        g.edge(c, doc, "PUBLISHED")
        g.edge(doc, g.node("Topic", t), "MENTIONS")
    for pc in r["portfolio"][:10]:
        g.edge(c, g.node("Portfolio", pc), "INVESTED_IN")
    return g.out("person", PERSON, person=r["person"])


def view(name: str, person_name: str | None = None) -> dict:
    if name == "person" and person_name:
        return person(person_name)
    return warm_intros() if name == "warm_intros" else overview()
