"""Look-back windows: YTD, 1y, 6m, 3m."""
import calendar
from datetime import date

WINDOWS = {"ytd": "Year to date", "1y": "Last 12 months", "6m": "Last 6 months", "3m": "Last 3 months"}
DEFAULT = "1y"


def _months_back(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def cutoff(window: str, today: date = None) -> date:
    """First date (inclusive) covered by the window."""
    today = today or date.today()
    if window == "ytd":
        return date(today.year, 1, 1)
    return _months_back(today, {"1y": 12, "6m": 6, "3m": 3}[window])


def years(window: str, today: date = None):
    today = today or date.today()
    return list(range(cutoff(window, today).year, today.year + 1))
