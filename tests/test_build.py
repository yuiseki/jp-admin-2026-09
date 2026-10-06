import json
import math

import pyarrow.parquet as pq
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

FIELDS = [
    ("lg_code", "string"), ("pref_code", "string"),
    ("rep_lon", "float64"), ("population", "int64"),
    ("geometry", "binary"),
]


def rows():
    # Deliberately out of order, with a -0.0, a null geometry and both
    # polygon types, which is what the real table holds.
    return [
        {"lg_code": "131016", "pref_code": "13", "rep_lon": 139.75,
         "population": 66680, "geometry": box(139.7, 35.6, 139.8, 35.7).wkb},
        {"lg_code": "011002", "pref_code": "01", "rep_lon": -0.0,
         "population": None, "geometry": None},
        {"lg_code": "012025", "pref_code": "01", "rep_lon": 140.7,
         "population": 251084,
         "geometry": MultiPolygon([box(140.6, 41.7, 140.8, 41.9),
                                   box(141.0, 42.0, 141.1, 42.1)]).wkb},
        {"lg_code": "011011", "pref_code": "01", "rep_lon": 141.35,
         "population": 237627,
         "geometry": Polygon([(141.3, 43.0), (141.4, 43.0),
                              (141.4, 43.1)]).wkb},
    ]


@pytest.fixture
def written(build, tmp_path):
    path = tmp_path / "t.parquet"
    build.write(rows(), FIELDS, path, sort_by=("pref_code", "lg_code"),
                group_by="pref_code")
    return path


def test_rows_are_sorted_by_the_codes(written):
    t = pq.read_table(written)
    assert t.column("lg_code").to_pylist() == ["011002", "011011", "012025",
                                               "131016"]


def test_one_row_group_per_prefecture(written):
    md = pq.ParquetFile(written).metadata
    assert md.num_row_groups == 2
    assert [md.row_group(i).num_rows for i in range(2)] == [3, 1]
    idx = pq.ParquetFile(written).schema_arrow.get_field_index("pref_code")
    for i, want in enumerate(["01", "13"]):
        st = md.row_group(i).column(idx).statistics
        assert (st.min, st.max) == (want, want)


def test_every_value_is_kept(written):
    t = pq.read_table(written).to_pylist()
    want = {r["lg_code"]: r for r in rows()}
    assert len(t) == len(want)
    for r in t:
        for name, _ in FIELDS:
            assert r[name] == want[r["lg_code"]][name], name
    neg = [r for r in t if r["lg_code"] == "011002"][0]["rep_lon"]
    assert neg == 0 and math.copysign(1, neg) < 0


def test_columns_keep_their_order_and_bbox_comes_last(written):
    names = pq.ParquetFile(written).schema_arrow.names
    assert names == [n for n, _ in FIELDS] + ["bbox"]


def test_bbox_column_is_the_geometry_bounds(written):
    t = pq.read_table(written).to_pylist()
    by = {r["lg_code"]: r["bbox"] for r in t}
    assert by["011002"] is None
    assert by["012025"] == {"xmin": 140.6, "ymin": 41.7,
                            "xmax": 141.1, "ymax": 42.1}
    assert by["131016"] == {"xmin": 139.7, "ymin": 35.6,
                            "xmax": 139.8, "ymax": 35.7}


def test_geo_metadata(build, written):
    geo = json.loads(pq.ParquetFile(written).schema_arrow.metadata[b"geo"])
    assert geo["version"] == "1.1.0"
    assert geo["primary_column"] == "geometry"
    col = geo["columns"]["geometry"]
    assert col["encoding"] == "WKB"
    assert col["geometry_types"] == ["MultiPolygon", "Polygon"]
    assert col["bbox"] == [139.7, 35.6, 141.4, 43.1]
    assert col["crs"]["id"] == {"authority": "EPSG", "code": 4612}
    assert col["covering"] == {"bbox": {
        "xmin": ["bbox", "xmin"], "ymin": ["bbox", "ymin"],
        "xmax": ["bbox", "xmax"], "ymax": ["bbox", "ymax"]}}


def test_crs_is_jgd2000_geographic(build):
    pyproj = pytest.importorskip("pyproj")
    crs = pyproj.CRS.from_json_dict(build.CRS)
    assert crs.to_epsg() == 4612
    assert crs.is_geographic
    # The publisher's .prj, verbatim from every one of the 47 archives.
    prj = pyproj.CRS.from_wkt(
        'GEOGCS["GCS_JGD_2000",DATUM["D_JGD_2000",SPHEROID["GRS_1980",'
        '6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],'
        'UNIT["Degree",0.0174532925199433]]')
    assert prj.to_epsg() == 4612


def test_writing_twice_gives_the_same_bytes(build, tmp_path):
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    for p in (a, b):
        build.write(rows(), FIELDS, p, sort_by=("pref_code", "lg_code"),
                    group_by="pref_code")
    assert a.read_bytes() == b.read_bytes()
