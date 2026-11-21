"""Local web app: python3 server.py  ->  http://127.0.0.1:8765

Everything a Load collects is kept in data/fed.db, so reopening the app shows the last
results straight away; Load only fetches what is new for the selected window.
"""
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fedwatch import db, windows
from fedwatch.loader import Loader
from fedwatch.net import Fetcher
from fedwatch.people import PEOPLE, display_name

ROOT = Path(__file__).parent
DATA = ROOT / "data"
PORT = 8765

conn = db.connect(DATA / "fed.db")
db_lock = threading.Lock()
fetcher = Fetcher(DATA / "cache")
load_state = {"running": False, "log": [], "ok": None, "window": None, "started": None, "elapsed": None}


def run_load(window):
    def log(line):
        load_state["log"].append(line)
        print(line, flush=True)
    load_state.update(running=True, log=[], ok=None, window=window, started=time.time(), elapsed=None)
    try:
        # own connection so the page stays readable while a load runs
        load_conn = db.connect(DATA / "fed.db")
        load_state["ok"] = Loader(load_conn, fetcher, window, log).run(load_state["log"])
        load_conn.close()
    finally:
        load_state["elapsed"] = time.time() - load_state["started"]
        load_state["running"] = False


def q(sql, args=()):
    with db_lock:
        return [dict(r) for r in conn.execute(sql, args)]


def summary(window):
    since = windows.cutoff(window).isoformat()
    meetings = q("SELECT * FROM meetings WHERE date>=? ORDER BY date", (since,))
    votes = q("SELECT * FROM votes WHERE meeting_date>=?", (since,))
    latest = meetings[-1]["date"] if meetings else None
    current = {v["person_id"] for v in votes if v["meeting_date"] == latest}
    roles = {r["person_id"]: r for r in q("SELECT * FROM roles")}
    counts = {}
    for r in q("SELECT person_id, kind, COUNT(*) n FROM speeches WHERE date>=? GROUP BY person_id, kind", (since,)):
        counts.setdefault(r["person_id"], {})[r["kind"]] = r["n"]
    members = []
    for pid in sorted({v["person_id"] for v in votes}):
        role = roles.get(pid, {})
        pv = [v for v in votes if v["person_id"] == pid]
        members.append({
            "id": pid,
            "name": display_name(pid) if pid in PEOPLE else pid,
            "title": role.get("title"),
            "fomc_role": role.get("fomc_role") if pid in current else None,
            "institution": PEOPLE.get(pid, {}).get("institution"),
            "speeches_tracked": bool(PEOPLE.get(pid, {}).get("source")),
            "current": pid in current,
            "speeches": counts.get(pid, {}).get("speech", 0),
            "other_items": {k: n for k, n in counts.get(pid, {}).items() if k != "speech"},
            "dissents": sum(v["vote"] == "against" for v in pv),
            "votes_cast": len(pv),
        })
    order = {"Chair": 0, "Vice Chair": 1}
    members.sort(key=lambda m: (not m["current"], order.get(m["fomc_role"], 2),
                                m["institution"] != "Board of Governors", m["name"].split()[-1]))
    # how far back successful loads reach, to warn when the window asks for more
    covered = q("SELECT MIN(cutoff) c FROM loads WHERE ok=1 AND cutoff IS NOT NULL")[0]["c"]
    return {
        "window": window,
        "windows": windows.WINDOWS,
        "since": since,
        "covered_since": covered,
        "meetings": meetings,
        "votes": votes,
        "members": members,
        "issues": q("SELECT scope, message FROM issues ORDER BY id"),
        "no_text": q("SELECT person_id, date, title, url FROM speeches WHERE kind='no_text' AND date>=? "
                     "ORDER BY person_id, date", (since,)),
        "unverified": q("SELECT person_id, date, title, url FROM speeches WHERE speaker_verified=0 AND date>=?", (since,)),
        "last_load": (q("SELECT id, started_at, finished_at, new_speeches, requests, ok, window, cutoff, duration_s "
                        "FROM loads ORDER BY id DESC LIMIT 1") or [None])[0],
        "recent_loads": q("SELECT finished_at, window, duration_s, new_speeches, requests, ok "
                          "FROM loads ORDER BY id DESC LIMIT 8"),
    }


def member(pid, window):
    since = windows.cutoff(window).isoformat()
    return {
        "speeches": q("SELECT url, date, title, kind, source, text_chars, speaker_verified FROM speeches "
                      "WHERE person_id=? AND date>=? ORDER BY date DESC", (pid, since)),
        "votes": q("SELECT v.*, m.roster_source FROM votes v JOIN meetings m ON m.date=v.meeting_date "
                   "WHERE person_id=? AND meeting_date>=? ORDER BY meeting_date", (pid, since)),
    }


def window_arg(args):
    w = args.get("window", [windows.DEFAULT])[0]
    return w if w in windows.WINDOWS else windows.DEFAULT


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json", status=200):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        args = parse_qs(u.query)
        if u.path == "/":
            return self._send((ROOT / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/summary":
            return self._send(summary(window_arg(args)))
        if u.path.startswith("/api/member/"):
            return self._send(member(u.path.rsplit("/", 1)[1], window_arg(args)))
        if u.path == "/api/speech":
            rows = q("SELECT * FROM speeches WHERE url=?", (args.get("url", [""])[0],))
            return self._send(rows[0] if rows else {}, status=200 if rows else 404)
        if u.path == "/api/load":
            s = load_state
            elapsed = (time.time() - s["started"]) if s["running"] else s["elapsed"]
            if not s["log"]:  # nothing run since the server started: show the saved log of the last load
                last = q("SELECT log, window, duration_s, ok FROM loads ORDER BY id DESC LIMIT 1")
                if last:
                    return self._send({"running": False, "ok": bool(last[0]["ok"]), "window": last[0]["window"],
                                       "elapsed": last[0]["duration_s"], "log": (last[0]["log"] or "").splitlines()})
            return self._send({"running": s["running"], "ok": s["ok"], "window": s["window"],
                               "elapsed": elapsed, "log": s["log"][-400:]})
        self._send({"error": "not found"}, status=404)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/load":
            w = window_arg(parse_qs(u.query))
            if not load_state["running"]:
                threading.Thread(target=run_load, args=(w,), daemon=True).start()
            return self._send({"started": True, "window": w})
        self._send({"error": "not found"}, status=404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if "--load" in sys.argv:  # headless load:  python3 server.py --load [ytd|1y|6m|3m]
        rest = [a for a in sys.argv[1:] if a in windows.WINDOWS]
        run_load(rest[0] if rest else windows.DEFAULT)
        sys.exit(0 if load_state["ok"] else 1)
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else PORT
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Serving on {url}")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    srv.serve_forever()
