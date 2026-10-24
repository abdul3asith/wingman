# wingman

Record a 30-second voice debrief after each conversation at a conference. wingman transcribes it, extracts who
you met (name, role, company, topics, promises), scrapes the company's public web presence with Bright Data,
joins it all in FalkorDB, and finds **Common Ground** — topics you discussed that the company has *published*
about. It then drafts a role-aware follow-up per person (referral ask for engineers at hiring companies, resume
for recruiters, deck for investors…) that opens with the Common Ground hook + source link. You approve drafts
in a queue; approved drafts send via Resend. Every draft has a **why** path through the graph.

## Setup (5 steps)

1. `make install` — installs requirements and copies `.env.example` → `.env` (MOCK_MODE=true by default).
2. `make run` — starts FalkorDB in Docker, waits for it, then starts the API on http://localhost:8000.
   On first boot in MOCK_MODE the empty graph is auto-seeded with 7 conversations + cached web data.
3. Open http://localhost:8000 — Record tab (or paste a transcript) → Process → People → Generate → Queue → Approve.
4. `make smoke` (in a second terminal) — hits every endpoint in order and prints PASS/FAIL.
5. Go live: put real keys in `.env`, set `MOCK_MODE=false`, restart. FalkorDB browser UI is at http://localhost:3000
   (if 3000 is taken, set `FALKORDB_UI_PORT=3001` in `.env` before `make up`; if a local Redis owns 6379,
   set `FALKORDB_PORT=6380` — compose and the app both read it).

Other targets: `make seed` (re-run seed, idempotent) · `make reset-graph` (drop + reseed) · `make down`.

## What MOCK_MODE does

| Piece | Mock | Live |
|---|---|---|
| Transcribe | returns a canned debrief (Maya @ Parallax Labs) | `gpt-4o-transcribe` |
| Extract | canned `SessionExtract` for Maya | chat model + structured output |
| Enrich (Bright Data) | serves `seed/webdocs/<company>.json` | SERP → fetch → LLM page parse |
| Embeddings | deterministic hash vectors (1536-d) | `text-embedding-3-small` |
| Drafts | templates | chat model + structured output |
| Send | prints to console, marks sent | Resend |

FalkorDB is always real (Docker). Seed companies are fictional so cached fixtures don't misattribute content to
real companies; for the live demo, debrief about a real company and let enrichment hit the web.

## Who owns what

| Folder | Owner | Notes |
|---|---|---|
| `app/ingest/`, `app/asks/`, `web/` | **Person A** | upload → transcribe → extract; drafts, queue, send; UI |
| `app/graph/`, `seed/webdocs/` | **Person B** | FalkorDB schema/writes/queries, Bright Data enrichment, `/graph/*` |
| `app/contract.py` | both (FROZEN) | Pydantic models crossing the seam — change only together |
| `app/llm.py`, `app/config.py`, `app/main.py` | shared | small; shout before editing |

### The seam (what A calls in B's folder)
- `graph.writes.ingest_session(uid, SessionExtract)` · `graph.writes.write_draft(Draft)` · `graph.writes.set_draft_status(id, status)`
- `graph.queries.people(uid)` · `common_ground(uid, person)` · `referral_radar(uid)` · `open_promises(uid)` · `draft_queue(status)` · `get_draft(id)`
- `graph.enrich.enrich_company(name, domain)`

Signatures are stable; B can change internals freely.

## API

| Method | Path | Returns |
|---|---|---|
| POST | `/sessions` (multipart `audio` or form `transcript`) | `{session_id}` |
| POST | `/sessions/{id}/process?sync_enrich=` | `SessionExtract` (+ enriches company in background) |
| GET | `/sessions`, `/sessions/{id}` | sessions with person/topics/promises |
| POST | `/asks/generate` `{person?}` | `list[Draft]` (one per person; idempotent ids `d_<slug>`) |
| GET | `/asks/queue?status=pending\|sent\|skipped\|all` | `list[Draft]` |
| POST | `/asks/{id}/approve`, `/asks/{id}/skip` | `Draft` |
| GET | `/graph/common-ground?person=` | `list[CommonGround]` — the headline query |
| GET | `/graph/referral-radar` | engineers at companies hiring your skills |
| GET | `/graph/segment?sector=&stage=&role_class=` | people filtered by company attributes |
| GET | `/graph/why/{draft_id}` | `{hops: [...], nodes, edges}` |
| GET | `/graph/promises`, `/graph/people`, `/graph/stats` | |
| POST | `/graph/enrich` `{company, domain?}` | `EnrichResult` |
| GET/POST | `/graph/presets`, `/graph/query/{name}` | canned Cypher for the Graph tab |
| POST | `/graph/reset?reseed=true` | drop graph, recreate schema, reseed |
| GET | `/health` | mock flag, graph status, node counts |

## Graph schema

```
(:User {id,name})-[:HAS_SKILL]->(:Skill {name})
(:User)-[:HAD]->(:Session {id,started_at,summary,transcript})-[:WITH]->(:Person {name,role,role_class,email})
(:Person)-[:WORKS_AT]->(:Company {name,domain,stage})-[:IN_SPACE]->(:Sector {name})
(:Company)-[:PUBLISHED]->(:WebDoc {url,title,kind,published_at,scraped_at})-[:MENTIONS]->(:Topic {name,embedding})
(:Session)-[:DISCUSSED]->(:Topic)
(:Company)-[:HIRING]->(:Job {title,url,req_id})-[:SOURCED_FROM]->(:WebDoc) ; (:Job)-[:NEEDS]->(:Skill)
(:Session)-[:PROMISED {by}]->(:Promise {text,done})
(:Draft {id,ask_type,subject,body,status})-[:FOR]->(:Person) ; (:Draft)-[:BECAUSE]->(:WebDoc|:Job|:Topic|:Promise)
```
Topic names are lowercased; `merge_topic()` reuses an existing Topic when the embedding is near-identical.

## Demo checklist

- [ ] `make run` is up, http://localhost:8000 loads, no red "FalkorDB down" badge
- [ ] People tab shows 7 people with common-ground rows (Priya → "cold starts" → Lattice blog post)
- [ ] Record a real debrief (or paste one) → Process → extract card appears with topics + promises
- [ ] Generate follow-up → Queue shows a draft whose first paragraph cites the company's post with a link
- [ ] Click **why?** → hops: met → discussed topic → company published doc → draft
- [ ] Approve → status sent (console log in mock; real email in live)
- [ ] Graph tab: run `referral_radar` and `open_promises`; open FalkorDB browser at :3000 for the visual
- [ ] Live mode rehearsed once with real keys (Bright Data request shape verified — see TODO in `brightdata.py`)

## Open TODOs
- `app/graph/brightdata.py`: verify request body / SERP JSON shape against Bright Data docs.
- `app/graph/schema.py` + `writes.merge_topic`: confirm vector index syntax and that `score` is a distance.
- Drafts are regenerated (overwritten) per person on each `/asks/generate`; fine for demo.
