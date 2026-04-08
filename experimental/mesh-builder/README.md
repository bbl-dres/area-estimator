# Mesh Builder (experimental)

Build watertight 3D mesh hulls for buildings, footprint-exact, from a swisstopo
GeoTIFF DSM/DTM and an AV cadastral footprint. For GIS visualisation, not
analysis.

## Why this exists

[swissBUILDINGS3D 3.0](https://www.swisstopo.admin.ch/en/geodata/landscape/buildings3d3.html)
is the obvious source for 3D building geometry in Switzerland, but its quality
is uneven — some buildings are excellent, others are unusable. This tool
generates a mesh from the same raw data the rest of [`area-estimator`](../../../README.md)
already consumes (swissALTI3D + swissSURFACE3D), so the result is consistent
across every building in the country and degrades gracefully on weird footprints.

## What it produces

* **One mesh file per building**, named `building_<id>.{obj,ply,glb,stl}`
* **Watertight by construction** — verified with `trimesh.is_watertight`
* **Footprint-exact** — wall bases follow the AV polygon vertex-for-vertex
* **LOD2.5-ish** — the roof is a triangulated DSM clip (smooth, captures
  real-world bumps), not a planar-faced LoD2.

For pure visualisation in QGIS 3D, ArcGIS Pro, Cesium, or similar, this
"smooth roof" form is often preferred over true LoD2 — it never invents
roof shapes that aren't there. If you need planar roof surfaces for
energy / solar / CityGML semantics, use [roofer](https://github.com/3DBAG/roofer)
instead (point cloud input only).

## Algorithm

| Step | What | How |
|---|---|---|
| 1 | Normalise polygon | `_normalize_polygon`: largest part of MultiPolygon, strip interior rings, force CCW exterior orientation |
| 2 | Densify boundary | Add vertices along the exterior every `--boundary-spacing` m (default 0.5) |
| 3 | Interior grid + dedup | `volume.create_aligned_grid_points` (orientation-aligned, voxel = `--interior-spacing`, default 0.5); `scipy.cKDTree` drops interior points within `boundary_spacing/4` of any boundary vertex |
| 4 | Sample DTM at all points | `volume.TileIndex.sample_heights` (`alti3d`). Per-vertex, **not** mean — so the floor follows the slope under the building |
| 5 | Sample DSM at all points | Same call (`surface3d`). Clamped against local DTM for sample-noise tolerance |
| 6 | Roof CDT | Shewchuk's `triangle` over (boundary + interior) with boundary edges as constraints. PSLG mode (`pQ`) — no Steiner points, vertex indices preserved |
| 7 | Floor CDT | Same `triangle` call over the boundary alone, lifted to per-vertex DTM. Reverse winding so the floor normal points down |
| 8 | Walls | Vectorised: two triangles per consecutive boundary edge, top (DSM) → bottom (DTM). Outward-facing for CCW exterior |
| 9 | Assemble | One `trimesh.Trimesh(..., process=False)`. `is_watertight` is checked and any failure raises — construction is the contract |

The boundary vertex set is **shared** between the roof's outer ring, the wall
tops, the wall bottoms, and the floor outline. No gap can appear by
construction — no plane fitting, no hole filling, no topology repair, and
trimesh is told not to silently merge or drop anything either.

## Install

From the project root:

```bash
pip install -r python/requirements.txt
pip install -r experimental/mesh-builder/requirements.txt
```

## Run

```bash
cd experimental/mesh-builder
python build_mesh.py ../../data/example.csv \
    --av D:/AV_data/AV_Switzerland.gpkg \
    --dsm-dir D:/swissSURFACE3D \
    --dtm-dir D:/swissALTI3D \
    --output-dir ./out
```

Default output format is **PLY** (single file, preserves face colours when
`--colour` is set, sidesteps trimesh's float32 PLY-export precision trap by
exporting in local coordinates with a `<file>.ply.offset.json` sidecar
recording the absolute LV95 origin). Use `--format obj` for OBJ, `--format glb`
for glTF, or `--format stl` for STL.

The CSV format matches the main pipeline — `id` and `egid` columns, looked up
against the AV layer with one push-down WHERE filter.

### Output formats

| Format | Best for |
|---|---|
| `obj` | QGIS 3D, generic 3D viewers, Blender |
| `ply` | CloudCompare, MeshLab |
| `glb` | Cesium, web 3D, Three.js |
| `stl` | 3D printing |

For ArcGIS Pro Multipatch, convert from OBJ via the `Import 3D Files` GP tool.
For CityJSON, post-process with [cjio](https://github.com/cityjson/cjio).

## Limitations

* **Interior holes (courtyards) are stripped** and a warning is logged.
  Hole-aware meshing needs the inner rings as additional CDT constraints
  plus a hole-marker point for `triangle`.
* **MultiPolygon footprints** take only the largest part and log a warning
  with the dropped area. Multi-part buildings (main + detached annex) should
  be meshed independently and concatenated — straightforward extension.
* **The coarse smoothing pass treats features narrower than ~3 m × 3 m as
  thin spikes** and replaces them with the surrounding background. This
  removes lift overruns, stair towers, antenna masts, and narrow chimneys
  (the intended behaviour). Real architecture at that scale (small dormers,
  ventilation stacks) is affected too. See the "Tuning" section below.
* **Smooth roofs only** — see "What it produces" above. Not planar LoD2.
* **Single-threaded** — no parallel batching yet. Trivially wrappable in
  `concurrent.futures.ProcessPoolExecutor`.

## Tuning

The smoothing has constants you might want to adjust for unusual buildings.
They live near the top of [build_mesh.py](build_mesh.py):

| Constant | Default | What it does | When to change |
|---|---|---|---|
| `_SMOOTH_K` | 12 | k-NN size for the fine pass | Rarely |
| `_SMOOTH_UPPER_MAD` / `_SMOOTH_LOWER_MAD` | 4.0 | MAD threshold for the fine pass | Lower = more aggressive on noisy roofs |
| `_SMOOTH_MIN_SUPPORT` | 3 | Min same-z neighbours to keep a fine outlier | 2 = more aggressive, 4 = preserves smaller features |
| `_SMOOTH_COARSE_RADIUS_M` | 5.0 | Coarse-pass radius | Larger = catches wider thin features |
| `_SMOOTH_COARSE_HEIGHT_GAP_M` | 2.0 | Min height above background to flag a spike | Larger = more permissive |
| `_SMOOTH_COARSE_MIN_SUPPORT` | 6 | Min same-z neighbours to keep a coarse spike | Lower = more aggressive |

The threshold sits cleanly between **2×2 verts (removed)** and **3×3 verts
(preserved)** at the default 1 m grid spacing. To preserve smaller features
(real chimneys), bump `_SMOOTH_COARSE_MIN_SUPPORT` down to 3 or 4.

`--smooth-radius 0` disables **both** fine and coarse passes.

## Performance notes

* Triangulation cost is roughly linear in footprint area at fixed grid spacing.
  A typical residential footprint (~150 m²) at 0.5 m spacing builds in
  milliseconds; a 100 × 100 m warehouse runs in seconds and produces a PLY
  in the few-hundred-KB range. For batch portfolios consider
  `--interior-spacing 2.0` to cut face count 4×.
* The interior dedup uses `scipy.cKDTree` for O((N+M) log N), constant memory.
  An earlier broadcast-based version OOM'd on warehouses.

## Inspecting results

[viewer.html](viewer.html) is a single-file three.js viewer (CDN, no build step,
ES modules via importmap). Open it in a browser, drag-and-drop a generated OBJ /
PLY / STL / glTF file, and you get:

* Orbit / pan / zoom (Z-up like LV95)
* Wireframe + edge overlay toggles, normal-coloured shading
* Stats panel: vertex count, face count, bbox size, **in-browser watertight
  check** (counts edges → every edge must appear in exactly 2 faces, the same
  criterion `trimesh.is_watertight` uses)

Open it directly from disk or via a local server — both work because it has no
imports from sibling files.

## Files

| File | Purpose |
|---|---|
| [build_mesh.py](build_mesh.py) | The whole prototype — algorithm + CLI |
| [viewer.html](viewer.html) | Standalone three.js inspector (drag-and-drop OBJ/PLY/STL/glTF) |
| [requirements.txt](requirements.txt) | Adds `trimesh`, `triangle`, and `scipy` on top of parent requirements |
| [README.md](README.md) | This file |

## Research notes

The major LOD2 reconstruction tools ([roofer](https://github.com/3DBAG/roofer),
[3dfier](https://github.com/tudelft3d/3dfier),
[City4CFD](https://github.com/tudelft3d/City4CFD)) all require LAS/LAZ point
clouds — none accept a raster DSM directly. The deep-learning option
([SAT2LoD2](https://github.com/GDAOSU/LOD2BuildingModel)) accepts DSM but
requires CUDA and is designed for whole satellite scenes, not single buildings.

This prototype trades planar LoD2 surfaces (which is what those tools produce)
for guaranteed watertightness, footprint-exactness, and zero plane-fitting
failure modes. The tradeoff fits the "GIS visualisation" use case, where
swissBUILDINGS3D's inconsistency is the actual pain point.
