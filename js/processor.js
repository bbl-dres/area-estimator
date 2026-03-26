/**
 * Core processing pipeline:
 * 1. Fetch building footprints (AV geodata via WFS or swisstopo API)
 * 2. Pre-load elevation tiles (DTM + DSM COGs)
 * 3. Compute volume and heights per building
 * 4. Optionally estimate floor areas via GWR lookup
 */

import { API, CONCURRENCY, STATUS, getFloorHeight, determineAccuracy } from "./config.js";
import { toLV95, preloadTiles, computeVolumeSync, polygonAreaLV95 } from "./elevation.js";

let cancelled = false;

export function cancelProcessing() {
  cancelled = true;
}

/**
 * Process all rows from the uploaded CSV.
 * @param {object[]} rows - Parsed CSV rows with id, lon, lat (or egid)
 * @param {function} onProgress - Callback({ processed, total, succeeded, failed })
 * @returns {object} { buildings: [...] } or null if cancelled
 */
export async function processRows(rows, onProgress) {
  cancelled = false;
  const total = rows.length;
  let processed = 0, succeeded = 0, failed = 0;

  async function processOne(row) {
    if (cancelled) return null;

    const result = {
      input_id: row.id || "",
      input_egid: row.egid || "",
      input_lon: row.lon || "",
      input_lat: row.lat || "",
      // Footprint
      geometry: null,
      av_egid: null,
      area_official_m2: null,
      // Volume
      volume_m3: null,
      area_footprint_m2: null,
      elevation_base_min: null,
      elevation_base_mean: null,
      elevation_base_max: null,
      elevation_roof_min: null,
      elevation_roof_mean: null,
      elevation_roof_max: null,
      height_min: null,
      height_max: null,
      height_mean: null,
      height_minimal: null,
      grid_points: null,
      // Area estimation
      gkat: null,
      gklas: null,
      gbauj: null,
      gastw: null,
      floor_height_used: null,
      floors_estimated: null,
      area_floor_total_m2: null,
      building_type: null,
      area_accuracy: null,
      // Status
      status: null,
    };

    try {
      // Get building footprint
      const footprint = await fetchFootprint(row);
      if (!footprint) {
        result.status = STATUS.NO_FOOTPRINT;
        failed++;
        return result;
      }

      result.geometry = footprint.geometry;
      result.av_egid = footprint.egid || null;
      result.area_official_m2 = footprint.area || null;

      // Convert to LV95 for volume computation
      const coords = footprint.geometry.coordinates[0];
      const lv95Coords = coords.map((c) => toLV95(c[0], c[1]));

      // Pre-load tiles for this building's extent
      await preloadTiles(lv95Coords);

      // Compute volume
      const vol = computeVolumeSync(lv95Coords);
      if (!vol) {
        result.status = STATUS.NO_HEIGHT_DATA;
        result.area_footprint_m2 = Math.round(polygonAreaLV95(lv95Coords) * 100) / 100;
        failed++;
        return result;
      }

      // Copy volume results (keep grid_cells as lightweight LV95 data for lazy conversion)
      const { grid_cells, ...volResults } = vol;
      Object.assign(result, volResults);
      if (grid_cells) result.grid_cells = grid_cells;
      result.status = STATUS.SUCCESS;
      succeeded++;

      // Try GWR lookup for floor area estimation
      const egid = footprint.egid || row.egid;
      if (egid) {
        try {
          const gwr = await fetchGWR(egid);
          if (gwr) {
            result.gkat = gwr.gkat;
            result.gklas = gwr.gklas;
            result.gbauj = gwr.gbauj;
            result.gastw = gwr.gastw;
          }
        } catch (e) {
          // GWR lookup failure is non-fatal
        }

        // Estimate floor area
        const fh = getFloorHeight(result.gkat, result.gklas);
        result.floor_height_used = Math.round(fh.floorHeight * 100) / 100;
        result.building_type = fh.description;

        if (result.height_minimal > 0 && result.area_footprint_m2 > 0) {
          const floorsEstimate = Math.max(1, result.height_minimal / fh.floorHeight);
          result.floors_estimated = Math.round(floorsEstimate);
          result.area_floor_total_m2 = Math.round(result.area_footprint_m2 * floorsEstimate * 100) / 100;
          result.area_accuracy = determineAccuracy(result.gkat, result.gklas, true);
        }
      }
    } catch (err) {
      result.status = "error:" + err.message;
      failed++;
    }

    return result;
  }

  // Process with bounded concurrency using a slot-based semaphore
  const results = new Array(total);
  let running = 0;
  let nextResolve = null;

  function releaseSlot() {
    running--;
    if (nextResolve) {
      const resolve = nextResolve;
      nextResolve = null;
      resolve();
    }
  }

  function acquireSlot() {
    if (running < CONCURRENCY) {
      running++;
      return Promise.resolve();
    }
    return new Promise((resolve) => { nextResolve = resolve; }).then(() => { running++; });
  }

  const allPromises = [];

  for (let i = 0; i < total; i++) {
    if (cancelled) return null;

    await acquireSlot();

    const idx = i;
    const promise = processOne(rows[idx]).then((r) => {
      results[idx] = r;
      processed++;
      releaseSlot();
      onProgress({ processed, total, succeeded, failed });
    });
    allPromises.push(promise);
  }

  await Promise.all(allPromises);

  if (cancelled) return null;
  return { buildings: results.filter(Boolean) };
}

// =============================================
// Footprint fetching
// =============================================

