"""HTTP handlers for the Analysis tab (called from server.py)."""
import json
import threading
import time
from datetime import date

from analysis import combine, run as runner
from analysis.settings import CONFIG, daily_cap, score_models
from analysis.store import calls_today, collector, connect

state = {"running": False, "log": [], "model": None, "started": None, "elapsed": None}


def _run(model):
    def log(line):
        state["log"].append(line)
        print(line, flush=True)
    state.update(running=True, log=[], model=model, started=time.time(), elapsed=None)
    try:
        runner.run(model=model, log=log, log_lines=state["log"])
    except Exception as e:
        log(f"Analysis failed: {e}")
    finally:
        state["elapsed"] = time.time() - state["started"]
        state["running"] = False


def start(model):
    model = model if model in CONFIG["models"] else CONFIG["model"]
    if not state["running"]:
        threading.Thread(target=_run, args=(model,), daemon=True).start()
    return {"started": True, "model": model}


def _reading(conn, model, label, next_meeting=None):
    sql = "SELECT * FROM readings WHERE model=? AND prompt_version=? AND label=?"
    args = [model, CONFIG["prompt_version"], label]
    if next_meeting:
        sql += " AND next_meeting=?"
        args.append(next_meeting)
    r = conn.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()
    if not r:
        return None
    return {**json.loads(r["data_json"]), "summary_text": r["summary_text"], "created_at": r["created_at"],
            "label": r["label"]}


def overview(model):
    conn = connect()
    live = _reading(conn, model, "live")
    snap = _reading(conn, model, "going into the meeting", live and live["context"]["next_meeting"])
    last = conn.execute("SELECT * FROM runs WHERE model=? AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1",
                        (model,)).fetchone()
    s = state
    return {
        "models": CONFIG["models"], "default_model": CONFIG["model"], "model": model,
        "prompt_version": CONFIG["prompt_version"], "provider": CONFIG["provider"],
        "method": {"source_weights": CONFIG["source_weights"], "window_decay": CONFIG["combine"]["window_decay"],
                   "vote_scores": CONFIG["vote_scores"]},
        "reading": live, "snapshot": snap,
        "last_run": dict(last) if last else None,
        "calls_today": calls_today(conn, model), "daily_limit": daily_cap(model),
        "fallback": (lambda fb: {"model": fb, "calls_today": calls_today(conn, fb), "daily_limit": daily_cap(fb)}
                     if fb else None)(score_models(model)[1] if len(score_models(model)) > 1 else None),
        "run": {"running": s["running"], "model": s["model"],
                "elapsed": (time.time() - s["started"]) if s["running"] else s["elapsed"],
                "log": s["log"][-300:] or ((last["log"] or "").splitlines() if last else [])},
    }


def member(model, pid):
    """Every scored document for one member over the path range, newest first."""
    conn, fed = connect(), collector()
    as_of = date.today().isoformat()
    live = _reading(conn, model, "live")
    since = live["path"][0]["month"] + "-01" if live else as_of
    dates = combine.decision_dates(fed, as_of)
    docs = combine._scored(conn, fed, model, [pid], min(since, live["prev_window"][0] if live and live["prev_window"] else since), as_of)
    decay = CONFIG["combine"]["window_decay"]
    for d in docs:  # same recency discount the reading applies
        age = len(dates) - 1 - max(j for j in range(len(dates)) if dates[j] <= d["date"])
        if age < len(decay) and "weight" in d:
            d.update(recency=decay[age], weight=d["weight"] * decay[age])
    return {"window_start": live and live["window_start"], "docs": list(reversed(docs))}


def get(path, args):
    model = args.get("model", [CONFIG["model"]])[0]
    model = model if model in CONFIG["models"] else CONFIG["model"]
    if path == "/api/analysis":
        return overview(model)
    if path.startswith("/api/analysis/member/"):
        return member(model, path.rsplit("/", 1)[1])
    if path == "/api/analyse":
        return overview(model)["run"]
    return None
