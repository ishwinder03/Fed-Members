"""Step 1 (no AI): the policy context as of a date, from fed.db and the FOMC calendar page."""
import re
import time
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from analysis.settings import ROOT
from fedwatch.fomc import CALENDAR_URL
from fedwatch.people import display_name

CACHE = ROOT / "data" / "analysis_cache" / "fomccalendars.htm"
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def _calendar_page():
    """Refetched at most once a day into the analysis cache (the collector's cache is left alone)."""
    if not CACHE.exists() or time.time() - CACHE.stat().st_mtime > 86400:
        try:
            r = requests.get(CALENDAR_URL, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(r.text)
        except requests.RequestException:
            if not CACHE.exists():
                raise
    return CACHE.read_text()


def scheduled_meetings():
    """[(first_day, last_day)] of every scheduled FOMC meeting on the calendar page (not notation votes)."""
    soup = BeautifulSoup(_calendar_page(), "html.parser")
    out = []
    for panel in soup.select(".panel.panel-default"):
        y = re.search(r"(\d{4}) FOMC Meetings", panel.get_text(" ", strip=True))
        if not y:
            continue
        year = int(y[1])
        for row in panel.select(".fomc-meeting"):
            month = row.select_one(".fomc-meeting__month").get_text(" ", strip=True)
            days = row.select_one(".fomc-meeting__date").get_text(" ", strip=True)
            m = re.match(r"(\d+)(?:-(\d+))?\*?$", days.strip())
            if not m or "notation" in days.lower():
                continue
            months = [MONTHS[x] for x in re.findall("|".join(MONTHS), month)] or \
                     [next(v for k, v in MONTHS.items() if k.startswith(month[:3]))]
            first = date(year, months[0], int(m[1]))
            last = date(year, months[-1], int(m[2] or m[1]))
            out.append((first, last))
    return sorted(out)


def blackout_start(first_day):
    """The Fed's rule: the blackout begins the second Saturday before the meeting's first day."""
    sat = first_day - timedelta(days=(first_day.weekday() - 5) % 7 or 7)
    return sat - timedelta(days=7)


def _vote_line(fed, meeting_date):
    votes = fed.execute("SELECT person_id, dissent_text FROM votes WHERE meeting_date=? AND vote='against'",
                        (meeting_date,)).fetchall()
    n = fed.execute("SELECT COUNT(*) FROM votes WHERE meeting_date=?", (meeting_date,)).fetchone()[0]
    if not votes:
        return f"unanimous ({n}-0)"
    who = "; ".join(f"{display_name(v['person_id'])} {v['dissent_text']}" for v in votes)
    return f"{n - len(votes)}-{len(votes)}; dissents: {who}"


def as_of(fed, day):
    """Context for a document or reading dated `day` (YYYY-MM-DD)."""
    last = fed.execute("SELECT * FROM meetings WHERE date<=? AND decision IS NOT NULL ORDER BY date DESC LIMIT 1",
                       (day,)).fetchone()
    prev = fed.execute("SELECT date FROM meetings WHERE date<? AND decision IS NOT NULL ORDER BY date DESC LIMIT 1",
                       (last["date"],)).fetchone()
    d = date.fromisoformat(day)
    nxt = next(((a, b) for a, b in scheduled_meetings() if b > d), None)
    words = {"hike": "raised", "cut": "lowered", "hold": "held"}[last["decision"]]
    bps = f" by {last['decision_bps']}bps" if last["decision_bps"] else ""
    ctx = {
        "as_of": day,
        "target_range": last["target_range"],
        "last_decision": last["decision"],
        "last_decision_bps": last["decision_bps"],
        "last_decision_date": last["date"],
        "previous_decision_date": prev["date"] if prev else None,
        "last_vote": _vote_line(fed, last["date"]),
        "next_meeting_start": nxt[0].isoformat() if nxt else None,
        "next_meeting": nxt[1].isoformat() if nxt else None,
        "blackout_start": blackout_start(nxt[0]).isoformat() if nxt else None,
    }
    ctx["text"] = (
        f"Target range for the federal funds rate: {last['target_range']}.\n"
        f"Last decision: {words} the target range{bps} on {last['date']} (vote {ctx['last_vote']}).\n"
        f"Next FOMC meeting: {ctx['next_meeting_start']} to {ctx['next_meeting']}."
    )
    return ctx
