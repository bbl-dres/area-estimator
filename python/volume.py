#!/usr/bin/env python3
"""
Step 3 — Sample Elevations & Calculate Volume

Samples terrain (swissALTI3D) and surface (swissSURFACE3D) elevations at each
grid point, then calculates building volume and all height metrics.

Outputs per building:
- volume_above_ground_m3
- elevation_base_m        (min terrain under building)
- elevation_roof_base_m   (min surface within footprint — estimated eave)
- height_mean_m           (mean of building heights at grid points)
- height_max_m            (max building height)
- height_minimal_m        (volume / footprint — equivalent uniform box height)
"""

import sys
from pathlib import Path
import numpy as np
import rasterio

from grid import create_aligned_grid_points


class TileIndex:
    """Indexes and caches swisstopo GeoTIFF elevation tiles."""

    def __init__(self, alti3d_dir, surface3d_dir):
        self.alti3d_dir = Path(alti3d_dir)
        self.surface3d_dir = Path(surface3d_dir)
        self.tile_cache = {}

        print("Indexing available tiles...")
        self.alti3d_tiles = self._index_tiles(self.alti3d_dir)
        self.surface3d_tiles = self._index_tiles(self.surface3d_dir)
        print(f"  Found {len(self.alti3d_tiles)} swissALTI3D tiles")
        print(f"  Found {len(self.surface3d_tiles)} swissSURFACE3D tiles")

    def _index_tiles(self, directory):
        """
        Scan directory and build tile_id -> filepath mapping.

        Expected filenames:
        - swissalti3d_YYYY_XXXX-YYYY_0.5_2056_5728.tif
        - swisssurface3d-raster_YYYY_XXXX-YYYY_0.5_2056_5728.tif

        Tile ID is at index 2 when split by underscore.
        """
        tile_index = {}

        if not directory.exists():
            print(f"Warning: Directory not found: {directory}", file=sys.stderr)
            return tile_index

        for filepath in directory.glob("*.tif"):
            try:
                parts = filepath.stem.split('_')
                if len(parts) >= 3:
                    tile_id = parts[2]
                    if '-' in tile_id and len(tile_id.split('-')) == 2:
                        tile_index[tile_id] = filepath
                    else:
                        print(f"Warning: Unexpected tile ID format in {filepath.name}",
                              file=sys.stderr)
            except Exception as e:
                print(f"Warning: Could not parse tile from {filepath.name}: {e}",
                      file=sys.stderr)

        return tile_index

    def get_required_tiles(self, bounds):
        """Get list of tile IDs covering a bounding box in LV95 coordinates."""
        minx, miny, maxx, maxy = bounds
        min_tile_x = int(minx / 1000)
        min_tile_y = int(miny / 1000)
        max_tile_x = int(maxx / 1000)
        max_tile_y = int(maxy / 1000)

        tiles = []
        for x in range(min_tile_x, max_tile_x + 1):
            for y in range(min_tile_y, max_tile_y + 1):
                tiles.append(f"{x:04d}-{y:04d}")
        return tiles

    def sample_heights(self, points, tiles, model_type):
        """
        Sample height values from raster tiles at given points.

        Args:
            points: List of (x, y) tuples in LV95
            tiles: List of tile IDs to search
            model_type: 'alti3d' or 'surface3d'

        Returns:
            numpy array of height values (NaN where no data)
        """
        heights = np.full(len(points), np.nan)
        tile_index = self.alti3d_tiles if model_type == 'alti3d' else self.surface3d_tiles

        for tile_id in tiles:
            cache_key = f"{model_type}_{tile_id}"

            if cache_key not in self.tile_cache:
                tile_path = tile_index.get(tile_id)
                if tile_path is None:
                    continue
                try:
                    self.tile_cache[cache_key] = rasterio.open(tile_path)
                except Exception as e:
                    print(f"Warning: Could not open {tile_path}: {e}", file=sys.stderr)
                    continue

            src = self.tile_cache[cache_key]

            try:
                sampled = list(src.sample(points, indexes=1))
                for i, value in enumerate(sampled):
                    if not np.isnan(value[0]) and value[0] != src.nodata:
                        heights[i] = value[0]
            except Exception as e:
                print(f"Warning: Error sampling from {tile_id}: {e}", file=sys.stderr)

        return heights

    def close(self):
        """Close all cached raster files."""
        for src in self.tile_cache.values():
            src.close()
        self.tile_cache.clear()


def calculate_building_volume(polygon, tile_index, egid=None, fid=None,
                              voxel_size=1.0):
    """
    Calculate volume and height metrics for a single building.

    Args:
        polygon: Shapely Polygon in LV95 (EPSG:2056)
        tile_index: TileIndex instance with loaded elevation tiles
        egid: Optional EGID
        fid: Optional FID from cadastral survey
        voxel_size: Grid cell size in meters

    Returns:
        Dict with volume, height metrics, and status
    """
    empty_result = {
        'egid': egid,
        'fid': fid,
        'area_footprint_m2': round(polygon.area, 2),
        'volume_above_ground_m3': 0,
        'elevation_base_m': np.nan,
        'elevation_roof_base_m': np.nan,
        'height_mean_m': 0,
        'height_max_m': 0,
        'height_minimal_m': 0,
        'grid_points_count': 0,
    }

    try:
        # Step 2: Create aligned grid
        grid_points = create_aligned_grid_points(polygon, voxel_size)

        if len(grid_points) == 0:
            return {**empty_result, 'status': 'no_grid_points'}

        # Determine required tiles
        tiles = tile_index.get_required_tiles(polygon.bounds)

        # Sample elevations
        terrain_heights = tile_index.sample_heights(grid_points, tiles, 'alti3d')
        surface_heights = tile_index.sample_heights(grid_points, tiles, 'surface3d')

        # Filter to points with both terrain and surface data
        valid_mask = ~(np.isnan(terrain_heights) | np.isnan(surface_heights))
        valid_terrain = terrain_heights[valid_mask]
        valid_surface = surface_heights[valid_mask]

        if len(valid_terrain) == 0:
            return {**empty_result, 'grid_points_count': len(grid_points),
                    'status': 'no_height_data'}

        # Base height = lowest terrain point under building
        base_height = np.min(valid_terrain)

        # Roof base = lowest surface point within footprint (estimated eave)
        roof_base = np.min(valid_surface)

        # Building heights relative to base (clamp negatives to 0)
        building_heights = np.maximum(valid_surface - base_height, 0)

        # Volume = sum of heights × cell area
        footprint_area = polygon.area
        volume = np.sum(building_heights) * (voxel_size ** 2)

        # Height metrics
        height_mean = np.mean(building_heights)
        height_max = np.max(building_heights)
        height_minimal = volume / footprint_area if footprint_area > 0 else 0

        return {
            'egid': egid,
            'fid': fid,
            'area_footprint_m2': round(footprint_area, 2),
            'volume_above_ground_m3': round(volume, 2),
            'elevation_base_m': round(base_height, 2),
            'elevation_roof_base_m': round(roof_base, 2),
            'height_mean_m': round(height_mean, 2),
            'height_max_m': round(height_max, 2),
            'height_minimal_m': round(height_minimal, 2),
            'grid_points_count': len(valid_terrain),
            'status': 'success',
        }

    except Exception as e:
        print(f"Error processing building (EGID={egid}, FID={fid}): {e}", file=sys.stderr)
        return {**empty_result, 'status': 'error'}
