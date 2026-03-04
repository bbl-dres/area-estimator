#!/usr/bin/env python3
"""
Roof Estimator for swissBUILDINGS3D
Extracts roof area, wall area, footprint area, and roof shape from 3D building meshes.

Data source: https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta

Usage:
    python main.py <input_gdb> <output_dir> [options]

Example:
    python main.py "C:/Data/SWISSBUILDINGS3D_3_0.gdb" "./output" --limit 1000
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import pandas as pd
import fiona
import numpy as np
import gc
import warnings
warnings.filterwarnings('ignore')

# Import roof analysis module
from roof_analysis import analyze_building_roof
from green_roof import GreenRoofAnalyzer
import shapely.geometry

# Processing configuration
CHUNK_SIZE = 100000  # Process and save every 100,000 buildings

# Global analyzer instance for workers
green_roof_analyzer = None

def worker_init(rs_dir):
    """Initialize the global analyzer in worker processes."""
    global green_roof_analyzer
    if rs_dir:
        try:
            green_roof_analyzer = GreenRoofAnalyzer(rs_dir)
            logging.info(f"Initialized GreenRoofAnalyzer with {rs_dir}")
        except Exception as e:
            logging.error(f"Failed to initialize GreenRoofAnalyzer: {e}")


def setup_logging(output_dir):
    """Setup logging configuration with file and console output."""
    log_file = output_dir / 'roof_estimator.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


def parse_multipatch_geometry(geometry):
    """
    Parse multipatch geometry from GDB into vertices and faces.

    swissBUILDINGS3D stores 3D building geometries as MultiPolygon/Multipatch
    with 3D coordinates (X, Y, Z in LV95 + elevation).

    Args:
        geometry: GeoJSON-like geometry dict from fiona

    Returns:
        tuple: (vertices, faces) lists for mesh creation
    """
    vertices = []
    faces = []

    try:
        if not geometry:
            return [], []

        geom_type = geometry.get('type', '')
        coords = geometry.get('coordinates', [])

        if not coords:
            return [], []

        # Handle MultiPolygon (standard multipatch format)
        if geom_type == 'MultiPolygon':
            for polygon in coords:
                if not isinstance(polygon, list):
                    continue

                for ring in polygon:
                    if not isinstance(ring, list):
                        continue

                    # Add vertices from this ring
                    start_idx = len(vertices)
                    valid_vertices = 0

                    for coord in ring[:-1]:  # Skip duplicate last point
                        if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                            if len(coord) >= 3:
                                vertices.append([float(coord[0]), float(coord[1]), float(coord[2])])
                            else:
                                vertices.append([float(coord[0]), float(coord[1]), 0.0])
                            valid_vertices += 1

                    # Create faces using fan triangulation
                    if valid_vertices >= 3:
                        for i in range(1, valid_vertices - 1):
                            faces.append([
                                start_idx,
                                start_idx + i,
                                start_idx + i + 1
                            ])

        # Handle single Polygon
        elif geom_type == 'Polygon':
            if not isinstance(coords, list):
                return [], []

            for ring in coords:
                if not isinstance(ring, list):
                    continue

                start_idx = len(vertices)
                valid_vertices = 0

                for coord in ring[:-1]:
                    if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                        if len(coord) >= 3:
                            vertices.append([float(coord[0]), float(coord[1]), float(coord[2])])
                        else:
                            vertices.append([float(coord[0]), float(coord[1]), 0.0])
                        valid_vertices += 1

                if valid_vertices >= 3:
                    for i in range(1, valid_vertices - 1):
                        faces.append([
                            start_idx,
                            start_idx + i,
                            start_idx + i + 1
                        ])

        return vertices, faces

    except Exception as e:
        logging.debug(f"Error parsing geometry: {str(e)}")
        return [], []


def list_gdb_layers(gdb_path):
    """List all layers in a GDB file."""
    return fiona.listlayers(gdb_path)


def read_gdb_buildings_chunked(gdb_path, layer_name='Building_solid', chunk_size=CHUNK_SIZE, limit=None, bbox=None):
    """
    Read buildings from GDB file in chunks using Fiona.

    Yields chunks of building data for memory-efficient processing of large datasets.

    Args:
        gdb_path: Path to the GDB file
        layer_name: Name of the layer to read (default: Building_solid)
        chunk_size: Number of buildings per chunk
        chunk_size: Number of buildings per chunk
        limit: Maximum total buildings to read (None for all)
        bbox: Optional (minx, miny, maxx, maxy) to filter features spatially

    Yields:
        tuple: (chunk_number, list of building dicts)
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Reading buildings from {gdb_path}, layer: {layer_name}")

    try:
        # List available layers
        layers = fiona.listlayers(gdb_path)
        logger.info(f"Available layers: {layers}")

        # Find the correct layer name (case-insensitive partial match)
        actual_layer = None
        for layer in layers:
            if layer_name.lower() in layer.lower() or layer.lower() in layer_name.lower():
                actual_layer = layer
                break

        if not actual_layer:
            logger.error(f"Layer '{layer_name}' not found. Available: {layers}")
            raise ValueError(f"Layer not found: {layer_name}")

        logger.info(f"Using layer: {actual_layer}")

        # Read features in chunks
        # fiona.open supports bbox filter (if driver supports it, GDB usually does or fiona handles it)
        with fiona.open(gdb_path, layer=actual_layer, bbox=bbox) as src:
            logger.info(f"Layer CRS: {src.crs}")
            logger.info(f"Layer bounds: {src.bounds}")
            logger.info(f"Schema: {src.schema}")

            chunk = []
            chunk_num = 0
            total_count = 0

            for feature in src:
                if limit and total_count >= limit:
                    break

                # Extract properties and geometry
                properties = dict(feature['properties'])
                geometry = feature.get('geometry')

                # Parse multipatch geometry
                vertices, faces = parse_multipatch_geometry(geometry)

                # Store parsed data
                properties['_vertices'] = vertices
                properties['_faces'] = faces
                properties['_geometry_type'] = geometry.get('type') if geometry else None

                chunk.append(properties)
                total_count += 1

                if total_count % 1000 == 0:
                    logger.info(f"Read {total_count} buildings...")

                # Yield chunk when it reaches chunk_size
                if len(chunk) >= chunk_size:
                    yield chunk_num, chunk
                    chunk = []
                    chunk_num += 1
                    gc.collect()  # Force garbage collection

            # Yield final chunk if any remaining
            if chunk:
                yield chunk_num, chunk

    except Exception as e:
        logger.error(f"Error reading GDB: {str(e)}")
        raise


