"""Economic data the FOMC reacts to: inflation (CPI, PCE) and the jobs report.

- Inflation: the Cleveland Fed's inflation-nowcasting file. For every month it has the daily nowcast,
  the actual figure and the release date of CPI and PCE. "Expected" = the last nowcast before release.
- Jobs: the BLS public API (no key; 25 requests a day). Payrolls, unemployment rate, hourly earnings.
  There is no free consensus forecast, so "expected" is the trend: the previous 3 months' average for
  payrolls and earnings, the previous month for unemployment. Values are as revised today, not first prints.
  Release dates follow the BLS rule: the third Friday after the week that includes the 12th.
"""
import re
from datetime import date, timedelta

NOWCAST_URL = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en"
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# series id -> (label, unit, source)
SERIES = {
    "cpi": ("CPI", "% m/m", "Cleveland Fed nowcast / BLS"),
    "core_cpi": ("Core CPI", "% m/m", "Cleveland Fed nowcast / BLS"),
    "pce": ("PCE", "% m/m", "Cleveland Fed nowcast / BEA"),
    "core_pce": ("Core PCE", "% m/m", "Cleveland Fed nowcast / BEA"),
    "payrolls": ("Payrolls", "k change", "BLS"),
    "unemployment": ("Unemployment rate", "%", "BLS"),
    "wages": ("Average hourly earnings", "% m/m", "BLS"),
}
NOWCAST_NAMES = {"cpi": "CPI Inflation", "core_cpi": "Core CPI Inflation", "pce": "PCE Inflation",
                 "core_pce": "Core PCE Inflation"}
BLS_IDS = {"CES0000000001": "payrolls", "LNS14000000": "unemployment", "CES0500000003": "wages"}


def _label_date(label, target_year, target_month):
    """'09/11' on the chart for target month 2026-8 -> 2026-09-11 (handles the year turn)."""
    m, d = (int(x) for x in label.split("/"))
    year = target_year + (1 if m < target_month - 6 else -1 if m > target_month + 6 else 0)
    return date(year, m, d)


def inflation(nowcast_json, since):
    """Rows {series, period, actual, expected, expected_kind, release_date} for months >= since (YYYY-MM)."""
    releases = {}   # ("CPI", "2026-08") -> release date
    charts = {}
    for c in nowcast_json:
        y, m = (int(x) for x in c["chart"]["subcaption"].split("-"))
        cats = c["categories"][0]["category"]
        days = []
        for k in cats:
            if k.get("vline"):
                kind, mon = k["label"].split()  # "CPI Aug" / "PCE Jul"
                if days:
                    mi = MONTHS.index(mon) + 1
                    ry = days[-1].year - (1 if mi > days[-1].month else 0)
                    releases[(kind, f"{ry}-{mi:02d}")] = days[-1]
            else:
                days.append(_label_date(k["label"], y, m))
        charts[f"{y}-{m:02d}"] = (days, {ds["seriesname"]: [v.get("value") for v in ds["data"]] for ds in c["dataset"]})
    rows = []
    for period, (days, data) in charts.items():
        if period < since:
            continue
        for sid, name in NOWCAST_NAMES.items():
            actual = next((float(v) for v in data.get("Actual " + name, []) if v not in ("", None)), None)
            rel = releases.get(("CPI" if "cpi" in sid else "PCE", period))
            now = data.get(name, [])
            before = [float(v) for d, v in zip(days, now) if v not in ("", None) and (rel is None or d < rel)]
            if actual is None and not before:
                continue
            rows.append({"series": sid, "period": period, "actual": actual, "expected": before[-1] if before else None,
                         "expected_kind": "nowcast", "release_date": rel.isoformat() if rel else None})
    return rows


def jobs_release_date(year, month):
    """Employment Situation for a month: the third Friday after the reference week (the Sunday-Saturday
    week containing the 12th)."""
    d12 = date(year, month, 12)
    offset = -1 if d12.weekday() == 5 else (4 - d12.weekday()) % 7   # that week's Friday
    return d12 + timedelta(days=offset + 21)


def _next(period):
    y, m = (int(x) for x in period.split("-"))
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def jobs(bls_json, since):
    rows = []
    for s in bls_json["Results"]["series"]:
        sid = BLS_IDS[s["seriesID"]]
        vals = {f"{x['year']}-{x['period'][1:]}": float(x["value"]) for x in s["data"]
                if re.match(r"M\d\d$", x["period"]) and re.match(r"-?[\d.]+$", x["value"])}  # "-" = not published
        ks = sorted(vals)
        level = {k: vals[k] for k in ks}
        if sid == "payrolls":
            series = {k: level[k] - level[p] for p, k in zip(ks, ks[1:]) if _next(p) == k}   # monthly change, thousands
        elif sid == "wages":
            series = {k: (level[k] / level[p] - 1) * 100 for p, k in zip(ks, ks[1:]) if _next(p) == k}
        else:
            series = level
        sk = sorted(series)
        for i, k in enumerate(sk):
            if k < since:
                continue
            prev = [series[x] for x in sk[max(0, i - 3):i]]
            expected = (prev[-1] if sid == "unemployment" else sum(prev) / len(prev)) if prev else None
            y, m = (int(x) for x in k.split("-"))
            rows.append({"series": sid, "period": k, "actual": round(series[k], 3), "expected":
                         None if expected is None else round(expected, 3), "expected_kind": "trend",
                         "release_date": jobs_release_date(y, m).isoformat()})
    return rows
