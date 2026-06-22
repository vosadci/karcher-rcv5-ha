// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no CI build toolchain. Lit is vendored as a committed
// self-contained ESM bundle (./lit-core.js) — no runtime CDN/import-map needed.
//
// Migration in progress (strangler-fig): UI is being converted to Lit leaves
// one at a time. The leaves render into LIGHT DOM (createRenderRoot returns
// `this`) so they inherit the shell's _CSS sheet — they carry no `css` of their
// own. Data flows DOWN via properties; actions flow UP via dispatchEvent.

import { LitElement, html } from "./lit-core.js";

const VERSION = "1.19.13";
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

// Segment option metadata — single source of truth for the Mode/Suction/Water
// controls. Shared by the standard-mode selector rows (deriveSelectorRows) and
// the per-room detail panel (roomDetailControls); the icon-by-key maps below
// derive from these too. Each callsite layers its own per-option `disabled`.
const MODE_OPTIONS = [
  { value: "vacuum", icon: "mdi:robot-vacuum", label: "Vacuum" },
  { value: "vacuum_and_mop", icon: "mdi:shimmer", label: "Vac & Mop" },
  { value: "mop", icon: "mdi:water", label: "Mop" },
];
const SUCTION_OPTIONS = [
  { value: "silent", icon: "mdi:fan-off", label: "Silent" },
  { value: "standard", icon: "mdi:fan-speed-2", label: "Standard" },
  { value: "medium", icon: "mdi:fan-speed-3", label: "Medium" },
  { value: "turbo", icon: "mdi:fan", label: "Turbo" },
];
const WATER_OPTIONS = [
  { value: "low", icon: "mdi:water-minus", label: "Low" },
  { value: "medium", icon: "mdi:water", label: "Medium" },
  { value: "high", icon: "mdi:water-plus", label: "High" },
];

// Suction / water option → mdi icon (mirror the segment-control icons), used for
// the icon-only parts of the collapsed room-summary line in Customise mode.
const POWER_ICON_BY_KEY = Object.fromEntries(SUCTION_OPTIONS.map((o) => [o.value, o.icon]));
const WATER_ICON_BY_KEY = Object.fromEntries(WATER_OPTIONS.map((o) => [o.value, o.icon]));
const _cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

