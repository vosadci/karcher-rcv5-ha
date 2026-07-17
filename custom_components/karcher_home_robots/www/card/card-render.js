import { html } from "../lit-core.js";
import { tr } from "./i18n.js";
import { MAP_MODE_ICON, VERSION } from "./constants.js";
import { buildDebugRows, NO_ROOMS_MESSAGE } from "./derive.js";
import { _CSS } from "./styles.js";

// Shell render template + clean-target sub-template (operate on the card element).

export function renderCard(el) {
    const v = el._view;
    if (v.notFound) {
      return html`
        <ha-card><hui-warning>${tr("Entity not available")}: ${v.vacuumEntity}</hui-warning></ha-card>`;
    }
    // Two derived axes over the unchanged tri-state cardMode: the floating map
    // control reads Rooms|Zone (Zone ⟺ Area), the sheet reads Standard|Customise.
    const mapMode = el._mapMode();
    const settingsMode = v.cardMode === "customise" ? "customise" : "standard";
    const sheetOpen = !!el._sheetOpen;
    const sheetTab = el._sheetTab || "target";
    const targetIcon = MAP_MODE_ICON[mapMode];
    return html`
      <style>${_CSS}</style>
      <ha-card class="card-shell" style=${el._config?.card_height
        ? `height:${el._config.card_height}px;min-height:${el._config.card_height}px`
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

        <ha-alert alert-type="error" class="rcv-region ${v.hasError ? "visible" : ""}">${v.errorText || tr("Robot reported a fault")}</ha-alert>

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
              @click=${(e) => el._onCanvasClick(e)}
              @pointerdown=${(e) => el._onMapPointerDown(e)}
              @pointermove=${(e) => el._onMapPointerMove(e)}
              @pointerup=${(e) => el._onMapPointerUp(e)}
              @pointercancel=${(e) => el._onMapPointerUp(e)}
              @wheel=${(e) => el._onWheelZoom(e)}></canvas>
            ${v.mapLoaded ? html`
              <div class="map-edge map-edge-l" style="opacity:${v.edgeFades.left}"></div>
              <div class="map-edge map-edge-r" style="opacity:${v.edgeFades.right}"></div>
              <div class="map-edge map-edge-t" style="opacity:${v.edgeFades.top}"></div>
              <div class="map-edge map-edge-b" style="opacity:${v.edgeFades.bottom}"></div>` : ""}
          </div>
          <karcher-map-mode class="map-mode" .mode=${mapMode} .locked=${v.controlsLocked}
            @karcher-map-mode=${(e) => el._onMapMode(e)}></karcher-map-mode>
          ${v.mapZoomed && v.mapLoaded ? html`
            <button class="map-reset" title=${tr("Reset zoom")}
              @click=${() => el._resetZoom()}>
              <ha-icon icon="mdi:fit-to-screen"></ha-icon>
              <span>${tr("Reset")}</span>
            </button>` : ""}
        </div>

        <div class="map-hint ${v.mapLoaded ? "" : "hint-hidden"} ${mapMode !== "zone" && v.controlsLocked ? "hint-locked" : ""}">
          <ha-icon icon=${targetIcon}></ha-icon>
          <span>${mapMode === "zone"
            ? (v.zoneRect
              ? tr("Drag to move, corners to resize · press Start to clean.")
              : tr("Drag to draw an area · press Start to clean it."))
            : tr("Tap rooms to select. Empty = whole home.")}</span>
        </div>

        <button class="target-strip rcv-region" ?disabled=${v.controlsLocked}
          @click=${() => el._openSheet()}>
          <ha-icon icon=${targetIcon}></ha-icon>
          <span class="target-strip-label">${v.targetLabel || ""}</span>
          <span class="target-strip-edit">${tr("Edit")}</span>
          <ha-icon class="target-strip-chevron" icon="mdi:chevron-up"></ha-icon>
        </button>

        <div class="action-bar rcv-region">
          <karcher-button-row class="buttons" .activity=${v.activity} .offline=${!!v.offline}
            .playLabel=${v.primaryLabel} .playDisabled=${v.playDisabled}
            @karcher-action=${(e) => el._onButtonAction(e)}></karcher-button-row>
        </div>

        <div class="sheet-scrim ${sheetOpen ? "open" : ""}" @click=${() => el._closeSheet()}></div>
        <div class="sheet ${sheetOpen ? "open" : ""}" role="dialog" aria-label=${tr("Cleaning options")} aria-hidden=${!sheetOpen}>
          <div class="sheet-handle"><span></span></div>
          <div class="sheet-tabs">
            <button class="sheet-tab ${sheetTab === "target" ? "active" : ""}"
              @click=${() => el._setSheetTab("target")}>${tr("What gets cleaned")}</button>
            <button class="sheet-tab ${sheetTab === "settings" ? "active" : ""}"
              @click=${() => el._setSheetTab("settings")}>${tr("Settings")}</button>
          </div>
          <div class="sheet-body">
            <div class="sheet-panel ${sheetTab === "target" ? "active" : ""}">
              ${el._renderCleanTarget(v, mapMode)}
              <karcher-stats-row class="stats-line" .tiles=${v.tiles || []}></karcher-stats-row>
              <div class="legend ${v.legend && v.legend.length ? "" : "legend-hidden"}">
                <div class="legend-items">
                  ${(v.legend || []).map((it) => html`
                    <span class="legend-chip">
                      ${it.kind === "icon"
                        ? html`<svg class="legend-sw legend-icon-sw" viewBox="0 0 24 24"><circle cx="12" cy="12" r=${it.discR} fill=${it.color} stroke="rgba(255,255,255,0.92)" stroke-width=${it.rimWidth}></circle><path d=${it.d} fill="#fff" transform=${`translate(${it.glyphOffset} ${it.glyphOffset}) scale(${it.glyphScale})`}></path></svg>`
                        : html`<span class="legend-sw legend-${it.kind} ${it.ring ? "legend-ring" : ""}"
                            style=${it.kind === "swatch"
                              ? `background:${it.fill};border-color:${it.color}`
                              : it.ringColor
                                ? `background:${it.color};border-color:${it.ringColor}`
                                : `background:${it.color}`}></span>`}
                      <span class="legend-label">${tr(it.label)}${it.count > 1 ? ` ×${it.count}` : ""}</span>
                    </span>`)}
                </div>
              </div>
            </div>

            <div class="sheet-panel ${sheetTab === "settings" ? "active" : ""}">
              ${v.controlsLocked ? html`
                <div class="busy-banner">
                  <ha-icon icon="mdi:lock"></ha-icon>
                  <span>${tr("Locked while cleaning — pause to change settings")}</span>
                </div>` : null}
              <div class="settings-lockable ${v.controlsLocked ? "busy" : ""}">
                <div class="tab-row">
                  <div class="segmented" style="width:auto"
                    role="group" aria-label=${tr("Cleaning settings mode")}>
                    <button class="seg-btn ${settingsMode === "standard" ? "active" : ""}"
                      aria-pressed=${settingsMode === "standard"} ?disabled=${v.controlsLocked}
                      @click=${() => el._setCardMode("standard")}>${tr("Standard")}</button>
                    <button class="seg-btn ${settingsMode === "customise" ? "active" : ""}"
                      aria-pressed=${settingsMode === "customise"} ?disabled=${v.controlsLocked}
                      @click=${() => el._setCardMode("customise")}>${tr("Customise")}</button>
                  </div>
                  <span class="tab-helper">${v.tabHelper || tr("Applies to all rooms")}</span>
                </div>
                <karcher-selector-rows class="standard-settings"
                  style=${settingsMode === "standard" ? "" : "display:none"}
                  .rows=${v.selectorRows || []}
                  @karcher-select=${(e) => el._onSelectorChange(e)}></karcher-selector-rows>
                <div class="area-note" style=${v.cardMode === "area" ? "" : "display:none"}>
                  <ha-icon icon="mdi:map-marker-radius"></ha-icon>
                  <span>${tr("Select the area to clean on the map.")}</span>
                </div>
                <karcher-room-list class="room-list ${v.zoneActive ? "zone-locked" : ""}"
                  style=${settingsMode === "customise" ? "" : "display:none"}
                  .rows=${v.roomRows || []} .busy=${v.controlsLocked || v.zoneActive}
                  @room-toggle=${(e) => el._onRoomToggle(e)}
                  @room-expand=${(e) => el._onRoomExpand(e)}
                  @room-reorder=${(e) => el._onRoomReorder(e)}
                  @room-pref=${(e) => el._onRoomPref(e)}></karcher-room-list>
              </div>
            </div>
          </div>
        </div>

        ${el._config?.show_debug && el.hass ? html`
          <div class="rcv-debug rcv-region">
            ${buildDebugRows({ version: VERSION, hass: el.hass, config: el._config,
              vacState: el._vacState(), imgSize: el._imgSize(),
              mapLoaded: el._mapLoaded, offline: el._isOffline() })
              .map((r) => html`<span class="rcv-debug-item"><b>${r.label}</b> ${r.value}</span>`)}
          </div>` : null}
      </ha-card>`;
  }

