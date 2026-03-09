# Code Review: Swiss Building Volume & Area Estimator

**Reviewer perspective:** Senior Python Developer, GIS & Cadastral Expert
**Date:** 2026-03-09

## Overall Assessment

This is a well-structured, domain-aware pipeline for estimating building volumes and floor areas from Swiss public geodata. The modular design (footprints → grid → volume → area) mirrors the conceptual workflow cleanly, and the code shows solid understanding of the Swiss cadastral ecosystem (AV, GWR, LV95, swisstopo services). The roof-estimator tool adds meaningful 3D mesh analysis capabilities.

**Rating: Strong foundation with actionable improvements needed.**

---

## Architecture & Design (Strong)

The 4-step pipeline is well-conceived:
- Step 1 (footprints) abstracts two input modes (CSV coordinates and geodata files) behind a common GeoDataFrame interface
- Step 2 (tile check) separates data availability from processing
- Step 3 (volume) uses a clean grid-sampling approach that handles complex roof shapes naturally
- Step 4 (area) correctly applies the Canton Zurich methodology with appropriate uncertainty bounds

The separation between `volume.py` (geometry + raster) and `area.py` (classification + estimation) is the right boundary.

---

## Bugs & Correctness Issues

### BUG 1: `gable` azimuth check is unreachable

**File:** `tools/roof-estimator/python/roof_analysis.py:182`

```python
if 150 < azimuth_diff < 210:
```

Since `azimuth_diff` is normalized to `[0, 180]` on lines 179-180 (via `if azimuth_diff > 180: azimuth_diff = 360 - azimuth_diff`), the condition `azimuth_diff > 180` is impossible after normalization. The range check `(150, 210)` should be `(150, 180]`.

### BUG 2: Negative coordinate tile ID calculation (latent)

**File:** `python/tile_fetcher.py:39-41`

`int()` truncates toward zero in Python, not toward negative infinity. For coordinates near tile boundaries with negative values, `int(-0.5)` gives `0` instead of `-1`. Not relevant for LV95 (always positive in Switzerland), but a latent bug if the code is adapted for other coordinate systems.

---

## GIS-Specific Issues

### ISSUE 3: Green roof convex hull approximation

**File:** `tools/roof-estimator/python/main.py:311-313`

Using convex hull of all 3D mesh vertices projected to 2D will overestimate footprint area for L-shaped, U-shaped, and courtyard buildings. This is acknowledged in the comments but should at minimum log a warning, since the green roof percentage will be underestimated for concave buildings (correct area measured against inflated total).

### ISSUE 4: Tile index filename parsing is fragile

**File:** `python/volume.py:65-69`

The tile ID extraction assumes `parts[2]` after splitting by `_`. This works for standard swisstopo filenames (e.g. `swissalti3d_2024_2683-1248_0.5_2056_5728.tif`) but would fail for any non-standard naming. The code does validate the extracted ID (`'-' in tile_id`), but a regex search for the `XXXX-YYYY` pattern would be more robust.

---

## Performance Issues

### PERF 1: Row-by-row iteration in main.py Step 3

**File:** `python/main.py:210`

`buildings.iterrows()` is the slowest way to iterate a GeoDataFrame. For large datasets (10K+ buildings), consider `itertuples()` or batch processing.

### PERF 2: Step 4 iterates rows unnecessarily

**File:** `python/main.py:264-272`

Step 4 converts the DataFrame to dicts, processes row-by-row, then converts back to a DataFrame. The `estimate_floor_area` function operates on dicts but could be vectorized since it's just arithmetic on columns + a lookup table.

### PERF 3: Tile download is sequential

**File:** `python/tile_fetcher.py:113-122`

Tile downloads happen one at a time. For large areas needing 50+ tiles, this is very slow. Using `concurrent.futures.ThreadPoolExecutor` with 4-8 workers would dramatically improve download speed.

---

## Code Quality Issues

### QUALITY 1: No type hints

The codebase would benefit from type hints throughout. Key signatures like `calculate_building_volume` return an untyped `dict` — a `TypedDict` or dataclass would make the interface explicit and enable static analysis.

### QUALITY 2: Broad `except Exception` clauses

**Files:** `python/volume.py:72`, `python/volume.py:267`, `tools/roof-estimator/python/green_roof.py:117`

Several overly broad `except Exception:` clauses silently swallow errors with only debug-level logging. Notably `green_roof.py:117` uses bare `except:` which also catches `SystemExit` and `KeyboardInterrupt`.

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

2. **No `--resume` capability.** For large runs (10K+ buildings), if the process crashes at building 8000, all work is lost. Periodic checkpointing or a resume-from-CSV feature would be valuable.

3. **No `__init__.py` or package structure.** The core pipeline lives as loose scripts in `python/`. This means imports rely on `sys.path` or running from the correct directory.

---

## Summary of Priority Fixes

| Priority | Issue | File | Impact |
|----------|-------|------|--------|
| **P1** | BUG 1: Unreachable gable azimuth condition | roof_analysis.py:182 | Hip roofs misclassified as complex |
| **P2** | ISSUE 3: Green roof convex hull approximation | roof-estimator/main.py:311 | Underestimates green roof % for concave buildings |
| **P2** | PERF 3: Sequential tile downloads | tile_fetcher.py:113 | Slow for large areas |
| **P2** | QUALITY 2: Broad except clauses | multiple | Silent error swallowing |
| **P3** | PERF 1: Row-by-row iteration in Step 3 | main.py:195 | Slower than itertuples for large datasets |
| **P3** | No tests | — | Regression risk |
| **P3** | No type hints | all files | Maintainability |
