# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries under `[Unreleased]` are grouped by `Added`, `Changed`,
`Deprecated`, `Removed`, `Fixed`, `Security`. Every user-visible
change cites the `FR-*` / `NFR-*` / `SEC-*` / `OPS-*` IDs it
satisfies. Traceability is a convention, not a CI gate (ADR-0004).

## [Unreleased]

### Phase: 6 — Map polish, reconnect hardening, and pinch-zoom/pan

### Added
- **Localization: Romanian, German, French, Italian, Spanish** —
  `translations/{ro,de,fr,it,es}.json` translate every HA-facing string (config/reauth
  flow, entity names, all ~52 fault-code states, select/vacuum state enums, repair issues);
  each loads automatically when the Home Assistant user language matches.
- `www/karcher-vacuum-card.js` (1.33.0) — the Lovelace card now has an i18n layer
  (`tr()` keyed on English source strings, driven by `hass.language`, English fallback on
  any miss) with `ro`/`de`/`fr`/`it`/`es` string tables for all card chrome: buttons,
  status line, map-mode control, legend, sheet tabs/hints, room list, and the config editor.
  Interpolated count labels ("clean N rooms" / "N of M rooms") use a per-language
  `COUNT_LABELS` map so each language's verb order and plural agreement are correct
  (Romanian keeps its three-form `roPlural`).
- **Translation parity gates** (CI) — `tests/unit/test_translations.py` asserts
  `strings.json` == `en.json` and that every `translations/<lang>.json` (auto-discovered)
  carries en's exact key tree with the `{email}` placeholder intact;
  `tests/frontend/karcher-i18n-parity.test.js` asserts all card `TRANSLATIONS` blocks
  share one key set, every wrapped `tr("…")` literal resolves in every language (guards
  the silent English-fallback class), each language has a `COUNT_LABELS` entry, and the
  card's mode/suction/water labels match each JSON's select states. Both run in the
  existing `tests` / `frontend` jobs — no new workflow.
- `doc/LOCAL_CONTROL.md` — new reference: on-device process architecture (RobotApp/everest,
  nanomsg bus via `everest-server`, `aiot_client` paho-mqtt/mbedTLS cloud bridge, Cartographer
  SLAM) derived from `/oem/bin` binary analysis, plus the ranked cloud-free control paths that
  open up post-root: (A) redirect the cloud MQTT to a local Mosquitto and repoint the existing
  integration, (B) a nanomsg agent talking to `RobotApp` directly, (C) a Valetudo port. Indexed
  in `doc/README.md`. Cross-referenced from `PROTOCOL.md §9`, `ROOTING.md §5`,
  `INVESTIGATION.md §4`, and `CONSTRAINTS.md §7`. Confirmed the broker pin is a PEM file on the
  writable partition (`/userdata/config/server.crt`, seeded by `S88scinit`), so the cert swap
  needs no binary patching; noted that `aiot_client` uses mbedTLS, so the OpenSSL `LD_PRELOAD`
  bypass in `ROOTING.md §5` does not apply to it (SEC).
- `www/karcher-vacuum-card.js` (1.31.0) — opt-in debug footer: a new `show_debug`
  config flag (off by default, toggled from the card editor) renders a small muted
  footer at the bottom of the card showing the loaded card version, HA version, vacuum
  entity id, activity, map-loaded state + dimensions, connectivity, and last-updated
  time. Chiefly this surfaces the loaded card version without devtools, to confirm a
  fresh build past the resource cache. Curated whitelist only — no raw attributes,
  device id, or serial (SEC).
- `www/karcher-vacuum-card.js` (1.30.2) — zoomed-map affordances: a soft directional
  shadow fades in on each edge where the map overflows the frame (opacity tracks the
  off-screen overhang, so reaching a true edge clears that side's scrim), and the first
  time the map is zoomed past fit it eases a short pan out-and-back toward the most-hidden
  side to telegraph that the map is draggable. Both are purely client-side; the nudge
  respects `prefers-reduced-motion` (the scrims remain) and re-arms on reset-zoom.
- `www/karcher-vacuum-card.js` — the map robot icon now animates: it glides along its
  path at the robot's measured travel speed (constant-velocity follower with a trailing
  buffer) with smoothed heading, the cleaned trail is revealed in step, and a pulse cue
  (matching the header status dot) plays while the robot is cleaning, returning, or
  relocalizing. Purely client-side; no new entity data.
- `vacuum.py` — `room_map` attribute now includes `area_m2` (float, m²) for each room,
  computed from the room-ID grid cell count × resolution². Card renders it below the room
  name in a smaller, lighter font, centred in the pill.
- `www/karcher-vacuum-card.js` — accessibility: the segmented controls (Mode / Suction /
  Water and the per-room detail panel) and the Standard / Customise tab strip now expose
  `role="group"` + `aria-pressed` / `aria-label`, so the selected option is announced to
  assistive technology.
- Map image now shows area carpets (rugs), matching the app's checkerboard rendering.
  On the RCV5 carpet cells are encoded in the grid bytes (147–196 in-room, 253
  non-room); the app paints them as a white-on-room-colour per-cell checkerboard
  (`GridMap.updateGlobalMap`) and `map_render._build_base_image` now does the same.
  A second mechanism — `furniture_info` quads (field 16, `type_id == 1550`) — is also
  parsed (`CarpetArea` DTO, `_parse_furniture_info()`, `_draw_carpet_areas()`) but has
  not been observed from the RCV5. See doc/MAP_DATA.md §6.4.
- `www/karcher-vacuum-card.js` — the map canvas now supports pinch-zoom and pan:
  two-finger pinch and ctrl+wheel (trackpad pinch) zoom at the gesture focal point;
  one-finger drag and trackpad two-finger scroll pan once zoomed in; a floating
  reset-zoom button appears while zoomed. The canvas is full-bleed (grows into
  letterbox margins beside a non-square map) and room labels stay a fixed on-screen
  size regardless of zoom level.

### Changed
- **i18n groundwork** — reconciled the previously-drifted `strings.json` and
  `translations/en.json` into one identical canonical English set (adopted the more
  descriptive fault-code wording; added the `room_names_changed` repair issue that was
  missing from `strings.json`), so the translation files mirror a single source of truth.
- **English fault-code wording** — polished eight fault-state strings that carried
  Chinese→English machine-translation artifacts from the Kärcher app, cross-checked
  against the `RobotError.java` constant names (APK v1.4.32): e.g. "Power switch not on"
  → "Power switch is off", "Escape from stuck failed" → "Could not get unstuck",
  "ToF sensor abnormal" → "ToF sensor error", "Water box not installed" → "Water tank not
  installed" (unifying with the "Water tank empty" fault). Values only — keyed by slug.
