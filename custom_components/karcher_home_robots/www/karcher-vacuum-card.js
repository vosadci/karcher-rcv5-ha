// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no CI build toolchain. Lit is vendored as a committed
// self-contained ESM bundle (./lit-core.js) — no runtime CDN/import-map needed.
//
// Migration in progress (strangler-fig): UI is being converted to Lit leaves
// one at a time. The leaves render into LIGHT DOM (createRenderRoot returns
// `this`) so they inherit the shell's _CSS sheet — they carry no `css` of their
// own. Data flows DOWN via properties; actions flow UP via dispatchEvent.

import { LitElement, html } from "./lit-core.js";

const VERSION = "1.18.0";
console.info(`%c karcher-vacuum-card %c ${VERSION} `, "color:#fff;background:#ffd400", "color:#ffd400;background:#333");

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

// Room colour palette — mirrors _ROOM_COLOR_TABLE in map_render.py (APK-verified).
// Index = (color_id - 1) % 5
const _ROOM_COLORS = [
  "#c9dcd2",  // color_id 1 — teal-green
  "#e9bac0",  // color_id 2 — pink
  "#e8e7e3",  // color_id 3 — off-white
  "#bddde0",  // color_id 4 — light blue
  "#b7b7b7",  // color_id 5 — grey
];
export function roomColor(colorId) {
  if (!colorId || colorId < 1) return _ROOM_COLORS[0];
  return _ROOM_COLORS[(colorId - 1) % _ROOM_COLORS.length];
}
const _roomColor = roomColor;

// Numeric wire values → option key (used to read room_preferences attribute)
const MODE_BY_INT   = { 0: "vacuum", 1: "vacuum_and_mop", 2: "mop" };
const POWER_BY_INT  = { 0: "silent", 1: "standard", 2: "medium", 3: "turbo" };
const REPEAT_BY_INT = { 0: "single", 1: "double" };
const WATER_BY_INT  = { 0: "low", 1: "medium", 2: "high" };

// Suction / water option → mdi icon (mirror the segment-control icons), used for
// the icon-only parts of the collapsed room-summary line in Customise mode.
const POWER_ICON_BY_KEY = { silent: "mdi:fan-off", standard: "mdi:fan-speed-2", medium: "mdi:fan-speed-3", turbo: "mdi:fan" };
const WATER_ICON_BY_KEY = { low: "mdi:water-minus", medium: "mdi:water", high: "mdi:water-plus" };
const _cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

const _CSS = `
  :host {
    display: block;
    container-type: inline-size;
    --rcv-accent: #FFD400;
    --rcv-accent-deep: #E8BE00;
    --rcv-accent-text: #1a1a1a;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, Helvetica, Arial, sans-serif;
  }

  .card-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* ── wide layout: Status/Control/Settings stacked left, Map right ── */
  @container (min-width: 680px) {
    .card-grid {
      display: grid;
      gap: 8px;
      grid-template-columns: 1fr 1fr;
      grid-template-rows: auto auto auto 1fr;
      grid-template-areas:
        "status   map"
        "control  map"
        "settings map"
        ".        map";
    }
    .card-status   { grid-area: status; }
    .card-control  { grid-area: control; }
    .card-settings { grid-area: settings; }
    .card-map      { grid-area: map; align-self: start; }
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
  .status-dot.dot-cleaning .status-dot-ping { background: var(--success-color, #4caf50); }
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
  .status-label.label-cleaning { color: var(--success-color, #4caf50); }
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
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
    gap: 10px;
    margin-top: 14px;
  }
  .stat-block {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px;
    border-radius: 14px;
    background: var(--secondary-background-color);
  }
  .stat-label-header {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: var(--disabled-text-color, rgba(0,0,0,0.4));
  }
  .stat-label-header ha-icon {
    display: inline-flex;
    --mdc-icon-size: 14px;
    flex-shrink: 0;
  }
  .stat-value {
    font-size: 17px;
    font-weight: 700;
    color: var(--primary-text-color);
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
  /* Compact strip (Suction · Water): inactive segments collapse to icon-only
     (the active one keeps its label) so the options fit the narrow card. */
  .segmented.seg-compact .seg-btn { min-width: 0; overflow: hidden; }
  .segmented.seg-compact .seg-btn:not(.active) .seg-label { display: none; }

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
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
    line-height: 1;
  }
  .room-summary-icon { --mdc-icon-size: 14px; display: block; }
  .room-summary-sep { opacity: 0.5; }
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

export function deriveCompanions(vacuumEntityId) {
  if (!vacuumEntityId) return {};
  const stem = vacuumEntityId.replace(/^vacuum\./, "");
  const result = {};
  for (const { key, domain, suffix } of _EDITOR_COMPANIONS) {
    result[key] = `${domain}.${stem}_${suffix}`;
  }
  return result;
}
const _deriveCompanions = deriveCompanions;

// ── Pure helpers extracted for unit testing (no DOM/canvas access) ────────────

export function isBusy(activity) {
  return activity === "cleaning" || activity === "returning";
}

// Wider than isBusy(): also covers "paused", for UI that should stay locked
// while a paused clean could still be resumed (selection hint, room-edit guard).
export function isOccupied(activity) {
  return isBusy(activity) || activity === "paused";
}

// Activity → enable/disable flags for the Play/Stop/Dock buttons. `offline`
// covers the connectivity-only outage window (robot unreachable but the vacuum
// entity still reports a cached activity) — the buttons must disable then too.
export function buttonStates(activity, offline = false) {
  const isCleaning  = activity === "cleaning";
  const isPaused    = activity === "paused";
  const isReturning = activity === "returning";
  const isOffline   = offline || activity === "unavailable";
  return {
    isCleaning,
    isPaused,
    isReturning,
    isOffline,
    canStop: isCleaning || isPaused || isReturning,
    canDock: isCleaning || isPaused || activity === "idle",
  };
}

// (canvasCssWidth/Height in device px, image size in px) → image→canvas factors.
export function canvasScale(canvasWidthPx, canvasHeightPx, imgSize, dpr = 1) {
  return {
    scaleX: (canvasWidthPx / dpr) / imgSize.width,
    scaleY: (canvasHeightPx / dpr) / imgSize.height,
  };
}

// Click coords (client space) → image-space pixel + cell-snapped row/col.
export function clientToImagePx(clientX, clientY, rect, imgSize) {
  const cs = imgSize.cell_size || 1;
  const px = Math.floor((clientX - rect.left) * (imgSize.width / rect.width));
  const py = Math.floor((clientY - rect.top) * (imgSize.height / rect.height));
  return {
    px,
    py,
    snapCol: Math.floor(px / cs) * cs,
    snapRow: Math.floor(py / cs) * cs,
  };
}

// Expand each room's RLE spans into a "row,col" → roomId lookup.
export function buildCellLookup(roomMap, cellSize) {
  const cs = cellSize || 1;
  const lookup = new Map();
  for (const [id, room] of Object.entries(roomMap || {})) {
    for (const [row, colStart, runLen] of (room.cells || [])) {
      for (let i = 0; i < runLen; i++) {
        lookup.set(`${row},${colStart + i * cs}`, id);
      }
    }
  }
  return lookup;
}

// Checkbox hit areas take priority over the cell lookup. Returns roomId|undefined.
export function hitTestRooms(px, py, snapRow, snapCol, checkboxHitAreas, cellLookup) {
  for (const cb of (checkboxHitAreas || [])) {
    if (px >= cb.x && px < cb.x + cb.w && py >= cb.y && py < cb.y + cb.h) {
      return cb.id;
    }
  }
  return cellLookup ? cellLookup.get(`${snapRow},${snapCol}`) : undefined;
}

// Image-space bounding box of a room's RLE cells (cs = cell_size).
export function roomBoundingBox(cells, cs = 1) {
  let minRow = Infinity, maxRow = -Infinity, minCol = Infinity, maxCol = -Infinity;
  for (const [row, colStart, runLen] of (cells || [])) {
    if (row < minRow) minRow = row;
    if (row > maxRow) maxRow = row;
    if (colStart < minCol) minCol = colStart;
    const colEnd = colStart + runLen * cs;
    if (colEnd > maxCol) maxCol = colEnd;
  }
  return { minRow, maxRow, minCol, maxCol };
}

export function roomCentroid(bbox) {
  return {
    cx: (bbox.minCol + bbox.maxCol) / 2,
    cy: (bbox.minRow + bbox.maxRow) / 2,
  };
}

// Room IDs sorted by persisted preference order (missing order sinks to 999).
export function parseRoomOrder(roomMap, prefs) {
  const p = prefs || {};
  return Object.keys(roomMap || {}).sort((a, b) => {
    const oa = p[a]?.order ?? 999;
    const ob = p[b]?.order ?? 999;
    return oa - ob;
  });
}

// ISO timestamp → short relative-time label, or null if unparseable.
export function relativeTime(isoString, now = Date.now()) {
  const then = new Date(isoString);
  if (isNaN(then.getTime())) return null;
  const diffMin = Math.floor((now - then.getTime()) / 60000);
  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD === 1) return "Yesterday";
  if (diffD < 7) return `${diffD}d ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Derive the last-run stat tiles from the area and time entity states. Always
