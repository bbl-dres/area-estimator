# Research Notes — Building Mesh Reconstruction

A living collection of tools, papers, datasets, and standards relevant to what
[mesh-builder](README.md) does and what it could become. Organised by problem
area so a future contributor can jump straight to whatever they're trying to
solve next.

> **Currency**: dated April 2026. Tools and links should still be live but
> versions move fast, so check before depending. Items marked **★** are ones
> we've actually used or read; everything else is "worth investigating",
> please update with first-hand notes as you confirm or refute.

---

## Where we sit in the landscape

We're solving the **footprint + raster DSM/DTM → watertight 3D building
hull** problem, in the regime where:

* The footprint is high-quality cadastral data (Swiss AV).
* The elevation data is a regular raster (swissALTI3D + swissSURFACE3D), not
  a classified point cloud.
* The goal is **visualisation**, not energy modelling, CityGML interop, or
  CFD — we accept smooth (non-planar) roofs in exchange for never-failing
  reconstruction across millions of buildings.

This regime is unusual in the literature. Almost everything published on
"3D building reconstruction" assumes a **classified point cloud** input
(LAS/LAZ from airborne LiDAR). The major tools (3dfier, roofer, City4CFD,
City3D) all want point clouds. Tools that take rasters tend to be
photogrammetry-based scene reconstructors (SAT2LoD2), which are heavy and
inconsistent.

Our pipeline trades the noisy-roof tradeoff for guaranteed watertightness
and footprint fidelity. The algorithm itself — densified-boundary
constrained Delaunay over (boundary + interior) DSM samples, with
edge-preserving outlier rejection — is straightforward enough that there's
no obvious paper to cite for it. Where we *do* depend on published research
is in the smoothing (modified Z-score / MAD outlier detection,
edge-preserving filters) and in any future plane-fitting / roof
classification work.

---

## 1. End-to-end LoD2 building reconstruction

The major open-source tools, all of which do the *full* pipeline from
footprint + point cloud → CityGML/CityJSON LoD2.2.

### Open source

