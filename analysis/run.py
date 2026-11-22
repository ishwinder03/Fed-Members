"""Analyse:  python3 -m analysis.run [--model M] [--as-of YYYY-MM-DD] [--limit N] [--no-summary]

Scores every unscored document (newest window first), stopping cleanly at the free-tier daily
limit; the next run carries on. Then rebuilds the reading (no AI) and asks for a short summary.
"""
import json
import sys
import time
from datetime import date

from analysis import combine, context, documents, providers, score, summarise
from analysis.providers.base import QuotaExhausted
from analysis.settings import CONFIG, daily_cap
from analysis.store import calls_today, collector, connect, now


def docs_to_score(fed, as_of):
    """The 12 voters' texts over the path range, current window first, then previous, then newest first."""
    people = documents.voters(fed, as_of)
    end = date.fromisoformat(as_of)
    months = CONFIG["combine"]["path_months"]
    y, m = end.year, end.month - (months - 1)
    while m < 1:
        y, m = y - 1, m + 12
    dates = combine.decision_dates(fed, as_of)
    back = len(CONFIG["combine"]["window_decay"]) + 1   # lookback windows, plus one for "change vs previous"
    since = min(date(y, m, 1).isoformat(), dates[max(0, len(dates) - back)])
    docs = documents.texts(fed, people, since, as_of)
    rank = lambda d: (0 if d["date"] >= dates[-1] else 1 if len(dates) > 1 and d["date"] >= dates[-2] else 2)
    docs.sort(key=lambda d: d["date"], reverse=True)
    return sorted(docs, key=rank)  # stable: newest first within each group


def save_reading(conn, run_id, model, as_of, label, r, p, ctx, summary_text, skey):
    conn.execute("DELETE FROM readings WHERE model=? AND prompt_version=? AND label=? AND "
                 "(label='going into the meeting' AND next_meeting=? OR label!='going into the meeting' AND as_of=?)",
                 (model, CONFIG["prompt_version"], label, ctx["next_meeting"], as_of))
    conn.execute("INSERT INTO readings (run_id, model, prompt_version, as_of, label, next_meeting, data_json, "
                 "summary_text, summary_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (run_id, model, CONFIG["prompt_version"], as_of, label, ctx["next_meeting"],
                  json.dumps({**r, "path": p, "context": ctx}), summary_text, skey, now()))
    conn.commit()


def fallback(conn, provider, log):
    """When the default model reaches its daily cap, carry on with the fallback model (if it has calls left)."""
    fb = CONFIG.get("fallback_model")
    if provider.model != CONFIG["model"] or not fb or calls_today(conn, fb) >= daily_cap(fb):
        return None
    log(f"Switching to the fallback model {fb} for the rest of this run.")
    return providers.get(fb, log)


def build_reading(conn, fed, model, provider, run_id, as_of, label, want_summary, log):
    """`model` names the reading; `provider` (maybe the fallback) makes the summary call."""
    r = combine.reading(conn, fed, model, as_of)
    p = combine.path(conn, fed, model, as_of)
    ctx = context.as_of(fed, as_of)
    facts = summarise.facts(r, ctx)
    skey = summarise.key(facts, model)
    old = conn.execute("SELECT summary_text FROM readings WHERE summary_key=? AND summary_text IS NOT NULL "
                       "ORDER BY id DESC LIMIT 1", (skey,)).fetchone()
    text = old[0] if old else None
    if text is None and want_summary:
        try:
            try:
                text = summarise.summarise(conn, provider, facts, run_id)
            except QuotaExhausted:
                fb = fallback(conn, provider, log)
                if not fb:
                    raise
                text = summarise.summarise(conn, fb, facts, run_id)
            log("Summary written.")
        except QuotaExhausted as e:
            log(f"Summary skipped: {e}")
        except Exception as e:
            log(f"Summary failed: {e}")
    save_reading(conn, run_id, model, as_of, label, r, p, ctx, text, skey)
    return r


def run(model=None, as_of=None, label=None, limit=None, want_summary=True, log=print, log_lines=None):
    t0 = time.time()
    conn, fed = connect(), collector()
    model = model or CONFIG["model"]
    provider = providers.get(model, log)
    live = as_of is None
    as_of = as_of or date.today().isoformat()
    label = label or ("live" if live else "backtest")
    cur = conn.execute("INSERT INTO runs (started_at, provider, model, prompt_version, as_of) VALUES (?,?,?,?,?)",
                       (now(), provider.name, provider.model, CONFIG["prompt_version"], as_of))
    run_id = cur.lastrowid
    conn.commit()
    log(f"Analysis with {model}, prompt {CONFIG['prompt_version']}, as of {as_of}")
    scored = failures = skipped = 0
    stopped = None
    todo = [d for d in docs_to_score(fed, as_of) if not score.is_scored(conn, d["doc_id"], model)]
    log(f"{len(todo)} documents not yet scored by this model and prompt version")
    for d in todo:
        if limit is not None and scored >= limit:
            break
        if score.prefilter(conn, d, model):
            skipped += 1
            log(f"  skip (no policy content)  {d['date']} {d['person_id']:<9} {d['title'][:60]}")
            continue
        try:
            try:
                s = score.score(conn, fed, provider, d, run_id, log=log)
            except QuotaExhausted as e:
                fb = fallback(conn, provider, log)
                if not fb:
                    raise
                log(f"  {e}")
                provider = fb
                s = score.score(conn, fed, provider, d, run_id, log=log)
            scored += 1
            tag = "" if provider.model == model else f"  [{provider.model}]"
            log(f"  {s['stance']:+.1f}  rel {s['policy_relevance']:.1f}  {d['date']} {d['person_id']:<9} {d['title'][:60]}{tag}")
        except QuotaExhausted as e:
            stopped = str(e)
            log(f"Stopped: {e}. Run again later to carry on.")
            break
        except Exception as e:
            failures += 1
            log(f"  FAILED {d['date']} {d['person_id']} {d['title'][:50]}: {str(e)[:200]}")
    pending = len(todo) - scored - skipped - failures
    r = build_reading(conn, fed, model, provider, run_id, as_of, label, want_summary and not stopped, log)
    if live:
        ctx = context.as_of(fed, as_of)
        if ctx["blackout_start"] and as_of >= ctx["blackout_start"]:
            build_reading(conn, fed, model, provider, run_id, ctx["blackout_start"], "going into the meeting", False, log)
            log(f"Snapshot saved: going into the {ctx['next_meeting']} meeting")
    g = r["gauge"]
    log(f"Gauge {g * 10:.0f}%" if g is not None else "Gauge: not enough scored documents yet")
    calls = conn.execute("SELECT COUNT(*) FROM ai_calls WHERE run_id=?", (run_id,)).fetchone()[0]
    dur = time.time() - t0
    log(f"Done in {dur:.0f}s: {scored} scored, {skipped} skipped by prefilter, {failures} failed, "
        f"{pending} still to do, {calls} AI calls.")
    conn.execute("UPDATE runs SET finished_at=?, calls=?, scored=?, failures=?, pending=?, duration_s=?, ok=?, log=? "
                 "WHERE id=?", (now(), calls, scored, failures, pending, dur, int(failures == 0),
                                "\n".join(log_lines or []), run_id))
    conn.commit()
    return r


if __name__ == "__main__":
    a = sys.argv[1:]
    opt = lambda k: a[a.index(k) + 1] if k in a else None
    run(model=opt("--model"), as_of=opt("--as-of"), limit=int(opt("--limit")) if opt("--limit") else None,
        want_summary="--no-summary" not in a)
