# Swiss Building Volume & Area Estimator

Estimate building volumes and gross floor areas from publicly available Swiss elevation models (swissALTI3D / swissSURFACE3D) and cadastral data (Amtliche Vermessung + GWR).

<!-- The hero image is clickable and opens the live app -->
[![Swiss Building Volume & Area Estimator — click to open the live app](assets/Social1.jpg)](https://bbl-dres.github.io/area-estimator/)

[![Demo on GitHub Pages](https://img.shields.io/badge/demo-GitHub%20Pages-2ea44f?logo=github&logoColor=white)](https://bbl-dres.github.io/area-estimator/)
![License](https://img.shields.io/badge/license-MIT-lightgrey)
![Python](https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white)
![MapLibre](https://img.shields.io/badge/maplibre-4.7-blue)
![swisstopo](https://img.shields.io/badge/data-swisstopo-red)
![CRS](https://img.shields.io/badge/CRS-LV95%20EPSG%3A2056-orange)

> [!TIP]
> **Try it now — open the live web app:** https://bbl-dres.github.io/area-estimator/
>
> No installation needed; it runs entirely in your browser.

## What is this?

Estimate the above-ground **volume** and **gross floor area** of Swiss buildings from public elevation and cadastral data. Provide a list of buildings (by EGID), and for each one the tool loads its footprint, samples terrain (DTM) and surface (DSM) elevations on an orientation-aligned grid, computes volume and heights, looks up the building's GWR classification, and converts that into an estimated floor count and gross floor area.

All processing works in CRS LV95 (EPSG:2056).

<p align="center">
  <img src="assets/Preview_2.jpg" width="45%" style="vertical-align: top;"/>
  <img src="assets/Preview_3.jpg" width="45%" style="vertical-align: top;"/>
</p>
<p align="center">
  <img src="assets/Preview_4.jpg" width="70%" />
</p>

## Solutions

The same estimation is available three ways. Each has its own README with full details.

### Web App

Zero-install browser app: upload a CSV of building EGIDs and explore volumes, heights, and floor-area estimates on an interactive 3D map, with export to CSV/Excel/GeoJSON.

- **Preview:** https://bbl-dres.github.io/area-estimator/
- **Source code:** [`webapp/`](webapp/) (entry point [`index.html`](index.html) at the repo root)

<p align="center">
  <img src="assets/Preview_2.jpg" width="45%" style="vertical-align: top;"/>
  <img src="assets/Preview_3.jpg" width="45%" style="vertical-align: top;"/>
</p>
<p align="center">
  <img src="assets/Preview_4.jpg" width="70%" />
</p>


---

### Python CLI

Open-source command-line tool for local, offline processing with exact planar (LV95) areas, a 1×1 m grid, local elevation tiles, and optional GWR-based floor-area estimation.

- **Preview:** command-line tool — run locally (no hosted demo)
- **Source code:** [`python/`](python/)

---

### FME

The FME Form workspace (`.fmw`) implementing the volume pipeline (Steps 1–3) that the other two solutions reproduce.

- **Preview:** requires [FME Form](https://fme.safe.com/fme-form/) (commercial licence)
- **Source code:** [`fme/`](fme/)

---

## Experimental tools

Standalone exploration tools that aren't part of the main pipeline. Each is independently runnable with its own README.

| Tool | Status | What it does |
|---|---|---|
| [`experimental/mesh-builder/`](experimental/mesh-builder/) | working | Watertight 3D building hulls from AV footprints + swisstopo DSM/DTM, with an in-browser three.js viewer |
| [`experimental/roof-shape-from-buildings3d/`](experimental/roof-shape-from-buildings3d/) | working | Per-building roof characteristics (area, slope, shape) from swissBUILDINGS3D meshes |
| [`experimental/green-roof-from-rs/`](experimental/green-roof-from-rs/) | working | Per-building green-roof coverage via NDVI on swissIMAGE-RS imagery |
| [`experimental/floor-level-estimator/`](experimental/floor-level-estimator/) | unmaintained | Earlier per-floor estimator with construction-period (gbaup) factor |

## Data & Documentation

> **Data coverage note:** Most cantons are available via the geodienste.ch WFS. Three cantons (JU, LU, VD) don't publish data there, so both the Web App and the Python CLI's `--use-api` mode fall back to swisstopo vec25 footprints (lower accuracy, ~2-year update cycle). Coverage can also be incomplete in TI and VS.

- **Data sources** — building geometry from the official cadastral survey [Amtliche Vermessung](https://www.geodienste.ch/services/av) (AV); building classification from the federal register [GWR](https://www.housing-stat.ch/); terrain and surface elevation from swisstopo [swissALTI3D](https://www.swisstopo.admin.ch/de/hoehenmodell-swissalti3d) and [swissSURFACE3D](https://www.swisstopo.admin.ch/de/hoehenmodell-swisssurface3d-raster). CRS: EPSG:2056 (CH1903+ / LV95).
- **[Technical Specification](docs/SPECIFICATION.md)** — the 4-step pipeline, AV vs GWR data model, limitations, methodology, and roadmap.
- **[Height Assumptions](docs/Height%20Assumptions.md)** — validation study behind the floor-height lookup table and accuracy buckets.

## Standards & References

| Resource | Link |
|----------|------|
| Amtliche Vermessung (AV) | [geodienste.ch/services/av](https://www.geodienste.ch/services/av) |
| swissALTI3D (terrain, DTM) | [swisstopo.admin.ch](https://www.swisstopo.admin.ch/de/hoehenmodell-swissalti3d) |
| swissSURFACE3D (surface, DSM) | [swisstopo.admin.ch](https://www.swisstopo.admin.ch/de/hoehenmodell-swisssurface3d-raster) |
| GWR (building register) | [housing-stat.ch](https://www.housing-stat.ch/de/index.html) |
| DM.01-AV-CH data model | [cadastre-manual.admin.ch](https://www.cadastre-manual.admin.ch/de/datenmodell-der-amtlichen-vermessung-dm01-av-ch) |
| Floor-area methodology | Seiler & Seiler GmbH (2020) for [Canton Zurich ARE](https://are.zh.ch/) |

## License

[MIT](LICENSE) — see [LICENSE](LICENSE).
