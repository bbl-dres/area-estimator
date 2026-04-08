#!/usr/bin/env python3
"""
Step 4 — GWR Enrichment + Floor Area Estimation

Two responsibilities, both only used after volume calculation:

1. Enrich buildings with GWR (Federal Register of Buildings) classification
   — gkat, gklas, gbauj, gastw — via either a bulk CSV download (preferred,
   no network) or the swisstopo `find` REST endpoint as a single-call
   per-EGID fallback.

2. Convert building volume to gross floor area using building-type-specific
   floor heights, capped at the GWR `gastw` floor count when present.

Based on the Canton Zurich methodology (Seiler & Seiler GmbH, Dec 2020).

Uses height_minimal_m (volume / footprint) rather than height_mean_m for
floor count estimation, as it represents the equivalent uniform box height
and handles complex roof shapes more consistently.
"""

import json
import logging
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from volume import append_warning

log = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

# Refuse to estimate floors above this height — Roche Tower 1 (the tallest
# building in Switzerland) is 178 m, so anything taller is almost certainly
# bad data (a tower next to a much shorter building, or vegetation noise).
HEIGHT_SANITY_CAP_M = 200

# Hard ceiling for floor count when GWR `gastw` is unavailable.
MAX_FLOORS_FALLBACK = 200

# GWR `find` REST endpoint tuning
#
# The swisstopo API has no documented bulk endpoint for attribute lookup by
# EGID — `/MapServer/<layer>/<id1,id2,...>` exists but requires the exact
# featureId-with-suffix format which we don't know without first calling
# `find`. So we parallelise the find calls instead. Benchmarked at
# ~3× speedup over sequential at 10 workers, with diminishing returns past
# 20. Bump GWR_API_MAX_WORKERS for very large runs if the API tolerates it.
GWR_API_MAX_WORKERS = 10
GWR_API_TIMEOUT_S = 10
GWR_API_WARN_THRESHOLD = 100     # warn the user above this many API calls

