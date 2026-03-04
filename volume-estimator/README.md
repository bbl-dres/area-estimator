# Swiss Building Volume Estimator

A tool to estimate building volumes using building footprints and high-resolution Swiss elevation models (swissALTI3D and swissSURFACE3D).

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage Examples](#usage-examples)
- [Command-Line Reference](#command-line-reference)
- [Output](#output)
- [Technical Details](#technical-details)
- [Accuracy & Limitations](#accuracy--limitations)
- [Data Sources](#data-sources)
- [Version History](#version-history)
- [License](#license)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)

---

## Overview

This tool estimates building volumes by combining:
- **Building footprints** from a PostGIS/Supabase database (WGS84 geography)
- **Terrain elevation** from swissALTI3D (0.5m resolution)
- **Surface elevation** from swissSURFACE3D (0.5m resolution, includes buildings)

The calculation is based on a voxel approach: creating a 1×1 meter grid within each building footprint and sampling elevations at each point.

**Key Features:**
- Orientation-aligned grid generation for better accuracy
- Direct PostGIS/Supabase database integration
- Automatic WGS84 → LV95 coordinate transformation
- Dynamic tile indexing (year-agnostic)
- Flexible output (CSV export and/or database update)

<p align="center">
  <img src="images/Preview_2.jpg" width="45%" />
  <img src="images/Preview_3.jpg" width="45%" />
</p>
<p align="center">
  <img src="images/Preview_4.jpg" />
</p>

---

## How It Works

### The Method

The volume estimation follows these steps:

1. **Load Building Footprint** from PostGIS database (WGS84 coordinates)
2. **Transform to LV95** (Swiss projection system used by elevation models)
3. **Create Aligned Grid:**
   - Calculate building orientation using minimum area bounding rectangle
   - Rotate building to align with axes
   - Generate 1×1m grid points in rotated space
   - Rotate grid points back to original LV95 coordinates
   - This improves coverage for diagonal/non-axis-aligned buildings
4. **Sample Elevations:**
   - Identify required GeoTIFF tiles based on building location
   - Sample terrain elevation (swissALTI3D) at each grid point
   - Sample surface elevation (swissSURFACE3D) at each grid point
5. **Calculate Volume:**
   - Base height = minimum terrain elevation across all grid points
   - Building height at each point = surface elevation - base height
   - Volume = Σ(building heights) × 1m²

### Why Orientation-Aligned Grids?

For a rectangular building rotated 45°:
- **Standard axis-aligned grid**: Many grid points fall outside the footprint → lower accuracy
- **Orientation-aligned grid**: Grid aligns with building edges → better coverage

This significantly improves volume estimation accuracy, especially for non-axis-aligned buildings.

---

## Requirements

### Python Dependencies

```bash
pip install psycopg2-binary geopandas rasterio numpy pandas shapely pyproj
```

Or use the requirements file:
```bash
pip install -r requirements.txt
```

### Data Requirements

**1. Building Footprints Database**
- PostGIS or Supabase database
- Table: `public.buildings` (configurable)
- Geometry column: `geography` type in WGS84 (EPSG:4326)
- Must contain polygon geometries

**2. swissALTI3D Tiles**
- Digital Terrain Model (DTM) - bare earth elevation
- Resolution: 0.5m
- Format: GeoTIFF
- Coordinate system: Swiss LV95 (EPSG:2056)
- Naming: `swissalti3d_YYYY_XXXX-YYYY_0.5_2056_5728.tif`
- Download: [swisstopo swissALTI3D](https://www.swisstopo.admin.ch/de/hoehenmodell-swissalti3d)

**3. swissSURFACE3D Tiles**
- Digital Surface Model (DSM) - includes buildings, vegetation, etc.
- Resolution: 0.5m
- Format: GeoTIFF
- Coordinate system: Swiss LV95 (EPSG:2056)
- Naming: `swisssurface3d-raster_YYYY_XXXX-YYYY_0.5_2056_5728.tif`
- Download: [swisstopo swissSURFACE3D](https://www.swisstopo.admin.ch/de/hoehenmodell-swisssurface3d-raster)

### Understanding Tile Naming

Tile IDs are based on the southwest corner coordinates in LV95, divided by 1000:
- Example: `2609-1176` covers coordinates 2609000-2610000 (East) and 1176000-1177000 (North)
- A building at LV95 coordinates (2609500, 1176300) would use tile `2609-1176`

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/davras5/OpenBuildings.git
cd OpenBuildings/tools/volume-estimator
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Organize Elevation Data

Store GeoTIFF tiles in separate directories:

```
D:\SwissAlti3D\
├── swissalti3d_2025_2600-1224_0.5_2056_5728.tif
├── swissalti3d_2025_2601-1224_0.5_2056_5728.tif
└── ...

D:\swissSURFACE3D\
├── swisssurface3d-raster_2023_2600-1224_0.5_2056_5728.tif
├── swisssurface3d-raster_2023_2601-1224_0.5_2056_5728.tif
└── ...
```

**Note:** The script automatically handles different years (2019-2025+) by scanning filenames.

### 4. Prepare Database

Ensure your Supabase/PostGIS database has:
- A table with building footprints (default: `public.buildings`)
- A geometry/geography column in WGS84 (default column name: `geog`)

---

## Quick Start

### Test with a Single Building

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    "D:\SwissAlti3D" \
    "D:\swissSURFACE3D" \
    --building-ids 6767 \
    --geometry-column geog \
    -o test.csv
```

### Update Database (No CSV)

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    "D:\SwissAlti3D" \
    "D:\swissSURFACE3D" \
    --limit 100 \
    --geometry-column geog \
    --write-to-db
```

### Process Specific Area

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    "D:\SwissAlti3D" \
    "D:\swissSURFACE3D" \
    --bbox 7.43 47.15 7.48 47.19 \
    --geometry-column geog \
    -o results.csv \
    --write-to-db
```

---

## Usage Examples

### Export to CSV Only

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    "D:\SwissAlti3D" \
    "D:\swissSURFACE3D" \
    --limit 10 \
    --geometry-column geog \
    -o output.csv
```

### Update Database Only

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    "D:\SwissAlti3D" \
    "D:\swissSURFACE3D" \
    --limit 10 \
    --geometry-column geog \
    --write-to-db
```

### Both CSV and Database

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    "D:\SwissAlti3D" \
    "D:\swissSURFACE3D" \
    --limit 10 \
    --geometry-column geog \
    -o output.csv \
    --write-to-db
```

### Process Specific Buildings

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    "D:\SwissAlti3D" \
    "D:\swissSURFACE3D" \
    --building-ids 6767 8921 12345 \
    --geometry-column geog \
    -o specific_buildings.csv
```

### Process Buildings in Bounding Box

```bash
# Coordinates in WGS84 (longitude, latitude)
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    "D:\SwissAlti3D" \
    "D:\swissSURFACE3D" \
    --bbox 7.5 47.5 8.0 48.0 \
    --geometry-column geog \
    --write-to-db
```

---

## Command-Line Reference

### Required Arguments

| Argument | Description |
|----------|-------------|
| `db_connection` | PostgreSQL connection string<br>Format: `postgresql://user:password@host:port/database`<br>For Supabase: `postgresql://postgres.PROJECT:PASSWORD@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require` |
| `alti3d_dir` | Path to directory containing swissALTI3D GeoTIFF tiles |
| `surface3d_dir` | Path to directory containing swissSURFACE3D GeoTIFF tiles |

### Optional Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `-o, --output` | string | - | CSV output file path (optional if `--write-to-db` is used) |
| `--write-to-db` | flag | false | Write results to database (optional if `-o` is used) |
| `-l, --limit` | int | - | Limit number of buildings to process |
| `--building-ids` | int list | - | Process specific building IDs (space-separated) |
| `-b, --bbox` | 4 floats | - | Bounding box in WGS84: `MINLON MINLAT MAXLON MAXLAT` |
| `--geometry-column` | string | `geog` | Name of geometry column in database |
| `--table-name` | string | `public.buildings` | Database table name |

**Important:** You must specify at least one of `--output` or `--write-to-db`.

---

## Output

### CSV Output Format

When using `--output`, a CSV file is generated with these columns:

| Column | Type | Description |
|--------|------|-------------|
| `id` | integer | Building ID from database |
| `egid` | string | Swiss building identifier (EGID) if available |
| `volume_m3` | float | Estimated building volume in cubic meters |
| `footprint_area_m2` | float | Building footprint area in square meters |
| `mean_height_m` | float | Average building height above base |
| `max_height_m` | float | Maximum building height above base |
| `base_height_m` | float | Minimum terrain elevation (LV95 elevation) |
| `grid_points_count` | integer | Number of grid points successfully sampled |
| `status` | string | Processing status (see below) |

**Status Values:**
- `success`: Volume calculated successfully
- `no_grid_points`: No grid points could be generated (polygon too small or invalid)
- `no_height_data`: Grid points generated but no elevation data available
- `error`: Processing error occurred

### Database Output

When using `--write-to-db`, these columns in your database are updated:

| Database Column | Source | Description |
|-----------------|--------|-------------|
| `volume_above_ground_m3` | `volume_m3` | Estimated above-ground volume |
| `elevation_base_m` | `base_height_m` | Minimum terrain elevation |
| `height_mean_m` | `mean_height_m` | Average building height |
| `height_max_m` | `max_height_m` | Maximum building height |
| `updated_at` | - | Timestamp (automatically set to NOW()) |

**Columns NOT updated (remain NULL/unchanged):**
- `volume_total_m3` - Not estimated by this tool
- `volume_below_ground_m3` - Cannot be estimated from LIDAR/DSM data
- `volume_accuracy` - Not yet implemented

---

## Technical Details

### Coordinate Systems

- **Input:** WGS84 (EPSG:4326) - worldwide standard, used by GPS
- **Processing:** Swiss LV95 (EPSG:2056) - Swiss national coordinate system
- **Height Models:** LV95 coordinates, elevations in meters above sea level

The script automatically transforms coordinates between systems.

### Volume Calculation Method

**Base Height Determination:**
```
base_height = min(terrain_elevation_at_all_grid_points)
```
Using the minimum ensures we measure from the lowest point of terrain under the building.

**Building Height Calculation:**
```
For each grid point:
  building_height = max(0, surface_elevation - base_height)
```
Negative values (underground) are set to 0.

**Volume Calculation:**
```
volume = Σ(building_heights) × 1m²
```

### Grid Generation Algorithm

1. Calculate building orientation using minimum area bounding rectangle
2. Get longest edge angle → rotation angle
3. Rotate polygon by -angle (align to axes)
4. Generate axis-aligned 1×1m grid
5. Filter points inside rotated polygon
6. Rotate grid points back by +angle
7. Result: grid aligned to building orientation in LV95 space

### Tile Indexing

The script scans directories on startup and builds an index:
```
Tile ID → File Path
"2609-1176" → "D:\SwissAlti3D\swissalti3d_2025_2609-1176_0.5_2056_5728.tif"
```

This approach:
- Handles any year automatically (2019-2025+)
- Fast O(1) lookup during processing
- Works with mixed years (e.g., 2023 Surface + 2025 ALTI)

### Tile Selection

For each building:
1. Get bounding box in LV95 coordinates
2. Calculate required tiles: `tile_x = floor(x/1000)`, `tile_y = floor(y/1000)`
3. Buildings spanning multiple tiles: all tiles are loaded and sampled

---

## Accuracy & Limitations

### Performance

- **Processing speed:** ~10-20 buildings/second (varies with building size and complexity)
- **Memory usage:** Low - processes buildings individually
- **Tile caching:** Tiles loaded on demand and cached in memory during execution
- **Database:** Fetches buildings efficiently with spatial filters

### Limitations

**What Works:**
- Buildings spanning multiple tiles
- Complex building shapes
- Mixed tile years
- Large-scale processing
- **Official survey data advantage:** Uses official cadastral survey building footprints, which prevents footprint merging issues common with computer vision or point cloud clustering methods

**Known Issues:**
- Missing elevation data → `status: no_height_data`
- Very small buildings (<1m²) → `status: no_grid_points`
- Underground portions are set to 0 (cannot estimate below-ground volume from DSM)
- Accuracy limited by 0.5m resolution of elevation models
- Grid alignment uses minimum bounding rectangle (may not be optimal for very irregular shapes)
- **swissSURFACE3D class merging:** The raster model merges multiple classes (Ground/Class 2, Vegetation/Class 3, Buildings/Class 6, Bridges/Class 17, Water/Class 9). Small buildings covered by tall trees may show inaccurate heights, though this is uncommon as most roofs are not vegetation-covered

**Requirements:**
- Both swissALTI3D and swissSURFACE3D tiles must be available locally
- Buildings must have valid geometry in database
- Building must be within coverage area of available tiles

### Accuracy Considerations

**Factors affecting accuracy:**
1. **Elevation model resolution:** 0.5m grid → ±0.5m positional accuracy
2. **Grid alignment:** Better for rectangular buildings
3. **Terrain complexity:** More accurate on flat terrain
4. **Building size:** Larger buildings → more grid points → better accuracy
5. **Data currency:** Using matching years for ALTI and SURFACE is ideal

**Expected accuracy:** Typically within 5-10% for well-defined buildings with good elevation coverage.

---

## Data Sources

### Building Footprints
Your PostGIS/Supabase database containing building polygons. Building footprint data can be sourced from [Swiss Cadastral Surveying Services](https://www.geodienste.ch/services/av).

### Elevation Models
Both available from [Federal Office of Topography swisstopo](https://www.swisstopo.admin.ch):

- **swissALTI3D:** [Download page](https://www.swisstopo.admin.ch/de/hoehenmodell-swissalti3d)
  - Digital Terrain Model (bare earth)
  - Represents ground elevation without vegetation or buildings

- **swissSURFACE3D:** [Download page](https://www.swisstopo.admin.ch/de/hoehenmodell-swisssurface3d-raster)
  - Digital Surface Model (includes all surface features)
  - Represents top of buildings, vegetation, and other structures

### Coordinate Systems
- [Swiss coordinate system documentation](https://www.swisstopo.admin.ch/en/knowledge-facts/surveying-geodesy/reference-systems.html)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-XX | Initial release with orientation-aligned grid generation |
| 1.1 | 2025-01 | Added database integration and CSV export options |

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

**Areas for improvement:**
- Additional accuracy metrics
- Support for other elevation data formats
- Performance optimizations for very large datasets
- Alternative grid generation algorithms

---

## Acknowledgments

- Federal Office of Topography swisstopo for providing high-quality elevation models
- Swiss cadastral surveying authorities for building footprint data
- Open-source geospatial community for excellent tools (GDAL, GeoPandas, Rasterio)

---

## Alternative: FME Workbench

An FME Desktop implementation is also available: `fme/Volume Estimator FME.fmw`

To use:
1. Open in FME Desktop (2020 or newer)
2. Configure database connection and data directories
3. Run the workbench

The Python script and FME workbench produce equivalent results.
