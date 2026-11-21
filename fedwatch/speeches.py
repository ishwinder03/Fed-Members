"""Speech listings per source, and full-text extraction from a speech page.

Every lister returns dicts: {url, person_id, date (YYYY-MM-DD), title, kind_hint}.
kind_hint is "speech", "statement" (a written statement explaining an FOMC vote)
or "essay"; after the page is fetched, items without real text become "no_text".
"""
import html
import json
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .people import PEOPLE, person_id

MIN_TEXT_CHARS = 1500  # below this the page is a blurb (e.g. video-only event), not a text

BOARD_LIST = "https://www.federalreserve.gov/newsevents/{year}-speeches.htm"
NY_LIST = "https://www.newyorkfed.org/newsevents/speeches/index"
CLEVELAND_LIST = "https://www.clevelandfed.org/collections/speeches"
CLEVELAND_API = ("https://www.clevelandfed.org/frbc/sitesearch/results?o=field.sortDate.desc&e=10&p={start}"
                 "&bcu=true&ppn=%2Fcollections%2Fspeeches&itemid=%7B7D253265-C90E-41F8-AD24-BBC7B68699B7%7D"
                 "&il=list&contentType=Speech&collection=Speeches")
PHILLY_LIST = "https://www.philadelphiafed.org/the-economy/speeches-anna-paulson"
DALLAS_LIST = "https://www.dallasfed.org/news/speeches/logan"
MINNEAPOLIS_LIST = "https://www.minneapolisfed.org/people/neel-kashkari"
MINNEAPOLIS_API = "https://www.minneapolisfed.org/api/ArticleList?itemId={item}&skip={skip}&take={take}"


def _ymd(yy_or_yyyy: str, mm: str, dd: str) -> str:
    y = yy_or_yyyy if len(yy_or_yyyy) == 4 else "20" + yy_or_yyyy
    return f"{y}-{mm}-{dd}"


def _statement_hint(title: str) -> str:
    return "statement" if re.match(r"\s*Statement\b", title or "", re.I) else "speech"


def list_board(fetch, years, since, issues):
    items, titles, seen = [], {}, set()
    for year in sorted(years, reverse=True):  # newest page first, so titles are current
        soup = BeautifulSoup(fetch(BOARD_LIST.format(year=year)), "html.parser")
        for a in soup.find_all("a", href=re.compile(rf"/newsevents/speech/[a-z]+{year}\d{{4}}[a-z]\.htm$")):
            # a speech can be linked twice (title link + "Video" link); the first is the title
            if a["href"] in seen:
                continue
            seen.add(a["href"])
            m = re.search(rf"/speech/([a-z]+)({year})(\d\d)(\d\d)[a-z]\.htm", a["href"])
            pid, date = m[1], _ymd(m[2], m[3], m[4])
            if date < since:
                continue
            row = a.find_parent(class_="row")
            speaker = row.find(class_="news__speaker").get_text(" ", strip=True) if row and row.find(class_="news__speaker") else ""
            if pid not in PEOPLE or PEOPLE[pid]["source"] != "board":
                issues.append(("board", f"speech URL prefix '{pid}' is not a known governor: {a['href']}"))
                continue
            # the URL is the key; the speaker line on the listing must name the same person
            if PEOPLE[pid]["names"][0].split()[-1] not in speaker:
                issues.append(("board", f"speaker line '{speaker}' does not match URL id '{pid}': {a['href']}"))
            if speaker and pid not in titles:  # listing is newest first: keep the current title
                titles[pid] = re.sub(r"\s*" + re.escape(PEOPLE[pid]["names"][0].split()[0]) + r".*$", "", speaker)
            items.append({"url": urljoin(BOARD_LIST, a["href"]), "person_id": pid, "date": date,
                          "title": a.get_text(" ", strip=True), "kind_hint": "speech"})
    return items, titles


def list_newyork(fetch, years, since, issues):
    soup = BeautifulSoup(fetch(NY_LIST), "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/newsevents/speeches/\d{4}/[a-z]+\d{6}[a-z]?$")):
        if a["href"] in seen:
            continue
        seen.add(a["href"])
        label = a.find_parent().get_text(" ", strip=True)
        m = re.match(r"([^:]+):\s*(.*)$", label)
        if not m or m[1].strip() != "Williams":
            continue  # other NY Fed staff
        d = re.search(r"/([a-z]+)(\d\d)(\d\d)(\d\d)[a-z]?$", a["href"])
        date = _ymd(d[2], d[3], d[4])
        if date < since:
            continue
        if d[1] != "wil":
            issues.append(("newyork", f"'Williams:' label on unexpected URL {a['href']}"))
        items.append({"url": urljoin(NY_LIST, a["href"]), "person_id": "williams",
                      "date": date, "title": m[2].strip(), "kind_hint": "speech"})
    return items


def list_cleveland(fetch, fetch_json, years, since, issues):
    page = fetch(CLEVELAND_LIST)
    m = re.search(r"<search-results[^>]*data-initialize='([^']*)'", page)
    if not m:
        issues.append(("cleveland", "embedded speech list not found on listing page"))
        return []
    data = json.loads(html.unescape(m[1]))
    results = list(data.get("results", []))
    start = 10
    # keep paging while the oldest item seen is still inside the window
    while results and results[-1].get("releaseDate", "")[:10] >= since and data["pagingInfo"].get("hasNextPage"):
        data = fetch_json(CLEVELAND_API.format(start=start))
        results += data.get("results", [])
        start += 10
    items = []
    for r in results:
        date = r.get("releaseDate", "")[:10]
        if date < since:
            continue
        authors = r.get("authors") or []
        if isinstance(authors, str):
            authors = re.findall(r"'label':\s*'([^']+)'", authors)
        else:
            authors = [x.get("label", "") for x in authors]
        if "hammack" not in {person_id(a) for a in authors}:
            continue  # other Cleveland Fed leaders
        items.append({"url": urljoin(CLEVELAND_LIST, r["url"]), "person_id": "hammack",
                      "date": date, "title": r["title"], "kind_hint": _statement_hint(r["title"])})
    return items


