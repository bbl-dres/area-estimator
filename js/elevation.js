/**
 * Elevation tile management — COG reading from swisstopo
 *
 * Adapted from property-inventory/osm-height/js/pipeline.js
 * Handles: LV95 projection, COG tile loading, elevation sampling, grid creation.
 */

import { ALTI3D_URL, SURFACE3D_URL, YEARS, GRID_SPACING } from "./config.js";

// =============================================
// LV95 projection
// =============================================
proj4.defs("EPSG:2056", "+proj=somerc +lat_0=46.9524055555556 +lon_0=7.43958333333333 +k_0=1 +x_0=2600000 +y_0=1200000 +ellps=bessel +towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs");

export function toLV95(lon, lat) {
  return proj4("EPSG:4326", "EPSG:2056", [lon, lat]);
}

export function fromLV95(x, y) {
  return proj4("EPSG:2056", "EPSG:4326", [x, y]);
}

// =============================================
// COG tile management
// =============================================
const tileDataCache = new Map();
const yearHints = { dtm: {}, dsm: {} };
const failedTiles = new Set();

export function tileIdFromLV95(x, y) {
  return Math.floor(x / 1000) + "-" + Math.floor(y / 1000);
}

/**
 * Open a COG tile and read the entire raster into memory.
 * Subsequent calls for the same tile return from cache instantly.
 */
export async function getTileData(urlTemplate, tileId) {
  const datasetKey = urlTemplate.includes("swissalti3d") ? "dtm" : "dsm";
  const cacheKey = datasetKey + ":" + tileId;

  if (tileDataCache.has(cacheKey)) return tileDataCache.get(cacheKey);
  if (failedTiles.has(cacheKey)) return null;

  const hint = yearHints[datasetKey][tileId];
  const yearsToTry = hint ? [hint, ...YEARS.filter((y) => y !== hint)] : YEARS;

  for (const year of yearsToTry) {
    const url = urlTemplate.replace(/{year}/g, year).replace(/{tile}/g, tileId);
    try {
      const tiff = await GeoTIFF.fromUrl(url, { allowFullFile: false });
      const image = await tiff.getImage();
      const rasters = await image.readRasters();
      const origin = image.getOrigin();
      const resolution = image.getResolution();

      const tileData = {
        data: rasters[0],
        width: image.getWidth(),
        height: image.getHeight(),
        ox: origin[0],
        oy: origin[1],
        rx: resolution[0],
        ry: resolution[1],
      };

      tileDataCache.set(cacheKey, tileData);
      yearHints[datasetKey][tileId] = year;
      return tileData;
    } catch (e) {
      continue;
    }
  }

  failedTiles.add(cacheKey);
  return null;
}

/**
 * Sample elevation at a single LV95 point from a cached tile.
 */
export function sampleFromTileData(tileData, x, y) {
  const col = Math.floor((x - tileData.ox) / tileData.rx);
  const row = Math.floor((y - tileData.oy) / tileData.ry);
  if (col < 0 || row < 0 || col >= tileData.width || row >= tileData.height) return null;
  const val = tileData.data[row * tileData.width + col];
  if (val === undefined || isNaN(val) || val < -100) return null;
  return val;
}

/**
 * Pre-load all DTM and DSM tiles needed for a set of LV95 points.
 */
export async function preloadTiles(pointsLV95, onProgress) {
  const tileIds = new Set();
  for (const pt of pointsLV95) {
    tileIds.add(tileIdFromLV95(pt[0], pt[1]));
  }

  let loaded = 0;
  const promises = [];
  tileIds.forEach((tileId) => {
    const dtmKey = "dtm:" + tileId;
    const dsmKey = "dsm:" + tileId;
    if (!tileDataCache.has(dtmKey) && !failedTiles.has(dtmKey)) {
      promises.push(
        getTileData(ALTI3D_URL, tileId).then(() => {
          loaded++;
          if (onProgress) onProgress(loaded, promises.length);
        })
      );
    }
    if (!tileDataCache.has(dsmKey) && !failedTiles.has(dsmKey)) {
      promises.push(
        getTileData(SURFACE3D_URL, tileId).then(() => {
          loaded++;
          if (onProgress) onProgress(loaded, promises.length);
        })
      );
    }
  });

  if (promises.length > 0) {
    // Load up to 4 tiles in parallel
    for (let j = 0; j < promises.length; j += 4) {
      await Promise.all(promises.slice(j, j + 4));
    }
  }
}

