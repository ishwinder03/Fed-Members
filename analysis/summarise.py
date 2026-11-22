"""Step 6: a 3-4 sentence AI read of the final numbers. It explains them; it never changes them."""
import hashlib
import json
import time

from analysis.settings import CONFIG, daily_cap, prompt
from analysis.store import calls_today, now, pacific_day
from analysis.providers.base import QuotaExhausted

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}


def facts(r, ctx):
    """The numbers and top quotes sent to the model, rounded the way the page shows them."""
    f = lambda x: None if x is None else round(x, 1)
    return {
        "policy_context": ctx["text"],
        "window": f"{r['window_start']} to {r['window_end']}",
        "gauge_out_of_10": f(r["gauge"]), "gauge_previous_window": f(r["gauge_prev"]),
        "gauge_change": f(r["gauge_change"]), "spread_std_dev": f(r["spread"]),
        "next_meeting_tally": {k: v for k, v in r["tally"].items() if v},
        "members": [{
            "name": m["name"], "stance": f(m["stance"]), "previous_window_stance": f(m["prev_stance"]),
            "change": f(m["change"]), "carried_over": m["carried_over"],
            "next_meeting_call": m["call_label"],
            "call_probability": f(m["call_prob"]),
            "call_note": m["call_note"],
            "latest_quote": m["latest_quote"] and f"{m['latest_quote']['quote']} ({m['latest_quote']['date']})",
        } for m in r["members"]],
    }


def garbled_names(text, facts_):
    """Members whose first name (and initial) appears without their surname following it."""
    bad = []
    for m in facts_["members"]:
        parts = m["name"].split()
        lead = " ".join(parts[:-1])
        if text.count(lead) > text.count(m["name"]):
            bad.append(m["name"])
    return bad


def key(facts_, model):
    return hashlib.sha1(json.dumps([facts_, model, CONFIG["summary_prompt_version"]], sort_keys=True).encode()).hexdigest()


def summarise(conn, provider, facts_, run_id=None):
    if calls_today(conn, provider.model) >= daily_cap(provider.model):
        raise QuotaExhausted(f"{provider.model}: daily calls used; summary not refreshed")
    t0 = time.time()
    status, usage, text, err = "ok", {}, None, None
    try:
        data, usage = provider.generate_json(prompt(CONFIG["summary_prompt_version"]),
                                             "DATA\n" + json.dumps(facts_, indent=1), SCHEMA, CONFIG["temperature"])
        text = data["summary"].strip()
        bad = garbled_names(text, facts_)
        if bad:  # small models sometimes mangle a name ("Michelle W. Experience"): one retry
            data, usage = provider.generate_json(prompt(CONFIG["summary_prompt_version"]),
                                                 "DATA\n" + json.dumps(facts_, indent=1), SCHEMA, CONFIG["temperature"])
            text = data["summary"].strip()
            if garbled_names(text, facts_):
                text += f" [note: name check failed for {', '.join(bad)}]"
    except QuotaExhausted as e:
        status, err = "quota", str(e)
        raise
    except Exception as e:
        status, err = "error", str(e)
        raise
    finally:
        conn.execute("INSERT INTO ai_calls (run_id, purpose, model, prompt_version, status, tokens_in, tokens_out, "
                     "latency_s, error, at, pacific_day) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (run_id, "summary", provider.model, CONFIG["summary_prompt_version"], status,
                      usage.get("tokens_in"), usage.get("tokens_out"), time.time() - t0, err and err[:500],
                      now(), pacific_day()))
        conn.commit()
    return text