export function renderCleanTarget(el, v, mapMode) {
    if (mapMode === "zone") {
      return html`
        <div class="zone-summary">
          <ha-icon icon=${MAP_MODE_ICON.zone}></ha-icon>
          <span>${v.zoneRect ? tr("Area selected — ready to clean") : tr("No area yet — draw one on the map")}</span>
        </div>`;
    }
    const rooms = v.cleanTargetRooms || [];
    if (rooms.length === 0) {
      return html`<div class="zone-summary"><ha-icon icon="mdi:home-outline"></ha-icon>
        <span>${tr(NO_ROOMS_MESSAGE)}</span></div>`;
    }
    return html`
      <div class="whole-home-banner">
        <ha-icon icon="mdi:home-outline"></ha-icon>
        <span>${v.targetLabel}</span>
      </div>
      <div class="room-chips">
        ${rooms.map((r) => html`
          <button class="room-chip ${r.enabled ? "on" : ""}" ?disabled=${v.controlsLocked}
            @click=${() => el._onRoomToggle({ detail: { roomId: r.id, on: !r.enabled } })}>
            <span class="room-chip-check">${r.enabled ? html`<ha-icon icon="mdi:check"></ha-icon>` : null}</span>
            <span>${r.name}</span>
            ${r.area != null ? html`<span class="room-chip-area">${r.area} m²</span>` : null}
          </button>`)}
      </div>`;
  }
