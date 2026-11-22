"""A self-contained, view-only copy of the board as one HTML file, and publishing it to GitHub.

The page is the live app with its data baked in: every API answer the page would ask for is embedded
as JSON, and fetch() is pointed at that, so it opens anywhere with no server. Load / Run analysis /
Copy / Log controls are hidden.

Publishing writes it to view_for_work.html at the repo root and commits and pushes only that file.
Emailing sends it as an attachment: through Gmail's SMTP server when SMTP_PASSWORD (a Gmail app
password) is in the environment or .env (how the GitHub Actions run sends it), otherwise through the
Mac's Mail app, from the first of EMAIL["from"] that Mail has set up.
"""
import json
import os
import re
import smtplib
import subprocess
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
EXPORTS = ROOT / "data" / "exports"
EMAIL = {"to": "ishwinder.sandhu@hsbc.com", "from": ["ishusandhu8@gmail.com", "is516@cantab.ac.uk"]}

SHIM = """<script>
// snapshot: answer the page's API calls from the data baked in below
window.SNAPSHOT = true;
(() => {
  const D = JSON.parse(document.getElementById("snapdata").textContent);
  // answer only once the whole page (including the inlined chart scripts) has loaded
  const ready = new Promise(r => document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", r) : r());
  const ok = body => ready.then(() => new Response(typeof body === "string" ? body : JSON.stringify(body),
    {status: 200, headers: {"Content-Type": "application/json"}}));
  window.fetch = (url) => {
    const u = new URL(url, "http://snapshot/"), p = u.pathname;
    if (p === "/api/summary") return ok(D.summary);
    if (p.startsWith("/api/member/")) return ok(D.members[p.split("/").pop()] || {speeches: [], votes: []});
    if (p === "/api/speech") return ok(D.speeches[u.searchParams.get("url")] || {text: "(not included in this snapshot)"});
    if (p === "/api/analysis") return ok(D.analysis);
    if (p.startsWith("/api/analysis/member/")) return ok(D.amembers[p.split("/").pop()] || {docs: []});
    if (p === "/api/load" || p === "/api/analyse") return ok({running: false, log: []});
    return ok({});
  };
  try { localStorage.setItem("window", D.window); localStorage.setItem("model", D.model); } catch {}
})();
</script>
<style>
  #load, #copyall, #logbtn, #windows, #analyse, #alogbtn, #model, #logwrap, #alogwrap, #publishbtn, #emailbtn { display: none !important; }
  .snapnote { font-size: 12.5px; color: var(--muted); }
</style>
"""


def _one_theme(page):
    """The snapshot has one fixed colour theme: no switch, and the theme isn't named anywhere in it."""
    page = re.sub(r"  /\* HSBC theme:.*?\*/\n", "", page, flags=re.S)
    page = re.sub(r'  <select id="skin".*?</select>\n', "", page)
    page = re.sub(r"// colour theme:.*?\n(?:.*Skin.*\n)+", "", page)
    page = page.replace('data-skin="hsbc"', 'data-skin="house"').replace('<html lang="en">', '<html lang="en" data-skin="house">')
    if re.search(r"hsbc|classic|setSkin|id=\"skin\"", page, re.I):
        raise RuntimeError("snapshot: theme switch not fully removed (static/index.html changed?)")
    return page


def build(window, model, summary, member, speech_rows, analysis_api):
    """HTML text of the snapshot. summary/member are server.py's functions; speech_rows the window's texts."""
    S = summary(window)
    data = {
        "window": window, "model": model, "summary": S,
        "members": {m["id"]: member(m["id"], window) for m in S["members"]},
        "speeches": {r["url"]: r for r in speech_rows},
        "analysis": None, "amembers": {},
    }
    if analysis_api:
        A = analysis_api.overview(model)
        A["run"] = {"running": False, "log": []}
        A["needs_password"] = False
        data["analysis"] = A
        if A.get("reading"):
            data["amembers"] = {m["id"]: analysis_api.member(model, m["id"]) for m in A["reading"]["members"]}
    page = _one_theme((ROOT / "static" / "index.html").read_text())
    for js in ("macro.js", "analysis.js"):
        page = page.replace(f'<script src="/static/{js}"></script>',
                            f"<script>\n{(ROOT / 'static' / js).read_text()}\n</script>")
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    taken = datetime.now().strftime("%d %b %Y %H:%M")
    page = page.replace("<title>FOMC Voters</title>", f"<title>FOMC board · {taken}</title>")
    page = page.replace("<h1>FOMC voters</h1>", f'<h1>FOMC voters <span class="snapnote">snapshot · {taken}</span></h1>')
    first_script = page.index("<script>")
    return page[:first_script] + f'<script id="snapdata" type="application/json">{blob}</script>\n' + SHIM + page[first_script:]


