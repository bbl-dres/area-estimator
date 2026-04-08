"""
Unit tests for footprints.py — covers the pure helpers. The loader
functions that hit the gpkg are not tested here (would need fixtures).
"""
import math
from pathlib import Path

import pandas as pd
import pytest

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point, Polygon

from footprints import (
    _normalise_cell,
    _parse_egid_cell,
    _read_input_csv,
    load_footprints_from_av_with_coordinates,
)


# ── _parse_egid_cell ────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    # Empty / missing
    (None, []),
    (float("nan"), []),
    ("", []),
    ("   ", []),

    # Single integer (various input types)
    ("1234567", [1234567]),
    (1234567, [1234567]),
    (1234567.0, [1234567]),
    ("  1234  ", [1234]),

    # Comma-separated multi-EGID
    ("1234, 5678", [1234, 5678]),
    ("1234,5678", [1234, 5678]),  # no space
    ("  1234  ,  5678  ", [1234, 5678]),  # leading/trailing whitespace
    ("1, 2, 3, 4, 5", [1, 2, 3, 4, 5]),

    # Slash-separated — now SUPPORTED (real-world colleague input)
    ("1234/5678", [1234, 5678]),
    ("1234 / 5678", [1234, 5678]),
    ("1234/5678/9012", [1234, 5678, 9012]),

    # Semicolon-separated — supported
    ("1234;5678", [1234, 5678]),
    ("1234; 5678", [1234, 5678]),
    ("1234 ; 5678", [1234, 5678]),

    # Whitespace-only separator (no comma/slash/semicolon)
    ("1234 5678", [1234, 5678]),
    ("1234\t5678", [1234, 5678]),  # tab
    ("1234   5678", [1234, 5678]),  # multiple spaces

    # Mixed separators in one cell — colleagues are unpredictable
    ("1234, 5678/9012;3456", [1234, 5678, 9012, 3456]),
    ("1234,;5678", [1234, 5678]),  # comma + semicolon
    ("1234,/5678", [1234, 5678]),  # comma + slash

    # Zero / negative — not valid
    ("0", []),
    ("-1", []),
    ("1234, 0", []),  # one bad token poisons the whole list
    ("1234, -5", []),

    # Non-numeric tokens
    ("garbage", []),
    ("1234, garbage", []),  # one bad token poisons the whole list
    ("garbage, 1234", []),
    ("1234/abc", []),
    ("1234;abc", []),

    # Empty / leading / trailing separators are tolerated (collapsed)
    ("1234,,5678", [1234, 5678]),  # was malformed before — now collapses
    (",1234", [1234]),               # leading comma — tolerated
    ("1234,", [1234]),               # trailing comma — tolerated
    ("/1234/", [1234]),              # leading + trailing slash

    # Float-looking values truncate (preserves prior _to_gwr_code behavior)
    ("1234.5", [1234]),
    ("1234.5, 5678", [1234, 5678]),

    # Infinity / overflow — int(inf) raises OverflowError natively, must
    # be caught and returned as [] instead of crashing the whole loader.
    ("inf", []),
    ("-inf", []),
    ("1e400", []),       # parses to inf via float()
    ("nan", []),         # parses to NaN via float() — also rejected
    ("1234, inf", []),   # one bad token poisons the whole list
    (float("inf"), []),
])
def test_parse_egid_cell(raw, expected):
    assert _parse_egid_cell(raw) == expected


def test_parse_egid_cell_returns_list_of_ints():
    """Result list elements must be Python int (for downstream type expectations)."""
    result = _parse_egid_cell("1234, 5678")
    assert all(isinstance(e, int) and not isinstance(e, bool) for e in result)


def test_parse_egid_cell_partial_invalid_returns_empty():
    """
    Documented behavior: if ANY token is invalid, the whole cell is rejected.
    We never silently drop part of a multi-EGID list.
    """
    assert _parse_egid_cell("1234, abc, 5678") == []
    assert _parse_egid_cell("1234, 5678, 0") == []


