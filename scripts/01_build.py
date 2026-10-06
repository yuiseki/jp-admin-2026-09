#!/usr/bin/env python3
"""Fuse the address registry with the census boundaries, at two rungs only.

47 prefectures and 1,918 municipalities. Nothing finer: the 町字 are in the
registry and the small areas are in the census, and both are published in
full, so a third copy of them here would be a liability rather than a
convenience.

Two sources, both CC BY, and each supplies what the other lacks:

  abr-src-2026-09      the codes, the names in kanji, kana and Latin script,
                       the county, the ward structure, a representative point
  estat-boundary-2020  the polygon, the population and the households

They join on the five-digit municipality code, which is the first five digits
of the registry's lg_code and the PREF + CITY of the census. 1,889 of 1,918
join directly, and the rest are three named cases rather than a residue:

  20 designated-city parents, 札幌市 and its peers. The census has the wards
     and not the city, so the city is the union of its wards.
   6 villages of the Northern Territories, which the census does not survey.
   3 wards Hamamatsu created in 2024, after the 2020 census.

The last two get no geometry and no population, written as null rather than
as zero, because a village of nobody and a village nobody counted are not the
same thing.
"""
import argparse
import collections
import sys
from pathlib import Path

ABR = "yuiseki/abr-src-2026-09"
ABR_REV = "3677b24f472218521a4ae728e6cb96926c7d1edf"
ESTAT = "yuiseki/estat-boundary-2020"
ESTAT_REV = "823195c40e1055e2c1b3c0a635369f8c82b6c3fb"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data"

MUNICIPALITY_FIELDS = [
    ("lg_code", "string"), ("code5", "string"),
    ("pref_code", "string"),
    ("pref", "string"), ("pref_kana", "string"), ("pref_roma", "string"),
    ("county", "string"), ("county_kana", "string"), ("county_roma", "string"),
    ("city", "string"), ("city_kana", "string"), ("city_roma", "string"),
    ("ward", "string"), ("ward_kana", "string"), ("ward_roma", "string"),
    ("name", "string"), ("name_roma", "string"),
    ("efct_date", "string"),
    ("rep_lon", "float64"), ("rep_lat", "float64"),
    ("population", "int64"), ("households", "int64"),
    ("small_areas", "int64"),
    ("geometry_source", "string"),
    ("geometry", "binary"),
]

PREFECTURE_FIELDS = [
    ("pref_code", "string"),
    ("pref", "string"), ("pref_kana", "string"), ("pref_roma", "string"),
    ("municipalities", "int64"),
    ("rep_lon", "float64"), ("rep_lat", "float64"),
    ("population", "int64"), ("households", "int64"),
    ("geometry", "binary"),
]

# Sorted by the codes and nothing else. They are strings, so the sort is exact;
# a DOUBLE used as a sort key in DuckDB 1.5.6 comes back with -0.0 as 0.0.
MUNICIPALITY_SORT = ("pref_code", "lg_code")
PREFECTURE_SORT = ("pref_code",)

# The coordinate reference system of every polygon. All 47 census archives
# carry the same .prj, GEOGCS["GCS_JGD_2000",DATUM["D_JGD_2000",
# SPHEROID["GRS_1980",...]]], which is EPSG:4612, JGD2000 geographic. Nothing
# in the build reprojects: estat-boundary-2020 copies the shapefile's
# coordinates into WKB, and the dissolve keeps them. It is JGD2000 and not
# JGD2011 because that is what the publisher declares for the 2020 census.
#
# PROJJSON, written out rather than generated so that the metadata does not
# change with the installed PROJ database. pyproj 3.7.1 (PROJ 9.5.1, EPSG
# v11.022) produced it from EPSG:4612, and tests/test_build.py reads it back.
CRS = {
    "$schema": "https://proj.org/schemas/v0.7/projjson.schema.json",
    "type": "GeographicCRS",
    "name": "JGD2000",
    "datum": {
        "type": "GeodeticReferenceFrame",
        "name": "Japanese Geodetic Datum 2000",
        "ellipsoid": {"name": "GRS 1980", "semi_major_axis": 6378137,
                      "inverse_flattening": 298.257222101},
    },
    "coordinate_system": {
        "subtype": "ellipsoidal",
        "axis": [
            {"name": "Geodetic latitude", "abbreviation": "Lat",
             "direction": "north", "unit": "degree"},
            {"name": "Geodetic longitude", "abbreviation": "Lon",
             "direction": "east", "unit": "degree"},
        ],
    },
    "scope": "Horizontal component of 3D system.",
    "area": "Japan - onshore and offshore.",
    "bbox": {"south_latitude": 17.09, "west_longitude": 122.38,
             "north_latitude": 46.05, "east_longitude": 157.65},
    "id": {"authority": "EPSG", "code": 4612},
}

