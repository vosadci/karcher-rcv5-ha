# Map Feature — MVP Implementation Plan

Captured 2026-05-03. Ready for execution.

## Key architectural finding

`karcher-home` already handles the hard parts via `get_map_data()`:
- Downloads from cloud CDN (REST, not MQTT)
- AES-decrypts + zlib-decompresses
- Parses protobuf via bundled `mapdata_pb2` + `google.protobuf`
- Returns `Map` with `.data` dict: `map_head`, `map_data`, `history_pose`, `charge_station`, `current_pose`, `room_data_info`

**No QuickLZ implementation needed for MVP.** Pillow is a HA core dep (`Pillow==12.2.0`).
`google.protobuf` is a transitive dep of `karcher-home` — already available.

---

## Files to create (5)

### `custom_components/karcher_home_robots/map_data.py`
Integration-owned DTOs.

```python
@dataclass(frozen=True)
class MapGrid:
    width: int          # cells (120)
    height: int         # cells (120)
    data: bytes         # raw grid bytes, 2 bits/cell
    resolution: float   # metres/cell
    min_x: float
    min_y: float

@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    phi: float = 0.0    # heading, radians

@dataclass(frozen=True)
class MapSnapshot:
    grid: MapGrid
    robot: Pose | None
    charger: Pose | None
    path: list[tuple[float, float]]      # history_pose world-space (x, y)
    cur_path: list[tuple[float, float]]  # live path accumulated from cur_path pushes
```

### `custom_components/karcher_home_robots/map_parser.py`
Translates `Map.data` dict from `karcher-home` → `MapSnapshot`. No I/O, pure function.

```python
def parse_map(raw: dict[str, Any], cur_path: list[tuple[float, float]]) -> MapSnapshot:
    ...
```

Extracts `map_head` (resolution, sizeX, sizeY, minX, minY), `map_data.map_data` bytes,
`history_pose.points` → list of (x, y), `charge_station` (x, y), `current_pose` (x, y, phi).

### `custom_components/karcher_home_robots/map_render.py`
Pure-function PNG renderer. No I/O, no HA imports. Testable in isolation.

```python
def render_map(snapshot: MapSnapshot, *, scale: int = 4) -> bytes:
    """Return PNG bytes. Called in executor from KarcherMapImage."""
```

Uses `PIL.Image` + `PIL.ImageDraw`. Grid at `scale` px/cell:
- Cell 0 (free/unknown): `#2a2a2a` dark grey
- Cell 1 (wall):         `#e0e0e0` white
- Cell 3 (cleaned):      `#4a6fa5` blue-grey
- `path` (history_pose): orange polyline, 1 px
- `cur_path` overlay:    bright orange polyline, 2 px (drawn on top)
- Charger:               cyan filled circle, radius 4 px
- Robot:                 white filled circle, radius 5 px + heading line

Returns PNG bytes via `io.BytesIO`.

### `custom_components/karcher_home_robots/image.py`
HA `ImageEntity` subclass.

```python
class KarcherMapImage(KarcherEntity, ImageEntity):
    _attr_content_type = "image/png"
    _attr_name = "Map"

    @property
    def image_last_updated(self) -> datetime | None:
        return self.coordinator.image_last_updated

    async def async_image(self) -> bytes | None:
        snapshot = self.coordinator.map_snapshot
        if snapshot is None:
            return None
        return await self.hass.async_add_executor_job(render_map, snapshot)
```

### Tests
- `tests/unit/test_map_parser.py` — synthetic dict → correct MapSnapshot fields
- `tests/unit/test_map_render.py` — valid PNG bytes, correct dimensions, smoke only
- `tests/unit/test_image_entity.py` — returns None when map_snapshot is None; bytes when set
- `tests/contract/test_cur_path_push.py` — cur_path/post MQTT payload → _path_callback with correct points
- Extend `tests/contract/test_adapter.py` — cover get_map_snapshot

---

## Files to modify (4)

### `adapter.py`

**Add `get_map_snapshot(device) -> MapSnapshot | None`:**
- Calls `client.get_map_data(kdev)` (same call already in `get_rooms`)
- Parses via `map_parser.parse_map(raw_map.data, cur_path=[])`
- Returns `MapSnapshot` or `None` on failure
- Runs in executor (blocking CDN download)

**Extend `_on_message` in `subscribe()` to handle `cur_path/post`:**
```python
if "thing/event/cur_path/post" in topic:
    # parse params["cur_path"]: List[float]
    # validate: len >= 6 and (len - 2) % 4 == 0
    # extract (x, y) pairs: indices [1],[2], [5],[6], [9],[10], ...
    # call loop.call_soon_threadsafe(self._path_callback, points)
```

