#!/usr/bin/env python3
"""
Synthetic data generator for the OTA Compset Benchmark.

Writes data/ota_benchmark_synthetic.json in exactly the shape the dashboard
expects (the same shape build_dashboard.py produces from real OTA exports),
for a fictional portfolio of hotels. Every hotel, brand, code, manager and
number here is invented. Seeded, so the output is reproducible.

What the generator models:
  * Hotel size    lognormal monthly room nights, so small hotels swing hard on YoY
  * Seasonality   city, resort and airport demand shapes, peaking in different months
  * Market trend  one compset growth path per market, shared by its hotels
  * Hotel skill   a persistent gap to compset plus AR(1) month-to-month drift,
                  which is what makes "ahead in 8 of 12 months" a meaningful read
  * Openings      a few hotels open mid-window: no prior year, so no YoY and no gap
  * Mix metrics   share-of-bookings levels with a persistent offset to compset

Usage:  python3 scripts/make_synthetic.py [--hotels 220] [--seed 7]
"""
import argparse, json, math, os, random, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "data", "ota_benchmark_synthetic.json")

MONTHS = ["2025-09","2025-10","2025-11","2025-12","2026-01","2026-02",
          "2026-03","2026-04","2026-05","2026-06","2026-07","2026-08"]

# fictional brands: (name, segment, ADR multiplier, typical LOS add)
BRANDS = [
    ("Alder House",        "upscale",   1.25, 0.2),
    ("Tidewater Suites",   "extended",  0.85, 1.1),
    ("Corvid Hotel",       "lifestyle", 1.35, 0.0),
    ("Palisade Resorts",   "resort",    1.70, 1.4),
    ("Marlow & Finch",     "luxury",    2.30, 0.6),
    ("Brightwater Inn",    "select",    0.70, 0.0),
    ("Halcyon Collection", "luxury",    2.00, 0.9),
]
# markets: (market label, country, super region, region, kind, base ADR, intl share)
MARKETS = [
    ("New York City","United States","Americas","US Northeast","city",310,.32),
    ("Boston","United States","Americas","US Northeast","city",265,.22),
    ("Philadelphia","United States","Americas","US Northeast","city",205,.14),
    ("Washington DC","United States","Americas","US Northeast","city",240,.20),
    ("Chicago","United States","Americas","US Central","city",215,.15),
    ("Minneapolis","United States","Americas","US Central","city",170,.07),
    ("Denver","United States","Americas","US Central","city",190,.09),
    ("Dallas","United States","Americas","US Central","city",175,.08),
    ("Austin","United States","Americas","US Central","city",220,.10),
    ("Houston Airport","United States","Americas","US Central","airport",140,.12),
    ("Atlanta","United States","Americas","US Southeast","city",180,.10),
    ("Nashville","United States","Americas","US Southeast","city",235,.06),
    ("Charleston","United States","Americas","US Southeast","resort",265,.07),
    ("Orlando","United States","Americas","US Southeast","resort",205,.24),
    ("Miami Beach","United States","Americas","US Southeast","resort",320,.38),
    ("Tampa Bay","United States","Americas","US Southeast","resort",215,.11),
    ("Key West","United States","Americas","US Southeast","resort",380,.12),
    ("Los Angeles","United States","Americas","US West","city",250,.27),
    ("San Diego","United States","Americas","US West","resort",245,.16),
    ("San Francisco","United States","Americas","US West","city",270,.28),
    ("Seattle","United States","Americas","US West","city",225,.17),
    ("Phoenix / Scottsdale","United States","Americas","US West","resort",230,.10),
    ("Las Vegas","United States","Americas","US West","resort",185,.19),
    ("Maui","United States","Americas","US West","resort",520,.21),
    ("Chicago O'Hare","United States","Americas","US Central","airport",135,.14),
    ("Toronto","Canada","Americas","Canada","city",220,.30),
    ("Vancouver","Canada","Americas","Canada","city",240,.34),
    ("Cancún","Mexico","Americas","Mexico & Caribbean","resort",290,.72),
    ("Mexico City","Mexico","Americas","Mexico & Caribbean","city",165,.41),
    ("Punta Cana","Dominican Republic","Americas","Mexico & Caribbean","resort",260,.85),
    ("London","United Kingdom","EMEA","UK & Ireland","city",295,.58),
    ("Edinburgh","United Kingdom","EMEA","UK & Ireland","city",210,.52),
    ("Dublin","Ireland","EMEA","UK & Ireland","city",230,.61),
    ("Paris","France","EMEA","Continental Europe","city",340,.66),
    ("Barcelona","Spain","EMEA","Continental Europe","city",250,.74),
    ("Amsterdam","Netherlands","EMEA","Continental Europe","city",260,.78),
    ("Lisbon","Portugal","EMEA","Continental Europe","city",195,.80),
    ("Dubai","United Arab Emirates","EMEA","Middle East","resort",280,.88),
    ("Tokyo","Japan","APAC","North Asia","city",260,.55),
    ("Seoul","South Korea","APAC","North Asia","city",190,.49),
    ("Singapore","Singapore","APAC","Southeast Asia","city",240,.81),
    ("Bangkok","Thailand","APAC","Southeast Asia","city",140,.83),
    ("Bali","Indonesia","APAC","Southeast Asia","resort",210,.90),
    ("Sydney","Australia","APAC","Australia & Pacific","city",230,.44),
]
# suffixes that make a hotel name read like a real property
SUFFIX = {"city": ["Downtown","Midtown","Riverfront","Convention Center","Old Town","Financial District","Waterfront","Uptown"],
          "resort": ["Resort","Resort & Spa","Golf Resort","Grand","Retreat","Club"],
          "airport": ["Airport","Airport North","Airport South"]}