# ── _read_input_csv ─────────────────────────────────────────────────────────


def test_read_csv_comma_delimited(tmp_path: Path):
    """Plain comma-delimited CSV with simple int egid column."""
    p = tmp_path / "comma.csv"
    p.write_text("id,egid\n1,1234\n2,5678\n", encoding="utf-8")
    df = _read_input_csv(p)
    assert list(df.columns) == ["id", "egid"]
    assert len(df) == 2
    assert int(df.iloc[0]["egid"]) == 1234


def test_read_csv_semicolon_delimited(tmp_path: Path):
    """Semicolon-delimited (web app format) must auto-detect."""
    p = tmp_path / "semi.csv"
    p.write_text("id;egid\n1;1234\n2;5678\n", encoding="utf-8")
    df = _read_input_csv(p)
    assert list(df.columns) == ["id", "egid"]
    assert len(df) == 2


def test_read_csv_strips_utf8_bom(tmp_path: Path):
    """
    Excel saves CSVs with a UTF-8 BOM by default. The first column header
    must NOT come through as '\\ufeffid'.
    """
    p = tmp_path / "bom.csv"
    # \ufeff = BOM
    p.write_text("\ufeffid,egid\n1,1234\n", encoding="utf-8")
    df = _read_input_csv(p)
    assert "id" in df.columns
    assert "\ufeffid" not in df.columns


def test_read_csv_lowercases_column_names(tmp_path: Path):
    p = tmp_path / "upper.csv"
    p.write_text("ID,EGID\n1,1234\n", encoding="utf-8")
    df = _read_input_csv(p)
    assert list(df.columns) == ["id", "egid"]


def test_read_csv_strips_whitespace_from_columns(tmp_path: Path):
    p = tmp_path / "ws.csv"
    p.write_text("  id  , egid \n1,1234\n", encoding="utf-8")
    df = _read_input_csv(p)
    assert list(df.columns) == ["id", "egid"]


def test_read_csv_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        _read_input_csv(tmp_path / "does_not_exist.csv")


# ── _normalise_cell ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    # Plain values pass through
    ("hello", "hello"),
    ("1234", "1234"),

    # Internal whitespace runs collapse to single spaces
    ("hello  world", "hello world"),
    ("hello   world", "hello world"),
    ("hello\tworld", "hello world"),  # tab → space
    ("hello\nworld", "hello world"),  # line break → space
    ("hello\r\nworld", "hello world"),  # CRLF → space
    ("hello\xa0world", "hello world"),  # NBSP → space

    # Leading / trailing whitespace stripped
    ("  hello  ", "hello"),
    ("\thello\t", "hello"),
    ("\nhello\n", "hello"),

    # Combined: leading + internal + trailing
    ("  hello\nworld  ", "hello world"),
    ("  1234,\n5678  ", "1234, 5678"),
])
def test_normalise_cell(raw, expected):
    assert _normalise_cell(raw) == expected


def test_normalise_cell_passes_nan_through():
    """NaN must stay NaN — we don't want to coerce it to the string 'nan'."""
    result = _normalise_cell(float("nan"))
    assert isinstance(result, float)
    import math
    assert math.isnan(result)


def test_normalise_cell_passes_none_through():
    assert _normalise_cell(None) is None


# ── _read_input_csv: cleanup pass ──────────────────────────────────────────


def test_read_csv_strips_string_column_padding(tmp_path: Path):
    """
    A string column (one pandas can't auto-parse to int/float) gets
    leading/trailing whitespace stripped by the cleanup pass.
    Numeric columns are pre-stripped by pandas at parse time, so they
    don't go through our cleanup at all — that's tested separately below.
    """
    p = tmp_path / "padded.csv"
    p.write_text("id,egid\n  1086/2010/BG  ,  1234567  \n", encoding="utf-8")
    df = _read_input_csv(p)
    # id is a string column (slashes prevent numeric inference)
    assert df.iloc[0]["id"] == "1086/2010/BG"