- **Translation cleanup** — a language review removed the same machine-translation
  artifacts from the localized fault strings: `ro`/`es` rendered the two IR/dock "exception"
  faults with the programmer-speak cognate ("Excepție"/"Excepción") — corrected to the
  proper fault word each language uses elsewhere ("Defecțiune"/"Fallo"); and `tof_abnormal`
  was aligned to "error"/"fault" wording across all five languages. No cross-language
  contamination was found.
- `vacuum.py` — the `status_label` attribute now carries a stable lowercase **slug**
  (`locating`) instead of English display text; the card localizes it. No visible change
  in English; enables the translated status line.
- **docs** — corrected a factual error across `doc/`: the OTA firmware image is **not
  encrypted**. `rootfs.img` is a UBI volume wrapping a plain XZ SquashFS; it extracts to
  cleartext offline (2,439 files, Buildroot 2018.02) once the UBI erase-block headers are
  stripped. The prior "squashfs blocks AES-encrypted with a TrustZone key" claim was a
  misdiagnosis — the "random" bytes were XZ-compressed data interleaved with UBI headers,
  and the `unsquashfs read_block @0x…` failure was the UBI wrapper, not a cipher. The
  extracted `/etc/shadow` root hash cracks to `root` / `3irobotix`, and `/etc/inittab`
  enables an always-on serial console (`getty` on `ttyFIQ0`); SSH/ADB are gated behind a
  `/userdata/debug_mode` flag. Updated `PROTOCOL.md §9.2` (reproduction), `ROOTING.md`
  (§2, §3 Option 4, §6.1/§6.3/§6.7/§6.8, refs), `INVESTIGATION.md §4/§6f`, and
  `CONSTRAINTS.md §1/§7`. Correction verified against the factory image `I3.12.26` (SEC).
- `www/karcher-vacuum-card.js` (1.29.1) — internal refactor, no behaviour change: dead
  code removed (unused reveal-loop bookkeeping, the room list's unused `simple` mode,
  the orphaned `.icon-btn` CSS block, multi-line room-label plumbing left from the
  dropped m² pill line), area-draw mode is now derived from the card mode instead of
  tracked separately, the map click handler reuses the shared room-toggle path, and
  the canvas gesture handlers are renamed `_onMapPointer*` (they own pan/pinch, not
  just zone drawing). The Lit strangler-fig migration is complete — the header comment
  now documents the final architecture.
- AI object 1005 (carpet) detections render as plain labelled dots like every other
  object — the app never draws polygons for them. The convex-hull cluster path
  (`_cluster_points`/`_draw_carpet_clusters`) and its tests are removed.
- `decode_room_id_grid` now matches the APK's verified signed-byte branches: cleaned
  room cells are bytes 60–127 only (previously 60–146 and 197–254 were also decoded
  as rooms — those ranges are unhandled by the app; 253 is the non-room carpet byte).
  Same correction applied to the wall-overlay room-byte mask. doc/MAP_DATA.md §4.2
  and doc/PROTOCOL.md §13.3/§13.4 updated accordingly.

### Fixed
- `coordinator.py` — the "room names changed" repair issue could fire spuriously while
  the robot was relocalizing (losing its map for a moment) and then never clear once the
  map recovered. Detection was split across two concurrent `get_rooms` fetches that could
  read mutually inconsistent, CDN-lagged map data and mistake it for a rename; and once
  raised, the issue had no path to clear because room names were only re-checked on a
  map-ID change. Detection now runs on the single, serialized map-refresh path off the map
  snapshot, ignores transient blank/empty reads, requires a differing name set to persist
  a few refreshes before firing, and clears automatically when names return to normal.
- `www/karcher-vacuum-card.js` (1.31.2) — the header status-dot pulse and the map robot
  icon's pulse now expand in sync on every engine. The canvas pulse read the
  `performance.now()` clock while the CSS `rcv-ping` animation ran on `document.timeline`;
  earlier attempts to align them by pinning the animation's `startTime` were fragile
  (Chromium and iOS WebKit disagree on whether those clocks share an origin, and
  `startTime`/`currentTime` are CSSNumberish, so arithmetic on them silently produced
  `NaN`). The canvas now samples the running `rcv-ping` animation's own `currentTime`
  instead — slaving the map pulse to the exact animation the header renders — with a
  performance-clock fallback when the animation is absent (reduced-motion). Purely
  client-side.
- `www/karcher-vacuum-card.js` — the card silently rendered blank when its configured
  `vacuum_entity` didn't resolve (typo, renamed entity, unloaded integration). It now
  shows an `<hui-warning>` naming the missing entity id instead of failing silently.
- `binary_sensor.py` — the fault/error binary sensor misclassified 21xx lifecycle
  status codes (e.g. relocalizing, self-check) as a vacuum `Error`; only genuine fault
  codes trigger it now. It also now fires while `Paused` with a genuine fault (e.g. a
  bumper/collision block), not only while idle and undocked. The card's error alert
  shows the fault sensor's actual description instead of a generic message, with an
  entity-registry scan fallback so it resolves regardless of an install's entity_id
  history.
- `www/karcher-vacuum-card.js` (1.33.1) — re-foregrounding the iOS app after it was
  backgrounded could still fire the "connection lost" `refresh_preferences` error toast
  even with the disconnected-skip added previously: `hass.connection.connected` can still
  read `true` for a moment after the socket is actually dead, since the disconnect event
  lags the OS-level suspend/resume. The service call now passes `notifyOnError=false`
  (this is a best-effort background refresh, not a user action) and re-arms for the next
  update if the call itself rejects, instead of relying solely on the pre-call connected
  check.
- `pyproject.toml` — `pytest-homeassistant-custom-component` was floating (`<1`) and
  its 0.13.341 release pins a pre-release `homeassistant==2026.7.0b1`, silently pulling
  CI onto a beta HA. Capped below 0.13.341; added `tests/unit/conftest.py` so unit
  snapshots resolve to `snapshots/` (HA convention) rather than syrupy's default
  `__snapshots__/`, fixing the diagnostics-bundle snapshot on CI.
- `coordinator.py` — `_project_overlays` no longer toggles the projected `cur_path_px`
  tip by up to one stride on every push (an off-by-one in the force-include of the final
  pose), which made a path-tip-following overlay jump back and forth.
