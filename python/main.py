#!/usr/bin/env python3
"""
Building Volume Calculator for Swiss Buildings
Uses swissALTI3D and swissSURFACE3D to calculate building volumes from PostGIS/Supabase database
"""

import argparse
import sys
from pathlib import Path
import psycopg2
import geopandas as gpd
import rasterio
import numpy as np
from shapely.geometry import Point, Polygon
from shapely import wkt
from shapely.affinity import rotate, translate
import pandas as pd
from pyproj import Transformer
import warnings
warnings.filterwarnings('ignore')

class BuildingVolumeCalculator:
    def __init__(self, db_connection, alti3d_dir, surface3d_dir):
        self.db_connection = db_connection
        self.alti3d_dir = Path(alti3d_dir)
        self.surface3d_dir = Path(surface3d_dir)
        self.voxel_size = 1.0

        # Coordinate transformer from WGS84 to LV95
        self.transformer_to_lv95 = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)

        # Cache for loaded tiles
        self.tile_cache = {}

        # Build tile index from directory contents
        print("Indexing available tiles...")
        self.alti3d_tiles = self._index_tiles(self.alti3d_dir)
        self.surface3d_tiles = self._index_tiles(self.surface3d_dir)
        print(f"  Found {len(self.alti3d_tiles)} swissALTI3D tiles")
        print(f"  Found {len(self.surface3d_tiles)} swissSURFACE3D tiles")

    def _index_tiles(self, directory):
        """
        Scan directory and build a tile ID -> filepath mapping

        Extracts tile IDs dynamically from filenames, making the system robust
        to different years and naming variations.

        Expected filename formats:
        - swissalti3d_YYYY_XXXX-YYYY_0.5_2056_5728.tif
        - swisssurface3d-raster_YYYY_XXXX-YYYY_0.5_2056_5728.tif

        Where:
        - YYYY = year (e.g., 2019, 2023, 2025)
        - XXXX-YYYY = tile ID (e.g., 2609-1176)

        The tile ID is always at index 2 when split by underscore.
        """
        tile_index = {}

        if not directory.exists():
            print(f"Warning: Directory not found: {directory}", file=sys.stderr)
            return tile_index

        # Scan all .tif files in directory
        for filepath in directory.glob("*.tif"):
            try:
                # Split filename by underscore to extract components
                parts = filepath.stem.split('_')

                if len(parts) >= 3:
                    # Extract tile ID from position 2
                    tile_id = parts[2]

                    # Validate tile ID format (should be XXXX-YYYY)
                    if '-' in tile_id and len(tile_id.split('-')) == 2:
                        tile_index[tile_id] = filepath
                    else:
                        print(f"Warning: Unexpected tile ID format in {filepath.name}", file=sys.stderr)

            except Exception as e:
                print(f"Warning: Could not parse tile from {filepath.name}: {e}", file=sys.stderr)

        return tile_index

    def get_database_connection(self):
        """Create a database connection"""
        return psycopg2.connect(self.db_connection)

    def load_buildings_from_db(self, table_name='public.buildings', geom_column='geog',
                                bbox=None, building_ids=None, limit=None):
        """Load building footprints from PostGIS database"""
        print(f"Loading buildings from {table_name}...")

        conn = self.get_database_connection()

        # Build query
        # Cast geography to geometry for proper WKT output
        query = f"""
            SELECT id, egid, ST_AsText({geom_column}::geometry) as geom_wkt
            FROM {table_name}
            WHERE {geom_column} IS NOT NULL
        """

        # Add filters
        if building_ids:
            ids_str = ','.join(map(str, building_ids))
            query += f" AND id IN ({ids_str})"

        if bbox:
            # bbox is in WGS84 (lon, lat)
            minlon, minlat, maxlon, maxlat = bbox
            query += f"""
                AND ST_Intersects(
                    {geom_column},
                    ST_MakeEnvelope({minlon}, {minlat}, {maxlon}, {maxlat}, 4326)
                )
            """

        if limit:
            query += f" LIMIT {limit}"

        # Execute query
        df = pd.read_sql(query, conn)
        conn.close()

        if len(df) == 0:
            print("No buildings found matching criteria")
            return gpd.GeoDataFrame()

        print(f"Found {len(df)} buildings")

        # Convert WKT to geometry and create GeoDataFrame
        df['geometry'] = df['geom_wkt'].apply(wkt.loads)
        gdf = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')

        # Transform to LV95 for processing
        gdf = gdf.to_crs('EPSG:2056')

        return gdf

    def get_tile_id_from_point(self, x, y):
        """
        Calculate tile ID from LV95 coordinates

        Swisstopo tiles are named based on their SW corner in kilometers.
        Format: XXXX-YYYY where XXXX and YYYY are the coordinates divided by 1000

        Examples:
        - Point (2609500, 1176300) -> Tile "2609-1176"
        - Point (2600750, 1224820) -> Tile "2600-1224"
        """
        tile_x = int(x / 1000)
        tile_y = int(y / 1000)
        return f"{tile_x:04d}-{tile_y:04d}"

    def get_required_tiles(self, bounds):
        """Get list of required tile IDs for a bounding box"""
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

    def get_tile_path(self, tile_id, model_type):
        """
        Get the file path for a specific tile using the pre-built index
        """
        if model_type == 'alti3d':
            return self.alti3d_tiles.get(tile_id)
        else:  # surface3d
            return self.surface3d_tiles.get(tile_id)

    def get_building_orientation(self, polygon):
        """
        Calculate building orientation using minimum area bounding rectangle
        Returns rotation angle in degrees
        """
        # Get minimum rotated rectangle
        min_rect = polygon.minimum_rotated_rectangle

        # Get the coordinates of the rectangle
        coords = list(min_rect.exterior.coords)

        # Calculate the angle of the longest edge
        edge_lengths = []
        angles = []

        for i in range(len(coords) - 1):
            x1, y1 = coords[i]
            x2, y2 = coords[i + 1]

            length = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))

            edge_lengths.append(length)
            angles.append(angle)

        # Get angle of longest edge
        longest_idx = np.argmax(edge_lengths)
        return angles[longest_idx]

    def create_aligned_grid_points(self, polygon):
        """
        Create 1x1m grid points aligned to building orientation

        This improves coverage and accuracy for non-axis-aligned buildings by:
        1. Rotating the building to align with axes
        2. Generating a regular grid in rotated space
        3. Rotating the grid points back to original orientation

        This ensures better grid coverage compared to a fixed axis-aligned grid,
        especially for diagonal buildings where many grid points would fall outside
        the footprint with a standard grid.
        """
        # Get building orientation angle from minimum area bounding rectangle
        rotation_angle = self.get_building_orientation(polygon)

        # Rotate polygon to align with axes (makes grid generation simpler)
        rotated_polygon = rotate(polygon, -rotation_angle, origin='centroid')

        # Get bounds of rotated polygon
        bounds = rotated_polygon.bounds
        x_min = np.floor(bounds[0] / self.voxel_size) * self.voxel_size
        y_min = np.floor(bounds[1] / self.voxel_size) * self.voxel_size
        x_max = np.ceil(bounds[2] / self.voxel_size) * self.voxel_size
        y_max = np.ceil(bounds[3] / self.voxel_size) * self.voxel_size

        # Generate grid in rotated space
        x_coords = np.arange(x_min + self.voxel_size/2, x_max, self.voxel_size)
        y_coords = np.arange(y_min + self.voxel_size/2, y_max, self.voxel_size)

        # Create points and filter by rotated polygon
        rotated_points = []
        for x in x_coords:
            for y in y_coords:
                point = Point(x, y)
                if rotated_polygon.contains(point) or rotated_polygon.touches(point):
                    rotated_points.append(point)

        if len(rotated_points) == 0:
            return []

        # Rotate points back to original orientation
        original_points = []
        for point in rotated_points:
            # Rotate back around the rotated polygon's centroid
            rotated_back = rotate(point, rotation_angle, origin=rotated_polygon.centroid)
            original_points.append((rotated_back.x, rotated_back.y))

        return original_points

    def sample_heights_from_tiles(self, points, tiles, model_type):
        """Sample height values from raster tiles"""
        heights = np.full(len(points), np.nan)

        for tile_id in tiles:
            # Check cache first
            cache_key = f"{model_type}_{tile_id}"

            if cache_key not in self.tile_cache:
                tile_path = self.get_tile_path(tile_id, model_type)

                if tile_path is None:
                    continue

                try:
                    self.tile_cache[cache_key] = rasterio.open(tile_path)
                except Exception as e:
                    print(f"Warning: Could not open {tile_path}: {e}", file=sys.stderr)
                    continue

            src = self.tile_cache[cache_key]

            try:
                # Sample all points
                sampled = list(src.sample(points, indexes=1))

                for i, value in enumerate(sampled):
                    if not np.isnan(value[0]) and value[0] != src.nodata:
                        heights[i] = value[0]
            except Exception as e:
                print(f"Warning: Error sampling from {tile_id}: {e}", file=sys.stderr)

        return heights

    def calculate_building_volume(self, polygon, building_id=None, egid=None):
        """
        Calculate volume for a single building

        Steps:
        1. Generate aligned 1x1m grid points within building footprint
        2. Sample terrain heights (swissALTI3D) at each grid point
        3. Sample surface heights (swissSURFACE3D) at each grid point
        4. Calculate base height as minimum terrain elevation
        5. Calculate volume as sum of (surface - base) * 1m² for all points
        """
        try:
            # Create aligned grid points
            grid_points = self.create_aligned_grid_points(polygon)

            if len(grid_points) == 0:
                return {
                    'id': building_id,
                    'egid': egid,
                    'volume_m3': 0,
                    'footprint_area_m2': polygon.area,
                    'mean_height_m': 0,
                    'max_height_m': 0,
                    'base_height_m': np.nan,
                    'grid_points_count': 0,
                    'status': 'no_grid_points'
                }

            # Get required tiles based on building bounds
            tiles = self.get_required_tiles(polygon.bounds)

            # Sample heights from GeoTIFF tiles
            terrain_heights = self.sample_heights_from_tiles(grid_points, tiles, 'alti3d')
            surface_heights = self.sample_heights_from_tiles(grid_points, tiles, 'surface3d')

            # Filter valid points (where both terrain and surface data exist)
            valid_mask = ~(np.isnan(terrain_heights) | np.isnan(surface_heights))
            valid_terrain = terrain_heights[valid_mask]
            valid_surface = surface_heights[valid_mask]

            if len(valid_terrain) == 0:
                return {
                    'id': building_id,
                    'egid': egid,
                    'volume_m3': 0,
                    'footprint_area_m2': polygon.area,
                    'mean_height_m': 0,
                    'max_height_m': 0,
                    'base_height_m': np.nan,
                    'grid_points_count': len(grid_points),
                    'status': 'no_height_data'
                }

            # Calculate base height as minimum terrain elevation across all grid points
            # This represents the lowest point of the terrain under the building
            base_height = np.min(valid_terrain)

            # Calculate building heights relative to base
            # Negative values (underground) are set to 0
            building_heights = np.maximum(valid_surface - base_height, 0)

            # Calculate total volume: sum of all heights × grid cell area (1m²)
            volume = np.sum(building_heights) * (self.voxel_size ** 2)

            return {
                'id': building_id,
                'egid': egid,
                'volume_m3': round(volume, 2),
                'footprint_area_m2': round(polygon.area, 2),
                'mean_height_m': round(np.mean(building_heights), 2),
                'max_height_m': round(np.max(building_heights), 2),
                'base_height_m': round(base_height, 2),
                'grid_points_count': len(valid_terrain),
                'status': 'success'
            }

        except Exception as e:
            print(f"Error processing building {building_id}: {e}", file=sys.stderr)
            return {
                'id': building_id,
                'egid': egid,
                'volume_m3': 0,
                'footprint_area_m2': 0,
                'mean_height_m': 0,
                'max_height_m': 0,
                'base_height_m': np.nan,
                'grid_points_count': 0,
                'status': 'error'
            }

    def process_buildings(self, buildings_gdf):
        """Process all buildings and return results DataFrame"""
        results = []
        total = len(buildings_gdf)

        for idx, row in buildings_gdf.iterrows():
            print(f"Processing building {len(results) + 1}/{total}", end='\r')
            building_id = row['id']
            egid = row.get('egid', None)
            result = self.calculate_building_volume(row.geometry, building_id, egid)
            results.append(result)

        print(f"\nProcessed {total} buildings")
        return pd.DataFrame(results)

    def write_results_to_db(self, results_df, table_name='public.buildings'):
        """
        Write calculated volumes back to database

        Updates the following columns:
        - volume_total_m3: Not estimated (kept NULL)
        - volume_above_ground_m3: Our volume estimation result
        - volume_below_ground_m3: Cannot estimate from LIDAR (kept NULL)
        - volume_accuracy: Not calculated yet (kept NULL)
        - elevation_base_m: Minimum terrain elevation
        - height_mean_m: Average building height
        - height_max_m: Maximum building height
        """
        print(f"\nWriting results to database table {table_name}...")

        conn = self.get_database_connection()
        cursor = conn.cursor()

        # Ensure columns exist
        columns = [
            ('volume_above_ground_m3', 'numeric'),
            ('elevation_base_m', 'numeric'),
            ('height_mean_m', 'numeric'),
            ('height_max_m', 'numeric'),
        ]

        for col_name, col_type in columns:
            cursor.execute(f"""
                ALTER TABLE {table_name}
                ADD COLUMN IF NOT EXISTS {col_name} {col_type}
            """)

        conn.commit()

        # Update rows (only successful calculations)
        successful = results_df[results_df['status'] == 'success']
        updated_count = 0

        for _, row in successful.iterrows():
            cursor.execute(f"""
                UPDATE {table_name}
                SET
                    volume_above_ground_m3 = %s,
                    elevation_base_m = %s,
                    height_mean_m = %s,
                    height_max_m = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (
                row['volume_m3'],
                row['base_height_m'],
                row['mean_height_m'],
                row['max_height_m'],
                row['id']
            ))
            updated_count += 1

        conn.commit()
        cursor.close()
        conn.close()

        print(f"Updated {updated_count} buildings in database")

    def close_tile_cache(self):
        """Close all cached raster files"""
        for src in self.tile_cache.values():
            src.close()
        self.tile_cache.clear()

def main():
    parser = argparse.ArgumentParser(
        description='Calculate building volumes from PostGIS database using Swiss height models'
    )
    parser.add_argument('db_connection',
                       help='PostgreSQL connection string (e.g., postgresql://user:pass@host:5432/db)')
    parser.add_argument('alti3d_dir',
                       help='Directory containing swissALTI3D tiles')
    parser.add_argument('surface3d_dir',
                       help='Directory containing swissSURFACE3D tiles')
    parser.add_argument('-o', '--output',
                       help='Output CSV file (optional, omit to skip CSV export)')
    parser.add_argument('-l', '--limit', type=int,
                       help='Limit number of buildings to process')
    parser.add_argument('-b', '--bbox', nargs=4, type=float,
                       metavar=('MINLON', 'MINLAT', 'MAXLON', 'MAXLAT'),
                       help='Bounding box in WGS84 coordinates')
    parser.add_argument('--building-ids', nargs='+', type=int,
                       help='Process specific building IDs')
    parser.add_argument('--write-to-db', action='store_true',
                       help='Write results back to database (updates volume_above_ground_m3, elevation_base_m, height_mean_m, height_max_m)')
    parser.add_argument('--geometry-column', default='geog',
                       help='Name of geometry column (default: geog)')
    parser.add_argument('--table-name', default='public.buildings',
                       help='Table name (default: public.buildings)')

    args = parser.parse_args()

    # Validate inputs
    if not Path(args.alti3d_dir).is_dir():
        print(f"Error: ALTI3D directory not found: {args.alti3d_dir}", file=sys.stderr)
        return 1

    if not Path(args.surface3d_dir).is_dir():
        print(f"Error: SURFACE3D directory not found: {args.surface3d_dir}", file=sys.stderr)
        return 1

    # Initialize calculator
    try:
        calc = BuildingVolumeCalculator(args.db_connection, args.alti3d_dir, args.surface3d_dir)
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        return 1

    # Load buildings
    try:
        buildings = calc.load_buildings_from_db(
            table_name=args.table_name,
            geom_column=args.geometry_column,
            bbox=args.bbox,
            building_ids=args.building_ids,
            limit=args.limit
        )
    except Exception as e:
        print(f"Error loading buildings: {e}", file=sys.stderr)
        return 1

    if len(buildings) == 0:
        print("No buildings to process")
        return 0

    # Validate that at least one output method is specified
    if not args.output and not args.write_to_db:
        print("Error: Must specify either --output for CSV export or --write-to-db for database update", file=sys.stderr)
        return 1

    # Process buildings
    results = calc.process_buildings(buildings)

    # Save CSV if output file specified
    if args.output:
        results.to_csv(args.output, index=False)
        print(f"\nResults saved to: {args.output}")

    # Write to database if requested
    if args.write_to_db:
        try:
            calc.write_results_to_db(results, table_name=args.table_name)
        except Exception as e:
            print(f"Error writing to database: {e}", file=sys.stderr)
            return 1

    # Clean up
    calc.close_tile_cache()

    # Print summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    successful = results[results['status'] == 'success']
    print(f"Successful: {len(successful)}/{len(results)}")

    if len(successful) > 0:
        print(f"Total volume: {successful['volume_m3'].sum():,.0f} m³")
        print(f"Avg volume: {successful['volume_m3'].mean():,.0f} m³")
        print(f"Avg height: {successful['mean_height_m'].mean():.1f} m")
        print(f"Avg grid points per building: {successful['grid_points_count'].mean():.0f}")

    # Status breakdown
    print("\nStatus breakdown:")
    for status, count in results['status'].value_counts().items():
        print(f"  {status}: {count}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
