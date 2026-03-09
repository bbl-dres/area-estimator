#!/usr/bin/env python3
"""
Step 1 — Load Building Footprints

Loads building polygons from one of two sources:
1. Geodata file (GeoPackage, Shapefile, GeoJSON) — typically from Amtliche Vermessung
2. CSV with WGS84 coordinates — buffered into small sampling polygons

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
    Load building footprints from a geodata file (GeoPackage, Shapefile, GeoJSON).

    Filters to building polygons (type = "Gebaeude") if a type column exists.
    Preserves official area attribute as area_official_m2 for reference.

    Returns GeoDataFrame in LV95 with columns: av_egid, fid, area_official_m2, geometry, status
    """
    filepath = Path(filepath)
    log.info(f"Loading footprints from {filepath.name}...")

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    gdf = gpd.read_file(filepath, bbox=bbox) if bbox else gpd.read_file(filepath)

    if len(gdf) == 0:
        log.info("No features found in file")
        return gpd.GeoDataFrame()

    gdf.columns = [c.lower() for c in gdf.columns]

    # Rename AV's egid column to av_egid to distinguish from user input
    if 'egid' in gdf.columns:
        gdf = gdf.rename(columns={'egid': 'av_egid'})
    else:
        gdf['av_egid'] = None
    if 'fid' not in gdf.columns:
        gdf['fid'] = gdf.index.astype(str)

    # Preserve official area if present
    area_col = next((c for c in gdf.columns if c in ('flaeche', 'area', 'shape_area')), None)
    gdf['area_official_m2'] = pd.to_numeric(gdf[area_col], errors='coerce') if area_col else None

    # Filter to buildings if a type column exists
    for type_col in ['bbart', 'art', 'type', 'objektart']:
        if type_col in gdf.columns:
            mask = gdf[type_col].astype(str).str.lower().str.contains(
                'gebaeude|gebäude|building', na=False
            )
            if mask.any():
                gdf = gdf[mask]
                break

    # Ensure LV95
    if gdf.crs is not None and gdf.crs.to_epsg() != 2056:
        gdf = gdf.to_crs('EPSG:2056')
    elif gdf.crs is None:
        log.warning("No CRS defined, assuming LV95 (EPSG:2056)")
        gdf = gdf.set_crs('EPSG:2056')

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


