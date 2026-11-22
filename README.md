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

Items are tagged:

- `speech`
- `statement` (a written statement about an FOMC vote)
- `essay`
- `no_text` (listed, but the page has no transcript, e.g. Kashkari's video events)

Only `speech` counts toward the speech totals.

Storage: `data/fed.db` (SQLite) and `data/cache/` (raw HTML). Requests are spaced ~1 s apart.
Speech URLs already stored are skipped, so later Loads only fetch new items.

## Analysis tab

Press **Run analysis** after a Load. The tab is separate from Load. It only *reads* `data/fed.db`
and keeps its own results in `data/analysis.db`.

### Set-up

- Put your Gemini API key in `.env` as `GEMINI_API_KEY=...`. The file is git-ignored, and the key is
  read from there only. It is never printed or exported.
- Every setting lives in `analysis/config.toml`: provider, default model and model-picker list,
  per-model daily call caps, prompt versions, source weights, vote scores, recency weights and the
  prefilter keywords.
- Default model: `gemini-3.5-flash-lite` (cap 500 calls/day). Other models are in the picker:
  - `gemini-3.5-flash` (cap 20)
  - `gemini-3.8-flash` (cap 20)
  - `gemini-4-hydrogen` (cap 0, blocked until paid credits are approved)
  - `gemini-4-neon` (cap 0, blocked until paid credits are approved)
- Each model keeps its own scores and readings.
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
   - **Fed gauge** = average stance of the 12 voters + 5 (0–10). The reading also gives the change
     vs the previous window, the hike/hold/cut **tally**, the **spread** (std dev of stances) and a
     **6-month path**.
6. **Summary (AI).** A 4-sentence read of the final numbers (`prompts/summary_v2.md`). It explains
   the numbers and never changes them.

A member's call for the next meeting comes from their latest policy document. These cases default
to hold, or follow the dissent, and are labelled in the table:

| Situation | Call | Label |
|---|---|---|
| No call | hold | "no call" |
| Call from before the latest decision | hold | "out of date" |
| Tie | hold | — |
| Rate dissent at the latest decision, nothing newer | the dissent's direction | "from dissent" |

**Snapshot.** When Run analysis is pressed on or after the blackout start (the second Saturday
before the meeting), the reading is also saved as "going into the meeting". Nothing runs on a
schedule, so press it once during the blackout.

**Daily caps.** A run stops cleanly at a model's daily cap, and the next run carries on where it
left off. Caps reset at midnight Pacific (08:00 UK).

### Command line

```
python3 -m analysis.run [--model M] [--as-of YYYY-MM-DD] [--limit N] [--no-summary]
python3 -m analysis.checks score URL ...          # score documents and print the full JSON
python3 -m analysis.checks consistency URL ...    # score each 3 more times, report the spread
```

`--as-of` rebuilds a past reading (a backtest). For example, `--as-of 2026-10-16` gives the reading
going into the 27–28 Oct 2026 meeting.

### Test results so far (Oct 2026 meeting: 10–2 hold, Cook and Hammack dissented for a hike)

- **Consistency:** repeat scores varied by 0–0.5 points (target: within 1).
- **Backtest of the member calls:** Hydrogen got 9/12, including both dissenters. Flash-Lite got
  6/12 and missed both, so treat its tally as rough. Its stances and gauge are close to Hydrogen's.

### Methodology for other tools

`FOMC_hawkishness_skill.txt` describes the whole method, prompts and rules in plain text, for
another AI to run on already-collected data.
