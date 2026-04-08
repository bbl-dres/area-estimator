# Green Roof from swissIMAGE-RS

Estimate **green roof coverage** per building by computing NDVI from
[swissIMAGE-RS](https://www.swisstopo.admin.ch/en/orthoimage-swissimage-rs)
multispectral imagery and intersecting it with building footprints.

> **Sibling tools** in [../](..):
> * **[mesh-builder/](../mesh-builder/)** — builds watertight 3D building hulls
>   from AV cadastral footprints + DSM/DTM
> * **[roof-shape-from-buildings3d/](../roof-shape-from-buildings3d/)** —
>   extracts roof characteristics from swissBUILDINGS3D 3D mesh geometry

## Why this exists

The active pipeline computes building areas and volumes from elevation rasters
but says nothing about *what's on top of* the roof. Green roofs (sedum mats,
gardens, intensive vegetation) are an architectural and ecological feature
worth tracking — for climate-adaptation reporting, biodiversity inventories,
roof-greening incentive programmes, and as input to solar-panel siting (a
green roof can co-exist with PV but the layout matters).

[swissIMAGE-RS](https://www.swisstopo.admin.ch/en/orthoimage-swissimage-rs) is
the right data source for this in Switzerland: 4-band multispectral imagery
(Blue, Green, Red, **Near-Infrared**) at 0.25 m ground sampling distance,
nationwide, free. With the NIR band you can compute **NDVI** per pixel and
threshold it to find vegetation — the same technique forestry and
agriculture have used for decades, applied to building footprints.

This tool is the thin pipe between building footprints and an NDVI raster:
clip the imagery to each footprint, threshold, count the green pixels, and
write a CSV.

## What it produces

* **One CSV file** per run, one row per building footprint
* Each row carries the green-roof metrics computed from the underlying NDVI:
  area in m², percentage of footprint covered, mean and max NDVI across the
  footprint, plus a status code so you can tell `analyzed` from `no_coverage`
  from `error`

## Algorithm

For each building footprint:

| Step | What | How |
|---|---|---|
| 1 | Find intersecting raster | R-tree (`shapely.STRtree`) lookup over all GeoTIFF bboxes in `--rs-dir`. **MVP shortcut**: takes the first intersecting tile only |
| 2 | Mask + clip | `rasterio.mask.mask(crop=True)` clips the raster to the footprint polygon |
| 3 | Compute NDVI | `(NIR − Red) / (NIR + Red)` per pixel, with hardcoded band assignment Band 1 = Red, Band 4 = NIR (see [Limitations](#limitations)) |
| 4 | Threshold for vegetation | Count pixels with `NDVI > --ndvi-threshold` (default `0.2`, the conventional vegetation cutoff) |
| 5 | Convert to area | Vegetation pixel count × pixel area (`src.res[0] × src.res[1]`) → green area in m² |
| 6 | Stats | Mean and max NDVI across all valid pixels, percentage of valid pixels that are vegetation |

### Why NDVI

The Normalised Difference Vegetation Index is the canonical remote-sensing
signal for vegetation. Live plants strongly absorb red light (chlorophyll
absorption peak around 670 nm) and strongly reflect near-infrared (cell
structure scattering above 700 nm), so the ratio `(NIR − Red) / (NIR + Red)`
sits near +1 for healthy vegetation, near 0 for bare soil / concrete /
asphalt, and near −1 for water. The threshold of 0.2 is a conventional
cutoff for "clearly vegetated".

For green-roof identification specifically, NDVI is particularly clean
because the rest of a roof (tiles, metal, gravel, asphalt) all have NDVI
values well below 0.2, so a simple thresholded count is usually enough.

## Quick start

### Install

Python 3.11 is recommended for the cleanest fiona / GDAL wheel install.

```bash
cd experimental/green-roof-from-rs

# Windows
py -3.11 -m venv venv
venv\Scripts\activate

# Linux/Mac
python3.11 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### Verify your RS data

Before the first real run, sanity-check that your TIFFs are readable
and have the expected band order:

```bash
python debug_rs.py
```

Edit the hardcoded `D:\SwissRS` path inside the script if your data lives
elsewhere. Output should show `CRS = EPSG:2056` and 4 bands per file.

### Run

```bash
python main.py path/to/buildings.gpkg \
    --rs-dir D:/SwissRS \
    --output green_roof.csv \
    --limit 100
```

Or against a swissBUILDINGS3D GDB file:

```bash
python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" \
    --layer Building_solid \
    --rs-dir D:/SwissRS \
    --output green_roof.csv \
    --limit 100
```

## CLI reference

| Argument | Required | Default | Description |
|---|---|---|---|
| `input` | yes | — | Footprint source: GeoPackage (`.gpkg`), Shapefile (`.shp`), GeoJSON (`.geojson`), or ESRI File Geodatabase (`.gdb`) |
| `--rs-dir` | yes | — | Directory containing swissIMAGE-RS GeoTIFFs |
| `--output` | yes | — | Output CSV path |
| `--layer` | conditional | — | Layer name (required for GDB; optional for GPKG with multiple layers) |
| `--ndvi-threshold` | no | `0.2` | Pixels with NDVI greater than this count as vegetation |
| `--limit` | no | — | Process at most N footprints |
| `-v`, `--verbose` | no | off | Debug logging |

## Output

A single CSV with one row per building footprint.

| Column | Type | Description |
|---|---|---|
| `id` | string | Building identifier (`EGID`, `UUID`, `id` from input properties, or row index in that priority) |
| `green_roof_status` | string | `analyzed`, `no_coverage`, `empty_mask`, or `error` |
| `green_roof_area_m2` | float | Vegetation pixel area in m² |
| `green_roof_percentage` | float | Vegetation pixels as % of valid pixels in the footprint |
| `ndvi_mean` | float | Mean NDVI across the footprint |
| `ndvi_max` | float | Max NDVI across the footprint |
| `error` | string | Error message (only present when `green_roof_status == "error"`) |

## Limitations

* **Single-tile-per-building MVP shortcut.** [`green_roof.py:137`](green_roof.py)
  uses only the *first* intersecting raster tile when a building's footprint
  spans multiple tiles. The right fix is to merge results from all
  intersecting tiles, but for the typical Swiss building (small enough to fit
  in one tile) it doesn't matter. Buildings on tile boundaries get partial
  results.
* **Hardcoded band assignment** (Band 1 = Red, Band 4 = NIR). Matches standard
  swissIMAGE-RS but verify with `debug_rs.py` before trusting output. Imagery
  from other sources may have different band order.
* **No reprojection** — input footprints must already be in LV95 (EPSG:2056),
  matching the raster CRS. The script doesn't transform.
* **Tree-canopy contamination at footprint edges** — overhanging branches
  outside the actual roof but inside the cadastral polygon contribute to the
  NDVI signal and overestimate green coverage. No automated fix; manual
  polygon trimming is the only mitigation.
* **NaN handling at the mask edges** — `rasterio.mask.mask` fills outside-the-shape
  pixels with `nodata=0`, which conflicts with real zero values in the bands.
  See the inline comments in `green_roof.py` for the workaround.
* **No parallelism in `main.py`** — buildings are processed sequentially.
  Easy to add via `ProcessPoolExecutor` when needed (the legacy integration
  in roof-shape-from-buildings3d's main.py had this pattern before the split).

## Files

| File | Purpose |
|---|---|
| [main.py](main.py) | Standalone CLI — loads footprints, runs the analyser, writes CSV |
| [green_roof.py](green_roof.py) | Core library: `RasterIndexer` (R-tree of tile bboxes) + `GreenRoofAnalyzer` (per-footprint NDVI calculation) |
| [debug_rs.py](debug_rs.py) | Sanity check — opens TIFFs, prints CRS / bounds / bands. Hardcoded path; edit before running |
| [find_buildings_in_area.py](find_buildings_in_area.py) | Helper: finds swissBUILDINGS3D buildings inside a single SWISSIMAGE-RS tile's coverage. Hardcoded paths |
| [check_coverage.py](check_coverage.py) | Helper: counts swissBUILDINGS3D buildings inside hardcoded SWISSIMAGE-RS bounds |
| [requirements.txt](requirements.txt) | `rasterio`, `shapely`, `fiona`, `numpy`, `pillow` |
| [README.md](README.md) | This file |

## Data sources

| Dataset | Provider | URL |
|---|---|---|
| swissIMAGE-RS | swisstopo | [swisstopo.admin.ch/en/orthoimage-swissimage-rs](https://www.swisstopo.admin.ch/en/orthoimage-swissimage-rs) |
| swissBUILDINGS3D 3.0 (one footprint source) | swisstopo | [swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta) |
| Amtliche Vermessung (cadastral footprints) | Cantons via geodienste.ch | [geodienste.ch/services/av](https://www.geodienste.ch/services/av) |

## swissIMAGE-RS background

[swissIMAGE-RS](https://www.swisstopo.admin.ch/en/orthoimage-swissimage-rs)
is the **multispectral** version of swissIMAGE: 4 bands (Blue, Green, Red,
Near-Infrared) at 0.25 m ground sampling distance, 16-bit per band, covering
Switzerland on a periodic update cycle. Distributed as GeoTIFFs in LV95
(EPSG:2056). It's the right input for any vegetation-index work in
Switzerland — the regular swissIMAGE 10cm RGB product doesn't have the NIR
band you need for NDVI.

The hardcoded **band assignment** in [green_roof.py](green_roof.py) is:

```python
BAND_RED = 1
BAND_NIR = 4
```

This matches the standard swissIMAGE-RS band order. **Verify against your
actual files** with `python debug_rs.py` before trusting output. If your
imagery uses a different band order, edit those constants at the top of
[green_roof.py](green_roof.py).

## Future cross-tool integration

There's a natural hook into the [mesh-builder/](../mesh-builder/) tool:
instead of computing NDVI on the 2D footprint polygon, compute it on the
**roof surface** of the watertight 3D mesh that mesh-builder produces. That
gives you NDVI per-roof-face, which:

* Correctly handles sloped green roofs (the 3D area is bigger than the 2D footprint)
* Drops tree canopies overhanging the eaves (faces classified as "wall" in the mesh-builder viewer aren't roof, so they're excluded)
* Lets you report per-wing or per-roof-section green coverage on multi-wing buildings

This is a Phase-2 idea. The current MVP's footprint-based approach is enough
to identify which buildings have *any* significant green roof coverage,
which is the usual screening question.
