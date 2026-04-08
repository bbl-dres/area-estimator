# Roof Shape from swissBUILDINGS3D (experimental)

Extract roof characteristics — area, slope, shape, height — from Swiss
buildings by analysing the 3D mesh geometry in
[swissBUILDINGS3D 3.0](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta).

> **Sibling tools** in [../](..):
> * **[mesh-builder/](../mesh-builder/)** — Watertight 3D building hulls from AV cadastral footprints + DSM/DTM rasters
> * **[green-roof-from-rs/](../green-roof-from-rs/)** — Green roof coverage via NDVI on swissIMAGE-RS multispectral imagery
> * **[floor-level-estimator/](../floor-level-estimator/)** — Per-floor estimator with construction-period (gbaup) factor

## Why this exists

The active pipeline uses elevation rasters to compute volumes, but doesn't
analyse roof geometry directly. swissBUILDINGS3D 3.0 ships closed 3D building
meshes with full multipatch geometry — when those meshes are good (which is
most of the time), they're a much richer source of per-roof metrics than
anything you can derive from a 2D footprint + raster.

This tool reads the swissBUILDINGS3D GDB, parses each building's mesh, and
extracts:

* Roof area (split into flat + sloped portions), wall area, footprint area
* Roof shape classification (`flat`, `gable`, `hip`, `shed`, `mansard`, `complex`)
* Roof slope (primary + secondary), azimuth, ridge orientation
* Building / eave / ridge heights, wall perimeter
* Per-class face counts

For buildings where swissBUILDINGS3D's mesh quality is poor (the inconsistency
that motivated [`mesh-builder/`](../mesh-builder/)), the output is unreliable.
For the bulk of the dataset where the mesh is good, this is a fast way to get
per-building shape and area metrics across all of Switzerland.

## What it produces

* **One CSV file** per run, containing all original GDB attributes plus
  the calculated fields below
* **Parallelised** — processes 100k+ buildings in chunks via
  `ProcessPoolExecutor`
* **Resumable** — chunked output, can keep intermediate chunks via `--keep-chunks`
* **All-Python**, no GUI dependencies

## Algorithm

