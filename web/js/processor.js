/**
 * Core processing pipeline:
 * 1. Fetch building footprints (AV geodata via WFS or swisstopo API)
 * 2. Pre-load elevation tiles (DTM + DSM COGs)
 * 3. Compute volume and heights per building
 * 4. Optionally estimate floor areas via GWR lookup
 */

import { API, CONCURRENCY, STATUS, getFloorHeight, determineAccuracy } from "./config.js";
import { toLV95, fromLV95, preloadTiles, computeVolumeSync, polygonAreaLV95 } from "./elevation.js";

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

  const results = [];

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

      // Copy volume results
      Object.assign(result, vol);
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

  // Process with bounded concurrency using a simple semaphore
  let running = 0;
  const allPromises = [];

  for (let i = 0; i < total; i++) {
    if (cancelled) return null;

    // Wait if at concurrency limit
    while (running >= CONCURRENCY) {
      await new Promise((r) => setTimeout(r, 50));
    }

    running++;
    const promise = processOne(rows[i]).then((r) => {
      if (r) results.push(r);
      processed++;
      running--;
      onProgress({ processed, total, succeeded, failed });
    });
    allPromises.push(promise);
  }

  // Wait for remaining
  await Promise.all(allPromises);

  if (cancelled) return null;
  return { buildings: results };
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

  // Strategy 1: If we have coordinates, query WFS with bbox
  if (!isNaN(lon) && !isNaN(lat)) {
    return await fetchFootprintByCoords(lon, lat, egid);
  }

  // Strategy 2: If we only have EGID, find location via swisstopo API then query WFS
  if (egid) {
    return await fetchFootprintByEGID(egid);
  }

  return null;
}

async function fetchFootprintByCoords(lon, lat, egid) {
  // Convert to LV95 for bbox
  const [x, y] = toLV95(lon, lat);

  // Query AV WFS with 50m buffer bbox
  const buffer = 50;
  const bbox = `${lat - 0.0005},${lon - 0.0007},${lat + 0.0005},${lon + 0.0007}`;
  const wfsUrl = `${API.WFS_AV}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature` +
    `&TYPENAMES=ms:LCSF&OUTPUTFORMAT=geojson&COUNT=100&BBOX=${bbox}`;

  try {
    const resp = await fetchWithTimeout(wfsUrl, 15000);
    if (!resp.ok) throw new Error(`WFS ${resp.status}`);
    const data = await resp.json();

    if (!data.features || data.features.length === 0) {
      // Fallback: try swisstopo identify
      return await fetchFootprintViaSwisstopo(lon, lat, egid);
    }

    // Find building features (Art = "Gebaeude" or "Gebäude")
    const buildings = data.features.filter((f) => {
      const art = (f.properties.art || f.properties.Art || "").toLowerCase();
      return art.includes("gebaeude") || art.includes("gebäude");
    });

    if (buildings.length === 0) {
      return await fetchFootprintViaSwisstopo(lon, lat, egid);
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

    if (!best) return await fetchFootprintViaSwisstopo(lon, lat, egid);

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
    // Fallback to swisstopo
    return await fetchFootprintViaSwisstopo(lon, lat, egid);
  }
}

async function fetchFootprintByEGID(egid) {
  // Step 1: Find building location via swisstopo search
  const searchUrl = `${API.SEARCH}?searchText=${encodeURIComponent(egid)}&type=locations&origins=address`;
  try {
    const resp = await fetchWithTimeout(searchUrl, 10000);
    if (!resp.ok) return null;
    const data = await resp.json();

    if (!data.results || data.results.length === 0) return null;

    // Find the GWR feature
    const gwrResult = data.results.find((r) =>
      r.attrs && r.attrs.featureId && r.attrs.layer &&
      r.attrs.layer.includes("gebaeude_wohnungs_register")
    );

    if (gwrResult && gwrResult.attrs) {
      const lon = gwrResult.attrs.lon;
      const lat = gwrResult.attrs.lat;
      if (lon && lat) {
        return await fetchFootprintByCoords(lon, lat, egid);
      }
    }

    // Try first result with coordinates
    for (const r of data.results) {
      if (r.attrs && r.attrs.lon && r.attrs.lat) {
        return await fetchFootprintByCoords(r.attrs.lon, r.attrs.lat, egid);
      }
    }
  } catch (err) {
    console.warn("EGID lookup failed:", err);
  }
  return null;
}

async function fetchFootprintViaSwisstopo(lon, lat, egid) {
  // Use swisstopo identify on the AV building layer
  const identifyUrl = `${API.IDENTIFY}?geometry=${lon},${lat}&geometryType=esriGeometryPoint` +
    `&layers=all:ch.swisstopo.amtliches-gebaeudeverzeichnis&mapExtent=0,0,1,1&imageDisplay=1,1,96` +
    `&tolerance=50&returnGeometry=true&geometryFormat=geojson&sr=4326`;

  try {
    const resp = await fetchWithTimeout(identifyUrl, 10000);
    if (!resp.ok) return null;
    const data = await resp.json();

    if (!data.results || data.results.length === 0) return null;

    // Find best match
    const result = data.results[0];
    if (result.geometry) {
      let geom = result.geometry;
      if (geom.type === "MultiPolygon") {
        geom = { type: "Polygon", coordinates: geom.coordinates[0] };
      }
      return {
        geometry: geom,
        egid: result.attributes?.egid || result.properties?.egid || egid,
        area: result.attributes?.area || null,
      };
    }
  } catch (err) {
    console.warn("Swisstopo identify failed:", err);
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
    // Search for the EGID
    const searchUrl = `${API.SEARCH}?searchText=${encodeURIComponent(key)}&type=locations&origins=address`;
    const resp = await fetchWithTimeout(searchUrl, 10000);
    if (!resp.ok) return null;
    const data = await resp.json();

    // Find GWR feature
    const gwrResult = data.results?.find((r) =>
      r.attrs?.featureId && r.attrs?.layer?.includes("gebaeude_wohnungs_register")
    );

    if (!gwrResult) { gwrCache.set(key, null); return null; }

    // Fetch full GWR attributes
    const detailUrl = `${API.GWR_DETAIL}/${gwrResult.attrs.featureId}`;
    const detailResp = await fetchWithTimeout(detailUrl, 10000);
    if (!detailResp.ok) { gwrCache.set(key, null); return null; }
    const detail = await detailResp.json();

    const attrs = detail.feature?.attributes || {};
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
