"""
Unit tests for the aggregate_by_input_id reduce step in main.py.

The aggregation step is the most behavior-critical change from the
recent session — it collapses multi-EGID and multi-polygon sub-rows into
one output row per input_id, with numeric columns becoming ;-joined
arrays where sub-rows disagree. These tests pin down that contract.
"""
import math

import numpy as np
import pandas as pd
import pytest

from main import (
    _AGGREGATE_PASS_THROUGH_COLS,
    _demote_int_float,
    _format_sub_value,
    _reduce_group,
    aggregate_by_input_id,
)


# ── _format_sub_value ──────────────────────────────────────────────────────


@pytest.mark.parametrize("v,expected", [
    (None, ""),
    (float("nan"), ""),
    (1234, "1234"),
    (1234.0, "1234"),       # integer-valued float demotes
    (1234.5, "1234.5"),     # real float keeps decimals
    ("hello", "hello"),
    (0, "0"),
])
def test_format_sub_value(v, expected):
    assert _format_sub_value(v) == expected


# ── _demote_int_float ──────────────────────────────────────────────────────


@pytest.mark.parametrize("v,expected", [
    (1234.0, 1234),
    (1234.5, 1234.5),
    ("string", "string"),
    (None, None),
    (1234, 1234),
])
def test_demote_int_float(v, expected):
    result = _demote_int_float(v)
    assert result == expected
    if expected == 1234 and v == 1234.0:
        assert isinstance(result, int)


def test_demote_int_float_nan_passes_through():
    result = _demote_int_float(float("nan"))
    assert isinstance(result, float) and math.isnan(result)


# ── aggregate_by_input_id: single-row groups (no aggregation) ──────────────


def _build_df(rows):
    """
    Helper: build a DataFrame from a list of dicts, preserving order.
    """
    return pd.DataFrame(rows)


def test_aggregate_no_input_id_passes_through():
    """If there's no input_id column, the function is a no-op."""
    df = _build_df([{"av_egid": 1234, "volume_above_ground_m3": 100.0}])
    out = aggregate_by_input_id(df)
    assert len(out) == 1
    assert out.iloc[0]["av_egid"] == 1234


def test_aggregate_empty_df_passes_through():
    df = _build_df([])
    out = aggregate_by_input_id(df)
    assert len(out) == 0


def test_aggregate_single_row_groups_unchanged():
    """Every input_id appears once → output identical to input."""
    df = _build_df([
        {"input_id": "A", "av_egid": 1, "fid": "f1",
         "area_footprint_m2": 100.0, "volume_above_ground_m3": 1000.0,
         "warnings": "", "status_step3": "success"},
        {"input_id": "B", "av_egid": 2, "fid": "f2",
         "area_footprint_m2": 200.0, "volume_above_ground_m3": 2000.0,
         "warnings": "", "status_step3": "success"},
    ])
    out = aggregate_by_input_id(df)
    assert len(out) == 2
    assert out.iloc[0]["av_egid"] == 1
    assert out.iloc[1]["av_egid"] == 2
    # Numeric columns stay numeric (not strings) for unaggregated rows
    assert out.iloc[0]["area_footprint_m2"] == 100.0


# ── aggregate_by_input_id: multi-row groups (aggregation) ──────────────────


def test_aggregate_multi_polygon_one_egid_arrays():
    """
    Same EGID, two AV polygons → one output row, fid becomes a ;-joined
    array, footprint becomes a ;-joined array (different per polygon),
    av_egid stays scalar (same), gkat stays scalar (same).
    """
    df = _build_df([
        {"input_id": "A", "av_egid": 1234, "fid": "f1",
         "area_footprint_m2": 100.0, "volume_above_ground_m3": 1000.0,
         "gkat": 1110, "gklas": 1110,
         "warnings": "EGID 1234 matched 2 AV polygons",
         "status_step3": "success"},
        {"input_id": "A", "av_egid": 1234, "fid": "f2",
         "area_footprint_m2": 150.0, "volume_above_ground_m3": 1200.0,
         "gkat": 1110, "gklas": 1110,
         "warnings": "EGID 1234 matched 2 AV polygons",
         "status_step3": "success"},
    ])
    out = aggregate_by_input_id(df)
    assert len(out) == 1
    row = out.iloc[0]
    # av_egid stays scalar — both sub-rows agree
    assert row["av_egid"] == 1234
    # gkat/gklas stay scalar — both sub-rows agree
    assert row["gkat"] == 1110
    # fid becomes ;-joined — sub-rows differ
    assert row["fid"] == "f1; f2"
    # numeric metrics become ;-joined — sub-rows differ
    assert row["area_footprint_m2"] == "100; 150"
    assert row["volume_above_ground_m3"] == "1000; 1200"
    # Aggregation note appended to warnings
    assert "AV polygons for one EGID" in row["warnings"]
    assert "EGID 1234 matched 2 AV polygons" in row["warnings"]


