#!/usr/bin/env python3
"""
Building Floor Area Estimator for Swiss Buildings

Estimates gross floor areas (Geschossflächen) using:
- Building volumes from LIDAR (volume-estimator output)
- Building footprints from cadastral data
- Building classifications from GWR (GKAT/GKLAS)
- Floor height assumptions based on building type

Based on Canton Zurich methodology (SEILER & SEILER GmbH, December 2020)
"""

import argparse
import sys
import psycopg2
import pandas as pd
import numpy as np

# Floor height lookup table based on Canton Zurich methodology
# Format: code -> (EG_min, EG_max, RG_min, RG_max, schema, description)
# EG = Erdgeschoss (ground floor), RG = Regelgeschoss (regular floors)
# schema: 'GKAT' or 'GKLAS' indicates which field to match
FLOOR_HEIGHT_LOOKUP = {
    # GKAT-based lookups (category)
    '1010': (2.70, 3.30, 2.70, 3.30, 'GKAT', 'Provisorische Unterkunft'),
    '1030': (2.70, 3.30, 2.70, 3.30, 'GKAT', 'Wohngebäude mit Nebennutzung'),
    '1040': (3.30, 3.70, 2.70, 3.70, 'GKAT', 'Gebäude mit teilweiser Wohnnutzung'),
    '1060': (3.30, 5.00, 3.00, 5.00, 'GKAT', 'Gebäude ohne Wohnnutzung'),
    '1080': (3.00, 4.00, 3.00, 4.00, 'GKAT', 'Sonderbauten'),

    # GKLAS-based lookups (class) - Residential
    '1110': (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Einfamilienhaus'),
    '1121': (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Zweifamilienhaus'),
    '1122': (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Mehrfamilienhaus'),
    '1130': (2.70, 3.30, 2.70, 3.30, 'GKLAS', 'Wohngebäude für Gemeinschaften'),

    # GKLAS-based lookups - Hotels and Tourism
    '1211': (3.30, 3.70, 3.00, 3.50, 'GKLAS', 'Hotelgebäude'),
    '1212': (3.00, 3.50, 3.00, 3.50, 'GKLAS', 'Kurzfristige Beherbergung'),

    # GKLAS-based lookups - Commercial and Industrial
    '1220': (3.40, 4.20, 3.40, 4.20, 'GKLAS', 'Bürogebäude'),
    '1230': (3.40, 5.00, 3.40, 5.00, 'GKLAS', 'Gross- und Einzelhandel'),
    '1231': (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Restaurants und Bars'),
    '1241': (4.00, 6.00, 4.00, 6.00, 'GKLAS', 'Bahnhöfe, Terminals'),
    '1242': (2.80, 3.20, 2.80, 3.20, 'GKLAS', 'Parkhäuser'),
    '1251': (4.00, 7.00, 4.00, 7.00, 'GKLAS', 'Industriegebäude'),
    '1252': (3.50, 6.00, 3.50, 6.00, 'GKLAS', 'Behälter, Silos, Lager'),
    '1261': (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Kultur und Freizeit'),
    '1262': (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Museen und Bibliotheken'),
    '1263': (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Schulen und Hochschulen'),
    '1264': (3.30, 4.00, 3.30, 4.00, 'GKLAS', 'Spitäler und Kliniken'),
    '1265': (3.00, 6.00, 3.00, 6.00, 'GKLAS', 'Sporthallen'),
    '1271': (3.50, 5.00, 3.50, 5.00, 'GKLAS', 'Landwirtschaftliche Betriebsgebäude'),
    '1272': (3.00, 6.00, 3.00, 6.00, 'GKLAS', 'Kirchen und Sakralbauten'),
    '1273': (3.00, 4.00, 3.00, 4.00, 'GKLAS', 'Denkmäler, geschützte Gebäude'),
    '1274': (3.00, 4.00, 3.00, 4.00, 'GKLAS', 'Andere Hochbauten'),
}

# Default floor heights for unknown building types (residential default)
DEFAULT_FLOOR_HEIGHT = (2.70, 3.30, 2.70, 3.30, 'DEFAULT', 'Unknown/Fallback')

# Accuracy categories based on building type uncertainty
ACCURACY_HIGH = 'high'       # ±10-15% - residential buildings with clear classification
ACCURACY_MEDIUM = 'medium'   # ±15-25% - commercial/office buildings
ACCURACY_LOW = 'low'         # ±25-40% - industrial, special use, or missing classification


class BuildingFloorAreaEstimator:
    """
    Estimates building floor areas using volume, footprint, and GWR classification data.
    """

    def __init__(self, db_connection):
        self.db_connection = db_connection

    def get_database_connection(self):
        """Create a database connection"""
        return psycopg2.connect(self.db_connection)

    def get_floor_height(self, category, building_class):
        """
        Look up floor height parameters based on building classification.

        Priority:
        1. Check GKLAS (building class) first for specific match
        2. Fall back to GKAT (category) if no GKLAS match
        3. Use default residential values if nothing matches

        Returns: (floor_height_min, floor_height_max, schema_used, description)
        """
        # Try GKLAS first (more specific)
        if building_class and str(building_class) in FLOOR_HEIGHT_LOOKUP:
            entry = FLOOR_HEIGHT_LOOKUP[str(building_class)]
            if entry[4] == 'GKLAS':
                # Use average of EG and RG for simplicity
                min_height = (entry[0] + entry[2]) / 2
                max_height = (entry[1] + entry[3]) / 2
                return (min_height, max_height, 'GKLAS', entry[5])

        # Try GKAT (category)
        if category and str(category) in FLOOR_HEIGHT_LOOKUP:
            entry = FLOOR_HEIGHT_LOOKUP[str(category)]
            if entry[4] == 'GKAT':
                min_height = (entry[0] + entry[2]) / 2
                max_height = (entry[1] + entry[3]) / 2
                return (min_height, max_height, 'GKAT', entry[5])

        # Default fallback
        entry = DEFAULT_FLOOR_HEIGHT
        min_height = (entry[0] + entry[2]) / 2
        max_height = (entry[1] + entry[3]) / 2
        return (min_height, max_height, 'DEFAULT', entry[5])

    def determine_accuracy(self, category, building_class, has_volume, has_footprint):
        """
        Determine accuracy level based on data quality and building type.
        """
        if not has_volume or not has_footprint:
            return ACCURACY_LOW

        # Check if we have classification data
        has_classification = category is not None or building_class is not None

        if not has_classification:
            return ACCURACY_LOW

        # Residential buildings (GKAT 1020 or GKLAS 11xx) have best accuracy
        cat_str = str(category) if category else ''
        class_str = str(building_class) if building_class else ''

        if cat_str == '1020' or class_str.startswith('11'):
            return ACCURACY_HIGH

        # Commercial/office buildings
        if class_str in ['1220', '1230', '1231', '1263', '1264']:
            return ACCURACY_MEDIUM

        # Industrial and special use buildings have lower accuracy
        if class_str in ['1251', '1252', '1265', '1272'] or cat_str in ['1060', '1080']:
            return ACCURACY_LOW

        return ACCURACY_MEDIUM

    def calculate_floor_area(self, row):
        """
        Calculate floor area estimates for a single building.

        Methodology:
        1. Get mean height from volume/footprint or use pre-calculated height_mean_m
        2. Look up floor height based on building classification
        3. Calculate floor count: mean_height / floor_height
        4. Calculate floor area: footprint × floor_count
        """
        building_id = row['id']
        footprint_area = row.get('area_footprint_m2')
        volume = row.get('volume_above_ground_m3')
        height_mean = row.get('height_mean_m')
        category = row.get('category')
        building_class = row.get('class')

        # Initialize result
        result = {
            'id': building_id,
            'area_floor_total_m2': None,
            'area_floor_above_ground_m2': None,
            'area_accuracy': None,
            'floors_total': None,
            'floors_above': None,
            'floors_accuracy': None,
            'status': 'error',
            'error_message': None
        }

        # Validate required data
        if footprint_area is None or footprint_area <= 0:
            result['error_message'] = 'Missing or invalid footprint area'
            return result

        if (volume is None or volume <= 0) and (height_mean is None or height_mean <= 0):
            result['error_message'] = 'Missing volume and height data'
            return result

        # Calculate mean height if not available
        if height_mean is None or height_mean <= 0:
            height_mean = volume / footprint_area

        # Sanity check on height (buildings shouldn't be > 200m typically)
        if height_mean > 200:
            result['error_message'] = f'Implausible mean height: {height_mean:.1f}m'
            return result

        # Get floor height parameters
        floor_height_min, floor_height_max, schema_used, description = self.get_floor_height(
            category, building_class
        )

        # Calculate floor count using min/max floor heights
        # Higher floor height = fewer floors (use max height for min floors)
        # Lower floor height = more floors (use min height for max floors)
        floors_min = height_mean / floor_height_max
        floors_max = height_mean / floor_height_min

        # Use mean of min/max for estimate
        floors_estimate = (floors_min + floors_max) / 2

        # Round to reasonable values (at least 1 floor)
        floors_estimate = max(1.0, floors_estimate)
        floors_rounded = round(floors_estimate)

        # Calculate floor areas
        area_min = footprint_area * floors_min
        area_max = footprint_area * floors_max
        area_estimate = footprint_area * floors_estimate

        # Determine accuracy
        has_volume = volume is not None and volume > 0
        has_footprint = footprint_area is not None and footprint_area > 0
        accuracy = self.determine_accuracy(category, building_class, has_volume, has_footprint)

        # Build result
        result['area_floor_total_m2'] = round(area_estimate, 2)
        result['area_floor_above_ground_m2'] = round(area_estimate, 2)  # Same as total (no underground estimate)
        result['area_accuracy'] = accuracy
        result['floors_total'] = floors_rounded
        result['floors_above'] = floors_rounded  # Same as total (no underground estimate)
        result['floors_accuracy'] = accuracy
        result['status'] = 'success'

        # Add debug info
        result['_height_mean_m'] = round(height_mean, 2)
        result['_floor_height_used'] = round((floor_height_min + floor_height_max) / 2, 2)
        result['_schema_used'] = schema_used
        result['_building_type'] = description

        return result

    def load_buildings_from_db(self, table_name='public.buildings', building_ids=None,
                                bbox=None, limit=None, only_with_volume=True):
        """
        Load buildings from database that have volume data.
        """
        print(f"Loading buildings from {table_name}...")

        conn = self.get_database_connection()

        # Build query - select fields needed for floor area calculation
        query = f"""
            SELECT
                id,
                egid,
                area_footprint_m2,
                volume_above_ground_m3,
                height_mean_m,
                category,
                class
            FROM {table_name}
            WHERE 1=1
        """

        # Only process buildings with volume data
        if only_with_volume:
            query += " AND volume_above_ground_m3 IS NOT NULL AND volume_above_ground_m3 > 0"
            query += " AND area_footprint_m2 IS NOT NULL AND area_footprint_m2 > 0"

        # Add filters
        if building_ids:
            ids_str = ','.join(map(str, building_ids))
            query += f" AND id IN ({ids_str})"

        if bbox:
            minlon, minlat, maxlon, maxlat = bbox
            query += f"""
                AND ST_Intersects(
                    geog,
                    ST_MakeEnvelope({minlon}, {minlat}, {maxlon}, {maxlat}, 4326)
                )
            """

        if limit:
            query += f" LIMIT {limit}"

        df = pd.read_sql(query, conn)
        conn.close()

        print(f"Found {len(df)} buildings with volume data")
        return df

    def process_buildings(self, buildings_df):
        """Process all buildings and return results DataFrame"""
        results = []
        total = len(buildings_df)

        for idx, row in buildings_df.iterrows():
            print(f"Processing building {len(results) + 1}/{total}", end='\r')
            result = self.calculate_floor_area(row)
            results.append(result)

        print(f"\nProcessed {total} buildings")
        return pd.DataFrame(results)

    def write_results_to_db(self, results_df, table_name='public.buildings'):
        """
        Write calculated floor areas back to database.

        Updates:
        - area_floor_total_m2
        - area_floor_above_ground_m2
        - area_accuracy
        - floors_total
        - floors_above
        - floors_accuracy
        """
        print(f"\nWriting results to database table {table_name}...")

        conn = self.get_database_connection()
        cursor = conn.cursor()

        # Update rows (only successful calculations)
        successful = results_df[results_df['status'] == 'success']
        updated_count = 0

        for _, row in successful.iterrows():
            cursor.execute(f"""
                UPDATE {table_name}
                SET
                    area_floor_total_m2 = %s,
                    area_floor_above_ground_m2 = %s,
                    area_accuracy = %s,
                    floors_total = %s,
                    floors_above = %s,
                    floors_accuracy = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (
                row['area_floor_total_m2'],
                row['area_floor_above_ground_m2'],
                row['area_accuracy'],
                row['floors_total'],
                row['floors_above'],
                row['floors_accuracy'],
                row['id']
            ))
            updated_count += 1

        conn.commit()
        cursor.close()
        conn.close()

        print(f"Updated {updated_count} buildings in database")


def main():
    parser = argparse.ArgumentParser(
        description='Estimate building floor areas using volume, footprint, and GWR classification data'
    )
    parser.add_argument('db_connection',
                        help='PostgreSQL connection string (e.g., postgresql://user:pass@host:5432/db)')
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
                        help='Write results back to database')
    parser.add_argument('--table-name', default='public.buildings',
                        help='Table name (default: public.buildings)')
    parser.add_argument('--include-missing-volume', action='store_true',
                        help='Include buildings without volume data (will fail estimation)')

    args = parser.parse_args()

    # Validate that at least one output method is specified
    if not args.output and not args.write_to_db:
        print("Error: Must specify either --output for CSV export or --write-to-db for database update",
              file=sys.stderr)
        return 1

    # Initialize estimator
    try:
        estimator = BuildingFloorAreaEstimator(args.db_connection)
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        return 1

    # Load buildings
    try:
        buildings = estimator.load_buildings_from_db(
            table_name=args.table_name,
            building_ids=args.building_ids,
            bbox=args.bbox,
            limit=args.limit,
            only_with_volume=not args.include_missing_volume
        )
    except Exception as e:
        print(f"Error loading buildings: {e}", file=sys.stderr)
        return 1

    if len(buildings) == 0:
        print("No buildings to process")
        return 0

    # Process buildings
    results = estimator.process_buildings(buildings)

    # Save CSV if output file specified
    if args.output:
        # Select columns for CSV output
        output_cols = [
            'id', 'area_floor_total_m2', 'area_floor_above_ground_m2', 'area_accuracy',
            'floors_total', 'floors_above', 'floors_accuracy', 'status', 'error_message',
            '_height_mean_m', '_floor_height_used', '_schema_used', '_building_type'
        ]
        results[output_cols].to_csv(args.output, index=False)
        print(f"\nResults saved to: {args.output}")

    # Write to database if requested
    if args.write_to_db:
        try:
            estimator.write_results_to_db(results, table_name=args.table_name)
        except Exception as e:
            print(f"Error writing to database: {e}", file=sys.stderr)
            return 1

    # Print summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    successful = results[results['status'] == 'success']
    print(f"Successful: {len(successful)}/{len(results)}")

    if len(successful) > 0:
        print(f"\nFloor Area Statistics:")
        print(f"  Total floor area: {successful['area_floor_total_m2'].sum():,.0f} m²")
        print(f"  Average floor area: {successful['area_floor_total_m2'].mean():,.0f} m²")
        print(f"  Median floor area: {successful['area_floor_total_m2'].median():,.0f} m²")

        print(f"\nFloor Count Statistics:")
        print(f"  Average floors: {successful['floors_total'].mean():.1f}")
        print(f"  Max floors: {successful['floors_total'].max()}")

        print(f"\nAccuracy Distribution:")
        for acc, count in successful['area_accuracy'].value_counts().items():
            pct = count / len(successful) * 100
            print(f"  {acc}: {count} ({pct:.1f}%)")

        # Schema usage stats
        if '_schema_used' in successful.columns:
            print(f"\nClassification Schema Used:")
            for schema, count in successful['_schema_used'].value_counts().items():
                pct = count / len(successful) * 100
                print(f"  {schema}: {count} ({pct:.1f}%)")

    # Error breakdown
    errors = results[results['status'] != 'success']
    if len(errors) > 0:
        print(f"\nErrors ({len(errors)}):")
        for msg, count in errors['error_message'].value_counts().items():
            print(f"  {msg}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
