
import os
import rasterio
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_rs_data(rs_dir):
    rs_path = Path(rs_dir)
    
    logger.info(f"Checking directory: {rs_path}")
    
    if not rs_path.exists():
        logger.error("Directory does not exist!")
        return

    # Find files
    # Case insensitive search
    files = [f for f in rs_path.iterdir() if f.suffix.lower() in ['.tif', '.tiff']]
    
    logger.info(f"Found {len(files)} TIFF files.")
    
    if not files:
        logger.warning(f"No TIFF files found. Content of {rs_dir}:")
        for x in list(rs_path.iterdir())[:10]:
             logger.info(f" - {x.name}")
        return

    # Check first 5 files
    logger.info("Checking first 5 files for CRS and Bounds:")
    for f in files[:5]:
        try:
            with rasterio.open(f) as src:
                logger.info(f"File: {f.name}")
                logger.info(f"  CRS: {src.crs}")
                logger.info(f"  Bounds: {src.bounds}")
                logger.info(f"  Bands: {src.count}")
        except Exception as e:
            logger.error(f"  Error reading {f.name}: {e}")

if __name__ == "__main__":
    # Hardcoded path from user request
    check_rs_data(r"D:\SwissRS")
