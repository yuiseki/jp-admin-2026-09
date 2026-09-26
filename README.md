# jp-admin-2026-09

Dataset: https://huggingface.co/datasets/yuiseki/jp-admin-2026-09

Japan's 47 prefectures and 1,918 municipalities with their codes, their names
in kanji, kana and Latin script, their polygons, their population and their
households. Two rungs and nothing finer. This repository holds the code; the
data is on the Hub.

CC BY 4.0. Japan's openly licensed geography has been split between
OpenStreetMap, which has polygons and is ODbL, and the government's own
registries, which are CC BY but publish either names without boundaries or
boundaries without names. This is both, under attribution alone.

## Where things are

```
scripts/01_build.py     two published datasets -> one fused table
scripts/02_verify.py    the counts, the geometry, and the census total
src/publish.py          pushes the data and its card to the Hub

data/README.md          the dataset card. Uploaded as-is
data/LICENSE            the CC BY notice and the five declared modifications
data/provenance.yaml    where each column comes from
data/*.parquet          generated, 229 MB
```

## Running it

```sh
python3 scripts/01_build.py     # a couple of minutes, mostly the dissolve
python3 scripts/02_verify.py
python3 src/publish.py          # dry run; --push to upload
```

Both inputs are pinned by commit sha in `scripts/01_build.py`:
[abr-src-2026-09](https://github.com/yuiseki/abr-src-2026-09) and
[estat-boundary-2020](https://github.com/yuiseki/estat-boundary-2020).

## The check worth having

The national population sums to 126,146,099, which is the published total of
the 2020 census. Nothing in the build tells it that number; it comes out of
grouping 232,019 small areas by municipality code and municipalities by
prefecture. A mis-grouped code, or a designated city that took both its own
areas and its wards', would not add up.

`scripts/02_verify.py` asserts it from both directions, over municipalities
and over prefectures.

## The three cases that do not join

1,889 of 1,918 municipalities join to the census by code. The rest are named
rather than dropped:

**20 designated-city parents.** The census has 札幌市中央区 and not 札幌市, so
the city is the union of its wards.

**6 villages of the Northern Territories.** The registry lists them; the
census does not survey them.

**3 wards Hamamatsu created in 2024**, after the 2020 census. Hamamatsu
itself has a polygon, built from the seven wards it had then.

All nine carry null rather than zero, and `geometry_source` says which case a
row is.

## Two vintages in one table

Names and codes from the 2026-09 registry, boundaries and counts from the
2020 census. Six years apart, and the three Hamamatsu wards are what that gap
looks like. Stated rather than smoothed: the alternative is publishing names
that no longer exist.

## Licence

The code here is MIT. The data is CC BY 4.0, from two sources that are each
CC BY and neither share-alike. See `data/LICENSE` for the notice and the five
modifications, in Japanese as both sets of terms ask.
