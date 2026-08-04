# Kärcher RCV5 App — Feature Inventory & Gap Analysis

Source: decompiled `KHR_1.4.32_APKPure.apk` via jadx, inspected 2026-05-03 / 2026-05-08.
Main package: `com.irobotix.rcvhome`

## Cleaning Operations

- **Modes:** Auto clean, Sweep only, Mop only, Sweep+Mop
- **Targeted cleaning:** Spot/point clean, Zone clean (polygon areas), Edge/perimeter clean, Room-specific clean
- **Controls:** Pause, Resume, Stop, Return to dock
- **Parameters:** Suction level, Water level, Carpet mode/detection

## Maps & Rooms

- Build, rename, delete, and switch between multiple maps
- Split and rename rooms
- Set per-room preferences (suction/water level per room)
- Virtual walls — create, edit, delete
- Real-time robot position and cleaning path visualization

## Scheduling / Plans

- Create, edit, delete cleaning schedules with repeat options
- Plan-based room selection
- Two plan variants (standard and 330G model-specific)

## Device Setup & Management

- BLE + WiFi pairing/onboarding
- QR code scanning for device setup
- Multiple device support
- Factory reset, find device (beep), firmware OTA upgrade
- Fault code detection and display

## Settings

- Quiet mode with configurable time window (begin/end time)
- Voice/language selection with downloadable voice packs
- Volume control
- Carpet detection toggle

## Consumables Tracking

- Usage % for: main brush, side brush, HEPA filter, mop cloth, water tank
- Reset individual consumable counters
- Replacement instructions per consumable

## Cleaning History

- Per-session records: timestamp, duration, area covered
- Delete records

## User Account & Sharing

- Login, registration, password reset
- Device sharing with other users (send/receive invitations)
- Shared device management / unbind

## Backend & Communication

- MQTT for all robot commands and property updates
- HTTP/REST API (Retrofit) for account/cloud operations
- WebSocket real-time communication
- Request/response encryption
- Firebase: analytics, FCM push notifications, crash reporting

## MQTT Commands (observed in source)

| Command | Description |
|---|---|
| `start_clean` | Full auto clean |
| `start_sweep` | Sweep only |
| `start_mop` | Mop only |
| `start_sweep_mop` | Sweep + mop |
| `pause_clean` | Pause current job |
| `stop_clean` | Stop and idle |
| `start_recharge` | Return to dock |
| `start_point_clean` | Spot/point clean |
| `set_room_clean` | Room-based clean |
| `set_zone_clean` | Zone clean (polygon) |
| `set_point_clean` | Set target point |
| `edge_clean` | Edge/perimeter clean (RCV2 only) |
| `start_station_act` | Dock station action. `station_act: 3` = auto-empty (dust collection) — RCV5 + Suction Station. See `doc/PROTOCOL.md` §15. |
| `set_calibration` | Robot calibration |
| `set_direction` | Directional movement (RCV2 only) |
| `set_preference` | Set robot preferences |
| `reset_consumable` | Reset consumable counter |
| `reset_factory` | Factory reset |
| `reset_map` | Clear map data |
| `find_device` | Locate robot (beep) |
| `delete_device` | Remove device from account |

## MQTT Properties Monitored