// returns exactly 3 tiles (Area cleaned, Duration, Finished) so the card's
// stat strip has a stable layout; any tile with no usable data shows "-". ALL
// the branching lives here (entity missing, unknown/unavailable, NaN, area>0,
// time "0", and the finished-at tile only when not occupied) so it is
// unit-testable; the leaf just renders the returned [{ value, label, icon }]
// list and the shell only does the trivial hass lookups. `now` is threaded
// for deterministic tests.
export function deriveStatTiles(areaState, timeState, occupied, now = Date.now()) {
  const valid = (s) => s && s.state !== "unknown" && s.state !== "unavailable";

  let areaValue = "-";
  if (valid(areaState)) {
    const v = parseFloat(areaState.state);
    if (!isNaN(v) && v > 0) areaValue = `${v.toFixed(1)} m²`;
  }

  let durationValue = "-";
  if (valid(timeState) && timeState.state !== "0") {
    durationValue = `${timeState.state} min`;
  }

  let finishedValue = "-";
  if (!occupied && valid(timeState) && timeState.state !== "0" && timeState.attributes?.finished_at) {
    const rel = relativeTime(timeState.attributes.finished_at, now);
    if (rel) finishedValue = rel;
  }

  return [
    { value: areaValue, label: "Area cleaned", icon: "mdi:floor-plan" },
    { value: durationValue, label: "Duration", icon: "mdi:clock-outline" },
    { value: finishedValue, label: "Finished", icon: "mdi:calendar-check-outline" },
  ];
}

// Build the standard-mode selector rows (Mode · Suction · Water) from entity
// state. Pure: all the option lists, per-option disabling (mode disabled_options,
// suction fan_speed_list filtering, water mode-gating) and current values live
// here so they are unit-testable. Each row carries `control` (mode|suction|water)
// so the leaf can emit it and the shell route the right service call. Returns
// [{ control, label, value, disabled, options:[{value,icon,label,disabled}] }].
export function deriveSelectorRows(attr, modeState, waterState, busy) {
  const rows = [];
  const fanSpeed = attr?.fan_speed;
  const fanSpeedList = attr?.fan_speed_list || [];

  if (modeState) {
    const disabledOpts = new Set(modeState.attributes?.disabled_options || []);
    rows.push({
      control: "mode",
      label: "Mode",
      value: modeState.state,
      disabled: busy,
      options: [
        { value: "vacuum", icon: "mdi:robot-vacuum", label: "Vacuum", disabled: disabledOpts.has("vacuum") },
        { value: "vacuum_and_mop", icon: "mdi:shimmer", label: "Vac & Mop", disabled: disabledOpts.has("vacuum_and_mop") },
        { value: "mop", icon: "mdi:water", label: "Mop", disabled: disabledOpts.has("mop") },
      ],
    });
  }

  const isMop = modeState?.state === "mop";
  // Keep Suction visible (but disabled) in mop-only mode even though the entity
  // drops fan_speed there — mirrors the Water row staying visible in vacuum mode.
  if ((fanSpeed !== undefined && fanSpeed !== null) || isMop) {
    const off = (v) => fanSpeedList.length > 0 && !fanSpeedList.includes(v);
    rows.push({
      control: "suction",
      label: "Suction",
      value: fanSpeed ?? null,
      disabled: busy || isMop,
      options: [
        { value: "silent", icon: "mdi:fan-off", label: "Silent", disabled: off("silent") },
        { value: "standard", icon: "mdi:fan-speed-2", label: "Standard", disabled: off("standard") },
        { value: "medium", icon: "mdi:fan-speed-3", label: "Medium", disabled: off("medium") },
        { value: "turbo", icon: "mdi:fan", label: "Turbo", disabled: off("turbo") },
      ],
    });
  }

  // Water row appears whenever the entity is configured (waterState !== undefined,
  // even if unavailable); it is disabled in vacuum mode or when state is missing.
  if (waterState !== undefined) {
    const unavailable = !waterState || waterState.state === "unavailable" || waterState.state === "unknown";
    const isVacuum = modeState?.state === "vacuum";
    rows.push({
      control: "water",
      label: "Water",
      value: unavailable ? null : waterState.state,
      disabled: busy || unavailable || !modeState?.state || isVacuum,
      options: [
        { value: "low", icon: "mdi:water-minus", label: "Low" },
        { value: "medium", icon: "mdi:water", label: "Medium" },
        { value: "high", icon: "mdi:water-plus", label: "High" },
      ],
    });
  }

  return rows;
}

// Detail-panel control descriptors for one room (shown when expanded+enabled).
// Pure: maps the int-coded pref to string segment values. Each entry's `field`
// routes the pref-change event; `value` is the current string option.
function roomDetailControls(pref) {
  if (!pref) return [];
  const seg = (label, field, value, options, disabled = false) =>
    ({ label, field, value, disabled, options });
  return [
    seg("Cleaning cycles", "repeat", REPEAT_BY_INT[pref.repeat], [
      { value: "single", label: "×1" }, { value: "double", label: "×2" },
    ]),
    seg("Mode", "mode", MODE_BY_INT[pref.mode], [
      { value: "vacuum", icon: "mdi:robot-vacuum", label: "Vacuum" },
      { value: "vacuum_and_mop", icon: "mdi:shimmer", label: "Vac & Mop" },
      { value: "mop", icon: "mdi:water", label: "Mop" },
    ]),
    seg("Suction", "power", POWER_BY_INT[pref.power], [
      { value: "silent", icon: "mdi:fan-off", label: "Silent" },
      { value: "standard", icon: "mdi:fan-speed-2", label: "Standard" },
      { value: "medium", icon: "mdi:fan-speed-3", label: "Medium" },
      { value: "turbo", icon: "mdi:fan", label: "Turbo" },
    ]),
    // Water is gated off in vacuum mode (matches the standard-mode selector).
    seg("Water", "water", WATER_BY_INT[pref.water], [
      { value: "low", icon: "mdi:water-minus", label: "Low" },
      { value: "medium", icon: "mdi:water", label: "Medium" },
      { value: "high", icon: "mdi:water-plus", label: "High" },
    ], MODE_BY_INT[pref.mode] === "vacuum"),
  ];
}

// Build the customise-mode room-list descriptors. Pure: rooms in preference
// order, each with enabled/expanded flags, the collapsed summary line, color,
// and (when expanded+enabled) its detail controls. `selected` is the
// already-reconciled enabled-set; `detailRoomId` is the open row. The leaf
// renders these and emits events; the shell owns selected/detailRoomId (the map
// reads them too). Returns [{ id, name, colorId, enabled, expanded, summary,
// detail:[...] }].
export function deriveRoomRows(roomMap, prefs, selected, detailRoomId) {
  const rm = roomMap || {};
  const p = prefs || {};
  const sel = selected || new Set();
  const order = parseRoomOrder(rm, p);
  return order.map((id) => {
    const room = rm[id] || {};
    const pref = p[id];
    const enabled = sel.has(id);
    const expanded = detailRoomId === id;
    // Collapsed summary parts: repeat + mode as text, suction + water as icon
    // only (`{ text }` or `{ icon, label }`); the row template renders them.
    let summary = [];
    if (pref) {
      const repeatX = (REPEAT_BY_INT[pref.repeat] || "single") === "double" ? "×2" : "×1";
      const modeKey = MODE_BY_INT[pref.mode] || "vacuum";
      const modeLabel = CLEANING_MODE_LABELS[modeKey] || "Vacuum";
      const powerKey = POWER_BY_INT[pref.power];
      const waterKey = WATER_BY_INT[pref.water];
      summary = [{ text: repeatX }, { text: modeLabel }];
      // Only show settings that apply to the mode: suction off in mop-only,
      // water off in vacuum-only (mirrors the detail-panel gating).
      if (powerKey && modeKey !== "mop") summary.push({ icon: POWER_ICON_BY_KEY[powerKey], label: _cap(powerKey) });
      if (waterKey && modeKey !== "vacuum") summary.push({ icon: WATER_ICON_BY_KEY[waterKey], label: _cap(waterKey) });
    }
    return {
      id,
      name: room.name || id,
      colorId: room.color_id,
      enabled,
      expanded,
      hasPref: !!pref,
      summary,
      detail: (expanded && enabled) ? roomDetailControls(pref) : [],
    };
  });
}

// Render a structured room-summary line (from deriveRoomRows): `{ text }` parts
// as text, `{ icon, label }` parts as an icon-only ha-icon (label → title for a11y),
// joined by a middot. Returns a Lit template fragment.
function roomSummaryParts(parts) {
  return (parts || []).flatMap((p, i) => [
    i ? html`<span class="room-summary-sep">·</span>` : "",
    p.icon
      ? html`<ha-icon class="room-summary-icon" icon=${p.icon} title=${p.label} aria-label=${p.label}></ha-icon>`
      : html`<span>${p.text}</span>`,
  ]);
}

