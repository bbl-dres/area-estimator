#!/usr/bin/env python3
"""
Steps 2 & 3 — Aligned Grid + Volume

Step 2: Generates an orientation-aligned 1×1m grid within each building
footprint, rotated to the longest edge so non-axis-aligned buildings are
covered tightly.

Step 3: Samples terrain (swissALTI3D) and surface (swissSURFACE3D) elevations
at each grid point, then calculates building volume and all height metrics.

Outputs per building:
- volume_above_ground_m3
- elevation_base_min_m    (min terrain under building — used as volume base datum)
- elevation_base_mean_m   (mean terrain elevation under building)
- elevation_base_max_m    (max terrain elevation under building)
- elevation_roof_min_m    (min surface elevation within footprint — estimated eave)
- elevation_roof_mean_m   (mean surface elevation within footprint)
- elevation_roof_max_m    (max surface elevation within footprint — estimated ridge)
- height_mean_m           (mean of building heights at grid points)
- height_max_m            (max building height)
- height_minimal_m        (volume / footprint — equivalent uniform box height)
"""

import logging
from collections import OrderedDict
from pathlib import Path

import numpy as np
import rasterio
from shapely import contains_xy
from shapely.affinity import rotate

from tile_fetcher import tile_ids_from_bounds

log = logging.getLogger(__name__)

# LRU tile cache size (each cached tile = one open file handle)
MAX_CACHED_TILES = 200


# ── Step 2: Aligned Grid ────────────────────────────────────────────────────


def get_building_orientation(polygon):
    """
    Calculate building orientation using minimum area bounding rectangle.

    Returns rotation angle in degrees (angle of the longest edge).
    Returns 0.0 for degenerate polygons (too small or linear).
    """
    min_rect = polygon.minimum_rotated_rectangle

    # Guard against degenerate geometry (point or line)
    if min_rect.geom_type != 'Polygon' or min_rect.area < 1e-6:
        return 0.0

    coords = list(min_rect.exterior.coords)

    edge_lengths = []
    angles = []

    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]

        length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))

        edge_lengths.append(length)
        angles.append(angle)

    longest_idx = np.argmax(edge_lengths)
    return angles[longest_idx]


def create_aligned_grid_points(polygon, voxel_size=1.0):
    """
    Create grid points aligned to building orientation.

    Algorithm:
    1. Compute building orientation from minimum rotated rectangle
    2. Rotate polygon to align with axes
    3. Generate regular grid in rotated space
    4. Filter points inside/touching the polygon
    5. Rotate points back to original orientation

    Args:
        polygon: Shapely Polygon in LV95 coordinates
        voxel_size: Grid cell size in meters (default 1.0)

    Returns:
        List of (x, y) tuples in LV95 coordinates
    """
    rotation_angle = get_building_orientation(polygon)

    # Rotate polygon to align with axes
    rotated_polygon = rotate(polygon, -rotation_angle, origin='centroid')

    # Snap bounding box to grid boundaries
    bounds = rotated_polygon.bounds
    x_min = np.floor(bounds[0] / voxel_size) * voxel_size
    y_min = np.floor(bounds[1] / voxel_size) * voxel_size
    x_max = np.ceil(bounds[2] / voxel_size) * voxel_size
    y_max = np.ceil(bounds[3] / voxel_size) * voxel_size

    # Generate grid at cell centers
    x_coords = np.arange(x_min + voxel_size / 2, x_max, voxel_size)
    y_coords = np.arange(y_min + voxel_size / 2, y_max, voxel_size)

    # Filter points inside the rotated polygon using vectorized containment
    xx, yy = np.meshgrid(x_coords, y_coords)
    flat_x = xx.ravel()
    flat_y = yy.ravel()

    mask = contains_xy(rotated_polygon, flat_x, flat_y)
    inside_x = flat_x[mask]
    inside_y = flat_y[mask]

    if len(inside_x) == 0:
        return []

    # Rotate points back to original orientation (vectorized)
    cx, cy = rotated_polygon.centroid.x, rotated_polygon.centroid.y
    angle_rad = np.radians(rotation_angle)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)

    dx = inside_x - cx
    dy = inside_y - cy
    orig_x = cx + dx * cos_a - dy * sin_a
    orig_y = cy + dx * sin_a + dy * cos_a

    return list(zip(orig_x.tolist(), orig_y.tolist()))


