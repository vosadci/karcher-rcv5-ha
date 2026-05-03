# Architecture

`karcher_home_robots` — HA custom integration for the Kärcher RCV5.
Wraps the `karcher-home` library (`karcher` import, PyPI `karcher-home==0.5.1`)
behind a three-layer boundary: HA entities → coordinator → adapter.

## Layers

```
┌───────────────────────────────────────────────────────────┐
│ HA layer                                                  │
│   vacuum.py · sensor.py · binary_sensor.py · select.py   │
│   config_flow.py · __init__.py · entity.py               │
│   imports: coordinator.py, const.py, HA core             │
└───────────────────────┬───────────────────────────────────┘
                        │
┌───────────────────────▼───────────────────────────────────┐
│ Coordinator layer                                         │
│   coordinator.py · exceptions.py                         │
│   imports: adapter.py, const.py                          │
│   owns: VacuumState derivation, push/poll reconciliation  │
└───────────────────────┬───────────────────────────────────┘
                        │
┌───────────────────────▼───────────────────────────────────┐
│ Adapter layer                                             │
│   adapter.py  ←  the ONLY importer of karcher            │
│   imports: karcher, asyncio, logging                     │
│   forbidden: homeassistant.* at runtime                  │
└───────────────────────────────────────────────────────────┘
```

Enforced by `tests/tools/check_imports.py` (pre-commit + CI).

### Hard rules

- **`adapter.py` is the only module that imports `karcher`** — no entity or coordinator file touches it directly.
- **`adapter.py` does not import `homeassistant.*` at runtime** — `TYPE_CHECKING` annotations only.
- **Entity modules do not import `adapter.py`** — they go through the coordinator.
- **`run_in_executor` / `hass.async_add_executor_job` only inside `adapter.py`** — everything above is async end-to-end.
- **paho-mqtt callbacks re-enter the event loop only via `loop.call_soon_threadsafe`** — coordinator state is never mutated from the MQTT thread.
- **No `tls_insecure_set(True)`** anywhere.
- **No credential, token, SN, or MQTT payload above DEBUG log level.**

## Module responsibilities

| Module | Owns |
|---|---|
| `adapter.py` | Async boundary (executor), foreign-thread bridge (paho→loop), workaround containment, vendor-exception → `ClientError` mapping |
| `coordinator.py` | State lifetime, push/poll reconciliation, `derive_vacuum_state`, room UI state |
| `entity.py` | Shared base: `device_info`, coordinator binding, availability |
| `vacuum.py` / `sensor.py` / `binary_sensor.py` / `select.py` | Map coordinator state to HA entity properties; dispatch commands via coordinator |
| `exceptions.py` | `ClientError` hierarchy (see Error taxonomy below) |
| `_types.py` | Integration-owned DTOs; `KarcherHomeProtocol` / `DevicePropertiesProtocol` for mypy |
| `config_flow.py` | Region → credentials → optional device picker → reauth |
| `const.py` | HA-facing constants only (platform names, conf keys). Wire constants live in `karcher-home`. |

## `karcher-home` private API access

The library ships no `py.typed` and no stubs. The adapter declares the surface it uses as `Protocol` classes in `_types.py` and applies a single `cast()` at construction. After the cast, mypy `--strict` checks all adapter code against the Protocols.

Private symbol access is permitted **only inside `adapter.py`**, only against this explicit allowlist, and each call site carries an inline `# private-api: <reason>` comment:

| Symbol | Why |
|---|---|
| `KarcherHome._mqtt` | No public way to bind an MQTT message callback |
| `KarcherHome._mqtt.on_message` | Bind the adapter's threadsafe bridge as the paho message handler |
| `KarcherHome._update_device_properties` | Workaround: `_process_mqtt_message` ignores `property/post` payloads; call this internal updater directly |
| `KarcherHome._device_props` | Read the internal `dict[sn, DeviceProperties]` cache after subscribe/fetch |
| `KarcherHome._wait_events` | Register a `threading.Event` for `prop.get` reply-wait (workaround for stale `get_device_properties`) |
| `KarcherHome._base_url` | Capture resolved REST URL for region endpoint snapshot; no public accessor |
| `KarcherHome._mqtt_url` | Capture resolved MQTT URL for region endpoint snapshot; no public accessor |
| `DeviceProperties.net_stauts` | Upstream typo; accessed via `getattr` to avoid `AttributeError` on the MQTT thread |
| `KarcherHome._download` | Replaced after `create()` to fix upstream `resp.status_code` vs `resp.status` mismatch |
| `KarcherHome.subscribe_device` | Undocumented; pinned here so upstream renames are caught at lint time |
| `KarcherHome.unsubscribe_device` | Symmetric counterpart to `subscribe_device` |

Adding a symbol requires updating the allowlist in `tests/tools/check_imports.py`, the call site, and this table in the same PR.

## State derivation

Lives exactly once in `coordinator.derive_vacuum_state`. No entity reads raw properties.

States: `Cleaning`, `Paused`, `Returning`, `Docked`, `Idle`, `Error`, `Unknown`.

