# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries are grouped by `Added`, `Changed`, `Deprecated`, `Removed`,
`Fixed`, `Security`. Older phase entries also cite the `FR-*` / `NFR-*`
/ `SEC-*` / `OPS-*` IDs they satisfy; traceability is a convention, not
a CI gate (ADR-0004).

## [Unreleased]

### Phase: 6 — Map polish, reconnect hardening, and pinch-zoom/pan

### Added
- Localization: full Romanian, German, French, Italian, and Spanish translations for
  every Home Assistant string and all Lovelace card text; each loads automatically when
  the Home Assistant language matches.
- Lovelace card map: pinch-zoom and pan — two-finger pinch, ctrl/trackpad zoom, and
  one-finger drag once zoomed — with a reset-zoom button and directional edge shadows.
- Lovelace card map: the robot icon now animates, gliding along the cleaning path with
  smoothed heading and pulsing while cleaning, returning, or relocalizing.
- Map now shows area carpets (rugs), matching the app's rendering.
- Map now marks detected objects (wire, shoe, sock, pet, pet waste, scale, chair) with
  distinct icons that stay crisp at any zoom.
- Per-room cleaning preferences: cleaning order, custom-settings on/off, and per-room
  cleaning mode and suction. Entities appear automatically as rooms are discovered.
- Standard / Customise mode is now persisted on the robot and restored on load, matching
  the Kärcher app.
- Room area (m²) shown under each room name on the card.
- `set_room_preference` / `set_room_selection` services accept an optional `device_id` to
  disambiguate multi-robot setups; ambiguous or unmatched calls now raise a clear error.
- Opt-in card debug footer (`show_debug`) showing the loaded card/HA versions and state.
- Accessibility: card segmented controls and tabs expose roles and pressed/label state to
  screen readers.
- Suction Station support: sensors for station-attached and emptying-in-progress, and a
  button to manually trigger an empty cycle — also on the Lovelace card's control row. The
  card's status line now shows "Emptying" while the station is running, instead of "Docked".

### Changed
- Lovelace card visual overhaul: four card sections (Status / Map / Controls / Settings),
  animated status dot, inline battery glyph, circle control buttons, inline segmented
  mode/suction/water controls, in-place expanding room rows, smooth carpet wash, curved
  path trail, and yellow accent highlighting.
- Fan-speed and water-level options are now populated from the entity's attribute lists
  and hidden when unavailable; room selects show plain room names.
- Polished the English and localized fault-code strings, removing machine-translation
  artifacts (cross-checked against the app).
- Devices now show their actual model (RCV 5, RCV 3, RCF 3) in Home Assistant instead of
  always reporting "RCV5".

### Fixed
- Apple Home "clean all rooms" cleaned only one room: a stale room selection silently
  filtered the start down to one room. Selection is now one-shot, and `vacuum.start` is
  whole-home for external callers (HAMH/Apple Home, voice assistants, automations).
- The "room names changed" repair issue could fire spuriously while the robot was
  relocalizing and then never clear. Detection is now serialized on the map-refresh path,
  ignores transient blank reads, and clears automatically when names return to normal.
- The error binary sensor no longer flags 21xx lifecycle codes (relocalizing, self-check)
  as faults, and now fires for genuine faults while paused.
- The card no longer renders blank when its configured vacuum entity is missing — it shows
  a warning naming the entity id.
- The Clean button now reads "Clean whole home" when every room is manually selected,
  matching the label already shown when none are selected.
- Card controls are now disabled while offline instead of dispatching commands that can't
  reach the robot.
- Re-foregrounding the iOS app no longer fires a spurious "connection lost" toast.
- Robot position and heading now update during return-to-dock and track the live path
  stream, removing map lag; `current_room_name` no longer flickers in doorways.
- The "Finished X ago" stat is suppressed while a job is in progress and uses the actual
  dock-transition time.
- Single-room preference edits no longer zero the material and carpet fields for every room.
- Map renders no longer serve a stale cached image; carpet AI detections render as labelled
  dots and room-cell decoding matches the app.
- Reconnect hardening: push traffic survives an MQTT client rebuild, a poll reply can no
  longer overwrite newer push data, and a failed setup no longer leaks the shared adapter.
- A robot model this integration's pinned library doesn't recognize could crash setup for
  every robot on the same cloud account. It now fails with a clear, permanent error naming
  the cause instead.
- Migration: a minimal v2 → v3 entry migration drops redundant keys so pre-v3 installs load.
- A robot that rejects or malforms a property request no longer looks silent: setup and
  polling report the robot's reason instead of "prop.get reply not received within 5s".
  The dock's own fields are asked for separately, so a robot without a Suction Station
  cannot take the whole poll down with them.

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
