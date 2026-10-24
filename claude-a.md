# CLAUDE.md — Ask Engine (Person A: Capture, Asks, UI)

> Rename this file to `CLAUDE.md` at the repo root of **your** clone. Do not commit it over Person B's.

## Who you are working with

You are pairing with **Person A** at a 3-hour hackathon (Patch the Conference, Bright Data SF, demos 5:30 PM).
Person A owns everything the user touches: recording, transcription, extraction, ask drafting, sending, and the web UI.
Person B owns the graph (FalkorDB) and Bright Data enrichment. You never write Cypher; you call Person B's functions/endpoints.

Speed beats polish. Ship working, demoable code in small commits. When unsure, pick the simplest option that keeps the demo working and leave a `TODO(A):` comment.

## The product in one paragraph

Users record short voice debriefs after conference conversations. We transcribe and extract who they met (name, role, company, topics, promises). Bright Data scrapes each company's public web (site, careers, blog, news, GitHub). FalkorDB joins conversations with web data. **Common Ground** = topics the user discussed that the company also published about. We draft a role-aware follow-up per person that opens with the Common Ground hook + source link, the user approves in a queue, and approved drafts send by email. Every draft can show its "why" path in the graph.

## What you own (only edit these)

```
app/ingest/      routes.py, transcribe.py, extract.py
app/asks/        routes.py, rules.py, drafts.py, send.py
web/index.html
seed/sessions/*.json
app/llm.py       (shared helper; you are its primary owner, tell B before changing signatures)
```

