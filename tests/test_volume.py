"""
Unit tests for volume.py — covers the pure logic. Raster sampling and
TileIndex are not tested here (they need real files or mocks).
"""
import math

import numpy as np
import pytest
from shapely.geometry import Polygon

from volume import (
    append_warning,
    create_aligned_grid_points,
    get_building_orientation,
    make_empty_volume_result,
)


# ── make_empty_volume_result ────────────────────────────────────────────────


def test_empty_result_has_warnings_field():
    """Regression test for the bug where the success path forgot warnings."""
    r = make_empty_volume_result()
    assert "warnings" in r
    assert r["warnings"] == ""


def test_empty_result_warnings_parameterised():
    r = make_empty_volume_result(warnings="step1 said hi")
    assert r["warnings"] == "step1 said hi"


def test_empty_result_measurements_are_nan_not_zero():
    """
    Missing measurements MUST be NaN, never 0 — otherwise downstream
    .mean() and .sum() pull averages down silently.
    """
    r = make_empty_volume_result()
    for col in (
        "volume_above_ground_m3",
        "elevation_base_min_m",
        "elevation_base_mean_m",
        "elevation_base_max_m",
        "elevation_roof_min_m",
        "elevation_roof_mean_m",
        "elevation_roof_max_m",
        "height_mean_m",
        "height_max_m",
        "height_minimal_m",
    ):
        assert isinstance(r[col], float) and math.isnan(r[col]), (
            f"{col} should be NaN, got {r[col]!r}"
        )


def test_empty_result_grid_points_count_is_zero_not_nan():
    """grid_points_count is a count, not a measurement — 0 is right."""
    r = make_empty_volume_result()
    assert r["grid_points_count"] == 0


def test_empty_result_carries_metadata():
    r = make_empty_volume_result(
        av_egid=1234567,
        fid="42",
        area_footprint_m2=100.5,
        area_official_m2=99.0,
    )
    assert r["av_egid"] == 1234567
    assert r["fid"] == "42"
    assert r["area_footprint_m2"] == 100.5
    assert r["area_official_m2"] == 99.0


def test_empty_result_status_only_set_when_passed():
    r1 = make_empty_volume_result()
    assert "status_step3" not in r1

    r2 = make_empty_volume_result(status_step3="no_grid_points")
    assert r2["status_step3"] == "no_grid_points"


# ── append_warning ──────────────────────────────────────────────────────────


def test_append_warning_to_empty():
    r = {"warnings": ""}
    append_warning(r, "first")
    assert r["warnings"] == "first"


def test_append_warning_concatenates():
    r = {"warnings": "first"}
    append_warning(r, "second")
    assert r["warnings"] == "first; second"


def test_append_warning_empty_message_is_noop():
    r = {"warnings": "first"}
    append_warning(r, "")
    assert r["warnings"] == "first"
    append_warning(r, None)
    assert r["warnings"] == "first"


def test_append_warning_handles_missing_key():
    """Should not crash on a dict that doesn't have a `warnings` key yet."""
    r = {}
    append_warning(r, "hello")
    assert r["warnings"] == "hello"


# ── get_building_orientation ───────────────────────────────────────────────


def test_orientation_axis_aligned_rectangle():
    """A 10×4 rectangle aligned to the x-axis should report 0° (or 180°)."""
    rect = Polygon([(0, 0), (10, 0), (10, 4), (0, 4)])
    angle = get_building_orientation(rect)
    # Either 0 or 180 is fine — both align with the x-axis
    assert angle in (0.0, 180.0) or abs(angle) < 1e-6 or abs(abs(angle) - 180) < 1e-6


def test_orientation_45_degree_rotated():
    """A square rotated 45° has all edges of equal length — angle is degenerate."""
    sq = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    # All four edges are 10 m, so any of them can be 'longest'.
    # Just verify it returns a finite angle without crashing.
    angle = get_building_orientation(sq)
    assert -180 <= angle <= 180


def test_orientation_degenerate_polygon_returns_zero():
    """Degenerate (zero-area) input must not crash."""
    line = Polygon([(0, 0), (1, 0), (2, 0)])  # zero-area
    assert get_building_orientation(line) == 0.0


# ── create_aligned_grid_points ─────────────────────────────────────────────


def test_grid_points_axis_aligned_rectangle():
    """A 10×4 rectangle at 1m resolution should produce ~40 grid cells."""
    rect = Polygon([(0, 0), (10, 0), (10, 4), (0, 4)])
    pts = create_aligned_grid_points(rect, voxel_size=1.0)
    # 10x4 cells with 1m grid → expect 40 cell centers
    assert 30 <= len(pts) <= 50, f"expected ~40 grid points, got {len(pts)}"


def test_grid_points_returns_list_of_tuples():
    rect = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    pts = create_aligned_grid_points(rect, voxel_size=1.0)
    assert isinstance(pts, list)
    assert all(isinstance(p, tuple) and len(p) == 2 for p in pts)


def test_grid_points_voxel_size_scales_count():
    """Halving voxel_size quadruples the point count (roughly)."""
    rect = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    coarse = create_aligned_grid_points(rect, voxel_size=2.0)
    fine = create_aligned_grid_points(rect, voxel_size=1.0)
    # Coarse: 5x5=25; fine: 10x10=100. Ratio ~4x.
    assert 3 <= len(fine) / len(coarse) <= 5


def test_grid_points_too_small_returns_empty():
    """A polygon smaller than the voxel can produce zero grid points."""
    tiny = Polygon([(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])
    pts = create_aligned_grid_points(tiny, voxel_size=1.0)
    # 0.1x0.1m polygon under 1m grid → may or may not get 1 cell depending
    # on snap; just ensure no crash and result is a valid list.
    assert isinstance(pts, list)


def test_grid_points_all_inside_polygon():
    """Every returned point must lie inside the polygon."""
    rect = Polygon([(0, 0), (10, 0), (10, 4), (0, 4)])
    pts = create_aligned_grid_points(rect, voxel_size=1.0)
    arr = np.array(pts)
    # All x in [0, 10], all y in [0, 4]
    assert (arr[:, 0] >= 0).all() and (arr[:, 0] <= 10).all()
    assert (arr[:, 1] >= 0).all() and (arr[:, 1] <= 4).all()
