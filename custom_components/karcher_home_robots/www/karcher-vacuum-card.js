// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no build toolchain required.

const VERSION = "1.14.0";

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

const _CSS = `
  :host {
    display: flex;
    flex-direction: column;
    gap: 8px;
    --rcv-accent: #FFD400;
    --rcv-accent-deep: #E8BE00;
    --rcv-accent-text: #1a1a1a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, Helvetica, Arial, sans-serif;
  }

  ha-card {
    padding: 16px;
    box-sizing: border-box;
    overflow: hidden;
    box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.12));
  }

  /* ── top bar: name+status (left) | battery (right) ── */
  .top-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }
  .top-bar-left {
    display: flex;
    flex-direction: column;
    gap: 5px;
    min-width: 0;
    flex: 1;
  }
  .top-bar-right {
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }

  /* ── robot name ── */
  .robot-name {
    font-weight: 800;
    font-size: 1.1em;
    letter-spacing: -0.02em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--primary-text-color);
  }

  /* ── status row: dot + label ── */
  .status-row {
    display: flex;
    align-items: center;
    gap: 7px;
  }
  .status-dot {
    position: relative;
    display: inline-flex;
    width: 10px;
    height: 10px;
    flex-shrink: 0;
  }
  .status-dot-inner {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--secondary-text-color);
  }
  .status-dot-ping {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: inherit;
    opacity: 0;
  }
  @media (prefers-reduced-motion: no-preference) {
    .status-dot.pinging .status-dot-ping {
      animation: rcv-ping 1.6s cubic-bezier(0,0,.2,1) infinite;
    }
  }
  @keyframes rcv-ping {
    0%   { transform: scale(1); opacity: 0.75; }
    100% { transform: scale(2.5); opacity: 0; }
  }
  .status-dot.dot-cleaning .status-dot-inner,
  .status-dot.dot-cleaning .status-dot-ping { background: var(--rcv-accent); }
  .status-dot.dot-returning .status-dot-inner,
  .status-dot.dot-returning .status-dot-ping { background: var(--primary-color); }
  .status-dot.dot-paused .status-dot-inner   { background: var(--warning-color, #ff9800); }
  .status-dot.dot-docked .status-dot-inner,
  .status-dot.dot-idle .status-dot-inner     { background: var(--success-color, #4caf50); }
  .status-dot.dot-error .status-dot-inner    { background: var(--error-color, #f44336); }
  .status-dot.dot-offline .status-dot-inner  { background: var(--disabled-color, #9e9e9e); }

  .status-label {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--secondary-text-color);
  }
  .status-label.label-cleaning { color: var(--rcv-accent-deep); }
  .status-label.label-paused   { color: var(--warning-color, #ff9800); }
  .status-label.label-returning,
  .status-label.label-locating { color: var(--primary-color); }
  .status-label.label-docked,
  .status-label.label-idle     { color: var(--success-color, #4caf50); }
  .status-label.label-error    { color: var(--error-color, #f44336); }
  .status-label.label-offline  { color: var(--disabled-color, #9e9e9e); }

  /* ── battery glyph ── */
  .battery-wrap {
    display: inline-flex;
    align-items: center;
    gap: 7px;
  }
  .battery-glyph {
    position: relative;
    width: 28px;
    height: 14px;
    border: 2px solid var(--secondary-text-color);
    border-radius: 3px;
    flex-shrink: 0;
  }
  .battery-glyph::after {
    content: "";
    position: absolute;
    right: -5px;
    top: 50%;
    transform: translateY(-50%);
    width: 3px;
    height: 6px;
    background: var(--secondary-text-color);
    border-radius: 0 2px 2px 0;
  }
  .battery-fill {
    position: absolute;
    left: 1.5px;
    top: 1.5px;
    bottom: 1.5px;
    border-radius: 1.5px;
    background: var(--rcv-accent-deep);
    transition: width 0.4s ease;
  }
  .battery-fill.fill-charging { background: var(--success-color, #4caf50); }
  .battery-fill.fill-low      { background: var(--error-color, #f44336); }
  .battery-pct {
    font-size: 17px;
    font-weight: 700;
    color: var(--primary-text-color);
    font-variant-numeric: tabular-nums;
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }
  .battery-bolt {
    display: none;
    color: var(--success-color, #4caf50);
    --mdc-icon-size: 14px;
  }
  .battery-bolt.visible { display: inline-flex; }

  /* ── last-run stat strip ── */
  .stats-line {
    display: flex;
    gap: 12px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .stat-block {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .stat-label-header {
    display: flex;
    align-items: center;
    gap: 3px;
    font-size: 11.5px;
    font-weight: 500;
    color: var(--disabled-text-color, rgba(0,0,0,0.4));
  }
  .stat-label-header ha-icon {
    display: inline-flex;
    --mdc-icon-size: 12px;
    flex-shrink: 0;
  }
  .stat-value {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums;
  }

  /* ── error ── */
  ha-alert {
    display: none;
    margin-bottom: 0;
  }
  ha-alert.visible {
    display: block;
  }

  /* ── map chip button (clear/select all) ── */
  .map-chip-btn {
    background: var(--secondary-background-color);
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    color: var(--secondary-text-color);
    font-size: 12px;
    font-weight: 700;
    font-family: inherit;
    padding: 6px 11px;
    border-radius: 9px;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  .map-chip-btn:disabled {
    opacity: 0.45;
    cursor: default;
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
    .map-placeholder.map-loading { animation: none; }
  }
  @keyframes map-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .map-badge {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--secondary-text-color);
    padding: 8px 4px 2px;
  }
  .map-badge-icon {
    --mdc-icon-size: 15px;
    color: var(--rcv-accent-deep);
  }

  /* ── control buttons ── */
  .buttons {
    display: flex;
    align-items: flex-start;
    justify-content: space-around;
    margin-top: 0;
    margin-bottom: 0;
    gap: 6px;
  }
  .btn-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    border: none;
    background: none;
    font-family: inherit;
    cursor: pointer;
    padding: 0;
  }
  .btn-wrap:disabled,
  .btn-wrap.disabled {
    cursor: default;
  }
  .btn-circle {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--secondary-background-color);
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    transition: transform 0.12s ease, background 0.15s;
    --mdc-icon-size: 24px;
    color: var(--secondary-text-color);
  }
  .btn-wrap.primary .btn-circle {
    background: var(--rcv-accent);
    border: none;
    color: var(--rcv-accent-text);
    box-shadow: 0 6px 18px color-mix(in srgb, var(--rcv-accent) 55%, transparent);
  }
  .btn-wrap.danger .btn-circle {
    color: var(--error-color, #f44336);
  }
  .btn-wrap.disabled .btn-circle,
  .btn-wrap:disabled .btn-circle {
    background: var(--secondary-background-color);
    border: 1px solid var(--divider-color, rgba(0,0,0,0.12));
    color: var(--disabled-text-color, rgba(0,0,0,0.26));
    box-shadow: none;
    opacity: 0.55;
  }
  @media (prefers-reduced-motion: no-preference) {
    .btn-wrap:not(.disabled):not(:disabled):active .btn-circle {
      transform: scale(0.93);
    }
  }
  .btn-wrap .btn-label {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--secondary-text-color);
    line-height: 1;
    white-space: nowrap;
  }
  .btn-wrap.disabled .btn-label,
  .btn-wrap:disabled .btn-label {
    color: var(--disabled-text-color, rgba(0,0,0,0.26));
  }
  .btn-wrap.primary .btn-label {
    color: var(--primary-text-color);
  }

  /* ── Standard / Customise mode row (segmented pill + helper text) ── */
  .tab-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 14px;
  }
  .tab-helper {
    font-size: 12px;
    font-weight: 600;
    color: var(--secondary-text-color);
    white-space: nowrap;
    flex-shrink: 0;
  }

  /* ── busy banner ── */
  .busy-banner {
    display: none;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    margin-bottom: 10px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--rcv-accent) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--rcv-accent) 30%, transparent);
  }
  .busy-banner.visible { display: flex; }
  .busy-banner ha-icon {
    --mdc-icon-size: 15px;
    color: var(--rcv-accent-deep);
    flex-shrink: 0;
  }
  .busy-banner-text {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--secondary-text-color);
  }

  /* ── Standard settings — mode, suction, water ── */
  .standard-settings {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /* ── field rows for standard panel ── */
  .field-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 0;
    border-bottom: 1px solid var(--divider-color, rgba(0,0,0,0.08));
  }
  .field-row:last-child { border-bottom: none; }
  .field-row-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--secondary-text-color);
    white-space: nowrap;
    flex-shrink: 0;
    min-width: 7.5em;
  }
  .field-row-control { flex: 1; }

  /* ── segmented control ── */
  .segmented {
    display: flex;
    gap: 4px;
    background: var(--secondary-background-color);
    border-radius: 11px;
    padding: 4px;
    width: 100%;
    box-sizing: border-box;
  }
  .seg-btn {
    flex: 1;
    height: 30px;
    padding: 0 8px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    background: transparent;
    color: var(--secondary-text-color);
    font-weight: 600;
    font-size: 12px;
    font-family: inherit;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s;
    white-space: nowrap;
  }
  .seg-btn.active {
    background: var(--ha-card-background, var(--card-background-color));
    color: var(--primary-text-color);
    font-weight: 700;
    box-shadow: 0 1px 3px rgba(0,0,0,0.15);
  }
  .seg-btn ha-icon { --mdc-icon-size: 14px; }
  .seg-btn.active ha-icon { color: var(--rcv-accent-deep); }
  .seg-btn:disabled {
    opacity: 0.35;
    pointer-events: none;
    cursor: default;
  }
  .segmented.seg-disabled {
    opacity: 0.4;
    pointer-events: none;
  }

  /* ── Customise: room list ── */
  .room-list {
    display: none;
    flex-direction: column;
  }
  .room-list.visible { display: flex; }
  .room-row {
    background: var(--secondary-background-color);
    border: 1px solid transparent;
    border-radius: 12px;
    margin-bottom: 8px;
    transition: opacity 0.12s, border-color 0.15s;
  }
  .room-row:last-child { margin-bottom: 0; }
  .room-row.expanded { border-color: var(--divider-color, rgba(0,0,0,0.08)); }
  .room-row.dragging { opacity: 0.4; }
  .room-row.disabled-room { opacity: 0.55; }
  .room-row-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 11px 12px;
  }
  .drop-indicator {
    height: 2px;
    background: var(--rcv-accent-deep);
    margin: 0 4px;
    border-radius: 1px;
    pointer-events: none;
  }
  .room-drag-handle {
    cursor: grab;
    color: var(--disabled-text-color, rgba(0,0,0,0.35));
    font-size: 1.1em;
    padding: 0 2px;
    flex-shrink: 0;
    user-select: none;
  }
  .room-drag-handle:active { cursor: grabbing; }
  .room-color-dot {
    width: 12px;
    height: 12px;
    border-radius: 4px;
    flex-shrink: 0;
  }
  .room-row-select { cursor: pointer; }
  .room-text {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .room-text-inner { flex: 1; min-width: 0; }
  .room-name { font-weight: 700; font-size: 14px; color: var(--primary-text-color); }
  .room-summary {
    font-size: 11.5px;
    color: var(--secondary-text-color);
    font-weight: 600;
    margin-top: 2px;
  }
  .room-chevron {
    color: var(--disabled-text-color, rgba(0,0,0,0.35));
    font-size: 1.2em;
    flex-shrink: 0;
    transition: transform 0.2s;
  }
  .room-chevron.open { transform: rotate(90deg); }
  .room-toggle {
    width: 42px;
    height: 25px;
    border-radius: 13px;
    border: none;
    cursor: pointer;
    padding: 2px;
    background: var(--disabled-text-color, rgba(0,0,0,0.26));
    transition: background 0.2s;
    flex-shrink: 0;
  }
  .room-toggle.on { background: var(--rcv-accent); }
  .room-toggle-knob {
    display: block;
    width: 21px;
    height: 21px;
    border-radius: 50%;
    background: #fff;
    transform: translateX(0);
    transition: transform 0.2s;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  .room-toggle.on .room-toggle-knob { transform: translateX(17px); }
  .room-inline-detail {
    padding: 2px 14px 12px;
    border-top: 1px solid var(--divider-color, rgba(0,0,0,0.08));
  }
  .room-list-footer {
    font-size: 11.5px;
    color: var(--disabled-text-color, rgba(0,0,0,0.4));
    text-align: center;
    margin-top: 4px;
    font-weight: 500;
  }

  /* ── Settings lockout wrapper ── */
  .settings-body {
    display: flex;
    flex-direction: column;
  }
  .settings-body.busy-locked {
    pointer-events: none;
    opacity: 0.55;
  }

  .icon-btn-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .icon-btn {
    min-width: 52px;
    height: 52px;
    border: 1.5px solid var(--divider-color, rgba(0,0,0,0.15));
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    background: transparent;
    flex-direction: column;
    gap: 3px;
    padding: 0 10px;
    transition: background 0.15s, border-color 0.15s;
  }
  .icon-btn.selected {
    background: var(--rcv-accent);
    border-color: var(--rcv-accent);
    color: var(--rcv-accent-text);
  }
  .icon-btn.selected ha-icon { color: var(--rcv-accent-text); }
  .icon-btn.disabled {
    opacity: 0.35;
    pointer-events: none;
  }
  .icon-btn ha-icon { --mdc-icon-size: 22px; color: var(--primary-text-color); }
  .icon-btn .btn-label { font-size: 0.65em; font-weight: 600; }

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


const _EDITOR_COMPANIONS = [
  { key: "battery_entity",       domain: "sensor",        suffix: "battery",       label: "Battery sensor" },
  { key: "charging_entity",      domain: "binary_sensor", suffix: "charging",      label: "Charging binary sensor" },
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
    this._roomCheckboxHitAreas = [];     // [{id, x, y, size} in image-space] rebuilt each _drawRoomLabels
    this._lastSelectorKey = null;
    this._lastListKey = null;
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

    // ── Card 1: Status ───────────────────────────────────────────────────────
    const cardStatus = document.createElement("ha-card");

    // Top bar: name+status-row (left) | battery (right)
    const topBar = _el("div", "top-bar");

    const topLeft = _el("div", "top-bar-left");
    this._nameEl = _el("div", "robot-name");

    // Status row: dot + label
    const statusRow = _el("div", "status-row");
    this._dotEl = _el("span", "status-dot");
    this._dotInnerEl = _el("span", "status-dot-inner");
    this._dotPingEl = _el("span", "status-dot-ping");
    this._dotEl.appendChild(this._dotInnerEl);
    this._dotEl.appendChild(this._dotPingEl);
    this._stateEl = _el("span", "status-label");
    statusRow.appendChild(this._dotEl);
    statusRow.appendChild(this._stateEl);

    topLeft.appendChild(this._nameEl);
    topLeft.appendChild(statusRow);
    topBar.appendChild(topLeft);

    // Battery glyph (right side)
    const topRight = _el("div", "top-bar-right");
    this._battWrapEl = _el("span", "battery-wrap");
    this._battGlyphEl = _el("span", "battery-glyph");
    this._battFillEl = _el("span", "battery-fill");
    this._battGlyphEl.appendChild(this._battFillEl);
    this._battBoltEl = _icon("mdi:lightning-bolt");
    this._battBoltEl.className = "battery-bolt";
    this._battPctEl = _el("span", "battery-pct");
    this._battWrapEl.appendChild(this._battGlyphEl);
    this._battWrapEl.appendChild(this._battBoltEl);
    this._battWrapEl.appendChild(this._battPctEl);
    this._battWrapEl.style.display = "none";
    topRight.appendChild(this._battWrapEl);
    topBar.appendChild(topRight);

    cardStatus.appendChild(topBar);

    // Last-run stats strip (area + duration)
    this._statsEl = _el("div", "stats-line");
    cardStatus.appendChild(this._statsEl);

    shadow.appendChild(cardStatus);

    // ── Card 2: Map ──────────────────────────────────────────────────────────
    const cardMap = document.createElement("ha-card");

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
    // Map badge (icon + text left, chip button right)
    this._badgeEl = _el("div", "map-badge");
    this._badgeEl.style.display = "none";
    this._badgeIconEl = _icon("mdi:map-marker-radius");
    this._badgeIconEl.className = "map-badge-icon";
    this._badgeTextEl = document.createElement("span");
    this._mapChipBtn = _el("button", "map-chip-btn");
    this._mapChipBtn.textContent = "Select all";
    this._mapChipBtn.addEventListener("click", () => this._onMapChipClick());
    this._badgeEl.appendChild(this._badgeTextEl);
    this._badgeEl.appendChild(this._mapChipBtn);

    this._mapContainer.appendChild(this._placeholderEl);
    this._mapContainer.appendChild(this._canvas);
    cardMap.appendChild(this._mapContainer);

    cardMap.appendChild(this._badgeEl);

    // Error alert
    this._errorEl = document.createElement("ha-alert");
    this._errorEl.setAttribute("alert-type", "error");
    this._errorEl.textContent = "Robot reported a fault";
    cardMap.appendChild(this._errorEl);

    shadow.appendChild(cardMap);

    // ── Card 3: Controls ─────────────────────────────────────────────────────
    const cardControls = document.createElement("ha-card");

    // Buttons row
    this._buttonsEl = _el("div", "buttons");
    cardControls.appendChild(this._buttonsEl);

    shadow.appendChild(cardControls);

    // ── Card 4: Settings ─────────────────────────────────────────────────────
    const cardSettings = document.createElement("ha-card");

    // Busy banner (shown when cleaning/returning)
    this._busyBannerEl = _el("div", "busy-banner");
    const busyIcon = _icon("mdi:lock");
    this._busyBannerEl.appendChild(busyIcon);
    const busyText = _el("span", "busy-banner-text");
    busyText.textContent = "Locked while cleaning — pause to change settings";
    this._busyBannerEl.appendChild(busyText);
    cardSettings.appendChild(this._busyBannerEl);

    this._settingsBodyEl = _el("div", "settings-body");

    const tabRow = _el("div", "tab-row");
    this._tabPill = _el("div", "segmented");
    this._tabPill.style.width = "auto";
    this._tabStandard = _el("button", "seg-btn active");
    this._tabStandard.textContent = "Standard";
    this._tabStandard.addEventListener("click", () => this._setCardMode("standard"));
    this._tabCustomise = _el("button", "seg-btn");
    this._tabCustomise.textContent = "Customise";
    this._tabCustomise.addEventListener("click", () => this._setCardMode("customise"));
    this._tabPill.appendChild(this._tabStandard);
    this._tabPill.appendChild(this._tabCustomise);
    this._tabHelperEl = _el("span", "tab-helper");
    this._tabHelperEl.textContent = "Applies to all rooms";
    tabRow.appendChild(this._tabPill);
    tabRow.appendChild(this._tabHelperEl);
    this._settingsBodyEl.appendChild(tabRow);

    // Standard settings panel — rebuilt each update by _updateSelectors
    this._standardSettingsEl = _el("div", "standard-settings");
    this._settingsBodyEl.appendChild(this._standardSettingsEl);

    // Customise: room list view
    this._roomListEl = _el("div", "room-list");
    this._settingsBodyEl.appendChild(this._roomListEl);

    cardSettings.appendChild(this._settingsBodyEl);

    shadow.appendChild(cardSettings);
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

    // Status dot + label (with current room appended when cleaning)
    const connEntity = this._config.connectivity_entity;
    const isOffline = activity === "unavailable" ||
      (connEntity && this._hass.states[connEntity]?.state === "off");
    let statusText, dotClass, labelClass;
    if (isOffline) {
      statusText = "Offline";
      dotClass = "dot-offline";
      labelClass = "label-offline";
    } else {
      statusText = attr.status_label || STATE_LABELS[activity] || activity;
      const roomEntity = this._config.current_room_entity;
      if (activity === "cleaning" && roomEntity) {
        const r = this._hass.states[roomEntity]?.state;
        if (r && r !== "unknown" && r !== "unavailable") statusText += ` · ${r}`;
      }
      if (attr.status_label === "Locating") {
        dotClass = "dot-returning";
        labelClass = "label-locating";
      } else {
        dotClass = `dot-${activity}`;
        labelClass = `label-${activity}`;
      }
    }
    this._stateEl.textContent = statusText;
    this._stateEl.className = `status-label ${labelClass}`;
    const pinging = !isOffline && (activity === "cleaning" || activity === "returning");
    this._dotEl.className = `status-dot ${dotClass}${pinging ? " pinging" : ""}`;

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
  // room list and detail view so the only actions are pause/stop/dock
  // (which live in _buttonsEl and are gated by _updateButtons).
  _isBusy(activity) {
    return activity === "cleaning" || activity === "returning";
  }

  _updateBusyLock(activity) {
    const busy = this._isBusy(activity);
    this._busyBannerEl.classList.toggle("visible", busy);
    this._settingsBodyEl.classList.toggle("busy-locked", busy);
  }

  // ── Standard / Customise mode ─────────────────────────────────────────────────

  _applyMode(mode) {
    this._cardMode = mode;
    this._lastSelectorKey = null;
    this._lastListKey = null;
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
    this._roomListEl.classList.toggle("visible", isCustomise);

    if (isCustomise) {
      const roomMap = attr?.room_map || {};
      const prefs = attr?.room_preferences || {};
      const total = Object.keys(roomMap).length;
      const enabled = Object.keys(roomMap).filter(id => prefs[id]?.custom === true).length;
      this._tabHelperEl.textContent = `${enabled} of ${total} room${total !== 1 ? "s" : ""} on`;
    } else {
      this._tabHelperEl.textContent = "Applies to all rooms";
    }

    if (!isCustomise) return;
    this._renderList(attr);
  }

  _renderList(attr) {
    const roomMap = attr?.room_map || {};
    const prefs = attr?.room_preferences || {};

    const roomIds = Object.keys(roomMap).sort((a, b) => {
      const oa = prefs[a]?.order ?? 999;
      const ob = prefs[b]?.order ?? 999;
      return oa - ob;
    });

    // Mirror prefs into _customiseSelected so external changes propagate AND
    // toggling-off works on a single click. While a service call is in flight
    // the local optimistic state wins: _customisePending records the expected
    // value and is cleared once the persisted pref matches.
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

    const busy = this._isBusy(this._hass?.states[this._config?.vacuum_entity]?.state ?? attr?.state);

    // Dedup: avoid stomping optimistic per-room edits on every hass poll.
    // Key covers room order, per-room settings, enabled state, expanded row, busy.
    const listKey = roomIds.map(id => {
      const p = prefs[id];
      return `${id}:${p?.mode}:${p?.power}:${p?.water}:${p?.repeat}:${this._customiseSelected.has(id)}`;
    }).join("|") + `|exp:${this._detailRoomId}|busy:${busy}`;
    if (listKey === this._lastListKey) return;
    this._lastListKey = listKey;

    this._roomListEl.textContent = "";

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
      // device_id disambiguates when the account has more than one robot.
      const vacuumEntry = this._hass.entities?.[this._config.vacuum_entity];
      const serviceData = {
        room_order: newOrder.map(rid => parseInt(rid, 10)),
      };
      if (vacuumEntry?.device_id) serviceData.device_id = vacuumEntry.device_id;
      this._hass.callService("karcher_home_robots", "set_room_preference", serviceData);
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
      const isEnabled = this._customiseSelected.has(id);
      const isExpanded = this._detailRoomId === id;

      const row = _el("div", `room-row${isExpanded ? " expanded" : ""}${!isEnabled ? " disabled-room" : ""}`);
      row.dataset.roomId = id;
      row.draggable = true;

      row.addEventListener("dragstart", (e) => {
        const act = this._hass?.states[this._config.vacuum_entity]?.state;
        if (this._isBusy(act)) { e.preventDefault(); return; }
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

      // ── Row header (always visible) ────────────────────────────────────
      const header = _el("div", "room-row-header");
      header.draggable = false; // prevent inner elements from starting row drag

      // Drag handle
      const handle = _el("span", "room-drag-handle");
      handle.textContent = "⠿";
      handle.title = "Drag to reorder";
      header.appendChild(handle);

      // Color dot
      const roomColor = _roomColor(room.color_id);
      const colorDot = _el("span", "room-color-dot");
      colorDot.style.background = roomColor;
      header.appendChild(colorDot);

      // Text block + chevron — click to expand/collapse
      const text = _el("div", "room-text room-row-select");
      const textInner = _el("div", "room-text-inner");
      const nameEl = _el("span", "room-name");
      nameEl.textContent = room.name || id;
      textInner.appendChild(nameEl);
      if (pref) {
        const modeLabel = CLEANING_MODE_LABELS[MODE_BY_INT[pref.mode]] || "Vacuum";
        const repeatKey = REPEAT_BY_INT[pref.repeat] || "single";
        const repeatX = repeatKey === "double" ? "×2" : "×1";
        const summary = _el("div", "room-summary");
        summary.textContent = isExpanded ? "" : `${modeLabel} · ${repeatX}`;
        textInner.appendChild(summary);
      }
      text.appendChild(textInner);
      const chev = _el("span", `room-chevron${isExpanded ? " open" : ""}`);
      chev.textContent = "›";
      if (!isEnabled) chev.style.visibility = "hidden";
      text.appendChild(chev);
      text.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!isEnabled) return;
        if (this._isBusy(this._hass?.states[this._config.vacuum_entity]?.state)) return;
        this._detailRoomId = isExpanded ? null : id;
        this._lastListKey = null; // force rebuild
        this._renderList(attr);
      });
      header.appendChild(text);

      // Toggle switch (right side)
      const toggle = _el("button", `room-toggle${isEnabled ? " on" : ""}`);
      toggle.setAttribute("aria-label", isEnabled ? "Disable room" : "Enable room");
      const knob = _el("span", "room-toggle-knob");
      toggle.appendChild(knob);
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        if (this._isBusy(this._hass?.states[this._config.vacuum_entity]?.state)) return;
        const nowOn = !this._customiseSelected.has(id);
        if (nowOn) this._customiseSelected.add(id);
        else this._customiseSelected.delete(id);
        this._customisePending.set(id, nowOn);
        this._toggleRoomCustom(id, nowOn);
        this._drawMap(attr);
        this._lastListKey = null;
        this._renderList(attr);
      });
      header.appendChild(toggle);

      row.appendChild(header);

      // ── Inline detail (expanded only, and only when enabled) ───────────
      if (isExpanded && isEnabled && pref) {
        const modeKey = MODE_BY_INT[pref.mode];
        const waterDisabled = modeKey === "vacuum";
        const detail = _el("div", "room-inline-detail");

        detail.appendChild(this._makeFieldRow("Cleaning cycles",
          this._makeSegmented(
            [{ value: "single", label: "×1" }, { value: "double", label: "×2" }],
            REPEAT_BY_INT[pref.repeat], (val) => { this._setRoomPref(id, "repeat", val); this._lastListKey = null; }, busy)));

        detail.appendChild(this._makeFieldRow("Mode",
          this._makeSegmented(
            [
              { value: "vacuum",         icon: "mdi:robot-vacuum", label: "Vacuum"    },
              { value: "vacuum_and_mop", icon: "mdi:shimmer",      label: "Vac & Mop" },
              { value: "mop",            icon: "mdi:water",        label: "Mop"       },
            ],
            MODE_BY_INT[pref.mode], (val) => { this._setRoomPref(id, "mode", val); this._lastListKey = null; }, busy)));

        detail.appendChild(this._makeFieldRow("Suction",
          this._makeSegmented(
            [
              { value: "silent",   icon: "mdi:fan-off",     label: "Silent"   },
              { value: "standard", icon: "mdi:fan-speed-2", label: "Standard" },
              { value: "medium",   icon: "mdi:fan-speed-3", label: "Medium"   },
              { value: "turbo",    icon: "mdi:fan",         label: "Turbo"    },
            ],
            POWER_BY_INT[pref.power], (val) => { this._setRoomPref(id, "power", val); this._lastListKey = null; }, busy)));

        detail.appendChild(this._makeFieldRow("Water",
          this._makeSegmented(
            [
              { value: "low",    icon: "mdi:water-minus", label: "Low"    },
              { value: "medium", icon: "mdi:water",       label: "Medium" },
              { value: "high",   icon: "mdi:water-plus",  label: "High"   },
            ],
            WATER_BY_INT[pref.water], (val) => { this._setRoomPref(id, "water", val); this._lastListKey = null; }, waterDisabled || busy)));

        row.appendChild(detail);
      }

      this._roomListEl.appendChild(row);
    }

    // Footer hint
    const footer = _el("div", "room-list-footer");
    footer.textContent = "⠿ Drag to set cleaning order";
    this._roomListEl.appendChild(footer);
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
        const dpr = window.devicePixelRatio || 1;
        const rect = this._canvas.getBoundingClientRect();
        this._canvas.width = rect.width * dpr;
        this._canvas.height = rect.height * dpr;
        this._dpr = dpr;
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
    const dpr = this._dpr || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cssW = this._canvas.width / dpr;
    const cssH = this._canvas.height / dpr;
    ctx.clearRect(0, 0, cssW, cssH);
    ctx.drawImage(this._mapImg, 0, 0, cssW, cssH);
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

    const dpr = this._dpr || 1;
    const scaleX = (this._canvas.width / dpr) / imgSize.width;
    const scaleY = (this._canvas.height / dpr) / imgSize.height;
    const lineW = Math.max(1, imgSize.cell_size * scaleX * 0.66);

    ctx.save();
    ctx.globalAlpha = 0.55;
    ctx.strokeStyle = "#999";
    ctx.shadowColor = "#555";
    ctx.shadowBlur = 4;
    ctx.lineWidth = lineW;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    const x0 = pts[0] * scaleX, y0 = pts[1] * scaleY;
    ctx.moveTo(x0, y0);
    if (pts.length === 4) {
      ctx.lineTo(pts[2] * scaleX, pts[3] * scaleY);
    } else {
      let px = x0, py = y0;
      for (let i = 2; i < pts.length - 2; i += 2) {
        const cx = pts[i] * scaleX, cy = pts[i + 1] * scaleY;
        const nx = pts[i + 2] * scaleX, ny = pts[i + 3] * scaleY;
        const mx = (cx + nx) / 2, my = (cy + ny) / 2;
        ctx.quadraticCurveTo(cx, cy, mx, my);
        px = mx; py = my;
      }
      const last = pts.length - 2;
      ctx.lineTo(pts[last] * scaleX, pts[last + 1] * scaleY);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.restore();
  }

  _drawCharger(ctx, attr) {
    const cp = attr.charger_px;
    const imgSize = attr.map_image_size;
    if (!cp || !imgSize) return;

    const dpr = this._dpr || 1;
    const scaleX = (this._canvas.width / dpr) / imgSize.width;
    const scaleY = (this._canvas.height / dpr) / imgSize.height;
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

    const dpr = this._dpr || 1;
    const scaleX = (this._canvas.width / dpr) / imgSize.width;
    const scaleY = (this._canvas.height / dpr) / imgSize.height;
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

    const dpr = this._dpr || 1;
    const scaleX = (this._canvas.width / dpr) / imgSize.width;
    const scaleY = (this._canvas.height / dpr) / imgSize.height;
    const cs = imgSize.cell_size || 1;
    const cellH = cs * scaleY;

    if (this._cardMode === "customise") {
      for (const [id, room] of Object.entries(roomMap)) {
        const cells = room.cells;
        if (!cells || cells.length === 0) continue;

        if (this._customiseSelected.has(id)) {
          ctx.fillStyle = "rgba(255,212,0,0.55)";
          for (const [row, colStart, runLen] of cells) {
            ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
          }
        }
      }
    } else {
      // Standard mode: highlight active room during cleaning; accent tint for queued rooms.
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
          fill = "rgba(255,212,0,0.40)";
        } else if (this._selectedRooms.has(id)) {
          fill = "rgba(255,212,0,0.55)";
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
    const imgSize = attr?.map_image_size;
    if (!imgSize) return;
    const isCustomise = this._cardMode === "customise";
    const prefs = attr?.room_preferences || {};
    const dpr = this._dpr || 1;
    const scaleX = (this._canvas.width / dpr) / imgSize.width;
    const scaleY = (this._canvas.height / dpr) / imgSize.height;
    const cs = imgSize.cell_size || 1;

    // Rebuild per-frame so stale rooms don't leave phantom hit areas
    this._roomCheckboxHitAreas = [];

    for (const [id, room] of Object.entries(roomMap)) {
      const cells = room.cells;
      if (!cells || cells.length === 0) continue;

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

      let chipText;
      if (isCustomise) {
        const pref = prefs[id];
        if (!pref) continue;
        const repeatSym = ["×1", "×2"][pref.repeat] || "×1";
        const modeSym   = ["▽", "▽~", "~"][pref.mode] || "▽";
        const powerSym  = ["○", "◎", "◉", "●"][pref.power] || "◎";
        const modeKey   = MODE_BY_INT[pref.mode];
        const waterSym  = modeKey !== "vacuum" ? ([, "▿", "▾", "▼"][pref.water] || "") : "";
        const symLine   = [repeatSym, modeSym, powerSym, waterSym].filter(Boolean).join(" ");
        chipText = `${room.name || id}\n${symLine}`;
      } else {
        const areaLine = (room.area_m2 != null) ? `${room.area_m2} m²` : null;
        chipText = areaLine ? `${room.name || id}\n${areaLine}` : (room.name || id);
      }

      const isSelected = isCustomise
        ? this._customiseSelected.has(id)
        : this._selectedRooms.has(id);

      const fontSize = Math.max(16, Math.min(24, cs * scaleX * 2.1));
      const areaFontSize = fontSize * 0.75;
      ctx.save();
      ctx.font = `bold ${fontSize}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const lines = chipText.split("\n");
      const isNormalWithArea = !isCustomise && lines.length === 2;
      // Line heights: name line uses full fontSize, area line uses areaFontSize.
      const nameLineH = fontSize * 1.25;
      const areaLineH = areaFontSize * 1.25;
      const totalTextH = isNormalWithArea ? nameLineH + areaLineH : nameLineH * lines.length;
      // Measure text width per line, using the right font for each.
      const lineWidths = lines.map((l, i) => {
        if (isNormalWithArea && i === 1) ctx.font = `${areaFontSize}px sans-serif`;
        else ctx.font = `bold ${fontSize}px sans-serif`;
        return ctx.measureText(l).width;
      });
      ctx.font = `bold ${fontSize}px sans-serif`;
      const tw = Math.max(...lineWidths);
      const ph = totalTextH + fontSize * 0.4;

      // Inline checkbox circle on the left side of the pill
      const cbR = Math.max(7, Math.min(11, fontSize * 0.38));
      const cbGap = fontSize * 0.45; // gap between circle right edge and text
      const cbOffsetX = cbR + fontSize * 0.5; // distance from pill left edge to circle center
      // pw must fit: left padding + circle diameter + gap + text + right padding
      const pw = cbOffsetX + cbR + cbGap + tw + fontSize * 0.5;

      const pillX = cx - pw / 2;
      ctx.fillStyle = isSelected ? "#FFD400" : "rgba(255,255,255,0.92)";
      ctx.beginPath();
      ctx.roundRect(pillX, cy - ph / 2, pw, ph, ph / 2);
      ctx.fill();

      // Draw checkbox circle
      const cbCx = pillX + cbOffsetX;
      const cbCy = cy;
      ctx.beginPath();
      ctx.arc(cbCx, cbCy, cbR, 0, Math.PI * 2);
      if (isSelected) {
        ctx.fillStyle = "rgba(0,0,0,0.18)";
        ctx.fill();
        // Checkmark
        ctx.strokeStyle = "#1a1a1a";
        ctx.lineWidth = cbR * 0.28;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.beginPath();
        ctx.moveTo(cbCx - cbR * 0.30, cbCy);
        ctx.lineTo(cbCx - cbR * 0.08, cbCy + cbR * 0.28);
        ctx.lineTo(cbCx + cbR * 0.38, cbCy - cbR * 0.30);
        ctx.stroke();
      } else {
        ctx.fillStyle = "rgba(255,255,255,0.0)";
        ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,0.35)";
        ctx.lineWidth = cbR * 0.18;
        ctx.stroke();
      }

      // Text shifted right to leave room for the circle.
      // Name line: bold, dark. Area line (normal mode only): smaller, lighter.
      ctx.textAlign = "left";
      const textX = pillX + cbOffsetX + cbR + cbGap;
      const startY = cy - totalTextH / 2 + nameLineH / 2;
      ctx.font = `bold ${fontSize}px sans-serif`;
      ctx.fillStyle = "#1b1c1f";
      ctx.fillText(lines[0], textX, startY);
      if (isNormalWithArea) {
        ctx.font = `${areaFontSize}px sans-serif`;
        ctx.fillStyle = "rgba(60,60,60,0.55)";
        ctx.textAlign = "center";
        ctx.fillText(lines[1], textX + tw / 2, startY + nameLineH);
      } else {
        for (let i = 1; i < lines.length; i++) {
          ctx.fillText(lines[i], textX, startY + i * nameLineH);
        }
      }
      ctx.restore();

      // Hit area: the checkbox circle inside the pill, in image-space
      this._roomCheckboxHitAreas.push({
        id,
        x: (cbCx - cbR) / scaleX,
        y: (cbCy - cbR) / scaleY,
        w: (cbR * 2) / scaleX,
        h: (cbR * 2) / scaleY,
      });
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

    // Check checkbox hit areas first (stored in image-space to match px/py)
    let hitId = undefined;
    for (const cb of (this._roomCheckboxHitAreas || [])) {
      if (px >= cb.x && px < cb.x + cb.w && py >= cb.y && py < cb.y + cb.h) {
        hitId = cb.id;
        break;
      }
    }
    // Fall back to cell lookup
    if (hitId === undefined) {
      hitId = this._cellLookup.get(`${snapRow},${snapCol}`);
    }

    if (hitId !== undefined) {
      if (this._cardMode === "customise") {
        const nowOn = !this._customiseSelected.has(hitId);
        if (nowOn) this._customiseSelected.add(hitId);
        else this._customiseSelected.delete(hitId);
        this._customisePending.set(hitId, nowOn);
        this._toggleRoomCustom(hitId, nowOn);
        this._drawMap(attr);
        this._lastListKey = null;
        this._renderList(attr);
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

  _onMapChipClick() {
    const vacState = this._hass?.states[this._config?.vacuum_entity];
    if (!vacState) return;
    const attr = vacState.attributes;
    const roomMap = attr?.room_map || {};
    const roomIds = Object.keys(roomMap);
    if (roomIds.length === 0) return;

    if (this._cardMode === "customise") {
      const allEnabled = roomIds.every(id => this._customiseSelected.has(id));
      for (const id of roomIds) {
        const nowOn = !allEnabled;
        const wasOn = this._customiseSelected.has(id);
        if (nowOn === wasOn) continue;
        if (nowOn) this._customiseSelected.add(id);
        else this._customiseSelected.delete(id);
        this._customisePending.set(id, nowOn);
        this._toggleRoomCustom(id, nowOn);
      }
      this._lastListKey = null;
      this._renderList(attr);
    } else {
      const allSelected = roomIds.every(id => this._selectedRooms.has(id));
      if (allSelected) {
        this._selectedRooms.clear();
      } else {
        for (const id of roomIds) this._selectedRooms.add(id);
      }
    }
    this._updateSelectionHint(attr);
    this._drawMap(attr);
  }

  // ── UI helpers ────────────────────────────────────────────────────────────────

  _updateSelectionHint(attr) {
    const roomMap = attr?.room_map || {};
    const roomIds = Object.keys(roomMap);
    const vacState = this._hass?.states[this._config?.vacuum_entity];
    const activity = vacState?.state;
    const isBusy = activity === "cleaning" || activity === "returning" || activity === "paused";
    const isCustomise = this._cardMode === "customise";

    // Chip button: always visible when rooms exist; label flips on all-selected/enabled
    if (this._mapChipBtn) {
      const hasRooms = roomIds.length > 0;
      this._mapChipBtn.style.display = hasRooms ? "" : "none";
      this._mapChipBtn.disabled = isBusy || !hasRooms;
      const allOn = roomIds.length > 0 && roomIds.every(id =>
        isCustomise ? this._customiseSelected.has(id) : this._selectedRooms.has(id));
      this._mapChipBtn.textContent = allOn ? "Clear all" : "Select all";
    }

    if (roomIds.length === 0 || isBusy) {
      this._badgeEl.style.display = "none";
      return;
    }
    this._badgeEl.style.display = "";

    if (isCustomise) {
      const count = this._customiseSelected.size;
      if (count === 0) {
        this._badgeTextEl.textContent = "Tap a room to enable it";
      } else {
        const names = [...this._customiseSelected].map(id => roomMap[id]?.name || id);
        const preview = names.slice(0, 2).join(", ");
        const extra = count > 2 ? ` +${count - 2}` : "";
        this._badgeTextEl.textContent = `${count} room${count !== 1 ? "s" : ""} enabled · ${preview}${extra}`;
      }
    } else {
      if (this._selectedRooms.size === 0) {
        this._badgeTextEl.textContent = "Tap a room to select · cleans all if none selected";
      } else {
        const names = [...this._selectedRooms].map(id => roomMap[id]?.name || id);
        const count = this._selectedRooms.size;
        const preview = names.slice(0, 2).join(", ");
        const extra = count > 2 ? ` +${count - 2}` : "";
        this._badgeTextEl.textContent = `Cleaning ${count} room${count !== 1 ? "s" : ""} · ${preview}${extra}`;
      }
    }
  }

  _updateStats() {
    // Battery → header glyph
    const battEntity = this._config.battery_entity;
    const chargingEntity = this._config.charging_entity;
    if (battEntity) {
      const b = this._hass.states[battEntity];
      if (b && b.state !== "unknown" && b.state !== "unavailable") {
        const pct = parseInt(b.state, 10);
        const isCharging = chargingEntity
          ? this._hass.states[chargingEntity]?.state === "on"
          : false;
        const isLow = pct <= 20;
        const isFull = pct >= 100;
        const fillW = `clamp(3px, ${pct}%, calc(100% - 3px))`;
        this._battFillEl.style.width = fillW;
        this._battFillEl.className = "battery-fill" +
          (isCharging || isFull ? " fill-charging" : isLow ? " fill-low" : "");
        this._battBoltEl.classList.toggle("visible", isCharging);
        this._battPctEl.textContent = `${pct}%`;
        this._battWrapEl.style.display = "";
      } else {
        this._battWrapEl.style.display = "none";
      }
    } else {
      this._battWrapEl.style.display = "none";
    }

    // Last-run stat tiles: area + duration + finished
    this._statsEl.textContent = "";
    const blocks = [];

    const ae = this._config.cleaning_area_entity;
    if (ae) {
      const a = this._hass.states[ae];
      if (a && a.state !== "unknown" && a.state !== "unavailable") {
        const v = parseFloat(a.state);
        if (!isNaN(v) && v > 0) {
          blocks.push(this._makeStatBlock(`${v.toFixed(1)} m²`, "Area cleaned", "mdi:floor-plan"));
        }
      }
    }

    const te = this._config.cleaning_time_entity;
    if (te) {
      const t = this._hass.states[te];
      const vacActivity = this._hass.states[this._config.vacuum_entity]?.state;
      const isCleaning = vacActivity === "cleaning" || vacActivity === "returning" || vacActivity === "paused";
      if (t && t.state !== "unknown" && t.state !== "unavailable" && t.state !== "0") {
        blocks.push(this._makeStatBlock(`${t.state} min`, "Duration", "mdi:clock-outline"));
        if (!isCleaning && t.attributes?.finished_at) {
          const rel = this._relativeTime(t.attributes.finished_at);
          if (rel) blocks.push(this._makeStatBlock(rel, "Finished", "mdi:calendar-check-outline"));
        }
      }
    }

    for (const block of blocks) this._statsEl.appendChild(block);
    this._statsEl.style.display = blocks.length ? "" : "none";
  }

  _relativeTime(isoString) {
    const then = new Date(isoString);
    if (isNaN(then.getTime())) return null;
    const diffMs = Date.now() - then.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return "Just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH}h ago`;
    const diffD = Math.floor(diffH / 24);
    if (diffD === 1) return "Yesterday";
    if (diffD < 7) return `${diffD}d ago`;
    return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  _makeStatBlock(value, label, icon) {
    const block = _el("div", "stat-block");
    const hdr = _el("span", "stat-label-header");
    if (icon) hdr.appendChild(_icon(icon));
    const labelText = document.createElement("span");
    labelText.textContent = label;
    hdr.appendChild(labelText);
    const val = _el("span", "stat-value");
    val.textContent = value;
    block.appendChild(hdr);
    block.appendChild(val);  // inline: icon · label · value
    return block;
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

    const selectorKey = [
      fanSpeed, (fanSpeedList).join(","), modeState?.state,
      (modeState?.attributes?.disabled_options || []).join(","),
      waterState?.state, busy,
    ].join("|");
    if (selectorKey === this._lastSelectorKey) return;
    this._lastSelectorKey = selectorKey;

    this._standardSettingsEl.textContent = "";

    // Mode — segmented
    if (modeState) {
      const disabledOpts = new Set(modeState.attributes.disabled_options || []);
      const modeOpts = [
        { value: "vacuum",         icon: "mdi:robot-vacuum", label: "Vacuum",    disabled: disabledOpts.has("vacuum")         },
        { value: "vacuum_and_mop", icon: "mdi:shimmer",      label: "Vac & Mop", disabled: disabledOpts.has("vacuum_and_mop") },
        { value: "mop",            icon: "mdi:water",        label: "Mop",       disabled: disabledOpts.has("mop")            },
      ];
      this._standardSettingsEl.appendChild(
        this._makeFieldRow("Mode", this._makeSegmented(modeOpts, modeState.state,
          (val) => this._hass.callService("select", "select_option", { entity_id: modeEntityId, option: val }),
          busy))
      );
    }

    // Suction — segmented
    if (fanSpeed !== undefined && fanSpeed !== null) {
      const isMop = modeState?.state === "mop";
      const suctionOpts = [
        { value: "silent",   icon: "mdi:fan-off",     label: "Silent",   disabled: fanSpeedList.length > 0 && !fanSpeedList.includes("silent")   },
        { value: "standard", icon: "mdi:fan-speed-2", label: "Standard", disabled: fanSpeedList.length > 0 && !fanSpeedList.includes("standard") },
        { value: "medium",   icon: "mdi:fan-speed-3", label: "Medium",   disabled: fanSpeedList.length > 0 && !fanSpeedList.includes("medium")   },
        { value: "turbo",    icon: "mdi:fan",         label: "Turbo",    disabled: fanSpeedList.length > 0 && !fanSpeedList.includes("turbo")    },
      ];
      this._standardSettingsEl.appendChild(
        this._makeFieldRow("Suction", this._makeSegmented(suctionOpts, fanSpeed,
          (val) => this._hass.callService("vacuum", "set_fan_speed", { entity_id: this._config.vacuum_entity, fan_speed: val }),
          busy || isMop))
      );
    }

    // Water level — always show if entity configured; disable when mode=vacuum
    if (waterEntityId) {
      const waterUnavailable = !waterState || waterState.state === "unavailable" || waterState.state === "unknown";
      const isVacuum = modeState?.state === "vacuum";
      const waterDisabled = waterUnavailable || !modeState?.state || isVacuum;
      const currentWater = waterUnavailable ? null : waterState.state;
      const waterOpts = [
        { value: "low",    icon: "mdi:water-minus", label: "Low"    },
        { value: "medium", icon: "mdi:water",       label: "Medium" },
        { value: "high",   icon: "mdi:water-plus",  label: "High"   },
      ];
      this._standardSettingsEl.appendChild(
        this._makeFieldRow("Water", this._makeSegmented(waterOpts, currentWater,
          (val) => this._hass.callService("select", "select_option", { entity_id: waterEntityId, option: val }),
          busy || waterDisabled))
      );
    }
  }

  _makeFieldRow(label, control) {
    const row = _el("div", "field-row");
    const lbl = _el("span", "field-row-label");
    lbl.textContent = label;
    const ctrl = _el("div", "field-row-control");
    ctrl.appendChild(control);
    row.appendChild(lbl);
    row.appendChild(ctrl);
    return row;
  }

  _makeSegmented(options, currentValue, onChange, disabled = false) {
    const wrap = _el("div", `segmented${disabled ? " seg-disabled" : ""}`);
    const btns = [];
    for (const opt of options) {
      const optDisabled = disabled || !!opt.disabled;
      const btn = _el("button", `seg-btn${opt.value === currentValue ? " active" : ""}`);
      btn.disabled = optDisabled;
      if (opt.icon) btn.appendChild(_icon(opt.icon));
      btn.appendChild(document.createTextNode(opt.label));
      if (!optDisabled) btn.addEventListener("click", () => {
        btns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        onChange(opt.value);
      });
      btns.push(btn);
      wrap.appendChild(btn);
    }
    return wrap;
  }

  _updateButtons(activity) {
    this._buttonsEl.textContent = "";

    const isCleaning  = activity === "cleaning";
    const isPaused    = activity === "paused";
    const isReturning = activity === "returning";
    const isOffline   = activity === "unavailable";
    const canStop     = isCleaning || isPaused || isReturning;
    const canDock     = isCleaning || isPaused || activity === "idle";

    // Play/Pause/Resume button — primary filled
    const playIcon   = isCleaning ? "mdi:pause" : "mdi:play";
    const playLabel  = isCleaning ? "Pause" : (isPaused ? "Resume" : "Start");
    const playAction = isCleaning ? () => this._pause() : () => this._play();
    this._buttonsEl.appendChild(this._makeBtn(playIcon, playLabel, "primary", !isOffline, playAction));

    // Stop — danger tint, only enabled when canStop
    this._buttonsEl.appendChild(this._makeBtn("mdi:stop", "Stop", "danger", !isOffline && canStop, () => this._stop()));

    // Dock
    const dockLabel = activity === "docked" ? "Docked" : "Dock";
    this._buttonsEl.appendChild(this._makeBtn("mdi:home-import-outline", dockLabel, "secondary", !isOffline && canDock, () => this._dock()));
  }

  _makeBtn(icon, label, variant, enabled, onClick) {
    const wrap = _el("button", `btn-wrap ${enabled ? variant : "disabled"}`);
    if (!enabled) wrap.disabled = true;
    const circle = _el("span", "btn-circle");
    circle.appendChild(_icon(icon));
    wrap.appendChild(circle);
    const lbl = _el("span", "btn-label");
    lbl.textContent = label;
    wrap.appendChild(lbl);
    if (enabled) wrap.addEventListener("click", onClick);
    return wrap;
  }

  // ── actions ───────────────────────────────────────────────────────────────────

  _play() {
    const vacuumEntity = this._config.vacuum_entity;
    const roomIds = [...this._selectedRooms].map((id) => parseInt(id, 10));
    if (roomIds.length === 0) {
      // No selection → whole-home clean via the standard service.
      this._hass.callService("vacuum", "start", { entity_id: vacuumEntity });
      return;
    }
    // Start the selected rooms with explicit ids. app_segment_clean preserves
    // caller order, so sort into preference order here (previously the
    // coordinator reordered the selection in default_clean_room_ids()).
    //
    // Deliberately NOT set_room_selection + vacuum.start: vacuum.start must
    // stay whole-home for external callers. HAMH dispatches Apple Home's
    // "clean all rooms" as a parameterless vacuum.start, and a selection
    // pushed from here used to persist on the coordinator and turn that
    // into a single-room clean.
    const prefs = this._hass.states[vacuumEntity]?.attributes?.room_preferences || {};
    const ord = (id) => prefs[id]?.order ?? Number.MAX_SAFE_INTEGER;
    roomIds.sort((a, b) => ord(a) - ord(b));
    this._hass.callService("vacuum", "send_command", {
      entity_id: vacuumEntity,
      command: "app_segment_clean",
      params: roomIds,
    });
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
