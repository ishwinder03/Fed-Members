"""Step 3: one AI call per document, validated, cached by (document, model, prompt version)."""
import json
import re
import time

from analysis import context
from analysis.documents import keyword_hits
from analysis.providers.base import QuotaExhausted
from analysis.settings import CONFIG, daily_cap, prompt, score_models
from analysis.store import calls_today, now, pacific_day
from fedwatch.people import PEOPLE, display_name

SCHEMA = {
    "type": "object",
    "properties": {
        "stance": {"type": "number", "minimum": -5, "maximum": 5},
        "next_meeting_call": {
            "type": "object",
            "properties": {k: {"type": "number", "minimum": 0, "maximum": 1} for k in ("hike", "hold", "cut")},
            "required": ["hike", "hold", "cut"]},
        "policy_relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "mandate_balance": {"type": "number", "minimum": -1, "maximum": 1},
        "mandate_reason": {"type": "string"},
        "sub_views": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in ("inflation", "labour_market", "preferred_path", "urgency")},
            "required": ["inflation", "labour_market", "preferred_path", "urgency"]},
        "evidence": {
            "type": "array", "minItems": 2, "maxItems": 3,
            "items": {"type": "object",
                      "properties": {"quote": {"type": "string"}, "date": {"type": "string"},
                                     "timestamp": {"type": ["string", "null"]}},
                      "required": ["quote", "date"]}},
        "summary": {"type": "string"},
    },
    "required": ["stance", "next_meeting_call", "policy_relevance", "confidence", "mandate_balance",
                 "mandate_reason", "sub_views", "evidence", "summary"],
}


class Invalid(Exception):
    pass


def _norm(s):
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                                   "—": "-", "‑": "-", " ": " "}))
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_found(quote, text_norm):
    parts = [p.strip(" .,;") for p in re.split(r"\.\.\.|…|\[\.\.\.\]", _norm(quote))]
    return all(p in text_norm for p in parts if p)


def validate(data, text):
    """Returns (cleaned data, notes). Raises Invalid when the reply can't be used as is."""
    notes = []
    for k, lo, hi in (("stance", -5, 5), ("policy_relevance", 0, 1), ("confidence", 0, 1), ("mandate_balance", -1, 1)):
        if not isinstance(data.get(k), (int, float)) or not lo <= data[k] <= hi:
            raise Invalid(f"{k}={data.get(k)!r} outside {lo}..{hi}")
    call = data["next_meeting_call"]
    total = sum(call.get(k, 0) for k in ("hike", "hold", "cut"))
    if abs(total - 1) > 0.02:
        raise Invalid(f"next_meeting_call sums to {total:.3f}")
    data["next_meeting_call"] = {k: call[k] / total for k in ("hike", "hold", "cut")}
    tn = _norm(text)
    good = [e for e in data["evidence"] if quote_found(e["quote"], tn)]
    for e in data["evidence"]:
        if e not in good:
            notes.append(f"dropped non-verbatim quote: {e['quote'][:80]!r}")
    if len(good) < 2:
        raise Invalid(f"only {len(good)} verbatim quote(s)")
    data["evidence"] = good
    top = max(data["next_meeting_call"], key=data["next_meeting_call"].get)
    if (data["stance"] >= 3 and top == "cut") or (data["stance"] <= -3 and top == "hike"):
        notes.append(f"stance {data['stance']} disagrees with most likely call '{top}'")
    return data, notes


def user_message(doc, ctx):
    p = PEOPLE.get(doc["person_id"], {})
    return (f"POLICY CONTEXT (as of the document date)\n{ctx['text']}\n\n"
            f"DOCUMENT\nSpeaker: {display_name(doc['person_id'])} ({p.get('institution', '')})\n"
            f"Date: {doc['date']}\nType: {doc['doc_type']}\nTitle: {doc['title']}\nURL: {doc['url']}\n\n"
            f"TEXT\n{doc['text']}")


