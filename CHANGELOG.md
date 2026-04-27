# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries under `[Unreleased]` are grouped by `Added`, `Changed`,
`Deprecated`, `Removed`, `Fixed`, `Security`. Every user-visible
change cites the `FR-*` / `NFR-*` / `SEC-*` / `OPS-*` IDs it
satisfies. Traceability is a convention, not a CI gate (ADR-0004).

## [Unreleased]

## Phase 1 — MVP (in progress)

### Added
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
