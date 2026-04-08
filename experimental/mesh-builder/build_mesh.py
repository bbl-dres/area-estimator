#!/usr/bin/env python3
"""
Mesh Builder (experimental) — watertight LOD2-ish hulls from footprint + raster.

Builds one mesh per input row, footprint-exact and watertight by construction.

Algorithm
---------
1. Normalise the polygon (largest part of MultiPolygon, strip holes, force CCW).
2. Densify the exterior (~0.5 m vertices).
3. Sample an interior aligned grid (reuses ``volume.create_aligned_grid_points``);
   drop interior points too close to boundary verts using a KDTree.
4. Sample DTM at every (boundary + interior) point → variable ground contour.
5. Sample DSM at every (boundary + interior) point → variable roof contour.
6. Two-pass edge-preserving outlier rejection on the DSM samples
   (``_smooth_dsm_outliers``):
     * Fine pass (~1.5 m radius): bidirectional with neighbour-support
       gating. Kills isolated noise (vegetation, antennas, single bad
       boundary samples) without flattening real low or high features.
     * Coarse pass (~5 m radius, upward only): catches *thin tall
       features* that survive the fine pass because their own verts
       dominate the small neighbourhood — lift overruns, stair towers,
       narrow chimneys, antenna masts. The threshold sits between 2×2
       (removed) and 3×3 (preserved) at 1 m grid spacing.
7. Roof surface: constrained Delaunay (Shewchuk's ``triangle``) over
   (boundary + interior) with boundary edges as constraints.
8. Floor surface: constrained Delaunay over the boundary alone, lifted to the
   per-vertex DTM (so the floor follows the slope under the building).
9. Walls: two triangles per consecutive boundary edge, top (DSM) → bottom (DTM).
10. Concatenate into one ``trimesh.Trimesh``. Per-face colours are *not*
    baked in by default — the viewer derives them from face normals at
    render time. Pass ``--colour`` to bake them into the file (useful for
    QGIS/ArcGIS where runtime classification isn't available).

Watertightness
--------------
The boundary vertex set is **shared** between the roof's outer ring, the wall
tops, the wall bottoms, and the floor's outline. No gap can appear by
construction. The mesh is built with ``process=False`` so trimesh does not
silently merge or drop anything — ``is_watertight`` is then a real validation
of the assembly, checked at the end of every build and raised as a hard error.

PLY export uses **local coordinates** (translated to the bbox centre) with a
sidecar ``<file>.ply.offset.json`` carrying the LV95 offset, because trimesh's
PLY exporter writes vertex positions as float32 — and float32 only gives
~10–30 cm of precision for LV95 coordinates in the millions. Distinct
in-memory vertices within that range would otherwise collapse to the same
float32 on export and break watertightness on reload. To recover absolute
LV95 from a PLY, add the offset XYZ vector to every mesh vertex.

Limitations
-----------
* Interior holes (courtyards) are stripped and logged. Hole-aware meshing
  needs the inner rings as additional CDT constraints plus a hole-marker
  point for ``triangle``.
* MultiPolygon footprints take only the largest part (logged). Multi-part
  buildings (main + detached annex) should be meshed independently and
  concatenated.
* The roof is a smooth triangulated DSM clip — **not planar LoD2 surfaces**.
  For visualisation this is usually what you want; for energy / solar /
  CityGML semantics, use ``roofer`` instead.
* The coarse smoothing pass treats features narrower than ~3 m × 3 m as
  thin spikes and replaces them with the surrounding background. This
  removes lift overruns, stair towers, antenna masts, and narrow chimneys.
  Real architecture at that scale (small dormers, ventilation stacks) is
  affected too. Tune via the ``_SMOOTH_COARSE_*`` constants if you need
  to preserve smaller features.
* ``--smooth-radius 0`` disables **both** the fine and coarse passes
  (the coarse pass has no separate CLI knob — yet).

Usage
-----
::

    python build_mesh.py input.csv \\
        --av AV_data.gpkg \\
        --dsm-dir D:/swissSURFACE3D \\
        --dtm-dir D:/swissALTI3D \\
        --output-dir ./meshes

The CSV format matches the main pipeline (``id`` + ``egid`` columns).
Output defaults to PLY (single file, preserves face colours when ``--colour``
is set). OBJ, glTF/glb, and STL are also supported via ``--format``.
"""

