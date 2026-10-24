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

Open http://localhost:8000. Everything is one button: tap the orb (or hold space) and talk. The old tabbed UI is at
`/classic.html`. Each line below also works as a chip or typed message if the room is too loud.

1. **Problem.** "You met 20 people today. You'll follow up with 2, and they'll be generic."
2. **Before the conference.** Tap and say: *"I want an LLM inference engineering job, and seed investors for my side project."*
   Goals appear above the orb.
3. **During.** Tap **Record a conversation**, have a 20-second chat with a teammate playing Sarah:
   *"I'm Sarah Chen, backend engineer at Modal. We're hiring for inference. Find me on LinkedIn, sarahchen."*
   **Stop & save**: the person card appears, then the amber bar: Bright Data is pulling her LinkedIn posts live.
4. **After.** *"Who fits my goals?"*: people sorted into your goals, each with the ask that serves it.
5. *"Research my job search people."*: the Live web card: LinkedIn posts + this week's company news (Bright Data).
6. *"Draft follow-ups for my job search."*: each draft opens with common ground or **their post from this week**,
   and referral asks name the real open role.
7. **Why this?** on a draft: the path through the graph, with clickable sources.
8. *"Schedule them for Monday 9am."*: Wingman reads back who gets what and asks. *"Yes, go ahead."* Scheduled.
9. **Close.** "Your conversation is half the context. Bright Data brings the other half live; FalkorDB joins them."

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
