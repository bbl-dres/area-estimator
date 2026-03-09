#!/usr/bin/env python3
"""
Swisstopo GeoTIFF Tile Downloader

Batch downloads elevation model tiles (swissALTI3D / swissSURFACE3D) from
swisstopo's data distribution service using a CSV file of URLs.

Features:
- Async downloads with configurable concurrency
- Automatic retry with exponential backoff (swisstopo often aborts)
- Skip existing files (by size comparison with HTTP Content-Length)
- Remove local files not listed in the CSV (--cleanup)
- Detailed log file for every run
- Resume-friendly: re-run safely at any time

Usage:
    python download_tiles.py URL_CSV OUTPUT_DIR [options]

Example:
    python download_tiles.py \
        "D:/SwissAlti3D/ch.swisstopo.swissalti3d-686PSzUp.csv" \
        "D:/SwissAlti3D" \
        --workers 8 --cleanup
"""

import argparse
import asyncio
import hashlib
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import aiohttp

# Defaults
DEFAULT_WORKERS = 4
DEFAULT_RETRIES = 5
DEFAULT_TIMEOUT = 300  # seconds per request
BACKOFF_BASE = 5       # seconds, doubles each retry
CHUNK_SIZE = 1024 * 64  # 64 KB read chunks


def setup_logging(output_dir):
    """Configure file + console logging. Returns the log file path."""
    log_dir = Path(output_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"download_{timestamp}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s"
    ))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("tile_dl")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return log_file


def parse_csv(csv_path):
    """Read URL list from CSV (one URL per line, no header)."""
    urls = []
    with open(csv_path, "r", encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url and url.startswith("http"):
                urls.append(url)
    return urls


def filename_from_url(url):
    """Extract filename from a swisstopo download URL."""
    return url.rsplit("/", 1)[-1]


async def download_one(session, url, dest_path, retries, log):
    """
    Download a single file with retry + exponential backoff.

    Downloads to a .tmp file first, then renames on success to avoid
    leaving partial files.
    """
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    for attempt in range(1, retries + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT, sock_read=120)
            async with session.get(url, timeout=timeout) as resp:
                if resp.status != 200:
                    log.warning(f"HTTP {resp.status} for {dest_path.name} (attempt {attempt})")
                    if attempt < retries:
                        await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue

                expected_size = resp.content_length

                # Skip if local file matches expected size
                if dest_path.exists() and expected_size:
                    local_size = dest_path.stat().st_size
                    if local_size == expected_size:
                        log.debug(f"SKIP  {dest_path.name} (size match: {local_size})")
                        return "skipped"

                # Stream to temp file
                downloaded = 0
                with open(tmp_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                        f.write(chunk)
                        downloaded += len(chunk)

                # Verify size
                if expected_size and downloaded != expected_size:
                    log.warning(
                        f"Size mismatch for {dest_path.name}: "
                        f"got {downloaded}, expected {expected_size} (attempt {attempt})"
                    )
                    tmp_path.unlink(missing_ok=True)
                    if attempt < retries:
                        await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue

                # Atomic-ish rename
                tmp_path.replace(dest_path)
                log.debug(f"OK    {dest_path.name} ({downloaded:,} bytes)")
                return "downloaded"

        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            log.warning(f"Error downloading {dest_path.name}: {e} (attempt {attempt})")
            tmp_path.unlink(missing_ok=True)
            if attempt < retries:
                await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))

    log.error(f"FAILED {dest_path.name} after {retries} attempts")
    return "failed"


