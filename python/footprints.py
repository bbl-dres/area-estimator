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

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, box

log = logging.getLogger(__name__)

# Buffer size (meters) for creating sampling polygons around CSV points
POINT_BUFFER_M = 5.0

# WGS84 → LV95 transformer (reused across calls)
_wgs84_to_lv95 = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)

# Layer name for building polygons in Swiss AV GeoPackages (Bodenbedeckungsflaeche)
AV_BUILDING_LAYER = 'lcsf'
# Art value for buildings within the lcsf layer
AV_BUILDING_TYPE = 'Gebaeude'
# Buffer (m) around each point's bbox when querying AV in spatial join mode
AV_POINT_BBOX_BUFFER_M = 200


def load_footprints_from_file(filepath, bbox=None, limit=None):
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

    gdf['status_step1'] = 'ok'
    gdf['warnings'] = ''
    log.info(f"  {len(gdf)} building footprints loaded")
    return gdf[['av_egid', 'fid', 'area_official_m2', 'geometry', 'status_step1', 'warnings']]


def load_coordinates_from_csv(csv_path, limit=None):
    """
    Load WGS84 coordinates from CSV and buffer into 10x10m sampling polygons.

    Required columns: lon, lat, id
    Optional columns: egid (preserved as-is for reference and GWR lookup)

    Returns GeoDataFrame in LV95 with columns: id, egid, area_official_m2, geometry, status_step1
    """
    filepath = Path(csv_path)
    log.info(f"Loading coordinates from {filepath.name}...")

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    df = pd.read_csv(filepath)
    df.columns = [c.lower().strip() for c in df.columns]

    required = ['lon', 'lat', 'id']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}. Found: {list(df.columns)}")

    # Keep user's egid column as-is for reference (av_egid is only from AV geodata)
    if 'egid' not in df.columns:
        df['egid'] = None

    if limit:
        df = df.head(limit)

    geometry = [Point(row['lon'], row['lat']) for _, row in df.iterrows()]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')
    gdf = gdf.to_crs('EPSG:2056')

    # Buffer points into square polygons
    gdf['geometry'] = gdf.geometry.apply(
        lambda pt: box(pt.x - POINT_BUFFER_M, pt.y - POINT_BUFFER_M,
                       pt.x + POINT_BUFFER_M, pt.y + POINT_BUFFER_M)
    )
    gdf['area_official_m2'] = None
    gdf['status_step1'] = 'ok'

    log.info(f"Loaded {len(gdf)} coordinates (buffered to {POINT_BUFFER_M*2}x{POINT_BUFFER_M*2}m)")
    return gdf[['id', 'egid', 'area_official_m2', 'geometry', 'status_step1']]


def _load_av_buildings(av_path, bbox_lv95=None, where_sql=None):
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