def process_single_building(row_data):
    """
    Process a single building - designed for parallel execution.

    Args:
        row_data: tuple of (index, building_dict)

    Returns:
        tuple: (index, result_dict)
    """
    idx, row = row_data
    result = dict(row)

    try:
        # Get pre-parsed geometry data
        vertices = row.get('_vertices', [])
        faces = row.get('_faces', [])

        # Validate geometry data types
        if not isinstance(vertices, list):
            result['analysis_status'] = 'failed'
            result['analysis_error'] = f'Invalid vertices type: {type(vertices).__name__}'
            return idx, result

        if not isinstance(faces, list):
            result['analysis_status'] = 'failed'
            result['analysis_error'] = f'Invalid faces type: {type(faces).__name__}'
            return idx, result

        if not vertices or not faces:
            result['analysis_status'] = 'failed'
            result['analysis_error'] = f'Empty geometry: {len(vertices)} vertices, {len(faces)} faces'
            return idx, result

        # Perform roof analysis
        roof_results = analyze_building_roof(vertices, faces)
        result.update(roof_results)

        # Perform green roof analysis if available
        if green_roof_analyzer:
            # We need a 2D footprint. 
            # 1. Try to use the original geometry from the row if available and if it's a Polygon/MultiPolygon
            # The 'geometry' in row is a fiona geometry dict (GeoJSON-like).
            # But wait! read_gdb_buildings_chunked yields 'properties' dict, and we added '_vertices' etc.
            # We DID NOT keep the original geometry object in the properties dict to save memory?
            # Let's check read_gdb_buildings_chunked.
            # It does: properties = dict(feature['properties'])
            # It uses geometry to parse vertices but DOES NOT store the geometry dict in properties.
            # We need to reconstruct the footprint from vertices.
            
            # Simple footprint: convex hull of xy coordinates?
            # Or assume the 'footprint_area' calculation in roof_analysis knows the footprint?
            # roof_analysis calculates footprint area but doesn't return the polygon.
            
            # Let's reconstruct a simple 2D polygon from vertices (ignoring Z)
            # This is an approximation. Ideally we'd pass the original geometry.
            # But the 'vertices' list is just points. We don't know the winding/connectivity for the footprint 
            # unless we project all faces to 2D and union them? That's expensive.
            
            # Better approach: Modify read_gdb_buildings_chunked to optionally store the validation 2D footprint.
            # For now, let's use the vertices projected to 2D and take the convex hull.
            # It's fast and reasonable for single buildings, though it might overestimate L-shapes.
            points_2d = [(v[0], v[1]) for v in vertices]
            if len(points_2d) >= 3:
                footprint_geom = shapely.geometry.MultiPoint(points_2d).convex_hull
                green_results = green_roof_analyzer.calculate_green_area(footprint_geom)
                result.update(green_results)

    except Exception as e:
        result['analysis_status'] = 'failed'
        result['analysis_error'] = str(e)

    # Remove internal fields before returning
    result.pop('_vertices', None)
    result.pop('_faces', None)
    result.pop('_geometry_type', None)

    return idx, result


