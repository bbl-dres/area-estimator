/**
 * Export — CSV, XLSX, GeoJSON
 */
import { loadScript } from "./config.js";

const CSV_COLUMNS = [
  "input_id", "input_egid", "input_lon", "input_lat",
  "av_egid", "area_official_m2",
  "volume_m3", "area_footprint_m2",
  "elevation_base_min", "elevation_base_mean", "elevation_base_max",
  "elevation_roof_min", "elevation_roof_mean", "elevation_roof_max",
  "height_min", "height_max", "height_mean", "height_minimal",
  "grid_points",
  "gkat", "gklas", "gbauj", "gastw",
  "floor_height_used", "floors_estimated", "area_floor_total_m2",
  "building_type", "area_accuracy",
  "status",
];

export function downloadCSV(buildings) {
  const header = CSV_COLUMNS.join(";");
  const rows = buildings.map((b) =>
    CSV_COLUMNS.map((col) => {
      const v = b[col];
      if (v == null) return "";
      const s = String(v);
      return s.includes(";") || s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(";")
  );
  const csv = [header, ...rows].join("\n");
  downloadBlob(csv, "gebaeudevolumen.csv", "text/csv;charset=utf-8");
}

export async function downloadXLSX(buildings) {
  if (!window.XLSX) {
    await loadScript("https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js");
  }
  const data = buildings.map((b) => {
    const row = {};
    CSV_COLUMNS.forEach((col) => { row[col] = b[col] ?? ""; });
    return row;
  });
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.json_to_sheet(data, { header: CSV_COLUMNS });
  XLSX.utils.book_append_sheet(wb, ws, "Gebaeude");
  XLSX.writeFile(wb, "gebaeudevolumen.xlsx");
}

export function downloadGeoJSON(buildings) {
  const features = buildings
    .filter((b) => b.geometry)
    .map((b) => {
      const props = { ...b };
      delete props.geometry;
      return { type: "Feature", geometry: b.geometry, properties: props };
    });
  const geojson = { type: "FeatureCollection", features };
  downloadBlob(JSON.stringify(geojson, null, 2), "gebaeudevolumen.geojson", "application/geo+json");
}

function downloadBlob(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
