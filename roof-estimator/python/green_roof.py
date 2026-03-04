
import os
import glob
import logging
import numpy as np
import rasterio
from rasterio.mask import mask
import shapely.geometry
from shapely.strtree import STRtree
from pathlib import Path

# Constants for NDVI calculation
# Assuming Band 1 = Red, Band 4 = NIR (standard for many products)
# Adjust these based on specific sensor data if needed
BAND_RED = 1
BAND_NIR = 4

class RasterIndexer:
    """
    Indexes GeoTIFF files in a directory for fast spatial lookups.
    Uses an R-tree (STRtree) to find which raster contains a given geometry.
    """
    def __init__(self, raster_dir):
        self.raster_dir = Path(raster_dir)
        self.raster_paths = []
        self.geometries = []
        self.tree = None
        self._build_index()

    def _build_index(self):
        logger = logging.getLogger(__name__)
        logger.info(f"Indexing rasters in {self.raster_dir}...")
        
        # Find all .tif files
        tif_files = list(self.raster_dir.glob("*.tif")) + list(self.raster_dir.glob("*.tiff"))
        
        for tif_path in tif_files:
            try:
                with rasterio.open(tif_path) as src:
                    bbox = src.bounds
                    # Create a polygon from bounds
                    geom = shapely.geometry.box(bbox.left, bbox.bottom, bbox.right, bbox.top)
                    self.raster_paths.append(str(tif_path))
                    self.geometries.append(geom)
            except Exception as e:
                logger.warning(f"Failed to read bounds for {tif_path}: {e}")

        if self.geometries:
            self.tree = STRtree(self.geometries)
            logger.info(f"Indexed {len(self.geometries)} rasters.")
        else:
            logger.warning("No valid rasters found to index.")

    def query(self, geometry):
        """
        Find rasters intersecting with the given geometry.
        Returns a list of file paths.
        """
        if not self.tree:
            return []
        
        # query returns indices of geometries that intersect
        indices = self.tree.query(geometry)
        
        # STRtree.query returns a list of indices in modern shapely versions
        # or an iterable. Handle appropriately.
        return [self.raster_paths[i] for i in indices]

    def get_total_bounds(self):
        """Returns the total bounding box (minx, miny, maxx, maxy) of all indexed rasters."""
        if not self.geometries:
            return None
        
        # Calculate union of all bounds
        # Efficient way: min/max of all bounds
        minx = min(g.bounds[0] for g in self.geometries)
        miny = min(g.bounds[1] for g in self.geometries)
        maxx = max(g.bounds[2] for g in self.geometries)
        maxy = max(g.bounds[3] for g in self.geometries)
        
        return (minx, miny, maxx, maxy)

class GreenRoofAnalyzer:
    """
    Analyzes building geometries against aerial imagery to detect green usage.
    """
    def __init__(self, raster_dir, ndvi_threshold=0.2):
        self.indexer = RasterIndexer(raster_dir)
        self.ndvi_threshold = ndvi_threshold
    
    def get_coverage_bounds(self):
        """Returns the spatial bounds of the available imagery."""
        return self.indexer.get_total_bounds()
    
    
    def calculate_green_area(self, building_geometry_mapping):
        """
        Calculate green roof area for a single building.
        
        Args:
            building_geometry_mapping: A GeoJSON-like dictionary or shapely geometry
                                     representing the building footprint/roof.
        
        Returns:
            dict: {
                'green_roof_area_m2': float,
                'green_roof_percentage': float,
                'ndvi_mean': float,
                'ndvi_max': float
            }
        """
        # Convert input to shapely geometry if it's a dict
        if isinstance(building_geometry_mapping, dict):
            # Assuming it's a GeoJSON geometry object
             try:
                geom = shapely.geometry.shape(building_geometry_mapping)
             except:
                # If it's the raw properties from GDB with _vertices, we might need
                # to reconstruct the polygon. However, main.py passes the raw read
                # which usually contains 'geometry' key if it's from fiona.
                # BUT, the processed dict in main.py has `_vertices` and `_faces`.
                # We need the 2D footprint for raster analysis.
                # Let's handle the case where we pass a polygon created from footprint.
                return {'error': 'Invalid geometry input'}
        else:
            geom = building_geometry_mapping

        results = {
            'green_roof_area_m2': 0.0,
            'green_roof_percentage': 0.0,
            'ndvi_mean': None, 
            'ndvi_max': None,
            'green_roof_status': 'unknown'
        }

        # Find intersecting raster
        raster_paths = self.indexer.query(geom)
        if not raster_paths:
            results['green_roof_status'] = 'no_coverage'
            return results

        # Use the first intersecting raster (handling edge cases spanning multiple tiles is complex
        # and usually buildings are small enough to be in one, or we just take the first one)
        # Proper way: merge if spanning. For MVP, take first.
        tif_path = raster_paths[0]

        try:
            with rasterio.open(tif_path) as src:
                # Mask the raster to the building geometry
                # crop=True clips the array to the bounding box of the geometry
                out_image, out_transform = mask(src, [geom], crop=True, nodata=0)
                
                # out_image is (bands, height, width)
                # Check we have enough bands
                if out_image.shape[0] < max(BAND_RED, BAND_NIR):
                    results['error'] = 'Insufficient bands'
                    return results

                # Extract Red and NIR
                # Band indices are 0-based in array, but 1-based in constants
                red = out_image[BAND_RED - 1].astype(float)
                nir = out_image[BAND_NIR - 1].astype(float)

                # Avoid division by zero
                # NDVI = (NIR - Red) / (NIR + Red)
                denominator = nir + red
                # Mask out zero/nodata values (where denominator is 0)
                valid_mask = denominator != 0
                
                ndvi = np.zeros_like(red)
                ndvi[valid_mask] = (nir[valid_mask] - red[valid_mask]) / denominator[valid_mask]

                # only consider pixels inside the geometry (mask sets outside to nodata=0)
                # But Red+NIR=0 might be real black pixels. 
                # The 'mask' function sets values outside the shape to 'nodata'.
                # if nodata is 0, we might confuse it.
                # Better: mask returns data where outside is masked?
                # Actually 'mask' returns a numpy array.
                
                # Let's count vegetation pixels
                vegetation_pixels = np.logical_and(valid_mask, ndvi > self.ndvi_threshold)
                
                pixel_area_m2 = src.res[0] * src.res[1] # Resolution x * y
                
                green_area = np.sum(vegetation_pixels) * pixel_area_m2
                
                # Total area of validity (pixels inside the polygon)
                # We can estimate this better or just use the non-masked pixels count
                # The mask function zeroes out outside pixels. 
                # If we assume 0 is nodata, then any non-zero pixel is valid?
                # A safer way with 'mask' is it fills outside with fill value. default 0.
                
                total_valid_pixels = np.count_nonzero(valid_mask)
                total_area = total_valid_pixels * pixel_area_m2
                
                results['green_roof_area_m2'] = round(green_area, 2)
                if total_area > 0:
                    results['green_roof_percentage'] = round((green_area / total_area) * 100, 1)
                    results['ndvi_mean'] = round(np.mean(ndvi[valid_mask]), 3)
                    results['ndvi_max'] = round(np.max(ndvi[valid_mask]), 3)
                    results['green_roof_status'] = 'analyzed'
                else:
                    results['green_roof_status'] = 'empty_mask'

        except Exception as e:
            logging.error(f"Error processing green roof for {geom}: {e}")
            results['green_roof_status'] = 'error'
            results['error'] = str(e)

        return results
