# 06 — Test strategy

## 1. Principles

- **Fast by default, hardware opt-in.** The full default suite runs in
  under 30 s locally. Hardware-in-the-loop (HIL) tests live in
  `tests/hardware/` and are skipped unless `KARCHER_HIL=1` is set.
- **Deterministic.** No test may depend on wall time, network, or RNG
  without explicit seeding. `freezegun` is mandatory for any
  time-sensitive logic; `random.Random(seed)` for any stochastic
  path.
- **Record once, replay forever.** MQTT traffic is recorded once from
  the real broker (via `tools/capture-mqtt.py`), sanitised, and
  replayed in contract/integration tests. A HIL run regenerates the
  baseline when protocol drift is detected on a release candidate.
- **Traceability is a convention, not a gate.** See
  `adr/0004-testing-strategy.md`. Tests cite `Covers: FR-X-N` in
  docstrings where the link is obvious; `docs-check` warns on orphan
  requirement IDs at review time. CI does not fail on missing
  citations.

## 2. The pyramid

```
       ┌──────────────┐
       │    HIL (≈ 5) │  Opt-in; manual; per-release
       └──────────────┘
      ┌────────────────┐
      │  HA / E2E (~40)│  pytest-homeassistant-custom-component
      └────────────────┘
     ┌──────────────────┐
     │ Contract (~25)   │  adapter vs FakeKarcherClient + FakePahoClient
     └──────────────────┘
    ┌────────────────────┐
    │   Unit (~200)      │  derive_vacuum_state, adapter exception mapping,
    │                    │  typed DTOs, topic/ID generation
    └────────────────────┘
```

Counts are rough order-of-magnitude targets, not quotas.

## 3. Test types

### 3.1 Unit tests (`tests/unit/`)

Pure-Python, no HA, no I/O.

- `test_state_derivation.py` — `derive_vacuum_state()` for every
  combination of `work_mode × status × fault × charge_state` that the
  protocol specifies. Table-driven.
- `test_exception_mapping.py` — the adapter's mapping from
  `karcher-home` native exceptions and HTTP/MQTT error shapes to
  `ClientError` subclasses; every documented mapping has a row.
- `test_device_properties_dto.py` — translation from whatever
  `karcher-home` hands back into the integration-owned frozen
  `DeviceProperties` dataclass; missing / out-of-range fields raise
  `ValidationError`.
- `test_config_entry_migration.py` — `async_migrate_entry` from v1 to
  v2; includes the unique_id re-key path (FR-MG-3) and the migration
  failure path (FR-MG-5).
- `test_diagnostics_redaction.py` — FR-D-2: diagnostic payload
  against a regex of credential-shaped strings.

### 3.2 Contract tests (`tests/contract/`)

Adapter against a `FakeKarcherClient` (stands in for `karcher`)
and a `FakePahoClient` (stands in for the foreign-thread MQTT
callback path). HA is not involved.

- `test_auth_flow.py` — login → token → reauth on 401 → rate-limit
  surfaces as `TransientError` (FR-A-10).
- `test_subscribe_push.py` — subscribe → fake paho delivers a push on
  a foreign thread → `loop.call_soon_threadsafe` brings it into the
  loop → coordinator receives it.
- `test_reconnect_resync.py` — on reconnect, adapter re-subscribes
  and forces `fetch_properties` so UI is not stuck on stale data
  (FR-UP-6).
- `test_fetch_properties_timeout.py` — `prop.get` with no reply
  raises `TransientError` after 5 s (covers `GAP 3.5`).
- `test_current_map_id_change.py` — room list invalidation when
  `current_map_id` changes (covers `GAP 3.1`, FR-SL-7).
- `test_region_routing.py` — endpoint snapshot is populated on auth;
  reconnect after restart uses the snapshot (FR-RG-2, FR-RG-3).
- `test_ca_rotation_degradation.py` — a broker cert that no longer
  validates raises `TransientError` and triggers a `repair` issue,
  not a silent insecure fallback (NFR-R-6).
- `test_clock_skew_ordering.py` — push with a device-reported
  timestamp far in the past still arrives "after" an earlier push
  because we key on monotonic receipt time (FR-UP-5).

### 3.3 HA integration tests (`tests/integration/`)

Use `pytest-homeassistant-custom-component`. Tests assert HA-visible
behaviour: entity states, service calls, config-flow transitions,
reauth, setup retry.

- `test_config_flow.py` — all setup paths including `no_devices` and
  dedupe.
- `test_init_lifecycle.py` — setup → reload → unload leaves no
  tasks, no warnings, no sessions.
- `test_vacuum_entity.py` — activity transitions, start/stop/pause/
  dock, `app_segment_clean` via `send_command`, mop-mode fan-speed
  disable.
