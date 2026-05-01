# 04 — Architecture

## 1. Guiding principles

1. **Boundary discipline over topology.** Three sharp one-way layers —
   HA entities → coordinator → adapter — enforced by an import-graph
   check in CI. No port-per-collaborator ceremony. See
   `adr/0002-boundary-not-hexagonal.md`.
2. **Library-adapter, not in-tree client.** `karcher-home` is the
   vendor-protocol implementation; the integration wraps it through a
   single `adapter.py` module that absorbs blocking-call, foreign-thread,
   and work-around concerns. Everything above the adapter sees an async
   surface. See `adr/0001-library-adapter.md`.
3. **Asynchronous at the coordinator boundary.** No blocking I/O
   reaches the event loop. `karcher-home` calls happen in the default
   executor inside the adapter; callers never see the boundary.
4. **Typed public surfaces.** The adapter exposes typed DTOs;
   `DeviceProperties` and `VacuumState` are integration-owned dataclasses;
   `mypy --strict` succeeds across the package.
5. **Single direction of dependency.** `entities → coordinator →
   adapter → karcher`. Never the reverse. CI asserts this via
   `tests/tools/check_imports.py`.

## 2. Package layout

```
custom_components/karcher_home_robots/
  __init__.py            — HA entry point: create ConfigEntry resources, setup, unload
  manifest.json          — HA/HACS metadata; quality_scale: bronze until FR-D-1 ships
  strings.json           — UI translations (en) — source of truth
  translations/          — other locales
  const.py               — UI-facing constants only (platform names, conf keys).
                           Wire constants live in karcher-home and are not re-exported here.
  config_flow.py         — region → credentials → (optional) device picker → reauth
  diagnostics.py         — FR-D-1 redacted-dump endpoint (Phase 4)
  entity.py              — shared base: device_info + coordinator binding + availability
  coordinator.py         — DataUpdateCoordinator: state ownership, push+poll reconciliation,
                           selected-room UI state, derive_vacuum_state
  exceptions.py          — ClientError hierarchy (see adr/0003-error-taxonomy.md)
  adapter.py             — the ONLY module that imports karcher or accesses
                           third-party privates. Async boundary via run_in_executor;
                           paho-mqtt bridge via loop.call_soon_threadsafe.
  vacuum.py              — StateVacuumEntity
  sensor.py              — battery (separate entity since HA 2026.8), area, time sensors
  binary_sensor.py       — error indicator
  select.py              — room, cleaning-mode, water-level selects
  services.yaml          — HA service schema registrations (e.g. app_segment_clean) (Phase 4)
```

```
tests/                    — mirrors package layout
  conftest.py             — shared fixtures (FakeAdapter, recorded traffic replay)
  fixtures/captures/*.jsonl  — sanitised MQTT traces
  fixtures/rest/*.json    — recorded REST responses
  unit/                   — unit tests: pure logic, no HA, no network
  contract/               — adapter against a FakeAdapter collaborator — protocol
                           behaviour as observed from above the adapter
  integration/            — full HA-loop tests via pytest-homeassistant-custom-component
  hardware/               — opt-in HIL tests; skipped in CI

tools/
  capture-mqtt.py         — records broker traffic; produces .jsonl for tests
  rotate-ca-cert.py       — checks current 3iRobotix broker cert against the snapshot;
                           flags drift (informational; adapter degrades gracefully)
```

## 3. Layer responsibilities and rules

| Layer | Owns | Forbidden to import |
|---|---|---|
| `vacuum.py`, `sensor.py`, `binary_sensor.py`, `select.py`, `config_flow.py`, `__init__.py`, `entity.py` | Presentation and HA lifecycle: map coordinator state to entity properties; dispatch commands via the coordinator | `karcher`, `paho.*`, `adapter` internals |
| `coordinator.py`, `exceptions.py` | Device state lifetime for one config entry: data freshness, push/poll reconciliation, derivation, error translation | `karcher`, `paho.*`, `aiohttp` (transitive via adapter is fine) |
| `adapter.py` | Wire-format I/O via `karcher-home`; async/foreign-thread bridging; vendor-exception → `ClientError` mapping; work-around containment | `homeassistant.*` (at runtime; `TYPE_CHECKING` is fine for annotations) |

