# 03 — Constraints and deltas from current repo

This document carries forward the constraints in `doc/CONSTRAINTS.md`
and records where the rewrite changes them. The authoritative list is
here, not in the original file, for anything consumed by Phase-0+ work.

Constraint type: **H** hard (cannot be relaxed without changing the
device, the cloud, or the deployment target); **S** soft (current
decision, can be revisited through a new ADR).

## 1. Physical device

Carried forward verbatim from `doc/CONSTRAINTS.md §1`: 2.4 GHz only;
no open TCP ports; no local control API; MQTT broker cert pinning on
the device against `server.bks`; encrypted firmware (RV1126 TrustZone);
single robot per MQTT session.

No deltas. These are properties of the hardware.

## 2. Cloud platform (3iRobotix)

Carried forward from `doc/CONSTRAINTS.md §2`.

| Constraint | Type | Change from current repo |
|---|---|---|
| All control is MQTT; no REST command endpoints | H | Same |
| Broker: `eu-gamqttaiot.3irobotix.net:8883` (EU); US/CN equivalents | H | Same |
| TLS 1.2, cipher ECDHE-RSA-AES256-GCM-SHA384 | H | Same |
| Self-signed server cert, `*.3irobotix.net`, 3iRobotix CA | H | **Delta:** `karcher-home` validates against the bundled 3iRobotix CA rather than `tls_insecure_set(True)`. If the CA rotates and validation fails, the adapter surfaces `TransientError` and the coordinator marks the entity unavailable — it does **not** silently fall back to insecure TLS. See NFR-R for the degradation contract. |
| REST API for auth and map data only | H | Same |
| REST signing `MD5(token + timestamp + nonce + body)` | H | Handled by `karcher-home` |
| Tenant ID `1528983614213726208` hardcoded | H | Same |
| No token refresh mechanism | H | Same; auth must be replayed on 401/403 — see FR-S reauth behaviour |
| OTA check on every MQTT connection | H | Same |
| MQTT QoS 0 fire-and-forget | H | Same |
| Map data via REST, protobuf `RobotMap` | H | Same |

## 3. Cloud client library

The rewrite **keeps** `karcher-home` as the wire-protocol
implementation. See `adr/0001-library-adapter.md` for the reasoning.
The integration wraps it through a single `adapter.py` module.

| Constraint | Type | Detail |
|---|---|---|
| `karcher-home` dependency | H | Pinned to an exact version (`==X.Y.Z`) in both `pyproject.toml` and `manifest.json` `requirements`. Ranges are forbidden — bumps go through dependabot, are reviewed PRs, and require an HIL pass. This mirrors HA core's discipline (e.g. `python-roborock==5.5.1` in `homeassistant/components/roborock/manifest.json`). |
| Mixed sync/async library API | H | `karcher-home` has a mixed API: `login`, `get_devices`, `get_map_data`, `close`, and `create` are async coroutines and are awaited directly; `subscribe_device`, `unsubscribe_device`, MQTT publish, and the `fetch_properties` round-trip are synchronous and run in the executor via `async_add_executor_job`. No blocking call reaches the event loop directly. |
| paho-mqtt foreign-thread callbacks | H | `karcher-home` uses paho-mqtt; callbacks arrive on a background thread. The adapter re-enters the event loop exclusively through `loop.call_soon_threadsafe`. Coordinator state is never mutated from the mqtt thread. |
| Private-API access | H | Permitted **only inside `adapter.py`** and **only against an explicit allowlist** (see §3.1). Each call site carries an inline `# private-api: <justification>` comment. `tests/tools/check_imports.py` enforces both rules: no private access outside `adapter.py`, and no private access inside `adapter.py` that is not in the allowlist constant. Adding a symbol requires a PR that updates the allowlist, the spec table, and the call site. |
| Known upstream bugs to work around | S | Four, all patched inside the adapter: (a) the `net_stauts` typo causing `AttributeError` on nested access; (b) `get_device_properties()` returns stale cache when already subscribed, and the `thing/event/property/post` topic is not parsed automatically; (c) `KarcherHome.create()` has no `region=` parameter — it only accepts a `country=` string which it maps internally to a region. The adapter's `_REGION_TO_COUNTRY` map converts the integration's region value (`eu`/`us`/`cn`) to a canonical seed country code for that call; (d) `KarcherHome._download()` uses `resp.status_code` (requests-style) instead of `resp.status` (aiohttp) in its non-200 error path — `_patch_download()` replaces the method on the instance after `create()`. |
| REST list-serialisation quirk | S | Handled by `karcher-home`; not the integration's concern. |
| Tenant ID handling | H | Hardcoded inside `karcher-home` as `1528983614213726208`; the adapter does not re-expose it. **No escape hatch:** no env-var override, no advanced-options config-flow field, no `AdapterConfig` constructor parameter. If 3iRobotix migrates Kärcher to a different tenant, or a contributor wants to support a sibling 3iRobotix-OEM device (Bissell, Severin, etc.), it is handled by a release that bumps the constant in `karcher-home` and the integration's pin together. Hidden overrides accumulate support cost (forum users pasting random IDs) without delivering value while the current tenant works. |