import argparse
import json
import logging
import re
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import triangle as tr
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

# Import sibling modules from the parent project's python/ folder.
# Layout:
#   <repo>/python/                                    ← target
#   <repo>/experimental/mesh-builder/build_mesh.py    ← this file
# So the project root is two levels up, and python/ is its sibling.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "python"))

from footprints import load_footprints_from_av_with_egids  # noqa: E402
from tile_fetcher import tile_ids_from_bounds  # noqa: E402
from volume import TileIndex, create_aligned_grid_points  # noqa: E402

log = logging.getLogger("mesh-builder")

DEFAULT_BOUNDARY_SPACING_M = 0.5
DEFAULT_INTERIOR_SPACING_M = 1.0
DEFAULT_SMOOTH_RADIUS_M = 1.5
# Minimum vertical separation between roof (DSM) and floor (DTM) at any
# vertex. Real-world DSM samples can equal DTM at boundary points where the
# AV polygon extends slightly past the actual building envelope (path, yard,
# etc.). Without an enforced gap, those points produce degenerate wall edges
# that survive in-memory construction but get merged by any downstream
# consumer running default vertex-dedup, breaking watertightness on reload.
# 1 cm is invisible at building scale, far above trimesh.tol.merge (1e-5 m),
# and far below DSM/DTM precision (~10 cm).
MIN_WALL_HEIGHT_M = 0.01

# Per-face colours when ``--colour`` is on. Roof gets attention; walls and
# floor stay neutral so the roof reads clearly against them. RGBA, 0-255.
COLOUR_ROOF  = np.array([200,  60,  60, 255], dtype=np.uint8)  # red
COLOUR_WALL  = np.array([200, 205, 215, 255], dtype=np.uint8)  # light cool grey
COLOUR_FLOOR = np.array([ 90,  90,  95, 255], dtype=np.uint8)  # dark grey


# ── Geometry helpers ────────────────────────────────────────────────────────


