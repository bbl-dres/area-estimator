"""
Mesh repair and volume calculation module
Processes multipatch geometries to calculate building volumes
"""

import numpy as np
import trimesh
import logging

def repair_mesh(mesh):
    """Repair mesh to make it watertight"""
    repair_steps = []
    
    try:
        # Skip visual processing
        mesh.visual = None
        
        # Check if already watertight
        if mesh.is_watertight:
            volume = float(mesh.volume)
            # Handle negative volume (inside-out mesh)
            if volume < 0:
                repair_steps.append("Mesh is inside-out, taking absolute value")
                volume = abs(volume)
            return True, volume, ["Already watertight"]
        
        # Step 1: Merge duplicate vertices
        initial_vertices = len(mesh.vertices)
        mesh.merge_vertices(digits=5)
        merged = initial_vertices - len(mesh.vertices)
        if merged > 0:
            repair_steps.append(f"Merged {merged} duplicate vertices")
        
        # Step 2: Remove degenerate faces
        initial_faces = len(mesh.faces)
        mesh.remove_degenerate_faces()
        removed = initial_faces - len(mesh.faces)
        if removed > 0:
            repair_steps.append(f"Removed {removed} degenerate faces")
        
        # Step 3: Fix normals
        mesh.fix_normals()
        repair_steps.append("Fixed normals")
        
        # Check if watertight now
        if mesh.is_watertight:
            repair_steps.append("Watertight after basic repairs")
            volume = float(mesh.volume)
            # Handle negative volume
            if volume < 0:
                repair_steps.append("Mesh is inside-out, taking absolute value")
                volume = abs(volume)
            return True, volume, repair_steps
        
        # Step 4: Fill holes
        mesh.fill_holes()
        repair_steps.append("Filled holes")
        
        # Step 5: Final cleanup
        mesh.remove_degenerate_faces()
        mesh.remove_unreferenced_vertices()
        
        # Final check
        if mesh.is_watertight:
            repair_steps.append("Watertight after full repair")
            volume = float(mesh.volume)
            # Handle negative volume
            if volume < 0:
                repair_steps.append("Mesh is inside-out, taking absolute value")
                volume = abs(volume)
            return True, volume, repair_steps
        else:
            repair_steps.append("Still not watertight after repair")
            # Try to get volume anyway - trimesh can sometimes calculate volume for non-watertight meshes
            try:
                volume = float(mesh.volume)
                if volume < 0:
                    volume = abs(volume)
                repair_steps.append(f"Calculated volume despite non-watertight: {volume:.2f} m³")
                return False, volume, repair_steps
            except:
                return False, None, repair_steps
            
    except Exception as e:
        repair_steps.append(f"Repair error: {str(e)}")
        return False, None, repair_steps

def process_building_mesh(vertices, faces):
    """Process building geometry to calculate volume"""
    result = {
        'mesh_volume': None,
        'mesh_is_watertight': None,
        'mesh_vertex_count': None,
        'mesh_face_count': None,
        'mesh_repair_applied': False,
        'mesh_repair_steps': None,
        'mesh_process_error': None,
        'mesh_orientation_fixed': False
    }
    
    try:
        # Validate input
        if not vertices or not faces:
            result['mesh_process_error'] = "No vertices or faces provided"
            return result
        
        # Create trimesh
        mesh = trimesh.Trimesh(
            vertices=np.array(vertices),
            faces=np.array(faces),
            process=True  # Merge duplicate vertices
        )
        
        # Store mesh statistics
        result['mesh_vertex_count'] = len(mesh.vertices)
        result['mesh_face_count'] = len(mesh.faces)
        
        # Check if already watertight
        if mesh.is_watertight:
            volume = float(mesh.volume)
            # Handle negative volume
            if volume < 0:
                result['mesh_volume'] = abs(volume)
                result['mesh_orientation_fixed'] = True
                result['mesh_repair_steps'] = "Already watertight - fixed inside-out orientation"
            else:
                result['mesh_volume'] = volume
                result['mesh_repair_steps'] = "Already watertight - no repair needed"
            result['mesh_is_watertight'] = True
        else:
            # Attempt repair
            result['mesh_repair_applied'] = True
            is_watertight, volume, repair_steps = repair_mesh(mesh)
            
            result['mesh_is_watertight'] = is_watertight
            result['mesh_volume'] = volume
            result['mesh_repair_steps'] = " | ".join(repair_steps)
            
            # Check if orientation was fixed
            if volume is not None and "inside-out" in result['mesh_repair_steps']:
                result['mesh_orientation_fixed'] = True
        
    except Exception as e:
        result['mesh_process_error'] = str(e)
        logging.debug(f"Mesh processing error: {str(e)}")
    
    return result