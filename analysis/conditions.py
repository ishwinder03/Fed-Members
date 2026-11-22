"""Resolve members' data-dependent statements ("if August inflation is hot, I'd hike in September")
against the economic data released after the statement and up to the reading date (no AI, except one
small call for conditions on an indicator the data doesn't cover)."""
import hashlib
import json
import time

from analysis.settings import CONFIG, daily_cap
from analysis.store import calls_today, now, pacific_day

SERIES_FOR = {
    "core_cpi": ["core_cpi"], "cpi": ["cpi"], "core_pce": ["core_pce"], "pce": ["pce"],
    "inflation": ["core_cpi", "cpi", "core_pce"], "payrolls": ["payrolls"], "unemployment": ["unemployment"],
    "wages": ["wages"], "labor_market": ["payrolls", "unemployment"],
}
LABEL = {"cpi": "CPI", "core_cpi": "core CPI", "pce": "PCE", "core_pce": "core PCE", "payrolls": "payrolls",
         "unemployment": "unemployment", "wages": "hourly earnings"}
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt(sid, v):
    return f"{v:+.0f}k" if sid == "payrolls" else f"{v:.1f}%" if sid == "unemployment" else f"{v:.2f}%"


def _hotter(sid, row, threshold, tol):
    """+1 if this release is hotter (more inflation / stronger jobs) than the threshold or what was
    expected, -1 if cooler, 0 if in line."""
    ref = threshold if threshold is not None else row["expected"]
    if ref is None:
        return 0
    d = row["actual"] - ref
    if threshold is None and abs(d) <= tol.get(sid, 0.03):
        return 0
    return (-1 if sid == "unemployment" else 1) * (1 if d > 0 else -1 if d < 0 else 0)


def releases(fed, cond, said_on, as_of):
    """The data releases a condition refers to, known by `as_of`: its named month, or else the latest
    release of each series since the statement ("if inflation comes in hot" is judged on the newest data)."""
    sids = SERIES_FOR.get(cond["indicator"], [])
    if not sids:
        return []
    q = (f"SELECT * FROM macro WHERE series IN ({','.join('?' * len(sids))}) AND actual IS NOT NULL "
         "AND release_date IS NOT NULL AND release_date<=?")
    args = [*sids, as_of]
    if cond.get("data_period"):
        q += " AND period=?"
        args.append(cond["data_period"][:7])
    else:
        q += " AND release_date>?"
        args.append(said_on)
    rows = [dict(r) for r in fed.execute(q + " ORDER BY release_date, series", args)]
    if not cond.get("data_period"):
        latest = {r["series"]: r for r in rows}  # ordered by release date: the last one per series wins
        rows = sorted(latest.values(), key=lambda r: sids.index(r["series"]))
    return rows


def resolve(fed, cond, said_on, as_of):
    """{'status': met | not_met | pending | ai, 'detail': str}"""
    if cond["indicator"] == "other":
        return {"status": "ai", "detail": "indicator not in the data feed"}
    rows = releases(fed, cond, said_on, as_of)
    if not rows:
        what = f"{cond['indicator']} for {cond['data_period']}" if cond.get("data_period") else f"the next {cond['indicator']} data"
        return {"status": "pending", "detail": f"waiting for {what}"}
    tol = CONFIG["conditions"]["tolerance"]
    signs = [_hotter(r["series"], r, cond.get("threshold"), tol) for r in rows]
    want = 1 if cond["direction"] == "hotter" else -1
    hits = sum(s == want for s in signs)
    met = hits * 2 > len(signs) or (hits * 2 == len(signs) and signs[0] == want)  # tie: the first series decides
    parts = []
    for r, s in zip(rows, signs):
        y, m = r["period"].split("-")
        ref = f"threshold {_fmt(r['series'], cond['threshold'])}" if cond.get("threshold") is not None else (
            f"exp. {_fmt(r['series'], r['expected'])}" if r["expected"] is not None else "no expectation")
        parts.append(f"{MON[int(m) - 1]} {LABEL[r['series']]} {_fmt(r['series'], r['actual'])} vs {ref}"
                     f" ({'hotter' if s > 0 else 'cooler' if s < 0 else 'in line'}, out {r['release_date']})")
    return {"status": "met" if met else "not_met", "detail": "; ".join(parts)}


AI_SCHEMA = {"type": "object", "properties": {"status": {"type": "string", "enum": ["met", "not_met", "unclear"]},
                                              "reason": {"type": "string"}}, "required": ["status", "reason"]}


def resolve_with_ai(conn, fed, provider, cond, said_on, as_of):
    """Fallback for indicator 'other': one small call with every release since the statement. Cached;
    without a provider (page views, past readings) only the cache is used."""
    rows = [dict(r) for r in fed.execute("SELECT * FROM macro WHERE actual IS NOT NULL AND release_date>? "
                                         "AND release_date<=? ORDER BY release_date", (said_on, as_of))]
    key = hashlib.sha1(json.dumps([cond, rows]).encode()).hexdigest()
    hit = conn.execute("SELECT result_json FROM condition_ai WHERE key=?", (key,)).fetchone()
    if hit:
        return json.loads(hit[0])
    if not rows:
        return {"status": "pending", "detail": "no data released since the statement"}
    if provider is None:
        return {"status": "pending", "detail": "not checked yet (run the analysis)"}
    if calls_today(conn, provider.model) >= daily_cap(provider.model):
        return {"status": "pending", "detail": "daily call limit reached; not checked"}
    table = "\n".join(f"{r['series']} {r['period']}: actual {r['actual']}, expected {r['expected']} "
                      f"({r['expected_kind']}), released {r['release_date']}" for r in rows)
    t0 = time.time()
    data, usage = provider.generate_json(
        "Decide whether a Federal Reserve official's data-dependent condition has been met by the economic data "
        "released since they stated it. Use only the data given. Answer unclear if the data don't bear on it.",
        f"CONDITION (stated {said_on}): {cond['quote']}\nDirection: {cond['direction']}\n\nDATA RELEASED SINCE\n{table}",
        AI_SCHEMA, CONFIG["temperature"])
    conn.execute("INSERT INTO ai_calls (purpose, model, prompt_version, status, tokens_in, tokens_out, latency_s, at, "
                 "pacific_day) VALUES (?,?,?,?,?,?,?,?,?)", ("condition", provider.model, "condition-v1", "ok",
                 usage.get("tokens_in"), usage.get("tokens_out"), time.time() - t0, now(), pacific_day()))
    res = {"status": data["status"] if data["status"] != "unclear" else "pending", "detail": "AI: " + data["reason"]}
    conn.execute("INSERT OR REPLACE INTO condition_ai VALUES (?,?,?)", (key, json.dumps(res), now()))
    conn.commit()
    return res
