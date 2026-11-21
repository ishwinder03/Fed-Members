"""FOMC calendar, statement and minutes parsing, and per-meeting roster assembly."""
import html
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .people import normalize_name

BASE = "https://www.federalreserve.gov"
CALENDAR_URL = BASE + "/monetarypolicy/fomccalendars.htm"
ROLE_SUFFIX = re.compile(r",\s*(Chairman|Chair|Vice Chair)\s*$")


def _clean(text: str) -> str:
    text = html.unescape(text).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def calendar_meetings(page: str, year: int):
    """Return [{date, statement_url, minutes_url}] for each meeting with an HTML statement."""
    soup = BeautifulSoup(page, "html.parser")
    meetings = {}
    for a in soup.find_all("a", href=re.compile(rf"/newsevents/pressreleases/monetary{year}\d{{4}}a\.htm$")):
        # only the link labelled as the Statement (not the implementation note)
        if "Statement" not in a.find_parent().get_text(" ", strip=True):
            continue
        d = re.search(r"monetary(\d{4})(\d{2})(\d{2})a", a["href"])
        date = f"{d[1]}-{d[2]}-{d[3]}"
        meetings[date] = {"date": date, "statement_url": urljoin(BASE, a["href"]), "minutes_url": None}
    for a in soup.find_all("a", href=re.compile(rf"/monetarypolicy/fomcminutes{year}\d{{4}}\.htm$")):
        d = re.search(r"fomcminutes(\d{4})(\d{2})(\d{2})", a["href"])
        date = f"{d[1]}-{d[2]}-{d[3]}"
        if date in meetings:
            meetings[date]["minutes_url"] = urljoin(BASE, a["href"])
    return [meetings[k] for k in sorted(meetings)]


def split_names(chunk: str):
    """'A, Chair; B; and C'  or  'A, B, and C'  or  'A and B'  ->  [(name, role)]"""
    chunk = _clean(chunk).rstrip(".")
    parts = chunk.split(";") if ";" in chunk else re.split(r",\s*(?:and\s+)?|\s+and\s+", chunk)
    out = []
    for p in parts:
        p = normalize_name(p)
        if not p:
            continue
        role = None
        m = ROLE_SUFFIX.search(p)
        if m:
            role = "Chair" if m[1].startswith("Chair") else "Vice Chair"
            p = p[: m.start()]
        # a ";"-separated item can still hold "X and Y"
        for q in re.split(r"\s+and\s+", p):
            q = normalize_name(q)
            if q:
                out.append((q, role))
    return out


PERSON_NAME = re.compile(r"[A-Z][a-z]+(?:\s+[A-Z]\.)*\s+[A-Z][a-zA-Z'’\-]+")


def parse_dissents(chunk: str):
    """'X and Y, who preferred ...; and Z, who supported ...'  ->  {name: 'preferred ...'}

    Groups are separated by ';' or ', and' depending on the statement, so the text is cut
    at each ', who': whatever precedes the first person name in a segment is the previous
    group's reason, and the names from there on belong to the next group."""
    chunk = _clean(chunk)
    if re.fullmatch(r"None\s*\.?", chunk):
        return {}
    markers = list(re.finditer(r",?\s+who\s+", chunk))
    if not markers:
        return {n: "" for n, _ in split_names(chunk)}
    result, pending, pos = {}, [], 0
    for m in markers:
        seg = chunk[pos:m.start()]
        first = PERSON_NAME.search(seg)
        if pending:
            reason = seg[: first.start()] if first else seg
            reason = re.sub(r"[;,]?\s*(?:and)?\s*$", "", reason).rstrip(".")
            for n in pending:
                result[n] = reason
        names_text = seg[first.start():] if first else ""
        pending = [n for n, _ in split_names(names_text)]
        pos = m.end()
    for n in pending:
        result[n] = chunk[pos:].strip().rstrip(".")
    return result


def _fraction(s: str) -> float:
    """'1/4' -> 0.25, '3-3/4' -> 3.75, '1' -> 1.0 (also handles a non-breaking hyphen)."""
    s = s.replace("‑", "-").strip()
    m = re.fullmatch(r"(\d+)(?:-(\d+)/(\d+))?", s)
    if m:
        return int(m[1]) + (int(m[2]) / int(m[3]) if m[2] else 0)
    m = re.fullmatch(r"(\d+)/(\d+)", s)
    return int(m[1]) / int(m[2])


def parse_decision(text: str):
    """-> {'decision': hike|cut|hold, 'bps': int, 'range': '3-3/4 to 4 percent'} or None"""
    text = text.replace("‑", "-")
    m = re.search(r"decided to (raise|lower|maintain) the target range for the federal funds rate"
                  r"(?: by ([\d/\-]+) percentage points?)?\s+(?:to|at) ([\d/\-]+ to [\d/\-]+) percent", text)
    if not m:
        return None
    bps = round(_fraction(m[2]) * 100) if m[2] else 0
    return {"decision": {"raise": "hike", "lower": "cut", "maintain": "hold"}[m[1]], "bps": bps,
            "range": m[3] + " percent"}


