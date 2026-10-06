---
license: cc-by-4.0
language:
- ja
- en
task_categories:
- table-question-answering
- question-answering
- text-generation
tags:
- japan
- administrative-boundaries
- gazetteer
- geospatial
- census
- cc-by
size_categories:
- 1K<n<10K
configs:
- config_name: prefectures
  data_files: prefectures.parquet
- config_name: municipalities
  data_files: municipalities.parquet
---

# jp-admin-2026-09

Japan's 47 prefectures and 1,918 municipalities, each with its codes, its
name in kanji, kana and Latin script, its polygon, its population and its
households. Two rungs and nothing finer.

CC BY 4.0. That is the point. Japan's openly licensed geography has been
split between OpenStreetMap, which has polygons and is ODbL, whose
share-alike reaches everything built from it, and the government's own
registries, which are CC BY but publish either names without boundaries or
boundaries without names. This is both, under attribution alone.

```python
from datasets import load_dataset

pref = load_dataset("yuiseki/jp-admin-2026-09", "prefectures", split="train")
muni = load_dataset("yuiseki/jp-admin-2026-09", "municipalities", split="train")
```

## What is here

| | rows | |
|---|---:|---|
| `prefectures` | 47 | |
| `municipalities` | 1,918 | including 171 wards of the 20 designated cities |

923 municipalities belong to a 郡. Every row has a representative point.

| column | |
|---|---|
| `lg_code`, `code5`, `pref_code` | the registry's six-digit code, its five-digit form and the prefecture |
| `pref`, `county`, `city`, `ward` | each with `_kana` and `_roma` |
| `name`, `name_roma` | 松山市 and Matsuyama-shi; for a ward, 浜松市中央区 |
| `efct_date` | when the municipality came into being |
| `rep_lon`, `rep_lat` | the registry's representative point |
| `population`, `households` | the 2020 census, summed from small areas |
| `small_areas` | how many were summed |
| `geometry_source` | `census small areas`, `union of its wards`, or `none` |
| `geometry` | WKB polygon, JGD2000 longitude and latitude (EPSG:4612) |
| `bbox` | the polygon's bounds, `xmin`, `ymin`, `xmax`, `ymax`; null where `geometry` is |

The national population sums to **126,146,099**, which is the published total
of the 2020 census. That is the check worth trusting: if the small areas had
been grouped by the wrong code, or a designated city had taken both its own
areas and its wards', it would not come out.

A ward and its parent city cover the same ground, so a national sum must be
taken over the rows where `ward` is null. The prefecture table has done that
already.

## How the files are laid out

Both files are GeoParquet 1.1. The `geo` metadata names `geometry` as WKB,
gives its types, its overall bbox and its coordinate reference system as
PROJJSON, EPSG:4612, JGD2000 longitude and latitude. That is the datum the
census declares in the `.prj` of all 47 of its archives, and nothing here
reprojects. GeoPandas, QGIS and DuckDB pick the geometry and the CRS up
without being told.

Rows are sorted by `pref_code`, then `lg_code`, and each prefecture is one
row group, in both files: 47 row groups each. The Parquet statistics of
`pref_code`, `code5` and `lg_code` then say which row group a code is in,
and a reader that filters on one fetches that prefecture and nothing else.
Fetching 千代田区 reads Tokyo's 2.7 MB rather than the whole 149 MB file;
the largest row group is Nagasaki's 11 MB, all those islands.

```sql
-- DuckDB, over HTTP: one row group of 47
SELECT name, population, geometry
FROM 'hf://datasets/yuiseki/jp-admin-2026-09/municipalities.parquet'
WHERE lg_code = '131016';
```

`bbox` is the GeoParquet covering column for `geometry`. WKB carries no
statistics, so a filter by area works on `bbox.xmin` and the rest, and skips
the prefectures that the area misses. Its values are the polygon's own
bounds, which `geometry` already implies; it adds 0.1 MB.

## Where each column comes from

Two sources, each supplying what the other lacks.

[`yuiseki/abr-src-2026-09`](https://huggingface.co/datasets/yuiseki/abr-src-2026-09),
the Digital Agency's Address Base Registry, gives the codes, the names in
three scripts, the county and ward structure, the effective dates and the
representative points. It has no boundaries.

[`yuiseki/estat-boundary-2020`](https://huggingface.co/datasets/yuiseki/estat-boundary-2020),
the 2020 census small-area boundaries, gives the polygons, the population and
the households. Its names are the census's own and its geometry is at a finer
rung.

They join on the five-digit municipality code, which is the first five digits
of `lg_code` and the `PREF` + `CITY` of the census. 1,889 of 1,918 join
directly. The rest are three named cases rather than a residue.

**20 designated-city parents.** The census has 札幌市中央区 and not 札幌市, so
the city is the union of its wards. `geometry_source` says so.

**6 villages of the Northern Territories.** 色丹村, 泊村, 留夜別村, 留別村,
紗那村, 蘂取村. The registry lists them; the census does not survey them.
They have a name, a code and a representative point, and null for geometry,
population and households.

**3 wards Hamamatsu created in 2024.** 中央区, 浜名区, 天竜区, after the 2020
census. Hamamatsu itself has a polygon, built from the seven wards it had
then; its three current wards do not.

Null rather than zero in all nine cases. A village of nobody and a village
nobody counted are not the same thing.

## Two vintages in one table

The names and codes are the registry as of 2026-09, and the boundaries and
counts are the census of 2020. Six years apart, and the three Hamamatsu wards
are what that gap looks like. Any municipality that changed between them will
show it the same way: the current name over the older shape.

This is stated rather than smoothed. The alternative, dropping to the 2020
municipality list, would mean publishing names that no longer exist.

## What it is not

It stops at the municipality. The 町字 are in
[`abr-src-2026-09`](https://huggingface.co/datasets/yuiseki/abr-src-2026-09),
all 727,428 of them, and the census small areas are in
[`estat-boundary-2020`](https://huggingface.co/datasets/yuiseki/estat-boundary-2020),
all 232,019. Both are published whole, so a third copy of them here would be
a liability rather than a convenience.

It is not a cartographic product. The polygons are the census's small-area
boundaries dissolved, at the resolution the census publishes, unsimplified
and unprojected.

## Reproducing it

```bash
git clone https://github.com/yuiseki/jp-admin-2026-09
cd jp-admin-2026-09
python3 scripts/01_build.py      # reads the two datasets at pinned revisions
python3 scripts/02_verify.py
```

Both inputs are pinned by commit sha in `scripts/01_build.py`, and both carry
the publisher's own archives, so the chain can be checked to the byte on
either side.

## Licence

CC BY 4.0.

    出典：「アドレス・ベース・レジストリ」（デジタル庁）
    出典：「令和2年国勢調査 小地域（町丁・字等別）境界データ」
    （政府統計の総合窓口(e-Stat)）

The Digital Agency applies PDL1.0 and e-Stat applies 政府標準利用規約
（第2.0版）; both state compatibility with CC BY 4.0 and neither is
share-alike. `LICENSE` lists the six modifications in Japanese, as both
sets of terms ask.