async def download_batch(urls, output_dir, workers, retries, log):
    """Download all URLs with bounded concurrency."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(workers)
    stats = {"downloaded": 0, "skipped": 0, "failed": 0}
    total = len(urls)
    completed = 0

    async def bounded_download(session, url):
        nonlocal completed
        filename = filename_from_url(url)
        dest = output_dir / filename

        async with sem:
            result = await download_one(session, url, dest, retries, log)

        stats[result] += 1
        completed += 1

        if completed % 50 == 0 or completed == total:
            log.info(
                f"Progress: {completed}/{total}  "
                f"(downloaded: {stats['downloaded']}, "
                f"skipped: {stats['skipped']}, "
                f"failed: {stats['failed']})"
            )

    connector = aiohttp.TCPConnector(limit=workers, limit_per_host=workers)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [bounded_download(session, url) for url in urls]
        await asyncio.gather(*tasks)

    return stats


def cleanup_extra_files(output_dir, expected_filenames, log):
    """Remove .tif files in output_dir that are not in the expected set."""
    output_dir = Path(output_dir)
    removed = []

    for filepath in output_dir.glob("*.tif"):
        if filepath.name not in expected_filenames:
            log.info(f"REMOVE  {filepath.name} (not in CSV)")
            filepath.unlink()
            removed.append(filepath.name)

    # Also clean up any leftover .tmp files
    for filepath in output_dir.glob("*.tif.tmp"):
        log.info(f"REMOVE  {filepath.name} (incomplete download)")
        filepath.unlink()

    return removed


def main():
    parser = argparse.ArgumentParser(
        description="Batch download swisstopo GeoTIFF tiles from a URL list"
    )
    parser.add_argument("csv", help="CSV file with one download URL per line")
    parser.add_argument("output_dir", help="Directory to store downloaded tiles")
    parser.add_argument(
        "-w", "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Concurrent downloads (default: {DEFAULT_WORKERS})"
    )
    parser.add_argument(
        "-r", "--retries", type=int, default=DEFAULT_RETRIES,
        help=f"Max retries per file (default: {DEFAULT_RETRIES})"
    )
    parser.add_argument(
        "--cleanup", action="store_true",
        help="Remove local .tif files not listed in the CSV"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without downloading or deleting"
    )

    args = parser.parse_args()

    # Setup
    log_file = setup_logging(args.output_dir)
    log = logging.getLogger("tile_dl")
    log.info(f"Log file: {log_file}")

    # Parse URLs
    urls = parse_csv(args.csv)
    if not urls:
        log.error(f"No URLs found in {args.csv}")
        return 1

    expected_filenames = {filename_from_url(u) for u in urls}
    log.info(f"CSV contains {len(urls)} tile URLs")

    # Check what already exists
    output_dir = Path(args.output_dir)
    existing = {f.name for f in output_dir.glob("*.tif")} if output_dir.exists() else set()
    to_download = [u for u in urls if filename_from_url(u) not in existing]
    already_have = len(urls) - len(to_download)

    log.info(f"Already downloaded: {already_have}")
    log.info(f"To download: {len(to_download)}")

    if args.cleanup:
        extra = existing - expected_filenames
        log.info(f"Files to remove (not in CSV): {len(extra)}")
        if extra and not args.dry_run:
            removed = cleanup_extra_files(args.output_dir, expected_filenames, log)
            log.info(f"Removed {len(removed)} files")
        elif extra:
            for name in sorted(extra):
                log.info(f"  Would remove: {name}")

    if args.dry_run:
        log.info("Dry run — no downloads performed")
        return 0

    if not to_download:
        log.info("Nothing to download — all tiles present")
        return 0

    # Download
    log.info(f"Starting download with {args.workers} workers...")
    t0 = time.time()

    stats = asyncio.run(
        download_batch(to_download, args.output_dir, args.workers, args.retries, log)
    )

    elapsed = time.time() - t0
    log.info(f"\nCompleted in {elapsed:.0f}s")
    log.info(f"  Downloaded: {stats['downloaded']}")
    log.info(f"  Skipped:    {stats['skipped']}")
    log.info(f"  Failed:     {stats['failed']}")

    if stats["failed"] > 0:
        log.warning(f"\n{stats['failed']} tiles failed — re-run to retry")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