| Tool | Authors | Input | Output | Notes |
|---|---|---|---|---|
| **★ [3dfier](https://github.com/tudelft3d/3dfier)** | TU Delft 3D Geoinformation | LAS/LAZ + footprints (shapefile) | LoD1/LoD2 (CityJSON, OBJ) | The classic. Hugo Ledoux et al. Watertight by stitching. C++. Documented at [tudelft3d.github.io/3dfier](https://tudelft3d.github.io/3dfier/) |
| **★ [roofer](https://github.com/3DBAG/roofer)** | 3DBAG / TU Delft / 3DGI | LAS/LAZ + footprints | LoD1.2 / LoD1.3 / LoD2.2 (CityJSON sequence) | The current production tool behind 3DBAG. Successor to the geoflow plugins. C++ + Python bindings. **The thing to use if you have point clouds and want LoD2.2 today.** |
| **[City4CFD](https://github.com/tudelft3d/City4CFD)** | TU Delft (Pađen et al.) | LAS/LAZ + footprints | Watertight LoD1/LoD2 for CFD simulations | Newer than 3dfier, designed specifically for fluid-dynamics meshes. Strict watertightness. |
| **[City3D](https://github.com/tudelft3d/City3D)** | Liangliang Nan et al. | Airborne LiDAR + footprints | LoD2 | Implementation of the City3D paper, builds on PolyFit. Research prototype but used at city scale. |
| **[PolyFit](https://github.com/LiangliangNan/PolyFit)** | Liangliang Nan, Peter Wonka | Point cloud | Polygonal surface | Foundational tool for plane-intersection-based reconstruction. SIGGRAPH 2017. The algorithmic ancestor of City3D. |
| **[SAT2LoD2](https://github.com/GDAOSU/LOD2BuildingModel)** | Ohio State / GDA OSU | Satellite DSM + orthophoto | LoD2 OBJ | Deep-learning based, **needs CUDA**, designed for satellite-derived DSMs (not airborne LiDAR). The closest published thing to our raster-input regime, but heavyweight. |

### Commercial

| Tool | Vendor | Notes |
|---|---|---|
| **[ArcGIS Pro "Extract LOD2 Buildings"](https://pro.arcgis.com/en/pro-app/latest/tool-reference/3d-analyst/extract-lod2-buildings.htm)** | Esri | The mainstream commercial option. Inputs: point cloud + footprints. |
| **FME Workbench** | Safe Software | No built-in LoD2 reconstructor, but custom pipelines via PointCloud transformers + SurfaceModel transformers are common. The parent project's `fme/` folder has examples. |
| **Autodesk InfraWorks** | Autodesk | LoD1 from footprints + heights. Full LoD2 requires manual modelling. |
| **Bentley OpenCities** | Bentley | Reality-mesh-driven; LoD2 from point clouds and oblique imagery. |
| **Vricon / Maxar Precision3D** | Maxar | Global 3D city models from satellite imagery. Closed-source, commercial license. |

### Key papers

| Paper | Year | Code | Why it matters |
|---|---|---|---|
| **[Automated 3D reconstruction of LoD2 and LoD1 models for all 10 million buildings of the Netherlands](https://arxiv.org/abs/2201.01191)** (Peters, Dukai, Vitalis, van Liempt, Stoter) | 2022 | [3DBAG / roofer](https://github.com/3DBAG/roofer) | The 3DBAG paper. Read this first if you want to understand the production-quality LoD2 pipeline that's been deployed nationally. |
| **[3dfier: automatic reconstruction of 3D city models](https://www.researchgate.net/publication/348796610_3dfier_automatic_reconstruction_of_3D_city_models)** (Ledoux et al.) | 2021 | [3dfier](https://github.com/tudelft3d/3dfier) | The original 3dfier algorithm description. Cleaner than the 3DBAG paper but less production-focused. |
| **[Polyfit: Polygonal Surface Reconstruction from Point Clouds](https://github.com/LiangliangNan/PolyFit/blob/main/README.md)** (Nan & Wonka) | 2017 | [PolyFit](https://github.com/LiangliangNan/PolyFit) | The "extract planes, then choose which intersections form the building" approach. SIGGRAPH 2017. |
| **[City3D: Large-scale Building Reconstruction from Airborne LiDAR Point Clouds](https://www.mdpi.com/2072-4292/14/9/2254)** | 2022 | [City3D](https://github.com/tudelft3d/City3D) | Builds on PolyFit, scales to city-wide reconstruction. |
| **[Voxel Depth-Constrained LOD2 Modeling for Urban Buildings](https://link.springer.com/article/10.1007/s44212-025-00090-y)** | 2025 | not released | Recent comparative study with PolyFit, City3D as baselines. Useful for benchmarking. |

---

## 2. Plane segmentation / RANSAC for roofs

If we ever go to "real LoD2" (planar roof faces, not the smooth DSM clip we
have now), this is the literature to know.

### Tools

| Tool | Language | Notes |
|---|---|---|
| **[Open3D `segment_plane`](https://www.open3d.org/docs/release/python_api/open3d.geometry.PointCloud.html)** | Python / C++ | The accessible RANSAC plane fitter. `pcd.segment_plane(distance_threshold, ransac_n, num_iterations)` returns plane equation + inlier indices. Iterate to find multiple planes. ~150 MB dependency. |
| **[pyransac3d](https://pypi.org/project/pyransac3d/)** | Pure Python | Lightweight RANSAC for points / planes / cylinders. No native dependencies. Slower than Open3D for large clouds but trivial to install. |
| **[PCL (Point Cloud Library)](https://pointclouds.org/)** | C++ (Python bindings exist) | The classic. RANSAC, region growing, normal estimation, all the usual point-cloud primitives. Heavy dependency. |
| **[CGAL Shape Detection](https://doc.cgal.org/latest/Shape_detection/index.html)** | C++ | Efficient RANSAC + region growing implementations of Schnabel et al. Used inside roofer. |
| **[Multiple Planes Detection](https://github.com/yuecideng/Multiple_Planes_Detection)** | Python (Open3D-based) | Helper repo for iterating RANSAC across multiple roof planes. Worth reading if you want to understand the iterate-and-remove pattern. |

### Key papers

| Paper | Year | Code | Why it matters |
|---|---|---|---|
| **★ [Efficient RANSAC for Point-Cloud Shape Detection](https://www.hinkali.com/Education/PointCloud.pdf)** (Schnabel, Wahl, Klein) | 2007 | [CGAL implementation](https://doc.cgal.org/latest/Shape_detection/index.html#Shape_detection_RANSAC) | **The foundational paper.** Efficient RANSAC on point clouds via spatial subdivision. Cited everywhere. |
| **[An improved RANSAC algorithm for extracting roof planes from airborne LiDAR data](https://onlinelibrary.wiley.com/doi/abs/10.1111/phor.12296)** (Canaz Sevgen) | 2020 | not released | Roof-specific RANSAC tweaks. Useful for understanding what goes wrong with plain RANSAC on building roofs. |
| **[Plane segmentation for a building roof combining deep learning and the RANSAC method](https://www.spiedigitallibrary.org/journals/journal-of-electronic-imaging/volume-30/issue-5/053022/Plane-segmentation-for-a-building-roof-combining-deep-learning-and/10.1117/1.JEI.30.5.053022.short)** (Chen et al.) | 2021 | not released | DL pre-segmentation feeding RANSAC. The current zeitgeist for combining the two. |
| **[Building Plane Segmentation Based on Point Clouds](https://www.mdpi.com/2072-4292/14/1/95)** | 2022 | not specified | Recent survey. |
| **[An Improved Multi-Task Pointwise Network for Segmentation of Building Roofs](https://onlinelibrary.wiley.com/doi/10.1111/phor.12420)** (Zhang et al.) | 2022 | not released | Pure deep-learning approach (no RANSAC), instance + semantic segmentation jointly. |

### How this would slot into our pipeline

If you want to add plane segmentation:

1. After the roof CDT, sample the smoothed DSM densely (boundary + interior already do this).
2. Feed `(x, y, z)` into Open3D as a `PointCloud`.
3. Iterate `segment_plane` until residuals fall below a threshold or a max plane count is hit.
4. Each detected plane gives you `(a, b, c, d)` with `ax + by + cz + d = 0` and an inlier set.
5. Optionally re-triangulate each inlier set in 2D and project up to its plane → planar roof faces.
6. Snap plane intersection edges (ridges) to integer ridge lines if you want clean LoD2 topology.

The hard part is **step 5–6**: turning N planes into a watertight roof
mesh. CGAL's polygonal surface reconstruction does this; everything else
needs custom plumbing. **PolyFit** is the canonical reference.

---

## 3. Roof shape classification

The "what kind of roof is this" problem — distinct from plane segmentation.
Less academic literature here than you'd expect; most LoD2 work focuses on
geometric reconstruction and treats classification as a downstream
labelling step.

### Taxonomies

> **The full taxonomy with German names, CityGML codes, and standards-mapping
> table lives in [README.md → Roof shape taxonomy](README.md#roof-shape-taxonomy).**
> Treat the README as the canonical reference; this section is for the
> classifier-detection-signal angle.

The standard architectural roof types most pipelines distinguish, with the
geometric signature each one produces in a face-normal histogram:

| Type | Description | Detection signal |
|---|---|---|
| **Flat** | All slope ≤ ~5° | All face normals near vertical |
| **Shed (mono-pitch)** | Single sloped surface | One azimuth peak, one pitch |
| **Gable** | Two opposing slopes meeting at a ridge | Two azimuth peaks 180° apart, equal pitch |
| **Hip** | Four slopes meeting at a peak | Four peaks at 90° intervals |
| **Hip-and-valley** | Hip with intersecting wings | Multi-modal but well-structured |
| **Mansard** | Two pitches per side (steep lower, shallow upper) | Two pitch levels, gable-like azimuth |
| **Gambrel** | Two pitches per side (gable variant) | Same as mansard but two-sided |
| **Pyramidal** | Four equal slopes meeting at a point | Hip with all eaves at same z |
| **Sawtooth** | Repeated mono-pitches | Periodic azimuth + ridge pattern |
| **Butterfly** | Two slopes meeting at a central valley (inverted gable) | Inverse-gable normal pattern |
| **Complex** | None of the above | Many peaks, no clear structure |

The German [SIG3D modeling guide](https://files.sig3d.org/file/ag-qualitaet/201311_SIG3D_Modeling_Guide_for_3D_Objects_Part_2.pdf)
formalises a similar list for CityGML LoD2 modelling — useful reference.

### Existing standards / code lists

* **INSPIRE Building** has a `RoofTypeValue` code list
* **ALKIS** (German cadastre) has roof-type attributes for some buildings
* **OpenStreetMap** `roof:shape=*` tag — 19 values, used in OSM 3D rendering ([wiki](https://wiki.openstreetmap.org/wiki/Key:roof:shape))

### Open source

| Tool | Notes |
|---|---|
| **[OSM2World](http://osm2world.org/)** | Renders OSM 3D buildings from `roof:shape` tags. Inverse problem (rendering from labels) but the taxonomy and parameter mapping are documented. |
| **[F4Map](https://demo.f4map.com/)** | Same idea, web-based. Closed-source but very fast. |
| **[CityGML LoD2 generators](https://github.com/OloOcki/awesome-citygml)** | Curated list of open CityGML datasets and tools. Worth scanning. |

### Key papers

| Paper | Year | Code | Why it matters |
|---|---|---|---|
| **[Segmentation of Airborne Point Cloud Data for Automatic Building Roof Extraction](https://www.tandfonline.com/doi/full/10.1080/15481603.2017.1361509)** | 2017 | not released | Survey + comparison of segmentation methods for roof extraction. Good entry point. |
| **[Building segmentation and modeling from airborne LiDAR data](https://www.tandfonline.com/doi/full/10.1080/17538947.2014.914252)** | 2014 | not released | Older but foundational survey. |

### Pragmatic approach for our pipeline

Discussed in the previous chat turn but worth recording: the cheapest
useful classifier is a **face-normal histogram + peak detection** in the
viewer. ~100 LoC, no new deps, runs in milliseconds:

1. For each roof face (`nz > 0.3`), compute pitch (angle from horizontal)
   and azimuth (compass direction the slope faces).
2. Build an area-weighted azimuth histogram in 10–20° bins.
3. Find peaks above a 5%-of-roof-area threshold.
4. Decision tree on (peak count, peak relationships, mean pitch):
   * 0 peaks (all flat) → flat
   * 1 peak → shed
   * 2 peaks ~180° apart → gable
   * 4 peaks at 90° intervals → hip
   * else → complex

Failure modes: multi-wing buildings (each wing may be a different type),
small dormers contributing minor peaks, edge faces near eaves with weird
normals. Mitigate with area weighting + per-wing clustering as a
preprocessing step.

For "real" LoD2 you'd want **plane segmentation** (section 2) first, then
classification on the plane geometry rather than per-face normals. Cleaner
input but much more code.

---

## 4. DSM denoising and edge-preserving filtering

The "kill the noise without flattening real features" problem. We do
two-pass MAD-based outlier rejection with neighbour-support gating. There
are more sophisticated alternatives if our simple version turns out to be
insufficient on some classes of building.

### Algorithms

| Method | Notes |
|---|---|
| **Bilateral filter** | Smooths within homogeneous regions, preserves edges. Standard for image/range-image denoising. Slower than median. |
| **Joint bilateral filter** | Uses a guidance signal (e.g. orthophoto edges) to drive the smoothing. Useful when you have aligned imagery. |
| **Total Variation (TV) denoising** | Preserves piecewise-constant structure, well suited for buildings. Has nice theoretical properties but slow. |
| **★ Modified Z-score / MAD outlier detection** | Iglewicz & Hoaglin (1993). What we use. Robust to outliers because median + MAD aren't dragged by them. |
| **Conditional Random Fields (CRF)** | Energy-minimisation labelling. Used in semantic segmentation and could be adapted for "is this point on a real surface or noise". |
| **Anisotropic diffusion (Perona–Malik)** | Edge-preserving smoothing via diffusion equations. Classic. |
| **Guided filter (He et al.)** | Faster bilateral alternative, O(N). Standard in image processing now. |

### Tools

| Tool | Language | Notes |
|---|---|---|
| **[WhiteboxTools](https://www.whiteboxgeo.com/manual/wbt_book/)** | Rust + bindings | Extensive raster smoothing toolkit. Specifically built for terrain/elevation work. |
| **[SAGA GIS](http://www.saga-gis.org/)** | C++ | Long-standing terrain analysis package. |
| **[lidR](https://github.com/r-lidar/lidR)** | R | LiDAR-specific processing. Has `lidR::filter_*` family for outlier removal. |
| **[PDAL](https://pdal.io/)** | C++ + Python | Point Data Abstraction Library — the LiDAR equivalent of GDAL. Has `filters.outlier`, `filters.smrf`, etc. |
| **[scipy.ndimage](https://docs.scipy.org/doc/scipy/reference/ndimage.html)** | Python | Has `median_filter`, `gaussian_filter`, `generic_filter` — good for raster-domain smoothing **before** sampling. We don't currently do this. |
| **[scikit-image](https://scikit-image.org/)** | Python | Bilateral filter (`skimage.restoration.denoise_bilateral`), TV denoising, anisotropic diffusion — applies to the raster as a 2D image. |

### Could-improve

A specific improvement worth investigating: **pre-filter the DSM raster
with a 3×3 or 5×5 median filter via scipy.ndimage *before* sampling**, then
apply our KDTree outlier rejection on top. The raster-domain median is
much faster (operates on the regular grid) and removes a lot of single-pixel
noise that the KDTree pass currently has to deal with.

---

## 5. Mesh I/O and processing

Foundation libraries we depend on, and alternatives if we ever outgrow them.

### What we use

| Library | Version | Role |
|---|---|---|
| **[trimesh](https://github.com/mikedh/trimesh)** | ≥4.0 | Mesh assembly + I/O (OBJ/PLY/glTF/STL). The `is_watertight` check, `apply_translation`, `face_colors`. **Well maintained, recommended.** |
| **[triangle](https://pypi.org/project/triangle/)** (Shewchuk) | ≥20230923 | Constrained Delaunay triangulation. Python wrapper around the canonical C library. The PSLG mode (`p` flag) preserves vertex indices and respects boundary segments. |
| **[scipy.spatial.cKDTree](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.cKDTree.html)** | ≥1.11 | Nearest-neighbour queries for the smoothing pass. |
| **[shapely](https://shapely.readthedocs.io/)** | ≥2.0 | Polygon orientation, simplification, the `constrained_delaunay_triangles` function (which we don't use anymore but is documented in case). |

### Could replace / supplement

| Library | Notes |
|---|---|
| **[PyVista](https://pyvista.org/)** | Higher-level mesh manipulation built on VTK. `extrude_trim`, `clip_box`, plotting. Heavier dependency than trimesh, but better at advanced operations. |
| **[Open3D](https://www.open3d.org/)** | Mesh + point cloud + RANSAC + visualisation. The closest single-library to "everything we'd ever need". ~150 MB. |
| **[meshio](https://github.com/nschloe/meshio)** | Pure-Python format conversions. Good for OBJ↔CityJSON↔glTF gluing. |
| **[pyfqmr](https://pypi.org/project/pyfqmr/)** | Fast Quadric Mesh Reduction. Pure C++ wrapper, ~100 KB. The decimation tool to use if we ever want to reduce face counts further. |
| **[CGAL Python bindings](https://github.com/CGAL/cgal-swig-bindings)** | Computational geometry. Has CDT, surface mesh, polygon mesh processing. C++ heavy. |

### Watertight-mesh-specific

| Tool | Notes |
|---|---|
| **[MeshLab](https://www.meshlab.net/)** | GUI mesh repair / inspection. Useful as a sanity check on questionable output. |
| **[Manifold](https://github.com/elalish/manifold)** | C++ library specifically for guaranteed-manifold mesh boolean operations. Used by OpenSCAD. Worth knowing if you ever need clean union/intersection of building meshes. |
| **[libigl](https://libigl.github.io/)** | Geometry processing library. Extensive remeshing, simplification, boolean ops. C++ + Python. |

---

## 6. Output formats and standards

What to know about the formats we support and the standards we *don't* but
maybe should.

### Output formats

| Format | What it preserves | Use case |
|---|---|---|
| **OBJ** | Vertices, faces, optional MTL for materials | Generic 3D viewers, Blender, QGIS 3D. ASCII = full float64 precision. |
| **PLY** | Vertices, faces, **per-face colours**, custom properties | CloudCompare, MeshLab. Binary = float32 (the precision trap we hit). Single file. |
| **STL** | Faces only (vertex sharing not preserved on disk) | 3D printing. Drops everything else. |
| **glTF / glb** | Vertices, faces, materials, animation, scene graph | Web 3D (Three.js, Cesium), Unity/Unreal. The modern format. |
| **3D Tiles** | Hierarchical tiled glTF | Web 3D at city/world scale. Cesium standard. |

### Standards (not currently emitted)

| Standard | What it is | Why we'd care |
|---|---|---|
| **[CityGML](https://www.ogc.org/standards/citygml/)** | OGC standard for 3D city models. XML-encoded. Semantic (roof / wall / floor / window). | The interop standard for sharing LoD2/LoD3 building data across tools and jurisdictions. |
| **[CityJSON](https://www.cityjson.org/)** | JSON encoding of CityGML 3.0. Smaller, easier to parse. | Modern alternative to CityGML XML. **If we ever want LoD2 interop, this is the format to write.** |
| **[3D Tiles](https://www.ogc.org/standard/3dtiles/)** | Cesium-driven spec for tiled 3D content streaming | If we ever want a Cesium-based web viewer over a national dataset. |
| **[IFC](https://www.buildingsmart.org/standards/bsi-standards/industry-foundation-classes/)** | BIM standard. Detailed building elements (walls, slabs, beams). | Overkill for our use case but the BIM/AEC industry standard. |

### Resources

* **[awesome-citygml](https://github.com/OloOcki/awesome-citygml)** — curated
  list of open semantic 3D city models worldwide. Browse to see what national
  datasets exist and in what format.
* **[CityJSON specification](https://www.cityjson.org/specs/)** — read this if
  you ever want to write a CityJSON exporter from mesh-builder.
* **[3DBAG documentation](https://docs.3dbag.nl/en/)** — the operational
  manual for the world's largest open national LoD2 dataset.

---

## 7. Datasets — what national 3D building data exists

Useful as **reference / benchmark / training data** for any improvements to
our pipeline. Most are LoD2; quality varies by country.

| Country | Dataset | License | Coverage | Notes |
|---|---|---|---|---|
| **Switzerland** | [swissBUILDINGS3D 3.0](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta) | Open | National | LoD2 from automated reconstruction. **Inconsistent** — the reason this prototype exists. |
| **Switzerland** | [swissTLM3D](https://www.swisstopo.admin.ch/en/landscape-model-swisstlm3d) | Open | National | LoD1 buildings as part of the broader topographic model. Curated, consistent. |
| **Netherlands** | [3DBAG](https://3dbag.nl) | CC0 | All ~10 million buildings | LoD1.2 / 1.3 / 2.2 in CityJSON, OBJ, glTF, GeoPackage, Shapefile. **The gold standard for open national LoD2 data.** |
| **Germany** | [LoD2-DE](https://data.europa.eu/data/datasets/31bedca5-1843-4254-a168-1acda618c0b4) | Varies by state | Most states free | National LoD2 coverage, federated by state. CityGML. Quality varies. |
| **Austria** | Various state datasets | Varies | Partial | No unified national release. |
| **France** | [BD TOPO](https://geoservices.ign.fr/bdtopo) (3D) | Open | National | LoD1 with eaves heights. |
| **USA** | [Microsoft Building Footprints](https://github.com/microsoft/USBuildingFootprints) | ODbL | National | Footprints only, no 3D. |
| **Global** | [Microsoft Global Building Footprints](https://github.com/microsoft/GlobalMLBuildingFootprints) | ODbL | Worldwide | Footprints only, no 3D. |
| **Global** | [Overture Maps Buildings](https://overturemaps.org/) | ODbL | Worldwide | Footprints + height attributes (where available). |

### Test sets for roof shape classification

If we ever want to train or benchmark a classifier:

* **[RoofN3D](https://roofn3d.gis.tu-berlin.de/)** — TU Berlin labelled roof-shape
  point cloud dataset. Includes per-roof class labels. (Worth investigating —
  haven't used it directly.)
* **3DBAG** — has implicit shape information you can derive from the LoD2.2 mesh
  topology (count of planar faces, ridge orientations).
* **OSM `roof:shape` tags** — sparse but free crowdsourced labels.

---

## 8. Constrained Delaunay Triangulation — the foundation of our mesh

What we use, and the alternatives.

### Tools

| Tool | Notes |
|---|---|
| **★ [Triangle (Shewchuk)](https://www.cs.cmu.edu/~quake/triangle.html)** | C library, the gold standard for 2D CDT. Python wrapper at [pypi.org/project/triangle](https://pypi.org/project/triangle/). What we use. Free for non-commercial; commercial license available. |
| **[CGAL Triangulation](https://doc.cgal.org/latest/Triangulation_2/index.html)** | C++ alternative. More general than Triangle (3D triangulations, periodic, etc.) but heavier dependency. |
| **[GEOS / Shapely CDT](https://shapely.readthedocs.io/en/stable/reference/shapely.constrained_delaunay_triangles.html)** | New in Shapely 2.1. Pure-polygon CDT (no Steiner points). We tried it for the floor; switched to triangle for consistency with the roof CDT. |
| **[earcut](https://github.com/mapbox/earcut)** | Ear-clipping (not CDT). Faster for simple polygons but doesn't handle interior points. The mapping/web-rendering standard. |
| **[meshpy.triangle](https://documen.tician.de/meshpy/)** | Another Python wrapper around Triangle. Older interface than the `triangle` package. |

### Key references

| Reference | Year | Notes |
|---|---|---|
| **[Triangle: Engineering a 2D Quality Mesh Generator](https://www.cs.cmu.edu/~quake-papers/triangle.ps)** (Shewchuk) | 1996 | The Triangle paper. Read once if you want to understand what `pq30a` and friends mean. |
| **[Constrained Delaunay Triangulations](https://link.springer.com/article/10.1007/BF02187783)** (Chew) | 1989 | Foundational paper on CDT. |

---

## 9. Swiss-specific resources

Resources specific to Switzerland that the rest of the literature doesn't
cover.

| Resource | Authority | Notes |
|---|---|---|
| **[swissALTI3D](https://www.swisstopo.admin.ch/en/height-model-swissalti3d)** | swisstopo | DTM (terrain). 0.5 m. What our `--dtm-dir` consumes. |
| **[swissSURFACE3D Raster](https://www.swisstopo.admin.ch/en/height-model-swisssurface3d-raster)** | swisstopo | DSM (surface). 0.5 m. What our `--dsm-dir` consumes. |
| **[swissBUILDINGS3D 3.0](https://www.swisstopo.admin.ch/en/landscape-model-swissbuildings3d-3-0-beta)** | swisstopo | The pre-built LoD2 we're trying to improve on (consistency-wise). |
| **[swissTLM3D](https://www.swisstopo.admin.ch/en/landscape-model-swisstlm3d)** | swisstopo | National LoD1 with eaves heights. Discussed earlier in the chat as a potential hybrid input. |
| **[Amtliche Vermessung (AV)](https://www.geodienste.ch/services/av)** | Cantons via geodienste.ch | Cadastral building polygons. The footprint source we use. |
| **[GWR (Gebäude- und Wohnungsregister)](https://www.housing-stat.ch/de/index.html)** | Federal Statistical Office | Building register. The parent project uses this for floor counts and building classifications. |
| **[swisstopo data download portal](https://www.swisstopo.admin.ch/en/geodata)** | swisstopo | Where to manually download tiles. The parent project's `tile_fetcher.py` does this programmatically. |

---

## 10. People to follow

Researchers and groups producing the most relevant work.

| Person / Group | Affiliation | What they do |
|---|---|---|
| **[3D Geoinformation @ TU Delft](https://3d.bk.tudelft.nl/)** | TU Delft | The most prolific group in open-source 3D building reconstruction. Hugo Ledoux, Jantien Stoter, Ravi Peters et al. Authors of 3dfier, City4CFD, City3D, 3DBAG, CityJSON. **Read everything they publish.** |
| **[3DGI](https://3dgi.nl/)** | Spinout from TU Delft | Operational arm of the 3DBAG project. Maintains roofer. |
| **[Liangliang Nan](https://3d.bk.tudelft.nl/liangliang/)** | TU Delft / Wuhan U | PolyFit, Easy3D, Mapple. The point-cloud-to-mesh person. |
| **Florent Lafarge** | Inria Sophia Antipolis | Building reconstruction from urban scans. Many influential papers in the late 2010s. |
| **Thomas H. Kolbe** | TU München | CityGML chair. The 3D city modelling standardisation lead. |
| **Norbert Pfeifer** | TU Wien | LiDAR processing. Authority on point cloud denoising and segmentation for terrain/buildings. |

---

## 11. Conferences and venues

Where the relevant work gets published.

| Venue | Frequency | Focus |
|---|---|---|
| **[ISPRS Annals / Archives](https://www.isprs.org/publications/annals.aspx)** | Annual + congress every 4 years | Photogrammetry, remote sensing, 3D city modelling. **The primary venue for LoD2 reconstruction work.** Open access. |
| **[3D GeoInfo conference](https://www.3dgeoinfo.org/)** | Annual | Smaller, specifically 3D geographic information. Where the 3DBAG / TU Delft group publishes a lot. |
| **[ACM SIGGRAPH](https://www.siggraph.org/)** | Annual | Computer graphics. Where PolyFit (Nan & Wonka 2017) was published. Mesh processing fundamentals. |
| **[Eurographics](https://www.eg.org/)** | Annual | European computer graphics. Schnabel's Efficient RANSAC paper was here. |
| **[IEEE TGRS / GRSL](https://www.grss-ieee.org/publications/transactions-on-geoscience-and-remote-sensing/)** | Monthly | Remote sensing. Heavier on satellite/airborne sensor papers. |
| **[CVPR / ICCV / ECCV](https://cvpr2025.thecvf.com/)** | Annual | Deep-learning-heavy. Where the new neural approaches to 3D building reconstruction are showing up. |

---

## 12. Things we haven't tried but maybe should

A list of "interesting next experiments" that don't fit cleanly into the
categories above. **Add to this freely.**

* **Pre-filter the DSM raster with `scipy.ndimage.median_filter` (3×3 or 5×5)
  before sampling**, instead of relying entirely on the post-sampling KDTree
  smoother. Likely faster and removes a lot of single-pixel noise upstream.
* **Hybrid eaves: TLM3D eaves polygon + DSM ridge.** Discussed earlier. Use
  TLM3D's authoritative eaves height as a clamping floor for DSM samples
  near the polygon boundary, fixing the polygon-edge artifact case at its
  root rather than via outlier rejection.
* **Per-wing classification** for multi-wing buildings (like EGID 2241912).
  Cluster the roof by height region first, classify each cluster separately.
  Probably needs a connected-component step on the height-binned DSM.
* **Median filter the boundary samples specifically** (not the whole DSM),
  since boundary samples are where most of our remaining noise lives.
* **Adaptive interior spacing** based on local DSM roughness. Smooth roofs
  could be sampled at 2 m, complex roofs at 0.5 m. Same fidelity, fewer
  faces.
* **Pre-compute a per-tile spatial index of valid building pixels** so
  sample_heights can use a Boolean mask to drop noise samples (e.g., trees
  reaching above the roof and registering as part of the building).
* **Quadric edge collapse decimation** ([pyfqmr](https://pypi.org/project/pyfqmr/))
  as a post-build step to halve face counts on flat-roof regions while
  preserving detail elsewhere. ~50 LOC, no dependencies.
* **Multi-pass smoothing** with progressively larger radii: 1.5 m → 5 m → 10 m,
  each catching features the previous missed. We have two passes; a third
  might catch big sloppy features (whole low wings on irregular complexes).
* **Output CityJSON LoD1.3** as an additional `--format` option, to give
  GIS-tool consumers an interop-friendly format. ~200 LOC using the existing
  vertex/face arrays plus a small JSON wrapper.

---

## How to use this document

* **When you find a useful tool or paper**: add a row to the relevant section
  with a one-line "why it matters". Mark with **★** if you've used it.
* **When a link breaks**: replace it; don't delete the entry. Most things in
  this space have stable canonical sources (researchgate, arxiv, official
  product pages) so finding the new home is usually easy.
* **When you try something from "things we haven't tried"**: move it out of
  that section and into the relevant topic with a verdict.
* **When you find a paper that contradicts a claim here**: update the claim.
  This is a working document, not a publication.
