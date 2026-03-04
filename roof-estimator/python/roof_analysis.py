"""
Roof analysis module for swissBUILDINGS3D data
Analyzes 3D building meshes to extract roof, wall, and footprint areas,
and classifies roof shapes based on surface geometry.
"""

import numpy as np
import trimesh
import logging
from collections import defaultdict

# Roof shape classification constants
ROOF_SHAPES = {
    'flat': 'Flat roof - horizontal or near-horizontal surfaces',
    'gable': 'Gable roof - two sloped surfaces meeting at a ridge',
    'hip': 'Hip roof - four sloped surfaces',
    'shed': 'Shed/mono-pitch roof - single sloped surface',
    'mansard': 'Mansard roof - double slope on multiple sides',
    'complex': 'Complex roof - multiple gables or irregular geometry',
    'unknown': 'Unable to classify roof shape'
}


def classify_face_orientation(normal_z, horizontal_tolerance=10.0, vertical_tolerance=10.0):
    """
    Classify face orientation based on its normal vector's Z component.

    Args:
        normal_z: Z component of the face normal vector
        horizontal_tolerance: Angle tolerance in degrees for horizontal classification
        vertical_tolerance: Angle tolerance in degrees for vertical classification

    Returns:
        str: 'horizontal_up', 'horizontal_down', 'vertical', or 'sloped'
    """
    horizontal_tol_rad = np.radians(horizontal_tolerance)
    vertical_tol_rad = np.radians(vertical_tolerance)

    abs_z = abs(normal_z)

    # Check if horizontal (normal pointing up or down)
    if abs_z > np.cos(horizontal_tol_rad):
        return 'horizontal_up' if normal_z > 0 else 'horizontal_down'

    # Check if vertical (normal pointing horizontally)
    elif abs_z < np.sin(vertical_tol_rad):
        return 'vertical'

    # Otherwise sloped
    else:
        return 'sloped'


def get_face_slope_angle(normal):
    """
    Calculate the slope angle of a face from horizontal.

    Args:
        normal: 3D normal vector [x, y, z]

    Returns:
        float: Slope angle in degrees (0 = horizontal, 90 = vertical)
    """
    return np.degrees(np.arccos(abs(normal[2])))


def get_face_azimuth(normal):
    """
    Calculate the azimuth (compass direction) a sloped face is facing.

    Args:
        normal: 3D normal vector [x, y, z]

    Returns:
        float: Azimuth in degrees (0 = North, 90 = East, etc.)
    """
    azimuth = np.degrees(np.arctan2(normal[0], normal[1]))
    if azimuth < 0:
        azimuth += 360
    return azimuth