def _log_call(conn, run_id, doc, provider, status, usage=None, latency=None, error=None):
    conn.execute("INSERT INTO ai_calls (run_id, purpose, doc_id, model, prompt_version, status, tokens_in, "
                 "tokens_out, latency_s, error, at, pacific_day) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (run_id, "score", doc["doc_id"], provider.model, CONFIG["prompt_version"], status,
                  (usage or {}).get("tokens_in"), (usage or {}).get("tokens_out"), latency, error, now(),
                  pacific_day()))
    conn.commit()


def _save(conn, doc, model, data, ctx, raw, notes, trial, prefiltered=0):
    call = data.get("next_meeting_call") or {}
    conn.execute(
        "INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (doc["doc_id"], model, CONFIG["prompt_version"], trial, doc["person_id"], doc["date"], data["stance"],
         call.get("hike"), call.get("hold"), call.get("cut"), data["policy_relevance"], data["confidence"],
         data.get("mandate_balance"), data.get("mandate_reason"), json.dumps(data.get("sub_views")),
         json.dumps(data.get("evidence", [])), data.get("summary"), json.dumps(ctx), raw,
         "; ".join(notes) or None, prefiltered, now()))
    conn.commit()


def is_scored(conn, doc_id, model, trial=0):
    """True if `model` (or, for the default model, its fallback) has scored this document."""
    models = score_models(model) if trial == 0 else [model]
    return conn.execute(f"SELECT 1 FROM scores WHERE doc_id=? AND prompt_version=? AND trial=? "
                        f"AND model IN ({','.join('?' * len(models))})",
                        (doc_id, CONFIG["prompt_version"], trial, *models)).fetchone() is not None


def prefilter(conn, doc, model):
    """No-AI skip: a text with almost no monetary-policy words gets relevance 0 without a call."""
    hits = keyword_hits(doc["text"])
    if hits >= CONFIG["prefilter"]["min_hits"]:
        return False
    _save(conn, doc, model, {"stance": 0, "policy_relevance": 0, "confidence": 0,
                             "summary": f"No monetary-policy content ({hits} keyword hits); not sent to the model."},
          None, None, [], 0, prefiltered=1)
    return True


def score(conn, fed, provider, doc, run_id=None, trial=0, log=print):
    """Scores one document; returns the stored data. Raises QuotaExhausted when the day's calls are used."""
    ctx = context.as_of(fed, doc["date"])
    system = prompt(CONFIG["prompt_version"])
    user = user_message(doc, ctx)
    temperature = CONFIG["temperature"]
    for attempt in (1, 2):  # one retry on an invalid reply
        cap = daily_cap(provider.model)
        if calls_today(conn, provider.model) >= cap:
            raise QuotaExhausted(f"{provider.model}: daily cap of {cap} calls reached"
                                 + (" (resets midnight Pacific)" if cap else " (paid credits not approved)"))
        t0 = time.time()
        try:
            data, usage = provider.generate_json(system, user, SCHEMA, temperature)
        except QuotaExhausted as e:
            _log_call(conn, run_id, doc, provider, "quota", error=str(e)[:500])
            raise
        except Exception as e:
            _log_call(conn, run_id, doc, provider, "error", error=str(e)[:500], latency=time.time() - t0)
            raise
        raw = json.dumps(data)
        try:
            data, notes = validate(data, doc["text"])
        except (Invalid, KeyError, TypeError) as e:
            _log_call(conn, run_id, doc, provider, "invalid", usage, time.time() - t0, str(e))
            log(f"  invalid reply for {doc['doc_id']} (attempt {attempt}): {e}")
            if attempt == 2:
                raise Invalid(str(e))
            continue
        _log_call(conn, run_id, doc, provider, "ok", usage, time.time() - t0)
        _save(conn, doc, provider.model, data, {k: v for k, v in ctx.items() if k != "text"}, raw, notes, trial)
        return data
