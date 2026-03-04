import fiona

# Open the GDB and get feature count
with fiona.open(r"C:\Users\DavidRasner\Downloads\SWISSBUILDINGS3D_3_0.gdb", layer='Building_solid') as src:
    feature_count = len(src)
    print(f"Feature count: {feature_count}")