**Do not edit:** `app/graph/**` (Person B), `app/contract.py` (frozen, change only with B's agreement), `seed/webdocs/**` (B).
If you need something from the graph that doesn't exist, write the call you wish existed, stub it in your own module behind a clearly named function, and leave `TODO(B-request): …` so B can implement it.

## Interfaces you depend on (from Person B)

Import from `app.graph` — do not reimplement:

| Function / endpoint | Returns | Use it for |
|---|---|---|
| `graph.writes.ingest_session(extract: SessionExtract, uid)` / `POST /graph/ingest` | None | After extraction |
| `POST /graph/enrich/{company}` | `EnrichResult` | Kick off in a background task after ingest |
| `graph.queries.common_ground(uid, person=None)` | `list[CommonGround]` | Draft hook + insights panel |
| `graph.queries.referral_radar(uid)` | rows: person, company, job title, url, matched skills, score | Referral asks |
| `graph.queries.segment(uid, role_class, sector)` | rows | Query presets |
| `graph.writes.write_draft(draft: Draft, uid, because_refs)` | None | Persist drafts + BECAUSE edges |
| `GET /graph/why/{draft_id}` | `{nodes:[…], edges:[…]}` | "Why this ask?" panel |
| `POST /graph/query` `{preset, params}` | rows | Preset buttons |

If B's function isn't ready, call the endpoint and fall back to mock JSON when `MOCK_MODE=true`.

## Shared contract (app/contract.py — FROZEN)

`Person`, `Company`, `Promise`, `SessionExtract`, `WebDoc`, `Job`, `EnrichResult`, `CommonGround`, `Draft`.
`role_class` ∈ `engineer | recruiter | founder | investor | pm_design | other` — it drives the ask.
Always produce/consume these models; never pass raw dicts across the A/B boundary.

## Your build plan

### Hour 1 — capture → graph
- [ ] `web/index.html` Record panel: Start / End (MediaRecorder, `audio/webm`), POST to `/sessions`, then `/sessions/{id}/process`. Show a spinner and the extracted card.
- [ ] Typed-debrief fallback textarea → `POST /sessions/debrief-text` (demo insurance if mic/Wi-Fi fails).
- [ ] `transcribe.py`: OpenAI `gpt-4o-transcribe`; fallback `whisper-1` on error.
- [ ] `extract.py`: one structured-output call returning `SessionExtract` (promises included). Prompt rules below.
- [ ] `/sessions/{id}/process` → `ingest_session` → background `enrich(company)`.

### Hour 2 — seed + drafts
- [ ] Record 6–8 real debriefs around the venue (3 engineers at inference/infra cos, 1 recruiter, 1 founder, 1 investor, 1 designer). Save resulting JSON into `seed/sessions/`. Never record anyone without asking; debriefs are your own voice.
- [ ] `rules.py`: role → ask mapping (below).
- [ ] `drafts.py`: gather context (person, company, topics, promises, common ground rows, radar match) → one structured-output call → `Draft`.
- [ ] `/asks/generate` writes drafts through `write_draft` with `because` refs (doc URLs, topic names, job titles, promise texts).

### Hour 3 — queue, send, why, polish
- [ ] Ask queue UI: card per draft (to, ask-type badge, subject, editable body), Approve / Skip.
- [ ] `send.py`: Resend. `MOCK_MODE=true` → log + mark sent. Before the demo, verify the sender domain and send one to a teammate.
- [ ] "Why this ask?" toggle → `/graph/why/{id}` → render as a vertical chain of labeled nodes, URLs clickable.
- [ ] Insights panel: 3 preset buttons + Common Ground + Referral Radar as cards with source links.
- [ ] Own the demo script and the live recording on stage.

**Freeze features at 3:15 PM.** After that: bug fixes, rehearsal, backup screen recording.

## Prompts (keep them in code as constants)

### Extraction (`extract.py`)
- Input: transcript. Output: `SessionExtract` via structured outputs.
- Rules: the speaker is the user ("me"). Extract the **other** person only. Normalize role to a short title; map to `role_class`. Company as spoken, best-effort spelling (B resolves it via SERP). Topics: 2–4 short noun phrases, lowercase, no duplicates ("kv cache", "inference serving"). Promises: anything either side committed to, with `by: me|them`. Summary: one sentence, factual. If a field is unknown, null — never invent emails.

### Draft (`drafts.py`)
- Under 120 words. Plain-text email. One clear ask.
- First sentence references the specific conversation topic **and** the Common Ground doc title with its URL.
- Include fulfilment of any `by: me` promise (link to the asset).
- No flattery filler, no "I hope this finds you well".
- Return `subject`, `body`, `because` (the URLs/topics/jobs actually used).

## Ask rules (`rules.py`)

| role_class | Condition | ask_type | Attach |
|---|---|---|---|
| engineer | has referral_radar match | `referral` (name job title + link) | `RESUME_URL` |
| engineer | no match | `technical_followup` | — |
| recruiter | — | `resume` | `RESUME_URL` |
| founder | — | `coffee_partnership` | `DECK_URL` |
| investor | — | `update` | `DECK_URL` |
| pm_design | — | `feedback_collab` | demo link |
| any | promise `by: me` exists | add fulfilment line | promised asset |

## UI guidelines

- Single page, Tailwind CDN, vanilla JS, no build step. Dark-friendly.
- Four panels: Record · Insights · Ask Queue · status bar (FalkorDB health, MOCK_MODE, link to FalkorDB Browser `http://localhost:3000`).
- Every result card that came from the web shows its source link. Explainability is a judging criterion.
- Big, legible on a projector: base font ≥ 16px, high contrast, one primary button per panel.

## Guardrails

- Never auto-send. Every email needs an Approve click.
- Never scrape or guess personal emails or LinkedIn. Emails come only from the conversation or manual entry.
- Keep API keys in `.env`; never log them.
- Default to `MOCK_MODE=true` until the real path works end to end; the demo must run in mock mode.

## Commands

```
make up          # FalkorDB in Docker
make run         # uvicorn app.main:app --reload
make seed        # reset graph + load seed (B's loader; you supply seed/sessions)
make smoke       # end-to-end check
```

## Integration checkpoints with Person B

| Time | Checkpoint |
|---|---|
| 12:30 PM | Contract frozen, both import it |
| 1:15 PM | One hand-written SessionExtract → graph → one draft |
| 2:15 PM | 6+ seed sessions in, companies enriched, Common Ground ≥ 4 rows, Radar ≥ 2 |
| 3:15 PM | Approve sends a real email; why-path renders; presets answer. **Feature freeze.** |

## Demo script (you present)

1. "You met 20 people today. You'll follow up with 2, and they'll be generic."
2. Record a live 20-second debrief; it appears in the graph.
3. B enriches that company live; blog, repos, jobs land with URLs.
4. Common Ground lights up: topic you discussed ↔ their blog post.
5. Generate: 7 drafts, each opening with a Common Ground hook; 2 referral asks name real jobs.
6. "Why this ask?": Session → Topic ← WebDoc ← Company ← Person, with the link.
7. Approve one → lands in a judge's inbox (ask first).
8. Close: "Your conversation is half the context. Bright Data brings the other half live; FalkorDB joins them."

## How to work with me (Claude)

- Make small, focused changes; run `make smoke` after each meaningful change.
- When a task touches B's folder, stop and tell me what B needs instead of editing it.
- Prefer working code with a TODO over a perfect design. Say what you skipped.
- If something blocks the demo, propose the fastest fallback first (mock data, typed debrief, preset query).