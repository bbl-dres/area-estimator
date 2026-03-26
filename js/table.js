/**
 * Results table — sortable, paginated, with building selection.
 */
import { esc, fmtNum, STATUS } from "./config.js";

let container = null;
let callbacks = {};
let allData = [];
let sortKey = "input_id";
let sortAsc = true;
let page = 0;
let pageSize = 50;

export function initTable(el, cbs) {
  container = el;
  callbacks = cbs || {};
}

export function populateTable(buildings) {
  allData = buildings || [];
  page = 0;
  render();
}

export function highlightRow(index) {
  if (!container) return;
  container.querySelectorAll("tr.row-active").forEach((r) => r.classList.remove("row-active"));
  const row = container.querySelector(`tr[data-index="${index}"]`);
  if (row) {
    row.classList.add("row-active");
    row.scrollIntoView({ block: "nearest" });
  }
}

const COLUMNS = [
  { key: "input_id", label: "ID", cls: "" },
  { key: "av_egid", label: "EGID", cls: "" },
  { key: "status", label: "Status", cls: "" },
  { key: "volume_m3", label: "Volumen (m\u00B3)", cls: "num" },
  { key: "area_footprint_m2", label: "Grundfläche (m\u00B2)", cls: "num" },
  { key: "height_mean", label: "Höhe Mittel (m)", cls: "num" },
  { key: "height_max", label: "Höhe Max (m)", cls: "num" },
  { key: "height_minimal", label: "Höhe Minimal (m)", cls: "num" },
  { key: "floors_estimated", label: "Geschosse", cls: "num" },
  { key: "area_floor_total_m2", label: "Geschossfläche (m\u00B2)", cls: "num" },
  { key: "building_type", label: "Typ", cls: "" },
  { key: "area_accuracy", label: "Genauigkeit", cls: "" },
];

function render() {
  if (!container) return;

  // Sort
  const sorted = [...allData].sort((a, b) => {
    let va = a[sortKey], vb = b[sortKey];
    if (va == null) va = "";
    if (vb == null) vb = "";
    if (typeof va === "number" && typeof vb === "number") {
      return sortAsc ? va - vb : vb - va;
    }
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  });

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  if (page >= totalPages) page = totalPages - 1;
  const start = page * pageSize;
  const pageData = sorted.slice(start, start + pageSize);

  const statusLabel = (s) => {
    if (s === STATUS.SUCCESS) return '<span style="color:var(--color-good-text)">OK</span>';
    if (s === STATUS.NO_FOOTPRINT) return '<span style="color:var(--color-poor-text)">Kein Grundriss</span>';
    if (s === STATUS.NO_HEIGHT_DATA) return '<span style="color:var(--color-warn-text)">Keine Höhe</span>';
    if (s && s.startsWith("error:")) return `<span style="color:var(--color-poor-text)">Fehler</span>`;
    return s || "\u2013";
  };

  const fmtCell = (val, cls) => {
    if (val == null || val === "") return "\u2013";
    if (cls === "num") return fmtNum(val, 1);
    return esc(String(val));
  };

  // Build HTML
  container.innerHTML = `
    <div class="tbl-resize-handle" id="tbl-resize-handle"></div>
    <div class="list-table-container">
      <div class="toolbar">
        <div class="toolbar-search">
          <span class="material-symbols-outlined">search</span>
          <input type="text" id="tbl-search" placeholder="Suche in Tabelle...">
        </div>
        <div class="toolbar-actions">
          <span style="font-size:var(--text-2xs);color:var(--gray-500)">${sorted.length} Gebäude</span>
        </div>
      </div>
      <div class="list-table-wrapper">
        <table class="list-table">
          <thead>
            <tr>
              ${COLUMNS.map((c) => `<th data-sort="${c.key}" class="${sortKey === c.key ? "sort-active" : ""}">${esc(c.label)} <span class="sort-icon">${sortKey === c.key ? (sortAsc ? "\u25B2" : "\u25BC") : ""}</span></th>`).join("")}
            </tr>
          </thead>
          <tbody>
            ${pageData.length === 0 ? `<tr><td colspan="${COLUMNS.length}" class="empty-cell"><span class="material-symbols-outlined">search_off</span>Keine Ergebnisse</td></tr>` :
              pageData.map((row) => {
                const isError = row.status !== STATUS.SUCCESS;
                return `<tr data-index="${allData.indexOf(row)}" class="${isError ? "row-error" : ""}">
                  ${COLUMNS.map((c) => {
                    if (c.key === "status") return `<td>${statusLabel(row.status)}</td>`;
                    return `<td class="${c.cls}">${fmtCell(row[c.key], c.cls)}</td>`;
                  }).join("")}
                </tr>`;
              }).join("")}
          </tbody>
        </table>
      </div>
      <div class="pagination-footer">
        <div class="pagination-info">${start + 1}\u2013${Math.min(start + pageSize, sorted.length)} von ${sorted.length}</div>
        <div class="pagination-nav">
          <button class="pagination-btn" id="pg-prev" ${page === 0 ? "disabled" : ""}><span class="material-symbols-outlined">chevron_left</span></button>
          <span class="pagination-page-info">${page + 1} / ${totalPages}</span>
          <button class="pagination-btn" id="pg-next" ${page >= totalPages - 1 ? "disabled" : ""}><span class="material-symbols-outlined">chevron_right</span></button>
        </div>
        <div class="pagination-rows">
          <span>Zeilen:</span>
          <select class="pg-size" id="pg-size">
            ${[25, 50, 100].map((n) => `<option value="${n}" ${n === pageSize ? "selected" : ""}>${n}</option>`).join("")}
          </select>
        </div>
      </div>
    </div>
  `;

  // Event: sort
  container.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) { sortAsc = !sortAsc; } else { sortKey = key; sortAsc = true; }
      render();
    });
  });

  // Event: row click
  container.querySelectorAll("tbody tr[data-index]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const idx = parseInt(tr.dataset.index);
      container.querySelectorAll("tr.row-active").forEach((r) => r.classList.remove("row-active"));
      tr.classList.add("row-active");
      if (callbacks.onBuildingSelect) callbacks.onBuildingSelect(idx);
    });
  });

  // Event: pagination
  container.querySelector("#pg-prev")?.addEventListener("click", () => { if (page > 0) { page--; render(); } });
  container.querySelector("#pg-next")?.addEventListener("click", () => { page++; render(); });
  container.querySelector("#pg-size")?.addEventListener("change", (e) => { pageSize = parseInt(e.target.value); page = 0; render(); });

  // Event: search
  container.querySelector("#tbl-search")?.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    if (!q) { allData = callbacks._allData || allData; page = 0; render(); return; }
    if (!callbacks._allData) callbacks._allData = allData;
    allData = callbacks._allData.filter((r) =>
      Object.values(r).some((v) => v != null && String(v).toLowerCase().includes(q))
    );
    page = 0;
    render();
  });

  // Resize handle
  initResizeHandle();
}

function initResizeHandle() {
  const handle = document.getElementById("tbl-resize-handle");
  const panel = document.getElementById("results-table-container");
  if (!handle || !panel) return;

  let startY, startH;
  handle.addEventListener("mousedown", (e) => {
    startY = e.clientY;
    startH = panel.offsetHeight;
    handle.classList.add("dragging");
    const onMove = (ev) => {
      const delta = startY - ev.clientY;
      panel.style.height = Math.max(100, startH + delta) + "px";
    };
    const onUp = () => {
      handle.classList.remove("dragging");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      // Resize map after table resize
      const { resizeMap } = import("./map.js");
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}