GEOMETRY_TYPES = {1: "Point", 2: "LineString", 3: "Polygon", 4: "MultiPoint",
                  5: "MultiLineString", 6: "MultiPolygon",
                  7: "GeometryCollection"}


def write(rows, fields, path, sort_by, group_by):
    """GeoParquet 1.1: sorted by the codes, one row group per group_by value,
    a bbox covering column after the original columns, and the CRS.

    Every column in fields is written as it is in rows. The bbox column is
    the only addition: four doubles per row, the geometry's own bounds, null
    where the geometry is null. Its per-row-group statistics are what let a
    reader skip row groups by area, since WKB carries none.
    """
    import itertools
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq
    import shapely

    rows = sorted(rows, key=lambda r: tuple(r[k] for k in sort_by))
    types = {"string": pa.string(), "int64": pa.int64(),
             "float64": pa.float64(), "binary": pa.binary()}
    bbox_type = pa.struct([(k, pa.float64())
                           for k in ("xmin", "ymin", "xmax", "ymax")])

    geoms = shapely.from_wkb([r["geometry"] for r in rows])
    present = [g for g in geoms if g is not None]
    bounds = [None if g is None else
              dict(zip(("xmin", "ymin", "xmax", "ymax"), g.bounds))
              for g in geoms]
    total = shapely.total_bounds(present).tolist()
    geo = {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {"geometry": {
            "encoding": "WKB",
            "geometry_types": sorted({GEOMETRY_TYPES[int(t)] for t in
                                      shapely.get_type_id(present)}),
            "crs": CRS,
            "bbox": total,
            "covering": {"bbox": {k: ["bbox", k] for k in
                                  ("xmin", "ymin", "xmax", "ymax")}},
        }},
    }
    schema = pa.schema([pa.field(n, types[t]) for n, t in fields]
                       + [pa.field("bbox", bbox_type)],
                       metadata={"geo": json.dumps(geo)})

    with pq.ParquetWriter(path, schema, compression="zstd") as w:
        i = 0
        for _, group in itertools.groupby(rows, key=lambda r: r[group_by]):
            group = list(group)
            cols = [pa.array([r[n] for r in group], type=types[t])
                    for n, t in fields]
            cols.append(pa.array(bounds[i:i + len(group)], type=bbox_type))
            i += len(group)
            w.write_table(pa.Table.from_arrays(cols, schema=schema),
                          row_group_size=len(group))
    md = pq.ParquetFile(path).metadata
    print(f"  {path.name}: {md.num_rows:,} rows in {md.num_row_groups} "
          f"row groups, {path.stat().st_size:,} bytes")


def abr_table(name, revision=ABR_REV):
    from datasets import load_dataset
    return list(load_dataset(ABR, name, split="train", revision=revision))


def estat_tables(revision=ESTAT_REV):
    """Every small area, as (code5, city_name, population, households, wkb)."""
    from huggingface_hub import snapshot_download
    import pyarrow.parquet as pq

    local = snapshot_download(ESTAT, repo_type="dataset", revision=revision,
                              allow_patterns=["parquet/*.parquet"])
    for p in sorted((Path(local) / "parquet").glob("*.parquet")):
        t = pq.read_table(p, columns=["PREF", "CITY", "CITY_NAME",
                                      "JINKO", "SETAI", "geometry"])
        yield p.name, t.to_pylist()


