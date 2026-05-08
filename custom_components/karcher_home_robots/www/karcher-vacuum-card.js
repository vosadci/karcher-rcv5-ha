// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no build toolchain required.

const VERSION = "1.0.0";

const STATE_LABELS = {
  cleaning: "Cleaning",
  paused: "Paused",
  returning: "Returning to base",
  docked: "Docked",
  idle: "Idle",
  error: "Error",
  unknown: "Unknown",
};

const CLEANING_MODE_LABELS = {
  vacuum: "Vacuum",
  vacuum_and_mop: "Vacuum & Mop",
  mop: "Mop",
};

// MDI icon for each action button.
const _BTN_DEFS = {
  start:  { icon: "mdi:play",            label: "Start"  },
  resume: { icon: "mdi:play",            label: "Resume" },
  pause:  { icon: "mdi:pause",           label: "Pause"  },
  stop:   { icon: "mdi:stop",            label: "Stop"   },
  dock:   { icon: "mdi:home-import-outline", label: "Dock" },
  locate: { icon: "mdi:crosshairs-gps", label: "Locate" },
};

const _CSS = `
  :host { display: block; }

  ha-card {
    padding: 16px;
    box-sizing: border-box;
  }

  /* ── header ── */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2px;
  }
  .title {
    font-size: var(--ha-card-header-font-size, 1.24em);
    font-weight: var(--ha-card-header-font-weight, 500);
    color: var(--ha-card-header-color, var(--primary-text-color));
    letter-spacing: var(--ha-card-header-letter-spacing, -0.012em);
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .battery {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--secondary-text-color);
    font-size: 0.9em;
    flex-shrink: 0;
    margin-left: 8px;
  }
  .battery ha-icon {
    --mdc-icon-size: 18px;
    color: var(--state-sensor-battery-icon-color, var(--primary-color));
  }

  /* ── status / error ── */
  .status-line {
    font-size: 0.9em;
    color: var(--secondary-text-color);
    margin-bottom: 10px;
    min-height: 1.25em;
  }
  ha-alert {
    display: none;
    margin-bottom: 8px;
  }
  ha-alert.visible {
    display: block;
  }

  /* ── map ── */
  .map-container {
    position: relative;
    width: 100%;
    background: var(--secondary-background-color);
    border-radius: var(--ha-card-border-radius, 12px);
    overflow: hidden;
    margin-bottom: 6px;
    min-height: 120px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .map-container canvas {
    display: block;
    width: 100%;
    height: auto;
    cursor: pointer;
  }
  .map-placeholder {
    color: var(--secondary-text-color);
    font-size: 0.85em;
    padding: 32px;
    text-align: center;
  }

  /* ── selection hint / stats ── */
  .selection-hint {
    font-size: 0.8em;
    color: var(--secondary-text-color);
    text-align: center;
    margin-bottom: 8px;
    min-height: 1.1em;
  }
  .stats-line {
    font-size: 0.85em;
    color: var(--secondary-text-color);
    margin-bottom: 12px;
    min-height: 1.1em;
  }

  /* ── selectors ── */
  .selectors {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }
  .selector-wrap {
    flex: 1;
    min-width: 110px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .selector-wrap label {
    font-size: 0.72em;
    font-weight: 500;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--secondary-text-color);
    padding-left: 2px;
  }
  .selector-wrap select {
    width: 100%;
    box-sizing: border-box;
    padding: 9px 10px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    border-radius: 8px;
    background: var(--input-fill-color, var(--secondary-background-color));
    color: var(--primary-text-color);
    font-size: 0.9em;
    font-family: inherit;
    cursor: pointer;
    outline: none;
    -webkit-appearance: auto;
    appearance: auto;
  }
  .selector-wrap select:focus {
    border-color: var(--primary-color);
    border-width: 2px;
  }

  /* ── buttons ── */
  .buttons {
    display: flex;
    gap: 8px;
  }
  .btn-wrap {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }
  .btn-wrap ha-icon-button {
    --mdc-icon-button-size: 48px;
    --mdc-icon-size: 24px;
  }
  .btn-wrap.primary ha-icon-button {
    color: var(--primary-color);
  }
  .btn-wrap.secondary ha-icon-button {
    color: var(--secondary-text-color);
  }
  .btn-wrap.disabled ha-icon-button {
    color: var(--disabled-text-color, rgba(0,0,0,0.26));
    pointer-events: none;
  }
  .btn-label {
    font-size: 0.7em;
    color: var(--secondary-text-color);
    letter-spacing: 0.02em;
    text-align: center;
    line-height: 1;
  }
  .btn-wrap.disabled .btn-label {
    color: var(--disabled-text-color, rgba(0,0,0,0.26));
  }
`;

