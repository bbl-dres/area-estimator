# Green Roof Detection from swissIMAGE RS

Automated detection and quantification of green roofs using NDVI analysis on swisstopo aerial imagery.

## Overview

This FME workspace analyzes building rooftops using near-infrared (NIR) and red band imagery from swissIMAGE RS to calculate the Normalized Difference Vegetation Index (NDVI). Buildings are classified as having green roofs based on vegetation coverage thresholds.

## Data Sources

| Dataset | Source | Description |
|---------|--------|-------------|
| **swissIMAGE RS** | [swisstopo](https://www.swisstopo.admin.ch/en/orthoimage-swissimage-rs) | 4-band orthophotos (NIR, R, G, B) at 10cm resolution |
| **swissBUILDINGS3D** | [swisstopo](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d) | 3D building geometries |

## Workflow

```
┌─────────────┐     ┌─────────────────────┐     ┌─────────────────┐     ┌─────────────────────────┐
│ swissIMAGE  │────▶│  RasterSelector     │────▶│ RasterExpression│────▶│        Clipper          │
│ RS (GeoTIFF)│     │  (Bands 0:;1:)      │     │ Evaluator (NDVI)│     │  (Clip to buildings)    │
└─────────────┘     └─────────────────────┘     └─────────────────┘     └───────────┬─────────────┘
                                                                                    │
┌─────────────┐     ┌─────────────────────┐     ┌─────────────────┐                 │
│swissBUILDINGS│───▶│SurfaceFootprint     │────▶│ CoordinateSystem│─────────────────┘
│    3D       │     │Replacer (2D footprint)    │ Setter (LV95)   │
└─────────────┘     └─────────────────────┘     └─────────────────┘
                                                                        
                    ┌─────────────────────┐     ┌─────────────────┐
                    │    PythonCaller     │────▶│ AttributeManager│────▶ Output
                    │ (Green Roof Stats)  │     │                 │
                    └─────────────────────┘     └─────────────────┘
```

## Transformer Configuration

<img title="a title" alt="Alt text" src="FME Workflow.JPG">

### RasterSelector
Selects NIR and Red bands for NDVI calculation:
```
Band and Palette List: 0:;1:
```

### RasterExpressionEvaluator
Calculates NDVI from NIR (Band 0) and Red (Band 1):

| Interpretation | Expression |
|----------------|------------|
| Real64 | `(A[0] - A[1]) / (A[0] + A[1])` |

### GeoTIFF Reader Settings
To preserve 16-bit precision:
- **Non-standard Color Bit Depth**: `Do Not Scale`

## Output Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `_ndvi_avg` | Float | Average NDVI value for the roof |
| `_ndvi_min` | Float | Minimum NDVI value |
| `_ndvi_max` | Float | Maximum NDVI value |
| `_is_green_roof` | String | Classification result: `Yes`, `No`, `NoData`, or `Error` |
| `_green_area_m2` | Float | Green area in square meters |
| `_green_percentage` | Float | Percentage of roof classified as green |
| `_green_pixels` | Integer | Count of pixels above NDVI threshold |
| `_total_pixels` | Integer | Total valid pixels analyzed |

## Classification Criteria

A roof is classified as a **green roof** if:
- At least **30%** of the roof area has NDVI > 0.25
- AND average NDVI > 0.15

These thresholds can be adjusted in the Python script.

## Python Script (PythonCaller)

```python
# FME PythonCaller Script: Green Roof Statistics from NDVI raster
# Input: Single-band NDVI raster (output from RasterExpressionEvaluator)
# Expression used: (A[0] - A[1]) / (A[0] + A[1])
# Output: Green roof statistics with preserved incoming attributes

import fmeobjects
import numpy as np
import traceback

# Configuration
NDVI_THRESHOLD = 0.25  # Threshold for "green" classification

class FeatureProcessor(object):
    
    def __init__(self):
        self._incoming_attributes = []  # Store attribute names to preserve
    
    def input(self, feature):
        debug_info = []
        
        # Store all incoming attribute names and values
        incoming_attrs = {}
        for attr_name in feature.getAllAttributeNames():
            incoming_attrs[attr_name] = feature.getAttribute(attr_name)
        
        try:
            debug_info.append("Step 1: Get raster")
            geom = feature.getGeometry()
            
            if geom is None or not isinstance(geom, fmeobjects.FMERaster):
                self._set_error(feature, debug_info, "Not a raster", incoming_attrs)
                return
            
            raster = geom
            
            # Get dimensions
            props = raster.getProperties()
            num_rows = props.getNumRows()
            num_cols = props.getNumCols()
            num_bands = raster.getNumBands()
            debug_info.append(f"{num_rows}x{num_cols}, {num_bands} band(s)")
            
            # Calculate pixel area from bounds
            debug_info.append("Step 2: Pixel area")
            try:
                bbox = raster.boundingBox()
                pixel_width = (bbox[1][0] - bbox[0][0]) / num_cols
                pixel_height = (bbox[1][1] - bbox[0][1]) / num_rows
                pixel_area = abs(pixel_width * pixel_height)
                debug_info.append(f"{pixel_area:.4f} m2/pixel")
            except:
                pixel_area = 0.01  # Default 10cm resolution
                debug_info.append("Using default 0.01 m2")
            
            # Get NDVI band (band 0)
            debug_info.append("Step 3: Get NDVI data")
            band = raster.getBand(0)
            band_props = band.getProperties()
            interp = band_props.getInterpretation()
            debug_info.append(f"Interp: {interp}")
            
            # Try Real64 tile first (NDVI output), then Real32
            tile = None
            data = None
            
            for tile_class in [fmeobjects.FMEReal64Tile, fmeobjects.FMEReal32Tile]:
                try:
                    tile = tile_class(num_rows, num_cols)
                    tile = band.getTile(0, 0, tile)
                    data = tile.getData()
                    debug_info.append(f"Got data via {tile_class.__name__}")
                    break
                except Exception as e:
                    debug_info.append(f"{tile_class.__name__} failed")
                    continue
            
            if data is None:
                self._set_error(feature, debug_info, "Could not read NDVI tile", incoming_attrs)
                return
            
            # Convert to numpy
            debug_info.append("Step 4: Calculate stats")
            ndvi = np.array(data, dtype=np.float64)
            debug_info.append(f"Shape: {ndvi.shape}")
            debug_info.append(f"Range: {ndvi.min():.3f} to {ndvi.max():.3f}")
            
            # Filter valid NDVI values (-1 to 1 range, exclude nodata)
            valid_mask = (ndvi >= -1) & (ndvi <= 1) & ~np.isnan(ndvi)
            valid_ndvi = ndvi[valid_mask]
            debug_info.append(f"Valid pixels: {len(valid_ndvi)}")
            
            if len(valid_ndvi) == 0:
                self._set_error(feature, debug_info, "No valid NDVI values", incoming_attrs)
                return
            
            # Calculate statistics
            ndvi_avg = float(np.mean(valid_ndvi))
            ndvi_min = float(np.min(valid_ndvi))
            ndvi_max = float(np.max(valid_ndvi))
            
            green_pixels = int(np.sum(valid_ndvi > NDVI_THRESHOLD))
            total_pixels = len(valid_ndvi)
            green_area_m2 = green_pixels * pixel_area
            green_percentage = (green_pixels / total_pixels) * 100
            
            # Classification
            is_green_roof = 'Yes' if (green_percentage >= 30 and ndvi_avg > 0.15) else 'No'
            
            debug_info.append(f"NDVI avg: {ndvi_avg:.3f}")
            debug_info.append(f"Green: {green_percentage:.1f}% ({green_area_m2:.1f} m2)")
            debug_info.append(f"Result: {is_green_roof}")
            
            # Re-apply all incoming attributes first (ensures they're preserved)
            for attr_name, attr_value in incoming_attrs.items():
                feature.setAttribute(attr_name, attr_value)
            
            # Set new output attributes (will overwrite if names conflict)
            feature.setAttribute('_ndvi_avg', round(ndvi_avg, 4))
            feature.setAttribute('_ndvi_min', round(ndvi_min, 4))
            feature.setAttribute('_ndvi_max', round(ndvi_max, 4))
            feature.setAttribute('_is_green_roof', is_green_roof)
            feature.setAttribute('_green_area_m2', round(green_area_m2, 2))
            feature.setAttribute('_green_percentage', round(green_percentage, 2))
            feature.setAttribute('_green_pixels', green_pixels)
            feature.setAttribute('_total_pixels', total_pixels)
            feature.setAttribute('_pixel_area_m2', round(pixel_area, 6))
            debug_info.append("SUCCESS")
            
        except Exception as e:
            debug_info.append(f"ERROR: {str(e)}")
            self._set_error(feature, debug_info, str(e), incoming_attrs)
            return
        
        feature.setAttribute('_debug', ' | '.join(debug_info))
        self.pyoutput(feature)
    
    def _set_error(self, feature, debug_info, msg, incoming_attrs=None):
        # Re-apply incoming attributes even on error
        if incoming_attrs:
            for attr_name, attr_value in incoming_attrs.items():
                feature.setAttribute(attr_name, attr_value)
        
        feature.setAttribute('_is_green_roof', 'Error')
        feature.setAttribute('_error_message', msg)
        feature.setAttribute('_debug', ' | '.join(debug_info))
        self.pyoutput(feature)
    
    def close(self):
        pass
```

## Requirements

- FME Form 2024.0 or later
- Python 3.x with NumPy (included with FME)
- swissIMAGE RS data (order from geodata@swisstopo.ch)
- swissBUILDINGS3D data

## Notes

- swissIMAGE RS has 10cm resolution in flat areas, 25cm in mountains
- Summer imagery provides better vegetation detection
- NDVI values range from -1 to +1, with values > 0.2-0.3 indicating vegetation
- The coordinate system should be set to LV95 (EPSG:2056) for Swiss data

## License

This workflow is provided as-is for educational and research purposes.

## Author

Created with FME Form and Claude AI assistance.
