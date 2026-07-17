export const CSS_A = `
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
  .map-edge-l { top: 0; bottom: 0; left: 0; width: 5%;
    background: linear-gradient(to right, rgba(0,0,0,0.18), transparent); }
  .map-edge-r { top: 0; bottom: 0; right: 0; width: 5%;
    background: linear-gradient(to left, rgba(0,0,0,0.18), transparent); }
  .map-edge-t { left: 0; right: 0; top: 0; height: 5%;
    background: linear-gradient(to bottom, rgba(0,0,0,0.18), transparent); }
  .map-edge-b { left: 0; right: 0; bottom: 0; height: 5%;
    background: linear-gradient(to top, rgba(0,0,0,0.18), transparent); }
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
  /* Frosted glass over the (always-white) map render, shared by both floating
     map controls so they read as one family: tinted from the card's own surface
     colour, so it reads as light glass/dark text in light theme and dark
     glass/light text in dark theme, instead of staying a dark blob. */
  .map-mode-inner, .map-reset {
    background: color-mix(in srgb, var(--rcv-card) 78%, transparent);
    -webkit-backdrop-filter: blur(10px);
    backdrop-filter: blur(10px);
    border: 1px solid color-mix(in srgb, var(--rcv-text) 14%, transparent);
    box-shadow: 0 6px 20px rgba(0,0,0,0.22);
  }
  .map-mode-inner {
    display: flex;
    gap: 3px;
    padding: 4px;
    border-radius: 13px;
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
  .legend-icon-sw { width: 14px; height: 14px; display: block; }
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
  }`;