| Property | Description |
|---|---|
| `charge_state` | Battery / charge status |
| `status` | Overall robot status |
| `work_mode` | Current work mode |
| `sweep_type` | Sweep type variant |
| `mop_route` | Mop routing pattern |
| `wind` | Suction level |
| `water` | Water level |
| `tank_state` | Water tank presence: 3 = seated. APK-verified 2026-05-08. |
| `cloth_state` | Mop cloth presence: 1 = installed. APK-verified 2026-05-08. |
| `mop_life` | Mop pad remaining life |
| `main_brush` | Main brush remaining life |
| `side_brush` | Side brush remaining life |
| `hypa` | HEPA filter remaining life |
| `cleaning_time` | Session duration |
| `cleaning_area` | Session area covered |
| `quantity` | Session count |
| `current_map_id` | Active map ID |
| `map_num` | Number of maps stored |
| `build_map` | Map-building status |
| `quiet_is_open` | Quiet mode enabled |
| `quiet_begin_time` | Quiet mode start (minutes since midnight) |
| `quiet_end_time` | Quiet mode end (minutes since midnight) |
| `volume` | Speaker volume (0–100) |
| `sound` | Sound setting |
| `voice_type` | Voice pack selection |
| `net_status` | Network connectivity |
| fault codes | Error/fault state |
| `station_act` | Dock busy flag. `1` = station action running; app refuses to start a clean. |
| `dust_action` | Auto-empty progress. `1` or `2` = emptying in progress. |
| `charge_station_type` | Dock type. `0` = plain charging dock; non-zero = Suction Station attached. |

---

## Gap Analysis: App Features vs. HA Integration

### Implemented

| Feature | HA Entity |
|---|---|
| Start / Pause / Stop / Return to dock | `vacuum` entity |
| State display (cleaning, docked, idle, error…) | `vacuum` entity |
| Fan speed (Silent / Standard / Medium / Turbo) | `vacuum` fan speed |
| Locate / find robot (`find_device`) | `vacuum.locate` |
| Cleaning mode (Vacuum / Vacuum+Mop / Mop) | `select.cleaning_mode` |
| Water level (Low / Medium / High) | `select.water_level` |
| Room selection | `select.room` |
| Mop attachment detection (tank_state + cloth_state) | gates `cleaning_mode` options; `disabled_options` attribute |
| Battery % | `sensor.battery` |
| Cleaning area (current session) | `sensor.cleaning_area` |
| Cleaning time (current session) | `sensor.cleaning_time` |
| Main brush wear % | `sensor.main_brush` |
| Side brush wear % | `sensor.side_brush` |
| HEPA filter wear % | `sensor.filter` |
| Mop pad wear % | `sensor.mopping_pad` |
| Error / fault indicator | `binary_sensor.error` |
| Current room indicator | `sensor.current_room` |
| Map image (live: rooms, path, robot/charger position, carpet, objects) | `image` entity |
| Diagnostics dump | `diagnostics` |
| Suction Station attached / not (`charge_station_type`) | `binary_sensor.station_attached` |
| Auto-empty in progress (`dust_action`) | `binary_sensor.emptying` |
| Manual station empty (`service.start_station_act`) | `button.empty_station` |

### Gaps — controllable via MQTT (feasible)

| Feature | Effort | MQTT details |
|---|---|---|
| **Quiet mode** — enable + begin/end time | Low | `service.set_quiet_time`; params `quiet_is_open` (0/1), `quiet_begin_time` / `quiet_end_time` (minutes since midnight). Properties already in stream. Would be 1 `switch` + 2 `time` entities. |
| **Carpet turbo boost** | Low | `prop.set {"privacy": {"carpet_turbo": 0\|1}}`. RCV5-only `switch`. |
| **Carpet avoidance** | Low | `prop.set {"privacy": {"carpet_avoid": 0\|1}}`. RCV5-only `switch`. |
| **AI room recognition** | Low | `prop.set {"privacy": {"ai_recognize": 0\|1}}`. RCV5 + RCF3 `switch`. |
| **Volume control** | Low | `prop.set {"volume": 0–100}`. `volume` already in property stream. `number` entity. |
| **Reset consumables** | Medium | `service.reset_consumable` MQTT call. One `button` per consumable. Payload format needs confirming from traffic capture. |
| **Mop attachment binary sensors** | Low | `tank_state` and `cloth_state` already parsed in `_types.py`/`adapter.py`. Just need `binary_sensor` entities exposing them. |
| **Map count sensor** | Low | `map_num` already in property stream. Simple `sensor`. |
| **Sweep type select** | Low | `sweep_type` in stream. Valid values not yet reversed — needs capture or APK dig. |
| **Mop route select** | Low | `mop_route` in stream. Same — values need confirming. |
| **Map switching** | Medium | `service.set_current_map_id` with `map_id`. Would be a `select`, but requires enumerating stored maps — only `current_map_id` is in the property stream today, not the full list. |

