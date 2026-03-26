/**
 * Map module — MapLibre GL with 3D building extrusions, basemap switching,
 * accordion menu, and building popups.
 */
import { MAP_STYLES, MAP_DEFAULT, GRID_SPACING, esc, fmtNum } from "./config.js";
import { fromLV95 } from "./elevation.js";

let map = null;
let buildingsGeoJSON = null;
let gridCellsGeoJSON = null;
let rawGridCells = null;
let callbacks = {};
let summaryToggleCb = null;

/** Convert raw LV95 grid cells to WGS84 GeoJSON on first use */
function ensureGridCellsConverted() {
  if (gridCellsGeoJSON || !rawGridCells || rawGridCells.length === 0) return;
  const half = GRID_SPACING / 2;
  const features = rawGridCells.map((c) => {
    const sw = fromLV95(c.x - half, c.y - half);
    const se = fromLV95(c.x + half, c.y - half);
    const ne = fromLV95(c.x + half, c.y + half);
    const nw = fromLV95(c.x - half, c.y + half);
    return {
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [[sw, se, ne, nw, sw]] },
      properties: { h: Math.round(c.h * 10) / 10 },
    };
  });
  gridCellsGeoJSON = { type: "FeatureCollection", features };
  if (map && map.getSource("grid-cells")) {
    map.getSource("grid-cells").setData(gridCellsGeoJSON);
  }
}

export function onSummaryToggle(cb) { summaryToggleCb = cb; }
export function setSummaryToggleVisible(visible) {
  const btn = document.getElementById("summary-toggle-btn");
  if (btn) btn.hidden = !visible;
}

export async function initMap(containerId, cbs) {
  callbacks = cbs || {};

  map = new maplibregl.Map({
    container: containerId,
    style: MAP_STYLES.positron.url,
    center: MAP_DEFAULT.center,
    zoom: MAP_DEFAULT.zoom,
    maxZoom: 19,
    attributionControl: true,
  });

  map.addControl(new maplibregl.NavigationControl(), "top-right");
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 200 }), "bottom-left");

  await new Promise((resolve) => map.on("load", resolve));

  // Basemap switcher
  initBasemapSwitcher();

  // Accordion menu
  initAccordion();

  // Footer coordinates
  map.on("mousemove", (e) => {
    const el = document.getElementById("footer-coords");
    if (el) el.textContent = `${e.lngLat.lat.toFixed(5)}, ${e.lngLat.lng.toFixed(5)}`;
  });

  // Style switcher visible
  document.getElementById("style-switcher")?.classList.add("visible");
}

