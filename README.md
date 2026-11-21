# FOMC voters — 2026

Local web app that collects Federal Reserve FOMC votes and speeches year to date.

```
pip install -r requirements.txt
python3 server.py              # opens http://127.0.0.1:8765 ; pick YTD / 1y / 6m / 3m, press Load
python3 server.py --load 3m    # same load, headless (window defaults to 1y)
python3 verify.py 1y           # checks votes, decisions, governor counts, spot-checks 3 speeches
```

The window picker sets both what a Load fetches (only items dated inside the window) and what the
page shows. Everything loaded is kept in `data/fed.db`, so reopening the app shows the last results
straight away, with the last load's log and how long each load took under **Log**.

## Where the data comes from

- **Voters**: every 2026 statement linked from the FOMC calendar. Since June the statements only
  name dissenters ("approved by a 10–2 vote"), so the "Voting for" list comes from the meeting
  **minutes**. If a meeting has no minutes yet, its for-votes are carried over from the previous
  meeting and marked *provisional* until the minutes appear. Dissent wording always comes from the
  statement.
- **People** are matched by a fixed id (`waller`, `williams`, …) via the exact printed names in
  `fedwatch/people.py`; an unknown name is reported, never fuzzy-matched.
- **Speeches**
  - Governors: `federalreserve.gov/newsevents/2026-speeches.htm` (speaker = URL prefix)
  - Williams: `newyorkfed.org/newsevents/speeches/index` ("Williams:" rows)
  - Hammack: `clevelandfed.org/collections/speeches` (+ its paging JSON)
  - Paulson: `philadelphiafed.org/the-economy/speeches-anna-paulson`
  - Logan: `dallasfed.org/news/speeches/logan`
  - Kashkari: `minneapolisfed.org/people/neel-kashkari` (speeches and written essays)

Items are tagged `speech`, `statement` (a written statement about an FOMC vote), `essay`, or
`no_text` (listed, but the page has no transcript — e.g. Kashkari's video events). Only `speech`
counts toward "speeches YTD".

Storage: `data/fed.db` (SQLite) and `data/cache/` (raw HTML). Requests are spaced ~1 s apart;
speech URLs already stored are skipped, so later Loads only fetch new items.
