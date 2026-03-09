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

import logging
import sys
from pathlib import Path
import numpy as np
import rasterio

from grid import create_aligned_grid_points

log = logging.getLogger(__name__)

# LRU-style tile cache limit (each open tile = one file handle)
MAX_CACHED_TILES = 50


class TileIndex:
    """Indexes and caches swisstopo GeoTIFF elevation tiles."""

    def __init__(self, alti3d_dir, surface3d_dir):
        self.alti3d_dir = Path(alti3d_dir)
        self.surface3d_dir = Path(surface3d_dir)
        self.tile_cache = {}
        self._cache_order = []

        log.info("Indexing available tiles...")
        self.alti3d_tiles = self._index_tiles(self.alti3d_dir)
        self.surface3d_tiles = self._index_tiles(self.surface3d_dir)
        log.info(f"  Found {len(self.alti3d_tiles)} swissALTI3D tiles")
        log.info(f"  Found {len(self.surface3d_tiles)} swissSURFACE3D tiles")

    def _index_tiles(self, directory):
        """
        Scan directory and build tile_id -> filepath mapping.

        Expected filenames:
        - swissalti3d_YYYY_XXXX-YYYY_0.5_2056_5728.tif
        - swisssurface3d-raster_YYYY_XXXX-YYYY_0.5_2056_5728.tif

        Tile ID is at index 2 when split by underscore.
        Tile IDs encode the 1km LV95 grid position (e.g. 2683-1248).
        """
        tile_index = {}

        if not directory.exists():
            log.warning(f"Directory not found: {directory}")
            return tile_index

        for filepath in directory.glob("*.tif"):
            try:
                parts = filepath.stem.split('_')
                if len(parts) >= 3:
                    tile_id = parts[2]
                    if '-' in tile_id and len(tile_id.split('-')) == 2:
                        tile_index[tile_id] = filepath
                    else:
                        log.debug(f"Unexpected tile ID format in {filepath.name}")
            except Exception as e:
                log.debug(f"Could not parse tile from {filepath.name}: {e}")

        return tile_index

    def _open_tile(self, cache_key, tile_path):
        """Open a tile and manage cache eviction."""
        if len(self.tile_cache) >= MAX_CACHED_TILES:
            evict_key = self._cache_order.pop(0)
            if evict_key in self.tile_cache:
                self.tile_cache[evict_key].close()
                del self.tile_cache[evict_key]

        self.tile_cache[cache_key] = rasterio.open(tile_path)
        self._cache_order.append(cache_key)

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

        Only samples points that fall within each tile's bounds to avoid
        unnecessary raster reads.

        Args:
            points: List of (x, y) tuples in LV95
            tiles: List of tile IDs to search
            model_type: 'alti3d' or 'surface3d'

        Returns:
            numpy array of height values (NaN where no data)
        """
        heights = np.full(len(points), np.nan)
        points_arr = np.array(points)
        tile_index = self.alti3d_tiles if model_type == 'alti3d' else self.surface3d_tiles

        for tile_id in tiles:
            cache_key = f"{model_type}_{tile_id}"

            if cache_key not in self.tile_cache:
                tile_path = tile_index.get(tile_id)
                if tile_path is None:
                    continue
                try:
                    self._open_tile(cache_key, tile_path)
                except Exception as e:
                    log.debug(f"Could not open {tile_path}: {e}")
                    continue

            src = self.tile_cache[cache_key]

            try:
                # Filter to points within this tile's bounds
                bounds = src.bounds
                mask = (
                    (points_arr[:, 0] >= bounds.left) &
                    (points_arr[:, 0] <= bounds.right) &
                    (points_arr[:, 1] >= bounds.bottom) &
                    (points_arr[:, 1] <= bounds.top)
                )

                if not mask.any():
                    continue

                tile_points = [tuple(p) for p in points_arr[mask]]
                indices = np.where(mask)[0]

                sampled = list(src.sample(tile_points, indexes=1))
                for idx, value in zip(indices, sampled):
                    if not np.isnan(value[0]) and value[0] != src.nodata:
                        heights[idx] = value[0]
            except Exception as e:
                log.debug(f"Error sampling from {tile_id}: {e}")

        return heights

    def add_tiles(self, directory, model_type):
        """Incrementally index new tiles from a directory without full rescan."""
        tile_index = self.alti3d_tiles if model_type == 'alti3d' else self.surface3d_tiles
        new_count = 0
        for filepath in Path(directory).glob("*.tif"):
            try:
                parts = filepath.stem.split('_')
                if len(parts) >= 3:
                    tile_id = parts[2]
                    if '-' in tile_id and tile_id not in tile_index:
                        tile_index[tile_id] = filepath
                        new_count += 1
            except Exception:
                pass
        return new_count

    def close(self):
        """Close all cached raster files."""
        for src in self.tile_cache.values():
            src.close()
        self.tile_cache.clear()
        self._cache_order.clear()


def calculate_building_volume(polygon, tile_index, av_egid=None, fid=None,
                              area_official_m2=None, voxel_size=1.0):
    """
    Calculate volume and height metrics for a single building.

    Uses polygon.area (computed from geometry) as the primary footprint area.
    The official area attribute is kept for reference only.

    Args:
        polygon: Shapely Polygon in LV95 (EPSG:2056)
        tile_index: TileIndex instance with loaded elevation tiles
        av_egid: Optional EGID from Amtliche Vermessung (GWR_EGID)
        fid: Optional FID from cadastral survey
        area_official_m2: Optional official area from source data (reference only)
        voxel_size: Grid cell size in meters

    Returns:
        Dict with volume, height metrics, and status
    """
    footprint_area = polygon.area

    empty_result = {
        'av_egid': av_egid,
        'fid': fid,
        'area_footprint_m2': round(footprint_area, 2),
        'area_official_m2': area_official_m2,
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
            return {**empty_result, 'status_step3': 'no_grid_points'}

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
                    'status_step3': 'no_height_data'}

        # Base height = lowest terrain point under building
        base_height = np.min(valid_terrain)

        # Roof base = lowest surface point within footprint (estimated eave)
        roof_base = np.min(valid_surface)

        # Building heights relative to base (clamp negatives to 0)
        building_heights = np.maximum(valid_surface - base_height, 0)

        # Volume = sum of heights × cell area
        volume = np.sum(building_heights) * (voxel_size ** 2)

        # Height metrics
        height_mean = np.mean(building_heights)
        height_max = np.max(building_heights)
        height_minimal = volume / footprint_area if footprint_area > 0 else 0

        return {
            'av_egid': av_egid,
            'fid': fid,
            'area_footprint_m2': round(footprint_area, 2),
            'area_official_m2': area_official_m2,
            'volume_above_ground_m3': round(volume, 2),
            'elevation_base_m': round(base_height, 2),
            'elevation_roof_base_m': round(roof_base, 2),
            'height_mean_m': round(height_mean, 2),
            'height_max_m': round(height_max, 2),
            'height_minimal_m': round(height_minimal, 2),
            'grid_points_count': len(valid_terrain),
            'status_step3': 'success',
        }

    except Exception as e:
        log.debug(f"Error processing building (av_egid={av_egid}, FID={fid}): {e}")
        return {**empty_result, 'status_step3': 'error'}