def classify_roof_shape(sloped_faces, horizontal_roof_faces, building_height, footprint_area):
    """
    Classify the roof shape based on analysis of sloped and horizontal faces.

    Args:
        sloped_faces: List of dicts with 'area', 'slope', 'azimuth' for each sloped face
        horizontal_roof_faces: List of dicts with 'area' for horizontal roof faces
        building_height: Total building height in meters
        footprint_area: Building footprint area in m²

    Returns:
        dict: Roof classification with shape, confidence, and details
    """
    result = {
        'roof_shape': 'unknown',
        'roof_shape_confidence': 0.0,
        'roof_slope_primary_deg': None,
        'roof_slope_secondary_deg': None,
        'roof_azimuth_primary_deg': None,
        'roof_ridge_orientation': None,
        'roof_face_count': 0
    }

    total_sloped_area = sum(f['area'] for f in sloped_faces)
    total_horizontal_roof_area = sum(f['area'] for f in horizontal_roof_faces)
    total_roof_area = total_sloped_area + total_horizontal_roof_area

    if total_roof_area == 0:
        return result

    result['roof_face_count'] = len(sloped_faces) + len(horizontal_roof_faces)

    # Calculate ratio of flat vs sloped roof
    flat_ratio = total_horizontal_roof_area / total_roof_area if total_roof_area > 0 else 0

    # FLAT ROOF: Predominantly horizontal surfaces
    if flat_ratio > 0.85:
        result['roof_shape'] = 'flat'
        result['roof_shape_confidence'] = min(flat_ratio, 1.0)
        if sloped_faces:
            result['roof_slope_primary_deg'] = np.mean([f['slope'] for f in sloped_faces])
        else:
            result['roof_slope_primary_deg'] = 0.0
        return result

    # Analyze sloped faces for roof type classification
    if not sloped_faces:
        result['roof_shape'] = 'flat'
        result['roof_shape_confidence'] = 1.0
        result['roof_slope_primary_deg'] = 0.0
        return result

    # Group sloped faces by azimuth (compass direction)
    azimuth_groups = defaultdict(list)
    for face in sloped_faces:
        # Group into 45-degree sectors
        sector = int((face['azimuth'] + 22.5) / 45) % 8
        azimuth_groups[sector].append(face)

    # Count significant azimuth groups (groups with substantial area)
    significant_groups = []
    for sector, faces in azimuth_groups.items():
        group_area = sum(f['area'] for f in faces)
        if group_area > 0.1 * total_sloped_area:  # More than 10% of sloped area
            avg_slope = np.average([f['slope'] for f in faces], weights=[f['area'] for f in faces])
            avg_azimuth = np.average([f['azimuth'] for f in faces], weights=[f['area'] for f in faces])
            significant_groups.append({
                'sector': sector,
                'area': group_area,
                'avg_slope': avg_slope,
                'avg_azimuth': avg_azimuth,
                'face_count': len(faces)
            })

    # Sort by area (largest first)
    significant_groups.sort(key=lambda x: x['area'], reverse=True)
    num_groups = len(significant_groups)

    # Set primary slope info
    if significant_groups:
        result['roof_slope_primary_deg'] = significant_groups[0]['avg_slope']
        result['roof_azimuth_primary_deg'] = significant_groups[0]['avg_azimuth']

    if len(significant_groups) > 1:
        result['roof_slope_secondary_deg'] = significant_groups[1]['avg_slope']

    # SHED ROOF: One dominant slope direction
    if num_groups == 1:
        result['roof_shape'] = 'shed'
        result['roof_shape_confidence'] = 0.8
        return result

    # GABLE ROOF: Two opposite slope directions
    if num_groups == 2:
        # Check if the two groups are roughly opposite (180 degrees apart)
        azimuth_diff = abs(significant_groups[0]['avg_azimuth'] - significant_groups[1]['avg_azimuth'])
        if azimuth_diff > 180:
            azimuth_diff = 360 - azimuth_diff

        if 150 < azimuth_diff < 210:  # Roughly opposite directions
            result['roof_shape'] = 'gable'
            result['roof_shape_confidence'] = 0.85
            # Ridge orientation is perpendicular to the slope directions
            ridge_azimuth = (significant_groups[0]['avg_azimuth'] + 90) % 360
            result['roof_ridge_orientation'] = ridge_azimuth
            return result

    # HIP ROOF: Four slope directions (or three for half-hip)
    if num_groups >= 3:
        # Check if slopes are distributed around the building
        sectors_used = set(g['sector'] for g in significant_groups)

        # Check for roughly equal distribution
        areas = [g['area'] for g in significant_groups]
        area_variance = np.std(areas) / np.mean(areas) if np.mean(areas) > 0 else 1

        if num_groups >= 4 and area_variance < 0.5:
            result['roof_shape'] = 'hip'
            result['roof_shape_confidence'] = 0.8
            return result

        # Check for mansard (steep lower slopes, flatter upper)
        slopes = [g['avg_slope'] for g in significant_groups]
        if max(slopes) > 60 and min(slopes) < 40:
            result['roof_shape'] = 'mansard'
            result['roof_shape_confidence'] = 0.7
            return result

    # COMPLEX ROOF: Multiple gables or irregular
    if num_groups > 4 or (num_groups > 2 and flat_ratio > 0.2):
        result['roof_shape'] = 'complex'
        result['roof_shape_confidence'] = 0.6
        return result

    # Default fallback
    result['roof_shape'] = 'complex'
    result['roof_shape_confidence'] = 0.5
    return result