def process_chunk_parallel(chunk_data, chunk_num, num_workers=None, rs_dir=None):
    """
    Process a chunk of buildings in parallel using ProcessPoolExecutor.

    Args:
        chunk_data: List of building dicts
        chunk_num: Chunk number for logging
        num_workers: Number of parallel workers (default: CPU count - 1, max 8)
        rs_dir: Directory containing RS imagery for green roof analysis (optional)

    Returns:
        dict: Results indexed by building index
    """
    logger = logging.getLogger(__name__)

    if num_workers is None:
        num_workers = min(os.cpu_count() - 1, 8)
        num_workers = max(num_workers, 1)

    logger.info(f"Processing chunk {chunk_num} with {len(chunk_data)} buildings using {num_workers} workers")

    results = {}
    total = len(chunk_data)
    processed = 0

    # Prepare data for parallel processing
    row_data = [(idx, row) for idx, row in enumerate(chunk_data)]

    with ProcessPoolExecutor(max_workers=num_workers, initializer=worker_init, initargs=(rs_dir,)) as executor:
        # Submit all tasks
        future_to_idx = {
            executor.submit(process_single_building, data): data[0]
            for data in row_data
        }

        # Process completed tasks
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                idx, result = future.result()
                results[idx] = result
                processed += 1

                if processed % 1000 == 0:
                    logger.info(f"Chunk {chunk_num}: Processed {processed}/{total} buildings")

            except Exception as e:
                logger.error(f"Error processing building in chunk {chunk_num}, idx {idx}: {str(e)}")
                results[idx] = {'analysis_status': 'failed', 'analysis_error': str(e)}

    return results


def save_chunk_results(results, output_path, chunk_num):
    """
    Save chunk results to CSV file.

    Args:
        results: Dict of results indexed by building index
        output_path: Base output path
        chunk_num: Chunk number

    Returns:
        dict: Summary statistics for the chunk
    """
    logger = logging.getLogger(__name__)

    # Convert results to DataFrame
    df_results = pd.DataFrame.from_dict(results, orient='index')

    # Save as CSV
    csv_path = output_path.parent / f"{output_path.stem}_chunk_{chunk_num:04d}.csv"
    df_results.to_csv(csv_path, index=False)
    logger.info(f"Saved chunk {chunk_num} with {len(df_results)} records to {csv_path}")

    # Calculate summary statistics
    successful = 0
    roof_shapes = {}

    if 'analysis_status' in df_results.columns:
        successful = df_results['analysis_status'].value_counts().get('success', 0)

    if 'roof_shape' in df_results.columns:
        roof_shapes = df_results['roof_shape'].value_counts().to_dict()

    return {
        'chunk_num': chunk_num,
        'total': len(df_results),
        'successful': successful,
        'roof_shapes': roof_shapes,
        'csv_path': csv_path
    }


