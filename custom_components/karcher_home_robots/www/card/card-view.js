import { tr, setLang, STATUS_SLUG_LABELS, STATE_LABELS, countLabels } from "./i18n.js";
import {
  _EDITOR_COMPANIONS, isOccupied, isBusy, isUsableValue, isUsableState, batteryIcon, BATTERY_LOW_THRESHOLD,
  primaryCleanLabel, targetStripLabel, deriveStatTiles, deriveSelectorRows, deriveRoomRows,
  parseRoomOrder, reconcileCustomise,
} from "./derive.js";
import { panEdgeHidden, EDGE_FADE_RAMP_PX } from "./geometry.js";
import { legendItems } from "./map-draw.js";
import { isHaStyle } from "./constants.js";
import { canvasCssDims } from "./card-gestures.js";

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
// falling back to the activity label. Wash-station phases come from the station
// status sensor, not status_label: the Live Activity blueprint clears on any
// docked label but "emptying", and the sensor already holds the mid-drying blip.
const WASH_PHASES = new Set(["self_cleaning", "drying"]);
function washPhase(el, activity) {
    if (activity !== "docked" && activity !== "idle") return null;
    const phase = el.hass.states[companionEntity(el, "station_status_entity")]?.state;
    return WASH_PHASES.has(phase) ? phase : null;
  }