const _CSS = `
  :host {
    display: block;
    container-type: inline-size;
    --rcv-accent: #FFD400;
    --rcv-accent-deep: #E8BE00;
    --rcv-accent-text: #1a1a1a;
    /* Role tokens — map design roles onto HA theme vars (raw values are
       fallback-only, per the design handoff). New regions reference these so a
       theme swap or a future light/dark tweak happens in one place. */
    --rcv-card: var(--ha-card-background, var(--card-background-color, #1c1c1f));
    --rcv-inset: var(--secondary-background-color, #161618);
    --rcv-text: var(--primary-text-color, #e8e8ea);
    --rcv-text2: var(--secondary-text-color, #9a9aa2);
    --rcv-text3: var(--disabled-text-color, #6c6c74);
    --rcv-divider: var(--divider-color, rgba(255,255,255,0.08));
    --rcv-success: var(--success-color, #4caf50);
    --rcv-warning: var(--warning-color, #ff9800);
    --rcv-danger: var(--error-color, #f44336);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, Helvetica, Arial, sans-serif;
  }

  /* ── single-surface shell ──
     One ha-card, no internal card gaps (the design is one continuous surface).
     Regions stack: header · map · target strip · action bar, with a card-relative
     bottom sheet overlaying them.

     Height is CONTENT-DRIVEN (like the pre-shell card): the map fills the card
     width and its height follows the map's aspect ratio, so the card is as tall
     as the (full-width) map needs — no letterbox bars, no dead space. Set the
     card_height editor field to pin an exact pixel height instead. */
  ha-card.card-shell {
    padding: 0;
    box-sizing: border-box;
    overflow: hidden;
    position: relative;
    display: flex;
    flex-direction: column;
    box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.12));
  }
  .rcv-region { flex-shrink: 0; }

  /* ── header bar: name+status (left) | battery (right) ── */
  .top-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--rcv-divider);
    background: var(--rcv-card);
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
    font-size: 18px;
    letter-spacing: -0.025em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--rcv-text);
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
    font-size: 13px;
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
    gap: 5px;
  }
  .battery-icon {
    --mdc-icon-size: 20px;
    color: var(--success-color, #4caf50);
    transform: rotate(90deg);
  }
  .battery-icon.icon-low { color: var(--error-color, #f44336); }
  .battery-pct {
    font-size: 14px;
    font-weight: 700;
    color: var(--rcv-text);
    font-variant-numeric: tabular-nums;
  }

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

  /* ── map region: full card width, height follows the map aspect ── */
  .rcv-map {
    position: relative;
    width: 100%;
    overflow: hidden;
    /* Card surface (not a distinct map grey) so the letterbox margins beside a
       portrait map blend into the card and read as empty, not as a grey frame. */
    background: var(--rcv-card);
    /* No-map fallback height so the placeholder is visible before a map loads;
       once a map loads the aspect-sized .map-container drives the (taller)
       height. */
    min-height: 280px;
  }
  /* The canvas frame keeps the map's aspect-ratio (bound inline from
     map_image_size). It fills the card width UNTIL its height would exceed the
     cap (--rcv-map-max-height); past that the inline max-width (cap × aspect)
     bounds the width so the height stays at the cap and the frame centres,
     letterboxing a portrait map so the whole card still fits ~one screen. */
  .map-container {
    position: relative;
    width: 100%;
    margin: 0 auto;
    overflow: hidden;
  }
  .map-container canvas {
    display: block;
    width: 100%;
    height: 100%;
    cursor: pointer;
  }
  .map-container canvas.zone-draw {
    cursor: crosshair;
    touch-action: none;
  }

  /* ── floating Rooms|Zone map-mode control (top-left) ── */
  .map-mode {
    position: absolute;
    top: 12px;
    left: 12px;
    z-index: 6;
  }
  .map-mode-inner {
    display: flex;
    gap: 3px;
    padding: 4px;
    border-radius: 13px;
    /* Frosted glass over the (always-white) map render: tinted from the card's
       own surface colour, so it reads as light glass/dark text in light theme
       and dark glass/light text in dark theme, instead of staying a dark blob. */
    background: color-mix(in srgb, var(--rcv-card) 78%, transparent);
    -webkit-backdrop-filter: blur(10px);
    backdrop-filter: blur(10px);
    border: 1px solid color-mix(in srgb, var(--rcv-text) 14%, transparent);
    box-shadow: 0 6px 20px rgba(0,0,0,0.22);
    transition: opacity 0.15s;
  }
  .map-mode-inner.locked { opacity: 0.5; pointer-events: none; }
  .map-mode-btn {
    display: flex;
    align-items: center;
    gap: 7px;
    height: 36px;
    padding: 0 13px;
    border: none;
    border-radius: 10px;
    cursor: pointer;
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    background: transparent;
    color: color-mix(in srgb, var(--rcv-text) 82%, transparent);
    transition: background 0.14s, color 0.14s;
    --mdc-icon-size: 16px;
  }
  .map-mode-btn.active {
    background: var(--rcv-accent);
    color: var(--rcv-accent-text);
    font-weight: 800;
  }

  /* ── contextual hint bar (own row below the map, not overlaid — room pills
     can land anywhere on the map, so a floating overlay risked covering one) ── */
  .map-hint {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 9px 13px;
    margin: 8px 12px;
    border-radius: 11px;
    background: var(--rcv-inset);
  }
  .map-hint ha-icon { --mdc-icon-size: 15px; color: var(--rcv-accent); flex-shrink: 0; }
  .map-hint span { font-size: 12.5px; font-weight: 600; color: var(--rcv-text2); line-height: 1.35; }
  .map-hint.hint-hidden { display: none; }
  .legend { padding: 8px 4px 0; }
  .legend-hidden { display: none; }
  .legend-items { display: flex; flex-wrap: wrap; gap: 6px 14px; }
  .legend-chip {
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 12px; color: var(--primary-text-color);
  }
  .legend-sw { flex: 0 0 auto; }
  .legend-swatch { width: 12px; height: 12px; border-radius: 3px; border: 1px solid rgba(0,0,0,0.25); }
  .legend-line { width: 14px; height: 3px; border-radius: 2px; }
  .legend-dot { width: 10px; height: 10px; border-radius: 50%; border: 1px solid rgba(0,0,0,0.2); }
  .legend-ring { border: 1.5px solid rgba(0,0,0,0.55); }
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

  /* ── action bar: full-width primary pill + two 54×54 icon squares ── */
  .buttons {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .btn-wrap {
    height: 54px;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    border: 1px solid var(--rcv-divider);
    background: var(--rcv-inset);
    color: var(--rcv-text2);
    font-family: inherit;
    cursor: pointer;
    padding: 0;
    --mdc-icon-size: 24px;
    transition: transform 0.12s ease, background 0.15s, box-shadow 0.15s;
  }
  .btn-wrap.primary {
    flex: 1;
    background: var(--rcv-accent);
    border: none;
    color: var(--rcv-accent-text);
    box-shadow: 0 6px 18px color-mix(in srgb, var(--rcv-accent) 45%, transparent);
  }
  .btn-wrap.danger,
  .btn-wrap.secondary {
    flex: 0 0 54px;
    width: 54px;
  }
  .btn-wrap.danger { color: var(--rcv-danger); }
  .btn-wrap.disabled,
  .btn-wrap:disabled {
    background: var(--rcv-inset);
    border: 1px solid var(--rcv-divider);
    color: var(--rcv-text3);
    box-shadow: none;
    cursor: default;
    opacity: 0.55;
  }
  @media (prefers-reduced-motion: no-preference) {
    .btn-wrap:not(.disabled):not(:disabled):active { transform: scale(0.93); }
  }
  .btn-wrap .btn-label {
    font-size: 16px;
    font-weight: 800;
    line-height: 1;
    white-space: nowrap;
  }
  /* Stop/Dock are icon-only squares: keep the label in the DOM for a11y (and the
     leaf's render/tests) but hide it visually. */
  .btn-wrap.danger .btn-label,
  .btn-wrap.secondary .btn-label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
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

  /* ── Standard settings — mode, suction, water ── */
  .standard-settings {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /* ── Area mode note ── */
  .area-note {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    margin-top: 10px;
    border-radius: 10px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--secondary-text-color);
    background: color-mix(in srgb, var(--rcv-accent) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--rcv-accent) 30%, transparent);
  }
  .area-note ha-icon {
    --mdc-icon-size: 15px;
    color: var(--rcv-accent-deep);
    flex-shrink: 0;
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
    min-width: 4.5em;
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
  /* While an area is selected, room selection is disabled (mutually exclusive). */
  .room-list.zone-locked { opacity: 0.55; pointer-events: none; }
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

  /* ── target strip: tappable row that opens the sheet ── */
  .target-strip {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 50px;
    padding: 0 16px;
    border: none;
    border-top: 1px solid var(--rcv-divider);
    background: var(--rcv-card);
    cursor: pointer;
    font-family: inherit;
    text-align: left;
    width: 100%;
    box-sizing: border-box;
  }
  .target-strip:disabled { cursor: default; }
  .target-strip > ha-icon { --mdc-icon-size: 17px; color: var(--rcv-accent-deep); flex-shrink: 0; }
  .target-strip-label {
    flex: 1;
    min-width: 0;
    font-size: 14px;
    font-weight: 700;
    color: var(--rcv-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .target-strip-edit { font-size: 12.5px; font-weight: 600; color: var(--rcv-accent-deep); }
  .target-strip-chevron { --mdc-icon-size: 16px; color: var(--rcv-text3); flex-shrink: 0; }

  /* ── action bar region (wraps the button row) ── */
  .action-bar {
    background: var(--rcv-card);
    border-top: 1px solid var(--rcv-divider);
    padding: 10px 16px 14px;
    padding-bottom: calc(14px + env(safe-area-inset-bottom));
  }

  /* ── bottom sheet (card-relative: anchored to the shell, not the viewport) ── */
  .sheet-scrim {
    position: absolute;
    inset: 0;
    z-index: 40;
    background: rgba(0,0,0,0.5);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.25s;
  }
  .sheet-scrim.open { opacity: 1; pointer-events: auto; }
  .sheet {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 50;
    height: 78%;
    max-height: 78%;
    border-radius: 22px 22px 0 0;
    background: var(--rcv-card);
    border-top: 1px solid var(--rcv-divider);
    box-shadow: 0 -16px 56px rgba(0,0,0,0.45);
    transform: translateY(110%);
    transition: transform 0.32s cubic-bezier(0.32,0.72,0,1);
    display: flex;
    flex-direction: column;
  }
  .sheet.open { transform: translateY(0); }
  @media (prefers-reduced-motion: reduce) {
    .sheet, .sheet-scrim { transition: none; }
  }
  .sheet-handle {
    display: flex;
    justify-content: center;
    padding: 14px 0 6px;
    flex-shrink: 0;
  }
  .sheet-handle span {
    width: 38px;
    height: 5px;
    border-radius: 3px;
    background: var(--rcv-divider);
  }
  .sheet-tabs {
    display: flex;
    gap: 6px;
    padding: 0 16px 14px;
    flex-shrink: 0;
  }
  .sheet-tab {
    flex: 1;
    height: 38px;
    border: none;
    border-radius: 11px;
    cursor: pointer;
    font-family: inherit;
    font-size: 14px;
    font-weight: 600;
    background: var(--rcv-inset);
    color: var(--rcv-text2);
    transition: background 0.13s, color 0.13s;
  }
  .sheet-tab.active {
    background: var(--rcv-accent);
    color: var(--rcv-accent-text);
    font-weight: 800;
  }
  .sheet-body {
    flex: 1;
    overflow-y: auto;
    padding: 0 16px 24px;
  }
  .sheet-panel { display: none; }
  .sheet-panel.active { display: block; }

  /* ── "What gets cleaned": whole-home banner + room chips / zone summary ── */
  .whole-home-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 11px 14px;
    border-radius: 12px;
    margin-bottom: 10px;
    background: color-mix(in srgb, var(--rcv-accent) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--rcv-accent) 55%, transparent);
    font-size: 13px;
    font-weight: 700;
    color: var(--rcv-text);
  }
  .whole-home-banner ha-icon { --mdc-icon-size: 17px; color: var(--rcv-accent-deep); }
  .room-chips { display: flex; flex-wrap: wrap; gap: 7px; }
  .room-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px 8px 10px;
    border-radius: 999px;
    cursor: pointer;
    font-family: inherit;
    font-size: 13px;
    font-weight: 700;
    background: var(--rcv-inset);
    border: 1px solid var(--rcv-divider);
    color: var(--rcv-text2);
    transition: background 0.13s, color 0.13s, border-color 0.13s;
  }
  .room-chip.on {
    background: var(--rcv-accent);
    border-color: transparent;
    color: var(--rcv-accent-text);
  }
  .room-chip:disabled { opacity: 0.55; cursor: default; }
  .room-chip-check {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1.5px solid var(--rcv-divider);
    --mdc-icon-size: 11px;
  }
  .room-chip.on .room-chip-check {
    background: var(--rcv-accent-text);
    border: none;
    color: var(--rcv-accent);
  }
  .room-chip-area { font-size: 11px; font-weight: 600; opacity: 0.7; }
  .zone-summary {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--rcv-inset);
    border: 1px solid var(--rcv-divider);
    font-size: 13.5px;
    font-weight: 600;
    color: var(--rcv-text2);
  }
  .zone-summary ha-icon { --mdc-icon-size: 18px; color: var(--rcv-accent-deep); }

  /* ── busy lock banner (sheet settings panel) ── */
  .busy-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    margin-bottom: 12px;
    border-radius: 10px;
    background: color-mix(in srgb, var(--rcv-accent) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--rcv-accent) 40%, transparent);
    font-size: 12.5px;
    font-weight: 600;
    color: var(--rcv-text2);
  }
  .busy-banner ha-icon { --mdc-icon-size: 15px; color: var(--rcv-accent-deep); flex-shrink: 0; }
  .settings-lockable.busy { opacity: 0.5; pointer-events: none; }

`;

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

// Pure: compute the next editor config after an entity-picker change. Sets (or
// clears, when empty) the changed key; when the vacuum entity itself changes,
// drops any companion override that was still at its old derived default so it
// re-derives from the new stem. Strips undefined keys. Never mutates prevConfig.
export function nextEditorConfig(prevConfig, configKey, value) {
  const prev = prevConfig || {};
  const next = { ...prev };
  next[configKey] = value || undefined;
  if (configKey === "vacuum_entity") {
    const oldDerived = deriveCompanions(prev.vacuum_entity);
    for (const { key } of _EDITOR_COMPANIONS) {
      if (!next[key] || next[key] === oldDerived[key]) delete next[key];
    }
  }
  for (const k of Object.keys(next)) {
    if (next[k] === undefined) delete next[k];
  }
  return next;
}

// ── Pure helpers extracted for unit testing (no DOM/canvas access) ────────────

// True when a raw state value is present and not one of HA's placeholder states.
// (Empty/missing values are also unusable.)
export function isUsableValue(state) {
  return !!state && state !== "unknown" && state !== "unavailable";
}

// True when a state OBJECT exists and holds a usable value (the common
// `s && s.state !== "unknown"/"unavailable"` guard, in one place).
export function isUsableState(s) {
  return !!s && isUsableValue(s.state);
}

export function isBusy(activity) {
  return activity === "cleaning" || activity === "returning";
}

