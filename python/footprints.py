#!/usr/bin/env python3
"""
Step 1 — Load Building Footprints

Loads building polygons from one of three sources:
1. Geodata file (GeoPackage, Shapefile, GeoJSON) — typically from Amtliche Vermessung
2. CSV with WGS84 coordinates — buffered into small sampling polygons
3. GeoJSON with point features — footprints resolved from AV via spatial containment

All functions return a GeoDataFrame in LV95 (EPSG:2056) with columns:
    av_egid, area_official_m2, geometry, status (+ id for CSV, fid for geodata/GeoJSON)
"""

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, box
from shapely.strtree import STRtree

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
    Optional columns: egid (mapped to av_egid)

    Returns GeoDataFrame in LV95 with columns: id, av_egid, area_official_m2, geometry, status_step1
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

    if 'egid' in df.columns:
        df = df.rename(columns={'egid': 'av_egid'})
    else:
        df['av_egid'] = None

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
    return gdf[['id', 'av_egid', 'area_official_m2', 'geometry', 'status_step1']]


def _load_av_buildings(av_path, av_layer, bbox=None):
    """
    Load AV building polygons once and build a spatial index.

    Returns (GeoDataFrame of buildings, STRtree index) or (None, None) on error.
    """
    try:
        gdf = gpd.read_file(av_path, layer=av_layer, bbox=bbox,
                            engine='pyogrio', fid_as_index=True)
    except (IOError, ValueError) as e:
        log.error(f"Failed to read AV file: {e}")
        return None, None

    if len(gdf) == 0:
        return None, None

    buildings = gdf[gdf["Art"] == "Gebaeude"].copy()
    if len(buildings) == 0:
        return None, None

    tree = STRtree(buildings.geometry.values)
    return buildings, tree


def _find_av_building_at_point(pt, av_buildings, av_tree):
    """
    Find the AV building polygon that contains an LV95 point using a spatial index.

    Returns (polygon, av_egid, av_fid) or (None, None, None) if no building found.
    """
    indices = av_tree.query(pt)
    for idx in indices:
        geom = av_buildings.geometry.iloc[idx]
        if geom.contains(pt):
            row = av_buildings.iloc[idx]
            return geom, row["GWR_EGID"], av_buildings.index[idx]

    return None, None, None


def load_geojson_with_av(geojson_path, av_path, av_layer="lcsf", limit=None):
    """
    Load a GeoJSON of building coordinates and resolve footprints from the AV.

    Each feature needs Point geometry (WGS84). The matching is purely spatial:
    the point must fall inside an AV building polygon.

    Input properties are preserved with 'input_' prefix:
      - input_id: from 'id' in source (or index)
      - input_egid: from 'egid' in source (reference only)

    The authoritative EGID comes from the AV (GWR_EGID attribute).

    Returns GeoDataFrame in LV95 with columns:
        input_id, input_egid, input_lon, input_lat,
        av_egid, fid, area_official_m2, geometry, status_step1
    """
    log.info(f"Loading GeoJSON from {Path(geojson_path).name}...")

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data["features"]
    if limit:
        features = features[:limit]

    total = len(features)
    log.info(f"  {total} features, resolving footprints from AV...")

    # Compute bounding box of all input points to load AV data once
    lons = []
    lats = []
    for feat in features:
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            lons.append(coords[0])
            lats.append(coords[1])

    if not lons:
        log.warning("No valid coordinates found in GeoJSON features")
        return gpd.GeoDataFrame()

    # Transform corner points to LV95 to get AV bbox
    x_min, y_min = _wgs84_to_lv95.transform(min(lons), min(lats))
    x_max, y_max = _wgs84_to_lv95.transform(max(lons), max(lats))
    av_bbox = (x_min - AV_SEARCH_BUFFER_M, y_min - AV_SEARCH_BUFFER_M,
               x_max + AV_SEARCH_BUFFER_M, y_max + AV_SEARCH_BUFFER_M)

    # Load AV buildings once with spatial index
    av_buildings, av_tree = _load_av_buildings(av_path, av_layer, bbox=av_bbox)
    if av_buildings is None:
        log.warning("No AV buildings loaded — all points will be unmatched")

    rows = []
    geometries = []

    for i, feat in enumerate(features):
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            rows.append({
                "input_id": props.get("id", str(i)), "input_egid": props.get("egid", ""),
                "input_lon": None, "input_lat": None,
                "av_egid": None, "fid": None, "area_official_m2": None,
                "status_step1": "invalid_geometry",
            })
            geometries.append(None)
            continue

        lon, lat = coords[0], coords[1]
        x, y = _wgs84_to_lv95.transform(lon, lat)
        pt = Point(x, y)

        polygon, av_egid, av_fid = (None, None, None)
        if av_buildings is not None:
            polygon, av_egid, av_fid = _find_av_building_at_point(pt, av_buildings, av_tree)

        row = {
            "input_id": props.get("id", str(i)),
            "input_egid": props.get("egid", ""),
            "input_lon": lon,
            "input_lat": lat,
            "av_egid": av_egid if polygon else None,
            "fid": av_fid if polygon else None,
            "area_official_m2": polygon.area if polygon else None,
            "status_step1": "ok" if polygon else "no_building_at_point",
        }

        rows.append(row)
        geometries.append(polygon)

        if (i + 1) % 100 == 0 or (i + 1) == total:
            matched_so_far = sum(1 for r in rows if r["status_step1"] == "ok")
            log.info(f"  AV lookup: [{i+1}/{total}] {(i+1)/total*100:.0f}%  "
                     f"matched: {matched_so_far}")

    gdf = gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:2056")

    matched = sum(1 for r in rows if r["status_step1"] == "ok")
    log.info(f"  Matched to AV: {matched}/{len(rows)}")

    return gdf[['input_id', 'input_egid', 'input_lon', 'input_lat',
                'av_egid', 'fid', 'area_official_m2', 'geometry', 'status_step1']]