def _densify_ring(coords: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
    """
    Subdivide each segment of a closed ring so no segment is longer than
    ``spacing``. Returns the open ring (no duplicate closing vertex), in
    insertion order.

    Also drops near-duplicate consecutive vertices (closer than 1 µm) so
    that downstream consumers running default vertex-dedup don't merge
    distinct boundary indices into one and break topology. AV cadastral
    polygons occasionally contain such micro-jitter from the original
    digitisation tool, and ``_normalize_polygon`` simplifies most of it
    away — this guard catches what survives, including duplicates that
    appear only at the ring's closing edge.
    """
    if len(coords) < 2:
        return list(coords)

    DEDUPE_TOL = 1e-6  # 1 µm — far below boundary spacing, far above FP noise

    out: list[tuple[float, float]] = []

    def push(p: tuple[float, float]) -> None:
        if out:
            dx = p[0] - out[-1][0]
            dy = p[1] - out[-1][1]
            if (dx * dx + dy * dy) < DEDUPE_TOL * DEDUPE_TOL:
                return
        out.append(p)

    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        seg_len = float(np.hypot(x2 - x1, y2 - y1))
        n_subdiv = max(1, int(np.ceil(seg_len / spacing)))
        for k in range(n_subdiv):
            t = k / n_subdiv
            push((x1 + t * (x2 - x1), y1 + t * (y2 - y1)))

    # Also guard against the closing edge: if the last densified vertex
    # ended up coincident with the first, drop it.
    if len(out) >= 2:
        dx = out[-1][0] - out[0][0]
        dy = out[-1][1] - out[0][1]
        if (dx * dx + dy * dy) < DEDUPE_TOL * DEDUPE_TOL:
            out.pop()

    return out


_SMOOTH_K = 12
_SMOOTH_UPPER_MAD = 4.0
_SMOOTH_LOWER_MAD = 4.0
_SMOOTH_SUPPORT_DZ = 1.0       # metres
_SMOOTH_MIN_SUPPORT = 3        # min agreeing neighbours to keep a downward outlier

# Coarse pass — catches thin tall features (lift overruns, antenna masts,
# stair towers, narrow chimneys) that are too wide for the fine pass to see
# as outliers. At a 5 m radius, a 2 m wide spike is in the minority and the
# surrounding roof becomes the dominant background.
_SMOOTH_COARSE_K = 30
_SMOOTH_COARSE_RADIUS_M = 5.0
_SMOOTH_COARSE_HEIGHT_GAP_M = 2.0   # min height above background to consider a spike
_SMOOTH_COARSE_MIN_SUPPORT = 6      # max agreeing neighbours for a spike to be flagged


def _smooth_dsm_outliers(
    xy: np.ndarray,
    dsm_z: np.ndarray,
    radius: float,
    k: int = _SMOOTH_K,
) -> np.ndarray:
    """
    Two-pass edge-preserving outlier rejection on DSM samples.

    **Fine pass** (radius ~1.5 m, bidirectional): catches single-vert and
    small-cluster noise.

    * Upward outliers — sample much higher than the local median (vegetation,
      antennas, AC units, mixed-pixel artifacts at building edges). Always
      replaced; there is no realistic case where a single sample is correctly
      several metres above its tight neighbourhood.
    * Downward outliers — sample much lower than the local median. Replaced
      *only* when poorly supported by their neighbourhood (< 3 neighbours
      within ±1 m of the candidate's z). Real lower features — a lower wing,
      a stairwell, a one-storey annex flanked by taller wings — have many
      same-z supporters and survive. Isolated stalactite-causing boundary
      samples don't.

    **Coarse pass** (radius ~5 m, upward only): catches *thin tall features*
    that the fine pass can't see — lift overruns, stair towers, antenna
    masts, narrow chimneys 1-3 m wide. At the fine scale these features'
    own verts dominate the neighbourhood and the median sits at spike
    height; at the coarse scale the surrounding roof becomes the majority
    and the spike is detectable as a high-z minority. We compute a
    "background" z from neighbours that are *not* at the candidate's z
    (excluding the spike's own self-supporters), and replace spikes whose
    candidate sits more than ~2 m above background AND have few
    same-z supporters. The downward direction has no coarse pass — thin
    deep pits in roofs are very rare and almost always real (light wells,
    courtyards, atria).

    Algorithm references:
    * Iglewicz & Hoaglin (1993), modified Z-score for outlier detection
    * Bilateral filter logic — preserve edges, smooth within
    """
    if radius <= 0 or len(xy) < 4:
        return dsm_z

    tree = cKDTree(xy)

    # ── Fine pass: bidirectional, MAD-based ────────────────────────────────
    k_fine = min(k, len(xy))
    dists, idxs = tree.query(xy, k=k_fine)

    z_neighbours = dsm_z[idxs]
    in_radius = dists <= radius
    z_masked = np.where(in_radius, z_neighbours, np.nan)

    medians = np.nanmedian(z_masked, axis=1)
    mads = 1.4826 * np.nanmedian(np.abs(z_masked - medians[:, None]), axis=1)
    mads = np.maximum(mads, 0.3)  # floor for perfectly flat regions

    deviation = dsm_z - medians

    # Both directions are gated by neighbour-support count. Without the
    # guard, MAD-based deviation alone fires false positives at the corners
    # of real multi-vert features: a corner of a 5×5 cluster has only 3
    # cluster neighbours within k=12, so the median of its neighbourhood
    # sits at the *background* z (the 9 surrounding plane verts dominate),
    # MAD floors to ~0.3 m, and the corner's true z gets flagged as a
    # spike. Requiring `n_supporting < 3` cleanly separates "isolated noise"
    # from "edge of a real feature".
    z_diff = np.abs(z_neighbours - dsm_z[:, None])
    n_supporting_fine = (in_radius & (z_diff < _SMOOTH_SUPPORT_DZ)).sum(axis=1) - 1

    is_upper_outlier_fine = (deviation > _SMOOTH_UPPER_MAD * mads) & (n_supporting_fine < _SMOOTH_MIN_SUPPORT)
    is_lower_outlier      = (deviation < -_SMOOTH_LOWER_MAD * mads) & (n_supporting_fine < _SMOOTH_MIN_SUPPORT)

    smoothed = np.where(is_upper_outlier_fine | is_lower_outlier, medians, dsm_z)

    # ── Coarse pass: upward only, background-aware ─────────────────────────
    # Operates on the fine-pass output so micro-noise is gone first. Catches
    # multi-vert spike features that survived the fine pass because their
    # own verts dominated the small-radius neighbourhood.
    n_up_fine = int(is_upper_outlier_fine.sum())
    n_down_fine = int(is_lower_outlier.sum())
    n_spikes = 0

    if len(xy) >= _SMOOTH_COARSE_K:
        k_coarse = min(_SMOOTH_COARSE_K, len(xy))
        dists_c, idxs_c = tree.query(xy, k=k_coarse)
        z_n_c = smoothed[idxs_c]
        in_rad_c = dists_c <= _SMOOTH_COARSE_RADIUS_M

        # "Background" = neighbours that are NOT at the candidate's z. We mask
        # out neighbours within ±_SMOOTH_SUPPORT_DZ of self (those would be
        # spike-self-support) and take the median of what's left. Where the
        # entire neighbourhood is at the same z (real flat roof), background
        # is NaN and the spike test is harmless (NaN > anything is False).
        z_diff_c = np.abs(z_n_c - smoothed[:, None])
        is_background = in_rad_c & (z_diff_c > _SMOOTH_SUPPORT_DZ)
        bg_masked = np.where(is_background, z_n_c, np.nan)
        # Suppress nanmedian's "All-NaN slice encountered" warning. It fires
        # for verts whose entire coarse-radius neighbourhood is at the same
        # z as themselves — i.e. anywhere in the middle of a true flat roof,
        # which is by far the common case. The resulting NaN background
        # propagates harmlessly: the spike test below uses
        # `~np.isnan(background)` so NaN rows never flag.
        # Note: this is a Python RuntimeWarning emitted via warnings.warn,
        # NOT a numpy floating-point invalid op, so np.errstate doesn't
        # catch it — we need warnings.catch_warnings.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            background = np.nanmedian(bg_masked, axis=1)

        # Same-z supporters at the coarse scale
        n_supporting_coarse = (in_rad_c & (z_diff_c <= _SMOOTH_SUPPORT_DZ)).sum(axis=1) - 1

        # A spike: candidate sits above the background by the height gap AND
        # has too few same-z supporters in its broader neighbourhood. We
        # require background to be valid (not NaN) — otherwise we're on a
        # uniformly-flat roof and there's nothing to flag. The np.errstate
        # here silences the "invalid value in subtract/greater" warnings
        # that fire when smoothed - background hits NaN.
        with np.errstate(invalid="ignore"):
            is_spike = (
                ~np.isnan(background)
                & (smoothed - background > _SMOOTH_COARSE_HEIGHT_GAP_M)
                & (n_supporting_coarse < _SMOOTH_COARSE_MIN_SUPPORT)
            )
        n_spikes = int(is_spike.sum())
        if n_spikes:
            smoothed = np.where(is_spike, background, smoothed)

    if n_up_fine or n_down_fine or n_spikes:
        log.debug(
            "Smoothing: %d upward + %d downward (fine), %d thin-spike (coarse)  / %d samples",
            n_up_fine, n_down_fine, n_spikes, len(dsm_z),
        )
    return smoothed


def _normalize_polygon(geom: BaseGeometry) -> Polygon:
    """
    Bring an arbitrary input geometry to the canonical form expected by the
    builder: a single Polygon, exterior ring oriented CCW, no interior rings.

    * MultiPolygon → keeps the largest part, logs the dropped area count.
    * Interior rings (holes / courtyards) → stripped, logged as a v0 limitation.
    * Orientation → forced CCW exterior via ``shapely.geometry.polygon.orient``.
      Shapely does not enforce this on construction; AV cadastral data is
      mixed, and CW input would otherwise produce inverted normals (walls
      facing inward, negative volume).
    """
    if geom is None or geom.is_empty:
        raise ValueError("Empty geometry")

    if geom.geom_type == "MultiPolygon":
        parts = sorted(geom.geoms, key=lambda p: p.area, reverse=True)
        if len(parts) > 1:
            dropped_area = sum(p.area for p in parts[1:])
            log.warning(
                "MultiPolygon: keeping largest part (%.0f m²), dropping %d others (%.0f m² total)",
                parts[0].area, len(parts) - 1, dropped_area,
            )
        polygon = parts[0]
    elif geom.geom_type == "Polygon":
        polygon = geom
    else:
        raise ValueError(f"Unsupported geometry type: {geom.geom_type}")

    if polygon.interiors:
        log.warning(
            "Polygon has %d interior ring(s); v0 ignores them.",
            len(list(polygon.interiors)),
        )
        polygon = Polygon(polygon.exterior)

    # Strip sub-mm jitter from the AV source. Cadastral polygons sometimes
    # contain near-duplicate vertices (1 mm or less apart) carried over from
    # the original digitisation tool. If we don't simplify them out, the
    # densifier preserves them as distinct boundary verts at the same xy,
    # and any downstream consumer that does position-based vertex dedup
    # collapses them and breaks topology. Douglas-Peucker at 1 mm tolerance
    # only removes verts that are *visually indistinguishable* from a
    # straight-line segment between their neighbours.
    polygon = polygon.simplify(0.001, preserve_topology=True)

    return orient(polygon, sign=1.0)


# ── Core mesh builder ───────────────────────────────────────────────────────


def build_building_mesh(
    polygon: Polygon,
    tile_index: TileIndex,
    *,
    boundary_spacing: float = DEFAULT_BOUNDARY_SPACING_M,
    interior_spacing: float = DEFAULT_INTERIOR_SPACING_M,
    smooth_radius: float = DEFAULT_SMOOTH_RADIUS_M,
    colour: bool = True,
) -> trimesh.Trimesh:
    """
    Build a watertight mesh hull for one building footprint.

    Args:
        polygon: AV footprint polygon in LV95 (EPSG:2056).
        tile_index: Pre-built TileIndex with DTM + DSM directories.
        boundary_spacing: Max distance between adjacent boundary vertices [m].
        interior_spacing: Cell size of the interior DSM sampling grid [m].
        smooth_radius: Radius (m) for KDTree-based DSM outlier rejection.
            Set to 0 to disable smoothing entirely.
        colour: If True, set per-face RGBA colours (roof red, walls light grey,
            floor dark grey). Preserved by PLY / glTF output formats; OBJ
            requires an MTL sidecar which trimesh writes automatically.

    Returns:
        trimesh.Trimesh in LV95 coordinates with Z = elevation [m].

    Raises:
        RuntimeError: if no DTM/DSM coverage at the footprint, if the footprint
            is degenerate, or if construction fails to produce a watertight mesh.
    """
    polygon = _normalize_polygon(polygon)

    # 1. Densified boundary (open ring — no duplicate closing vertex)
    boundary_coords = _densify_ring(list(polygon.exterior.coords), boundary_spacing)
    n_boundary = len(boundary_coords)
    if n_boundary < 3:
        raise RuntimeError(f"Footprint degenerate after densification ({n_boundary} verts)")
    boundary_arr = np.asarray(boundary_coords, dtype=float)

    # 2. Interior grid points; KDTree-based dedup against boundary verts.
    # The dedup is mandatory because Triangle refuses near-coincident inputs;
    # a KDTree keeps it O((N+M) log N) instead of O(N·M) (the broadcast version
    # OOMs on large warehouses).
    raw_interior = create_aligned_grid_points(polygon, voxel_size=interior_spacing)
    if raw_interior:
        interior_arr = np.asarray(raw_interior, dtype=float)
        nearest, _ = cKDTree(boundary_arr).query(interior_arr, k=1)
        interior_arr = interior_arr[nearest > (boundary_spacing / 4.0)]
    else:
        interior_arr = np.empty((0, 2), dtype=float)

    all_xy = np.vstack([boundary_arr, interior_arr])
    if len(all_xy) < 3:
        raise RuntimeError(f"Not enough points to triangulate ({len(all_xy)})")

    # 3. Sample DTM and DSM at every (boundary + interior) point.
    # Per-vertex DTM is essential for slope handling: collapsing to a mean
    # would put the floor below the actual ground uphill and above it downhill.
    bounds = polygon.bounds
    tiles = tile_ids_from_bounds(bounds)
    all_pts = [(float(x), float(y)) for x, y in all_xy.tolist()]

    dtm_z = tile_index.sample_heights(all_pts, tiles, "alti3d")
    if np.all(np.isnan(dtm_z)):
        raise RuntimeError("No DTM coverage at footprint")
    if np.isnan(dtm_z).any():
        dtm_z[np.isnan(dtm_z)] = float(np.nanmean(dtm_z))

    dsm_z = tile_index.sample_heights(all_pts, tiles, "surface3d")
    if np.all(np.isnan(dsm_z)):
        raise RuntimeError("No DSM coverage at footprint")
    if np.isnan(dsm_z).any():
        dsm_z[np.isnan(dsm_z)] = float(np.nanmean(dsm_z))

    # Edge-preserving outlier rejection on the DSM samples — kills isolated
    # spikes (vegetation, antennas, AC units) without flattening real roof
    # detail. Applied before the DTM clamp so the clamp still works on the
    # smoothed values.
    dsm_z = _smooth_dsm_outliers(all_xy, dsm_z, smooth_radius)

    # Clamp DSM against *local* DTM with a minimum wall height. Real boundary
    # points sometimes have DSM ≈ DTM (the AV polygon extends slightly past
    # the actual building envelope into a path or yard), and zero-height
    # walls produce degenerate triangles that any downstream vertex-dedup
    # will collapse, breaking watertightness on reload.
    dsm_z = np.maximum(dsm_z, dtm_z + MIN_WALL_HEIGHT_M)

    # 4. CDT for the roof — boundary + interior, boundary edges as constraints.
    # 'p' = PSLG mode (respect segments). 'Q' = quiet. No quality flag, so
    # Triangle does not insert Steiner points; vertex indices are preserved.
    boundary_segments = np.column_stack([
        np.arange(n_boundary, dtype=np.int32),
        (np.arange(n_boundary, dtype=np.int32) + 1) % n_boundary,
    ])
    roof_cdt = tr.triangulate(
        {"vertices": all_xy, "segments": boundary_segments}, "pQ"
    )
    roof_simplices = np.asarray(roof_cdt["triangles"], dtype=np.int64)
    if len(roof_simplices) == 0:
        raise RuntimeError("Roof CDT produced no triangles")
    if len(roof_cdt["vertices"]) != len(all_xy):
        raise RuntimeError(
            f"Roof CDT added Steiner points ({len(roof_cdt['vertices']) - len(all_xy)}); "
            "vertex indexing assumptions broken"
        )

    # 5. CDT for the floor — boundary alone, same constraint segments.
    # Identical algorithm to the roof, just no interior points. The output
    # vertex indices are 0..n_boundary-1, exactly the boundary block.
    floor_cdt = tr.triangulate(
        {"vertices": boundary_arr, "segments": boundary_segments}, "pQ"
    )
    floor_simplices = np.asarray(floor_cdt["triangles"], dtype=np.int64)
    if len(floor_simplices) == 0:
        raise RuntimeError("Floor CDT produced no triangles")
    if len(floor_cdt["vertices"]) != n_boundary:
        raise RuntimeError("Floor CDT added Steiner points")

    # 6. Build vertex array — roof block then floor block.
    # Floor uses the boundary's per-vertex DTM (slope-following), not a mean.
    roof_verts = np.column_stack([all_xy, dsm_z])
    floor_verts = np.column_stack([boundary_arr, dtm_z[:n_boundary]])
    roof_offset = 0
    floor_offset = len(roof_verts)
    vertices = np.vstack([roof_verts, floor_verts])

    # 7. Roof faces — Triangle outputs CCW in 2D, lifts to upward normal in 3D
    roof_faces = roof_simplices + roof_offset

    # 8. Wall faces — vectorised. For each consecutive boundary edge i→j,
    # produce two triangles forming a quad from (top_i, top_j) down to
    # (bottom_i, bottom_j). Winding gives outward normals for CCW exterior.
    i = np.arange(n_boundary, dtype=np.int64)
    j = (i + 1) % n_boundary
    rt_i, rt_j = roof_offset + i, roof_offset + j
    fl_i, fl_j = floor_offset + i, floor_offset + j
    wall_tri_a = np.column_stack([rt_i, fl_i, rt_j])
    wall_tri_b = np.column_stack([rt_j, fl_i, fl_j])
    wall_faces = np.vstack([wall_tri_a, wall_tri_b])

    # 9. Floor faces — same boundary indices, reverse winding so normal is -Z.
    # Floor CDT vertex i is the same xy as boundary vertex i, so we can
    # offset directly into the floor block.
    floor_faces = floor_simplices[:, [0, 2, 1]] + floor_offset

    n_roof  = len(roof_faces)
    n_wall  = len(wall_faces)
    n_floor = len(floor_faces)
    faces = np.vstack([roof_faces, wall_faces, floor_faces])

    # process=False so trimesh doesn't merge / drop anything — our shared-vertex
    # construction is the watertightness guarantee, and we want is_watertight
    # to validate the assembly directly. If construction breaks, fail loudly
    # instead of letting trimesh paper over it.
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if not mesh.is_watertight:
        raise RuntimeError(
            "Mesh construction did not produce a watertight result — "
            "this is a bug in build_building_mesh, not in the input data."
        )

    if colour:
        # Faces are stored as [roof | walls | floor] in that exact order, so
        # we can colour by slice without needing to track per-face region tags.
        face_colors = np.empty((len(faces), 4), dtype=np.uint8)
        face_colors[:n_roof] = COLOUR_ROOF
        face_colors[n_roof:n_roof + n_wall] = COLOUR_WALL
        face_colors[n_roof + n_wall:] = COLOUR_FLOOR
        mesh.visual.face_colors = face_colors

    log.debug(
        "Built mesh: %d verts, %d faces (roof=%d wall=%d floor=%d), "
        "watertight=True, volume=%.1f m³",
        len(mesh.vertices), len(mesh.faces), n_roof, n_wall, n_floor,
        mesh.volume if mesh.is_volume else float("nan"),
    )
    return mesh


# ── CLI ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build watertight LOD2-ish meshes from AV footprints + swisstopo rasters",
    )
    p.add_argument("input_csv", type=Path, help="CSV with id + egid columns (matches main pipeline)")
    p.add_argument("--av", type=Path, required=True, help="AV GeoPackage path")
    p.add_argument("--dsm-dir", type=Path, required=True, help="swissSURFACE3D tile directory")
    p.add_argument("--dtm-dir", type=Path, required=True, help="swissALTI3D tile directory")
    p.add_argument("--output-dir", type=Path, default=Path("./meshes"), help="Output mesh directory")
    p.add_argument(
        "--boundary-spacing", type=float, default=DEFAULT_BOUNDARY_SPACING_M,
        help=f"Max distance between adjacent boundary vertices [m] (default {DEFAULT_BOUNDARY_SPACING_M})",
    )
    p.add_argument(
        "--interior-spacing", type=float, default=DEFAULT_INTERIOR_SPACING_M,
        help=f"Interior DSM sampling grid cell size [m] (default {DEFAULT_INTERIOR_SPACING_M})",
    )
    p.add_argument(
        "--smooth-radius", type=float, default=DEFAULT_SMOOTH_RADIUS_M,
        help=f"Radius (m) for KDTree-based DSM outlier rejection. 0 = disable. "
             f"(default {DEFAULT_SMOOTH_RADIUS_M})",
    )
    p.add_argument(
        "--colour", action="store_true",
        help="Bake per-face colours into the file (roof red, walls grey, floor "
             "dark grey). Off by default — the viewer derives surface colours "
             "from face normals at render time, which is more flexible. Use "
             "this flag only if you need a coloured file for QGIS/ArcGIS or "
             "another consumer that doesn't do runtime classification.",
    )
    p.add_argument(
        "--format", choices=("ply", "obj", "glb", "stl"), default="ply",
        help="Output mesh format. PLY preserves face colours in a single file; "
             "OBJ requires an MTL sidecar; STL drops colours entirely (default ply)",
    )
    p.add_argument("--limit", type=int, default=None, help="Stop after this many buildings")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return p.parse_args(argv)