- `www/karcher-vacuum-card.js` — during a connectivity-only outage (the first transient
  poll failure, inside the `_FAILURE_THRESHOLD = 2` flap-prevention window) the vacuum
  entity still reports its cached activity while the connectivity sensor reads `off`. The
  card showed "Offline" in the header but left Start / Pause / Dock enabled and clickable,
  dispatching services that could not reach the robot. The button row now receives the
  derived offline flag and disables every control while offline. (FR-OF-5)
- `coordinator.py` — detects when the robot resets or shuffles room names (e.g. after a
  factory reset) and surfaces a repair issue prompting the user to reload the integration.
- `sensor.py` — "Finished" stat tile now uses the dock-transition timestamp recorded by
  the coordinator instead of `cleaning_time.last_changed`, which was not a reliable finish
  time while the robot was paused mid-clean.
- Apple Home full clean (all rooms selected) cleaned only one room. Apple Home expresses
  "clean all rooms" as an empty Matter ServiceArea selection, which HAMH dispatches as a
  parameterless `vacuum.start`; a stale room selection on the coordinator (card map-tap or
  `select.<name>_room`) silently filtered that start down to a single room. The selection
  is now one-shot — consumed by the first clean dispatch and cleared
  (`coordinator.consume_clean_room_ids()`) — and the card's Start button now starts
  selected rooms via explicit ids (`vacuum.send_command app_segment_clean`, preference
  order) instead of the `set_room_selection` + `vacuum.start` side channel. `vacuum.start`
  is therefore whole-home for external callers (HAMH/Apple Home, voice assistants,
  automations). (FR-V-1, FR-V-2)
- `__init__.py` — a setup failure after shared-adapter acquisition (e.g. cloud down at HA
  start → `ConfigEntryNotReady` from the first refresh) leaked one adapter refcount per
  retry and left the failed attempt's MQTT subscription registered, so the adapter was
  never released or closed. Cleanup (`coordinator.async_shutdown()` + `release_adapter`)
  now runs on any failure past acquisition.
- `adapter.py` — the MQTT dispatcher install check was a boolean flag; if karcher-home
  rebuilt its MQTT client (e.g. on re-login), push traffic was silently lost for the rest
  of the session. The bind is now identity-checked against the current `on_message`, and a
  successful `silent_reauth` replays all device subscriptions and re-binds the dispatcher
  (`_restore_push_pipeline`).
- `coordinator.py` — a poll reply that was in flight when a push landed overwrote the newer
  push data. `_handle_push` records a monotonic receipt timestamp; `_async_update_data`
  discards a poll result superseded mid-flight.
- `coordinator.py` — CPU-bound map post-processing (`compute_room_cell_map`, room-ID grid
  decode, render layout) ran on the event loop every 10 s while cleaning; it now runs in
  the executor (`_derive_map_state`) and all derived state is assigned in one synchronous
  block so readers never see a snapshot paired with a stale layout.
- `_types.py` — `RoomPreference.to_raw()` hard-coded `materialId` and `carpet` to 0, so any
  single-room preference edit zeroed those fields for every room on the robot. Both now
  round-trip (`from_raw` indices 2 and 7).
- `image.py` / `coordinator.py` — the map PNG cache was keyed on `id(snapshot)`; CPython
  address reuse after GC could serve a stale render. Now keyed on a monotonic
  `coordinator.map_snapshot_seq`.
- `adapter.py` — `silent_reauth` slept its backoff (up to 2 min) while holding the
  account-wide reauth lock, blocking every coordinator on the account. The sleep now runs
  outside the lock; concurrent callers dedup on `_last_reauth_ts` (one login total).
- `adapter.py` — generic login failures mapped to bare `ClientError`, which no caller
  caught — setup failed with a traceback instead of retrying. They now go through
  `_translate_exception` (→ `TransientError` → `ConfigEntryNotReady`).
- `adapter.py` — `_project_properties` read `current_map_id` with direct attribute access
  (the only field not using `getattr`); an upstream shape change would have raised on the
  MQTT thread.
- `tests/tools/coverage_gate.py` — the gate shelled out to a bare `coverage` executable
  (PATH-dependent on an activated venv) and treated a failed `coverage report` as an empty
  report, passing silently with nothing enforced. It now runs
  `sys.executable -m coverage` and fails loudly when the report cannot be produced.

### Added
- `__init__.py` — minimal `async_migrate_entry` restored: v2 → v3 drops the redundant
  `sn` / `product_id` / `nickname` keys; v1 (never shipped) fails cleanly with
  `MIGRATION_ERROR` instead of "migration handler not found". (FR-MG-2)
- `select.py` / `switch.py` / `number.py` — per-room entities are now added dynamically via
  a coordinator listener when rooms appear after setup (initial fetch retried, or a map
  change introduces new rooms); previously they were created once at platform setup and
  late-arriving rooms got no entities until a reload.
- `services.yaml` / `__init__.py` — `set_room_preference` and `set_room_selection` accept an
  optional `device_id` (HA device-registry id). Without it, room-set matching that is
  ambiguous (two robots) or unmatched now raises `ServiceValidationError` instead of
  silently picking the first robot or doing nothing. The card passes `device_id` derived
  from the configured vacuum entity. `set_room_selection` is now also removed on last
  entry unload (was leaked).
- `number.py` — per-room `KarcherRoomOrderNumber` (`NumberEntity`): sets the cleaning order
  for each room (1 = first). Writes via `async_set_room_preference` on the coordinator.
- `switch.py` — per-room `KarcherRoomCustomSwitch` (`SwitchEntity`): enables or disables
  custom per-room settings (`check` flag). On = use per-room mode/power/repeat overrides;
  off = use global defaults. Writes via `async_set_room_preference`.
- `select.py` — per-room `KarcherRoomModeSelect` (Vacuum / Vacuum & Mop / Mop) and
  `KarcherRoomPowerSelect` (Silent / Standard / Medium / Turbo). Both write via
  `async_set_room_preference`.
- `services.yaml` — `set_room_preference` HA service: accepts a `room_order` list of room IDs
  and rewrites the full preference table with that ordering. Useful for bulk reorders.
- `_types.py` — `RoomPreference` dataclass (frozen): parses and serialises the robot's
  12-element preference array (`from_raw` / `to_raw`). APK-verified layout:
  `[roomId, roomName, materialId, mode, wind, water, repeat, carpet, check, 0, 0, carpetAvoidance]`.