def test_aggregate_multi_egid_input_arrays():
    """
    Multi-EGID input cell → multiple distinct EGIDs → arrays everywhere.
    """
    df = _build_df([
        {"input_id": "A", "av_egid": 1234, "fid": "f1",
         "area_footprint_m2": 100.0, "volume_above_ground_m3": 1000.0,
         "gkat": 1110, "gklas": 1110,
         "warnings": "Input cell contained 2 EGIDs: 1234, 5678",
         "status_step3": "success"},
        {"input_id": "A", "av_egid": 5678, "fid": "f2",
         "area_footprint_m2": 200.0, "volume_above_ground_m3": 2500.0,
         "gkat": 1110, "gklas": 1220,  # different gklas → array
         "warnings": "Input cell contained 2 EGIDs: 1234, 5678",
         "status_step3": "success"},
    ])
    out = aggregate_by_input_id(df)
    assert len(out) == 1
    row = out.iloc[0]
    # av_egid becomes ;-joined (different)
    assert row["av_egid"] == "1234; 5678"
    # gkat stays scalar (both 1110)
    assert row["gkat"] == 1110
    # gklas becomes ;-joined (1110 vs 1220)
    assert row["gklas"] == "1110; 1220"
    # Aggregation note matches the multi-EGID branch (not the multi-polygon one)
    assert "distinct EGIDs" in row["warnings"]
    assert "fix the input CSV" in row["warnings"]


def test_aggregate_multi_egid_partial_match_empty_slots():
    """
    Multi-EGID input where some sub-EGIDs failed to find an AV polygon
    → array contains empty strings at the failed positions.
    """
    df = _build_df([
        {"input_id": "A", "av_egid": 1234, "fid": "f1",
         "area_footprint_m2": 100.0, "volume_above_ground_m3": 1000.0,
         "warnings": "", "status_step3": "success"},
        {"input_id": "A", "av_egid": None, "fid": None,
         "area_footprint_m2": None, "volume_above_ground_m3": None,
         "warnings": "", "status_step3": "skipped:no_footprint"},
        {"input_id": "A", "av_egid": 5678, "fid": "f3",
         "area_footprint_m2": 200.0, "volume_above_ground_m3": 2000.0,
         "warnings": "", "status_step3": "success"},
    ])
    out = aggregate_by_input_id(df)
    assert len(out) == 1
    row = out.iloc[0]
    # The failed position (index 1) shows as empty between two ;
    assert row["av_egid"] == "1234; ; 5678"
    assert row["fid"] == "f1; ; f3"
    assert row["area_footprint_m2"] == "100; ; 200"
    # Status rolls up to success because at least one sub-row succeeded
    assert row["status_step3"] == "success"


def test_aggregate_status_rollup_all_failed():
    """
    All sub-rows failed → aggregate keeps the first sub-row's failure
    status (so downstream filtering works).
    """
    df = _build_df([
        {"input_id": "A", "av_egid": 1234, "fid": None, "area_footprint_m2": None,
         "warnings": "", "status_step3": "skipped:no_footprint"},
        {"input_id": "A", "av_egid": 5678, "fid": None, "area_footprint_m2": None,
         "warnings": "", "status_step3": "skipped:no_footprint"},
    ])
    out = aggregate_by_input_id(df)
    assert out.iloc[0]["status_step3"] == "skipped:no_footprint"


def test_aggregate_warnings_deduplicated():
    """
    The same warning text repeated across sub-rows must NOT appear twice
    in the aggregated warnings — it's deduplicated.
    """
    df = _build_df([
        {"input_id": "A", "av_egid": 1234, "fid": "f1",
         "area_footprint_m2": 100.0, "warnings": "duplicate warning",
         "status_step3": "success"},
        {"input_id": "A", "av_egid": 1234, "fid": "f2",
         "area_footprint_m2": 150.0, "warnings": "duplicate warning",
         "status_step3": "success"},
    ])
    out = aggregate_by_input_id(df)
    parts = out.iloc[0]["warnings"].split("; ")
    # "duplicate warning" should appear at most once + the aggregation note
    duplicate_count = sum(1 for p in parts if p == "duplicate warning")
    assert duplicate_count == 1


def test_aggregate_demotes_integer_floats_in_object_cols():
    """
    Cosmetic fix: when aggregation forces a column to object dtype,
    integer-valued floats from non-aggregated rows must be written as
    "1234567" not "1234567.0".
    """
    df = _build_df([
        # First group: aggregated → av_egid becomes string
        {"input_id": "A", "av_egid": 1234.0, "fid": "f1",
         "area_footprint_m2": 100.0, "warnings": "", "status_step3": "success"},
        {"input_id": "A", "av_egid": 5678.0, "fid": "f2",
         "area_footprint_m2": 150.0, "warnings": "", "status_step3": "success"},
        # Second group: not aggregated → av_egid stays as a value
        {"input_id": "B", "av_egid": 9999.0, "fid": "f3",
         "area_footprint_m2": 200.0, "warnings": "", "status_step3": "success"},
    ])
    out = aggregate_by_input_id(df)
    # The column is object dtype now (mixed string + float)
    assert out["av_egid"].dtype == object
    # The non-aggregated row should be int 9999, not float 9999.0
    row_b = out[out["input_id"] == "B"].iloc[0]
    assert row_b["av_egid"] == 9999
    assert isinstance(row_b["av_egid"], int)


def test_aggregate_pass_through_cols_not_arrayed():
    """
    Columns in _AGGREGATE_PASS_THROUGH_COLS (input_id, status_*, warnings)
    must not be ;-joined even if they differ — they have special handling
    elsewhere in _reduce_group or are the group key.
    """
    assert "input_id" in _AGGREGATE_PASS_THROUGH_COLS
    assert "status_step3" in _AGGREGATE_PASS_THROUGH_COLS
    assert "warnings" in _AGGREGATE_PASS_THROUGH_COLS


def test_aggregate_preserves_column_order():
    """The output schema must match the input schema (same columns, same order)."""
    df = _build_df([
        {"input_id": "A", "av_egid": 1, "fid": "f1", "area_footprint_m2": 100.0,
         "warnings": "", "status_step3": "success"},
    ])
    out = aggregate_by_input_id(df)
    assert list(out.columns) == list(df.columns)