### Gaps — cloud API dependent (not direct MQTT)

| Feature | Notes |
|---|---|
| **Schedules / Plans** | Cloud-side constructs. Requires REST API calls via `python-karcher`. Not feasible without library support. |
| **Cleaning history** | Cloud REST API only (`/smart-home-service/cleanRecord/list`). No MQTT path. |
| **Virtual walls / no-go zones** | Embedded in map protobuf, uploaded to cloud. Walls are visible in current map rendering (objects layer). Editing requires cloud upload — not feasible via MQTT. |
| **Per-room preferences** | Suction/water level per room is plan-side, cloud-stored. |
| **Zone clean with coordinates** | MQTT service call exists (`set_zone_clean`), but polygon geometry is cloud-mediated. |
| **Spot clean with coordinates** | Same as zone clean — service is MQTT, coordinates via cloud. |
| **OTA firmware trigger** | Possible via REST API; high risk, probably not HA-appropriate. |
| **Device sharing** | Cloud-only. Not HA-relevant. |

### Not applicable to RCV5

| Feature | Reason |
|---|---|
| Manual joystick control (`set_direction`) | RCV2 only — explicit model gate in `ControlMainActivity.java` |
| Edge clean | RCV2 only |

> **Corrected 2026-08-03, implemented 2026-08-04.** This table previously claimed auto-empty was
> "not present on RCV5 hardware". That was wrong. The Suction Station RCV 5 (part 22696430) is a
> real auto-empty dock — sold standalone or bundled in an initial pack with the robot — and the
> APK gates its UI on the RCV5 product ID specifically. Device-confirmed on hardware and shipped
> as the three entities under
> *Implemented* above. See `doc/PROTOCOL.md` §15.
>
> That entry also lumped in **electrolysis / mop-wash station actions**, which are now
> *unverified* rather than N/A — no RCV5 product-ID gate was found either way, and strings like
> `fault_title_587` ("The water station is disconnected") and `fault_title_2013` ("Return to the
> self-cleaning station to clean the mop pad") show the concept exists in the app without
> establishing whether RCV5 reaches it. Do not treat as settled in either direction.

---

## Carpet Settings — MQTT payload detail

Properties nested under a `privacy` object (APK-verified `CarpetSettingVM.java`, 2026-05-08):

```json
{
  "method": "prop.set",
  "msgId": "...",
  "tenantId": "1528983614213726208",
  "version": "1.0",
  "params": {
    "privacy": {
      "carpet_turbo": 0,
      "carpet_avoid": 0,
      "carpet_show": 0
    }
  }
}
```

## Quiet Mode — MQTT payload detail

Times as minutes since midnight (APK-verified `QuietSettingActivity.java`, 2026-05-08):

```json
{
  "method": "service.set_quiet_time",
  "msgId": "...",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {
    "quiet_is_open": 1,
    "quiet_begin_time": 1320,
    "quiet_end_time": 540
  }
}
```

Validation: minimum window 18 h (1080 min). `begin > end` wraps past midnight.

## Mop Attachment Detection — semantics

APK-verified `DevProperties.java` + `PlanAddCleanPlanActivity.java`, 2026-05-08:

| Field | Value | Meaning |
|---|---|---|
| `tank_state` | `3` | Water tank seated |
| `tank_state` | other | Tank absent or unknown |
| `cloth_state` | `1` | Mop cloth installed |
| `cloth_state` | `0` | Mop cloth absent |

Both must be true (`tank_state == 3 && cloth_state == 1`) to enable mop modes — mirrors the app's RCV5 gate in `PlanAddCleanPlanActivity.java`.