- `adapter.py` — `set_preference_type(device, prefer_type)`: publishes
  `service.set_preference_type` to switch Standard (0) or Customise (1) mode on the robot.
  APK-verified: `GuideVm.setPreferenceType`, `DeviceMethod.SET_PREFERENCE_TYPE`, v1.4.32,
  2026-06-03.
- `coordinator.py` — `prefer_mode` field (`"standard"` | `"customise"`): read from
  `prefer_on` in the `get_preference` reply and updated by `async_set_preference_type`.
- `vacuum.py` — `prefer_mode` added to `extra_state_attributes` so the Lovelace card can
  restore the active tab on page load.
- `www/karcher-vacuum-card.js` — Standard / Customise tab state is now persisted on the robot
  via `set_preference_type` and restored from `prefer_mode` on first hass update, matching
  the behaviour of the official Kärcher app.
- `tests/contract/test_adapter.py` — 5 new contract tests: `get_preference` dict return,
  `prefer_on=1` / `prefer_on=0` parsing, timeout fallback, `set_preference_type` payload.

### Changed
- `coordinator.py` — poll-path `get_preference` is throttled to 5 minutes (was every 30 s
  poll, one MQTT round-trip per cycle with a 5 s executor block on timeout). External
  prefer_mode changes (Kärcher app, robot panel) now sync within 5 minutes; setup, map
  changes, and HA-side writes refresh immediately.
- `coordinator.py` — `ProtocolError` poll misses log at WARNING per the documented error
  taxonomy (was DEBUG); `ValidationError` stays at DEBUG.
- `vacuum.py` — the per-room preference entity-id lookup in `extra_state_attributes` is
  cached and invalidated on entity-registry updates; previously a full registry scan ran
  on every state write (each path push while cleaning).
- `ARCHITECTURE.md` / `CLAUDE.md` — aligned with the implementation: shared adapter per
  account (not per entry), actual push/poll ordering mechanism, reconnect semantics,
  executor exception for pure map work, render pipeline (paths/robot drawn by the card,
  not baked into the PNG), repository layout, pytest config location, and the PEP 758
  Python ≥ 3.14 parse-time requirement.
- `adapter.py` — `get_preference` / `_get_preference_sync` now return
  `{"rooms": [...], "prefer_on": int}` (was a bare list). `prefer_on` is now parsed and
  propagated instead of discarded. (APK-verified: `ControlMainActivity.java:543`,
  `GuideThreeFragment.java:312`, v1.4.32, 2026-06-03)
- `__init__.py` — `Platform.NUMBER` and `Platform.SWITCH` registered in `PLATFORMS`.
- `select.py` — per-room mode and power selects added alongside the existing room, cleaning
  mode, and water level selects.

### Changed
- `www/karcher-vacuum-card.js` — visual overhaul: card split into four `ha-card` sections
  (Status, Map, Controls, Settings); status pill replaced with animated status dot + label;
  battery now rendered as an inline glyph with bolt icon for charging; control buttons
  redesigned as circle-icon buttons with labels; mode/suction/water selectors and
  per-room settings replaced with inline segmented controls; room rows expand in-place
  (no separate detail view); carpet rendering changed from per-cell checkerboard to a
  smooth 25 % white wash; path trail rendered as a smooth quadratic Bézier curve instead
  of a straight polyline; room overlay and pill-label colours changed from blue to
  accent yellow. `charging_entity` (binary sensor) added to card config to drive the
  battery charging indicator.
- `map_render.py` — carpet rendering changed from per-cell checkerboard to a uniform 25 %
  white wash applied at room-fill time (carpet-room bytes 147–196) or carpet-overlay time
  (byte 253 outside rooms). Room labels and charger dot moved from the server-side PNG to
  the card's canvas overlay (exposed via `charger_px` attribute).
- `vacuum.py` — robot `phi` passed through to the card without the π offset that was
  applied when docked; the card's drawing code now handles orientation directly.
- `doc/MAP_DATA.md` — `MapExtInfo` §3.1 added: both date fields carry Unix epoch seconds;
  `task_begin_date` marks session boundaries; `map_upload_date` drives map-staleness checks.
- `www/karcher-vacuum-card.js` — fan speed and water level selectors now populated dynamically
  from the vacuum entity's `fan_speed_list` / `water_level_list` attributes rather than
  hard-coded option lists; selector is hidden when the attribute is absent.
- `vacuum.py` / `strings.json` — fan speed option labels are now translated via
  `state_attributes` entries in `strings.json` instead of being hard-coded English strings.
- `entity.py` (and siblings) — entity icons migrated from inline `_attr_icon` assignments to
  `icons.json`, following current HA best practice.
- `select.py` — room select options are now plain room names instead of `"{id}:{name}"` strings,
  making the UI read naturally. The coordinator still matches by room ID internally, so selection
  is unambiguous even after a map reload. (F008)
- `ARCHITECTURE.md` / `ROADMAP.md` replace the `spec/` + `adr/` apparatus; no behaviour change.
- `_types.py` — `KarcherHomeProtocol` and `DevicePropertiesProtocol` removed; adapter types its
  client as `Any` and accesses private symbols via `getattr()`. Reduces maintenance surface;
  mypy `--strict` still passes.

### Fixed
- `www/karcher-vacuum-card.js` — "Finished X ago" stat was shown while the robot was
  paused (cleaning_time `last_changed` is not a finish timestamp while a job is in
  progress). Now suppressed whenever activity is `cleaning`, `returning`, or `paused`.
- `coordinator.py` — `current_room_name` no longer flickers when the robot briefly enters a
  doorway: requires 5 consecutive cleaning-flagged path points in a new room before committing
  the change. Path points in rooms not included in the active `set_room_clean` command are
  ignored entirely.
- `coordinator.py` — robot position on the map now updates during the return-to-dock phase;
  previously frozen until docking completed.
- `adapter.py` / `coordinator.py` / `vacuum.py` — robot position and heading (`robot_px`) now
  derived from the live MQTT path stream (`current_robot_pose`) instead of the 10 s-throttled
  cloud snapshot, eliminating visual lag between the path line and the robot icon. `phi` is
  now preserved through the full pipeline.
- `www/karcher-vacuum-card.js` — card loaded while a Custom-mode clean is in progress no longer
  incorrectly shows the Standard tab.
- `www/karcher-vacuum-card.js` — map area no longer reflows when the map image loads; aspect
  ratio is reserved from `map_image_size` before the image arrives. Placeholder text
  "No map yet…" is suppressed while a map exists but is still loading.