- `test_sensor_entities.py` — battery, area, time; unavailable when
  `coordinator.data is None`.
- `test_binary_sensor.py` — error on/off across the full state table,
  including transient fault during cleaning (FR-BS-2).
- `test_select_room.py` — including the empty-rooms path (covers
  `GAP 3.3`).
- `test_select_mode_water.py` — water-level entity disabled by
  default; mode changes reflect in water-level availability.
- `test_diagnostics.py` — FR-D-1, FR-D-2.
- `test_reauth.py` — token expiry triggers reauth; happy + failure
  paths; rate-limit surfaces as transient, not auth.
- `test_offline_semantics.py` — cloud unreachable → entities
  unavailable; commands while offline raise `HomeAssistantError`
  (FR-OF-2); no flap on a single failed poll (FR-OF-5).
- `test_migration_integration.py` — v1 entry migrates to v2; entity
  IDs stable (FR-MG-4).

### 3.4 Hardware-in-the-loop (`tests/hardware/`)

Opt-in, manual, **release-gated only**. Guarded by `KARCHER_HIL=1`
and `RCV5_SN`. Run by the maintainer at each release tag and on
protocol-change investigations. **Not** a per-PR or per-phase
gate (see `spec/08-definition-of-done.md` §2 item 4 for the
rationale; reference integrations in HA core operate the same way).

- `test_hil_command_roundtrip.py` — send `start`, observe state
  change to `Cleaning` within 2 s.
- `test_hil_room_clean.py` — `app_segment_clean` with a real room ID.
- `test_hil_locate.py` — robot beeps (manual attestation).
- `test_hil_reconnect.py` — kill the TCP session at the broker,
  observe reconnect within 30 s and push updates resuming.

## 4. Fixtures

### 4.1 Adapter-layer fixtures

| Fixture | Purpose |
|---|---|
| `fake_karcher_client` | Stand-in for the `karcher` class the adapter constructs. Every contract test gets one |
| `fake_paho_client` | Stand-in for the paho-mqtt callback path; tests can simulate foreign-thread delivery and disconnects |
| `recorded_capture` | Parameterised over `.jsonl` files in `tests/fixtures/captures/`; yields `(topic, payload)` tuples. Phase 0 ships *documented* captures derived from the literal payload blocks in `doc/PROTOCOL.md` (sanitised by reverse-engineering at the time they were written; see §4.3). The first **real** captures from the maintainer's robot are committed at the Phase 1 release per Phase 1 acceptance in `spec/09-roadmap-and-backlog.md`; documented captures stay in place as a contract baseline. |
| `fake_rest` | `aiohttp.test_utils.TestServer` with canned routes for `/login`, `/device/list`, `/map/data` — used when a test needs to bypass `karcher` entirely |

### 4.2 HA fixtures

Relies on `pytest-homeassistant-custom-component` defaults. Adds:

| Fixture | Purpose |
|---|---|
| `config_entry_v1` | Frozen v1 config entry for migration tests |
| `config_entry_v2` | Pre-migrated v2 config entry |
| `device_props_idle`, `..._cleaning`, `..._docked`, `..._error`, `..._paused` | Hand-constructed `DeviceProperties` for deterministic state tests |
| `two_devices` | Two config entries to validate `NFR-SC-1..3` isolation |

### 4.3 Capture provenance and lifecycle

Phase 0 ships `tests/fixtures/captures/*.jsonl` whose entries are
derived from the documented MQTT payload blocks in
`doc/PROTOCOL.md`. These payloads were sanitised at the time the
protocol notes were written (SNs, tokens, device IDs replaced with
synthetic equivalents) and are the closest the integration has to
real wire shapes without running HIL.

- File layout: one capture per documented scenario
  (`service_invoke_set_room_clean.jsonl`,
  `service_invoke_start_recharge.jsonl`,
  `prop_set_water_level.jsonl`,
  `event_property_post_idle.jsonl`,
  `event_property_post_cleaning.jsonl`, etc.). Each line is a JSON
  object `{"topic": "...", "payload": {...}, "direction": "tx"|"rx",
  "ts_offset_ms": <int>}`.
- Source: extracted by hand from `doc/PROTOCOL.md` §3 onward;
  the block is the source of truth at Phase 0.
- Ownership: Phase 0 captures are spec-traceable but are not
  evidence the wire shape works against real firmware. That
  evidence lands at the Phase 1 release.
- Phase 1 transition: when the maintainer runs the HIL set at the
  Phase 1 release tag (`spec/08-definition-of-done.md` §3), the
  recorded `tests/fixtures/captures/*.jsonl` files **augment**, not
  replace, the documented Phase 0 captures. A documented capture
  whose shape diverges from a recorded capture is a finding for
  `doc/PROTOCOL.md` (the protocol doc was wrong) and a PR that
  updates both files in lockstep.
