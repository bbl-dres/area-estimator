#!/usr/bin/env python3
"""
Step 1 — Load Building Footprints

Loads building polygons from one of three modes:
1. AV file only — every Gebaeude in the file (optionally bbox-filtered)
2. AV + CSV (EGID match, default) — looks each `egid` up against
   ``GWR_EGID`` in the AV file. Fast, unambiguous, requires AV polygons
   to carry an EGID. This is what the web app does.
3. AV + CSV (coordinate spatial join, opt-in) — for each ``lon``/``lat``
   point, finds the AV polygon that contains it. Slower but works for
   buildings that have no EGID assigned in the cadastral data.

All functions return a GeoDataFrame in LV95 (EPSG:2056) with columns:
    av_egid, fid, area_official_m2, geometry, status_step1, warnings
    (+ input_id, input_egid, etc. for CSV-driven modes)
"""

import json
import logging
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional, Union

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, shape

from volume import (
    STATUS_INVALID_EGID,
    STATUS_NO_FOOTPRINT,
    STATUS_OK,
)

log = logging.getLogger(__name__)

# Layer name for building polygons in Swiss AV GeoPackages (Bodenbedeckungsflaeche)
AV_BUILDING_LAYER = 'lcsf'
# Art value for buildings within the lcsf layer
AV_BUILDING_TYPE = 'Gebaeude'
# Buffer (m) around the union bbox of all input points when querying AV
# in coordinate spatial-join mode. Wide enough to include any building a
# point could realistically belong to (Swiss buildings rarely exceed 100m
# across) without pulling in unnecessary neighbours.
AV_POINT_BBOX_BUFFER_M = 200

# Warn the user when the union bbox of all input points covers more than
# this many square kilometres — that means a portfolio scattered across a
# huge area, and the single AV read might pull millions of features.
AV_UNION_BBOX_WARN_KM2 = 100