### Removed
- `__init__.py` — the v1 migration helpers (`_migrate_v1_to_v2`, `_CANONICAL_ENTITY_TYPES`)
  and their repair-issue machinery. v1 never shipped publicly. A minimal `async_migrate_entry`
  with the v2 → v3 step was retained after review (see Added) so any pre-v3 install can
  still load. Config entry version remains 3.
- `spec/` directory (11 files) and `adr/` directory (4 files + README) — superseded by
  `ARCHITECTURE.md` and `ROADMAP.md`.
- `exceptions.py` — unused subclasses `AccessDenied`, `TimeoutError`, `DeviceNotFound`,
  `InvalidRegion` removed.

## Phase 4 — Hardening to Silver (closed 2026-05-02)

### Added
- `diagnostics.py` — `async_get_config_entry_diagnostics` returning a redacted
  bundle (config, last-known device properties, rooms, coordinator state, library
  version). Email, password, token, nonce, and serial-number fields are redacted.
  (P4-1, FR-D-1, FR-D-2)
- `__init__.py` — `async_migrate_entry` bumps config entries from version 1 to 2:
  adds `region_endpoint_snapshot` placeholder; re-keys any entity-registry entry
  whose unique_id does not match the canonical `{device_id}_{entity_type}` form.
  On failure, creates a persistent repair issue and logs at ERROR. (P4-2, FR-MG-2,
  FR-MG-3, FR-MG-5, FR-MG-5a)
- `adapter.py` — `silent_reauth()`: bounded silent token refresh (max 3 attempts
  per 5-minute window, exponential backoff 5 s / 30 s / 2 min). `InvalidCredentials`
  surfaces immediately; transient login failures become `TransientError`. (P4-4,
  FR-A-8, FR-A-8a, FR-A-8b)
- `coordinator.py` — persistent repair issue created after 1 h of continuous cloud
  outage; dismissed automatically on recovery. Log spam bounded: WARNING with
  traceback on first failure; INFO per poll within first 5 min; one INFO line per
  10 min thereafter; full traceback re-logged on online/offline transitions. (P4-11,
  P4-12, FR-OF-6, FR-OF-7, FR-OF-8)
- `sensor.py` — `cleaning_area` and `cleaning_time` sensors get
  `EntityCategory.DIAGNOSTIC`. `PARALLEL_UPDATES = 0` set. (P4-7)
- `vacuum.py`, `binary_sensor.py`, `select.py` — `PARALLEL_UPDATES` constant added
  to each platform module. (P4-7)
- `strings.json` / `translations/en.json` — repair-issue strings for
  `cloud_outage_persistent` and `migration_failed_v1_v2`. (P4-2, P4-11)
- `.github/workflows/release.yml` — SBOM step generates a CycloneDX JSON asset
  and attaches it to every release. (P4-5)
- `tests/integration/test_migration_integration.py` — 7 integration tests covering
  v1 to v2 migration (data shape, field preservation, snapshot idempotency), entity
  unique_id re-keying, upgrade continuity (FR-MG-4), and migration failure leading
  to repair issue. (P4-3, FR-MG-4, FR-MG-5, FR-MG-5a)
- `tests/integration/test_reauth_robustness.py` — 7 tests covering silent reauth
  happy path, attempt limit, window reset, credential failure, transient login
  failure, and coordinator integration. (P4-4, FR-A-8, FR-A-8a, FR-A-8b)
- `tests/integration/test_outage_repair.py` — 8 tests for repair issue
  creation/dismissal threshold and log throttle behaviour. (P4-11, P4-12, FR-OF-6..8)
- `tests/unit/test_diagnostics_redaction.py` — 13 tests for the diagnostics
  redaction helper and bundle structure. (P4-1, FR-D-1, FR-D-2)

### Changed
- `manifest.json` — `quality_scale` bumped to `silver`; `version` set to `2.3.0`.
  (P4-7)

## Phase 5 — Map display and Lovelace card (closed 2026-05-08)

### Changed
- `manifest.json` — `version` bumped to `2.4.0`. (Phase 5)
- `quality_scale.yaml` — comprehensive audit: all Bronze and Silver items now
  `done`; Gold items updated to reflect Phase 4 deliverables; `icon-translations`
  and `reconfiguration-flow` marked `todo` (deferred post-Silver). (P4-7)
- `coordinator.py` — `KarcherCoordinator` now accepts optional `config_entry`
  parameter and passes it to `DataUpdateCoordinator` to avoid ContextVar reliance.

### Migration notes (v1 to v2)

If you installed a pre-release build before `v2.0.0`, your config entry is at
version 1. Upgrading to `v2.3.0` migrates it automatically on the next HA restart
— no manual action required.

The migration adds an internal `region_endpoint_snapshot` field (populated on
first reconnect) and re-keys any entity registry entries that use a non-canonical
unique_id to the standard `{device_id}_{entity_type}` form.

If migration fails (a repair issue will appear in HA), downgrade to the previous
release, download a diagnostics report from Settings → Integrations, and file a
bug with the report attached at https://github.com/vosadci/karcher-rcv5-ha/issues.

## Phase 3 — Rooms, region routing, Apple Home (closed 2026-05-01)

### Added
- `select.py` — `KarcherRoomSelect`: dynamic options from `coordinator.rooms`
  (`All rooms` + named rooms); unavailable when no rooms known (FR-SL-2);
  selection stored on coordinator and consumed by `async_start` (FR-SL-3). (P3-2)
- `coordinator.py` — `_maybe_refresh_rooms`: detects `current_map_id` changes,
  clears rooms + selection immediately, re-fetches rooms asynchronously,
  notifies entity listeners at each stage (FR-SL-7). (P3-6)
- `adapter.py` — `get_endpoint_snapshot()`: reads `_base_url` and `_mqtt_url`
  from the resolved client after setup (FR-RG-2). (P3-7)
- `__init__.py` — persists `region_endpoint_snapshot` in config entry data on
  every `async_setup_entry` call; only writes when changed (FR-RG-2, FR-RG-3). (P3-7)
- `_types.py` — `KarcherHomeProtocol` extended with `_base_url` and `_mqtt_url`. (P3-7)
- `tests/integration/test_room_select.py` — 12 integration tests covering room
  select options, availability, selection storage, `async_start` room dispatch,
  map-ID change room refresh, empty-rooms path, and endpoint snapshot storage.
  (P3-2, P3-3, P3-6, P3-7, P3-8)