The import-graph check runs in pre-commit and CI. Any crossing of
these boundaries requires an ADR-amending PR and a waiver entry in
`WAIVERS.md` per `08-definition-of-done.md` §5.

## 4. Public interfaces

### 4.1 `KarcherAdapter`

```python
class KarcherAdapter:
    """Thin async wrapper around karcher-home.

    Runs every blocking call in the default executor and bridges
    paho-mqtt foreign-thread callbacks into the event loop via
    loop.call_soon_threadsafe. Maps karcher-home exceptions into
    ClientError subclasses (see adr/0003).
    """

    def __init__(self, hass: HomeAssistant, config: AdapterConfig) -> None: ...

    async def authenticate(self, email: str, password: str) -> None: ...
    # Silent reauth (FR-A-8): the adapter holds the credentials in
    # memory after the first authenticate() and re-runs login()
    # transparently on token expiry, with bounded backoff
    # (3 attempts in 5 min, 5/30/120 s). On exhaustion it raises
    # AuthError, which the coordinator translates to
    # ConfigEntryAuthFailed. No public method on this façade.
    async def get_devices(self) -> list[Device]: ...
    async def get_rooms(self, device: Device) -> list[Room]: ...

    async def subscribe(
        self,
        device: Device,
        on_push: Callable[[DeviceProperties], None],
    ) -> None: ...
    async def unsubscribe(self, device: Device) -> None: ...

    async def send_command(
        self, device: Device, service: str, params: Mapping[str, Any]
    ) -> None: ...
    async def set_property(
        self, device: Device, params: Mapping[str, Any]
    ) -> None: ...
    async def fetch_properties(self, device: Device) -> DeviceProperties: ...

    async def close(self) -> None: ...
```

The façade is async end-to-end; no method blocks the loop. No method
raises a native `karcher-home` exception — every failure surfaces as
a `ClientError` subclass. `DeviceProperties` is an integration-owned
frozen dataclass, not a re-export of `karcher-home`'s internal type.

### 4.1.1 Typing the `karcher` surface