def _read_input_csv(csv_path):
    """
    Read a CSV with comma- or semicolon-delimiter auto-detect and BOM
    handling.

    - The web app uses ``;``, the Python world expects ``,`` — accepting
      both means a single CSV (e.g. data/example.csv) works in both tools.
    - ``utf-8-sig`` transparently strips a UTF-8 BOM if one is present
      (Excel and many Windows tools save CSVs with BOM by default), so the
      first column header doesn't come through as ``\\ufeffid``.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    # python engine + sep=None enables csv.Sniffer auto-detection
    df = pd.read_csv(csv_path, sep=None, engine='python', encoding='utf-8-sig')
    df.columns = [c.lower().strip() for c in df.columns]
    return df


def load_footprints_from_av_with_egids(av_path, csv_path, limit=None):
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
    df['input_egid'] = pd.to_numeric(df['egid'], errors='coerce')
    df = df.reset_index(drop=True)

    # Build the set of valid EGIDs we need to fetch from the AV file.
    valid_mask = df['input_egid'].notna() & (df['input_egid'] > 0)
    valid_egids = sorted({int(e) for e in df.loc[valid_mask, 'input_egid']})

    log.info(
        f"Loaded {len(df)} rows from {Path(csv_path).name} "
        f"({len(valid_egids)} unique valid EGIDs, {(~valid_mask).sum()} invalid)"
    )

    # ── Single push-down read ─────────────────────────────────────────────
    av_by_egid: dict[int, list] = {}
    if valid_egids:
        # GeoPackage WHERE pushdown via pyogrio. The IN list is fine for
        # the example case (~10 EGIDs); a portfolio of 50k+ may need
        # batching, but pyogrio handles fairly large IN lists in practice.
        where = f"GWR_EGID IN ({','.join(str(e) for e in valid_egids)})"
        log.info(
            f"Querying AV: {Path(av_path).name} "
            f"(layer={AV_BUILDING_LAYER}, WHERE GWR_EGID IN [{len(valid_egids)} ids])"
        )
        av = _load_av_buildings(av_path, where_sql=where)
        log.info(f"  AV returned {len(av)} polygons")

        # Group AV rows by EGID for fast lookup
        for egid_val, group in av.groupby('av_egid', dropna=True):
            av_by_egid[int(egid_val)] = list(group.itertuples(index=False))

    # ── Build output rows in CSV order ────────────────────────────────────
    records = []
    matched = 0
    no_match = 0
    invalid = 0
    multi_polygon_egids = 0

    for _, row in df.iterrows():
        input_id = row['input_id']
        input_egid_num = row['input_egid']

        # Invalid / missing EGID
        if not valid_mask.loc[row.name]:
            records.append(_egid_record(
                input_id=input_id,
                input_egid=row['input_egid_raw'],
                av_egid=None, fid=None, geometry=None, area_official_m2=None,
                status='invalid_egid',
                warnings=[f'EGID could not be parsed as int: {row["input_egid_raw"]!r}'],
            ))
            invalid += 1
            continue

        egid_int = int(input_egid_num)
        matches = av_by_egid.get(egid_int)

        if not matches:
            records.append(_egid_record(
                input_id=input_id, input_egid=egid_int,
                av_egid=None, fid=None, geometry=None, area_official_m2=None,
                status='no_footprint',
                warnings=[],
            ))
            no_match += 1
            continue

        warnings = []
        if len(matches) > 1:
            warnings.append(
                f'EGID matched {len(matches)} AV polygons — emitting one row per polygon'
            )
            multi_polygon_egids += 1

        for av_row in matches:
            records.append(_egid_record(
                input_id=input_id,
                input_egid=egid_int,
                av_egid=av_row.av_egid,
                fid=av_row.fid,
                geometry=av_row.geometry,
                area_official_m2=av_row.area_official_m2,
                status='ok',
                warnings=list(warnings),
            ))
            matched += 1

    log.info(
        f"  Matched: {matched}  no_footprint: {no_match}  invalid_egid: {invalid}"
        + (f"  multi-polygon EGIDs: {multi_polygon_egids}" if multi_polygon_egids else "")
    )

    return gpd.GeoDataFrame(records, crs='EPSG:2056')


def _egid_record(input_id, input_egid, av_egid, fid, geometry,
                 area_official_m2, status, warnings):
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


def load_footprints_from_av_with_coordinates(av_path, csv_path, limit=None):
    """
    Load AV building footprints, filtered to a set of CSV coordinates via spatial join.

    Each CSV point must fall strictly within an AV building polygon (predicate='within').
    There are no fallbacks: points that do not intersect any polygon get
    status_step1 = 'no_footprint' and are skipped downstream.

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

    # ── Create LV95 points ────────────────────────────────────────────────
    pts = gpd.GeoDataFrame(
        df,
        geometry=[Point(r['lon'], r['lat']) for _, r in df.iterrows()],
        crs='EPSG:4326',
    ).to_crs('EPSG:2056')

    n = len(pts)
    log.info(f"  Point-by-point spatial join: {n} points  "
             f"(AV: {Path(av_path).name}, layer={AV_BUILDING_LAYER}, "
             f"bbox buffer={AV_POINT_BBOX_BUFFER_M}m)")

    # ── Process point by point ────────────────────────────────────────────
    records = []
    matched = 0
    no_match = 0

    for i, (_, row) in enumerate(pts.iterrows()):
        pt = row.geometry
        bbox = (pt.x - AV_POINT_BBOX_BUFFER_M, pt.y - AV_POINT_BBOX_BUFFER_M,
                pt.x + AV_POINT_BBOX_BUFFER_M, pt.y + AV_POINT_BBOX_BUFFER_M)

        local_av = _load_av_buildings(av_path, bbox_lv95=bbox)

        # Find the polygon(s) containing this point
        hit = local_av[local_av.geometry.contains(pt)]

        if len(hit) > 0:
            av_row = hit.iloc[0]
            warnings = []
            if len(hit) > 1:
                warnings.append(
                    f'Point fell inside {len(hit)} AV polygons — using first match'
                )
            records.append({
                'input_id': row['input_id'],
                'input_egid': row['input_egid'],
                'input_lon': row['input_lon'],
                'input_lat': row['input_lat'],
                'av_egid': av_row['av_egid'],
                'fid': av_row['fid'],
                'area_official_m2': av_row['area_official_m2'],
                'geometry': av_row['geometry'],
                'status_step1': 'ok',
                'warnings': '; '.join(warnings),
            })
            matched += 1
        else:
            records.append({
                'input_id': row['input_id'],
                'input_egid': row['input_egid'],
                'input_lon': row['input_lon'],
                'input_lat': row['input_lat'],
                'av_egid': None,
                'fid': None,
                'area_official_m2': None,
                'geometry': None,
                'status_step1': 'no_footprint',
                'warnings': '',
            })
            no_match += 1

        if (i + 1) % 100 == 0 or (i + 1) == n:
            log.info(f"  [{i+1}/{n}] {(i+1)/n*100:.0f}%  "
                     f"matched: {matched}  no_footprint: {no_match}")

    log.info(f"  Total: {matched} matched, {no_match} no_footprint")
    return gpd.GeoDataFrame(records, crs='EPSG:2056')

