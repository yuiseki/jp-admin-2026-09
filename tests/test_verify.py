import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely.geometry import box

FIELDS = [("lg_code", "string"), ("pref_code", "string"),
          ("rep_lon", "float64"), ("geometry", "binary")]


def rows():
    return [
        {"lg_code": "011002", "pref_code": "01", "rep_lon": -0.0,
         "geometry": None},
        {"lg_code": "011011", "pref_code": "01", "rep_lon": 141.35,
         "geometry": box(141.3, 43.0, 141.4, 43.1).wkb},
        {"lg_code": "131016", "pref_code": "13", "rep_lon": 139.75,
         "geometry": box(139.7, 35.6, 139.8, 35.7).wkb},
    ]


def plain(path, rs):
    """The old layout: one row group, no geo metadata, no bbox."""
    pq.write_table(pa.Table.from_pylist(rs, schema=pa.schema(
        [("lg_code", pa.string()), ("pref_code", pa.string()),
         ("rep_lon", pa.float64()), ("geometry", pa.binary())])), path)
    return path


@pytest.fixture
def new(build, tmp_path):
    p = tmp_path / "new.parquet"
    build.write(list(reversed(rows())), FIELDS, p,
                sort_by=("pref_code", "lg_code"), group_by="pref_code")
    return p


def test_same_rows_in_another_order_compare_equal(verify, new, tmp_path):
    ref = plain(tmp_path / "ref.parquet", rows())
    assert verify.compare_rows(new, ref) == []


def test_negative_zero_turned_positive_is_caught(verify, new, tmp_path):
    rs = rows()
    rs[0]["rep_lon"] = 0.0
    assert verify.compare_rows(new, plain(tmp_path / "ref.parquet", rs))


def test_a_changed_geometry_byte_is_caught(verify, new, tmp_path):
    rs = rows()
    g = bytearray(rs[1]["geometry"])
    g[-1] ^= 1
    rs[1]["geometry"] = bytes(g)
    assert verify.compare_rows(new, plain(tmp_path / "ref.parquet", rs))


def test_a_duplicated_row_is_caught(verify, new, tmp_path):
    rs = rows()
    rs[2] = dict(rs[1])
    assert verify.compare_rows(new, plain(tmp_path / "ref.parquet", rs))


def test_a_missing_column_is_caught(verify, new, tmp_path):
    rs = [dict(r, extra="x") for r in rows()]
    pq.write_table(pa.Table.from_pylist(rs), tmp_path / "ref.parquet")
    assert verify.compare_rows(new, tmp_path / "ref.parquet")


def test_layout_of_a_built_file_passes(verify, new):
    assert verify.check_layout(new, ("pref_code", "lg_code"), "pref_code") == []


def test_layout_of_the_old_file_fails(verify, tmp_path):
    old = plain(tmp_path / "old.parquet", rows())
    assert verify.check_layout(old, ("pref_code", "lg_code"), "pref_code")


def test_layout_out_of_order_fails(verify, tmp_path):
    old = plain(tmp_path / "old.parquet", list(reversed(rows())))
    problems = verify.check_layout(old, ("pref_code", "lg_code"), "pref_code")
    assert any("sorted" in p for p in problems)


def test_geo_of_a_built_file_passes(verify, new):
    assert verify.check_geo(new) == []


def test_geo_missing_fails(verify, tmp_path):
    assert verify.check_geo(plain(tmp_path / "old.parquet", rows()))


def test_geo_with_a_wrong_bbox_fails(verify, new, tmp_path):
    pf = pq.ParquetFile(new)
    t = pf.read()
    geo = json.loads(t.schema.metadata[b"geo"])
    geo["columns"]["geometry"]["bbox"] = [0, 0, 1, 1]
    bad = tmp_path / "bad.parquet"
    pq.write_table(t.replace_schema_metadata({"geo": json.dumps(geo)}), bad)
    assert verify.check_geo(bad)
