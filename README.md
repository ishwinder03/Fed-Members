# FOMC voters

A local web app with two tabs:

- **Votes & speeches** collects Federal Reserve FOMC votes and what the 12 voters have said.
- **Analysis** turns that collected material into a hawkishness signal ahead of the next FOMC meeting.

```
pip install -r requirements.txt
python3 server.py              # opens http://127.0.0.1:8765
python3 server.py --load 3m    # same load, headless (window defaults to 1y)
python3 verify.py 1y           # checks votes, decisions, governor counts, spot-checks 3 speeches
python3 -m analysis.run        # same as "Run analysis", headless (see Analysis below)
```

After changing any code or `analysis/config.toml`, restart `server.py`: a running server keeps the
old code and settings in memory.

## Theme and publishing

- **Theme:** the switch in the header picks **HSBC colours** (default) or **Classic**, the original
  look. A full copy of the classic page is kept in `static/themes/index_classic_backup.html`.
- **Publish to GitHub:** builds a view-only copy of the whole board (both tabs, current window and
  model, all data baked in, no Load / Run / Copy / Log buttons) as `view_for_work.html` at the repo
  root. It commits **only that file** and pushes it to `origin` (github.com/ishwinder03/Fed-Members).
  The repo is public, so anyone with the link can see the file. Open it at work by downloading it
  from GitHub ("Download raw file") and opening it in a browser. The snapshot always uses the HSBC
  colours, with no theme switch and no mention of the theme.
- **Email to work:** the same file as an attachment to the work address (`EMAIL` in `snapshot.py`),
  through the Mac's Mail app, or through Gmail's SMTP server if `SMTP_PASSWORD` (a Gmail app
  password) is set in `.env` or the environment.
- `GET /api/snapshot?window=1y` downloads the same file without publishing or emailing it.

## Refreshing from your phone (GitHub Actions)

`.github/workflows/refresh.yml` ("Refresh board") does Load, Run analysis and the snapshot on
GitHub's machines, so the Mac can be shut: in the GitHub app open the repo, **Actions > Refresh
board > Run workflow**, pick the window (and whether to email it). It commits the new
`view_for_work.html` (and emails it when the `SMTP_PASSWORD` secret is set). The same steps run
locally with `python3 refresh.py --window 6m [--email]`.

- Secrets (repo Settings > Secrets and variables > Actions): `GEMINI_API_KEY` (required),
  `SMTP_PASSWORD` (optional, a Gmail app password for ishusandhu8@gmail.com).
- `data/` is kept between runs in the Actions cache, so later runs fetch and score only what is
  new. GitHub drops the cache after 7 days unused; the next run rebuilds it (about 100 Flash-Lite calls).
- It uses the default model (Flash-Lite, free tier); the paid models aren't available there.

## Votes & speeches tab

The window picker sets both what a **Load** fetches (only items dated inside the window) and what
the page shows. Everything loaded is kept in `data/fed.db`, so reopening the app shows the last
results straight away. **Log** shows the last load's log and how long each load took.

**Copy all text** copies every collected speech, statement and essay in the selected window to the
clipboard. Items are oldest first, then ordered by speaker, and each has a header (date, name, type,
title, link) followed by the exact text.

### Where the data comes from

- **Voters**: every statement linked from the FOMC calendar. Since June 2026 the statements only
  name dissenters ("approved by a 10–2 vote"), so the "Voting for" list comes from the meeting
  **minutes**. If a meeting has no minutes yet, its for-votes are carried over from the previous
  meeting and marked *provisional* until the minutes appear. Dissent wording always comes from the
  statement.
- **People** are matched by a fixed id (`waller`, `williams`, …) via the exact printed names in
  `fedwatch/people.py`. An unknown name is reported, never fuzzy-matched.
