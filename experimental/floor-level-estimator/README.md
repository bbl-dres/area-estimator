# Floor Level Estimator (experimental)

Per-floor count estimation that adds a construction-period (`gbaup`) factor on
top of the GWR floor-height table. Standalone exploration kept as reference;
not currently imported anywhere.

> **Sibling tools** in [../](..):
> * **[mesh-builder/](../mesh-builder/)** — Watertight 3D building hulls from AV cadastral footprints + DSM/DTM rasters
> * **[roof-shape-from-buildings3d/](../roof-shape-from-buildings3d/)** — Roof characteristics from swissBUILDINGS3D 3D meshes
> * **[green-roof-from-rs/](../green-roof-from-rs/)** — Green roof coverage via NDVI on swissIMAGE-RS multispectral imagery

## Why this exists

The active pipeline ([python/area.py](../../python/area.py)) computes floor
counts using a per-`GKAT`/`GKLAS` floor-height table sourced from
[Seiler & Seiler 2020](../../docs/Height%20Assumptions.md). That table averages
across construction periods.

This experimental tool adds a `GWR_GBAUP`-derived modifier on top, capturing
real-world variation in floor heights across construction eras:

* **Pre-1919** — representative period buildings have notably taller ceilings
* **Post-war (1946–1960)** — rationalisation, lowest typical floor heights
* **Modern (post-2000)** — Minergie comfort, slightly taller floors again

If validated against real building drawings, the modifier could fold into
[python/area.py](../../python/area.py) as an optional refinement to the
documented Seiler & Seiler methodology. Until then this file is intentionally
not imported anywhere.

## What it produces

* A floor-height lookup table indexed by `GWR_GKAT` (building category code)
  with `GH_EG_MIN`/`GH_EG_MAX` (ground floor) and `GH_RG_MIN`/`GH_RG_MAX`
  (upper floors)
* A `GWR_GBAUP`-based multiplicative modifier
* Helper functions for floor-count estimation from `building_volume / footprint_area / floor_height`

## Quick start

### Install

```bash
cd experimental/floor-level-estimator
pip install -r requirements.txt
```

### Run

This tool is currently a **standalone exploration script** — no CLI. To use
it, edit the `__main__` block in [main.py](main.py) or import the lookup
tables and helper functions from a notebook:

```python
from main import lookup_table_height, gbaup_factor
```

## Files

| File | Purpose |
|---|---|
| [main.py](main.py) | The whole exploration: lookup table, gbaup factor, calculation helpers |
| [requirements.txt](requirements.txt) | `pandas`, `requests` |
| [README.md](README.md) | This file |

## Data sources

| Dataset | Provider | URL |
|---|---|---|
| GWR (Gebäude- und Wohnungsregister) | Federal Statistical Office | [housing-stat.ch](https://www.housing-stat.ch/) |
| Floor-height base table | Seiler & Seiler 2020 | [docs/Height Assumptions.md](../../docs/Height%20Assumptions.md) |

## Status

**Unmaintained.** Kept as reference for the gbaup-factor idea. If proven on
real data, the gbaup modifier should fold into [python/area.py](../../python/area.py)
as an optional refinement rather than living as a separate tool.