function _el(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

function _icon(name) {
  const el = document.createElement("ha-icon");
  el.setAttribute("icon", name);
  return el;
}

class KarcherVacuumCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._selectedRooms = new Set();
    this._mapLoaded = false;
    this._mapImg = null;
    this._mapToken = null;
  }

  setConfig(config) {
    if (!config.vacuum_entity) throw new Error("vacuum_entity is required");
    this._config = config;
    this._buildDOM();
  }

  set hass(hass) {
    this._hass = hass;
    this._updateCard();
  }

  getCardSize() { return 6; }

  static getStubConfig() {
    return { vacuum_entity: "vacuum.karcher_rcv5" };
  }

  // ── DOM construction (once) ──────────────────────────────────────────────────

  _buildDOM() {
    const shadow = this.shadowRoot;
    shadow.innerHTML = "";

    const style = document.createElement("style");
    style.textContent = _CSS;
    shadow.appendChild(style);

    const card = document.createElement("ha-card");

    // Header: title + battery
    const header = _el("div", "header");
    this._titleEl = _el("div", "title");
    this._batteryEl = _el("div", "battery");
    header.appendChild(this._titleEl);
    header.appendChild(this._batteryEl);
    card.appendChild(header);

    // Status line
    this._statusEl = _el("div", "status-line");
    card.appendChild(this._statusEl);

    // Error alert (ha-alert)
    this._errorEl = document.createElement("ha-alert");
    this._errorEl.setAttribute("alert-type", "error");
    this._errorEl.textContent = "Robot reported a fault";
    card.appendChild(this._errorEl);

    // Map canvas
    const mapContainer = _el("div", "map-container");
    this._placeholderEl = _el("div", "map-placeholder");
    this._placeholderEl.textContent = "Map not yet available";
    this._canvas = document.createElement("canvas");
    this._canvas.style.display = "none";
    this._canvas.addEventListener("click", (e) => this._onCanvasClick(e));
    mapContainer.appendChild(this._placeholderEl);
    mapContainer.appendChild(this._canvas);
    card.appendChild(mapContainer);

    // Selection hint
    this._hintEl = _el("div", "selection-hint");
    card.appendChild(this._hintEl);

    // Stats line
    this._statsEl = _el("div", "stats-line");
    card.appendChild(this._statsEl);

    // Selectors row
    this._selectorsEl = _el("div", "selectors");
    card.appendChild(this._selectorsEl);

    // Buttons row
    this._buttonsEl = _el("div", "buttons");
    card.appendChild(this._buttonsEl);

    shadow.appendChild(card);
  }

  // ── update cycle ─────────────────────────────────────────────────────────────

  _updateCard() {
    if (!this._hass || !this._config || !this._titleEl) return;
    const vacState = this._hass.states[this._config.vacuum_entity];
    if (!vacState) return;

    const attr = vacState.attributes;
    const activity = vacState.state;

    // Title
    this._titleEl.textContent = attr.friendly_name || "Kärcher RCV5";

    // Battery — ha-icon + text
    this._batteryEl.textContent = "";
    const battEntity = this._config.battery_entity;
    if (battEntity) {
      const b = this._hass.states[battEntity];
      if (b && b.state !== "unknown" && b.state !== "unavailable") {
        const pct = parseInt(b.state, 10);
        const iconName = pct > 80 ? "mdi:battery" : pct > 50 ? "mdi:battery-70" :
                         pct > 20 ? "mdi:battery-30" : "mdi:battery-alert";
        this._batteryEl.appendChild(_icon(iconName));
        const txt = document.createTextNode(` ${pct}%`);
        this._batteryEl.appendChild(txt);
      }
    }

    // Status line
    let status = STATE_LABELS[activity] || activity;
    const roomEntity = this._config.current_room_entity;
    if (roomEntity) {
      const r = this._hass.states[roomEntity]?.state;
      if (r && r !== "unknown" && r !== "unavailable") status += ` · ${r}`;
    }
    this._statusEl.textContent = status;

    // Error alert
    const errEntity = this._config.error_entity;
    const hasError = activity === "error" ||
      (errEntity && this._hass.states[errEntity]?.state === "on");
    this._errorEl.classList.toggle("visible", !!hasError);

    // Map
    this._updateMap(attr);

    // Stats
    const parts = [];
    const te = this._config.cleaning_time_entity;
    if (te) {
      const t = this._hass.states[te];
      if (t && t.state !== "unknown" && t.state !== "unavailable") parts.push(`${t.state} min`);
    }
    const ae = this._config.cleaning_area_entity;
    if (ae) {
      const a = this._hass.states[ae];
      if (a && a.state !== "unknown" && a.state !== "unavailable") {
        const v = parseFloat(a.state);
        if (!isNaN(v)) parts.push(`${v.toFixed(1)} m²`);
      }
    }
    this._statsEl.textContent = parts.join(" · ");

    this._updateSelectors(attr);
    this._updateSelectionHint(attr);
    this._updateButtons(activity);
  }

  // ── map ───────────────────────────────────────────────────────────────────────

  _updateMap(attr) {
    const mapEntity = this._config.map_entity;
    if (!mapEntity) {
      this._placeholderEl.textContent = "Set map_entity in card config";
      return;
    }
    const mapState = this._hass.states[mapEntity];
    if (!mapState) {
      this._placeholderEl.textContent = `Entity not found: ${mapEntity}`;
      return;
    }

    const pic = mapState.attributes.entity_picture;
    const token = mapState.attributes.access_token || "";
    const imageTimestamp = mapState.state;

    if (imageTimestamp !== this._mapToken) {
      this._mapToken = imageTimestamp;
      if (!this._mapLoaded) this._placeholderEl.textContent = "Map not yet available";

      const url = pic
        ? `${pic}&_t=${encodeURIComponent(imageTimestamp)}`
        : `/api/image_proxy/${mapEntity}?token=${token}&_t=${encodeURIComponent(imageTimestamp)}`;

      const img = new Image();
      img.onload = () => {
        this._mapImg = img;
        this._mapLoaded = true;
        this._placeholderEl.style.display = "none";
        this._canvas.style.display = "block";
        const sz = attr.map_image_size;
        this._canvas.width = sz ? sz.width : img.naturalWidth;
        this._canvas.height = sz ? sz.height : img.naturalHeight;
        this._drawMap(attr);
      };
      img.onerror = () => {
        this._placeholderEl.textContent = "Map unavailable";
      };
      img.src = url;
    } else if (this._mapLoaded) {
      this._drawMap(attr);
    }
  }

  _drawMap(attr) {
    if (!this._mapImg || !this._canvas) return;
    const ctx = this._canvas.getContext("2d");
    ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
    ctx.drawImage(this._mapImg, 0, 0, this._canvas.width, this._canvas.height);
    this._drawRoomOverlays(ctx, attr.room_map || {});
  }

  _drawRoomOverlays(ctx, roomMap) {
    const imgSize = this._hass?.states[this._config?.vacuum_entity]?.attributes?.map_image_size;
    if (!imgSize) return;

    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const cs = imgSize.cell_size || 1;
    const cellW = Math.ceil(cs * scaleX);
    const cellH = Math.ceil(cs * scaleY);

    for (const [id, room] of Object.entries(roomMap)) {
      const cells = room.cells; // RLE: [[px_row, col_start, run_len], ...]
      if (!cells || cells.length === 0) continue;
      if (!this._selectedRooms.has(id)) continue;

      ctx.fillStyle = "rgba(255, 200, 0, 0.35)";
      for (const [row, colStart, runLen] of cells) {
        ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
      }
    }
  }

  _onCanvasClick(e) {
    if (!this._hass || !this._config) return;
    const attr = this._hass.states[this._config.vacuum_entity]?.attributes;
    const roomMap = attr?.room_map;
    const imgSize = attr?.map_image_size;
    if (!roomMap || !imgSize) return;

    const cs = imgSize.cell_size || 1;
    const rect = this._canvas.getBoundingClientRect();
    const px = Math.floor((e.clientX - rect.left) * (imgSize.width / rect.width));
    const py = Math.floor((e.clientY - rect.top) * (imgSize.height / rect.height));
    // Cell origins: px_col = (grid_col - col0) * cs  → 0, cs, 2*cs, ...
    // px_row = (out_h - 1) - (grid_row - row0) * cs  → (out_h-1), (out_h-1)-cs, ...
    // The row grid is offset by (out_h - 1) % cs, so snap to that offset.
    const rowOffset = (imgSize.height - 1) % cs;
    const snapCol = Math.floor(px / cs) * cs;
    const snapRow = Math.floor((py - rowOffset) / cs) * cs + rowOffset;

    // Build RLE-based lookup: "row,col_start" → roomId for each span start.
    // Also used to check membership: snap click → row/col and scan spans.
    if (!this._cellLookup || this._cellLookupAttr !== attr) {
      this._cellLookup = new Map(); // "row,col" → roomId (one entry per span start)
      this._cellLookupAttr = attr;
      this._debuggedCells = false;
      for (const [id, room] of Object.entries(roomMap)) {
        for (const [row, colStart, runLen] of (room.cells || [])) {
          for (let i = 0; i < runLen; i++) {
            this._cellLookup.set(`${row},${colStart + i * cs}`, id);
          }
        }
      }
    }

    // Log row range of all cells to diagnose coordinate mismatch.
    if (!this._debuggedCells) {
      this._debuggedCells = true;
      const allRows = [...this._cellLookup.keys()].map(k => parseInt(k.split(",")[0]));
      const allCols = [...this._cellLookup.keys()].map(k => parseInt(k.split(",")[1]));
      console.debug("[karcher] cell row range:", Math.min(...allRows), "–", Math.max(...allRows),
        "col range:", Math.min(...allCols), "–", Math.max(...allCols),
        "imgSize:", imgSize);
    }
    console.debug("[karcher] click px=", px, "py=", py, "snapCol=", snapCol, "snapRow=", snapRow, "cs=", cs);
    const hitId = this._cellLookup.get(`${snapRow},${snapCol}`);
    console.debug("[karcher] hitId=", hitId);
    if (hitId !== undefined) {
      if (this._selectedRooms.has(hitId)) this._selectedRooms.delete(hitId);
      else this._selectedRooms.add(hitId);
      this._updateSelectionHint(attr);
      this._drawMap(attr);
    }
  }

  // ── UI helpers ────────────────────────────────────────────────────────────────

  _updateSelectionHint(attr) {
    const roomMap = attr?.room_map || {};
    if (Object.keys(roomMap).length === 0) {
      this._hintEl.textContent = "";
      return;
    }
    if (this._selectedRooms.size === 0) {
      this._hintEl.textContent = "Tap a room to select · no selection cleans all";
    } else {
      const names = [...this._selectedRooms].map((id) => roomMap[id]?.name || id);
      this._hintEl.textContent = `Selected: ${names.join(", ")}`;
    }
  }

  _updateSelectors(attr) {
    this._selectorsEl.textContent = "";

    // Fan speed selector — hidden when null (Mop-only mode has no fan).
    const fanSpeed = attr.fan_speed;
    if (fanSpeed !== null && fanSpeed !== undefined) {
      this._selectorsEl.appendChild(
        this._makeSelect(
          "Fan speed",
          ["Silent", "Standard", "Medium", "Turbo"].map((v) => ({ value: v, label: v })),
          fanSpeed,
          (v) => this._hass.callService("vacuum", "set_fan_speed", {
            entity_id: this._config.vacuum_entity,
            fan_speed: v,
          })
        )
      );
    }

    // Cleaning mode selector.
    const modeEntityId = this._config.cleaning_mode_entity;
    if (modeEntityId) {
      const modeState = this._hass.states[modeEntityId];
      if (modeState) {
        const opts = (modeState.attributes.options || []).map((k) => ({
          value: k,
          label: CLEANING_MODE_LABELS[k] || k,
        }));
        this._selectorsEl.appendChild(
          this._makeSelect("Cleaning mode", opts, modeState.state,
            (v) => this._hass.callService("select", "select_option", {
              entity_id: modeEntityId,
              option: v,
            })
          )
        );
      }
    }
  }

  _makeSelect(labelText, options, currentValue, onChange) {
    const wrap = _el("div", "selector-wrap");

    const label = _el("label");
    label.textContent = labelText;

    const sel = document.createElement("select");
    for (const opt of options) {
      const o = document.createElement("option");
      o.value = opt.value;
      o.textContent = opt.label;
      o.selected = opt.value === currentValue;
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => onChange(sel.value));

    wrap.appendChild(label);
    wrap.appendChild(sel);
    return wrap;
  }

  _updateButtons(activity) {
    this._buttonsEl.textContent = "";

    const isCleaning  = activity === "cleaning";
    const isPaused    = activity === "paused";
    const isReturning = activity === "returning";
    const isDocked    = activity === "docked";

    // Always 4 buttons: Play/Pause · Stop · Dock · Locate
    // Each entry: [key, cssClass, action]
    // cssClass: "primary" | "secondary" | "disabled"
    const playKey    = isCleaning ? "pause" : (isPaused ? "resume" : "start");
    const playClass  = (isCleaning || isPaused || isDocked || activity === "idle") ? "primary" : "disabled";
    const stopClass  = (isCleaning || isPaused) ? "secondary" : "disabled";
    const dockClass  = (isCleaning || isPaused || activity === "idle" || isReturning) ? "secondary" : "disabled";

    const plan = [
      [playKey,  playClass,  `_${playKey === "resume" ? "start" : playKey}`],
      ["stop",   stopClass,  "_stop"],
      ["dock",   dockClass,  "_dock"],
      ["locate", "secondary","_locate"],
    ];

    for (const [key, cls, method] of plan) {
      const def = _BTN_DEFS[key];
      const wrap = _el("div", `btn-wrap ${cls}`);

      const btn = document.createElement("ha-icon-button");
      btn.setAttribute("label", def.label);
      btn.appendChild(_icon(def.icon));
      if (cls !== "disabled") btn.addEventListener("click", () => this[method]());

      const lbl = _el("span", "btn-label");
      lbl.textContent = def.label;

      wrap.appendChild(btn);
      wrap.appendChild(lbl);
      this._buttonsEl.appendChild(wrap);
    }
  }

  // ── actions ───────────────────────────────────────────────────────────────────

  _start() {
    const vacuumEntity = this._config.vacuum_entity;
    const attr = this._hass.states[vacuumEntity]?.attributes;
    const roomMap = attr?.room_map || {};
    const allIds = Object.keys(roomMap).map(Number);
    const ids = this._selectedRooms.size > 0
      ? [...this._selectedRooms].map(Number)
      : allIds;

    if (ids.length > 0) {
      this._hass.callService("vacuum", "send_command", {
        entity_id: vacuumEntity,
        command: "app_segment_clean",
        params: ids,
      });
    } else {
      this._hass.callService("vacuum", "start", { entity_id: vacuumEntity });
    }
  }

  _resume() { this._start(); }

  _pause() {
    this._hass.callService("vacuum", "pause", { entity_id: this._config.vacuum_entity });
  }

  _stop() {
    this._hass.callService("vacuum", "stop", { entity_id: this._config.vacuum_entity });
  }

  _dock() {
    this._hass.callService("vacuum", "return_to_base", { entity_id: this._config.vacuum_entity });
  }

  _locate() {
    this._hass.callService("vacuum", "locate", { entity_id: this._config.vacuum_entity });
  }
}

customElements.define("karcher-vacuum-card", KarcherVacuumCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "karcher-vacuum-card",
  name: "Kärcher Vacuum Card",
  description: "Map, room selection, controls for the Kärcher RCV5",
  preview: false,
  version: VERSION,
});