// MDI outline battery family only has three filled levels (low/medium/high)
// plus the empty outline glyph at <=20% — no separate 100% icon, so high
// covers everything above 80% including full. Charging variants mirror the levels.
export function batteryIcon(pct, charging) {
  const clamped = Math.max(0, Math.min(100, pct));
  const prefix = charging ? "mdi:battery-charging" : "mdi:battery";
  let level;
  if (clamped <= 20) level = "outline";
  else if (clamped > 80) level = "high";
  else if (clamped > 40) level = "medium";
  else level = "low";
  return `${prefix}-${level}`;
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

// Smallest area-clean rectangle worth sending: one robot-width square.
// Robot is ~34cm wide; resolution=0.05m/cell → ~7 cells per side (see drawRobot).
// Matches the Kärcher app's own AreaMap.AREA_MIN_SIZE clamp-while-dragging
// approach (no zero-size rect ever exists, rather than validating on release).
const MIN_ZONE_CELLS = 7;

export function minZonePx(cellSize) {
  return MIN_ZONE_CELLS * (cellSize || 1);
}

// Push the dragged corner (x1,y1) out from the anchor (x0,y0) so neither side
// of the rect can shrink below minPx — same live-clamp behavior as the
// Kärcher app's corner-drag handler, applied to a fresh drag gesture.
export function clampZoneRect(rect, minPx) {
  const { x0, y0, x1, y1 } = rect;
  const dx = x1 - x0;
  const dy = y1 - y0;
  const sign = (v) => (v < 0 ? -1 : 1);
  const cx1 = Math.abs(dx) < minPx ? x0 + sign(dx) * minPx : x1;
  const cy1 = Math.abs(dy) < minPx ? y0 + sign(dy) * minPx : y1;
  return { x0, y0, x1: cx1, y1: cy1 };
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
// returns exactly 3 tiles (Area, Duration, Finished) so the card's
// stat strip has a stable layout; any tile with no usable data shows "-". ALL
// the branching lives here (entity missing, unknown/unavailable, NaN, area>0,
// time "0", and the finished-at tile only when not occupied) so it is
// unit-testable; the leaf just renders the returned [{ value, label, icon }]
// list and the shell only does the trivial hass lookups. `now` is threaded
// for deterministic tests.
export function deriveStatTiles(areaState, timeState, occupied, now = Date.now()) {
  const valid = isUsableState;

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
    { value: areaValue, label: "Area", icon: "mdi:floor-plan" },
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
export function deriveSelectorRows(attr, modeState, waterState) {
  const rows = [];
  const fanSpeed = attr?.fan_speed;
  const fanSpeedList = attr?.fan_speed_list || [];

  if (modeState) {
    const disabledOpts = new Set(modeState.attributes?.disabled_options || []);
    rows.push({
      control: "mode",
      label: "Mode",
      value: modeState.state,
      disabled: false,
      options: MODE_OPTIONS.map((o) => ({ ...o, disabled: disabledOpts.has(o.value) })),
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
      disabled: isMop,
      options: SUCTION_OPTIONS.map((o) => ({ ...o, disabled: off(o.value) })),
    });
  }

  // Water row appears whenever the entity is configured (waterState !== undefined,
  // even if unavailable); it is disabled in vacuum mode or when state is missing.
  if (waterState !== undefined) {
    const unavailable = !isUsableState(waterState);
    const isVacuum = modeState?.state === "vacuum";
    rows.push({
      control: "water",
      label: "Water",
      value: unavailable ? null : waterState.state,
      disabled: unavailable || !modeState?.state || isVacuum,
      options: WATER_OPTIONS.map((o) => ({ ...o })),
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
    seg("Repeat", "repeat", REPEAT_BY_INT[pref.repeat], [
      { value: "single", label: "×1" }, { value: "double", label: "×2" },
    ]),
    seg("Mode", "mode", MODE_BY_INT[pref.mode], MODE_OPTIONS.map((o) => ({ ...o }))),
    seg("Suction", "power", POWER_BY_INT[pref.power], SUCTION_OPTIONS.map((o) => ({ ...o }))),
    // Water is gated off in vacuum mode (matches the standard-mode selector).
    seg("Water", "water", WATER_BY_INT[pref.water], WATER_OPTIONS.map((o) => ({ ...o })),
      MODE_BY_INT[pref.mode] === "vacuum"),
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

// Shared segmented-control row template — one Mode/Suction/Water/etc. field row.
// Used by both the standard-mode selector leaf and the per-room detail panel.
// Presentational only: callers own their optimistic-highlight state (compute
// `active`) and pass a unique `idBase` (aria), the `compact` decision, and an
// `onSelect(opt, optDisabled)` handler. Per-button disable is the general form
// `rowDisabled || opt.disabled` so per-option flags (mode disabled_options,
// suction fan_speed filtering) and whole-row gating both work.
function segmentRow({ idBase, label, rowDisabled, compact, active, options, onSelect }) {
  return html`
    <div class="field-row">
      <span class="field-row-label" id=${idBase}>${label}</span>
      <div class="field-row-control">
        <div class="segmented ${rowDisabled ? "seg-disabled" : ""} ${compact ? "seg-compact" : ""}"
          role="group" aria-labelledby=${idBase}>
          ${options.map((opt) => {
            const optDisabled = rowDisabled || !!opt.disabled;
            return html`
              <button
                class="seg-btn ${opt.value === active ? "active" : ""}"
                aria-pressed=${opt.value === active} aria-label=${opt.label}
                ?disabled=${optDisabled}
                @click=${() => onSelect(opt, optDisabled)}
              >${opt.icon ? html`<ha-icon icon=${opt.icon}></ha-icon>` : null}<span class="seg-label">${opt.label}</span></button>`;
          })}
        </div>
      </div>
    </div>`;
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
      ? "Tap a room to select"
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

// One-line summary for the target strip (the tappable row that opens the sheet),
// mirroring the prototype's getTargetLabel. `mode` is "zone" (area draw) or
// anything else (rooms). Rooms: "Whole home" when nothing selected, else the
// first two names + " +N". Zone: single-rect copy (we ship one area at a time).
// names() maps a room id to its display name. Pure — unit-tested directly.
export function targetStripLabel(mode, selectedIds, hasZone, names) {
  if (mode === "zone") {
    return hasZone ? "Area selected" : "Draw an area on the map";
  }
  const sel = [...(selectedIds || [])];
  if (sel.length === 0) return "Whole home";
  const nameOf = typeof names === "function" ? names : (id => id);
  const picked = sel.slice(0, 2).map(nameOf);
  return sel.length <= 2 ? picked.join(", ") : `${picked[0]}, ${picked[1]} +${sel.length - 2}`;
}

// Play/Stop/Dock button icon+label mapping for a given vacuum activity. The
// enabled/disabled decisions live in buttonStates(); this is the user-facing
// text/icon layer only. cleaning/returning → Pause, paused → Resume; the resting
// "Start" is the default the shell overrides with a context-aware clean label
// (see primaryCleanLabel).
export function buttonLabels(activity) {
  const inProgress = activity === "cleaning" || activity === "returning";
  const isPaused = activity === "paused";
  return {
    playIcon: inProgress ? "mdi:pause" : "mdi:play",
    playLabel: inProgress ? "Pause" : (isPaused ? "Resume" : "Start"),
    playAction: inProgress ? "pause" : "play",
    dockLabel: "Dock",
  };
}

// Context-aware primary label for a resting robot (idle/docked), per the design:
// Rooms mode names the selection ("Clean whole home" / "Clean N rooms"); Zone
// mode is "Clean area" once drawn, else the disabled "Draw an area first". The
// shell passes this to the button row as a label override; while the robot is
// occupied the row falls back to buttonLabels (Pause/Resume). Pure.
export function primaryCleanLabel(mapMode, roomCount, hasZone) {
  if (mapMode === "zone") return hasZone ? "Clean area" : "Draw an area first";
  return roomCount > 0
    ? `Clean ${roomCount} room${roomCount !== 1 ? "s" : ""}`
    : "Clean whole home";
}

// Room-label chip text: the room name only (the m² area was dropped from the
// on-map pills). Returns the string the canvas renders. Pure — used by
// drawRoomLabels and unit-tested directly.
export function roomChipText(room) {
  return room?.name || room?.id || "";
}

// Resolve which room is currently being cleaned, by matching the live
// current-room name against room_map. Returns the room id (string) or null.
// The card derives currentRoomName from hass so the renderer never reads hass.
export function activeRoomId(roomMap, currentRoomName, isCleaning) {
  if (!isCleaning || !isUsableValue(currentRoomName)) return null;
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
    viewState.zoneRect
      ? `${viewState.zoneRect.x0},${viewState.zoneRect.y0},${viewState.zoneRect.x1},${viewState.zoneRect.y1}`
      : "",
  ].join("|");
}

// ---------------------------------------------------------------------------
// AI-object type id → [label, dot colour]. Colours mirror map_render._OBJECT_TYPES
// exactly so a legend dot matches the dot drawn on the map. Unknown ids fall back
// to a grey "Object".
const OBJECT_LABELS = {
  "1001": ["Sock", "rgb(220,120,60)"],
  "1002": ["Shoe", "rgb(180,100,40)"],
  "1003": ["Wire", "rgb(230,60,60)"],
  "1006": ["Cat", "rgb(160,100,200)"],
  "1007": ["Dog", "rgb(160,100,200)"],
  "1011": ["Pet waste", "rgb(200,60,60)"],
  "1017": ["Scale", "rgb(80,140,200)"],
  "1038": ["Chair", "rgb(120,120,120)"],
};

// Pure: build the dynamic map-legend rows from the vacuum entity's attributes.
// Returns only symbols actually present in the current map. Zone/object/carpet
// presence comes from the `map_legend` attribute (computed server-side); robot,
// dock and path are inferred from the px overlays the card already receives.
// Swatch colours use the zones' solid outline colours (the fills are ~18 %
// alpha and would be invisible at swatch size).
export function legendItems(attr) {
  const items = [];
  const L = (attr && attr.map_legend) || {};
  // Zone swatches mirror the map: a light fill (the ~18 % alpha overlay) with the
  // solid outline colour as the border — so they read at the same brightness as
  // the map, not as solid blocks. Dot/line colours match what drawMap paints.
  if (L.no_go) items.push({ key: "no_go", label: "No-go", kind: "swatch", fill: "rgba(220,60,60,0.20)", color: "rgb(200,40,40)", count: L.no_go });
  if (L.no_mop) items.push({ key: "no_mop", label: "No-mop", kind: "swatch", fill: "rgba(70,110,220,0.20)", color: "rgb(50,90,200)", count: L.no_mop });
  if (L.virtual_wall) items.push({ key: "wall", label: "Wall", kind: "line", color: "rgb(200,40,40)", count: L.virtual_wall });
  if (L.area_clean) items.push({ key: "area_clean", label: "Cleaning area", kind: "swatch", fill: "rgba(77,182,196,0.22)", color: "rgb(60,150,165)", count: L.area_clean });
  if (L.carpet) items.push({ key: "carpet", label: "Carpet", kind: "swatch", fill: "rgb(236,236,236)", color: "rgba(0,0,0,0.18)" });
  if (attr && attr.robot_px) items.push({ key: "robot", label: "Robot", kind: "dot", color: "#fff", ring: true });
  // drawCharger paints a teal disc with a white centre (a ring, not a filled
  // dot) — mirror that exactly rather than a solid teal fill.
  if (attr && attr.charger_px) {
    items.push({ key: "dock", label: "Dock", kind: "dot", color: "#fff", ringColor: "#4db6c4", ring: true });
  }
  if (attr && Array.isArray(attr.cur_path_px) && attr.cur_path_px.length) {
    items.push({ key: "path", label: "Path", kind: "line", color: "#999" });
  }
  const objs = L.objects || {};
  for (const typeId of Object.keys(objs)) {
    const [label, color] = OBJECT_LABELS[typeId] || ["Object", "rgb(160,160,160)"];
    items.push({ key: "obj_" + typeId, label, kind: "dot", color, count: objs[typeId] });
  }
  return items;
}

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
  drawZoneRect(ctx, canvas, vs);
  return hitAreas;
}

function drawZoneRect(ctx, canvas, vs) {
  const r = vs.zoneRect;
  if (!r) return;
  const imgSize = vs.attr?.map_image_size;
  if (!imgSize) return;
  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const x = Math.min(r.x0, r.x1) * scaleX;
  const y = Math.min(r.y0, r.y1) * scaleY;
  const w = Math.abs(r.x1 - r.x0) * scaleX;
  const h = Math.abs(r.y1 - r.y0) * scaleY;
  ctx.save();
  // Fill — strong enough to read as a region over any room colour.
  ctx.fillStyle = "rgba(77,182,196,0.30)";
  ctx.fillRect(x, y, w, h);
  // Marching-ants border: a solid white halo underneath keeps the box visible
  // on dark/coloured rooms, with a bold dashed deep-teal stroke on top for
  // contrast on light ones — so it stands out against the pastel map palette.
  ctx.lineJoin = "round";
  ctx.strokeStyle = "rgba(255,255,255,0.95)";
  ctx.lineWidth = 4;
  ctx.strokeRect(x, y, w, h);
  ctx.setLineDash([7, 5]);
  ctx.strokeStyle = "#15707f";
  ctx.lineWidth = 2.5;
  ctx.strokeRect(x, y, w, h);
  ctx.restore();
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

    const pw = tw + fontSize * 1.8;

    const pillX = cx - pw / 2;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.35)";
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 1;
    ctx.fillStyle = isSelected ? "rgba(255,212,0,0.75)" : "rgba(255,255,255,0.7)";
    ctx.beginPath();
    ctx.roundRect(pillX, cy - ph / 2, pw, ph, ph / 2);
    ctx.fill();
    ctx.restore();
    ctx.strokeStyle = "rgba(0,0,0,0.15)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.textAlign = "left";
    const textX = pillX + fontSize * 0.9;
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

    // Hit area: the whole pill, in image-space.
    hitAreas.push({
      id,
      x: pillX / scaleX,
      y: (cy - ph / 2) / scaleY,
      w: pw / scaleX,
      h: ph / scaleY,
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
  static properties = {
    activity: { attribute: false },
    offline: { attribute: false },
    playDisabled: { attribute: false },
    // Optional primary-label override (shell's context-aware clean label); when
    // unset the row uses buttonLabels (Start/Pause/Resume).
    playLabel: { attribute: false },
  };

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
        class="btn-wrap ${variant} ${enabled ? "" : "disabled"}"
        ?disabled=${!enabled}
        @click=${enabled ? () => this._emit(action) : null}
      >
        <ha-icon icon=${icon}></ha-icon>
        <span class="btn-label">${label}</span>
      </button>`;
  }

  render() {
    const activity = this.activity;
    const { isOffline, canStop, canDock } = buttonStates(activity, this.offline);
    const { playIcon, playLabel, playAction, dockLabel } = buttonLabels(activity);
    const primaryLabel = this.playLabel ?? playLabel;
    return html`
      ${this._btn(playIcon, primaryLabel, "primary", !isOffline && !this.playDisabled, playAction)}
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
    return segmentRow({
      idBase: `seg-lbl-${row.control}`,
      label: row.label,
      rowDisabled: row.disabled,
      compact,
      active,
      options: row.options,
      onSelect: (opt, optDisabled) => this._select(row.control, opt.value, optDisabled),
    });
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
  static properties = {
    rows: { attribute: false },
    busy: { attribute: false },
    // Standard-mode list: enable/disable only — no reorder, no expand/detail.
    simple: { attribute: false },
  };

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
    if (this.busy || this.simple) { e.preventDefault(); return; }
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
    if (this.simple) return;
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
    if (this.simple) return;
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
    return segmentRow({
      idBase: `rseg-lbl-${roomId}-${c.field}`,
      label: c.label,
      rowDisabled: c.disabled,
      compact,
      active,
      options: c.options,
      onSelect: (opt) => this._onPref(roomId, c.field, opt.value, c.disabled),
    });
  }

  _roomRow(r) {
    const simple = this.simple;
    const cls = `room-row${r.expanded ? " expanded" : ""}${!r.enabled ? " disabled-room" : ""}`;
    return html`
      <div class="${cls}" data-room-id=${r.id} draggable=${simple ? "false" : "true"}
        @dragstart=${(e) => this._onDragStart(e, r.id)}
        @dragend=${(e) => this._onDragEnd(e)}>
        <div class="room-row-header" draggable="false">
          ${simple ? null : html`<span class="room-drag-handle" title="Drag to reorder">⠿</span>`}
          <span class="room-color-dot" style="background:${_roomColor(r.colorId)}"></span>
          <div class="room-text ${simple ? "" : "room-row-select"}"
            @click=${simple ? null : (e) => this._onTextClick(e, r)}>
            <div class="room-text-inner">
              <span class="room-name">${r.name}</span>
              ${!simple && r.hasPref && !r.expanded ? html`<div class="room-summary">${roomSummaryParts(r.summary)}</div>` : null}
            </div>
            ${simple ? null : html`<span class="room-chevron ${r.expanded ? "open" : ""}"
              style=${r.enabled ? "" : "visibility:hidden"}>›</span>`}
          </div>
          <button class="room-toggle ${r.enabled ? "on" : ""}"
            aria-label=${r.enabled ? "Disable room" : "Enable room"}
            @click=${(e) => this._onToggle(e, r)}>
            <span class="room-toggle-knob"></span>
          </button>
        </div>
        ${!simple && r.detail.length ? html`<div class="room-inline-detail">
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
      ${this.simple ? null : html`<div class="room-list-footer">⠿ Drag to set cleaning order</div>`}`;
  }
}
if (!customElements.get("karcher-room-list")) {
  customElements.define("karcher-room-list", KarcherRoomList);
}

// ---------------------------------------------------------------------------
// Lit leaf: floating Rooms|Zone map-mode control (top-left of the map hero).
//
// The map-interaction axis, split out from the old 3-way settings tab. Light DOM
// (inherits .map-mode CSS). Data down: the shell sets `.mode` ("rooms" | "zone")
// and `.locked`. Up: a click emits `karcher-map-mode` ({ detail: { mode } }); the
// shell maps "zone" onto its existing Area cardMode and "rooms" back to the last
// non-area settings mode — the prefer_type wiring underneath is unchanged.
// ---------------------------------------------------------------------------
class KarcherMapMode extends LitElement {
  static properties = {
    mode: { attribute: false },
    locked: { attribute: false },
  };

  createRenderRoot() { return this; }

  _emit(mode) {
    if (this.locked) return;
    this.dispatchEvent(new CustomEvent("karcher-map-mode", {
      detail: { mode }, bubbles: true, composed: true,
    }));
  }

  _btn(value, label, icon) {
    const on = this.mode === value;
    return html`
      <button class="map-mode-btn ${on ? "active" : ""}" aria-pressed=${on}
        @click=${() => this._emit(value)}>
        <ha-icon icon=${icon}></ha-icon><span>${label}</span>
      </button>`;
  }

  render() {
    return html`
      <div class="map-mode-inner ${this.locked ? "locked" : ""}" role="group" aria-label="Map mode">
        ${this._btn("rooms", "Rooms", "mdi:view-grid-outline")}
        ${this._btn("zone", "Zone", "mdi:select-drag")}
      </div>`;
  }
}
if (!customElements.get("karcher-map-mode")) {
  customElements.define("karcher-map-mode", KarcherMapMode);
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
    this._cardMode = "standard";         // "standard" | "customise" | "area"
    this._lastPreferMode = null;         // last robot-reported prefer_mode
    this._pendingPreferMode = null;      // backend value sent but not yet confirmed by the robot
    this._pendingCardMode = null;        // UI cardMode the pending backend value should confirm into
    this._pendingPrefRefresh = false;    // request a "fresh on look" preference refetch
    this._onVisibilityChange = null;     // bound visibilitychange handler (mount/foreground)
    this._detailRoomId = null;           // string room_id when detail is open
    this._customiseSelected = new Set(); // selected room IDs in Customise mode
    this._customisePending = new Map();  // id → expected custom (optimistic) until HA confirms
    this._roomCheckboxHitAreas = [];     // [{id, x, y, size} in image-space] rebuilt each _drawRoomLabels
    this._lastDrawKey = null;
    this._zoneMode = false;              // area-draw mode active
    this._zoneRect = null;               // {x0,y0,x1,y1} in image-space px, or null
    this._zoneDragging = false;
    this._sheetOpen = false;             // bottom sheet visibility
    this._sheetTab = "target";           // "target" | "settings"
    this._lastSettingsMode = "standard"; // restored when leaving Zone back to Rooms
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
    // Two derived axes over the unchanged tri-state cardMode: the floating map
    // control reads Rooms|Zone (Zone ⟺ Area), the sheet reads Standard|Customise.
    const mapMode = v.cardMode === "area" ? "zone" : "rooms";
    const settingsMode = v.cardMode === "customise" ? "customise" : "standard";
    const sheetOpen = !!this._sheetOpen;
    const sheetTab = this._sheetTab || "target";
    const targetIcon = mapMode === "zone" ? "mdi:select-drag" : "mdi:view-grid-outline";
    return html`
      <style>${_CSS}</style>
      <ha-card class="card-shell" style=${this._config?.card_height
        ? `height:${this._config.card_height}px;min-height:${this._config.card_height}px`
        : ""}>
        <div class="top-bar rcv-region">
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
              <ha-icon class="battery-icon ${v.battIconClass || ""}" icon=${v.battIcon || "mdi:battery-unknown"}></ha-icon>
              <span class="battery-pct">${v.battPct || ""}</span>
            </span>
          </div>
        </div>

        <ha-alert alert-type="error" class="rcv-region ${v.hasError ? "visible" : ""}">Robot reported a fault</ha-alert>

        <div class="rcv-map">
          <div class="map-placeholder ${v.mapLoading ? "map-loading" : ""}"
               style=${v.mapLoaded ? "display:none" : ""}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z"></path>
            </svg>
            <span>${v.placeholderText || ""}</span>
          </div>
          <div class="map-container" style=${v.aspectRatio
            ? `aspect-ratio:${v.aspectRatio};max-width:calc(var(--rcv-map-max-height, 64dvh) * ${v.mapAspect})`
            : ""}>
            <canvas class=${v.zoneMode ? "zone-draw" : ""}
              style=${v.mapLoaded ? "display:block" : "display:none"}
              @click=${(e) => this._onCanvasClick(e)}
              @pointerdown=${(e) => this._onZonePointerDown(e)}
              @pointermove=${(e) => this._onZonePointerMove(e)}
              @pointerup=${(e) => this._onZonePointerUp(e)}></canvas>
          </div>
          <karcher-map-mode class="map-mode" .mode=${mapMode} .locked=${v.controlsLocked}
            @karcher-map-mode=${(e) => this._onMapMode(e)}></karcher-map-mode>
        </div>

        <div class="map-hint ${v.mapLoaded ? "" : "hint-hidden"}">
          <ha-icon icon=${targetIcon}></ha-icon>
          <span>${mapMode === "zone"
            ? "Drag to draw an area · press Start to clean it."
            : "Tap rooms to select. Empty = whole home."}</span>
        </div>

        <button class="target-strip rcv-region" ?disabled=${v.controlsLocked}
          @click=${() => this._openSheet()}>
          <ha-icon icon=${targetIcon}></ha-icon>
          <span class="target-strip-label">${v.targetLabel || ""}</span>
          <span class="target-strip-edit">Edit</span>
          <ha-icon class="target-strip-chevron" icon="mdi:chevron-up"></ha-icon>
        </button>

        <div class="action-bar rcv-region">
          <karcher-button-row class="buttons" .activity=${v.activity} .offline=${!!v.offline}
            .playLabel=${v.primaryLabel}
            .playDisabled=${v.cardMode === "area" && !v.zoneRect
              && v.activity !== "cleaning" && v.activity !== "paused" && v.activity !== "returning"}
            @karcher-action=${(e) => this._onButtonAction(e)}></karcher-button-row>
        </div>

        <div class="sheet-scrim ${sheetOpen ? "open" : ""}" @click=${() => this._closeSheet()}></div>
        <div class="sheet ${sheetOpen ? "open" : ""}" role="dialog" aria-label="Cleaning options" aria-hidden=${!sheetOpen}>
          <div class="sheet-handle"><span></span></div>
          <div class="sheet-tabs">
            <button class="sheet-tab ${sheetTab === "target" ? "active" : ""}"
              @click=${() => this._setSheetTab("target")}>What gets cleaned</button>
            <button class="sheet-tab ${sheetTab === "settings" ? "active" : ""}"
              @click=${() => this._setSheetTab("settings")}>Settings</button>
          </div>
          <div class="sheet-body">
            <div class="sheet-panel ${sheetTab === "target" ? "active" : ""}">
              ${this._renderCleanTarget(v, mapMode)}
              <karcher-stats-row class="stats-line" .tiles=${v.tiles || []}></karcher-stats-row>
              <div class="legend ${v.legend && v.legend.length ? "" : "legend-hidden"}">
                <div class="legend-items">
                  ${(v.legend || []).map((it) => html`
                    <span class="legend-chip">
                      <span class="legend-sw legend-${it.kind} ${it.ring ? "legend-ring" : ""}"
                        style=${it.kind === "swatch"
                          ? `background:${it.fill};border-color:${it.color}`
                          : it.ringColor
                            ? `background:${it.color};border-color:${it.ringColor}`
                            : `background:${it.color}`}></span>
                      <span class="legend-label">${it.label}${it.count > 1 ? ` ×${it.count}` : ""}</span>
                    </span>`)}
                </div>
              </div>
            </div>

            <div class="sheet-panel ${sheetTab === "settings" ? "active" : ""}">
              ${v.controlsLocked ? html`
                <div class="busy-banner">
                  <ha-icon icon="mdi:lock"></ha-icon>
                  <span>Locked while cleaning — pause to change settings</span>
                </div>` : null}
              <div class="settings-lockable ${v.controlsLocked ? "busy" : ""}">
                <div class="tab-row">
                  <div class="segmented" style="width:auto"
                    role="group" aria-label="Cleaning settings mode">
                    <button class="seg-btn ${settingsMode === "standard" ? "active" : ""}"
                      aria-pressed=${settingsMode === "standard"} ?disabled=${v.controlsLocked}
                      @click=${() => this._setSettingsMode("standard")}>Standard</button>
                    <button class="seg-btn ${settingsMode === "customise" ? "active" : ""}"
                      aria-pressed=${settingsMode === "customise"} ?disabled=${v.controlsLocked}
                      @click=${() => this._setSettingsMode("customise")}>Customise</button>
                  </div>
                  <span class="tab-helper">${v.tabHelper || "Applies to all rooms"}</span>
                </div>
                <karcher-selector-rows class="standard-settings"
                  style=${settingsMode === "standard" ? "" : "display:none"}
                  .rows=${v.selectorRows || []}
                  @karcher-select=${(e) => this._onSelectorChange(e)}></karcher-selector-rows>
                <div class="area-note" style=${v.cardMode === "area" ? "" : "display:none"}>
                  <ha-icon icon="mdi:map-marker-radius"></ha-icon>
                  <span>Select the area to clean on the map.</span>
                </div>
                <karcher-room-list class="room-list visible ${v.zoneActive ? "zone-locked" : ""}"
                  style=${settingsMode === "customise" ? "" : "display:none"}
                  .rows=${v.roomRows || []} .busy=${v.controlsLocked || v.zoneActive} .simple=${false}
                  @room-toggle=${(e) => this._onRoomToggle(e)}
                  @room-expand=${(e) => this._onRoomExpand(e)}
                  @room-reorder=${(e) => this._onRoomReorder(e)}
                  @room-pref=${(e) => this._onRoomPref(e)}></karcher-room-list>
              </div>
            </div>
          </div>
        </div>
      </ha-card>`;
  }

  // Sheet tab 1 "What gets cleaned": room chips (Rooms) or a one-line area
  // summary (Zone). Chips toggle the same selection set the map writes to, via
  // the existing _onRoomToggle path (one source of truth).
  _renderCleanTarget(v, mapMode) {
    if (mapMode === "zone") {
      return html`
        <div class="zone-summary">
          <ha-icon icon="mdi:select-drag"></ha-icon>
          <span>${v.zoneRect ? "Area selected — ready to clean" : "No area yet — draw one on the map"}</span>
        </div>`;
    }
    const rooms = v.cleanTargetRooms || [];
    if (rooms.length === 0) {
      return html`<div class="zone-summary"><ha-icon icon="mdi:home-outline"></ha-icon>
        <span>No rooms found — load a map first</span></div>`;
    }
    const none = rooms.every((r) => !r.enabled);
    return html`
      ${none ? html`
        <div class="whole-home-banner">
          <ha-icon icon="mdi:home-outline"></ha-icon>
          <span>Whole home · all ${rooms.length} room${rooms.length !== 1 ? "s" : ""}</span>
        </div>` : null}
      <div class="room-chips">
        ${rooms.map((r) => html`
          <button class="room-chip ${r.enabled ? "on" : ""}" ?disabled=${v.controlsLocked}
            @click=${() => this._onRoomToggle({ detail: { roomId: r.id, on: !r.enabled } })}>
            <span class="room-chip-check">${r.enabled ? html`<ha-icon icon="mdi:check"></ha-icon>` : null}</span>
            <span>${r.name}</span>
            ${r.area != null ? html`<span class="room-chip-area">${r.area} m²</span>` : null}
          </button>`)}
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
    if (this._pendingPrefRefresh) {
      this._pendingPrefRefresh = false;
      this._refreshPreferences();
    }
    const vacState = this.hass.states[this._config.vacuum_entity];
    if (!vacState) return;

    const attr = vacState.attributes;
    const activity = vacState.state;

    if (this._pendingPreferMode) {
      // An optimistic switch is in flight: only the matching echo can resolve
      // it. Any other poll (including a stale pre-click value still in
      // transit) is ignored outright — applying it would knock the
      // optimistic tab back before the real echo ever arrives (e.g.
      // Customise -> Area: a "customise" poll racing the "standard" echo).
      if (attr?.prefer_mode === this._pendingPreferMode) {
        this._lastPreferMode = attr.prefer_mode;
        this._applyMode(this._pendingCardMode);
        this._pendingPreferMode = null;
        this._pendingCardMode = null;
      }
    } else if (
      attr?.prefer_mode && attr.prefer_mode !== this._lastPreferMode && !isOccupied(activity)
    ) {
      // Defer a reactive (non-optimistic) prefer_mode echo while a clean is in
      // progress: a room-only Standard clean can make the robot push a
      // custom_type change mid-run, which would otherwise flip _cardMode to
      // "customise" and silently swap the target-strip selection out from
      // under the active run. Controls are locked while occupied anyway, so
      // picking this up once the run ends to resting is no real loss.
      this._lastPreferMode = attr.prefer_mode;
      this._applyMode(attr.prefer_mode);
    }
    // Clear the room selection only when a run truly ends (occupied → resting),
    // never when merely pausing — pausing keeps the selection so a resume (and
    // the map/list highlight) carries through. isOccupied covers cleaning,
    // paused and returning, so cleaning⇄paused stays selected and the set only
    // clears on the drop to idle/docked/error.
    if (isOccupied(this._prevActivity) && !isOccupied(activity)) {
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
    const isOffline = this._isOffline();
    let statusText, dotClass, labelClass;
    if (isOffline) {
      statusText = "Offline"; dotClass = "dot-offline"; labelClass = "label-offline";
    } else {
      statusText = attr.status_label || STATE_LABELS[activity] || activity;
      const roomEntity = cfg.current_room_entity;
      if (activity === "cleaning" && roomEntity) {
        const r = this.hass.states[roomEntity]?.state;
        if (isUsableValue(r)) statusText += ` · ${r}`;
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
      legend: legendItems(attr),
      name: attr.friendly_name || "Kärcher RCV5",
      statusText, dotClass, labelClass,
      pinging: !isOffline && (activity === "cleaning" || activity === "returning"),
      hasError: !!hasError,
      activity,
      offline: !!isOffline,
      cardMode: this._cardMode,
      controlsLocked: this._controlsLocked(activity),
      tiles: this._statTiles(),
      selectorRows: this._selectorRows(attr),
      tabHelper: this._tabHelperText(attr),
      // Context-aware primary label for a resting robot; null while occupied so
      // the button row falls back to Pause/Resume.
      primaryLabel: isOccupied(activity)
        ? null
        : primaryCleanLabel(
            this._cardMode === "area" ? "zone" : "rooms",
            this._activeSelection().size,
            !!this._zoneRect,
          ),
      roomRows: this._roomListRows(attr),
      targetLabel: this._targetLabel(attr),
      cleanTargetRooms: this._cleanTargetRooms(attr),
      mapLoaded: this._mapLoaded,
      zoneMode: this._zoneMode,
      zoneRect: this._zoneRect,
      zoneActive: this._zoneMode || !!this._zoneRect,
    };
  }

  // Selection set the map/chips/strip all read: customise → the per-room custom
  // set, otherwise the transient standard set.
  _activeSelection() {
    return this._cardMode === "customise" ? this._customiseSelected : this._selectedRooms;
  }

  // One-line target-strip summary (rooms names / "Whole home" / area copy).
  _targetLabel(attr) {
    const roomMap = attr?.room_map || {};
    const mapMode = this._cardMode === "area" ? "zone" : "rooms";
    return targetStripLabel(
      mapMode, this._activeSelection(), !!this._zoneRect,
      (id) => roomMap[id]?.name || id,
    );
  }

  // Room-chip descriptors for the sheet's "What gets cleaned" tab: the derived
  // room rows (selection-aware) augmented with the room area for the chip.
  _cleanTargetRooms(attr) {
    const roomMap = attr?.room_map || {};
    return this._roomListRows(attr).map((r) => ({
      id: r.id,
      name: r.name,
      enabled: r.enabled,
      area: roomMap[r.id]?.area_m2 ?? null,
    }));
  }

  // Robot unreachable: entity unavailable, or the connectivity sensor is off.
  _isOffline() {
    const cfg = this._config;
    const activity = this.hass?.states[cfg?.vacuum_entity]?.state;
    const conn = cfg?.connectivity_entity;
    return activity === "unavailable" || !!(conn && this.hass.states[conn]?.state === "off");
  }

  // Config + selection (mode tabs, settings, room list, map selection, area
  // drawing) lock whenever a job is in progress — cleaning, paused OR returning
  // (editing then would re-target the in-flight clean; Resume re-dispatches the
  // selection) — or the robot is offline (the service call can't reach it).
  _controlsLocked(activity) {
    return isOccupied(activity) || this._isOffline();
  }

  // ── Standard / Customise mode ─────────────────────────────────────────────────

  // State-only mode switch. `mode` is "standard" | "customise" | "area" here.
  // Area rides on the robot's Standard preference (no prefer_mode value of
  // its own), so it shares Standard's branch below. Does NOT requestUpdate:
  // when called from willUpdate (prefer_mode change) the in-progress cycle
  // already re-derives _view; when called from _setCardMode (user tab) that
  // handler requests the update.
  _applyMode(mode) {
    this._cardMode = mode;
    // Remember the settings-axis value so leaving Zone (Area) via the map control
    // restores Standard/Customise rather than always snapping to Standard.
    if (mode === "standard" || mode === "customise") this._lastSettingsMode = mode;
    if (mode === "standard" || mode === "area") {
      this._detailRoomId = null;
      this._customiseSelected.clear();
    }
    if (mode === "area") {
      this._zoneMode = true;
      // Area draws its own selection; a room pick carried over from Standard
      // must not still show as selected on the map or feed the Start fallback.
      this._selectedRooms.clear();
    } else if (this._zoneMode || this._zoneRect) {
      // Only the Area tab draws — leaving it for Standard or Customise exits
      // draw mode and drops any selection so it can't leak into another tab.
      this._zoneMode = false;
      this._zoneRect = null;
      this._lastDrawKey = null;
    }
  }

  _setCardMode(mode) {
    if (!this.hass || !this._config) return;
    const activity = this.hass.states[this._config.vacuum_entity]?.state;
    if (this._controlsLocked(activity)) return;
    // Area has no robot-side preference of its own — it rides on Standard's
    // prefer_type 0. The robot will echo back prefer_mode="standard", but not
    // immediately: mark it pending so willUpdate ignores every poll (stale
    // pre-click values included) until that exact echo arrives — otherwise a
    // poll still carrying the old value (e.g. "customise") can land first and
    // knock the optimistic tab back before the real echo ever shows up.
    const backendMode = mode === "area" ? "standard" : mode;
    this.hass.callService("vacuum", "send_command", {
      entity_id: this._config.vacuum_entity,
      command: "set_preference_type",
      params: { prefer_type: backendMode === "customise" ? 1 : 0 },
    });
    this._pendingPreferMode = backendMode;
    this._pendingCardMode = mode;
    this._applyMode(mode);
    this.requestUpdate(); // user tab switch outside an update cycle → re-render
  }

  // Ask the integration to refetch room preferences now (bypasses the 5-min poll;
  // coordinator throttles to ~5 s). Passes device_id when known so multi-robot
  // setups route correctly. Used by the mount/foreground "fresh on look" trigger.
  _refreshPreferences() {
    const hass = this.hass;
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
    if (this._cardMode === "area") {
      return this._zoneRect ? "Cleans the selected area" : "Draw an area on the map";
    }
    if (this._cardMode !== "customise") {
      return "Applies to all rooms";
    }
    const roomMap = attr?.room_map || {};
    const roomIds = parseRoomOrder(roomMap, attr?.room_preferences || {});
    const total = Object.keys(roomMap).length;
    const enabled = roomIds.filter((id) => this._customiseSelected.has(id)).length;
    return `${enabled} of ${total} room${total !== 1 ? "s" : ""} on`;
  }

  _roomListRows(attr) {
    const roomMap = attr?.room_map || {};
    const prefs = attr?.room_preferences || {};
    if (this._cardMode === "customise") {
      return deriveRoomRows(roomMap, prefs, this._customiseSelected, this._detailRoomId);
    }
    // Standard mode: same enable/disable selection the map clicks toggle
    // (_selectedRooms) — no expand/detail, so detailRoomId is always null.
    return deriveRoomRows(roomMap, prefs, this._selectedRooms, null);
  }

  _onRoomToggle(e) {
    const { roomId, on } = e.detail || {};
    if (this._cardMode !== "customise") {
      if (on) this._selectedRooms.add(roomId);
      else this._selectedRooms.delete(roomId);
      this.requestUpdate(); // re-derive view (leaf rows + header) and redraw map overlay
      return;
    }
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
    const vacuumEntry = this.hass.entities?.[this._config.vacuum_entity];
    const serviceData = { room_order: order.map((rid) => parseInt(rid, 10)) };
    // device_id disambiguates when the account has more than one robot.
    if (vacuumEntry?.device_id) serviceData.device_id = vacuumEntry.device_id;
    this.hass.callService("karcher_home_robots", "set_room_preference", serviceData);
  }

  _onRoomPref(e) {
    const { roomId, field, value } = e.detail || {};
    this._setRoomPref(roomId, field, value);
  }

  // Read entity_ids from vacuum.room_preferences[roomId].entities (built by vacuum.py).
  _roomEntities(roomId) {
    const attr = this.hass?.states[this._config?.vacuum_entity]?.attributes;
    return attr?.room_preferences?.[roomId]?.entities || {};
  }

  _setRoomPref(roomId, field, value) {
    const entityId = this._roomEntities(roomId)[field];
    if (!entityId) { console.warn(`Kärcher card: no entity for ${field} room ${roomId}`); return; }
    this.hass.callService("select", "select_option", { entity_id: entityId, option: value });
  }

  _toggleRoomCustom(roomId, on) {
    const entityId = this._roomEntities(roomId)["custom"];
    if (!entityId) { console.warn(`Kärcher card: no custom switch for room ${roomId}`); return; }
    this.hass.callService("switch", on ? "turn_on" : "turn_off", { entity_id: entityId });
  }

  // ── map ───────────────────────────────────────────────────────────────────────

  // Placeholder text + aspect-ratio + loading flag as view fields. Pure read of
  // hass/config + the _map* side-effect flags (which _updateMap maintains).
  _mapPlaceholderView(attr) {
    const mapEntity = this._config.map_entity;
    if (!mapEntity) return { placeholderText: "Set map_entity in card config" };
    if (!this.hass.states[mapEntity]) return { placeholderText: `Entity not found: ${mapEntity}` };
    const sz = attr.map_image_size;
    const out = {
      mapLoading: this._mapPending,
      mapLoaded: this._mapLoaded,
      aspectRatio: sz ? `${sz.width} / ${sz.height}` : "",
      // Numeric w/h, for the height-cap max-width calc (keeps the map's aspect
      // while bounding its height so the card fits one screen).
      mapAspect: sz ? sz.width / sz.height : 0,
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
    const mapState = mapEntity ? this.hass.states[mapEntity] : null;
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
      if (this._mapLoaded && this.hass && this._config) {
        const attr = this.hass.states[this._config.vacuum_entity]?.attributes;
        if (attr) this._drawMap(attr);
      }
    };
    img.src = "/karcher_home_robots/static/icon.svg";
  }

  // Assemble the plain viewState the module renderer consumes: everything
  // hass-derived is pre-resolved here so the renderer never reads hass/config.
  _viewState(attr) {
    const isCleaning = this._cardMode !== "customise" && (() => {
      const a = this.hass?.states[this._config?.vacuum_entity]?.state;
      return a === "cleaning" || a === "paused";
    })();
    let currentRoomName = null;
    if (isCleaning && this._config.current_room_entity) {
      currentRoomName = this.hass.states[this._config.current_room_entity]?.state ?? null;
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
      zoneRect: this._zoneRect,
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

  _zonePx(e) {
    const imgSize = this.hass?.states[this._config?.vacuum_entity]?.attributes?.map_image_size;
    if (!imgSize || !this._canvas) return null;
    const rect = this._canvas.getBoundingClientRect();
    const { px, py } = clientToImagePx(e.clientX, e.clientY, rect, imgSize);
    return {
      x: Math.max(0, Math.min(imgSize.width, px)),
      y: Math.max(0, Math.min(imgSize.height, py)),
    };
  }

  _zoneMinPx() {
    const cellSize = this.hass?.states[this._config?.vacuum_entity]?.attributes?.map_image_size?.cell_size;
    return minZonePx(cellSize);
  }

  _onZonePointerDown(e) {
    if (!this._zoneMode) return;
    const activity = this.hass?.states[this._config?.vacuum_entity]?.state;
    if (this._controlsLocked(activity)) return;
    const p = this._zonePx(e);
    if (!p) return;
    e.preventDefault();
    this._canvas.setPointerCapture?.(e.pointerId);
    this._zoneDragging = true;
    // Anchor plus the minimum size, not a zero-size point — the rect is
    // always at least the minimum, even before the user drags at all.
    this._zoneRect = clampZoneRect({ x0: p.x, y0: p.y, x1: p.x, y1: p.y }, this._zoneMinPx());
    this._lastDrawKey = null;
    this.requestUpdate();
  }

  _onZonePointerMove(e) {
    if (!this._zoneMode || !this._zoneDragging || !this._zoneRect) return;
    const p = this._zonePx(e);
    if (!p) return;
    const { x0, y0 } = this._zoneRect;
    this._zoneRect = clampZoneRect({ x0, y0, x1: p.x, y1: p.y }, this._zoneMinPx());
    this._lastDrawKey = null;
    this.requestUpdate();
  }

  _onZonePointerUp(e) {
    if (!this._zoneMode || !this._zoneDragging) return;
    this._zoneDragging = false;
    this._canvas.releasePointerCapture?.(e.pointerId);
    this._lastDrawKey = null;
    this.requestUpdate();
  }

  _startZoneClean() {
    const r = this._zoneRect;
    if (!r) return;
    this.hass.callService("vacuum", "send_command", {
      entity_id: this._config.vacuum_entity,
      command: "app_zone_clean",
      params: { rect_px: [r.x0, r.y0, r.x1, r.y1] },
    });
    // Drawing stays enabled while the Area tab is active — only the rect clears.
    this._zoneRect = null;
    this._lastDrawKey = null;
    this.requestUpdate();
  }

  _onCanvasClick(e) {
    if (this._zoneMode) return;
    if (!this.hass || !this._config) return;
    const vacState = this.hass.states[this._config.vacuum_entity];
    const activity = vacState?.state;
    if (this._controlsLocked(activity)) return;
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

  // ── map-mode control · bottom sheet ─────────────────────────────────────────

  // Floating Rooms|Zone control. Maps onto the unchanged tri-state cardMode:
  // Zone ⟺ Area, Rooms ⟺ the last Standard/Customise settings value.
  _onMapMode(e) {
    const mode = e.detail?.mode;
    if (mode === "zone") {
      if (this._cardMode !== "area") this._setCardMode("area");
    } else if (this._cardMode === "area") {
      this._setCardMode(this._lastSettingsMode || "standard");
    }
  }

  // Sheet Standard|Customise switch — drives the existing prefer_type wiring.
  _setSettingsMode(mode) {
    this._setCardMode(mode);
  }

  _openSheet() {
    if (this._sheetOpen) return;
    this._sheetOpen = true;
    this.requestUpdate();
  }

  _closeSheet() {
    if (!this._sheetOpen) return;
    this._sheetOpen = false;
    this.requestUpdate();
  }

  _setSheetTab(tab) {
    if (this._sheetTab === tab) return;
    this._sheetTab = tab;
    this.requestUpdate();
  }

  // Battery header glyph as view fields (was imperative writes in _updateStats).
  _batteryView() {
    const battEntity = this._config.battery_entity;
    if (battEntity) {
      const b = this.hass.states[battEntity];
      if (isUsableState(b)) {
        const pct = parseInt(b.state, 10);
        const chargingEntity = this._config.charging_entity;
        const isCharging = chargingEntity
          ? this.hass.states[chargingEntity]?.state === "on" : false;
        return {
          battVisible: true,
          battPct: `${pct}%`,
          battIcon: batteryIcon(pct, isCharging),
          battIconClass: pct <= 20 ? "icon-low" : "",
        };
      }
    }
    return { battVisible: false };
  }

  _statTiles() {
    const areaState = this.hass.states[this._config.cleaning_area_entity];
    const timeState = this.hass.states[this._config.cleaning_time_entity];
    const occupied = isOccupied(this.hass.states[this._config.vacuum_entity]?.state);
    return deriveStatTiles(areaState, timeState, occupied);
  }

  _selectorRows(attr) {
    if (this._cardMode === "customise") return [];
    const modeEntityId = this._config.cleaning_mode_entity;
    const modeState = modeEntityId ? this.hass.states[modeEntityId] : null;
    const waterEntityId = this._config.water_level_entity;
    // undefined (not null) when no entity configured → deriveSelectorRows omits
    // the water row; a configured-but-missing entity yields a disabled row.
    const waterState = waterEntityId ? (this.hass.states[waterEntityId] ?? null) : undefined;
    const rows = deriveSelectorRows(attr, modeState, waterState);
    // Offline: the service call can't reach the robot — disable every row.
    if (this._isOffline()) for (const r of rows) r.disabled = true;
    return rows;
  }

  _onSelectorChange(e) {
    const { control, value } = e.detail || {};
    if (control === "mode") {
      this.hass.callService("select", "select_option",
        { entity_id: this._config.cleaning_mode_entity, option: value });
    } else if (control === "suction") {
      this.hass.callService("vacuum", "set_fan_speed",
        { entity_id: this._config.vacuum_entity, fan_speed: value });
    } else if (control === "water") {
      this.hass.callService("select", "select_option",
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
    // Resuming a pause must never re-dispatch the current selection as a fresh
    // clean (set_room_clean with non-empty room_ids restarts those rooms rather
    // than continuing — doc/PROTOCOL.md §5 documents only room_ids:[] as the
    // resume signal). Controls are locked while paused, so the selection can't
    // have changed since the clean started — vacuum.start's own paused-state
    // handling (async_start) is always the right call here.
    if (this.hass.states[vacuumEntity]?.state === "paused") {
      this.hass.callService("vacuum", "start", { entity_id: vacuumEntity });
      return;
    }
    // A drawn area takes precedence over room selection and whole-home. The
    // redirect lives here in the card; vacuum.start stays whole-home for
    // external callers (Apple Home/HAMH dispatch a parameterless vacuum.start).
    if (this._zoneRect) {
      this._startZoneClean();
      return;
    }
    const roomIds = [...this._selectedRooms].map((id) => parseInt(id, 10));
    if (roomIds.length === 0) {
      // No selection → whole-home clean via the standard service.
      this.hass.callService("vacuum", "start", { entity_id: vacuumEntity });
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
    const prefs = this.hass.states[vacuumEntity]?.attributes?.room_preferences || {};
    const selectedRoomMap = Object.fromEntries(roomIds.map((id) => [String(id), {}]));
    const ordered = parseRoomOrder(selectedRoomMap, prefs).map((id) => parseInt(id, 10));
    this.hass.callService("vacuum", "send_command", {
      entity_id: vacuumEntity,
      command: "app_segment_clean",
      params: ordered,
    });
  }

  _pause() {
    this.hass.callService("vacuum", "pause", { entity_id: this._config.vacuum_entity });
  }

  _stop() {
    this.hass.callService("vacuum", "stop", { entity_id: this._config.vacuum_entity });
  }

  _dock() {
    this.hass.callService("vacuum", "return_to_base", { entity_id: this._config.vacuum_entity });
  }

}

if (!customElements.get("karcher-vacuum-card")) {
  customElements.define("karcher-vacuum-card", KarcherVacuumCard);
}


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
  ha-textfield { width: 100%; }
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

// Stable per-domain arrays for ha-entity-picker's `includeDomains` so a re-render
// passes the same reference (a fresh `[domain]` each time would force the picker
// to re-filter its list every hass tick).
const _DOMAIN_ARRAYS = {};
function _domainArr(domain) {
  if (!domain) return undefined;
  if (!_DOMAIN_ARRAYS[domain]) _DOMAIN_ARRAYS[domain] = [domain];
  return _DOMAIN_ARRAYS[domain];
}

class KarcherVacuumCardEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  // CSS as a <style> tag, not `static styles` — same constraint as the card
  // shell (a plain-string `static styles` throws a TypeError via adoptStyles).

  constructor() {
    super();
    this.hass = null;
    this._config = {};
  }

  // HA calls setConfig imperatively; _config is reactive so this re-renders.
  setConfig(config) {
    this._config = { ...config };
  }

  _onPickerChange(configKey, e) {
    this._config = nextEditorConfig(this._config, configKey, e.detail.value);
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }

  // Fixed card height (px). Blank → omit it so the card fills the height in
  // Panel view and falls back to its CSS floor in masonry.
  _onHeightChange(e) {
    const raw = e.target.value;
    const n = parseInt(raw, 10);
    const next = { ...this._config };
    if (raw === "" || isNaN(n) || n <= 0) delete next.card_height;
    else next.card_height = n;
    this._config = next;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }

  _picker(configKey, domain, label, required = false) {
    const derived = _deriveCompanions(this._config.vacuum_entity);
    const value = this._config[configKey] || derived[configKey] || "";
    return html`
      <div class="field">
        <label class=${required ? "required" : ""}>${label}</label>
        <ha-entity-picker
          allow-custom-entity
          .hass=${this.hass}
          .value=${value}
          .includeDomains=${_domainArr(domain)}
          @value-changed=${(e) => this._onPickerChange(configKey, e)}
        ></ha-entity-picker>
      </div>`;
  }

  render() {
    return html`
      <style>${_EDITOR_CSS}</style>
      ${this._picker("vacuum_entity", "vacuum", "Vacuum entity", true)}
      <div class="field">
        <label>Card height (px)</label>
        <ha-textfield type="number" min="320" inputmode="numeric"
          placeholder="Auto (fills Panel view)"
          .value=${this._config.card_height != null ? String(this._config.card_height) : ""}
          @change=${(e) => this._onHeightChange(e)}
        ></ha-textfield>
      </div>
      <details>
        <summary>Advanced — entity overrides</summary>
        <div class="advanced">
          ${_EDITOR_COMPANIONS.map(({ key, label, domain }) =>
            this._picker(key, domain, label))}
        </div>
      </details>`;
  }
}

if (!customElements.get("karcher-vacuum-card-editor")) {
  customElements.define("karcher-vacuum-card-editor", KarcherVacuumCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "karcher-vacuum-card")) {
  window.customCards.push({
    type: "karcher-vacuum-card",
    name: "Kärcher Vacuum Card",
    description: "Map, room selection, controls for the Kärcher RCV5",
    preview: false,
    version: VERSION,
  });
}
