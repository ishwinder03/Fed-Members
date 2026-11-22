"""Step 5 (plain code): member stances, Fed gauge, tally, spread, carry-over and the 6-month path."""
import json
import re
import statistics
from datetime import date, timedelta

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
                 model=r["model"], conditions=json.loads(r["conditions_json"] or "[]"))
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
        return "hold", None, (f"out of date: no policy speech since the {latest_decision} decision; last one was "
                              f"{call['date']}, so assumed hold")
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


def next_meeting(as_of):
    from analysis import context
    return next((b.isoformat() for a, b in context.scheduled_meetings() if b.isoformat() > as_of), None)


def apply_conditions(conn, fed, docs, as_of, latest_decision, upcoming, provider=None):
    """The newest data-dependent statement this member made for the upcoming meeting, resolved against
    the data released since. Returns (label, probability, note, detail) or None."""
    from analysis import conditions as C
    for d in reversed(docs):
        for cond in reversed(d.get("conditions") or []):
            meeting = (cond.get("meeting") or "")[:10]
            if meeting and meeting != upcoming:
                continue
            if not meeting and d["date"] < latest_decision:
                continue  # an open-ended condition from before the last decision has been overtaken
            res = C.resolve(fed, cond, d["date"], as_of)
            if res["status"] == "ai":
                res = C.resolve_with_ai(conn, fed, provider, cond, d["date"], as_of)
            info = {"quote": cond["quote"], "date": d["date"], "url": d.get("url"), "status": res["status"],
                    "detail": res["detail"], "then": cond["then"], "otherwise": cond.get("otherwise")}
            if res["status"] == "met":
                return cond["then"], CONFIG["conditions"]["met_probability"], "condition met", info
            if res["status"] == "not_met" and cond.get("otherwise"):
                return cond["otherwise"], CONFIG["conditions"]["met_probability"], "condition not met", info
            if res["status"] == "pending":
                return None, None, "condition pending", info
    return None


def reading(conn, fed, model, as_of, provider=None):
    """All numbers for the window ending at `as_of` (no AI, except the condition fallback when a
    provider is passed)."""
    dates = decision_dates(fed, as_of)
    i = len(dates) - 1
    people = documents.voters(fed, as_of)
    upcoming = next_meeting(as_of)
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
        condition = None
        cr = apply_conditions(conn, fed, cur["docs"], as_of, dates[i], upcoming, provider)
        if cr:
            c_label, c_prob, c_note, condition = cr
            if c_label:  # resolved by the data: overrides the speech-based call
                label, prob, note = c_label, c_prob, f"{c_note}: {condition['detail']}"
        basis = ("condition" if condition and condition["status"] in ("met", "not_met") else
                 "speech" if prob is not None else "dissent" if note and note.startswith("from their dissent") else None)
        members.append({
            "id": pid, "name": display_name(pid),
            "stance": cur["stance"], "prev_stance": prev["stance"],
            "change": None if cur["stance"] is None or prev["stance"] is None else cur["stance"] - prev["stance"],
            "carried_over": cur["carried_over"], "carried_from": cur.get("carried_from"),
            "silent_now": cur["silent_now"], "n_earlier": len(earlier),
            "n_policy": sum(not d.get("pending") and d["policy_relevance"] >= MIN_RELEVANCE_FOR_CALL for d in texts),
            "call": call, "call_label": label, "call_prob": prob, "call_note": note, "call_basis": basis,
            "condition": condition,
            "n_docs": len(texts), "n_scored": sum(d["weight"] > 0 for d in texts if not d.get("pending")),
            "pending": sum(bool(d.get("pending")) for d in texts), "latest_quote": latest_quote,
        })
    # committee view: average the hike/hold/cut odds of members with a current view (a recent policy
    # speech, a resolved condition, or a rate dissent at the last meeting); members without one are
    # assumed to vote with the committee, as members almost always do
    views = []
    for m in members:
        if m["call_basis"] == "speech" and m["call_note"] is None:
            views.append({k: m["call"][k] for k in ("hike", "hold", "cut")})
        elif m["call_basis"] in ("condition", "dissent", "speech"):
            p = m["call_prob"] if m["call_prob"] is not None else 1.0
            views.append({k: p if k == m["call_label"] else (1 - p) / 2 for k in ("hike", "hold", "cut")})
    committee = {k: sum(v[k] for v in views) / len(views) for k in ("hike", "hold", "cut")} if views else None
    predicted = max(("hold", "hike", "cut"), key=committee.get) if committee else "hold"
    for m in members:
        if m["call_basis"] is None:
            m.update(call_label=predicted, call_basis="committee",
                     call_note=f"follows the committee ({predicted}): no current view of their own")
    # each member on the headline's scale: their own hike odds minus cut odds (+100% = sure to back a 25bp hike)
    for m in members:
        if m["call_basis"] == "committee":
            m["implied"] = committee and (committee["hike"] - committee["cut"]) * 100
        elif m["call_basis"] == "speech" and m["call_note"] is None:
            m["implied"] = (m["call"]["hike"] - m["call"]["cut"]) * 100
        else:
            p = m["call_prob"] if m["call_prob"] is not None else 1.0
            m["implied"] = {"hike": p, "cut": -p}.get(m["call_label"], 0) * 100
    stances = [m["stance"] for m in members if m["stance"] is not None]
    prev_stances = [m["prev_stance"] for m in members if m["prev_stance"] is not None]
    gauge = statistics.mean(stances) + 5 if stances else None
    gauge_prev = statistics.mean(prev_stances) + 5 if prev_stances else None
    tally = {k: sum(m["call_label"] == k for m in members) for k in ("hike", "hold", "cut")}
    tally_own = {k: sum(m["call_label"] == k for m in members if m["call_basis"] != "committee") for k in ("hike", "hold", "cut")}
    tally["none"] = sum(m["call_label"] is None for m in members)
    return {
        "as_of": as_of, "window_start": dates[i], "window_end": as_of,
        "prev_window": [dates[i - 1], dates[i]] if i > 0 else None,
        "gauge": gauge, "gauge_prev": gauge_prev,
        "gauge_change": None if gauge is None or gauge_prev is None else gauge - gauge_prev,
        "spread": statistics.pstdev(stances) if len(stances) > 1 else None,
        "tally": tally, "tally_own": tally_own, "members": members,
        "committee": committee and {**committee, "predicted": predicted, "n_views": len(views),
                                    # Bloomberg-style: +100% = a 25bp hike fully expected, -100% = a 25bp cut
                                    "implied": (committee["hike"] - committee["cut"]) * 100},
        "implied": committee and (committee["hike"] - committee["cut"]) * 100,
        "no_view": sum(m["call_basis"] == "committee" for m in members),
        "next_meeting": upcoming, "missing_stance": [m["id"] for m in members if m["stance"] is None],
        "pending_docs": pending,
    }


