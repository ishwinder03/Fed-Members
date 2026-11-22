"""Step 5 (plain code): member stances, Fed gauge, tally, spread, carry-over and the 6-month path."""
import json
import statistics
from datetime import date

from analysis import documents
from analysis.settings import CONFIG, score_models
from fedwatch.people import display_name

MIN_RELEVANCE_FOR_CALL = 0.5  # a member's call comes from their latest document that is actually about policy


def _scored(conn, fed, model, people, since, until):
    """Every document for `people` dated since..until with its score (votes scored in code)."""
    docs = documents.votes(fed, people, since, until)
    sw = CONFIG["source_weights"]
    for d in docs:
        d["weight"] = sw["vote_agree"] if d["agree"] else sw["vote"]
    models = score_models(model)
    for d in documents.texts(fed, people, since, until):
        r = None
        for m in models:  # the chosen model's score, else the fallback model's
            r = conn.execute("SELECT * FROM scores WHERE doc_id=? AND model=? AND prompt_version=? AND trial=0",
                             (d["doc_id"], m, CONFIG["prompt_version"])).fetchone()
            if r:
                break
        d.pop("text")
        if not r:
            d["pending"] = True
            docs.append(d)
            continue
        d.update(stance=r["stance"], policy_relevance=r["policy_relevance"], confidence=r["confidence"],
                 call={"hike": r["p_hike"], "hold": r["p_hold"], "cut": r["p_cut"]} if r["p_hold"] is not None else None,
                 mandate_balance=r["mandate_balance"], mandate_reason=r["mandate_reason"],
                 sub_views=json.loads(r["sub_views_json"] or "null"), evidence=json.loads(r["evidence_json"] or "[]"),
                 summary=r["summary"], prefiltered=bool(r["prefiltered"]), notes=r["validation_notes"],
                 model=r["model"])
        d["weight"] = sw[d["doc_type"]] * r["policy_relevance"] * r["confidence"]
        docs.append(d)
    return sorted(docs, key=lambda d: (d["date"], d["doc_id"]))


def _stance(docs):
    docs = [d for d in docs if not d.get("pending") and d["weight"] > 0]
    total = sum(d["weight"] for d in docs)
    return sum(d["weight"] * d["stance"] for d in docs) / total if total else None


def _call(docs):
    for d in reversed(docs):
        if d.get("call") and d["policy_relevance"] >= MIN_RELEVANCE_FOR_CALL:
            return {**d["call"], "from": d["doc_id"], "date": d["date"]}
    return None


def call_label(call, latest_decision):
    """(label, probability, note). Hold is the default: no call, an out-of-date call, or a tie."""
    if call is None:
        return "hold", None, "no call: no policy document, so assumed hold"
    if call["date"] < latest_decision:
        return "hold", None, f"out of date: last call ({call['date']}) predates the {latest_decision} decision, so assumed hold"
    label = max(("hold", "hike", "cut"), key=call.get)  # ties go to hold (listed first)
    return label, call[label], None


def decision_dates(fed, until):
    return [r[0] for r in fed.execute("SELECT date FROM meetings WHERE decision IS NOT NULL AND date<=? ORDER BY date",
                                      (until,))]


def member_window(conn, fed, model, pid, dates, i, until, depth=0):
    """Stance and call for one member as of window i (dates[i] .. until).

    Documents from the current window and the windows before it all count, discounted by recency
    (config combine.window_decay, e.g. 1.0 / 0.5 / 0.25). Only when the member has said nothing in
    any of those windows does an older score carry over."""
    decay = CONFIG["combine"]["window_decay"]
    first = max(0, i - len(decay) + 1)
    docs = _scored(conn, fed, model, [pid], dates[first], until)
    for d in docs:
        age = i - max(j for j in range(first, i + 1) if dates[j] <= d["date"])
        d.update(window_age=age, recency=decay[age])
        if "weight" in d:
            d["base_weight"] = d["weight"]
            d["weight"] = d["weight"] * decay[age]
    spoke = [d for d in docs if d["doc_type"] != "vote" and not d.get("pending") and d["weight"] > 0]
    res = {"docs": docs, "stance": _stance(docs), "call": _call(docs), "carried_over": False,
           "silent_now": not any(d["window_age"] == 0 for d in spoke),
           "pending": sum(bool(d.get("pending")) for d in docs)}
    if (not spoke or res["call"] is None) and first > 0 and depth < 4:
        prev_until = date.fromordinal(date.fromisoformat(dates[first]).toordinal() - 1).isoformat()
        prev = member_window(conn, fed, model, pid, dates, first - 1, prev_until, depth + 1)
        if not spoke and prev["stance"] is not None:
            # silent across the whole lookback: the older score carries over, together with any dissent
            # cast since (a dissent is a fresh signal; an agreeing vote adds nothing to the carried score)
            dissents = [d for d in docs if d["doc_type"] == "vote" and d["stance"] != 0]
            carried = {"stance": prev["stance"], "weight": CONFIG["source_weights"]["vote"], "doc_type": "carried"}
            res.update(stance=_stance([carried, *dissents]), carried_over=True,
                       carried_from=prev.get("carried_from", dates[first - 1]))
        if res["call"] is None and prev["call"]:
            res["call"] = {**prev["call"], "carried_over": True}
    return res


