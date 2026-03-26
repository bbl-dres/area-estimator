/**
 * Configuration — API endpoints, floor height lookup, map styles, constants
 */

/** Max rows in uploaded CSV */
export const MAX_ROWS = 5000;

/** Grid spacing for volume computation (meters) */
export const GRID_SPACING = 1;

/** Concurrency for parallel API requests */
export const CONCURRENCY = 5;

/** API endpoints */
export const API = {
  /** AV WFS — building footprints from official survey */
  WFS_AV: "https://geodienste.ch/db/av_0/deu",
  /** swisstopo MapServer find — exact attribute search (GWR EGID lookup) */
  GWR_FIND: "https://api3.geo.admin.ch/rest/services/ech/MapServer/find",
};

/** COG tile URL templates */
export const ALTI3D_URL = "https://data.geo.admin.ch/ch.swisstopo.swissalti3d/swissalti3d_{year}_{tile}/swissalti3d_{year}_{tile}_0.5_2056_5728.tif";
export const SURFACE3D_URL = "https://data.geo.admin.ch/ch.swisstopo.swisssurface3d-raster/swisssurface3d-raster_{year}_{tile}/swisssurface3d-raster_{year}_{tile}_0.5_2056_5728.tif";
export const YEARS = [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017];

/**
 * Floor height lookup table — ported from python/area.py
 * Format: code -> { gf: [min, max], uf: [min, max], schema, description }
 */
export const FLOOR_HEIGHT_LOOKUP = {
  // GKAT-based (category)
  "1010": { gf: [2.70, 3.30], uf: [2.70, 3.30], schema: "GKAT", desc: "Provisorische Unterkunft" },
  "1030": { gf: [2.70, 3.30], uf: [2.70, 3.30], schema: "GKAT", desc: "Wohngebäude mit Nebennutzung" },
  "1040": { gf: [3.30, 3.70], uf: [2.70, 3.70], schema: "GKAT", desc: "Teilweise bewohnt" },
  "1060": { gf: [3.30, 5.00], uf: [3.00, 5.00], schema: "GKAT", desc: "Nicht-Wohngebäude" },
  "1080": { gf: [3.00, 4.00], uf: [3.00, 4.00], schema: "GKAT", desc: "Spezialgebäude" },

  // GKLAS-based (class) — Residential
  "1110": { gf: [2.70, 3.30], uf: [2.70, 3.30], schema: "GKLAS", desc: "Einfamilienhaus" },
  "1121": { gf: [2.70, 3.30], uf: [2.70, 3.30], schema: "GKLAS", desc: "Zweifamilienhaus" },
  "1122": { gf: [2.70, 3.30], uf: [2.70, 3.30], schema: "GKLAS", desc: "Mehrfamilienhaus" },
  "1130": { gf: [2.70, 3.30], uf: [2.70, 3.30], schema: "GKLAS", desc: "Wohngebäude für Gemeinschaft" },

  // Hotels and Tourism
  "1211": { gf: [3.30, 3.70], uf: [3.00, 3.50], schema: "GKLAS", desc: "Hotel" },
  "1212": { gf: [3.00, 3.50], uf: [3.00, 3.50], schema: "GKLAS", desc: "Kurzaufenthalt" },

  // Commercial and Industrial
  "1220": { gf: [3.40, 4.20], uf: [3.40, 4.20], schema: "GKLAS", desc: "Bürogebäude" },
  "1230": { gf: [3.40, 5.00], uf: [3.40, 5.00], schema: "GKLAS", desc: "Gross- und Einzelhandel" },
  "1231": { gf: [3.30, 4.00], uf: [3.30, 4.00], schema: "GKLAS", desc: "Restaurant" },
  "1241": { gf: [4.00, 6.00], uf: [4.00, 6.00], schema: "GKLAS", desc: "Bahnhof/Terminal" },
  "1242": { gf: [2.80, 3.20], uf: [2.80, 3.20], schema: "GKLAS", desc: "Parkhaus" },
  "1251": { gf: [4.00, 7.00], uf: [4.00, 7.00], schema: "GKLAS", desc: "Industriegebäude" },
  "1252": { gf: [3.50, 6.00], uf: [3.50, 6.00], schema: "GKLAS", desc: "Tank/Silo/Lager" },
  "1261": { gf: [3.50, 5.00], uf: [3.50, 5.00], schema: "GKLAS", desc: "Kultur und Freizeit" },
  "1262": { gf: [3.50, 5.00], uf: [3.50, 5.00], schema: "GKLAS", desc: "Museum/Bibliothek" },
  "1263": { gf: [3.30, 4.00], uf: [3.30, 4.00], schema: "GKLAS", desc: "Schule/Universitat" },
  "1264": { gf: [3.30, 4.00], uf: [3.30, 4.00], schema: "GKLAS", desc: "Spital/Klinik" },
  "1265": { gf: [3.00, 6.00], uf: [3.00, 6.00], schema: "GKLAS", desc: "Sporthalle" },
  "1271": { gf: [3.50, 5.00], uf: [3.50, 5.00], schema: "GKLAS", desc: "Landwirtschaftsgebäude" },
  "1272": { gf: [3.00, 6.00], uf: [3.00, 6.00], schema: "GKLAS", desc: "Kirche" },
  "1273": { gf: [3.00, 4.00], uf: [3.00, 4.00], schema: "GKLAS", desc: "Denkmalgeschütztes Gebäude" },
  "1274": { gf: [3.00, 4.00], uf: [3.00, 4.00], schema: "GKLAS", desc: "Sonstiges Bauwerk" },
};