// Reconcile the optimistic "customise" selection against freshly-persisted prefs.
//
// Pure decision function for the _renderList state-mirroring block: external
// pref changes propagate into `selected`, and toggling off works on a single
// click. While a service call is in flight, `pending` records the expected
// custom value and the optimistic state in `selected` wins until the persisted
// pref matches the expectation, at which point the pending entry clears.
//
// Inputs are plain values; returns NEW Set/Map instances (no mutation of the
// arguments) so the caller can assign them back to instance fields.
export function reconcileCustomise(roomIds, prefs, pending, selected) {
  const p = prefs || {};
  const nextSelected = new Set(selected || []);
  const nextPending = new Map(pending || []);
  for (const id of (roomIds || [])) {
    const persisted = p[id]?.custom === true;
    if (nextPending.has(id)) {
      const expected = nextPending.get(id);
      if (persisted === expected) {
        nextPending.delete(id);
        if (persisted) nextSelected.add(id);
        else nextSelected.delete(id);
      }
      // else: still pending — keep the optimistic value in nextSelected.
      continue;
    }
    if (persisted) nextSelected.add(id);
    else nextSelected.delete(id);
  }
  return { selected: nextSelected, pending: nextPending };
}

// Dedup key for the room list: re-render only when something the list shows
// actually changed. Covers room order, per-room settings, customise-enabled
// state, the expanded row, and the busy flag. A stable key across a hass poll
// prevents stomping in-flight optimistic per-room edits.
export function computeListKey(roomIds, prefs, selected, detailRoomId, busy) {
  const p = prefs || {};
  const sel = selected || new Set();
  const body = (roomIds || []).map(id => {
    const r = p[id];
    return `${id}:${r?.mode}:${r?.power}:${r?.water}:${r?.repeat}:${sel.has(id)}`;
  }).join("|");
  return `${body}|exp:${detailRoomId}|busy:${busy}`;
}

// Selection-hint text for the room badge + the chip button label, derived from
// the current selection. `mode` is "customise" or anything else (default flow);
// each mode reads its own selection set. Returns the strings only — the caller
// writes them to the DOM. names() maps a room id to its display name.
export function selectionHint(roomIds, selectedIds, mode, names) {
  const ids = roomIds || [];
  const sel = [...(selectedIds || [])];
  const hasRooms = ids.length > 0;
  const allOn = hasRooms && ids.every(id => (selectedIds || new Set()).has(id));
  const chipLabel = allOn ? "Clear all" : "Select all";

  const nameOf = typeof names === "function" ? names : (id => id);
  const count = sel.length;
  let badge;
  if (count === 0) {
    badge = mode === "customise"
      ? "Tap a room to enable it"
      : "Tap a room to select · cleans all if none selected";
  } else {
    const preview = sel.slice(0, 2).map(nameOf).join(", ");
    const extra = count > 2 ? ` +${count - 2}` : "";
    const plural = count !== 1 ? "s" : "";
    badge = mode === "customise"
      ? `${count} room${plural} enabled · ${preview}${extra}`
      : `Cleaning ${count} room${plural} · ${preview}${extra}`;
  }
  return { chipLabel, badge };
}

// Play/Stop/Dock button icon+label mapping for a given vacuum activity. The
// enabled/disabled decisions live in buttonStates(); this is the user-facing
// text/icon layer only.
export function buttonLabels(activity) {
  const isCleaning = activity === "cleaning";
  const isPaused = activity === "paused";
  return {
    playIcon: isCleaning ? "mdi:pause" : "mdi:play",
    playLabel: isCleaning ? "Pause" : (isPaused ? "Resume" : "Start"),
    playAction: isCleaning ? "pause" : "play",
    dockLabel: activity === "docked" ? "Docked" : "Dock",
  };
}

// Room-label chip text: name, plus an area line when area_m2 is known. Both
// standard and customise modes use the same pill (customise adds no symbols).
// Returns the multi-line string the canvas splits on "\n". Pure — used by
// drawRoomLabels and unit-tested directly.
export function roomChipText(room) {
  const name = room?.name || room?.id || "";
  const areaLine = (room?.area_m2 != null) ? `${room.area_m2} m²` : null;
  return areaLine ? `${name}\n${areaLine}` : name;
}

// Resolve which room is currently being cleaned, by matching the live
// current-room name against room_map. Returns the room id (string) or null.
// The card derives currentRoomName from hass so the renderer never reads hass.
export function activeRoomId(roomMap, currentRoomName, isCleaning) {
  if (!isCleaning || !currentRoomName) return null;
  if (currentRoomName === "unknown" || currentRoomName === "unavailable") return null;
  const hit = Object.entries(roomMap || {}).find(([, r]) => r.name === currentRoomName);
  return hit ? hit[0] : null;
}

// Cache key for the canvas draw: a redraw is skipped when this is unchanged.
// Covers everything the rendered overlay depends on — map token, robot/charger/
// path geometry, room names+colours (room_map is rebuilt fresh every HA update,
// so a reference check never matches), selection sets, mode, and canvas size.
export function computeDrawKey(attr, viewState) {
  const rp = attr?.robot_px;
  const cp = attr?.charger_px;
  const roomMap = attr?.room_map || {};
  const roomSig = Object.entries(roomMap)
    .map(([id, r]) => `${id}:${r.name}:${r.color_id}`)
    .join(",");
  return [
    viewState.mapToken,
    rp ? `${rp.x},${rp.y},${rp.phi ?? 0}` : "",
    cp ? `${cp.x},${cp.y}` : "",
    attr?.cur_path_px ? attr.cur_path_px.join(",") : "",
    roomSig,
    viewState.cardMode,
    viewState.detailRoomId,
    [...(viewState.selectedRooms || [])].sort().join(","),
    [...(viewState.customiseSelected || [])].sort().join(","),
    !!viewState.robotIcon,
    viewState.canvasWidth,
    viewState.canvasHeight,
    viewState.dpr,
  ].join("|");
}

// ---------------------------------------------------------------------------
// Canvas map renderer — pure of card/hass state.
//
// All inputs arrive in `vs` (viewState), a plain object the card assembles by
// pre-resolving everything hass-derived (selection sets, activeRoomId, icons).
// The renderer never touches this/_hass/_config. drawMap returns the room
// checkbox hit areas (image-space rects) for the card's click handler to store;
// it does not write them back onto any object.
//
// vs = { attr, dpr, mapImg, robotIcon, cardMode, detailRoomId, selectedRooms,
//        customiseSelected, activeRoomId, mapToken, canvasWidth, canvasHeight }
// ---------------------------------------------------------------------------

export function drawMap(ctx, canvas, vs) {
  const { attr, mapImg } = vs;
  if (!mapImg || !canvas) return [];
  const dpr = vs.dpr || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const cssW = canvas.width / dpr;
  const cssH = canvas.height / dpr;
  ctx.clearRect(0, 0, cssW, cssH);
  ctx.drawImage(mapImg, 0, 0, cssW, cssH);
  const roomMap = attr.room_map || {};
  drawRoomOverlays(ctx, canvas, roomMap, vs);
  drawCurPath(ctx, canvas, vs);
  const hitAreas = drawRoomLabels(ctx, canvas, roomMap, vs);
  drawCharger(ctx, canvas, vs);
  drawRobot(ctx, canvas, vs);
  return hitAreas;
}

function drawCurPath(ctx, canvas, vs) {
  const { attr } = vs;
  const pts = attr.cur_path_px;
  const imgSize = attr.map_image_size;
  if (!pts || pts.length < 4 || !imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
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
    for (let i = 2; i < pts.length - 2; i += 2) {
      const cx = pts[i] * scaleX, cy = pts[i + 1] * scaleY;
      const nx = pts[i + 2] * scaleX, ny = pts[i + 3] * scaleY;
      const mx = (cx + nx) / 2, my = (cy + ny) / 2;
      ctx.quadraticCurveTo(cx, cy, mx, my);
    }
    const last = pts.length - 2;
    ctx.lineTo(pts[last] * scaleX, pts[last + 1] * scaleY);
  }
  ctx.stroke();
  ctx.shadowBlur = 0;
  ctx.restore();
}