export function plotResults(data) {
  if (!map || !data || !data.buildings) return;

  // Build GeoJSON from results
  const features = data.buildings
    .filter((b) => b.geometry)
    .map((b, i) => ({
      type: "Feature",
      geometry: b.geometry,
      properties: {
        _index: i,
        id: b.input_id,
        egid: b.av_egid || b.input_egid,
        volume: b.volume_m3,
        height: b.height_mean,
        height_max: b.height_max,
        floors: b.floors_estimated,
        area_floor: b.area_floor_total_m2,
        area_footprint: b.area_footprint_m2,
        status: b.status,
        building_type: b.building_type,
      },
    }));

  buildingsGeoJSON = { type: "FeatureCollection", features };

  // Add source
  if (map.getSource("buildings")) {
    map.getSource("buildings").setData(buildingsGeoJSON);
  } else {
    map.addSource("buildings", { type: "geojson", data: buildingsGeoJSON });
  }

  // 3D fill-extrusion layer
  if (!map.getLayer("buildings-3d")) {
    map.addLayer({
      id: "buildings-3d",
      type: "fill-extrusion",
      source: "buildings",
      paint: {
        "fill-extrusion-color": [
          "case",
          ["==", ["get", "status"], "success"],
          ["interpolate", ["linear"], ["coalesce", ["get", "height"], 0],
            0, "#3498db",
            10, "#2ecc71",
            20, "#f39c12",
            40, "#e74c3c",
          ],
          "#95a5a6",
        ],
        "fill-extrusion-height": ["coalesce", ["get", "height_max"], 3],
        "fill-extrusion-base": 0,
        "fill-extrusion-opacity": 0.8,
      },
    });
  }

  // 2D outline
  if (!map.getLayer("buildings-outline")) {
    map.addLayer({
      id: "buildings-outline",
      type: "line",
      source: "buildings",
      paint: {
        "line-color": [
          "case",
          ["==", ["get", "status"], "success"], "#1a365d",
          "#ef4444",
        ],
        "line-width": 1.5,
      },
    });
  }

  // Grid cells — store raw LV95 data, convert lazily on first toggle
  rawGridCells = data.buildings
    .filter((b) => b.grid_cells)
    .flatMap((b) => b.grid_cells);
  gridCellsGeoJSON = null;

  const emptyGeoJSON = { type: "FeatureCollection", features: [] };
  if (map.getSource("grid-cells")) {
    map.getSource("grid-cells").setData(emptyGeoJSON);
  } else {
    map.addSource("grid-cells", { type: "geojson", data: emptyGeoJSON });
  }

  if (!map.getLayer("grid-cells-3d")) {
    map.addLayer({
      id: "grid-cells-3d",
      type: "fill-extrusion",
      source: "grid-cells",
      layout: { visibility: "none" },
      paint: {
        "fill-extrusion-color": ["interpolate", ["linear"], ["get", "h"],
          0, "#3498db",
          10, "#2ecc71",
          20, "#f39c12",
          40, "#e74c3c",
        ],
        "fill-extrusion-height": ["get", "h"],
        "fill-extrusion-base": 0,
        "fill-extrusion-opacity": 0.85,
      },
    });
  }

  // Labels
  if (!map.getLayer("buildings-labels")) {
    map.addLayer({
      id: "buildings-labels",
      type: "symbol",
      source: "buildings",
      layout: {
        "text-field": ["get", "id"],
        "text-size": 11,
        "text-anchor": "center",
        "text-allow-overlap": false,
      },
      paint: {
        "text-color": "#1f2937",
        "text-halo-color": "#fff",
        "text-halo-width": 1.5,
      },
      minzoom: 15,
    });
  }

  // Click handler
  map.on("click", "buildings-3d", (e) => {
    if (!e.features.length) return;
    const f = e.features[0];
    const p = f.properties;

    const html = `
      <div class="map-popup">
        <div class="popup-layer">GEBÄUDE</div>
        <div class="popup-title">${esc(p.id)}</div>
        <div class="popup-sub">EGID: ${esc(p.egid || "\u2013")}</div>
        <table class="popup-table">
          <tr><td>Volumen</td><td>${p.volume != null ? fmtNum(p.volume, 0) + " m\u00B3" : "\u2013"}</td></tr>
          <tr><td>Höhe (Mittel)</td><td>${p.height != null ? fmtNum(p.height, 1) + " m" : "\u2013"}</td></tr>
          <tr><td>Höhe (Max)</td><td>${p.height_max != null ? fmtNum(p.height_max, 1) + " m" : "\u2013"}</td></tr>
          <tr><td>Grundfläche</td><td>${p.area_footprint != null ? fmtNum(p.area_footprint, 1) + " m\u00B2" : "\u2013"}</td></tr>
          <tr><td>Geschosse</td><td>${p.floors || "\u2013"}</td></tr>
          <tr><td>Geschossflache</td><td>${p.area_floor != null ? fmtNum(p.area_floor, 0) + " m\u00B2" : "\u2013"}</td></tr>
          <tr><td>Typ</td><td>${esc(p.building_type || "\u2013")}</td></tr>
        </table>
      </div>`;

    new maplibregl.Popup({ maxWidth: "300px" })
      .setLngLat(e.lngLat)
      .setHTML(html)
      .addTo(map);

    if (callbacks.onBuildingSelect) callbacks.onBuildingSelect(p._index);
  });

  map.on("mouseenter", "buildings-3d", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "buildings-3d", () => { map.getCanvas().style.cursor = ""; });

  // Layer toggles
  document.getElementById("layer-toggle-footprints")?.addEventListener("change", (e) => {
    if (map.getLayer("buildings-outline")) {
      map.setLayoutProperty("buildings-outline", "visibility", e.target.checked ? "visible" : "none");
    }
  });
  document.getElementById("layer-toggle-buildings")?.addEventListener("change", (e) => {
    if (map.getLayer("buildings-3d")) {
      map.setLayoutProperty("buildings-3d", "visibility", e.target.checked ? "visible" : "none");
    }
  });
  document.getElementById("layer-toggle-grid")?.addEventListener("change", (e) => {
    if (e.target.checked) {
      ensureGridCellsConverted();
    }
    if (map.getLayer("grid-cells-3d")) {
      map.setLayoutProperty("grid-cells-3d", "visibility", e.target.checked ? "visible" : "none");
    }
  });
  document.getElementById("layer-toggle-labels")?.addEventListener("change", (e) => {
    if (map.getLayer("buildings-labels")) {
      map.setLayoutProperty("buildings-labels", "visibility", e.target.checked ? "visible" : "none");
    }
  });

  // AV cadastral overlay
  document.getElementById("layer-toggle-av")?.addEventListener("change", (e) => {
    if (e.target.checked) {
      if (!map.getSource("av-cadastral")) {
        map.addSource("av-cadastral", {
          type: "raster",
          tiles: ["https://wms.geo.admin.ch/?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=ch.kantone.cadastralwebmap-farbe&FORMAT=image/png&TRANSPARENT=true&CRS=EPSG:3857&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256"],
          tileSize: 256,
        });
      }
      if (!map.getLayer("av-cadastral-layer")) {
        map.addLayer({ id: "av-cadastral-layer", type: "raster", source: "av-cadastral", paint: { "raster-opacity": 0.5 } }, "buildings-outline");
      }
    } else {
      if (map.getLayer("av-cadastral-layer")) map.removeLayer("av-cadastral-layer");
    }
  });

  // Fit bounds
  if (features.length > 0) {
    const bounds = new maplibregl.LngLatBounds();
    for (const f of features) {
      const coords = f.geometry.coordinates[0];
      for (const c of coords) bounds.extend(c);
    }
    map.fitBounds(bounds, { padding: 60, maxZoom: 17 });
  }
}

