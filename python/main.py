#!/usr/bin/env python3
"""
Swiss Building Volume & Area Estimator

Unified CLI that runs the full pipeline:
  Step 1 — Read building footprints (geodata file or CSV coordinates)
  Step 2 — Ensure all required elevation tiles are available (download if --auto-fetch)
  Step 3 — Create aligned 1×1m grid + sample elevations + calculate volume
  Step 4 — Estimate floor areas using GWR classification (optional, off by default)

Output is always a CSV file.
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from footprints import load_footprints_from_file, load_coordinates_from_csv
from volume import TileIndex, calculate_building_volume
from tile_fetcher import ensure_tiles, tile_ids_from_bounds
from gwr import enrich_with_gwr
from area import estimate_floor_area


def setup_logging(output_path):
    """Configure file + console logging. Log goes next to the output CSV."""
    log_dir = Path(output_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"run_{timestamp}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s"
    ))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Suppress noisy third-party loggers
    for noisy in ('urllib3', 'requests', 'rasterio', 'fiona', 'pyproj'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return log_file


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

    # Auto-fetch missing tiles
    parser.add_argument('--auto-fetch', action='store_true',
                        help='Automatically download missing elevation tiles from swisstopo')

    # Output
    parser.add_argument('-o', '--output',
                        help='Output CSV file path (default: data/output/result_<timestamp>.csv)')

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

    # Add timestamp to output filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not args.output:
        args.output = str(Path("data/output") / f"result_{timestamp}.csv")
    else:
        p = Path(args.output)
        args.output = str(p.parent / f"{p.stem}_{timestamp}{p.suffix}")

    # ── Logging ────────────────────────────────────────────────────────────
    log_file = setup_logging(args.output)
    log = logging.getLogger("main")
    log.info(f"Log file: {log_file}")

    # ── Validate inputs ────────────────────────────────────────────────────
    alti3d_dir = Path(args.alti3d)
    surface3d_dir = Path(args.surface3d)

    if not args.auto_fetch:
        if not alti3d_dir.is_dir():
            log.error(f"ALTI3D directory not found: {args.alti3d}")
            return 1
        if not surface3d_dir.is_dir():
            log.error(f"SURFACE3D directory not found: {args.surface3d}")
            return 1
    else:
        alti3d_dir.mkdir(parents=True, exist_ok=True)
        surface3d_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Load building footprints ──────────────────────────────────
    log.info("=" * 50)
    log.info("STEP 1: Loading building footprints")
    log.info("=" * 50)

    try:
        if args.footprints:
            buildings = load_footprints_from_file(
                args.footprints, bbox=args.bbox, limit=args.limit,
            )
        else:
            buildings = load_coordinates_from_csv(args.coordinates, limit=args.limit)
    except Exception as e:
        log.error(f"Error loading input: {e}")
        return 1

    total = len(buildings)
    with_geometry = buildings[buildings['status_step1'] == 'ok']
    log.info(f"  Total features:  {total}")
    log.info(f"  With footprint:  {len(with_geometry)}")
    log.info(f"  Without:         {total - len(with_geometry)}")

    if len(with_geometry) == 0:
        log.info("No buildings with footprints to process")
        return 0

    # ── Step 2: Ensure elevation tiles ────────────────────────────────────
    log.info("")
    log.info("=" * 50)
    log.info("STEP 2: Checking elevation tiles")
    log.info("=" * 50)

    # Collect all required tile IDs from all footprints
    all_tile_ids = set()
    for _, row in with_geometry.iterrows():
        all_tile_ids |= tile_ids_from_bounds(row.geometry.bounds)

    log.info(f"  Required tiles: {len(all_tile_ids)}")

    if args.auto_fetch:
        log.info(f"  Auto-fetching missing tiles from swisstopo...")
        t_fetch = time.time()
        stats = ensure_tiles(all_tile_ids, alti3d_dir, surface3d_dir)
        fetch_elapsed = time.time() - t_fetch

        log.info(f"  ALTI3D:    {stats['alti3d_ok']} ok, {stats['alti3d_missing']} missing")
        log.info(f"  SURFACE3D: {stats['surface3d_ok']} ok, {stats['surface3d_missing']} missing")
        log.info(f"  Fetch time: {fetch_elapsed:.0f}s")
    else:
        log.info(f"  (auto-fetch disabled — using local tiles only)")

    # ── Step 3: Grid + Volume ─────────────────────────────────────────────
    log.info("")
    log.info("=" * 50)
    log.info("STEP 3: Calculating building volumes")
    log.info("=" * 50)

    tile_index = TileIndex(str(alti3d_dir), str(surface3d_dir))

    try:
        results = []
        t_start = time.time()

        for i, (_, row) in enumerate(buildings.iterrows()):
            if row['status_step1'] != 'ok':
                # No footprint — carry forward metadata with empty volume
                result = {
                    'av_egid': row.get('av_egid'), 'fid': row.get('fid'),
                    'area_footprint_m2': None, 'area_official_m2': None,
                    'volume_above_ground_m3': None, 'elevation_base_m': None,
                    'elevation_roof_base_m': None, 'height_mean_m': None,
                    'height_max_m': None, 'height_minimal_m': None,
                    'grid_points_count': None, 'status_step3': 'skipped',
                }
            else:
                result = calculate_building_volume(
                    polygon=row.geometry,
                    tile_index=tile_index,
                    av_egid=row.get('av_egid'),
                    fid=row.get('fid'),
                    area_official_m2=row['area_official_m2'],
                )

            # Preserve extra columns from input (e.g. input_id)
            for col in buildings.columns:
                if col not in ('id', 'av_egid', 'fid', 'area_official_m2', 'geometry', 'status_step1'):
                    result[col] = row[col]

            results.append(result)

            # Progress
            if (i + 1) % 100 == 0 or (i + 1) == total:
                elapsed = time.time() - t_start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (total - i - 1) / rate if rate > 0 else 0
                eta_m, eta_s = divmod(int(eta), 60)
                log.info(f"  [{i+1}/{total}] {(i+1)/total*100:.0f}%  "
                         f"{rate:.1f} bldg/s  ETA: {eta_m}m {eta_s:02d}s")

    finally:
        tile_index.close()

    elapsed = time.time() - t_start
    log.info(f"\n  Processed {len(results)} buildings in {elapsed:.0f}s")

    results_df = pd.DataFrame(results)

    # ── Step 4 (optional): GWR enrichment + Area estimation ──────────────
    if args.estimate_area:
        log.info("")
        log.info("=" * 50)
        log.info("STEP 4: Estimating floor areas")
        log.info("=" * 50)

        results_df = enrich_with_gwr(results_df, gwr_csv_path=args.gwr_csv)

        area_results = []
        for _, row in results_df.iterrows():
            if row['status_step3'] == 'success':
                area_results.append(estimate_floor_area(row.to_dict()))
            else:
                result = row.to_dict()
                result['status_step4'] = 'skipped'
                area_results.append(result)

        results_df = pd.DataFrame(area_results)

    # ── Output CSV ────────────────────────────────────────────────────────
    # Reorder columns: identifiers first
    id_cols = ["input_id", "input_egid", "input_lon", "input_lat", "av_egid", "fid"]
    existing_id_cols = [c for c in id_cols if c in results_df.columns]
    other_cols = [c for c in results_df.columns if c not in id_cols]
    results_df = results_df[existing_id_cols + other_cols]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(output_path, index=False)
    log.info(f"\nResults saved to: {output_path.resolve()}")

    # ── Summary ───────────────────────────────────────────────────────────
    log.info("")
    log.info("=" * 50)
    log.info("SUMMARY")
    log.info("=" * 50)

    successful = results_df[results_df['status_step3'] == 'success']
    log.info(f"Successful: {len(successful)}/{len(results_df)}")

    if len(successful) > 0:
        log.info(f"\nVolume:")
        log.info(f"  Total:   {successful['volume_above_ground_m3'].sum():,.0f} m³")
        log.info(f"  Average: {successful['volume_above_ground_m3'].mean():,.0f} m³")

        if args.estimate_area and 'area_floor_total_m2' in successful.columns:
            has_area = successful['area_floor_total_m2'].notna()
            if has_area.any():
                area_data = successful[has_area]
                log.info(f"\nFloor Area:")
                log.info(f"  Total:   {area_data['area_floor_total_m2'].sum():,.0f} m²")
                log.info(f"  Average: {area_data['area_floor_total_m2'].mean():,.0f} m²")
                log.info(f"  Avg floors: {area_data['floors_estimated'].mean():.1f}")

    log.info("\nStatus (Step 3):")
    for status, count in results_df['status_step3'].value_counts().items():
        log.info(f"  {status}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