- `strings.json` / `en.json` — `room` select translation key added.

### Changed
- `spec/03-constraints-and-deltas.md` §3.1 — added `_base_url` and `_mqtt_url`
  to the permitted private-API surface table. (P3-7)
- `tests/tools/check_imports.py` — `ALLOWED_PRIVATE_API` extended with
  `_base_url` and `_mqtt_url`. (P3-7)
- `tests/integration/test_init_lifecycle.py` — `FakeAdapter` gains
  `get_endpoint_snapshot()` stub.

## Phase 2 — Feature parity: sensors and selects (closed 2026-04-28)

### Added
- `custom_components/karcher_home_robots/select.py` — `KarcherCleaningModeSelect`
  (Vacuum / Vacuum & Mop / Mop; writes `prop.set {"mode": N}`) and
  `KarcherWaterLevelSelect` (Low / Medium / High; `entity_registry_enabled_default=False`;
  unavailable when mode=Vacuum-only). (P2-3, P2-4, FR-SL-4, FR-SL-5, FR-SL-6, FR-AH-2)
- `_types.py` — `mode: int | None` field added to `DeviceProperties` DTO and Protocol. (P2-3)
- `const.py` — `CLEANING_MODE_VACUUM`, `CLEANING_MODE_VACUUM_AND_MOP`,
  `CLEANING_MODE_MOP` constants. (P2-3)
- `Platform.SELECT` registered in `PLATFORMS` in `__init__.py`. (P2-3)
- `select` entity translations in `strings.json` and `translations/en.json`. (P2-3, P2-4)
- `tests/contract/test_prop_set_encoding.py` — 7 contract tests confirming `prop.set`
  envelope and topic for all `mode` and `water` values. (P2-6, FR-SL-4, FR-SL-5)
- `tests/integration/test_select_availability.py` — 11 integration tests covering
  cleaning-mode select state and dispatch, water-level availability (Vacuum-only →
  unavailable; Mop → available), water-level disabled-by-default, and fan-speed
  unavailability when mode=Mop-only. (P2-7, FR-SL-4..6, FR-V-8)

### Changed
- `vacuum.py` — `fan_speed` returns `None` when `data.mode == CLEANING_MODE_MOP`
  (FR-V-8 unavailability in Mop-only mode). (P2-5)
- `adapter.py` — projects `mode` field from upstream `DeviceProperties`. (P2-3)
- `tests/conftest.py` — `make_props` defaults include `mode`. (P2-3)
- `tests/contract/test_adapter.py` — `FakeUpstreamProps` includes `mode` field. (P2-3)

## Phase 1 — MVP (closed 2026-04-28)

### Added
- `tests/hardware/` — HIL test skeleton: `test_hil_command_roundtrip.py`
  (start → Cleaning within 2 s), `test_hil_room_clean.py`
  (`app_segment_clean` with a real room ID), `test_hil_locate.py`
  (locate command accepted; beep is manual attestation),
  `test_hil_reconnect.py` (close + re-setup delivers push updates within
  30 s). All skipped unless `KARCHER_HIL=1` is set. (P1-15)
- `tests/integration/test_init_lifecycle.py` — 7 integration tests covering entry
  setup/unload lifecycle via `FakeAdapter` (no network): coordinator created, rooms
  loaded, auth failure → `SETUP_ERROR`, unload calls `adapter.close`, two entries
  are independent (NFR-SC-1..3), device not on account → `SETUP_ERROR`, transient
  fetch error → `SETUP_RETRY`. (P1-14, FR-A-1, FR-A-5..6, FR-OF-1, NFR-SC-1..3)
- `tests/integration/test_entity_states.py` — 15 integration tests covering
  vacuum activity states for all 6 `DeviceProperties` snapshots (FR-V-9), rooms
  in Roborock format (FR-V-11, FR-AH-1), battery/area/time sensor values and units
  (FR-SE-1..3), sensors unavailable on no data (FR-SE-4), error binary sensor off
  when idle and on when error state (FR-BS-1), off during cleaning/returning with
  fault (FR-BS-2). (P1-14)
- `tests/conftest.py` — shared `make_props` helper and six canned `DeviceProperties`
  snapshots (`PROPS_IDLE`, `PROPS_CLEANING`, `PROPS_PAUSED`, `PROPS_DOCKED`,
  `PROPS_RETURNING`, `PROPS_ERROR`), `TEST_DEVICE`, `TEST_ROOMS`, `fake_hass`
  fixture. (P1-14)
- `tests/integration/conftest.py` — autouse `enable_custom_integrations` fixture
  so HA loads the custom component in all integration tests. (P1-14)
- `custom_components/karcher_home_robots/adapter.py` — full async
  implementation of `KarcherAdapter`: `async_setup`, `authenticate`,
  `get_devices`, `get_rooms` (via `get_map_data` protobuf), `subscribe`
  (patches `_mqtt.on_message` with a threadsafe push bridge), `unsubscribe`,
  `fetch_properties` (registers `threading.Event` in `_wait_events`, publishes
  `prop.get`, waits for reply — work-around for stale-cache upstream bug),
  `send_command`, `set_property`, `close`. All blocking calls dispatched via
  `hass.async_add_executor_job`; paho callbacks re-enter the event loop
  through `loop.call_soon_threadsafe`. (P1-1, FR-UP-1..4, ADR-0001)
- `custom_components/karcher_home_robots/coordinator.py` — `KarcherCoordinator`
  (`DataUpdateCoordinator[DeviceProperties]`): push/poll reconciliation with
  monotonic `loop.time()` receipt timestamps and `asyncio.Lock` (FR-UP-5,
  NFR-R-5); `_FAILURE_THRESHOLD = 2` flap prevention (FR-OF-5); error taxonomy
  translation (`AuthError` → `ConfigEntryAuthFailed`, `PermanentError` →
  `ConfigEntryError`, `TransientError` → `UpdateFailed`, `ValidationError` /
  `ProtocolError` → cached data); `vacuum_state` property; `selected_room_id`
  state (FR-SL-3); room list loading via adapter. (P1-5)
- `tests/contract/test_adapter.py` — 26 contract tests against a
  `FakeKarcherClient` (no real MQTT/REST): `authenticate`, `get_devices`,
  `get_rooms`, `subscribe` push delivery, `fetch_properties` prop.get
  round-trip, `send_command`, `set_property`, `close`, error translation
  for all five exception classes, and property projection for all
  `DeviceProperties` fields. (P1-4)
