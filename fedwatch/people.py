"""Identity registry: maps the exact name strings the Fed publishes to a fixed person id.

This is NOT the list of voters. Who votes is derived from the FOMC statements and
minutes; this table only says which id a printed name belongs to, and where that
person's speeches are published. A name that is not listed here is reported as an
issue instead of being fuzzy-matched.
"""
import re
import unicodedata

PEOPLE = {
    # Board of Governors (speeches on federalreserve.gov; URL prefix == id)
    "warsh":     {"names": ["Kevin Warsh", "Kevin M. Warsh"], "institution": "Board of Governors", "source": "board"},
    "powell":    {"names": ["Jerome H. Powell"], "institution": "Board of Governors", "source": "board"},
    "jefferson": {"names": ["Philip N. Jefferson"], "institution": "Board of Governors", "source": "board"},
    "bowman":    {"names": ["Michelle W. Bowman"], "institution": "Board of Governors", "source": "board"},
    "barr":      {"names": ["Michael S. Barr"], "institution": "Board of Governors", "source": "board"},
    "cook":      {"names": ["Lisa D. Cook"], "institution": "Board of Governors", "source": "board"},
    "waller":    {"names": ["Christopher J. Waller"], "institution": "Board of Governors", "source": "board"},
    "miran":     {"names": ["Stephen I. Miran"], "institution": "Board of Governors", "source": "board"},
    # Reserve Bank presidents
    "williams":  {"names": ["John C. Williams"], "institution": "Federal Reserve Bank of New York", "source": "newyork"},
    "hammack":   {"names": ["Beth M. Hammack"], "institution": "Federal Reserve Bank of Cleveland", "source": "cleveland"},
    "paulson":   {"names": ["Anna Paulson"], "institution": "Federal Reserve Bank of Philadelphia", "source": "philadelphia"},
    "logan":     {"names": ["Lorie K. Logan"], "institution": "Federal Reserve Bank of Dallas", "source": "dallas"},
    "kashkari":  {"names": ["Neel Kashkari"], "institution": "Federal Reserve Bank of Minneapolis", "source": "minneapolis"},
    # 2025 rotating voters: their votes are kept, their speeches are not collected (source None)
    "collins":   {"names": ["Susan M. Collins"], "institution": "Federal Reserve Bank of Boston", "source": None},
    "goolsbee":  {"names": ["Austan D. Goolsbee"], "institution": "Federal Reserve Bank of Chicago", "source": None},
    "musalem":   {"names": ["Alberto G. Musalem"], "institution": "Federal Reserve Bank of St. Louis", "source": None},
    "schmid":    {"names": ["Jeffrey R. Schmid"], "institution": "Federal Reserve Bank of Kansas City", "source": None},
}

_BY_NAME = {}
for _pid, _p in PEOPLE.items():
    for _n in _p["names"]:
        _BY_NAME[_n.lower()] = _pid


def normalize_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).replace(" ", " ")
    name = re.sub(r"\s+", " ", name).strip(" .,;")
    name = re.sub(r"^and\s+", "", name)
    return name


def person_id(name: str):
    """Exact (case-insensitive) lookup. Returns None for an unknown name."""
    return _BY_NAME.get(normalize_name(name).lower())


def display_name(pid: str) -> str:
    return PEOPLE[pid]["names"][0] if pid in PEOPLE else pid