// =============================================
// Grid creation
// =============================================
function pointInPolygon(x, y, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/**
 * Create a grid of sample points inside a polygon (LV95 coordinates).
 * Uses axis-aligned grid at GRID_SPACING (1m).
 */
export function createGridPoints(coordsLV95, spacing = GRID_SPACING) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const pt of coordsLV95) {
    if (pt[0] < minX) minX = pt[0];
    if (pt[0] > maxX) maxX = pt[0];
    if (pt[1] < minY) minY = pt[1];
    if (pt[1] > maxY) maxY = pt[1];
  }

  const points = [];
  for (let gx = minX + spacing / 2; gx < maxX; gx += spacing) {
    for (let gy = minY + spacing / 2; gy < maxY; gy += spacing) {
      if (pointInPolygon(gx, gy, coordsLV95)) {
        points.push([gx, gy]);
      }
    }
  }

  // Fallback: centroid if grid is empty (very small footprint)
  if (points.length === 0) {
    let cx = 0, cy = 0;
    for (const pt of coordsLV95) { cx += pt[0]; cy += pt[1]; }
    points.push([cx / coordsLV95.length, cy / coordsLV95.length]);
  }
  return points;
}

/**
 * Polygon area via Shoelace formula on LV95 coords (returns m2).
 */
export function polygonAreaLV95(ring) {
  let area = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    area += ring[j][0] * ring[i][1];
    area -= ring[i][0] * ring[j][1];
  }
  return Math.abs(area) / 2;
}

/**
 * Compute volume and height statistics for a building footprint.
 *
 * Volume is calculated as the sum of (DSM - min_DTM) for each grid point,
 * measured from the lowest terrain point (flat base datum).
 *
 * All tile data must be pre-loaded. This is a synchronous CPU-only operation.
 *
 * @param {number[][]} coordsLV95 - Building footprint ring in LV95
 * @returns {object|null} Volume result or null if no data
 */
export function computeVolumeSync(coordsLV95) {
  const gridPoints = createGridPoints(coordsLV95);
  if (gridPoints.length === 0) return null;

  const heights = [];
  const dtmValues = [];
  const dsmValues = [];
  const validPoints = [];

  for (const pt of gridPoints) {
    const x = pt[0], y = pt[1];
    const tileId = tileIdFromLV95(x, y);

    const dtmTile = tileDataCache.get("dtm:" + tileId);
    const dsmTile = tileDataCache.get("dsm:" + tileId);
    if (!dtmTile || !dsmTile) continue;

    const dtm = sampleFromTileData(dtmTile, x, y);
    const dsm = sampleFromTileData(dsmTile, x, y);
    if (dtm !== null && dsm !== null) {
      dtmValues.push(dtm);
      dsmValues.push(dsm);
      validPoints.push(pt);
    }
  }

  if (dtmValues.length === 0) return null;

  // Use minimum terrain elevation as base datum (flat base)
  const minDTM = Math.min(...dtmValues);
  const maxDTM = Math.max(...dtmValues);
  const meanDTM = dtmValues.reduce((a, b) => a + b, 0) / dtmValues.length;

  const minDSM = Math.min(...dsmValues);
  const maxDSM = Math.max(...dsmValues);
  const meanDSM = dsmValues.reduce((a, b) => a + b, 0) / dsmValues.length;

  // Heights measured from lowest terrain point
  let volume = 0;
  const cells = [];
  for (let i = 0; i < dtmValues.length; i++) {
    const h = Math.max(dsmValues[i] - minDTM, 0);
    heights.push(h);
    volume += h; // Each grid point represents 1m2 (GRID_SPACING = 1)
    cells.push({ x: validPoints[i][0], y: validPoints[i][1], h });
  }

  // Height statistics
  heights.sort((a, b) => a - b);
  const heightMin = heights[0];
  const heightMax = heights[heights.length - 1];
  const heightMean = heights.reduce((a, b) => a + b, 0) / heights.length;

  // Footprint area from grid points
  const footprintArea = polygonAreaLV95(coordsLV95);

  // height_minimal = volume / footprint (equivalent uniform box height)
  const heightMinimal = footprintArea > 0 ? volume / footprintArea : heightMean;

  return {
    volume_m3: Math.round(volume * 100) / 100,
    area_footprint_m2: Math.round(footprintArea * 100) / 100,
    elevation_base_min: Math.round(minDTM * 10) / 10,
    elevation_base_mean: Math.round(meanDTM * 10) / 10,
    elevation_base_max: Math.round(maxDTM * 10) / 10,
    elevation_roof_min: Math.round(minDSM * 10) / 10,
    elevation_roof_mean: Math.round(meanDSM * 10) / 10,
    elevation_roof_max: Math.round(maxDSM * 10) / 10,
    height_min: Math.round(heightMin * 10) / 10,
    height_max: Math.round(heightMax * 10) / 10,
    height_mean: Math.round(heightMean * 10) / 10,
    height_minimal: Math.round(heightMinimal * 10) / 10,
    grid_points: dtmValues.length,
    grid_cells: cells,
    grid_spacing: GRID_SPACING,
  };
}

export function clearElevationCache() {
  failedTiles.clear();
}