- `custom_components/karcher_home_robots/_types.py` — `KarcherHomeProtocol`
  updated to match karcher-home 0.5.1 actual surface: `_mqtt`, `_device_props`,
  `_wait_events`, `_update_device_properties`, `subscribe_device`,
  `unsubscribe_device`, `get_map_data`. (P1-1)
- `tests/tools/check_imports.py` allowlist updated: added `_device_props`,
  `_wait_events`, `unsubscribe_device`; removed `_lib_publish` and
  `_lib_wait_for_reply` (do not exist in 0.5.1). (P1-1)
- `spec/03-constraints-and-deltas.md` §3.1 table updated to reflect the
  actual karcher-home 0.5.1 private-API surface. (P1-1)
- `custom_components/karcher_home_robots/config_flow.py` — three-step
  config flow (country → credentials → device picker) plus reauth path.
  `VERSION = 2` matches the migration contract (FR-MG-2). Deduplicates by
  `device_id` (FR-A-5); surfaces `invalid_auth`, `cannot_connect`,
  `no_devices`, `unknown` error keys (FR-A-6, FR-A-9, FR-A-11). (P1-7)
- `custom_components/karcher_home_robots/strings.json` and
  `translations/en.json` — English translations for all config-flow steps,
  errors, and abort reasons; entity names for vacuum, battery, cleaning_area,
  cleaning_time, error. (P1-7, P1-13)
- `custom_components/karcher_home_robots/entity.py` — `KarcherEntity` base
  class: device_info grouped by device_id, `_attr_has_entity_name = True`,
  `available` override, `_data` helper property for None-safe coordinator
  data access. (P1-8)
- `custom_components/karcher_home_robots/vacuum.py` — `KarcherVacuum`
  (`StateVacuumEntity`): start/stop/pause/return/locate commands; fan speed
  (Silent/Standard/Medium/Turbo via prop.set wind); rooms in Roborock format
  as `extra_state_attributes` (FR-AH-1); `async_send_command` passthrough
  (FR-V-12). (P1-9)
- `custom_components/karcher_home_robots/sensor.py` — `KarcherBatterySensor`
  (BATTERY, %, FR-SE-1), `KarcherCleaningAreaSensor` (AREA, m², raw÷100,
  FR-SE-2), `KarcherCleaningTimeSensor` (DURATION, min, FR-SE-3). All return
  None when coordinator data absent (FR-SE-4). (P1-10)
- `custom_components/karcher_home_robots/binary_sensor.py` — `KarcherErrorSensor`
  (PROBLEM device class, `mdi:robot-vacuum-alert`); on only when
  `vacuum_state == Error` — transient faults during cleaning/returning are
  suppressed (FR-BS-1..3). (P1-11)
- `custom_components/karcher_home_robots/__init__.py` — `async_setup_entry`
  creates adapter + coordinator per entry, authenticates, resolves device by
  `device_id`, calls `coordinator.async_setup()`, stores coordinator in
  `entry.runtime_data`, forwards to VACUUM/SENSOR/BINARY_SENSOR platforms;
  `async_unload_entry` tears down in reverse. (P1-12)

---

## Phase 0 — Scaffold (closed 2026-04-27)

### Added
- Specification set (`spec/01`–`spec/11`, four ADRs `adr/0001`..`adr/0004`,
  `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`) bootstrapped from
  rewrite seed.
- `.claude/skills/review/` — combined review skill (layering, HA
  patterns, SOLID, security posture, simplification).
- `.claude/skills/docs-check/` — docs-freshness check.
- Baseline tooling: `pyproject.toml` (`ruff`, `mypy --strict`,
  `pytest`, phase-graduated coverage gate), `Makefile`,
  `.pre-commit-config.yaml`, `hacs.json`, `.gitignore`.
- CI workflow `.github/workflows/ci.yml` pinning HA `2025.1.0` and
  `2025.10.0`, pinning `hacs/action@22.5.0`, running `pip-audit
  --strict` (no `|| true`), `hassfest`, and
  `tests/tools/check_imports.py`. (P0-3)
- Release workflow `.github/workflows/release.yml` verifying
  `manifest.json` version matches the tag, auditing
  `quality_scale.yaml` vs manifest claim, and packaging the
  integration zip. (P0-4, P0-10)
- Dependabot config `.github/dependabot.yml` with grouped updates
  (`python-patches`, `pytest-stack`, `lint-stack`,
  `actions-patches`). (P0-3)
- Pull-request template (`.github/PULL_REQUEST_TEMPLATE.md`) and
  single-maintainer `.github/CODEOWNERS`. (P0-6)
- `custom_components/karcher_home_robots/` package skeleton:
  `__init__.py` (`async_setup_entry` / `async_unload_entry` return
  `True`), `manifest.json` (`quality_scale: bronze`,
  `iot_class: cloud_push`, `version: 2.0.0-alpha.1`,
  `requirements: ["karcher-home==0.5.1"]`), `const.py`, `py.typed`,
  `icon.png`, `icon.svg`. (P0-1, P0-12)
- `custom_components/karcher_home_robots/exceptions.py` — full
  `ClientError` hierarchy per ADR-0003: `AuthError`,
  `InvalidCredentials`, `TokenRejected`, `AccessDenied`,
  `TransientError`, `NetworkError`, `TimeoutError`, `RateLimited`,
  `BrokerDisconnect`, `PermanentError`, `DeviceNotFound`,
  `InvalidRegion`, `ValidationError`, `ProtocolError`. (P0-9)
- `custom_components/karcher_home_robots/_types.py` — integration-owned
  `KarcherHomeProtocol` and `DevicePropertiesProtocol` so `mypy --strict`
  can type-check against `karcher-home` without vendored stubs. (P0-9)
- `custom_components/karcher_home_robots/adapter.py` — `KarcherAdapter`
  with `NotImplementedError` stubs; only file permitted to import
  `karcher`; accepts `karcher_factory` for test injection; all HA
  imports `TYPE_CHECKING`-only. (P0-9)
- `custom_components/karcher_home_robots/quality_scale.yaml` — all 56
  Bronze/Silver/Gold/Platinum rules declared (`done` / `todo` /
  `exempt`) with one-line justifications. (P0-10)
- `tests/tools/check_imports.py` rewritten (AST-based): Rule 1 enforces
  that only `adapter.py` imports `karcher`; Rule 2 enforces that every
  `_`-prefixed access on a `karcher` object inside `adapter.py` matches
  the `ALLOWED_PRIVATE_API` allowlist from `spec/03` §3.1. (P0-7)
