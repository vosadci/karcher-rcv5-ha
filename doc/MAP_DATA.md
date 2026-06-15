# Kärcher RCV5 — Map Data: Formats, Flows & Encoding

Epistemic tags: **[K]** known (capture/APK/working code), **[I]** inferred, **[A]** assumed.

Capture date: 2026-03-28 / APK analysis: 2026-05-03 / 2026-05-08 / 2026-06-14.

---

## 1. Map Data Lifecycle

```
TRIGGER (startup / dock / every 10 s cleaning)
    │
    ▼
coordinator reads current_map_id from DeviceProperties (from property/post push)
    │
    ▼
adapter publishes:  upload_by_mapid  { mapId: <id> }
    │
    ▼
Robot compresses map → publishes binary reply on upload_by_mapid_reply
    │
    ▼  QuickLZ-compressed protobuf (MapData.RobotMap)
Cloud broker forwards binary payload to all subscribers
    │
    ▼
karcher-home library decompresses + parses protobuf → raw dict
    │
    ▼  [K — adapter calls get_map_data() via executor]
map_parser.py  →  MapSnapshot DTO
    │
    ▼
coordinator stores MapSnapshot; derives room_cell_map + render_layout
    │
    ▼  [executor — numpy + Pillow]
map_render.render_map()  →  PNG bytes
    │
    ▼
KarcherMapImage (ImageEntity)  →  HA frontend
```

---

## 2. Wire Format — `upload_by_mapid_reply`

**Topic:** `/mqtt/{product_id}/{sn}/thing/service_invoke_reply/upload_by_mapid` [K — APK]

**Format:** Raw binary, not JSON. [K — APK + working parser]

```
[ QuickLZ frame 1 ][ QuickLZ frame 2 ]...
         │
         ▼  decompress each frame
[ concatenated raw bytes ]
         │
         ▼  protobuf parse
MapData.RobotMap
```

QuickLZ level-1 compression. The APK decompressor loops over frames (multiple frames are
possible in principle). [K — APK `MapProcessUtil.decCombyte()`]. Whether the RCV5 ever
sends more than one frame in practice is [I] — not yet observed.

---

## 3. Protobuf Schema — `MapData.RobotMap`

The `.proto` file is not in the APK. Field numbers verified two ways on 2026-06-12:
(a) the `newMessageInfo` descriptor string in APK `MapData.java` (v1.4.32, jadx), and
(b) the compiled descriptor bundled in `karcher-home` 0.5.1 (`karcher/mapdata_pb2.py`).
Both agree exactly. [K]