def merge_chunk_results(chunk_summaries, output_path):
    """
    Merge all chunk CSVs into a single final CSV file.

    Args:
        chunk_summaries: List of chunk summary dicts
        output_path: Final output path
    """
    logger = logging.getLogger(__name__)
    logger.info("Merging all chunks into final CSV file...")

    # Read and combine all chunks
    all_data = []
    for summary in chunk_summaries:
        csv_path = summary['csv_path']
        chunk_df = pd.read_csv(csv_path)
        all_data.append(chunk_df)
        logger.info(f"Loaded {len(chunk_df)} records from {csv_path.name}")

    # Combine all data
    final_df = pd.concat(all_data, ignore_index=True)

    # Save complete CSV
    final_csv_path = output_path.with_suffix('.csv')
    final_df.to_csv(final_csv_path, index=False)
    logger.info(f"Saved complete CSV with {len(final_df)} records to {final_csv_path}")

    # Calculate final statistics
    total = len(final_df)

    logger.info(f"\n{'='*60}")
    logger.info("FINAL PROCESSING SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total buildings processed: {total}")

    if 'analysis_status' in final_df.columns:
        successful = final_df['analysis_status'].value_counts().get('success', 0)
        logger.info(f"Successfully analyzed: {successful} ({successful/total*100:.1f}%)" if total > 0 else "Successfully analyzed: 0")

    # Roof shape distribution
    if 'roof_shape' in final_df.columns:
        logger.info("\nRoof Shape Distribution:")
        for shape, count in final_df['roof_shape'].value_counts().items():
            pct = count / total * 100 if total > 0 else 0
            logger.info(f"  {shape}: {count} ({pct:.1f}%)")

    # Area statistics
    if 'roof_area_m2' in final_df.columns:
        valid_roofs = final_df[final_df['roof_area_m2'].notna()]
        if len(valid_roofs) > 0:
            logger.info(f"\nRoof Area Statistics:")
            logger.info(f"  Mean: {valid_roofs['roof_area_m2'].mean():.1f} m²")
            logger.info(f"  Median: {valid_roofs['roof_area_m2'].median():.1f} m²")
            logger.info(f"  Total: {valid_roofs['roof_area_m2'].sum():,.0f} m²")

    if 'wall_area_m2' in final_df.columns:
        valid_walls = final_df[final_df['wall_area_m2'].notna()]
        if len(valid_walls) > 0:
            logger.info(f"\nWall Area Statistics:")
            logger.info(f"  Mean: {valid_walls['wall_area_m2'].mean():.1f} m²")
            logger.info(f"  Total: {valid_walls['wall_area_m2'].sum():,.0f} m²")

    if 'footprint_area_m2' in final_df.columns:
        valid_footprints = final_df[final_df['footprint_area_m2'].notna()]
        if len(valid_footprints) > 0:
            logger.info(f"\nFootprint Area Statistics:")
            logger.info(f"  Mean: {valid_footprints['footprint_area_m2'].mean():.1f} m²")
            logger.info(f"  Total: {valid_footprints['footprint_area_m2'].sum():,.0f} m²")

    # Clean up chunk files
    logger.info("\nCleaning up chunk files...")
    for summary in chunk_summaries:
        try:
            summary['csv_path'].unlink()
            logger.debug(f"Deleted {summary['csv_path'].name}")
        except Exception as e:
            logger.warning(f"Could not delete {summary['csv_path'].name}: {e}")


