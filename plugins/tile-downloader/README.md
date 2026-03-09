# Tile Downloader

Batch downloads swisstopo GeoTIFF elevation tiles (swissALTI3D / swissSURFACE3D) from a CSV URL list.

## Setup

```bash
pip install -r plugins/tile-downloader/requirements.txt
```

## Get the URL list

1. Go to [swisstopo data distribution](https://www.swisstopo.admin.ch/de/hoehenmodell-swissalti3d)
2. Select your area of interest and export the URL list as CSV

The CSV is one URL per line, no header:

```
https://data.geo.admin.ch/ch.swisstopo.swissalti3d/swissalti3d_2019_2501-1120/swissalti3d_2019_2501-1120_0.5_2056_5728.tif
https://data.geo.admin.ch/ch.swisstopo.swissalti3d/swissalti3d_2019_2501-1121/swissalti3d_2019_2501-1121_0.5_2056_5728.tif
...
```

## Usage

```bash
# Download all tiles (4 concurrent workers)
python plugins/tile-downloader/download_tiles.py \
    "D:/SwissAlti3D/ch.swisstopo.swissalti3d-686PSzUp.csv" \
    "D:/SwissAlti3D"

# Faster with more workers
python plugins/tile-downloader/download_tiles.py \
    urls.csv output_dir -w 8

# Remove tiles not in the CSV
python plugins/tile-downloader/download_tiles.py \
    urls.csv output_dir --cleanup

# Preview what would happen
python plugins/tile-downloader/download_tiles.py \
    urls.csv output_dir --cleanup --dry-run
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-w, --workers` | 4 | Concurrent downloads |
| `-r, --retries` | 5 | Max retries per file (exponential backoff) |
| `--cleanup` | off | Remove local `.tif` files not in the CSV |
| `--dry-run` | off | Show plan without downloading or deleting |

## How it works

- **Skip existing**: Files matching by name and size are skipped
- **Atomic writes**: Downloads to `.tmp` first, renames on success — no partial files
- **Retry with backoff**: 5 retries with exponential backoff (5s, 10s, 20s, 40s, 80s) — handles swisstopo's frequent aborts
- **Logs**: Every run creates a timestamped log in `OUTPUT_DIR/logs/`
- **Re-run safe**: Run as many times as needed; only missing/incomplete tiles are downloaded