```proto
message RobotMap {
  int32                 map_type       = 1;
  MapExtInfo            map_ext_info   = 2;   // task start time, map upload time, validity, angle [K — §3.1]
  MapHeadInfo           map_head       = 3;   // grid dimensions & world origin
  MapDataInfo           map_data       = 4;   // raw grid bytes
  repeated AllMapInfo   map_info       = 5;   // list of stored maps [I — not parsed]
  DeviceHistoryPoseInfo history_pose   = 6;   // persistent clean-path points
  DevicePoseDataInfo    charge_station = 7;   // charger position
  DeviceCurrentPoseInfo current_pose   = 8;   // robot position + heading

  repeated DeviceAreaDataInfo            virtual_walls     = 9;   // [I — not parsed]
  repeated DeviceAreaDataInfo            areas_info        = 10;  // [I — not parsed]
  repeated DeviceNavigationPointDataInfo navigation_points = 11;  // [I — not parsed]

  repeated RoomDataInfo  room_data_info = 12;  // room metadata
  DeviceRoomMatrix       room_matrix    = 13;  // room boundary bitmap [I — not decoded]
  repeated RoomChainInfo room_chain     = 14;  // room perimeter polygons [K — decoded]
  repeated AiObjectInfo  objects        = 15;  // AI-detected objects [K — decoded]

  repeated FurnitureDataInfo furniture_info = 16;  // carpet/furniture polygons [K — §6.4]
  repeated HouseInfo         house_infos    = 17;  // multi-map house grouping [I — not parsed]
}

message MapExtInfo {
  int32 task_begin_date  = 1;  // Unix seconds — clean task start time [K]
  int32 map_upload_date  = 2;  // Unix seconds — map snapshot upload time [K]
  int32 map_valid        = 3;  // map validity flag [K — field confirmed, semantics not decoded]
  float angle            = 4;  // map rotation angle [K — field confirmed, semantics not decoded]
}

message FurnitureDataInfo {
  int32  id      = 1;
  int32  type_id = 2;   // 1550 = carpet area [K — APK GlobalRender.updateMatericalSpecialInfo]
  repeated DevicePointInfo points = 3;  // polygon corners, world metres
  string url     = 4;   // icon URL for furniture types [I]
}

message DevicePointInfo {
  float x = 1;
  float y = 2;
}

message MapHeadInfo {
  float resolution = 1;   // metres per grid cell (typically 0.05 m)
  int32 sizeX      = 2;   // grid width  (120 for RCV5)
  int32 sizeY      = 3;   // grid height (120 for RCV5)
  float minX       = 4;   // world-space X of grid origin (metres)
  float minY       = 5;   // world-space Y of grid origin (metres)
}

message MapDataInfo {
  bytes mapData = 1;   // raw grid bytes — see §4
}

message RoomDataInfo {
  int32  room_id          = 1;
  string room_name        = 2;
  int32  room_type_id     = 3;
  int32  meterial_id      = 4;   // 1 = carpet, 0 = hard floor (note APK typo)
  int32  clean_state      = 5;
  int32  room_clean       = 6;
  int32  room_clean_index = 7;
  DevicePoseDataInfo room_name_post = 8;  // {x, y} world coords for label placement [K]
  CleanPerferenceDataInfo clean_perfer = 9;  // [I — not parsed]
  int32  color_id         = 10;  // 1-5, maps to palette (see §6.2)
}

message DeviceHistoryPoseInfo {
  int32  poseId  = 1;               // sequence number of last point
  repeated DeviceCoverPointDataInfo points = 2;  // (x, y) in world metres
}

message DeviceCoverPointDataInfo {
  float x = 1;
  float y = 2;
}

message DeviceCurrentPoseInfo {
  float x   = 1;
  float y   = 2;
  float phi = 3;   // heading in radians, standard math convention (0=east, CCW positive)
}

message DevicePoseDataInfo {
  float x = 1;
  float y = 2;
}

message AiObjectInfo {
  int32  object_id      = 1;
  int32  object_type_id = 2;   // see §6.3
  float  x              = 3;
  float  y              = 4;
}

message RoomChainInfo {
  int32  room_id = 1;
  repeated ChainPoint points = 2;  // value encodes role: -1=outer wall, 1=separator, 2/3=inner
}
```

Field name translation: `karcher-home` applies `snake_case()` to protobuf field names before
surfacing them as dict keys (e.g. `mapHead` → `map_head`, `sizeX` → `size_x`). The parser
handles both forms. [K]

### 3.1 MapExtInfo semantics [K — APK `MapData.java`, `RobotMapApi.java` v1.4.32, 2026-06-14]

Both date fields are 32-bit signed integers carrying **Unix epoch seconds** (not milliseconds).
A 32-bit int fits epoch seconds through 2038; epoch-millisecond values for current dates
already exceed 2^31 and would overflow, so seconds is the only consistent interpretation.

**`task_begin_date` (field 1)** — the wall-clock time when the current (or most recent)
clean task started. The app uses it to detect session boundaries: when a newly received map
carries a different `task_begin_date` from the previous one, `RobotMapApi.parseGlobalInfo()`
resets the path overlay and clears the area map. It is stable for the entire duration of one
clean and changes exactly when the next clean begins.

**`map_upload_date` (field 2)** — the wall-clock time when this particular map snapshot was
uploaded by the robot. The app stores it as `mapTimeStamp` and compares it against
`MapInfoResp.timestamp` (from the MQTT map-info notification) to decide whether a more
recent map is available and should be re-requested.

**Deriving "last clean finished at":** the protocol carries no explicit finish timestamp.
An approximation is `task_begin_date + cleaning_time_minutes * 60`, assuming the robot
reports `cleaning_time` up to the moment it docks. The cleanest integration-side approach
is to record `datetime.now(UTC)` in the coordinator when it observes the
`CLEANING → DOCKED` state transition — no additional protocol parsing required.

---

## 4. Grid Byte Encoding

