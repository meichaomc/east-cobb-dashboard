"""Pull macro and East Cobb housing data for the East Cobb dashboard.

Writes one JSON file of rows per dataset into ./data, and lists the datasets
whose rows changed since the last run in data/changed.json, so the daily
refresh only uploads those. Standard library only.

    python fetch_data.py
"""
import csv
import datetime as dt
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
STATE = DATA / "_state.json"
HEADERS = {"User-Agent": "east-cobb-dashboard/1.0 (personal research script)"}

ZIPS = ["30068", "30062", "30066"]
MONTHS_KEPT = 37  # 24 months shown, plus 13 more so year-over-year changes have a base
DAYS_KEPT = 430   # daily/weekly series compared year over year: a year plus a margin

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
FRED_DAILY = ["OBMMIC30YF", "DGS10", "DGS2", "DFF", "BAMLH0A0HYM2", "SP500", "NASDAQCOM"]
FRED_WEEKLY = ["MORTGAGE30US", "MORTGAGE15US", "ICSA", "CCSA"]
FRED_MONTHLY = [
    # national
    "UNRATE", "PAYEMS", "CPIAUCSL", "CPILFESL", "HOUST", "PERMIT", "MSACSR", "EXHOSLUSM495S", "MTSDS133FMS",
    # Atlanta metro and Cobb County
    "ATXRSA", "ATLA013UR", "GACOBB0URN",
    # Realtor.com, Cobb County (FIPS 13067)
    "ACTLISCOU13067", "NEWLISCOU13067", "MEDDAYONMAR13067", "PRIREDCOU13067", "MEDLISPRI13067",
]
# rates and politics: long Treasuries, term premium, real yield, inflation expectations,
# next-meeting pricing, jumbo rate, policy uncertainty, VIX, dollar
FRED_POLICY = ["DGS30", "THREEFYTP10", "DFII10", "T10YIE", "T5YIFR", "DGS3MO", "USEPUINDXD", "OBMMIJUMBO30YF", "VIXCLS", "DTWEXBGS"]
FRED_POLICY_LONG = ["WSHOMCB"]  # Fed MBS holdings, weekly: a year shows the runoff
# white-collar jobs
FRED_WHITECOLLAR = [
    # unemployment: bachelor's degree+, management/professional occupations, duration
    "LNS14027662", "LNU04032215", "LNU04032216", "LNU04032217", "UEMPMED", "UEMP27OV",
    # JOLTS: professional & business services, information
    "JTS540099QUR", "JTU540099LDR", "JTS540099JOL", "JTU510099QUR", "JTU510099JOL",
    # payrolls: national and Atlanta
    "USINFO", "USFIRE", "CES6054150001", "CES6054000001", "ATLA013PBSV", "ATLA013FIRE", "ATLA013INFO",
]
FRED_WHITECOLLAR_LONG = ["GAICLAIMS"]  # Georgia initial claims, weekly, not seasonally adjusted
INDEED = ["IHLIDXUS", "IHLIDXUSGA"] + ["IHLIDXUSTP" + s for s in (
    "SOFTDEVE", "ITOPHE", "MATH", "MARK", "BAFI", "ACCO", "MANA", "PROJMANA", "LEGA", "PHSU")]

RDC_LATEST = "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Zip.csv"
RDC_HISTORY = "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Zip_History.csv"
RDC_FIELDS = {
    "median_listing_price": float,
    "median_listing_price_per_square_foot": float,
    "active_listing_count": int,
    "new_listing_count": int,
    "pending_listing_count": int,
    "median_days_on_market": float,
    "price_reduced_share": float,
    "pending_ratio": float,
}

ZILLOW = {
    "zhvi_sfr": "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfr_tier_0.33_0.67_sm_sa_month.csv",
    "zhvi_condo": "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_condo_tier_0.33_0.67_sm_sa_month.csv",
    "zori": "https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv",
    # top third of values, all homes: the $1M+ band in 30068 (about 125 MB, streamed)
    "zhvi_top": "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.67_1.0_sm_sa_month.csv",
}

