# Kärcher RCV5 — Data Types, Formats & Flows

All entries carry an epistemic tag:
- **[K]** Known — confirmed by traffic capture, APK decompilation, or working code
- **[I]** Inferred — derived from partial evidence; high confidence but not directly observed
- **[A]** Assumed — plausible extrapolation; not verified

Capture date: 2026-03-28 / 2026-05-08. Device: Kärcher RCV5 (firmware I3.12.26).

---

## 1. System Topology

```
  ┌──────────────┐         REST + MQTT/TLS         ┌─────────────────────────────┐
  │  Mobile App  │ ◄─────────────────────────────► │   3iRobotix Cloud           │
  │(com.kaercher │                                  │  eu-appaiot.3irobotix.net   │
  │ .homerobots) │                                  │  eu-gamqttaiot.3irobotix.net│
  └──────────────┘                                  └──────────────┬──────────────┘
                                                                   │  MQTT/TLS
  ┌──────────────┐         REST + MQTT/TLS                         │
  │ Home Assist. │ ◄─────────────────────────────► ───────────────┤
  │(karcher-home │                                                 │
  │   library)   │                                                 │
  └──────────────┘                                  ┌─────────────▼──────────────┐
                                                    │   Robot (RCV5)              │
                                                    │   Rockchip RV1126, Linux    │
                                                    │   MQTT client only          │
                                                    │   No local ports open       │
                                                    └─────────────────────────────┘
```

**All control and telemetry is cloud-brokered.** The robot is a pure MQTT client with no
local REST API and no open TCP ports. [K]

---

## 2. Transport Layers

### 2.1 REST (HTTPS)

| Property | Value | Status |
|---|---|---|
| Base URL (EU) | `https://eu-appaiot.3irobotix.net` | [K] |
| Purpose | Auth, device listing, OTA, map download (via `KarcherHome.get_map_data`) | [K] |
| mTLS client cert | `iot_dev.p12` (EC P-256, bundled in APK `assets/`) | [K] |
| Request signing | `sign = MD5(auth_token + timestamp + nonce + body_string)` | [K] |
| Body encoding for signing | Non-string values JSON-serialised (not Python repr) | [K] — was a library bug |
| Commands via REST | **No.** Confirmed absent by mitmproxy capture during Start/Pause | [K] |

### 2.2 MQTT

| Property | Value | Status |
|---|---|---|
| Broker (EU) | `eu-gamqttaiot.3irobotix.net:8883` | [K] |
| TLS version | TLS 1.2 | [K] |
| Cipher | `ECDHE-RSA-AES256-GCM-SHA384` | [K] |
| MQTT version | 3.1.1 | [K] |
| Clean session | true | [K] |
| Client auth | Username + password (MQTT-level); no client cert for MQTT | [K] |
| Server cert | Self-signed EC P-256 wildcard `*.3irobotix.net`, expires 2031-11-29 | [K] |
| Robot cert pinning | Application-layer against `server.bks` (password `sc2021`); closes silently on mismatch | [K] |
| App cert pinning | Same BKS trust store embedded in APK | [K] |
| python-karcher TLS | `tls_insecure_set(True)` — does NOT verify server cert | [K] |

### 2.3 Topic Schema

All topics share the prefix `/mqtt/{product_id}/{sn}/`. For the RCV5, `product_id` is the
numeric value of the `ProductId` enum in python-karcher. [K]

---

## 3. Data Types and Formats

### 3.1 Telemetry — `property/post` (Robot → Cloud → App/HA)

**Direction:** Robot publishes → cloud broker forwards → all subscribers (app + HA)
**Topic:** `/mqtt/{pid}/{sn}/thing/event/property/post` [K]
**Format:** JSON, same envelope as all MQTT messages [K]

Payload envelope:
```json
{
  "method": "event.property.post",
  "params": { <flat key-value map of device state> }
}
```

**Known fields in `params`** (all [K] unless noted):

