# Swiss Building Volume & Area Estimator

![Python](https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![swisstopo](https://img.shields.io/badge/data-swisstopo-red)
![CRS](https://img.shields.io/badge/CRS-LV95%20EPSG%3A2056-orange)

Estimates building volumes and gross floor areas using publicly available Swiss elevation models and cadastral data.

<p align="center">
  <img src="images/Preview_2.jpg" width="45%" />
  <img src="images/Preview_3.jpg" width="45%" />
</p>
<p align="center">
  <img src="images/Preview_4.jpg" width="70%" />
</p>

---

## Model Overview

```mermaid
flowchart TD
    subgraph INPUT
        A1[Building input<br><i>CSV coordinates or geodata footprints</i>]
        A2[swissALTI3D tiles<br><i>terrain DTM, 0.5m</i>]
        A3[swissSURFACE3D tiles<br><i>surface DSM, 0.5m</i>]
    end

    A1 --> S1
    A2 --> S3
    A3 --> S3

    S1["<b>Step 1 — Read Footprints</b><br>CSV: buffer points to 10×10 m<br>Geodata: load building polygons<br>Reprojected to LV95"]
    S2["<b>Step 2 — Aligned 1×1m Grid</b><br>Minimum rotated rectangle orientation<br>Grid points filtered to footprint"]
    S3["<b>Step 3 — Volume & Heights</b><br>Sample DTM + DSM at each point<br>Volume = Σ max(surface_i − terrain_i, 0) × 1m²"]
    S4["<b>Step 4 — Floor Areas</b> <i>(optional)</i><br>GWR classification → floor height<br>Floors = height_minimal / floor_height<br>GFA = footprint × floors"]

    S1 --> S2 --> S3 --> S4

    S3 --> OUT
    S4 -.->|--estimate-area| OUT

    OUT[/"<b>Output CSV</b><br>volume, heights, elevations<br>+ floor areas if enabled"/]

    subgraph GWR["GWR Data <i>(optional)</i>"]
        G1[CSV bulk download<br><i>housing-stat.ch</i>]
        G2[swisstopo API<br><i>per EGID</i>]
    end

    GWR -.-> S4
```

---

## Command-Line Reference

| Argument | Required | Description |
|----------|:--------:|-------------|
| **Input** (mutually exclusive) | | |
| `--coordinates FILE` | one of | CSV with `id`, `lon`, `lat` columns (WGS84); optionally `egid` |
| `--footprints FILE` | one of | Geodata file with building polygons (GeoPackage, Shapefile, or GeoJSON from AV) |
| **Elevation data** | | |
| `--alti3d DIR` | yes | Directory with swissALTI3D GeoTIFF tiles |
| `--surface3d DIR` | yes | Directory with swissSURFACE3D GeoTIFF tiles |
| `--auto-fetch` | | Automatically download missing tiles from swisstopo |
| **Output** | | |
| `-o, --output FILE` | | Output CSV file path (default: `data/output/result_<timestamp>.csv`) |
| **Filters** | | |
| `-l, --limit N` | | Process only the first N buildings |
| `-b, --bbox MIN_LON MIN_LAT MAX_LON MAX_LAT` | | Bounding box filter in WGS84 (only with `--footprints`) |
| **Area estimation** (off by default) | | |
| `--estimate-area` | | Enable Step 4: floor area estimation |
| `--gwr-csv FILE` | | GWR CSV from [housing-stat.ch](https://www.housing-stat.ch/de/data/supply/public.html); if omitted, uses swisstopo API |

---

## Examples

### Setup

```bash
pip install -r python/requirements.txt
```

### Example 1 — Estimate volumes for a list of buildings (CSV)

You have a CSV with building coordinates (e.g. exported from a portfolio system).
The tool buffers each point into a 10x10 m sampling polygon, fetches the elevation
tiles it needs, and outputs volume and height metrics:

```csv
id,lon,lat,egid
1,8.5391,47.3769,1234567
2,8.5010,47.3925,
3,7.4474,46.9480,9876543
```

The `egid` column is optional — when provided, it enables GWR enrichment in Step 4.

```bash
python python/main.py \
    --coordinates my_buildings.csv \
    --alti3d data/swissalti3d \
    --surface3d data/swisssurface3d \
    --auto-fetch \
    -o portfolio_volumes.csv
```

Add `--estimate-area` with a GWR CSV to also get floor area estimates:

```bash
python python/main.py \
    --coordinates my_buildings.csv \
    --alti3d data/swissalti3d \
    --surface3d data/swisssurface3d \
    --auto-fetch \
    --estimate-area --gwr-csv data/gwr/buildings.csv \
    -o portfolio_full.csv
```

For small datasets (< 100 buildings) without a GWR CSV, the tool can query the
swisstopo REST API per building instead:

```bash
python python/main.py \
    --coordinates my_buildings.csv \
    --alti3d data/swissalti3d \
    --surface3d data/swisssurface3d \
    --auto-fetch \
    --estimate-area
```

### Example 2 — Process all buildings in Switzerland (AV footprints)

Download the full Amtliche Vermessung dataset from
[geodienste.ch](https://www.geodienste.ch/services/av) as a GeoPackage, and the
complete swissALTI3D + swissSURFACE3D tile sets from swisstopo. Then run:

```bash
python python/main.py \
    --footprints data/av/ch_av_2056.gpkg \
    --alti3d /data/swisstopo/swissalti3d \
    --surface3d /data/swisstopo/swisssurface3d \
    --estimate-area --gwr-csv data/gwr/buildings.csv \
    -o results/ch_all_buildings.csv
```

This processes ~2.5 million buildings. For a first test run, limit to a small batch:

```bash
python python/main.py \
    --footprints data/av/ch_av_2056.gpkg \
    --alti3d /data/swisstopo/swissalti3d \
    --surface3d /data/swisstopo/swisssurface3d \
    --limit 100
```

To process a specific region (e.g. City of Bern), use a bounding box filter:

```bash
python python/main.py \
    --footprints data/av/ch_av_2056.gpkg \
    --alti3d /data/swisstopo/swissalti3d \
    --surface3d /data/swisstopo/swisssurface3d \
    --bbox 7.40 46.93 7.48 46.97 \
    --estimate-area --gwr-csv data/gwr/buildings.csv \
    -o results/bern_buildings.csv
```

### Example 3 — Quick test with auto-fetch

No local elevation data needed — the tool downloads tiles on-the-fly from swisstopo:

```bash
python python/main.py \
    --coordinates my_buildings.csv \
    --alti3d data/swissalti3d \
    --surface3d data/swisssurface3d \
    --auto-fetch \
    --limit 10
```

---

## Inputs

### Required Data

| Data | Format | Required | Download | Description |
|------|--------|:--------:|----------|-------------|
| Building input | `.csv` or geodata | yes | — | CSV with coordinates (`--coordinates`) or GeoPackage/Shapefile (`--footprints`) |
| swissALTI3D | GeoTIFF tiles (0.5 m) | yes | [swisstopo.admin.ch](https://www.swisstopo.admin.ch/de/hoehenmodell-swissalti3d) | Terrain elevation model (DTM). Can be auto-downloaded with `--auto-fetch`. |
| swissSURFACE3D Raster | GeoTIFF tiles (0.5 m) | yes | [swisstopo.admin.ch](https://www.swisstopo.admin.ch/de/hoehenmodell-swisssurface3d-raster) | Surface elevation model (DSM). Can be auto-downloaded with `--auto-fetch`. |
| GWR (Federal Register of Buildings) | `.csv` | with `--estimate-area` | [housing-stat.ch/data](https://www.housing-stat.ch/de/data/supply/public.html) | Building classification for floor height lookup. Falls back to swisstopo API per EGID if omitted. |

### Input Columns (CSV mode)

Expected columns in the user-provided buildings CSV (`--coordinates`).

| Column | Required | Description |
|--------|----------|-------------|
| `id` | yes | Building ID — preserved as `id` in output |
| `lon` | yes | WGS84 longitude |
| `lat` | yes | WGS84 latitude |
| `egid` | no | Federal building ID — mapped to `av_egid` for GWR enrichment |

When using `--footprints`, the tool reads building polygons directly from the geodata file. The `egid` column (if present) is mapped to `av_egid`. Building type filtering (`Gebaeude`) is applied automatically.

---

## Outputs

All results are written to a single CSV file (`result_<timestamp>.csv`).

### Step 1 — Footprints

- **CSV mode** (`--coordinates`): Buffers each point into a 10×10 m sampling polygon and reprojects to LV95. The `id` column is preserved; `egid` is mapped to `av_egid`.
- **Geodata mode** (`--footprints`): Loads building polygons directly, filters to buildings (`Gebaeude`), and ensures LV95 projection. The `egid` column is mapped to `av_egid`; a `fid` is assigned from the source feature ID.

| Column | Format | Required | Source | Description |
|--------|--------|:--------:|--------|-------------|
| `area_footprint_m2` | float | yes | Computed | Footprint area from polygon geometry (m²) |
| `status_step1` | string | yes | Computed | `ok` |

### Step 2 — Grid

Generates a building-oriented 1×1m sampling grid aligned to the minimum rotated rectangle of the footprint. No columns added to output CSV — grid points are consumed internally by Step 3.

<p align="center">
  <img src="images/Oriented_Grid.jpg" width="70%" />
</p>

### Step 3 — Volume & Heights

Samples DTM and DSM elevations at each grid point to compute above-ground volume and height metrics.

| Column | Format | Required | Source | Description |
|--------|--------|:--------:|--------|-------------|
| `volume_above_ground_m3` | float | yes | DTM + DSM | Above-ground volume: `Σ max(surface_i − terrain_i, 0) × 1m²` |
| `elevation_base_m` | float | yes | DTM | Lowest terrain point under footprint (m asl) — reference datum |
| `elevation_roof_base_m` | float | yes | DSM | Lowest surface point in footprint — estimated eave (m asl) |
| `height_mean_m` | float | yes | DTM + DSM | Mean above-ground building height (m) |
| `height_max_m` | float | yes | DTM + DSM | Max above-ground building height — ridge (m) |
| `height_minimal_m` | float | yes | Computed | `volume / footprint_area` — equivalent uniform box height (m) |
| `grid_points_count` | integer | yes | Computed | Number of valid elevation sample points |
| `status_step3` | string | yes | Computed | `success` / `skipped` / `no_grid_points` / `no_height_data` / `error` |

### Step 4 — Floor Areas _(optional, `--estimate-area`)_

Estimates gross floor area from GWR building classification and `height_minimal_m`. Based on the [Canton Zurich methodology](https://are.zh.ch/) (Seiler & Seiler, 2020). Floor height lookup priority: GKLAS → GKAT → default 2.70–3.30 m.

| Column | Format | Required | Source | Description |
|--------|--------|:--------:|--------|-------------|
| `gkat` | integer | no, from GWR | GWR | Building category code |
| `gklas` | integer | no, from GWR | GWR | Building class code |
| `gbauj` | integer | no, from GWR | GWR | Construction year |
| `gastw` | integer | no, from GWR | GWR | Number of stories |
| `floor_height_used_m` | float | yes | Lookup | Floor height applied (m) |
| `floors_estimated` | float | yes | Computed | Estimated floor count |
| `area_floor_total_m2` | float | yes | Computed | Gross floor area — `footprint × floors` (m²) |
| `area_accuracy` | string | yes | Computed | `high` (±10–15%) / `medium` (±15–25%) / `low` (±25–40%) |
| `building_type` | string | yes | Lookup | Building type description from floor height lookup (e.g. `Single-family house`) |
| `status_step4` | string | yes | Computed | `success` / `skipped` / `no_volume` / `height_exceeds_200m` |

---

## Limitations

| Limitation | Detail |
|------------|--------|
| No underground estimation | LIDAR captures above-ground only; basements not included |
| Surface class merging | swissSURFACE3D merges ground, vegetation, buildings; trees over small buildings may cause overestimation |
| Small buildings | Footprints < 1 m² produce no grid points |
| Mixed-use buildings | Single floor height applied; actual heights may vary by floor |
| Industrial / special | Wide floor height ranges (4–7 m) reduce accuracy |
| Data currency | Elevation model year may not match building construction date |
| Roof base estimation | `elevation_roof_base_m` may capture ground features (overhangs, passages) instead of true eave |
| Tree canopy over roofs | LIDAR surface model does not differentiate between roofs and foliage — tall trees covering small buildings produce false positive heights and inflated volumes |

---

## Future Development

| Feature | Description |
|---------|-------------|
| Watertight 3D mesh | Generate closed building geometry from elevation data. swisstopo provides an official 3D buildings dataset (swissBUILDINGS3D), but quality varies significantly between buildings. |
| Roof geometry estimation | Classify roof shapes (flat, gable, hip, etc.) and estimate roof surface areas from 3D mesh or elevation profiles. |
| Outer wall quantities | Estimate exterior wall areas from building footprint perimeter and height metrics. |
| Material classification | Investigate building material detection from imagery or other data sources — expected to be challenging. |
| International buildings | Extend support beyond Switzerland. The Swiss federal real estate portfolio includes buildings worldwide, requiring alternative elevation and cadastral data sources. |

---

## Project Structure

```
area-estimator/
├── python/                            ← unified pipeline (Steps 1–4)
│   ├── main.py                           CLI entry point
│   ├── footprints.py                     Step 1: load footprints / coordinates
│   ├── grid.py                           Step 2: aligned 1×1m grid
│   ├── volume.py                         Step 3: elevation sampling & volume
│   ├── tile_fetcher.py                   On-demand tile download from swisstopo
│   ├── gwr.py                            GWR lookup (CSV + API)
│   ├── area.py                           Step 4: floor area estimation
│   └── requirements.txt
├── fme/                              ← FME workbench (same as python, requires license)
├── tools/
│   ├── roof-estimator/               ← roof shape analysis from 3D meshes
│   └── green-roof-eval/              ← green roof detection (FME-based)
├── legacy/                            ← original implementations (reference)
│   ├── volume-estimator/
│   ├── area-estimator/
│   ├── base-worker/
│   └── swisstopo3d-volume_DEPRECATED/
├── data/                              ← .gitignored
│   ├── output/                           pipeline results CSV + logs
│   ├── gwr/                              GWR CSV download
│   ├── swissalti3d/                      terrain tiles
│   └── swisssurface3d/                   surface tiles
└── images/
```

---

## Floor Height Lookup

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
| swisstopo STAC API | [data.geo.admin.ch/api/stac/v1](https://data.geo.admin.ch/api/stac/v1/) |
| STAC API Docs | [geo.admin.ch/de/rest-schnittstelle-stac-api](https://www.geo.admin.ch/de/rest-schnittstelle-stac-api/) |
| swisstopo Search API | [docs.geo.admin.ch](https://docs.geo.admin.ch/access-data/search.html) |
| GWR | [housing-stat.ch](https://www.housing-stat.ch/de/index.html) |
| GWR Public Data | [housing-stat.ch/data](https://www.housing-stat.ch/de/data/supply/public.html) |
| GWR Catalog v4.3 | [housing-stat.ch/catalog](https://www.housing-stat.ch/catalog/en/4.3/final) |
| Canton Zurich Methodology | Seiler & Seiler GmbH, Dec 2020 — [are.zh.ch](https://are.zh.ch/) |
| DM.01-AV-CH Data Model | [cadastre-manual.admin.ch](https://www.cadastre-manual.admin.ch/de/datenmodell-der-amtlichen-vermessung-dm01-av-ch) |

---

## License

MIT License — see [LICENSE](LICENSE).