`karcher-home` 0.5.1 ships no `py.typed` marker and no `.pyi` stubs;
mypy resolves every import as `Any`. To keep `mypy --strict` honest
inside the adapter without writing and maintaining vendored stubs
that would silently drift against an effectively-dormant upstream,
the adapter declares the surface it uses as
[`typing.Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)
classes in `_types.py` and applies a single `cast()` at construction
time:

```python
# custom_components/karcher_home_robots/_types.py
from typing import Any, Mapping, Protocol

class KarcherHomeProtocol(Protocol):
    """Structural type for the upstream KarcherHome client.

    Mirrors the public + allowlisted-private surface the adapter
    uses. Pinned in spec/03-constraints-and-deltas.md §3.1; updated
    in lockstep with the ALLOWED_PRIVATE_API constant in
    tests/tools/check_imports.py.
    """
    # public methods the adapter calls — full signatures here
    def login(self, email: str, password: str) -> None: ...
    def get_devices(self) -> list[Any]: ...
    # ... allowlisted private surface (spec/03 §3.1) ...
    _mqtt: Any
    _device_props: dict[str, Any]
    _wait_events: dict[str, Any]
    _base_url: str
    _mqtt_url: str | None
    def _update_device_properties(self, sn: str, data: dict[str, Any]) -> Any: ...
    def subscribe_device(self, *args: Any, **kwargs: Any) -> None: ...

class DevicePropertiesProtocol(Protocol):
    """Structural type for the upstream DeviceProperties.

    Field set is observed against `doc/PROTOCOL.md` and HIL captures.
    """
    battery: int | None
    cleaning_area: int | None
    cleaning_time: int | None
    # ... only the fields the adapter projects out ...
```

```python
# custom_components/karcher_home_robots/adapter.py
from typing import cast
from karcher.karcher import KarcherHome  # the only import of karcher
from ._types import KarcherHomeProtocol, DevicePropertiesProtocol

class KarcherAdapter:
    def __init__(self, hass: HomeAssistant, config: AdapterConfig) -> None:
        raw = KarcherHome.create(...)
        self._client: KarcherHomeProtocol = cast(KarcherHomeProtocol, raw)
```

After the cast, every adapter line that touches `self._client` is
type-checked against the Protocol; mypy `--strict` runs as written
inside the adapter. The cast itself is the asserted-by-runtime
boundary — two of them in the file, both reviewable. No `.pyi`
stubs are vendored; the Protocols *are* the stubs, in-tree, owned
by the integration.

The Protocols reference `Any` only in places where the upstream
type is genuinely opaque (e.g. paho-mqtt internals via `_mqtt`). The
goal is not to type the universe; it is to localise `Any` to call
sites where it is the truth.

If `karcher` upstream ships `py.typed` in a future release, the
Protocols are removed and the cast deleted in the same PR that
bumps the pin.

### 4.2 `KarcherCoordinator`

Extends `DataUpdateCoordinator[DeviceProperties]`. Adds:

- `rooms: list[Room]`
- `get_selected_room_id() -> int | None`
- `set_selected_room_id(room_id: int | None) -> None`
- `async_send_command(service: str, params: Mapping) -> None`
- `async_set_property(params: Mapping) -> None`
- `async_setup()` / `async_shutdown()`
- `vacuum_state: VacuumState` (computed from `self.data`)

Entities never import `adapter.py` directly. They only use the
coordinator.

### 4.3 Entity base

```python
class KarcherEntity(CoordinatorEntity[KarcherCoordinator]):
    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo: ...

    @property
    def available(self) -> bool: ...
```

Availability defaults to
`coordinator.last_update_success AND coordinator.data is not None`.
Subclasses may refine (e.g. water-level unavailable in Vacuum-only
mode).

## 5. State derivation

Derivation lives exactly once, in `coordinator.derive_vacuum_state`.
No entity reads raw properties directly.

State enum (integration-owned):

`Cleaning`, `Paused`, `Returning`, `Docked`, `Idle`, `Error`, `Unknown`.

Derivation rules:

1. `work_mode ∈ WORK_MODE_CLEANING` → `Cleaning`.
2. `work_mode ∈ WORK_MODE_GO_HOME`: `Docked` if `status == 4` or
   `charge_state > 0`; else `Returning`.
3. `work_mode ∈ WORK_MODE_PAUSE` → `Paused`.
4. `work_mode ∈ WORK_MODE_IDLE`: `Docked` if charging; `Error` if
   `fault != 0`; else `Idle`.
5. Unknown `work_mode` is logged at DEBUG; `Docked` if charging else
   `Unknown`.

FR-BS-1 (error binary sensor) reflects `vacuum_state == Error`, not a
raw `fault` field. Tests assert the two cannot disagree (see
`06-test-strategy.md`).

## 6. Push-first coordinator with poll fallback

The coordinator treats MQTT push as primary and REST+`prop.get` poll
as fallback. Three reasons: (a) push is immediate; (b) MQTT QoS 0 is
fire-and-forget, so no delivery guarantee; (c) the broker drops
subscribers silently on some error paths.

Cadence:

- Push is wired before `_async_first_refresh` so the very first refresh
  can already benefit from it.
- Poll runs every 30 s while the coordinator is active. The interval is
  a constant; there is no adaptive backoff other than the error retry
  logic inherited from `DataUpdateCoordinator`.
- Each update (push or poll) carries an HA-side *monotonic* receipt
  timestamp (`loop.time()`). The coordinator discards any update whose
  receipt timestamp is older than the current one. Device-reported
  timestamps are not used for ordering — they have been observed to
  skew by tens of seconds relative to HA wall-clock and cannot be
  trusted as a sequence key.
- On reconnect, `subscribe()` is replayed for each subscribed device
  and a `fetch_properties` is forced so the UI is not stuck on stale
  data.

## 7. Concurrency model

- One `KarcherAdapter` per config entry.
- The adapter owns one executor-bound `karcher-home` client instance.
- Reconnection and backoff are delegated to `karcher-home`
  internally; the adapter only re-subscribes on reconnect and
  re-raises as `TransientError` if reconnection fails altogether.
- paho-mqtt callbacks are invoked on a foreign thread; the adapter
  wraps each callback body in `loop.call_soon_threadsafe(...)` so that
  coordinator state is never mutated from the mqtt thread.
- The coordinator holds a single `asyncio.Lock` around
  `fetch_properties` / `async_set_updated_data` to prevent a race
  where a push arrives mid-poll and an older poll response overwrites
  newer push data (NFR-R-5).
- No shared mutable state across config entries.

## 8. Error taxonomy

Defined in `exceptions.py`. See `adr/0003-error-taxonomy.md` for the
full hierarchy. Summary of translation at the coordinator:

| Raised by adapter      | Raised by coordinator       | Effect                                       |
|------------------------|-----------------------------|----------------------------------------------|
| `AuthError` (any)      | `ConfigEntryAuthFailed`     | Reauth flow; entities unavailable            |
| `PermanentError` (any) | `ConfigEntryError`          | No retry; surfaced to user                   |
| `TransientError` (any) | `UpdateFailed`              | Retry via coordinator                        |
| `ValidationError`      | — (logged at DEBUG)         | Missed update                                |
| `ProtocolError`        | — (logged at WARNING)       | Missed update                                |

## 9. Observability hooks

- Structured `_LOGGER.debug(...)` at every adapter boundary.
- A rolling in-memory deque of the last 100 wire events per adapter
  for diagnostics (FR-D-1). Redacted on export.
- Adapter exposes `status: AdapterStatus` (connected, reconnecting,
  last error, attempt count) for diagnostics.

## 10. Testability affordances

- `KarcherAdapter` accepts a `karcher_factory` callable so
  tests can inject a `FakeKarcherClient` instead of the real class.
  Tests never patch `karcher.*` internals directly.
- Recorded MQTT captures are replayed into the adapter through a
  `FakePahoClient` that yields messages at captured timestamps.
- `derive_vacuum_state` is a pure function; all state-transition tests
  are unit tests with hand-constructed `DeviceProperties`.

## 11. Migration from the prior repo

- HA domain preserved: `karcher_home_robots`.
- Entity unique IDs preserved: `{device_id}_{entity_type}` with the
  existing type tokens (`vacuum`, `battery`, `cleaning_area`,
  `cleaning_time`, `error`, `room`, `cleaning_mode`, `water_level`).
  A test asserts exact string equality against a frozen list so a
  rename cannot slip through (FR-MG-1).
- `async_migrate_entry` bumps entry `version = 2`; the only change is
  the shape of `data` (add `region_endpoint_snapshot`, drop
  `product_id` redundancy).
- Any entity-registry entries whose unique_id does not match the
  frozen list are re-keyed in `async_migrate_entry` — the migration
  test covers both the happy path and a pre-existing-mismatch path.
- **Failure handling.** `async_migrate_entry` follows HA default:
  on exception it returns `False`, the integration shows as failed
  to load, and a `repair` issue surfaces (`migration_failed_v{from}_v{to}`)
  pointing the user to the diagnostics download and a downgrade
  path. No snapshot-and-restore: HA's `ConfigEntry` has no
  transaction model, and inventing one in-tree is more risk than
  the maintainer-side mitigation (FR-MG-4 integration test gates
  every release per `spec/08-definition-of-done.md` §3 item 10).
  See FR-MG-5, 5a, 5b.

## 12. Region routing

The vendor cloud has distinct broker/REST clusters per region (EU, US,
CN, and possibly more). `karcher-home` selects the correct endpoints
based on an explicit region parameter; the integration exposes this as
`region` in the config entry data. The adapter stores a snapshot of
the resolved endpoints (`region_endpoint_snapshot`) at auth time so
the coordinator can reconnect after an HA restart without re-running
the discovery REST call. See FR-S for the detailed requirement.
