"""Load, Run analysis and refresh view_for_work.html in one go, with no browser: what the GitHub Actions
"Refresh board" workflow runs (and works the same on the Mac).

    python3 refresh.py [--window 6m] [--model M] [--email]

Writes view_for_work.html at the repo root (the workflow commits and pushes it). --email also sends it
to work; on GitHub that needs the SMTP_PASSWORD secret (a Gmail app password), otherwise it is skipped.
"""
import sys

import server
import snapshot
from fedwatch import windows


def main(argv):
    opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
    window = opt("--window", "6m")
    if window not in windows.WINDOWS:
        sys.exit(f"--window must be one of {', '.join(windows.WINDOWS)}")
    if not server.analysis_api:
        sys.exit("Analysis unavailable (pip install -r requirements.txt)")
    model = opt("--model") or server.analysis_api.CONFIG["model"]

    print(f"== Load ({window})", flush=True)
    server.run_load(window)
    if not server.load_state["ok"]:
        print("Load finished with errors; carrying on with what was collected", flush=True)

    print(f"== Analysis ({model})", flush=True)
    from analysis import run
    run.run(model=model, log=lambda line: print(line, flush=True))

    print("== Snapshot", flush=True)
    html = server.snapshot_html(window, model)
    (snapshot.ROOT / snapshot.PUBLISH_FILE).write_text(html)
    print(f"Wrote {snapshot.PUBLISH_FILE} ({len(html) / 1e6:.1f} MB)", flush=True)

    if "--email" in argv:
        if not snapshot._smtp_password() and sys.platform != "darwin":
            print("Email skipped: add the SMTP_PASSWORD secret (a Gmail app password) to send from GitHub", flush=True)
        else:
            r = snapshot.email(html, window)
            print(f"Emailed {r['file']} to {r['to']} from {r['sender']}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
