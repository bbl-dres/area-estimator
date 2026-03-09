#!/usr/bin/env python3
"""
Step 1 — Load Building Footprints

Loads building polygons from one of three sources:
1. Geodata file (GeoPackage, Shapefile, GeoJSON) — typically from Amtliche Vermessung
2. CSV with WGS84 coordinates — buffered into small sampling polygons
3. GeoJSON with point features — footprints resolved from AV via spatial containment

All functions return a GeoDataFrame in LV95 (EPSG:2056) with a consistent schema:
    egid, fid, area_official_m2, geometry, status
"""

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, box

log = logging.getLogger(__name__)

# Buffer size (meters) for creating sampling polygons around CSV points
POINT_BUFFER_M = 5.0

# Buffer around WGS84 point when querying AV (meters in LV95)
AV_SEARCH_BUFFER_M = 200

# WGS84 → LV95 transformer (reused across calls)
_wgs84_to_lv95 = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)


def load_footprints_from_file(filepath, bbox=None, limit=None):
    """
    Load building footprints from a geodata file (GeoPackage, Shapefile, GeoJSON).

    Filters to building polygons (type = "Gebaeude") if a type column exists.
    Preserves official area attribute as area_official_m2 for reference.

    Returns GeoDataFrame in LV95 with columns: egid, fid, area_official_m2, geometry, status
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

    if 'egid' not in gdf.columns:
        gdf['egid'] = None
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

    gdf['status'] = 'ok'
    log.info(f"Loaded {len(gdf)} building footprints")
    return gdf[['egid', 'fid', 'area_official_m2', 'geometry', 'status']]


def load_coordinates_from_csv(csv_path, limit=None):
    """
    Load WGS84 coordinates from CSV and buffer into 10x10m sampling polygons.

    Expected columns: lon, lat (required), egid (optional), fid (optional)

    Returns GeoDataFrame in LV95 with columns: egid, fid, area_official_m2, geometry, status
    """
    filepath = Path(csv_path)
    log.info(f"Loading coordinates from {filepath.name}...")

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    df = pd.read_csv(filepath)
    df.columns = [c.lower().strip() for c in df.columns]

    lon_col = next((c for c in df.columns if c in ('lon', 'longitude', 'lng', 'x')), None)
    lat_col = next((c for c in df.columns if c in ('lat', 'latitude', 'y')), None)

    if lon_col is None or lat_col is None:
        raise ValueError(f"CSV must have lon/lat columns. Found: {list(df.columns)}")

    if 'egid' not in df.columns:
        df['egid'] = None
    if 'fid' not in df.columns:
        df['fid'] = df.index.astype(str)

    if limit:
        df = df.head(limit)

    geometry = [Point(row[lon_col], row[lat_col]) for _, row in df.iterrows()]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')
    gdf = gdf.to_crs('EPSG:2056')

    # Buffer points into square polygons
    gdf['geometry'] = gdf.geometry.apply(
        lambda pt: box(pt.x - POINT_BUFFER_M, pt.y - POINT_BUFFER_M,
                       pt.x + POINT_BUFFER_M, pt.y + POINT_BUFFER_M)
    )
    gdf['area_official_m2'] = None
    gdf['status'] = 'ok'

    log.info(f"Loaded {len(gdf)} coordinates (buffered to {POINT_BUFFER_M*2}x{POINT_BUFFER_M*2}m)")
    return gdf[['egid', 'fid', 'area_official_m2', 'geometry', 'status']]


def _find_av_building_at_point(lon, lat, av_path, av_layer):
    """
    Find the AV building polygon that contains a WGS84 point.

    Transforms the point to LV95, queries the AV GeoPackage within a 200m bbox,
    and returns the building polygon that spatially contains the point.

    Returns (polygon, av_egid, av_fid) or (None, None, None) if no building found.
    """
    x, y = _wgs84_to_lv95.transform(lon, lat)
    pt = Point(x, y)

    bbox = (x - AV_SEARCH_BUFFER_M, y - AV_SEARCH_BUFFER_M,
            x + AV_SEARCH_BUFFER_M, y + AV_SEARCH_BUFFER_M)

    try:
        gdf = gpd.read_file(av_path, layer=av_layer, bbox=bbox,
                            engine='pyogrio', fid_as_index=True)
    except Exception:
        return None, None, None

    if len(gdf) == 0:
        return None, None, None

    buildings = gdf[gdf["Art"] == "Gebaeude"]
    if len(buildings) == 0:
        return None, None, None

    # Find which building contains the point
    contains = buildings[buildings.geometry.contains(pt)]
    if len(contains) == 0:
        return None, None, None

    hit = contains.iloc[0]
    return hit.geometry, hit["GWR_EGID"], contains.index[0]


def load_geojson_with_av(geojson_path, av_path, av_layer="lcsf", limit=None):
    """
    Load a GeoJSON of building coordinates and resolve footprints from the AV.

    Each feature needs Point geometry (WGS84). The matching is purely spatial:
    the point must fall inside an AV building polygon.

    Input properties are preserved with 'input_' prefix:
      - input_id: from 'bbl_id' in source (or index)
      - input_egid: from 'egid' in source (reference only)

    The authoritative EGID comes from the AV (GWR_EGID attribute).

    Returns GeoDataFrame in LV95 with columns:
        input_id, input_egid, egid, fid, area_official_m2, geometry, status
    """
    log.info(f"Loading GeoJSON from {Path(geojson_path).name}...")

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data["features"]
    if limit:
        features = features[:limit]

    total = len(features)
    log.info(f"  {total} features, resolving footprints from AV...")

    rows = []
    geometries = []

    for i, feat in enumerate(features):
        props = feat["properties"]
        coords = feat["geometry"]["coordinates"]
        lon, lat = coords[0], coords[1]

        polygon, av_egid, av_fid = _find_av_building_at_point(lon, lat, av_path, av_layer)

        row = {
            "input_id": props.get("bbl_id", str(i)),
            "input_egid": props.get("egid", ""),
            "input_lon": lon,
            "input_lat": lat,
            "egid": av_egid if polygon else None,
            "fid": av_fid if polygon else None,
            "area_official_m2": polygon.area if polygon else None,
            "status": "ok" if polygon else "no_building_at_point",
        }

        rows.append(row)
        geometries.append(polygon)

        if (i + 1) % 100 == 0 or (i + 1) == total:
            matched_so_far = sum(1 for r in rows if r["status"] == "ok")
            log.info(f"  AV lookup: [{i+1}/{total}] {(i+1)/total*100:.0f}%  "
                     f"matched: {matched_so_far}")

    gdf = gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:2056")

    matched = sum(1 for r in rows if r["status"] == "ok")
    log.info(f"  Matched to AV: {matched}/{len(rows)}")

    return gdf