`MapDataInfo.mapData` after protobuf extraction carries a 6-byte binary header followed by
the grid bytes. [K — APK `MapProcessUtil.processMapData()`] The library strips this before
surfacing to the adapter; `map_parser.py` receives only the grid bytes.

### Two formats exist — distinguished by byte length

| Format | Bytes for 120×120 | Status |
|---|---|---|
| **Packed 2-bit** | 3 600 | [K — APK `parseGlobalMapData3600`; described in PROTOCOL.md §13.3] |
| **Full-resolution 1-byte** | 14 400 | [K — implemented in `map_render.py`; required for room ID data] |

The renderer auto-detects format: if `len(data) >= width * height` → full-res; otherwise → packed. [K]

**PROTOCOL.md §13.3 only documents the packed format.** The full-res format is what carries
room ID information and is what the RCV5 actually sends when rooms are present. [I — inferred
from the renderer needing it for room colours to work]

### 4.1 Packed 2-bit Format (3 600 bytes)

Byte index for cell `(row, col)`: `(row // 2) * 60 + (col // 2)`

Bit slot within that byte:
```python
bit_slot = (row % 2) + (col % 2) * 2   # 0..3
shifts   = {0: 6, 1: 4, 2: 2, 3: 0}
masks    = {0: 0xC0, 1: 0x30, 2: 0x0C, 3: 0x03}
cell_val = (byte & masks[bit_slot]) >> shifts[bit_slot]
```

| Value | Meaning |
|---|---|
| `0` | Free / unknown (unvisited) |
| `1` | Wall / obstacle |
| `3` | Cleaned |
| other | Treated as wall in some parse paths |

### 4.2 Full-resolution Format (14 400 bytes for 120×120)

Each byte encodes **both** the cell type (low 2 bits) **and** the room ID (byte value via range tables).

**Cell type** from low 2 bits (`byte & 0x3`):

| `byte & 0x3` | Meaning |
|---|---|
| `0` | Free / unknown |
| `1` | Cleaned |
| `2` | Deep-cleaned |
| `3` | Wall |

**Room ID decoding** from raw byte value [K — `map_render.decode_room_id_grid()`]:

| Byte range | Interpretation | Room ID formula |
|---|---|---|
| `0–9` | Not a room cell (free/cleaned/wall/unknown) | — |
| `10–59` | Unvisited room cell | `room_id = byte` |
| `60–127` | Cleaned room cell | `room_id = byte - 50` → IDs 10–77 |
| `128–146` | Unhandled by the app (no colour assigned) | — |
| `147–196` | **Carpet / second-pass room cell** — rendered as white checkerboard (§6.4) | `room_id = 206 - byte` → IDs 10–59 |
| `197–252`, `254` | Unhandled by the app (no colour assigned) | — |
| `253` | Carpet / second-pass cell outside any room — checkerboard over cleaned colour | — |
| `255` (0xFF) | Solid wall / obstacle marker | — |

Java bytes are signed — the app's branches in `GridMap.updateGlobalMap` are
`b in [-109, -60]` (= 147–196 unsigned) and `b >= 60` (= 60–127 unsigned only).
Earlier revisions of this table guessed 60–146 and 197–254 as cleaned ranges; the
verified colour pass handles neither beyond what is listed above.
[K — APK `GridMap.updateGlobalMap`, re-verified 2026-06-12]

**This is the authoritative source for which room a cell belongs to** — not the room chain
polygons, which are approximate outlines used for display only.

---

## 5. Coordinate System

```
World origin: (min_x, min_y) = bottom-left of the grid in metres
Resolution:   typically 0.05 m/cell (5 cm)
Grid cell (col, row) ↔ world (x, y):
    x = min_x + col * resolution
    y = min_y + row * resolution
    (inverse: col = int((x - min_x) / resolution))

Image Y-axis: FLIPPED relative to grid rows.
    grid row 0 = world y = min_y = image BOTTOM
    grid row (height-1) = world y_max = image TOP

Heading (phi): radians, standard math convention.
    0 = east (+X), π/2 = north (+Y), CCW positive.
```

All coordinates — `history_pose` points, `current_pose`, `charge_station`,
`cur_path/post` float array, `room_chain` points — share this world-space metric
convention. [K]

`room_chain` points are pre-converted to world coords by `map_parser._parse_room_chain()`:
```python
wx = min_x + point["x"] * resolution
wy = min_y + point["y"] * resolution
```