### 3.1 Permitted private-API surface

The adapter is allowed to access exactly the following private symbols
of `karcher` (the import name; PyPI distribution `karcher-home`). Every
entry has a justification rooted in a known upstream limitation. The
list is the source of truth for the allowlist constant in
`tests/tools/check_imports.py`; the two must agree.

| Symbol | Type of access | Why |
|---|---|---|
| `KarcherHome._mqtt` | attribute | The library exposes no public way to bind an MQTT message callback. Required for push delivery (§4 of `04-architecture.md`). |
| `KarcherHome._mqtt.on_message` | attribute set | Bind the adapter's threadsafe bridge as the paho-mqtt message handler. |
| `KarcherHome._update_device_properties` | method call | Work-around for upstream bug 1: `_process_mqtt_message` ignores `property/post` payloads; the adapter calls this internal updater directly after parsing the payload so the in-memory cache stays current. |
| `KarcherHome._device_props` | attribute read | Read the internal `dict[sn, DeviceProperties]` cache to snapshot the current telemetry and project it into the integration-owned DTO after subscribe or fetch. |
| `KarcherHome._wait_events` | attribute read/write | Register a `threading.Event` in the library's internal reply-wait dict before publishing a `prop.get` request, so `fetch_properties` can block until the `get_reply` arrives (work-around for bug 2 — stale `get_device_properties`). |
| `KarcherHome._base_url` | attribute read | Read after `KarcherHome.create()` to capture the resolved REST base URL for the region endpoint snapshot (FR-RG-2). No public accessor. |
| `KarcherHome._mqtt_url` | attribute read | Read after `KarcherHome.create()` to capture the resolved MQTT broker URL for the region endpoint snapshot (FR-RG-2). No public accessor. |
| `DeviceProperties.net_stauts` | attribute access (typo path) | Work-around for upstream typo: the field is named `net_stauts` in the library dataclass. Touching it via `getattr` prevents `AttributeError` from propagating to the MQTT thread when the library's own `update()` accesses `net_status`. |
| `KarcherHome.subscribe_device` | method call | Public-looking name but undocumented and may be considered private by upstream; pinned here so any future upstream renaming is caught by the allowlist check rather than at runtime. |
| `KarcherHome.unsubscribe_device` | method call | Symmetric counterpart to `subscribe_device`; same rationale. |

The list **may not grow** without an ADR amendment to `adr/0001` and a
PR that updates the allowlist constant, the call sites, and this
table together. If a `karcher` upstream release exposes a public
equivalent, the entry moves to the public surface and is removed from
the allowlist in the same PR.

## 4. Home Assistant platform

| Constraint | Type | Change |
|---|---|---|
| Minimum HA version 2025.1.0 | S | Same; CI pins two HA versions explicitly (oldest supported + current) — no `latest` |
| Python 3.12 target | S | Same; `ruff target-version = "py312"`, `mypy python_version = "3.12"` |
| `VacuumActivity` enum required | H | Same |
| Battery as separate `SensorEntity` | H | Same (removed from `VacuumEntity` in HA 2026.8) |
| Non-blocking event loop | H | Same. Blocking is permitted only inside `adapter.py` and only via `run_in_executor`. |
| `DataUpdateCoordinator` pattern | S | Same |
| One `ConfigEntry` per device | H | Same |
| `config_flow: true` | H | Same |
| HACS packaging | H | Same |