def test_read_csv_collapses_multi_egid_cells(tmp_path: Path):
    """
    The realistic use case: a multi-EGID cell with embedded whitespace
    (the kind of thing colleagues paste from Excel) must come through
    cleaned. egid stays as a string column because the comma prevents
    numeric inference.
    """
    p = tmp_path / "multi.csv"
    p.write_text('id,egid\n1086/2010/BG,"1234   5678"\n', encoding="utf-8")
    df = _read_input_csv(p)
    assert df.iloc[0]["egid"] == "1234 5678"


def test_read_csv_normalises_line_breaks_in_cells(tmp_path: Path):
    """
    A cell that contains an embedded line break (Excel's Alt+Enter)
    must come out with the break replaced by a single space.
    """
    p = tmp_path / "linebreak.csv"
    p.write_text('id,egid\n1086/2010/BG,"1234,\n5678"\n', encoding="utf-8")
    df = _read_input_csv(p)
    assert df.iloc[0]["egid"] == "1234, 5678"


def test_read_csv_handles_tab_in_cells(tmp_path: Path):
    p = tmp_path / "tabby.csv"
    p.write_text('id,egid\n1086/2010/BG,"1234\t5678"\n', encoding="utf-8")
    df = _read_input_csv(p)
    assert df.iloc[0]["egid"] == "1234 5678"


def test_read_csv_cleanup_preserves_nan_in_string_column(tmp_path: Path):
    """
    Empty cells in a string column must stay NaN, not become 'nan' strings.
    The multi-EGID cell is quoted so the comma stays inside one field.
    """
    p = tmp_path / "blanks.csv"
    p.write_text(
        'id,egid\n1086/2010/BG,"1234,5678"\n1086/2018/VG,\n',
        encoding="utf-8",
    )
    df = _read_input_csv(p)
    # The egid column is object dtype because of the comma-separated value
    assert df.iloc[0]["egid"] == "1234,5678"
    assert pd.isna(df.iloc[1]["egid"])


# ── Coordinate-mode loader integration tests ──────────────────────────────


# A few real-ish LV95 coordinates near Bern (Roche Tower area).
# Building polygons are tiny squares around these points so the test runs fast.
_TEST_LV95_X = 2600000
_TEST_LV95_Y = 1200000
_LV95_TO_WGS84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)


def _make_synthetic_av_gpkg(tmp_path: Path) -> Path:
    """
    Build a tiny synthetic AV-style GeoPackage with three known building
    polygons. Used by the coordinate-loader integration tests so we don't
    depend on the real ~5 GB cadastral file.
    """
    cx, cy = _TEST_LV95_X, _TEST_LV95_Y
    polys = [
        # Building A: 10x10 m square at (cx, cy)
        Polygon([(cx, cy), (cx + 10, cy), (cx + 10, cy + 10), (cx, cy + 10)]),
        # Building B: 10x10 m square 30 m east
        Polygon([(cx + 30, cy), (cx + 40, cy), (cx + 40, cy + 10), (cx + 30, cy + 10)]),
        # Building C: 10x10 m square 60 m east
        Polygon([(cx + 60, cy), (cx + 70, cy), (cx + 70, cy + 10), (cx + 60, cy + 10)]),
    ]
    gdf = gpd.GeoDataFrame(
        {
            'Art': ['Gebaeude', 'Gebaeude', 'Gebaeude'],
            'GWR_EGID': [1001, 1002, 1003],
            'geometry': polys,
        },
        crs='EPSG:2056',
    )
    av_path = tmp_path / "synthetic_av.gpkg"
    gdf.to_file(av_path, layer='lcsf', driver='GPKG')
    return av_path


def _lv95_point_to_wgs(x: float, y: float) -> tuple[float, float]:
    lon, lat = _LV95_TO_WGS84.transform(x, y)
    return lon, lat


