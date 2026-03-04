"""
Find buildings within SWISSIMAGE-RS coverage area using spatial filter
"""
import fiona
from fiona import Feature
import numpy as np

# TFW info: upper-left = (2621243.375, 1093794.625), pixel = 0.25m
# Need to determine image size - let's read TIF metadata
try:
    from PIL import Image
    img = Image.open(r'D:\SwissRS\SWISSIMAGE-RS_25cm_Example.tif')
    width, height = img.size
    img.close()
    print(f"Image size: {width} x {height} pixels")
except:
    # Estimate from file size (4 bands, 16-bit = 2 bytes per band)
    # 583493088 bytes / 8 bytes per pixel = 72,936,636 pixels
    # sqrt = ~8540 pixels per side
    width = 8001  # Typical swisstopo tile
    height = 8001
    print(f"Estimated image size: {width} x {height} pixels")

# Calculate bounds
pixel_size = 0.25
ul_x = 2621243.375
ul_y = 1093794.625

# Lower-right corner
lr_x = ul_x + width * pixel_size
lr_y = ul_y - height * pixel_size

# Bounds
rs_west = ul_x - pixel_size/2  # Edge of first pixel
rs_east = lr_x + pixel_size/2  # Edge of last pixel
rs_north = ul_y + pixel_size/2
rs_south = lr_y - pixel_size/2

print(f"\n=== SWISSIMAGE-RS Coverage (LV95) ===")
print(f"Upper-left: ({ul_x:.2f}, {ul_y:.2f})")
print(f"Lower-right: ({lr_x:.2f}, {lr_y:.2f})")
print(f"Bounds: X=[{rs_west:.2f}, {rs_east:.2f}], Y=[{rs_south:.2f}, {rs_north:.2f}]")
print(f"Coverage: {(rs_east-rs_west):.0f}m x {(rs_north-rs_south):.0f}m")

gdb_path = r'C:\BBL DEV\Data\swissbuildings3d_3_0_2025_2056_5728\SWISSBUILDINGS3D_3_0.gdb'

print(f"\nSearching for buildings in area...")

# Try using fiona's bbox filter
try:
    bbox = (rs_west, rs_south, rs_east, rs_north)
    print(f"Using bbox filter: {bbox}")

    buildings_in_area = []

    with fiona.open(gdb_path, layer='Building_solid', bbox=bbox) as src:
        for feature in src:
            geom = feature['geometry']
            if geom and 'coordinates' in geom:
                coords = geom['coordinates']
                if coords and len(coords) > 0:
                    first_coord = coords
                    while isinstance(first_coord, list) and len(first_coord) > 0:
                        if isinstance(first_coord[0], (int, float)):
                            break
                        first_coord = first_coord[0]

                    if isinstance(first_coord, list) and len(first_coord) >= 2:
                        x, y = first_coord[0], first_coord[1]
                        buildings_in_area.append({
                            'uuid': feature['properties'].get('UUID', 'unknown'),
                            'type': feature['properties'].get('OBJEKTART', 'unknown'),
                            'name': feature['properties'].get('NAME_KOMPLETT', ''),
                            'x': x,
                            'y': y
                        })

    print(f"\n=== Results (bbox filter) ===")
    print(f"Buildings found: {len(buildings_in_area)}")

    if buildings_in_area:
        print("\nSample buildings:")
        for b in buildings_in_area[:15]:
            name = f' ({b["name"]})' if b["name"] else ''
            print(f'  - {b["type"]}{name} at ({b["x"]:.0f}, {b["y"]:.0f})')

except Exception as e:
    print(f"Bbox filter failed: {e}")
    print("\nFalling back to full scan...")

    # Full scan
    buildings_in_area = []
    total = 0

    with fiona.open(gdb_path, layer='Building_solid') as src:
        for feature in src:
            total += 1
            geom = feature['geometry']
            if geom and 'coordinates' in geom:
                coords = geom['coordinates']
                if coords and len(coords) > 0:
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

            if total % 500000 == 0:
                print(f'Scanned {total} buildings, found {len(buildings_in_area)} in area...')

    print(f"\n=== Results (full scan) ===")
    print(f"Total buildings scanned: {total}")
    print(f"Buildings in area: {len(buildings_in_area)}")
