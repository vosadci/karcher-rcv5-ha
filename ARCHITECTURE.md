# Architecture

`karcher_home_robots` — HA custom integration for the Kärcher RCV5.
Wraps the `karcher-home` library (`karcher` import, PyPI `karcher-home==0.5.1`)
behind a three-layer boundary: HA entities → coordinator → adapter.

## Layers

```
┌───────────────────────────────────────────────────────────┐
│ HA layer                                                  │
│   vacuum.py · sensor.py · binary_sensor.py · select.py · button.py   │
│   number.py · switch.py                                              │
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
- **Blocking library I/O goes through the executor only inside `adapter.py`** — everything above is async end-to-end. Exception: CPU-bound *pure* map work (`map_render` helpers) is dispatched to the executor by its callers (`image.py` render, `coordinator._refresh_map` post-processing) so large grids cannot stall the event loop.
- **paho-mqtt callbacks re-enter the event loop only via `loop.call_soon_threadsafe`** — coordinator state is never mutated from the MQTT thread.
- **No `tls_insecure_set(True)`** anywhere.
- **No credential, token, SN, or MQTT payload above DEBUG log level.**

## Module responsibilities

| Module | Owns |
|---|---|
| `adapter.py` | Async boundary (executor), foreign-thread bridge (paho→loop), workaround containment, vendor-exception → `ClientError` mapping |
| `coordinator.py` | State lifetime, push/poll reconciliation, `derive_vacuum_state`, room UI state |
| `entity.py` | Shared base: `device_info`, coordinator binding, availability |
| `vacuum.py` / `sensor.py` / `binary_sensor.py` / `select.py` / `button.py` / `number.py` / `switch.py` | Map coordinator state to HA entity properties; dispatch commands via coordinator |
| `exceptions.py` | `ClientError` hierarchy (see Error taxonomy below) |
| `_types.py` | Integration-owned DTOs; `DeviceProperties` snapshot passed from adapter to coordinator |
| `config_flow.py` | Region → credentials → optional device picker → reauth |
| `const.py` | HA-facing constants only (platform names, conf keys). Wire constants live in `karcher-home`. |
| `image.py` | `KarcherMapImage` — serves rendered map PNG via HA `ImageEntity` |
| `map_data.py` | DTOs: `MapSnapshot`, `MapGrid`, `Pose`, `MapObject`, `RoomInfo`, `RoomChain`, `CarpetArea`, `RestrictedZone` |
| `map_parser.py` | Translates raw `Map.data` protobuf dict → `MapSnapshot`; pure, no I/O |
| `map_render.py` | Renders `MapSnapshot` → PNG bytes (numpy + Pillow); pure, no I/O, called in executor |
| `diagnostics.py` | `async_get_config_entry_diagnostics` — redacted bundle |
| `_account_registry.py` | Shared `KarcherAdapter` registry — one adapter instance per cloud account, shared across coordinators for the same account |

## `karcher-home` private API access

The library ships no `py.typed` and no stubs. The adapter types its client as `Any` and accesses private symbols via `getattr()`; each call site carries an inline `# private-api: <reason>` comment.

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
- Ordering: push handlers run on the event loop and are inherently ordered; only a poll can race a push. `_handle_push` records a monotonic receipt timestamp (`loop.time()`); `_async_update_data` records `poll_started` before the `prop.get` round-trip and discards the poll result in favour of `coordinator.data` when a push landed mid-flight. Device-reported timestamps are not used for ordering — they skew by tens of seconds.
- Reconnects: TCP-level broker reconnects are delegated to karcher-home/paho. After a successful silent re-login the adapter replays all device subscriptions and re-binds its MQTT dispatcher (`_restore_push_pipeline`); the coordinator's post-reauth fetch retry restores data freshness. The dispatcher bind is identity-checked on every `subscribe()`, so a rebuilt MQTT client cannot silently lose push.

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
│   └── TokenRejected
├── TransientError
│   ├── NetworkError
│   ├── RateLimited
│   └── BrokerDisconnect
├── PermanentError
├── ValidationError
└── ProtocolError
```

## Concurrency

- One `KarcherAdapter` per cloud account, shared across config entries for that account via `_account_registry` (refcounted; closed when the last entry unloads). Adapter callbacks are keyed per device SN, so coordinators do not share mutable state.
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

## Map

`coordinator.py` fetches a `MapSnapshot` via the adapter on startup, on dock, and every 10 s during cleaning. The snapshot contains:

- `grid` — variable-size byte array (1 byte/cell: raw ≥ 10 = room cell encoding room ID; 0–3 = free/cleaned/deep-cleaned/wall; 0xFF = solid wall)
- `path` — persistent `history_pose` path points in world coords (metres)
- `cur_path` — live session path from `cur_path/post` MQTT pushes (not observed on all firmware)
- `robot` / `charger` — current poses; `robot.phi` = heading in radians (standard math convention: 0 = east, CCW positive)
- `room_chains` — per-room perimeter polygons in world coords (room fill and current-room detection)
- `rooms` — room name, colour ID, material (carpet/tile/hardwood)

After each map refresh the coordinator also computes (the CPU-bound parts run in the executor via `_derive_map_state`):
- `room_cell_map` — RLE pixel spans `(px_row, col_start, run_len)` per room for the Lovelace card overlay
- `render_layout` — crop/scale parameters (`col0`, `row0`, `scale`, output dimensions) for coordinate conversion
- `render_image_size` — `(width, height, cell_size)` of the rendered PNG, exposed as vacuum attributes
- `room_areas_m2` — per-room cleaned-cell area in m² (`np.bincount` over the decoded room-ID grid, one pass for all rooms)

Pixel-space overlays are projected on the coordinator, not the entity, because the projection needs `render_layout` + grid (which live here). They are refreshed on **every path push** as well as on every map refresh — `render_layout` shifts as the explored map grows, so a stale projection would mix coordinate systems:
- `cur_path_px` — flat `[x0, y0, x1, y1, …]` pixel list, decimated by `_CUR_PATH_STEP` with the final point always kept. The decimated base is cached and grown incrementally on path pushes (only the newly appended points are projected); a full reprojection runs only when `render_layout` changes or the path resets, so per-push cost is O(new points), not O(whole path)
- `robot_px` — `{x, y, phi}`; pose prefers the live path stream over the cloud snapshot
- `charger_px` — `{x, y}`

`map_parser.py` translates the raw protobuf dict into a `MapSnapshot` (pure, no I/O).
`map_render.py` renders it to PNG bytes using numpy + Pillow (pure, no I/O, runs in executor). Pipeline: white background → room colour fills (APK-verified palette, numpy masks) → cleaned-area overlay → wall overlay (dilated 1 px) → objects → LANCZOS downsample. Paths, the robot icon, room labels, and the charger are NOT baked into the PNG — the Lovelace card draws them on its canvas overlay from the coordinator-projected `cur_path_px` / `robot_px` / `charger_px`.
`image.py` wraps the PNG as an HA `ImageEntity`.

`vacuum.py` exposes `room_map` (including per-room `area_m2`), `map_image_size`, `robot_px {x, y, phi}`, `charger_px {x, y}`, `cur_path_px`, `room_preferences` (per-room settings), and `prefer_mode` (`"standard"` | `"customise"`) as extra state attributes — reading the coordinator's already-projected values — so the Lovelace card can draw room overlays, the robot icon, and restore the active tab.

`__init__.py` registers `www/` as a static path at `/karcher_home_robots/static/` so `karcher-vacuum-card.js` and `icon.svg` are served to the browser without a separate HACS install.

`current_room_name` is derived by `_current_room_id`: ray-casting point-in-polygon against room chain polygons.

## Entity unique IDs

Shape: `{device_id}_{entity_type}` where `entity_type ∈ {vacuum, battery, cleaning_area, cleaning_time, error, charging, connectivity, fault_code, current_room, room, cleaning_mode, water_level, main_brush, side_brush, hypa, mop_life, reset_main_brush, reset_side_brush, reset_hypa, reset_mop_life, map}`. Per-room entities use `room_{room_id}_{attr}` where `attr ∈ {mode, power, order, custom}`. A test asserts exact string equality against a frozen list so a rename cannot slip through.

## Region routing

Config entry stores `region` (immutable after setup) and `region_endpoint_snapshot` (`rest_base_url` + `mqtt_url`, captured via `get_endpoint_snapshot()`). The snapshot is persisted for diagnostics/observability only — it surfaces the resolved endpoints in the diagnostics bundle. It is **not** read back on restart: `adapter.async_setup()` always re-runs region discovery via `KarcherHome.create(country=…)`. Reconnect-from-snapshot (skipping discovery) is not implemented.

## HA constraints

- Minimum HA version: 2026.6.0
- Python 3.14+ — required at *parse time*: the codebase uses PEP 758 bare except tuples (`except KeyError, TypeError:`), which are a SyntaxError on ≤ 3.13. Tooling running older interpreters cannot even import the package.
- Battery is a separate `SensorEntity` (removed from `VacuumEntity` in HA 2026.8)
- `quality_scale: silver` (diagnostics landed in Phase 4)
- `iot_class: cloud_push`