| Field | Type | Units / Range | Notes |
|---|---|---|---|
| `work_mode` | int | See §4.1 | Primary state signal. Authoritative for HA state derivation. [K] |
| `status` | int | `4` = docked | Secondary signal. Used to disambiguate returning vs. docked. [K] |
| `charge_state` | int | `0` = not charging | Non-zero = charging/docked. [K] |
| `fault` | int | `0` = no fault | Non-zero can coexist with normal operation. Only treated as Error when `work_mode` is idle and `status ≠ 4`. [K] |
| `quantity` | int | 0–100 | Battery %. [K] |
| `wind` | int | 0–3 | Suction power: 0=Silent, 1=Standard, 2=Medium, 3=Turbo. [K] |
| `water` | int | 0–3 | Water level: 0=Inactive, 1=Low, 2=Medium, 3=High. Values 0–2 confirmed by capture; 3 inferred from pattern. [K/I] |
| `mode` | int | 0–2 | Cleaning type: 0=Vacuum, 1=Vacuum&Mop, 2=Mop. [K] |
| `tank_state` | int | `3` = seated | Water tank physical presence. APK-verified (`DevProperties.java`). [K] |
| `cloth_state` | int | `1` = installed | Mop cloth presence. APK-verified. [K] |
| `cleaning_time` | int | minutes | Minutes in current cleaning session. [K] |
| `cleaning_area` | int | 0.01 m² units | Divide by 100 for m². E.g. raw 2228 → 22.28 m². [K] |
| `current_map_id` | str/int | — | ID of the active map. [K] |
| `map_num` | int | — | Number of stored maps. [I] — seen in APK, not yet in a live capture |
| `has_new_map` | int | non-zero = new | Signals a new map is available. [I] — APK source, not live-captured |
| `main_brush` | int | minutes | Use time. Full life 360 h (21 600 min). APK-confirmed. [K] |
| `side_brush` | int | minutes | Full life 180 h (10 800 min). [K] |
| `hypa` | int | minutes | HEPA filter. Full life 180 h. [K] |
| `mop_life` | int | minutes | Mop pad. Full life 180 h. [K] |
| `net_stauts` | int | — | Network status. Upstream typo (not `net_status`). Actual semantics unknown. [K-typo; A-semantics] |

**Note:** The `property/post` push is unsolicited — the robot sends it on state change. The python-karcher
library (≤ 0.5.x) silently discards this payload; the integration patches `on_message` to call
`_update_device_properties` manually. [K]

### 3.2 Property Snapshot — `prop.get` / `get_reply` (HA → Cloud → Robot → Cloud → HA)

**Direction:** HA publishes request → robot replies with current state
**Request topic:** `/mqtt/{pid}/{sn}/thing/service/property/get` [K]
**Reply topic:** `/mqtt/{pid}/{sn}/thing/service/property/get_reply` [K]
**Format:** Same flat JSON `params` object as §3.1 [I — reply format not independently captured; assumed symmetric]
**Trigger:** Polled every 30 s by the coordinator as fallback; also forced on startup and reconnect. [K]

python-karcher bug: `get_device_properties()` returns stale cache if already subscribed. The
integration works around this by calling `request_device_update()` then waiting for the reply topic. [K]

### 3.3 Commands — `service_invoke` (App/HA → Cloud → Robot)

**Direction:** App/HA publishes → cloud broker forwards → robot executes
**Topic pattern:** `/mqtt/{pid}/{sn}/thing/service_invoke/{service_name}` [K]
**Reply topic:** `/mqtt/{pid}/{sn}/thing/service_invoke/{service_name}_reply` [K — topic exists; reply payload structure not fully documented]
**Format:** JSON envelope, version `"3.0"` [K]:

```json
{
  "method": "service.{service_name}",
  "msgId": "<unix_ms_as_string>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": { ... }
}
```

**Known commands** (all [K] unless noted):

| Command | `service_name` | Key params |
|---|---|---|
| Start/Resume cleaning | `set_room_clean` | `room_ids: []` (all), `ctrl_value: 1`, `clean_type: 0` |
| Pause | `set_room_clean` | `ctrl_value: 2`, `clean_type: 0` |
| Return to dock | `start_recharge` | `params: {}` |
| Cancel dock return (HA "stop") | `stop_recharge` | `params: {}` |
| Clean specific rooms | `set_room_clean` | `room_ids: [id, ...]`, `ctrl_value: 1` |
| Request map | `upload_by_mapid` | `mapId: <current_map_id>` |
| List saved maps | `get_map_list` | `params: {}` |
| Request current path | `get_cur_path` | `params: {}` |

**Notes on `set_room_clean`:**
- `room_ids: []` does **not** mean "all rooms" — firmware picks one room semi-randomly. Pass all known IDs for full-house clean. [K]
- `clean_type: 0` always observed; meaning of other values unknown. [K/A]
- `ctrl_value: 1` serves as both Start and Resume (same command). [K]

### 3.4 Property Set — `prop.set` (App/HA → Cloud → Robot)