- `tests/tools/test_check_imports.py` — 22 unit tests covering both
  rules, including chain access, computed `getattr`, self-attribute
  exclusion, and a parametrised sweep of all allowlist entries. (P0-7)
- `tests/tools/check_quality_scale.py` — stdlib-only release-gate
  script: parses `quality_scale.yaml`, computes highest earned tier,
  exits 1 if the manifest claim exceeds it. (P0-10)
- `tests/tools/coverage_gate.py` — phase-graduated coverage gate reading
  `[tool.karcher].phase` from `pyproject.toml`; gate suspended in
  Phase 0. (P0-2)
- `tests/fixtures/captures/` — 9 `.jsonl` files (one per documented
  MQTT scenario) hand-extracted from `doc/PROTOCOL.md` §3 onward:
  `service_invoke_set_room_clean`, `service_invoke_start_recharge`,
  `service_invoke_stop_recharge`, `prop_set_water_level`,
  `prop_set_fan_speed`, `prop_set_cleaning_mode`,
  `event_property_post_idle`, `event_property_post_docked`,
  `event_property_post_cleaning`. (P0-11)

### Changed
- **Cloud-client strategy:** the rewrite wraps `karcher-home`
  behind a single `adapter.py` rather than rewriting the wire
  protocol in-tree (`adr/0001-library-adapter.md`). The adapter owns
  the async boundary (`run_in_executor`), the foreign-thread bridge
  (`loop.call_soon_threadsafe` for paho-mqtt callbacks), and
  containment of the two documented upstream bugs
  (`net_stauts` typo, stale `get_device_properties` and unparsed
  `property/post`).
- **Architectural pattern:** three one-way layers (entities →
  coordinator → adapter) enforced by `tests/tools/check_imports.py`,
  replacing the previous hexagonal ports-and-adapters framing
  (`adr/0002-boundary-not-hexagonal.md`).
- **Error taxonomy:** single `ClientError` hierarchy with
  `AuthError`, `TransientError` (incl. `RateLimited`),
  `PermanentError`, `ValidationError`, `ProtocolError`
  (`adr/0003-error-taxonomy.md`).
- **Testing strategy:** traceability is a convention (review-time
  warning only), not a CI gate. Coverage thresholds lowered from
  `≥ 90 %/≥ 85 %` to `≥ 85 %/≥ 80 %` overall; `adapter.py` and
  `coordinator.derive_vacuum_state` held at 100 %
  (`adr/0004-testing-strategy.md`).
- **Requirements namespaces** renamed for clarity:
  - `FR-A` (Account) — includes `FR-A-10` rate-limit tolerance on
    reauth.
  - `FR-RG` (Region) — five region-routing requirements including
    endpoint snapshot persistence.
  - `FR-MG` (Migration) — five requirements, including
    `async_migrate_entry` v1→v2 and unique-id re-key
    (`FR-MG-1..5`).
  - `FR-OF` (Offline) — five offline-semantics requirements.
  - `FR-UP` (Updates) — push/poll semantics, monotonic HA-side
    receipt ordering (`FR-UP-5`), resync on reconnect
    (`FR-UP-6`).
- **NFR-R-6** added: broker-CA rotation surfaces a `repair` issue
  rather than silently falling back to `tls_insecure_set(True)`.
- **SEC-3** scoped: private-API access to `karcher-home` is
  permitted only inside `adapter.py`; the prohibition is hard
  everywhere else and enforced by `check_imports.py`.
- **License reverted to MIT.** An earlier draft of the rewrite
  carried an Apache-2.0 `LICENSE` (with the copyright placeholder
  unfilled) plus matching `pyproject.toml`, `README.md`, and
  `CONTRIBUTING.md` claims. This was an unintentional drift from the
  original repo's MIT licence; restored on continuity grounds. Aligns
  with `karcher-home` upstream (also MIT) and avoids Apache-2.0
  compliance overhead (NOTICE, patent grant) without a real benefit
  for a small HACS integration.

### Deprecated

### Removed
- **ADRs 0005..0011** (`secrets-and-reauth`, `error-taxonomy`
  duplicate, `room-selection-contract`,
  `diagnostics-and-silver-quality`, `matter-contract`,
  `testing-strategy`, `in-tree-cloud-client`,
  `hexagonal-architecture`). Survivors renumbered into the four-ADR
  set above; retired rationale folded into the main spec files
  (reauth policy into `05-security-threat-model.md` §4, room
  selection into `02-requirements.md` `FR-V`/`FR-SL`, diagnostics
  into `09-roadmap-and-backlog.md` Phase 4, Matter contract into
  `02-requirements.md` `FR-AH`).
- **Claude reviewer agents:** `solid-reviewer`, `security-reviewer`,
  `design-reviewer`, `ha-reviewer`, `pr-reviewer`. Their checklists
  are absorbed into `/review`.
- **Claude skills:** `security-review`, `simplify`, `solid-check`.
  Absorbed into `/review`.
- **Traceability CI job** and
  `tests/tools/check_traceability.py`. Traceability remains as a
  docstring convention surfaced by `check_docs.py` at review time.
- **Python 3.13** from the CI matrix; HA targets Python 3.12 in the
  supported release range.
- `aiomqtt`, `pydantic`, `cryptography` from runtime dependencies —
  all owned by `karcher-home`.
- `mutmut` from dev dependencies — promoted to a cross-cutting
  backlog item (`X-5`), not a CI gate.

### Fixed
- `pip-audit --strict` is now actually strict: the trailing
  `|| true` has been removed from the CI step.
- HACS and HA versions are pinned in CI rather than floating
  (`hacs/action@22.5.0`; HA `2025.1.0` + `2025.10.0` matrix).

### Security
- Reauth policy documented (`05-security-threat-model.md` §4):
  vendor 429s surface as `TransientError`, not `AuthError`; region
  and `device_id` are preserved across reauth; `Retry-After` honoured
  up to a 60 s ceiling.
- CA-rotation graceful degradation (`NFR-R-6`,
  `05-security-threat-model.md` §5): on fingerprint mismatch, the
  adapter raises `TransientError`, the coordinator raises
  `UpdateFailed`, and a persistent HA `repair` issue
  (`ca_rotation_required`) is created — never a silent insecure
  fallback.

---

## Releases

<!-- Release entries go here when tags are cut. Template:

## [2.0.0] — YYYY-MM-DD

### Added
- … (FR-A-1, FR-V-1)

### Changed
- …

### Security
- … (SEC-*)

-->
