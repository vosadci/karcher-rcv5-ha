// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no CI build toolchain. Lit is vendored as a committed
// self-contained ESM bundle (./lit-core.js) — no runtime CDN/import-map needed.
//
// Architecture: one Lit shell (<karcher-vacuum-card>) renders the whole card
// declaratively; presentational leaves (button row, stats, selectors, room
// list, map mode) render into LIGHT DOM (createRenderRoot returns `this`) so
// they inherit the shell's _CSS sheet — they carry no `css` of their own.
// Data flows DOWN via properties; actions flow UP via dispatchEvent. The map
// is a <canvas> painted imperatively by the pure drawMap renderer below (the
// one deliberate non-Lit island, plus the transient drag-and-drop indicators).

import { LitElement, html } from "./lit-core.js";

const VERSION = "1.30.0";
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
const NO_ROOMS_MESSAGE = "No rooms found — load a map first";

// Canvas paint colours — mirror the CSS --rcv-accent/--rcv-accent-deep tokens
// (canvas fillStyle/strokeStyle can't read CSS custom properties, so these are
// the same hex values restated as JS constants, single source for the paint code).
const ACCENT_DEEP_HEX = "#E8BE00";
const ZONE_FILL = "rgba(255,212,0,0.28)";
const ROOM_ACTIVE_FILL = "rgba(255,212,0,0.40)";
const ROOM_SELECTED_FILL = "rgba(255,212,0,0.55)";
const PATH_COLOR = "#999";
// Robot is ~34cm wide; resolution=0.05m/cell → ~7 cells diameter → 3.5 cell radius.
const ROBOT_RADIUS_CELLS = 3.5;

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
  /* Full-bleed canvas frame: always the full card width, height from the
     map's aspect-ratio (bound inline from map_image_size) capped at
     --rcv-map-max-height so the whole card still fits ~one screen. The map
     itself is aspect-fit + centered INSIDE the canvas (fitContentBox), so a
     portrait map's letterbox margins are canvas the zoomed map can grow into. */
  .map-container {
    position: relative;
    width: 100%;
    overflow: hidden;
  }
  .map-container canvas {
    display: block;
    width: 100%;
    height: 100%;
    cursor: pointer;
    /* At fit zoom, vertical page scroll over the map still works; once
       zoomed in (.map-zoomed) every touch gesture belongs to the card
       (one-finger pan, two-finger pinch). */
    touch-action: pan-y;
  }
  .map-container canvas.map-zoomed {
    touch-action: none;
  }
  .map-container canvas.zone-draw {
    cursor: crosshair;
    touch-action: none;
  }
  .map-container canvas.locked { cursor: default; }

  /* ── directional edge scrims: a soft "the map continues this way" shadow on
     each side where the zoomed map overflows the frame. Opacity is bound per
     edge to the off-screen overhang (panEdgeHidden), so a side with nothing
     hidden fades to fully transparent — reaching a true edge visibly clears its
     scrim. pointer-events:none so they never intercept a pan/tap. */
  .map-edge {
    position: absolute;
    z-index: 4;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.18s ease;
  }
  .map-edge-l { top: 0; bottom: 0; left: 0; width: 15%;
    background: linear-gradient(to right, rgba(0,0,0,0.30), transparent); }
  .map-edge-r { top: 0; bottom: 0; right: 0; width: 15%;
    background: linear-gradient(to left, rgba(0,0,0,0.30), transparent); }
  .map-edge-t { left: 0; right: 0; top: 0; height: 15%;
    background: linear-gradient(to bottom, rgba(0,0,0,0.30), transparent); }
  .map-edge-b { left: 0; right: 0; bottom: 0; height: 15%;
    background: linear-gradient(to top, rgba(0,0,0,0.30), transparent); }
  @media (prefers-reduced-motion: reduce) {
    .map-edge { transition: none; }
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

  /* ── floating reset-zoom control (top-right, only while zoomed in) ── */
  .map-reset {
    position: absolute;
    top: 12px;
    right: 12px;
    z-index: 6;
    display: flex;
    align-items: center;
    gap: 7px;
    height: 44px;
    padding: 0 13px;
    border-radius: 13px;
    cursor: pointer;
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    /* Same frosted glass as .map-mode-inner so the two floating map controls
       read as one family. */
    background: color-mix(in srgb, var(--rcv-card) 78%, transparent);
    -webkit-backdrop-filter: blur(10px);
    backdrop-filter: blur(10px);
    border: 1px solid color-mix(in srgb, var(--rcv-text) 14%, transparent);
    box-shadow: 0 6px 20px rgba(0,0,0,0.22);
    color: color-mix(in srgb, var(--rcv-text) 82%, transparent);
    --mdc-icon-size: 20px;
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
  .map-hint.hint-locked { opacity: 0.5; }
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
    display: flex;
    flex-direction: column;
  }
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
  .target-strip:disabled { opacity: 0.5; cursor: default; }
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
    box-sizing: border-box;
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
  { key: "fault_code_entity",    domain: "sensor",        suffix: "robot_status",  label: "Fault code sensor" },
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

// Single source for the "low battery" cutoff — shared by the icon-level and
// header icon-colour decisions, which must agree on where "low" starts.
export const BATTERY_LOW_THRESHOLD = 20;

// MDI outline battery family only has three filled levels (low/medium/high)
// plus the empty outline glyph at <=20% — no separate 100% icon, so high
// covers everything above 80% including full. Charging variants mirror the levels.
export function batteryIcon(pct, charging) {
  const clamped = Math.max(0, Math.min(100, pct));
  const prefix = charging ? "mdi:battery-charging" : "mdi:battery";
  let level;
  if (clamped <= BATTERY_LOW_THRESHOLD) level = "outline";
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

// Uniform-fit content box for the map inside a full-bleed canvas: largest
// aspect-preserving {w,h} that fits cssW×cssH, centered ({ox,oy} letterbox
// margins in CSS px). The canvas no longer matches the map's aspect ratio —
// it fills the card width — so the letterboxing that used to live in the CSS
// aspect-ratio/max-width lives here instead, which is what lets a zoomed map
// grow into the side margins.
export function fitContentBox(cssW, cssH, imgSize) {
  if (!imgSize || !imgSize.width || !imgSize.height) {
    return { w: cssW, h: cssH, ox: 0, oy: 0 };
  }
  const s = Math.min(cssW / imgSize.width, cssH / imgSize.height);
  const w = imgSize.width * s;
  const h = imgSize.height * s;
  return { w, h, ox: (cssW - w) / 2, oy: (cssH - h) / 2 };
}

// Click coords (client space) → image-space pixel + cell-snapped row/col.
// pan is in CSS px, applied in the same canvas matrix as drawMap: the client
// point is first un-panned, un-zoomed (both in CSS-px space), then shifted by
// the letterbox offset and converted from content-box CSS px to image px.
// When the canvas box matches the map's aspect the box offsets are 0 and this
// is unchanged from the pre-zoom behaviour. Points in the letterbox margins
// yield out-of-range image px (negative or > width) — callers already treat
// those as no-hit.
export function clientToImagePx(clientX, clientY, rect, imgSize, zoom = 1, pan = { x: 0, y: 0 }) {
  const cs = imgSize.cell_size || 1;
  const box = fitContentBox(rect.width, rect.height, imgSize);
  const cssX = (clientX - rect.left - pan.x) / zoom - box.ox;
  const cssY = (clientY - rect.top - pan.y) / zoom - box.oy;
  const px = Math.floor(cssX * (imgSize.width / box.w));
  const py = Math.floor(cssY * (imgSize.height / box.h));
  return {
    px,
    py,
    snapCol: Math.floor(px / cs) * cs,
    snapRow: Math.floor(py / cs) * cs,
  };
}

// Zoom clamp range. 1 = fit-to-frame (the pre-zoom default); 4 is enough to
// read small rooms without the base render (scale=4 PNG) going soft.
export const MIN_ZOOM = 1;
export const MAX_ZOOM = 4;

export function clampZoom(zoom) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

// Zoom toward a focal point (e.g. cursor or pinch midpoint), keeping the image
// point under that focal point fixed. focalX/Y and pan are in CSS px, relative
// to the canvas's top-left (i.e. already offset by rect.left/top).
export function zoomAtPoint(prevZoom, prevPan, nextZoom, focal) {
  const z = clampZoom(nextZoom);
  // Solve for the new pan that keeps (focal - pan) / zoom constant.
  const imgX = (focal.x - prevPan.x) / prevZoom;
  const imgY = (focal.y - prevPan.y) / prevZoom;
  return {
    zoom: z,
    pan: { x: focal.x - imgX * z, y: focal.y - imgY * z },
  };
}

// Clamp one pan axis. While the scaled content is narrower than the canvas
// on this axis it stays centered (pan pinned — the map grows outward into
// the letterbox margin as zoom rises); once it outgrows the canvas, pan is
// free within [content covers canvas] bounds.
function clampPanAxis(p, zoom, css, offset, size) {
  const scaled = zoom * size;
  // `+ 0` normalizes a -0 result (offset 0 edge) to +0 for clean equality.
  if (scaled <= css) return (css - scaled) / 2 - zoom * offset + 0;
  return Math.min(-zoom * offset, Math.max(css - zoom * (offset + size), p)) + 0;
}

// Clamp pan so the zoomed map can't be dragged past its own edges. At zoom=1
// the only valid pan is {0,0} (nothing to pan to). With imgSize the clamp is
// content-box aware (full-bleed canvas, letterbox inside); without it the
// content is assumed to fill the canvas exactly (pre-full-bleed behaviour,
// kept for callers/tests without an image).
export function clampPan(pan, zoom, cssW, cssH, imgSize = null) {
  if (zoom <= 1) return { x: 0, y: 0 };
  const box = fitContentBox(cssW, cssH, imgSize);
  return {
    x: clampPanAxis(pan.x, zoom, cssW, box.ox, box.w),
    y: clampPanAxis(pan.y, zoom, cssH, box.oy, box.h),
  };
}

// How much scaled content (CSS px) is hidden past the near/far edge of one axis.
// Same clamp geometry as clampPanAxis: the valid pan range is [minP, maxP]; at
// maxP the content's near edge is flush (nothing hidden before), at minP the far
// edge is flush (nothing hidden after). The distance from the current pan to each
// bound is exactly the off-screen overhang on that side.
function panAxisHidden(p, zoom, css, offset, size) {
  if (zoom * size <= css) return { before: 0, after: 0 };
  const maxP = -zoom * offset;
  const minP = css - zoom * (offset + size);
  return { before: Math.max(0, maxP - p), after: Math.max(0, p - minP) };
}

// Off-screen overhang (CSS px) past each edge of the zoomed map, so the card can
// fade in a directional "there's more this way" scrim only where content is
// actually hidden. Zero on every edge at fit zoom (nothing to pan to). Pure —
// unit-tested directly; the content-box math mirrors clampPan.
export function panEdgeHidden(pan, zoom, cssW, cssH, imgSize = null) {
  if (zoom <= 1) return { left: 0, right: 0, top: 0, bottom: 0 };
  const box = fitContentBox(cssW, cssH, imgSize);
  const x = panAxisHidden(pan.x, zoom, cssW, box.ox, box.w);
  const y = panAxisHidden(pan.y, zoom, cssH, box.oy, box.h);
  return { left: x.before, right: x.after, top: y.before, bottom: y.after };
}

// Off-screen overhang ramps a fade from 0 to full over this many CSS px, so an
// edge with only a sliver hidden shows a faint hint and a deep overhang is solid.
const EDGE_FADE_RAMP_PX = 40;

// One step of a two-finger touch pinch/pan gesture. `start` is a snapshot
// taken once when the gesture began (second finger down): { zoom, pan, mid,
// dist }. Every move frame recomputes from that FIXED start, not from the
// previous frame — an incremental frame-to-frame version telescopes: a pure
// pan slightly changes the inter-finger distance each frame (one finger
// necessarily moves before the other), so per-frame zoom ratios drift below
// 1 and back, and clampZoom's floor at MIN_ZOOM truncates the dip asymmetrically,
// ratcheting zoom down and wiping the accumulated pan via clampPan every time
// it touches the floor. Referencing the gesture start instead makes a pure
// pan produce curDist≈start.dist → zoom pinned, pan = pure translation — no
// drift to accumulate. start.dist<=0 or newDist<=0 (degenerate geometry)
// leaves zoom at start.zoom.
// Rate exponent > 1 steepens zoom response to finger-spread ratio. Must satisfy
// pow(1, RATE) === 1 (i.e. any exponent works here) so a pure pan — spread
// ratio staying ~1 — never introduces zoom drift; a flat multiplier (scale*k)
// would NOT have this property and would re-zoom on every pan gesture.
const PINCH_ZOOM_RATE = 1.3;

// One-finger (or trackpad two-finger-scroll) pan: translate the gesture-start
// pan by the pointer's total displacement, clamped to the map edges. Pure
// translation — zoom is untouched. At zoom<=1 clampPan pins the result to
// {0,0} (nothing to pan to).
export function dragPan(startPan, dx, dy, zoom, cssW, cssH, imgSize = null) {
  return clampPan({ x: startPan.x + dx, y: startPan.y + dy }, zoom, cssW, cssH, imgSize);
}

// A press that moves less than this (CSS px) is still a tap: it must fall
// through to the click handler (room select) instead of becoming a pan.
export const TAP_SLOP_PX = 5;

export function pinchStep(start, newMid, newDist, cssW, cssH, imgSize = null) {
  const scale = start.dist > 0 && newDist > 0 ? newDist / start.dist : 1;
  const zoom = clampZoom(start.zoom * Math.pow(scale, PINCH_ZOOM_RATE));
  // Keep the image point under the gesture's start midpoint fixed at zoom0,
  // then re-center on the current midpoint — same derivation as zoomAtPoint,
  // applied relative to the gesture start rather than the previous frame.
  const imgX = (start.mid.x - start.pan.x) / start.zoom;
  const imgY = (start.mid.y - start.pan.y) / start.zoom;
  const pan = {
    x: newMid.x - imgX * zoom,
    y: newMid.y - imgY * zoom,
  };
  return { zoom, pan: clampPan(pan, zoom, cssW, cssH, imgSize) };
}

// Smallest area-clean rectangle worth sending: one robot-width square.
// Robot is ~34cm wide; resolution=0.05m/cell → ~7 cells per side (see drawRobot).
// Matches the Kärcher app's own AreaMap.AREA_MIN_SIZE clamp-while-dragging
// approach (no zero-size rect ever exists, rather than validating on release).
// Side length scaled by √2 so the minimum *area* is 2x the one-robot-width square.
const MIN_ZONE_CELLS = 10;

export function minZonePx(cellSize) {
  return MIN_ZONE_CELLS * (cellSize || 1);
}

// Default starting rect is 5x the minimum drag side — big enough to read as
// a real selection rather than the smallest-possible square.
const DEFAULT_ZONE_SCALE = 5;

// Centered starting rect for a freshly entered Area tab, so the user edits
// a real selection instead of an empty map. Falls back to null when the map
// size isn't known yet.
export function defaultZoneRect(imgSize) {
  if (!imgSize) return null;
  const side = minZonePx(imgSize.cell_size) * DEFAULT_ZONE_SCALE;
  const x0 = Math.max(0, (imgSize.width - side) / 2);
  const y0 = Math.max(0, (imgSize.height - side) / 2);
  return { x0, y0, x1: Math.min(imgSize.width, x0 + side), y1: Math.min(imgSize.height, y0 + side) };
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

// Handle hit-radius, in image px — converted from a fixed screen-px radius
// via the same scale the canvas uses, so handles stay grabbable at any zoom.
export const ZONE_HANDLE_RADIUS_PX = 14;

// Normalize a possibly-inverted drag rect to (x0,y0) top-left / (x1,y1) bottom-right.
function normalizeRect(rect) {
  return {
    x0: Math.min(rect.x0, rect.x1),
    x1: Math.max(rect.x0, rect.x1),
    y0: Math.min(rect.y0, rect.y1),
    y1: Math.max(rect.y0, rect.y1),
  };
}

// Where on an existing zone rect did the pointer land? Corner handles take
// priority over the body so a drag started near an edge always resizes
// rather than moves. Returns 'nw'|'ne'|'sw'|'se'|'body'|null.
export function hitTestZoneRect(px, py, rect, handleRadius) {
  if (!rect) return null;
  const { x0, x1, y0, y1 } = normalizeRect(rect);
  const near = (ax, ay) => Math.hypot(px - ax, py - ay) <= handleRadius;
  if (near(x0, y0)) return "nw";
  if (near(x1, y0)) return "ne";
  if (near(x0, y1)) return "sw";
  if (near(x1, y1)) return "se";
  if (px >= x0 && px <= x1 && py >= y0 && py <= y1) return "body";
  return null;
}

// Resize by dragging one corner; the opposite corner stays fixed (anchor).
// Re-clamps to the minimum size and to the image bounds afterward.
export function resizeZoneRect(rect, corner, px, py, minPx, bounds) {
  const { x0, x1, y0, y1 } = normalizeRect(rect);
  const fx = corner.includes("e") ? x0 : x1;
  const fy = corner.includes("s") ? y0 : y1;
  const nx = Math.max(0, Math.min(bounds.width, px));
  const ny = Math.max(0, Math.min(bounds.height, py));
  return normalizeRect(clampZoneRect({ x0: fx, y0: fy, x1: nx, y1: ny }, minPx));
}

// Translate the whole rect by (dx,dy), clamped so it stays fully on the map.
export function moveZoneRect(rect, dx, dy, bounds) {
  const { x0, x1, y0, y1 } = normalizeRect(rect);
  const w = x1 - x0;
  const h = y1 - y0;
  const nx0 = Math.max(0, Math.min(bounds.width - w, x0 + dx));
  const ny0 = Math.max(0, Math.min(bounds.height - h, y0 + dy));
  return { x0: nx0, y0: ny0, x1: nx0 + w, y1: ny0 + h };
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
      compactEligible: true,
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
      compactEligible: true,
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
  const seg = (label, field, value, options, disabled = false, compactEligible = false) =>
    ({ label, field, value, disabled, compactEligible, options });
  return [
    seg("Repeat", "repeat", REPEAT_BY_INT[pref.repeat], [
      { value: "single", label: "×1" }, { value: "double", label: "×2" },
    ]),
    seg("Mode", "mode", MODE_BY_INT[pref.mode], MODE_OPTIONS.map((o) => ({ ...o }))),
    seg("Suction", "power", POWER_BY_INT[pref.power], SUCTION_OPTIONS.map((o) => ({ ...o })),
      false, true),
    // Water is gated off in vacuum mode (matches the standard-mode selector).
    seg("Water", "water", WATER_BY_INT[pref.water], WATER_OPTIONS.map((o) => ({ ...o })),
      MODE_BY_INT[pref.mode] === "vacuum", true),
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
  const inProgress = isBusy(activity);
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
    viewState.zoom || 1,
    viewState.pan ? `${Math.round(viewState.pan.x)},${Math.round(viewState.pan.y)}` : "",
  ].join("|");
}

// Interpolate between two angles (radians) along the shortest arc, so a robot
// turning across the ±π wrap glides instead of spinning the long way round.
export function lerpAngle(a, b, t) {
  let d = (b - a) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return a + d * t;
}

// Total length of a flat [x0,y0,x1,y1,...] polyline (image px).
export function pathArcLength(pts) {
  let acc = 0;
  for (let i = 0; i < pts.length / 2 - 1; i++) {
    acc += Math.hypot(pts[2 * i + 2] - pts[2 * i], pts[2 * i + 3] - pts[2 * i + 1]);
  }
  return acc;
}

// Reveal a flat [x0,y0,x1,y1,...] polyline up to arc length `dist`. Returns the
// truncated path (ending at an interpolated cursor) and the cursor x/y. Arc
// length (not index) gives even spatial speed when the cursor is paced linearly.
export function revealPath(pts, dist) {
  const n = pts.length / 2;
  if (n === 0) return { path: [], x: 0, y: 0 };
  if (n === 1 || dist <= 0) return { path: [pts[0], pts[1]], x: pts[0], y: pts[1] };
  let acc = 0;
  for (let i = 0; i < n - 1; i++) {
    const x1 = pts[2 * i], y1 = pts[2 * i + 1];
    const x2 = pts[2 * i + 2], y2 = pts[2 * i + 3];
    const seg = Math.hypot(x2 - x1, y2 - y1);
    if (acc + seg >= dist) {
      const f = seg > 0 ? (dist - acc) / seg : 0;
      const cx = x1 + (x2 - x1) * f;
      const cy = y1 + (y2 - y1) * f;
      const path = pts.slice(0, 2 * i + 2);
      path.push(cx, cy);
      return { path, x: cx, y: cy };
    }
    acc += seg;
  }
  const last = pts.length - 2;
  return { path: pts.slice(), x: pts[last], y: pts[last + 1] };
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
    items.push({ key: "path", label: "Path", kind: "line", color: PATH_COLOR });
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
//        customiseSelected, activeRoomId, mapToken, canvasWidth, canvasHeight,
//        zoom, pan }
// ---------------------------------------------------------------------------

export function drawMap(ctx, canvas, vs) {
  const { attr, mapImg } = vs;
  if (!mapImg || !canvas) return [];
  const dpr = vs.dpr || 1;
  const zoom = vs.zoom || 1;
  const pan = vs.pan || { x: 0, y: 0 };
  // Clear in full device space (no zoom/pan) so a zoomed-in view doesn't
  // leave stale pixels outside the transformed draw area.
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const cssW = canvas.width / dpr;
  const cssH = canvas.height / dpr;
  ctx.clearRect(0, 0, cssW, cssH);
  // The canvas is full-bleed (card width), so the map's aspect-fit letterbox
  // lives in the transform: pan/zoom first, then the centering offset. Every
  // draw* child scales via canvasScale() against the CONTENT box, not the
  // canvas — pass content-box dims so no child needs to know any of this.
  const box = fitContentBox(cssW, cssH, attr.map_image_size);
  ctx.translate(pan.x, pan.y);
  ctx.scale(zoom, zoom);
  ctx.translate(box.ox, box.oy);
  const contentDims = { width: box.w * dpr, height: box.h * dpr };
  ctx.drawImage(mapImg, 0, 0, box.w, box.h);
  const roomMap = attr.room_map || {};
  drawRoomOverlays(ctx, contentDims, roomMap, vs);
  drawCurPath(ctx, contentDims, vs);
  const hitAreas = drawRoomLabels(ctx, contentDims, roomMap, vs);
  drawCharger(ctx, contentDims, vs);
  drawRobot(ctx, contentDims, vs);
  drawZoneRect(ctx, contentDims, vs);
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
  const radius = Math.min(10, w / 2, h / 2);
  ctx.save();
  // Kärcher-yellow fill + accent stroke, matching the rest of the card's
  // accent usage (--rcv-accent / --rcv-accent-deep).
  ctx.fillStyle = ZONE_FILL;
  ctx.strokeStyle = "rgba(255,255,255,0.95)";
  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, radius);
  ctx.fill();
  ctx.stroke();
  ctx.strokeStyle = ACCENT_DEEP_HEX;
  ctx.lineWidth = 2.5;
  ctx.stroke();
  ctx.restore();

  drawZoneHandles(ctx, x, y, w, h);
}

// Corner resize handles — small accent-ringed circles, matching the
// prototype's drag handles, drawn in canvas (device) space.
function drawZoneHandles(ctx, x, y, w, h) {
  const corners = [[x, y], [x + w, y], [x, y + h], [x + w, y + h]];
  ctx.save();
  for (const [hx, hy] of corners) {
    ctx.beginPath();
    ctx.arc(hx, hy, 9, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,255,255,0.55)";
    ctx.fill();
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = ACCENT_DEEP_HEX;
    ctx.stroke();
  }
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
  ctx.strokeStyle = PATH_COLOR;
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
  const r = Math.max(6, imgSize.cell_size * scaleX * ROBOT_RADIUS_CELLS);

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
  const r = imgSize.cell_size * scaleX * ROBOT_RADIUS_CELLS;
  const phi = rp.phi ?? 0;

  ctx.save();
  ctx.translate(cx, cy);

  // Pulse cue: a filled "radar ping" disc expands and fades from the robot,
  // mirroring the header status dot (CSS @keyframes rcv-ping): scale 1→2.5,
  // opacity 0.75→0, ease-out, 1.6s, themed colour. Circular → rotation-
  // independent, so drawn before the heading rotate below. baseR is floored in
  // device px so the cue stays visible when the icon is tiny (zoomed out).
  if (vs.pulse) {
    const p = vs.pulsePhase || 0;
    const e = 1 - Math.pow(1 - p, 3); // ease-out, ~cubic-bezier(0,0,.2,1)
    const baseR = Math.max(r, 9 * dpr);
    const alpha = 0.75 * (1 - e);
    if (alpha > 0) {
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = vs.pulseColor || "#4caf50";
      ctx.beginPath();
      ctx.arc(0, 0, baseR * (1 + 1.5 * e), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }

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
      if (vs.customiseSelected.has(id)) fillCells(cells, ROOM_SELECTED_FILL);
    }
    return;
  }

  // Standard mode: highlight active room during cleaning; accent tint for queued.
  for (const [id, room] of Object.entries(roomMap)) {
    const cells = room.cells;
    if (!cells || cells.length === 0) continue;
    let fill = null;
    if (id === vs.activeRoomId) fill = ROOM_ACTIVE_FILL;
    else if (vs.selectedRooms.has(id)) fill = ROOM_SELECTED_FILL;
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
  const zoom = vs.zoom || 1;
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
    ctx.save();
    // Labels keep a constant on-screen size: anchor at the room centroid
    // (which pans/zooms with the map), then locally undo the zoom so the
    // pill/text render at 1:1 regardless of zoom level. All pill geometry
    // below is relative to this origin.
    ctx.translate(cx, cy);
    ctx.scale(1 / zoom, 1 / zoom);
    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.textBaseline = "middle";
    const tw = ctx.measureText(chipText).width;
    const ph = fontSize * 1.65; // one 1.25em text line + 0.4em vertical padding
    const pw = tw + fontSize * 1.8;

    const pillX = -pw / 2;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.35)";
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 1;
    ctx.fillStyle = isSelected ? "rgba(255,212,0,0.75)" : "rgba(255,255,255,0.7)";
    ctx.beginPath();
    ctx.roundRect(pillX, -ph / 2, pw, ph, ph / 2);
    ctx.fill();
    ctx.restore();
    ctx.strokeStyle = "rgba(0,0,0,0.15)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.textAlign = "left";
    ctx.fillStyle = "#1b1c1f";
    ctx.fillText(chipText, pillX + fontSize * 0.9, 0);
    ctx.restore();

    // Hit area: the whole pill, in image-space. The pill's constant screen
    // size means its image-space footprint shrinks by 1/zoom as zoom rises —
    // matching exactly what's painted.
    hitAreas.push({
      id,
      x: (cx + pillX / zoom) / scaleX,
      y: (cy - ph / 2 / zoom) / scaleY,
      w: pw / zoom / scaleX,
      h: ph / zoom / scaleY,
    });
  }
  return hitAreas;
}

// ---------------------------------------------------------------------------
// Lit leaf: control button row (Play/Pause/Resume · Stop · Dock).
//
// Light DOM (createRenderRoot returns `this`) so
// the shell's `.btn-wrap` CSS applies with no duplication. Data
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
    const compact = row.compactEligible && row.options.some((o) => o.value === active);
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
    const compact = c.compactEligible && c.options.some((o) => o.value === active);
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
    const cls = `room-row${r.expanded ? " expanded" : ""}${!r.enabled ? " disabled-room" : ""}`;
    return html`
      <div class="${cls}" data-room-id=${r.id} draggable="true"
        @dragstart=${(e) => this._onDragStart(e, r.id)}
        @dragend=${(e) => this._onDragEnd(e)}>
        <div class="room-row-header" draggable="false">
          <span class="room-drag-handle" title="Drag to reorder">⠿</span>
          <span class="room-color-dot" style="background:${roomColor(r.colorId)}"></span>
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
      return html`<div class="room-summary" style="padding:16px 4px">${NO_ROOMS_MESSAGE}</div>`;
    }
    return html`
      ${rows.map((r) => this._roomRow(r))}
      <div class="room-list-footer">⠿ Drag to set cleaning order</div>`;
  }
}
if (!customElements.get("karcher-room-list")) {
  customElements.define("karcher-room-list", KarcherRoomList);
}

// Map-mode → icon, single source for the floating control, the map-hint icon,
// and the target-strip icon (previously hand-duplicated at each call site).
const MAP_MODE_ICON = { rooms: "mdi:view-grid-outline", zone: "mdi:select-drag" };

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
        ${this._btn("rooms", "Rooms", MAP_MODE_ICON.rooms)}
        ${this._btn("zone", "Zone", MAP_MODE_ICON.zone)}
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
    this._view = {}; // derived display state the template binds to (see _deriveView)
    this._selectedRooms = new Set();
    this._prevActivity = null;
    this._stopped = false;               // user pressed Stop: robot is paused, but the
                                         // cycle is over — rooms editable, primary = Start
                                         // (vs Pause, which keeps the resume-in-place lock)
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
    // Reveal-cursor animation: a single timeline drives both the path draw and
    // the robot. The robot rides the tip of the progressively-revealed path, so
    // the two can never desync, and the reveal is paced to the measured push
    // interval so motion stays continuous instead of glide-then-pause.
    this._revealRaf = null;      // requestAnimationFrame handle (runs while cleaning)
    this._revealAttr = null;     // latest attrs for the loop to draw from
    // The robot icon is a 2D exponential follower toward the backend FLOAT
    // robot_px (full sub-pixel precision). cur_path_px is int()-truncated +
    // decimated, so its arc length plateaus-then-snaps; robot_px does not. The
    // trail is pinned to the follower's position so path and robot stay synced
    // (the trail tip never runs ahead of the icon).
    this._robotDispX = null;     // drawn robot pixel x (float follower)
    this._robotDispY = null;     // drawn robot pixel y
    this._robotEmaV = null;      // EMA of robot travel speed (px/ms), cruise rate
    this._prevPushRpx = null;    // robot_px at the previous push (for speed calc)
    this._revealLastTs = 0;      // last frame timestamp (for dt)
    this._robotDisplayPhi = null;// smoothed heading actually drawn
    this._robotPrevX = null;     // last position used for heading baseline
    this._robotPrevY = null;
    this._prevPathHead = null;    // path head pixel, to detect map reprojection
    this._lastPathSig = null;    // detect a new path push
    this._lastPushTs = 0;        // timestamp of last path change (for speed dt)
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
    this._zoneRect = null;               // {x0,y0,x1,y1} in image-space px, or null
    this._zoneDrag = null;               // {mode: 'create'|'move'|'resize', ...} while dragging, else null
    this._sheetOpen = false;             // bottom sheet visibility
    this._sheetTab = "target";           // "target" | "settings"
    this._lastSettingsMode = "standard"; // restored when leaving Zone back to Rooms
    this._zoom = 1;                      // map zoom level, 1 = fit-to-frame
    this._pan = { x: 0, y: 0 };           // map pan offset in CSS px, {0,0} at zoom=1
    this._activePointers = new Map();    // pointerId → {x,y} CSS px, tracked regardless of zoneMode
    this._pinch = null;                  // {mid, dist, zoom, pan} snapshot at gesture start, while 2+ pointers are down
    this._panDrag = null;                // {pointerId, start:{x,y}, pan} snapshot for a one-finger pan while zoomed
    this._gestured = false;              // a pinch/pan happened this touch sequence — swallow the trailing click
    this._hasNudged = false;             // the one-shot "map is pannable" nudge fired this zoom-in session
    this._nudgePending = false;          // zoom crossed 1 mid-pinch; nudge once the fingers lift
    this._nudgeRaf = null;               // requestAnimationFrame handle for the nudge animation
  }

  // HA calls setConfig imperatively; store config (a reactive property).
  setConfig(config) {
    if (!config.vacuum_entity) throw new Error("vacuum_entity is required");
    this._config = { ...deriveCompanions(config.vacuum_entity), ...config };
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
    this._stopReveal();
    if (this._nudgeRaf) {
      cancelAnimationFrame(this._nudgeRaf);
      this._nudgeRaf = null;
    }
    if (this._mapResizeObserver) {
      this._mapResizeObserver.disconnect();
      this._mapResizeObserver = null;
    }
  }

  // ── render (declarative; was _buildDOM) ──────────────────────────────────────

  render() {
    const v = this._view;
    if (v.notFound) {
      return html`
        <ha-card><hui-warning>Entity not available: ${v.vacuumEntity}</hui-warning></ha-card>`;
    }
    // Two derived axes over the unchanged tri-state cardMode: the floating map
    // control reads Rooms|Zone (Zone ⟺ Area), the sheet reads Standard|Customise.
    const mapMode = this._mapMode();
    const settingsMode = v.cardMode === "customise" ? "customise" : "standard";
    const sheetOpen = !!this._sheetOpen;
    const sheetTab = this._sheetTab || "target";
    const targetIcon = MAP_MODE_ICON[mapMode];
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

        <ha-alert alert-type="error" class="rcv-region ${v.hasError ? "visible" : ""}">${v.errorText || "Robot reported a fault"}</ha-alert>

        <div class="rcv-map">
          <div class="map-placeholder ${v.mapLoading ? "map-loading" : ""}"
               style=${v.mapLoaded ? "display:none" : ""}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z"></path>
            </svg>
            <span>${v.placeholderText || ""}</span>
          </div>
          <div class="map-container" style=${v.aspectRatio
            ? `aspect-ratio:${v.aspectRatio};max-height:var(--rcv-map-max-height, 60dvh)`
            : ""}>
            <canvas class="${v.zoneMode ? "zone-draw" : ""} ${!v.zoneMode && v.controlsLocked ? "locked" : ""} ${v.mapZoomed ? "map-zoomed" : ""}"
              style=${v.mapLoaded ? "display:block" : "display:none"}
              @click=${(e) => this._onCanvasClick(e)}
              @pointerdown=${(e) => this._onMapPointerDown(e)}
              @pointermove=${(e) => this._onMapPointerMove(e)}
              @pointerup=${(e) => this._onMapPointerUp(e)}
              @pointercancel=${(e) => this._onMapPointerUp(e)}
              @wheel=${(e) => this._onWheelZoom(e)}></canvas>
            ${v.mapLoaded ? html`
              <div class="map-edge map-edge-l" style="opacity:${v.edgeFades.left}"></div>
              <div class="map-edge map-edge-r" style="opacity:${v.edgeFades.right}"></div>
              <div class="map-edge map-edge-t" style="opacity:${v.edgeFades.top}"></div>
              <div class="map-edge map-edge-b" style="opacity:${v.edgeFades.bottom}"></div>` : ""}
          </div>
          <karcher-map-mode class="map-mode" .mode=${mapMode} .locked=${v.controlsLocked}
            @karcher-map-mode=${(e) => this._onMapMode(e)}></karcher-map-mode>
          ${v.mapZoomed && v.mapLoaded ? html`
            <button class="map-reset" title="Reset zoom"
              @click=${() => this._resetZoom()}>
              <ha-icon icon="mdi:fit-to-screen"></ha-icon>
              <span>Reset</span>
            </button>` : ""}
        </div>

        <div class="map-hint ${v.mapLoaded ? "" : "hint-hidden"} ${mapMode !== "zone" && v.controlsLocked ? "hint-locked" : ""}">
          <ha-icon icon=${targetIcon}></ha-icon>
          <span>${mapMode === "zone"
            ? (v.zoneRect
              ? "Drag to move, corners to resize · press Start to clean."
              : "Drag to draw an area · press Start to clean it.")
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
            .playLabel=${v.primaryLabel} .playDisabled=${v.playDisabled}
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
                      @click=${() => this._setCardMode("standard")}>Standard</button>
                    <button class="seg-btn ${settingsMode === "customise" ? "active" : ""}"
                      aria-pressed=${settingsMode === "customise"} ?disabled=${v.controlsLocked}
                      @click=${() => this._setCardMode("customise")}>Customise</button>
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
                <karcher-room-list class="room-list ${v.zoneActive ? "zone-locked" : ""}"
                  style=${settingsMode === "customise" ? "" : "display:none"}
                  .rows=${v.roomRows || []} .busy=${v.controlsLocked || v.zoneActive}
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
  // the existing _onRoomToggle path (one source of truth). The banner always
  // shows v.targetLabel — the same selection summary as the target strip below
  // the map — so it reflects the selection and never collapses (no content jump).
  _renderCleanTarget(v, mapMode) {
    if (mapMode === "zone") {
      return html`
        <div class="zone-summary">
          <ha-icon icon=${MAP_MODE_ICON.zone}></ha-icon>
          <span>${v.zoneRect ? "Area selected — ready to clean" : "No area yet — draw one on the map"}</span>
        </div>`;
    }
    const rooms = v.cleanTargetRooms || [];
    if (rooms.length === 0) {
      return html`<div class="zone-summary"><ha-icon icon="mdi:home-outline"></ha-icon>
        <span>${NO_ROOMS_MESSAGE}</span></div>`;
    }
    return html`
      <div class="whole-home-banner">
        <ha-icon icon="mdi:home-outline"></ha-icon>
        <span>${v.targetLabel}</span>
      </div>
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
    const vacState = this._vacState();
    if (!vacState) {
      this._view = { notFound: true, vacuumEntity: this._config.vacuum_entity };
      return;
    }

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
    // Reload recovery: a card mounted mid-clean has no in-memory selection, so the
    // map highlight and target note would wrongly read "whole home". Re-seed from
    // the backend's active-clean room set (empty there genuinely means whole-home).
    // Skip while _stopped — there the user is re-selecting rooms for a new clean.
    if (
      isOccupied(activity) && !this._stopped && this._selectedRooms.size === 0 &&
      Array.isArray(attr?.active_clean_room_ids) && attr.active_clean_room_ids.length
    ) {
      for (const id of attr.active_clean_room_ids) this._selectedRooms.add(String(id));
    }
    // The Stop intent is spent once the robot leaves the paused state it created
    // (a fresh clean began, or it docked/idled). The prevActivity===paused guard
    // avoids wiping the flag during the brief cleaning→paused settle right after
    // Stop is pressed, when the robot is still reported as cleaning.
    if (this._stopped && (!isOccupied(activity) || this._prevActivity === "paused")) {
      this._stopped = false;
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
    const attr = this._vacState()?.attributes;
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
    // Re-clamp pan against the new CSS size — a pan valid before a resize
    // (rotation, sidebar toggle) can expose the map edge afterward otherwise.
    this._pan = clampPan(this._pan, this._zoom, rect.width, rect.height, this._imgSize());
  }

  _deriveView(attr, activity) {
    const cfg = this._config;
    const isOffline = this._isOffline();
    let statusText, dotClass, labelClass;
    if (isOffline) {
      statusText = "Offline"; dotClass = "dot-offline"; labelClass = "label-offline";
    } else if (this._stopped && activity === "paused") {
      // A user Stop ended the cycle; the robot is technically paused, but the card
      // presents it as resting (ready for a new clean) to match the unlocked
      // controls and "Start" button — not a resumable "Paused".
      statusText = "Stopped"; dotClass = "dot-idle"; labelClass = "label-idle";
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

    // fault_code sensor's state is the translation slug (e.g. "place_on_dock");
    // formatEntityState resolves it to the curated text already shipped in
    // translations/en.json. Falls back to the raw slug if unavailable (older
    // frontend), or the generic message if no fault is set.
    const faultState = this.hass.states[this._resolveFaultEntity()];
    const errorText = (hasError && faultState && isUsableValue(faultState.state) && faultState.state !== "none")
      ? (typeof this.hass.formatEntityState === "function"
          ? this.hass.formatEntityState(faultState)
          : faultState.state)
      : "Robot reported a fault";

    return {
      ...this._batteryView(),
      ...this._mapPlaceholderView(attr),
      legend: legendItems(attr),
      name: attr.friendly_name || "Kärcher RCV5",
      statusText, dotClass, labelClass,
      pinging: !isOffline && isBusy(activity),
      hasError: !!hasError,
      errorText,
      activity,
      offline: !!isOffline,
      cardMode: this._cardMode,
      controlsLocked: this._controlsLocked(activity),
      tiles: this._statTiles(),
      selectorRows: this._selectorRows(attr),
      tabHelper: this._tabHelperText(attr),
      // Context-aware primary label for a resting robot; null while occupied so
      // the button row falls back to Pause/Resume. A Stop→paused robot counts as
      // resting here, so its primary button reads "Start" (a fresh clean), not
      // "Resume".
      primaryLabel: this._restingForUx(activity)
        ? primaryCleanLabel(this._mapMode(), this._activeSelection().size, !!this._zoneRect)
        : null,
      // Area mode with no drawn rect yet: nothing to clean, so disable Start
      // (but only while resting — once occupied the row falls back to Pause/Resume).
      playDisabled: this._cardMode === "area" && !this._zoneRect && this._restingForUx(activity),
      roomRows: this._roomListRows(attr),
      targetLabel: this._targetLabel(attr),
      cleanTargetRooms: this._cleanTargetRooms(attr),
      mapLoaded: this._mapLoaded,
      zoneMode: this._zoneMode,
      zoneRect: this._zoneRect,
      zoneActive: this._zoneMode || !!this._zoneRect,
      mapZoomed: this._zoom > 1,
      edgeFades: this._edgeFades(),
    };
  }

  // Per-edge scrim opacity (0..1) for the four directional "map continues this
  // way" overlays: the off-screen overhang past each edge, ramped to full over
  // EDGE_FADE_RAMP_PX. All zero at fit zoom or before the canvas is sized.
  _edgeFades() {
    const zero = { left: 0, right: 0, top: 0, bottom: 0 };
    if (this._zoom <= 1 || !this._canvas) return zero;
    const dpr = this._dpr || 1;
    const cssW = this._canvas.width / dpr;
    const cssH = this._canvas.height / dpr;
    if (!cssW || !cssH) return zero;
    const hidden = panEdgeHidden(this._pan, this._zoom, cssW, cssH, this._imgSize());
    const ramp = (px) => Math.min(1, px / EDGE_FADE_RAMP_PX);
    return {
      left: ramp(hidden.left), right: ramp(hidden.right),
      top: ramp(hidden.top), bottom: ramp(hidden.bottom),
    };
  }

  // The map-interaction axis derived from the tri-state cardMode: "zone" ⟺ Area,
  // "rooms" otherwise. Single source for render(), _targetLabel, and primaryLabel.
  _mapMode() {
    return this._cardMode === "area" ? "zone" : "rooms";
  }

  // Area-draw mode is not separate state — it is exactly "the Area tab is
  // active". Derived so it can never drift from _cardMode.
  get _zoneMode() {
    return this._cardMode === "area";
  }

  // Selection set the map/chips/strip all read: customise → the per-room custom
  // set, otherwise the transient standard set.
  _activeSelection() {
    return this._cardMode === "customise" ? this._customiseSelected : this._selectedRooms;
  }

  // One-line target-strip summary (rooms names / "Whole home" / area copy).
  _targetLabel(attr) {
    const roomMap = attr?.room_map || {};
    return targetStripLabel(
      this._mapMode(), this._activeSelection(), !!this._zoneRect,
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

  // The vacuum entity's state object — the single lookup every other accessor
  // below builds on (state, attributes, map_image_size all flow through here).
  _vacState() {
    return this.hass?.states[this._config?.vacuum_entity];
  }

  _imgSize() {
    return this._vacState()?.attributes?.map_image_size;
  }

  // Robot unreachable: entity unavailable, or the connectivity sensor is off.
  _isOffline() {
    const activity = this._vacState()?.state;
    const conn = this._config?.connectivity_entity;
    return activity === "unavailable" || !!(conn && this.hass.states[conn]?.state === "off");
  }

  // True when the card should present resting controls (room selection editable,
  // primary button = a fresh "Start"): the robot is genuinely resting, OR the
  // user pressed Stop and it has settled into the paused state that produced —
  // a finished cycle the card lets them re-target into a new clean.
  _restingForUx(activity) {
    return !isOccupied(activity) || (this._stopped && activity === "paused");
  }

  // Config + selection (mode tabs, settings, room list, map selection, area
  // drawing) lock whenever a job is in progress — cleaning, paused OR returning
  // (editing then would re-target the in-flight clean; Resume re-dispatches the
  // selection) — or the robot is offline (the service call can't reach it). A
  // user-initiated Stop unlocks the paused state so new rooms can be picked.
  _controlsLocked(activity) {
    return this._isOffline() || !this._restingForUx(activity);
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
      // Area draws its own selection; a room pick carried over from Standard
      // must not still show as selected on the map or feed the Start fallback.
      this._selectedRooms.clear();
      // Start with a centered default selection rather than an empty map —
      // the user adjusts it instead of having to draw from scratch. Only
      // seed when there's no rect yet: _applyMode("area") re-runs when the
      // backend echoes prefer_mode after the optimistic switch, and that
      // re-application must not clobber an edit made in the meantime.
      if (!this._zoneRect) {
        const imgSize = this._imgSize();
        this._zoneRect = defaultZoneRect(imgSize);
        this._lastDrawKey = null;
      }
    } else if (this._zoneRect) {
      // Only the Area tab draws — leaving it for Standard or Customise drops
      // the selection so it can't leak into another tab.
      this._zoneRect = null;
      this._lastDrawKey = null;
      if (this._canvas) this._canvas.style.cursor = "";
    }
  }

  _setCardMode(mode) {
    if (!this.hass || !this._config) return;
    const activity = this._vacState()?.state;
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

  // Resolve the fault_code sensor's live entity_id. The derived/configured
  // cfg.fault_code_entity (sensor.<stem>_robot_status) is correct for installs
  // created after this entity's name changed from "Fault code" to "Robot
  // status" — but HA assigns entity_id once at first registration and never
  // renames it, so older installs kept sensor.<stem>_fault_code. If the derived
  // guess doesn't resolve to a real entity, fall back to a registry scan by
  // device_id + translation_key (mirrors vacuum.py's _pref_entity_map); if that
  // also finds nothing, fall back to the guess itself (status quo, no regression).
  _resolveFaultEntity() {
    const cfgId = this._config?.fault_code_entity;
    if (cfgId && this.hass?.states[cfgId]) return cfgId;
    const vac = this._config?.vacuum_entity;
    const deviceId = this.hass?.entities?.[vac]?.device_id;
    if (deviceId) {
      for (const [entityId, entry] of Object.entries(this.hass.entities)) {
        if (entry.device_id === deviceId && entry.translation_key === "fault_code") {
          return entityId;
        }
      }
    }
    return cfgId;
  }

  // Ask the integration to refetch room preferences now (bypasses the 5-min poll;
  // coordinator throttles to ~5 s). Passes device_id when known so multi-robot
  // setups route correctly. Used by the mount/foreground "fresh on look" trigger.
  _refreshPreferences() {
    const hass = this.hass;
    const vac = this._config?.vacuum_entity;
    if (!hass || !vac) return;
    // After the iOS app is backgrounded and re-foregrounded the WebSocket is
    // briefly reconnecting; calling a service then rejects with "connection
    // lost" and HA surfaces its own action_failed toast (we can't suppress it
    // from here). Skip while disconnected and re-arm so the next hass update —
    // which fires once the socket is back — retries the best-effort refresh.
    if (hass.connection?.connected === false) {
      this._pendingPrefRefresh = true;
      return;
    }
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
    const attr = this._vacState()?.attributes;
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
        const attr = this._vacState()?.attributes;
        if (attr) this._drawMap(attr);
      }
    };
    img.src = "/karcher_home_robots/static/icon.svg";
  }

  // Assemble the plain viewState the module renderer consumes: everything
  // hass-derived is pre-resolved here so the renderer never reads hass/config.
  _viewState(attr) {
    // "Cleaning" highlight excludes "returning" deliberately — the active-room
    // tint should drop the moment the robot starts heading back to dock.
    const activity = this._vacState()?.state;
    const isCleaning = this._cardMode !== "customise"
      && (activity === "cleaning" || activity === "paused");
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
      zoom: this._zoom,
      pan: this._pan,
    };
  }

  // True while the robot is busy and the pulse cue should run: cleaning,
  // returning, or relocalizing ("Locating"). Cleaning/returning also glide the
  // icon along the path; locating has no live pose so the icon holds still but
  // still pulses (a "working" cue), matching the header status dot.
  _robotMoving() {
    const v = this._vacState();
    const state = v?.state;
    if (state === "cleaning" || state === "returning") return true;
    return v?.attributes?.status_label === "Locating";
  }

  // Pulse colour resolved from the active theme to match the header status dot:
  // green (--success-color) for cleaning, accent (--primary-color) for
  // returning/locating (the header renders "Locating" with the returning dot).
  _pulseColor() {
    if (!this._pulseColors) {
      const cs = getComputedStyle(this);
      this._pulseColors = {
        success: (cs.getPropertyValue("--success-color") || "").trim() || "#4caf50",
        primary: (cs.getPropertyValue("--primary-color") || "").trim() || "#03a9f4",
      };
    }
    const v = this._vacState();
    const usePrimary =
      v?.state === "returning" || v?.attributes?.status_label === "Locating";
    return usePrimary ? this._pulseColors.primary : this._pulseColors.success;
  }

  _drawMap(attr) {
    if (!this._mapImg || !this._canvas) return;
    this._revealAttr = attr;
    // Run the reveal loop whenever the robot is busy and has a pose: it glides
    // the icon along the path (cleaning/returning) and/or animates the pulse cue
    // (including locating, where the pose is static but we still want the pulse).
    // Everything else (docked/idle/paused) draws statically.
    const moving = this._robotMoving();
    const tip = attr.robot_px;
    if (!moving || !tip) {
      this._stopReveal();
      this._staticDraw(attr);
      return;
    }
    const path = attr.cur_path_px || [];
    const sig = `${path.length}:${path[path.length - 2]},${path[path.length - 1]}`;
    if (sig !== this._lastPathSig) {
      this._onNewPath(path, sig);
    }
    this._ensureRevealLoop();
  }

  // Plain key-checked static draw (the pre-animation behaviour).
  _staticDraw(attr) {
    const vs = this._viewState(attr);
    const key = computeDrawKey(attr, vs);
    if (key === this._lastDrawKey) return;
    this._lastDrawKey = key;
    this._loadRobotIcon();
    const ctx = this._canvas.getContext("2d");
    this._roomCheckboxHitAreas = drawMap(ctx, this._canvas, vs);
  }

  // A new path push arrived: measure the robot's real travel speed (distance the
  // float robot_px moved / time since the last push) and EMA it. The RAF loop
  // cruises the icon at this speed, so the glide is even regardless of how lumpy
  // each individual push is.
  _onNewPath(path, sig) {
    this._lastPathSig = sig;
    const now = performance.now();
    const rp = this._revealAttr?.robot_px;
    if (this._lastPushTs) {
      const dt = now - this._lastPushTs;
      if (rp && this._prevPushRpx && dt > 0) {
        const d = Math.hypot(rp.x - this._prevPushRpx.x, rp.y - this._prevPushRpx.y);
        // Only learn the cruise speed while the robot is actually moving (>2px),
        // so genuine pauses/turns don't drag the average down. Long window so the
        // per-push lumpiness averages out into a stable cruise rate.
        if (d > 2) {
          const inst = d / dt; // px/ms over this push
          this._robotEmaV =
            this._robotEmaV == null ? inst : this._robotEmaV * 0.85 + inst * 0.15;
        }
      }
    }
    this._lastPushTs = now;
    if (rp) this._prevPushRpx = { x: rp.x, y: rp.y };
  }

  _ensureRevealLoop() {
    if (this._revealRaf) return;
    this._loadRobotIcon();
    const step = (now) => {
      if (!this._canvas || !this._mapImg || !this._robotMoving()) {
        this._revealRaf = null;
        return;
      }
      const attr = this._revealAttr;
      const path = attr?.cur_path_px || [];
      const tip = attr?.robot_px;
      if (!tip) {
        this._revealRaf = requestAnimationFrame(step);
        return;
      }

      // A whole-path reprojection (map refresh) moves every pixel including the
      // robot; snap the follower onto the new frame so it doesn't glide across
      // the discontinuity. Detected via the path head pixel changing.
      const head = path.length >= 2 ? `${path[0]},${path[1]}` : null;
      const reproj = head != null && this._prevPathHead != null && head !== this._prevPathHead;
      this._prevPathHead = head;

      const dt = this._revealLastTs ? Math.min(100, now - this._revealLastTs) : 16;
      this._revealLastTs = now;
      if (this._robotDispX == null || reproj) {
        this._robotDispX = tip.x; // first sight / post-reproject: snap, no glide
        this._robotDispY = tip.y;
      }
      // Constant-velocity follower: cruise the icon at the robot's measured
      // travel speed (EMA from _onNewPath) while holding a small trailing buffer
      // behind the live tip. A bare exponential moves at speed ∝ gap, so it
      // surges on big lumps and crawls when caught up — that is the residual
      // speed variation. Here the speed is dominated by the feed-forward EMA and
      // only gently corrected toward the buffer setpoint, so the gap converges to
      // ~one push of travel and the icon cruises at an even pace.
      const dx0 = tip.x - this._robotDispX;
      const dy0 = tip.y - this._robotDispY;
      const gap = Math.hypot(dx0, dy0);
      // Feed-forward dominated: cruise at the stable long-run speed, ease to a
      // stop when caught up, and allow only a *bounded* catch-up when the robot
      // has surged ahead — never the gap-proportional surge that made earlier
      // builds pulse (that correction term ran ~3-12x the feed-forward).
      const ema = this._robotEmaV || 0;
      // buffer ≈ two pushes of travel: the routine per-push gap sawtooth (~one
      // push) stays *below* it, so during steady motion speed == ema (flat, no
      // per-push ripple). Catch-up only engages on a genuine fall-behind.
      const buffer = ema * 1600;
      const easeDist = 8; // px: glide to a stop instead of snapping on
      let speed = gap < easeDist ? ema * (gap / easeDist) : ema;
      if (gap > buffer) speed += Math.min((gap - buffer) * 0.001, ema * 0.6);
      const move = speed * dt;
      if (gap < 0.5 || move >= gap) {
        this._robotDispX = tip.x;
        this._robotDispY = tip.y;
      } else {
        this._robotDispX += (dx0 / gap) * move;
        this._robotDispY += (dy0 / gap) * move;
      }
      const rx = this._robotDispX;
      const ry = this._robotDispY;

      // Pin the trail to the follower: reveal the path up to (total − trailGap),
      // where trailGap is how far the icon now trails the tip. When the tip snaps
      // forward (int path lump), total and trailGap jump together → revealLen is
      // steady → the trail tip stays glued to the icon instead of running ahead.
      const total = pathArcLength(path);
      const trailGap = Math.hypot(tip.x - rx, tip.y - ry);
      const reveal = revealPath(path, Math.max(0, total - trailGap));

      // Heading from the icon's actual travel over a ≥2px baseline (not the
      // per-segment direction), so decimation zig-zag doesn't make it twitch.
      // Below the baseline the heading holds steady.
      if (this._robotPrevX == null) {
        this._robotPrevX = rx;
        this._robotPrevY = ry;
      } else {
        const dx = rx - this._robotPrevX;
        const dy = ry - this._robotPrevY;
        if (Math.hypot(dx, dy) >= 2) {
          const target = Math.atan2(-dy, dx); // image y flipped → world phi
          this._robotDisplayPhi =
            this._robotDisplayPhi == null ? target : lerpAngle(this._robotDisplayPhi, target, 0.2);
          this._robotPrevX = rx;
          this._robotPrevY = ry;
        }
      }
      const vs = this._viewState(attr);
      vs.attr = {
        ...attr,
        cur_path_px: reveal.path,
        robot_px: { x: rx, y: ry, phi: this._robotDisplayPhi ?? 0 },
      };
      // Pulse cue: the loop only runs while the robot is busy, so flag it and
      // hand drawRobot a looping 0..1 phase + theme colour. 1.6s period matches
      // the header status dot's rcv-ping animation.
      vs.pulse = true;
      vs.pulsePhase = (now % 1600) / 1600;
      vs.pulseColor = this._pulseColor();
      // Repaint every frame while moving so the pulse keeps animating even when
      // the robot is momentarily stationary.
      const ctx = this._canvas.getContext("2d");
      this._roomCheckboxHitAreas = drawMap(ctx, this._canvas, vs);
      this._revealRaf = requestAnimationFrame(step);
    };
    this._revealRaf = requestAnimationFrame(step);
  }

  _stopReveal() {
    if (this._revealRaf) {
      cancelAnimationFrame(this._revealRaf);
      this._revealRaf = null;
    }
    this._robotDispX = null;
    this._robotDispY = null;
    this._robotEmaV = null;
    this._prevPushRpx = null;
    this._revealLastTs = 0;
    this._lastPathSig = null;
    this._robotDisplayPhi = null;
    this._robotPrevX = null;
    this._robotPrevY = null;
    this._prevPathHead = null;
    // Reset pacing too: no pushes fire while docked, so a carried-over timestamp
    // makes the first push of the next clean measure a huge bogus interval (the
    // whole idle gap).
    this._lastPushTs = 0;
  }

  _zonePx(e) {
    const imgSize = this._imgSize();
    if (!imgSize || !this._canvas) return null;
    const rect = this._canvas.getBoundingClientRect();
    const { px, py } = clientToImagePx(e.clientX, e.clientY, rect, imgSize, this._zoom, this._pan);
    return {
      x: Math.max(0, Math.min(imgSize.width, px)),
      y: Math.max(0, Math.min(imgSize.height, py)),
    };
  }

  _zoneMinPx() {
    const cellSize = this._imgSize()?.cell_size;
    return minZonePx(cellSize);
  }

  // Corner-handle hit radius, in image px. ZONE_HANDLE_RADIUS_PX is a fixed
  // screen-px tolerance — divide by the canvas scale (and the current zoom,
  // since zooming in shrinks the image-px-per-screen-px ratio further) so
  // handles stay equally grabbable regardless of scale or zoom level.
  _zoneHandleRadiusPx() {
    const imgSize = this._imgSize();
    if (!imgSize || !this._canvas) return ZONE_HANDLE_RADIUS_PX;
    const dpr = this._dpr || 1;
    // Content-box scale, not raw canvas scale — the full-bleed canvas is wider
    // than the aspect-fit map it letterboxes.
    const box = fitContentBox(this._canvas.width / dpr, this._canvas.height / dpr, imgSize);
    const scaleX = box.w / imgSize.width;
    return ZONE_HANDLE_RADIUS_PX / (scaleX || 1) / (this._zoom || 1);
  }

  _zoneBounds() {
    const imgSize = this._imgSize();
    return imgSize ? { width: imgSize.width, height: imgSize.height } : { width: 0, height: 0 };
  }

  // Midpoint + inter-finger distance (CSS px, canvas-relative) of the tracked
  // pointers — the shared geometry a 2+-finger touch gesture pinches/pans from.
  _pinchGeometry() {
    const pts = [...this._activePointers.values()];
    const [a, b] = pts;
    return {
      mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
      dist: Math.hypot(b.x - a.x, b.y - a.y),
    };
  }

  // Arm a one-finger drag-to-pan from this press. Only meaningful once zoomed
  // in — at fit zoom there is nothing to pan to, and vertical swipes should
  // keep scrolling the page (touch-action: pan-y). The actual pan starts in
  // pointermove once the pointer travels past TAP_SLOP_PX, so a plain tap
  // still falls through to the click handler (room select).
  _armPanDrag(e) {
    if (this._zoom <= 1) return;
    const pt = this._activePointers.get(e.pointerId);
    if (!pt) return;
    this._panDrag = { pointerId: e.pointerId, start: { ...pt }, pan: this._pan };
  }

  _onMapPointerDown(e) {
    if (!this._canvas) return;
    const rect = this._canvas.getBoundingClientRect();
    this._activePointers.set(e.pointerId, { x: e.clientX - rect.left, y: e.clientY - rect.top });
    this._canvas.setPointerCapture?.(e.pointerId);
    // Fresh single-finger touch starting a new sequence — clear any leftover
    // swallow flag from a prior pinch that ended without a synthetic click,
    // so this new tap isn't silently eaten too.
    if (this._activePointers.size === 1) this._gestured = false;

    if (this._activePointers.size >= 2) {
      // A second finger landing always starts/continues a pinch/pan, even if
      // a zone drag or one-finger pan was mid-gesture on the first finger —
      // never resume those once pinch takes over (would require lift +
      // re-press). Snapshot the gesture's starting geometry once here;
      // pinchStep references this FIXED start every frame rather than the
      // previous frame (see pinchStep for why the incremental version
      // ratchets/drifts).
      e.preventDefault();
      this._zoneDrag = null;
      this._panDrag = null;
      this._gestured = true;
      this._pinch = { ...this._pinchGeometry(), zoom: this._zoom, pan: this._pan };
      return;
    }

    if (!this._zoneMode) {
      this._armPanDrag(e);
      return;
    }
    const activity = this._vacState()?.state;
    if (this._controlsLocked(activity)) {
      this._armPanDrag(e);
      return;
    }
    const p = this._zonePx(e);
    if (!p) return;
    e.preventDefault();

    const hit = hitTestZoneRect(p.x, p.y, this._zoneRect, this._zoneHandleRadiusPx());
    if (hit === "body") {
      // Grab offset from the rect's top-left, fixed for the whole gesture —
      // an incremental delta would drift once the rect clamps at a map edge.
      const x0 = Math.min(this._zoneRect.x0, this._zoneRect.x1);
      const y0 = Math.min(this._zoneRect.y0, this._zoneRect.y1);
      this._zoneDrag = { mode: "move", grabDX: p.x - x0, grabDY: p.y - y0 };
    } else if (hit) {
      this._zoneDrag = { mode: "resize", corner: hit };
    } else if (!this._zoneRect) {
      // No selection yet at all (map not loaded when Area was entered) —
      // draw a fresh one. Once a selection exists, a tap outside it is a
      // no-op: the selection always stays present, never replaced by a click.
      this._zoneDrag = { mode: "create" };
      this._zoneRect = clampZoneRect({ x0: p.x, y0: p.y, x1: p.x, y1: p.y }, this._zoneMinPx());
    } else {
      // Outside the existing selection: never replaces the rect, but while
      // zoomed in the drag can still pan the map.
      this._armPanDrag(e);
      return;
    }
    this._lastDrawKey = null;
    this.requestUpdate();
  }

  // Cursor feedback while hovering an existing zone without dragging:
  // resize cursor over a corner handle, move cursor over the body.
  _onZonePointerHover(e) {
    if (!this._zoneMode || !this._zoneRect || !this._canvas) return;
    const p = this._zonePx(e);
    if (!p) return;
    const hit = hitTestZoneRect(p.x, p.y, this._zoneRect, this._zoneHandleRadiusPx());
    const cursor =
      hit === "nw" || hit === "se" ? "nwse-resize" :
      hit === "ne" || hit === "sw" ? "nesw-resize" :
      hit === "body" ? "move" : "default";
    this._canvas.style.cursor = cursor;
  }

  _onMapPointerMove(e) {
    if (!this._canvas) return;
    if (this._activePointers.has(e.pointerId)) {
      const rect = this._canvas.getBoundingClientRect();
      this._activePointers.set(e.pointerId, { x: e.clientX - rect.left, y: e.clientY - rect.top });
    }

    if (this._activePointers.size >= 2 && this._pinch) {
      e.preventDefault();
      const { mid, dist } = this._pinchGeometry();
      const dpr = this._dpr || 1;
      const cssW = this._canvas.width / dpr;
      const cssH = this._canvas.height / dpr;
      // Reference the FIXED gesture-start snapshot every frame (not the
      // previous frame) — see pinchStep for why the incremental version drifts.
      const { zoom, pan } = pinchStep(this._pinch, mid, dist, cssW, cssH, this._imgSize());
      // Crossing 1 mid-pinch arms the nudge, but the fingers are still driving
      // pan/zoom — defer the animation to pointerup so it can't fight the gesture.
      if (this._zoom <= 1 && zoom > 1 && !this._hasNudged) this._nudgePending = true;
      this._zoom = zoom;
      this._pan = pan;
      this._lastDrawKey = null;
      this.requestUpdate();
      return;
    }

    if (this._panDrag && this._panDrag.pointerId === e.pointerId) {
      const pt = this._activePointers.get(e.pointerId);
      const dx = pt.x - this._panDrag.start.x;
      const dy = pt.y - this._panDrag.start.y;
      // Within the slop radius this may still turn out to be a tap — hold off.
      // Past it once, the whole sequence is a pan (and the trailing click is
      // swallowed), even if the finger later re-enters the slop radius.
      if (!this._gestured && Math.hypot(dx, dy) < TAP_SLOP_PX) return;
      this._gestured = true;
      e.preventDefault();
      const dpr = this._dpr || 1;
      this._pan = dragPan(
        this._panDrag.pan, dx, dy, this._zoom,
        this._canvas.width / dpr, this._canvas.height / dpr, this._imgSize()
      );
      this._lastDrawKey = null;
      this.requestUpdate();
      return;
    }

    if (!this._zoneMode) return;
    if (!this._zoneDrag || !this._zoneRect) {
      this._onZonePointerHover(e);
      return;
    }
    const p = this._zonePx(e);
    if (!p) return;
    const d = this._zoneDrag;
    if (d.mode === "create") {
      const { x0, y0 } = this._zoneRect;
      this._zoneRect = clampZoneRect({ x0, y0, x1: p.x, y1: p.y }, this._zoneMinPx());
    } else if (d.mode === "move") {
      const x0 = Math.min(this._zoneRect.x0, this._zoneRect.x1);
      const y0 = Math.min(this._zoneRect.y0, this._zoneRect.y1);
      const dx = (p.x - d.grabDX) - x0;
      const dy = (p.y - d.grabDY) - y0;
      this._zoneRect = moveZoneRect(this._zoneRect, dx, dy, this._zoneBounds());
    } else if (d.mode === "resize") {
      this._zoneRect = resizeZoneRect(this._zoneRect, d.corner, p.x, p.y, this._zoneMinPx(), this._zoneBounds());
    }
    this._lastDrawKey = null;
    this.requestUpdate();
  }

  _onMapPointerUp(e) {
    this._activePointers.delete(e.pointerId);
    this._canvas?.releasePointerCapture?.(e.pointerId);
    if (this._panDrag?.pointerId === e.pointerId) this._panDrag = null;
    if (this._activePointers.size < 2) {
      // Dropping below 2 fingers ends the pinch outright — never resume it
      // or fall back into a zone drag from the remaining finger; that finger
      // must be lifted and re-pressed to start a fresh gesture.
      this._pinch = null;
    }
    // Fire the deferred pinch-zoom nudge only once every finger is off the map,
    // so the animated pan can't fight a still-active gesture.
    if (this._nudgePending && this._activePointers.size === 0) {
      this._nudgePending = false;
      this._triggerNudge();
    }
    this.requestUpdate();
    if (!this._zoneMode || !this._zoneDrag) return;
    this._zoneDrag = null;
    this._lastDrawKey = null;
  }

  // Back to fit-to-frame. Also drops any in-flight pan/pinch/nudge gesture so a
  // finger still resting on the map can't reapply the stale snapshot, and re-arms
  // the pannability nudge for the next fresh zoom-in.
  _resetZoom() {
    this._zoom = 1;
    this._pan = { x: 0, y: 0 };
    this._panDrag = null;
    this._pinch = null;
    this._hasNudged = false;
    this._nudgePending = false;
    if (this._nudgeRaf) {
      cancelAnimationFrame(this._nudgeRaf);
      this._nudgeRaf = null;
    }
    this._lastDrawKey = null;
    this.requestUpdate();
  }

  // One-shot discoverability cue: the first time the map is zoomed past fit, ease
  // the pan a short distance toward whichever side hides the most map and back,
  // telegraphing that the map is draggable. The edge scrims already show WHERE
  // content is hidden; this shows THAT it moves. Skipped under reduced-motion (the
  // scrims remain), and bailed if the user grabs the map or resets mid-animation.
  _triggerNudge() {
    if (this._hasNudged) return;
    this._hasNudged = true;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    if (!this._canvas || this._zoom <= 1) return;
    const dpr = this._dpr || 1;
    const cssW = this._canvas.width / dpr;
    const cssH = this._canvas.height / dpr;
    const imgSize = this._imgSize();
    const hidden = panEdgeHidden(this._pan, this._zoom, cssW, cssH, imgSize);
    const totalX = hidden.left + hidden.right;
    const totalY = hidden.top + hidden.bottom;
    if (totalX < 1 && totalY < 1) return; // fully framed — nothing to reveal
    // Nudge on the dominant axis, toward the side hiding more (guaranteed room to
    // move, so the clamp can't swallow the animation). Revealing the right/bottom
    // means panning content the other way → negative offset.
    const AMP = 24; // px peak displacement
    const horiz = totalX >= totalY;
    const dx = horiz ? (hidden.right >= hidden.left ? -AMP : AMP) : 0;
    const dy = horiz ? 0 : (hidden.bottom >= hidden.top ? -AMP : AMP);
    const base = { ...this._pan };
    const DURATION = 540;
    const start = performance.now();
    const tick = (now) => {
      // A real gesture or a reset takes over — abandon and restore.
      if (this._panDrag || this._pinch || this._zoom <= 1) {
        this._nudgeRaf = null;
        return;
      }
      const t = Math.min(1, (now - start) / DURATION);
      const k = Math.sin(t * Math.PI); // 0 → 1 → 0: out and back to rest
      this._pan = clampPan(
        { x: base.x + dx * k, y: base.y + dy * k },
        this._zoom, cssW, cssH, imgSize,
      );
      this._lastDrawKey = null;
      this.requestUpdate();
      if (t < 1) {
        this._nudgeRaf = requestAnimationFrame(tick);
        return;
      }
      this._pan = base; // land exactly where we started
      this._nudgeRaf = null;
      this._lastDrawKey = null;
      this.requestUpdate();
    };
    this._nudgeRaf = requestAnimationFrame(tick);
  }

  // Desktop zoom + pan. Ctrl+wheel (also how browsers report trackpad pinch)
  // zooms toward the cursor so the point under the pointer stays put as the
  // map scales. Plain wheel (trackpad two-finger scroll) pans — but only once
  // zoomed in; at fit zoom it's left alone so scrolling the dashboard past
  // the map still works. Only preventDefault when we consume the gesture.
  _onWheelZoom(e) {
    if (!this._canvas) return;
    const imgSize = this._imgSize();
    if (!imgSize) return;
    const dpr = this._dpr || 1;
    const cssW = this._canvas.width / dpr;
    const cssH = this._canvas.height / dpr;
    if (!e.ctrlKey) {
      if (this._zoom <= 1) return;
      e.preventDefault();
      this._pan = dragPan(this._pan, -e.deltaX, -e.deltaY, this._zoom, cssW, cssH, imgSize);
      this._lastDrawKey = null;
      this.requestUpdate();
      return;
    }
    e.preventDefault();
    const rect = this._canvas.getBoundingClientRect();
    const focal = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    // Negative deltaY (scroll up / pinch out) zooms in. Rate tuned +30% per
    // user feedback that the original 0.0015 felt sluggish.
    const factor = Math.exp(-e.deltaY * 0.00195);
    const { zoom, pan } = zoomAtPoint(this._zoom, this._pan, this._zoom * factor, focal);
    const crossedIntoZoom = this._zoom <= 1 && zoom > 1;
    this._zoom = zoom;
    this._pan = clampPan(pan, zoom, cssW, cssH, imgSize);
    this._lastDrawKey = null;
    this.requestUpdate();
    // No pointers to wait on for a wheel/trackpad zoom — nudge as soon as it
    // crosses into zoom (the flag guards the once-per-session behaviour).
    if (crossedIntoZoom) this._triggerNudge();
  }

  _startZoneClean() {
    const r = this._zoneRect;
    if (!r) return;
    this.hass.callService("vacuum", "send_command", {
      entity_id: this._config.vacuum_entity,
      command: "app_zone_clean",
      params: { rect_px: [r.x0, r.y0, r.x1, r.y1] },
    });
    // Keep the drawn rect in place after starting so the user can see and
    // re-run what they selected, rather than resetting to the centered default.
  }

  _onCanvasClick(e) {
    // A pinch/pan gesture can end with a synthesized trailing click — swallow
    // exactly that one so it doesn't also toggle whatever room was underneath.
    if (this._gestured) {
      this._gestured = false;
      return;
    }
    if (this._zoneMode) return;
    if (!this.hass || !this._config) return;
    const vacState = this._vacState();
    const activity = vacState?.state;
    if (this._controlsLocked(activity)) return;
    const attr = vacState?.attributes;
    const roomMap = attr?.room_map;
    const imgSize = attr?.map_image_size;
    if (!roomMap || !imgSize) return;

    const cs = imgSize.cell_size || 1;
    const rect = this._canvas.getBoundingClientRect();
    const { px, py, snapCol, snapRow } = clientToImagePx(
      e.clientX, e.clientY, rect, imgSize, this._zoom, this._pan
    );

    if (!this._cellLookup || this._cellLookupAttr !== attr) {
      this._cellLookup = buildCellLookup(roomMap, cs);
      this._cellLookupAttr = attr;
    }

    const hitId = hitTestRooms(
      px, py, snapRow, snapCol, this._roomCheckboxHitAreas, this._cellLookup
    );
    if (hitId === undefined) return;

    // Same toggle path as the sheet's room chips and the room-list leaf — one
    // handler owns the selection/pending/service-call logic. The draw key
    // covers the selection sets, so the overlay redraws without forcing it.
    this._onRoomToggle({ detail: { roomId: hitId, on: !this._activeSelection().has(hitId) } });
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
          battIconClass: pct <= BATTERY_LOW_THRESHOLD ? "icon-low" : "",
        };
      }
    }
    return { battVisible: false };
  }

  _statTiles() {
    const areaState = this.hass.states[this._config.cleaning_area_entity];
    const timeState = this.hass.states[this._config.cleaning_time_entity];
    const occupied = isOccupied(this._vacState()?.state);
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
    const paused = this.hass.states[vacuumEntity]?.state === "paused";
    // A pure Pause→Resume must never re-dispatch the current selection as a fresh
    // clean (set_room_clean with non-empty room_ids restarts those rooms rather
    // than continuing — doc/PROTOCOL.md §5 documents only room_ids:[] as the
    // resume signal). Controls are locked while paused, so the selection can't
    // have changed since the clean started — vacuum.start's own paused-state
    // handling (async_start) is always the right call here. Stop also leaves the
    // robot paused, but there the intent is to abandon the cycle and start fresh,
    // so _stopped suppresses the resume short-circuit and falls through below.
    if (paused && !this._stopped) {
      this.hass.callService("vacuum", "start", { entity_id: vacuumEntity });
      return;
    }
    // Past the resume guard the button always dispatches a fresh clean; the Stop
    // intent is now consumed.
    const fromStop = this._stopped;
    this._stopped = false;
    // A drawn area takes precedence over room selection and whole-home. The
    // redirect lives here in the card; vacuum.start stays whole-home for
    // external callers (Apple Home/HAMH dispatch a parameterless vacuum.start).
    if (this._zoneRect) {
      this._startZoneClean();
      return;
    }
    let roomIds = [...this._selectedRooms].map((id) => parseInt(id, 10));
    // Whole-home after Stop can't be a bare vacuum.start: the robot is still
    // paused, where room_ids:[] resumes the abandoned clean rather than starting
    // a fresh whole-home. Expand to every known room so it dispatches as an
    // explicit fresh clean instead.
    if (roomIds.length === 0 && fromStop && paused) {
      const roomMap = this.hass.states[vacuumEntity]?.attributes?.room_map || {};
      roomIds = Object.keys(roomMap).map((id) => parseInt(id, 10));
    }
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
    // Pause in place — the cycle is resumable, so clear any prior Stop intent.
    this._stopped = false;
    this.hass.callService("vacuum", "pause", { entity_id: this._config.vacuum_entity });
  }

  _stop() {
    // The device has no true stop-in-place: vacuum.stop pauses the robot. Remember
    // the Stop intent so the card treats the resulting paused state as a finished
    // cycle (rooms editable, primary = Start) instead of a resumable pause.
    this._stopped = true;
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
    const derived = deriveCompanions(this._config.vacuum_entity);
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