MANAGERS = ["Dana Whitfield","Marco Ruiz","Priya Raman","Owen Castellano","Leah Brandt",
            "Samuel Adeyemi","Nina Kowalczyk","Jonah Park","Carla Mendes","Theo Lindqvist"]

SEASON = {  # demand index by calendar month (Jan..Dec)
    "city":    [.78,.84,.98,1.04,1.10,1.08,1.00,.98,1.10,1.12,.94,.80],
    "resort":  [1.12,1.20,1.24,1.08,.96,1.00,1.06,.94,.78,.86,.92,1.02],
    "airport": [.90,.92,1.00,1.02,1.04,1.06,1.04,1.02,1.02,1.04,.96,.88],
}

def clamp(x, lo, hi): return max(lo, min(hi, x))
def r6(x): return None if x is None else float(f"{x:.6g}")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--hotels", type=int, default=220); ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(); rnd = random.Random(a.seed); N = len(MONTHS)
    cal = [int(m[5:7]) - 1 for m in MONTHS]

    # one compset growth path per market (room nights and ADR), with a slow drift
    mk_path = {}
    for mk in MARKETS:
        lvl = rnd.gauss(0.03, 0.05); drift = rnd.gauss(0, 0.012); adr_l = rnd.gauss(0.025, 0.03)
        nrn, adr = [], []
        for t in range(N):
            nrn.append(lvl + drift * t + rnd.gauss(0, 0.04)); adr.append(adr_l + rnd.gauss(0, 0.02))
        mk_path[mk[0]] = (nrn, adr)

    used_codes, used_names, hotels = set(), set(), []
    ids = rnd.sample(range(1_200_000, 9_800_000), a.hotels)
    for k in range(a.hotels):
        mk = rnd.choice(MARKETS); market, country, sreg, region, kind, base_adr, intl_base = mk
        pool = [b for b in BRANDS if (b[1] == "resort") == (kind == "resort") or b[1] in ("luxury","upscale")] if kind == "resort" else [b for b in BRANDS if b[1] != "resort"]
        brand, seg, adr_mult, los_add = rnd.choice(pool)
        for _ in range(20):
            name = f"{brand} {market.split(' /')[0]} {rnd.choice(SUFFIX[kind])}" if rnd.random() < .8 else f"{brand} {market.split(' /')[0]}"
            if name not in used_names: break
        used_names.add(name)
        letters = "".join(c for c in market.upper() if c.isalpha())
        for _ in range(50):
            code = letters[:3] + f"{rnd.randint(11, 98):02d}"      # letters + digits: reads as a code, avoids real-world codes
            if code not in used_codes: break
        used_codes.add(code)

        size = math.exp(rnd.gauss(math.log(850), 0.65))           # monthly OTA room nights
        vol = 0.07 + 0.10 * clamp(500 / size, 0, 2.5)              # small hotels swing harder
        skill = rnd.gauss(0, 0.07); phi = 0.6; e = rnd.gauss(0, vol)
        opened = rnd.randint(3, 8) if rnd.random() < .05 else 0    # month index the hotel opens
        season = SEASON[kind]
        adr0 = base_adr * adr_mult * math.exp(rnd.gauss(0, .12))
        adr_skill = rnd.gauss(0, .025)

        d = {k2: [None] * N for k2 in ["nrn","nrn_yoy","nrn_cs","rev","rev_yoy","rev_cs","adr","adr_yoy","adr_cs"]}
        cs_n, cs_a = mk_path[market]
        for t in range(N):
            if t < opened: continue
            ramp = 0.45 + 0.55 * min(1, (t - opened) / 4) if opened else 1
            e = phi * e + rnd.gauss(0, vol)
            nrn = size * season[cal[t]] * ramp * math.exp(rnd.gauss(0, .09))
            adr = adr0 * (0.88 + 0.24 * (season[cal[t]] - .78) / .46) * math.exp(rnd.gauss(0, .03))
            d["nrn"][t] = round(nrn); d["adr"][t] = adr; d["rev"][t] = nrn * adr
            d["nrn_cs"][t] = cs_n[t]; d["adr_cs"][t] = cs_a[t]
            d["rev_cs"][t] = (1 + cs_n[t]) * (1 + cs_a[t]) - 1
            if opened: continue                                    # no prior year -> no YoY, no gap
            ny = clamp(cs_n[t] + skill + e + (rnd.gauss(0, .5) if rnd.random() < .02 else 0), -0.85, 3.0)
            ay = clamp(cs_a[t] + adr_skill + rnd.gauss(0, .035), -0.4, 0.8)
            d["nrn_yoy"][t] = ny; d["adr_yoy"][t] = ay; d["rev_yoy"][t] = (1 + ny) * (1 + ay) - 1

        # share-of-bookings metrics: level (fraction), YoY (pts), gap to compset (pts)
        def share(key, base, spread, gap_sd, zero_p=0.0, lo=0.0, hi=0.95):
            if rnd.random() < zero_p:           # hotel not enrolled: 0% share, sits below compset
                cs_lvl = clamp(base + rnd.gauss(0, spread), .02, hi)
                d[key] = [None if t < opened else 0.0 for t in range(N)]
                d[key + "_cs"] = [None if t < opened else -cs_lvl * 100 * math.exp(rnd.gauss(0, .15)) for t in range(N)]
                d[key + "_yoy"] = [None if (t < opened or opened) else 0.0 for t in range(N)]
                return
            lvl = clamp(base + rnd.gauss(0, spread), lo + .01, hi); off = rnd.gauss(0, gap_sd); w = 0
            v, c, y = [None] * N, [None] * N, [None] * N
            for t in range(N):
                if t < opened: continue
                w = .7 * w + rnd.gauss(0, spread * .18)
                x = clamp(lvl + w, max(lo, lvl * .45), hi); v[t] = x
                c[t] = off + (w * 100) * .6 + rnd.gauss(0, 1.2)
                if not opened: y[t] = rnd.gauss(off * .15, 2.8)
            d[key], d[key + "_cs"], d[key + "_yoy"] = v, c, y
        resortish = kind == "resort"
        share("spon", .16, .07, 5, zero_p=.18, hi=.5)             # sponsored listings
        share("pkg",  .34 if resortish else .14, .08, 7)
        share("mob",  .31, .06, 5)
        share("intl", intl_base, .06, 6)
        share("cxl",  .27, .05, 4)
        share("ref",  .62, .10, 8)
        share("boost", .20, .08, 6, zero_p=.45, hi=.6)             # visibility boost program

        def days(key, base, sd, gap_sd):
            lvl = max(.9, base + rnd.gauss(0, sd)); off = rnd.gauss(0, gap_sd)
            v, c, y = [None] * N, [None] * N, [None] * N
            for t in range(N):
                if t < opened: continue
                x = max(.8, lvl * (1 + .12 * (season[cal[t]] - 1)) + rnd.gauss(0, sd * .15)); v[t] = x
                c[t] = off + rnd.gauss(0, gap_sd * .35)
                if not opened: y[t] = rnd.gauss(0, sd * .12)
            d[key], d[key + "_cs"], d[key + "_yoy"] = v, c, y
        days("los", (3.1 if resortish else 1.8) + los_add, .35, .25)
        days("bw", 38 if resortish else 21, 6, 3.5)

        # a few holes, as real exports have (a month missing from one report)
        for _ in range(rnd.choice([0, 0, 0, 1])):
            t = rnd.randrange(N)
            for key in d: d[key][t] = None

        hotels.append({"id": str(ids[k]), "name": name, "code": code, "brand": brand, "sregion": sreg,
                       "region": region, "country": country, "market": market, "mgr": "", "tier": "",
                       "d": {key: [r6(x) for x in arr] for key, arr in sorted(d.items())}})

    # portfolio managers own contiguous regions (like a real field team); ~12% of hotels unassigned
    order = sorted(range(len(hotels)), key=lambda i: (hotels[i]["sregion"], hotels[i]["region"], hotels[i]["market"]))
    assigned = [i for i in order if rnd.random() > .12]
    per = math.ceil(len(assigned) / len(MANAGERS))
    for j, i in enumerate(assigned):
        hotels[i]["mgr"] = MANAGERS[j // per]
        hotels[i]["tier"] = rnd.choices(["Tier 1", "Tier 2", "Tier 3"], [.25, .45, .30])[0]
    hotels.sort(key=lambda h: int(h["id"]))

    metrics = sorted({k for h in hotels for k in h["d"]})
    data = {"asOf": MONTHS[-1], "built": datetime.date.today().isoformat(), "months": MONTHS,
            "metrics": metrics, "synthetic": True, "hotels": hotels}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh: json.dump(data, fh, separators=(",", ":"))
    print(f"{len(hotels)} hotels, {len(metrics)} metrics, {len({h['mgr'] for h in hotels if h['mgr']})} managers "
          f"-> {OUT} ({os.path.getsize(OUT)/1e3:.0f} KB)")

if __name__ == "__main__":
    main()