Uses a **different topic and envelope** from `service_invoke` commands. Version `"1.0"`, method `"prop.set"`. [K]

**Topic:** `/mqtt/{pid}/{sn}/thing/service/property/set`

```json
{
  "method": "prop.set",
  "msgId": "...",
  "tenantId": "1528983614213726208",
  "version": "1.0",
  "params": { "wind": 1 }
}
```

**Known settable properties:**

| Property | Key | Values |
|---|---|---|
| Suction power | `wind` | 0=Silent, 1=Standard, 2=Medium, 3=Turbo [K] |
| Cleaning mode | `mode` | 0=Vacuum, 1=Vacuum&Mop, 2=Mop [K] |
| Water level | `water` | 1=Low, 2=Medium, 3=High; 0 sent by app when switching away from mop [K] |

### 3.5 Live Path — `cur_path/post` (Robot → Cloud → App/HA)

**Direction:** Robot publishes incremental path updates during cleaning
**Topic:** `/mqtt/{pid}/{sn}/thing/event/cur_path/post` [K — APK source; reception not confirmed in live capture]
**Format:** JSON envelope, `params.cur_path` is a flat `List<float>` [K — APK source]:

```
[start_poseId, x0, y0, phi0, flag0, x1, y1, phi1, flag1, ...]
```

Layout: 1 starting poseId + N×4 floats per pose. Validity: `len ≥ 6` and `(len - 2) % 4 == 0`. [K — APK]

Coordinates are in the robot's internal metric space (same as the protobuf map). [K]

On-demand request available via `get_cur_path` / `get_cur_path_reply`. [K — APK]

### 3.6 Map Data — `upload_by_mapid_reply` (Robot → Cloud → App/HA)

**Direction:** Triggered by `upload_by_mapid` request; robot sends binary reply
**Topic:** `/mqtt/{pid}/{sn}/thing/service_invoke_reply/upload_by_mapid` [K — APK]
**Format:** **Not JSON.** Raw binary: QuickLZ-compressed protobuf (`MapData.RobotMap`). [K — APK]

Parsing pipeline:
1. Decompress: QuickLZ level-1, potentially multiple concatenated frames. [K — APK]
2. Parse protobuf: `MapData.RobotMap.parseFrom(decompressed)`. [K — APK]
3. Extract `MapDataInfo.mapData` bytes: 6-byte header + grid bytes. [K — APK]

**Map grid format** (120×120 cells, `parseGlobalMapData3600` path, active on RCV5):
- 3 600 bytes total, 2 bits per cell. [K — APK]
- Byte index for cell `(row, col)`: `(row // 2) * 60 + (col // 2)`. [K]
- Cell values: `0`=free/unknown, `1`=wall/obstacle, `3`=cleaned area. [K — APK]

**Protobuf schema** (reconstructed from Java accessors, no `.proto` in APK):

| Message | Key fields | Status |
|---|---|---|
| `RobotMap` | `map_head`, `map_data`, `map_ext`, `room_data[]`, `history_pose`, `current_pose`, `charge_station`, `virtual_walls[]` | [K — APK] |
| `MapHeadInfo` | `resolution` (m/cell), `sizeX=120`, `sizeY=120`, `minX`, `minY` (world origin) | [K — APK] |
| `MapDataInfo` | `mapData` bytes (grid, §13.3 of PROTOCOL.md) | [K — APK] |
| `RoomDataInfo` | `roomId`, `roomName`, `colorId`, `materialId`, `cleanState` | [K — APK] |
| `DeviceHistoryPoseInfo` | `poseId`, `points[]` (`x`, `y`) — historical clean path | [K — APK] |
| `DeviceCurrentPoseInfo` | `x`, `y`, `phi` — robot position + heading | [K — APK] |
| `DevicePoseDataInfo` | `x`, `y` — charger location | [K — APK] |
| `DeviceRoomMatrix` | Room boundary bitmap | [K — APK; format not fully decoded] |

**python-karcher also provides `get_map_data()` via REST** (not MQTT). Whether the REST
and MQTT map payloads are identical in format is [I] — they likely are since the APK uses
the same `parseFrom` path for both.

### 3.7 Map List — `get_map_list_reply`

**Topic:** `/mqtt/{pid}/{sn}/thing/service_invoke_reply/get_map_list` [K — APK]
**Format:** [A] — likely JSON, payload structure not decoded.

---

## 4. State Derivation

### 4.1 `work_mode` → HA Vacuum State

`work_mode` is the **authoritative** state field. [K]

