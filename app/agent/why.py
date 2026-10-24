"""'Why this ask?': the full path through the graph for one draft. OWNER: Person A.

Starts from Person B's queries.why_path (You -> Person -> Company -> Topic/WebDoc/Job/Promise -> Draft) and adds
what the agent layer knows: facts learned in the conversation, the LinkedIn post the draft cites, the investor's
portfolio companies where you met someone, and the goal the person advances. Nodes stay in reading order.
"""
from app.agent import store
from app.graph import queries
from app.graph.db import run


def why(draft_id: str) -> dict:
    w = queries.why_path(draft_id)
    if not w:
        return {}
    person, company = w["person"], w["company"]
    # The base path can repeat a node (same doc via two topics, same promise in two sessions): keep the first.
    seen: set[tuple] = set()
    nodes = [n for n in w["nodes"] if not ((n.get("kind"), n.get("label")) in seen or seen.add((n.get("kind"), n.get("label"))))]
    hops = list(dict.fromkeys(w["hops"]))
    edges = list({(e["from"], e["to"], e["type"]): e for e in w["edges"]}.values())
    draft_node = nodes.pop() if nodes and nodes[-1].get("kind") == "Draft" else None
    draft_hop = hops.pop() if hops and hops[-1].startswith("→ Draft") else None
    after_person = 2  # nodes[0] = You, nodes[1] = Person

    def add(node: dict, edge: dict, hop: str, at: int | None = None) -> None:
        if any(n["id"] == node["id"] for n in nodes):
            return
        nodes.insert(at, node) if at is not None else nodes.append(node)
        edges.append(edge)
        hops.append(hop)

    # What they told you (event memory), right after the person
    facts = run(
        """MATCH (s:Session)-[:WITH]->(:Person {name:$p}) MATCH (s)-[:LEARNED]->(f:Fact)
           RETURN f.id AS id, f.kind AS kind, f.text AS text ORDER BY f.id LIMIT 3""",
        {"p": person},
    )
    for i, f in enumerate(facts):
        add({"id": f"fact:{f['id']}", "label": f["text"], "kind": "Fact"},
            {"from": person, "to": f"fact:{f['id']}", "type": "TOLD_YOU"}, f"{person} told you: {f['text']}",
            at=after_person + i)

    # Their post this week that the draft cites (Bright Data LinkedIn)
    for p in run("MATCH (:Draft {id:$id})-[:BECAUSE]->(x:Post) RETURN x.url AS url, x.text AS text", {"id": draft_id}):
        add({"id": p["url"], "label": p["text"][:140], "kind": "Post", "url": p["url"]},
            {"from": person, "to": p["url"], "type": "POSTED"}, f"{person} posted this week: “{p['text'][:100]}” ({p['url']})")

    # Investor / accelerator: portfolio companies where you also met someone (warm path)
    if company:
        rows = run(
            """MATCH (c:Company {name:$c})-[r:INVESTED_IN]->(pc:Company)
               OPTIONAL MATCH (pc)<-[:WORKS_AT]-(m:Person)<-[:WITH]-(:Session)
               WITH pc, r, collect(DISTINCT m.name) AS met
               RETURN pc.name AS name, r.round AS round, met ORDER BY size(met) DESC LIMIT 3""",
            {"c": company},
        )
        for r in rows:
            met = f", where you met {r['met'][0]}" if r["met"] else ""
            add({"id": f"portfolio:{r['name']}", "label": f"{r['name']}" + (f" · {r['round']}" if r["round"] else "") + met,
                 "kind": "Portfolio"},
                {"from": company, "to": f"portfolio:{r['name']}", "type": "INVESTED_IN"},
                f"{company} backs {r['name']}" + (f" ({r['round']})" if r["round"] else "") + met)

    # The goal this person advances (founder persona)
    persona = store.personas().get(person)
    goal = store.PERSONA_INTENTS.get(persona or "")
    if goal:
        add({"id": f"goal:{goal}", "label": goal, "kind": "Goal"},
            {"from": person, "to": f"goal:{goal}", "type": "ADVANCES"}, f"{person} ({persona}) advances: {goal}")

    if draft_node:
        nodes.append(draft_node)
    if draft_hop:
        hops.append(draft_hop)
    return {**w, "nodes": nodes, "edges": edges, "hops": hops}
