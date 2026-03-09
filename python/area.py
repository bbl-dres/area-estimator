#!/usr/bin/env python3
"""
Step 4 — Estimate Floor Areas

Converts building volume to gross floor area using building-type-specific
floor heights from the GWR classification.

Based on the Canton Zurich methodology (Seiler & Seiler GmbH, Dec 2020).

Uses height_minimal_m (volume / footprint) rather than height_mean_m for
floor count estimation, as it represents the equivalent uniform box height
and handles complex roof shapes more consistently.
"""

import math

# Floor height lookup table
# Format: code -> (GF_min, GF_max, UF_min, UF_max, schema, description)
# GF = ground floor, UF = upper floors
FLOOR_HEIGHT_LOOKUP = {
    # GKAT-based (category)
    '1010': (2.70, 3.30, 2.70, 3.30, 'GKAT', 'Provisional shelter'),
    '1030': (2.70, 3.30, 2.70, 3.30, 'GKAT', 'Residential with secondary use'),
    '1040': (3.30, 3.70, 2.70, 3.70, 'GKAT', 'Partially residential'),
    '1060': (3.30, 5.00, 3.00, 5.00, 'GKAT', 'Non-residential'),
    '1080': (3.00, 4.00, 3.00, 4.00, 'GKAT', 'Special-purpose'),

    # GKLAS-based (class) — Residential
    '1110': (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Single-family house'),
    '1121': (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Two-family house'),
    '1122': (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Multi-family house'),
    '1130': (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Community residential'),

    # GKLAS — Hotels and Tourism
    '1211': (3.30, 3.70, 3.00, 3.50, 'GKLAS', 'Hotel'),
    '1212': (3.00, 3.50, 3.00, 3.50, 'GKLAS', 'Short-term accommodation'),

    # GKLAS — Commercial and Industrial
    '1220': (3.40, 4.20, 3.40, 4.20, 'GKLAS', 'Office building'),
    '1230': (3.40, 5.00, 3.40, 5.00, 'GKLAS', 'Wholesale and retail'),
    '1231': (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Restaurants and bars'),
    '1241': (4.00, 6.00, 4.00, 6.00, 'GKLAS', 'Stations and terminals'),
    '1242': (2.80, 3.20, 2.80, 3.20, 'GKLAS', 'Parking garages'),
    '1251': (4.00, 7.00, 4.00, 7.00, 'GKLAS', 'Industrial building'),
    '1252': (3.50, 6.00, 3.50, 6.00, 'GKLAS', 'Tanks, silos, warehouses'),
    '1261': (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Culture and leisure'),
    '1262': (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Museums and libraries'),
    '1263': (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Schools and universities'),
    '1264': (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Hospitals and clinics'),
    '1265': (3.00, 6.00, 3.00, 6.00, 'GKLAS', 'Sports halls'),
    '1271': (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Agricultural buildings'),
    '1272': (3.00, 6.00, 3.00, 6.00, 'GKLAS', 'Churches and religious buildings'),
    '1273': (3.00, 4.00, 3.00, 4.00, 'GKLAS', 'Monuments and protected buildings'),
    '1274': (3.00, 4.00, 3.00, 4.00, 'GKLAS', 'Other structures'),
}

DEFAULT_FLOOR_HEIGHT = (2.70, 3.30, 2.70, 3.30, 'DEFAULT', 'Unknown/Fallback')

ACCURACY_HIGH = 'high'       # ±10-15% — residential
ACCURACY_MEDIUM = 'medium'   # ±15-25% — commercial/office
ACCURACY_LOW = 'low'         # ±25-40% — industrial, special, missing


def _safe_int_str(value):
    """Convert a numeric value to string, handling NaN/None safely."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return str(int(value))
    except (ValueError, TypeError):
        return None


def get_floor_height(gkat, gklas):
    """
    Look up floor height parameters based on GWR classification.

    Priority: GKLAS (specific) → GKAT (category) → default residential.

    Returns: (floor_height_min, floor_height_max, schema_used, description)
    """
    # Try GKLAS first
    gklas_str = _safe_int_str(gklas)
    if gklas_str and gklas_str in FLOOR_HEIGHT_LOOKUP:
        entry = FLOOR_HEIGHT_LOOKUP[gklas_str]
        if entry[4] == 'GKLAS':
            min_h = (entry[0] + entry[2]) / 2
            max_h = (entry[1] + entry[3]) / 2
            return (min_h, max_h, 'GKLAS', entry[5])

    # Try GKAT
    gkat_str = _safe_int_str(gkat)
    if gkat_str and gkat_str in FLOOR_HEIGHT_LOOKUP:
        entry = FLOOR_HEIGHT_LOOKUP[gkat_str]
        if entry[4] == 'GKAT':
            min_h = (entry[0] + entry[2]) / 2
            max_h = (entry[1] + entry[3]) / 2
            return (min_h, max_h, 'GKAT', entry[5])

    # Default
    entry = DEFAULT_FLOOR_HEIGHT
    min_h = (entry[0] + entry[2]) / 2
    max_h = (entry[1] + entry[3]) / 2
    return (min_h, max_h, 'DEFAULT', entry[5])


def determine_accuracy(gkat, gklas, has_volume, has_footprint):
    """Determine accuracy level based on data quality and building type."""
    if not has_volume or not has_footprint:
        return ACCURACY_LOW

    if gkat is None and gklas is None:
        return ACCURACY_LOW

    cat_str = _safe_int_str(gkat) or ''
    cls_str = _safe_int_str(gklas) or ''

    # Residential — best accuracy
    if cat_str == '1020' or cls_str.startswith('11'):
        return ACCURACY_HIGH

    # Commercial/office
    if cls_str in ('1220', '1230', '1231', '1263', '1264'):
        return ACCURACY_MEDIUM

    # Industrial and special use
    if cls_str in ('1251', '1252', '1265', '1272') or cat_str in ('1060', '1080'):
        return ACCURACY_LOW

    return ACCURACY_MEDIUM


def estimate_floor_area(volume_result):
    """
    Estimate floor area for a single building from its volume result.

    Uses height_minimal_m (volume / footprint) for floor count estimation,
    as it represents the equivalent uniform box height and is more robust
    for complex building shapes than height_mean_m.

    Args:
        volume_result: Dict from volume.calculate_building_volume(),
                       enriched with gkat, gklas from gwr.enrich_with_gwr()

    Returns:
        Dict with area estimates added to the volume result
    """
    result = dict(volume_result)

    # Initialize area fields
    result.update({
        'area_floor_total_m2': None,
        'area_accuracy': None,
        'floors_estimated': None,
        'floor_height_used_m': None,
        'building_type': None,
        'status_step4': None,
    })

    footprint = result.get('area_footprint_m2', 0)
    volume = result.get('volume_above_ground_m3', 0)
    height_minimal = result.get('height_minimal_m', 0)

    if not footprint or footprint <= 0 or not volume or volume <= 0:
        result['status_step4'] = 'no_volume'
        return result

    # Use height_minimal_m (volume / footprint) for floor estimation
    if not height_minimal or height_minimal <= 0:
        height_minimal = volume / footprint

    if height_minimal > 200:
        result['status_step4'] = 'height_exceeds_200m'
        return result

    # Floor height lookup
    gkat = result.get('gkat')
    gklas = result.get('gklas')
    fh_min, fh_max, schema, description = get_floor_height(gkat, gklas)

    # Floor count from min/max floor heights
    floors_min = height_minimal / fh_max
    floors_max = height_minimal / fh_min
    floors_estimate = max(1.0, (floors_min + floors_max) / 2)
    floors_rounded = round(floors_estimate)

    # Gross floor area
    area_estimate = footprint * floors_estimate

    # Accuracy
    has_volume = volume is not None and volume > 0
    has_footprint = footprint is not None and footprint > 0
    accuracy = determine_accuracy(gkat, gklas, has_volume, has_footprint)

    result['area_floor_total_m2'] = round(area_estimate, 2)
    result['area_accuracy'] = accuracy
    result['floors_estimated'] = floors_rounded
    result['floor_height_used_m'] = round((fh_min + fh_max) / 2, 2)
    result['building_type'] = description
    result['status_step4'] = 'success'

    return result