function drawCharger(ctx, canvas, vs) {
  const cp = vs.attr.charger_px;
  const imgSize = vs.attr.map_image_size;
  if (!cp || !imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const cx = cp.x * scaleX;
  const cy = cp.y * scaleY;
  const r = Math.max(6, imgSize.cell_size * scaleX * 3.5);

  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = "#4db6c4";
  ctx.fill();

  ctx.beginPath();
  ctx.arc(cx, cy, r * 0.55, 0, Math.PI * 2);
  ctx.fillStyle = "#fff";
  ctx.fill();
}

function drawRobot(ctx, canvas, vs) {
  const rp = vs.attr.robot_px;
  const imgSize = vs.attr.map_image_size;
  if (!rp || !imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const cx = rp.x * scaleX;
  const cy = rp.y * scaleY;
  // Robot is ~34cm wide; resolution=0.05m/cell → ~7 cells diameter → 3.5 cell radius.
  const r = imgSize.cell_size * scaleX * 3.5;
  const phi = rp.phi ?? 0;

  ctx.save();
  ctx.translate(cx, cy);
  // SVG front (camera bump) is at upper-right: atan2(-21.79, 13.13) = -1.029 rad from east.
  // Canvas target angle for world phi (Y-flipped) = -phi. Required rotation:
  // θ = -phi - SVG_rest_angle = -phi + 1.029. If icon.svg's camera-bump geometry
  // ever changes, recompute this constant — see www/icon.svg.
  ctx.rotate(-phi + 1.029);

  if (vs.robotIcon) {
    ctx.drawImage(vs.robotIcon, -r, -r, r * 2, r * 2);
  } else {
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

function drawRoomOverlays(ctx, canvas, roomMap, vs) {
  const imgSize = vs.attr?.map_image_size;
  if (!imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const cs = imgSize.cell_size || 1;
  const cellH = cs * scaleY;

  const fillCells = (cells, style) => {
    ctx.fillStyle = style;
    for (const [row, colStart, runLen] of cells) {
      ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
    }
  };

  if (vs.cardMode === "customise") {
    for (const [id, room] of Object.entries(roomMap)) {
      const cells = room.cells;
      if (!cells || cells.length === 0) continue;
      if (vs.customiseSelected.has(id)) fillCells(cells, "rgba(255,212,0,0.55)");
    }
    return;
  }

  // Standard mode: highlight active room during cleaning; accent tint for queued.
  for (const [id, room] of Object.entries(roomMap)) {
    const cells = room.cells;
    if (!cells || cells.length === 0) continue;
    let fill = null;
    if (id === vs.activeRoomId) fill = "rgba(255,212,0,0.40)";
    else if (vs.selectedRooms.has(id)) fill = "rgba(255,212,0,0.55)";
    if (!fill) continue;
    fillCells(cells, fill);
  }
}

function drawRoomLabels(ctx, canvas, roomMap, vs) {
  const hitAreas = [];
  const imgSize = vs.attr?.map_image_size;
  if (!imgSize) return hitAreas;
  const isCustomise = vs.cardMode === "customise";
  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const cs = imgSize.cell_size || 1;

  for (const [id, room] of Object.entries(roomMap)) {
    const cells = room.cells;
    if (!cells || cells.length === 0) continue;

    const bbox = roomBoundingBox(cells, cs);
    const centroid = roomCentroid(bbox);
    const cx = centroid.cx * scaleX;
    const cy = centroid.cy * scaleY;

    const chipText = roomChipText({ ...room, id });

    const isSelected = isCustomise ? vs.customiseSelected.has(id) : vs.selectedRooms.has(id);

    const fontSize = Math.max(16, Math.min(24, cs * scaleX * 2.1));
    const areaFontSize = fontSize * 0.75;
    ctx.save();
    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const lines = chipText.split("\n");
    const isNormalWithArea = lines.length === 2;
    const nameLineH = fontSize * 1.25;
    const areaLineH = areaFontSize * 1.25;
    const totalTextH = isNormalWithArea ? nameLineH + areaLineH : nameLineH * lines.length;
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
    const cbGap = fontSize * 0.45;
    const cbOffsetX = cbR + fontSize * 0.5;
    const pw = cbOffsetX + cbR + cbGap + tw + fontSize * 0.9;

    const pillX = cx - pw / 2;
    ctx.fillStyle = isSelected ? "#FFD400" : "rgba(255,255,255,0.92)";
    ctx.beginPath();
    ctx.roundRect(pillX, cy - ph / 2, pw, ph, ph / 2);
    ctx.fill();

    const cbCx = pillX + cbOffsetX;
    const cbCy = cy;
    ctx.beginPath();
    ctx.arc(cbCx, cbCy, cbR, 0, Math.PI * 2);
    if (isSelected) {
      ctx.fillStyle = "rgba(0,0,0,0.18)";
      ctx.fill();
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

    // Hit area: the checkbox circle inside the pill, in image-space.
    hitAreas.push({
      id,
      x: (cbCx - cbR) / scaleX,
      y: (cbCy - cbR) / scaleY,
      w: (cbR * 2) / scaleX,
      h: (cbR * 2) / scaleY,
    });
  }
  return hitAreas;
}

// ---------------------------------------------------------------------------
// Lit leaf: control button row (Play/Pause/Resume · Stop · Dock).
//
// First strangler-fig increment. Light DOM (createRenderRoot returns `this`) so
// the shell's `.btn-wrap`/`.btn-circle` CSS applies with no duplication. Data
// down: the shell sets `.activity`. Actions up: clicking emits a bubbling
// `karcher-action` event ({ detail: { action } }); the shell routes it to its
// existing _play/_pause/_stop/_dock handlers. The button enable/label decisions
// stay in the already-tested buttonStates()/buttonLabels() pure functions.
// ---------------------------------------------------------------------------
class KarcherButtonRow extends LitElement {
  static properties = { activity: { attribute: false }, offline: { attribute: false } };

  // Light DOM: inherit the shell's stylesheet instead of a private shadow root.
  createRenderRoot() { return this; }

  _emit(action) {
    this.dispatchEvent(new CustomEvent("karcher-action", {
      detail: { action }, bubbles: true, composed: true,
    }));
  }

  _btn(icon, label, variant, enabled, action) {
    return html`
      <button
        class="btn-wrap ${enabled ? variant : "disabled"}"
        ?disabled=${!enabled}
        @click=${enabled ? () => this._emit(action) : null}
      >
        <span class="btn-circle"><ha-icon icon=${icon}></ha-icon></span>
        <span class="btn-label">${label}</span>
      </button>`;
  }

  render() {
    const activity = this.activity;
    const { isOffline, canStop, canDock } = buttonStates(activity, this.offline);
    const { playIcon, playLabel, playAction, dockLabel } = buttonLabels(activity);
    return html`
      ${this._btn(playIcon, playLabel, "primary", !isOffline, playAction)}
      ${this._btn("mdi:stop", "Stop", "danger", !isOffline && canStop, "stop")}
      ${this._btn("mdi:home-import-outline", dockLabel, "secondary", !isOffline && canDock, "dock")}
    `;
  }
}
if (!customElements.get("karcher-button-row")) {
  customElements.define("karcher-button-row", KarcherButtonRow);
}

// ---------------------------------------------------------------------------
// Lit leaf: last-run stat tiles (area cleaned · duration · finished).
//
// Light DOM (inherits the shell's .stat-* CSS). Data down: the shell sets
// `.tiles` to deriveStatTiles(...)'s output (all branching is in that pure fn).
// The host collapses to display:none when there are no tiles, so an empty row
// leaves no gap/margin band — the old code did this via _statsEl.style.display.
// ---------------------------------------------------------------------------
class KarcherStatsRow extends LitElement {
  static properties = { tiles: { attribute: false } };

  createRenderRoot() { return this; }

  render() {
    const tiles = this.tiles || [];
    // Collapse the host itself when empty (light DOM has no wrapper to hide).
    this.style.display = tiles.length ? "" : "none";
    return html`${tiles.map((t) => html`
      <div class="stat-block">
        <span class="stat-label-header">
          ${t.icon ? html`<ha-icon icon=${t.icon}></ha-icon>` : null}
          <span>${t.label}</span>
        </span>
        <span class="stat-value">${t.value}</span>
      </div>`)}`;
  }
}
if (!customElements.get("karcher-stats-row")) {
  customElements.define("karcher-stats-row", KarcherStatsRow);
}

// ---------------------------------------------------------------------------
// Lit leaf: standard-mode selector rows (Mode · Suction · Water).
//
// Light DOM (inherits .field-row / .segmented / .seg-btn CSS). Data down: the
// shell sets `.rows` to deriveSelectorRows(...)'s output. Actions up: clicking
// a segment emits `karcher-select` ({ detail: { control, value } }); the shell
// routes it to the right callService.
//
// OPTIMISTIC ACTIVE STATE: the old code protected the just-clicked highlight
// from the next poll via the _lastSelectorKey rebuild-skip. Here the leaf keeps
// a per-control `_pending` value — render highlights `pending ?? row.value`, and
// the pending entry clears once the derived value catches up (round-trip done).
// Without this the highlight would snap back to the pre-click value on the next
// poll (~1s). Same pattern as reconcileCustomise.
// ---------------------------------------------------------------------------
class KarcherSelectorRows extends LitElement {
  static properties = { rows: { attribute: false } };

  constructor() {
    super();
    this._pending = new Map(); // control -> optimistic value, until the poll confirms
  }

  createRenderRoot() { return this; }

  willUpdate() {
    // Clear any pending optimistic value the latest derived state now matches.
    for (const row of this.rows || []) {
      if (this._pending.get(row.control) === row.value) this._pending.delete(row.control);
    }
  }

  _select(control, value, optDisabled) {
    if (optDisabled) return;
    this._pending.set(control, value);
    this.requestUpdate(); // reflect the optimistic highlight immediately
    this.dispatchEvent(new CustomEvent("karcher-select", {
      detail: { control, value }, bubbles: true, composed: true,
    }));
  }

  _segment(row) {
    const active = this._pending.get(row.control) ?? row.value;
    // Compact (icon-only inactive) only when a segment is actually active;
    // with no active value (loading/unset) fall back to full labels.
    const compact = (row.control === "suction" || row.control === "water")
      && row.options.some((o) => o.value === active);
    return html`
      <div class="field-row">
        <span class="field-row-label" id="seg-lbl-${row.control}">${row.label}</span>
        <div class="field-row-control">
          <div class="segmented ${row.disabled ? "seg-disabled" : ""} ${compact ? "seg-compact" : ""}"
            role="group" aria-labelledby="seg-lbl-${row.control}">
            ${row.options.map((opt) => {
              const optDisabled = row.disabled || !!opt.disabled;
              return html`
                <button
                  class="seg-btn ${opt.value === active ? "active" : ""}"
                  aria-pressed=${opt.value === active} aria-label=${opt.label}
                  ?disabled=${optDisabled}
                  @click=${() => this._select(row.control, opt.value, optDisabled)}
                >
                  ${opt.icon ? html`<ha-icon icon=${opt.icon}></ha-icon>` : null}<span class="seg-label">${opt.label}</span>
                </button>`;
            })}
          </div>
        </div>
      </div>`;
  }

  render() {
    const rows = this.rows || [];
    // Collapse when empty (no configured selector entities). We only force
    // `none`, never `""`, so the shell's _applyMode mode-gate (which sets
    // display:none in customise mode) is never overridden by a re-render.
    if (rows.length === 0) this.style.display = "none";
    else if (this.style.display === "none") this.style.display = "";
    return html`${rows.map((row) => this._segment(row))}`;
  }
}
if (!customElements.get("karcher-selector-rows")) {
  customElements.define("karcher-selector-rows", KarcherSelectorRows);
}

// ---------------------------------------------------------------------------
// Lit leaf: customise-mode room list (reorder · enable/disable · per-room detail).
//
// Light DOM (inherits .room-row / .field-row / .segmented CSS). View + events
// only — the shell owns selected/pending/detailRoomId because the still-vanilla
// MAP reads them too (one source of truth, two readers). The leaf's ONLY private
// state is the transient drag (`_dragSrcId`), and `shouldUpdate` suppresses
// re-renders mid-drag so a poll can't clobber the drag (the role the retired
// _lastListKey dedup used to play).
//
// Data down: shell sets `.rows` (deriveRoomRows output) and `.busy`. Events up:
//   room-toggle  { roomId, on }      room-expand { roomId }
//   room-reorder { order:[id,...] }  room-pref   { roomId, field, value }
// ---------------------------------------------------------------------------
class KarcherRoomList extends LitElement {
  static properties = { rows: { attribute: false }, busy: { attribute: false } };

  constructor() {
    super();
    this._dragSrcId = null;
    // Optimistic per-detail-segment value, keyed `${roomId}:${field}`, so a
    // clicked mode/power/water/repeat highlights immediately and survives the
    // next poll — same pattern as the standalone selector leaf. Cleared once the
    // derived (persisted) value catches up.
    this._prefPending = new Map();
  }

  createRenderRoot() { return this; }

  willUpdate() {
    // Drop any optimistic detail value the latest derived rows now match.
    for (const row of this.rows || []) {
      for (const c of row.detail) {
        const key = `${row.id}:${c.field}`;
        if (this._prefPending.get(key) === c.value) this._prefPending.delete(key);
      }
    }
  }

  connectedCallback() {
    super.connectedCallback();
    // Drag handlers live on the host (light DOM): rows are direct flex children
    // of .room-list, so container-level DnD avoids child elements swallowing it.
    this.addEventListener("dragover", (e) => this._onDragOver(e));
    this.addEventListener("drop", (e) => this._onDrop(e));
    this.addEventListener("dragleave", (e) => this._onDragLeave(e));
  }

  shouldUpdate() {
    // A hass poll mid-drag would re-render and destroy the drag state — suppress.
    return this._dragSrcId === null;
  }

  _emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
  }

  _order() {
    return (this.rows || []).map((r) => r.id);
  }

  _onDragStart(e, id) {
    if (this.busy) { e.preventDefault(); return; }
    this._dragSrcId = id;
    e.currentTarget.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", id);
  }

  _onDragEnd(e) {
    e.currentTarget.classList.remove("dragging");
    this._dragSrcId = null;
    this._clearIndicators();
    this.requestUpdate(); // drag suppressed updates; refresh now it has ended
  }

  _clearIndicators() {
    this.querySelectorAll(".drop-indicator").forEach((d) => d.remove());
  }

  _rowUnder(target) {
    let el = target;
    while (el && el !== this) {
      if (el.dataset && el.dataset.roomId) return el;
      el = el.parentNode;
    }
    return null;
  }

  _onDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const row = this._rowUnder(e.target);
    if (row && row.dataset.roomId !== this._dragSrcId) {
      this._clearIndicators();
      const ind = document.createElement("div");
      ind.className = "drop-indicator";
      row.parentNode.insertBefore(ind, row);
    }
  }

  _onDrop(e) {
    e.preventDefault();
    this._clearIndicators();
    const row = this._rowUnder(e.target);
    const srcId = this._dragSrcId;
    if (!row || !srcId) return;
    const tgtId = row.dataset.roomId;
    const order = this._order();
    const from = order.indexOf(srcId);
    const to = order.indexOf(tgtId);
    if (from === -1 || to === -1 || from === to) return;
    order.splice(from, 1);
    order.splice(to, 0, srcId);
    this._emit("room-reorder", { order });
  }

  _onDragLeave(e) {
    if (!this.contains(e.relatedTarget)) this._clearIndicators();
  }

  _onPref(roomId, field, value, disabled) {
    if (disabled) return;
    this._prefPending.set(`${roomId}:${field}`, value); // optimistic highlight
    this.requestUpdate();
    this._emit("room-pref", { roomId, field, value });
  }

  _detailRow(roomId, c) {
    const active = this._prefPending.get(`${roomId}:${c.field}`) ?? c.value;
    const compact = (c.field === "power" || c.field === "water")
      && c.options.some((o) => o.value === active);
    return html`
      <div class="field-row">
        <span class="field-row-label" id="rseg-lbl-${roomId}-${c.field}">${c.label}</span>
        <div class="field-row-control">
          <div class="segmented ${c.disabled ? "seg-disabled" : ""} ${compact ? "seg-compact" : ""}"
            role="group" aria-labelledby="rseg-lbl-${roomId}-${c.field}">
            ${c.options.map((opt) => html`
              <button
                class="seg-btn ${opt.value === active ? "active" : ""}"
                aria-pressed=${opt.value === active} aria-label=${opt.label}
                ?disabled=${c.disabled}
                @click=${() => this._onPref(roomId, c.field, opt.value, c.disabled)}
              >${opt.icon ? html`<ha-icon icon=${opt.icon}></ha-icon>` : null}<span class="seg-label">${opt.label}</span></button>`)}
          </div>
        </div>
      </div>`;
  }

  _roomRow(r) {
    const cls = `room-row${r.expanded ? " expanded" : ""}${!r.enabled ? " disabled-room" : ""}`;
    return html`
      <div class="${cls}" data-room-id=${r.id} draggable="true"
        @dragstart=${(e) => this._onDragStart(e, r.id)}
        @dragend=${(e) => this._onDragEnd(e)}>
        <div class="room-row-header" draggable="false">
          <span class="room-drag-handle" title="Drag to reorder">⠿</span>
          <span class="room-color-dot" style="background:${_roomColor(r.colorId)}"></span>
          <div class="room-text room-row-select" @click=${(e) => this._onTextClick(e, r)}>
            <div class="room-text-inner">
              <span class="room-name">${r.name}</span>
              ${r.hasPref && !r.expanded ? html`<div class="room-summary">${roomSummaryParts(r.summary)}</div>` : null}
            </div>
            <span class="room-chevron ${r.expanded ? "open" : ""}"
              style=${r.enabled ? "" : "visibility:hidden"}>›</span>
          </div>
          <button class="room-toggle ${r.enabled ? "on" : ""}"
            aria-label=${r.enabled ? "Disable room" : "Enable room"}
            @click=${(e) => this._onToggle(e, r)}>
            <span class="room-toggle-knob"></span>
          </button>
        </div>
        ${r.detail.length ? html`<div class="room-inline-detail">
          ${r.detail.map((c) => this._detailRow(r.id, c))}
        </div>` : null}
      </div>`;
  }

  _onTextClick(e, r) {
    e.stopPropagation();
    if (!r.enabled || this.busy) return;
    this._emit("room-expand", { roomId: r.id });
  }

  _onToggle(e, r) {
    e.stopPropagation();
    if (this.busy) return;
    this._emit("room-toggle", { roomId: r.id, on: !r.enabled });
  }

  render() {
    const rows = this.rows || [];
    if (rows.length === 0) {
      return html`<div class="room-summary" style="padding:16px 4px">No rooms found — load a map first</div>`;
    }
    return html`
      ${rows.map((r) => this._roomRow(r))}
      <div class="room-list-footer">⠿ Drag to set cleaning order</div>`;
  }
}
if (!customElements.get("karcher-room-list")) {
  customElements.define("karcher-room-list", KarcherRoomList);
}

// ---------------------------------------------------------------------------
// Lit leaf: map selection badge (hint text + "Select all"/"Clear all" chip).
//
// One contiguous region (.map-badge contains both the text and the chip).
// Light DOM (inherits .map-badge / .map-chip-btn CSS). Data down: the shell sets
// `.state` = { visible, badge, chipLabel, chipDisabled, chipVisible } — all
// pre-resolved from the tested selectionHint() pure fn. Up: the chip emits
// `chip-click`, routed by the shell to its select-all/clear-all logic. The shell
// owns the selection sets (the map reads them), so the leaf holds no state.
// ---------------------------------------------------------------------------
class KarcherSelectionBadge extends LitElement {
  static properties = { state: { attribute: false } };

  createRenderRoot() { return this; }

  render() {
    const s = this.state || {};
    this.style.display = s.visible ? "" : "none";
    return html`
      <span>${s.badge || ""}</span>
      <button class="map-chip-btn"
        style=${s.chipVisible ? "" : "display:none"}
        ?disabled=${s.chipDisabled}
        @click=${() => this.dispatchEvent(new CustomEvent("chip-click", { bubbles: true, composed: true }))}
      >${s.chipLabel || ""}</button>`;
  }
}
if (!customElements.get("karcher-selection-badge")) {
  customElements.define("karcher-selection-badge", KarcherSelectionBadge);
}

class KarcherVacuumCard extends LitElement {
  // hass + config are reactive: HA assigns el.hass each poll, el.setConfig once.
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    // Derived display state the template binds to (set in willUpdate).
    _view: { state: true },
  };

  // NOTE: _CSS is injected as a <style> in render() (see below), NOT via Lit's
  // `static styles`. `static styles` requires css`` CSSResults and routes through
  // adoptStyles()/adoptedStyleSheets, which threw a TypeError in HA (a plain
  // string has no .styleSheet getter). A <style> tag in the shadow root styles
  // the tree — including the light-DOM leaf children — identically, and is how
  // the card worked pre-flip.

  constructor() {
    super();
    this._config = null;
    this.hass = null;
    this._view = {}; // { name, statusText, dotClass, labelClass, pinging, hasError, placeholderText, mapLoading, aspectRatio, busy }
    this._selectedRooms = new Set();
    this._prevActivity = null;
    this._mapLoaded = false;
    this._mapPending = false;    // map image fetch in flight
    this._mapError = false;      // last map image fetch failed
    this._needsCanvasSize = false; // size the canvas on the next updated()
    this._mapImg = null;
    this._mapImgLoad = null;     // in-flight Image() for the map, cleared on disconnect
    this._mapToken = null;
    this._robotIcon = null;
    this._robotIconLoad = null;  // in-flight Image() for the robot icon, cleared on disconnect
    this._robotIconLoading = false;
    this._cardMode = "standard";         // "standard" | "customise"
    this._lastPreferMode = null;         // last robot-reported prefer_mode
    this._pendingPrefRefresh = false;    // request a "fresh on look" preference refetch
    this._onVisibilityChange = null;     // bound visibilitychange handler (mount/foreground)
    this._detailRoomId = null;           // string room_id when detail is open
    this._customiseSelected = new Set(); // selected room IDs in Customise mode
    this._customisePending = new Map();  // id → expected custom (optimistic) until HA confirms
    this._roomCheckboxHitAreas = [];     // [{id, x, y, size} in image-space] rebuilt each _drawRoomLabels
    this._lastDrawKey = null;
  }

  // HA calls setConfig imperatively; store config (a reactive property).
  setConfig(config) {
    if (!config.vacuum_entity) throw new Error("vacuum_entity is required");
    this._config = { ..._deriveCompanions(config.vacuum_entity), ...config };
  }

  getCardSize() { return 6; }

  static getConfigElement() {
    return document.createElement("karcher-vacuum-card-editor");
  }

  static getStubConfig() {
    return { vacuum_entity: "vacuum.karcher_rcv5" };
  }

  connectedCallback() {
    super.connectedCallback();
    // "Fresh on look": pull the latest per-room preferences when the card mounts
    // (dashboard opened) and when the tab is re-foregrounded — the closest analog
    // to the Kärcher app's on-screen refetch. The coordinator throttles repeats.
    this._pendingPrefRefresh = true;
    if (!this._onVisibilityChange) {
      this._onVisibilityChange = () => {
        if (document.visibilityState === "visible") {
          this._pendingPrefRefresh = true;
          this.requestUpdate();
        }
      };
    }
    document.addEventListener("visibilitychange", this._onVisibilityChange);
    this.requestUpdate();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._onVisibilityChange) {
      document.removeEventListener("visibilitychange", this._onVisibilityChange);
    }
    if (this._mapImgLoad) {
      this._mapImgLoad.onload = null;
      this._mapImgLoad.onerror = null;
      this._mapImgLoad = null;
    }
    if (this._robotIconLoad) {
      this._robotIconLoad.onload = null;
      this._robotIconLoad = null;
    }
    if (this._mapResizeObserver) {
      this._mapResizeObserver.disconnect();
      this._mapResizeObserver = null;
    }
  }

  // ── render (declarative; was _buildDOM) ──────────────────────────────────────

  render() {
    const v = this._view;
    return html`
      <style>${_CSS}</style>
      <div class="card-grid">
      <ha-card class="card-status">
        <div class="top-bar">
          <div class="top-bar-left">
            <div class="robot-name">${v.name || ""}</div>
            <div class="status-row">
              <span class="status-dot ${v.dotClass || ""}${v.pinging ? " pinging" : ""}">
                <span class="status-dot-inner"></span>
                <span class="status-dot-ping"></span>
              </span>
              <span class="status-label ${v.labelClass || ""}">${v.statusText || ""}</span>
            </div>
          </div>
          <div class="top-bar-right">
            <span class="battery-wrap" style=${v.battVisible ? "" : "display:none"}>
              <span class="battery-glyph">
                <span class="battery-fill ${v.battFillClass || ""}" style="width:${v.battFillW || "0"}"></span>
              </span>
              <ha-icon class="battery-bolt ${v.charging ? "visible" : ""}" icon="mdi:lightning-bolt"></ha-icon>
              <span class="battery-pct">${v.battPct || ""}</span>
            </span>
          </div>
        </div>
        <karcher-stats-row class="stats-line" .tiles=${v.tiles || []}></karcher-stats-row>
      </ha-card>

      <ha-card class="card-map">
        <div class="map-container" style=${v.aspectRatio ? `aspect-ratio:${v.aspectRatio}` : ""}>
          <div class="map-placeholder ${v.mapLoading ? "map-loading" : ""}"
               style=${v.mapLoaded ? "display:none" : ""}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z"></path>
            </svg>
            <span>${v.placeholderText || ""}</span>
          </div>
          <canvas style=${v.mapLoaded ? "display:block" : "display:none"} @click=${(e) => this._onCanvasClick(e)}></canvas>
        </div>
        <karcher-selection-badge class="map-badge" .state=${v.badgeState}
          @chip-click=${() => this._onMapChipClick()}></karcher-selection-badge>
        <ha-alert alert-type="error" class=${v.hasError ? "visible" : ""}>Robot reported a fault</ha-alert>
      </ha-card>

      <ha-card class="card-control">
        <karcher-button-row class="buttons" .activity=${v.activity} .offline=${!!v.offline}
          @karcher-action=${(e) => this._onButtonAction(e)}></karcher-button-row>
      </ha-card>

      <ha-card class="card-settings">
        <div class="busy-banner ${v.busy ? "visible" : ""}">
          <ha-icon icon="mdi:lock"></ha-icon>
          <span class="busy-banner-text">Locked while cleaning — pause to change settings</span>
        </div>
        <div class="settings-body ${v.busy ? "busy-locked" : ""}">
          <div class="tab-row">
            <div class="segmented" style="width:auto" role="group" aria-label="Cleaning settings mode">
              <button class="seg-btn ${v.cardMode === "standard" ? "active" : ""}"
                aria-pressed=${v.cardMode === "standard"}
                @click=${() => this._setCardMode("standard")}>Standard</button>
              <button class="seg-btn ${v.cardMode === "customise" ? "active" : ""}"
                aria-pressed=${v.cardMode === "customise"}
                @click=${() => this._setCardMode("customise")}>Customise</button>
            </div>
            <span class="tab-helper">${v.tabHelper || "Applies to all rooms"}</span>
          </div>
          <karcher-selector-rows class="standard-settings"
            style=${v.cardMode === "standard" ? "" : "display:none"}
            .rows=${v.selectorRows || []}
            @karcher-select=${(e) => this._onSelectorChange(e)}></karcher-selector-rows>
          <karcher-room-list class="room-list ${v.cardMode === "customise" ? "visible" : ""}"
            .rows=${v.roomRows || []} .busy=${!!v.busy}
            @room-toggle=${(e) => this._onRoomToggle(e)}
            @room-expand=${(e) => this._onRoomExpand(e)}
            @room-reorder=${(e) => this._onRoomReorder(e)}
            @room-pref=${(e) => this._onRoomPref(e)}></karcher-room-list>
        </div>
      </ha-card>
      </div>`;
  }

  firstUpdated() {
    // Grab the persistent canvas (a static literal → reused across re-renders;
    // node-identity spike confirmed the bitmap survives). The click is bound in
    // the template via @click; the ref is kept for sizing + draw.
    this._canvas = this.renderRoot.querySelector("canvas");
    // The canvas backing-buffer is sized once per image load. Its CSS width
    // changes responsively (two-column breakpoint, window resize, sidebar
    // collapse), so re-fit when the laid-out width changes — otherwise the
    // buffer goes stale and the map renders blurry/distorted.
    const mapContainer = this.renderRoot.querySelector(".map-container");
    if (mapContainer && "ResizeObserver" in window) {
      this._lastMapWidth = mapContainer.getBoundingClientRect().width;
      this._mapResizeObserver = new ResizeObserver((entries) => {
        const w = entries[0]?.contentRect?.width;
        if (!w || w === this._lastMapWidth) return;
        this._lastMapWidth = w;
        this._needsCanvasSize = true;
        this.requestUpdate();
      });
      this._mapResizeObserver.observe(mapContainer);
    }
  }

  // ── update cycle (derive _view from hass; was _updateCard) ────────────────────

  willUpdate() {
    if (!this.hass || !this._config) return;
    // Keep _hass available to the verbatim logic/handler methods.
    this._hass = this.hass;
    if (this._pendingPrefRefresh) {
      this._pendingPrefRefresh = false;
      this._refreshPreferences();
    }
    const vacState = this.hass.states[this._config.vacuum_entity];
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

    // Reconcile optimistic customise state before deriving the view (the derived
    // room rows + header count + map overlay all read _customiseSelected).
    this._reconcileCustomise(attr);

    this._view = this._deriveView(attr, activity);
  }

  updated() {
    // Map draw is a side effect — runs here, never in render(). _lastDrawKey
    // early-returns on updates that don't change the overlay.
    if (!this.hass || !this._config) return;
    // Size the canvas now that the re-render has made it visible (display:block).
    this._sizeCanvasIfNeeded();
    const attr = this.hass.states[this._config.vacuum_entity]?.attributes;
    if (attr) this._updateMap(attr);
  }

  // One-time canvas sizing after the map first becomes visible. Measured here
  // (in updated(), post-render) so getBoundingClientRect reflects the laid-out,
  // display:block canvas — never the display:none state during onload.
  _sizeCanvasIfNeeded() {
    if (!this._needsCanvasSize || !this._canvas) return;
    const rect = this._canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return; // not laid out yet — retry next update
    const dpr = window.devicePixelRatio || 1;
    this._canvas.width = rect.width * dpr;
    this._canvas.height = rect.height * dpr;
    this._dpr = dpr;
    this._needsCanvasSize = false;
    this._lastDrawKey = null; // force a draw on the freshly-sized canvas
  }

  _deriveView(attr, activity) {
    const cfg = this._config;
    const connEntity = cfg.connectivity_entity;
    const isOffline = activity === "unavailable" ||
      (connEntity && this.hass.states[connEntity]?.state === "off");
    let statusText, dotClass, labelClass;
    if (isOffline) {
      statusText = "Offline"; dotClass = "dot-offline"; labelClass = "label-offline";
    } else {
      statusText = attr.status_label || STATE_LABELS[activity] || activity;
      const roomEntity = cfg.current_room_entity;
      if (activity === "cleaning" && roomEntity) {
        const r = this.hass.states[roomEntity]?.state;
        if (r && r !== "unknown" && r !== "unavailable") statusText += ` · ${r}`;
      }
      if (attr.status_label === "Locating") {
        dotClass = "dot-returning"; labelClass = "label-locating";
      } else {
        dotClass = `dot-${activity}`; labelClass = `label-${activity}`;
      }
    }
    const errEntity = cfg.error_entity;
    const hasError = activity === "error" ||
      (errEntity && this.hass.states[errEntity]?.state === "on");

    return {
      ...this._batteryView(),
      ...this._mapPlaceholderView(attr),
      name: attr.friendly_name || "Kärcher RCV5",
      statusText, dotClass, labelClass,
      pinging: !isOffline && (activity === "cleaning" || activity === "returning"),
      hasError: !!hasError,
      activity,
      offline: !!isOffline,
      cardMode: this._cardMode,
      busy: this._isBusy(activity),
      tiles: this._statTiles(),
      selectorRows: this._selectorRows(attr),
      badgeState: this._selectionHintState(attr),
      tabHelper: this._tabHelperText(attr),
      roomRows: this._roomListRows(attr),
      mapLoaded: this._mapLoaded,
    };
  }

  // While the robot is mid-job, mutating selection or settings would change
  // the in-flight clean — gray out the Standard chips, Custom tab strip,
  // room list and detail view so the only actions are pause/stop/dock
  // (which live in _buttonsEl and are gated by _updateButtons).
  _isBusy(activity) {
    return isBusy(activity);
  }

  // ── Standard / Customise mode ─────────────────────────────────────────────────

  // State-only mode switch. Does NOT requestUpdate: when called from willUpdate
  // (prefer_mode change) the in-progress cycle already re-derives _view; when
  // called from _setCardMode (user tab) that handler requests the update.
  _applyMode(mode) {
    this._cardMode = mode;
    if (mode === "standard") {
      this._detailRoomId = null;
      this._customiseSelected.clear();
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
    this.requestUpdate(); // user tab switch outside an update cycle → re-render
  }

  // Ask the integration to refetch room preferences now (bypasses the 5-min poll;
  // coordinator throttles to ~5 s). Passes device_id when known so multi-robot
  // setups route correctly. Used by the mount/foreground "fresh on look" trigger.
  _refreshPreferences() {
    const hass = this._hass;
    const vac = this._config?.vacuum_entity;
    if (!hass || !vac) return;
    const deviceId = hass.entities?.[vac]?.device_id;
    hass.callService(
      "karcher_home_robots",
      "refresh_preferences",
      deviceId ? { device_id: deviceId } : {},
    );
  }

  // Reconcile the optimistic enabled-set once per render cycle (called from
  // willUpdate). Single source of truth — the map reads _customiseSelected too.
  _reconcileCustomise(attr) {
    if (this._cardMode !== "customise") return;
    const prefs = attr?.room_preferences || {};
    const roomIds = parseRoomOrder(attr?.room_map || {}, prefs);
    const r = reconcileCustomise(roomIds, prefs, this._customisePending, this._customiseSelected);
    this._customiseSelected = r.selected;
    this._customisePending = r.pending;
  }

  _tabHelperText(attr) {
    if (this._cardMode !== "customise") return "Applies to all rooms";
    const roomMap = attr?.room_map || {};
    const roomIds = parseRoomOrder(roomMap, attr?.room_preferences || {});
    const total = Object.keys(roomMap).length;
    const enabled = roomIds.filter((id) => this._customiseSelected.has(id)).length;
    return `${enabled} of ${total} room${total !== 1 ? "s" : ""} on`;
  }

  _roomListRows(attr) {
    if (this._cardMode !== "customise") return [];
    return deriveRoomRows(
      attr?.room_map || {}, attr?.room_preferences || {},
      this._customiseSelected, this._detailRoomId,
    );
  }

  _onRoomToggle(e) {
    const { roomId, on } = e.detail || {};
    if (on) this._customiseSelected.add(roomId);
    else this._customiseSelected.delete(roomId);
    this._customisePending.set(roomId, on);
    this._toggleRoomCustom(roomId, on);
    this.requestUpdate(); // re-derive view (leaf rows + header) and redraw map overlay
  }

  _onRoomExpand(e) {
    const { roomId } = e.detail || {};
    this._detailRoomId = this._detailRoomId === roomId ? null : roomId;
    this.requestUpdate();
  }

  _onRoomReorder(e) {
    const order = e.detail?.order || [];
    const vacuumEntry = this._hass.entities?.[this._config.vacuum_entity];
    const serviceData = { room_order: order.map((rid) => parseInt(rid, 10)) };
    // device_id disambiguates when the account has more than one robot.
    if (vacuumEntry?.device_id) serviceData.device_id = vacuumEntry.device_id;
    this._hass.callService("karcher_home_robots", "set_room_preference", serviceData);
  }

  _onRoomPref(e) {
    const { roomId, field, value } = e.detail || {};
    this._setRoomPref(roomId, field, value);
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

  // Placeholder text + aspect-ratio + loading flag as view fields. Pure read of
  // hass/config + the _map* side-effect flags (which _updateMap maintains).
  _mapPlaceholderView(attr) {
    const mapEntity = this._config.map_entity;
    if (!mapEntity) return { placeholderText: "Set map_entity in card config" };
    if (!this._hass.states[mapEntity]) return { placeholderText: `Entity not found: ${mapEntity}` };
    const sz = attr.map_image_size;
    const out = {
      mapLoading: this._mapPending,
      mapLoaded: this._mapLoaded,
      aspectRatio: sz ? `${sz.width} / ${sz.height}` : "",
    };
    if (this._mapError) out.placeholderText = "Map unavailable";
    else if (sz) out.placeholderText = "";
    else out.placeholderText = "No map yet — start a cleaning run to generate one.";
    return out;
  }

  // Side effect only (runs from updated()): fetch the map image, size the canvas,
  // and draw. Display/placeholder state flows through _view via _mapPlaceholderView;
  // this method flips the _map* flags and requestUpdate()s when they change.
  _updateMap(attr) {
    const mapEntity = this._config.map_entity;
    const mapState = mapEntity ? this._hass.states[mapEntity] : null;
    if (!mapState) return;

    const pic = mapState.attributes.entity_picture;
    const token = mapState.attributes.access_token || "";
    const imageTimestamp = mapState.state;

    if (imageTimestamp !== this._mapToken) {
      this._mapToken = imageTimestamp;
      this._mapError = false;
      this._mapPending = true;
      const url = pic
        ? `${pic}&_t=${encodeURIComponent(imageTimestamp)}`
        : `/api/image_proxy/${encodeURIComponent(mapEntity)}?token=${encodeURIComponent(token)}&_t=${encodeURIComponent(imageTimestamp)}`;
      const img = new Image();
      this._mapImgLoad = img;
      img.onload = () => {
        if (this._mapImgLoad !== img) return;
        this._mapImgLoad = null;
        this._mapImg = img;
        this._mapLoaded = true;
        this._mapPending = false;
        // Do NOT measure the canvas here: it is still display:none until the
        // re-render below applies the .mapLoaded binding, so getBoundingClientRect
        // would return 0×0 and the map would draw blank. Sizing happens in
        // updated() (_sizeCanvasIfNeeded), after the canvas is visible in layout.
        this._needsCanvasSize = true;
        this.requestUpdate();
      };
      img.onerror = () => {
        if (this._mapImgLoad !== img) return;
        this._mapImgLoad = null;
        this._mapPending = false;
        this._mapError = true;
        this.requestUpdate();
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
    this._robotIconLoad = img;
    img.onload = () => {
      if (this._robotIconLoad !== img) return;
      this._robotIconLoad = null;
      this._robotIcon = img;
      // Redraw if map is already shown.
      if (this._mapLoaded && this._hass && this._config) {
        const attr = this._hass.states[this._config.vacuum_entity]?.attributes;
        if (attr) this._drawMap(attr);
      }
    };
    img.src = "/karcher_home_robots/static/icon.svg";
  }

  // Assemble the plain viewState the module renderer consumes: everything
  // hass-derived is pre-resolved here so the renderer never reads hass/config.
  _viewState(attr) {
    const isCleaning = this._cardMode !== "customise" && (() => {
      const a = this._hass?.states[this._config?.vacuum_entity]?.state;
      return a === "cleaning" || a === "paused";
    })();
    let currentRoomName = null;
    if (isCleaning && this._config.current_room_entity) {
      currentRoomName = this._hass.states[this._config.current_room_entity]?.state ?? null;
    }
    return {
      attr,
      dpr: this._dpr || 1,
      mapImg: this._mapImg,
      robotIcon: this._robotIcon,
      cardMode: this._cardMode,
      detailRoomId: this._detailRoomId,
      selectedRooms: this._selectedRooms,
      customiseSelected: this._customiseSelected,
      activeRoomId: activeRoomId(attr.room_map || {}, currentRoomName, isCleaning),
      mapToken: this._mapToken,
      canvasWidth: this._canvas.width,
      canvasHeight: this._canvas.height,
    };
  }

  _drawMap(attr) {
    if (!this._mapImg || !this._canvas) return;
    const vs = this._viewState(attr);
    const key = computeDrawKey(attr, vs);
    if (key === this._lastDrawKey) return;
    this._lastDrawKey = key;
    this._loadRobotIcon();
    const ctx = this._canvas.getContext("2d");
    // Rebuilt every draw so stale rooms leave no phantom hit areas.
    this._roomCheckboxHitAreas = drawMap(ctx, this._canvas, vs);
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
    const { px, py, snapCol, snapRow } = clientToImagePx(e.clientX, e.clientY, rect, imgSize);

    if (!this._cellLookup || this._cellLookupAttr !== attr) {
      this._cellLookup = buildCellLookup(roomMap, cs);
      this._cellLookupAttr = attr;
    }

    const hitId = hitTestRooms(
      px, py, snapRow, snapCol, this._roomCheckboxHitAreas, this._cellLookup
    );

    if (hitId !== undefined) {
      if (this._cardMode === "customise") {
        const nowOn = !this._customiseSelected.has(hitId);
        if (nowOn) this._customiseSelected.add(hitId);
        else this._customiseSelected.delete(hitId);
        this._customisePending.set(hitId, nowOn);
        this._toggleRoomCustom(hitId, nowOn);
      } else {
        if (this._selectedRooms.has(hitId)) this._selectedRooms.delete(hitId);
        else this._selectedRooms.add(hitId);
      }
      this._lastDrawKey = null;  // selection changed → overlay must redraw
      this.requestUpdate();      // re-derive view (badge/rows) + redraw in updated()
    }
  }

  _onMapChipClick() {
    const vacState = this._hass?.states[this._config?.vacuum_entity];
    if (!vacState) return;
    const roomMap = vacState.attributes?.room_map || {};
    const roomIds = Object.keys(roomMap);
    if (roomIds.length === 0) return;

    if (this._cardMode === "customise") {
      const allEnabled = roomIds.every(id => this._customiseSelected.has(id));
      for (const id of roomIds) {
        const nowOn = !allEnabled;
        if (nowOn === this._customiseSelected.has(id)) continue;
        if (nowOn) this._customiseSelected.add(id);
        else this._customiseSelected.delete(id);
        this._customisePending.set(id, nowOn);
        this._toggleRoomCustom(id, nowOn);
      }
    } else {
      const allSelected = roomIds.every(id => this._selectedRooms.has(id));
      if (allSelected) this._selectedRooms.clear();
      else for (const id of roomIds) this._selectedRooms.add(id);
    }
    this._lastDrawKey = null;
    this.requestUpdate();
  }

  // ── UI helpers ────────────────────────────────────────────────────────────────

  _selectionHintState(attr) {
    const roomMap = attr?.room_map || {};
    const roomIds = Object.keys(roomMap);
    const occupied = isOccupied(this._hass?.states[this._config?.vacuum_entity]?.state);
    const isCustomise = this._cardMode === "customise";
    const selectedSet = isCustomise ? this._customiseSelected : this._selectedRooms;
    const hasRooms = roomIds.length > 0;

    const { chipLabel, badge } = selectionHint(
      roomIds, selectedSet, isCustomise ? "customise" : "default",
      id => roomMap[id]?.name || id,
    );
    return {
      visible: hasRooms && !occupied,
      badge, chipLabel,
      chipVisible: hasRooms,
      chipDisabled: occupied || !hasRooms,
    };
  }

  // Battery header glyph as view fields (was imperative writes in _updateStats).
  _batteryView() {
    const battEntity = this._config.battery_entity;
    if (battEntity) {
      const b = this._hass.states[battEntity];
      if (b && b.state !== "unknown" && b.state !== "unavailable") {
        const pct = parseInt(b.state, 10);
        const chargingEntity = this._config.charging_entity;
        const isCharging = chargingEntity
          ? this._hass.states[chargingEntity]?.state === "on" : false;
        return {
          battVisible: true,
          battPct: `${pct}%`,
          battFillW: `clamp(3px, ${pct}%, calc(100% - 3px))`,
          battFillClass: pct <= 20 ? "fill-low" : "fill-charging",
          charging: isCharging,
        };
      }
    }
    return { battVisible: false };
  }

  _statTiles() {
    const areaState = this._hass.states[this._config.cleaning_area_entity];
    const timeState = this._hass.states[this._config.cleaning_time_entity];
    const occupied = isOccupied(this._hass.states[this._config.vacuum_entity]?.state);
    return deriveStatTiles(areaState, timeState, occupied);
  }

  _selectorRows(attr) {
    if (this._cardMode !== "standard") return [];
    const modeEntityId = this._config.cleaning_mode_entity;
    const modeState = modeEntityId ? this._hass.states[modeEntityId] : null;
    const waterEntityId = this._config.water_level_entity;
    // undefined (not null) when no entity configured → deriveSelectorRows omits
    // the water row; a configured-but-missing entity yields a disabled row.
    const waterState = waterEntityId ? (this._hass.states[waterEntityId] ?? null) : undefined;
    return deriveSelectorRows(attr, modeState, waterState, this._isBusy(attr.state));
  }

  _onSelectorChange(e) {
    const { control, value } = e.detail || {};
    if (control === "mode") {
      this._hass.callService("select", "select_option",
        { entity_id: this._config.cleaning_mode_entity, option: value });
    } else if (control === "suction") {
      this._hass.callService("vacuum", "set_fan_speed",
        { entity_id: this._config.vacuum_entity, fan_speed: value });
    } else if (control === "water") {
      this._hass.callService("select", "select_option",
        { entity_id: this._config.water_level_entity, option: value });
    }
  }

  _onButtonAction(e) {
    // Actions up: route the leaf's bubbling event to the existing handlers.
    const action = e.detail?.action;
    if (action === "play") this._play();
    else if (action === "pause") this._pause();
    else if (action === "stop") this._stop();
    else if (action === "dock") this._dock();
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
    const selectedRoomMap = Object.fromEntries(roomIds.map((id) => [String(id), {}]));
    const ordered = parseRoomOrder(selectedRoomMap, prefs).map((id) => parseInt(id, 10));
    this._hass.callService("vacuum", "send_command", {
      entity_id: vacuumEntity,
      command: "app_segment_clean",
      params: ordered,
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
