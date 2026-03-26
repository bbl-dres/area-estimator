/**
 * App state machine: upload → processing → results
 */
import { initUpload } from "./upload.js";
import { processRows, cancelProcessing } from "./processor.js";
import { initMap, plotResults, highlightBuilding, resizeMap, onSummaryToggle, setSummaryToggleVisible } from "./map.js";
import { initTable, populateTable, highlightRow } from "./table.js";
import { downloadCSV, downloadXLSX, downloadGeoJSON } from "./export.js";
import { esc, fmtNum, STATUS } from "./config.js";

let processedResults = null;
let currentFilename = "";

document.addEventListener("DOMContentLoaded", () => {
  initUpload(onStartProcessing);

  // Cancel
  document.getElementById("btn-cancel").addEventListener("click", () => cancelProcessing());

  // Table toggle
  document.getElementById("tbl-toggle").addEventListener("click", () => {
    const panel = document.getElementById("results-table-container");
    const btn = document.getElementById("tbl-toggle");
    const collapsed = !panel.classList.contains("collapsed");
    panel.style.height = "";
    panel.classList.toggle("collapsed", collapsed);
    btn.classList.toggle("collapsed", collapsed);
    setTimeout(() => resizeMap(), 280);
  });

  // Reset
  function resetToUpload() {
    cancelProcessing();
    processedResults = null;
    currentFilename = "";
    showState("upload");
    document.getElementById("btn-new").hidden = true;
    document.getElementById("btn-download").hidden = true;
    document.getElementById("search-wrapper").hidden = true;
    document.getElementById("file-input").value = "";
    const err = document.getElementById("upload-error");
    if (err) { err.hidden = true; err.textContent = ""; }
  }

  document.getElementById("btn-new").addEventListener("click", resetToUpload);
  document.querySelector(".header-left").addEventListener("click", resetToUpload);

  // Summary panel
  document.getElementById("sp-close").addEventListener("click", () => {
    document.getElementById("summary-panel").classList.add("collapsed");
    setTimeout(() => resizeMap(), 280);
  });

  // Download modal
  const dlOverlay = document.getElementById("download-overlay");
  const dlModal = dlOverlay.querySelector(".dl-modal");

  function openDownloadModal() { dlOverlay.hidden = false; }
  function closeDownloadModal() { dlOverlay.hidden = true; }

  dlOverlay.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDownloadModal(); });
  document.getElementById("btn-download").addEventListener("click", openDownloadModal);
  document.getElementById("dl-close").addEventListener("click", closeDownloadModal);
  dlOverlay.addEventListener("click", (e) => { if (e.target === dlOverlay) closeDownloadModal(); });

  document.getElementById("dl-csv").addEventListener("click", () => {
    if (processedResults) downloadCSV(processedResults.buildings);
    closeDownloadModal();
  });
  document.getElementById("dl-xlsx").addEventListener("click", async () => {
    if (processedResults) await downloadXLSX(processedResults.buildings);
    closeDownloadModal();
  });
  document.getElementById("dl-geojson").addEventListener("click", () => {
    if (processedResults) downloadGeoJSON(processedResults.buildings);
    closeDownloadModal();
  });
});

function showState(state) {
  document.querySelectorAll(".app-state").forEach((el) => {
    el.hidden = el.id !== `state-${state}`;
  });
  if (state === "results") setTimeout(() => resizeMap(), 100);
}

async function onStartProcessing(parsedData) {
  showState("processing");
  currentFilename = parsedData.filename || "";
  const startTime = Date.now();

  try {
    processedResults = await processRows(parsedData.rows, (progress) => {
      updateProgress(progress, startTime);
    });

    if (!processedResults || !processedResults.buildings.length) {
      showState("upload");
      const err = document.getElementById("upload-error");
      if (err) { err.textContent = "Keine Ergebnisse. Prufen Sie die Eingabedatei."; err.hidden = false; }
      return;
    }

    progressEls.barFill.style.width = "100%";
    progressEls.bar.setAttribute("aria-valuenow", "100");

    showResults();
  } catch (err) {
    console.error("Processing failed:", err);
    showState("upload");
    const errEl = document.getElementById("upload-error");
    if (errEl) { errEl.textContent = `Verarbeitung fehlgeschlagen: ${err.message}`; errEl.hidden = false; }
  }
}

