# Volume Estimator (DEPRECATED)

> **This tool has been deprecated and is no longer maintained.**
>
> Please use the **[DTM-based Volume Estimator](../volume-estimator/)** instead, which provides more consistent and reliable results.

## Table of Contents

- [Deprecation Notice](#deprecation-notice)
- [Why This Tool Was Deprecated](#why-this-tool-was-deprecated)
- [The Better Alternative](#the-better-alternative)
- [Archived Documentation](#archived-documentation)
  - [Overview](#overview)
  - [Requirements](#requirements)
  - [Usage](#usage)
  - [Output Format](#output-format)
- [Version History](#version-history)
- [License](#license)

---

## Deprecation Notice

This tool attempted to calculate building volumes by processing **3D mesh geometries** (multipatch) from Swisstopo's swissBUILDINGS3D dataset. While the approach was technically sophisticated, it produced **highly inconsistent results** across different buildings.

---

## Why This Tool Was Deprecated

### The Inconsistency Problem

**Some buildings achieved excellent, accurate results** while **others failed completely or produced unreliable volumes**. The root cause was the variable quality of the source 3D mesh data and the inherent difficulty of repairing complex 3D geometries.

### Technical Reasons for Failure

| Issue | Impact | Why It Caused Inconsistency |
|-------|--------|----------------------------|
| **Mesh Quality Variance** | High | Source 3D models from Swisstopo varied significantly in quality. Clean, watertight meshes → accurate results. Meshes with holes or errors → failed or inaccurate results. |
| **Non-Watertight Meshes** | High | Volume calculation requires "watertight" (closed) meshes. Many building meshes had gaps, holes, or missing faces that couldn't be reliably repaired. |
| **Inside-Out Meshes** | Medium | Some meshes had inverted face normals, producing negative volumes. While detectable, this indicated underlying geometry issues. |
| **Fan Triangulation Limitations** | Medium | The geometry parser used fan triangulation, which works for simple convex polygons but fails for complex concave shapes common in detailed building models. |
| **Repair Algorithm Uncertainty** | High | The repair pipeline (merge vertices → remove degenerate faces → fix normals → fill holes) had no guarantee of success. Each building required different repairs. |
| **Complex Building Geometries** | Medium | Buildings with courtyards, overhangs, or complex roof structures often had mesh issues that couldn't be automatically resolved. |

### What Happened During Processing

```
Building A: Clean mesh → Watertight → Accurate volume ✓
Building B: Minor gaps → Repaired successfully → Good volume ✓
Building C: Major holes → Repair failed → No volume ✗
Building D: Inside-out mesh → Corrected → Questionable accuracy ~
Building E: Complex geometry → Partial repair → Unreliable volume ✗
```

This unpredictability made the tool unsuitable for production use.

---

## The Better Alternative

The **[current Volume Estimator](../volume-estimator/)** uses a completely different approach:

| Aspect | This Tool (Deprecated) | Current Tool |
|--------|------------------------|--------------|
| **Method** | 3D mesh reconstruction | DTM (elevation model) sampling |
| **Data Source** | swissBUILDINGS3D multipatch (GDB) | Building footprints + swissALTI3D + swissSURFACE3D |
| **Consistency** | Variable (50-80% success rate) | High (95%+ success rate) |
| **Accuracy** | Good when it works, unreliable otherwise | Consistent ±5-10% for well-defined buildings |
| **Integration** | Standalone (GDB files only) | Database-integrated (PostGIS/Supabase) |
| **Maintenance** | Complex mesh repair logic | Simple elevation sampling |

### Why LIDAR Is More Reliable

1. **Pre-processed Data**: Swiss elevation models are professionally surveyed and validated
2. **No Mesh Repair Needed**: Raster data doesn't have holes, inverted faces, or topology issues
3. **Consistent Method**: Same calculation approach works for all buildings
4. **Official Footprints**: Uses cadastral survey footprints, avoiding geometry merging issues

---

## Archived Documentation

The sections below are preserved for historical reference only.

### Overview

This toolset processed [Swisstopo 3D building data](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta) (multipatch geometries) to calculate building volumes and analyze surface areas. It was designed to handle large datasets efficiently using parallel processing, providing detailed metrics for each building including volume, roof area, footprint, and wall areas.

### Result
The full processed dataset as a CSV file (1.2 GB) is available at:
- [Download from Google Drive](https://drive.google.com/file/d/1AS-dI3VbV52xkmuAYBvPIzVNZnVGNWXG/view?usp=sharing)

### What the Toolset Did

1. **Read** Swisstopo 3D building data from GDB (geodatabase) files
2. **Repaired** mesh geometries to ensure they are watertight for accurate volume calculation
3. **Calculated** building volumes using advanced mesh repair techniques
4. **Analyzed** surface areas, classifying them as roof, footprint, or walls
5. **Output** comprehensive results in CSV format

### Requirements

- Python 3.8 or higher
- Required Python packages:
  - fiona
  - pandas
  - numpy
  - trimesh

Install with:
```bash
python -m pip install fiona pandas numpy trimesh
```

### Files

- `main.py` - Main orchestrator script
- `mesh_repair_volume.py` - Mesh repair and volume calculation module
- `surface_analysis.py` - Surface area analysis module
- `test_imports.py` - Utility to verify installation

### Usage

#### Basic Command Structure

```bash
python main.py <input_gdb_path> <output_directory> [options]
```

#### Parameters

- `<input_gdb_path>` - Path to Swisstopo GDB file (required)
- `<output_directory>` - Where to save results (required)
- `--layer` - GDB layer name (default: "Building_solid")
- `--limit` - Process only first N buildings (optional, for testing)
- `--workers` - Number of parallel workers (default: CPU count - 1, max 8)
- `--chunk-size` - Number of buildings per chunk (default: 100000)
- `--keep-chunks` - Keep individual chunk CSV files after merging

#### Example Usage

1. **Test run 100 buildings with 8 workers:**
   ```bash
   cd "C:\DEV\Python\SWT 3D Buildings"
   python main.py "C:\DEV\Inputs\SWISSBUILDINGS3D_3_0.gdb" "C:\DEV\Python\SWT 3D Buildings\output" --layer Building_solid --workers 8 --limit 100
   ```

2. **Process entire dataset with 8 workers:**
   ```bash
   python main.py "C:\DEV\Inputs\SWISSBUILDINGS3D_3_0.gdb" "C:\DEV\Output" --layer Building_solid --workers 8
   ```

### Output Format

#### Generated Files

- `building_analysis_YYYYMMDD_HHMMSS.csv` - Complete results in CSV format
- `building_analysis_YYYYMMDD_HHMMSS_chunk_XXXX.csv` - Individual chunk files (if `--keep-chunks` is used)
- `processing.log` - Detailed processing log

#### Output Variables

**Input Fields (preserved from GDB)**

- `OBJECTID` - Original Swisstopo building ID
- `UUID` - Unique identifier
- `OBJEKTART` - Object type
- `NAME_KOMPLETT` - Complete building name
- `GEBAEUDE_NUTZUNG` - Building usage
- `DACH_MAX`/`DACH_MIN` - Roof height values
- `EGID` - Federal building ID
- (and all other original fields)

**Mesh Processing Fields (prefix: mesh_)**

| Field | Type | Description |
|-------|------|-------------|
| `mesh_volume` | float | Building volume in cubic meters |
| `mesh_is_watertight` | bool | Whether mesh is watertight |
| `mesh_vertex_count` | int | Number of mesh vertices |
| `mesh_face_count` | int | Number of mesh faces |
| `mesh_repair_applied` | bool | Whether repair was needed |
| `mesh_repair_steps` | string | Description of repair process |
| `mesh_process_error` | string | Error message if processing failed |

**Surface Analysis Fields (prefix: surf_)**

| Field | Type | Description |
|-------|------|-------------|
| `surf_roof_area` | float | Roof surface area (m²) |
| `surf_footprint_area` | float | Building footprint area (m²) |
| `surf_wall_area` | float | Total wall area (m²) |
| `surf_sloped_area` | float | Sloped surface area (m²) |
| `surf_total_area` | float | Total surface area (m²) |
| `surf_building_height` | float | Calculated building height (m) |
| `surf_wall_perimeter` | float | Estimated wall perimeter (m) |
| `surf_roof_complexity` | float | Roof complexity ratio (0-1) |
| `surf_min_elevation` | float | Minimum Z coordinate |
| `surf_max_elevation` | float | Maximum Z coordinate |
| `surf_horizontal_faces` | int | Count of horizontal faces |
| `surf_vertical_faces` | int | Count of vertical faces |
| `surf_sloped_faces` | int | Count of sloped faces |
| `surf_analysis_error` | string | Error message if analysis failed |

**Processing Status Fields**

- `processing_status` - "success" or "failed"
- `processing_error` - Overall error message if failed

### Performance Tips

1. **Test First**: Always run with `--limit 100` to verify everything works
2. **Workers**: Use `--workers` equal to your CPU cores minus 1
3. **Memory**: For large datasets (>500k buildings), the chunking system handles memory automatically
4. **Storage**: Ensure sufficient disk space for output files (estimate ~300-500 bytes per building)

### Troubleshooting

1. **Import Errors**: Run `python test_imports.py` to verify installation
2. **Memory Issues**: Reduce `--workers` or decrease `--chunk-size`
3. **GDB Access**: Ensure the GDB file path has no special characters
4. **Missing Libraries**: Install with `python -m pip install [library_name]`

### Processing Time Estimates

- 100 buildings: ~10-30 seconds
- 10,000 buildings: ~5-10 minutes
- 100,000 buildings: ~1-2 hours
- 1,700,000 buildings: ~2-4 hours (depending on CPU and workers)
- 2,500,000 buildings: ~6-8 hours (depending on CPU and workers)


### Notes

- Surface classification uses 10° tolerance for horizontal/vertical determination
- Footprint is defined as horizontal surfaces in the lowest 10% of building height
- Wall perimeter is estimated from wall area divided by building height
- All area measurements are in square meters (m²)
- All volume measurements are in cubic meters (m³)
- Coordinates are preserved in the original Swiss coordinate system
- For datasets exceeding 1 million rows, only CSV output is generated (Excel has a 1,048,576 row limit)

### Authors

Developed by the Federal Office for Buildings and Logistics BBL for processing Swisstopo 3D building data (swissBUILDINGS3D 3.0).

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-XX | Initial release |
| — | 2025-01 | Deprecated in favor of LIDAR-based Volume Estimator |

---

## License

MIT License — See LICENSE file for details.
