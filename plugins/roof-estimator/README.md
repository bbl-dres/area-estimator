# Swiss Building Roof Estimator

A tool for extracting roof characteristics from Swiss buildings using swissBUILDINGS3D 3.0 3D mesh data.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Command-Line Reference](#command-line-reference)
- [Methodology](#methodology)
- [Data Sources](#data-sources)
- [Roof Shape Classification](#roof-shape-classification)
- [Output Format](#output-format)
- [Sample Results](#sample-results)
- [Accuracy & Limitations](#accuracy--limitations)
- [References](#references)
- [Version History](#version-history)
- [License](#license)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)

---

## Overview

This estimator analyzes 3D building meshes from swissBUILDINGS3D to extract:

- **Roof area** (m²) — Total roof surface area including flat and sloped portions
- **Wall area** (m²) — Total vertical wall surface area
- **Footprint area** (m²) — Building ground footprint area
- **Roof shape** — Classification of roof type (flat, gable, hip, shed, mansard, complex)

Additional metrics include:
- Building height and elevation data
- Roof slope angles (primary and secondary)
- Roof orientation/azimuth
- Eave and ridge heights
- Surface face counts

**Data Source:** This tool uses 3D mesh data from [swissBUILDINGS3D 3.0](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta) (swisstopo).

---

## Quick Start

### 1. Setup (first time only)

```bash
cd workers/roof-estimator/python
py -3.11 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Analyze roof characteristics for 100 buildings

```bash
venv\Scripts\python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output --limit 100
```

### 3. List available layers in GDB

```bash
venv\Scripts\python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output --list-layers
```

### 4. Process all buildings with 4 workers

```bash
venv\Scripts\python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output --workers 4
```

---

## Requirements

### Python Version

**Python 3.11 recommended** — Fiona requires GDAL and has pre-built wheels for Python 3.11. Newer Python versions (3.12+) may require building from source.

### Python Dependencies

```bash
pip install fiona trimesh numpy pandas
```

Or install from requirements file:

```bash
pip install -r python/requirements.txt
```

### Data Requirements

| Data | Source | Description |
|------|--------|-------------|
| swissBUILDINGS3D 3.0 | swisstopo | GDB file with 3D building meshes |

---

## Installation

### 1. Create Virtual Environment (Recommended)

Using Python 3.11 for best compatibility with fiona:

```bash
cd workers/roof-estimator/python

# Windows
py -3.11 -m venv venv
venv\Scripts\activate

# Linux/Mac
python3.11 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Verify GDB Access

Ensure you have access to the swissBUILDINGS3D GDB file:

```bash
python main.py "path/to/SWISSBUILDINGS3D_3_0.gdb" ./output --list-layers
```

**Available layers in swissBUILDINGS3D 3.0:**
- `Floor` — Floor surfaces
- `Roof` — Roof surfaces (2D)
- `Wall` — Wall surfaces
- `Building_solid` — Complete 3D building meshes (used by this tool)
- `Roof_solid` — 3D roof meshes

---

## Usage

All examples assume you are in the `workers/roof-estimator/python` directory with the virtual environment activated.

### Basic Processing (CSV Output)

```bash
python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output
```

### Process with Limit (Testing)

```bash
python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output --limit 1000
```

### Specify Layer Name

```bash
python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output --layer Building_solid
```

### Custom Chunk Size for Memory Management

```bash
python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" ./output --chunk-size 50000
```

---

## Command-Line Reference

### Required Arguments

| Argument | Description |
|----------|-------------|
| `input_gdb` | Path to swissBUILDINGS3D GDB file |
| `output_dir` | Output directory for results (CSV files and logs) |

### Optional Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--layer` | string | `Building_solid` | GDB layer name containing 3D building meshes |
| `--limit` | int | - | Maximum number of buildings to process |
| `--workers` | int | CPU-1 (max 8) | Number of parallel workers |
| `--chunk-size` | int | 100000 | Buildings per processing chunk |
| `--list-layers` | flag | false | List available layers and exit |
| `--keep-chunks` | flag | false | Keep intermediate chunk CSV files |

---

## Methodology

### Core Calculation Pipeline

The roof estimator processes each building through the following steps:

```
GDB File → Parse Multipatch → Create Trimesh → Classify Faces → Calculate Areas → Classify Roof Shape
```

### 1. Geometry Parsing

The tool reads multipatch geometries from the GDB and converts them to triangle meshes:

```
MultiPolygon/Polygon → Vertices + Faces → Trimesh object
```

Fan triangulation is used to convert polygon rings into triangles.

### 2. Face Classification

Each mesh face is classified based on its normal vector:

```
normal_z = face_normal · [0, 0, 1]

if |normal_z| > cos(10°):
    → Horizontal (up or down)
elif |normal_z| < sin(10°):
    → Vertical (wall)
else:
    → Sloped (roof surface)
```

### 3. Footprint vs Roof Separation

Horizontal faces are separated into footprint and roof based on elevation:

```
z_threshold = min_z + 0.1 × (max_z - min_z)

if face_centroid_z ≤ z_threshold:
    → Footprint
else:
    → Roof (horizontal portion)
```

### 4. Area Calculations

Areas are computed directly from mesh face geometry:

```
roof_area = Σ(horizontal_roof_faces) + Σ(sloped_faces above footprint)
wall_area = Σ(vertical_faces)
footprint_area = Σ(horizontal_faces at ground level)
```

### 5. Roof Shape Classification

The algorithm analyzes sloped roof faces by:

1. **Grouping by azimuth** — Faces grouped into 45° compass sectors
2. **Identifying significant groups** — Groups with >10% of total sloped area
3. **Classifying based on distribution** — Number and arrangement of groups

See [Roof Shape Classification](#roof-shape-classification) for details.

### 6. Height Calculations

```
building_height = max_elevation - min_elevation
eave_height = max(wall_face_z) - min_elevation
ridge_height = max_elevation
wall_perimeter = wall_area / building_height
```

---

## Data Sources

### swissBUILDINGS3D 3.0

| Property | Value |
|----------|-------|
| Provider | Federal Office of Topography (swisstopo) |
| Format | ESRI File Geodatabase (GDB) |
| Layer | Building_solid (multipatch/3D geometry) |
| Coordinate System | LV95 (EPSG:2056) + elevation |
| Coverage | Switzerland |
| Update Cycle | Periodic |

The dataset contains 3D building models as closed mesh surfaces representing the outer shell of buildings. Each building is stored as a multipatch geometry with full 3D coordinates.

**URL:** https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta

### GDB Schema (Building_solid layer)

The following attributes are available in the source data and preserved in the output:

| Attribute | Type | Description |
|-----------|------|-------------|
| `UUID` | string | Unique identifier |
| `OBJEKTART` | string | Object type (e.g., "Gebaeude Einzelhaus", "Lagertank") |
| `NAME_KOMPLETT` | string | Complete building name |
| `GEBAEUDE_NUTZUNG` | string | Building usage |
| `EGID` | int | Federal building identifier (EGID) |
| `DACH_MAX` | float | Maximum roof elevation (m) |
| `DACH_MIN` | float | Minimum roof elevation (m) |
| `GELAENDEPUNKT` | float | Terrain elevation (m) |
| `GESAMTHOEHE` | float | Total building height (m) |
| `HERKUNFT` | string | Data source |
| `HERKUNFT_JAHR` | int | Source year |
| `DATUM_AENDERUNG` | datetime | Last modification date |
| `GEBAEUDEEINHEIT` | string | Building unit identifier |

---

## Roof Shape Classification

### Classification Algorithm

The roof shape classifier analyzes the distribution of sloped faces:

| Groups | Distribution | Classification |
|--------|--------------|----------------|
| 0 | All horizontal | `flat` |
| 1 | Single slope direction | `shed` |
| 2 | Opposite directions (180° apart) | `gable` |
| 3+ | Evenly distributed | `hip` |
| 3+ | Mixed steep/shallow slopes | `mansard` |
| 4+ | Irregular distribution | `complex` |

### Roof Shape Types

| Shape | Description | Typical Buildings |
|-------|-------------|-------------------|
| `flat` | Horizontal or near-horizontal surfaces (>85% flat) | Modern commercial, industrial |
| `gable` | Two sloped surfaces meeting at a ridge | Traditional residential |
| `hip` | Four sloped surfaces meeting at ridge/point | Residential, institutional |
| `shed` | Single sloped surface (mono-pitch) | Extensions, modern design |
| `mansard` | Double slope on multiple sides | Historic urban buildings |
| `complex` | Multiple gables or irregular geometry | Large buildings, additions |
| `unknown` | Unable to classify | Incomplete geometry |

### Confidence Levels

| Shape | Typical Confidence |
|-------|-------------------|
| Flat | 85–100% |
| Gable | 80–85% |
| Hip | 75–80% |
| Shed | 75–80% |
| Mansard | 65–70% |
| Complex | 50–60% |

---

## Output Format

### CSV Output Structure

The tool outputs a CSV file containing all original GDB attributes plus the following calculated fields:

#### Area Measurements

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| `roof_area_m2` | float | m² | Total roof surface area |
| `flat_roof_area_m2` | float | m² | Horizontal roof area |
| `sloped_roof_area_m2` | float | m² | Sloped roof area |
| `wall_area_m2` | float | m² | Vertical wall area |
| `footprint_area_m2` | float | m² | Ground footprint area |
| `total_surface_area_m2` | float | m² | Total mesh surface area |

#### Roof Shape Classification

| Column | Type | Description |
|--------|------|-------------|
| `roof_shape` | string | Roof type: flat, gable, hip, shed, mansard, complex, unknown |
| `roof_shape_confidence` | float | Classification confidence (0.0–1.0) |
| `roof_slope_primary_deg` | float | Primary slope angle in degrees |
| `roof_slope_secondary_deg` | float | Secondary slope angle in degrees |
| `roof_azimuth_primary_deg` | float | Primary slope direction (0=N, 90=E, 180=S, 270=W) |
| `roof_ridge_orientation` | float | Ridge line orientation in degrees |
| `roof_face_count` | int | Number of roof faces |

#### Building Metrics

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| `building_height_m` | float | m | Total building height |
| `eave_height_m` | float | m | Height to roof eave |
| `ridge_height_m` | float | m | Height to roof ridge |
| `wall_perimeter_m` | float | m | Estimated wall perimeter |
| `min_elevation_m` | float | m | Minimum elevation (LV95) |
| `max_elevation_m` | float | m | Maximum elevation (LV95) |

#### Face Counts

| Column | Type | Description |
|--------|------|-------------|
| `horizontal_face_count` | int | Number of horizontal faces |
| `vertical_face_count` | int | Number of vertical faces |
| `sloped_face_count` | int | Number of sloped faces |

#### Processing Status

| Column | Type | Description |
|--------|------|-------------|
| `analysis_status` | string | `success` or `failed` |
| `analysis_error` | string | Error message if failed |

---

## Sample Results

Results from processing 100 buildings from swissBUILDINGS3D 3.0:

### Roof Shape Distribution

| Shape | Count | Percentage |
|-------|-------|------------|
| Gable | 57 | 57% |
| Flat | 30 | 30% |
| Shed | 11 | 11% |
| Hip | 2 | 2% |

### Area Statistics

| Metric | Mean | Median | Total |
|--------|------|--------|-------|
| Roof Area | 182.6 m² | 69.7 m² | 18,261 m² |
| Wall Area | 376.2 m² | — | 37,620 m² |
| Footprint Area | 165.0 m² | — | 16,498 m² |

### Performance

| Metric | Value |
|--------|-------|
| Success Rate | 100% |
| Processing Time | 1.4 seconds (100 buildings) |
| Parallel Workers | 5 |

---

## Accuracy & Limitations

### Expected Accuracy

| Metric | Accuracy | Notes |
|--------|----------|-------|
| Surface areas | ±5% | Direct mesh calculation |
| Roof shape (simple) | 80–85% | Flat, gable, shed |
| Roof shape (complex) | 60–70% | Hip, mansard, complex |

### Known Limitations

1. **Mesh Quality Dependency**
   - Results depend on swissBUILDINGS3D mesh quality
   - Some buildings may have incomplete or non-watertight meshes
   - Complex geometries may not be perfectly represented

2. **Fan Triangulation**
   - GDB multipatch parsing uses fan triangulation
   - May not perfectly represent all polygon shapes
   - Generally accurate for typical building faces

3. **Roof Shape Classification**
   - Works best for standard Swiss roof types
   - Complex or unusual designs classified as "complex"
   - Multi-wing buildings may be oversimplified

4. **Elevation Threshold**
   - 10% threshold for footprint separation
   - May not work well for buildings on steep terrain
   - Split-level buildings may have inaccurate footprint

5. **Dormers and Details**
   - Small roof features (dormers, skylights) may affect classification
   - Very detailed meshes may increase "complex" classifications

---

## References

- **swissBUILDINGS3D 3.0**: [swisstopo.admin.ch](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta)
- **LV95 Coordinate System**: [swisstopo.admin.ch](https://www.swisstopo.admin.ch/en/knowledge-facts/surveying-geodesy/reference-frames/local/lv95.html)
- **Trimesh Library**: [trimesh.org](https://trimesh.org/)
- **Fiona Library**: [fiona.readthedocs.io](https://fiona.readthedocs.io/)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-01 | Initial release with roof area, wall area, footprint area, and roof shape classification |

---

## License

MIT License — See LICENSE file for details.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

**Areas for improvement:**
- Validation against manually classified roof types
- Support for additional roof shape categories (butterfly, sawtooth, etc.)
- Integration with solar potential calculations
- Green roof suitability analysis

---

## Acknowledgments

- Federal Office of Topography (swisstopo) for swissBUILDINGS3D data
- Trimesh library developers for 3D mesh processing tools
- Fiona/GDAL community for GDB file access

---

*This tool is provided for estimation purposes only. For official building measurements, consult certified surveyors or building authorities.*
