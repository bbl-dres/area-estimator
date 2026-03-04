"""
Surface area analysis module
Analyzes building surfaces to calculate roof, footprint, and wall areas
"""

import numpy as np
import trimesh
import logging

def classify_face_orientation(normal_z, horizontal_tolerance=10.0, vertical_tolerance=10.0):
    """Classify face as horizontal, vertical, or sloped"""
    horizontal_tol_rad = np.radians(horizontal_tolerance)
    vertical_tol_rad = np.radians(vertical_tolerance)
    
    abs_z = abs(normal_z)
    
    # Check if horizontal
    if abs_z > np.cos(horizontal_tol_rad):
        return 'horizontal_up' if normal_z > 0 else 'horizontal_down'
    
    # Check if vertical
    elif abs_z < np.sin(vertical_tol_rad):
        return 'vertical'
    
    # Otherwise sloped
    else:
        return 'sloped'

def analyze_building_surfaces(vertices, faces):
    """Analyze building surfaces and calculate areas"""
    result = {
        'surf_roof_area': None,
        'surf_footprint_area': None,
        'surf_wall_area': None,
        'surf_sloped_area': None,
        'surf_total_area': None,
        'surf_building_height': None,
        'surf_wall_perimeter': None,
        'surf_roof_complexity': None,
        'surf_min_elevation': None,
        'surf_max_elevation': None,
        'surf_horizontal_faces': None,
        'surf_vertical_faces': None,
        'surf_sloped_faces': None,
        'surf_analysis_error': None
    }
    
    try:
        # Validate input
        if not vertices or not faces:
            result['surf_analysis_error'] = "No vertices or faces provided"
            return result
        
        # Create trimesh directly from vertices and faces
        mesh = trimesh.Trimesh(
            vertices=np.array(vertices),
            faces=np.array(faces),
            process=True  # Merge duplicate vertices
        )
        
        # Get mesh properties
        face_normals = mesh.face_normals
        face_areas = mesh.area_faces
        face_centroids = mesh.triangles_center
        
        # Initialize accumulators
        roof_area = 0.0
        footprint_area = 0.0
        wall_area = 0.0
        sloped_area = 0.0
        
        # Classify faces
        horizontal_faces = []
        vertical_faces = []
        sloped_faces = []
        
        for i, (normal, area, centroid) in enumerate(zip(face_normals, face_areas, face_centroids)):
            orientation = classify_face_orientation(normal[2])
            
            if orientation in ['horizontal_up', 'horizontal_down']:
                horizontal_faces.append({
                    'area': area,
                    'z': centroid[2],
                    'normal_z': normal[2]
                })
            elif orientation == 'vertical':
                vertical_faces.append({'area': area})
                wall_area += area
            else:  # sloped
                sloped_faces.append({'area': area})
                sloped_area += area
        
        # Separate roof and footprint
        if horizontal_faces:
            z_values = [f['z'] for f in horizontal_faces]
            min_z = min(z_values)
            max_z = max(z_values)
            z_range = max_z - min_z
            
            # Footprint threshold
            footprint_threshold = min_z + 0.1 * z_range if z_range > 0.01 else min_z + 0.1
            
            for face in horizontal_faces:
                if face['z'] <= footprint_threshold:
                    footprint_area += face['area']
                else:
                    roof_area += face['area']
        
        # Calculate statistics
        result['surf_roof_area'] = float(roof_area)
        result['surf_footprint_area'] = float(footprint_area)
        result['surf_wall_area'] = float(wall_area)
        result['surf_sloped_area'] = float(sloped_area)
        result['surf_total_area'] = float(mesh.area)
        
        result['surf_horizontal_faces'] = len(horizontal_faces)
        result['surf_vertical_faces'] = len(vertical_faces)
        result['surf_sloped_faces'] = len(sloped_faces)
        
        # Building height and elevation
        if len(mesh.vertices) > 0:
            z_coords = mesh.vertices[:, 2]
            result['surf_min_elevation'] = float(np.min(z_coords))
            result['surf_max_elevation'] = float(np.max(z_coords))
            result['surf_building_height'] = float(np.max(z_coords) - np.min(z_coords))
            
            # Wall perimeter estimation
            if wall_area > 0 and result['surf_building_height'] > 0:
                result['surf_wall_perimeter'] = float(wall_area / result['surf_building_height'])
        
        # Roof complexity
        total_roof_area = roof_area + sloped_area
        if total_roof_area > 0:
            result['surf_roof_complexity'] = float(sloped_area / total_roof_area)
        else:
            result['surf_roof_complexity'] = 0.0
            
    except Exception as e:
        result['surf_analysis_error'] = str(e)
        logging.debug(f"Surface analysis error: {str(e)}")
    
    return result