def load_footprints_from_file(
    filepath: Union[str, Path],
    bbox: Optional[tuple[float, float, float, float]] = None,
    limit: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """
    Load all building footprints from a geodata file (GeoPackage, Shapefile, GeoJSON).

    Filters to building polygons (type = "Gebaeude") if a type column exists.
    Preserves official area attribute as area_official_m2 for reference.

    Returns GeoDataFrame in LV95 with columns: av_egid, fid, area_official_m2, geometry, status_step1
    """
    log.info(f"Loading AV from {Path(filepath).name} (layer: {AV_BUILDING_LAYER}, Art={AV_BUILDING_TYPE})...")
    gdf = _load_av_buildings(filepath, bbox_lv95=bbox)

    if len(gdf) == 0:
        log.info("No features found in file")
        return gpd.GeoDataFrame()

    if limit:
        gdf = gdf.head(limit)

    gdf['status_step1'] = STATUS_OK
    gdf['warnings'] = ''
    log.info(f"  {len(gdf)} building footprints loaded")
    return gdf[['av_egid', 'fid', 'area_official_m2', 'geometry', 'status_step1', 'warnings']]


def _load_av_buildings(
    av_path: Union[str, Path],
    bbox_lv95: Optional[tuple[float, float, float, float]] = None,
    where_sql: Optional[str] = None,
) -> gpd.GeoDataFrame:
    """
    Internal helper: load and normalise an AV GeoPackage/Shapefile/GeoJSON.
    For GeoPackages, always reads the AV_BUILDING_LAYER ('lcsf').
    Returns a GeoDataFrame in LV95 with columns: av_egid, fid, area_official_m2, geometry.

    Args:
        av_path: Path to the AV file.
        bbox_lv95: Optional ``(minx, miny, maxx, maxy)`` in LV95 to pre-filter
            the file read at the GDAL/pyogrio level.
        where_sql: Optional SQL WHERE clause (no leading "WHERE") pushed down
            to the reader. Used by the EGID loader for IN-list filtering.

    Note: AV building features are guaranteed to be **single Polygons** —
    verified across all 2,465,446 ``Art = Gebaeude`` features in the
    Swiss AV file (0 MultiPolygons, 0 invalid geometries). The cadastral
    data model enforces single-polygon-per-building, so we don't need
    defensive ``make_valid()`` / ``unary_union()`` calls. Polygons with
    interior holes (~0.07% of buildings) are handled correctly by
    ``polygon.area`` and ``shapely.contains_xy``.
    """
    av_path = Path(av_path)
    if not av_path.exists():
        raise FileNotFoundError(f"AV file not found: {av_path}")

    kwargs = {}
    if bbox_lv95:
        kwargs['bbox'] = bbox_lv95
    if where_sql:
        kwargs['where'] = where_sql
    if av_path.suffix.lower() == '.gpkg':
        kwargs['layer'] = AV_BUILDING_LAYER

    gdf = gpd.read_file(av_path, **kwargs)

    if len(gdf) == 0:
        return gpd.GeoDataFrame(columns=['av_egid', 'fid', 'area_official_m2', 'geometry'],
                                 crs='EPSG:2056')

    gdf.columns = [c.lower() for c in gdf.columns]

    # Filter to buildings: Art = AV_BUILDING_TYPE ('Gebaeude')
    if 'art' in gdf.columns:
        gdf = gdf[gdf['art'] == AV_BUILDING_TYPE].copy()
    elif 'bbart' in gdf.columns:
        gdf = gdf[gdf['bbart'] == AV_BUILDING_TYPE].copy()

    # AV GeoPackage (lcsf) uses GWR_EGID; other sources may use egid
    egid_col = next((c for c in gdf.columns if c in ('gwr_egid', 'egid')), None)
    if egid_col:
        gdf = gdf.rename(columns={egid_col: 'av_egid'})
        gdf['av_egid'] = pd.to_numeric(gdf['av_egid'], errors='coerce')
    else:
        gdf['av_egid'] = None

    if 'fid' not in gdf.columns:
        gdf['fid'] = gdf.index.astype(str)

    area_col = next((c for c in gdf.columns if c in ('flaeche', 'area', 'shape_area')), None)
    if area_col:
        gdf['area_official_m2'] = pd.to_numeric(gdf[area_col], errors='coerce')
    else:
        # Compute from geometry (valid since we are already in a metric CRS)
        gdf['area_official_m2'] = gdf.geometry.area.round(2)

    if gdf.crs is None:
        gdf = gdf.set_crs('EPSG:2056')
    elif gdf.crs.to_epsg() != 2056:
        gdf = gdf.to_crs('EPSG:2056')

    return gdf[['av_egid', 'fid', 'area_official_m2', 'geometry']].reset_index(drop=True)


# Separators accepted between EGIDs in a multi-EGID input cell. Real-world
# CSVs use every combination of comma, slash, semicolon, and bare whitespace,
# often mixed within a single cell. The regex accepts any run of these
# characters as a single separator. Whitespace is included so that values
# like "1234 5678" (space-only), "1234\n5678" (line-break, surviving past
# csv-quoting), and "1234,\t5678" (comma + tab) all parse uniformly.
_EGID_SEPARATOR_RE = re.compile(r'[,/;\s]+')


def _parse_egid_cell(raw: Any) -> list[int]:
    """
    Parse a CSV ``egid`` cell into a list of valid (positive int) EGIDs.

    Accepted separators between EGIDs: ``,``, ``/``, ``;``, and any
    whitespace. They can be mixed and repeated within one cell.

    - ``None`` / NaN / empty → ``[]``
    - Single integer ("1234567") → ``[1234567]``
    - Multi-EGID with any separator(s):
        - "1234, 5678"     → ``[1234, 5678]``
        - "1234 / 5678"    → ``[1234, 5678]``
        - "1234;5678"      → ``[1234, 5678]``
        - "1234 5678"      → ``[1234, 5678]``  (whitespace alone)
        - "1234, 5678/9012;3456" → ``[1234, 5678, 9012, 3456]`` (mixed)
    - Any token that's not a positive integer (including 0, negatives,
      and non-numeric strings) poisons the whole cell → ``[]``. We
      never silently drop part of a multi-EGID list.

    Caller is responsible for the upstream cleanup pass that strips
    line breaks and collapses internal whitespace (see ``_read_input_csv``).
    """
    if pd.isna(raw):
        return []
    s = str(raw).strip()
    if not s:
        return []

    # Drop empty tokens that fall out of leading/trailing separators.
    tokens = [t for t in _EGID_SEPARATOR_RE.split(s) if t]
    if not tokens:
        return []

    result = []
    for token in tokens:
        try:
            as_float = float(token)
        except (TypeError, ValueError):
            return []
        # Reject NaN, inf, -inf — int(inf) raises OverflowError, NaN
        # would silently truncate to a meaningless integer.
        if not math.isfinite(as_float):
            return []
        n = int(as_float)
        if n <= 0:
            return []
        result.append(n)
    return result


def _normalise_cell(value: Any) -> Any:
    """
    Collapse every run of whitespace (spaces, tabs, line breaks, NBSPs)
    to a single space and strip leading/trailing whitespace. Returns
    NaN unchanged. Used by _read_input_csv to scrub every input cell
    before any per-column parsing runs — the project's input CSVs come
    from spreadsheets edited by hand and contain every kind of stray
    whitespace imaginable.
    """
    if pd.isna(value):
        return value
    # ' '.join(str(v).split()) collapses ALL Unicode whitespace runs.
    return ' '.join(str(value).split())


def _read_input_csv(csv_path: Union[str, Path]) -> pd.DataFrame:
    """
    Read a CSV with delimiter auto-detect, BOM handling, and a strict
    cell-cleanup pass.

    - The web app uses ``;``, the Python world expects ``,`` — sniffer
      auto-detect handles both so a single CSV works in both tools.
    - ``utf-8-sig`` transparently strips a UTF-8 BOM if one is present
      (Excel and many Windows tools save CSVs with BOM by default), so
      the first column header doesn't come through as ``\\ufeffid``.
    - Every cell goes through ``_normalise_cell``: tabs, line breaks,
      double spaces, and Unicode whitespace are collapsed to single
      ASCII spaces and trimmed. This means downstream parsers (like
      ``_parse_egid_cell``) only have to deal with clean strings, no
      matter what mess a colleague pasted into Excel.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    # python engine + sep=None enables csv.Sniffer auto-detection
    df = pd.read_csv(csv_path, sep=None, engine='python', encoding='utf-8-sig')
    df.columns = [c.lower().strip() for c in df.columns]

    # Cleanup pass: scrub whitespace in every string cell.
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(_normalise_cell)

    return df


def _prepare_egid_csv(
    csv_path: Union[str, Path],
    limit: Optional[int] = None,
) -> tuple[pd.DataFrame, list[int]]:
    """
    Read and validate a CSV with ``id``/``egid`` columns, parse EGID cells.

    Returns ``(df, all_egids)`` where *df* has columns ``input_id``,
    ``input_egid_raw``, ``parsed_egids`` (plus any extra CSV columns),
    and *all_egids* is a sorted de-duplicated list of valid EGIDs.
    """
    df = _read_input_csv(csv_path)

    missing = [c for c in ('id', 'egid') if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV missing required columns: {missing}. Found: {list(df.columns)}"
        )

    if limit:
        df = df.head(limit)

    df = df.rename(columns={'id': 'input_id'})
    df['input_egid_raw'] = df['egid']
    df['parsed_egids'] = df['egid'].apply(_parse_egid_cell)
    df = df.reset_index(drop=True)

    all_egids = sorted({e for lst in df['parsed_egids'] for e in lst})
    n_invalid = int((df['parsed_egids'].apply(len) == 0).sum())
    n_multi = int((df['parsed_egids'].apply(len) > 1).sum())

    log.info(
        f"Loaded {len(df)} rows from {Path(csv_path).name} "
        f"({len(all_egids)} unique valid EGIDs across {len(df) - n_invalid} rows, "
        f"{n_invalid} invalid"
        + (f", {n_multi} multi-EGID" if n_multi else "")
        + ")"
    )

    return df, all_egids


def load_footprints_from_av_with_egids(
    av_path: Union[str, Path],
    csv_path: Union[str, Path],
    limit: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """
    Load AV building footprints, filtered to a set of EGIDs from a CSV.

    For every input row, the building is looked up by ``egid`` against the
    AV layer's ``GWR_EGID`` column with a single push-down WHERE filter
    (one I/O for the whole batch). Each input row produces at least one
    output row:

    - **1 polygon match** — normal case, ``status_step1='ok'``.
    - **N polygons match** — emits *N* output rows, each carrying the same
      ``input_id``/``input_egid`` and a ``warnings`` entry noting the
      multiplicity. (This happens when a building is split across cadastral
      parcels.)
    - **0 polygons match** — emits one row with empty geometry and
      ``status_step1='no_footprint'``.
    - **EGID NaN/0/non-numeric** — ``status_step1='invalid_egid'``.

    Required CSV columns: ``id``, ``egid``
    Lon/lat columns are ignored if present.

    Returns GeoDataFrame in LV95 with columns:
        input_id, input_egid, av_egid, fid, area_official_m2,
        geometry, status_step1, warnings
    """
    df, all_egids = _prepare_egid_csv(csv_path, limit)

    # ── Single push-down read ─────────────────────────────────────────────
    av_by_egid: dict[int, list] = {}
    if all_egids:
        # GeoPackage WHERE pushdown via pyogrio. The IN list is fine for
        # the example case (~10 EGIDs); a portfolio of 50k+ may need
        # batching, but pyogrio handles fairly large IN lists in practice.
        where = f"GWR_EGID IN ({','.join(str(e) for e in all_egids)})"
        log.info(
            f"Querying AV: {Path(av_path).name} "
            f"(layer={AV_BUILDING_LAYER}, WHERE GWR_EGID IN [{len(all_egids)} ids])"
        )
        try:
            av = _load_av_buildings(av_path, where_sql=where)
        except Exception as e:
            # The most common cause is an AV file whose building layer uses
            # `egid` (or some other casing) instead of `GWR_EGID`. Re-raise
            # with a clearer hint pointing the user at --use-coordinates.
            raise ValueError(
                f"EGID-match Step 1 failed querying {Path(av_path).name}: {e}. "
                f"This usually means the AV file does not expose a GWR_EGID "
                f"column on the {AV_BUILDING_LAYER!r} layer. EGID-match only "
                f"works for AV-CH GeoPackages following the cadastral data "
                f"model — use --use-coordinates if your file does not."
            ) from e
        log.info(f"  AV returned {len(av)} polygons")

        # Group AV rows by EGID for fast lookup
        for egid_val, group in av.groupby('av_egid', dropna=True):
            av_by_egid[int(egid_val)] = list(group.itertuples(index=False))

    # ── Build output rows in CSV order ────────────────────────────────────
    #
    # Each input row produces ≥ 1 sub-rows: one per (parsed EGID × matching
    # AV polygon). All sub-rows from the same input row share `input_id`
    # and are aggregated back to a single output row by main.py at the
    # end of the pipeline.
    records = []
    matched = 0
    no_match = 0
    invalid = 0
    multi_polygon_hits = 0
    multi_egid_hits = 0

    for row in df.itertuples(index=False):
        input_id = row.input_id
        egids = row.parsed_egids  # list[int]

        # Invalid / unparseable cell
        if not egids:
            records.append(_egid_record(
                input_id=input_id,
                input_egid=row.input_egid_raw,
                av_egid=None, fid=None, geometry=None, area_official_m2=None,
                status=STATUS_INVALID_EGID,
                warnings=[f'EGID could not be parsed as a positive integer: {row.input_egid_raw!r}'],
            ))
            invalid += 1
            continue

        # Multi-EGID input → one warning shared by every sub-row from this input row
        base_warnings = []
        if len(egids) > 1:
            base_warnings.append(
                f'Input cell contained {len(egids)} EGIDs: '
                f'{", ".join(str(e) for e in egids)}'
            )
            multi_egid_hits += 1

        for egid_int in egids:
            matches = av_by_egid.get(egid_int)

            if not matches:
                records.append(_egid_record(
                    input_id=input_id, input_egid=egid_int,
                    av_egid=None, fid=None, geometry=None, area_official_m2=None,
                    status=STATUS_NO_FOOTPRINT,
                    warnings=list(base_warnings),
                ))
                no_match += 1
                continue

            sub_warnings = list(base_warnings)
            if len(matches) > 1:
                sub_warnings.append(
                    f'EGID {egid_int} matched {len(matches)} AV polygons'
                )
                multi_polygon_hits += 1

            for av_row in matches:
                records.append(_egid_record(
                    input_id=input_id,
                    input_egid=egid_int,
                    av_egid=av_row.av_egid,
                    fid=av_row.fid,
                    geometry=av_row.geometry,
                    area_official_m2=av_row.area_official_m2,
                    status=STATUS_OK,
                    warnings=list(sub_warnings),
                ))
                matched += 1

    log.info(
        f"  Matched: {matched}  no_footprint: {no_match}  invalid_egid: {invalid}"
        + (f"  multi-polygon EGIDs: {multi_polygon_hits}" if multi_polygon_hits else "")
        + (f"  multi-EGID inputs: {multi_egid_hits}" if multi_egid_hits else "")
    )

    return gpd.GeoDataFrame(records, crs='EPSG:2056')


def _egid_record(
    input_id: Any,
    input_egid: Any,
    av_egid: Any,
    fid: Any,
    geometry: Any,
    area_official_m2: Any,
    status: str,
    warnings: list[str],
) -> dict:
    """Build a single output row for the EGID-match loader."""
    return {
        'input_id': input_id,
        'input_egid': input_egid,
        'av_egid': av_egid,
        'fid': fid,
        'area_official_m2': area_official_m2,
        'geometry': geometry,
        'status_step1': status,
        'warnings': '; '.join(warnings) if warnings else '',
    }


def load_footprints_from_av_with_coordinates(
    av_path: Union[str, Path],
    csv_path: Union[str, Path],
    limit: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """
    Load AV building footprints, filtered to a set of CSV coordinates via spatial join.

    Each CSV point must fall strictly within an AV building polygon (predicate='within').
    There are no fallbacks: points that do not intersect any polygon get
    status_step1 = 'no_footprint' and are skipped downstream.

    Performance: a single ``_load_av_buildings`` read is performed against
    the *union* bbox of every input point (with buffer), and the resulting
    GeoDataFrame's spatial index handles all per-point lookups in memory.
    This is O(1) gpkg I/O instead of the previous O(n) per-point reads.

    This is the legacy/opt-in path. EGID match (see
    ``load_footprints_from_av_with_egids``) is faster and unambiguous, but
    coordinate-based matching is the only way to find buildings that have
    no EGID assigned in the cadastral data.

    Required CSV columns: id, lon, lat
    Optional CSV columns: egid (preserved as input_egid for reference only)

    Returns GeoDataFrame in LV95 with columns:
        input_id, input_egid, input_lon, input_lat,
        av_egid, fid, area_official_m2, geometry, status_step1, warnings
    """
    csv_path = Path(csv_path)
    df = _read_input_csv(csv_path)

    missing = [c for c in ['lon', 'lat', 'id'] if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}. Found: {list(df.columns)}")

    if limit:
        df = df.head(limit)

    df = df.rename(columns={'id': 'input_id'})
    if 'egid' in df.columns:
        df = df.rename(columns={'egid': 'input_egid'})
        df['input_egid'] = pd.to_numeric(df['input_egid'], errors='coerce')
    else:
        df['input_egid'] = None
    df['input_lon'] = df['lon']
    df['input_lat'] = df['lat']
    df = df.reset_index(drop=True)

    log.info(f"Loaded {len(df)} rows from {csv_path.name}")

    if len(df) == 0:
        return gpd.GeoDataFrame(geometry=[], crs='EPSG:2056')

    # ── Convert input lon/lat to LV95 points ──────────────────────────────
    pts = gpd.GeoDataFrame(
        df,
        geometry=[Point(r['lon'], r['lat']) for _, r in df.iterrows()],
        crs='EPSG:4326',
    ).to_crs('EPSG:2056')

    n = len(pts)

    # ── Single push-down read against the union bbox ──────────────────────
    minx, miny, maxx, maxy = pts.total_bounds
    union_bbox = (
        minx - AV_POINT_BBOX_BUFFER_M,
        miny - AV_POINT_BBOX_BUFFER_M,
        maxx + AV_POINT_BBOX_BUFFER_M,
        maxy + AV_POINT_BBOX_BUFFER_M,
    )

    # Sanity-check the bbox extent. A portfolio scattered across a huge
    # area can pull millions of features in one shot — warn the user but
    # don't auto-chunk; that's a separate optimisation.
    bbox_km2 = ((union_bbox[2] - union_bbox[0]) *
                (union_bbox[3] - union_bbox[1])) / 1_000_000
    if bbox_km2 > AV_UNION_BBOX_WARN_KM2:
        log.warning(
            f"  Union bbox of {n} input points spans {bbox_km2:,.0f} km² — "
            f"the AV read may pull a large number of features into memory. "
            f"Consider splitting the input by region if this is slow."
        )

    log.info(
        f"  Coordinate spatial join: {n} points "
        f"(AV: {Path(av_path).name}, layer={AV_BUILDING_LAYER}, "
        f"union bbox: {bbox_km2:,.1f} km² with {AV_POINT_BBOX_BUFFER_M}m buffer)"
    )
    av = _load_av_buildings(av_path, bbox_lv95=union_bbox)
    log.info(f"  AV returned {len(av)} polygons within union bbox")

    # Build a spatial index over the AV polygons. The index lets each
    # point-in-polygon check run in O(log n) instead of O(n).
    sindex = av.sindex

    # ── Process each point against the cached gdf ─────────────────────────
    records = []
    matched = 0
    no_match = 0
    multi_polygon_hits = 0

    for row in pts.itertuples(index=False):
        pt = row.geometry
        # Spatial index narrows down candidates by bounding box, then
        # contains() filters to actual point-in-polygon hits.
        candidate_idx = list(sindex.intersection((pt.x, pt.y, pt.x, pt.y)))
        candidates = av.iloc[candidate_idx] if candidate_idx else av.iloc[[]]
        hit = candidates[candidates.geometry.contains(pt)]

        if len(hit) > 0:
            warnings = []
            if len(hit) > 1:
                warnings.append(
                    f'Point fell inside {len(hit)} AV polygons'
                )
                multi_polygon_hits += 1
            for _, av_row in hit.iterrows():
                records.append({
                    'input_id': row.input_id,
                    'input_egid': row.input_egid,
                    'input_lon': row.input_lon,
                    'input_lat': row.input_lat,
                    'av_egid': av_row['av_egid'],
                    'fid': av_row['fid'],
                    'area_official_m2': av_row['area_official_m2'],
                    'geometry': av_row['geometry'],
                    'status_step1': STATUS_OK,
                    'warnings': '; '.join(warnings),
                })
                matched += 1
        else:
            records.append({
                'input_id': row.input_id,
                'input_egid': row.input_egid,
                'input_lon': row.input_lon,
                'input_lat': row.input_lat,
                'av_egid': None,
                'fid': None,
                'area_official_m2': None,
                'geometry': None,
                'status_step1': STATUS_NO_FOOTPRINT,
                'warnings': '',
            })
            no_match += 1

    log.info(
        f"  Matched: {matched}  no_footprint: {no_match}"
        + (f"  multi-polygon points: {multi_polygon_hits}" if multi_polygon_hits else "")
    )
    return gpd.GeoDataFrame(records, crs='EPSG:2056')


# ═════════════════════════════════════════════════════════════════════════
# API-based footprint fetching  (GWR → geodienste WFS → vec25 fallback)
# ═════════════════════════════════════════════════════════════════════════

# API endpoints  (GWR_FIND_URL intentionally duplicates area.py's constant
# to avoid a cross-module import for a single string)
_GWR_FIND_URL = "https://api3.geo.admin.ch/rest/services/ech/MapServer/find"
_WFS_AV_URL = "https://geodienste.ch/db/av_0/deu"
_VEC25_IDENTIFY_URL = "https://api3.geo.admin.ch/rest/services/ech/MapServer/identify"

# Cantons where geodienste.ch WFS data is not freely available — these
# skip the WFS and go straight to vec25. Last verified 2026-04-10 at
# https://geodienste.ch/services/av
_WFS_BLOCKED_CANTONS = frozenset({'JU', 'LU', 'VD'})

_API_TIMEOUT_S = 15          # HTTP timeout per request (seconds)
_API_POINT_BUFFER_M = 50     # Buffer around GWR point for bbox queries (m)
_API_MAX_WORKERS = 10         # Concurrent HTTP requests


def _fetch_json(url: str, context: str = '') -> Optional[dict]:
    """HTTP GET → parsed JSON dict, or ``None`` on any error."""
    try:
        with urllib.request.urlopen(url, timeout=_API_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        if context:
            log.debug("%s: %s", context, e)
        return None


def _parse_geojson_geometry(geom_data: dict) -> Optional[Any]:
    """Parse a GeoJSON geometry dict into a Shapely Polygon.

    MultiPolygons are reduced to their largest component.
    Returns ``None`` on parse failure.
    """
    try:
        geom = shape(geom_data)
    except Exception:
        return None
    if geom.geom_type == 'MultiPolygon':
        geom = max(geom.geoms, key=lambda g: g.area)
    return geom if geom.geom_type == 'Polygon' else None


def _query_gwr_location(egid: int) -> Optional[dict]:
    """
    Query GWR API for a building's LV95 coordinates and canton.

    Returns ``{'gkode': float, 'gkodn': float, 'gdekt': str}`` or ``None``.
    """
    query = urllib.parse.urlencode({
        'layer': 'ch.bfs.gebaeude_wohnungs_register',
        'searchText': str(egid),
        'searchField': 'egid',
        'returnGeometry': 'false',
        'contains': 'false',
    })
    data = _fetch_json(f"{_GWR_FIND_URL}?{query}",
                       f"GWR location for EGID {egid}")
    if not data:
        return None

    results = data.get('results') or []
    if not results:
        return None

    attrs = results[0].get('attributes') or results[0].get('properties') or {}
    gkode = attrs.get('gkode')
    gkodn = attrs.get('gkodn')
    if gkode is None or gkodn is None:
        return None

    return {
        'gkode': float(gkode),
        'gkodn': float(gkodn),
        'gdekt': attrs.get('gdekt') or '',
    }


def _query_wfs_footprints(gkode: float, gkodn: float) -> list[dict]:
    """
    Query geodienste.ch WFS for AV building footprints near a point.

    Returns a list of candidate dicts with keys:
    ``geometry``, ``av_egid``, ``area_official_m2``, ``source``.
    """
    buf = _API_POINT_BUFFER_M
    bbox = f"{gkode - buf},{gkodn - buf},{gkode + buf},{gkodn + buf},EPSG:2056"

    params = urllib.parse.urlencode({
        'SERVICE': 'WFS',
        'VERSION': '2.0.0',
        'REQUEST': 'GetFeature',
        'TYPENAMES': 'ms:LCSF',
        'OUTPUTFORMAT': 'geojson',
        'SRSNAME': 'urn:ogc:def:crs:EPSG::2056',
        'BBOX': bbox,
    })
    data = _fetch_json(f"{_WFS_AV_URL}?{params}",
                       f"WFS at ({gkode:.0f}, {gkodn:.0f})")
    if not data:
        return []

    result = []
    for f in data.get('features') or []:
        props = f.get('properties') or {}
        art = (props.get('Art') or props.get('art') or '').lower()
        if 'unterirdisch' in art:
            continue
        if 'gebaeude' not in art and 'gebäude' not in art:
            continue

        geom = _parse_geojson_geometry(f.get('geometry') or {})
        if geom is None:
            continue

        result.append({
            'geometry': geom,
            'av_egid': props.get('GWR_EGID') or props.get('gwr_egid'),
            'area_official_m2': props.get('Flaeche') or props.get('flaeche'),
            'source': 'wfs',
        })

    return result


def _query_vec25_footprints(gkode: float, gkodn: float) -> list[dict]:
    """
    Query swisstopo vec25 identify for building footprints near a point.

    Lower accuracy (~2-year update cycle) but covers the whole country.
    Returns a list of candidate dicts (same shape as ``_query_wfs_footprints``).
    """
    # imageDisplay=500,500,96 with mapExtent ±250 m → 1 m/px.
    # tolerance=50 → 50 px = 50 m search radius.
    extent_buf = 250
    me = f"{gkode - extent_buf},{gkodn - extent_buf},{gkode + extent_buf},{gkodn + extent_buf}"

    params = urllib.parse.urlencode({
        'geometryType': 'esriGeometryPoint',
        'geometry': f'{gkode},{gkodn}',
        'layers': 'all:ch.swisstopo.vec25-gebaeude',
        'tolerance': '50',
        'sr': '2056',
        'returnGeometry': 'true',
        'geometryFormat': 'geojson',
        'imageDisplay': '500,500,96',
        'mapExtent': me,
    })
    data = _fetch_json(f"{_VEC25_IDENTIFY_URL}?{params}",
                       f"vec25 at ({gkode:.0f}, {gkodn:.0f})")
    if not data:
        return []

    result = []
    for r in data.get('results') or []:
        geom = _parse_geojson_geometry(r.get('geometry') or {})
        if geom is None:
            continue

        props = r.get('properties') or {}
        result.append({
            'geometry': geom,
            'av_egid': None,       # vec25 carries no EGID
            'area_official_m2': props.get('area'),
            'source': 'vec25',
        })

    return result


def _fetch_footprint_for_egid(egid: int) -> dict:
    """
    Fetch a single building footprint via the GWR → WFS → vec25 cascade.

    Returns a dict with ``status``, and on success: ``geometry``,
    ``av_egid``, ``area_official_m2``, ``source``, ``warning``.
    """
    # Step 1: GWR lookup → coordinates + canton
    gwr = _query_gwr_location(egid)
    if gwr is None:
        return {'status': STATUS_NO_FOOTPRINT,
                'warning': f'EGID {egid} not found in GWR'}

    gkode, gkodn, gdekt = gwr['gkode'], gwr['gkodn'], gwr['gdekt']
    pt = Point(gkode, gkodn)

    # Step 2/3: Try WFS (skip for blocked cantons), then vec25 fallback
    candidates = []
    sources: list[str] = []

    if gdekt not in _WFS_BLOCKED_CANTONS:
        candidates = _query_wfs_footprints(gkode, gkodn)
        sources.append('wfs')

    if not candidates:
        candidates = _query_vec25_footprints(gkode, gkodn)
        sources.append('vec25')

    if not candidates:
        return {'status': STATUS_NO_FOOTPRINT,
                'warning': f'No footprint found via {"+".join(sources)} '
                           f'(canton={gdekt})'}

    # Step 4: Point-in-polygon match against the GWR coordinate
    match = None
    for c in candidates:
        if c['geometry'].contains(pt):
            match = c
            break

    # No exact PIP hit → take the candidate nearest to the GWR point
    if match is None:
        match = min(candidates, key=lambda c: c['geometry'].centroid.distance(pt))

    area = match.get('area_official_m2')
    if area is None:
        area = round(match['geometry'].area, 2)

    return {
        'status': STATUS_OK,
        'geometry': match['geometry'],
        'av_egid': match.get('av_egid'),    # None for vec25 — intentional
        'area_official_m2': area,
        'source': match['source'],
        'warning': None,
    }


def load_footprints_from_api_with_egids(
    csv_path: Union[str, Path],
    limit: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """
    Load building footprints via API cascade: GWR → WFS → vec25.

    No local AV GeoPackage file required. For each EGID in the CSV:

    1. **GWR API** → building LV95 coordinates + canton abbreviation
    2. **geodienste.ch WFS** → official AV footprint polygon (free cantons)
    3. **swisstopo vec25 identify** → lower-accuracy fallback (for blocked
       cantons JU/LU/VD, or when WFS returns empty)

    Point-in-polygon matching against the GWR coordinate selects the
    correct feature when multiple buildings are within the search buffer.

    Required CSV columns: ``id``, ``egid``

    Returns GeoDataFrame in LV95 with columns:
        input_id, input_egid, av_egid, fid, area_official_m2,
        geometry, status_step1, warnings
    """
    df, all_egids = _prepare_egid_csv(csv_path, limit)

    # ── Parallel API cascade for all unique EGIDs ────────────────────────
    footprint_by_egid: dict[int, dict] = {}

    if all_egids:
        log.info(f"Fetching footprints via API for {len(all_egids)} EGIDs "
                 f"({_API_MAX_WORKERS} workers)...")

        with ThreadPoolExecutor(max_workers=_API_MAX_WORKERS) as pool:
            futures = {
                pool.submit(_fetch_footprint_for_egid, e): e
                for e in all_egids
            }
            done = 0
            for future in as_completed(futures):
                egid = futures[future]
                try:
                    footprint_by_egid[egid] = future.result()
                except Exception as e:
                    log.debug("API fetch failed for EGID %s: %s", egid, e)
                    footprint_by_egid[egid] = {
                        'status': STATUS_NO_FOOTPRINT,
                        'warning': f'API error: {e}',
                    }
                done += 1
                if done % 50 == 0 or done == len(all_egids):
                    log.info(f"  API progress: {done}/{len(all_egids)}")

        n_wfs = sum(1 for r in footprint_by_egid.values()
                    if r.get('source') == 'wfs')
        n_vec25 = sum(1 for r in footprint_by_egid.values()
                      if r.get('source') == 'vec25')
        n_fail = sum(1 for r in footprint_by_egid.values()
                     if r['status'] != STATUS_OK)
        log.info(f"  Results: {n_wfs} from WFS, {n_vec25} from vec25, "
                 f"{n_fail} not found")

    # ── Build output rows in CSV order ───────────────────────────────────
    records = []
    matched = 0
    no_match = 0
    invalid = 0
    fid_counter = 0

    for row in df.itertuples(index=False):
        input_id = row.input_id
        egids = row.parsed_egids

        if not egids:
            records.append(_egid_record(
                input_id=input_id, input_egid=row.input_egid_raw,
                av_egid=None, fid=None, geometry=None, area_official_m2=None,
                status=STATUS_INVALID_EGID,
                warnings=[f'EGID could not be parsed as a positive integer: '
                          f'{row.input_egid_raw!r}'],
            ))
            invalid += 1
            continue

        base_warnings = []
        if len(egids) > 1:
            base_warnings.append(
                f'Input cell contained {len(egids)} EGIDs: '
                f'{", ".join(str(e) for e in egids)}'
            )

        for egid_int in egids:
            fp = footprint_by_egid.get(egid_int, {})

            if fp.get('status') != STATUS_OK:
                warnings = list(base_warnings)
                if fp.get('warning'):
                    warnings.append(fp['warning'])
                records.append(_egid_record(
                    input_id=input_id, input_egid=egid_int,
                    av_egid=None, fid=None, geometry=None,
                    area_official_m2=None,
                    status=STATUS_NO_FOOTPRINT, warnings=warnings,
                ))
                no_match += 1
                continue

            warnings = list(base_warnings)
            if fp.get('source') == 'vec25':
                warnings.append(
                    'footprint from vec25 (lower accuracy, ~2-year update cycle)'
                )

            fid_counter += 1
            records.append(_egid_record(
                input_id=input_id,
                input_egid=egid_int,
                av_egid=fp.get('av_egid'),     # None for vec25; input EGID
                fid=f'api_{fid_counter}',      # is already in input_egid
                geometry=fp.get('geometry'),
                area_official_m2=fp.get('area_official_m2'),
                status=STATUS_OK, warnings=warnings,
            ))
            matched += 1

    log.info(
        f"  Matched: {matched}  no_footprint: {no_match}  "
        f"invalid_egid: {invalid}"
    )
    return gpd.GeoDataFrame(records, crs='EPSG:2056')

