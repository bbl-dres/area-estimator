"""
Unit tests for area.py — covers the pure logic. Network paths
(query_gwr_api, enrich_with_gwr API mode) are not tested here.
"""
import math

import pandas as pd
import pytest

from area import (
    ACCURACY_HIGH,
    ACCURACY_LOW,
    ACCURACY_MEDIUM,
    DEFAULT_FLOOR_HEIGHT,
    FLOOR_HEIGHT_LOOKUP,
    HEIGHT_SANITY_CAP_M,
    MAX_FLOORS_FALLBACK,
    STATUS_HEIGHT_EXCEEDS_CAP,
    STATUS_NO_FOOTPRINT,
    STATUS_NO_VOLUME,
    STATUS_SUCCESS,
    _ACCURACY_BY_GKAT,
    _ACCURACY_BY_GKLAS,
    _GWR_OUTPUT_COLS,
    _to_gwr_code,
    determine_accuracy,
    estimate_floor_area,
    get_floor_height,
)
from volume import make_empty_volume_result


# ── _to_gwr_code ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value,expected", [
    (None, None),
    (float("nan"), None),
    ("", None),
    ("garbage", None),
    ("1234567", 1234567),
    (1234567, 1234567),
    (1234567.0, 1234567),
    (1234567.7, 1234567),  # truncates
    ("  1234  ", 1234),
    (0, 0),
    (-1, -1),
])
def test_to_gwr_code(value, expected):
    assert _to_gwr_code(value) == expected


def test_to_gwr_code_returns_int_type():
    """_to_gwr_code must return int (not numpy.int64) for downstream comparisons."""
    result = _to_gwr_code(1110.0)
    assert isinstance(result, int)


# ── get_floor_height ────────────────────────────────────────────────────────


def test_floor_height_gklas_takes_priority_over_gkat():
    """GKLAS is more specific, should win over GKAT."""
    fh_min, fh_max, src, desc = get_floor_height(gkat=1020, gklas=1110)
    assert src == "GKLAS"
    assert desc == "Single-family house"


def test_floor_height_gkat_fallback():
    fh_min, fh_max, src, desc = get_floor_height(gkat=1060, gklas=None)
    assert src == "GKAT"
    assert desc == "Non-residential"


def test_floor_height_unknown_codes_default():
    """Codes not in the lookup must fall through to DEFAULT, not crash."""
    fh_min, fh_max, src, desc = get_floor_height(gkat=99999, gklas=99999)
    assert src == "DEFAULT"


def test_floor_height_both_none_default():
    fh_min, fh_max, src, desc = get_floor_height(gkat=None, gklas=None)
    assert src == "DEFAULT"


def test_floor_height_office_known_value():
    """Office building (1220): GF and UF both 3.40-4.20m → midpoint 3.80m."""
    fh_min, fh_max, src, desc = get_floor_height(gkat=None, gklas=1220)
    assert src == "GKLAS"
    assert (fh_min + fh_max) / 2 == pytest.approx(3.80)


def test_floor_height_returns_floats_and_strings():
    fh_min, fh_max, src, desc = get_floor_height(gkat=None, gklas=1110)
    assert isinstance(fh_min, float) and isinstance(fh_max, float)
    assert isinstance(src, str) and isinstance(desc, str)


def test_floor_height_lookup_keys_are_int():
    """The lookup table must use int keys (not strings) for direct comparison."""
    for k in FLOOR_HEIGHT_LOOKUP:
        assert isinstance(k, int), f"key {k!r} is {type(k).__name__}, expected int"


# ── determine_accuracy ──────────────────────────────────────────────────────


def test_accuracy_missing_volume_or_footprint_low():
    assert determine_accuracy(1110, None, has_volume=False, has_footprint=True) == ACCURACY_LOW
    assert determine_accuracy(1110, None, has_volume=True, has_footprint=False) == ACCURACY_LOW


def test_accuracy_no_class_info_low():
    """Both gkat and gklas None → low (no information)."""
    assert determine_accuracy(gkat=None, gklas=None,
                              has_volume=True, has_footprint=True) == ACCURACY_LOW


def test_accuracy_default_source_forces_low():
    """
    S5 fix regression: when floor_height_source == 'DEFAULT', accuracy
    must be LOW even if the class codes are present (because we fell
    through the lookup table without a real match).
    """
    assert determine_accuracy(gkat=99999, gklas=99999,
                              has_volume=True, has_footprint=True,
                              floor_height_source="DEFAULT") == ACCURACY_LOW


# ── Per-code accuracy buckets (derived from docs/Height Assumptions.md) ────
#
# Every code in FLOOR_HEIGHT_LOOKUP must have an explicit accuracy
# assignment. The expected buckets below come from the validation study,
# mapped 5→3 levels conservatively (Medium-High → medium, Low-Medium → low).
# Drift between the table and the dict will cause one of these tests to
# fail loudly.