# ── Step 3: Tile Index, Sampling & Volume ───────────────────────────────────


class TileIndex:
    """Indexes and caches swisstopo GeoTIFF elevation tiles."""

    def __init__(self, alti3d_dir, surface3d_dir):
        self.alti3d_dir = Path(alti3d_dir)
        self.surface3d_dir = Path(surface3d_dir)
        # OrderedDict gives us real LRU semantics: move_to_end(key) on hit,
        # popitem(last=False) to evict the oldest entry on overflow.
        self.tile_cache: "OrderedDict[str, rasterio.DatasetReader]" = OrderedDict()

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
            parts = filepath.stem.split('_')
            if len(parts) < 3:
                log.debug("Unexpected filename layout: %s", filepath.name)
                continue
            tile_id = parts[2]
            if '-' not in tile_id or len(tile_id.split('-')) != 2:
                log.debug("Unexpected tile ID format in %s", filepath.name)
                continue
            tile_index[tile_id] = filepath

        return tile_index

    def _open_tile(self, cache_key, tile_path):
        """Open a tile, evicting the least-recently-used entry when full."""
        if len(self.tile_cache) >= MAX_CACHED_TILES:
            _, evicted = self.tile_cache.popitem(last=False)
            evicted.close()

        self.tile_cache[cache_key] = rasterio.open(tile_path)

    def sample_heights(self, points, tiles, model_type):
        """
        Sample height values from raster tiles at given points.

        Uses a single windowed read per tile instead of point-by-point sampling:
        converts all points to pixel row/col indices, reads the minimal bounding
        window in one IO call, then indexes into the resulting numpy array.

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
                except (rasterio.errors.RasterioIOError, OSError) as e:
                    log.debug("Could not open %s: %s", tile_path, e)
                    continue
            else:
                # Cache hit — refresh LRU position
                self.tile_cache.move_to_end(cache_key)

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

                tile_pts = points_arr[mask]
                indices = np.where(mask)[0]

                # Convert LV95 coordinates to pixel row/col indices
                rows, cols = rasterio.transform.rowcol(
                    src.transform, tile_pts[:, 0], tile_pts[:, 1]
                )
                rows = np.clip(np.asarray(rows), 0, src.height - 1)
                cols = np.clip(np.asarray(cols), 0, src.width - 1)

                # Read the minimal bounding window in a single IO call
                row_min, row_max = int(rows.min()), int(rows.max())
                col_min, col_max = int(cols.min()), int(cols.max())
                window = rasterio.windows.Window(
                    col_min, row_min,
                    col_max - col_min + 1,
                    row_max - row_min + 1,
                )
                data = src.read(1, window=window).astype(float)

                # Index into the window and apply nodata mask
                values = data[rows - row_min, cols - col_min]
                nodata = src.nodata
                valid = ~np.isnan(values)
                if nodata is not None:
                    valid &= values != float(nodata)

                heights[indices[valid]] = values[valid]

            except (rasterio.errors.RasterioIOError, ValueError, IndexError) as e:
                log.debug("Error sampling from %s: %s", tile_id, e)

        return heights

    def close(self):
        """Close all cached raster files."""
        for src in self.tile_cache.values():
            src.close()
        self.tile_cache.clear()


def make_empty_volume_result(av_egid=None, fid=None,
                             area_footprint_m2=None, area_official_m2=None,
                             status_step3=None, warnings=''):
    """
    Build a result row with no measurements — used both as the base for
    successful runs (mutated below) and standalone for skipped buildings
    (e.g. no footprint after Step 1). Missing measurements are NaN, never
    zero, so downstream aggregations skip them correctly.

    The ``warnings`` field is a ``';'``-joined string that accumulates
    notes across pipeline steps (multi-polygon EGID, GWR lookup miss, etc.).

    Keep this in sync with the keys returned by calculate_building_volume.
    """
    result = {
        'av_egid': av_egid,
        'fid': fid,
        'area_footprint_m2': area_footprint_m2,
        'area_official_m2': area_official_m2,
        'volume_above_ground_m3': np.nan,
        'elevation_base_min_m': np.nan,
        'elevation_base_mean_m': np.nan,
        'elevation_base_max_m': np.nan,
        'elevation_roof_min_m': np.nan,
        'elevation_roof_mean_m': np.nan,
        'elevation_roof_max_m': np.nan,
        'height_mean_m': np.nan,
        'height_max_m': np.nan,
        'height_minimal_m': np.nan,
        'grid_points_count': 0,
        'warnings': warnings or '',
    }
    if status_step3 is not None:
        result['status_step3'] = status_step3
    return result


def append_warning(result, message):
    """Append a warning message to a result row's ``warnings`` column."""
    if not message:
        return
    existing = result.get('warnings', '') or ''
    result['warnings'] = f'{existing}; {message}' if existing else message


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
    empty_result = make_empty_volume_result(
        av_egid=av_egid, fid=fid,
        area_footprint_m2=round(footprint_area, 2),
        area_official_m2=area_official_m2,
    )

    try:
        # Step 2: Create aligned grid
        grid_points = create_aligned_grid_points(polygon, voxel_size)

        if len(grid_points) == 0:
            return {**empty_result, 'status_step3': 'no_grid_points'}

        # Determine required tiles (sorted for deterministic logging order)
        tiles = sorted(tile_ids_from_bounds(polygon.bounds))

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

        # Terrain (base) elevation statistics
        base_min = np.min(valid_terrain)
        base_mean = np.mean(valid_terrain)
        base_max = np.max(valid_terrain)

        # Roof surface elevation statistics
        roof_min = np.min(valid_surface)
        roof_mean = np.mean(valid_surface)
        roof_max = np.max(valid_surface)

        # Building heights measured from the lowest terrain point (flat base datum).
        # Using base_min ensures volume is referenced to a consistent horizontal
        # plane, which is stable on sloped terrain.
        building_heights = np.maximum(valid_surface - base_min, 0)

        # Volume = sum of heights × cell area
        volume = np.sum(building_heights) * (voxel_size ** 2)

        # Height metrics
        height_mean = np.mean(building_heights)
        height_max = np.max(building_heights)
        height_minimal = volume / footprint_area if footprint_area > 0 else 0

        # Spread empty_result first so any future column added to the
        # factory automatically lands in the success branch too. This is
        # the drift hazard that previously dropped the `warnings` field.
        return {
            **empty_result,
            'volume_above_ground_m3': round(volume, 2),
            'elevation_base_min_m': round(base_min, 2),
            'elevation_base_mean_m': round(base_mean, 2),
            'elevation_base_max_m': round(base_max, 2),
            'elevation_roof_min_m': round(roof_min, 2),
            'elevation_roof_mean_m': round(roof_mean, 2),
            'elevation_roof_max_m': round(roof_max, 2),
            'height_mean_m': round(height_mean, 2),
            'height_max_m': round(height_max, 2),
            'height_minimal_m': round(height_minimal, 2),
            'grid_points_count': len(valid_terrain),
            'status_step3': 'success',
        }

    except (rasterio.errors.RasterioIOError, ValueError, IndexError, ArithmeticError) as e:
        log.debug(
            "Error processing building (av_egid=%s, FID=%s): %s: %s",
            av_egid, fid, type(e).__name__, e,
        )
        return {**empty_result, 'status_step3': f'error:{type(e).__name__}'}
