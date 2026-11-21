"""One 'Load': refresh the FOMC roster and collect new speeches within a look-back window."""
import re
import time
import traceback
from datetime import date, datetime

from bs4 import BeautifulSoup

from . import fomc, speeches, windows
from .people import PEOPLE, person_id

PRESIDENT_TITLE = "President, {inst}"


def now():
    return datetime.now().isoformat(timespec="seconds")


class Loader:
    def __init__(self, conn, fetcher, window, log, today=None):
        self.conn, self.f, self.window, self.log = conn, fetcher, window, log
        self.today = today or date.today()
        self.since = windows.cutoff(window, self.today).isoformat()
        self.years = windows.years(window, self.today)
        self.issues = []
        self.new_speeches = 0

    def issue(self, scope, msg):
        self.issues.append((scope, msg))
        self.log(f"  ! [{scope}] {msg}")

    # ------------------------------------------------------------ FOMC
    def load_fomc(self):
        self.log(f"FOMC calendar (meetings since {self.since}) ...")
        cal = self.f.get(fomc.CALENDAR_URL, use_cache=False)
        all_meetings = [m for y in self.years for m in fomc.calendar_meetings(cal, y)]
        meetings = [m for m in all_meetings if m["date"] >= self.since]
        self.log(f"  {len(meetings)} statements in the window")
        latest_roles = {}
        for m in meetings:
            row = self.conn.execute("SELECT * FROM meetings WHERE date=?", (m["date"],)).fetchone()
            settled = (row and row["roster_source"] in ("statement", "minutes") and row["check_ok"]
                       and row["decision"] is not None
                       and not (row["roster_source"] == "statement" and m["minutes_url"] and not row["minutes_url"]))
            if settled:
                self.log(f"  {m['date']}: already stored ({row['roster_source']})")
                if m is meetings[-1]:
                    latest_roles = self._roles_for(m)
                continue
            statement = fomc.parse_statement(self.f.get(m["statement_url"]))
            if not statement["decision"] and not statement["voting_for"] and not statement["tally"]:
                self.log(f"  {m['date']}: not a policy decision statement, skipped")
                continue
            minutes = fomc.parse_minutes(self.f.get(m["minutes_url"])) if m["minutes_url"] else None
            previous = None
            if not statement["voting_for"] and not (minutes and minutes["voting_for"]):
                previous = self._previous_roster(m["date"], all_meetings)
            roster, source, notes = fomc.build_roster(statement, minutes, previous)
            if roster is None:
                self.issue("fomc", f"{m['date']}: could not determine voters ({'; '.join(notes)})")
                continue
            if not statement["decision"]:
                notes.append("could not read the rate decision from the statement")
            ok, notes = self._check(m["date"], roster, statement, notes)
            self._store_meeting(m, roster, source, statement, ok, notes)
            latest_roles = {**(minutes or {}).get("roles", {}), **statement["roles"]}
            d = statement["decision"] or {}
            self.log(f"  {m['date']}: {d.get('decision', '?')} {d.get('bps', '')}bps · {len(roster)} votes from {source}, "
                     f"{sum(v[0] == 'against' for v in roster.values())} dissent(s){'' if ok else '  CHECK FAILED'}")
        if latest_roles:
            self.conn.execute("UPDATE roles SET fomc_role=NULL")
            for name, role in latest_roles.items():
                pid = person_id(name)
                if pid:
                    self.conn.execute("INSERT INTO roles(person_id, fomc_role) VALUES(?,?) "
                                      "ON CONFLICT(person_id) DO UPDATE SET fomc_role=excluded.fomc_role", (pid, role))
        self.conn.commit()

    def _roles_for(self, m):
        roles = {}
        if m["minutes_url"]:
            roles.update(fomc.parse_minutes(self.f.get(m["minutes_url"]))["roles"])
        roles.update(fomc.parse_statement(self.f.get(m["statement_url"]))["roles"])
        return roles

    def _previous_roster(self, date_, all_meetings):
        """Voters at the meeting before date_, from the DB or (if outside the window) its sources."""
        row = self.conn.execute("SELECT meeting_date FROM votes WHERE meeting_date<? "
                                "ORDER BY meeting_date DESC LIMIT 1", (date_,)).fetchone()
        if row:
            return [r["printed_name"] for r in
                    self.conn.execute("SELECT printed_name FROM votes WHERE meeting_date=?", (row["meeting_date"],))]
        earlier = [m for m in all_meetings if m["date"] < date_]
        for m in reversed(earlier):
            st = fomc.parse_statement(self.f.get(m["statement_url"]))
            mn = fomc.parse_minutes(self.f.get(m["minutes_url"])) if m["minutes_url"] else None
            roster, _, _ = fomc.build_roster(st, mn, None)
            if roster:
                return list(roster)
        return None

    def _check(self, date_, roster, statement, notes):
        notes = list(notes)
        n_for = sum(v[0] == "for" for v in roster.values())
        n_against = len(roster) - n_for
        if len(roster) != 12:
            notes.append(f"{len(roster)} votes, expected 12")
        if statement["tally"] and statement["tally"] != (n_for, n_against):
            notes.append(f"statement says {statement['tally'][0]}-{statement['tally'][1]}, parsed {n_for}-{n_against}")
        if set(statement["dissents"]) != {k for k, v in roster.items() if v[0] == "against"}:
            notes.append("dissenters differ from statement text")
        for name in roster:
            if not person_id(name):
                notes.append(f"unknown person '{name}'")
        hard = [n for n in notes if not n.startswith("minutes not yet published")]
        for n in hard:
            self.issue("fomc", f"{date_}: {n}")
        return not hard, notes

    def _store_meeting(self, m, roster, source, statement, ok, notes):
        c = self.conn
        tally = statement["tally"] or (sum(v[0] == "for" for v in roster.values()),
                                       sum(v[0] == "against" for v in roster.values()))
        d = statement["decision"] or {}
        c.execute("""INSERT INTO meetings(date, statement_url, minutes_url, tally_for, tally_against, roster_source,
                     check_ok, check_notes, updated_at, decision, decision_bps, target_range)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(date) DO UPDATE SET statement_url=excluded.statement_url,
                     minutes_url=excluded.minutes_url, tally_for=excluded.tally_for,
                     tally_against=excluded.tally_against, roster_source=excluded.roster_source,
                     check_ok=excluded.check_ok, check_notes=excluded.check_notes, updated_at=excluded.updated_at,
                     decision=excluded.decision, decision_bps=excluded.decision_bps, target_range=excluded.target_range""",
                  (m["date"], m["statement_url"], m["minutes_url"], tally[0], tally[1], source,
                   int(ok), "; ".join(notes), now(), d.get("decision"), d.get("bps"), d.get("range")))
        c.execute("DELETE FROM votes WHERE meeting_date=?", (m["date"],))
        for name, (vote, reason) in roster.items():
            pid = person_id(name) or "unknown:" + name
            c.execute("INSERT INTO votes VALUES(?,?,?,?,?)", (m["date"], pid, name, vote, reason))

    # ------------------------------------------------------------ speeches
    def load_speeches(self):
        f, ys, since = self.f, self.years, self.since
        listing = lambda url: f.get(url, use_cache=False)  # noqa: E731
        sources = [
            ("board", lambda: speeches.list_board(listing, ys, since, self.issues)),
            ("newyork", lambda: speeches.list_newyork(listing, ys, since, self.issues)),
            ("cleveland", lambda: speeches.list_cleveland(listing, f.get_json, ys, since, self.issues)),
            ("philadelphia", lambda: speeches.list_philadelphia(listing, ys, since, self.issues)),
            ("dallas", lambda: speeches.list_dallas(listing, ys, since, self.issues)),
            ("minneapolis", lambda: speeches.list_minneapolis(listing, f.get_json, ys, since, self.issues)),
        ]
        for source, lister in sources:
            self.log(f"Speeches: {source} listing ...")
            try:
                result = lister()
            except Exception as e:  # keep going with the other sources
                self.issue(source, f"listing failed: {e}")
                continue
            if source == "board":
                items, titles = result
                for pid, title in titles.items():
                    self._set_title(pid, title)
            else:
                items = result
            known = {r["url"] for r in self.conn.execute("SELECT url FROM speeches WHERE source=?", (source,))}
            new = [it for it in items if it["url"] not in known]
            self.log(f"  {len(items)} listed since {since}, {len(new)} new")
            for it in new:
                self._fetch_speech(source, it)
        for pid, p in PEOPLE.items():
            if p["source"] != "board":
                self._set_title(pid, PRESIDENT_TITLE.format(inst=p["institution"]))
        self.conn.commit()

    def _set_title(self, pid, title):
        self.conn.execute("INSERT INTO roles(person_id, title) VALUES(?,?) "
                          "ON CONFLICT(person_id) DO UPDATE SET title=excluded.title", (pid, title))

    def _fetch_speech(self, source, it):
        try:
            page = self.f.get(it["url"])
        except Exception as e:
            self.issue(source, f"could not fetch {it['url']}: {e}")
            return
        title, text = speeches.extract(page, source)
        title = it["title"] or title
        min_chars = 300 if it["kind_hint"] in ("statement", "essay") else speeches.MIN_TEXT_CHARS
        kind = it["kind_hint"] if len(text) >= min_chars else "no_text"
        page_text = BeautifulSoup(page, "html.parser").get_text(" ")
        surname = PEOPLE[it["person_id"]]["names"][0].split()[-1]
        verified = int(bool(re.search(rf"\b{re.escape(surname)}\b", page_text)))
        if not verified:
            self.issue(source, f"speaker name '{surname}' not found on page {it['url']}")
        self.conn.execute("INSERT OR REPLACE INTO speeches VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (it["url"], it["person_id"], it["date"], title, kind, source, text, len(text), verified,
                           self.f.cache_path(it["url"]).name, now()))
        self.conn.commit()
        self.new_speeches += 1
        self.log(f"    + {it['date']} {it['person_id']:<9} {kind:<9} {len(text):>6} chars  {title[:60]}")

    # ------------------------------------------------------------ run
    def run(self, log_lines=None):
        started, t0 = now(), time.monotonic()
        requests_before = self.f.requests_made
        ok = True
        self.log(f"Load: {windows.WINDOWS[self.window]} (since {self.since})")
        try:
            self.load_fomc()
            self.load_speeches()
        except Exception:
            ok = False
            self.issue("load", traceback.format_exc().splitlines()[-1])
            self.log(traceback.format_exc())
        duration = time.monotonic() - t0
        n_requests = self.f.requests_made - requests_before
        self.log(f"Done in {duration:.1f}s: {self.new_speeches} new items, {n_requests} HTTP requests.")
        self.conn.execute("DELETE FROM issues")
        self.conn.executemany("INSERT INTO issues(scope, message, created_at) VALUES(?,?,?)",
                              [(s, m, now()) for s, m in self.issues])
        self.conn.execute("INSERT INTO loads(started_at, finished_at, new_speeches, requests, ok, window, cutoff, "
                          "duration_s, log) VALUES(?,?,?,?,?,?,?,?,?)",
                          (started, now(), self.new_speeches, n_requests, int(ok), self.window, self.since,
                           round(duration, 1), "\n".join(log_lines or [])))
        self.conn.commit()
        return ok
