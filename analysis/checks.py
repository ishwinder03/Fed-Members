"""Checks from the spec, run one at a time:

    python3 -m analysis.checks score [--model M] URL ...        score these documents, print the full JSON
    python3 -m analysis.checks consistency [--model M] URL ...  score each 3 more times (trials 1-3), report spread
"""
import statistics
import json
import sys

from analysis import documents, providers, score
from analysis.settings import CONFIG
from analysis.store import collector, connect


def doc_for(fed, url):
    r = fed.execute("SELECT person_id, date FROM speeches WHERE url=?", (url,)).fetchone()
    return next(d for d in documents.texts(fed, [r["person_id"]], r["date"], r["date"]) if d["url"] == url)


def check_score(model, urls):
    conn, fed = connect(), collector()
    p = providers.get(model)
    for url in urls:
        d = doc_for(fed, url)
        print(f"\n=== {d['date']} {d['person_id']} [{d['doc_type']}] {d['title']}\n    {url}")
        if not score.is_scored(conn, d["doc_id"], p.model):
            score.score(conn, fed, p, d)
        row = conn.execute("SELECT * FROM scores WHERE doc_id=? AND model=? AND prompt_version=? AND trial=0",
                           (d["doc_id"], p.model, CONFIG["prompt_version"])).fetchone()
        print(json.dumps(json.loads(row["raw_json"]), indent=2, ensure_ascii=False))
        print(f"    validation: {row['validation_notes'] or 'all quotes verbatim, ranges ok'}")
    u = conn.execute("SELECT COUNT(*), SUM(tokens_in), SUM(tokens_out), AVG(latency_s) FROM ai_calls "
                     "WHERE model=? AND purpose='score'", (p.model,)).fetchone()
    print(f"\n{u[0]} score calls so far with {p.model}; tokens in {u[1]}, out {u[2]}; avg {u[3]:.1f}s per call")


def check_consistency(model, urls, trials=3):
    conn, fed = connect(), collector()
    p = providers.get(model)
    worst = 0
    for url in urls:
        d = doc_for(fed, url)
        for t in range(1, trials + 1):
            if not score.is_scored(conn, d["doc_id"], p.model, trial=t):
                score.score(conn, fed, p, d, trial=t)
        rows = conn.execute("SELECT * FROM scores WHERE doc_id=? AND model=? AND prompt_version=? ORDER BY trial",
                            (d["doc_id"], p.model, CONFIG["prompt_version"])).fetchall()
        reps = [r for r in rows if r["trial"] >= 1]
        st = [r["stance"] for r in reps]
        spread = max(st) - min(st)
        worst = max(worst, spread)
        print(f"\n=== {d['date']} {d['person_id']} {d['title'][:70]}")
        print(f"    {'trial':<6}{'stance':>7}{'hike':>7}{'hold':>7}{'cut':>7}{'relev':>7}{'conf':>7}{'mandate':>9}")
        for r in rows:
            print(f"    {r['trial'] if r['trial'] else '0 (check 3)':<6}{r['stance']:>+7.1f}{r['p_hike']:>7.2f}{r['p_hold']:>7.2f}"
                  f"{r['p_cut']:>7.2f}{r['policy_relevance']:>7.2f}{r['confidence']:>7.2f}{r['mandate_balance']:>+9.2f}")
        print(f"    trials 1-3: stance range {spread:.1f} (sd {statistics.pstdev(st):.2f}), "
              f"weight range {min(r['policy_relevance'] * r['confidence'] for r in reps):.2f}-"
              f"{max(r['policy_relevance'] * r['confidence'] for r in reps):.2f}  ->  "
              f"{'PASS' if spread <= 1 else 'FAIL'} (target within 1 point)")
        for r in reps:
            print(f"      t{r['trial']} quotes: " + " | ".join(e["quote"][:60] for e in json.loads(r["evidence_json"])))
    print(f"\nWorst stance range: {worst:.1f}")


if __name__ == "__main__":
    a = sys.argv[1:]
    model = a[a.index("--model") + 1] if "--model" in a else CONFIG["model"]
    rest = [x for x in a[1:] if x.startswith("http")]
    if a[0] == "score":
        check_score(model, rest)
    elif a[0] == "consistency":
        check_consistency(model, rest)
