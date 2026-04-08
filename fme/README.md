# FME Volume Estimator

[`Volume Estimator FME.fmw`](Volume%20Estimator%20FME.fmw) is an FME workbench that performs the same building volume estimation as the [Python pipeline](../python/) — Steps 1 through 3 (footprint loading, aligned grid, volume + height calculation). Built with [FME Form](https://fme.safe.com/fme-form/) 2025.0.3.0 and last saved 2026-03-10.

> **License notice:** FME requires a commercial license from [Safe Software](https://fme.safe.com/). The [Python CLI](../python/) provides the same functionality (plus Step 4 floor-area estimation, which is not implemented in this workbench) without any license requirement.

---

## Pipeline overview

The workbench is a 70+ transformer chain that mirrors the Python pipeline conceptually:

| Python step | FME equivalent |
|---|---|
| **Step 1** — Load AV footprints | `FeatureReader` × 6 to load AV polygons + `swissALTI3D` and `swissSURFACE3D-raster` tile catalogs from CSV. `Reprojector` to LV95 (EPSG:2056). |
| **Step 2** — Aligned grid generation | `BoundingBoxReplacer` + `CenterPointExtractor` + `Rotator` × 2 + `Tiler` × 2 + `Clipper` + `CenterPointReplacer`. Same minimum-rotated-rectangle alignment logic as the Python `create_aligned_grid_points`, expressed as a transformer chain. |
| **Step 3** — Sample DTM/DSM and compute volume | `RasterMosaicker` × 2 (combine tiles) + `PointOnRasterValueExtractor` × 2 (sample DTM and DSM at each grid point) + `StatisticsCalculator` (base/roof elevation min/mean/max) + `Extruder` (turn samples into 3D extrusions) + `VolumeCalculator` (sum to volume). |
| **Output** | `AttributeRounder` + `AttributeKeeper` + `FeatureWriter`. |
| ~~Step 4~~ — Floor area estimation | **Not implemented in this workbench.** Use the Python CLI with `--estimate-area` for GWR-based floor area estimation. |

The HTTP-based tile fetching (analogous to `tile_fetcher.py` in Python) is handled by `HTTPCaller` × 2 transformers that download missing GeoTIFFs from `data.geo.admin.ch` on demand.

---

## Inputs

| Reader | Source |
|---|---|
| swissALTI3D tiles | swissALTI3D-raster CSV catalog (`ch.swisstopo.swissalti3d-…csv`) |
| swissSURFACE3D tiles | swissSURFACE3D-raster CSV catalog (`ch.swisstopo.swisssurface3d-raster-…csv`) |
| AV building polygons | Two `FeatureReader` instances driven by `@Value(path_windows)` parameters — see workbench user parameters |

The CSV catalogs are swisstopo's tile-index files, listing every available tile and its download URL. The workbench reads them, filters to the tiles intersecting the input building bbox, and downloads them via `HTTPCaller`.

---

## Optional database connection

The workbench includes a `Supabase Dav` PostgreSQL connection (declared in the `<CONNECTIONS>` block of the `.fmw`). This appears to be intended for results storage but is not required to run the volume estimation pipeline itself.

---

## Running the workbench

```cmd
"C:\Program Files\FME\fme.exe" "Volume Estimator FME.fmw" --FME_LAUNCH_VIEWER_APP "YES"
```

Or open it in FME Workbench (the GUI editor) and click Run. Configure the AV input path via the `path_windows` user parameter.

---

## When to use FME vs the Python CLI

| | Python CLI | FME workbench |
|---|---|---|
| **License** | Free (MIT) | Commercial (FME Form) |
| **Floor area estimation** | ✓ Step 4 with GWR enrichment | ✗ Steps 1–3 only |
| **Aggregation** | ✓ Multi-EGID, multi-polygon array form | ✗ |
| **Test coverage** | ✓ pytest suite | ✗ |
| **Visual debugging** | Logs + CSV output | ✓ FME Inspector + visual transformer chain |
| **Custom branching / GUI editing** | ✗ (requires Python edits) | ✓ Drag-and-drop transformer editor |
| **Throughput** | Hundreds of buildings per minute (parallel GWR) | Comparable for the volume step |

The Python CLI is the recommended path unless you specifically need FME's visual debugging or want to extend the workbench with custom transformers. If you have FME and want a GUI to inspect intermediate results step-by-step, the workbench is useful for understanding what the pipeline does.
