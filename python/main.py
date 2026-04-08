#!/usr/bin/env python3
"""
Swiss Building Volume & Area Estimator

Unified CLI that runs the full pipeline:
  Step 1 — Read building footprints           [footprints.py]
  Step 2 — Ensure required elevation tiles    [tile_fetcher.py]
  Step 3 — Aligned grid + volume + heights    [volume.py]
  Step 4 — GWR enrichment + floor areas       [area.py, optional]

Output is always a CSV file.
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from footprints import (
    load_footprints_from_file,
    load_footprints_from_av_with_egids,
    load_footprints_from_av_with_coordinates,
)
from volume import (
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_SKIPPED_PREFIX,
    STATUS_SUCCESS,
    TileIndex,
    append_warning,
    calculate_building_volume,
    make_empty_volume_result,
)
from tile_fetcher import ensure_tiles, tile_ids_from_bounds
from area import enrich_with_gwr, estimate_floor_area


# Columns where ``;``-joining sub-row values doesn't carry information —
# either because the value is the group key, the rolled-up status of the
# group, or because aggregation has its own dedicated handling below.
_AGGREGATE_PASS_THROUGH_COLS = frozenset({
    'input_id', 'input_egid_raw',
    'status_step1', 'status_step3', 'status_step4',
    'warnings',
})


def aggregate_by_input_id(results_df):
    """
    Collapse sub-rows that share an ``input_id`` into one output row each.

    A sub-row exists when a single CSV input row produced multiple Step 1
    matches — either the cell contained several EGIDs (separated by any of
    ``,`` ``/`` ``;`` or whitespace), or one EGID matched several AV
    polygons. The aggregate represents the BBL building **with every
    sub-building visible**:

    - For each value column where the sub-rows disagree, the output row
      contains a ``';'``-joined string of every sub-value in input order.
    - Where every sub-row agrees on a value (e.g. all sub-buildings share
      the same ``gkat``), the output keeps the scalar.
    - ``warnings`` from every sub-row are concatenated and an aggregation
      note is appended.
    - ``status_step3`` rolls up to ``'success'`` if any sub-row succeeded,
      otherwise the first sub-row's status.

    The point of the array form is **transparency**: a downstream user
    looking at one bbl_id row can see immediately that the EGID has 4 AV
    polygons or that the input cell contained 5 EGIDs, and can fix the
    source data accordingly. Sums would silently hide the multi-source
    nature of the row.

    Single-element groups pass through unchanged.
    """
    if 'input_id' not in results_df.columns or len(results_df) == 0:
        return results_df

    aggregated_rows = []
    for input_id, group in results_df.groupby('input_id', sort=False, dropna=False):
        if len(group) == 1:
            aggregated_rows.append(group.iloc[0].to_dict())
            continue
        aggregated_rows.append(_reduce_group(group))

    out = pd.DataFrame(aggregated_rows, columns=results_df.columns)

    # When some rows are aggregated (string arrays) and others aren't
    # (float scalars), the column becomes object dtype. Pandas then writes
    # integer-valued floats as "1234567.0" — ugly. Demote them to int so
    # the CSV stays clean. Strings (the array rows) pass through unchanged.
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].map(_demote_int_float)

    return out


def _demote_int_float(v):
    """Convert integer-valued floats to ints; pass everything else through."""
    if isinstance(v, float) and not pd.isna(v) and v.is_integer():
        return int(v)
    return v


def _format_sub_value(v):
    """Stringify one sub-row value for ``;``-joined arrays. Skips NaN."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _reduce_group(group):
    """Reduce one group of sub-rows (sharing input_id) into a single dict."""
    # Start from the first sub-row so the group key + pass-through columns
    # land naturally in the output.
    row = group.iloc[0].to_dict()

    for col in group.columns:
        if col in _AGGREGATE_PASS_THROUGH_COLS:
            continue

        sub_values = list(group[col])
        # If every sub-row agrees on the value, keep the scalar form so
        # downstream numeric ops still work for the homogeneous columns.
        # NaN comparisons need explicit handling.
        unique_repr = {_format_sub_value(v) for v in sub_values}
        unique_non_empty = {r for r in unique_repr if r != ''}
        if len(unique_non_empty) <= 1:
            # All sub-rows agree (or all are NaN). Keep the first sub-row's
            # value as the scalar representation.
            continue

        # Sub-rows differ → emit a ;-joined string of every sub-value.
        row[col] = '; '.join(_format_sub_value(v) for v in sub_values)

    # Status rollup: if any sub-row succeeded, the aggregate is success;
    # otherwise the first sub-row's status (for downstream filtering).
    if 'status_step3' in group.columns:
        successes = group['status_step3'] == STATUS_SUCCESS
        if successes.any():
            row['status_step3'] = STATUS_SUCCESS
        else:
            row['status_step3'] = group['status_step3'].iloc[0]

    # Concatenate warnings from every sub-row + an aggregation note.
    all_warnings = []
    for w in group['warnings']:
        if w and isinstance(w, str):
            for piece in w.split('; '):
                if piece and piece not in all_warnings:
                    all_warnings.append(piece)

    n_sub_rows = len(group)
    n_unique_egids = group['av_egid'].dropna().nunique() if 'av_egid' in group.columns else 0
    if n_unique_egids > 1:
        all_warnings.append(
            f'aggregated {n_sub_rows} sub-rows from {n_unique_egids} distinct EGIDs '
            f'(numeric columns are ;-joined arrays — fix the input CSV to one EGID per row)'
        )
    else:
        all_warnings.append(
            f'aggregated {n_sub_rows} AV polygons for one EGID '
            f'(numeric columns are ;-joined arrays — building is split across cadastral parcels)'
        )
    row['warnings'] = '; '.join(all_warnings)

    return row


