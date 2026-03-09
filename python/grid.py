#!/usr/bin/env python3
"""
Step 2 — Create Aligned 1×1m Grid

Generates an orientation-aligned grid of 1×1 meter cells within each building
footprint. The grid is aligned to the building's longest edge (via minimum
rotated rectangle) to maximize coverage for non-axis-aligned buildings.
"""

import numpy as np
from shapely.affinity import rotate
from shapely.prepared import prep


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

        length = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
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
    prepared_polygon = prep(rotated_polygon)
    xx, yy = np.meshgrid(x_coords, y_coords)
    flat_x = xx.ravel()
    flat_y = yy.ravel()

    # Use shapely's vectorized contains for a significant speedup over
    # creating individual Point objects
    from shapely import contains_xy
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