def as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    from shapely import wkb as shapely_wkb
    from shapely.ops import unary_union

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    pref_rows = [r for r in abr_table("pref") if not (r["ablt_date"] or "").strip()]
    pref_pos = {r["lg_code"][:2]: r for r in abr_table("pref_pos")}
    city_rows = [r for r in abr_table("city") if not (r["ablt_date"] or "").strip()]
    city_pos = {r["lg_code"]: r for r in abr_table("city_pos")}
    print(f"registry: {len(pref_rows)} prefectures, {len(city_rows):,} municipalities")

    # The census, grouped by the five-digit code, and by city name so that a
    # designated city can find its own wards.
    geoms = collections.defaultdict(list)
    pop = collections.Counter()
    sets = collections.Counter()
    areas = collections.Counter()
    name_of = {}
    for fname, rows in estat_tables():
        for r in rows:
            code5 = (r["PREF"] or "") + (r["CITY"] or "")
            geoms[code5].append(r["geometry"])
            areas[code5] += 1
            name_of.setdefault(code5, r["CITY_NAME"] or "")
            for col, acc in (("JINKO", pop), ("SETAI", sets)):
                v = as_int(r[col])
                if v is not None:
                    acc[code5] += v
        print(f"  {fname}: {len(rows):,} small areas", flush=True)
    print(f"census: {sum(areas.values()):,} small areas in "
          f"{len(areas):,} municipality codes")

    # A designated city's wards, by the name the census gives them.
    wards_of = collections.defaultdict(list)
    for code5, nm in name_of.items():
        for r in city_rows:
            if r["ward"] and nm.startswith(r["city"]) and nm != r["city"]:
                wards_of[r["pref"] + r["city"]].append(code5)
                break

    def dissolve(wkbs):
        return unary_union([shapely_wkb.loads(b) for b in wkbs])

    muni = []
    by_pref = collections.defaultdict(list)
    for r in sorted(city_rows, key=lambda r: r["lg_code"]):
        code5 = r["lg_code"][:5]
        name = r["city"] + (r["ward"] or "")
        codes, source = [code5], "census small areas"
        if code5 not in geoms:
            key = r["pref"] + r["city"]
            if not r["ward"] and wards_of.get(key):
                codes = sorted(set(wards_of[key]))
                source = "union of its wards"
            else:
                codes = []
                source = "none"
        wkbs = [b for c in codes for b in geoms.get(c, ())]
        geom = dissolve(wkbs).wkb if wkbs else None
        pos = city_pos.get(r["lg_code"], {})
        row = {
            "lg_code": r["lg_code"], "code5": code5,
            "pref_code": code5[:2],
            "pref": r["pref"], "pref_kana": r["pref_kana"],
            "pref_roma": r["pref_roma"],
            "county": r["county"] or None, "county_kana": r["county_kana"] or None,
            "county_roma": r["county_roma"] or None,
            "city": r["city"], "city_kana": r["city_kana"],
            "city_roma": r["city_roma"],
            "ward": r["ward"] or None, "ward_kana": r["ward_kana"] or None,
            "ward_roma": r["ward_roma"] or None,
            "name": name,
            "name_roma": (r["city_roma"] + " " + r["ward_roma"]).strip()
                         if r["ward_roma"] else r["city_roma"],
            "efct_date": r["efct_date"] or None,
            "rep_lon": float(pos["rep_lon"]) if pos.get("rep_lon") else None,
            "rep_lat": float(pos["rep_lat"]) if pos.get("rep_lat") else None,
            "population": sum(pop[c] for c in codes) if codes else None,
            "households": sum(sets[c] for c in codes) if codes else None,
            "small_areas": sum(areas[c] for c in codes) if codes else None,
            "geometry_source": source,
            "geometry": geom,
        }
        muni.append(row)
        if geom is not None and not r["ward"]:
            by_pref[code5[:2]].append(geom)
        elif geom is not None and r["ward"] and code5 in geoms:
            # A ward of a designated city: its parent carries the same area,
            # so only one of the two may go into the prefecture union.
            pass
    print(f"municipalities built: {len(muni):,}")
    by_source = collections.Counter(r["geometry_source"] for r in muni)
    for k, n in sorted(by_source.items()):
        print(f"  {k:22} {n:>5,}")

    pref = []
    for r in sorted(pref_rows, key=lambda r: r["lg_code"]):
        code2 = r["lg_code"][:2]
        mine = [m for m in muni if m["pref_code"] == code2 and not m["ward"]]
        wkbs = [m["geometry"] for m in mine if m["geometry"]]
        pos = pref_pos.get(code2, {})
        pref.append({
            "pref_code": code2, "pref": r["pref"], "pref_kana": r["pref_kana"],
            "pref_roma": r["pref_roma"],
            "municipalities": len(mine),
            "rep_lon": float(pos["rep_lon"]) if pos.get("rep_lon") else None,
            "rep_lat": float(pos["rep_lat"]) if pos.get("rep_lat") else None,
            "population": sum(m["population"] or 0 for m in mine),
            "households": sum(m["households"] or 0 for m in mine),
            "geometry": dissolve(wkbs).wkb if wkbs else None,
        })
    print(f"prefectures built: {len(pref)}")

    # One prefecture per row group in both files, so that a reader filtering
    # on pref_code, code5 or lg_code fetches that prefecture's bytes only.
    write(muni, MUNICIPALITY_FIELDS, out / "municipalities.parquet",
          sort_by=MUNICIPALITY_SORT, group_by="pref_code")
    write(pref, PREFECTURE_FIELDS, out / "prefectures.parquet",
          sort_by=PREFECTURE_SORT, group_by="pref_code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