## 5. Apple Home / Matter via HAMH

Carried forward verbatim. Relevant requirements: FR-AH-1..3 in
`02-requirements.md`.

## 6. Development and tooling

| Constraint | Type | Change |
|---|---|---|
| Python as implementation language | H | Same |
| Type annotations required | **S→H** | `mypy --strict` is a CI gate (NFR-M-2) |
| Linter: `ruff` | S | Same; `ruff format --check` is a gate |
| Test framework: `pytest` with `pytest-homeassistant-custom-component`, `pytest-asyncio` (mode auto) | S | Same |
| Local Python interpreter `/opt/anaconda3/bin/python3` | H (local only) | Noted; CI uses the matrix Python |
| PyPI packages only in `manifest.json requirements` | H | Same |
| Secrets never committed | H | Enforced by pre-commit `forbidden-strings` hook scanning for the known research passwords `sc2021`, `hj2WtyHYYEvBTxDb` |

## 7. Scope constraints (out of bounds)

Same as `doc/CONSTRAINTS.md §7`, updated:

| Out of scope | Reason |
|---|---|
| Local control | Hardware wall; see §1 |
| Offline operation | Consequence of cloud-only control. The integration surfaces an explicit offline state (FR-V); it does not attempt to cache commands and replay them. |
| Other Kärcher models | Untested; treat as separate product in a future major version |
| Kärcher app replacement | Out of intent |
| Historical cleaning records | Not exposed by REST |
| Map image v1 | Deferred to Phase 5 |
| OTA interception | Out of intent |
| HA Supervisor add-on packaging | Deployment target is Home Assistant OS |

## 8. Constraints that the rewrite does **not** relax

Contrary to the first draft of this document, several constraints of
the current repo remain in place because `karcher-home` remains the
transport. Documented here so the rewrite does not quietly drift from
these facts:

- **Executor dispatch** for blocking calls is still required — inside
  `adapter.py` only.
- **Foreign-thread paho callbacks** still need `call_soon_threadsafe`
  re-entry — inside `adapter.py` only.
- **Private-API access** is still required for two targeted work-arounds
  — inside `adapter.py` only.
- **Upstream bugs** (`net_stauts`, stale `get_device_properties`) still
  need adapter-level patching.

The single-module concentration is what the rewrite buys: the rest of
the codebase runs in a clean async/typed world, and the awkward bits
are named and contained.

## 9. New constraints introduced by the rewrite

| Constraint | Type | Detail |
|---|---|---|
| Import-graph boundary | H | `tests/tools/check_imports.py` enforces that only `adapter.py` imports `karcher`, and that `adapter.py` does not import `homeassistant.*` at runtime |
| Typed DTO boundary | H | The adapter returns integration-owned frozen dataclasses (`DeviceProperties`, `VacuumState`); `karcher-home` types are never exposed above the adapter |
| Recorded MQTT traffic for regression | H | `tests/fixtures/captures/*.jsonl` contains sanitised captures used by contract and integration tests |
| Region snapshot in config entry | H | At auth time, the adapter stores `region_endpoint_snapshot` in config-entry data so reconnect after HA restart does not require repeating the region-discovery REST call |

## 10. Deprecations and migrations

The rewrite is a **greenfield package**:
`custom_components/karcher_home_robots/` is re-created from empty.
There is no in-place migration of source files. For users who already
have the integration installed:

- The domain (`karcher_home_robots`) and entity unique IDs are
  preserved, so existing automations and dashboards carry forward
  unchanged.
- A one-time config-entry-version bump (`version = 2`) triggers an
  `async_migrate_entry` path that reshapes the entry data to the new
  schema (`region_endpoint_snapshot` added; `product_id` redundancy
  dropped). Migration is covered by a dedicated integration test
  (FR-MG-2).
- Any entity-registry entries whose unique_id shape deviates from the
  frozen list are re-keyed in the migration. Covered by FR-MG-3.


