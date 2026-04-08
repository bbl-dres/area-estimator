#!/usr/bin/env python3
"""
Tile Fetcher — Download missing swisstopo GeoTIFF tiles on demand.

Given a tile ID (e.g. "2601-1204"), checks local directories first.
If missing, downloads from swisstopo's data distribution service.

Supports both swissALTI3D (DTM) and swissSURFACE3D-Raster (DSM).
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Union

import requests

log = logging.getLogger("tile_fetcher")

# swisstopo COG URL patterns (year varies per tile)
ALTI3D_URL = (
    "https://data.geo.admin.ch/ch.swisstopo.swissalti3d/"
    "swissalti3d_{year}_{tile}/swissalti3d_{year}_{tile}_0.5_2056_5728.tif"
)
SURFACE3D_URL = (
    "https://data.geo.admin.ch/ch.swisstopo.swisssurface3d-raster/"
    "swisssurface3d-raster_{year}_{tile}/swisssurface3d-raster_{year}_{tile}_0.5_2056_5728.tif"
)

YEARS_TO_TRY = range(datetime.now().year, 2016, -1)
CHUNK_SIZE = 64 * 1024  # 64 KB
DOWNLOAD_TIMEOUT = 300


def tile_ids_from_bounds(
    bounds: tuple[float, float, float, float],
) -> set[str]:
    """Get set of tile IDs covering a bounding box in LV95 coordinates."""
    minx, miny, maxx, maxy = bounds
    tile_ids = set()
    for tx in range(int(minx / 1000), int(maxx / 1000) + 1):
        for ty in range(int(miny / 1000), int(maxy / 1000) + 1):
            tile_ids.add(f"{tx:04d}-{ty:04d}")
    return tile_ids


def _download_tile(
    tile_id: str,
    url_template: str,
    output_dir: Path,
    label: str,
) -> bool:
    """
    Download a single tile if not already present locally.

    Returns True if tile is available (already local or downloaded),
    False if tile could not be found on server.
    """
    existing = list(output_dir.glob(f"*_{tile_id}_*.tif"))
    if existing:
        log.debug("%s %s: already local", label, tile_id)
        return True

    for year in YEARS_TO_TRY:
        url = url_template.format(year=year, tile=tile_id)
        try:
            resp = requests.head(url, timeout=10)
            if resp.status_code != 200:
                continue

            size_mb = int(resp.headers.get("content-length", 0)) / 1024 / 1024
            filename = url.rsplit("/", 1)[-1]
            dest = output_dir / filename
            tmp = dest.with_suffix(dest.suffix + ".tmp")

            log.debug("%s %s: downloading %.1f MB (year=%s)", label, tile_id, size_mb, year)
            t0 = time.monotonic()

            resp = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(CHUNK_SIZE):
                    f.write(chunk)
            tmp.replace(dest)

            elapsed = max(time.monotonic() - t0, 1e-6)  # avoid /0 on cached fast paths
            log.debug("%s %s: done (%.0fs, %.1f MB/s)", label, tile_id, elapsed, size_mb / elapsed)
            return True

        except requests.RequestException as e:
            log.debug("%s %s: error for year %s: %s", label, tile_id, year, e)
            continue

    log.warning(f"{label} {tile_id}: NOT FOUND on server")
    return False


def ensure_tiles(
    tile_ids: Iterable[str],
    alti3d_dir: Union[str, Path],
    surface3d_dir: Union[str, Path],
) -> dict[str, int]:
    """
    Ensure all required tiles are available locally, downloading any that are missing.

    Args:
        tile_ids: Set of tile IDs (e.g. {"2601-1204", "2602-1195"})
        alti3d_dir: Path to swissALTI3D tile directory
        surface3d_dir: Path to swissSURFACE3D-Raster tile directory

    Returns:
        dict with counts: {"alti3d_ok", "surface3d_ok", "alti3d_missing", "surface3d_missing"}
    """
    alti3d_dir = Path(alti3d_dir)
    surface3d_dir = Path(surface3d_dir)
    alti3d_dir.mkdir(parents=True, exist_ok=True)
    surface3d_dir.mkdir(parents=True, exist_ok=True)

    stats = {"alti3d_ok": 0, "surface3d_ok": 0, "alti3d_missing": 0, "surface3d_missing": 0}
    sorted_ids = sorted(tile_ids)
    total = len(sorted_ids)
    t_start = time.monotonic()

    for i, tile_id in enumerate(sorted_ids):
        if _download_tile(tile_id, ALTI3D_URL, alti3d_dir, "ALTI3D"):
            stats["alti3d_ok"] += 1
        else:
            stats["alti3d_missing"] += 1

        if _download_tile(tile_id, SURFACE3D_URL, surface3d_dir, "SURF3D"):
            stats["surface3d_ok"] += 1
        else:
            stats["surface3d_missing"] += 1

        # Progress every 10 tiles or at end
        if (i + 1) % 10 == 0 or (i + 1) == total:
            elapsed = time.monotonic() - t_start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total - i - 1) / rate if rate > 0 else 0
            eta_m, eta_s = divmod(int(eta), 60)
            log.info(f"  Tiles: [{i+1}/{total}] {(i+1)/total*100:.0f}%  "
                     f"ETA: {eta_m}m {eta_s:02d}s")

    return stats