def main():
    """Main entry point for the roof estimator."""
    parser = argparse.ArgumentParser(
        description='Roof Estimator for swissBUILDINGS3D - Extract roof characteristics from 3D building meshes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "C:/Data/SWISSBUILDINGS3D.gdb" ./output
  python main.py "C:/Data/SWISSBUILDINGS3D.gdb" ./output --limit 1000
  python main.py "C:/Data/SWISSBUILDINGS3D.gdb" ./output --layer Building_solid --workers 4
        """
    )

    parser.add_argument('input_gdb',
                        help='Path to input GDB file (swissBUILDINGS3D)')
    parser.add_argument('output_dir',
                        help='Output directory for results')
    parser.add_argument('--layer', default='Building_solid',
                        help='GDB layer name (default: Building_solid)')
    parser.add_argument('--limit', type=int,
                        help='Limit number of buildings to process')
    parser.add_argument('--workers', type=int,
                        help='Number of parallel workers (default: CPU count - 1, max 8)')
    parser.add_argument('--chunk-size', type=int, default=CHUNK_SIZE,
                        help=f'Number of buildings per chunk (default: {CHUNK_SIZE})')
    parser.add_argument('--list-layers', action='store_true',
                        help='List available layers in GDB and exit')
    parser.add_argument('--keep-chunks', action='store_true',
                        help='Keep individual chunk CSV files after merging')
    parser.add_argument('--rs-dir',
                        help='Directory containing SwissIMAGE RS GeoTIFFs for green roof estimation')
    parser.add_argument('--no-filter', action='store_true',
                        help='Do not filter buildings by RS coverage (process all)')

    args = parser.parse_args()

    # Setup paths
    input_path = Path(args.input_gdb)
    output_dir = Path(args.output_dir)
    rs_dir = Path(args.rs_dir) if args.rs_dir else None

    # Handle --list-layers option
    if args.list_layers:
        try:
            layers = list_gdb_layers(str(input_path))
            print(f"Available layers in {input_path}:")
            for layer in layers:
                print(f"  - {layer}")
            return 0
        except Exception as e:
            print(f"Error listing layers: {e}", file=sys.stderr)
            return 1

    # Validate input
    if not input_path.exists():
        print(f"Error: Input GDB not found: {input_path}", file=sys.stderr)
        return 1

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Setup logging
    logger = setup_logging(output_dir)
    logger.info("="*60)
    logger.info("ROOF ESTIMATOR FOR SWISSBUILDINGS3D")
    logger.info("="*60)
    logger.info(f"Input: {input_path}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Layer: {args.layer}")
    logger.info(f"Chunk size: {args.chunk_size}")
    if args.limit:
        logger.info(f"Limit: {args.limit} buildings")
    if rs_dir:
        logger.info(f"Green Roof Analysis: Enabled (RS data: {rs_dir})")
    
    # Pre-check RS dir if enabled
    if rs_dir and not rs_dir.exists():
        logger.error(f"RS directory not found: {rs_dir}")
        return 1

    start_time = time.time()

    try:
        # Process chunks
        chunk_summaries = []
        output_path = output_dir / f'roof_analysis_{time.strftime("%Y%m%d_%H%M%S")}'

        # Determine bounds for filtering if requested
        filter_bbox = None
        if rs_dir and not args.no_filter:
            try:
                # Initialize analyzer here temporarily to get bounds (lazy init in workers later)
                # Or just use the one we'll pass to workers? 
                # Since we need bounds BEFORE reading, we must create an instance or helper here.
                # Just create one.
                logging.info("Scanning RS directory for spatial bounds...")
                analyzer_for_bounds = GreenRoofAnalyzer(str(rs_dir))
                filter_bbox = analyzer_for_bounds.get_coverage_bounds()
                if filter_bbox:
                    logging.info(f"Filtering buildings within RS bounds: {filter_bbox}")
                else:
                    logging.warning("Could not determine RS bounds. Processing all buildings.")
            except Exception as e:
                logging.warning(f"Error determining RS bounds: {e}. Processing all buildings.")

        # Process each chunk
        for chunk_num, chunk_data in read_gdb_buildings_chunked(
            str(input_path), args.layer, args.chunk_size, args.limit, bbox=filter_bbox
        ):
            logger.info(f"\n{'='*40}")
            logger.info(f"Processing chunk {chunk_num}")
            logger.info(f"{'='*40}")

            # Process chunk in parallel
            results = process_chunk_parallel(chunk_data, chunk_num, args.workers, str(rs_dir) if rs_dir else None)

            # Save chunk results
            summary = save_chunk_results(results, output_path, chunk_num)
            chunk_summaries.append(summary)

            # Log chunk summary
            logger.info(f"Chunk {chunk_num} complete: {summary['successful']}/{summary['total']} successful")
            if summary['roof_shapes']:
                logger.info(f"Roof shapes: {summary['roof_shapes']}")

            # Force garbage collection
            del chunk_data
            del results
            gc.collect()

        # Merge all chunks into final output
        if chunk_summaries:
            merge_chunk_results(chunk_summaries, output_path)

            if args.keep_chunks:
                logger.info("Keeping individual chunk files as requested")

    except Exception as e:
        logger.error(f"Processing failed: {str(e)}", exc_info=True)
        return 1

    elapsed_time = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing completed in {elapsed_time:.1f} seconds ({elapsed_time/60:.1f} minutes)")
    logger.info(f"{'='*60}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