- No PII or live tokens are permitted in either documented or
  recorded captures. The pre-commit `forbidden-strings` hook and
  the CI secret-grep cover this layer too.

## 5. CI gates

Run on every PR (see `.github/workflows/ci.yml`):

1. `ruff check` and `ruff format --check` — **blocking**.
2. `mypy --strict custom_components/karcher_home_robots` — **blocking**.
3. `pytest tests/ --cov=custom_components/karcher_home_robots` — **blocking**.
4. Coverage gates per phase (see §6) — **blocking from Phase 1
   onwards; suspended in Phase 0**. The current phase is declared in
   `pyproject.toml` `[tool.karcher]` `phase`; the wrapper
   `tests/tools/coverage_gate.py` reads it and feeds the right
   `--cov-fail-under` and per-file thresholds to coverage.
5. `python tests/tools/check_imports.py` (layer boundary) —
   **blocking**.
6. `python tests/tools/check_docs.py --strict` — **blocking**.
7. `pip-audit --strict` — **blocking**.
8. HACS validation — **not run in CI** for unregistered repos (the
   `hacs/action` validator returns `None` for the manifest in PR
   context, producing false positives). Validation is run manually at
   release time (see `spec/08-definition-of-done.md` §3 item 6).
9. `hassfest` action — **blocking**.

Traceability: **not** a CI gate. `docs-check` warns on orphaned IDs
at review time but does not fail the build.

## 6. Coverage targets

Targets are graduated per phase. Phase 0 ships only stubs and
scaffolding; the gate is suspended. From Phase 1 the gate is
blocking, with both an overall floor and per-file floors. The
current phase is the single source of truth in `pyproject.toml`
`[tool.karcher]` `phase`; the wrapper `tests/tools/coverage_gate.py`
maps it to thresholds. Bumping the phase is a one-line PR.

### 6.1 Per-phase floors

All values are lines % / branches %. `coordinator.py` covers
`derive_vacuum_state` (it lives in that file). Entity files are
`vacuum.py`, `sensor.py`, `binary_sensor.py`, `select.py` — each
tracked individually; the floor shown applies to every one of them.
The gate script (`tests/tools/coverage_gate.py`) is authoritative;
this table is a human-readable summary.

| Phase | Overall | `adapter.py` | `coordinator.py` | `config_flow.py`, `diagnostics.py` | Entity files |
|---|---|---|---|---|---|
| 0 | suspended | n/a (stubs) | n/a | n/a | n/a |
| 1 | ≥ 70 / ≥ 60 | ≥ 90 / ≥ 90 | ≥ 90 / ≥ 90 | ≥ 80 / ≥ 75 | ≥ 75 / ≥ 70 |
| 2 | ≥ 80 / ≥ 70 | ≥ 95 / ≥ 95 | ≥ 95 / ≥ 95 | ≥ 90 / ≥ 85 | ≥ 85 / ≥ 80 |
| 3 | ≥ 85 / ≥ 80 | 100 / 100 | 100 / 100 | ≥ 95 / ≥ 90 | ≥ 90 / ≥ 85 |
| 4+ | ≥ 85 / ≥ 80 | 100 / 100 | 100 / 100 | ≥ 95 / ≥ 90 | ≥ 90 / ≥ 85 |

Phase-graduated floors **do not** mean "drop test discipline early
phases". They mean the *blocking gate* graduates; PRs that lower
coverage still need a reason in review even when the gate would
pass numerically. Coverage at phase exit is reported in the phase
DoD (`spec/08-definition-of-done.md` §2).

### 6.2 Suspended-gate hygiene (Phase 0 only)

While the gate is suspended:

- Stub methods (`raise NotImplementedError`) carry a single
  `# pragma: no cover` line. No other use of the pragma is permitted.
- `make test-cov` still runs and prints the report; it does not
  fail. CI uploads the report as an artefact.
- A green CI run with 12 % coverage in Phase 0 is acceptable;
  the same run in Phase 1 fails the gate.

## 7. Flakiness policy

A test that fails once on `main` is reopened the same day. Two flakes
in one week trigger a quarantine (`@pytest.mark.flaky`) and a
tracking issue. No test stays quarantined for more than one sprint.

## 8. Manual / exploratory tests

For each new entity or command added in a phase, the PR description
includes a manual-test checklist that a reviewer runs on their own
hardware before approving.

## 9. Dependency testing

- Dependabot opens grouped patch-bump PRs weekly (see
  `.github/dependabot.yml`).
- Major updates of `karcher-home` require a HIL run before merge.
- Major updates of HA or test dependencies require the full CI matrix
  plus one HIL smoke run.