def test_coordinate_loader_matches_each_point_to_correct_polygon(tmp_path: Path):
    """End-to-end: 3 points → 3 polygons, each matched correctly."""
    av_path = _make_synthetic_av_gpkg(tmp_path)
    cx, cy = _TEST_LV95_X, _TEST_LV95_Y
    # Centers of each polygon
    centers_lv95 = [(cx + 5, cy + 5), (cx + 35, cy + 5), (cx + 65, cy + 5)]
    centers_wgs = [_lv95_point_to_wgs(x, y) for x, y in centers_lv95]

    csv_path = tmp_path / "pts.csv"
    csv_path.write_text(
        "id,lon,lat\n"
        + f"A,{centers_wgs[0][0]},{centers_wgs[0][1]}\n"
        + f"B,{centers_wgs[1][0]},{centers_wgs[1][1]}\n"
        + f"C,{centers_wgs[2][0]},{centers_wgs[2][1]}\n",
        encoding='utf-8',
    )

    result = load_footprints_from_av_with_coordinates(str(av_path), str(csv_path))
    # Sort by input_id so the assertions are positional
    result = result.sort_values('input_id').reset_index(drop=True)
    assert len(result) == 3
    assert result.iloc[0]['input_id'] == 'A'
    assert int(result.iloc[0]['av_egid']) == 1001
    assert int(result.iloc[1]['av_egid']) == 1002
    assert int(result.iloc[2]['av_egid']) == 1003
    # Every match has status_step1='ok' and a real geometry
    assert (result['status_step1'] == 'ok').all()
    assert result['geometry'].notna().all()


def test_coordinate_loader_no_match_emits_no_footprint(tmp_path: Path):
    """A point that lands far from any polygon → status_step1='no_footprint'."""
    av_path = _make_synthetic_av_gpkg(tmp_path)
    cx, cy = _TEST_LV95_X, _TEST_LV95_Y
    # Point 500 m east of any polygon — outside the union bbox + buffer
    far_lv95 = (cx + 1000, cy)
    far_lon, far_lat = _lv95_point_to_wgs(*far_lv95)

    csv_path = tmp_path / "far.csv"
    csv_path.write_text(
        f"id,lon,lat\nMISS,{far_lon},{far_lat}\n",
        encoding='utf-8',
    )

    result = load_footprints_from_av_with_coordinates(str(av_path), str(csv_path))
    assert len(result) == 1
    assert result.iloc[0]['status_step1'] == 'no_footprint'
    assert result.iloc[0]['av_egid'] is None
    assert result.iloc[0]['geometry'] is None


def test_coordinate_loader_does_one_gpkg_read_for_many_points(tmp_path: Path, monkeypatch):
    """
    Regression: the refactored loader must call _load_av_buildings exactly
    ONCE regardless of how many input points there are. The old code did
    one read per point (O(n) gpkg I/O); the refactor moves to O(1).
    """
    av_path = _make_synthetic_av_gpkg(tmp_path)
    cx, cy = _TEST_LV95_X, _TEST_LV95_Y
    centers_lv95 = [(cx + 5, cy + 5), (cx + 35, cy + 5), (cx + 65, cy + 5)]

    # 9 input points, 3 hitting each polygon
    rows = []
    for i, (x, y) in enumerate(centers_lv95 * 3):
        lon, lat = _lv95_point_to_wgs(x, y)
        rows.append(f"id_{i},{lon},{lat}")
    csv_path = tmp_path / "many.csv"
    csv_path.write_text("id,lon,lat\n" + "\n".join(rows) + "\n", encoding='utf-8')

    # Spy on _load_av_buildings to count invocations
    import footprints
    call_count = {"n": 0}
    real_loader = footprints._load_av_buildings

    def counting_loader(*args, **kwargs):
        call_count["n"] += 1
        return real_loader(*args, **kwargs)

    monkeypatch.setattr(footprints, "_load_av_buildings", counting_loader)

    result = load_footprints_from_av_with_coordinates(str(av_path), str(csv_path))
    assert len(result) == 9
    assert call_count["n"] == 1, (
        f"expected exactly 1 call to _load_av_buildings, got {call_count['n']}"
    )