@pytest.mark.parametrize("gklas,expected", [
    # Residential — High in the study
    (1110, ACCURACY_HIGH),   # Single-family house
    (1121, ACCURACY_HIGH),   # Two-family house
    (1122, ACCURACY_HIGH),   # Multi-family house
    (1130, ACCURACY_MEDIUM), # Community residential — Medium-High → medium
    # Hotels / Tourism — Medium
    (1211, ACCURACY_MEDIUM), # Hotel
    (1212, ACCURACY_MEDIUM), # Short-term accommodation
    # Commercial / Office
    (1220, ACCURACY_MEDIUM), # Office building — Medium-High → medium
    (1230, ACCURACY_MEDIUM), # Wholesale and retail — Medium
    (1231, ACCURACY_MEDIUM), # Restaurants and bars — Medium
    (1241, ACCURACY_LOW),    # Stations and terminals — Low-Medium → low
    (1242, ACCURACY_MEDIUM), # Parking garages — Medium
    # Industrial
    (1251, ACCURACY_MEDIUM), # Industrial building — Medium-High → medium
    (1252, ACCURACY_LOW),    # Tanks, silos, warehouses — Low-Medium → low
    # Cultural / Public
    (1261, ACCURACY_LOW),    # Culture and leisure — Low-Medium → low
    (1262, ACCURACY_LOW),    # Museums and libraries — Low-Medium → low
    (1263, ACCURACY_HIGH),   # Schools and universities — High
    (1264, ACCURACY_MEDIUM), # Hospitals and clinics — Medium-High → medium
    (1265, ACCURACY_MEDIUM), # Sports halls — Medium
    # Special / Heritage
    (1271, ACCURACY_LOW),    # Agricultural buildings — Low-Medium → low
    (1272, ACCURACY_LOW),    # Churches and religious — Low
    (1273, ACCURACY_LOW),    # Monuments and protected — Low
    (1274, ACCURACY_LOW),    # Other structures — Low
])
def test_accuracy_per_gklas(gklas, expected):
    assert determine_accuracy(gkat=None, gklas=gklas,
                              has_volume=True, has_footprint=True) == expected


@pytest.mark.parametrize("gkat,expected", [
    (1010, ACCURACY_MEDIUM), # Provisional shelter — Medium
    (1020, ACCURACY_HIGH),   # Residential single-house parent — High
    (1030, ACCURACY_HIGH),   # Residential w/ secondary use — High
    (1040, ACCURACY_MEDIUM), # Partially residential — Medium-High → medium
    (1060, ACCURACY_MEDIUM), # Non-residential — Medium
    (1080, ACCURACY_LOW),    # Special-purpose — Low-Medium → low
])
def test_accuracy_per_gkat(gkat, expected):
    assert determine_accuracy(gkat=gkat, gklas=None,
                              has_volume=True, has_footprint=True) == expected


def test_accuracy_dicts_cover_every_lookup_code():
    """
    Every code in FLOOR_HEIGHT_LOOKUP must have an accuracy assignment
    in either _ACCURACY_BY_GKLAS or _ACCURACY_BY_GKAT — otherwise it
    silently falls through to the catch-all and we lose the per-code
    confidence rating from the validation study.
    """
    missing = []
    for code, entry in FLOOR_HEIGHT_LOOKUP.items():
        schema = entry[4]  # 'GKAT' or 'GKLAS'
        if schema == 'GKLAS' and code not in _ACCURACY_BY_GKLAS:
            missing.append((code, 'GKLAS', entry[5]))
        elif schema == 'GKAT' and code not in _ACCURACY_BY_GKAT:
            missing.append((code, 'GKAT', entry[5]))
    assert not missing, (
        f"FLOOR_HEIGHT_LOOKUP codes without accuracy assignment: {missing}"
    )


def test_accuracy_gklas_takes_priority_over_gkat():
    """When both gkat and gklas are provided, GKLAS wins (more specific)."""
    # gklas=1272 (Churches → low) should beat gkat=1020 (residential → high)
    assert determine_accuracy(gkat=1020, gklas=1272,
                              has_volume=True, has_footprint=True) == ACCURACY_LOW


def test_accuracy_unknown_code_falls_through_to_medium():
    """A code not in either dict (e.g. a future GWR revision) → medium catch-all."""
    assert determine_accuracy(gkat=99998, gklas=99999,
                              has_volume=True, has_footprint=True) == ACCURACY_MEDIUM


# ── estimate_floor_area ─────────────────────────────────────────────────────


def _success_input(footprint=100.0, volume=900.0, height=9.0, gklas=1110, gastw=None):
    """Convenience: build a volume_result dict that estimate_floor_area accepts."""
    r = make_empty_volume_result(area_footprint_m2=footprint)
    r["volume_above_ground_m3"] = volume
    r["height_minimal_m"] = height
    r["gklas"] = gklas
    if gastw is not None:
        r["gastw"] = gastw
    return r


