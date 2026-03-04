#!/usr/bin/env python3
"""
Main orchestrator script for processing Swisstopo 3D building data
Reads GDB multipatch data, calculates volumes and surface areas
Processes in chunks to handle large datasets without memory issues
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
from fiona.crs import from_epsg
import numpy as np
import gc
import warnings
warnings.filterwarnings('ignore')

# Import our modules
from mesh_repair_volume import process_building_mesh
from surface_analysis import analyze_building_surfaces

CHUNK_SIZE = 5000  # Process and save every 1000 buildings

def setup_logging(output_dir):
    """Setup logging configuration"""
    log_file = output_dir / 'processing.log'
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
    """Parse multipatch geometry from GDB"""
    vertices = []
    faces = []
    
    try:
        if not geometry:
            return [], []
            
        geom_type = geometry.get('type', '')
        coords = geometry.get('coordinates', [])
        
        if not coords:
            return [], []
        
        # Multipatch geometry structure in GDB
        if geom_type == 'MultiPolygon':
            # For each polygon in the multipatch
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
                    
                    # Create faces (fan triangulation)
                    if valid_vertices >= 3:
                        for i in range(1, valid_vertices - 1):
                            faces.append([
                                start_idx,
                                start_idx + i,
                                start_idx + i + 1
                            ])
        
        elif geom_type == 'Polygon':
            # Single polygon
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

def read_gdb_buildings_chunked(gdb_path, layer_name='Building_solid', chunk_size=CHUNK_SIZE, limit=None):
    """Read buildings from GDB file in chunks using Fiona"""
    logger = logging.getLogger(__name__)
    logger.info(f"Reading buildings from {gdb_path}, layer: {layer_name}")
    
    try:
        # List available layers
        layers = fiona.listlayers(gdb_path)
        logger.info(f"Available layers: {layers}")
        
        # Find the correct layer name
        actual_layer = None
        for layer in layers:
            if layer_name in layer or layer in layer_name:
                actual_layer = layer
                break
        
        if not actual_layer:
            logger.error(f"Layer '{layer_name}' not found. Available: {layers}")
            raise ValueError(f"Layer not found")
        
        logger.info(f"Using layer: {actual_layer}")
        
        # Read features in chunks
        with fiona.open(gdb_path, layer=actual_layer) as src:
            logger.info(f"Layer CRS: {src.crs}")
            logger.info(f"Layer bounds: {src.bounds}")
            
            chunk = []
            chunk_num = 0
            total_count = 0
            
            for feature in src:
                if limit and total_count >= limit:
                    if chunk:  # Yield remaining chunk
                        yield chunk_num, chunk
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
                
                if total_count % 100 == 0:
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
    """Process a single building - runs in parallel"""
    idx, row = row_data
    result = dict(row)
    
    try:
        # Get pre-parsed geometry data
        vertices = row.get('_vertices', [])
        faces = row.get('_faces', [])
        
        # Validate that vertices and faces are lists
        if not isinstance(vertices, list):
            result['processing_status'] = 'failed'
            result['processing_error'] = f'Invalid vertices type: {type(vertices).__name__}'
            result['mesh_process_error'] = 'Vertices must be a list'
            return idx, result
            
        if not isinstance(faces, list):
            result['processing_status'] = 'failed'
            result['processing_error'] = f'Invalid faces type: {type(faces).__name__}'
            result['mesh_process_error'] = 'Faces must be a list'
            return idx, result
        
        if not vertices or not faces:
            result['processing_status'] = 'failed'
            result['processing_error'] = 'No geometry data'
            result['mesh_process_error'] = f'Empty vertices ({len(vertices)}) or faces ({len(faces)})'
            return idx, result
        
        # Step 1: Mesh repair and volume calculation
        mesh_results = process_building_mesh(vertices, faces)
        result.update(mesh_results)
        
        # Step 2: Surface analysis (only if mesh processing succeeded)
        if mesh_results.get('mesh_volume') is not None:
            surface_results = analyze_building_surfaces(vertices, faces)
            result.update(surface_results)
        
        result['processing_status'] = 'success'
        
    except Exception as e:
        result['processing_status'] = 'failed'
        result['processing_error'] = str(e)
        result['mesh_process_error'] = str(e)
    
    # Remove internal fields
    result.pop('_vertices', None)
    result.pop('_faces', None)
    result.pop('_geometry_type', None)
    
    return idx, result

def process_chunk_parallel(chunk_data, chunk_num, num_workers=None):
    """Process a chunk of buildings in parallel"""
    logger = logging.getLogger(__name__)
    
    if num_workers is None:
        num_workers = min(os.cpu_count() - 1, 8)
    
    logger.info(f"Processing chunk {chunk_num} with {len(chunk_data)} buildings using {num_workers} workers")
    
    results = {}
    total = len(chunk_data)
    processed = 0
    
    # Prepare data for parallel processing - chunk_data is already a list of dicts
    row_data = [(idx, row) for idx, row in enumerate(chunk_data)]
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        # Submit all tasks
        future_to_idx = {executor.submit(process_single_building, data): data[0] 
                        for data in row_data}
        
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
                results[idx] = {'processing_status': 'failed', 'processing_error': str(e)}
    
    return results

def save_chunk_results(results, output_path, chunk_num):
    """Save chunk results to CSV"""
    logger = logging.getLogger(__name__)
    
    # Convert results to DataFrame
    df_results = pd.DataFrame.from_dict(results, orient='index')
    
    # Save as CSV
    csv_path = output_path.parent / f"{output_path.stem}_chunk_{chunk_num:04d}.csv"
    df_results.to_csv(csv_path, index=False)
    logger.info(f"Saved chunk {chunk_num} with {len(df_results)} records to {csv_path}")
    
    # Return summary statistics with safe field access
    successful = 0
    volumes_calculated = 0
    
    if 'processing_status' in df_results.columns:
        successful = df_results['processing_status'].value_counts().get('success', 0)
    
    if 'mesh_volume' in df_results.columns:
        volumes_calculated = df_results['mesh_volume'].notna().sum()
    
    return {
        'chunk_num': chunk_num,
        'total': len(df_results),
        'successful': successful,
        'volumes_calculated': volumes_calculated,
        'csv_path': csv_path
    }

def merge_chunk_results(chunk_summaries, output_path):
    """Merge all chunk CSVs into final Excel file"""
    logger = logging.getLogger(__name__)
    logger.info("Merging all chunks into final Excel file...")
    
    # Read and combine all chunks
    all_data = []
    for summary in chunk_summaries:
        csv_path = summary['csv_path']
        chunk_df = pd.read_csv(csv_path)
        all_data.append(chunk_df)
        logger.info(f"Loaded {len(chunk_df)} records from {csv_path.name}")
    
    # Combine all data
    final_df = pd.concat(all_data, ignore_index=True)
    
    # Save as Excel
    excel_path = output_path.with_suffix('.xlsx')
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        final_df.to_excel(writer, sheet_name='Building_Analysis', index=False)
    
    logger.info(f"Saved final Excel with {len(final_df)} records to {excel_path}")
    
    # Also save complete CSV
    final_csv_path = output_path.with_suffix('.csv')
    final_df.to_csv(final_csv_path, index=False)
    logger.info(f"Saved complete CSV to {final_csv_path}")
    
    # Calculate final statistics with safe field access
    total = len(final_df)
    successful = 0
    volumes_calculated = 0
    
    if 'processing_status' in final_df.columns:
        successful = final_df['processing_status'].value_counts().get('success', 0)
    
    if 'mesh_volume' in final_df.columns:
        volumes_calculated = final_df['mesh_volume'].notna().sum()
    
    logger.info(f"\nFinal Processing Summary:")
    logger.info(f"Total buildings: {total}")
    logger.info(f"Successfully processed: {successful} ({successful/total*100:.1f}%)" if total > 0 else "Successfully processed: 0")
    logger.info(f"Volumes calculated: {volumes_calculated} ({volumes_calculated/total*100:.1f}%)" if total > 0 else "Volumes calculated: 0")
    
    if volumes_calculated > 0 and 'mesh_volume' in final_df.columns:
        avg_volume = final_df['mesh_volume'].mean()
        logger.info(f"Average building volume: {avg_volume:.2f} m³")
        
        if 'surf_footprint_area' in final_df.columns:
            avg_footprint = final_df['surf_footprint_area'].mean()
            logger.info(f"Average footprint area: {avg_footprint:.2f} m²")
    
    # Optionally delete chunk files after successful merge
    logger.info("Cleaning up chunk files...")
    for summary in chunk_summaries:
        try:
            summary['csv_path'].unlink()
            logger.debug(f"Deleted {summary['csv_path'].name}")
        except Exception as e:
            logger.warning(f"Could not delete {summary['csv_path'].name}: {e}")

def main():
    """Main processing function"""
    parser = argparse.ArgumentParser(description='Process Swisstopo 3D building data')
    parser.add_argument('input_gdb', help='Path to input GDB file')
    parser.add_argument('output_dir', help='Output directory for results')
    parser.add_argument('--layer', default='Building_solid', help='GDB layer name')
    parser.add_argument('--limit', type=int, help='Limit number of buildings to process')
    parser.add_argument('--workers', type=int, help='Number of parallel workers')
    parser.add_argument('--chunk-size', type=int, default=CHUNK_SIZE, 
                       help=f'Number of buildings per chunk (default: {CHUNK_SIZE})')
    parser.add_argument('--keep-chunks', action='store_true', 
                       help='Keep individual chunk CSV files after merging')
    
    args = parser.parse_args()
    
    # Setup paths
    input_path = Path(args.input_gdb)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    logger = setup_logging(output_dir)
    logger.info("Starting building processing")
    logger.info(f"Input: {input_path}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Chunk size: {args.chunk_size}")
    
    start_time = time.time()
    
    try:
        # Process chunks
        chunk_summaries = []
        output_path = output_dir / f'building_analysis_{time.strftime("%Y%m%d_%H%M%S")}'
        
        # Process each chunk
        for chunk_num, chunk_data in read_gdb_buildings_chunked(
            input_path, args.layer, args.chunk_size, args.limit
        ):
            logger.info(f"\n=== Processing chunk {chunk_num} ===")
            
            # Process chunk directly without DataFrame conversion
            results = process_chunk_parallel(chunk_data, chunk_num, args.workers)
            
            # Save chunk results
            summary = save_chunk_results(results, output_path, chunk_num)
            chunk_summaries.append(summary)
            
            # Force garbage collection
            del chunk_data
            del results
            gc.collect()
            
            logger.info(f"Chunk {chunk_num} complete. Memory cleaned.")
        
        # Merge all chunks into final output
        if chunk_summaries:
            merge_chunk_results(chunk_summaries, output_path)
            
            if args.keep_chunks:
                logger.info("Keeping individual chunk files as requested")
        
    except Exception as e:
        logger.error(f"Processing failed: {str(e)}", exc_info=True)
        sys.exit(1)
    
    elapsed_time = time.time() - start_time
    logger.info(f"\nProcessing completed in {elapsed_time:.1f} seconds ({elapsed_time/60:.1f} minutes)")

if __name__ == '__main__':
    main()