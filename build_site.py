"""Build the standalone dashboard: one HTML file with the data embedded.

Combines index.html (the same page the claude.ai artifact shows), standalone/dash-lite.js
and data/*.json into site/index.html, which works on any static host or by double-clicking it.
Standard library only.

    python build_site.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SITE = HERE / "site"
DATASETS = [
    "fred_daily", "fred_weekly", "fred_monthly", "zip_realtor", "zillow_zip",
    "fred_policy", "fred_whitecollar", "indeed_postings", "infl_nowcast",
]


def script_safe(text):
    """Keep embedded text from closing the script tag it sits in."""
    return text.replace("</", "<\\/")


def main():
    report = json.loads((DATA / "changed.json").read_text(encoding="utf-8"))
    payload = {
        "run_at": report["run_at"],
        "failed": report.get("failed", {}),
        "datasets": {name: json.loads((DATA / f"{name}.json").read_text(encoding="utf-8")) for name in DATASETS},
    }
    page = (HERE / "index.html").read_text(encoding="utf-8")
    page = re.sub(r'^\s*<meta name="dash-one-writer">\s*', "", page)
    html = (HERE / "standalone" / "shell.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/", script_safe(json.dumps(payload, separators=(",", ":"), ensure_ascii=False)))
    html = html.replace("/*__RUNTIME__*/", (HERE / "standalone" / "dash-lite.js").read_text(encoding="utf-8"))
    html = html.replace("<!--__PAGE__-->", page)
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(html, encoding="utf-8")
    print(f"wrote {SITE / 'index.html'} ({len(html.encode()) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