# Cleveland Fed inflation nowcasts: one chart per target month, month-over-month and year-over-year files
# (about 8 MB each), with each release's actual value once it is out
NOWCAST_URL = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_{}.json"
NOWCAST_SERIES = {"CPI Inflation": "cpi", "Core CPI Inflation": "core_cpi", "PCE Inflation": "pce", "Core PCE Inflation": "core_pce"}
NOWCAST_MONTHS = 4  # target months kept: the ones still open plus the last released


def open_url(url, method="GET"):
    req = urllib.request.Request(url, headers=HEADERS, method=method)
    return urllib.request.urlopen(req, timeout=120)


def last_modified(url):
    with open_url(url, "HEAD") as r:
        return r.headers.get("Last-Modified", "")


def months_back(today, n):
    """First day of the month n months before today's month."""
    y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
    return dt.date(y, m + 1, 1)


def two_months_back(today):
    first = months_back(today, 2)
    for day in (today.day, 30, 29, 28):
        try:
            return first.replace(day=day)
        except ValueError:
            continue


def fred_rows(series, start):
    with open_url(FRED_CSV.format(id=series, start=start.isoformat())) as r:
        reader = csv.reader(io.TextIOWrapper(r, encoding="utf-8"))
        next(reader)
        rows = []
        for date, value in reader:
            if value in ("", "."):
                continue
            rows.append({"date": date, "series": series, "value": round(float(value), 4)})
    if not rows:
        raise RuntimeError(f"FRED returned no rows for {series}")
    return rows


def fred_dataset(ids, start):
    rows = []
    for series in ids:
        rows += fred_rows(series, start)
    return rows


def rdc_rows(url, cutoff):
    """Realtor.com zip rows for ZIPS from month `cutoff` on (yyyymm int)."""
    rows = []
    with open_url(url) as r:
        reader = csv.DictReader(io.TextIOWrapper(r, encoding="utf-8", newline=""))
        for rec in reader:
            if rec.get("postal_code") not in ZIPS:
                continue
            ym = rec["month_date_yyyymm"]
            if not ym.isdigit() or int(ym) < cutoff:
                continue
            row = {"date": f"{ym[:4]}-{ym[4:]}-01", "zip": rec["postal_code"]}
            for field, cast in RDC_FIELDS.items():
                raw = rec.get(field, "")
                row[field] = cast(float(raw)) if raw not in ("", "NA") else None
            rows.append(row)
    return rows


def zillow_rows(series, url, cutoff):
    rows = []
    with open_url(url) as r:
        reader = csv.reader(io.TextIOWrapper(r, encoding="utf-8", newline=""))
        header = next(reader)
        name_col = header.index("RegionName")
        date_cols = [(i, h) for i, h in enumerate(header) if h[:4].isdigit() and h >= cutoff]
        for rec in reader:
            zip_code = rec[name_col].zfill(5)
            if zip_code not in ZIPS:
                continue
            for i, h in date_cols:
                if rec[i]:
                    rows.append({"date": h[:7] + "-01", "zip": zip_code, "series": series, "value": round(float(rec[i]), 1)})
    if not rows:
        raise RuntimeError(f"Zillow {series} had no rows for {ZIPS}")
    return rows


def nowcast_values(kind):
    """{(target month, date, measure, actual?): value} from one Cleveland Fed chart file."""
    with open_url(NOWCAST_URL.format(kind)) as r:
        charts = json.loads(r.read().decode("utf-8-sig"))
    out = {}
    for chart in charts[-NOWCAST_MONTHS:]:
        year, month = (int(x) for x in chart["chart"]["subcaption"].split("-"))
        labels = [c["label"] for c in chart["categories"][0]["category"] if not c.get("vline")]
        for series in chart["dataset"]:
            name = series["seriesname"]
            measure = NOWCAST_SERIES.get(name.removeprefix("Actual "))
            if measure is None:
                continue
            for label, point in zip(labels, series["data"]):
                if point.get("value") in ("", None):
                    continue
                m, d = (int(x) for x in label.split("/"))
                day = f"{year + (m < month)}-{m:02d}-{d:02d}"  # a target month's nowcasts run into the next month
                out[(f"{year}-{month:02d}", day, measure, name.startswith("Actual "))] = round(float(point["value"]), 3)
    return out


