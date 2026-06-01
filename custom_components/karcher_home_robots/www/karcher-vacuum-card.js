// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no build toolchain required.

const VERSION = "1.3.8";

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

const CLEANING_MODE_ICONS = {
  vacuum:         "mdi:robot-vacuum",
  vacuum_and_mop: "mdi:shimmer",
  mop:            "mdi:water",
};

const WATER_LEVEL_ICONS = {
  low:    "mdi:water-minus",
  medium: "mdi:water",
  high:   "mdi:water-plus",
};

const FAN_SPEED_LABELS = {
  silent: "Silent",
  standard: "Standard",
  medium: "Medium",
  turbo: "Turbo",
};

const WATER_LEVEL_LABELS = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

const FAN_SPEED_ICONS = {
  silent:   "mdi:fan-speed-1",
  standard: "mdi:fan-speed-2",
  medium:   "mdi:fan-speed-3",
  turbo:    "mdi:fan",
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
    overflow: hidden;
  }

  /* ── top bar: chips (left, wrapping) + battery (right) ── */
  .top-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
  }
  .top-bar-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
  }

  .fan-chip {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--secondary-background-color);
    border-radius: 20px;
    padding: 4px 10px 4px 8px;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.10));
  }
  .fan-chip ha-icon {
    --mdc-icon-size: 16px;
    color: var(--primary-text-color);
    flex-shrink: 0;
  }
  .fan-chip select {
    background: transparent;
    border: none;
    outline: none;
    color: var(--primary-text-color);
    font-size: 0.9em;
    font-family: inherit;
    cursor: pointer;
    -webkit-appearance: auto;
    appearance: auto;
    padding: 0;
    margin: 0;
    min-width: 60px;
  }

  .battery {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--secondary-text-color);
    font-size: 0.9em;
    flex-shrink: 0;
  }
  .battery ha-icon {
    --mdc-icon-size: 18px;
    color: var(--primary-color);
  }

  /* ── map ── */
  .map-container {
    position: relative;
    width: 100%;
    background: var(--secondary-background-color);
    border-radius: var(--ha-card-border-radius, 12px);
    overflow: hidden;
    min-height: 180px;
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
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
  }
  .map-placeholder svg {
    opacity: 0.35;
  }
  .map-placeholder.map-loading {
    background: linear-gradient(
      90deg,
      var(--secondary-background-color) 25%,
      var(--divider-color, rgba(255,255,255,0.1)) 50%,
      var(--secondary-background-color) 75%
    );
    background-size: 200% 100%;
    animation: map-shimmer 1.6s ease-in-out infinite;
  }
  @media (prefers-reduced-motion: reduce) {
    .map-placeholder.map-loading {
      animation: none;
    }
  }
  @keyframes map-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
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

  /* ── centered name + state ── */
  .robot-name {
    text-align: center;
    font-weight: bold;
    font-size: 1.15em;
    margin: 10px 0 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .robot-state {
    text-align: center;
    font-size: 0.9em;
    margin-bottom: 10px;
  }

  /* ── error ── */
  ha-alert {
    display: none;
    margin-bottom: 8px;
  }
  ha-alert.visible {
    display: block;
  }

  /* ── divider ── */
  .divider {
    border: none;
    border-top: 1px solid var(--divider-color, rgba(0,0,0,0.10));
    margin: 0 0 8px;
  }

  /* ── stats ── */
  .stats-line {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 12px;
    font-size: 0.82em;
    color: var(--secondary-text-color);
    margin-bottom: 8px;
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

  /* ── buttons ── */
  .buttons {
    display: flex;
    align-items: center;
  }
  .btn-group {
    display: flex;
    align-items: center;
  }
  .btn-spacer { flex: 1; }
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

    // Top bar: chip group (left, wrapping) + battery (right)
    const topBar = _el("div", "top-bar");
    const chipsEl = _el("div", "top-bar-chips");

    // Cleaning mode chip (built here; populated once entity is known)
    this._modeChipIconEl = _icon("mdi:robot-vacuum");
    this._modeChipSelect = document.createElement("select");
    this._modeChipWrap = _el("div", "fan-chip");
    this._modeChipWrap.appendChild(this._modeChipIconEl);
    this._modeChipWrap.appendChild(this._modeChipSelect);
    this._modeChipWrap.style.display = "none";
    chipsEl.appendChild(this._modeChipWrap);

    // Fan speed chip
    const fanChip = _el("div", "fan-chip");
    this._fanChipIconEl = _icon("mdi:fan-speed-1");
    fanChip.appendChild(this._fanChipIconEl);
    this._fanChipSelect = document.createElement("select");
    for (const [value, label] of Object.entries(FAN_SPEED_LABELS)) {
      const o = document.createElement("option");
      o.value = value;
      o.textContent = label;
      this._fanChipSelect.appendChild(o);
    }
    this._fanChipSelect.addEventListener("change", () => {
      this._hass.callService("vacuum", "set_fan_speed", {
        entity_id: this._config.vacuum_entity,
        fan_speed: this._fanChipSelect.value,
      });
    });
    fanChip.appendChild(this._fanChipSelect);
    chipsEl.appendChild(fanChip);

    // Water level chip
    this._waterChipIconEl = _icon("mdi:water");
    this._waterChipSelect = document.createElement("select");
    this._waterChipWrap = _el("div", "fan-chip");
    this._waterChipWrap.appendChild(this._waterChipIconEl);
    this._waterChipWrap.appendChild(this._waterChipSelect);
    chipsEl.appendChild(this._waterChipWrap);

    topBar.appendChild(chipsEl);
    this._batteryEl = _el("div", "battery");
    topBar.appendChild(this._batteryEl);
    card.appendChild(topBar);

    // Map canvas + overlay badge
    const mapContainer = _el("div", "map-container");
    this._placeholderEl = _el("div", "map-placeholder");
    const _svgNS = "http://www.w3.org/2000/svg";
    const _placeholderSvg = document.createElementNS(_svgNS, "svg");
    _placeholderSvg.setAttribute("width", "48");
    _placeholderSvg.setAttribute("height", "48");
    _placeholderSvg.setAttribute("viewBox", "0 0 24 24");
    _placeholderSvg.setAttribute("fill", "currentColor");
    const _placeholderPath = document.createElementNS(_svgNS, "path");
    _placeholderPath.setAttribute("d", "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z");
    _placeholderSvg.appendChild(_placeholderPath);
    this._placeholderTextEl = document.createElement("span");
    this._placeholderTextEl.textContent = "No map yet — start a cleaning run to generate one.";
    this._placeholderEl.appendChild(_placeholderSvg);
    this._placeholderEl.appendChild(this._placeholderTextEl);
    this._canvas = document.createElement("canvas");
    this._canvas.style.display = "none";
    this._canvas.addEventListener("click", (e) => this._onCanvasClick(e));
    this._badgeEl = _el("div", "map-badge");
    this._badgeEl.style.display = "none";
    mapContainer.appendChild(this._placeholderEl);
    mapContainer.appendChild(this._canvas);
    mapContainer.appendChild(this._badgeEl);
    card.appendChild(mapContainer);

    // Centered name + state
    this._nameEl = _el("div", "robot-name");
    card.appendChild(this._nameEl);
    this._stateEl = _el("div", "robot-state");
    card.appendChild(this._stateEl);

    // Error alert
    this._errorEl = document.createElement("ha-alert");
    this._errorEl.setAttribute("alert-type", "error");
    this._errorEl.textContent = "Robot reported a fault";
    card.appendChild(this._errorEl);

    // Divider
    card.appendChild(_el("hr", "divider"));

    // Stats line
    this._statsEl = _el("div", "stats-line");
    card.appendChild(this._statsEl);

    // Buttons row
    this._buttonsEl = _el("div", "buttons");
    card.appendChild(this._buttonsEl);

    shadow.appendChild(card);
  }

  // ── update cycle ─────────────────────────────────────────────────────────────

  _updateCard() {
    if (!this._hass || !this._config || !this._nameEl) return;
    const vacState = this._hass.states[this._config.vacuum_entity];
    if (!vacState) return;

    const attr = vacState.attributes;
    const activity = vacState.state;

    // Centered name
    this._nameEl.textContent = attr.friendly_name || "Kärcher RCV5";

    // Centered state (with current room if available)
    let statusText = STATE_LABELS[activity] || activity;
    const roomEntity = this._config.current_room_entity;
    if (roomEntity) {
      const r = this._hass.states[roomEntity]?.state;
      if (r && r !== "unknown" && r !== "unavailable") statusText += ` · ${r}`;
    }
    this._stateEl.textContent = statusText;
    this._stateEl.style.color = STATE_COLORS[activity] || "var(--secondary-text-color)";

    // Battery (top-bar right)
    this._batteryEl.textContent = "";
    const battEntity = this._config.battery_entity;
    if (battEntity) {
      const b = this._hass.states[battEntity];
      if (b && b.state !== "unknown" && b.state !== "unavailable") {
        const pct = parseInt(b.state, 10);
        const isCharging = this._hass.states[this._config.charging_entity]?.state === "on";
        const iconName = isCharging
          ? (pct > 80 ? "mdi:battery-charging-high" : pct > 50 ? "mdi:battery-charging-60" :
             pct > 20 ? "mdi:battery-charging-30" : "mdi:battery-charging-outline")
          : (pct > 80 ? "mdi:battery" : pct > 50 ? "mdi:battery-70" :
             pct > 20 ? "mdi:battery-30" : "mdi:battery-alert");
        this._batteryEl.appendChild(_icon(iconName));
        this._batteryEl.appendChild(document.createTextNode(` ${pct}%`));
      }
    }

    // Error alert
    const errEntity = this._config.error_entity;
    const hasError = activity === "error" ||
      (errEntity && this._hass.states[errEntity]?.state === "on");
    this._errorEl.classList.toggle("visible", !!hasError);

    // Map
    this._updateMap(attr);

    // Stats
    this._updateStats();

    this._updateSelectors(attr);
    this._updateSelectionHint(attr);
    this._updateButtons(activity);
  }

  // ── map ───────────────────────────────────────────────────────────────────────

  _updateMap(attr) {
    const mapEntity = this._config.map_entity;
    if (!mapEntity) {
      this._placeholderTextEl.textContent = "Set map_entity in card config";
      this._placeholderEl.classList.remove("map-loading");
      return;
    }
    const mapState = this._hass.states[mapEntity];
    if (!mapState) {
      this._placeholderTextEl.textContent = `Entity not found: ${mapEntity}`;
      this._placeholderEl.classList.remove("map-loading");
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

      this._placeholderEl.classList.add("map-loading");
      const img = new Image();
      img.onload = () => {
        this._mapImg = img;
        this._mapLoaded = true;
        this._placeholderEl.classList.remove("map-loading");
        this._placeholderEl.style.display = "none";
        this._canvas.style.display = "block";
        const sz = attr.map_image_size;
        this._canvas.width = sz ? sz.width : img.naturalWidth;
        this._canvas.height = sz ? sz.height : img.naturalHeight;
        this._drawMap(attr);
      };
      img.onerror = () => {
        this._placeholderEl.classList.remove("map-loading");
        this._placeholderTextEl.textContent = "Map unavailable";
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
    ctx.rotate(-phi + 1.029);

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
    const vacState = this._hass?.states[this._config?.vacuum_entity];
    const imgSize = vacState?.attributes?.map_image_size;
    if (!imgSize) return;

    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const cs = imgSize.cell_size || 1;
    const cellH = Math.ceil(cs * scaleY);

    const activity = vacState?.state;
    const isCleaning = activity === "cleaning";

    // While cleaning: highlight the current room from the sensor entity.
    let activeRoomId = null;
    if (isCleaning && this._config.current_room_entity) {
      const currentRoomName = this._hass.states[this._config.current_room_entity]?.state;
      if (currentRoomName && currentRoomName !== "unknown" && currentRoomName !== "unavailable") {
        for (const [id, room] of Object.entries(roomMap)) {
          if (room.name === currentRoomName) { activeRoomId = id; break; }
        }
      }
    }

    for (const [id, room] of Object.entries(roomMap)) {
      const cells = room.cells;
      if (!cells || cells.length === 0) continue;
      const isActive = id === activeRoomId;
      const isSelected = this._selectedRooms.has(id);
      if (!isActive && !isSelected) continue;

      ctx.fillStyle = isActive
        ? "rgba(255, 140, 0, 0.45)"
        : "rgba(255, 200, 0, 0.35)";
      for (const [row, colStart, runLen] of cells) {
        ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
      }
    }
  }

  _onCanvasClick(e) {
    if (!this._hass || !this._config) return;
    const vacState = this._hass.states[this._config.vacuum_entity];
    const activity = vacState?.state;
    if (activity === "cleaning" || activity === "returning") return;
    const attr = vacState?.attributes;
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
    const vacState = this._hass?.states[this._config?.vacuum_entity];
    const activity = vacState?.state;
    const isBusy = activity === "cleaning" || activity === "returning" || activity === "paused";
    if (!this._mapLoaded || Object.keys(roomMap).length === 0 || isBusy) {
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
    const fanSpeed = attr.fan_speed;
    const fanSpeedList = attr.fan_speed_list || [];
    const modeEntityId = this._config.cleaning_mode_entity;
    const modeState = modeEntityId ? this._hass.states[modeEntityId] : null;
    const waterEntityId = this._config.water_level_entity;
    const waterState = waterEntityId ? this._hass.states[waterEntityId] : null;

    // Fan chip
    if (fanSpeed !== undefined && fanSpeed !== null) {
      if (this._fanChipSelect.value !== String(fanSpeed)) this._fanChipSelect.value = fanSpeed;
      this._fanChipIconEl.setAttribute("icon", FAN_SPEED_ICONS[fanSpeed] || "mdi:fan");
    }
    this._fanChipSelect.disabled = fanSpeedList.length === 0;

    // Mode chip — populate options once, then sync value
    if (modeState) {
      if (!this._modeChipBuilt) {
        this._modeChipBuilt = true;
        this._modeChipOptionEls = {};
        for (const k of (modeState.attributes.options || [])) {
          const o = document.createElement("option");
          o.value = k;
          o.textContent = CLEANING_MODE_LABELS[k] || k;
          this._modeChipOptionEls[k] = o;
          this._modeChipSelect.appendChild(o);
        }
        this._modeChipSelect.addEventListener("change", () => {
          this._hass.callService("select", "select_option", {
            entity_id: modeEntityId,
            option: this._modeChipSelect.value,
          });
        });
        this._modeChipWrap.style.display = "";
      }
      if (this._modeChipSelect.value !== modeState.state) this._modeChipSelect.value = modeState.state;
      this._modeChipIconEl.setAttribute("icon", CLEANING_MODE_ICONS[modeState.state] || "mdi:robot-vacuum");
      const disabled = new Set(modeState.attributes.disabled_options || []);
      for (const [value, el] of Object.entries(this._modeChipOptionEls)) {
        el.disabled = disabled.has(value);
      }
    }

    // Water chip — populate once, then sync
    if (waterState && !this._waterChipBuilt) {
      this._waterChipBuilt = true;
      for (const k of (waterState.attributes.options || ["low", "medium", "high"])) {
        const o = document.createElement("option");
        o.value = k;
        o.textContent = WATER_LEVEL_LABELS[k] || k;
        this._waterChipSelect.appendChild(o);
      }
      this._waterChipSelect.addEventListener("change", () => {
        this._hass.callService("select", "select_option", {
          entity_id: waterEntityId,
          option: this._waterChipSelect.value,
        });
      });
    }
    const waterDisabled = !modeState?.state || modeState.state === "vacuum";
    this._waterChipSelect.disabled = waterDisabled;
    this._waterChipWrap.style.opacity = waterDisabled ? "0.4" : "";
    if (this._waterChipBuilt && waterState && waterState.state !== "unavailable" && waterState.state !== "unknown") {
      if (this._waterChipSelect.value !== waterState.state) this._waterChipSelect.value = waterState.state;
      this._waterChipIconEl.setAttribute("icon", WATER_LEVEL_ICONS[waterState.state] || "mdi:water");
    }
  }

  _updateButtons(activity) {
    this._buttonsEl.textContent = "";

    const isCleaning  = activity === "cleaning";
    const isPaused    = activity === "paused";
    const isReturning = activity === "returning";

    const playKey    = isCleaning ? "pause" : "start";
    const playMethod = isCleaning ? "_pause" : "_play";
    const playClass  = (isCleaning || isPaused || activity === "docked" || activity === "idle") ? "primary" : "disabled";
    const dockClass  = (isCleaning || isPaused || activity === "idle") ? "secondary" : "disabled";

    // Left group: play only
    const leftGroup = _el("div", "btn-group");
    leftGroup.appendChild(this._makeBtn(playKey, playClass, playMethod));

    const spacer = _el("div", "btn-spacer");

    // Right group: locate + (stop when returning, dock otherwise)
    const rightGroup = _el("div", "btn-group");
    rightGroup.appendChild(this._makeBtn("locate", "secondary", "_locate"));
    if (isReturning) {
      rightGroup.appendChild(this._makeBtn("stop", "secondary", "_stop"));
    } else {
      rightGroup.appendChild(this._makeBtn("dock", dockClass, "_dock"));
    }

    this._buttonsEl.appendChild(leftGroup);
    this._buttonsEl.appendChild(spacer);
    this._buttonsEl.appendChild(rightGroup);
  }

  _makeBtn(key, cls, method) {
    const def = _BTN_DEFS[key];
    const wrap = _el("div", `btn-wrap ${cls}`);
    const btn = document.createElement("ha-icon-button");
    btn.setAttribute("label", def.label);
    btn.appendChild(_icon(def.icon));
    if (cls !== "disabled") btn.addEventListener("click", () => this[method]());
    wrap.appendChild(btn);
    return wrap;
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
