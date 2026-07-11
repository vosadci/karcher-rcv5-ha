import { tr, setLang, STATUS_SLUG_LABELS, STATE_LABELS, countLabels } from "./i18n.js";
import {
  isOccupied, isBusy, isUsableValue, isUsableState, batteryIcon, BATTERY_LOW_THRESHOLD,
  primaryCleanLabel, targetStripLabel, deriveStatTiles, deriveSelectorRows, deriveRoomRows,
  parseRoomOrder, reconcileCustomise,
} from "./derive.js";
import { panEdgeHidden, EDGE_FADE_RAMP_PX } from "./geometry.js";
import { legendItems } from "./map-draw.js";

// View derivation: build el._view from hass/config (operate on the card element).

export function willUpdateCard(el) {
    if (!el.hass || !el._config) return;
    setLang(el.hass);
    if (el._pendingPrefRefresh) {
      el._pendingPrefRefresh = false;
      el._refreshPreferences();
    }
    const vacState = el._vacState();
    if (!vacState) {
      el._view = { notFound: true, vacuumEntity: el._config.vacuum_entity };
      return;
    }

    const attr = vacState.attributes;
    const activity = vacState.state;

    if (el._pendingPreferMode) {
      // An optimistic switch is in flight: only the matching echo can resolve
      // it. Any other poll (including a stale pre-click value still in
      // transit) is ignored outright — applying it would knock the
      // optimistic tab back before the real echo ever arrives (e.g.
      // Customise -> Area: a "customise" poll racing the "standard" echo).
      if (attr?.prefer_mode === el._pendingPreferMode) {
        el._lastPreferMode = attr.prefer_mode;
        el._applyMode(el._pendingCardMode);
        el._pendingPreferMode = null;
        el._pendingCardMode = null;
      }
    } else if (
      attr?.prefer_mode && attr.prefer_mode !== el._lastPreferMode && !isOccupied(activity)
    ) {
      // Defer a reactive (non-optimistic) prefer_mode echo while a clean is in
      // progress: a room-only Standard clean can make the robot push a
      // custom_type change mid-run, which would otherwise flip _cardMode to
      // "customise" and silently swap the target-strip selection out from
      // under the active run. Controls are locked while occupied anyway, so
      // picking el up once the run ends to resting is no real loss.
      el._lastPreferMode = attr.prefer_mode;
      el._applyMode(attr.prefer_mode);
    }
    // Clear the room selection only when a run truly ends (occupied → resting),
    // never when merely pausing — pausing keeps the selection so a resume (and
    // the map/list highlight) carries through. isOccupied covers cleaning,
    // paused and returning, so cleaning⇄paused stays selected and the set only
    // clears on the drop to idle/docked/error.
    if (isOccupied(el._prevActivity) && !isOccupied(activity)) {
      el._selectedRooms.clear();
    }
    // Reload recovery: a card mounted mid-clean has no in-memory selection, so the
    // map highlight and target note would wrongly read "whole home". Re-seed from
    // the backend's active-clean room set (empty there genuinely means whole-home).
    // Skip while _stopped — there the user is re-selecting rooms for a new clean.
    if (
      isOccupied(activity) && !el._stopped && el._selectedRooms.size === 0 &&
      Array.isArray(attr?.active_clean_room_ids) && attr.active_clean_room_ids.length
    ) {
      for (const id of attr.active_clean_room_ids) el._selectedRooms.add(String(id));
    }
    // The Stop intent is spent once the robot leaves the paused state it created
    // (a fresh clean began, or it docked/idled). The prevActivity===paused guard
    // avoids wiping the flag during the brief cleaning→paused settle right after
    // Stop is pressed, when the robot is still reported as cleaning.
    if (el._stopped && (!isOccupied(activity) || el._prevActivity === "paused")) {
      el._stopped = false;
    }
    el._prevActivity = activity;

    // Reconcile optimistic customise state before deriving the view (the derived
    // room rows + header count + map overlay all read _customiseSelected).
    el._reconcileCustomise(attr);

    el._view = el._deriveView(attr, activity);
  }

// Status text + dot/label classes for the top-bar. Offline and a user Stop
// (technically paused, but presented as resting to match the unlocked controls
// and "Start" button) are special-cased; otherwise the vacuum's status_label
// slug (e.g. "locating") maps to an English source key, then translates,
// falling back to the activity label.
function deriveStatus(el, attr, activity, isOffline) {
    if (isOffline) {
      return { statusText: tr("Offline"), dotClass: "dot-offline", labelClass: "label-offline" };
    }
    if (el._stopped && activity === "paused") {
      return { statusText: tr("Stopped"), dotClass: "dot-idle", labelClass: "label-idle" };
    }
    const slugLabel = attr.status_label ? (STATUS_SLUG_LABELS[attr.status_label] || attr.status_label) : null;
    let statusText = tr(slugLabel || STATE_LABELS[activity] || activity);
    const roomEntity = el._config.current_room_entity;
    if (activity === "cleaning" && roomEntity) {
      const r = el.hass.states[roomEntity]?.state;
      if (isUsableValue(r)) statusText += ` · ${r}`;
    }
    const [dotClass, labelClass] = attr.status_label === "locating"
      ? ["dot-returning", "label-locating"]
      : [`dot-${activity}`, `label-${activity}`];
    return { statusText, dotClass, labelClass };
  }

