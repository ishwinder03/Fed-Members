"""Checks the stored data against the live source pages.

    python3 verify.py [ytd|1y|6m|3m] [n_spot_checks]     (window defaults to the last load's)
"""
import random
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from fedwatch import db, fomc, speeches, windows
from fedwatch.net import Fetcher
from fedwatch.people import PEOPLE, person_id

DATA = Path(__file__).parent / "data"
conn = db.connect(DATA / "fed.db")
args = sys.argv[1:]
last = conn.execute("SELECT window FROM loads WHERE window IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
WINDOW = next((a for a in args if a in windows.WINDOWS), last["window"] if last else windows.DEFAULT)
SINCE = windows.cutoff(WINDOW).isoformat()
print(f"Window: {WINDOW} (since {SINCE})\n")
f = Fetcher(DATA / "cache")
failures = 0


def check(cond, msg):
    global failures
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    failures += not cond


print("1. Votes per meeting vs. statement text")
for m in conn.execute("SELECT * FROM meetings WHERE date>=? ORDER BY date", (SINCE,)):
    votes = conn.execute("SELECT * FROM votes WHERE meeting_date=?", (m["date"],)).fetchall()
    st = fomc.parse_statement(f.get(m["statement_url"]))
    stored = {v["person_id"]: v["dissent_text"] for v in votes if v["vote"] == "against"}
    expected = {person_id(n): r for n, r in st["dissents"].items()}
    check(len(votes) == 12, f"{m['date']}: {len(votes)} votes ({m['roster_source']})")
    check(stored == expected, f"{m['date']}: dissents {sorted(stored) or 'none'} match statement wording")
    d = st["decision"]
    check(d is not None and (m["decision"], m["decision_bps"]) == (d["decision"], d["bps"]),
          f"{m['date']}: decision stored as {m['decision']} {m['decision_bps']}bps")
    if st["tally"]:
        check(st["tally"] == (12 - len(stored), len(stored)), f"{m['date']}: statement tally {st['tally'][0]}-{st['tally'][1]}")

print("\n2. Governor speech counts vs. the Board's yearly speeches pages")
urls = set()
for year in windows.years(WINDOW):
    page = f.get(speeches.BOARD_LIST.format(year=year), use_cache=False)
    for u, ymd in re.findall(rf'href="(/newsevents/speech/[a-z]+({year}\d{{4}})[a-z]\.htm)"', page):
        if f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" >= SINCE:
            urls.add(u)
page_counts = Counter(re.search(r"speech/([a-z]+)", u)[1] for u in urls)
db_counts = Counter(r["person_id"] for r in conn.execute(
    "SELECT person_id FROM speeches WHERE source='board' AND date>=?", (SINCE,)))
for pid in sorted(set(page_counts) | set(db_counts)):
    check(page_counts[pid] == db_counts[pid], f"{pid:<10} page {page_counts[pid]:>3}  stored {db_counts[pid]:>3}")
print(f"  total unique on page: {len(urls)}")

print("\n3. Regional items stored (by kind)")
for r in conn.execute("SELECT person_id, source, kind, COUNT(*) n FROM speeches WHERE source!='board' "
                      "AND date>=? GROUP BY person_id, kind ORDER BY person_id", (SINCE,)):
    print(f"  {r['person_id']:<10} {r['source']:<13} {r['kind']:<10} {r['n']}")

print("\n4. Spot checks")
n = next((int(a) for a in args if a.isdigit()), 3)
rows = conn.execute("SELECT * FROM speeches WHERE kind='speech' AND date>=?", (SINCE,)).fetchall()
random.seed(None)
for s in random.sample(rows, n):
    html = f.get(s["url"])
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    y, mo, d = s["date"].split("-")
    long_date = f"{['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][int(mo)]} {int(d)}, {y}"
    surname = PEOPLE[s["person_id"]]["names"][0].split()[-1]
    print(f"\n  {s['url']}\n  speaker={s['person_id']}  date={s['date']}  chars={s['text_chars']}  title={s['title']}")
    check(surname in text, f"speaker surname '{surname}' on page")
    check(long_date in text or s["date"].replace("-", "") in s["url"] or s["date"][2:].replace("-", "") in s["url"],
          f"date {long_date} on page or in URL")
    body = s["text"]
    print("  begins: " + body[:220].replace("\n\n", " / "))
    print("  ends:   " + body[-220:].replace("\n\n", " / "))

print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
sys.exit(1 if failures else 0)