Rules (in priority order):
1. `work_mode ∈ WORK_MODE_CLEANING` → `Cleaning`
2. `work_mode ∈ WORK_MODE_GO_HOME`: `Docked` if `status == 4` or `charge_state > 0`; else `Returning`
3. `work_mode ∈ WORK_MODE_PAUSE` → `Paused`
4. `work_mode ∈ WORK_MODE_IDLE`: `Docked` if charging; `Error` if `fault != 0`; else `Idle`
5. Unknown `work_mode`: `Docked` if charging; else `Unknown`

The error binary sensor reflects `vacuum_state == Error`, not a raw `fault` field directly.

## Push-first coordinator

MQTT push is primary; REST `prop.get` poll at 30 s is fallback.

- Push is wired before `_async_first_refresh`.
- Updates carry a monotonic HA-side receipt timestamp (`loop.time()`). Updates older than the current timestamp are discarded. Device-reported timestamps are not used for ordering — they skew by tens of seconds.
- On reconnect: `subscribe()` is replayed and `fetch_properties` is forced so the UI doesn't show stale data.
- The coordinator holds a single `asyncio.Lock` around `fetch_properties` / `async_set_updated_data` to prevent a race where a push overwrites a newer poll response.

## Error taxonomy

`exceptions.py` defines the `ClientError` hierarchy. The adapter maps `karcher-home` exceptions into it; the coordinator translates to HA exceptions:

| Adapter raises | Coordinator raises | Effect |
|---|---|---|
| `AuthError` | `ConfigEntryAuthFailed` | Reauth flow; entities unavailable |
| `PermanentError` | `ConfigEntryError` | No retry; surfaced to user |
| `TransientError` | `UpdateFailed` | Retry via coordinator |
| `ValidationError` | — (logged DEBUG) | Missed update |
| `ProtocolError` | — (logged WARNING) | Missed update |

```
ClientError
├── AuthError
│   ├── InvalidCredentials
│   ├── TokenRejected
│   └── AccessDenied
├── TransientError
│   ├── NetworkError
│   ├── TimeoutError
│   ├── RateLimited
│   └── BrokerDisconnect
├── PermanentError
│   ├── DeviceNotFound
│   └── InvalidRegion
├── ValidationError
└── ProtocolError
```

## Concurrency

- One `KarcherAdapter` per config entry; no shared mutable state across entries.
- The adapter owns one executor-bound `karcher-home` client instance.
- Reconnection/backoff are delegated to `karcher-home`; the adapter only re-subscribes on reconnect.
- No `threading.Thread`, `threading.Lock`, or `queue.Queue` anywhere. `asyncio.Lock` / `asyncio.Queue` where synchronisation is needed.
- Background tasks tracked in a per-instance `set[asyncio.Task]`; every `create_task` is paired with a done-callback that drops the handle and logs exceptions.

## Upstream library constraints

`karcher-home` has a mixed sync/async API: `login`, `get_devices`, `get_map_data`, `close`, `create` are async and awaited directly; `subscribe_device`, `unsubscribe_device`, MQTT publish, and `fetch_properties` are synchronous and run via `async_add_executor_job`. No blocking call reaches the event loop.

Known workarounds (all contained inside `adapter.py`):
- `net_stauts` typo in upstream dataclass
- `get_device_properties()` returns stale cache when already subscribed
- `KarcherHome.create()` takes `country=` not `region=`; adapter maps via `_REGION_TO_COUNTRY`
- `KarcherHome._download()` uses `resp.status_code` (requests-style) not `resp.status` (aiohttp); patched via `_patch_download()` after `create()`

## Testing

Three fast layers plus one opt-in hardware layer:

- **Unit** — pure functions, no HA, no I/O. Covers state derivation, exception mapping, parsing.
- **Contract** — adapter against fake broker + fake REST server. Covers subscribe, push decode, command encode, reconnect, timeout, region routing.
- **Integration** — full HA loop via `pytest-homeassistant-custom-component`. Covers entity states, config flow, reauth, diagnostics, migration, offline semantics.
- **HIL** — opt-in, not CI-blocking, expected before a release tag.

Coverage gates (CI): lines ≥ 85%, branches ≥ 80%. Adapter and `derive_vacuum_state` held at 100%.

## Entity unique IDs

Shape: `{device_id}_{entity_type}` where `entity_type ∈ {vacuum, battery, cleaning_area, cleaning_time, error, room, cleaning_mode, water_level}`. A test asserts exact string equality against a frozen list so a rename cannot slip through.

## Region routing

Config entry stores `region` (immutable after setup) and `region_endpoint_snapshot` (broker host:port, REST base URL, CA fingerprint). On HA restart the adapter reconnects from the snapshot without re-running region-discovery REST.

## HA constraints

- Minimum HA version: 2026.1.3
- Python 3.13+
- Battery is a separate `SensorEntity` (removed from `VacuumEntity` in HA 2026.8)
- `quality_scale: bronze` until diagnostics (`diagnostics.py`) land; bump to `silver` on that PR
- `iot_class: cloud_push`