// Cached DOM refs
const progressEls = {};

function cacheProgressEls() {
  progressEls.barFill = document.getElementById("progress-bar-fill");
  progressEls.bar = document.querySelector(".progress-bar");
  progressEls.text = document.getElementById("progress-text");
  progressEls.eta = document.getElementById("progress-eta");
  progressEls.stats = document.getElementById("progress-stats");
}

function updateProgress(progress, startTime) {
  if (!progressEls.barFill) cacheProgressEls();

  const { processed, total, succeeded, failed } = progress;
  const pct = total > 0 ? ((processed / total) * 100).toFixed(1) : 0;

  progressEls.barFill.style.width = `${pct}%`;
  progressEls.bar.setAttribute("aria-valuenow", Math.round(pct));
  progressEls.text.textContent = `Gebaude ${processed} / ${total} (${pct}%)`;

  const elapsed = Date.now() - startTime;
  const perItem = processed > 0 ? elapsed / processed : 0;
  const remaining = perItem * (total - processed);
  const etaSeconds = Math.ceil(remaining / 1000);
  const etaMin = Math.floor(etaSeconds / 60);
  const etaSec = etaSeconds % 60;
  progressEls.eta.textContent = processed < total
    ? `Geschatzt: ${etaMin}min ${etaSec}s verbleibend`
    : "Abschluss...";
  progressEls.stats.textContent = `Erfolgreich: ${succeeded} | Fehlgeschlagen: ${failed}`;
}

function showResults() {
  showState("results");
  updateSummaryPanel();

  const isMobile = window.innerWidth <= 767;

  if (isMobile) {
    document.getElementById("summary-panel").classList.add("collapsed");
  } else {
    document.getElementById("summary-panel").classList.remove("collapsed");
  }

  initTable(document.getElementById("results-table-container"), {
    onBuildingSelect: (index) => highlightBuilding(index),
  });
  populateTable(processedResults.buildings);

  if (isMobile) {
    const tablePanel = document.getElementById("results-table-container");
    const tblBtn = document.getElementById("tbl-toggle");
    tablePanel.classList.add("collapsed");
    tblBtn.classList.add("collapsed");
  }

  document.getElementById("btn-download").hidden = false;
  document.getElementById("btn-new").hidden = false;

  requestAnimationFrame(async () => {
    try {
      await initMap("results-map", {
        onBuildingSelect: (index) => highlightRow(index),
      });
      plotResults(processedResults);
    } catch (err) {
      console.error("Map initialization failed:", err);
    }
  });
}

