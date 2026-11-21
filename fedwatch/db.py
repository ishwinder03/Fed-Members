import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    date TEXT PRIMARY KEY,            -- decision day, YYYY-MM-DD
    statement_url TEXT,
    minutes_url TEXT,
    tally_for INTEGER,
    tally_against INTEGER,
    roster_source TEXT,               -- statement | minutes | provisional
    check_ok INTEGER,
    check_notes TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS votes (
    meeting_date TEXT,
    person_id TEXT,
    printed_name TEXT,
    vote TEXT,                        -- for | against
    dissent_text TEXT,                -- e.g. "preferred to lower the target range ..."
    PRIMARY KEY (meeting_date, person_id)
);
CREATE TABLE IF NOT EXISTS roles (
    person_id TEXT PRIMARY KEY,
    title TEXT,                       -- e.g. "Governor", "Vice Chair for Supervision"
    fomc_role TEXT                    -- Chair | Vice Chair | NULL
);
CREATE TABLE IF NOT EXISTS speeches (
    url TEXT PRIMARY KEY,
    person_id TEXT,
    date TEXT,
    title TEXT,
    kind TEXT,                        -- speech | statement | essay | no_text
    source TEXT,
    text TEXT,
    text_chars INTEGER,
    speaker_verified INTEGER,
    cache_file TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT,
    message TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS loads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    new_speeches INTEGER,
    requests INTEGER,
    ok INTEGER
);
"""


# columns added after the first version; created on older databases at startup
MIGRATIONS = {
    "meetings": {"decision": "TEXT", "decision_bps": "INTEGER", "target_range": "TEXT"},
    "loads": {"window": "TEXT", "cutoff": "TEXT", "duration_s": "REAL", "log": "TEXT"},
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
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
