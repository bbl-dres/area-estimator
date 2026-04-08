#!/usr/bin/env python3
"""
Green Roof Estimator from swissIMAGE-RS multispectral imagery.

For each building footprint in the input file, computes NDVI from a directory
of 4-band swissIMAGE-RS GeoTIFFs and estimates the green-roof area and the
green-coverage percentage. Output is a CSV with one row per building.

Algorithm:
    1. Index all GeoTIFFs in --rs-dir into an STRtree (bbox lookup)
    2. For each footprint:
       a. Find the first intersecting raster (MVP — see Limitations in README)
       b. Mask/clip the raster to the footprint
       c. Compute NDVI = (NIR - Red) / (NIR + Red), with hardcoded
          band assignment: Band 1 = Red, Band 4 = NIR
       d. Count vegetation pixels (NDVI > --ndvi-threshold)
       e. Multiply by pixel area to get green area in m²

Usage:
    python main.py footprints.gpkg \\
        --rs-dir D:/SwissRS \\
        --output green_roof.csv \\
        --layer Building_solid

Input formats accepted: GeoPackage (.gpkg), Shapefile (.shp), GeoJSON (.geojson),
ESRI File Geodatabase (.gdb). Footprints must be in LV95 (EPSG:2056) — the same
CRS as the swissIMAGE-RS tiles. The script does NOT reproject.

For details on band assignment, threshold tuning, and known limitations
(single-tile-per-building MVP shortcut, fixed Band 1/4 mapping, etc.) see
README.md.
"""

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Iterator, Optional, Tuple

import fiona
import shapely.geometry
from shapely.geometry.base import BaseGeometry

from green_roof import GreenRoofAnalyzer

log = logging.getLogger("green-roof")


def load_footprints(
    input_path: Path,
    layer: Optional[str] = None,
) -> Iterator[Tuple[str, BaseGeometry]]:
    """
    Yield ``(id, geometry)`` tuples from the input file.

    The id field is picked from the first available of: ``EGID``, ``UUID``,
    ``id``, then the feature's own id, then a generated sequential index.
    Geometry is converted to a shapely geometry in whatever CRS the input
    is in (no reprojection — must match the raster CRS).
    """
    suffix = input_path.suffix.lower()
    if suffix not in (".gpkg", ".shp", ".geojson", ".gdb"):
        raise ValueError(f"Unsupported input format: {suffix}")

    with fiona.open(str(input_path), layer=layer) as src:
        log.info("Source CRS: %s, layer: %s, count: %d", src.crs, layer or "(default)", len(src))
        for i, feature in enumerate(src):
            geom_dict = feature["geometry"]
            if geom_dict is None:
                log.debug("[%d] empty geometry, skipping", i)
                continue
            try:
                geom = shapely.geometry.shape(geom_dict)
            except Exception as e:
                log.warning("[%d] geometry parse failed: %s", i, e)
                continue

            props = feature["properties"] or {}
            obj_id = (
                props.get("EGID")
                or props.get("UUID")
                or props.get("id")
                or feature.get("id")
                or f"row_{i}"
            )
            yield str(obj_id), geom


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Estimate green roof coverage per building from swissIMAGE-RS multispectral imagery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py buildings.gpkg --rs-dir D:/SwissRS --output green.csv\n"
            "  python main.py SWISSBUILDINGS3D.gdb --layer Building_solid \\\n"
            "                 --rs-dir D:/SwissRS --output green.csv --limit 100\n"
        ),
    )
    p.add_argument("input", type=Path, help="Footprint source (GPKG, SHP, GDB, GeoJSON)")
    p.add_argument("--rs-dir", type=Path, required=True, help="Directory containing swissIMAGE-RS GeoTIFFs")
    p.add_argument("--output", type=Path, required=True, help="Output CSV path")
    p.add_argument("--layer", help="Layer name (required for GDB; optional for GPKG)")
    p.add_argument(
        "--ndvi-threshold", type=float, default=0.2,
        help="Pixels with NDVI > this count as vegetation (default 0.2)",
    )
    p.add_argument("--limit", type=int, help="Stop after this many footprints")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if not args.rs_dir.exists():
        log.error("RS directory not found: %s", args.rs_dir)
        return 1
    if not args.input.exists():
        log.error("Input file not found: %s", args.input)
        return 1

    log.info("Indexing rasters in %s ...", args.rs_dir)
    analyzer = GreenRoofAnalyzer(str(args.rs_dir), ndvi_threshold=args.ndvi_threshold)

    bounds = analyzer.get_coverage_bounds()
    if bounds:
        log.info(
            "RS coverage bounds (LV95): X=[%.0f, %.0f], Y=[%.0f, %.0f]",
            bounds[0], bounds[2], bounds[1], bounds[3],
        )
    else:
        log.warning("No raster bounds available — every footprint will be reported as no_coverage")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    n_analyzed = 0
    n_no_coverage = 0
    n_failed = 0
    rows = []

    log.info("Processing footprints from %s ...", args.input)
    for i, (obj_id, geom) in enumerate(load_footprints(args.input, layer=args.layer)):
        if args.limit is not None and i >= args.limit:
            break
        try:
            result = analyzer.calculate_green_area(geom)
        except Exception as e:
            n_failed += 1
            log.error("[%s] failed: %s", obj_id, e)
            continue

        rows.append({"id": obj_id, **result})
        status = result.get("green_roof_status")
        if status == "analyzed":
            n_analyzed += 1
            log.info(
                "[%s] %.0f m² green (%.1f%%)  ndvi_mean=%.2f  ndvi_max=%.2f",
                obj_id,
                result["green_roof_area_m2"],
                result["green_roof_percentage"],
                result["ndvi_mean"],
                result["ndvi_max"],
            )
        elif status == "no_coverage":
            n_no_coverage += 1
            log.debug("[%s] no RS coverage", obj_id)
        else:
            log.debug("[%s] status=%s", obj_id, status)

    if rows:
        # Stable column order: id first, then status, then numeric metrics
        preferred = [
            "id",
            "green_roof_status",
            "green_roof_area_m2",
            "green_roof_percentage",
            "ndvi_mean",
            "ndvi_max",
            "error",
        ]
        all_keys = {k for row in rows for k in row.keys()}
        ordered = [k for k in preferred if k in all_keys] + sorted(all_keys - set(preferred))
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ordered)
            writer.writeheader()
            writer.writerows(rows)

    log.info(
        "Done — %d analyzed, %d no coverage, %d failed → %s",
        n_analyzed, n_no_coverage, n_failed, args.output.resolve(),
    )
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