function deriveStatus(el, attr, activity, isOffline) {
    if (isOffline) {
      return { statusText: tr("Offline"), dotClass: "dot-offline", labelClass: "label-offline" };
    }
    if (el._stopped && activity === "paused") {
      return { statusText: tr("Stopped"), dotClass: "dot-idle", labelClass: "label-idle" };
    }
    const slug = attr.status_label || washPhase(el, activity);
    const slugLabel = slug ? (STATUS_SLUG_LABELS[slug] || slug) : null;
    let statusText = tr(slugLabel || STATE_LABELS[activity] || activity);
    const roomEntity = companionEntity(el, "current_room_entity");
    if (activity === "cleaning" && roomEntity) {
      const r = el.hass.states[roomEntity]?.state;
      if (isUsableValue(r)) statusText += ` · ${r}`;
    }
    const [dotClass, labelClass] =
      attr.status_label === "locating" ? ["dot-returning", "label-locating"]
      : attr.status_label === "emptying" ? ["dot-returning", "label-emptying"]
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
    const isOffline = el._isOffline();
    const { statusText, dotClass, labelClass } = deriveStatus(el, attr, activity, isOffline);
    const errEntity = companionEntity(el, "error_entity");
    const hasError = activity === "error" ||
      (errEntity && el.hass.states[errEntity]?.state === "on");
    const errorText = deriveErrorText(el, hasError);
    // Visibility is gated on the (near-permanent) presence of a Suction
    // Station, not on the button's own transient availability — a robot
    // with no station should never show a permanently-disabled button, but
    // one docked without a station attached right now should still see it
    // (greyed) rather than have it pop in and out as it docks/undocks.
    const stationAttachedEntity = el._resolveStationAttachedEntity();
    const showEmptyStation = el.hass.states[stationAttachedEntity]?.state === "on";
    // Button state is the last-press timestamp once pressed, "unknown" (not an
    // error) before the first press, and "unavailable" only when the backend
    // entity's own guard (docked + station attached) says no — so "unknown"
    // must read as enabled, unlike isUsableState's binary_sensor/select usage.
    const emptyStationEntity = el._resolveEmptyStationEntity();
    const emptyStationState = emptyStationEntity
      ? el.hass.states[emptyStationEntity] : undefined;
    const emptyStationEnabled = !isOffline && !!emptyStationState &&
      emptyStationState.state !== "unavailable";
    // Derive the room rows once — both the list and the clean-target summary need them.
    const roomRows = el._roomListRows(attr);

    return {
      ...el._batteryView(),
      ...el._mapPlaceholderView(attr),
      legend: legendItems(attr),
      name: attr.friendly_name || "Kärcher Vacuum",
      statusText, dotClass, labelClass,
      pinging: !isOffline && isBusy(activity),
      hasError: !!hasError,
      errorText,
      activity,
      offline: !!isOffline,
      showEmptyStation,
      emptyStationEnabled,
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
        ? primaryCleanLabel(el._mapMode(), el._activeSelection().size, !!el._zoneRect, roomRows.length)
        : null,
      // Area mode with no drawn rect yet: nothing to clean, so disable Start
      // (but only while resting — once occupied the row falls back to Pause/Resume).
      playDisabled: el._cardMode === "area" && !el._zoneRect && el._restingForUx(activity),
      roomRows,
      targetLabel: el._targetLabel(attr),
      cleanTargetRooms: cleanTargetRooms(attr, roomRows),
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
    const { cssW, cssH } = canvasCssDims(el);
    if (!cssW || !cssH) return zero;
    const hidden = panEdgeHidden(el._pan, el._zoom, cssW, cssH, el._imgSize());
    const ramp = (px) => Math.min(1, px / EDGE_FADE_RAMP_PX);
    return {
      left: ramp(hidden.left), right: ramp(hidden.right),
      top: ramp(hidden.top), bottom: ramp(hidden.bottom),
    };
  }

export function mapPlaceholderView(el, attr) {
    const mapEntity = companionEntity(el, "map_entity");
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
    const battEntity = companionEntity(el, "battery_entity");
    if (battEntity) {
      const b = el.hass.states[battEntity];
      const pct = isUsableState(b) ? parseInt(b.state, 10) : NaN;
      // isUsableState only rules out unknown/unavailable, not a non-numeric state.
      // The editor's advanced overrides accept any entity, so battery_entity can
      // legitimately point at something that does not parse — which rendered a
      // literal "NaN%" next to a wrongly-chosen icon (batteryIcon's comparisons
      // are all false for NaN, so it fell through to "low"). deriveStatTiles
      // already guards its own parse this way; match it and hide the readout.
      if (!isNaN(pct)) {
        const chargingEntity = companionEntity(el, "charging_entity");
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
    const areaState = el.hass.states[companionEntity(el, "cleaning_area_entity")];
    const timeState = el.hass.states[companionEntity(el, "cleaning_time_entity")];
    const occupied = isOccupied(el._vacState()?.state);
    return deriveStatTiles(areaState, timeState, occupied);
  }

export function selectorRows(el, attr) {
    if (el._cardMode === "customise") return [];
    const modeEntityId = companionEntity(el, "cleaning_mode_entity");
    const modeState = modeEntityId ? el.hass.states[modeEntityId] : null;
    const waterEntityId = companionEntity(el, "water_level_entity");
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

export function cleanTargetRooms(attr, rows) {
    const roomMap = attr?.room_map || {};
    return rows.map((r) => ({
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
    const haStyle = isHaStyle(el._config);
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
      haStyle,
      accentRgb: haStyle ? themeAccentRgb(el) : "",
    };
  }

// The theme's primary colour as "r, g, b" for canvas paint (see map-draw.js).
// getComputedStyle is too costly per reveal frame, so it is re-read only when
// HA hands over a new themes object, dark-mode flag or selected theme. An empty
// result (theme not applied yet) is not cached, so the next frame retries.
function themeAccentRgb(el) {
    const themes = el.hass?.themes;
    const dark = themes?.darkMode;
    const selected = el.hass?.selectedTheme?.theme;
    const c = el._accentCache;
    if (c && c.themes === themes && c.dark === dark && c.selected === selected) return c.rgb;
    let rgb;
    try {
      rgb = getComputedStyle(el).getPropertyValue("--rgb-primary-color").trim();
    } catch {
      rgb = "";
    }
    if (rgb) el._accentCache = { themes, dark, selected, rgb };
    return rgb;
  }

// Resolve a companion entity_id, tolerating a wrong derived/configured guess.
// deriveCompanions() guesses `<domain>.<vacuum_entity_stem>_<suffix>`, which is
// only correct if the stem HA actually assigned to every entity on this device
// matches the vacuum entity's own stem — true in the common case, but not
// guaranteed (renames, disambiguation suffixes, entities registered before a
// translation_key existed). When the guess doesn't resolve to a live state,
// fall back to a registry scan by device_id + translation_key (mirrors
// vacuum.py's _pref_entity_map) — authoritative, independent of any guessed
// string shape. A configured id missing from hass.states is treated like a
// guess, so it too falls through to the registry. Falls back to the guess itself if that also finds nothing
// (status quo — the caller's own not-found handling takes over).
export function resolveCompanionEntity(el, cfgKey, translationKey) {
    const cfgId = el._config?.[cfgKey];
    if (cfgId && el.hass?.states[cfgId]) return cfgId;
    const entities = el.hass?.entities;
    const deviceId = entities?.[el._config?.vacuum_entity]?.device_id;
    if (!deviceId || !translationKey) return cfgId;
    // The registry scan runs on every hass update for every companion, so cache
    // per registry object: HA replaces hass.entities whenever it changes.
    if (el._companionCache?.entities !== entities || el._companionCache?.deviceId !== deviceId) {
      el._companionCache = { entities, deviceId, byKey: new Map() };
    }
    const cache = el._companionCache.byKey;
    if (!cache.has(translationKey)) {
      let found = null;
      for (const [entityId, entry] of Object.entries(entities)) {
        if (entry.device_id === deviceId && entry.translation_key === translationKey) {
          found = entityId;
          break;
        }
      }
      cache.set(translationKey, found);
    }
    return cache.get(translationKey) ?? cfgId;
  }

// Live entity_id for any companion config key (battery_entity, map_entity, ...).
// The derived `<domain>.<stem>_<suffix>` default is only a guess: the vacuum
// entity is named ("…_vacuum"), so on current installs the stem carries that
// suffix and every derived companion id was wrong — the map, battery, stats and
// selectors all silently resolved to entities that do not exist.
const _TK_BY_KEY = Object.fromEntries(_EDITOR_COMPANIONS.map((c) => [c.key, c.tk]));
export function companionEntity(el, cfgKey) {
    return resolveCompanionEntity(el, cfgKey, _TK_BY_KEY[cfgKey]);
  }

export function resolveFaultEntity(el) {
    return resolveCompanionEntity(el, "fault_code_entity", "fault_code");
  }

export function resolveStationAttachedEntity(el) {
    return resolveCompanionEntity(el, "station_attached_entity", "station_attached");
  }

export function resolveEmptyStationEntity(el) {
    return resolveCompanionEntity(el, "empty_station_entity", "empty_station");
  }

export function reconcileCustomiseView(el, attr) {
    if (el._cardMode !== "customise") return;
    const prefs = attr?.room_preferences || {};
    const roomIds = parseRoomOrder(attr?.room_map || {}, prefs);
    const r = reconcileCustomise(roomIds, prefs, el._customisePending, el._customiseSelected);
    el._customiseSelected = r.selected;
    el._customisePending = r.pending;
  }
