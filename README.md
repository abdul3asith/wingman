# wingman

Record each conversation you have at a conference, with the other person in it. wingman transcribes it with
speaker labels, splits one recording into the separate conversations it holds, extracts who you met (name, role,
company, topics, facts, promises) and how each conversation relates to your goal, scrapes the company's public web presence with Bright Data,
joins it all in FalkorDB, and finds **Common Ground** — topics you discussed that the company has *published*
about. It then drafts a role-aware follow-up per person (referral ask for engineers at hiring companies, resume
for recruiters, deck for investors…) that opens with the Common Ground hook + source link. You approve drafts
in a queue; approved drafts send via Resend. Every draft has a **why** path through the graph.

## Setup (5 steps)

1. `make install` — installs requirements and copies `.env.example` → `.env` (MOCK_MODE=true by default).
   Set `USER_GOAL` in `.env` (default "Get hired as a software engineer" — a dummy goal for now); every recorded
   conversation is scored against it.
2. `make run` — starts FalkorDB in Docker, waits for it, then starts the API on http://localhost:8000.
   On first boot in MOCK_MODE the empty graph is auto-seeded with 7 conversations + cached web data.
3. Open http://localhost:8000 — Record tab: press Record, keep recording through as many conversations as you like,
   press Stop → Process. wingman transcribes with speaker labels, works out which speaker is you (the one present in
   every conversation), splits the recording into conversations at long silences or partner switches, and shows one
   card per conversation: who, category, one-line context, topics, facts, promises, and whether it advances your
   goal. Each conversation lands in the graph and shows up in People → Generate → Queue → Approve. In MOCK_MODE the
   recording is a canned pair of conversations (Maya @ Parallax Labs, then Jordan, a recruiter @ Lattice Compute).
4. `make smoke` (in a second terminal) — hits every endpoint in order and prints PASS/FAIL.
5. Go live: put real keys in `.env`, set `MOCK_MODE=false`, restart. FalkorDB browser UI is at http://localhost:3000
   (if 3000 is taken, set `FALKORDB_UI_PORT=3001` in `.env` before `make up`; if a local Redis owns 6379,
   set `FALKORDB_PORT=6380` — compose and the app both read it).

Other targets: `make seed` (re-run seed, idempotent) · `make reset-graph` (drop + reseed) · `make down`.

## What MOCK_MODE does

| Piece | Mock | Live |
|---|---|---|
| Transcribe | returns canned timed turns: two conversations (Maya @ Parallax Labs, then Jordan @ Lattice Compute) | Deepgram `nova-3` with speaker diarization when `DEEPGRAM_API_KEY` is set, else `gpt-4o-transcribe` |
| Extract (per conversation) | canned extractions matching the mock conversations | chat model + structured output |
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
| POST | `/sessions/{id}/process` | `{session_id, me_speaker, goal, conversations: [{id, seq, start, end, partners, person, category, context, topics, facts, promises, goal: {relevance, similarity, reason, linked}, transcript}]}` — writes event memory to the graph; the transcript is saved to `cache/transcripts/` and returned for display only |
| GET | `/memory/goal` | `{goal, connections: [...]}` — people whose conversation advances your goal, most relevant first, with the facts you learned from them |
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

# event memory (one Recording holds one or more conversations; each conversation is a Session)
(:User)-[:WANTS]->(:Goal {id:'goal',text,embedding})
(:User)-[:RECORDED]->(:Recording {id,started_at,duration_s,conversations})-[:CONTAINS]->(:Session {id:'<rid>-c<seq>',category,context,start,end,recording_id,embedding})
(:Session)-[:LEARNED]->(:Fact {id,kind,text,embedding})
(:Session)-[:ADVANCES {similarity,relevance,reason}]->(:Goal)
(:Person)-[:ADVANCES {similarity,relevance,reason,session_id}]->(:Goal)
```
Topic names are lowercased; `merge_topic()` reuses an existing Topic when the embedding is near-identical.

Full transcripts never go into the graph: they stay in `cache/transcripts/<id>.txt`, and recorded Sessions carry an
empty `transcript`. The graph stores context, topics, categories, facts and embeddings. `ADVANCES` edges exist only
when the LLM's goal relevance is at least `GOAL_LINK_MIN` (0.5, `app/memory/build.py`); `similarity` is the cosine
between the conversation profile and the goal embedding. Segmentation thresholds (`GAP_S`, `SWITCH_S`, `MIN_WORDS`)
live at the top of `app/memory/segment.py`.

## Demo checklist

- [ ] `make run` is up, http://localhost:8000 loads, no red "FalkorDB down" badge
- [ ] People tab shows 7 people with common-ground rows (Priya → "cold starts" → Lattice blog post)
- [ ] Record two conversations back to back → Process → one card per conversation; the hiring one says "Advances your goal"
- [ ] `GET /memory/goal` (or Graph tab → `goal_map`) lists the recruiter with the job facts
- [ ] Generate follow-up → Queue shows a draft whose first paragraph cites the company's post with a link
- [ ] Click **why?** → hops: met → discussed topic → company published doc → draft
- [ ] Approve → status sent (console log in mock; real email in live)
- [ ] Graph tab: run `referral_radar` and `open_promises`; open FalkorDB browser at :3000 for the visual
- [ ] Live mode rehearsed once with real keys (Bright Data request shape verified — see TODO in `brightdata.py`)

## Open TODOs
- `app/graph/brightdata.py`: verify request body / SERP JSON shape against Bright Data docs.
- `app/graph/schema.py` + `writes.merge_topic`: confirm vector index syntax and that `score` is a distance.
- Drafts are regenerated (overwritten) per person on each `/asks/generate`; fine for demo.
