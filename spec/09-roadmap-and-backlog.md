# 09 — Roadmap and backlog

Phase numbering starts at 0 (scaffold). Phases 1..5 are user-visible;
Phase 0 is internal. Each phase has:

- **Goal** — one-line summary.
- **Acceptance** — the set of conditions under which the phase exits.
- **Backlog** — concrete work items, each tractable in a single PR.

Estimates are deliberately not included — they are a function of
throughput, not scope. Cadence is "phase exits when DoD passes", not a
calendar deadline.

## Phase 0 — Scaffold

**Goal.** Establish the empty project able to run CI green with zero
functionality.

**Acceptance.**

- A new package `custom_components/karcher_home_robots/` exists with
  the layout from `04-architecture.md` §2 (including empty
  `adapter.py`).
- `manifest.json` declares `quality_scale: bronze`,
  `iot_class: cloud_push`, version `2.0.0-alpha.1`. The version
  string is a placeholder in the file only — Phase 0 is internal
  and **no Phase 0 release tag is cut** (per
  `spec/08-definition-of-done.md` §3.0). The first user-visible tag
  is `v2.0.0` at Phase 1 exit; the Phase 1 release PR bumps the
  manifest version from `2.0.0-alpha.1` to `2.0.0` and creates the
  tag.
- `ruff`, `ruff format`, `mypy --strict`, `pytest`, `pip-audit`,
  `check_imports`, `check_docs --strict`, HACS validation, and
  `hassfest` all pass on an empty integration (`async_setup_entry`
  returns `True` unconditionally, no entities).
- `pyproject.toml`, `.pre-commit-config.yaml`,
  `.github/workflows/ci.yml`, `.github/workflows/release.yml`,
  `.github/dependabot.yml` committed.
- `karcher-home` is declared as a runtime dependency pinned to an
  exact version (`==X.Y.Z`, not a range; bumps go through dependabot
  + HIL gate per CONTRIBUTING.md). Adapter module exists with type
  stubs only.
- Four ADRs committed in `adr/`.
- `custom_components/karcher_home_robots/quality_scale.yaml` exists
  and declares every Bronze/Silver/Gold/Platinum item as `done`,
  `todo`, or `exempt` with a one-line justification, mirroring the
  per-item structure used by HA core integrations
  (e.g. `homeassistant/components/roborock/quality_scale.yaml`). At
  Phase 0 most items are `todo`.

**Backlog.**

- P0-1: New package skeleton and empty HA lifecycle
  (`async_setup_entry` / `async_unload_entry` return `True`).
- P0-2: `pyproject.toml`, dev deps, `pytest.ini` equivalent in
  `[tool.pytest.ini_options]`.
- P0-3: CI workflow with all gates wired (most have nothing to check
  yet).
- P0-4: Release workflow (`.github/workflows/release.yml`).
- P0-5: Pre-commit hook config + secret-scan regex patterns.
- P0-6: `.github/PULL_REQUEST_TEMPLATE.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`.
- P0-7: `tests/tools/check_imports.py`, `tests/tools/check_docs.py`.
  `check_imports.py` is rewritten in this phase to enforce two rules:
  (a) only `adapter.py` imports `karcher`; the `cloud/`-package
  shape from earlier drafts is removed; and (b) inside `adapter.py`,
  every `_`-prefixed access against a `karcher` symbol must match an
  entry in the `ALLOWED_PRIVATE_API` constant defined in the
  checker, which is the operational mirror of the table in
  `spec/03-constraints-and-deltas.md` §3.1. Adding a private symbol
  requires updating the constant, the spec table, and the call site
  in the same PR. The check is AST-based; computed `getattr(...)`
  with non-literal names is rejected.
- P0-9: `adapter.py` type stubs (methods defined, bodies
  `raise NotImplementedError`) so the rest of the package can be
  type-checked in isolation.
- P0-10: `quality_scale.yaml` scaffolded with every item declared
  (`done` / `todo` / `exempt` + one-line note). Tier claims in
  `manifest.json` may not exceed what this file marks `done`; a
  release-time check enforces it (added to
  `.github/workflows/release.yml`).
- P0-11: `tests/fixtures/captures/*.jsonl` extracted from the
  documented payload blocks in `doc/PROTOCOL.md` per
  `spec/06-test-strategy.md` §4.3. One file per documented
  scenario; format is one JSON object per line with `topic`,
  `payload`, `direction`, `ts_offset_ms`. These are the contract-
  test substrate from Phase 0; real recorded captures from the
  Phase 1 release tag augment, not replace, them.
- P0-12: Copy `img/icon.png` and `img/icon.svg` into
  `custom_components/karcher_home_robots/` at scaffold time, and place
  `icon.png` in the `brand/` subdirectory. Convention follows the
  prior implementation. The seed's `img/` remains the source of truth;
  the in-package files are a copy-on-scaffold mirror that ships in the
  HACS zip. Since HA 2026.3.0 the frontend reads `brand/icon.png`
  directly from the package — no brands repo PR required (see P4-10).

## Phase 1 — MVP