def nowcast_rows():
    mom, yoy = nowcast_values("month"), nowcast_values("year")
    rows = [{"target": t, "date": d, "measure": m, "kind": "actual" if a else "nowcast", "mom": v, "yoy": yoy.get((t, d, m, a))}
            for (t, d, m, a), v in mom.items()]
    if not rows:
        raise RuntimeError("Cleveland Fed nowcast files had no values")
    return sorted(rows, key=lambda r: (r["target"], r["measure"], r["kind"], r["date"]))


def load(name):
    path = DATA / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main():
    DATA.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    today = dt.date.today()
    window = two_months_back(today)
    monthly_start = months_back(today, MONTHS_KEPT)
    year_start = today - dt.timedelta(days=DAYS_KEPT)
    results, failures = {}, {}

    def build(name, fn):
        try:
            results[name] = fn()
        except Exception as e:  # keep yesterday's file when a source is down
            failures[name] = f"{type(e).__name__}: {e}"

    build("fred_daily", lambda: fred_dataset(FRED_DAILY, window))
    build("fred_weekly", lambda: fred_dataset(FRED_WEEKLY, window))
    build("fred_monthly", lambda: fred_dataset(FRED_MONTHLY, monthly_start))
    build("fred_policy", lambda: fred_dataset(FRED_POLICY, window) + fred_dataset(FRED_POLICY_LONG, year_start))
    build("fred_whitecollar", lambda: fred_dataset(FRED_WHITECOLLAR, monthly_start) + fred_dataset(FRED_WHITECOLLAR_LONG, year_start))
    build("indeed_postings", lambda: [{**r, "value": round(r["value"], 2)} for r in fred_dataset(INDEED, year_start)])
    build("infl_nowcast", nowcast_rows)

    def realtor():
        cutoff = int(monthly_start.strftime("%Y%m"))
        old = load("zip_realtor")
        stamp = last_modified(RDC_LATEST)
        if old is None:
            rows = rdc_rows(RDC_HISTORY, cutoff)
        elif stamp == state.get("rdc_modified"):
            rows = old
        else:
            latest = rdc_rows(RDC_LATEST, cutoff)
            fresh = {(r["date"], r["zip"]) for r in latest}
            rows = [r for r in old if (r["date"], r["zip"]) not in fresh] + latest
        state["rdc_modified"] = stamp
        cutoff_date = monthly_start.isoformat()
        return sorted((r for r in rows if r["date"] >= cutoff_date), key=lambda r: (r["date"], r["zip"]))

    build("zip_realtor", realtor)

    def zillow():
        old = load("zillow_zip")
        stamps = {k: last_modified(u) for k, u in ZILLOW.items()}
        if old is not None and stamps == state.get("zillow_modified"):
            return old
        cutoff = monthly_start.strftime("%Y-%m")
        rows = []
        for series, url in ZILLOW.items():
            rows += zillow_rows(series, url, cutoff)
        state["zillow_modified"] = stamps
        return sorted(rows, key=lambda r: (r["series"], r["zip"], r["date"]))

    build("zillow_zip", zillow)

    changed = []
    hashes = state.setdefault("hashes", {})
    for name, rows in results.items():
        text = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest != hashes.get(name) or not (DATA / f"{name}.json").exists():
            (DATA / f"{name}.json").write_text(text, encoding="utf-8")
            hashes[name] = digest
            changed.append(name)

    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    report = {"run_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "changed": changed, "failed": failures}
    (DATA / "changed.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if failures and not results else 0


if __name__ == "__main__":
    sys.exit(main())