# Floor height lookup table.
# Format: code -> (GF_min, GF_max, UF_min, UF_max, schema, description)
# GF = ground floor, UF = upper floors. Today the four numbers are averaged
# down to a single representative floor height — see get_floor_height.
FLOOR_HEIGHT_LOOKUP: "dict[int, tuple[float, float, float, float, str, str]]" = {
    # GKAT-based (category)
    1010: (2.70, 3.30, 2.70, 3.30, 'GKAT', 'Provisional shelter'),
    1030: (2.70, 3.30, 2.70, 3.30, 'GKAT', 'Residential with secondary use'),
    1040: (3.30, 3.70, 2.70, 3.70, 'GKAT', 'Partially residential'),
    1060: (3.30, 5.00, 3.00, 5.00, 'GKAT', 'Non-residential'),
    1080: (3.00, 4.00, 3.00, 4.00, 'GKAT', 'Special-purpose'),

    # GKLAS-based (class) — Residential
    1110: (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Single-family house'),
    1121: (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Two-family house'),
    1122: (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Multi-family house'),
    1130: (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Community residential'),

    # GKLAS — Hotels and Tourism
    1211: (3.30, 3.70, 3.00, 3.50, 'GKLAS', 'Hotel'),
    1212: (3.00, 3.50, 3.00, 3.50, 'GKLAS', 'Short-term accommodation'),

    # GKLAS — Commercial and Industrial
    1220: (3.40, 4.20, 3.40, 4.20, 'GKLAS', 'Office building'),
    1230: (3.40, 5.00, 3.40, 5.00, 'GKLAS', 'Wholesale and retail'),
    1231: (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Restaurants and bars'),
    1241: (4.00, 6.00, 4.00, 6.00, 'GKLAS', 'Stations and terminals'),
    1242: (2.80, 3.20, 2.80, 3.20, 'GKLAS', 'Parking garages'),
    1251: (4.00, 7.00, 4.00, 7.00, 'GKLAS', 'Industrial building'),
    1252: (3.50, 6.00, 3.50, 6.00, 'GKLAS', 'Tanks, silos, warehouses'),
    1261: (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Culture and leisure'),
    1262: (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Museums and libraries'),
    1263: (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Schools and universities'),
    1264: (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Hospitals and clinics'),
    1265: (3.00, 6.00, 3.00, 6.00, 'GKLAS', 'Sports halls'),
    1271: (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Agricultural buildings'),
    1272: (3.00, 6.00, 3.00, 6.00, 'GKLAS', 'Churches and religious buildings'),
    1273: (3.00, 4.00, 3.00, 4.00, 'GKLAS', 'Monuments and protected buildings'),
    1274: (3.00, 4.00, 3.00, 4.00, 'GKLAS', 'Other structures'),
}

DEFAULT_FLOOR_HEIGHT = (2.70, 3.30, 2.70, 3.30, 'DEFAULT', 'Unknown/Fallback')

ACCURACY_HIGH = 'high'       # ±10-15% — residential
ACCURACY_MEDIUM = 'medium'   # ±15-25% — commercial/office
ACCURACY_LOW = 'low'         # ±25-40% — industrial, special, missing

# Step 4 status codes
STATUS_SUCCESS = 'success'
STATUS_NO_FOOTPRINT = 'no_footprint'
STATUS_NO_VOLUME = 'no_volume'
STATUS_HEIGHT_EXCEEDS_CAP = f'height_exceeds_{HEIGHT_SANITY_CAP_M}m'


def _to_gwr_code(value):
    """
    Normalise a GWR code (gkat / gklas / gbauj / gastw) to ``int | None``.

    Accepts ints, floats (including NaN from pandas), strings, and None.
    Returns None for any value that can't be coerced to a clean int.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def get_floor_height(gkat, gklas):
    """
    Look up floor height parameters based on GWR classification.

    Priority: GKLAS (specific) → GKAT (category) → default residential.

    Returns: ``(floor_height_min, floor_height_max, source, description)``
    where ``source`` is one of ``'GKLAS'``, ``'GKAT'``, or ``'DEFAULT'``.
    """
    # Try GKLAS first
    gklas_int = _to_gwr_code(gklas)
    if gklas_int is not None:
        entry = FLOOR_HEIGHT_LOOKUP.get(gklas_int)
        if entry is not None and entry[4] == 'GKLAS':
            return ((entry[0] + entry[2]) / 2,
                    (entry[1] + entry[3]) / 2,
                    'GKLAS', entry[5])

    # Try GKAT
    gkat_int = _to_gwr_code(gkat)
    if gkat_int is not None:
        entry = FLOOR_HEIGHT_LOOKUP.get(gkat_int)
        if entry is not None and entry[4] == 'GKAT':
            return ((entry[0] + entry[2]) / 2,
                    (entry[1] + entry[3]) / 2,
                    'GKAT', entry[5])

    entry = DEFAULT_FLOOR_HEIGHT
    return ((entry[0] + entry[2]) / 2,
            (entry[1] + entry[3]) / 2,
            'DEFAULT', entry[5])


# Building-class buckets used by determine_accuracy. Pulled out of the
# function so they're greppable and easy to extend.
_ACCURACY_RESIDENTIAL_GKAT = {1020}
_ACCURACY_COMMERCIAL_GKLAS = {1220, 1230, 1231, 1263, 1264}
_ACCURACY_INDUSTRIAL_GKLAS = {1251, 1252, 1265, 1272}
_ACCURACY_INDUSTRIAL_GKAT = {1060, 1080}


def determine_accuracy(gkat, gklas, has_volume, has_footprint, floor_height_source=None):
    """
    Determine accuracy bucket from data quality and building type.

    If ``floor_height_source == 'DEFAULT'`` the floor-height lookup fell
    through to the residential default, meaning we have no class match for
    this building. Force LOW accuracy in that case so the output is honest
    about the uncertainty (and consistent with the warning that
    ``estimate_floor_area`` appends in the same path).
    """
    if not has_volume or not has_footprint:
        return ACCURACY_LOW

    if floor_height_source == 'DEFAULT':
        return ACCURACY_LOW

    gkat_int = _to_gwr_code(gkat)
    gklas_int = _to_gwr_code(gklas)
    if gkat_int is None and gklas_int is None:
        return ACCURACY_LOW

    # Residential — best accuracy. GKLAS 11xx is residential per GWR catalog.
    if gkat_int in _ACCURACY_RESIDENTIAL_GKAT or (
        gklas_int is not None and 1100 <= gklas_int < 1200
    ):
        return ACCURACY_HIGH

    if gklas_int in _ACCURACY_COMMERCIAL_GKLAS:
        return ACCURACY_MEDIUM

    if gklas_int in _ACCURACY_INDUSTRIAL_GKLAS or gkat_int in _ACCURACY_INDUSTRIAL_GKAT:
        return ACCURACY_LOW

    return ACCURACY_MEDIUM


def _is_missing(value):
    """True if value is None or NaN — used to detect upstream gaps."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def estimate_floor_area(volume_result):
    """
    Estimate floor area for a single building from its volume result.

    Uses ``height_minimal_m`` (volume / footprint) for floor count estimation
    — it represents the equivalent uniform box height and is more robust for
    complex building shapes than ``height_mean_m``.

    Args:
        volume_result: Dict from ``volume.calculate_building_volume()``,
            optionally enriched with ``gkat``, ``gklas``, ``gastw`` from
            ``area.enrich_with_gwr()``.

    Returns:
        A new dict with the original keys plus the area-estimation fields.
    """
    result = dict(volume_result)

    # Initialise area fields up front so the schema is consistent across
    # success and skip paths.
    result.update({
        'area_floor_total_m2': None,
        'area_accuracy': None,
        'floors_estimated': None,
        'floor_height_used_m': None,
        'floor_height_source': None,
        'building_type': None,
        'status_step4': None,
    })

    footprint = result.get('area_footprint_m2')
    volume = result.get('volume_above_ground_m3')
    height_minimal = result.get('height_minimal_m')

    # Distinguish "no footprint" from "no volume" so downstream filtering
    # can tell them apart.
    if _is_missing(footprint) or footprint <= 0:
        result['status_step4'] = STATUS_NO_FOOTPRINT
        return result
    if _is_missing(volume) or volume <= 0:
        result['status_step4'] = STATUS_NO_VOLUME
        return result

    # Fall back to volume/footprint if upstream didn't compute height_minimal.
    if _is_missing(height_minimal) or height_minimal <= 0:
        height_minimal = volume / footprint

    if height_minimal > HEIGHT_SANITY_CAP_M:
        result['status_step4'] = STATUS_HEIGHT_EXCEEDS_CAP
        return result

    # Floor height — collapse the min/max range to a single representative value.
    gkat = result.get('gkat')
    gklas = result.get('gklas')
    fh_min, fh_max, source, description = get_floor_height(gkat, gklas)
    floor_height = (fh_min + fh_max) / 2
    if source == 'DEFAULT':
        append_warning(result, 'no GWR class match — using default floor height')

    # Floor count = height_minimal ÷ floor_height, capped at GWR gastw if available.
    # `gastw_int or MAX_FLOORS_FALLBACK` treats both None and 0 as "no cap available".
    floors_estimate = max(1.0, height_minimal / floor_height)
    gastw_int = _to_gwr_code(result.get('gastw'))
    max_floors = gastw_int or MAX_FLOORS_FALLBACK
    floors_estimate = min(floors_estimate, float(max_floors))

    # Gross floor area uses the unrounded estimate so it stays consistent
    # with footprint × (height ÷ floor_height).
    area_estimate = footprint * floors_estimate

    accuracy = determine_accuracy(
        gkat, gklas,
        has_volume=True, has_footprint=True,
        floor_height_source=source,
    )

    result['area_floor_total_m2'] = round(area_estimate, 2)
    result['area_accuracy'] = accuracy
    # Round half-away-from-zero (matches the JS web app's Math.round and
    # avoids Python's banker's-rounding surprise where round(2.5) == 2).
    result['floors_estimated'] = int(floors_estimate + 0.5)
    result['floor_height_used_m'] = round(floor_height, 2)
    result['floor_height_source'] = source
    result['building_type'] = description
    result['status_step4'] = STATUS_SUCCESS

    return result


# ── GWR Enrichment ──────────────────────────────────────────────────────────
#
# Two data access methods, in order of cost:
#   1. Bulk CSV download from housing-stat.ch — zero network calls per building
#   2. swisstopo `find` REST endpoint — one network call per building (fallback)


# Columns we need from the GWR CSV (source name → internal name)
GWR_COLUMNS = {
    'EGID': 'egid',
    'GKAT': 'gkat',
    'GKLAS': 'gklas',
    'GBAUJ': 'gbauj',
    'GASTW': 'gastw',
}

# The four attribute fields we want from any GWR source (CSV or API).
# Used by both query_gwr_api and enrich_with_gwr.
_GWR_OUTPUT_COLS = ('gkat', 'gklas', 'gbauj', 'gastw')

GWR_FIND_URL = "https://api3.geo.admin.ch/rest/services/ech/MapServer/find"


def load_gwr_from_csv(csv_path):
    """
    Load GWR building data from a bulk CSV download.

    Source: https://www.housing-stat.ch/de/data/supply/public.html

    Returns:
        DataFrame indexed by EGID with columns: gkat, gklas, gbauj, gastw
    """
    log.info(f"Loading GWR data from {csv_path}...")

    df = pd.read_csv(csv_path, sep=';', dtype=str, low_memory=False)

    available = {src: dst for src, dst in GWR_COLUMNS.items() if src in df.columns}
    if 'EGID' not in available:
        raise ValueError(
            f"CSV does not contain EGID column. Found: {list(df.columns[:20])}"
        )

    df = df[list(available.keys())].rename(columns=available)

    for col in ['egid', 'gkat', 'gklas', 'gbauj', 'gastw']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=['egid'])
    df['egid'] = df['egid'].astype(int)
    df = df.set_index('egid')

    log.info(f"  Loaded {len(df)} buildings from GWR CSV")
    return df


def query_gwr_api(egid):
    """
    Fetch a single building's GWR attributes via swisstopo `find` (one HTTP call).

    Uses the ``ch.bfs.gebaeude_wohnungs_register`` layer with
    ``searchField=egid``, which returns full feature attributes in a single
    request — replacing the older Search → Detail two-call pattern.
    """
    result = {col: None for col in _GWR_OUTPUT_COLS}

    egid_int = _to_gwr_code(egid)
    if egid_int is None:
        return result

    # Canonical request — matches the curl in the swisstopo docs.
    # `sr` is intentionally omitted because returnGeometry=false means
    # there is no geometry to project.
    query = urllib.parse.urlencode({
        'layer': 'ch.bfs.gebaeude_wohnungs_register',
        'searchText': str(egid_int),
        'searchField': 'egid',
        'returnGeometry': 'false',
        'contains': 'false',
    })
    url = f"{GWR_FIND_URL}?{query}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=GWR_API_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        log.debug("GWR API query failed for EGID %s: %s", egid, e)
        return result

    results = data.get('results') or []
    if not results:
        return result

    # `find` returns features with attributes either under 'properties'
    # or 'attributes' depending on the geometry/SR settings. Pick whichever
    # key is *present* (not just truthy) so an empty 'properties' dict
    # doesn't silently fall through and mask a populated 'attributes'.
    feature = results[0]
    if 'properties' in feature:
        attrs = feature['properties'] or {}
    else:
        attrs = feature.get('attributes') or {}

    for col in _GWR_OUTPUT_COLS:
        if col in attrs:
            result[col] = attrs[col]

    return result


def enrich_with_gwr(buildings_df, gwr_csv_path=None):
    """
    Add GWR classification columns (gkat, gklas, gbauj, gastw) to a DataFrame.

    Uses the bulk CSV when ``gwr_csv_path`` is provided (zero network calls).
    Otherwise falls back to one API call per building with an EGID.
    """
    df = buildings_df.copy()

    for col in _GWR_OUTPUT_COLS:
        if col not in df.columns:
            df[col] = None

    # Prefer av_egid (from cadastral survey), fall back to user-supplied egid.
    if 'av_egid' in df.columns and df['av_egid'].notna().any():
        egid_col = 'av_egid'
    elif 'egid' in df.columns and df['egid'].notna().any():
        egid_col = 'egid'
    else:
        log.warning("No av_egid or egid column with values — skipping GWR enrichment")
        return df

    egids_available = df[egid_col].notna()
    n_with_egid = int(egids_available.sum())

    if gwr_csv_path:
        gwr_df = load_gwr_from_csv(gwr_csv_path)
        gwr_cols = [c for c in _GWR_OUTPUT_COLS if c in gwr_df.columns]

        # reindex aligns gwr_df rows to our EGIDs (NaN-filled where missing),
        # producing a frame with the same row order as our masked subset.
        keys = df.loc[egids_available, egid_col].astype(int)
        looked_up = gwr_df[gwr_cols].reindex(keys.values)
        looked_up.index = keys.index  # align back to df's row labels

        for col in gwr_cols:
            df.loc[egids_available, col] = looked_up[col].values

        matched = int(df.loc[egids_available, 'gkat'].notna().sum())
        log.info(f"  GWR CSV: matched {matched}/{n_with_egid} buildings")

    else:
        if n_with_egid > GWR_API_WARN_THRESHOLD:
            log.warning(
                f"Querying {n_with_egid} buildings via API "
                f"(parallel ×{GWR_API_MAX_WORKERS}). "
                f"Consider --gwr-csv for very large runs."
            )

        # Build (df_index, egid) pairs so we can write results back to the
        # right rows after the parallel pool returns out of order.
        targets = [
            (idx, int(df.at[idx, egid_col]))
            for idx in df.index[egids_available]
        ]

        log.info(
            f"  GWR API: parallel fetch ×{GWR_API_MAX_WORKERS} "
            f"for {n_with_egid} EGIDs"
        )
        t0 = time.monotonic()
        matched = 0
        completed = 0
        # ~20 progress lines, but always at least every 5 requests for small
        # batches and never more than every 50 for very large ones.
        progress_step = max(5, min(50, n_with_egid // 20 or 1))

        with ThreadPoolExecutor(max_workers=GWR_API_MAX_WORKERS) as ex:
            future_to_idx = {
                ex.submit(query_gwr_api, egid): (idx, egid)
                for idx, egid in targets
            }
            for fut in as_completed(future_to_idx):
                idx, egid = future_to_idx[fut]
                try:
                    attrs = fut.result()
                except Exception as e:  # noqa: BLE001 — log and continue
                    log.debug("GWR fetch raised for EGID %s: %s", egid, e)
                    attrs = {c: None for c in _GWR_OUTPUT_COLS}

                for col in _GWR_OUTPUT_COLS:
                    if attrs[col] is not None:
                        df.at[idx, col] = attrs[col]
                if attrs['gkat'] is not None:
                    matched += 1

                completed += 1
                if completed % progress_step == 0 or completed == n_with_egid:
                    elapsed = time.monotonic() - t0
                    rate = completed / elapsed if elapsed > 0 else 0
                    log.info(
                        f"  GWR API: [{completed}/{n_with_egid}] "
                        f"{rate:.1f} req/s"
                    )

        elapsed = time.monotonic() - t0
        log.info(
            f"  GWR API: matched {matched}/{n_with_egid} in {elapsed:.0f}s "
            f"({n_with_egid/elapsed:.0f} req/s)"
        )

    return df
