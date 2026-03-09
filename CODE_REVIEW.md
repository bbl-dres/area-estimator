# Code Review: Swiss Building Volume & Area Estimator

**Reviewer perspective:** Senior Python Developer, GIS & Cadastral Expert
**Date:** 2026-03-09

## Overall Assessment

This is a well-structured, domain-aware pipeline for estimating building volumes and floor areas from Swiss public geodata. The modular design (footprints → grid → volume → area) mirrors the conceptual workflow cleanly, and the code shows solid understanding of the Swiss cadastral ecosystem (AV, GWR, LV95, swisstopo services). The roof-estimator tool adds meaningful 3D mesh analysis capabilities.

**Rating: Strong foundation with actionable improvements needed.**

---

## Architecture & Design (Strong)

The 4-step pipeline is well-conceived:
- Step 1 (footprints) correctly abstracts three input modes behind a common GeoDataFrame interface
- Step 2 (tile check) separates data availability from processing
- Step 3 (volume) uses a clean grid-sampling approach that handles complex roof shapes naturally
- Step 4 (area) correctly applies the Canton Zurich methodology with appropriate uncertainty bounds

The separation between `volume.py` (geometry + raster) and `area.py` (classification + estimation) is the right boundary.

---

## Bugs & Correctness Issues

### BUG 1: `status` vs `status_step1` mismatch in `load_geojson_with_av`

**File:** `python/footprints.py:223`

`load_geojson_with_av` writes `"status"` to the row dict, but `main.py:164` filters on `"status_step1"`. This means **all GeoJSON+AV buildings will be treated as having no status_step1**, and the geometry check at line 164 will fail silently — no buildings will be processed.

```python
# footprints.py:223 — writes "status"
"status": "ok" if polygon else "no_building_at_point",

# main.py:164 — reads "status_step1"
with_geometry = buildings[buildings['status_step1'] == 'ok']
```

**Fix:** Change `"status"` to `"status_step1"` in `load_geojson_with_av`.

### BUG 2: `load_coordinates_from_csv` returns `'id'` and `'egid'` columns, but `main.py` expects `'av_egid'`

**File:** `python/footprints.py:137`

The CSV loader returns columns `['id', 'egid', ...]` but `main.py:225` accesses `row.get('av_egid')` and `main.py:227` accesses `row['area_official_m2']`. The `egid` column is never mapped to `av_egid`, so GWR enrichment in Step 4 will never match CSV-sourced buildings.

**Fix:** Rename `'egid'` to `'av_egid'` in the CSV loader, or add a mapping step.

### BUG 3: Negative coordinate tile ID calculation

**File:** `python/volume.py:91-94` and `python/tile_fetcher.py:39-41`