/**
 * Fetch building footprint geometry from AV WFS.
 * Uses bounding box query around the given coordinates.
 */
async function fetchFootprint(row) {
  const lon = parseFloat(row.lon);
  const lat = parseFloat(row.lat);
  const egid = row.egid ? String(row.egid).trim() : null;

  // Strategy 1: If we have EGID, query AV WFS directly by GWR_EGID filter
  if (egid) {
    return await fetchFootprintByEGID(egid);
  }

  // Strategy 2: If we have coordinates, query WFS with bbox
  if (!isNaN(lon) && !isNaN(lat)) {
    return await fetchFootprintByCoords(lon, lat, egid);
  }

  return null;
}

async function fetchFootprintByCoords(lon, lat, egid) {
  // Query AV WFS with ~50m buffer bbox in WGS84
  const bbox = `${lat - 0.0005},${lon - 0.0007},${lat + 0.0005},${lon + 0.0007},urn:ogc:def:crs:EPSG::4326`;
  const wfsUrl = `${API.WFS_AV}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature` +
    `&TYPENAMES=ms:LCSF&OUTPUTFORMAT=geojson&COUNT=100&SRSNAME=urn:ogc:def:crs:EPSG::4326&BBOX=${bbox}`;

  try {
    const resp = await fetchWithTimeout(wfsUrl, 15000);
    if (!resp.ok) throw new Error(`WFS ${resp.status}`);
    const data = await resp.json();

    if (!data.features || data.features.length === 0) {
      return null;
    }

    // Find building features (Art = "Gebaeude" or "Gebäude")
    const buildings = data.features.filter((f) => {
      const art = (f.properties.art || f.properties.Art || "").toLowerCase();
      return art.includes("gebaeude") || art.includes("gebäude");
    });

    if (buildings.length === 0) {
      return null;
    }

    // Find the building containing or nearest to the point
    let best = null;
    let bestDist = Infinity;

    for (const b of buildings) {
      if (b.geometry.type === "Polygon" || b.geometry.type === "MultiPolygon") {
        const pt = turf.point([lon, lat]);
        if (turf.booleanPointInPolygon(pt, b)) {
          best = b;
          bestDist = 0;
          break;
        }
        const dist = turf.distance(pt, turf.centroid(b));
        if (dist < bestDist) {
          bestDist = dist;
          best = b;
        }
      }
    }

    if (!best) return null;

    // Normalize geometry to Polygon
    let geom = best.geometry;
    if (geom.type === "MultiPolygon") {
      geom = { type: "Polygon", coordinates: geom.coordinates[0] };
    }

    return {
      geometry: geom,
      egid: best.properties.egid || best.properties.EGID || egid,
      area: best.properties.flaeche || best.properties.Flaeche || best.properties.area || null,
    };
  } catch (err) {
    console.warn("AV WFS query failed:", err);
    return null;
  }
}

async function fetchFootprintByEGID(egid) {
  // Validate EGID is numeric to prevent XML injection in filter
  if (!/^\d+$/.test(egid)) return null;

  // Query AV WFS directly by GWR_EGID attribute filter
  const filter = `<Filter><PropertyIsEqualTo><PropertyName>GWR_EGID</PropertyName><Literal>${egid}</Literal></PropertyIsEqualTo></Filter>`;
  const wfsUrl = `${API.WFS_AV}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature` +
    `&TYPENAMES=ms:LCSF&OUTPUTFORMAT=geojson&SRSNAME=urn:ogc:def:crs:EPSG::4326` +
    `&FILTER=${encodeURIComponent(filter)}`;

  try {
    const resp = await fetchWithTimeout(wfsUrl, 15000);
    if (!resp.ok) return null;
    const data = await resp.json();

    if (!data.features || data.features.length === 0) return null;

    const feature = data.features[0];
    let geom = feature.geometry;
    if (geom.type === "MultiPolygon") {
      geom = { type: "Polygon", coordinates: geom.coordinates[0] };
    }

    return {
      geometry: geom,
      egid: feature.properties.GWR_EGID || egid,
      area: null,
    };
  } catch (err) {
    console.warn("AV WFS EGID query failed:", err);
  }
  return null;
}

// =============================================
// GWR lookup
// =============================================

const gwrCache = new Map();

async function fetchGWR(egid) {
  if (!egid) return null;
  const key = String(egid).trim();
  if (gwrCache.has(key)) return gwrCache.get(key);

  try {
    // Exact EGID match via MapServer find
    const findUrl = `${API.GWR_FIND}?layer=ch.bfs.gebaeude_wohnungs_register` +
      `&searchText=${encodeURIComponent(key)}&searchField=egid&returnGeometry=false&contains=false`;
    const resp = await fetchWithTimeout(findUrl, 10000);
    if (!resp.ok) { gwrCache.set(key, null); return null; }
    const data = await resp.json();

    if (!data.results || data.results.length === 0) { gwrCache.set(key, null); return null; }

    const attrs = data.results[0].attributes || {};
    const result = {
      gkat: attrs.gkat || null,
      gklas: attrs.gklas || null,
      gbauj: attrs.gbauj || null,
      gastw: attrs.gastw || null,
    };

    gwrCache.set(key, result);
    return result;
  } catch (err) {
    gwrCache.set(key, null);
    return null;
  }
}

// =============================================
// Utilities
// =============================================

function fetchWithTimeout(url, timeout = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  return fetch(url, { signal: controller.signal }).finally(() => clearTimeout(timer));
}