def save(html):
    EXPORTS.mkdir(parents=True, exist_ok=True)
    path = EXPORTS / f"FOMC-board-{datetime.now():%Y-%m-%d-%H%M}.html"
    path.write_text(html)
    return path


PUBLISH_FILE = "view_for_work.html"   # at the repo root


def _git(*args, timeout=120):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"git {args[0]} failed")
    return r.stdout.strip()


def publish(html):
    """Write view_for_work.html at the repo root, commit only that file and push it to GitHub."""
    path = ROOT / PUBLISH_FILE
    path.write_text(html)
    _git("add", "--", PUBLISH_FILE)
    if not _git("diff", "--cached", "--name-only", "--", PUBLISH_FILE):
        return {"ok": True, "unchanged": True, "file": PUBLISH_FILE}
    taken = datetime.now().strftime("%d %b %Y %H:%M")
    _git("commit", "-m", f"Update {PUBLISH_FILE} (board snapshot {taken})", "--", PUBLISH_FILE)
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    _git("pull", "--rebase", "--autostash", "origin", branch, timeout=180)  # the GitHub refresh run may have pushed one
    _git("push", "origin", branch, timeout=180)
    remote = _git("remote", "get-url", "origin").removesuffix(".git")
    return {"ok": True, "file": PUBLISH_FILE, "commit": _git("rev-parse", "--short", "HEAD"),
            "url": f"{remote}/blob/{branch}/{PUBLISH_FILE}"}


def _osa(script, timeout=60):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "osascript failed")
    return r.stdout.strip()


def mail_accounts():
    """Email addresses set up in the Mail app (asks macOS for permission the first time)."""
    out = _osa('tell application "Mail" to get email addresses of every account')
    return [a.strip().lower() for a in out.replace("{", "").replace("}", "").split(",") if a.strip()]


def _smtp_password():
    if os.environ.get("SMTP_PASSWORD"):
        return os.environ["SMTP_PASSWORD"]
    from dotenv import dotenv_values
    return dotenv_values(ROOT / ".env").get("SMTP_PASSWORD")


def _send_smtp(path, subject, body, password):
    sender = os.environ.get("SMTP_USER") or EMAIL["from"][0]
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, EMAIL["to"], subject
    msg.set_content(body)
    msg.add_attachment(Path(path).read_bytes(), maintype="text", subtype="html", filename=Path(path).name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(sender, password.replace(" ", ""))
        s.send_message(msg)
    return sender


def send(path, subject, body):
    """Email `path` as an attachment to EMAIL['to']; returns the sending address."""
    password = _smtp_password()
    if password:
        return _send_smtp(path, subject, body, password)
    have = mail_accounts()
    sender = next((a for a in EMAIL["from"] if a.lower() in have), None)
    if not sender:
        raise RuntimeError(f"Mail has none of {', '.join(EMAIL['from'])} set up (it has: {', '.join(have) or 'no accounts'})")
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    _osa(f'''
tell application "Mail"
    set m to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}" & return & return, visible:false}}
    set sender of m to "{sender}"
    tell m to make new to recipient at end of to recipients with properties {{address:"{EMAIL['to']}"}}
    tell content of m to make new attachment with properties {{file name:(POSIX file "{path}")}} at after last paragraph
    delay 2
    send m
end tell''', timeout=120)
    return sender


def email(html, window):
    """Save the snapshot to data/exports and email it to work."""
    path = save(html)
    taken = datetime.now().strftime("%d %b %Y")
    sender = send(str(path), f"FOMC board · {window} · {taken}",
                  "The FOMC voters board, view only. Open the attached HTML file in a browser.")
    return {"ok": True, "sender": sender, "to": EMAIL["to"], "file": path.name}