def reading(conn, fed, model, as_of):
    """All numbers for the window ending at `as_of` (no AI)."""
    dates = decision_dates(fed, as_of)
    i = len(dates) - 1
    people = documents.voters(fed, as_of)
    members, pending = [], 0
    for pid in people:
        cur = member_window(conn, fed, model, pid, dates, i, as_of)
        prev_end = date.fromordinal(date.fromisoformat(dates[i]).toordinal() - 1).isoformat()
        prev = member_window(conn, fed, model, pid, dates, i - 1, prev_end) if i > 0 else {"stance": None}
        pending += cur["pending"]
        texts = [d for d in cur["docs"] if d["doc_type"] != "vote" and d["window_age"] == 0]
        earlier = [d for d in cur["docs"] if d["doc_type"] != "vote" and d["window_age"] > 0 and not d.get("pending")
                   and d["weight"] > 0]
        latest_quote = next(({"quote": e["quote"], "date": d["date"], "url": d["url"], "title": d["title"]}
                             for d in reversed(cur["docs"]) if d.get("evidence") and d["weight"] > 0
                             and d["policy_relevance"] >= MIN_RELEVANCE_FOR_CALL
                             for e in d["evidence"][:1]), None)
        call = cur["call"]
        label, prob, note = call_label(call, dates[i])
        dissent = next((d for d in cur["docs"] if d["doc_type"] == "vote" and d["date"] == dates[i] and not d["agree"]), None)
        if note and dissent and abs(dissent["stance"]) >= 4:
            # no current call, but they dissented on the rate at the latest decision: that preference stands
            label = "hike" if dissent["stance"] > 0 else "cut"
            note = f"from their dissent at the {dates[i]} decision (no policy speech since)"
        members.append({
            "id": pid, "name": display_name(pid),
            "stance": cur["stance"], "prev_stance": prev["stance"],
            "change": None if cur["stance"] is None or prev["stance"] is None else cur["stance"] - prev["stance"],
            "carried_over": cur["carried_over"], "carried_from": cur.get("carried_from"),
            "silent_now": cur["silent_now"], "n_earlier": len(earlier),
            "call": call, "call_label": label, "call_prob": prob, "call_note": note,
            "n_docs": len(texts), "n_scored": sum(d["weight"] > 0 for d in texts if not d.get("pending")),
            "pending": sum(bool(d.get("pending")) for d in texts), "latest_quote": latest_quote,
        })
    stances = [m["stance"] for m in members if m["stance"] is not None]
    prev_stances = [m["prev_stance"] for m in members if m["prev_stance"] is not None]
    gauge = statistics.mean(stances) + 5 if stances else None
    gauge_prev = statistics.mean(prev_stances) + 5 if prev_stances else None
    tally = {k: sum(m["call_label"] == k for m in members) for k in ("hike", "hold", "cut")}
    tally["none"] = sum(m["call_label"] is None for m in members)
    return {
        "as_of": as_of, "window_start": dates[i], "window_end": as_of,
        "prev_window": [dates[i - 1], dates[i]] if i > 0 else None,
        "gauge": gauge, "gauge_prev": gauge_prev,
        "gauge_change": None if gauge is None or gauge_prev is None else gauge - gauge_prev,
        "spread": statistics.pstdev(stances) if len(stances) > 1 else None,
        "tally": tally, "members": members, "missing_stance": [m["id"] for m in members if m["stance"] is None],
        "pending_docs": pending,
    }


def path(conn, fed, model, as_of):
    """Month-by-month stance per member and for the Fed over the last path_months, using all documents."""
    people = documents.voters(fed, as_of)
    end = date.fromisoformat(as_of)
    months = []
    y, m = end.year, end.month
    for _ in range(CONFIG["combine"]["path_months"]):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    rows = []
    for y, m in reversed(months):
        start = date(y, m, 1).isoformat()
        stop = min(date(y + (m == 12), m % 12 + 1, 1).toordinal() - 1, end.toordinal())
        docs = _scored(conn, fed, model, people, start, date.fromordinal(stop).isoformat())
        per = {pid: _stance([d for d in docs if d["person_id"] == pid]) for pid in people}
        vals = [v for v in per.values() if v is not None]
        rows.append({"month": f"{y}-{m:02d}", "members": per, "n_members": len(vals),
                     "fed_stance": statistics.mean(vals) if vals else None,
                     "gauge": statistics.mean(vals) + 5 if vals else None})
    return rows