def parse_statement(page: str):
    soup = BeautifulSoup(page, "html.parser")
    article = soup.find(id="article") or soup
    text = _clean(article.get_text(" "))
    tally = re.search(r"by an?\s+(\d+)\s*[–—-]\s*(\d+)\s+vote", text)
    voting_for, roles, dissents = None, {}, {}
    for p in article.find_all("p"):
        t = _clean(p.get_text(" "))
        m = re.search(r"Voting for (?:the monetary policy|this) action were (.*?)\.(?=\s*Voting against|\s*$)", t)
        if m:
            voting_for = []
            for name, role in split_names(m[1]):
                voting_for.append(name)
                if role:
                    roles[name] = role
        m = re.search(r"Voting against (?:the monetary policy|this) action (?:were|was) (.*)$", t)
        if m:
            dissents = parse_dissents(m[1])
    return {
        "tally": (int(tally[1]), int(tally[2])) if tally else None,
        "decision": parse_decision(text),
        "voting_for": voting_for,
        "dissents": dissents,
        "roles": roles,
    }


def parse_minutes(page: str):
    """Minutes are used for names only (who voted for / against); dissent wording comes
    from the statement. The 'against' paragraph comes in several layouts, so dissenter
    names are pulled out with a person-name pattern and then must resolve in the registry."""
    soup = BeautifulSoup(page, "html.parser")
    article = soup.find(id="article") or soup
    text = _clean(article.get_text(" "))
    blocks = []
    paras = [_clean(p.get_text(" ")) for p in article.find_all("p")]
    for i, t in enumerate(paras):
        m = re.match(r"Voting for this action\s*:\s*(.*)$", t)
        if not m:
            continue
        voters = [n for n, _ in split_names(m[1])]
        against = {}
        nxt = paras[i + 1] if i + 1 < len(paras) else ""
        m2 = re.match(r"Voting against this action\s*:\s*(.*)$", nxt)
        if m2:
            body = re.split(r"\s*Consistent with the Committee", m2[1])[0]
            if not re.match(r"None\s*\.?\s*$", body):
                for seg in re.split(r",?\s+who\s+(?:preferred|supported)", body):
                    for name in PERSON_NAME.findall(seg):
                        against[normalize_name(name)] = ""
        blocks.append((voters, against, t))
    # the monetary policy vote is the one with the full committee
    blocks.sort(key=lambda b: len(b[0]) + len(b[1]), reverse=True)
    roles = {}
    att = re.search(r"Attendance\s+(.*?)\s+(?:Alternate Members|Joint Meeting|Developments)", text)
    if att:
        for m in re.finditer(r"([A-Z][\w.\- ]+?),\s*(Chairman|Chair|Vice Chair)\b", att[1][:600]):
            roles[normalize_name(m[1])] = "Chair" if m[2].startswith("Chair") else "Vice Chair"
    if not blocks:
        return {"voting_for": None, "dissents": {}, "roles": roles}
    voters, against, _ = blocks[0]
    return {"voting_for": voters, "dissents": against, "roles": roles}


def build_roster(statement, minutes, previous_roster):
    """Combine sources into {name: (vote, dissent_text)} plus source label and check notes."""
    notes = []
    st_dissents = statement["dissents"]
    if statement["voting_for"]:
        source = "statement"
        roster = {n: ("for", None) for n in statement["voting_for"]}
        if minutes and minutes["voting_for"]:
            if set(minutes["voting_for"]) != set(statement["voting_for"]):
                notes.append("minutes 'voting for' list differs from statement")
    elif minutes and minutes["voting_for"]:
        source = "minutes"
        roster = {n: ("for", None) for n in minutes["voting_for"]}
    elif previous_roster:
        source = "provisional"
        roster = {n: ("for", None) for n in previous_roster}
        notes.append("minutes not yet published: 'for' votes assumed from previous meeting's roster")
    else:
        return None, "none", ["no source names the voters"]

    for name, reason in st_dissents.items():
        roster[name] = ("against", reason)
    if minutes and minutes["voting_for"] is not None:
        if set(minutes["dissents"]) != set(st_dissents):
            notes.append(f"minutes dissenters {sorted(minutes['dissents'])} != statement {sorted(st_dissents)}")
        for name in minutes["dissents"]:
            if name not in roster or roster[name][0] != "against":
                roster[name] = ("against", "(reason not stated in statement; see minutes)")
    return roster, source, notes
