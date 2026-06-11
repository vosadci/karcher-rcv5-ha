// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no build toolchain required.

const VERSION = "1.10.0";

const STATE_LABELS = {
  cleaning: "Cleaning",
  paused: "Paused",
  returning: "Returning",
  docked: "Docked",
  idle: "Ready",
  error: "Error",
  unknown: "Unknown",
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

// Room colour palette — mirrors _ROOM_COLOR_TABLE in map_render.py (APK-verified).
// Index = (color_id - 1) % 5
const _ROOM_COLORS = [
  "#c9dcd2",  // color_id 1 — teal-green
  "#e9bac0",  // color_id 2 — pink
  "#e8e7e3",  // color_id 3 — off-white
  "#bddde0",  // color_id 4 — light blue
  "#b7b7b7",  // color_id 5 — grey
];
function _roomColor(colorId) {
  if (!colorId || colorId < 1) return _ROOM_COLORS[0];
  return _ROOM_COLORS[(colorId - 1) % _ROOM_COLORS.length];
}

const REPEAT_LABELS = { single: "Clean once", double: "Double cleaning" };
const REPEAT_VALUES = ["single", "double"];
const MODE_VALUES   = ["vacuum", "vacuum_and_mop", "mop"];
const POWER_VALUES  = ["silent", "standard", "medium", "turbo"];
const WATER_VALUES  = ["low", "medium", "high"];

// Numeric wire values → option key (used to read room_preferences attribute)
const MODE_BY_INT   = { 0: "vacuum", 1: "vacuum_and_mop", 2: "mop" };
const POWER_BY_INT  = { 0: "silent", 1: "standard", 2: "medium", 3: "turbo" };
const REPEAT_BY_INT = { 0: "single", 1: "double" };
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

  /* ── section dividers ── */
  .section-divider {
    height: 1px;
    background: var(--divider-color, rgba(0,0,0,0.12));
    margin: 12px 0;
  }

  /* ── top bar: name+pill (left) | stats (right) ── */
  .top-bar {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
  }
  .top-bar-left {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex: 1;
  }
  .top-bar-right {
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }

  /* ── Standard settings — mode, suction, water ── */
  .standard-settings {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-top: 8px;
  }


  /* ── map ── */
  .map-container {
    position: relative;
    width: 100%;
    aspect-ratio: 1 / 1;
    background: var(--secondary-background-color);
    border-radius: var(--ha-card-border-radius, 12px);
    overflow: hidden;
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    margin-top: 12px;
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
    font-size: 0.78em;
    color: var(--secondary-text-color);
    text-align: center;
    padding: 4px 0 2px;
    pointer-events: none;
  }

  /* ── name + state (top-bar left column) ── */
  .robot-name {
    font-weight: bold;
    font-size: 1.1em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .status-pill {
    max-width: max-content;
    font-size: 0.78em;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    line-height: 1.5;
    background: color-mix(in srgb, var(--secondary-text-color) 15%, transparent);
    color: var(--secondary-text-color);
  }
  .status-pill.pill-cleaning {
    background: color-mix(in srgb, var(--info-color, #03a9f4) 15%, transparent);
    color: var(--info-color, #03a9f4);
  }
  .status-pill.pill-paused {
    background: color-mix(in srgb, var(--warning-color, #ff9800) 15%, transparent);
    color: var(--warning-color, #ff9800);
  }
  .status-pill.pill-error {
    background: color-mix(in srgb, var(--error-color, #f44336) 15%, transparent);
    color: var(--error-color, #f44336);
  }
  .status-pill.pill-docked,
  .status-pill.pill-idle {
    background: color-mix(in srgb, var(--success-color, #4caf50) 15%, transparent);
    color: var(--success-color, #4caf50);
  }
  .status-pill.pill-returning,
  .status-pill.pill-locating {
    background: color-mix(in srgb, var(--primary-color) 15%, transparent);
    color: var(--primary-color);
  }
  .status-pill.pill-offline {
    background: color-mix(in srgb, var(--disabled-color, #9e9e9e) 15%, transparent);
    color: var(--disabled-color, #9e9e9e);
  }

  /* ── error ── */
  ha-alert {
    display: none;
    margin-bottom: 0;
  }
  ha-alert.visible {
    display: block;
  }

  /* ── stats (top-bar right column) ── */
  .stats-line {
    display: flex;
    align-items: flex-start;
    gap: 0;
  }
  .stat-block {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    padding: 0 10px;
    border-left: 1px solid var(--divider-color, rgba(0,0,0,0.12));
  }
  .stat-block:first-child {
    border-left: none;
    padding-right: 10px;
    padding-left: 0;
  }
  .stat-value {
    font-size: 0.95em;
    font-weight: 600;
    color: var(--primary-text-color);
    line-height: 1.2;
    white-space: nowrap;
  }
  .stat-label {
    font-size: 0.72em;
    color: var(--secondary-text-color);
    line-height: 1.3;
    white-space: nowrap;
  }

  /* ── buttons ── */
  .buttons {
    display: flex;
    align-items: center;
    margin-top: 8px;
    margin-bottom: 0;
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
  .btn-wrap .btn-label {
    font-size: 0.68em;
    color: var(--secondary-text-color);
    line-height: 1;
    margin-top: -2px;
  }
  .btn-wrap.disabled .btn-label {
    color: var(--disabled-text-color, rgba(0,0,0,0.26));
  }

  /* ── Standard / Customise tab strip ── */
  .tab-strip {
    display: flex;
    border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.12));
  }
  .tab {
    flex: 1;
    padding: 8px 0;
    font-size: 0.85em;
    font-weight: 600;
    font-family: inherit;
    text-align: center;
    cursor: pointer;
    background: none;
    border: none;
    outline: none;
    color: var(--secondary-text-color);
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    transition: color 0.15s, border-color 0.15s;
  }
  .tab.active {
    color: var(--primary-color);
    border-bottom-color: var(--primary-color);
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
    background: var(--primary-color);
    margin: 0 4px;
    border-radius: 1px;
    pointer-events: none;
  }
  .room-color-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
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
    /* background applied via inline style using room colour */
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
    background: var(--primary-color);
    border-color: var(--primary-color);
    color: var(--text-primary-color, #fff);
  }
  .icon-btn.selected ha-icon {
    color: var(--text-primary-color, #fff);
  }
  .icon-btn.disabled {
    opacity: 0.35;
    pointer-events: none;
  }
  .icon-btn ha-icon { --mdc-icon-size: 22px; color: var(--primary-text-color); }
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

function _pillClass(activity, statusLabel) {
  if (statusLabel === "Locating") return "pill-locating";
  return `pill-${activity}`;
}

const _EDITOR_COMPANIONS = [
  { key: "battery_entity",       domain: "sensor",        suffix: "battery",       label: "Battery sensor" },
  { key: "cleaning_area_entity", domain: "sensor",        suffix: "cleaning_area", label: "Cleaning area sensor" },
  { key: "cleaning_time_entity", domain: "sensor",        suffix: "cleaning_time", label: "Cleaning time sensor" },
  { key: "current_room_entity",  domain: "sensor",        suffix: "current_room",  label: "Current room sensor" },
  { key: "cleaning_mode_entity", domain: "select",        suffix: "cleaning_mode", label: "Cleaning mode select" },
  { key: "water_level_entity",   domain: "select",        suffix: "water_level",   label: "Water level select" },
  { key: "error_entity",         domain: "binary_sensor", suffix: "error",         label: "Error binary sensor" },
  { key: "connectivity_entity",  domain: "binary_sensor", suffix: "connectivity",  label: "Connectivity binary sensor" },
  { key: "map_entity",           domain: "image",         suffix: "map",           label: "Map image entity" },
];

function _deriveCompanions(vacuumEntityId) {
  if (!vacuumEntityId) return {};
  const stem = vacuumEntityId.replace(/^vacuum\./, "");
  const result = {};
  for (const { key, domain, suffix } of _EDITOR_COMPANIONS) {
    result[key] = `${domain}.${stem}_${suffix}`;
  }
  return result;
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
    this._lastPreferMode = null;         // last robot-reported prefer_mode
    this._detailRoomId = null;           // string room_id when detail is open
    this._customiseSelected = new Set(); // selected room IDs in Customise mode
    this._customisePending = new Map();  // id → expected custom (optimistic) until HA confirms
    this._dragSrcId = null;              // room_id being dragged
  }

  setConfig(config) {
    if (!config.vacuum_entity) throw new Error("vacuum_entity is required");
    this._config = { ..._deriveCompanions(config.vacuum_entity), ...config };
    this._buildDOM();
  }

  set hass(hass) {
    if (!this._config) return;
    if (this._hass === hass) return;
    this._hass = hass;
    this._updateCard();
  }

  getCardSize() { return 6; }

  static getConfigElement() {
    return document.createElement("karcher-vacuum-card-editor");
  }

  disconnectedCallback() {
    if (this._canvas && this._canvasClickHandler) {
      this._canvas.removeEventListener("click", this._canvasClickHandler);
    }
  }

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

    // Top bar: name+pill (left) | stats (right)
    const topBar = _el("div", "top-bar");

    const topLeft = _el("div", "top-bar-left");
    this._nameEl = _el("div", "robot-name");
    this._stateEl = _el("div", "status-pill");
    topLeft.appendChild(this._nameEl);
    topLeft.appendChild(this._stateEl);
    topBar.appendChild(topLeft);

    const topRight = _el("div", "top-bar-right");
    this._statsEl = _el("div", "stats-line");
    topRight.appendChild(this._statsEl);
    topBar.appendChild(topRight);

    card.appendChild(topBar);

    // Map canvas + overlay badge
    this._mapContainer = _el("div", "map-container");
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
    this._canvasClickHandler = (e) => this._onCanvasClick(e);
    this._canvas.addEventListener("click", this._canvasClickHandler);
    this._badgeEl = _el("div", "map-badge");
    this._badgeEl.style.display = "none";
    this._mapContainer.appendChild(this._placeholderEl);
    this._mapContainer.appendChild(this._canvas);
    card.appendChild(this._mapContainer);

    card.appendChild(this._badgeEl);

    // Error alert
    this._errorEl = document.createElement("ha-alert");
    this._errorEl.setAttribute("alert-type", "error");
    this._errorEl.textContent = "Robot reported a fault";
    card.appendChild(this._errorEl);

    // Buttons row
    this._buttonsEl = _el("div", "buttons");
    card.appendChild(this._buttonsEl);

    card.appendChild(_el("div", "section-divider"));

    const tabStrip = _el("div", "tab-strip");
    this._tabStandard = _el("button", "tab active");
    this._tabStandard.textContent = "Standard";
    this._tabStandard.addEventListener("click", () => this._setCardMode("standard"));
    this._tabCustomise = _el("button", "tab");
    this._tabCustomise.textContent = "Customise";
    this._tabCustomise.addEventListener("click", () => this._setCardMode("customise"));
    tabStrip.appendChild(this._tabStandard);
    tabStrip.appendChild(this._tabCustomise);
    card.appendChild(tabStrip);

    // Standard settings panel — rebuilt each update by _updateSelectors
    this._standardSettingsEl = _el("div", "standard-settings");
    card.appendChild(this._standardSettingsEl);

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

    if (attr?.prefer_mode && attr.prefer_mode !== this._lastPreferMode) {
      this._lastPreferMode = attr.prefer_mode;
      this._applyMode(attr.prefer_mode);
    }

    if (this._prevActivity === "cleaning" && activity !== "cleaning") {
      this._selectedRooms.clear();
    }
    this._prevActivity = activity;

    // Name
    this._nameEl.textContent = attr.friendly_name || "Kärcher RCV5";

    // Status pill (with current room if available)
    const connEntity = this._config.connectivity_entity;
    const isOffline = activity === "unavailable" ||
      (connEntity && this._hass.states[connEntity]?.state === "off");
    let statusText, pillClass;
    if (isOffline) {
      statusText = "Offline";
      pillClass = "pill-offline";
    } else {
      statusText = attr.status_label || STATE_LABELS[activity] || activity;
      const roomEntity = this._config.current_room_entity;
      if (roomEntity) {
        const r = this._hass.states[roomEntity]?.state;
        if (r && r !== "unknown" && r !== "unavailable") statusText += ` · ${r}`;
      }
      pillClass = _pillClass(activity, attr.status_label);
    }
    this._stateEl.textContent = statusText;
    this._stateEl.className = `status-pill ${pillClass}`;

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
    this._standardSettingsEl.classList.toggle("busy-locked", busy);
    this._roomListEl.classList.toggle("busy-locked", busy);
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
    this._standardSettingsEl.style.display = mode === "standard" ? "" : "none";
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
    this._lastPreferMode = mode;
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
    const _clearIndicators = () =>
      listEl.querySelectorAll(".drop-indicator").forEach(d => d.remove());

    listEl.ondragover = (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      let el = e.target;
      while (el && el !== listEl) {
        if (el.dataset && el.dataset.roomId && el.dataset.roomId !== this._dragSrcId) {
          _clearIndicators();
          el.parentNode.insertBefore(_el("div", "drop-indicator"), el);
          break;
        }
        el = el.parentNode;
      }
    };
    listEl.ondrop = (e) => {
      e.preventDefault();
      _clearIndicators();
      const srcId = this._dragSrcId;
      let el = e.target;
      while (el && el !== listEl) {
        if (el.dataset && el.dataset.roomId) { _reorder(srcId, el.dataset.roomId); break; }
        el = el.parentNode;
      }
    };
    listEl.ondragleave = (e) => {
      if (!listEl.contains(e.relatedTarget)) _clearIndicators();
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
        _clearIndicators();
      });

      // ── Drag handle ────────────────────────────────────────────────────
      const handle = _el("span", "room-drag-handle");
      handle.textContent = "⠿";
      handle.title = "Drag to reorder";
      row.appendChild(handle);

      // ── Checkbox: persists selection via check field + updates map ──────
      const roomColor = _roomColor(room.color_id);
      const isSelected = this._customiseSelected.has(id);
      const check = _el("div", `room-check${isSelected ? " on" : ""}`);
      check.style.borderColor = roomColor;
      if (isSelected) check.style.background = roomColor;
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
        ],
        (val) => this._setRoomPref(roomId, "repeat", val),
        busy
      )
    );

    // Mode — use same options as Standard (with labels); no per-option disabling for room prefs
    this._roomDetailEl.appendChild(
      this._makeIconBtnSection(
        "Cleaning mode", MODE_BY_INT[pref.mode],
        this._modeOptions(),
        (val) => this._setRoomPref(roomId, "mode", val),
        busy
      )
    );

    // Suction — pass null for fanSpeedList so no options are disabled (room prefs allow any)
    this._roomDetailEl.appendChild(
      this._makeIconBtnSection(
        "Suction", POWER_BY_INT[pref.power],
        this._suctionOptions(null),
        (val) => this._setRoomPref(roomId, "power", val),
        busy
      )
    );

    // Water level
    const modeKey = MODE_BY_INT[pref.mode];
    const waterDisabled = modeKey === "vacuum";
    this._roomDetailEl.appendChild(
      this._makeIconBtnSection(
        "Water level", WATER_BY_INT[pref.water],
        this._waterOptions(),
        (val) => this._setRoomPref(roomId, "water", val),
        waterDisabled || busy
      )
    );
  }

  // ── shared option builders ────────────────────────────────────────────────────

  _modeOptions(disabledSet = new Set()) {
    return [
      { value: "vacuum",         icon: "mdi:robot-vacuum", label: "Vacuum",    disabled: disabledSet.has("vacuum")         },
      { value: "vacuum_and_mop",                            label: "Vac & Mop", disabled: disabledSet.has("vacuum_and_mop") },
      { value: "mop",            icon: "mdi:water",        label: "Mop",       disabled: disabledSet.has("mop")            },
    ];
  }

  _suctionOptions(fanSpeedList = null) {
    const all = ["silent", "standard", "medium", "turbo"];
    return [
      { value: "silent",   icon: "mdi:fan-off",     label: "Silent",   disabled: fanSpeedList !== null && !fanSpeedList.includes("silent")   },
      { value: "standard", icon: "mdi:fan-speed-2", label: "Standard", disabled: fanSpeedList !== null && !fanSpeedList.includes("standard") },
      { value: "medium",   icon: "mdi:fan-speed-3", label: "Medium",   disabled: fanSpeedList !== null && !fanSpeedList.includes("medium")   },
      { value: "turbo",    icon: "mdi:fan",         label: "Turbo",    disabled: fanSpeedList !== null && !fanSpeedList.includes("turbo")    },
    ];
  }

  _waterOptions() {
    return [
      { value: "low",    icon: "mdi:water-minus" },
      { value: "medium", icon: "mdi:water"       },
      { value: "high",   icon: "mdi:water-plus"  },
    ];
  }

  _makeIconBtnSection(label, currentValue, options, onChange, disabled = false) {
    const section = _el("div", "detail-section");
    const labelEl = _el("div", "detail-label");
    labelEl.textContent = label;
    section.appendChild(labelEl);
    const row = _el("div", "icon-btn-row");
    for (const opt of options) {
      const optDisabled = disabled || !!opt.disabled;
      const btn = _el("div", `icon-btn${opt.value === currentValue ? " selected" : ""}${optDisabled ? " disabled" : ""}`);
      if (opt.icon) btn.appendChild(_icon(opt.icon));
      if (opt.label) {
        const lbl = _el("span", "btn-label");
        lbl.textContent = opt.label;
        btn.appendChild(lbl);
      }
      if (!optDisabled) {
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
    this._drawCurPath(ctx, attr);
    this._drawRoomLabels(ctx, attr.room_map || {}, attr);
    this._drawCharger(ctx, attr);
    this._drawRobot(ctx, attr);
  }

  _drawCurPath(ctx, attr) {
    const pts = attr.cur_path_px;
    const imgSize = attr.map_image_size;
    if (!pts || pts.length < 4 || !imgSize) return;

    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const lineW = Math.max(1, imgSize.cell_size * scaleX * 0.6);

    ctx.save();
    ctx.strokeStyle = "#ffa000";
    ctx.lineWidth = lineW;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(pts[0] * scaleX, pts[1] * scaleY);
    for (let i = 2; i < pts.length; i += 2) {
      ctx.lineTo(pts[i] * scaleX, pts[i + 1] * scaleY);
    }
    ctx.stroke();
    ctx.restore();
  }

  _drawCharger(ctx, attr) {
    const cp = attr.charger_px;
    const imgSize = attr.map_image_size;
    if (!cp || !imgSize) return;

    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const cx = cp.x * scaleX;
    const cy = cp.y * scaleY;
    const r = Math.max(6, imgSize.cell_size * scaleX * 3.5);

    // Outer teal circle
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = "#4db6c4";
    ctx.fill();

    // White inner ring
    ctx.beginPath();
    ctx.arc(cx, cy, r * 0.55, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.fill();
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
    const cellH = cs * scaleY;

    if (this._cardMode === "customise") {
      for (const [id, room] of Object.entries(roomMap)) {
        const cells = room.cells;
        if (!cells || cells.length === 0) continue;

        if (this._customiseSelected.has(id)) {
          ctx.fillStyle = "rgba(33,150,243,0.35)";
          for (const [row, colStart, runLen] of cells) {
            ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
          }
        }
      }
    } else {
      // Standard mode: highlight active room during cleaning; dim-yellow for queued rooms.
      const vacActivity = this._hass?.states[this._config?.vacuum_entity]?.state;
      const isCleaning = vacActivity === "cleaning" || vacActivity === "paused";
      let activeRoomId = null;
      if (isCleaning && this._config.current_room_entity) {
        const curName = this._hass.states[this._config.current_room_entity]?.state;
        if (curName && curName !== "unknown" && curName !== "unavailable") {
          activeRoomId = Object.entries(roomMap).find(([, r]) => r.name === curName)?.[0] ?? null;
        }
      }

      for (const [id, room] of Object.entries(roomMap)) {
        const cells = room.cells;
        if (!cells || cells.length === 0) continue;
        let fill = null;
        if (id === activeRoomId) {
          fill = "rgba(33, 150, 243, 0.15)";
        } else if (this._selectedRooms.has(id)) {
          fill = "rgba(33,150,243,0.35)";
        }
        if (!fill) continue;
        ctx.fillStyle = fill;
        for (const [row, colStart, runLen] of cells) {
          ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
        }
      }
    }
  }

  _drawRoomLabels(ctx, roomMap, attr) {
    if (this._cardMode !== "customise") return;
    const imgSize = attr?.map_image_size;
    if (!imgSize) return;
    const prefs = attr?.room_preferences || {};
    const scaleX = this._canvas.width / imgSize.width;
    const scaleY = this._canvas.height / imgSize.height;
    const cs = imgSize.cell_size || 1;

    for (const [id, room] of Object.entries(roomMap)) {
      const cells = room.cells;
      if (!cells || cells.length === 0) continue;
      const pref = prefs[id];
      if (!pref) continue;

      let minRow = Infinity, maxRow = -Infinity, minCol = Infinity, maxCol = -Infinity;
      for (const [row, colStart, runLen] of cells) {
        if (row < minRow) minRow = row;
        if (row > maxRow) maxRow = row;
        if (colStart < minCol) minCol = colStart;
        const colEnd = colStart + runLen * cs;
        if (colEnd > maxCol) maxCol = colEnd;
      }

      const cx = ((minCol + maxCol) / 2) * scaleX;
      const cy = ((minRow + maxRow) / 2) * scaleY;
      const repeatSym = ["×1", "×2"][pref.repeat] || "×1";
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
    const snapCol = Math.floor(px / cs) * cs;
    const snapRow = Math.floor(py / cs) * cs;

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
    if (Object.keys(roomMap).length === 0 || isBusy) {
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
    const blocks = [];

    // Battery block (first)
    const battEntity = this._config.battery_entity;
    if (battEntity) {
      const b = this._hass.states[battEntity];
      if (b && b.state !== "unknown" && b.state !== "unavailable") {
        const pct = parseInt(b.state, 10);
        const block = _el("div", "stat-block");
        const val = _el("span", "stat-value");
        val.textContent = `${pct}%`;
        const lbl = _el("span", "stat-label");
        lbl.textContent = "Battery";
        block.appendChild(val);
        block.appendChild(lbl);
        blocks.push(block);
      }
    }

    // Area block
    const ae = this._config.cleaning_area_entity;
    if (ae) {
      const a = this._hass.states[ae];
      if (a && a.state !== "unknown" && a.state !== "unavailable") {
        const v = parseFloat(a.state);
        if (!isNaN(v) && v > 0) {
          const block = _el("div", "stat-block");
          const val = _el("span", "stat-value");
          val.textContent = `${v.toFixed(1)} m²`;
          const lbl = _el("span", "stat-label");
          lbl.textContent = "Last run";
          block.appendChild(val);
          block.appendChild(lbl);
          blocks.push(block);
        }
      }
    }

    // Duration block
    const te = this._config.cleaning_time_entity;
    if (te) {
      const t = this._hass.states[te];
      if (t && t.state !== "unknown" && t.state !== "unavailable" && t.state !== "0") {
        const block = _el("div", "stat-block");
        const val = _el("span", "stat-value");
        val.textContent = `${t.state} min`;
        const lbl = _el("span", "stat-label");
        lbl.textContent = "Duration";
        block.appendChild(val);
        block.appendChild(lbl);
        blocks.push(block);
      }
    }

    for (const block of blocks) this._statsEl.appendChild(block);
    this._statsEl.style.display = blocks.length ? "" : "none";
  }

  _updateSelectors(attr) {
    if (this._cardMode !== "standard") return;

    const fanSpeed = attr.fan_speed;
    const fanSpeedList = attr.fan_speed_list || [];
    const modeEntityId = this._config.cleaning_mode_entity;
    const modeState = modeEntityId ? this._hass.states[modeEntityId] : null;
    const waterEntityId = this._config.water_level_entity;
    const waterState = waterEntityId ? this._hass.states[waterEntityId] : null;
    const busy = this._isBusy(attr.state);

    this._standardSettingsEl.textContent = "";

    // Mode
    if (modeState) {
      const disabledOpts = new Set(modeState.attributes.disabled_options || []);
      this._standardSettingsEl.appendChild(
        this._makeIconBtnSection(
          "Cleaning mode", modeState.state,
          this._modeOptions(disabledOpts),
          (val) => this._hass.callService("select", "select_option", { entity_id: modeEntityId, option: val }),
          busy
        )
      );
    }

    // Suction
    if (fanSpeed !== undefined && fanSpeed !== null) {
      this._standardSettingsEl.appendChild(
        this._makeIconBtnSection(
          "Suction", fanSpeed,
          this._suctionOptions(fanSpeedList),
          (val) => this._hass.callService("vacuum", "set_fan_speed", { entity_id: this._config.vacuum_entity, fan_speed: val }),
          busy
        )
      );
    }

    // Water level — always show if entity is configured; disable when mode is vacuum or mop unavailable
    if (waterEntityId) {
      const waterUnavailable = !waterState || waterState.state === "unavailable" || waterState.state === "unknown";
      const waterDisabled = waterUnavailable || !modeState?.state || modeState.state === "vacuum";
      const currentWater = waterUnavailable ? null : waterState.state;
      this._standardSettingsEl.appendChild(
        this._makeIconBtnSection(
          "Water level", currentWater,
          this._waterOptions(),
          (val) => this._hass.callService("select", "select_option", { entity_id: waterEntityId, option: val }),
          waterDisabled || busy
        )
      );
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
    if (cls === "disabled") {
      btn.disabled = true;
    } else {
      btn.addEventListener("click", () => this[method]());
    }
    wrap.appendChild(btn);
    const label = document.createElement("span");
    label.className = "btn-label";
    label.textContent = def.label;
    wrap.appendChild(label);
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


const _EDITOR_CSS = `
  :host { display: block; }
  .field { margin-bottom: 16px; }
  .field label {
    display: block;
    font-size: 0.85em;
    color: var(--secondary-text-color);
    margin-bottom: 4px;
  }
  .field label.required::after { content: " *"; color: var(--error-color, red); }
  details { margin-top: 12px; }
  summary {
    cursor: pointer;
    font-size: 0.85em;
    color: var(--primary-color);
    font-weight: 600;
    user-select: none;
    padding: 4px 0;
  }
  .advanced { padding-top: 8px; }
`;

class KarcherVacuumCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._built = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._built) this._syncPickers();
  }

  setConfig(config) {
    this._config = { ...config };
    if (this._built) {
      this._syncPickers();
    } else {
      this._build();
    }
  }

  _build() {
    this._built = true;
    const shadow = this.shadowRoot;
    shadow.innerHTML = "";
    const style = document.createElement("style");
    style.textContent = _EDITOR_CSS;
    shadow.appendChild(style);

    // Required: vacuum entity
    this._vacuumPicker = this._makePicker("vacuum_entity");
    const vacField = _el("div", "field");
    const vacLabel = document.createElement("label");
    vacLabel.textContent = "Vacuum entity";
    vacLabel.className = "required";
    vacField.appendChild(vacLabel);
    vacField.appendChild(this._vacuumPicker);
    shadow.appendChild(vacField);

    // Optional overrides inside a <details>
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Advanced — entity overrides";
    details.appendChild(summary);

    const advanced = _el("div", "advanced");
    this._companionPickers = {};
    for (const { key, label } of _EDITOR_COMPANIONS) {
      const field = _el("div", "field");
      const lbl = document.createElement("label");
      lbl.textContent = label;
      const picker = this._makePicker(key);
      this._companionPickers[key] = picker;
      field.appendChild(lbl);
      field.appendChild(picker);
      advanced.appendChild(field);
    }
    details.appendChild(advanced);
    shadow.appendChild(details);

    this._syncPickers();
  }

  _makePicker(configKey) {
    const picker = document.createElement("ha-entity-picker");
    picker.setAttribute("allow-custom-entity", "");
    picker.addEventListener("value-changed", (e) => {
      const val = e.detail.value;
      const derived = _deriveCompanions(
        configKey === "vacuum_entity" ? val : this._config.vacuum_entity
      );
      const newConfig = { ...this._config };
      newConfig[configKey] = val || undefined;
      // When vacuum changes, clear companion overrides that still match the old
      // derived values so they re-derive from the new stem automatically.
      if (configKey === "vacuum_entity") {
        const oldDerived = _deriveCompanions(this._config.vacuum_entity);
        for (const { key } of _EDITOR_COMPANIONS) {
          if (!newConfig[key] || newConfig[key] === oldDerived[key]) {
            delete newConfig[key];
          }
        }
      }
      // Remove undefined keys
      for (const k of Object.keys(newConfig)) {
        if (newConfig[k] === undefined) delete newConfig[k];
      }
      this._config = newConfig;
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
    });
    return picker;
  }

  _syncPickers() {
    if (!this._built) return;
    if (this._hass) this._vacuumPicker.hass = this._hass;
    this._vacuumPicker.value = this._config.vacuum_entity || "";

    const derived = _deriveCompanions(this._config.vacuum_entity);
    for (const { key } of _EDITOR_COMPANIONS) {
      const picker = this._companionPickers[key];
      if (this._hass) picker.hass = this._hass;
      picker.value = this._config[key] || derived[key] || "";
    }
  }
}

customElements.define("karcher-vacuum-card-editor", KarcherVacuumCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "karcher-vacuum-card",
  name: "Kärcher Vacuum Card",
  description: "Map, room selection, controls for the Kärcher RCV5",
  preview: false,
  version: VERSION,
});
