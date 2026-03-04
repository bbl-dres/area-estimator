"""
Check for buildings within SWISSIMAGE-RS coverage area
"""
import fiona
import numpy as np

# SWISSIMAGE-RS coverage bounds (from previous analysis)
rs_west = 2621243.25
rs_east = 2623243.50
rs_south = 1091794.50
rs_north = 1093794.75

gdb_path = r'C:\BBL DEV\Data\swissbuildings3d_3_0_2025_2056_5728\SWISSBUILDINGS3D_3_0.gdb'

print('Checking for buildings within SWISSIMAGE-RS coverage area...')
print(f'Coverage: X=[{rs_west:.0f}, {rs_east:.0f}], Y=[{rs_south:.0f}, {rs_north:.0f}]')
print()

# Count buildings in the area
buildings_in_area = []
total_checked = 0

with fiona.open(gdb_path, layer='Building_solid') as src:
    for feature in src:
        total_checked += 1
        if total_checked > 100000:  # Limit search
            break

        geom = feature['geometry']
        if geom and 'coordinates' in geom:
            # Get first coordinate to check location
            coords = geom['coordinates']
            if coords and len(coords) > 0:
                # Navigate to actual coordinates
                first_coord = coords
                while isinstance(first_coord, list) and len(first_coord) > 0:
                    if isinstance(first_coord[0], (int, float)):
                        break
                    first_coord = first_coord[0]

                if isinstance(first_coord, list) and len(first_coord) >= 2:
                    x, y = first_coord[0], first_coord[1]
                    if rs_west <= x <= rs_east and rs_south <= y <= rs_north:
                        buildings_in_area.append({
                            'uuid': feature['properties'].get('UUID', 'unknown'),
                            'type': feature['properties'].get('OBJEKTART', 'unknown'),
                            'x': x,
                            'y': y
                        })

        if total_checked % 10000 == 0:
            print(f'Checked {total_checked} buildings, found {len(buildings_in_area)} in area...')

print()
print(f'=== Results ===')
print(f'Total buildings checked: {total_checked}')
print(f'Buildings in SWISSIMAGE-RS area: {len(buildings_in_area)}')

if buildings_in_area:
    print()
    print('Sample buildings found:')
    for b in buildings_in_area[:10]:
        print(f'  - {b["uuid"][:30]}... ({b["type"]}) at ({b["x"]:.0f}, {b["y"]:.0f})')
