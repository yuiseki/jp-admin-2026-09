#!/usr/bin/env python3
"""Check the fusion, mostly by checking what it adds up to.

The census total is the strongest check available and it is free: if the
small areas were grouped by the wrong code, or counted twice because a
designated city took both its own areas and its wards', the population would
not come to 126,146,099.
"""
import argparse
import collections
import json
import struct
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

# The layout 01_build.py writes: sorted by these codes, one row group per
# prefecture in both files.
LAYOUT = {
    "municipalities": (("pref_code", "lg_code"), "pref_code"),
    "prefectures": (("pref_code",), "pref_code"),
}
EPSG = {"authority": "EPSG", "code": 4612}


def _cell(v):
    """A value as something hashable that tells -0.0 from 0.0 and keeps NaN
    equal to itself: a float is compared by its eight bytes, not its value."""
    if isinstance(v, float):
        return ("f", struct.pack("<d", v))
    if isinstance(v, dict):
        return tuple(sorted((k, _cell(x)) for k, x in v.items()))
    return v


def compare_rows(new_path, ref_path):
    """The rows of ref_path, every column of it, against the same columns of
    new_path, as a multiset. Order is ignored; a value, a duplicate or a
    missing row is not. Returns a list of problems, empty when equal."""
    import pyarrow.parquet as pq

    ref = pq.read_table(ref_path)
    new_schema = pq.ParquetFile(new_path).schema_arrow
    problems = []
    for f in ref.schema:
        if f.name not in new_schema.names:
            problems.append(f"column {f.name} is missing")
        elif new_schema.field(f.name).type != f.type:
            problems.append(f"column {f.name} is {new_schema.field(f.name).type}"
                            f", was {f.type}")
    if problems:
        return problems
    new = pq.read_table(new_path, columns=ref.schema.names)
    if new.num_rows != ref.num_rows:
        problems.append(f"{new.num_rows:,} rows, was {ref.num_rows:,}")

    def multiset(t):
        return collections.Counter(
            tuple(_cell(r[n]) for n in t.schema.names) for r in t.to_pylist())

    a, b = multiset(new), multiset(ref)
    if a != b:
        problems.append(f"{sum((b - a).values()):,} reference rows not found, "
                        f"{sum((a - b).values()):,} new rows not in the "
                        f"reference")
    return problems


def check_layout(path, sort_by, group_by):
    """Sorted by sort_by, and each row group holds exactly one group_by value,
    a different one each, according to the footer statistics."""
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    problems = []
    t = pf.read(columns=list(dict.fromkeys(list(sort_by) + [group_by])))
    keys = list(zip(*(t.column(k).to_pylist() for k in sort_by)))
    if keys != sorted(keys):
        problems.append(f"not sorted by {', '.join(sort_by)}")
    values = set(t.column(group_by).to_pylist())
    md = pf.metadata
    if md.num_row_groups != len(values):
        problems.append(f"{md.num_row_groups} row groups for {len(values)} "
                        f"values of {group_by}")
    idx = pf.schema_arrow.get_field_index(group_by)
    seen = []
    for i in range(md.num_row_groups):
        st = md.row_group(i).column(idx).statistics
        if st is None or not st.has_min_max or st.min != st.max:
            problems.append(f"row group {i} spans more than one {group_by}")
        else:
            seen.append(st.min)
    if len(seen) != len(set(seen)):
        problems.append(f"a {group_by} is split over row groups")
    return problems


def check_geo(path):
    """GeoParquet metadata that is there and true: JGD2000, the geometry types
    and the bbox the geometries have, and a bbox covering column that holds
    each geometry's bounds."""
    import pyarrow.parquet as pq
    import shapely

    pf = pq.ParquetFile(path)
    meta = pf.schema_arrow.metadata or {}
    if b"geo" not in meta:
        return ["no geo metadata"]
    geo = json.loads(meta[b"geo"])
    problems = []
    col = geo.get("columns", {}).get(geo.get("primary_column"), {})
    if geo.get("version") not in ("1.0.0", "1.1.0"):
        problems.append(f"geo version {geo.get('version')}")
    if geo.get("primary_column") != "geometry":
        problems.append(f"primary column {geo.get('primary_column')}")
    if col.get("encoding") != "WKB":
        problems.append(f"encoding {col.get('encoding')}")
    if (col.get("crs") or {}).get("id") != EPSG:
        problems.append(f"crs is not EPSG:4612: {(col.get('crs') or {}).get('id')}")

    t = pf.read(columns=["geometry", "bbox"]
                if "bbox" in pf.schema_arrow.names else ["geometry"])
    geoms = shapely.from_wkb(t.column("geometry").to_pylist())
    present = [g for g in geoms if g is not None]
    names = {1: "Point", 2: "LineString", 3: "Polygon", 4: "MultiPoint",
             5: "MultiLineString", 6: "MultiPolygon", 7: "GeometryCollection"}
    types = sorted({names[int(i)] for i in shapely.get_type_id(present)})
    if col.get("geometry_types") != types:
        problems.append(f"geometry_types {col.get('geometry_types')}, data has "
                        f"{types}")
    total = shapely.total_bounds(present).tolist()
    if col.get("bbox") != total:
        problems.append(f"bbox {col.get('bbox')}, data has {total}")

    keys = ("xmin", "ymin", "xmax", "ymax")
    if col.get("covering") != {"bbox": {k: ["bbox", k] for k in keys}}:
        problems.append("no bbox covering")
    elif "bbox" not in t.schema.names:
        problems.append("the covering names a bbox column that is not there")
    else:
        wrong = 0
        for g, b in zip(geoms, t.column("bbox").to_pylist()):
            want = None if g is None else dict(zip(keys, g.bounds))
            if b != want:
                wrong += 1
        if wrong:
            problems.append(f"{wrong:,} rows whose bbox is not their bounds")
    return problems


def check_files(reference=None):
    """The layout, the geo metadata, and, given the directory of a previous
    build, the rows against it. Prints and returns whether all held."""
    import pyarrow.parquet as pq

    ok = True
    for name, (sort_by, group_by) in LAYOUT.items():
        path = ROOT / "data" / f"{name}.parquet"
        md = pq.ParquetFile(path).metadata
        sizes = [md.row_group(i).total_byte_size
                 for i in range(md.num_row_groups)]
        print(f"{name}: {md.num_row_groups} row groups, "
              f"{min(sizes) / 1e6:.1f} to {max(sizes) / 1e6:.1f} MB each "
              f"uncompressed")
        checks = [
            (f"sorted by {', '.join(sort_by)}, one row group per {group_by}",
             check_layout(path, sort_by, group_by)),
            ("geo metadata: EPSG:4612, types, bbox, bbox covering",
             check_geo(path)),
        ]
        if reference:
            ref = Path(reference) / f"{name}.parquet"
            checks.append((f"every row of {ref} and no other",
                           compare_rows(path, ref)))
        for label, problems in checks:
            print(f"  {'ok  ' if not problems else 'FAIL'} {label}")
            for p in problems:
                print(f"       {p}")
            ok = ok and not problems
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", metavar="DIR",
                    help="a directory holding the previous municipalities and "
                         "prefectures parquet; their rows must all be here")
    a = ap.parse_args()

    import pyarrow.parquet as pq
    from shapely import wkb

    ok = check_files(a.reference)
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
