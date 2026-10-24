# wingman: demo runbook (Person A presents)

## Before you go on stage

**Setup (do once, by 3:15 PM feature freeze)**
- [ ] `.env`: `OPENAI_API_KEY` set; `RESEND_API_KEY` set; `FROM_EMAIL` on a domain verified in Resend.
- [ ] Rehearsal send: set `SEND_TEST_TO=<your email>`, restart, approve one draft, and confirm it lands
      (subject starts with `[test → …]`). Then clear `SEND_TEST_TO` and send one real email to a teammate.
- [ ] Real seed: record 6–8 debriefs in **your own voice** around the venue (3 inference/infra engineers,
      1 recruiter, 1 founder, 1 investor, 1 designer). Ask before recording anyone else.
      Then `python scripts/export_seed.py`. Person B saves those companies' enrichment to `seed/webdocs/`.
- [ ] `ASSET_LINKS` in `.env` covers everything you promised people (repo, notes, …).

**Right before the demo (5 min)**
- [ ] `make up`, then `make run`. Status bar is green ("FalkorDB connected") and shows LIVE or MOCK as intended.
- [ ] `make smoke` prints **ALL PASS** (it never sends email; approve runs as a dry run).
- [ ] Insights tab: Common Ground has ≥ 4 rows and Referral Radar ≥ 2.
- [ ] Queue cleared of junk (Skip test drafts), FalkorDB Browser open in a second tab.
- [ ] Backup screen recording of the full flow is on the desktop.
- [ ] Mic permission already granted in the browser (record one throwaway clip).

## The script (about 3 minutes)

1. **Problem.** "You met 20 people today. You'll follow up with 2, and they'll be generic."
2. **Record live.** Record tab → **Start recording**, then a 20-second debrief:
   *"Just met Sarah Chen, backend engineer at Modal. We talked GPU cold starts and KV cache. She said they're
   hiring and could refer me. I promised to send my benchmark repo. Her email is sarah at modal dot com."*
   → **End & process**. The card shows person, role badge, topics, promises, and the email (only because it was said).
3. **Bright Data (Person B).** Enrichment lands: blog, repos, jobs, each with a URL.
4. **Common Ground.** Insights tab: "the topic you discussed ↔ the post they published", with links.
5. **Generate.** **Generate all follow-ups**: one draft per person. Each first sentence cites the topic and the
   company's post; engineers at hiring companies get a **referral** ask that names the real job.
6. **Why this ask?** On a referral draft: Person → Topic → WebDoc ← Company → Job → Draft, with clickable sources.
7. **Approve.** Edit a word live, then **Approve & send** to a judge's inbox (ask them first).
8. **Close.** "Your conversation is half the context. Bright Data brings the other half live; FalkorDB joins them."

## If something breaks

| Problem | Fastest fallback |
|---|---|
| Mic / browser permission | "No mic? Type the debrief instead": same pipeline, no audio |
| Transcription errors | Deepgram → gpt-4o-transcribe → whisper-1 fall back automatically; else type it |
| "couldn't tell who you met" | Say the person's full name in the first sentence |
| Bright Data slow | Enrich runs in the background; seed companies already have web data |
| OpenAI down | `MOCK_MODE=true` + restart: seed data, template drafts, everything still clickable |
| Email fails | Show the draft and the why path; the send is the least interesting part |
| FalkorDB down | `make up`; `make reset-graph` reloads seed in seconds |

## Guardrails to mention if asked
- Nothing auto-sends: every email needs an Approve click.
- Emails come only from what was said (code-checked) or manual entry; never scraped or guessed.
- Bright Data scrapes company-level public pages only; no personal profiles.