| `work_mode` values | HA intermediate | Final HA state |
|---|---|---|
| 1, 7, 25, 30, 36, 81 | CLEANING | `cleaning` |
| 4, 9, 27, 31, 37, 82 | PAUSE | `paused` |
| 5, 10, 11, 12, 21, 26, 32, 38, 47 | GO_HOME | `returning` or `docked` (if `status==4` or `charge_state>0`) |
| 0, 14, 23, 29, 35, 40, 85 | IDLE | `docked` (if charging), `error` (if `fault!=0`), else `idle` |

Completeness of these value lists: [I] — observed during testing; other values may exist for
unexercised modes (e.g. spot clean, zone clean, scheduled run). The `Unknown` path (`Docked`
if charging, else HA `Idle`) handles unseen values.

### 4.2 Consumable Life

All consumable fields are use-time counters (minutes elapsed). Full-life thresholds:

| Consumable | Field | Full life | Source |
|---|---|---|---|
| Main brush | `main_brush` | 21 600 min (360 h) | [K — APK `ConsumablesActivity`] |
| Side brush | `side_brush` | 10 800 min (180 h) | [K — APK] |
| HEPA filter | `hypa` | 10 800 min (180 h) | [K — APK] |
| Mop pad | `mop_life` | 10 800 min (180 h) | [K — APK] |

---

## 5. Authentication Flow

```
App/HA → POST /login (email + password + MD5 sign) → Cloud REST
Cloud REST → auth_token + MQTT credentials → App/HA
App/HA → MQTT CONNECT (username + password) → Cloud broker
Cloud broker → CONNACK → App/HA
App/HA → SUBSCRIBE /mqtt/{pid}/{sn}/# → Cloud broker
Cloud broker → forwards subscribed topics → App/HA
```

Tokens expire; the integration stores email + password (not tokens) in the HA config entry
to enable silent re-authentication. [K]

Re-auth: up to 3 attempts with backoff 5 s / 30 s / 120 s. On final failure: `ConfigEntryAuthFailed`. [K]

---

## 6. Map Fetch Flow

```
1. Coordinator reads current_map_id from DeviceProperties (from property/post push).
2. Coordinator publishes: upload_by_mapid { mapId: current_map_id }
3. Robot receives command → compresses map → publishes binary reply on upload_by_mapid_reply
4. Cloud broker forwards binary reply to all subscribers
5. Adapter receives bytes → QuickLZ decompress → protobuf parse → MapSnapshot DTO
6. Coordinator stores MapSnapshot; triggers map render in executor (numpy + Pillow → PNG)
7. ImageEntity serves PNG to HA frontend
```

Trigger conditions [K]: startup, dock event, every 10 s during cleaning.

---

## 7. Gaps and Unknowns

| Topic | Status | Notes |
|---|---|---|
| `property/get_reply` payload structure | [A] | Assumed same as `property/post`; not independently captured |
| `service_invoke_reply` payload content | [A] | Topics confirmed in APK; payload structure not decoded for most commands |
| Full `work_mode` value set | [I] | Observed set covers common operations; exotic modes (spot, zone, schedule) unknown |
| `clean_type` in `set_room_clean` | [A] | Always `0` in captures; other values and semantics not observed |
| `map_num` / `has_new_map` semantics | [I] | Seen in APK `DevProperties.java`; not live-captured yet |
| Map upload via `upload_by_maptype` | [A] | Topic observed in captures; direction and trigger unclear — may be robot-initiated upload |
| `net_stauts` field semantics | [A] | Upstream typo confirmed; actual meaning of integer values unknown |
| `DeviceRoomMatrix` (room_matrix) format | [I] | Field confirmed in protobuf schema; decoding not implemented |
| REST map vs MQTT map format parity | [I] | Assumed identical; both use `MapData.RobotMap` protobuf per APK |
| `water=0` robot feedback | [I] | App sends `water=0` when switching away from mop; whether robot also reports `water=0` in `property/post` unverified |
| Multiple QuickLZ frames | [I] | APK loops over frames; whether the RCV5 ever sends more than one frame in a map reply is unobserved |
| `cur_path/post` live reception | [I] | Topic and format confirmed in APK; real-time reception during a live session not yet confirmed in integration |
| OTA channel reachability for commands | [K-blocked] | OTA endpoint confirmed; firmware image encrypted (RV1126 TrustZone key) |
| Local MQTT interception | [K-blocked] | Certificate pinning prevents without UART/firmware access |
