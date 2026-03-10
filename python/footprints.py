#!/usr/bin/env python3
"""
Step 1 — Load Building Footprints

Loads building polygons from one of three modes:
1. Geodata file only (GeoPackage, Shapefile, GeoJSON) — all buildings in file
2. CSV coordinates only — buffered into small 10×10m sampling polygons
3. Geodata file + CSV — spatial join: AV footprints filtered to CSV points

All functions return a GeoDataFrame in LV95 (EPSG:2056) with columns:
    av_egid, area_official_m2, geometry, status_step1 (+ id for CSV, fid for geodata)
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


def load_footprints_from_file(filepath, bbox=None, limit=None):
    """
    Load all building footprints from a geodata file (GeoPackage, Shapefile, GeoJSON).

    Filters to building polygons (type = "Gebaeude") if a type column exists.
    Preserves official area attribute as area_official_m2 for reference.

    Returns GeoDataFrame in LV95 with columns: av_egid, fid, area_official_m2, geometry, status_step1
    """
    gdf = _load_av_buildings(filepath, bbox_lv95=bbox)

    if len(gdf) == 0:
        log.info("No features found in file")
        return gpd.GeoDataFrame()

    if limit:
        gdf = gdf.head(limit)

    gdf['status_step1'] = 'ok'
    log.info(f"Loaded {len(gdf)} building footprints")
    return gdf[['av_egid', 'fid', 'area_official_m2', 'geometry', 'status_step1']]


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


def _load_av_buildings(av_path, bbox_lv95=None):
    """
    Internal helper: load and normalise an AV GeoPackage/Shapefile/GeoJSON.
    Returns a GeoDataFrame in LV95 with columns: av_egid, fid, area_official_m2, geometry.
    bbox_lv95: (minx, miny, maxx, maxy) in LV95 to pre-filter the file read.
    """
    av_path = Path(av_path)
    if not av_path.exists():
        raise FileNotFoundError(f"AV file not found: {av_path}")

    log.info(f"Loading AV from {av_path.name}...")
    gdf = gpd.read_file(av_path, bbox=bbox_lv95) if bbox_lv95 else gpd.read_file(av_path)

    if len(gdf) == 0:
        return gpd.GeoDataFrame(columns=['av_egid', 'fid', 'area_official_m2', 'geometry'],
                                 crs='EPSG:2056')

    gdf.columns = [c.lower() for c in gdf.columns]

    # Filter to buildings where a type column exists
    for type_col in ['bbart', 'art', 'type', 'objektart']:
        if type_col in gdf.columns:
            mask = gdf[type_col].astype(str).str.lower().str.contains(
                'gebaeude|gebäude|building', na=False
            )
            if mask.any():
                gdf = gdf[mask].copy()
                break

    if 'egid' in gdf.columns:
        gdf = gdf.rename(columns={'egid': 'av_egid'})
        gdf['av_egid'] = pd.to_numeric(gdf['av_egid'], errors='coerce')
    else:
        gdf['av_egid'] = None

    if 'fid' not in gdf.columns:
        gdf['fid'] = gdf.index.astype(str)

    area_col = next((c for c in gdf.columns if c in ('flaeche', 'area', 'shape_area')), None)
    gdf['area_official_m2'] = pd.to_numeric(gdf[area_col], errors='coerce') if area_col else None

    if gdf.crs is None:
        gdf = gdf.set_crs('EPSG:2056')
    elif gdf.crs.to_epsg() != 2056:
        gdf = gdf.to_crs('EPSG:2056')

    log.info(f"  {len(gdf)} building footprints loaded")
    return gdf[['av_egid', 'fid', 'area_official_m2', 'geometry']].reset_index(drop=True)


def load_footprints_from_av_with_csv_filter(av_path, csv_path, limit=None):
    """
    Load AV building footprints, filtered to a set of CSV coordinates via spatial join.

    Each CSV point must fall strictly within an AV building polygon (predicate='within').
    There are no fallbacks: points that do not intersect any polygon get
    status_step1 = 'no_footprint' and are skipped downstream.

    Required CSV columns: id, lon, lat
    Optional CSV columns: egid (preserved as input_egid for reference only)

    Returns GeoDataFrame in LV95 with columns:
        input_id, input_egid, input_lon, input_lat,
        av_egid, fid, area_official_m2, geometry, status_step1
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    # ── Load CSV ──────────────────────────────────────────────────────────
    df = pd.read_csv(csv_path)
    df.columns = [c.lower().strip() for c in df.columns]

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

    # Bounding box (+ 500 m buffer) for efficient AV load
    b = pts.total_bounds
    av_bbox = (b[0] - 500, b[1] - 500, b[2] + 500, b[3] + 500)

    # ── Load AV ───────────────────────────────────────────────────────────
    av = _load_av_buildings(av_path, bbox_lv95=av_bbox)
    if len(av) == 0:
        log.warning("No AV buildings found in bounding box — loading full file")
        av = _load_av_buildings(av_path)

    # ── Spatial join ──────────────────────────────────────────────────────
    joined = gpd.sjoin(
        pts[['geometry']],
        av[['av_egid', 'fid', 'area_official_m2', 'geometry']],
        how='left',
        predicate='within',
    )
    # Keep first match per point (a point very rarely falls in >1 polygon)
    joined = joined[~joined.index.duplicated(keep='first')]

    matched_n = joined['fid'].notna().sum()
    no_match_n = joined['fid'].isna().sum()
    log.info(f"  Matched: {matched_n}/{len(pts)}  |  No polygon: {no_match_n}")

    # ── Build result GeoDataFrame ─────────────────────────────────────────
    records = []
    for idx, row in pts.iterrows():
        j = joined.loc[idx]
        if pd.notna(j['fid']):
            records.append({
                'input_id': row['input_id'],
                'input_egid': row['input_egid'],
                'input_lon': row['input_lon'],
                'input_lat': row['input_lat'],
                'av_egid': j['av_egid'],
                'fid': j['fid'],
                'area_official_m2': j['area_official_m2'],
                'geometry': av.at[j['index_right'], 'geometry'],
                'status_step1': 'ok',
            })
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
            })

    return gpd.GeoDataFrame(records, crs='EPSG:2056')