export function highlightBuilding(index) {
  // Could add highlight effect; for now just fly to it
  if (!buildingsGeoJSON || !map) return;
  const f = buildingsGeoJSON.features.find((f) => f.properties._index === index);
  if (!f) return;
  const center = turf.centroid(f);
  map.flyTo({ center: center.geometry.coordinates, zoom: 17 });
}

export function resizeMap() {
  if (map) map.resize();
}

// =============================================
// Basemap switcher
// =============================================
function initBasemapSwitcher() {
  const btn = document.getElementById("style-switcher-btn");
  const panel = document.getElementById("style-panel");
  if (!btn || !panel) return;

  btn.addEventListener("click", () => panel.classList.toggle("show"));

  panel.querySelectorAll(".style-option").forEach((opt) => {
    opt.addEventListener("click", () => {
      const style = opt.dataset.style;
      const cfg = MAP_STYLES[style];
      if (!cfg) return;

      // Remember current state
      const savedData = buildingsGeoJSON;

      map.setStyle(cfg.url);
      map.once("style.load", () => {
        // Re-add data after style change, respecting toggle states
        if (savedData) {
          const visFootprints = document.getElementById("layer-toggle-footprints")?.checked ? "visible" : "none";
          const visBuildings = document.getElementById("layer-toggle-buildings")?.checked ? "visible" : "none";
          const visLabels = document.getElementById("layer-toggle-labels")?.checked ? "visible" : "none";
          const visGrid = document.getElementById("layer-toggle-grid")?.checked ? "visible" : "none";

          map.addSource("buildings", { type: "geojson", data: savedData });
          map.addLayer({
            id: "buildings-3d", type: "fill-extrusion", source: "buildings",
            layout: { visibility: visBuildings },
            paint: {
              "fill-extrusion-color": ["case", ["==", ["get", "status"], "success"],
                ["interpolate", ["linear"], ["coalesce", ["get", "height"], 0], 0, "#3498db", 10, "#2ecc71", 20, "#f39c12", 40, "#e74c3c"],
                "#95a5a6"],
              "fill-extrusion-height": ["coalesce", ["get", "height_max"], 3],
              "fill-extrusion-base": 0,
              "fill-extrusion-opacity": 0.8,
            },
          });
          map.addLayer({
            id: "buildings-outline", type: "line", source: "buildings",
            layout: { visibility: visFootprints },
            paint: { "line-color": ["case", ["==", ["get", "status"], "success"], "#1a365d", "#ef4444"], "line-width": 1.5 },
          });
          map.addLayer({
            id: "buildings-labels", type: "symbol", source: "buildings",
            layout: { visibility: visLabels, "text-field": ["get", "id"], "text-size": 11, "text-anchor": "center", "text-allow-overlap": false },
            paint: { "text-color": "#1f2937", "text-halo-color": "#fff", "text-halo-width": 1.5 },
            minzoom: 15,
          });
          const gridData = gridCellsGeoJSON || { type: "FeatureCollection", features: [] };
          map.addSource("grid-cells", { type: "geojson", data: gridData });
          map.addLayer({
            id: "grid-cells-3d", type: "fill-extrusion", source: "grid-cells",
            layout: { visibility: visGrid },
            paint: {
              "fill-extrusion-color": ["interpolate", ["linear"], ["get", "h"], 0, "#3498db", 10, "#2ecc71", 20, "#f39c12", 40, "#e74c3c"],
              "fill-extrusion-height": ["get", "h"],
              "fill-extrusion-base": 0,
              "fill-extrusion-opacity": 0.85,
            },
          });
        }
      });

      // Update thumbnails
      document.getElementById("current-style-thumb").src = cfg.thumbnail;
      panel.querySelectorAll(".style-option").forEach((o) => o.classList.remove("active"));
      opt.classList.add("active");
      panel.classList.remove("show");
    });
  });

  // Close on outside click
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".style-switcher")) panel.classList.remove("show");
  });
}

// =============================================
// Accordion menu
// =============================================
function initAccordion() {
  const panel = document.getElementById("accordion-panel");
  const toggle = document.getElementById("menu-toggle");
  if (!panel || !toggle) return;

  toggle.addEventListener("click", () => {
    const collapsed = panel.classList.toggle("collapsed");
    toggle.querySelector(".material-symbols-outlined").textContent = collapsed ? "expand_more" : "expand_less";
    const textEl = document.getElementById("menu-toggle-text");
    if (textEl) textEl.textContent = collapsed ? "Menu offnen" : "Menu schliessen";
  });

  panel.querySelectorAll(".accordion-header").forEach((header) => {
    header.addEventListener("click", () => {
      const isActive = header.classList.contains("active");
      // Close all
      panel.querySelectorAll(".accordion-header").forEach((h) => {
        h.classList.remove("active");
        h.setAttribute("aria-expanded", "false");
        h.nextElementSibling?.classList.remove("show");
      });
      // Toggle clicked
      if (!isActive) {
        header.classList.add("active");
        header.setAttribute("aria-expanded", "true");
        header.nextElementSibling?.classList.add("show");
      }
    });
  });
}
