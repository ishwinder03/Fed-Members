# Analysis stage: proposal for review

Nothing below is built yet. This file proposes the tables, the config and the scoring prompt.

## Layout

```
analysis/
  config.toml          every setting: provider, model, prompt version, weights, vote scores, limits
  providers/base.py    Provider interface: generate_json(system, user, schema, media=None) -> (dict, usage)
  providers/gemini.py  google-genai SDK; throttle, 429 backoff, daily-quota stop
  providers/claude.py  same interface, filled in later
  context.py           Step 1: policy context as of a date (no AI)
  extract.py           Step 2: speaker extraction (AI)
  score.py             Step 3: document scoring (AI) + validation
  votes.py             Step 4: vote scores (no AI)
  combine.py           Step 5: gauge, tally, spread, carry-over, path, snapshots (no AI)
  summarise.py         Step 6: AI read of the final numbers
  prompts/score_v1.md, extract_v1.md, summary_v1.md
  run.py               python3 -m analysis.run [--as-of YYYY-MM-DD] [--check N]
data/analysis.db       separate SQLite file
```

- The collector database `data/fed.db` is opened **read-only** (`file:…?mode=ro`). Nothing in `fedwatch/` changes.
- The server gets new routes: `/api/analysis` and `POST /api/analyse`. The page gets an **Analysis** tab and its own **Run analysis** button, separate from **Load**.
- The key comes from `.env` via python-dotenv and is passed straight to the SDK client. It is never logged or put in `os.environ` beyond this process.

## Tables (data/analysis.db)

| table | key | columns |
|---|---|---|
| `documents` | `doc_id` (`speech:<url>`, `video:<url>`, `vote:<meeting>:<person>`) | person_id, date, doc_type (`vote`, `statement`, `essay`, `speech`, `qa`, `panel`), title, url, text_hash, source_weight. Rebuilt from fed.db on each run. |
| `extractions` | doc_id, model, prompt_version, chunk | start_s, end_s, format (`qa` or `panel`), kept_json [{start, end, text}], uncertain_json [{start, end, text, why}], created_at |
| `scores` | doc_id, model, prompt_version, trial | stance, p_hike, p_hold, p_cut, policy_relevance, confidence, mandate_balance, mandate_reason, sub_views_json, evidence_json, summary, context_json, raw_json, validation_notes, scored_at |
| `ai_calls` | id | run_id, purpose (`extract`, `score`, `summary`, `test`), doc_id, model, prompt_version, status (`ok`, `429`, `invalid`, `error`), attempt, tokens_in, tokens_out, latency_s, at. Used for "calls on last run" and for daily quota counting. |
| `runs` | id | started_at, finished_at, provider, model, prompt_version, as_of, calls, failures, ok, log |
| `readings` | id | run_id, as_of, label (`live`, `going into the meeting`, `backtest`), next_meeting, window_start, window_end, gauge, gauge_prev, spread, tally_json, members_json, path_json, summary_text |

- `trial` is 0 for normal scores. The consistency check uses trials 1–3 so normal results aren't overwritten.
- Votes are computed and not stored in `scores`. They appear as `vote:` documents with stance taken from config.
- Resume: every successful call is committed at once. A rerun skips anything already in `extractions` or `scores` for the current model and prompt version, so a run cut short by the daily quota carries on the next day.

## Config (analysis/config.toml, draft)

```toml
provider = "gemini"
model = "gemini-4-hydrogen"    # picker also offers gemini-3.8-flash and gemini-4-neon
prompt_version = "score-v1"
extract_prompt_version = "extract-v1"
temperature = 0

[limits]
requests_per_minute = 5        # free tier reports ~5–6 RPM, ~20 RPD for Flash
requests_per_day = 20          # stop cleanly at this; resume next day (resets midnight Pacific)
max_retries = 5                # on 429: wait for retry-after if given, else 15s, 30s, 60s… (with jitter)

[source_weights]
vote = 1.0
statement = 1.0                # dissent statement
essay = 1.0
speech = 0.8                   # prepared speech
qa = 0.6                       # one-on-one Q&A
panel = 0.4                    # panel / news

[vote_scores]                  # relative to the meeting's decision
agree = 0
dissent_tighter_rate = 4       # wanted a hike, or a hold when the majority cut (Goolsbee/Schmid Dec 2025)
dissent_looser_rate = -4       # wanted a cut, or a smaller hike
dissent_tighter_wording = 3    # (changed from 2 after review)
dissent_looser_wording = -3

[combine]
blackout_days = 10
path_months = 6
```

## Step 1: policy context (no AI)

`context.as_of(date)` comes from fed.db plus the FOMC calendar page. It gives the target range and last decision from the latest meeting on or before the date, plus the next meeting date. Each document is scored with the context **as of its own date**, so a July speech is judged against July's rate and the backtest works. The context goes into `context_json`.

## Step 2: speaker extraction

The collector has **no Q&A or panel transcripts**. Every stored text is a prepared speech, essay or statement. Kashkari's 10 events are video only (4 of them in the last 6 months). The one way I see to run this step is to give Gemini the event's **YouTube URL** directly. Gemini hears the audio, so it can tell voices apart, which captions alone couldn't.

- Each video is split into 20-minute clips. A clip is about 100 tokens per second at low resolution, so about 120k tokens, which fits the free-tier per-minute token limit.
- Each clip returns Kashkari's passages with start and end timestamps, plus an `uncertain` list. Uncertain passages are stored and shown but never scored.
- The free tier allows up to 8 hours of YouTube video a day, and each clip is one request against the ~20 a day.