- **Speeches**
  - Governors: `federalreserve.gov/newsevents/{year}-speeches.htm` (speaker = URL prefix)
  - Williams: `newyorkfed.org/newsevents/speeches/index` ("Williams:" rows)
  - Hammack: `clevelandfed.org/collections/speeches` (+ its paging JSON)
  - Paulson: `philadelphiafed.org/the-economy/speeches-anna-paulson`
  - Logan: `dallasfed.org/news/speeches/logan`
  - Kashkari: `minneapolisfed.org/people/neel-kashkari` (speeches and written essays)

### Economic data

Every Load also refreshes the monthly data the FOMC reacts to (table `macro`), shown as charts of
actual vs expected:

- **CPI, core CPI, PCE and core PCE** come from the Cleveland Fed's inflation-nowcasting file. It
  gives each month's actual figure and its release date. "Expected" is the nowcast just before
  release.
- **Payrolls, unemployment and hourly earnings** come from the BLS public API (no key needed).
  There's no free consensus forecast, so "expected" is the 3-month trend (for unemployment, the
  previous month). These figures are as revised today, and release dates follow the BLS rule.

Bars are coloured by surprise: hotter or stronger than expected = hawkish, cooler or weaker = dovish.

Items are tagged:

- `speech`
- `statement` (a written statement about an FOMC vote)
- `essay`
- `no_text` (listed, but the page has no transcript, e.g. Kashkari's video events)

Only `speech` counts toward the speech totals.

Storage: `data/fed.db` (SQLite) and `data/cache/` (raw HTML). Requests are spaced ~1 s apart.
Speech URLs already stored are skipped, so later Loads only fetch new items.

## Analysis tab

Press **Run analysis** after a Load. Under the implied move, a collapsed **How the score is worked out**
box explains the method in brief, with the current weights from the config. The tab is separate from Load. It only *reads* `data/fed.db`
and keeps its own results in `data/analysis.db`.

### Set-up

- Put your Gemini API key in `.env` as `GEMINI_API_KEY=...`. The file is git-ignored, and the key is
  read from there only. It is never printed or exported.
- Every setting lives in `analysis/config.toml`: provider, default model and model-picker list,
  per-model daily call caps, prompt versions, source weights, vote scores, recency weights and the
  prefilter keywords.
- Default model: `gemini-3.5-flash-lite` (500 free calls/day). Other models are in the picker:
  - `gemini-3.5-flash` (20 free)
  - `gemini-3.8-flash` (20 free)
  - `gemini-4-hydrogen` (paid only)
  - `gemini-4-neon` (paid only)
- Each model keeps its own scores and readings.
- **Paid password.** Paid-only models (Hydrogen, Neon), or a free model whose free calls for the day
  are used up, need the paid password before **Run analysis** starts. The dialog shows the hint.
  An unlocked run is still capped at 150 calls per model per day (`[paid] daily_cap`). Only a
  SHA-256 hash of the password is stored, in `[paid]` in `config.toml`. On the command line, add
  `--paid` to be asked for it.
- All AI calls go through `analysis/providers/` (`get()` → `generate_json`). To switch to Claude,
  fill in `providers/claude.py` and set `provider = "claude"`.

### What a run does

1. **Policy context (no AI).** Takes the target range, last decision and next meeting from `fed.db`
   and the FOMC calendar. Every document is judged against the rate in force on *its own* date.
2. **Speaker extraction.** This step is for Q&A or panel transcripts. It isn't built, because none
   are collected yet.
3. **Score each document (AI, one call each).** The prompt is `analysis/prompts/score_v1.md`. The
   reply is a JSON object with these fields:
   - `stance`: −5 to +5, relative to the current rate
   - `next_meeting_call`: hike / hold / cut probabilities
   - `policy_relevance`
   - `confidence`
   - `mandate_balance`
   - `sub_views`
   - 2–3 verbatim `evidence` quotes
   - a one-line `summary`

   Every reply is validated in code: values must be in range, probabilities must sum to 1, and
   each quote must appear word for word in the text. An invalid reply gets one retry. Results are
   cached per (document, model, prompt version). Speeches that barely mention policy are skipped
   without a call.
4. **Votes (no AI).** Agree = 0. A dissent for a tighter rate = +4, for a looser rate = −4. A
   dissent about the statement's wording only = ±3.
5. **Combine (no AI).**
   - **Member stance**: the weighted average over the current window (since the last decision) and
     the two windows before it, at recency weights 1.0 / 0.5 / 0.25. A document's weight is
     source × relevance × confidence × recency. Agreeing votes count at 0.3.
   - **Carry-over**: a member silent through all three windows has their older score carried over.
   - **Implied move**, Bloomberg WIRP-style: hike probability − cut probability, as a share of a
     25bp move. +100% = a 25bp hike fully expected, 0 = hold, −100% = a 25bp cut. The
     probabilities are the expected decision described below.
   - The reading also gives how the members line up (own views, plus those with no current view),
     the **spread** (std dev of stances) and a **meeting-by-meeting path**. The path shows the
     implied move going into each meeting next to what actually happened.
6. **Summary (AI).** A short read of the final numbers (`prompts/summary_v3.md`). It explains
   the numbers and never changes them.

**Data-dependent statements.** The scoring prompt (`score_v3.md`) also captures conditions such as
"if the August data show the improvement was fleeting, it may be appropriate to raise the rate in
September": the indicator, direction, any threshold, the data month and the action. Each run checks
them against the released data. A condition that names a month is judged on that month. Otherwise
it's judged on the latest release, against the threshold or what was expected. A met condition sets
that member's call. A condition on an indicator the data doesn't cover gets one small AI check.

**Expected decision.** This is the average hike / hold / cut odds of the members with a current view:
a recent policy speech, a resolved condition, or a rate dissent at the last meeting. Members with no
current view are assumed to vote with the committee, as members almost always do.

A member's call for the next meeting comes from their latest policy document. These cases default
to hold, or follow the dissent, and are labelled in the table:

| Situation | Call | Label |
|---|---|---|
| Data condition resolved by released data | the stated action | "condition met" / "not met" |
| No current view (no call, or from before the latest decision) | the expected decision | "follows committee" |
| Tie | hold | — |
| Rate dissent at the latest decision, nothing newer | the dissent's direction | "from dissent" |

**Snapshot.** Members stop speaking at the blackout, but data keeps coming out. Any run between the
blackout start and the meeting is also saved as "going into the meeting", and the latest such run
is the one kept. The path chart rebuilds every past meeting as of the day before it: speeches up to
the blackout, data up to that day.

**Daily caps.** A run stops cleanly at a model's daily cap, and the next run carries on where it
left off. Caps reset at midnight Pacific (08:00 UK).

### Command line

```
python3 -m analysis.run [--model M] [--as-of YYYY-MM-DD] [--limit N] [--no-summary] [--paid]
python3 -m analysis.checks score URL ...          # score documents and print the full JSON
python3 -m analysis.checks consistency URL ...    # score each 3 more times, report the spread
```

`--as-of` rebuilds a past reading (a backtest). For example, `--as-of 2026-10-16` gives the reading
going into the 27–28 Oct 2026 meeting.

### Test results so far (Flash-Lite, prompt v3)

- **Consistency:** repeat scores varied by 0–0.5 points (target: within 1).
- **Backtest, Jun–Oct 2026, as of the day before each meeting:**
  - The expected decision was right at all 4 meetings, including the unanimous September hike
    (75% hike).
  - Member calls were 40 of 47 right.
  - October was a near coin-flip (49% hold).
  - The rules were designed with these meetings in view, so treat this as encouraging, not proven.

### Methodology for other tools

`FOMC_hawkishness_skill.txt` describes the whole method, prompts and rules in plain text, for
another AI to run on already-collected data.
