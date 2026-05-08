// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no build toolchain required.

const VERSION = "1.1.0";

const STATE_LABELS = {
  cleaning: "Cleaning",
  paused: "Paused",
  returning: "Returning to base",
  docked: "Docked",
  idle: "Idle",
  error: "Error",
  unknown: "Unknown",
};

// Semantic colour tokens that exist in all HA themes.
const STATE_COLORS = {
  cleaning:  "var(--success-color, #4CAF50)",
  returning: "var(--info-color, var(--primary-color))",
  paused:    "var(--warning-color, #FF9800)",
  error:     "var(--error-color, #F44336)",
  docked:    "var(--primary-color)",
  idle:      "var(--secondary-text-color)",
};

const CLEANING_MODE_LABELS = {
  vacuum: "Vacuum",
  vacuum_and_mop: "Vacuum & Mop",
  mop: "Mop",
};

const _BTN_DEFS = {
  start:  { icon: "mdi:play",                 label: "Start"  },
  pause:  { icon: "mdi:pause",                label: "Pause"  },
  stop:   { icon: "mdi:stop",                 label: "Stop"   },
  dock:   { icon: "mdi:home-import-outline",  label: "Dock"   },
  locate: { icon: "mdi:crosshairs-gps",       label: "Locate" },
};

const _CSS = `
  :host { display: block; }

  ha-card {
    padding: var(--ha-space-4, 16px);
    box-sizing: border-box;
  }

  /* ── header ── */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2px;
  }
  h1.card-header {
    margin: 0;
    padding: 0;
    flex: 1;
    min-width: 0;
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
    color: var(--primary-color);
  }

  /* ── status / error ── */
  .status-line {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.9em;
    color: var(--secondary-text-color);
    margin-bottom: 10px;
    min-height: 1.25em;
  }
  .state-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  ha-alert {
    display: none;
    margin-bottom: 4px;
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
    margin-bottom: 8px;
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
  .map-badge {
    position: absolute;
    bottom: 8px;
    left: 8px;
    background: rgba(0,0,0,0.55);
    color: #fff;
    font-size: 0.72em;
    padding: 3px 8px;
    border-radius: 10px;
    pointer-events: none;
    max-width: calc(100% - 16px);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* ── stats ── */
  .stats-line {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;
    font-size: 0.82em;
    color: var(--secondary-text-color);
    margin-bottom: 10px;
  }
  .stat-item {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .stat-item ha-icon {
    --mdc-icon-size: 14px;
    opacity: 0.7;
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
    justify-content: center;
    gap: 4px;
  }
  .btn-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .btn-wrap ha-icon-button {
    --mdc-icon-button-size: 44px;
    --mdc-icon-size: 22px;
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
    this._robotIcon = null;
    this._robotIconLoading = false;
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

    // Header: h1 title + battery
    const header = _el("div", "header");
    this._titleEl = document.createElement("h1");
    this._titleEl.className = "card-header";
    this._batteryEl = _el("div", "battery");
    header.appendChild(this._titleEl);
    header.appendChild(this._batteryEl);
    card.appendChild(header);

    // Status line: dot + text
    this._statusEl = _el("div", "status-line");
    this._stateDotEl = _el("span", "state-dot");
    this._stateTextEl = _el("span");
    this._statusEl.appendChild(this._stateDotEl);
    this._statusEl.appendChild(this._stateTextEl);
    card.appendChild(this._statusEl);

    // Error alert
    this._errorEl = document.createElement("ha-alert");
    this._errorEl.setAttribute("alert-type", "error");
    this._errorEl.textContent = "Robot reported a fault";
    card.appendChild(this._errorEl);

    // Map canvas + overlay badge
    const mapContainer = _el("div", "map-container");
    this._placeholderEl = _el("div", "map-placeholder");
    this._placeholderEl.textContent = "Map not yet available";
    this._canvas = document.createElement("canvas");
    this._canvas.style.display = "none";
    this._canvas.addEventListener("click", (e) => this._onCanvasClick(e));
    this._badgeEl = _el("div", "map-badge");
    this._badgeEl.style.display = "none";
    mapContainer.appendChild(this._placeholderEl);
    mapContainer.appendChild(this._canvas);
    mapContainer.appendChild(this._badgeEl);
    card.appendChild(mapContainer);

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

    // Battery
    this._batteryEl.textContent = "";
    const battEntity = this._config.battery_entity;
    if (battEntity) {
      const b = this._hass.states[battEntity];
      if (b && b.state !== "unknown" && b.state !== "unavailable") {
        const pct = parseInt(b.state, 10);
        const iconName = pct > 80 ? "mdi:battery" : pct > 50 ? "mdi:battery-70" :
                         pct > 20 ? "mdi:battery-30" : "mdi:battery-alert";
        this._batteryEl.appendChild(_icon(iconName));
        this._batteryEl.appendChild(document.createTextNode(` ${pct}%`));
      }
    }

    // Status line: coloured dot + "State · Room"
    const dotColor = STATE_COLORS[activity] || "var(--secondary-text-color)";
    this._stateDotEl.style.background = dotColor;
    let statusText = STATE_LABELS[activity] || activity;
    const roomEntity = this._config.current_room_entity;
    if (roomEntity) {
      const r = this._hass.states[roomEntity]?.state;
      if (r && r !== "unknown" && r !== "unavailable") statusText += ` · ${r}`;
    }
    this._stateTextEl.textContent = statusText;

    // Error alert
    const errEntity = this._config.error_entity;
    const hasError = activity === "error" ||
      (errEntity && this._hass.states[errEntity]?.state === "on");
    this._errorEl.classList.toggle("visible", !!hasError);

    // Map
    this._updateMap(attr);

    // Stats — icons + right-aligned, hidden when empty
    this._updateStats();

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

  _loadRobotIcon() {
    if (this._robotIcon || this._robotIconLoading) return;
    this._robotIconLoading = true;
    const img = new Image();
    img.onload = () => {
      this._robotIcon = img;
      // Redraw if map is already shown.
      if (this._mapLoaded && this._hass && this._config) {
        const attr = this._hass.states[this._config.vacuum_entity]?.attributes;
        if (attr) this._drawMap(attr);
      }
    };
    img.src = "/karcher_home_robots/static/icon.svg";
  }

  _drawMap(attr) {
    if (!this._mapImg || !this._canvas) return;
    this._loadRobotIcon();
    const ctx = this._canvas.getContext("2d");
    ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
    ctx.drawImage(this._mapImg, 0, 0, this._canvas.width, this._canvas.height);
    this._drawRoomOverlays(ctx, attr.room_map || {});
    this._drawCharger(ctx, attr);
    this._drawRobot(ctx, attr);
  }

  _drawCharger(ctx, attr) {
    const cp = attr.charger_px;
    const imgSize = attr.map_image_size;
    if (!cp || !imgSize) return;

    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const cx = cp.x * scaleX;
    const cy = cp.y * scaleY;
    const r = Math.max(6, imgSize.cell_size * scaleX * 2.5);

    // Base: dark rounded rectangle
    const bw = r * 1.4, bh = r * 1.0;
    ctx.fillStyle = "#444";
    ctx.beginPath();
    ctx.roundRect(cx - bw / 2, cy - bh / 2, bw, bh, r * 0.25);
    ctx.fill();

    // Two yellow charging prongs on top
    const prongW = r * 0.22, prongH = r * 0.55;
    const prongY = cy - bh / 2 - prongH;
    ctx.fillStyle = "#fced4f";
    ctx.strokeStyle = "#888";
    ctx.lineWidth = 0.5;
    for (const dx of [-r * 0.3, r * 0.3]) {
      ctx.beginPath();
      ctx.roundRect(cx + dx - prongW / 2, prongY, prongW, prongH, prongW * 0.4);
      ctx.fill();
      ctx.stroke();
    }
  }

  _drawRobot(ctx, attr) {
    const rp = attr.robot_px;
    const imgSize = attr.map_image_size;
    if (!rp || !imgSize) return;

    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const cx = rp.x * scaleX;
    const cy = rp.y * scaleY;
    // Robot is ~34cm wide; resolution=0.05m/cell → ~7 cells diameter → 3.5 cell radius.
    const r = imgSize.cell_size * scaleX * 3.5;
    const phi = rp.phi ?? 0;

    ctx.save();
    ctx.translate(cx, cy);
    // SVG front (camera bump) is at upper-right: atan2(-21.79, 13.13) = -1.029 rad from east.
    // Canvas target angle for world phi (Y-flipped) = -phi.
    // Required rotation: θ = -phi - SVG_rest_angle = -phi - (-1.029) = -phi + 1.029
    ctx.rotate(-phi + 1.029 + Math.PI);

    if (this._robotIcon) {
      ctx.drawImage(this._robotIcon, -r, -r, r * 2, r * 2);
    } else {
      // Fallback circle while icon loads.
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.fillStyle = "#fff";
      ctx.strokeStyle = "#333";
      ctx.lineWidth = 1;
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }

  _drawRoomOverlays(ctx, roomMap) {
    const imgSize = this._hass?.states[this._config?.vacuum_entity]?.attributes?.map_image_size;
    if (!imgSize) return;

    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const cs = imgSize.cell_size || 1;
    const cellH = Math.ceil(cs * scaleY);

    for (const [id, room] of Object.entries(roomMap)) {
      const cells = room.cells;
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
    const rowOffset = (imgSize.height - 1) % cs;
    const snapCol = Math.floor(px / cs) * cs;
    const snapRow = Math.floor((py - rowOffset) / cs) * cs + rowOffset;

    if (!this._cellLookup || this._cellLookupAttr !== attr) {
      this._cellLookup = new Map();
      this._cellLookupAttr = attr;
      for (const [id, room] of Object.entries(roomMap)) {
        for (const [row, colStart, runLen] of (room.cells || [])) {
          for (let i = 0; i < runLen; i++) {
            this._cellLookup.set(`${row},${colStart + i * cs}`, id);
          }
        }
      }
    }

    const hitId = this._cellLookup.get(`${snapRow},${snapCol}`);
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
      this._badgeEl.style.display = "none";
      return;
    }
    this._badgeEl.style.display = "";
    if (this._selectedRooms.size === 0) {
      this._badgeEl.textContent = "Tap a room · no selection cleans all";
    } else {
      const names = [...this._selectedRooms].map((id) => roomMap[id]?.name || id);
      this._badgeEl.textContent = `Selected: ${names.join(", ")}`;
    }
  }

  _updateStats() {
    this._statsEl.textContent = "";
    const parts = [];

    const te = this._config.cleaning_time_entity;
    if (te) {
      const t = this._hass.states[te];
      if (t && t.state !== "unknown" && t.state !== "unavailable" && t.state !== "0") {
        const item = _el("span", "stat-item");
        item.appendChild(_icon("mdi:clock-outline"));
        item.appendChild(document.createTextNode(`${t.state} min`));
        parts.push(item);
      }
    }

    const ae = this._config.cleaning_area_entity;
    if (ae) {
      const a = this._hass.states[ae];
      if (a && a.state !== "unknown" && a.state !== "unavailable") {
        const v = parseFloat(a.state);
        if (!isNaN(v) && v > 0) {
          const item = _el("span", "stat-item");
          item.appendChild(_icon("mdi:floor-plan"));
          item.appendChild(document.createTextNode(`${v.toFixed(1)} m²`));
          parts.push(item);
        }
      }
    }

    for (const item of parts) this._statsEl.appendChild(item);
    this._statsEl.style.display = parts.length ? "" : "none";
  }

  _updateSelectors(attr) {
    // Build selector DOM once; on subsequent calls only sync the current value.
    const fanSpeed = attr.fan_speed;
    const hasFan = fanSpeed !== null && fanSpeed !== undefined;
    const modeEntityId = this._config.cleaning_mode_entity;
    const modeState = modeEntityId ? this._hass.states[modeEntityId] : null;

    if (!this._selectorsBuilt) {
      this._selectorsBuilt = true;
      this._fanSelect = null;
      this._modeSelect = null;
      this._modeOptionEls = {};

      if (hasFan) {
        const { wrap, sel } = this._makeSelect(
          "Fan speed",
          ["Silent", "Standard", "Medium", "Turbo"].map((v) => ({ value: v, label: v })),
          (v) => this._hass.callService("vacuum", "set_fan_speed", {
            entity_id: this._config.vacuum_entity,
            fan_speed: v,
          })
        );
        this._fanSelect = sel;
        this._selectorsEl.appendChild(wrap);
      }

      if (modeState) {
        const opts = (modeState.attributes.options || []).map((k) => ({
          value: k,
          label: CLEANING_MODE_LABELS[k] || k,
        }));
        const { wrap, sel, optionEls } = this._makeSelect(
          "Cleaning mode", opts,
          (v) => this._hass.callService("select", "select_option", {
            entity_id: modeEntityId,
            option: v,
          })
        );
        this._modeSelect = sel;
        this._modeOptionEls = optionEls;
        this._selectorsEl.appendChild(wrap);
      }
    }

    // Sync current values and disabled state without rebuilding DOM.
    if (this._fanSelect && fanSpeed !== undefined && fanSpeed !== null) {
      if (this._fanSelect.value !== String(fanSpeed)) this._fanSelect.value = fanSpeed;
    }
    if (this._modeSelect && modeState) {
      if (this._modeSelect.value !== modeState.state) this._modeSelect.value = modeState.state;
      const disabled = new Set(modeState.attributes.disabled_options || []);
      for (const [value, el] of Object.entries(this._modeOptionEls)) {
        el.disabled = disabled.has(value);
      }
    }
  }

  _makeSelect(labelText, options, onChange) {
    const wrap = _el("div", "selector-wrap");
    const label = _el("label");
    label.textContent = labelText;
    wrap.appendChild(label);

    const sel = document.createElement("select");
    const optionEls = {};
    for (const opt of options) {
      const o = document.createElement("option");
      o.value = opt.value;
      o.textContent = opt.label;
      optionEls[opt.value] = o;
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => onChange(sel.value));
    wrap.appendChild(sel);

    return { wrap, sel, optionEls };
  }

  _updateButtons(activity) {
    this._buttonsEl.textContent = "";

    const isCleaning  = activity === "cleaning";
    const isPaused    = activity === "paused";
    const isReturning = activity === "returning";
    const isDocked    = activity === "docked";

    const playKey   = isCleaning ? "pause" : "start";
    const playClass = (isCleaning || isPaused || isDocked || activity === "idle") ? "primary" : "disabled";
    const stopClass = (isCleaning || isPaused) ? "secondary" : "disabled";
    const dockClass = (isCleaning || isPaused || activity === "idle" || isReturning) ? "secondary" : "disabled";

    const plan = [
      [playKey,  playClass,  "_play"],
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
      wrap.appendChild(btn);
      this._buttonsEl.appendChild(wrap);
    }
  }

  // ── actions ───────────────────────────────────────────────────────────────────

  _play() {
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