**Goal.** Ship the minimum useful integration: vacuum entity + battery
sensor + error indicator, using the `karcher-home` adapter.

**Acceptance.**

- FR-A-1..10, FR-V-1..10 (no room selection yet — `room_ids` passes
  `[]` when idle; documented as Phase-3 improvement), FR-SE-1, FR-SE-4,
  FR-BS-1..3, FR-UP-1..6, and NFR-P / NFR-R / NFR-M / SEC-* met and
  tested.
- Adapter passes all contract tests (`tests/contract/`).
- `quality_scale` remains `bronze` (diagnostics not shipped yet).
- A user can install from HACS, configure, see the robot state change
  in HA within 2 s of a physical state change.
- `tools/capture-mqtt.py` produces a replayable capture; the
  release tag commits the first **real** captures recorded from
  the maintainer's robot to
  `tests/fixtures/captures/`. They augment the documented Phase 0
  captures (P0-11); divergences trigger a `doc/PROTOCOL.md` patch
  in the same PR per `spec/06-test-strategy.md` §4.3.
- Release tag `v2.0.0`. HIL is **not** a phase-exit gate
  (`spec/08-definition-of-done.md` §2 item 4); it is a release-tag
  gate (`spec/08` §3 item 3). The release that closes Phase 1
  carries the HIL run.

**Backlog.**

- P1-1: `adapter.py` — async wrapper around `karcher-home`; blocking
  calls via `run_in_executor`; paho-mqtt foreign-thread bridge via
  `loop.call_soon_threadsafe`; `ClientError` exception mapping;
  work-arounds for the two upstream bugs (`net_stauts` typo and stale
  `get_device_properties` / unparsed `property/post`).
- P1-2: `exceptions.py` — `ClientError` hierarchy (see
  `adr/0003-error-taxonomy.md`).
- P1-3: Integration-owned frozen `DeviceProperties` dataclass +
  `karcher-home` → DTO translation.
- P1-4: Adapter unit + contract tests (auth, subscribe/push,
  reconnect-resync, fetch timeout, rate limit).
- P1-5: `coordinator.py` — setup sequence, push/poll reconciliation,
  monotonic-timestamp ordering (FR-UP-5), race resolution (NFR-R-5),
  command/property methods, offline semantics (FR-OF).
- P1-6: `coordinator.derive_vacuum_state` + full table of derivation
  unit tests.
- P1-7: `config_flow.py` — region + credentials + (optional) device
  pick; reauth path including rate-limit tolerance (FR-A-10);
  translations.
- P1-8: `entity.py` — base class; `device_info`; availability.
- P1-9: `vacuum.py` — start / stop / pause / return_to_base / locate;
  `activity` property; minimum attributes.
- P1-10: `sensor.py` — battery only in this phase.
- P1-11: `binary_sensor.py` — error indicator (FR-BS-1..3).
- P1-12: `__init__.py` — `async_setup_entry`, `async_unload_entry`,
  reload on options change.
- P1-13: `strings.json` — English text for all user-visible strings.
- P1-14: `tests/integration/*` — HA-loop tests for the above.
- P1-15: HIL test set for MVP — written and committed under
  `tests/hardware/`; opt-in via `KARCHER_HIL=1` per
  `spec/06-test-strategy.md` §3.4. Run by the maintainer at the
  release that closes the phase, **not** as a phase-exit gate.
- P1-16: Docs — `README.md` user-facing; `doc/PROTOCOL.md` updated if
  anything was newly observed.

## Phase 2 — Feature parity: sensors and selects

**Goal.** Reach functional parity with the current integration except
for room selection and diagnostics.

**Acceptance.**

- FR-SE-2, FR-SE-3, FR-V-8, FR-SL-4..6 implemented and tested.
- Cleaning-mode and water-level selects behave per spec including
  availability logic.
- Release tag `v2.1.0`.

**Backlog.**

- P2-1: Cleaning-area sensor.
- P2-2: Cleaning-time sensor.
- P2-3: Cleaning-mode select (`prop.set mode ∈ {0,1,2}`).
- P2-4: Water-level select (`entity_registry_enabled_default=False`;
  unavailable when mode is Vacuum-only).
- P2-5: Fan-speed on vacuum; disabled in mop-only (FR-V-8).
- P2-6: Contract tests for `prop.set` encoding paths.
- P2-7: Integration tests for mode/water availability interactions.

## Phase 3 — Rooms, region routing, Apple Home

**Goal.** Room selection, `app_segment_clean`, region-endpoint
snapshot, and Roborock-format room exposure for HAMH.

**Acceptance.**

- FR-V-1..3, FR-V-11, FR-V-12, FR-SL-1..3, FR-SL-7, FR-AH-1..3,
  FR-RG-1..5 implemented.
- `current_map_id` change invalidates rooms per FR-SL-7.
- Region endpoint snapshot is populated on auth and used on restart
  (FR-RG-2, FR-RG-3).
- Release tag `v2.2.0`.

**Backlog.**

