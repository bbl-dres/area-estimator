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
        A1[Building footprints<br><i>GeoPackage / Shapefile / GeoJSON / CSV</i>]
        A2[swissALTI3D tiles<br><i>terrain DTM, 0.5m</i>]
        A3[swissSURFACE3D tiles<br><i>surface DSM, 0.5m</i>]
    end

    A1 --> S1
    A2 --> S3
    A3 --> S3

    S1["<b>Step 1 — Read Footprints</b><br>Geodata: read + filter to buildings<br>CSV: buffer points to 10×10 m<br>GeoJSON + AV: spatial containment match<br>All reprojected to LV95"]
    S2["<b>Step 2 — Aligned 1×1m Grid</b><br>Minimum rotated rectangle orientation<br>Grid points filtered to footprint"]
    S3["<b>Step 3 — Volume & Heights</b><br>Sample DTM + DSM at each point<br>Volume = Σ max(surface − base, 0) × 1m²"]
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
| **Input** (one required) | | |
| `--footprints FILE` | * | Geodata file (`.gpkg`, `.shp`, `.geojson`) from Amtliche Vermessung |
| `--coordinates FILE` | * | CSV with `lon`, `lat` columns (WGS84), optionally `egid`, `fid` |
| `--geojson FILE` | * | GeoJSON with building addresses (Point + EGID) — requires `--av` |
| **Elevation data** | | |
| `--alti3d DIR` | yes | Directory with swissALTI3D GeoTIFF tiles |
| `--surface3d DIR` | yes | Directory with swissSURFACE3D GeoTIFF tiles |
| `--auto-fetch` | | Automatically download missing tiles from swisstopo |
| **AV lookup** (for `--geojson`) | | |
| `--av FILE` | with `--geojson` | AV GeoPackage (e.g. `av_2056.gpkg`) for footprint lookup |
| `--av-layer NAME` | | AV layer name (default: `lcsf`) |
| **Output** | | |
| `-o, --output FILE` | | Output CSV file path (default: `data/output/result_<timestamp>.csv`) |
| **Filters** | | |
| `-l, --limit N` | | Process only the first N buildings |
| `-b, --bbox MINLON MINLAT MAXLON MAXLAT` | | Bounding box in WGS84 (only with `--footprints`) |
| **Area estimation** (off by default) | | |
| `--estimate-area` | | Enable Step 4: floor area estimation |
| `--gwr-csv FILE` | | GWR CSV from [housing-stat.ch](https://www.housing-stat.ch/de/data/supply/public.html); if omitted, uses swisstopo API |

---

## Examples

```bash
pip install -r python/requirements.txt
```

Minimal run — volume and heights only from a cadastral survey file:
```bash
python python/main.py \
    --footprints data/land_cover.gpkg \
    --alti3d data/swissalti3d \
    --surface3d data/swisssurface3d
```

From a CSV of coordinates, with auto-fetch and floor area estimation:
```bash
python python/main.py \
    --coordinates my_buildings.csv \
    --alti3d data/swissalti3d \
    --surface3d data/swisssurface3d \
    --auto-fetch \
    --estimate-area --gwr-csv data/gwr/buildings.csv \
    -o results.csv
```

From a GeoJSON address list, resolved against an AV file:
```bash
python python/main.py \
    --geojson addresses.geojson \
    --av data/av_2056.gpkg \
    --alti3d data/swissalti3d \
    --surface3d data/swisssurface3d \
    --auto-fetch \
    --estimate-area --gwr-csv data/gwr/buildings.csv \
    -o results.csv
```

---

## Inputs

### Required Data

| Data | Format | Required | Description |
|------|--------|:--------:|-------------|
| Building footprints | `.gpkg` / `.shp` / `.geojson` / `.csv` | yes | One of: AV geodata (`--footprints`), WGS84 coordinate CSV (`--coordinates`), or GeoJSON points with AV lookup (`--geojson` + `--av`) |
| swissALTI3D | GeoTIFF tiles (0.5 m) | yes | Terrain elevation model (DTM) — [swisstopo](https://www.swisstopo.admin.ch/de/hoehenmodell-swissalti3d). Can be auto-downloaded with `--auto-fetch`. |
| swissSURFACE3D | GeoTIFF tiles (0.5 m) | yes | Surface elevation model (DSM) — [swisstopo](https://www.swisstopo.admin.ch/de/hoehenmodell-swisssurface3d-raster). Can be auto-downloaded with `--auto-fetch`. |
| AV GeoPackage | `.gpkg` | with `--geojson` | Cadastral survey footprints for spatial containment lookup — [geodienste.ch](https://www.geodienste.ch/services/av) |
| GWR CSV | `.csv` | with `--estimate-area` | Building classification from [housing-stat.ch](https://www.housing-stat.ch/de/data/supply/public.html). Falls back to swisstopo API per EGID if omitted. |

### Input Columns

**`--footprints`** (geodata file)

| Column | Description |
|--------|-------------|
| `egid` | Federal building ID (optional, auto-set to `None` if missing) |
| `fid` | Feature ID (optional, defaults to row index) |
| `geometry` | Building polygon |
| `flaeche` / `area` / `shape_area` | Official footprint area in m² (optional, first match used) |
| `bbart` / `art` / `type` / `objektart` | Building type — used to filter to `Gebaeude` (optional) |

**`--coordinates`** (CSV)

| Column | Description |
|--------|-------------|
| `lon` / `longitude` / `lng` / `x` | WGS84 longitude (required) |
| `lat` / `latitude` / `y` | WGS84 latitude (required) |
| `egid` | Federal building ID (optional) |
| `fid` | Feature ID (optional, defaults to row index) |

**`--geojson`** (GeoJSON points)

| Column | Description |
|--------|-------------|
| `geometry` | Point geometry in WGS84 (required) |
| `bbl_id` | Building address ID → mapped to `input_id` (optional, defaults to feature index) |
| `egid` | Reference EGID → mapped to `input_egid` (optional, authoritative EGID comes from AV) |

---

## Outputs

All results are written to a single CSV file (`result_<timestamp>.csv`).

### Step 1 — Footprints

Resolves building polygons from [Amtliche Vermessung](https://www.geodienste.ch/services/av) and reprojects to LV95 (EPSG:2056).

| Column | Format | Status | Source | Description |
|--------|--------|:------:|--------|-------------|
| `egid` | integer | OPTIONAL | AV / Input | Federal building ID — from AV (`GWR_EGID`) or input data; `None` if unavailable |
| `fid` | integer | MUST | AV / Input | Feature ID — from GeoPackage or input data; defaults to row index if missing |
| `area_footprint_m2` | float | MUST | Computed | Footprint area from polygon geometry (m²) |
| `area_official_m2` | float | OPTIONAL | AV | Official area from source attribute (m²) |

### Step 2 — Grid

Generates a building-oriented 1×1m sampling grid aligned to the minimum rotated rectangle of the footprint. No columns added to output CSV — grid points are consumed internally by Step 3.

<p align="center">
  <img src="images/grid_alignment.svg" width="700" alt="Axis-aligned vs building-aligned grid comparison" />
</p>

### Step 3 — Volume & Heights

Samples DTM and DSM elevations at each grid point to compute above-ground volume and height metrics.

| Column | Format | Status | Source | Description |
|--------|--------|:------:|--------|-------------|
| `volume_above_ground_m3` | float | MUST | DTM + DSM | Above-ground volume: `Σ max(surface − base, 0) × 1m²` |
| `elevation_base_m` | float | MUST | DTM | Lowest terrain point under footprint (m asl) — height reference |
| `elevation_roof_base_m` | float | MUST | DSM | Lowest surface point in footprint — estimated eave (m asl) |
| `height_mean_m` | float | MUST | DTM + DSM | Mean building height above base (m) |
| `height_max_m` | float | MUST | DTM + DSM | Max building height above base — ridge (m) |
| `height_minimal_m` | float | MUST | Computed | `volume / footprint_area` — equivalent uniform box height (m) |
| `grid_points_count` | integer | MUST | Computed | Number of valid elevation sample points |
| `status` | string | MUST | Computed | `success` / `no_building_at_point` / `no_grid_points` / `no_height_data` / `error` |

### Step 4 — Floor Areas _(optional, `--estimate-area`)_

Estimates gross floor area from GWR building classification and `height_minimal_m`. Based on the [Canton Zurich methodology](https://are.zh.ch/) (Seiler & Seiler, 2020). Floor height lookup priority: GKLAS → GKAT → default 2.70–3.30 m.

| Column | Format | Status | Source | Description |
|--------|--------|:------:|--------|-------------|
| `gkat` | integer | OPTIONAL | GWR | Building category code |
| `gklas` | integer | OPTIONAL | GWR | Building class code |
| `gbauj` | integer | OPTIONAL | GWR | Construction year |
| `gastw` | integer | OPTIONAL | GWR | Number of stories |
| `floor_height_used_m` | float | OPTIONAL | Lookup | Floor height applied (m) |
| `floors_estimated` | float | OPTIONAL | Computed | Estimated floor count |
| `area_floor_total_m2` | float | OPTIONAL | Computed | Gross floor area — `footprint × floors` (m²) |
| `area_accuracy` | string | OPTIONAL | Computed | `high` (±10–15%) / `medium` (±15–25%) / `low` (±25–40%) |
| `building_type` | string | OPTIONAL | Lookup | Building type description from floor height lookup (e.g. `Single-family house`) |

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
├── plugins/
│   ├── roof-estimator/               ← roof shape analysis from 3D meshes
│   └── biodiversity-estimator/       ← biodiversity metrics (planned)
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

Canton Zurich methodology (Seiler & Seiler, 2020). GF = ground floor, UF = upper floors.

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