// fault_code sensor's state is the translation slug (e.g. "place_on_dock");
// formatEntityState resolves it to the curated text already shipped in
// translations/en.json. Falls back to the raw slug if unavailable (older
// frontend), or the generic message if no fault is set.
function deriveErrorText(el, hasError) {
    const faultState = el.hass.states[el._resolveFaultEntity()];
    if (!(hasError && faultState && isUsableValue(faultState.state) && faultState.state !== "none")) {
      return "Robot reported a fault";
    }
    return typeof el.hass.formatEntityState === "function"
      ? el.hass.formatEntityState(faultState)
      : faultState.state;
  }

export function deriveView(el, attr, activity) {
    const cfg = el._config;
    const isOffline = el._isOffline();
    const { statusText, dotClass, labelClass } = deriveStatus(el, attr, activity, isOffline);
    const errEntity = cfg.error_entity;
    const hasError = activity === "error" ||
      (errEntity && el.hass.states[errEntity]?.state === "on");
    const errorText = deriveErrorText(el, hasError);

    return {
      ...el._batteryView(),
      ...el._mapPlaceholderView(attr),
      legend: legendItems(attr),
      name: attr.friendly_name || "Kärcher RCV5",
      statusText, dotClass, labelClass,
      pinging: !isOffline && isBusy(activity),
      hasError: !!hasError,
      errorText,
      activity,
      offline: !!isOffline,
      cardMode: el._cardMode,
      controlsLocked: el._controlsLocked(activity),
      tiles: el._statTiles(),
      selectorRows: el._selectorRows(attr),
      tabHelper: el._tabHelperText(attr),
      // Context-aware primary label for a resting robot; null while occupied so
      // the button row falls back to Pause/Resume. A Stop→paused robot counts as
      // resting here, so its primary button reads "Start" (a fresh clean), not
      // "Resume".
      primaryLabel: el._restingForUx(activity)
        ? primaryCleanLabel(el._mapMode(), el._activeSelection().size, !!el._zoneRect)
        : null,
      // Area mode with no drawn rect yet: nothing to clean, so disable Start
      // (but only while resting — once occupied the row falls back to Pause/Resume).
      playDisabled: el._cardMode === "area" && !el._zoneRect && el._restingForUx(activity),
      roomRows: el._roomListRows(attr),
      targetLabel: el._targetLabel(attr),
      cleanTargetRooms: el._cleanTargetRooms(attr),
      mapLoaded: el._mapLoaded,
      zoneMode: el._zoneMode,
      zoneRect: el._zoneRect,
      zoneActive: el._zoneMode || !!el._zoneRect,
      mapZoomed: el._zoom > 1,
      edgeFades: el._edgeFades(),
    };
  }

export function edgeFades(el) {
    const zero = { left: 0, right: 0, top: 0, bottom: 0 };
    if (el._zoom <= 1 || !el._canvas) return zero;
    const dpr = el._dpr || 1;
    const cssW = el._canvas.width / dpr;
    const cssH = el._canvas.height / dpr;
    if (!cssW || !cssH) return zero;
    const hidden = panEdgeHidden(el._pan, el._zoom, cssW, cssH, el._imgSize());
    const ramp = (px) => Math.min(1, px / EDGE_FADE_RAMP_PX);
    return {
      left: ramp(hidden.left), right: ramp(hidden.right),
      top: ramp(hidden.top), bottom: ramp(hidden.bottom),
    };
  }

export function mapPlaceholderView(el, attr) {
    const mapEntity = el._config.map_entity;
    if (!mapEntity) return { placeholderText: tr("Set map_entity in card config") };
    if (!el.hass.states[mapEntity]) return { placeholderText: `${tr("Entity not found")}: ${mapEntity}` };
    const sz = attr.map_image_size;
    const out = {
      mapLoading: el._mapPending,
      mapLoaded: el._mapLoaded,
      aspectRatio: sz ? `${sz.width} / ${sz.height}` : "",
    };
    if (el._mapError) out.placeholderText = tr("Map unavailable");
    else if (sz) out.placeholderText = "";
    else out.placeholderText = tr("No map yet — start a cleaning run to generate one.");
    return out;
  }

