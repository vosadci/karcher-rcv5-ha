# 10 — Gap carry-over

Each gap in `doc/GAP_ANALYSIS.md` is one of:

- **Resolved by the rewrite** — the new architecture makes the gap
  impossible or trivially addressed. Listed with the resolution
  mechanism.
- **Addressed in a phase** — the gap becomes a concrete backlog
  item; the phase is named.
- **Persists** — the gap is a platform- or device-level issue the
  rewrite cannot fix. Documented; no work item.

## 1. Divergences from original intent

| GAP | Status | Notes |
|---|---|---|
| 1.1 `coordinator.async_setup()` pending in plan, implemented in code | **Resolved** | `04-architecture.md` §6 enshrines the setup-ordering; the adapter's subscribe-before-poll sequence is covered by contract tests |
| 1.2 `conftest.py` mock inconsistency | **Resolved** | New test harness in Phase 0; fresh fixtures (`06-test-strategy.md` §4) |
| 1.3 Room list not persisted across restarts | **Addressed Phase 3** | Phase 3 stores the room list in `hass.helpers.storage.Store` under `karcher_home_robots.{sn}.rooms` and loads before first refresh; unavailability window collapses to the first MQTT push after restart |
| 1.4 Map image entity not implemented | **Addressed Phase 5** | Explicitly deferred; protocol work already complete in `doc/` |
| 1.5 Diagnostics entity not implemented | **Addressed Phase 4** | FR-D-1, FR-D-2; Silver quality cannot declare early |
| 1.6 MQTT reconnect exponential backoff not implemented | **Resolved** | FR-UP-6 — reconnect is `karcher-home`'s responsibility; the adapter re-subscribes and forces a `fetch_properties` on reconnect |
| 1.7 `quality_scale: "silver"` premature | **Resolved** | `manifest.json` declares `bronze` until Phase 4 exit; the phase-4 DoD enforces accuracy (`09-roadmap-and-backlog.md` Phase 4) |

## 2. Implicit decisions

| GAP | Status | Notes |
|---|---|---|
| 2.1 `room_ids = []` fallback silently incorrect | **Addressed Phase 3** | Documented in FR-SL — when no rooms are known, the start command is blocked and a log at WARNING names the condition; the UI surface can be extended with a repair step later |
| 2.2 `tls_insecure_set(True)` accepted | **Resolved** | SEC-4; `karcher-home` pins to bundled CA; `tls_insecure_set` banned by pygrep and ruff |
| 2.3 `device_id` vs `sn` distinction undocumented | **Resolved** | `04-architecture.md` §11 documents unique-ID strategy; the integration-owned `DeviceProperties` dataclass field comments cite PROTOCOL.md |
| 2.4 `model = device.product_id.name` couples to lib enum | **Resolved** | Model string is derived inside `entity.py` via a static `MODEL_BY_PRODUCT_ID` map in `const.py`; `karcher-home`'s enum name is not surfaced |
| 2.5 `wind` alongside `fan_speed` duplicate | **Addressed Phase 2** | Vacuum `extra_state_attributes` drops `wind`; backwards-compat note in the upgrade notes |
| 2.6 `CMD_LOCATE` not hardware-verified | **Addressed Phase 1** | Backlog X-2; HIL attestation in the Phase-1 HIL run |
| 2.7 Error sensor logic non-obvious | **Resolved** | FR-BS-1 makes the derivation explicit; `coordinator.derive_vacuum_state` owns the logic; the binary sensor reads `vacuum_state == Error` directly |

## 3. Behaviour undefined or untested

| GAP | Status | Notes |
|---|---|---|
| 3.1 `current_map_id` change invalidation | **Addressed Phase 3** | FR-SL-7; contract test `test_current_map_id_change.py` |
| 3.2 Multiple simultaneous MQTT pushes | **Resolved** | `karcher-home`'s paho thread delivers on one callback; the adapter serialises re-entry via `loop.call_soon_threadsafe`; coordinator is single-task |
| 3.3 Robot with no stored map at first setup | **Addressed Phase 3** | Integration test `test_select_room.py::test_empty_rooms` (backlog P3-8) |
| 3.4 Reauth with device removed from account | **Addressed Phase 4** | Reauth robustness tests (P4-4); the config-entry surface distinguishes "auth OK but device missing" → `SETUP_ERROR` with a user-facing message |
| 3.5 `fetch_properties()` timeout behaviour | **Resolved** | Adapter's `fetch_properties` raises `TransientError` on 5 s timeout; covered by `test_fetch_properties_timeout.py` |
| 3.6 OTA check timing mid-session | **Persists (platform)** | The robot restarts during OTA; reconnect logic treats this as a disconnect and recovers. No integration-level action possible. Documented |
| 3.7 `clean_type` field semantics unknown | **Persists (protocol)** | Backlog item X-1; set to 0 unchanged; test verifies the wire value |

## 4. Test-coverage gaps

Gaps 4.* in the original table all become acceptance items in Phases
1–4:

- `async_locate()` test → Phase 1 (P1-15 HIL set).
- No-rooms startup path → Phase 3 (P3-8).
- `fetch_properties()` timeout → Phase 1 (P1-4 contract tests).
- `current_map_id` change → Phase 3 (P3-6).
- Error sensor in cleaning+fault → Phase 1 (P1-11).
- Two-device config-entry isolation → cross-cutting X-3, required by
  NFR-SC-1.
- Binary sensor with `None` coordinator data → Phase 1 (P1-14
  integration tests).

## 5. Documentation gaps

| GAP | Status |
|---|---|
| `find_device` APK-inferred only | `doc/PROTOCOL.md` updated at Phase-1 HIL pass; re-annotated "hardware-verified 2026-…-…" |
| `room_ids=[]` empty-list behaviour cross-reference | FR-SL in `02-requirements.md` is the canonical source; `vacuum.py` cites it |
| `clean_type` field semantics | `adapter.py` translation cites PROTOCOL.md §5 and backlog X-1 |
| `device_id` vs `sn` | Integration-owned `DeviceProperties` dataclass comments |
| `quality_scale` justification | Phase DoD enforces accuracy (`09-roadmap-and-backlog.md` Phase 4); release notes carry the statement |

## 6. Issues resolved that were not in GAP_ANALYSIS

New issues uncovered while drafting these specs:

- The current repo's `api.fetch_properties` uses `last_update_time`
  as its freshness sentinel, but the coordinator's
  `_async_update_data` does not. A race between push and poll can
  overwrite a newer push with an older poll. The rewrite's NFR-R-5
  and FR-UP-5 handle this explicitly via monotonic HA-side receipt
  timestamps (`04-architecture.md` §6).
- The current repo's `api.get_rooms` swallows every exception and
  returns `[]`. This masks real auth errors (token expired → empty
  rooms → confusing "no rooms" state). The adapter translates auth
  errors to `AuthError` (ADR-0003) and only swallows
  `ValidationError` to empty-list.
- `model = "RCV5"` is hardcoded in the UI; if 3iRobotix assigns a
  new product-ID value, the current code would create a new device
  entry because `product_id.name` would change. The rewrite uses a
  static `MODEL_BY_PRODUCT_ID` map in `const.py`.

Each of these has a named test in `06-test-strategy.md`.
