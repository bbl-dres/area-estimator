# Web App

Browser-based building volume & area estimator: upload a CSV of building EGIDs and get volumes, heights, and floor-area estimates on an interactive 3D map. Runs entirely client-side — no backend, no installation.

**Live app:** https://bbl-dres.github.io/area-estimator/

> The web app's entry point is [`index.html`](../index.html) at the **repo root** (so GitHub Pages serves it natively). This `webapp/` folder holds the CSS and JS modules it loads.

## How it works

Upload a CSV with `id` and `egid` columns; the app will:

1. Fetch building footprints from [geodienste.ch](https://geodienste.ch) WFS (`ms:LCSF`, filtered by `GWR_EGID`), with automatic [swisstopo vec25](https://api3.geo.admin.ch) fallback for cantons not on geodienste.ch
2. Load elevation data (DTM + DSM) from [swisstopo COG tiles](https://data.geo.admin.ch) on the fly
3. Compute volume and heights using an orientation-aligned 2×2 m grid
4. Look up building classification from [GWR](https://www.housing-stat.ch) via the swisstopo API
5. Estimate floor areas from building type and volume
6. Display results on an interactive map with table and summary panel

## Features

- **Interactive Map** — MapLibre GL JS with 3D building extrusions, orientation-aligned grid-cell visualization, 4 basemaps, scale bar
- **Layer Panel** — Toggle Gebäudegrundflächen, Gebäudevolumen, Rasterzellen, Beschriftungen, and AV cadastral overlay
- **Summary Panel** — Collapsible sections for building status, volume/height aggregates, and floor-area estimates
- **Table Widget** — Sortable columns, search filter, pagination, resizable panel, row click → map highlight
- **Export** — CSV, Excel (XLSX), and GeoJSON with timestamped filenames
- **Privacy** — All data stays in the browser. Only EGID and coordinates are sent to public APIs

## Run locally

Plain static files (ES modules, no build step). The entry `index.html` lives at the repo root and references `webapp/css/`, `webapp/js/`, and `data/example.csv` as siblings — so serve the **repo root**:

```bash
cd area-estimator
python -m http.server 8080
# Open http://localhost:8080
```

Or deploy the repo to any static host (GitHub Pages, Cloudflare Pages, etc.). GitHub Pages' "Deploy from a branch" mode only accepts the branch root or `/docs` as the publishing source — which is why the thin `index.html` sits at the root while the technical assets stay in `webapp/`.

## Limitations vs the Python CLI

| | Web App | Python CLI |
|---|---|---|
| **Data coverage** | All 26 cantons — WFS for most, automatic vec25 fallback for blocked cantons (JU, LU, VD) | All cantons via local GeoPackage or `--use-api` (same cascade) |
| **Elevation data** | On-the-fly COG tile loading from swisstopo CDN | Local GeoTIFF tiles (faster, offline) |
| **Grid resolution** | 2×2 m (configurable) | 1×1 m (configurable) |
| **Area calculation** | Spherical (Turf.js), ~0.1–0.5% error | Exact planar (LV95 / EPSG:2056) |
| **Throughput** | ~5 buildings in parallel, rate-limited | Bulk processing with local data |
| **EGID lookup** | Direct WFS filter by `GWR_EGID` | Local GeoPackage spatial join or API cascade |
| **Floor-area estimation** | ✓ | ✓ (`--estimate-area`) |
| **Offline** | Requires internet | Fully offline with local data |

> **Data coverage note:** Three cantons (JU, LU, VD) don't publish on geodienste.ch, so both the Web App and `--use-api` mode fall back to swisstopo vec25 footprints (lower accuracy, ~2-year update cycle). Coverage can also be incomplete in TI and VS.

## APIs used

| API | Purpose | Auth |
|-----|---------|------|
| `geodienste.ch/db/av_0/{lang}` WFS | Building footprints by EGID or BBOX (`ms:LCSF`) | None (CORS) |
| `api3.geo.admin.ch/MapServer/find` | GWR building attributes + coordinates by EGID | None (CORS) |
| `api3.geo.admin.ch/MapServer/identify` | vec25 building footprints — fallback for blocked cantons | None (CORS) |
| `data.geo.admin.ch` | swissALTI3D + swissSURFACE3D COG tiles | None (CORS) |

## Files

```
index.html        App entry point (at the repo root)
webapp/
  css/
    tokens.css     Design tokens (colors, spacing, typography)
    styles.css     Component styles + responsive breakpoints
  js/
    config.js      API endpoints, floor-height lookup, map styles, constants
    main.js        State machine (upload → processing → results)
    upload.js      CSV/XLSX parsing and validation (id + egid or lon/lat)
    processor.js   Footprint fetch → tile preload → volume/heights → floor area (parallel)
    elevation.js   LV95 projection, COG tile loading, elevation sampling, grid creation
    map.js         MapLibre map, 3D extrusions, basemaps, accordion menu, popups
    table.js       Results table (sortable, paginated, row → map selection)
    export.js      CSV/XLSX/GeoJSON export
```

## Tech stack

| Library | Version | Purpose |
|---------|---------|---------|
| [MapLibre GL JS](https://maplibre.org/) | 4.7 | Interactive map with 3D fill-extrusion rendering |
| [GeoTIFF.js](https://geotiffjs.github.io/) | 2.1 | Cloud Optimized GeoTIFF (COG) reading in-browser |
| [Turf.js](https://turfjs.org/) | 7 | Spatial operations (point-in-polygon, distance, centroid) |
| [proj4js](http://proj4js.org/) | 2.12 | Coordinate transforms (WGS84 ↔ LV95 / EPSG:2056) |
| [SheetJS (XLSX)](https://sheetjs.com/) | 0.18 | Excel import/export (lazy-loaded) |
| [Source Sans 3](https://fonts.google.com/specimen/Source+Sans+3) | — | Typography |
| [Material Symbols](https://fonts.google.com/icons) | — | UI icons |

For the full 4-step pipeline, data model, limitations, and methodology, see the [Technical Specification](../docs/SPECIFICATION.md).
