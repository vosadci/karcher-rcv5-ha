import { html } from "../lit-core.js";
import { tr, countLabels, CLEANING_MODE_LABELS } from "./i18n.js";

// Pure derivation of stat tiles, selector rows, room rows, labels, predicates.
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
export const NO_ROOMS_MESSAGE = "No rooms found — load a map first";

export const _EDITOR_COMPANIONS = [
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

// Curated diagnostics rows for the opt-in debug footer. Pure and whitelist-only:
// this is the security boundary — never dump raw attributes, device_id, serial,
// tokens, or MQTT payloads here (CLAUDE.md SEC constraint). Returns ordered
// [{ label, value }]; missing inputs collapse to "—".
export function buildDebugRows({ version, hass, config, vacState, imgSize, mapLoaded, offline }) {
  const dash = "—";
  let updated = dash;
  if (vacState?.last_updated) {
    const d = new Date(vacState.last_updated);
    if (!isNaN(d)) updated = d.toLocaleTimeString();
  }
  const map = mapLoaded
    ? (imgSize?.width && imgSize?.height ? `${imgSize.width}×${imgSize.height}` : "loaded")
    : "—";
  return [
    { label: "card", value: version || dash },
    { label: "HA", value: hass?.config?.version || dash },
    { label: "entity", value: config?.vacuum_entity || dash },
    { label: "state", value: vacState?.state || dash },
    { label: "map", value: map },
    { label: "conn", value: offline ? "offline" : "online" },
    { label: "updated", value: updated },
  ];
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
export function roomSummaryParts(parts) {
  return (parts || []).flatMap((p, i) => [
    i ? html`<span class="room-summary-sep">·</span>` : "",
    p.icon
      ? html`<ha-icon class="room-summary-icon" icon=${p.icon} title=${tr(p.label)} aria-label=${tr(p.label)}></ha-icon>`
      : html`<span>${tr(p.text)}</span>`,
  ]);
}

// Shared segmented-control row template — one Mode/Suction/Water/etc. field row.
// Used by both the standard-mode selector leaf and the per-room detail panel.
// Presentational only: callers own their optimistic-highlight state (compute
// `active`) and pass a unique `idBase` (aria), the `compact` decision, and an
// `onSelect(opt, optDisabled)` handler. Per-button disable is the general form
// `rowDisabled || opt.disabled` so per-option flags (mode disabled_options,
// suction fan_speed filtering) and whole-row gating both work.
export function segmentRow({ idBase, label, rowDisabled, compact, active, options, onSelect }) {
  return html`
    <div class="field-row">
      <span class="field-row-label" id=${idBase}>${tr(label)}</span>
      <div class="field-row-control">
        <div class="segmented ${rowDisabled ? "seg-disabled" : ""} ${compact ? "seg-compact" : ""}"
          role="group" aria-labelledby=${idBase}>
          ${options.map((opt) => {
            const optDisabled = rowDisabled || !!opt.disabled;
            return html`
              <button
                class="seg-btn ${opt.value === active ? "active" : ""}"
                aria-pressed=${opt.value === active} aria-label=${tr(opt.label)}
                ?disabled=${optDisabled}
                @click=${() => onSelect(opt, optDisabled)}
              >${opt.icon ? html`<ha-icon icon=${opt.icon}></ha-icon>` : null}<span class="seg-label">${tr(opt.label)}</span></button>`;
          })}
        </div>
      </div>
    </div>`;
}

// Optimistic segmented row: resolve the active value against the caller's pending
// Map (clicked value survives until the poll confirms), decide compact display,
// and wire up segmentRow. Shared by the standard-mode selector leaf and the
// per-room detail panel — both keep a per-key pending Map and the same
// active/compact logic. `onSelect` stays caller-supplied so each keeps its own
// disable guard (the selector honours per-option disable; detail rows don't).
export function optimisticSegment({ pending, key, row, idBase, onSelect }) {
  const active = pending.get(key) ?? row.value;
  // Compact (icon-only inactive) only when a segment is actually active; with no
  // active value (loading/unset) fall back to full labels.
  const compact = row.compactEligible && row.options.some((o) => o.value === active);
  return segmentRow({
    idBase,
    label: row.label,
    rowDisabled: row.disabled,
    compact,
    active,
    options: row.options,
    onSelect,
  });
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
    return hasZone ? tr("Area selected") : tr("Draw an area on the map");
  }
  const sel = [...(selectedIds || [])];
  if (sel.length === 0) return tr("Whole home");
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
    playLabel: inProgress ? tr("Pause") : (isPaused ? tr("Resume") : tr("Start")),
    playAction: inProgress ? "pause" : "play",
    dockLabel: tr("Dock"),
  };
}

// Context-aware primary label for a resting robot (idle/docked), per the design:
// Rooms mode names the selection ("Clean whole home" / "Clean N rooms"); Zone
// mode is "Clean area" once drawn, else the disabled "Draw an area first". The
// shell passes this to the button row as a label override; while the robot is
// occupied the row falls back to buttonLabels (Pause/Resume). Pure.
export function primaryCleanLabel(mapMode, roomCount, hasZone) {
  if (mapMode === "zone") return hasZone ? tr("Clean area") : tr("Draw an area first");
  if (roomCount <= 0) return tr("Clean whole home");
  return countLabels().cleanRooms(roomCount);
}

// Room-label chip text: the room name only (the m² area was dropped from the
// on-map pills). Returns the string the canvas renders. Pure — used by
// drawRoomLabels and unit-tested directly.
export function roomChipText(room) {
  return room?.name || room?.id || "";
}
