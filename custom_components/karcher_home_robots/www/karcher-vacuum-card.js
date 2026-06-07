// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no build toolchain required.

const VERSION = "1.8.0";

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

const REPEAT_LABELS = { single: "Clean once", double: "Double cleaning", triple: "Triple cleaning" };
const REPEAT_VALUES = ["single", "double", "triple"];
const MODE_VALUES   = ["vacuum", "vacuum_and_mop", "mop"];
const POWER_VALUES  = ["silent", "standard", "medium", "turbo"];
const WATER_VALUES  = ["low", "medium", "high"];

// Numeric wire values → option key (used to read room_preferences attribute)
const MODE_BY_INT   = { 0: "vacuum", 1: "vacuum_and_mop", 2: "mop" };
const POWER_BY_INT  = { 0: "silent", 1: "standard", 2: "medium", 3: "turbo" };
const REPEAT_BY_INT = { 0: "single", 1: "double", 2: "triple" };
const WATER_BY_INT  = { 1: "low", 2: "medium", 3: "high" };

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

  /* ── top bar: name+state (left) + status items (right) ── */
  .top-bar {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 10px;
  }
  .top-bar-left {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    flex: 1;
  }
  .top-bar-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
    flex-shrink: 0;
  }

  /* ── global chips — Standard mode, below tabs ── */
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
    aspect-ratio: 1 / 1;
    background: var(--secondary-background-color);
    border-radius: var(--ha-card-border-radius, 12px);
    overflow: hidden;
  }
  .map-container canvas {
    display: block;
    width: 100%;
    height: 100%;
    cursor: pointer;
  }
  .map-placeholder {
    position: absolute;
    inset: 0;
    color: var(--secondary-text-color);
    font-size: 0.85em;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 32px;
    text-align: center;
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

  /* ── name + state (top-bar left column) ── */
  .robot-name {
    font-weight: bold;
    font-size: 1.1em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .robot-state {
    font-size: 0.85em;
  }

  /* ── error ── */
  ha-alert {
    display: none;
    margin-bottom: 8px;
  }
  ha-alert.visible {
    display: block;
  }

  /* ── stats (top-bar right column, below battery) ── */
  .stats-line {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.82em;
    color: var(--secondary-text-color);
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

  /* ── Standard / Customise tab strip ── */
  .mode-tabs {
    display: flex;
    border: 1.5px solid var(--primary-text-color);
    border-radius: 6px;
    overflow: hidden;
    margin: 10px 0 6px;
  }
  .mode-tab {
    flex: 1;
    padding: 7px 0;
    text-align: center;
    font-size: 0.9em;
    font-weight: 600;
    cursor: pointer;
    background: transparent;
    color: var(--primary-text-color);
    border: none;
    outline: none;
    font-family: inherit;
    letter-spacing: 0.01em;
  }
  .mode-tab.active {
    background: var(--primary-text-color);
    color: var(--card-background-color, #fff);
  }

  /* ── Customise: room list ── */
  .room-list {
    display: none;
    flex-direction: column;
    max-height: 320px;
    overflow-y: auto;
    border-top: 1px solid var(--divider-color, rgba(0,0,0,0.10));
  }
  .room-list.visible { display: flex; }
  .room-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 4px;
    border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.08));
    cursor: default;
    transition: background 0.12s;
  }
  .room-row:last-child { border-bottom: none; }
  .room-row.dragging { opacity: 0.4; }
  .drop-indicator {
    height: 2px;
    background: #f5e642;
    margin: 0 4px;
    border-radius: 1px;
    pointer-events: none;
  }
  .room-drag-handle {
    cursor: grab;
    color: var(--secondary-text-color);
    font-size: 1.1em;
    padding: 0 2px;
    flex-shrink: 0;
    user-select: none;
  }
  .room-drag-handle:active { cursor: grabbing; }
  .room-row-select { cursor: pointer; }
  .room-check {
    width: 22px;
    height: 22px;
    border: 2px solid var(--primary-text-color);
    border-radius: 3px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
  }
  .room-check.on {
    background: var(--primary-text-color);
  }
  .room-check.on::after {
    content: "";
    display: block;
    width: 6px;
    height: 10px;
    border: 2px solid var(--card-background-color, #fff);
    border-top: none;
    border-left: none;
    transform: rotate(45deg) translate(-1px, -1px);
  }
  .room-text { flex: 1; min-width: 0; }
  .room-name-row {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .room-name { font-weight: 600; font-size: 0.95em; }
  .room-repeat-label {
    font-size: 0.8em;
    color: var(--info-color, #4db6ac);
    font-weight: 600;
  }
  .room-summary {
    font-size: 0.8em;
    color: var(--secondary-text-color);
    margin-top: 1px;
  }
  .room-chevron {
    color: var(--secondary-text-color);
    font-size: 1.1em;
    flex-shrink: 0;
  }

  /* ── Customise: per-room detail ── */
  .room-detail {
    display: none;
    flex-direction: column;
    gap: 14px;
    padding-top: 4px;
  }
  .room-detail.visible { display: flex; }
  .detail-back {
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    color: var(--primary-color);
    font-size: 0.9em;
    font-weight: 600;
    border: none;
    background: none;
    padding: 0;
    font-family: inherit;
    margin-bottom: 2px;
  }
  .detail-title {
    font-weight: 700;
    font-size: 1em;
    text-align: center;
    margin-bottom: 4px;
  }
  .detail-section { display: flex; flex-direction: column; gap: 6px; }
  .detail-label {
    font-weight: 700;
    font-size: 0.85em;
    color: var(--secondary-text-color);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .detail-label span {
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
    color: var(--primary-text-color);
    margin-left: 6px;
  }
  .icon-btn-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .icon-btn {
    width: 52px;
    height: 52px;
    border: 1.5px solid var(--divider-color, rgba(0,0,0,0.15));
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    background: transparent;
    flex-direction: column;
    gap: 2px;
    transition: background 0.15s, border-color 0.15s;
  }
  .icon-btn.selected {
    background: #f5e642;
    border-color: #c8bc00;
  }
  .icon-btn.disabled {
    opacity: 0.35;
    pointer-events: none;
  }
  .icon-btn ha-icon { --mdc-icon-size: 22px; }
  .icon-btn .btn-label { font-size: 0.65em; font-weight: 600; }

  /* ── Settings/selection lockout while the robot is in a cleaning run ── */
  .busy-locked {
    pointer-events: none;
    opacity: 0.55;
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
    this._prevActivity = null;
    this._mapLoaded = false;
    this._mapImg = null;
    this._mapToken = null;
    this._robotIcon = null;
    this._robotIconLoading = false;
    this._cardMode = "standard";         // "standard" | "customise"
    this._modeInitialised = false;       // true once prefer_mode restored from robot
    this._detailRoomId = null;           // string room_id when detail is open
    this._customiseSelected = new Set(); // selected room IDs in Customise mode
    this._customisePending = new Map();  // id → expected custom (optimistic) until HA confirms
    this._dragSrcId = null;              // room_id being dragged
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
    return {
      vacuum_entity: "vacuum.karcher_rcv5",
      room_entity: "select.karcher_rcv5_room",
    };
  }

  // ── DOM construction (once) ──────────────────────────────────────────────────

  _buildDOM() {
    const shadow = this.shadowRoot;
    shadow.innerHTML = "";

    const style = document.createElement("style");
    style.textContent = _CSS;
    shadow.appendChild(style);

    const card = document.createElement("ha-card");

    // Top bar: name+state (left) | battery+stats (right)
    const topBar = _el("div", "top-bar");

    const topLeft = _el("div", "top-bar-left");
    this._nameEl = _el("div", "robot-name");
    this._stateEl = _el("div", "robot-state");
    topLeft.appendChild(this._nameEl);
    topLeft.appendChild(this._stateEl);
    topBar.appendChild(topLeft);

    const topRight = _el("div", "top-bar-right");
    this._batteryEl = _el("div", "battery");
    this._statsEl = _el("div", "stats-line");
    topRight.appendChild(this._batteryEl);
    topRight.appendChild(this._statsEl);
    topBar.appendChild(topRight);

    card.appendChild(topBar);

    // Map canvas + overlay badge
    this._mapContainer = _el("div", "map-container");
    const mapContainer = this._mapContainer;
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
    this._placeholderTextEl.textContent = "";
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

    // Error alert
    this._errorEl = document.createElement("ha-alert");
    this._errorEl.setAttribute("alert-type", "error");
    this._errorEl.textContent = "Robot reported a fault";
    card.appendChild(this._errorEl);

    // Buttons row
    this._buttonsEl = _el("div", "buttons");
    card.appendChild(this._buttonsEl);

    // Standard / Customise tab strip
    const modeTabs = _el("div", "mode-tabs");
    this._tabStandard = _el("button", "mode-tab active");
    this._tabStandard.textContent = "Standard";
    this._tabStandard.addEventListener("click", () => this._setCardMode("standard"));
    this._tabCustomise = _el("button", "mode-tab");
    this._tabCustomise.textContent = "Customise";
    this._tabCustomise.addEventListener("click", () => this._setCardMode("customise"));
    modeTabs.appendChild(this._tabStandard);
    modeTabs.appendChild(this._tabCustomise);
    card.appendChild(modeTabs);

    // Global chips — shown in Standard mode only, hidden in Customise
    this._chipsEl = _el("div", "top-bar-chips");
    this._chipsEl.style.marginBottom = "8px";

    // Cleaning mode chip
    this._modeChipIconEl = _icon("mdi:robot-vacuum");
    this._modeChipSelect = document.createElement("select");
    this._modeChipWrap = _el("div", "fan-chip");
    this._modeChipWrap.appendChild(this._modeChipIconEl);
    this._modeChipWrap.appendChild(this._modeChipSelect);
    this._modeChipWrap.style.display = "none";
    this._chipsEl.appendChild(this._modeChipWrap);

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
    this._chipsEl.appendChild(fanChip);

    // Water level chip
    this._waterChipIconEl = _icon("mdi:water");
    this._waterChipSelect = document.createElement("select");
    this._waterChipWrap = _el("div", "fan-chip");
    this._waterChipWrap.appendChild(this._waterChipIconEl);
    this._waterChipWrap.appendChild(this._waterChipSelect);
    this._chipsEl.appendChild(this._waterChipWrap);

    card.appendChild(this._chipsEl);

    // Customise: room list view
    this._roomListEl = _el("div", "room-list");
    card.appendChild(this._roomListEl);

    // Customise: per-room detail view
    this._roomDetailEl = _el("div", "room-detail");
    card.appendChild(this._roomDetailEl);

    shadow.appendChild(card);
  }

  // ── update cycle ─────────────────────────────────────────────────────────────

  _updateCard() {
    if (!this._hass || !this._config || !this._nameEl) return;
    const vacState = this._hass.states[this._config.vacuum_entity];
    if (!vacState) return;

    const attr = vacState.attributes;
    const activity = vacState.state;

    if (!this._modeInitialised && attr?.prefer_mode) {
      this._modeInitialised = true;
      this._applyMode(attr.prefer_mode);
    }

    if (this._prevActivity === "cleaning" && activity !== "cleaning") {
      this._selectedRooms.clear();
    }
    this._prevActivity = activity;

    // Centered name
    this._nameEl.textContent = attr.friendly_name || "Kärcher RCV5";

    // Centered state (with current room if available)
    let statusText = attr.status_label || STATE_LABELS[activity] || activity;
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
    this._updateCustomise(attr);
    this._updateBusyLock(activity);
  }

  // While the robot is mid-job, mutating selection or settings would change
  // the in-flight clean — gray out the Standard chips, Custom tab strip,
  // room list and detail view so the only actions are pause/stop/dock/locate
  // (which live in _buttonsEl and are gated by _updateButtons).
  _isBusy(activity) {
    return activity === "cleaning" || activity === "returning";
  }

  _updateBusyLock(activity) {
    const busy = this._isBusy(activity);
    this._tabStandard.classList.toggle("busy-locked", busy);
    this._tabCustomise.classList.toggle("busy-locked", busy);
    this._chipsEl.classList.toggle("busy-locked", busy);
    this._roomListEl.classList.toggle("busy-locked", busy);
    // CSS pointer-events: none blocks mouse but not keyboard; also disable the
    // native <select> elements so tab-and-change can't bypass the lock.
    // _updateSelectors may re-enable them next render based on its own rules,
    // and that's fine — _updateBusyLock runs after it in _render.
    this._fanChipSelect.disabled = busy || this._fanChipSelect.disabled;
    this._modeChipSelect.disabled = busy || this._modeChipSelect.disabled;
    this._waterChipSelect.disabled = busy || this._waterChipSelect.disabled;
    this._busy = busy;
    // Detail view's icon-button sections gate themselves via _renderDetail
    // so the Back button stays usable while busy.
  }

  // ── Standard / Customise mode ─────────────────────────────────────────────────

  _applyMode(mode) {
    this._cardMode = mode;
    if (mode === "standard") {
      this._detailRoomId = null;
      this._customiseSelected.clear();
    }
    this._tabStandard.classList.toggle("active", mode === "standard");
    this._tabCustomise.classList.toggle("active", mode === "customise");
    this._chipsEl.style.display = mode === "standard" ? "" : "none";
    if (this._hass && this._config) {
      const attr = this._hass.states[this._config.vacuum_entity]?.attributes;
      if (attr) this._updateCustomise(attr);
    }
  }

  _setCardMode(mode) {
    if (this._hass && this._config) {
      const activity = this._hass.states[this._config.vacuum_entity]?.state;
      if (this._isBusy(activity)) return;
    }
    this._hass.callService("vacuum", "send_command", {
      entity_id: this._config.vacuum_entity,
      command: "set_preference_type",
      params: { prefer_type: mode === "customise" ? 1 : 0 },
    });
    this._applyMode(mode);
  }

  _updateCustomise(attr) {
    const isCustomise = this._cardMode === "customise";
    this._roomListEl.classList.toggle("visible", isCustomise && !this._detailRoomId);
    this._roomDetailEl.classList.toggle("visible", isCustomise && !!this._detailRoomId);
    if (!isCustomise) return;
    if (this._detailRoomId) {
      this._renderDetail(attr, this._detailRoomId);
    } else {
      this._renderList(attr);
    }
  }

  _renderList(attr) {
    const roomMap = attr?.room_map || {};
    const prefs = attr?.room_preferences || {};
    this._roomListEl.textContent = "";

    const roomIds = Object.keys(roomMap).sort((a, b) => {
      const oa = prefs[a]?.order ?? 999;
      const ob = prefs[b]?.order ?? 999;
      return oa - ob;
    });

    // Mirror prefs into _customiseSelected so external changes propagate AND
    // toggling-off works on a single click. The previous version was add-only,
    // which made the immediate re-render after a deselect re-add the room
    // (because the persisted pref hadn't caught up yet) — that's the bug
    // behind "two taps to deselect".
    //
    // While a service call is in flight the local optimistic state wins:
    // _customisePending records the expected value and is cleared once the
    // persisted pref matches.
    for (const id of roomIds) {
      const persisted = prefs[id]?.custom === true;
      if (this._customisePending.has(id)) {
        const expected = this._customisePending.get(id);
        if (persisted === expected) {
          this._customisePending.delete(id);
          if (persisted) this._customiseSelected.add(id);
          else this._customiseSelected.delete(id);
        }
        // else: still pending — keep the optimistic value in _customiseSelected.
        continue;
      }
      if (persisted) this._customiseSelected.add(id);
      else this._customiseSelected.delete(id);
    }

    if (roomIds.length === 0) {
      const empty = _el("div", "room-summary");
      empty.style.padding = "16px 4px";
      empty.textContent = "No rooms found — load a map first";
      this._roomListEl.appendChild(empty);
      return;
    }

    const _reorder = (srcId, tgtId) => {
      const newOrder = [...roomIds];
      const fromIdx = newOrder.indexOf(srcId);
      const toIdx   = newOrder.indexOf(tgtId);
      if (fromIdx === -1 || toIdx === -1 || fromIdx === toIdx) return;
      newOrder.splice(fromIdx, 1);
      newOrder.splice(toIdx, 0, srcId);
      this._hass.callService("karcher_home_robots", "set_room_preference", {
        room_order: newOrder.map(rid => parseInt(rid, 10)),
      });
    };

    // Container-level drop handler — avoids child elements swallowing the event
    const listEl = this._roomListEl;
    listEl.ondragover = (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      let el = e.target;
      while (el && el !== listEl) {
        if (el.dataset && el.dataset.roomId && el.dataset.roomId !== this._dragSrcId) {
          listEl.querySelectorAll(".drop-indicator").forEach(d => d.remove());
          const ind = _el("div", "drop-indicator");
          el.parentNode.insertBefore(ind, el);
          break;
        }
        el = el.parentNode;
      }
    };
    listEl.ondrop = (e) => {
      e.preventDefault();
      listEl.querySelectorAll(".drop-indicator").forEach(d => d.remove());
      const srcId = this._dragSrcId;
      let el = e.target;
      while (el && el !== listEl) {
        if (el.dataset && el.dataset.roomId) { _reorder(srcId, el.dataset.roomId); break; }
        el = el.parentNode;
      }
    };
    listEl.ondragleave = (e) => {
      if (!listEl.contains(e.relatedTarget))
        listEl.querySelectorAll(".drop-indicator").forEach(d => d.remove());
    };

    for (const id of roomIds) {
      const room = roomMap[id];
      const pref = prefs[id];
      const isCustom = pref?.custom === true;

      const row = _el("div", "room-row");
      row.dataset.roomId = id;
      row.draggable = true;

      row.addEventListener("dragstart", (e) => {
        const act = this._hass?.states[this._config.vacuum_entity]?.state;
        if (this._isBusy(act)) {
          e.preventDefault();
          return;
        }
        this._dragSrcId = id;
        row.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", id);
      });
      row.addEventListener("dragend", () => {
        row.classList.remove("dragging");
        this._dragSrcId = null;
        listEl.querySelectorAll(".drop-indicator").forEach(d => d.remove());
      });

      // ── Drag handle ────────────────────────────────────────────────────
      const handle = _el("span", "room-drag-handle");
      handle.textContent = "⠿";
      handle.title = "Drag to reorder";
      row.appendChild(handle);

      // ── Checkbox: persists selection via check field + updates map ──────
      const isSelected = this._customiseSelected.has(id);
      const check = _el("div", `room-check${isSelected ? " on" : ""}`);
      check.addEventListener("click", (e) => {
        e.stopPropagation();
        const act = this._hass?.states[this._config.vacuum_entity]?.state;
        if (this._isBusy(act)) return;
        const nowOn = !this._customiseSelected.has(id);
        if (nowOn) this._customiseSelected.add(id);
        else this._customiseSelected.delete(id);
        this._customisePending.set(id, nowOn);
        this._toggleRoomCustom(id, nowOn);
        this._drawMap(attr);
        this._renderList(attr);
      });
      row.appendChild(check);

      // ── Text block: click anywhere opens detail ────────────────────────
      const text = _el("div", "room-text room-row-select");
      const nameRow = _el("div", "room-name-row");
      const nameEl = _el("span", "room-name");
      nameEl.textContent = room.name || id;
      nameRow.appendChild(nameEl);
      if (pref) {
        const repeatKey = REPEAT_BY_INT[pref.repeat] || "single";
        const repeatLabel = _el("span", "room-repeat-label");
        repeatLabel.textContent = REPEAT_LABELS[repeatKey] || repeatKey;
        nameRow.appendChild(repeatLabel);
      }
      text.appendChild(nameRow);
      if (pref) {
        const summary = _el("div", "room-summary");
        const modeLabel = CLEANING_MODE_LABELS[MODE_BY_INT[pref.mode]] || "Vacuum";
        const powerLabel = FAN_SPEED_LABELS[POWER_BY_INT[pref.power]] || "Standard";
        summary.textContent = `${modeLabel} | ${powerLabel}`;
        text.appendChild(summary);
      }
      // Clicking the text area or chevron opens detail
      text.addEventListener("click", (e) => {
        e.stopPropagation();
        const act = this._hass?.states[this._config.vacuum_entity]?.state;
        if (this._isBusy(act)) return;
        this._detailRoomId = id;
        this._updateCustomise(attr);
      });
      row.appendChild(text);

      const chev = _el("span", "room-chevron");
      chev.textContent = "›";
      row.appendChild(chev);

      this._roomListEl.appendChild(row);
    }
  }

  _renderDetail(attr, roomId) {
    const roomMap = attr?.room_map || {};
    const prefs = attr?.room_preferences || {};
    const room = roomMap[roomId];
    const pref = prefs[roomId];
    const busy = this._isBusy(this._hass?.states[this._config?.vacuum_entity]?.state);
    this._roomDetailEl.textContent = "";

    // Back button
    const back = _el("button", "detail-back");
    back.textContent = "‹ Back";
    back.addEventListener("click", () => {
      this._detailRoomId = null;
      this._updateCustomise(attr);
    });
    this._roomDetailEl.appendChild(back);

    const title = _el("div", "detail-title");
    title.textContent = (room?.name || roomId).toUpperCase();
    this._roomDetailEl.appendChild(title);

    if (!pref) {
      const msg = _el("div", "room-summary");
      msg.textContent = "Settings not loaded yet";
      this._roomDetailEl.appendChild(msg);
      return;
    }

    // Repeat
    this._roomDetailEl.appendChild(
      this._makeIconBtnSection(
        "Cleaning cycles", REPEAT_BY_INT[pref.repeat],
        [
          { value: "single", label: "×1" },
          { value: "double", label: "×2" },
          { value: "triple", label: "×3" },
        ],
        (val) => this._setRoomPref(roomId, "repeat", val),
        busy
      )
    );

    // Mode
    this._roomDetailEl.appendChild(
      this._makeIconBtnSection(
        "Cleaning mode", MODE_BY_INT[pref.mode],
        [
          { value: "vacuum",         icon: "mdi:robot-vacuum" },
          { value: "vacuum_and_mop", icon: "mdi:shimmer"      },
          { value: "mop",            icon: "mdi:water"        },
        ],
        (val) => this._setRoomPref(roomId, "mode", val),
        busy
      )
    );

    // Suction
    this._roomDetailEl.appendChild(
      this._makeIconBtnSection(
        "Suction", POWER_BY_INT[pref.power],
        [
          { value: "silent",   icon: "mdi:fan-off",     label: "Silent"   },
          { value: "standard", icon: "mdi:fan-speed-2", label: "Standard" },
          { value: "medium",   icon: "mdi:fan-speed-3", label: "Medium"   },
          { value: "turbo",    icon: "mdi:fan",         label: "Turbo"    },
        ],
        (val) => this._setRoomPref(roomId, "power", val),
        busy
      )
    );

    // Water level — only meaningful for mop modes
    const modeKey = MODE_BY_INT[pref.mode];
    const waterDisabled = modeKey === "vacuum";
    this._roomDetailEl.appendChild(
      this._makeIconBtnSection(
        "Water level", WATER_BY_INT[pref.water],
        [
          { value: "low",    icon: "mdi:water-minus" },
          { value: "medium", icon: "mdi:water"       },
          { value: "high",   icon: "mdi:water-plus"  },
        ],
        (val) => this._setRoomPref(roomId, "water", val),
        waterDisabled || busy
      )
    );
  }

  _makeIconBtnSection(label, currentValue, options, onChange, disabled = false) {
    const section = _el("div", "detail-section");
    const labelEl = _el("div", "detail-label");
    labelEl.textContent = label;
    section.appendChild(labelEl);
    const row = _el("div", "icon-btn-row");
    for (const opt of options) {
      const btn = _el("div", `icon-btn${opt.value === currentValue ? " selected" : ""}${disabled ? " disabled" : ""}`);
      if (opt.icon) btn.appendChild(_icon(opt.icon));
      if (opt.label) {
        const lbl = _el("span", "btn-label");
        lbl.textContent = opt.label;
        btn.appendChild(lbl);
      }
      if (!disabled) {
        btn.addEventListener("click", () => onChange(opt.value));
      }
      row.appendChild(btn);
    }
    section.appendChild(row);
    return section;
  }

  // Read entity_ids from vacuum.room_preferences[roomId].entities (built by vacuum.py).
  _roomEntities(roomId) {
    const attr = this._hass?.states[this._config?.vacuum_entity]?.attributes;
    return attr?.room_preferences?.[roomId]?.entities || {};
  }

  _setRoomPref(roomId, field, value) {
    const entityId = this._roomEntities(roomId)[field];
    if (!entityId) { console.warn(`Kärcher card: no entity for ${field} room ${roomId}`); return; }
    this._hass.callService("select", "select_option", { entity_id: entityId, option: value });
  }

  _toggleRoomCustom(roomId, on) {
    const entityId = this._roomEntities(roomId)["custom"];
    if (!entityId) { console.warn(`Kärcher card: no custom switch for room ${roomId}`); return; }
    this._hass.callService("switch", on ? "turn_on" : "turn_off", { entity_id: entityId });
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

    // Reserve the correct space as soon as map_image_size is known — before the
    // image arrives — so the card doesn't reflow when the canvas appears.
    const sz = attr.map_image_size;
    if (sz) {
      this._mapContainer.style.aspectRatio = `${sz.width} / ${sz.height}`;
      // Robot has a map but it's still loading — suppress the "no map" message.
      if (!this._mapLoaded) this._placeholderTextEl.textContent = "";
    } else {
      // No map_image_size means the robot genuinely has no map yet.
      this._placeholderTextEl.textContent =
        "No map yet — start a cleaning run to generate one.";
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
    const attr = vacState?.attributes;
    const imgSize = attr?.map_image_size;
    if (!imgSize) return;

    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const cs = imgSize.cell_size || 1;
    const cellH = Math.ceil(cs * scaleY);

    if (this._cardMode === "customise") {
      const prefs = attr?.room_preferences || {};
      for (const [id, room] of Object.entries(roomMap)) {
        const cells = room.cells;
        if (!cells || cells.length === 0) continue;

        const isSelected = this._customiseSelected.has(id);
        ctx.fillStyle = isSelected ? "rgba(255, 200, 0, 0.45)" : "rgba(255, 200, 0, 0.15)";
        let minRow = Infinity, maxRow = -Infinity, minCol = Infinity, maxCol = -Infinity;
        for (const [row, colStart, runLen] of cells) {
          ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
          if (row < minRow) minRow = row;
          if (row > maxRow) maxRow = row;
          if (colStart < minCol) minCol = colStart;
          const colEnd = colStart + runLen * cs;
          if (colEnd > maxCol) maxCol = colEnd;
        }

        // Draw per-room chip at bounding box centre
        const pref = prefs[id];
        if (pref) {
          const cx = ((minCol + maxCol) / 2) * scaleX;
          const cy = ((minRow + maxRow) / 2) * scaleY;
          const repeatSym = ["×1", "×2", "×3"][pref.repeat] || "×1";
          const modeSym   = ["▽", "▽~", "~"][pref.mode] || "▽";
          const powerSym  = ["○", "◎", "◉", "●"][pref.power] || "◎";
          const modeKey   = MODE_BY_INT[pref.mode];
          const waterSym  = modeKey !== "vacuum" ? ([, "▿", "▾", "▼"][pref.water] || "") : "";
          const chipText  = [repeatSym, modeSym, powerSym, waterSym].filter(Boolean).join(" ");

          const fontSize = Math.max(9, Math.min(13, cs * scaleX * 1.1));
          ctx.save();
          ctx.font = `bold ${fontSize}px sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          // Dark pill background
          const tw = ctx.measureText(chipText).width;
          const ph = fontSize * 1.4, pw = tw + fontSize;
          ctx.fillStyle = "rgba(0,0,0,0.55)";
          ctx.beginPath();
          ctx.roundRect(cx - pw / 2, cy - ph / 2, pw, ph, ph / 2);
          ctx.fill();
          ctx.fillStyle = "#fff";
          ctx.fillText(chipText, cx, cy);
          ctx.restore();
        }
      }
    } else {
      // Standard mode: yellow fill for selected rooms only
      for (const [id, room] of Object.entries(roomMap)) {
        if (!this._selectedRooms.has(id)) continue;
        const cells = room.cells;
        if (!cells || cells.length === 0) continue;
        ctx.fillStyle = "rgba(255, 200, 0, 0.35)";
        for (const [row, colStart, runLen] of cells) {
          ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
        }
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
      if (this._cardMode === "customise") {
        const nowOn = !this._customiseSelected.has(hitId);
        if (nowOn) this._customiseSelected.add(hitId);
        else this._customiseSelected.delete(hitId);
        this._customisePending.set(hitId, nowOn);
        this._toggleRoomCustom(hitId, nowOn);
        this._drawMap(attr);
        if (!this._detailRoomId) this._renderList(attr);
      } else {
        if (this._selectedRooms.has(hitId)) {
          this._selectedRooms.delete(hitId);
        } else {
          this._selectedRooms.add(hitId);
        }
        this._updateSelectionHint(attr);
        this._drawMap(attr);
      }
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
      this._badgeEl.textContent = "Tap a room to select · cleans all if none selected";
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
    // Always push the current map-tap selection up to HA before starting.
    // Empty array = "clear selection" (clean all rooms). The robot respects the
    // order of room_ids in set_room_clean, so the coordinator reorders this set
    // into preference order in default_clean_room_ids().
    const roomIds = [...this._selectedRooms].map((id) => parseInt(id, 10));
    this._hass.callService("karcher_home_robots", "set_room_selection", {
      room_ids: roomIds,
    });
    this._hass.callService("vacuum", "start", { entity_id: vacuumEntity });
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
