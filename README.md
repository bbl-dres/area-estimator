# Swiss Building Volume & Area Estimator

![Area Estimator](images/Social1.jpg)

![Python](https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white)
![JavaScript](https://img.shields.io/badge/javascript-ES6+-yellow)
![MapLibre](https://img.shields.io/badge/maplibre-4.7-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![swisstopo](https://img.shields.io/badge/data-swisstopo-red)
![CRS](https://img.shields.io/badge/CRS-LV95%20EPSG%3A2056-orange)

Estimates building volumes and gross floor areas using publicly available Swiss elevation models and cadastral data.

The solution is available in three variants:

- **[Web App](https://bbl-dres.github.io/area-estimator/)** — Zero-install browser app. Upload a CSV with building EGIDs, get volumes and floor areas on a map with export to CSV/Excel/GeoJSON.
- **[Python CLI](python/)** — Open-source, requires Python >= 3.10 and free dependencies. Processes locally with exact LV95 areas and local elevation tiles.
- **[FME](fme/)** — Requires a licensed copy of [FME Form](https://fme.safe.com/fme-form/).

<p align="center">
  <img src="images/Preview_2.jpg" width="45%" />
  <img src="images/Preview_3.jpg" width="45%" />
</p>
<p align="center">
  <img src="images/Preview_4.jpg" width="70%" />
</p>

---

## Web App

The browser-based version runs entirely client-side — no backend, no installation. Upload a CSV with `id` and `egid` columns and the app will:

1. Fetch building footprints from [geodienste.ch](https://geodienste.ch) WFS (`ms:LCSF`, filtered by `GWR_EGID`)
2. Load elevation data (DTM + DSM) from [swisstopo COG tiles](https://data.geo.admin.ch) on-the-fly
3. Compute volume and heights using an orientation-aligned 2×2m grid
4. Look up building classification from [GWR](https://www.housing-stat.ch) via swisstopo API
5. Estimate floor areas from building type and volume
6. Display results on an interactive map with table and summary panel

### Features

- **Interactive Map** — MapLibre GL JS with 3D building extrusions, orientation-aligned grid cell visualization, 4 basemaps, scale bar
- **Layer Panel** — Toggle Gebäudegrundflächen, Gebäudevolumen, Rasterzellen, Beschriftungen, and AV cadastral overlay
- **Summary Panel** — Collapsible sections for building status, volume/height aggregates, and floor area estimates
- **Table Widget** — Sortable columns, search filter, pagination, resizable panel, row click → map highlight
- **Export** — CSV, Excel (XLSX), and GeoJSON with timestamped filenames
- **Privacy** — All data stays in the browser. Only EGID and coordinates are sent to public APIs

### Limitations vs Python Version

| | Web App | Python CLI |
|---|---|---|
| **Data coverage** | 20 of 26 cantons via public WFS (JU, LU, NE, NW, OW, VD blocked) | All cantons via local GeoPackage |
| **Elevation data** | On-the-fly COG tile loading from swisstopo CDN | Local GeoTIFF tiles (faster, offline) |
| **Grid resolution** | 2×2m (configurable) | 1×1m (configurable) |
| **Area calculation** | Spherical (Turf.js), ~0.1–0.5% error for spatial matching | Exact planar (LV95/EPSG:2056) |
| **Throughput** | ~5 buildings in parallel, limited by API rate | Bulk processing with local data |
| **EGID lookup** | Direct WFS filter by `GWR_EGID` | Local GeoPackage spatial join |
| **Offline** | Requires internet | Fully offline with local data |

> **Data coverage note:** The Web App uses the geodienste.ch WFS, which requires cantonal approval in 6 cantons (JU, LU, NE, NW, OW, VD). Buildings in these cantons will return "Kein Grundriss". Coverage is also incomplete in TI, VS, and NE.

### Quick Start

Open `index.html` in a browser (requires a local server for ES modules):

```bash
cd area-estimator
python -m http.server 8080
# Open http://localhost:8080
```

Or deploy to any static hosting (GitHub Pages, Cloudflare Pages, etc.).

### File Structure

```
index.html                   Entry point (GitHub Pages compatible)
css/
  tokens.css                 Design tokens (colors, spacing, typography)
  styles.css                 Component styles + responsive breakpoints
js/
  main.js                    State machine (upload → processing → results)
  upload.js                  CSV/XLSX parsing with auto-delimiter detection
  processor.js               EGID/coord lookup + WFS query + volume pipeline (5× parallel)
  elevation.js               COG tile loading, oriented grid, volume computation
  map.js                     MapLibre map, 3D extrusions, grid cell visualization
  table.js                   Sortable table with pagination and search
  config.js                  API endpoints, floor height lookup, map styles
  export.js                  CSV/XLSX/GeoJSON export
data/
  example.csv                Demo data (10 buildings with verified EGIDs)
```

### APIs Used

| API | Purpose | Auth |
|-----|---------|------|
| `geodienste.ch/db/av_0/{lang}` WFS | Building footprints by EGID or BBOX (`ms:LCSF`) | None (CORS) |
| `api3.geo.admin.ch/MapServer/find` | GWR building attributes by EGID | None (CORS) |
| `data.geo.admin.ch` | swissALTI3D + swissSURFACE3D COG tiles | None (CORS) |

---

## Model Overview

```mermaid
flowchart TD
    subgraph INPUT["Inputs"]
        A1A["🔴 --footprints<br>AV GeoPackage / Shapefile / GeoJSON<br><i>required</i>"]
        A1B["⚪ --csv<br>CSV: id, egid (default)<br>or id, lon, lat (with --use-coordinates)<br><i>optional</i>"]
        A2["🔴 --alti3d<br>swissALTI3D tiles — terrain DTM 0.5m<br><i>required</i>"]
        A3["🔴 --surface3d<br>swissSURFACE3D tiles — surface DSM 0.5m<br><i>required</i>"]
    end

    A1A --> S1
    A1B -.->|"--csv"| S1
    A2 --> S3
    A3 --> S3

    S1["<b>Step 1 — Read Footprints</b><br>Mode A: all AV buildings<br>Mode B: EGID match against GWR_EGID (default)<br>Mode C: lon/lat spatial join (--use-coordinates)<br>Unmatched → status: no_footprint"]
    S2["<b>Step 2 — Aligned Grid</b><br>Minimum rotated rectangle orientation<br>Grid points filtered to footprint"]
    S3["<b>Step 3 — Volume & Heights</b><br>Sample DTM + DSM at each point<br>Volume = Σ max(surface_i − min(terrain), 0) × cell_area"]
    S4["<b>Step 4 — Floor Areas</b><br>GWR classification → floor height<br>Floors = height_minimal / floor_height<br>GFA = footprint × floors"]

    S1 --> S2 --> S3
    S3 --> OUT
    S3 -.->|"--estimate-area"| S4
    S4 -.-> OUT

    OUT[/"<b>Output CSV</b><br>volume · heights · elevations<br>+ floor areas if --estimate-area"/]

    subgraph GWR["⚪ GWR Data — optional, only with --estimate-area"]
        G1["--gwr-csv<br>CSV bulk download<br><i>housing-stat.ch</i>"]
        G2["(default)<br>swisstopo API<br><i>per EGID, live lookup</i>"]
    end

    GWR -.-> S4

    classDef required fill:#fde8e8,stroke:#e02424,stroke-width:2px
    classDef optional fill:#f3f4f6,stroke:#9ca3af,stroke-width:1px
    classDef step fill:#eff6ff,stroke:#3b82f6,stroke-width:1.5px
    classDef optionalStep fill:#f3f4f6,stroke:#9ca3af,stroke-width:1px,stroke-dasharray:4 3

    class A1A,A2,A3 required
    class A1B optional
    class S1,S2,S3 step
    class S4 optionalStep
```

> **Note:** The flowchart above describes the Python CLI pipeline. The Web App follows the same 4 steps but sources data from public APIs instead of local files.

---

## Python CLI

### Command-Line Reference

| Argument | Required | Description |
|----------|:--------:|-------------|
| **Input** | | |
| `--footprints FILE` | yes | Geodata file with building polygons (GeoPackage, Shapefile, or GeoJSON from AV). Alone: processes all buildings in the file. |
| `--csv FILE` | no | CSV input file. **Default mode:** columns `id`, `egid` — each EGID is matched against `GWR_EGID` in the AV file via a single push-down query (one I/O for the whole batch, fast). With `--use-coordinates`: columns `id`, `lon`, `lat` — performs a strict point-in-polygon spatial join instead. Comma- and semicolon-delimited CSVs are both accepted. Unmatched rows are reported as `no_footprint`. |
| `--use-coordinates` | no | Switch `--csv` from EGID match to lon/lat spatial join. Required only for buildings that have no EGID assigned in the cadastral data. |
| **Elevation data** | | |
| `--alti3d DIR` | yes | Directory with swissALTI3D GeoTIFF tiles |
| `--surface3d DIR` | yes | Directory with swissSURFACE3D GeoTIFF tiles |
| `--auto-fetch` | | Automatically download missing tiles from swisstopo |
| **Output** | | |
| `-o, --output FILE` | | Output CSV file path. A `YYYYMMDD_HHMM` timestamp (matching the web app's export naming) is appended to the stem. If omitted, the output is dropped **next to `--csv`** (named `<csv_stem>_<timestamp>.csv`) when `--csv` is given, otherwise into `data/output/result_<timestamp>.csv`. The log file is written next to the CSV with a matching name (same stem, `.log` extension), so e.g. `Gebäude_IN_20260408_1542.csv` pairs with `Gebäude_IN_20260408_1542.log`. |
| **Filters** | | |
| `-l, --limit N` | | Process only the first N buildings |
| `-b, --bbox MIN_LON MIN_LAT MAX_LON MAX_LAT` | | Bounding box filter in WGS84 (only in all-buildings mode, i.e. without `--csv`) |
| **Area estimation** (off by default) | | |
| `--estimate-area` | | Enable Step 4: floor area estimation |
| `--gwr-csv FILE` | | GWR CSV from [housing-stat.ch](https://www.housing-stat.ch/de/data/supply/public.html); if omitted, uses swisstopo API (one call per building) |

### Setup

```bash
pip install -r python/requirements.txt
```

### Tests

The pure logic in `area.py`, `volume.py`, `footprints.py`, and the aggregation reduce in `main.py` is covered by a small `pytest` suite under [tests/](tests/). Run it with:

```bash
pip install -r python/requirements-dev.txt
pytest tests/
```

The suite covers floor-area estimation (including the `gastw` cap, banker's-rounding fix, and DEFAULT-source accuracy), the multi-EGID/multi-polygon array aggregation, the CSV reader's BOM and delimiter handling, and the `_to_gwr_code`/`_parse_egid_cell` parsers. Network-bound paths (`query_gwr_api`, `tile_fetcher`) and raster sampling (`TileIndex.sample_heights`) are intentionally not unit-tested — they're covered by the integration runs against [data/example.csv](data/example.csv) instead.

### Examples

```bash
# Portfolio list by EGID (default — accepts the same CSV as the web app)
python python/main.py \
    --footprints "D:\AV_lv95\av_2056.gpkg" \
    --csv data/example.csv \
    --alti3d "D:\SwissAlti3D" \
    --surface3d "D:\swissSURFACE3D Raster" \
    --estimate-area \
    -o portfolio_volumes.csv

# Same input via lon/lat spatial join (for buildings without an EGID in AV)
python python/main.py \
    --footprints "D:\AV_lv95\av_2056.gpkg" \
    --csv my_buildings_with_coords.csv \
    --use-coordinates \
    --alti3d "D:\SwissAlti3D" \
    --surface3d "D:\swissSURFACE3D Raster" \
    -o portfolio_volumes.csv

# All buildings in Switzerland with bulk GWR for floor areas
python python/main.py \
    --footprints data/av/ch_av_2056.gpkg \
    --alti3d /data/swisstopo/swissalti3d \
    --surface3d /data/swisstopo/swisssurface3d \
    --estimate-area --gwr-csv data/gwr/buildings.csv \
    -o results/ch_all_buildings.csv

# Quick test with auto-fetch (no local elevation data needed)
python python/main.py \
    --footprints data/av/ch_av_2056.gpkg \
    --csv data/example.csv \
    --alti3d data/swissalti3d \
    --surface3d data/swisssurface3d \
    --auto-fetch \
    --limit 10
```

---

## Outputs

All results are written to a single CSV file (`result_<timestamp>.csv`).

### Step 1 — Footprints

Three modes, automatically selected based on which flags are provided:

- **AV only** (`--footprints`): Loads all building polygons from the geodata file and filters to buildings (`Art = Gebaeude`). Converts to LV95 if needed. The `GWR_EGID` column is renamed to `av_egid`; each feature gets an `fid`.
- **AV + CSV by EGID** (`--footprints` + `--csv`, default): Each input row's `egid` is matched against `GWR_EGID` in the AV file via a single push-down query — fast and unambiguous. The cell may contain a single EGID *or* a list of EGIDs separated by **any combination of `,`, `/`, `;`, or whitespace** (real-world colleague CSVs use all of them, often mixed). Every cell goes through a cleanup pass first that collapses tabs, line breaks, NBSPs, and double spaces — so `"1234,\n5678"`, `"1234 / 5678"`, and `"1234;5678"` all parse the same way. Each EGID is looked up independently and the results are joined back to one output row per input CSV row (see "Array aggregation" below). EGIDs not present in AV get `status_step1 = no_footprint`. Cells that contain no parseable positive integer get `status_step1 = invalid_egid`. **This is the same input format the web app uses** — `data/example.csv` works in both tools.
- **AV + CSV by lon/lat** (`--footprints` + `--csv` + `--use-coordinates`): Strict point-in-polygon spatial join. Slower but works for buildings that have no EGID assigned in the cadastral data. Points with no matching polygon get `status_step1 = no_footprint`.

> **AV vs GWR:** AV (Amtliche Vermessung) is the cadastral survey — it provides parcel and building geometry. GWR (Gebäude- und Wohnungsregister) provides building master data: addresses, classification, construction year, dwelling counts. The `GWR_EGID` column on AV polygons is the link between the two registers. EGID match (mode B) is the natural key, but a few percent of AV building polygons have no EGID assigned, which is why coordinate-based matching is kept as an option.

#### Array aggregation: one output row per input row

The pipeline guarantees **one output CSV row per input CSV row** (per `input_id`). When a single input row produces several intermediate sub-rows — because the cell contained multiple EGIDs (separated by any of `,`, `/`, `;`, or whitespace), or because one EGID matches multiple AV polygons — they are collapsed back to a single output row at the end of the pipeline.

The collapse is **transparent, not summed**. Numeric metrics (`area_footprint_m2`, `volume_above_ground_m3`, `area_floor_total_m2`, height/elevation columns, …) become `;`-joined arrays of every sub-value when sub-rows disagree, and stay as scalars when all sub-rows agree. Identifier columns (`av_egid`, `fid`) become `;`-joined too. Empty positions in the array (e.g. `"727; ; ; 6.59; 6.54"`) mark sub-EGIDs that did not find a match in the AV file.

This is a deliberate design choice: **the array form makes data-quality issues visible at the row level**, so a downstream user can fix the source CSV (split multi-EGID cells into separate rows, decide whether overlapping parcels should be merged, etc.) instead of discovering the issue much later as inflated totals. Pipeline summary stats only count the single-source rows; array rows are reported separately in the run log.

Every output row carries a `warnings` column that accumulates data-quality notes from every step. See **Warning messages** below for the catalog.

### Step 2 — Aligned Grid

Fills each building footprint with a grid of sample points. The grid is rotated to align with the building's longest edge (using the minimum area bounding rectangle), so it fits tightly even for angled buildings. Grid resolution is 1×1m (Python) or 2×2m (Web App).

<p align="center">
  <img src="images/Oriented_Grid.jpg" width="70%" />
</p>

### Step 3 — Volume & Heights

At each grid point, the tool reads two elevations: the ground level (DTM) and the surface level including buildings/trees (DSM). The above-ground height at each point is measured from the lowest terrain elevation under the building (`elevation_base_min`) as a flat horizontal datum — `max(surface_i − min(terrain), 0)`. Volume is the sum of all those heights, each multiplied by the cell area.

| Column | Description |
|--------|-------------|
| `area_footprint_m2` | Footprint area from AV polygon geometry (m²) |
| `volume_m3` | Total above-ground volume: `Σ max(surface_i − min(terrain), 0) × cell_area` |
| `elevation_base_min` | Lowest ground elevation — volume base datum (m a.s.l.) |
| `elevation_base_mean` | Mean ground elevation (m a.s.l.) |
| `elevation_base_max` | Highest ground elevation (m a.s.l.) |
| `elevation_roof_min` | Lowest surface elevation — typically the eave (m a.s.l.) |
| `elevation_roof_mean` | Mean surface elevation (m a.s.l.) |
| `elevation_roof_max` | Highest surface elevation — typically the ridge (m a.s.l.) |
| `height_mean` | Average above-ground height from `elevation_base_min` (m) |
| `height_max` | Tallest above-ground point (m) |
| `height_minimal` | `volume ÷ footprint area` — equivalent uniform box height (m) |
| `grid_points` | Number of grid points with valid DTM + DSM data |

### Step 4 — Floor Areas _(optional)_

Estimates gross floor area by dividing building height by a typical floor height for that building type. The building type comes from the GWR (Federal Register of Buildings). The tool looks up the floor height in this order: first by the specific building class (GKLAS, e.g. "Office building" → 3.80 m), then by the broader category (GKAT, e.g. "Non-residential" → 4.15 m), and falls back to a default of 3.00 m. Based on the [Canton Zurich methodology](https://are.zh.ch/) (Seiler & Seiler, 2020).

| Column | Description |
|--------|-------------|
| `gkat` | GWR building category code (e.g. 1020 = Residential) |
| `gklas` | GWR building class code (e.g. 1110 = Single-family house) |
| `gbauj` | Construction year |
| `gastw` | Number of stories (from register) |
| `floor_height_used_m` | Floor height used for estimation (m) |
| `floor_height_source` | Where the floor height came from: `GKLAS` (specific class), `GKAT` (broader category), or `DEFAULT` (no GWR class match — appended to `warnings`) |
| `floors_estimated` | Estimated floors: `height_minimal ÷ floor_height`, capped at GWR `gastw` if available |
| `area_floor_total_m2` | Gross floor area: `footprint × estimated floors` (m²) |
| `area_accuracy` | `high` (±10–15%) / `medium` (±15–25%) / `low` (±25–40%) — see decision tree below |
| `building_type` | Human-readable building type |
| `warnings` | `;`-joined data-quality notes accumulated across all four steps (empty when nothing to report) |

#### How `area_accuracy` is computed

Each successful Step 4 row gets one of three buckets — `high`, `medium`, or `low` — that captures **how trustworthy the floor-area estimate is for that building type**. The decision is data-driven: every GWR code in `FLOOR_HEIGHT_LOOKUP` has an explicit per-code bucket assignment, derived from the validation study at [docs/Height Assumptions.md](docs/Height%20Assumptions.md).

The decision tree, evaluated top to bottom:

| # | Condition | Result | Reason |
|---|---|---|---|
| 1 | Volume or footprint missing | **low** | No measurement to be confident about |
| 2 | `floor_height_source == DEFAULT` (no GWR class match in `FLOOR_HEIGHT_LOOKUP`) | **low** | Fell back to the residential default (~3.0 m); the floor count is a guess |
| 3 | Both `gkat` and `gklas` are missing | **low** | No type information at all |
| 4 | `gklas` is in [`_ACCURACY_BY_GKLAS`](python/area.py) | the dict's value | Per-code bucket from the validation study, mapped 5→3 levels conservatively |
| 5 | `gkat` is in [`_ACCURACY_BY_GKAT`](python/area.py) | the dict's value | Same, broader category fallback |
| 6 | Anything else (e.g. a future GWR revision not in the dicts) | **medium** | Safe catch-all — neither over- nor under-promising on something we haven't characterised |

The per-code dicts map every code in `FLOOR_HEIGHT_LOOKUP` to one of the three buckets, with the validation study's qualitative confidence as the source of truth:

| Bucket | Source confidence (study) | GWR codes |
|---|---|---|
| **high** | High | `1020` GKAT (Residential single-house), `1030` GKAT (Residential w/ secondary use), `1110` SFH, `1121` Two-family, `1122` MFH, `1263` Schools and universities |
| **medium** | Medium-High *or* Medium | `1010` Provisional shelter, `1040` Partially residential, `1060` Non-residential, `1130` Community residential, `1211` Hotel, `1212` Short-term accommodation, `1220` Office, `1230` Retail, `1231` Restaurants, `1242` Parking garages, `1251` Industrial, `1264` Hospitals, `1265` Sports halls |
| **low** | Low *or* Low-Medium | `1080` Special-purpose, `1241` Stations and terminals, `1252` Tanks/silos/warehouses, `1261` Culture and leisure, `1262` Museums and libraries, `1271` Agricultural, `1272` Churches and religious, `1273` Monuments and protected, `1274` Other structures |

When both `gklas` and `gkat` are present, **GKLAS wins** (more specific). The percentage tolerances (`±10–15%`, etc.) are estimated confidence intervals from the Seiler & Seiler 2020 methodology and Swiss regulatory anchors — they are *not* measured against ground-truth drawings. See [docs/Height Assumptions.md](docs/Height%20Assumptions.md) for the full validation study, including the per-code rationale and the original 5-level qualitative scale this 3-bucket simplification is derived from.

> **Note:** The 5→3 mapping is **conservative**: only the study's `High` maps to our `high`, and any `Low` or `Low-Medium` maps to `low`. The half-steps `Medium-High` and `Low-Medium` both round toward the middle. This makes `high` trustworthy and `low` inclusive — better to under-promise than over-promise on a single-number bucket.

#### Warning messages

The `warnings` column accumulates `;`-joined data-quality notes from every pipeline step. An empty cell means nothing to report. Most warnings come from Step 1 (input parsing and AV matching); Step 4 adds one more for the GWR-class fallback; the aggregation step at the end of the pipeline appends a final note when more than one sub-row contributed to an output row.

| Step | Warning text (template) | What it means | What to do |
|---|---|---|---|
| Step 1 | `EGID could not be parsed as a positive integer: '<raw>'` | The `egid` cell contained no parseable positive integer at all — typically free text, a zero/negative value, or a token that mixes letters with digits. Row gets `status_step1=invalid_egid` and is skipped by Steps 2-4. | Fix the source CSV. Single integer or any-separator list of positive integers is fine; raw text is not. |
| Step 1 | `Input cell contained N EGIDs: 1234, 5678` | The cell contained multiple EGIDs separated by `,`, `/`, `;`, whitespace, or any combination. Each was looked up independently in AV and then aggregated back to one output row. | Splitting multi-EGID cells into separate input rows (one EGID per row) gives cleaner output and avoids the `;`-joined array form in the result. |
| Step 1 | `EGID 1234567 matched N AV polygons` | One EGID appears as multiple polygon records in the AV cadastral data — typically a building split across cadastral parcels. Each polygon was processed individually and aggregated. | Usually nothing — this is a real cadastral situation. The aggregated row's numeric columns will be `;`-joined arrays showing every sub-polygon's value. |
| Step 1 | `Point fell inside N AV polygons — emitting one row per polygon` | Only in `--use-coordinates` mode: the lon/lat point landed inside multiple AV polygons. | Verify the input coordinate. Overlapping AV polygons usually indicate slivers or duplicates in the cadastral data. |
| Step 4 | `no GWR class match — using default floor height` | The building's `gkat`/`gklas` codes weren't found in the floor-height lookup table, so the residential default (≈3.0 m) was applied. This forces `area_accuracy = low`. | Indicative — area estimation is unreliable for this row. May indicate a GWR code newer than the lookup table or a building type the lookup doesn't cover. |
| Aggregation | `aggregated N sub-rows from M distinct EGIDs (numeric columns are ;-joined arrays — fix the input CSV to one EGID per row)` | The input row had multi-EGID content (parsed N sub-EGIDs, M of which actually matched in AV); the output row's numeric columns are `;`-joined arrays. | Fix the source CSV: one EGID per row. The arrays in the output show exactly which sub-EGIDs contributed. |
| Aggregation | `aggregated N AV polygons for one EGID (numeric columns are ;-joined arrays — building is split across cadastral parcels)` | A single EGID matches N polygons in AV (split across parcels). The numeric columns become `;`-joined arrays so each parcel's value is visible. | Usually nothing — this is structural to the cadastral data. Sum the array values yourself if you need a building total. |

When more than one warning fires for the same row, they are concatenated with `; ` separators in the order Step 1 → Step 4 → Aggregation.

---

## Limitations

| Limitation | Detail |
|------------|--------|
| No underground estimation | LIDAR only sees above ground — basements and underground floors are not included |
| Trees over buildings | The surface model doesn't distinguish roofs from foliage — tall trees over small buildings inflate the measured height and volume |
| Surface model merging | swissSURFACE3D combines ground, vegetation, and buildings into one surface; this can cause overestimation near vegetation |
| Small buildings | Footprints smaller than the grid cell size produce no grid points and can't be measured |
| Mixed-use buildings | A single floor height is applied per building; actual floor heights may vary (e.g. retail ground floor + residential upper floors) |
| Industrial / special buildings | Floor height ranges are wide (4–7 m), so floor count estimates are less reliable |
| Data timing | The elevation model may have been captured before or after the building was constructed or modified |
| Sloped terrain | Volume is measured from `elevation_base_min` (lowest terrain point) as a flat datum. On steeply sloped sites, this includes terrain undulation. |
| Web App coverage | 6 cantons (JU, LU, NE, NW, OW, VD) block the geodienste.ch WFS — use the Python CLI with a local GeoPackage for full coverage |

---

## Project Structure

```
area-estimator/
├── index.html                        ← Web App entry point (GitHub Pages)
├── css/                              ← Stylesheets
│   ├── tokens.css                       Design tokens
│   └── styles.css                       Component styles
├── js/                               ← Web App modules
│   ├── main.js                          State machine + UI
│   ├── upload.js                        CSV/XLSX parsing
│   ├── processor.js                     EGID lookup + WFS + volume pipeline
│   ├── elevation.js                     COG tiles, oriented grid, volume
│   ├── map.js                           MapLibre map + 3D visualization
│   ├── table.js                         Results table
│   ├── config.js                        Endpoints, floor heights, constants
│   └── export.js                        CSV/XLSX/GeoJSON export
├── python/                           ← Python CLI (Steps 1–4)
│   ├── main.py                          CLI entry point
│   ├── footprints.py                    Step 1: load footprints / coordinates
│   ├── grid.py                          Step 2: aligned grid
│   ├── volume.py                        Step 3: elevation sampling & volume
│   ├── tile_fetcher.py                  On-demand tile download from swisstopo
│   ├── gwr.py                           GWR lookup (CSV + API)
│   ├── area.py                          Step 4: floor area estimation
│   └── requirements.txt
├── fme/                              ← FME workbench (requires license)
├── tools/
│   ├── roof-estimator/               ← Roof shape analysis from 3D meshes
│   └── green-roof-eval/              ← Green roof detection (FME-based)
├── legacy/                           ← Original implementations (reference)
├── data/                             ← .gitignored (except example.csv)
│   ├── example.csv                      Demo data for Web App
│   ├── output/                          Pipeline results
│   ├── gwr/                             GWR CSV download
│   ├── swissalti3d/                     Terrain tiles
│   └── swisssurface3d/                  Surface tiles
└── images/
```

---

## Floor Height Lookup

Story heights per building class, used by Step 4 to convert volume into floor count.

- **GF** = ground floor (German: *Erdgeschoss*, EG). The first storey of the building.
- **UF** = upper floor (German: *Regelgeschoss*, RG). The "typical" non-ground storey above.
- **min–max** is a validation range observed across real buildings of that class. It is not used as a confidence interval — Step 4 collapses all four numbers into a single representative floor height (`(GF_min + GF_max + UF_min + UF_max) / 4`) and computes `floors = height ÷ floor_height`. The ranges are kept for cross-checking against known buildings, not to drive the math.

| Code | Building Type | Schema | GF (m) | UF (m) |
|------|---------------|--------|--------|--------|
| 1010 | Provisional shelter | GKAT | 2.70–3.30 | 2.70–3.30 |
| 1030 | Residential with secondary use | GKAT | 2.70–3.30 | 2.70–3.30 |
| 1040 | Partially residential | GKAT | 3.30–3.70 | 2.70–3.70 |
| 1060 | Non-residential | GKAT | 3.30–5.00 | 3.00–5.00 |
| 1080 | Special-purpose | GKAT | 3.00–4.00 | 3.00–4.00 |
| 1110 | Single-family house | GKLAS | 2.70–3.30 | 2.70–3.30 |
| 1121 | Two-family house | GKLAS | 2.70–3.30 | 2.70–3.30 |
| 1122 | Multi-family house | GKLAS | 2.70–3.30 | 2.70–3.30 |
| 1130 | Community residential | GKLAS | 2.70–3.30 | 2.70–3.30 |
| 1211 | Hotel | GKLAS | 3.30–3.70 | 3.00–3.50 |
| 1212 | Short-term accommodation | GKLAS | 3.00–3.50 | 3.00–3.50 |
| 1220 | Office building | GKLAS | 3.40–4.20 | 3.40–4.20 |
| 1230 | Wholesale and retail | GKLAS | 3.40–5.00 | 3.40–5.00 |
| 1231 | Restaurants and bars | GKLAS | 3.30–4.00 | 3.30–4.00 |
| 1241 | Stations and terminals | GKLAS | 4.00–6.00 | 4.00–6.00 |
| 1242 | Parking garages | GKLAS | 2.80–3.20 | 2.80–3.20 |
| 1251 | Industrial building | GKLAS | 4.00–7.00 | 4.00–7.00 |
| 1252 | Tanks, silos, warehouses | GKLAS | 3.50–6.00 | 3.50–6.00 |
| 1261 | Culture and leisure | GKLAS | 3.50–5.00 | 3.50–5.00 |
| 1262 | Museums and libraries | GKLAS | 3.50–5.00 | 3.50–5.00 |
| 1263 | Schools and universities | GKLAS | 3.30–4.00 | 3.30–4.00 |
| 1264 | Hospitals and clinics | GKLAS | 3.30–4.00 | 3.30–4.00 |
| 1265 | Sports halls | GKLAS | 3.00–6.00 | 3.00–6.00 |
| 1271 | Agricultural buildings | GKLAS | 3.50–5.00 | 3.50–5.00 |
| 1272 | Churches and religious buildings | GKLAS | 3.00–6.00 | 3.00–6.00 |
| 1273 | Monuments and protected buildings | GKLAS | 3.00–4.00 | 3.00–4.00 |
| 1274 | Other structures | GKLAS | 3.00–4.00 | 3.00–4.00 |
| — | Default (unknown) | — | 2.70–3.30 | 2.70–3.30 |

---

## References

| Resource | Link |
|----------|------|
| Amtliche Vermessung (AV) | [geodienste.ch/services/av](https://www.geodienste.ch/services/av) |
| swissALTI3D | [swisstopo.admin.ch](https://www.swisstopo.admin.ch/de/hoehenmodell-swissalti3d) |
| swissSURFACE3D Raster | [swisstopo.admin.ch](https://www.swisstopo.admin.ch/de/hoehenmodell-swisssurface3d-raster) |
| swisstopo Search API | [docs.geo.admin.ch](https://docs.geo.admin.ch/access-data/search.html) |
| swisstopo Find API | [docs.geo.admin.ch](https://docs.geo.admin.ch/access-data/find-features.html) |
| GWR | [housing-stat.ch](https://www.housing-stat.ch/de/index.html) |
| GWR Public Data | [housing-stat.ch/data](https://www.housing-stat.ch/de/data/supply/public.html) |
| GWR Catalog v4.3 | [housing-stat.ch/catalog](https://www.housing-stat.ch/catalog/en/4.3/final) |
| Canton Zurich Methodology | Seiler & Seiler GmbH, Dec 2020 — [are.zh.ch](https://are.zh.ch/) |
| DM.01-AV-CH Data Model | [cadastre-manual.admin.ch](https://www.cadastre-manual.admin.ch/de/datenmodell-der-amtlichen-vermessung-dm01-av-ch) |

---

## Future Development

| Feature | Description |
|---------|-------------|
| Watertight 3D mesh | Generate closed building geometry from elevation data |
| Roof geometry estimation | Classify roof shapes (flat, gable, hip) and estimate roof surface areas |
| Outer wall quantities | Estimate exterior wall areas from footprint perimeter and height metrics |
| Material classification | Building material detection from imagery or other data sources |
| International buildings | Extend beyond Switzerland using alternative elevation and cadastral data |
| Eaves-height floor count | Use `elevation_roof_min − elevation_base_min` (≈ eaves height for pitched roofs) as the input to floor counting instead of `height_minimal`. Equivalent for flat roofs, more accurate for SFH/MFH with attics: `height_minimal` sits between eaves and ridge and slightly over-counts floors. Cheap to add as an extra `height_eaves_m` column in Step 3. |
| Voxel-slice GFA estimation | Replace `footprint × floors` with horizontal slab integration over the per-cell heightfield: for each slab `k`, count cells where building height ≥ slab ceiling, multiply by cell area, sum across slabs. Naturally handles setbacks, attics, towers, dormers, and stepped buildings — cases where the current method silently overcounts because it assumes every floor is the full footprint. Open questions to investigate: (1) cell-qualification rule (strict vs. centerline vs. tunable threshold for partial floors), (2) sensitivity to the assumed floor height, (3) handling of trees-over-buildings noise, (4) per-floor slab areas in the output as a JSON column. Should be opt-in via `--gfa-method slice` and validated against buildings with known drawings before becoming the default. |

---

## Tech Stack & Credits

### Web App

| Library | Version | Purpose |
|---------|---------|---------|
| [MapLibre GL JS](https://maplibre.org/) | 4.7 | Interactive map with 3D fill-extrusion rendering |
| [GeoTIFF.js](https://geotiffjs.github.io/) | 2.1 | Cloud Optimized GeoTIFF (COG) reading in-browser |
| [Turf.js](https://turfjs.org/) | 7 | Spatial operations (point-in-polygon, distance, centroid) |
| [proj4js](http://proj4js.org/) | 2.12 | Coordinate transforms (WGS84 ↔ LV95/EPSG:2056) |
| [SheetJS (XLSX)](https://sheetjs.com/) | 0.18 | Excel import/export (lazy-loaded) |
| [Source Sans 3](https://fonts.google.com/specimen/Source+Sans+3) | — | Typography |
| [Material Symbols](https://fonts.google.com/icons) | — | UI icons |

### Python CLI

| Library | Purpose |
|---------|---------|
| [GeoPandas](https://geopandas.org/) | Vector geodata processing |
| [Rasterio](https://rasterio.readthedocs.io/) | GeoTIFF reading with windowed access |
| [Shapely](https://shapely.readthedocs.io/) | Geometry operations, minimum rotated rectangle |
| [NumPy](https://numpy.org/) | Vectorized grid creation and elevation sampling |
| [pyproj](https://pyproj4.github.io/pyproj/) | CRS transforms |

### Data Sources

| Provider | Dataset | Usage |
|----------|---------|-------|
| [swisstopo](https://www.swisstopo.admin.ch/) | swissALTI3D, swissSURFACE3D | Terrain (DTM) and surface (DSM) elevation models at 0.5m resolution |
| [geodienste.ch](https://www.geodienste.ch/) | Amtliche Vermessung (AV) WFS | Building footprints from official cadastral survey |
| [BFS](https://www.bfs.admin.ch/) | GWR (Gebäude- und Wohnungsregister) | Building classification, construction year, floor count |
| [CARTO](https://carto.com/) | Positron, Dark Matter | Basemap tiles |

### Methodology

Floor area estimation is based on the methodology developed by Seiler & Seiler GmbH (Dec 2020) for the [Canton of Zurich ARE](https://are.zh.ch/).

---

## License

MIT License — see [LICENSE](LICENSE).