def setup_logging(output_path):
    """Configure file + console logging. The log file lives next to the
    output CSV and shares its stem (so ``Gebäude_IN_20260408_1542.csv``
    pairs with ``Gebäude_IN_20260408_1542.log``). Idempotent if main()
    runs more than once in the same process (e.g. from a notebook or
    test runner)."""
    output_path = Path(output_path)
    log_dir = output_path.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{output_path.stem}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s"
    ))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.handlers.clear()  # avoid stacking handlers across repeat invocations
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

    # Input: building footprints. Three modes:
    #   --footprints only                       → all buildings in the AV file
    #   --footprints + --csv                    → EGID match (default for CSV input)
    #   --footprints + --csv --use-coordinates  → spatial join via lon/lat
    parser.add_argument('--footprints', required=True,
                        help='Geodata file with building footprints '
                             '(GeoPackage, Shapefile, or GeoJSON from Amtliche Vermessung).')
    parser.add_argument('--csv',
                        help='CSV input file. By default looks up buildings by `egid` '
                             '(columns: id, egid). With --use-coordinates, instead does a '
                             'spatial join via lon/lat (columns: id, lon, lat). '
                             'Comma- and semicolon-delimited CSVs both work.')
    parser.add_argument('--use-coordinates', action='store_true',
                        help='Match buildings via lon/lat spatial join instead of EGID. '
                             'Required only for buildings that have no EGID assigned in '
                             'the cadastral data; EGID match is faster and unambiguous.')

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
                        help='Output CSV file path. A YYYYMMDD_HHMM timestamp '
                             'is appended to the stem. If omitted, the output '
                             'is dropped next to --csv (named after its stem) '
                             'when --csv is given, otherwise into '
                             'data/output/result_<timestamp>.csv. The log '
                             'file is written next to the CSV with a matching '
                             'name (same stem, .log extension).')

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

    # ── Output path & timestamp ───────────────────────────────────────────
    # YYYYMMDD_HHMM matches the web app's export naming. The same timestamp
    # is reused below for the log file (via setup_logging) so the .csv and
    # .log always agree on the suffix.
    #
    # Resolution order:
    #   1. --output explicitly set: append timestamp to user-provided path
    #   2. --csv given: drop output next to the CSV, named after its stem
    #   3. neither: fall back to data/output/result_<timestamp>.csv
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    if args.output:
        p = Path(args.output)
        args.output = str(p.parent / f"{p.stem}_{timestamp}{p.suffix}")
    elif args.csv:
        csv_path = Path(args.csv)
        args.output = str(csv_path.parent / f"{csv_path.stem}_{timestamp}.csv")
    else:
        args.output = str(Path("data/output") / f"result_{timestamp}.csv")

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

    if args.use_coordinates and not args.csv:
        log.error("--use-coordinates requires --csv")
        return 1

    try:
        if args.csv and args.use_coordinates:
            log.info("Mode: AV + CSV (lon/lat spatial join)")
            buildings = load_footprints_from_av_with_coordinates(
                args.footprints, args.csv, limit=args.limit,
            )
        elif args.csv:
            log.info("Mode: AV + CSV (EGID match)")
            buildings = load_footprints_from_av_with_egids(
                args.footprints, args.csv, limit=args.limit,
            )
        else:
            log.info("Mode: all buildings from AV file")
            buildings = load_footprints_from_file(
                args.footprints, bbox=args.bbox, limit=args.limit,
            )
    except (FileNotFoundError, ValueError) as e:
        log.error(f"Error loading input: {e}")
        return 1

    total = len(buildings)
    with_geometry = buildings[buildings['status_step1'] == STATUS_OK]
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
        t_fetch = time.monotonic()
        stats = ensure_tiles(all_tile_ids, alti3d_dir, surface3d_dir)
        fetch_elapsed = time.monotonic() - t_fetch

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
        t_start = time.monotonic()

        # Columns the result dict already populates — never let an input
        # column with the same name overwrite a computed value. `warnings`
        # is owned by the result but is *appended to*, not overwritten,
        # so we handle it explicitly below. `status_step1` is allowed
        # through (the input column carries the Step 1 outcome verbatim).
        reserved_input_cols = {'id', 'geometry', 'warnings'}

        for i, (_, row) in enumerate(buildings.iterrows()):
            step1_warnings = row.get('warnings') or ''

            if row['status_step1'] != STATUS_OK:
                result = make_empty_volume_result(
                    av_egid=row.get('av_egid'),
                    fid=row.get('fid'),
                    area_official_m2=row.get('area_official_m2'),
                    status_step3=f"{STATUS_SKIPPED_PREFIX}{row['status_step1']}",
                    warnings=step1_warnings,
                )
            else:
                result = calculate_building_volume(
                    polygon=row.geometry,
                    tile_index=tile_index,
                    av_egid=row.get('av_egid'),
                    fid=row.get('fid'),
                    area_official_m2=row.get('area_official_m2'),
                )
                # Carry Step 1 warnings into the success path too.
                if step1_warnings:
                    append_warning(result, step1_warnings)

            # Preserve extra input columns (e.g. input_id) — but never
            # overwrite a key the result dict already owns.
            for col in buildings.columns:
                if col in reserved_input_cols or col in result:
                    continue
                result[col] = row[col]

            results.append(result)

            # Progress
            if (i + 1) % 100 == 0 or (i + 1) == total:
                elapsed = time.monotonic() - t_start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (total - i - 1) / rate if rate > 0 else 0
                eta_m, eta_s = divmod(int(eta), 60)
                log.info(f"  [{i+1}/{total}] {(i+1)/total*100:.0f}%  "
                         f"{rate:.1f} bldg/s  ETA: {eta_m}m {eta_s:02d}s")

    finally:
        tile_index.close()

    elapsed = time.monotonic() - t_start
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
            if row['status_step3'] == STATUS_SUCCESS:
                area_results.append(estimate_floor_area(row.to_dict()))
            else:
                result = row.to_dict()
                result['status_step4'] = STATUS_SKIPPED
                area_results.append(result)

        results_df = pd.DataFrame(area_results)

    # ── Aggregate sub-rows by input_id ────────────────────────────────────
    # Multi-EGID inputs and multi-polygon AV matches both produce more
    # than one intermediate row sharing the same input_id. Collapse them
    # to one output row per input_id; multi-source columns become
    # ;-joined arrays so the user can see every sub-building's value
    # and improve the input data quality at the source.
    n_before = len(results_df)
    results_df = aggregate_by_input_id(results_df)
    n_after = len(results_df)
    if n_before != n_after:
        log.info(f"\nAggregated {n_before} sub-rows -> {n_after} output rows by input_id")

    # ── Output CSV ────────────────────────────────────────────────────────
    # Reorder columns: identifiers first
    id_cols = [
        "input_id", "input_egid", "input_lon", "input_lat",
        "av_egid", "egid", "fid",
    ]
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

    successful = results_df[results_df['status_step3'] == STATUS_SUCCESS]
    log.info(f"Successful: {len(successful)}/{len(results_df)}")

    if len(successful) > 0:
        # After aggregate_by_input_id, multi-source rows have ;-joined
        # string values in the numeric columns. Coerce to numeric so the
        # array rows become NaN and don't crash .sum() — then report the
        # number we excluded separately so the user knows the total is
        # only over the single-source rows.
        vol_numeric = pd.to_numeric(successful['volume_above_ground_m3'], errors='coerce')
        n_array_rows = int(vol_numeric.isna().sum() - successful['volume_above_ground_m3'].isna().sum())
        n_summable = int(vol_numeric.notna().sum())

        log.info(f"\nVolume:")
        log.info(f"  Total:   {vol_numeric.sum():,.0f} m³  (across {n_summable} single-source rows)")
        log.info(f"  Average: {vol_numeric.mean():,.0f} m³")
        if n_array_rows > 0:
            log.info(f"  Note:    {n_array_rows} multi-source rows excluded from sum "
                     f"(see ;-joined values in CSV)")

        if args.estimate_area and 'area_floor_total_m2' in successful.columns:
            area_numeric = pd.to_numeric(successful['area_floor_total_m2'], errors='coerce')
            floors_numeric = pd.to_numeric(successful['floors_estimated'], errors='coerce')
            has_area = area_numeric.notna()
            if has_area.any():
                log.info(f"\nFloor Area:")
                log.info(f"  Total:   {area_numeric.sum():,.0f} m²  (across {int(has_area.sum())} single-source rows)")
                log.info(f"  Average: {area_numeric[has_area].mean():,.0f} m²")
                log.info(f"  Avg floors: {floors_numeric[has_area].mean():.1f}")

    log.info("\nStatus (Step 3):")
    for status, count in results_df['status_step3'].value_counts().items():
        log.info(f"  {status}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
