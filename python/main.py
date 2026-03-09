#!/usr/bin/env python3
"""
Swiss Building Volume & Area Estimator

Unified CLI that runs the full pipeline:
  Step 1 — Read building footprints from geodata file or CSV coordinates
  Step 2 — Create aligned 1×1m grid (grid.py)
  Step 3 — Sample elevations & calculate volume (volume.py)
  Step 4 — Estimate floor areas using GWR classification (optional, off by default)

Output is always a CSV file.
"""

import argparse
import sys
from pathlib import Path
import pandas as pd

from footprints import load_footprints_from_file, load_coordinates_from_csv
from volume import TileIndex, calculate_building_volume
from gwr import enrich_with_gwr
from area import estimate_floor_area


def main():
    parser = argparse.ArgumentParser(
        description='Swiss Building Volume & Area Estimator — '
                    'estimates building volumes and floor areas from elevation models'
    )

    # Input: building footprints
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--footprints',
                             help='Geodata file with building footprints '
                                  '(GeoPackage, Shapefile, or GeoJSON from Amtliche Vermessung)')
    input_group.add_argument('--coordinates',
                             help='CSV file with WGS84 coordinates (columns: lon, lat)')

    # Input: elevation tiles
    parser.add_argument('--alti3d', required=True,
                        help='Directory containing swissALTI3D GeoTIFF tiles')
    parser.add_argument('--surface3d', required=True,
                        help='Directory containing swissSURFACE3D GeoTIFF tiles')

    # Output
    parser.add_argument('-o', '--output', required=True,
                        help='Output CSV file path')

    # Filters
    parser.add_argument('-l', '--limit', type=int,
                        help='Limit number of buildings to process')
    parser.add_argument('-b', '--bbox', nargs=4, type=float,
                        metavar=('MINLON', 'MINLAT', 'MAXLON', 'MAXLAT'),
                        help='Bounding box filter in WGS84 (only for --footprints)')

    # Step 4: Area estimation (off by default)
    parser.add_argument('--estimate-area', action='store_true',
                        help='Enable Step 4: estimate floor areas using GWR classification '
                             '(requires EGID in input data)')
    parser.add_argument('--gwr-csv',
                        help='Path to GWR CSV bulk download (from housing-stat.ch). '
                             'If omitted with --estimate-area, uses swisstopo API per building.')

    args = parser.parse_args()

    # Validate elevation directories
    if not Path(args.alti3d).is_dir():
        print(f"Error: ALTI3D directory not found: {args.alti3d}", file=sys.stderr)
        return 1

    if not Path(args.surface3d).is_dir():
        print(f"Error: SURFACE3D directory not found: {args.surface3d}", file=sys.stderr)
        return 1

    # ── Step 1: Load building footprints ──────────────────────────────────
    try:
        if args.footprints:
            buildings = load_footprints_from_file(
                args.footprints,
                bbox=args.bbox,
                limit=args.limit,
            )
        else:
            buildings = load_coordinates_from_csv(args.coordinates)
            if args.limit:
                buildings = buildings.head(args.limit)
    except Exception as e:
        print(f"Error loading input: {e}", file=sys.stderr)
        return 1

    if len(buildings) == 0:
        print("No buildings to process")
        return 0

    # ── Steps 2 & 3: Grid + Volume ───────────────────────────────────────
    tile_index = TileIndex(args.alti3d, args.surface3d)

    results = []
    total = len(buildings)
    for i, (_, row) in enumerate(buildings.iterrows()):
        print(f"Processing building {i + 1}/{total}", end='\r', flush=True)
        result = calculate_building_volume(
            polygon=row.geometry,
            tile_index=tile_index,
            egid=row.get('egid'),
            fid=row.get('fid'),
            area_official_m2=row.get('area_official_m2'),
        )
        results.append(result)

    tile_index.close()
    print(f"\nProcessed {total} buildings")

    results_df = pd.DataFrame(results)

    # ── Step 4 (optional): GWR enrichment + Area estimation ──────────────
    if args.estimate_area:
        print("\nStep 4: Estimating floor areas...")

        # Enrich with GWR classification
        results_df = enrich_with_gwr(results_df, gwr_csv_path=args.gwr_csv)

        # Estimate floor areas for successful volume calculations
        area_results = []
        for _, row in results_df.iterrows():
            if row['status'] == 'success':
                area_results.append(estimate_floor_area(row.to_dict()))
            else:
                area_results.append(row.to_dict())

        results_df = pd.DataFrame(area_results)

    # ── Output CSV ────────────────────────────────────────────────────────
    results_df.to_csv(args.output, index=False)
    print(f"\nResults saved to: {args.output}")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    successful = results_df[results_df['status'] == 'success']
    print(f"Successful: {len(successful)}/{len(results_df)}")

    if len(successful) > 0:
        print(f"\nVolume:")
        print(f"  Total:   {successful['volume_above_ground_m3'].sum():,.0f} m³")
        print(f"  Average: {successful['volume_above_ground_m3'].mean():,.0f} m³")

        if args.estimate_area and 'area_floor_total_m2' in successful.columns:
            has_area = successful['area_floor_total_m2'].notna()
            if has_area.any():
                area_data = successful[has_area]
                print(f"\nFloor Area:")
                print(f"  Total:   {area_data['area_floor_total_m2'].sum():,.0f} m²")
                print(f"  Average: {area_data['area_floor_total_m2'].mean():,.0f} m²")
                print(f"  Avg floors: {area_data['floors_estimated'].mean():.1f}")

                print(f"\nAccuracy:")
                for acc, count in area_data['area_accuracy'].value_counts().items():
                    pct = count / len(area_data) * 100
                    print(f"  {acc}: {count} ({pct:.1f}%)")

    # Status breakdown
    print("\nStatus:")
    for status, count in results_df['status'].value_counts().items():
        print(f"  {status}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
