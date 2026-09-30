#!/usr/bin/env python3
"""
Production build: read an OTA's monthly partner production extracts and build the page.

Each monthly workbook has one sheet with a two-row header: a group row
(Room Nights, Hotel Revenue, ADR, Package, Mobile, ...) above a sub-header row
(value, YoY, Compset YoY / vs Compset pp). The parser matches headers by name,
not position, so column order can change between months without breaking it.

Inputs (none of them are in this repository):
  raw/<year>/YYYY MM - Monthly OTA Production.xlsx     the monthly extracts
  config/hotel_master.csv                              OTA ID -> hotel code, manager, tier

Output: ota_benchmark.json and ota-compset-benchmark.html (the template with the data embedded).

Usage:  python3 scripts/build_dashboard.py [--months 12] [--sheet "Last Month Booked"]
Requires Python 3 with openpyxl.
"""
import argparse, csv, glob, json, os, re, datetime
import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
MASTER = os.path.join(ROOT, "config", "hotel_master.csv")
TEMPLATE = os.path.join(ROOT, "dashboard.html")
OUT_JSON = os.path.join(ROOT, "ota_benchmark.json")
OUT_HTML = os.path.join(ROOT, "ota-compset-benchmark.html")

# (group header, sub header) -> metric key; headers are matched after normalising case and spaces
SUBMAP = {
    ("room nights", "nrn"): "nrn", ("room nights", "yoy"): "nrn_yoy", ("room nights", "compset yoy"): "nrn_cs",
    ("hotel revenue", "hotel revenue"): "rev", ("hotel revenue", "yoy"): "rev_yoy", ("hotel revenue", "compset yoy"): "rev_cs",
    ("adr", "adr"): "adr", ("adr", "yoy"): "adr_yoy", ("adr", "compset yoy"): "adr_cs",
    ("length of stay", "avg los"): "los", ("length of stay", "yoy (days)"): "los_yoy", ("length of stay", "vs compset (days)"): "los_cs",
    ("booking window", "avg bw"): "bw", ("booking window", "yoy (days)"): "bw_yoy", ("booking window", "vs compset (days)"): "bw_cs",
}
# share-of-bookings groups: level ("... share"/"... mix"), "yoy pp", "vs compset pp"
SHARE_GROUPS = {"package": "pkg", "visibility boost": "boost", "sponsored listings": "spon", "mobile": "mob",
                "international": "intl", "cancellations": "cxl", "refundable rate plans": "ref"}
PROPERTY = {"property id": "id", "property name": "name", "hotel code": "code", "brand name": "brand",
            "super region": "sregion", "region": "region", "country": "country", "market": "market"}
TEXT = set(PROPERTY.values())

def norm(s): return re.sub(r"\s+", " ", str(s or "")).strip().lower()

def num(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip()
    if s.upper() in ("N/A", "NA", "-", "—", "#N/A", "NULL"): return None
    try: return float(s.replace(",", "").replace("%", ""))
    except ValueError: return None

def r6(x): return None if x is None else float(f"{x:.6g}")

def find_reports():
    out = {}
    for f in glob.glob(os.path.join(RAW, "*", "* - Monthly OTA Production.*")):
        m = re.match(r"(\d{4}) (\d{2}) - ", os.path.basename(f))
        if m: out[f"{m.group(1)}-{m.group(2)}"] = f
    return dict(sorted(out.items()))

def read_report(path, sheet):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)[sheet]
    rows = ws.iter_rows(values_only=True)
    top = sub = None
    for r in rows:                                   # first row with 5+ filled cells is the group header
        if sum(1 for c in r if c not in (None, "")) >= 5: top = r; sub = next(rows); break
    if top is None: raise RuntimeError(f"no header in {path}")
    cols, cur = {}, None
    for i, (t, s) in enumerate(zip(top, sub)):
        if t not in (None, ""): cur = norm(t)       # group headers are merged cells: carry forward
        if s in (None, ""): continue
        sn = norm(s); key = SUBMAP.get((cur, sn))
        if key is None and cur in SHARE_GROUPS:
            g = SHARE_GROUPS[cur]
            key = g if sn.endswith(("share", "mix")) else g + "_yoy" if sn == "yoy pp" else g + "_cs" if sn == "vs compset pp" else None
        if key is None and cur == "property": key = PROPERTY.get(sn)
        if key: cols[key] = i
    hotels = {}
    for r in rows:
        pid = r[cols["id"]]
        if pid in (None, "") or not str(pid).strip().isdigit(): continue   # skips subtotal and blank rows
        d = {}
        for k, i in cols.items():
            v = r[i]
            d[k] = (str(v).strip() if v not in (None, "") else None) if k in TEXT else r6(num(v))
        hotels[str(pid).strip()] = d
    return hotels

def load_master():
    info = {}
    if os.path.exists(MASTER):
        with open(MASTER, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                info[r["ota_id"].strip()] = {"code": r.get("hotel_code", "").strip().upper(),
                                             "mgr": r.get("manager", "").strip(), "tier": r.get("tier", "").strip()}
    return info

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--sheet", default="Last Month Booked"); a = ap.parse_args()
    reports = find_reports(); months = list(reports)[-a.months:]
    if not months: raise SystemExit(f"no reports found under {RAW}")
    per_month = {ym: read_report(reports[ym], a.sheet) for ym in months}
    master = load_master()
    keys = sorted({k for d in per_month.values() for h in d.values() for k in h if k not in TEXT})
    hotels = []
    for pid in sorted({p for d in per_month.values() for p in d}, key=int):
        latest = next(per_month[ym][pid] for ym in reversed(months) if pid in per_month[ym])
        m = master.get(pid, {})
        hotels.append({"id": pid, "name": latest.get("name"), "code": m.get("code") or (latest.get("code") or "").upper() or None,
                       "brand": latest.get("brand"), "sregion": latest.get("sregion"), "region": latest.get("region"),
                       "country": latest.get("country"), "market": latest.get("market"),
                       "mgr": m.get("mgr", ""), "tier": m.get("tier", ""),
                       "d": {k: [per_month[ym].get(pid, {}).get(k) for ym in months] for k in keys}})
    used = sorted({k for h in hotels for k, v in h["d"].items() if any(x is not None for x in v)})
    for h in hotels: h["d"] = {k: v for k, v in h["d"].items() if k in used}
    data = {"asOf": months[-1], "built": datetime.date.today().isoformat(), "months": months, "metrics": used, "hotels": hotels}
    json.dump(data, open(OUT_JSON, "w"), separators=(",", ":"))
    html = open(TEMPLATE, encoding="utf-8").read().replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    open(OUT_HTML, "w", encoding="utf-8").write(html)
    print(f"{len(hotels)} hotels, {months[0]}..{months[-1]} -> {OUT_HTML}")

if __name__ == "__main__":
    main()
