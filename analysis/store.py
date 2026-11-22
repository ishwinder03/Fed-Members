"""data/analysis.db (analysis results) and a read-only handle on the collector's data/fed.db."""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from analysis.settings import ANALYSIS_DB, COLLECTOR_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
    doc_id TEXT,                      -- speech:<url>
    model TEXT,
    prompt_version TEXT,
    trial INTEGER DEFAULT 0,          -- 0 = the score used; 1-3 = consistency-check repeats
    person_id TEXT,
    date TEXT,
    stance REAL,
    p_hike REAL, p_hold REAL, p_cut REAL,
    policy_relevance REAL,
    confidence REAL,
    mandate_balance REAL,
    mandate_reason TEXT,
    sub_views_json TEXT,
    evidence_json TEXT,               -- [{quote, date, timestamp}] verified verbatim
    summary TEXT,
    context_json TEXT,                -- policy context sent with the call
    raw_json TEXT,                    -- reply as received
    validation_notes TEXT,
    prefiltered INTEGER DEFAULT 0,    -- 1 = no monetary-policy content, scored without AI
    scored_at TEXT,
    PRIMARY KEY (doc_id, model, prompt_version, trial)
);
CREATE TABLE IF NOT EXISTS extractions (  -- step 2: speaker passages from Q&A / panel transcripts
    doc_id TEXT, model TEXT, prompt_version TEXT, chunk INTEGER,
    format TEXT, kept_json TEXT, uncertain_json TEXT, created_at TEXT,
    PRIMARY KEY (doc_id, model, prompt_version, chunk)
);
CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    purpose TEXT,                     -- score | summary | test
    doc_id TEXT,
    model TEXT,
    prompt_version TEXT,
    status TEXT,                      -- ok | invalid | quota | error
    tokens_in INTEGER, tokens_out INTEGER,
    latency_s REAL,
    error TEXT,
    at TEXT,
    pacific_day TEXT                  -- the free-tier daily quota resets at midnight Pacific
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, finished_at TEXT,
    provider TEXT, model TEXT, prompt_version TEXT,
    as_of TEXT,
    calls INTEGER, scored INTEGER, failures INTEGER, pending INTEGER,
    duration_s REAL,
    ok INTEGER,
    log TEXT
);
CREATE TABLE IF NOT EXISTS condition_ai (  -- AI fallback verdicts for conditions on indicators not in the data
    key TEXT PRIMARY KEY, result_json TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    model TEXT, prompt_version TEXT,
    as_of TEXT,
    label TEXT,                       -- live | going into the meeting | backtest
    next_meeting TEXT,
    data_json TEXT,                   -- gauge, change, tally, spread, members, path, context
    summary_text TEXT,
    summary_key TEXT,                 -- hash of the numbers the summary was written from
    created_at TEXT
);
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def pacific_day():
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


MIGRATIONS = {"scores": {"conditions_json": "TEXT"}}  # columns added after the first version


def connect():
    ANALYSIS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ANALYSIS_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    conn.commit()
    return conn


def collector():
    """The collector's database, read-only: analysis never writes to it."""
    conn = sqlite3.connect(f"file:{COLLECTOR_DB}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def calls_today(conn, model):
    return conn.execute("SELECT COUNT(*) FROM ai_calls WHERE model=? AND pacific_day=? AND status!='quota'",
                        (model, pacific_day())).fetchone()[0]