`int()` truncates toward zero in Python, not toward negative infinity. For coordinates near tile boundaries with negative values (not relevant for LV95 which is always positive, but the code doesn't validate this), `int(-0.5)` gives `0` instead of `-1`. While LV95 coordinates are always positive for Switzerland, this is a latent bug if the code is ever adapted.

More importantly, the tile ID calculation is **duplicated** between `TileIndex.get_required_tiles()` and `tile_fetcher.tile_ids_from_bounds()` with slightly different formatting (`{x:04d}` vs `{tx:04d}`). This is a DRY violation that could lead to divergence.

### BUG 4: `load_geojson_with_av` doesn't return consistent columns

**File:** `python/footprints.py:234`

Unlike the other two loaders that return a well-defined column set, `load_geojson_with_av` returns all columns from the `rows` list (including `input_id`, `input_egid`, `input_lon`, `input_lat`) without filtering. The function's docstring says it returns specific columns but doesn't enforce it via column selection like lines 92 and 137 do.

### BUG 5: `gable` azimuth check is unreachable

**File:** `tools/roof-estimator/python/roof_analysis.py:182`

```python
if 150 < azimuth_diff < 210:
```

Since `azimuth_diff` is normalized to `[0, 180]` on lines 179-180 (via `if azimuth_diff > 180: azimuth_diff = 360 - azimuth_diff`), the condition `azimuth_diff > 180` is impossible after normalization. The range check `(150, 210)` should be `(150, 180]`.

---

## GIS-Specific Issues

### ISSUE 6: Volume calculation base height assumption

**File:** `python/volume.py:244`

Using `base_height = np.min(valid_terrain)` means for buildings on a slope, the base reference is the lowest terrain point under the footprint. This inflates volume for hillside buildings because one side of the building doesn't actually extend to the lowest terrain point — it's built into the slope.

A more accurate approach for sloped terrain would be to compute heights per-point: `building_heights = np.maximum(valid_surface - valid_terrain, 0)`, which gives the true above-ground height at each grid cell. The current approach overestimates volume for any building with >1m terrain variation under its footprint.

### ISSUE 7: Green roof convex hull approximation

**File:** `tools/roof-estimator/python/main.py:311-313`

Using convex hull of all 3D mesh vertices projected to 2D will overestimate footprint area for L-shaped, U-shaped, and courtyard buildings. This is acknowledged in the comments but should at minimum log a warning, since the green roof percentage will be underestimated for concave buildings (correct area measured against inflated total).

### ISSUE 8: Building orientation for very small or degenerate polygons

**File:** `python/grid.py:22-39`

`minimum_rotated_rectangle` can return degenerate geometry (a line) for very narrow buildings. `get_building_orientation` doesn't handle this case — `exterior.coords` may have fewer than 4 distinct points, causing `np.argmax(edge_lengths)` to pick a degenerate edge.

### ISSUE 9: AV lookup is per-building with no spatial indexing

**File:** `python/footprints.py:140-174`

`_find_av_building_at_point` opens the GeoPackage and reads a bbox region **for every single input point**. For 1000+ buildings, this is extremely slow because fiona opens and closes the file each time. Consider loading the AV data once and using an STRtree index (like the roof estimator does for rasters).

### ISSUE 10: Tile index filename parsing is fragile

**File:** `python/volume.py:65-69`

The tile ID extraction assumes `parts[2]` after splitting by `_`. This breaks for filenames like `swissalti3d_2024_2683-1248_0.5_2056_5728.tif` (works) but would fail for any non-standard naming. The parser should search for the `XXXX-YYYY` pattern via regex instead of relying on positional indexing.

---

## Performance Issues

### PERF 1: Grid point creation uses Shapely Point objects

**File:** `python/grid.py:79-80`

```python
candidates = [Point(x, y) for x, y in zip(xx.ravel(), yy.ravel())]
rotated_points = list(filter(prepared_polygon.contains, candidates))
```

Creating a Shapely `Point` for every candidate grid cell is expensive. For a 50×50m building, that's ~2500 Point objects. Shapely 2.0+ supports vectorized `contains_xy` or `shapely.vectorized.contains` for a 10-50x speedup.

### PERF 2: Row-by-row iteration in main.py Step 3

**File:** `python/main.py:210`

`buildings.iterrows()` is the slowest way to iterate a GeoDataFrame. For large datasets (10K+ buildings), consider `itertuples()` or batch processing.

### PERF 3: Step 4 iterates rows unnecessarily

**File:** `python/main.py:264-272`

Step 4 converts the DataFrame to dicts, processes row-by-row, then converts back to a DataFrame. The `estimate_floor_area` function operates on dicts but could be vectorized since it's just arithmetic on columns + a lookup table.

### PERF 4: Tile download is sequential

**File:** `python/tile_fetcher.py:113-122`

Tile downloads happen one at a time. For large areas needing 50+ tiles, this is very slow. Using `concurrent.futures.ThreadPoolExecutor` with 4-8 workers would dramatically improve download speed.

---

## Code Quality Issues

### QUALITY 1: No type hints

The codebase would benefit from type hints throughout. Key signatures like `calculate_building_volume` return an untyped `dict` — a `TypedDict` or dataclass would make the interface explicit and enable static analysis.

### QUALITY 2: Bare `except` clauses

**Files:** `python/footprints.py:158`, `python/volume.py:173`, `tools/roof-estimator/python/green_roof.py:117`

Several bare `except:` or overly broad `except Exception:` clauses silently swallow errors. Notably `green_roof.py:117` uses bare `except:` which catches `SystemExit` and `KeyboardInterrupt`.

### QUALITY 3: Global mutable state in roof-estimator

**File:** `tools/roof-estimator/python/main.py:38`

Using a module-level global for the analyzer instance in multiprocessing workers is fragile. If `worker_init` fails, the worker continues with `green_roof_analyzer = None` and silently skips green roof analysis.

### QUALITY 4: `warnings.filterwarnings('ignore')`

**File:** `tools/roof-estimator/python/main.py:28`

Blanket warning suppression hides important deprecation warnings, shapely geometry issues, and numpy casting warnings. Filter specific warning categories instead.

### QUALITY 5: Duplicated geometry parsing logic

**File:** `tools/roof-estimator/python/main.py:92-148`

The `MultiPolygon` and `Polygon` branches in `parse_multipatch_geometry` share nearly identical code. Extract the ring-processing logic into a helper function.

### QUALITY 6: Unused imports

- `python/volume.py:19` — `sys` imported but never used
- `tools/roof-estimator/python/green_roof.py:2-3` — `os` and `glob` imported but never used

---

## Security & Robustness

### SEC 1: No validation on downloaded tile integrity

**File:** `python/tile_fetcher.py:72-77`

Downloaded tiles are written to `.tmp` then renamed, which is good for atomicity. However, there's no checksum validation — a corrupted or truncated download will produce a bad tile that silently produces wrong elevation data.

### SEC 2: GWR API queries are not rate-limited properly

**File:** `python/gwr.py:205`

The 0.1s sleep between API queries is a fixed delay, not an adaptive rate limiter. If the API returns 429 (Too Many Requests), the code doesn't back off.

### SEC 3: Hardcoded API URLs

**File:** `python/gwr.py:97`

API base URLs in `gwr.py` are inline strings in the function body. The swisstopo API has changed URLs historically. Consider making these module-level constants (as `tile_fetcher.py` correctly does).

---

## Missing Functionality

1. **No unit tests.** A pipeline this complex — with coordinate transforms, spatial operations, and numerical calculations — needs test coverage. At minimum: grid generation for known polygons, volume calculation for a simple box, floor height lookup, and tile ID computation.

2. **No input validation on GeoJSON structure.** `load_geojson_with_av` assumes `feat["geometry"]["coordinates"]` exists without validation. Malformed GeoJSON will crash with an unhelpful KeyError.

3. **No `--resume` capability.** For large runs (10K+ buildings), if the process crashes at building 8000, all work is lost. Periodic checkpointing or a resume-from-CSV feature would be valuable.

4. **No `__init__.py` or package structure.** The core pipeline lives as loose scripts in `python/`. This means imports rely on `sys.path` or running from the correct directory.

---

## Summary of Priority Fixes

| Priority | Issue | File | Impact |
|----------|-------|------|--------|
| **P0** | BUG 1: `status` vs `status_step1` | footprints.py:223 | GeoJSON+AV mode completely broken |
| **P0** | BUG 2: `egid` not mapped to `av_egid` | footprints.py:137 | CSV mode GWR enrichment broken |
| **P1** | ISSUE 6: Volume overcounted on slopes | volume.py:244 | Systematic overestimation |
| **P1** | ISSUE 9: Per-point AV file reads | footprints.py:140 | 100x slowdown for batch |
| **P1** | BUG 5: Unreachable gable condition | roof_analysis.py:182 | Hip roofs misclassified as complex |
| **P2** | PERF 1: Point object overhead in grid | grid.py:79 | 10-50x slower than vectorized |
| **P2** | PERF 4: Sequential tile downloads | tile_fetcher.py:113 | Slow for large areas |
| **P2** | QUALITY 2: Bare except clauses | multiple | Silent error swallowing |
| **P3** | No tests | — | Regression risk |
| **P3** | No type hints | all files | Maintainability |