export const DEFAULT_FLOOR_HEIGHT = { gf: [2.70, 3.30], uf: [2.70, 3.30], schema: "DEFAULT", desc: "Unbekannt" };

/**
 * Look up floor height for a given GKAT/GKLAS combination.
 * Returns { floorHeight, schema, description }
 */
export function getFloorHeight(gkat, gklas) {
  // Try GKLAS first (more specific)
  const gklasStr = gklas != null ? String(Math.floor(Number(gklas))) : null;
  if (gklasStr && FLOOR_HEIGHT_LOOKUP[gklasStr] && FLOOR_HEIGHT_LOOKUP[gklasStr].schema === "GKLAS") {
    const e = FLOOR_HEIGHT_LOOKUP[gklasStr];
    const minH = (e.gf[0] + e.uf[0]) / 2;
    const maxH = (e.gf[1] + e.uf[1]) / 2;
    return { floorHeight: (minH + maxH) / 2, schema: "GKLAS", description: e.desc };
  }
  // Try GKAT
  const gkatStr = gkat != null ? String(Math.floor(Number(gkat))) : null;
  if (gkatStr && FLOOR_HEIGHT_LOOKUP[gkatStr] && FLOOR_HEIGHT_LOOKUP[gkatStr].schema === "GKAT") {
    const e = FLOOR_HEIGHT_LOOKUP[gkatStr];
    const minH = (e.gf[0] + e.uf[0]) / 2;
    const maxH = (e.gf[1] + e.uf[1]) / 2;
    return { floorHeight: (minH + maxH) / 2, schema: "GKAT", description: e.desc };
  }
  // Default
  const d = DEFAULT_FLOOR_HEIGHT;
  const minH = (d.gf[0] + d.uf[0]) / 2;
  const maxH = (d.gf[1] + d.uf[1]) / 2;
  return { floorHeight: (minH + maxH) / 2, schema: "DEFAULT", description: d.desc };
}

/**
 * Determine accuracy level based on building classification.
 */
export function determineAccuracy(gkat, gklas, hasVolume) {
  if (!hasVolume) return "low";
  if (gkat == null && gklas == null) return "low";
  const catStr = gkat != null ? String(Math.floor(Number(gkat))) : "";
  const clsStr = gklas != null ? String(Math.floor(Number(gklas))) : "";
  // Residential — best accuracy
  if (catStr === "1020" || clsStr.startsWith("11")) return "high";
  // Commercial/office
  if (["1220", "1230", "1231", "1263", "1264"].includes(clsStr)) return "medium";
  // Industrial and special
  if (["1251", "1252", "1265", "1272"].includes(clsStr) || ["1060", "1080"].includes(catStr)) return "low";
  return "medium";
}

/** Status constants */
export const STATUS = {
  SUCCESS: "success",
  NO_FOOTPRINT: "no_footprint",
  NO_HEIGHT_DATA: "no_height_data",
  NO_GRID_POINTS: "no_grid_points",
  ERROR: "error",
};

/** Basemap styles */
export const MAP_STYLES = {
  positron: {
    name: "Hell",
    url: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    thumbnail: "https://basemaps.cartocdn.com/light_all/8/134/91.png",
  },
  voyager: {
    name: "Standard",
    url: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
    thumbnail: "https://basemaps.cartocdn.com/rastertiles/voyager/8/134/91.png",
  },
  swissimage: {
    name: "Luftbild",
    url: {
      version: 8,
      glyphs: "https://tiles.basemaps.cartocdn.com/fonts/{fontstack}/{range}.pbf",
      sources: {
        swissimage: {
          type: "raster",
          tiles: ["https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg"],
          tileSize: 256,
          maxzoom: 20,
          attribution: '&copy; <a href="https://www.swisstopo.admin.ch">swisstopo</a>',
        },
      },
      layers: [{ id: "swissimage", type: "raster", source: "swissimage" }],
    },
    thumbnail: "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/8/134/91.jpeg",
  },
  "dark-matter": {
    name: "Dunkel",
    url: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    thumbnail: "https://basemaps.cartocdn.com/dark_all/8/134/91.png",
  },
};

/** Default map center and zoom (Switzerland) */
export const MAP_DEFAULT = { center: [8.2275, 46.8182], zoom: 7 };

/** Shared HTML escape utility */
const _escDiv = document.createElement("div");
export function esc(s) {
  _escDiv.textContent = s || "";
  return _escDiv.innerHTML;
}

/** Shared number formatter */
export function fmtNum(n, decimals = 1) {
  if (n == null || isNaN(n)) return "\u2013";
  return Number(n).toLocaleString("de-CH", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** Dynamic script loader */
export function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}