def _safe_building_id(row: pd.Series) -> str:
    """
    Pick a stable, filesystem-safe identifier for the row's output filename.

    Prefers ``av_egid`` (the EGID matched in the AV layer) over the
    user-supplied ``input_id``, so output filenames always carry the
    cadastral identity of the building rather than an arbitrary CSV row tag.
    Falls back to ``input_id`` only when the AV match yielded no EGID.
    Uses an explicit ``pd.notna`` check rather than truthiness so legitimate
    values like ``0`` or ``""`` survive. Strips anything that's not
    word/dot/dash so the result is safe on Windows paths.
    """
    for key in ("av_egid", "input_id"):
        v = row.get(key)
        if v is not None and pd.notna(v):
            return re.sub(r"[^\w.-]", "_", str(v))
    return "unknown"


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    log.info("Loading footprints from %s …", args.av)
    gdf = load_footprints_from_av_with_egids(args.av, args.input_csv, limit=args.limit)
    ok_rows = gdf[gdf["status_step1"] == "ok"]
    n_skipped = len(gdf) - len(ok_rows)
    log.info("Footprints loaded: %d total, %d usable, %d skipped", len(gdf), len(ok_rows), n_skipped)

    log.info("Indexing raster tiles …")
    tile_index = TileIndex(str(args.dtm_dir), str(args.dsm_dir))

    n_ok = 0
    n_failed = 0
    try:
        for _, row in ok_rows.iterrows():
            building_id = _safe_building_id(row)
            try:
                mesh = build_building_mesh(
                    row.geometry,
                    tile_index,
                    boundary_spacing=args.boundary_spacing,
                    interior_spacing=args.interior_spacing,
                    smooth_radius=args.smooth_radius,
                    colour=args.colour,
                )

                # Translate to a local origin before export. trimesh's PLY
                # exporter writes vertex positions as float32, which only
                # gives ~10–30 cm of precision for LV95 coordinates in the
                # millions — distinct in-memory vertices within that range
                # collapse to the same float32 on export, breaking
                # watertightness on reload. Subtracting the bbox centre
                # brings coordinates into [-100, +100] range where float32
                # has µm-level precision. The offset is logged + written
                # to a sidecar JSON so any GIS tool can recover absolute
                # LV95 coordinates by adding it back.
                offset = mesh.bounds.mean(axis=0)
                mesh.apply_translation(-offset)

                out_path = args.output_dir / f"building_{building_id}.{args.format}"
                mesh.export(str(out_path))
                offset_path = out_path.with_suffix(out_path.suffix + ".offset.json")
                with open(offset_path, "w") as f:
                    json.dump(
                        {
                            "lv95_offset_m": offset.tolist(),
                            "crs": "EPSG:2056",
                            "note": "Add this XYZ vector to every mesh vertex to recover absolute LV95 coordinates.",
                        },
                        f,
                        indent=2,
                    )
                n_ok += 1
                log.info(
                    "[%s] %s — %d verts, %d faces, offset=(%.1f, %.1f, %.1f)",
                    building_id, out_path.name, len(mesh.vertices), len(mesh.faces),
                    *offset,
                )
            except Exception as e:
                n_failed += 1
                # log.exception attaches the current traceback. For an
                # experimental tool whose entire job is exposing edge cases
                # in real cadastral data, the bare exception message is
                # rarely enough to know which assertion fired. The traceback
                # is only logged at DEBUG level so normal runs stay terse;
                # `-v` surfaces it.
                log.error("[%s] failed: %s", building_id, e)
                log.debug("traceback for [%s]:", building_id, exc_info=True)
    finally:
        # Release file handles cached in the tile LRU. The main pipeline gets
        # away with leaking these because it exits the process immediately;
        # an experimental tool may be re-run from a notebook in the same
        # process, and on Windows leaked handles block tile-file replacement.
        for src in tile_index.tile_cache.values():
            try:
                src.close()
            except Exception:
                pass
        tile_index.tile_cache.clear()

    log.info(
        "Done — %d ok, %d failed, %d skipped → %s",
        n_ok, n_failed, n_skipped, args.output_dir.resolve(),
    )
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