def path_meetings(fed, as_of):
    """Meetings in the path range: [(first_day, last_day, snapshot_as_of)], where the snapshot is the day
    before the meeting: speeches stop at the blackout, but data released during it counts. Oldest first."""
    from analysis import context  # late import: context fetches the calendar page
    end = date.fromisoformat(as_of)
    y, m = end.year, end.month - (CONFIG["combine"]["path_months"] - 1)
    while m < 1:
        y, m = y - 1, m + 12
    start = date(y, m, 1)
    decided = set(decision_dates(fed, as_of))
    out = []
    for first, last in context.scheduled_meetings():
        snap = first - timedelta(days=1)
        if start <= last <= end and last.isoformat() in decided:
            out.append((first, last, snap.isoformat()))
    return out


def actual_votes(fed, meeting_date):
    """{person: 'hike'|'hold'|'cut'} as each member actually voted (a dissent = what they preferred)."""
    m = fed.execute("SELECT decision FROM meetings WHERE date=?", (meeting_date,)).fetchone()
    out = {}
    for v in fed.execute("SELECT * FROM votes WHERE meeting_date=?", (meeting_date,)):
        t = (v["dissent_text"] or "").lower()
        out[v["person_id"]] = ("hike" if "raise" in t else "cut" if "lower" in t else
                               "hold" if re.search(r"no change|maintain", t) and v["vote"] == "against" and
                               m["decision"] != "hold" else m["decision"])
    return out


def path(conn, fed, model, as_of, live=None, provider=None):
    """Meeting by meeting: for each past meeting, the reading the app would have shown just before its
    blackout (rebuilt from stored scores), next to what actually happened; then the upcoming meeting,
    taken from the live reading `live`, so it only changes when the analysis is re-run."""
    rows = []
    for first, last, snap in path_meetings(fed, as_of):
        r = reading(conn, fed, model, snap, provider)
        md = last.isoformat()
        m = fed.execute("SELECT * FROM meetings WHERE date=?", (md,)).fetchone()
        acts = actual_votes(fed, md)
        right = [x["id"] for x in r["members"] if x["id"] in acts and x["call_label"] == acts[x["id"]]]
        dissents = [(display_name(p), a) for p, a in acts.items() if a != m["decision"]]
        rows.append({
            "meeting_start": first.isoformat(), "meeting": md, "as_of": snap, "upcoming": False,
            "gauge": r["gauge"], "fed_stance": None if r["gauge"] is None else r["gauge"] - 5,
            "tally": r["tally"], "spread": r["spread"], "pending": r["pending_docs"], "committee": r["committee"],
            "members": {x["id"]: x["stance"] for x in r["members"]},
            "member_implied": {x["id"]: x.get("implied") for x in r["members"]},
            "calls": {x["id"]: x["call_label"] for x in r["members"]},
            "implied": r["implied"],
            "actual": {"decision": m["decision"], "bps": m["decision_bps"],
                       "implied": (1 if m["decision"] == "hike" else -1 if m["decision"] == "cut" else 0)
                                  * (m["decision_bps"] or 0) / 25 * 100,
                       "for": sum(a == m["decision"] for a in acts.values()), "against": len(dissents),
                       "dissents": dissents, "votes": acts},
            "calls_right": len(right), "calls_compared": sum(x["id"] in acts for x in r["members"]),
        })
    if live is not None:
        ctx = live.get("context") or {}
        rows.append({
            "meeting_start": ctx.get("next_meeting_start"), "meeting": ctx.get("next_meeting"), "as_of": live["as_of"],
            "upcoming": True, "implied": live.get("implied"), "gauge": live["gauge"], "fed_stance": None if live["gauge"] is None else live["gauge"] - 5,
            "tally": live["tally"], "spread": live["spread"], "pending": live["pending_docs"],
            "committee": live.get("committee"),
            "members": {x["id"]: x["stance"] for x in live["members"]},
            "member_implied": {x["id"]: x.get("implied") for x in live["members"]},
            "calls": {x["id"]: x["call_label"] for x in live["members"]},
        })
    return rows


def path_docs(fed, as_of):
    """(people, since, until) spans whose documents the meeting path needs scored."""
    back = len(CONFIG["combine"]["window_decay"]) + 1
    spans = []
    for _, _, snap in path_meetings(fed, as_of):
        dates = decision_dates(fed, snap)
        spans.append((documents.voters(fed, snap), dates[max(0, len(dates) - back)], snap))
    return spans