- P3-1: `adapter.get_rooms()` wired through the coordinator.
- P3-2: `select.room`.
- P3-3: Vacuum `async_start` consumes the selected room (FR-V-1..3).
- P3-4: `send_command("app_segment_clean", [room_ids])`.
- P3-5: Roborock-format rooms in `extra_state_attributes`.
- P3-6: `current_map_id` change handler (FR-SL-7).
- P3-7: Region endpoint snapshot storage + use on restart.
- P3-8: Integration test for empty-rooms path (covers `GAP 3.3`).

## Phase 4 — Hardening to Silver (closed 2026-05-02)

**Goal.** Meet HACS Silver: diagnostics, migration, reauth robustness,
CA-rotation graceful degradation, observability.

**Acceptance.**

- FR-D-1, FR-D-2 implemented.
- FR-MG-1..5 implemented; `async_migrate_entry` v1→v2 tested
  end-to-end, including upgrade from the legacy
  `karcher_home_robots` install.
- Reauth tested against three failure modes: wrong password, account
  removed, token permanently revoked.
- NFR-R-6 implemented: a broker-CA rotation surfaces a `repair` issue,
  not silent insecure fallback.
- `manifest.json` declares `quality_scale: silver`.
- Release tag `v2.3.0`.

**Why quality_scale is gated on this phase.** HACS Silver requires
diagnostics and a working migration path. Declaring `silver` before
FR-D-1 and FR-MG-1..5 land would violate HACS's own rules and break
trust with users. `bronze` is the honest claim until this phase exits.

**Backlog.**

- P4-1: `diagnostics.py` per FR-D-1..2.
- P4-2: `async_migrate_entry` v1→v2 (FR-MG-2, FR-MG-3, FR-MG-5).
- P4-3: Migration integration test (FR-MG-4) — upgrade a v1.x config
  fixture to v2.3.0 and assert entity continuity.
- P4-4: Reauth robustness tests.
- P4-5: SBOM workflow on release.
- P4-6: `tools/rotate-ca-cert.py` and the graceful-degradation
  handler (NFR-R-6).
- P4-7: Quality-scale badge update; HACS validation run.
- P4-8: `/review` on the release branch; no outstanding blockers.
- P4-9: User-facing migration notes in `CHANGELOG.md` and release
  notes.
- P4-10: ~~Submit brand-icon entry to `home-assistant/brands`.~~
  **Done — no PR needed.** Since HA 2026.3.0 the frontend reads
  `brand/icon.png` directly from the integration package; the brands
  repo no longer accepts PRs for custom integrations. The
  `custom_components/karcher_home_robots/brand/icon.png` shipped at
  P0-12 is served automatically for users on HA ≥ 2026.3. Users on
  2026.1–2026.2 (our stated minimum) will not see the icon, but that
  is a minor gap — the integration functions correctly without it.
- P4-11: Persistent `repair` issue after 1 h of continuous cloud
  outage (FR-OF-6, FR-OF-7). Add `OUTAGE_REPAIR_THRESHOLD` constant
  to `coordinator.py`; create/dismiss the issue in
  `_async_update_data`; integration test for create and auto-dismiss.
- P4-12: Log-spam throttle during outage (FR-OF-8). First failure
  logs at WARNING with traceback; subsequent failures log at INFO, one
  line per 10 min after the first 5 min of continuous failure.
  Transition (online→offline, offline→online) re-logs the full
  traceback.

## Phase 5 — Map image (optional)

**Goal.** Render the robot's floor plan as an `ImageEntity`. Purely
additive; no behaviour change to existing entities.

**Acceptance.**

- Map image entity renders the occupancy grid + robot + charger
  markers.
- Lovelace Xiaomi Vacuum Map Card calibration points exposed.
- Refresh on `Cleaning → Docked` transition and on a 5 min background
  interval.
- Release tag `v2.4.0`.

If the map-parsing code grows beyond ~300 LoC or pulls in image
libraries (`pillow`, `numpy`) that are not justified for the rest of
the integration, factor it into a separate library
`vacuum-map-parser-karcher` on PyPI, mirroring HA core's
`vacuum-map-parser-roborock` split. The integration then depends on
that library at an exact pin, the same as `karcher-home`.

Phase 5 backlog is intentionally thin at this stage; it is re-planned
at Phase 4 exit.

## Cross-cutting backlog

Items that do not belong to any single phase:

- X-1: Investigate whether `clean_type != 0` has useful semantics
  (`GAP 3.7`).
- X-2: Document `find_device` verification against hardware
  (`GAP 2.6`).
- X-3: Scheduled integration run against a two-device test account
  (NFR-SC-1..3).
- X-4: Track `karcher-home` upstream; if the library offers a clean
  public API for the two worked-around bugs, revisit the adapter
  work-around code and simplify.
- X-5: Evaluate `mutmut` mutation testing on
  `coordinator.derive_vacuum_state` and the adapter exception mapper
  quarterly; not a CI gate.
- X-6: HAMH compatibility smoke test — pair with a HAMH Docker container,
  start a room clean via Matter, verify the vacuum transitions to Cleaning.
  Requires HAMH infrastructure; descoped from P3-9 on 2026-05-01 because
  no container environment is available. Not a CI gate.