def list_philadelphia(fetch, years, since, issues):
    soup = BeautifulSoup(fetch(PHILLY_LIST), "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/the-economy/monetary-policy/\d{6}-")):
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)
        d = re.search(r"/(\d\d)(\d\d)(\d\d)-", href)
        date = _ymd(d[1], d[2], d[3])
        if date < since:
            continue
        items.append({"url": urljoin(PHILLY_LIST, href), "person_id": "paulson", "date": date,
                      "title": a.get_text(" ", strip=True), "kind_hint": "speech"})
    return items


def list_dallas(fetch, years, since, issues):
    soup = BeautifulSoup(fetch(DALLAS_LIST), "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/news/speeches/logan/\d{4}/lkl\d{6}")):
        href = a["href"].strip()
        if href in seen:
            continue
        seen.add(href)
        d = re.search(r"lkl(\d\d)(\d\d)(\d\d)", href)
        date = _ymd(d[1], d[2], d[3])
        if date < since:
            continue
        items.append({"url": urljoin(DALLAS_LIST, href), "person_id": "logan", "date": date,
                      "title": a.get_text(" ", strip=True), "kind_hint": "speech"})
    return items


def list_minneapolis(fetch, fetch_json, years, since, issues):
    """Kashkari's profile page has two lists, 'Essays' (written) and 'Speeches and Events'.
    The page only renders the newest few; the rest come from the ArticleList API that the
    page's 'Show Next 20 Items' button calls, paged until we pass the window start."""
    page = fetch(MINNEAPOLIS_LIST)
    lists = re.findall(r'"componentName":"ArticleListByTags","dataSource":"(\{[0-9A-Fa-f-]+\})"', page)
    if not lists:
        issues.append(("minneapolis", "article lists not found on profile page"))
        return []
    items, seen = [], set()
    for source_id in lists:
        skip = 0
        while True:
            data = fetch_json(MINNEAPOLIS_API.format(item=source_id, skip=skip, take=20))
            arts = data.get("Articles", [])
            for a in arts:
                href = a.get("url", "")
                if href in seen or not re.match(r"^/(speeches|article)/\d{4}/", href):
                    continue
                seen.add(href)
                try:
                    date = datetime.strptime(a["dateTimeText"].strip(), "%B %d, %Y").strftime("%Y-%m-%d")
                except (KeyError, ValueError):
                    issues.append(("minneapolis", f"no date on listing for {href}"))
                    continue
                if date < since:
                    continue
                items.append({"url": urljoin(MINNEAPOLIS_LIST, href), "person_id": "kashkari", "date": date,
                              "title": a.get("title", "").strip(),
                              "kind_hint": "essay" if href.startswith("/article/") else "speech"})
            skip += len(arts)
            last = arts[-1]["dateTimeText"] if arts else ""
            try:
                last_date = datetime.strptime(last.strip(), "%B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                last_date = ""
            if not arts or skip >= data.get("TotalCount", 0) or last_date < since:
                break
    return items


# ---------------------------------------------------------------- page text

BODY_SELECTORS = {
    "board": ["#article .col-md-8", "#article"],
    "newyork": [".ts-article-text"],
    "cleveland": [".component-content"],
    "philadelphia": [".article-body"],
    "dallas": [".dal-main-content"],
    "minneapolis": [".i9-c-rich-text-area"],
}
BLOCK_TAGS = ["p", "h2", "h3", "h4", "h5", "li", "blockquote"]


def _densest(soup):
    best, best_n = None, -1
    for e in soup.find_all(["div", "article", "section", "main"]):
        n = len(e.find_all("p", recursive=False))
        if n > best_n:
            best, best_n = e, n
    return best


def extract(page: str, source: str):
    """Return (title, clean_text). Picks the site's body container (falling back to the
    element with the most paragraphs) and joins its block elements in order."""
    soup = BeautifulSoup(page, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "button", "svg"]):
        t.decompose()
    for t in soup.select(".shareDL, .share, .social-share, .watchLive"):
        t.decompose()
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    containers = []
    for sel in BODY_SELECTORS.get(source, []):
        found = soup.select(sel)
        # multiple matching blocks (e.g. NY Fed splits text into sections): keep them all
        found = [f for f in found if not any(f is not g and g in f.parents for g in found)]
        if source != "newyork" and found:
            # other sites reuse the class for side boxes: keep the block with the most paragraphs
            found = [max(found, key=lambda f: len(f.find_all("p")))]
        if found and sum(len(f.find_all("p")) for f in found) >= 2:
            containers = found
            break
    if not containers:
        d = _densest(soup)
        containers = [d] if d else [soup]
    blocks = []
    for c in containers:
        for el in c.find_all(BLOCK_TAGS):
            if el.find_parent(BLOCK_TAGS):  # nested; parent already taken
                continue
            t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
            t = re.sub(r"\s*Return to text$", "", t)
            if t:
                blocks.append(t)
    if source == "newyork":
        for fn in soup.select("[class*=ts-footnote]"):
            t = re.sub(r"\s+", " ", fn.get_text(" ", strip=True))
            if t:
                blocks.append(t)
    # drop exact duplicate consecutive blocks
    out = [b for i, b in enumerate(blocks) if i == 0 or b != blocks[i - 1]]
    return title, "\n\n".join(out)