---

## 6. Sub-object Details

### 6.1 Room Chains (Perimeter Polygons)

Each room has a `RoomChainInfo` with a list of `ChainPoint` values encoded by a `value` field:

| `value` | Role | Used for |
|---|---|---|
| `-1` | Outer wall point | Outline polygon AND fill |
| `1` | Separator point | Fill only (excluded from outline) |
| `2` | Unknown interior | Fill only |
| `3` | Inner boundary | Fill only |

The outer wall points (`value == -1`) are stored in `RoomChain.points`; all others go into
`RoomChain.separator_points`. Current-room detection uses ray-casting point-in-polygon
against `points`. [K]

### 6.2 Room Colour Palette

APK-verified from `GridMap.java` (`ROOM_COLOR[]`). [K — 2026-05-08]

| `color_id` | Colour | Hex |
|---|---|---|
| 1 | Teal-green | `#C9DCD2` |
| 2 | Pink | `#E9BAC0` |
| 3 | Off-white | `#E8E7E3` |
| 4 | Light blue | `#BDDDE0` |
| 5 | Grey | `#B7B7B7` |

Index formula: `(color_id - 1) % 5`. Values cycle for more than 5 rooms. [K]

Carpet rooms (`meterial_id == 1`) get a vertical stripe hatch overlay in the renderer. [K]

### 6.3 AI Object Types

From `AiObjectType.java` [K — APK]. Only types surfaced in the app UI:

| `type_id` | Object | Render colour |
|---|---|---|
| 1001 | Sock | Orange |
| 1002 | Shoe | Brown |
| 1003 | Wire / cable | Red |
| 1005 | Carpet | Semi-transparent orange-brown convex hull |
| 1006 | Cat | Purple |
| 1007 | Dog | Purple |
| 1011 | Pet waste | Red (!) |
| 1017 | Scale | Blue |
| 1038 | Chair | Grey |

All AI objects — including 1005 carpet — render as labelled dots/icons. (An earlier
integration revision clustered 1005 points into convex hulls; the app never does this,
and the hull path is now disconnected. The carpet area comes from grid bytes, §6.4.)
[K — APK, 2026-06-12]

### 6.4 Area Carpets (rugs)

Two distinct carpet mechanisms exist in the app; the RCV5 uses the grid-byte one.

**Mechanism 1 — grid bytes (RCV5-confirmed, 2026-06-12).** Carpet cells are encoded
directly in the map grid: bytes 147–196 mark a carpet/second-pass cell inside a room
(`room_id = 206 - byte`), byte 253 outside any room. The app renders these as a
per-cell checkerboard — white where `row % 2 == col % 2`, the underlying room/cleaned
colour otherwise (`GridMap.updateGlobalMap`). This produces the dithered region visible
in the app over rugs. The integration replicates this in `map_render._build_base_image`.
[K — APK + live RCV5 map: no `furniture_info` present while the app showed the carpet]

Whether this byte range semantically means "carpet" or "cleaned twice" is unresolved —
the APK symbol names say `CleanedDouble`/`COLOR_COVER_TWICE`, but on the RCV5 the
observed region matches the physical rug. [I]

**Mechanism 2 — `furniture_info` quads (field 16, type_id 1550; not observed from the
RCV5).** Each entry is `{id, type_id, points[]}`, corners in world metres. The app
consumes exactly the first four points as a quad (`CarpetTexture.processPose` reads
8 floats; `CarpetMap.changeRectPose` draws the border cycle p0→p1→p2→p3) and ignores
any further points. `karcher-home` 0.5.1 surfaces the field as
`furniture_info: [{"id", "type_id", "points": [{"x", "y"}]}]`; the integration parses
it (`CarpetArea` DTO) and renders quads, but a live RCV5 capture (2026-06-12) contained
no `furniture_info` — the path may only apply to other models. [K — APK; I — RCV5 usage]

AI object type 1005 ("carpet", `AiObjectType.java`) is rendered by the app as a plain
object icon like any other detection — never as polygons. [K — APK
`RobotMapApi.parseObjectDataInfo`: no type-specific geometry]

### 6.5 History Pose Path

`DeviceHistoryPoseInfo.points` — persistent clean path, (x, y) world coords, accumulated
across sessions. [K]

