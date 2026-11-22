"""What gets scored: the collector's texts (read-only) and the votes (Step 4, no AI)."""
import re

from analysis.settings import CONFIG

# collector kind -> analysis document type; 'no_text' (e.g. Kashkari's video-only events) is skipped
DOC_TYPES = {"speech": "speech", "statement": "statement", "essay": "essay"}


def voters(fed, day):
    """The 12 who voted at the last decision on or before `day`."""
    last = fed.execute("SELECT MAX(date) FROM meetings WHERE date<=? AND decision IS NOT NULL", (day,)).fetchone()[0]
    return [r[0] for r in fed.execute("SELECT person_id FROM votes WHERE meeting_date=? ORDER BY person_id", (last,))]


def texts(fed, people, since, until):
    rows = fed.execute(
        f"SELECT url, person_id, date, title, kind, text FROM speeches WHERE date>=? AND date<=? "
        f"AND kind IN ({','.join('?' * len(DOC_TYPES))}) AND person_id IN ({','.join('?' * len(people))}) "
        "ORDER BY date", (since, until, *DOC_TYPES, *people)).fetchall()
    return [{"doc_id": "speech:" + r["url"], "url": r["url"], "person_id": r["person_id"], "date": r["date"],
             "title": r["title"], "doc_type": DOC_TYPES[r["kind"]], "text": r["text"]} for r in rows]


def keyword_hits(text):
    t = text.lower()
    return sum(t.count(k.lower()) for k in CONFIG["prefilter"]["keywords"])


def vote_score(vote, decision):
    """Score from config [vote_scores], relative to the meeting's decision."""
    vs = CONFIG["vote_scores"]
    if vote["vote"] != "against":
        return vs["agree"], "agree"
    t = (vote["dissent_text"] or "").lower()
    if "raise" in t:
        return vs["dissent_tighter_rate"], "dissent: wanted a hike"
    if "lower" in t:
        return vs["dissent_looser_rate"], "dissent: wanted a cut" if decision != "cut" else "dissent: wanted a bigger cut"
    if re.search(r"no change|maintain", t) and decision in ("cut", "hike"):
        return (vs["dissent_tighter_rate"], "dissent: wanted a hold, not a cut") if decision == "cut" else \
               (vs["dissent_looser_rate"], "dissent: wanted a hold, not a hike")
    if "easing bias" in t:
        return vs["dissent_tighter_wording"], "dissent: objected to the easing bias"
    if "tightening bias" in t:
        return vs["dissent_looser_wording"], "dissent: objected to the tightening bias"
    return 0, "dissent: direction unclear"


def votes(fed, people, since, until):
    rows = fed.execute(
        f"SELECT v.*, m.decision, m.decision_bps FROM votes v JOIN meetings m ON m.date=v.meeting_date "
        f"WHERE v.meeting_date>=? AND v.meeting_date<=? AND v.person_id IN ({','.join('?' * len(people))})",
        (since, until, *people)).fetchall()
    out = []
    for r in rows:
        stance, label = vote_score(r, r["decision"])
        out.append({"doc_id": f"vote:{r['meeting_date']}:{r['person_id']}", "person_id": r["person_id"],
                    "date": r["meeting_date"], "doc_type": "vote", "title": f"FOMC vote {r['meeting_date']}: {label}",
                    "url": None, "agree": r["vote"] != "against", "stance": stance, "policy_relevance": 1.0, "confidence": 1.0,
                    "summary": label + (f" ({r['dissent_text']})" if r["dissent_text"] else ""), "evidence": []})
    return out