## Step 3: scoring prompt (prompts/score_v1.md, draft)

**System:**

> You rate the monetary-policy stance of one FOMC participant from one document.
>
> **The mandate.** The Federal Reserve's dual mandate is maximum employment and stable prices. Price stability means 2% inflation over the longer run, measured by the PCE price index. A member's stance reflects which side of the mandate they treat as the bigger risk and what policy that implies. Concern that inflation stays above 2% is hawkish (keep rates higher or raise them). Concern that the labour market is weakening is dovish (lower rates). Judge the balance of risks the member describes, not just which topics they mention.
>
> **Stance is relative to the current policy rate given in POLICY CONTEXT**, not to a neutral rate or to history:
>
> | score | meaning | example of the kind of language |
> |---|---|---|
> | +5 | wants bigger or faster hikes than a single 25bps move | "a 50bps move would be appropriate"; "we are behind the curve and must act forcefully" |
> | +4 | wants a hike at the next meeting | "I would support raising the rate at our next meeting" |
> | +3 | leans toward another hike soon; tightening bias | "further firming may well be needed"; "I am not convinced we are done" |
> | +2 | hold, but inflation is clearly the bigger risk; would resist cuts | "policy needs to stay restrictive for some time"; "cuts are not on the table" |
> | +1 | hold, mild hawkish tilt | "I want to see more progress on inflation before considering any change" |
> | 0 | comfortable holding, risks balanced, no bias | "policy is well positioned"; "we can wait and see" |
> | −1 | hold, mild dovish tilt | "I'm watching the softening in hiring closely" |
> | −2 | hold now, expects cuts; employment risk is bigger | "cuts would likely be appropriate later this year" |
> | −3 | open to a cut soon | "a cut could be appropriate in the coming meetings" |
> | −4 | wants a cut at the next meeting | "I would support lowering the rate at our next meeting" |
> | −5 | wants big or fast cuts (50bps or a series) | "we should move quickly to bring the rate down" |
>
> Half points (e.g. +1.5) are allowed.
>
> **Rules**
> 1. Rate only views the speaker states as their own. Ignore questions put to them, other people's views they describe, and staff or market forecasts they don't endorse.
> 2. If the document has no monetary-policy content (e.g. payments, regulation, history, research), set policy_relevance near 0, stance 0 and confidence low. Don't infer a stance from the speaker's reputation or past views.
> 3. Standard disclaimers ("my views are my own", "data dependent") are not evidence for either side.
> 4. next_meeting_call is the probability the speaker would favour each action at the NEXT MEETING in the context. It must be consistent with the stance; e.g. a stance of +4 implies hike is the most likely call.
> 5. mandate_balance runs from −1 (worried only about employment) to +1 (worried only about inflation), with a one-line reason.
> 6. evidence: 2–3 quotes copied exactly from the text, each under 40 words, with the document date (or the timestamp for video passages). Pick the quotes that most determine the stance.
> 7. Reply only in the JSON schema.

**User message:** POLICY CONTEXT (target range, last decision and date, next meeting date), DOCUMENT (speaker, role, date, type, title, URL), then TEXT (or the kept passages with timestamps).

**JSON schema** (sent as Gemini `response_json_schema`):

```json
{
  "stance": "number -5..5",
  "next_meeting_call": {"hike": "0..1", "hold": "0..1", "cut": "0..1"},
  "policy_relevance": "0..1",
  "confidence": "0..1",
  "mandate_balance": "-1..1",
  "mandate_reason": "string, one line",
  "sub_views": {"inflation": "string", "labour_market": "string", "preferred_path": "string", "urgency": "string"},
  "evidence": [{"quote": "string", "date": "YYYY-MM-DD", "timestamp": "string or null"}],
  "summary": "string, one line"
}
```

**Validation, done in code after each reply:**
- Every value must be in its range.
- Probabilities summing to within 0.02 of 1 are renormalised; otherwise the call is retried once.
- Each quote must appear verbatim in the text (after normalising whitespace and quote marks). Quotes that don't are dropped and noted. Fewer than 2 valid quotes means one retry.
- A stance that contradicts the call (e.g. ≥ +3 with cut as the top probability) is flagged, not changed.

## Step 5: definitions I'll use

- **Window:** from the last decision date (inclusive, so that meeting's votes count) to the as-of date. The previous window runs from the decision before that up to the last decision. That window gives the "change vs previous window" figure and the carry-over scores.
- **Blackout snapshot:** the second Saturday before the meeting's first day, the Fed's actual rule. That is about 10 days before, and `blackout_days` is the fallback. For Oct 27–28 it is Oct 17. For the December meeting it is about Nov 28.
- **Path:** month-end stance per member and for the Fed, each using all documents dated in that month.

## Call budget on the free tier (~20 requests a day)

| task | calls |
|---|---|
| checks 1–5 | about 1 + 2–3 + 5 + 9 + 21 (Sep 16–Oct 27 documents) ≈ 40 |
| all 6 months of the 12 voters | 66 speeches + 2 statements or essays + 4 Kashkari videos (about 10 clips) ≈ 78 |
| summary | 1 per run |

That's about 6 days of free quota in total, mostly reused across the checks. Two ways to cut it:

- **(a)** A no-AI pre-filter. Speeches that never mention inflation, employment, the policy rate or monetary policy (e.g. Barr on AI, Hammack on stablecoins) get relevance 0 without a call. This probably saves 15–25 calls.
- **(b)** Enable billing on the Google project. The whole job is roughly 0.5M input tokens, so the cost should be small; check the current price in AI Studio.
