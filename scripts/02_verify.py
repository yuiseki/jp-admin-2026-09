#!/usr/bin/env python3
"""Check the fusion, mostly by checking what it adds up to.

The census total is the strongest check available and it is free: if the
small areas were grouped by the wrong code, or counted twice because a
designated city took both its own areas and its wards', the population would
not come to 126,146,099.
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXPECTED = {
    "municipalities": 1918,
    "prefectures": 47,
    "with_a_county": 923,
    "designated_city_wards": 171,
    "no_geometry": 9,
    # The published total of the 2020 Population Census.
    "population": 126146099,
}

# Japan, generously.
BOUNDS = (122.0, 20.0, 154.5, 46.0)


def main():
    import pyarrow.parquet as pq
    from shapely import wkb

    ok = True
    m = pq.read_table(ROOT / "data" / "municipalities.parquet").to_pylist()
    p = pq.read_table(ROOT / "data" / "prefectures.parquet").to_pylist()
    print(f"municipalities {len(m):>9,}")
    print(f"prefectures    {len(p):>9,}")

    counts = {
        "municipalities": len(m),
        "prefectures": len(p),
        "with_a_county": sum(1 for r in m if r["county"]),
        "designated_city_wards": sum(1 for r in m if r["ward"]),
        "no_geometry": sum(1 for r in m if r["geometry"] is None),
    }
    for k, got in counts.items():
        if got != EXPECTED[k]:
            ok = False
            print(f"  {k}: expected {EXPECTED[k]:,}, found {got:,}")

    # A ward and its parent city cover the same ground. Counting both would
    # double 30 million people, so the national sum is taken over the rows
    # that are not wards.
    plain = [r for r in m if not r["ward"]]
    totals = {
        "municipalities, excluding wards": sum(r["population"] or 0 for r in plain),
        "prefectures": sum(r["population"] or 0 for r in p),
    }
    for label, got in totals.items():
        print(f"population, {label:<32} {got:>13,}")
        if got != EXPECTED["population"]:
            ok = False
            print(f"  expected {EXPECTED['population']:,}")

    # Every code is unique, and every municipality belongs to a prefecture
    # that is here.
    if len({r["lg_code"] for r in m}) != len(m):
        ok = False
        print("  lg_code is not unique")
    pref_codes = {r["pref_code"] for r in p}
    stray = {r["pref_code"] for r in m} - pref_codes
    if stray:
        ok = False
        print(f"  municipalities in an unknown prefecture: {sorted(stray)}")

    # Geometry: valid, and in Japan.
    bad = outside = 0
    for r in m + p:
        if r["geometry"] is None:
            continue
        g = wkb.loads(r["geometry"])
        if not g.is_valid:
            bad += 1
        x0, y0, x1, y1 = g.bounds
        if not (BOUNDS[0] <= x0 and x1 <= BOUNDS[2]
                and BOUNDS[1] <= y0 and y1 <= BOUNDS[3]):
            outside += 1
    print(f"invalid geometries {bad:>7,}")
    print(f"outside Japan      {outside:>7,}")
    if bad or outside:
        ok = False

    by_source = collections.Counter(r["geometry_source"] for r in m)
    print("geometry from:")
    for k, n in sorted(by_source.items()):
        print(f"  {k:24} {n:>5,}")

    missing = [(r["code5"], r["name"]) for r in m if r["geometry"] is None]
    print("no geometry:", missing)

    print()
    print("すべて通過" if ok else "検証に失敗した項目があります")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