Rendered as a dark-teal polyline (`#508C78` approximately) over the cleaned area. [K]

### 6.6 Current Path (`cur_path`)

Pushed live during cleaning on `/mqtt/{pid}/{sn}/thing/event/cur_path/post`. [K — APK]

Payload `params.cur_path` — flat float array:
```
[start_poseId, x0, y0, phi0, flag0, x1, y1, phi1, flag1, ...]
```
Validity: `len >= 6` and `(len - 2) % 4 == 0`. Each pose: 4 floats (x, y, phi, flag).
`flag` is the cleaning/navigation discriminator [K — APK `PathMap.java`, `ChainMap.java`]:
- `flag == 0` → transit/navigation point (robot moving to reach a cleaning area)
- `flag != 0` → actively cleaning point

The APK renders these as distinct visual styles: transit points are dimmed with no connecting line; cleaning points form a bright connected polyline. The current integration parser discards the flag — only X/Y are accumulated in `coordinator._cur_path`.

Can also be fetched on demand: `get_cur_path` / `get_cur_path_reply`. [K — APK]

Rendered as an amber polyline (`#FFA000`) on top of history path. [K]

---

## 7. Rendering Pipeline

```
MapSnapshot
    │
    ▼  _crop_cells()
Find content bounding box → add 10-cell margin → crop to (crop_h × crop_w)

    │
    ▼  _build_base_image()  [at scale × 4 supersampling]
1. White background (255, 255, 255)
2. Room colour fills from full-res grid bytes (decode_room_id_grid)
   └─ Carpet rooms: add vertical stripe hatch (darken every 3rd column)
3. Cleaned-area overlay (#D5F0E8) — only on non-room cells
4. Wall overlay (60, 60, 60) — dilated 1px for LANCZOS survival
   └─ True walls: raw byte in {0..9} with (byte & 0x3) == 3, OR byte == 0xFF

    │
    ▼  ImageDraw overlays
5. History path polyline (dark teal, `miter` joints)
6. Current path polyline (amber, `miter` joints)
7. AI object dots + labels
8. Room name labels (white halo for readability)
9. Charger dot (dark circle + light inner circle)
10. [robot position drawn by Lovelace card, not in PNG]

    │
    ▼  LANCZOS downsample  (4× supersample → output scale)
PNG bytes → KarcherMapImage → HA ImageEntity
```

Robot position is NOT drawn in the PNG — it is provided to the Lovelace card as
`robot_px {x, y, phi}` attributes on the vacuum entity, so the card can overlay an
animated icon. [K]

### Coordinate Conversion for the Lovelace Card

`world_to_pixel(wx, wy)` in `map_render.py`:
```python
col = int((wx - min_x) / resolution)   # clipped to [0, width-1]
row = int((wy - min_y) / resolution)   # clipped to [0, height-1]
px  = (col - layout.col0) * scale + scale // 2
py  = layout.out_h - 1 - ((row - layout.row0) * scale + scale // 2)
```

`room_cell_map` on the vacuum entity is RLE-encoded pixel spans per room:
`{room_id: [(px_row, col_start, run_len), ...]}`. Lovelace card uses this for room overlay
colouring without needing to decode the grid itself. [K]

---

## 8. Known Gaps

| Gap | Status |
|---|---|
| `MapExtInfo.map_valid` / `angle` semantics | [K] — fields confirmed and named; exact flag values and angle reference not decoded |
| `DeviceRoomMatrix` (room_matrix) format | [I] — field confirmed in protobuf; not decoded; likely a bitmap of room boundaries |
| `AllMapInfo` (map_info) structure | [I] — list of stored maps; content not decoded |
| `virtual_walls` format | [I] — field confirmed; content not decoded |
| Exact room chain `value=2` semantics | [A] — grouped with separator points; actual meaning unknown |
| `cur_path` flag field meaning | [K] — `0` = transit/navigation, non-zero = cleaning; confirmed in APK `PathMap.java` and `ChainMap.java` |
| Whether RCV5 ever sends multiple QuickLZ frames | [I] — APK loops over frames; single frame assumed in practice |
| Full-res vs packed format trigger | [I] — inferred that rooms present → full-res; no explicit trigger confirmed |
| Room ID range 197–254 in practice | [I] — formula matches `GridMap.java` pattern; no live capture confirmed |
