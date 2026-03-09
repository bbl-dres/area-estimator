#!/usr/bin/env python3
"""
Step 1 — Read Building Footprints

Loads building polygons from local geodata files or a user-provided CSV with
WGS84 coordinates. Source data originates from the Bodenbedeckung layer of the
Amtliche Vermessung (official Swiss cadastral survey).

Supported input formats:
- GeoPackage (.gpkg), Shapefile (.shp), GeoJSON (.geojson) — from Amtliche Vermessung
- CSV with WGS84 lon/lat coordinates — user-provided list of locations

Each building carries two key identifiers:
- EGID: Federal building identifier (links to GWR)
- FID: Feature ID from the official cadastral survey
"""

import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def load_footprints_from_file(filepath, bbox=None, limit=None):
    """
    Load building footprints from a geodata file (GeoPackage, Shapefile, GeoJSON).

    Reads the Bodenbedeckung layer from the Amtliche Vermessung and filters
    to building polygons (BBArt = Gebaeude where applicable).

    Args:
        filepath: Path to geodata file (.gpkg, .shp, .geojson)
        bbox: Optional bounding box (minlon, minlat, maxlon, maxlat) in WGS84
        limit: Optional maximum number of buildings to load

    Returns:
        GeoDataFrame in LV95 (EPSG:2056) with columns: egid, fid, geometry
    """
    filepath = Path(filepath)
    print(f"Loading footprints from {filepath.name}...")

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    # Read geodata file
    if bbox:
        minlon, minlat, maxlon, maxlat = bbox
        gdf = gpd.read_file(filepath, bbox=(minlon, minlat, maxlon, maxlat))
    else:
        gdf = gpd.read_file(filepath)

    if len(gdf) == 0:
        print("No features found in file")
        return gpd.GeoDataFrame()

    # Normalize column names to lowercase
    gdf.columns = [c.lower() for c in gdf.columns]

    # Ensure we have egid and fid columns (may not exist in all datasets)
    if 'egid' not in gdf.columns:
        gdf['egid'] = None
    if 'fid' not in gdf.columns:
        # Use index as fallback FID
        gdf['fid'] = gdf.index.astype(str)

    # Filter to buildings if a type column exists
    for type_col in ['bbart', 'art', 'type', 'objektart']:
        if type_col in gdf.columns:
            building_mask = gdf[type_col].astype(str).str.lower().str.contains(
                'gebaeude|gebäude|building', na=False
            )
            if building_mask.any():
                gdf = gdf[building_mask]
                break

    # Transform to LV95 if needed
    if gdf.crs is not None and gdf.crs.to_epsg() != 2056:
        gdf = gdf.to_crs('EPSG:2056')
    elif gdf.crs is None:
        print("Warning: No CRS defined, assuming LV95 (EPSG:2056)", file=sys.stderr)
        gdf = gdf.set_crs('EPSG:2056')

    if limit:
        gdf = gdf.head(limit)

    print(f"Loaded {len(gdf)} building footprints")
    return gdf[['egid', 'fid', 'geometry']]


def load_coordinates_from_csv(csv_path, alti3d_dir=None, surface3d_dir=None):
    """
    Load a list of WGS84 coordinates from a CSV file and create point geometries.

    This mode is for processing specific locations — the user provides coordinates
    and the tool creates a small buffer to sample elevations. Building footprints
    are not used in this mode.

    Expected CSV columns: lon, lat (required), egid (optional), fid (optional)

    Args:
        csv_path: Path to CSV file with lon, lat columns

    Returns:
        GeoDataFrame in LV95 (EPSG:2056) with columns: egid, fid, geometry
    """
    filepath = Path(csv_path)
    print(f"Loading coordinates from {filepath.name}...")

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    df = pd.read_csv(filepath)
    df.columns = [c.lower().strip() for c in df.columns]

    # Find coordinate columns
    lon_col = next((c for c in df.columns if c in ('lon', 'longitude', 'lng', 'x')), None)
    lat_col = next((c for c in df.columns if c in ('lat', 'latitude', 'y')), None)

    if lon_col is None or lat_col is None:
        raise ValueError(
            f"CSV must have lon/lat columns. Found: {list(df.columns)}"
        )

    if 'egid' not in df.columns:
        df['egid'] = None
    if 'fid' not in df.columns:
        df['fid'] = df.index.astype(str)

    # Create point geometries in WGS84, then transform to LV95
    geometry = [Point(row[lon_col], row[lat_col]) for _, row in df.iterrows()]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')
    gdf = gdf.to_crs('EPSG:2056')

    print(f"Loaded {len(gdf)} coordinate points")
    return gdf[['egid', 'fid', 'geometry']]