def analyze_building_roof(vertices, faces):
    """
    Analyze building mesh to extract roof characteristics.

    Args:
        vertices: List of [x, y, z] vertex coordinates
        faces: List of [v0, v1, v2] face indices

    Returns:
        dict: Analysis results including areas and roof shape classification
    """
    result = {
        # Area measurements
        'roof_area_m2': None,
        'wall_area_m2': None,
        'footprint_area_m2': None,
        'sloped_roof_area_m2': None,
        'flat_roof_area_m2': None,
        'total_surface_area_m2': None,

        # Roof shape classification
        'roof_shape': None,
        'roof_shape_confidence': None,
        'roof_slope_primary_deg': None,
        'roof_slope_secondary_deg': None,
        'roof_azimuth_primary_deg': None,
        'roof_ridge_orientation': None,
        'roof_face_count': None,

        # Building metrics
        'building_height_m': None,
        'eave_height_m': None,
        'ridge_height_m': None,
        'wall_perimeter_m': None,
        'min_elevation_m': None,
        'max_elevation_m': None,

        # Face counts
        'horizontal_face_count': None,
        'vertical_face_count': None,
        'sloped_face_count': None,

        # Processing status
        'analysis_status': None,
        'analysis_error': None
    }

    try:
        # Validate input
        if not vertices or not faces:
            result['analysis_status'] = 'failed'
            result['analysis_error'] = 'No vertices or faces provided'
            return result

        # Create trimesh from vertices and faces
        mesh = trimesh.Trimesh(
            vertices=np.array(vertices),
            faces=np.array(faces),
            process=True  # Merge duplicate vertices
        )

        # Get mesh properties
        face_normals = mesh.face_normals
        face_areas = mesh.area_faces
        face_centroids = mesh.triangles_center

        # Initialize area accumulators
        roof_horizontal_area = 0.0
        roof_sloped_area = 0.0
        footprint_area = 0.0
        wall_area = 0.0

        # Initialize face collections for classification
        horizontal_faces = []
        vertical_faces = []
        sloped_faces = []

        horizontal_roof_faces = []
        sloped_roof_faces = []

        # Classify each face
        for i, (normal, area, centroid) in enumerate(zip(face_normals, face_areas, face_centroids)):
            orientation = classify_face_orientation(normal[2])
            slope_angle = get_face_slope_angle(normal)
            azimuth = get_face_azimuth(normal)

            face_info = {
                'index': i,
                'area': area,
                'z': centroid[2],
                'normal': normal,
                'slope': slope_angle,
                'azimuth': azimuth
            }

            if orientation in ['horizontal_up', 'horizontal_down']:
                horizontal_faces.append(face_info)
            elif orientation == 'vertical':
                vertical_faces.append(face_info)
                wall_area += area
            else:  # sloped
                sloped_faces.append(face_info)

        # Separate horizontal faces into roof and footprint based on Z position
        if horizontal_faces:
            z_values = [f['z'] for f in horizontal_faces]
            min_z = min(z_values)
            max_z = max(z_values)
            z_range = max_z - min_z

            # Footprint threshold: faces in the bottom 10% of Z range
            footprint_threshold = min_z + 0.1 * z_range if z_range > 0.01 else min_z + 0.1

            for face in horizontal_faces:
                if face['z'] <= footprint_threshold:
                    footprint_area += face['area']
                else:
                    roof_horizontal_area += face['area']
                    horizontal_roof_faces.append(face)

        # Sloped faces above footprint level are roof surfaces
        if horizontal_faces:
            z_values = [f['z'] for f in horizontal_faces]
            footprint_z = min(z_values)
        else:
            footprint_z = min(f['z'] for f in sloped_faces) if sloped_faces else 0

        for face in sloped_faces:
            if face['z'] > footprint_z + 0.5:  # Above ground level
                roof_sloped_area += face['area']
                sloped_roof_faces.append(face)

        # Calculate building height metrics
        if len(mesh.vertices) > 0:
            z_coords = mesh.vertices[:, 2]
            min_elevation = float(np.min(z_coords))
            max_elevation = float(np.max(z_coords))
            building_height = max_elevation - min_elevation

            result['min_elevation_m'] = round(min_elevation, 2)
            result['max_elevation_m'] = round(max_elevation, 2)
            result['building_height_m'] = round(building_height, 2)
            result['ridge_height_m'] = round(max_elevation, 2)

            # Estimate eave height (height where walls meet roof)
            if wall_area > 0 and vertical_faces:
                wall_top_z = max(f['z'] for f in vertical_faces)
                result['eave_height_m'] = round(wall_top_z - min_elevation, 2)

            # Estimate wall perimeter from wall area and height
            if wall_area > 0 and building_height > 0:
                result['wall_perimeter_m'] = round(wall_area / building_height, 2)

        # Store area results
        total_roof_area = roof_horizontal_area + roof_sloped_area
        result['roof_area_m2'] = round(total_roof_area, 2)
        result['flat_roof_area_m2'] = round(roof_horizontal_area, 2)
        result['sloped_roof_area_m2'] = round(roof_sloped_area, 2)
        result['wall_area_m2'] = round(wall_area, 2)
        result['footprint_area_m2'] = round(footprint_area, 2)
        result['total_surface_area_m2'] = round(float(mesh.area), 2)

        # Store face counts
        result['horizontal_face_count'] = len(horizontal_faces)
        result['vertical_face_count'] = len(vertical_faces)
        result['sloped_face_count'] = len(sloped_faces)

        # Classify roof shape
        roof_classification = classify_roof_shape(
            sloped_roof_faces,
            horizontal_roof_faces,
            result['building_height_m'] or 0,
            result['footprint_area_m2'] or 0
        )

        result['roof_shape'] = roof_classification['roof_shape']
        result['roof_shape_confidence'] = round(roof_classification['roof_shape_confidence'], 2)
        result['roof_face_count'] = roof_classification['roof_face_count']

        if roof_classification['roof_slope_primary_deg'] is not None:
            result['roof_slope_primary_deg'] = round(roof_classification['roof_slope_primary_deg'], 1)
        if roof_classification['roof_slope_secondary_deg'] is not None:
            result['roof_slope_secondary_deg'] = round(roof_classification['roof_slope_secondary_deg'], 1)
        if roof_classification['roof_azimuth_primary_deg'] is not None:
            result['roof_azimuth_primary_deg'] = round(roof_classification['roof_azimuth_primary_deg'], 1)
        if roof_classification['roof_ridge_orientation'] is not None:
            result['roof_ridge_orientation'] = round(roof_classification['roof_ridge_orientation'], 1)

        result['analysis_status'] = 'success'

    except Exception as e:
        result['analysis_status'] = 'failed'
        result['analysis_error'] = str(e)
        logging.debug(f"Roof analysis error: {str(e)}")

    return result
