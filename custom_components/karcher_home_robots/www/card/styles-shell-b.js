export const CSS_B = `

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

  /* ── opt-in debug footer (show_debug) ── */
  .rcv-debug {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 12px;
    padding: 6px 12px;
    border-top: 1px solid var(--rcv-divider);
    background: var(--rcv-inset);
    color: var(--rcv-text3);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .rcv-debug-item b { color: var(--rcv-text2); font-weight: 600; }

 `;