export function batteryView(el) {
    const battEntity = el._config.battery_entity;
    if (battEntity) {
      const b = el.hass.states[battEntity];
      if (isUsableState(b)) {
        const pct = parseInt(b.state, 10);
        const chargingEntity = el._config.charging_entity;
        const isCharging = chargingEntity
          ? el.hass.states[chargingEntity]?.state === "on" : false;
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

export function statTiles(el) {
    const areaState = el.hass.states[el._config.cleaning_area_entity];
    const timeState = el.hass.states[el._config.cleaning_time_entity];
    const occupied = isOccupied(el._vacState()?.state);
    return deriveStatTiles(areaState, timeState, occupied);
  }

export function selectorRows(el, attr) {
    if (el._cardMode === "customise") return [];
    const modeEntityId = el._config.cleaning_mode_entity;
    const modeState = modeEntityId ? el.hass.states[modeEntityId] : null;
    const waterEntityId = el._config.water_level_entity;
    // undefined (not null) when no entity configured → deriveSelectorRows omits
    // the water row; a configured-but-missing entity yields a disabled row.
    const waterState = waterEntityId ? (el.hass.states[waterEntityId] ?? null) : undefined;
    const rows = deriveSelectorRows(attr, modeState, waterState);
    // Offline: the service call can't reach the robot — disable every row.
    if (el._isOffline()) for (const r of rows) r.disabled = true;
    return rows;
  }

export function tabHelperText(el, attr) {
    if (el._cardMode === "area") {
      return el._zoneRect ? tr("Cleans the selected area") : tr("Draw an area on the map");
    }
    if (el._cardMode !== "customise") {
      return tr("Applies to all rooms");
    }
    const roomMap = attr?.room_map || {};
    const roomIds = parseRoomOrder(roomMap, attr?.room_preferences || {});
    const total = Object.keys(roomMap).length;
    const enabled = roomIds.filter((id) => el._customiseSelected.has(id)).length;
    return countLabels().roomsOn(enabled, total);
  }

export function roomListRows(el, attr) {
    const roomMap = attr?.room_map || {};
    const prefs = attr?.room_preferences || {};
    if (el._cardMode === "customise") {
      return deriveRoomRows(roomMap, prefs, el._customiseSelected, el._detailRoomId);
    }
    // Standard mode: same enable/disable selection the map clicks toggle
    // (_selectedRooms) — no expand/detail, so detailRoomId is always null.
    return deriveRoomRows(roomMap, prefs, el._selectedRooms, null);
  }

export function targetLabel(el, attr) {
    const roomMap = attr?.room_map || {};
    return targetStripLabel(
      el._mapMode(), el._activeSelection(), !!el._zoneRect,
      (id) => roomMap[id]?.name || id,
    );
  }

export function cleanTargetRooms(el, attr) {
    const roomMap = attr?.room_map || {};
    return el._roomListRows(attr).map((r) => ({
      id: r.id,
      name: r.name,
      enabled: r.enabled,
      area: roomMap[r.id]?.area_m2 ?? null,
    }));
  }

export function viewState(el, attr) {
    const activity = el._vacState()?.state;
    // Area box: the live local selection while editing, else the backend's active
    // zone rect during a running zone clean. The fallback survives a card reload
    // (in-memory _zoneRect is gone) because the coordinator mirrors the sent rect,
    // exactly as active_clean_room_ids backs the room highlight. It's display-only —
    // gestures read el._zoneRect (still null), so there's nothing to drag.
    let zoneRect = el._zoneRect;
    if (!zoneRect && isOccupied(activity) && !el._stopped) {
      const z = attr?.active_clean_zone_px;
      if (Array.isArray(z) && z.length === 4) {
        zoneRect = { x0: z[0], y0: z[1], x1: z[2], y1: z[3] };
      }
    }
    return {
      attr,
      dpr: el._dpr || 1,
      mapImg: el._mapImg,
      robotIcon: el._robotIcon,
      cardMode: el._cardMode,
      detailRoomId: el._detailRoomId,
      selectedRooms: el._selectedRooms,
      customiseSelected: el._customiseSelected,
      mapToken: el._mapToken,
      canvasWidth: el._canvas.width,
      canvasHeight: el._canvas.height,
      zoneRect,
      zoneEditable: !el._controlsLocked(activity),
      zoom: el._zoom,
      pan: el._pan,
    };
  }

export function resolveFaultEntity(el) {
    const cfgId = el._config?.fault_code_entity;
    if (cfgId && el.hass?.states[cfgId]) return cfgId;
    const vac = el._config?.vacuum_entity;
    const deviceId = el.hass?.entities?.[vac]?.device_id;
    if (deviceId) {
      for (const [entityId, entry] of Object.entries(el.hass.entities)) {
        if (entry.device_id === deviceId && entry.translation_key === "fault_code") {
          return entityId;
        }
      }
    }
    return cfgId;
  }

export function reconcileCustomiseView(el, attr) {
    if (el._cardMode !== "customise") return;
    const prefs = attr?.room_preferences || {};
    const roomIds = parseRoomOrder(attr?.room_map || {}, prefs);
    const r = reconcileCustomise(roomIds, prefs, el._customisePending, el._customiseSelected);
    el._customiseSelected = r.selected;
    el._customisePending = r.pending;
  }