def test_estimate_happy_path_residential():
    """100 m² footprint, 900 m³ volume, 9 m height, SFH (3.0 m floors) → 3 floors → 300 m²."""
    r = _success_input()
    out = estimate_floor_area(r)
    assert out["status_step4"] == STATUS_SUCCESS
    assert out["floors_estimated"] == 3
    assert out["area_floor_total_m2"] == pytest.approx(300.0)
    assert out["floor_height_source"] == "GKLAS"
    assert out["building_type"] == "Single-family house"
    assert out["area_accuracy"] == ACCURACY_HIGH


def test_estimate_no_footprint_status():
    """Missing footprint → status_step4 = no_footprint, distinct from no_volume."""
    r = make_empty_volume_result()  # no footprint, no volume
    r["volume_above_ground_m3"] = 100.0  # has volume but no footprint
    out = estimate_floor_area(r)
    assert out["status_step4"] == STATUS_NO_FOOTPRINT


def test_estimate_no_volume_status():
    """Has footprint but missing volume → status = no_volume."""
    r = make_empty_volume_result(area_footprint_m2=100.0)
    # volume stays NaN
    out = estimate_floor_area(r)
    assert out["status_step4"] == STATUS_NO_VOLUME


def test_estimate_height_exceeds_cap():
    """Anything above HEIGHT_SANITY_CAP_M is rejected as bad data."""
    r = _success_input(volume=10_000_000, height=HEIGHT_SANITY_CAP_M + 50)
    out = estimate_floor_area(r)
    assert out["status_step4"] == STATUS_HEIGHT_EXCEEDS_CAP


def test_estimate_gastw_caps_floors():
    """If GWR says the building has 3 floors, the estimate must not exceed 3."""
    # 15m / 3.0m would give 5 floors, but gastw=3 caps it
    r = _success_input(footprint=100.0, volume=1500.0, height=15.0, gklas=1110, gastw=3)
    out = estimate_floor_area(r)
    assert out["floors_estimated"] == 3
    assert out["area_floor_total_m2"] == pytest.approx(300.0)


def test_estimate_gastw_zero_falls_back():
    """gastw=0 should be treated as 'no cap', not 'cap at 0'."""
    r = _success_input(footprint=100.0, volume=1500.0, height=15.0, gklas=1110, gastw=0)
    out = estimate_floor_area(r)
    # 15 / 3.0 = 5 floors, no cap
    assert out["floors_estimated"] == 5


def test_estimate_banker_rounding_fix():
    """
    Regression: Python's round() uses banker's rounding (round-half-to-even),
    so round(2.5) == 2, not 3. The JS web app uses round-half-away-from-zero.
    The fix is `int(floors_estimate + 0.5)`. Verify exactly 2.5 rounds to 3.
    """
    # height_minimal=7.5, floor_height=3.0 → floors_estimate=2.5
    r = _success_input(footprint=100.0, volume=750.0, height=7.5, gklas=1110)
    out = estimate_floor_area(r)
    assert out["floors_estimated"] == 3, "2.5 must round to 3, not banker's-rounded 2"


def test_estimate_default_class_appends_warning():
    """Unknown gkat/gklas → DEFAULT source → warning + low accuracy (S5)."""
    r = _success_input(gklas=99999)
    r["gkat"] = 99999
    out = estimate_floor_area(r)
    assert out["status_step4"] == STATUS_SUCCESS
    assert out["floor_height_source"] == "DEFAULT"
    assert out["area_accuracy"] == ACCURACY_LOW
    assert "no GWR class match" in out["warnings"]


def test_estimate_known_class_no_default_warning():
    """A real class match must NOT add the default-class warning."""
    r = _success_input(gklas=1110)
    out = estimate_floor_area(r)
    assert "no GWR class match" not in out["warnings"]


def test_estimate_preserves_input_warnings():
    """Step-1 warnings (e.g. multi-polygon) must survive into the Step-4 output."""
    r = _success_input(gklas=1110)
    r["warnings"] = "EGID matched 2 AV polygons"
    out = estimate_floor_area(r)
    assert "EGID matched 2 AV polygons" in out["warnings"]


def test_estimate_does_not_mutate_input():
    """estimate_floor_area must return a new dict, not mutate the input."""
    r = _success_input()
    r_copy = dict(r)
    estimate_floor_area(r)
    assert r == r_copy, "estimate_floor_area mutated its input dict"


# ── Schema invariants ──────────────────────────────────────────────────────


def test_gwr_output_cols_are_canonical():
    assert _GWR_OUTPUT_COLS == ("gkat", "gklas", "gbauj", "gastw")


def test_status_constants_are_strings():
    """Status constants must be strings — they're written to CSV."""
    for c in (STATUS_SUCCESS, STATUS_NO_FOOTPRINT, STATUS_NO_VOLUME, STATUS_HEIGHT_EXCEEDS_CAP):
        assert isinstance(c, str) and len(c) > 0


def test_default_floor_height_shape():
    """DEFAULT_FLOOR_HEIGHT must match the lookup table tuple shape."""
    assert len(DEFAULT_FLOOR_HEIGHT) == 6
    assert DEFAULT_FLOOR_HEIGHT[4] == "DEFAULT"