**`subscribe()` signature change:**
```python
async def subscribe(
    self,
    device: Device,
    on_push: Callable[[DeviceProperties], None],
    on_path: Callable[[list[tuple[float, float]]], None] | None = None,
) -> None:
```

**cur_path payload layout** (from APK ControlMainActivity.java:2870):
```
[startPoseId, x0, y0, phi0, flag0, x1, y1, phi1, flag1, ...]
validity: len >= 6 and (len - 2) % 4 == 0
points: indices (i*4+1, i*4+2) for i in range((len-2)//4)
```

### `coordinator.py`

**Add state:**
```python
self.map_snapshot: MapSnapshot | None = None
self.image_last_updated: datetime | None = None
self._cur_path: list[tuple[float, float]] = []
```

**Add `async _refresh_map()`:**
- Calls `adapter.get_map_snapshot()`
- Stores result, resets `_cur_path`, sets `image_last_updated = dt_util.utcnow()`
- Calls `async_update_listeners()`

**Add `_handle_path_push(points)`:**
- Extends `_cur_path`
- Rebuilds `map_snapshot` with new `cur_path` (reuse cached grid/charger/robot pose)
- Sets `image_last_updated = dt_util.utcnow()`
- Calls `async_update_listeners()`

**Trigger `_refresh_map()`:**
- In `async_setup()` after rooms are fetched
- In `_maybe_refresh_rooms()` when map ID changes (replaces or supplements room fetch)

**Clear `_cur_path`:**
- When `current_map_id` changes
- When vacuum state transitions to DOCKED (robot finished cleaning)

**Wire `on_path` callback in `async_setup()`:**
```python
await self._adapter.subscribe(self._device, self._handle_push, self._handle_path_push)
```

### `__init__.py`
Add `Platform.IMAGE` to `PLATFORMS` list.

### `manifest.json`
No new requirements. Pillow is HA core dep; google.protobuf comes with karcher-home.
Bump version to `2.4.0`.

---

## Data flow

```
Startup:
  coordinator.async_setup()
    → adapter.subscribe(..., on_path=_handle_path_push)
    → adapter.get_map_snapshot()        [executor: REST CDN + decrypt + proto parse]
      → map_parser.parse_map()          [pure function: dict → MapSnapshot]
    → coordinator.map_snapshot = ...
    → coordinator.image_last_updated = now()

During cleaning (live path):
  robot MQTT → adapter._on_message (cur_path/post)
    → parse float list → list[tuple[float, float]]
    → loop.call_soon_threadsafe(coordinator._handle_path_push, points)
      → coordinator._cur_path.extend(...)
      → rebuild MapSnapshot(grid=cached, cur_path=_cur_path, ...)
      → coordinator.image_last_updated = now()
      → async_update_listeners() → KarcherMapImage notified

Map change:
  robot MQTT → property/post → current_map_id changes
    → coordinator._maybe_refresh_rooms()
      → adapter.get_map_snapshot()      [executor]
      → coordinator.map_snapshot = new
      → coordinator._cur_path = []
      → image_last_updated = now()

HA frontend requests image:
  KarcherMapImage.async_image()
    → hass.async_add_executor_job(render_map, snapshot)
      → PIL drawing → PNG bytes → return
```

---

## Deferred (not in MVP)

| Feature | Reason |
|---|---|
| Room-coloured grid cells | Needs `room_matrix`/`room_chain` parsing — not yet in adapter |
| Interactive zone selection | Needs calibration data + custom Lovelace card |
| Virtual walls display | Available in protobuf, not needed for MVP |
| MQTT `upload_by_mapid` path | Cloud CDN path works; MQTT path needed for local-control future |
| QuickLZ decompressor | Only needed for MQTT-direct path |
| Map rotation (`angle` from `map_ext_info`) | Trivial add-on later |
| Multiple stored maps / map switching | `current_map_id` tracked; UI is a separate feature |

---

## Execution order

1. `map_data.py` — DTOs, no deps
2. `map_parser.py` + `tests/unit/test_map_parser.py`
3. `map_render.py` + `tests/unit/test_map_render.py`
4. `adapter.py` additions + `tests/contract/test_cur_path_push.py`
5. `coordinator.py` additions
6. `image.py` + `tests/unit/test_image_entity.py`
7. Wire `__init__.py` + bump `manifest.json` version
8. `make check` — lint + type + test-cov + coverage-gate + import-graph