function updateSummaryPanel() {
  if (!processedResults) return;
  const buildings = processedResults.buildings;
  const total = buildings.length;
  const success = buildings.filter((b) => b.status === STATUS.SUCCESS).length;
  const failed = total - success;

  // Compute aggregates
  let totalVolume = 0, totalFootprint = 0, totalFloorArea = 0;
  let heightSum = 0, heightCount = 0;
  for (const b of buildings) {
    if (b.status === STATUS.SUCCESS) {
      totalVolume += b.volume_m3 || 0;
      totalFootprint += b.area_footprint_m2 || 0;
      totalFloorArea += b.area_floor_total_m2 || 0;
      if (b.height_mean != null) { heightSum += b.height_mean; heightCount++; }
    }
  }
  const avgHeight = heightCount > 0 ? heightSum / heightCount : 0;

  // Accuracy distribution
  const accHigh = buildings.filter((b) => b.area_accuracy === "high").length;
  const accMed = buildings.filter((b) => b.area_accuracy === "medium").length;
  const accLow = buildings.filter((b) => b.area_accuracy === "low").length;

  const now = new Date();

  document.getElementById("sp-body").innerHTML = `
    <!-- Ubersicht -->
    <div class="sp-collapse-section open" data-sp-section="overview">
      <div class="sp-collapse-header">
        <span class="material-symbols-outlined sp-collapse-arrow">expand_more</span>
        <span>Gebaude-Zuordnung</span>
      </div>
      <div class="sp-collapse-content">
        <div class="sp-meta-row">
          <span class="sp-meta-filename">${esc(currentFilename)}</span>
          <span class="sp-meta-sep">&middot;</span>
          <span>${now.toLocaleDateString("de-CH", { dateStyle: "medium" })}, ${now.toLocaleTimeString("de-CH", { timeStyle: "short" })}</span>
        </div>
        <div class="sp-kpi-grid" style="margin-top:var(--space-3)">
          <div class="sp-kpi"><div class="sp-kpi-value sp-color-good">${success}</div><div class="sp-kpi-label">Erfolgreich</div></div>
          <div class="sp-kpi"><div class="sp-kpi-value sp-color-poor">${failed}</div><div class="sp-kpi-label">Fehlgeschlagen</div></div>
        </div>
      </div>
    </div>

    <!-- Volumen -->
    <div class="sp-collapse-section open" data-sp-section="volume">
      <div class="sp-collapse-header">
        <span class="material-symbols-outlined sp-collapse-arrow">expand_more</span>
        <span>Volumen und Hohen</span>
      </div>
      <div class="sp-collapse-content">
        <div class="sp-kpi-grid">
          <div class="sp-kpi"><div class="sp-kpi-value">${fmtNum(totalVolume, 0)}</div><div class="sp-kpi-label">Volumen (m\u00B3)</div></div>
          <div class="sp-kpi"><div class="sp-kpi-value">${fmtNum(totalFootprint, 0)}</div><div class="sp-kpi-label">Grundflache (m\u00B2)</div></div>
          <div class="sp-kpi"><div class="sp-kpi-value">${fmtNum(avgHeight, 1)}</div><div class="sp-kpi-label">Hohe \u00D8 (m)</div></div>
          <div class="sp-kpi"><div class="sp-kpi-value">${fmtNum(totalFloorArea, 0)}</div><div class="sp-kpi-label">Geschossflache (m\u00B2)</div></div>
        </div>
      </div>
    </div>

    <!-- Genauigkeit -->
    <div class="sp-collapse-section open" data-sp-section="accuracy">
      <div class="sp-collapse-header">
        <span class="material-symbols-outlined sp-collapse-arrow">expand_more</span>
        <span>Genauigkeit</span>
      </div>
      <div class="sp-collapse-content">
        <div class="sp-legend-row">
          <span class="sp-dist-dot" style="background:var(--color-good)"></span>
          <span class="sp-legend-label">Hoch (\u00B110-15%)</span>
          <span class="sp-legend-val">${accHigh}</span>
        </div>
        <div class="sp-legend-row">
          <span class="sp-dist-dot" style="background:var(--color-warn)"></span>
          <span class="sp-legend-label">Mittel (\u00B115-25%)</span>
          <span class="sp-legend-val">${accMed}</span>
        </div>
        <div class="sp-legend-row">
          <span class="sp-dist-dot" style="background:var(--color-poor)"></span>
          <span class="sp-legend-label">Tief (\u00B125-40%)</span>
          <span class="sp-legend-val">${accLow}</span>
        </div>
      </div>
    </div>
  `;

  // Section collapse toggles
  document.querySelectorAll(".sp-collapse-header").forEach((header) => {
    header.addEventListener("click", () => {
      header.parentElement.classList.toggle("open");
    });
  });
}
