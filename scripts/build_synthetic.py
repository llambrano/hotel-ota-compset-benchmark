#!/usr/bin/env python3
"""
Build the public page: dashboard.html (template) + the synthetic dataset -> index.html.

Refuses to write if the dataset is not flagged synthetic, or if any of the
synthetic-data disclaimers has gone missing from the template.

Usage:  python3 scripts/build_synthetic.py
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "dashboard.html")
DATA = os.path.join(ROOT, "data", "ota_benchmark_synthetic.json")
OUT = os.path.join(ROOT, "index.html")

REQUIRED = [                      # the page must say it is synthetic in all of these places
    'class="pill"',                                   # masthead badge
    "Synthetic data. Every hotel, brand, code",       # page footer
    "All data on this page is synthetic",             # how-to-read panel
    "Synthetic data: every hotel, brand, manager",    # PDF report footer
]

def main():
    data = json.load(open(DATA))
    if not data.get("synthetic"):
        sys.exit("refusing to build: dataset is not flagged synthetic")
    html = open(TEMPLATE, encoding="utf-8").read()
    missing = [s for s in REQUIRED if s not in html]
    if missing:
        sys.exit("refusing to build: disclaimer missing from template: " + "; ".join(missing))
    marker = "/*__DATA__*/null"
    if html.count(marker) != 1:
        sys.exit("template must contain exactly one data marker")
    out = html.replace(marker, json.dumps(data, separators=(",", ":")))
    open(OUT, "w", encoding="utf-8").write(out)
    print(f"{len(data['hotels'])} hotels, {data['months'][0]}..{data['months'][-1]} -> {OUT} ({os.path.getsize(OUT)/1e6:.2f} MB)")

if __name__ == "__main__":
    main()