| Step | What | How |
|---|---|---|
| 1 | Parse multipatch geometry | Read MultiPolygon/Polygon from GDB; fan-triangulate polygon rings into vertices + faces |
| 2 | Build trimesh | Wrap as a `trimesh.Trimesh` for face normal computation and area math |
| 3 | Classify each face | By the z-component of its normal: \|nz\| > cos(10°) → horizontal, \|nz\| < sin(10°) → vertical (wall), else → sloped (roof) |
| 4 | Footprint vs roof | Horizontal faces split by elevation: ≤ `min_z + 0.1×(max_z − min_z)` → footprint, else → flat roof |
| 5 | Areas | Sum face areas per category. `roof_area = horizontal_roof + sloped`, `wall_area = vertical`, `footprint_area = horizontal at ground` |
| 6 | Heights | `building_height = max_z − min_z`, `eave_height = max(wall_face_z) − min_z`, `ridge_height = max_z`, `wall_perimeter = wall_area / building_height` |
| 7 | Roof shape | Group sloped faces into 45° azimuth sectors, identify groups with > 10% of total sloped area, classify by group count and arrangement (see [Roof shape classification](#roof-shape-classification)) |

## Quick start

### Install

Python 3.11 is recommended for the cleanest fiona/GDAL wheel install.

```bash
cd experimental/roof-shape-from-buildings3d

# Windows
py -3.11 -m venv venv
venv\Scripts\activate

# Linux/Mac
python3.11 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### Run

```bash
# List available layers in the GDB
python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output --list-layers

# Process all buildings
python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output

# Process the first 1000 with 4 parallel workers (testing)
python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output --limit 1000 --workers 4
```

## CLI reference

| Argument | Required | Default | Description |
|---|---|---|---|
| `input_gdb` | yes | — | Path to swissBUILDINGS3D GDB file |
| `output_dir` | yes | — | Output directory for CSV results and logs |
| `--layer` | no | `Building_solid` | GDB layer name containing 3D building meshes |
| `--limit` | no | — | Stop after this many buildings |
| `--workers` | no | CPU − 1 (max 8) | Number of parallel worker processes |
| `--chunk-size` | no | `100000` | Buildings per processing chunk (memory tuning) |
| `--list-layers` | no | off | List available layers in the GDB and exit |
| `--keep-chunks` | no | off | Keep intermediate chunk CSV files after merging |

The bbox filter parameter on `read_gdb_buildings_chunked` is still in the
code (it's a thin pass-through to fiona) but isn't currently exposed via CLI.
Add a `--bbox` flag if you need spatial pre-filtering.

## Output

A single CSV file per run, containing **all original GDB attributes** plus
the calculated fields below.

### Area measurements

| Column | Unit | Description |
|---|---|---|
| `roof_area_m2` | m² | Total roof surface area |
| `flat_roof_area_m2` | m² | Horizontal roof area |
| `sloped_roof_area_m2` | m² | Sloped roof area |
| `wall_area_m2` | m² | Vertical wall area |
| `footprint_area_m2` | m² | Ground footprint area |
| `total_surface_area_m2` | m² | Total mesh surface area |

### Roof shape classification

| Column | Description |
|---|---|
| `roof_shape` | One of: `flat`, `gable`, `hip`, `shed`, `mansard`, `complex`, `unknown` |
| `roof_shape_confidence` | Classification confidence (0.0 – 1.0) |
| `roof_slope_primary_deg` | Primary slope angle |
| `roof_slope_secondary_deg` | Secondary slope angle |
| `roof_azimuth_primary_deg` | Primary slope direction (0=N, 90=E, 180=S, 270=W) |
| `roof_ridge_orientation` | Ridge line orientation |
| `roof_face_count` | Number of roof faces |

### Building metrics

| Column | Unit | Description |
|---|---|---|
| `building_height_m` | m | Total building height |
| `eave_height_m` | m | Height to roof eave |
| `ridge_height_m` | m | Height to roof ridge |
| `wall_perimeter_m` | m | Wall area / building height |
| `min_elevation_m` | m (LV95) | Minimum elevation |
| `max_elevation_m` | m (LV95) | Maximum elevation |

### Face counts + status

| Column | Description |
|---|---|
| `horizontal_face_count` | Number of horizontal faces |
| `vertical_face_count` | Number of vertical faces |
| `sloped_face_count` | Number of sloped faces |
| `analysis_status` | `success` or `failed` |
| `analysis_error` | Error message (only if failed) |

## Limitations

* **Mesh quality dependency.** Results depend on swissBUILDINGS3D mesh
  quality. Some buildings have incomplete or non-watertight meshes; complex
  geometries may not be perfectly represented. This is the inconsistency
  that [mesh-builder/](../mesh-builder/) was created to work around.
* **Fan triangulation** — GDB multipatch parsing fan-triangulates polygon
  rings, which is generally accurate for typical building faces but won't
  perfectly represent self-intersecting or extreme polygon shapes.
* **10% elevation threshold** for footprint vs roof separation. Doesn't
  cope well with buildings on steep terrain or split-level designs.
* **Roof shape classification** works best for standard Swiss roof types.
  Unusual designs end up in `complex`. Multi-wing buildings get a single
  whole-building classification.
* **Dormers and small features** can shift classification, especially for
  highly detailed meshes — they show up as additional sloped face groups.
* **Sample-tested accuracy** — typical surface area accuracy is ~±5%
  (direct mesh integration), simple-shape classification 80–85%,
  complex-shape classification 60–70%.

## Files

| File | Purpose |
|---|---|
| [main.py](main.py) | CLI orchestrator: GDB reader, parallel chunked processing, CSV merging |
| [roof_analysis.py](roof_analysis.py) | Per-building geometric analysis: face classification, area math, shape classification |
| [requirements.txt](requirements.txt) | `fiona`, `trimesh`, `numpy`, `pandas` |
| [README.md](README.md) | This file |

## Data sources

| Dataset | Provider | Layer | Format | URL |
|---|---|---|---|---|
| swissBUILDINGS3D 3.0 | swisstopo | `Building_solid` (multipatch / 3D) | ESRI File Geodatabase (.gdb) | [swisstopo.admin.ch](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta) |

### swissBUILDINGS3D — what we read

The `Building_solid` layer contains 3D building models as closed multipatch
surfaces representing the outer shell of each building, in LV95 (EPSG:2056)
with full elevation. The following attributes are present in the source data
and **preserved verbatim** in the output CSV:

| Attribute | Type | Description |
|---|---|---|
| `UUID` | string | Unique identifier |
| `OBJEKTART` | string | Object type (e.g. `Gebaeude Einzelhaus`, `Lagertank`) |
| `NAME_KOMPLETT` | string | Complete building name |
| `GEBAEUDE_NUTZUNG` | string | Building usage |
| `EGID` | int | Federal building identifier |
| `DACH_MAX` | float | Maximum roof elevation (m) |
| `DACH_MIN` | float | Minimum roof elevation (m) |
| `GELAENDEPUNKT` | float | Terrain elevation (m) |
| `GESAMTHOEHE` | float | Total building height (m) |
| `HERKUNFT` | string | Data source |
| `HERKUNFT_JAHR` | int | Source year |
| `DATUM_AENDERUNG` | datetime | Last modification date |
| `GEBAEUDEEINHEIT` | string | Building unit identifier |

Available layers in swissBUILDINGS3D 3.0 (use `--list-layers` to confirm):
`Floor`, `Roof`, `Wall`, `Building_solid`, `Roof_solid`. This tool uses
`Building_solid` (the complete 3D building shell) by default.

## Roof shape classification

The classifier groups sloped faces by 45° azimuth sectors and decides shape
based on the number and arrangement of significant groups (each > 10% of
total sloped area):

| Significant groups | Distribution | Classification |
|---|---|---|
| 0 | All horizontal | `flat` |
| 1 | Single slope direction | `shed` |
| 2 | Opposite directions (180° apart) | `gable` |
| 3+ | Evenly distributed | `hip` |
| 3+ | Mixed steep / shallow slopes | `mansard` |
| 4+ | Irregular distribution | `complex` |

### Roof shape labels

| Shape | Description | Typical buildings |
|---|---|---|
| `flat` | Horizontal or near-horizontal surfaces (> 85% flat) | Modern commercial, industrial |
| `gable` | Two sloped surfaces meeting at a ridge | Traditional residential |
| `hip` | Four sloped surfaces meeting at a ridge or point | Residential, institutional |
| `shed` | Single sloped surface (mono-pitch) | Extensions, modern design |
| `mansard` | Double slope on multiple sides | Historic urban buildings |
| `complex` | Multiple gables or irregular geometry | Large buildings, additions |
| `unknown` | Unable to classify | Incomplete geometry |

### Typical confidence

| Shape | Typical confidence |
|---|---|
| `flat` | 85–100% |
| `gable` | 80–85% |
| `hip` | 75–80% |
| `shed` | 75–80% |
| `mansard` | 65–70% |
| `complex` | 50–60% |

> The sibling tool [mesh-builder/](../mesh-builder/) has a more nuanced
> classifier on its built meshes — see its
> [Roof shape taxonomy](../mesh-builder/README.md#roof-shape-taxonomy)
> section for the broader CityGML / OSM / ALKIS reference taxonomies and
> their German names.

## References

- [swissBUILDINGS3D 3.0](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta)
- [LV95 coordinate system](https://www.swisstopo.admin.ch/en/knowledge-facts/surveying-geodesy/reference-frames/local/lv95.html)
- [trimesh](https://trimesh.org/)
- [fiona](https://fiona.readthedocs.io/)
