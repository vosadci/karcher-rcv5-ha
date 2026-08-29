# Kärcher RCV5 Protocol — Reverse Engineering Notes

All findings below were obtained by:
- MQTT traffic capture via `tools/capture_commands.py` (python-karcher + wildcard MQTT subscription)
- Android emulator (API 28, Google APIs) + mitmproxy for HTTPS interception
- APK decompilation via jadx (`KHR_1.4.32_APKPure.apk`)
- Direct TLS probing with openssl and a custom Python spy server

Capture date: **2026-03-28**. Device: **Kärcher RCV5**.

---

## 1. Platform and Cloud Architecture

The robot uses the **3irobotix** cloud platform — not Tuya, not iRobot. All traffic goes to
3irobotix-operated infrastructure.

| Service | URL / endpoint |
|---|---|
| REST API (EU) | `https://eu-appaiot.3irobotix.net` |
| MQTT broker (EU) | `eu-gamqttaiot.3irobotix.net:8883` (TLS) |
| OTA updates | `https://ota.3irobotix.net:8001/service-publish/open/upgrade/try_upgrade` |
| Tenant ID | `1528983614213726208` (hardcoded in app and payloads) |

The library supports three regions: EU (`eu-appaiot`), US (`us-appaiot`), CN (`cn-appaiot`).
The correct MQTT hostname is returned by the REST `/domains` endpoint as part of login
(`eu-gamqttaiot.3irobotix.net`, **not** `eu-mqttaiot` — note the `g`).

---

## 2. Authentication (REST)

Authentication is handled by python-karcher (`KarcherHome.create()` + `login()`).
Credentials (email + password) are stored in the HA config entry because tokens expire;
re-login uses the stored credentials.

The REST API uses a request signing scheme:
- Headers: `sign = MD5(auth_token + timestamp + nonce + body_string)`
- Body string for POST: keys and values concatenated in order, with list/dict values
  JSON-serialised (not Python `str()`-serialised — a bug in older python-karcher versions).

---

## 3. MQTT Connection

The robot and the app both connect to `eu-gamqttaiot.3irobotix.net:8883` with:
- **TLS 1.2**, cipher `ECDHE-RSA-AES256-GCM-SHA384` (confirmed by TLS spy)
- **Server certificate**: self-signed EC P-256 wildcard, `CN=*.3irobotix.net`
  (issued 2021-ish, valid until 2031-11-29, self-signed — Issuer == Subject)
- **Client authentication**: username + password (MQTT-level credentials), no client cert
  for MQTT (mutual TLS is used for the REST API separately via `iot_dev.p12`)
- **MQTT version**: 3.1.1
- **Clean session**: true

The python-karcher library uses paho-mqtt with `tls_insecure_set(True)` — it does NOT verify
the server certificate. The robot firmware, however, DOES verify the server certificate
against a pinned cert (see §6).

---

## 4. MQTT Topic Patterns

All topics are prefixed `/mqtt/{product_id}/{sn}/`.
For the RCV5, `product_id` is the numeric value of the `ProductId` enum in python-karcher.

```
# Robot publishes state updates (unsolicited push):
/mqtt/{product_id}/{sn}/thing/event/property/post

# App requests a full property snapshot:
/mqtt/{product_id}/{sn}/thing/service/property/get
# Robot replies to snapshot request:
/mqtt/{product_id}/{sn}/thing/service/property/get_reply

# App sends a named service command:
/mqtt/{product_id}/{sn}/thing/service_invoke/{service_name}
# Robot acknowledges the command:
/mqtt/{product_id}/{sn}/thing/service_invoke/{service_name}_reply

# Robot uploads map data (observed during capture, not yet decoded):
/mqtt/{product_id}/{sn}/thing/service_invoke/upload_by_maptype
/mqtt/{product_id}/{sn}/thing/service_invoke/upload_by_maptype_reply
```

---

## 5. Commands (Confirmed)

Commands are MQTT PUBLISH messages. The general payload structure is:

```json
{
  "method": "service.{service_name}",
  "msgId": "<unix_millisecond_timestamp_as_string>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": { ... }
}
```

`msgId` is the current Unix time in milliseconds as a string (from `karcher.utils.get_timestamp_ms()`).

### Start cleaning / Resume after pause

Both actions use the same command. `ctrl_value: 1` from dock/idle = start;
from paused state = resume.

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/set_room_clean
```
```json
{
  "method": "service.set_room_clean",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {"room_ids": [], "ctrl_value": 1, "clean_type": 0}
}
```

### Pause during cleaning

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/set_room_clean
```
```json
{
  "method": "service.set_room_clean",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {"room_ids": [], "ctrl_value": 2, "clean_type": 0}
}
```

### Area (zone) cleaning

⚠ **APK-derived, not yet device-capture-verified.** Command names, topics, and
payload shapes are from APK v1.4.32 (`ControlVM.setZonePoints` / `setZoneClean`,
`DeviceMethod.SET_ZONE_POINTS` / `SET_ZONE_CLEAN`). The coordinate units of
`zone_points` are **inferred** to be world metres — both this command and
`set_virtual_wall` build their payload from raw `RobotMapApi` draw-space floats
with no conversion, and the virtual-wall read path is verified as world metres.
Confirm units/Y-axis direction against a real capture before treating as fact.

Two-step: define the rectangle, then start. `zone_points` is a flat list of
polygon corners `[x1, y1, x2, y2, ...]` in world metres (4 corners for one
rectangle). v1 sends a single rectangle.

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/set_zone_points
```
```json
{
  "method": "service.set_zone_points",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {"zone_points": [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0, 1.0, -1.0]}
}
```
```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/set_zone_clean
```
```json
{
  "method": "service.set_zone_clean",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {"ctrl_value": 1}
}
```

`ctrl_value`: `1` = start, `2` = pause, `0` = stop-to-idle (same convention as
`set_room_clean`; the `0` stop case is inferred for zone — see §5).

Pause/resume must route through `set_zone_clean`, not `set_room_clean`. The app
decides this from the live `work_mode` (`IotBase.getCleanMode == 6`), not local
state. The robot encodes `(clean-family, lifecycle)` in `work_mode`; the zone
family is `{30 cleaning, 31 paused, 32 returning, 35 idle}` — consistent with the
§6 lifecycle sets (30∈cleaning, 31∈pause, 32∈go-home, 35∈idle). The integration
mirrors this: `vacuum.pause`/`stop`/resume check `work_mode ∈ {30,31,32,35}` and
route to `set_zone_clean` so app-started and HA-restart cases stay correct.

HA exposes the start through `vacuum.send_command` command `app_zone_clean` with
`params: {rect_px: [x0, y0, x1, y1]}` — two opposite rectangle corners in
rendered-map-image pixels; the integration converts to world metres.

### Return to dock

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/start_recharge
```
```json
{
  "method": "service.start_recharge",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {}
}
```

### Stop a clean to idle (`ctrl_value: 0`)

**Device-verified on RCV5, 2026-06-23.** Sending `set_room_clean {ctrl_value: 0}`
mid-clean transitions the robot to an idle work_mode (a true stop, distinct from
pause). `ctrl_value` has three values — `0` = stop/cancel-to-idle, `1` = start/resume,
`2` = pause — and the firmware has a distinct idle work_mode per clean family separate
from pause (`WorkModeKt.java`: e.g. AUTO_PAUSE `4` vs IDLE `0`; AREA_PAUSE `31` vs
AREA_IDLE `35`).

There is **no `stop_clean` command** (the entry in `APP_FEATURES.md` is spurious;
`pause_clean`/`start_clean` constants exist but are never sent — reply-topic matching
only). The official cleaning UI's play button only toggles `1`/`2`, so the app itself
never issues a stop-to-idle for a room clean; `ctrl_value: 0` was found via
`ManualControlActivity.onBackPressed` (`set_room_clean {clean_type:0, ctrl_value:0,
room_ids:[]}` stops manual driving) and `setPointClean(0)` / `setRoomClean(_, 0)`
(stop point cleans), then confirmed to also stop a room clean. The integration's
`vacuum.stop` sends this.

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/set_room_clean
```
```json
{
  "method": "service.set_room_clean",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {"room_ids": [], "ctrl_value": 0, "clean_type": 0}
}
```

Area (zone) cleans stop via `set_zone_clean {ctrl_value: 0}` by symmetry (the app
only sends zone `1`/`2`, so the `0` case there is still inferred — not separately
captured). HA's `stop` service routes by clean type, like pause/resume.

### Cancel dock return (HA "stop" while returning)

Cancels an in-progress dock return and leaves the robot stationary on the floor.
`stop_recharge` is what the integration sends when `vacuum.stop` is called while the
robot is RETURNING.

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/stop_recharge
```
```json
{
  "method": "service.stop_recharge",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {}
}
```

### Set cleaning mode (vacuum / mop / both)

```
Topic:  /mqtt/{product_id}/{sn}/thing/service/property/set
```
```json
{"method": "prop.set", "msgId": "...", "tenantId": "...", "version": "1.0", "params": {"mode": 1}}
```

| `mode` | Label |
|---|---|
| `0` | Vacuum |
| `1` | Vacuum & Mop |
| `2` | Mop |

Note: `mode` here is the cleaning type selector — distinct from `work_mode` which is the operational state (cleaning/idle/returning). The HA integration exposes this as `select.karcher_cleaning_mode`.

### Set water level (mop)

```
Topic:  /mqtt/{product_id}/{sn}/thing/service/property/set
```
```json
{"method": "prop.set", "msgId": "...", "tenantId": "...", "version": "1.0", "params": {"water": 2}}
```

| `water` | Label |
|---|---|
| `0` | Low |
| `1` | Medium |
| `2` | High |

The HA integration exposes this as `select.karcher_water_level` with options Low/Medium/High.
Scale is **0-based** (0=Low, 1=Medium, 2=High) — APK-verified 2026-06-18 from
`ControlMainActivity.setUpWaterTab` / `PlanAddCleanPlanActivity.setUpWaterTab`
(`setWater(tabIndex)` writes 0/1/2; load clamps `water <= 2 ? water : 2`) and
`CustomRoomAdapter.getCleanText` (0→Low, 1→Medium, 2→High). Device-confirmed: a
room set to High in the app stores `water=2` in the per-room preference array.

There is no value 3. `water=0` (Low) is also what the app stores when leaving mop
mode, and the water selector is covered/disabled while mode=Vacuum.

### Set suction power (fan speed)

Uses a different topic and payload structure from service_invoke commands:
`version: "1.0"` and `method: "prop.set"`.

```
Topic:  /mqtt/{product_id}/{sn}/thing/service/property/set
```
```json
{
  "method": "prop.set",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "1.0",
  "params": {"wind": 1}
}
```

Wind values (confirmed via traffic capture 2026-03-28):

| `wind` | Label |
|---|---|
| `0` | Silent |
| `1` | Standard |
| `2` | Medium |
| `3` | Turbo |

The HA integration exposes these as fan speed options on the vacuum entity
(`VacuumEntityFeature.FAN_SPEED`). The `coordinator.async_set_property()` method handles
this topic/payload format.

---

### Reset consumable timer

Resets the wear counter for a single consumable after replacement.
APK-verified (`ConsumableVM.kt`, v1.4.32, 2026-06-02).

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/reset_consumable
```
```json
{
  "method": "service.reset_consumable",
  "msgId": "1743175200000",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {"consumable": 1}
}
```

| `consumable` | Part |
|---|---|
| `1` | Main brush (360 h life) |
| `2` | Side brush (180 h life) |
| `3` | Filter (180 h life) |
| `4` | Mop pad (180 h life) |

Reply topic: `.../thing/service_invoke/reset_consumable_reply`

The app also issues a `prop.set` with the field zeroed (`{"main_brush": 0}` etc.) after
receiving the reply — this appears to be a belt-and-suspenders UI refresh. The robot
issues its own `property/post` push to confirm the reset.

---

### Notes on `set_room_clean` parameters

| Field | Observed values | Meaning |
|---|---|---|
| `room_ids` | `[id, ...]` | Explicit list of room IDs to clean. Pass all known room IDs for a full-house clean. An empty list does **not** mean "all rooms" — the firmware picks one room semi-randomly. |
| `ctrl_value` | `0` = stop-to-idle (device-verified 2026-06-23 — see §5), `1` = start/resume, `2` = pause | |
| `clean_type` | `0` | Unknown; always 0 in captures. Possibly 0=auto, others=specific mode. |

Room IDs and names come from the stored map protobuf (`RoomDataInfo.roomId` / `roomName`),
fetched via `KarcherHome.get_map_data(dev, map=1)`. The HA integration exposes a
`SelectEntity` (entity `select.karcher_room`) pre-populated with room names at startup.
Selecting a room causes the next `Start` command to send `room_ids: [selected_id]`.

---

## 6. Device State Fields

The robot publishes state as a flat JSON object. All known fields:

| Field | Type | Notes |
|---|---|---|
| `work_mode` | int | **Primary state signal.** Maps directly to HA vacuum state. |
| `mode` | int | Always `0`; ignore for state mapping. |
| `status` | int | Secondary signal. `4` = docked. |
| `charge_state` | int | `0` = not on dock; `1` = on dock (charging or fully charged). Device does not transition to a distinct value when full. "Actively charging" = `charge_state == 1 && fault != 2105`. Charging complete is signalled by `fault == 2105` (`FAULT_ROBOT_CHARGE_FINISH`). APK-verified (`ControlMainActivity.java:3338`, `RobotError.java:45`); device-verified 2026-06-03. |
| `fault` | int | `0` = no fault. Non-zero values can coexist with normal operation. 21xx codes are lifecycle status notifications, not hardware faults. Only treat as Error state when `work_mode` is in the idle set and `status` ≠ 4. See §6 fault code table below. |
| `quantity` | int | Battery level, 0–100. |
| `wind` | int | Suction level (fan speed). Higher = stronger. |
| `water` | int | Water level (mop feature). `0` if not a mop model or no water. |
| `tank_state` | int | Water tank physical presence. `3` = tank seated; other values = absent/unknown. APK-verified (`DevProperties.java`, `PlanAddCleanPlanActivity.java`) 2026-05-08. |
| `cloth_state` | int | Mop cloth physical presence. `1` = installed; `0` = absent. APK-verified (`DevProperties.java`, `PlanAddCleanPlanActivity.java`) 2026-05-08. |
| `cleaning_time` | int | Minutes elapsed in current cleaning session. Raw value is in minutes. |
| `cleaning_area` | int | Area cleaned in current session. Raw value is in units of 0.01 m²; divide by 100 to get m² (e.g. raw 2228 → 22.28 m²). |
| `current_map_id` | str/int | ID of the currently active map. |
| `main_brush` | int | Main brush use time in minutes. Full life 360 h (21 600 min). Confirmed from APK (`ConsumablesActivity`) 2026-05-03. |
| `side_brush` | int | Side brush use time in minutes. Full life 180 h (10 800 min). |
| `hypa` | int | HEPA filter use time in minutes. Full life 180 h (10 800 min). |
| `mop_life` | int | Mop pad use time in minutes. Full life 180 h (10 800 min). |

### `work_mode` → HA State Mapping

`work_mode` is the authoritative state field. All observed values per state:

| HA State | `work_mode` values observed |
|---|---|
| `cleaning` | 1, 7, 25, 30, 36, 81 |
| `paused` | 4, 9, 27, 31, 37, 82 |
| `returning` / `docked` | 5, 10, 11, 12, 21, 26, 32, 38, 47 |
| `idle` / `docked` / `error` | 0, 14, 23, 29, 35, 40, 85 |

For the `returning` and `idle` sets, distinguish docked vs. not-docked by checking:
`status == 4` OR `charge_state > 0`.

Full decision logic (from `coordinator.py`):

```
work_mode in CLEANING  → Cleaning
work_mode in GO_HOME:
  if docked             → Docked
  else                  → Returning
work_mode in PAUSE     → Paused
work_mode in IDLE:
  if docked             → Docked
  elif fault != 0       → Error
  else                  → Idle
unknown work_mode:
  if docked             → Docked
  else                  → Unknown (rendered as Idle in HA)
```

### `fault` Field — Code Reference

APK-verified (`RobotError.java`, `RobotFaultCode.java`, `ControlMainActivity.java` — v1.4.32, 2026-06-01).

The **21xx range are lifecycle status notifications**, not hardware faults. The robot emits them during normal operation transitions; they coexist with active `work_mode` values and do not trigger the HA Error state. The app displays them in the status text widget, not in the error dialog.

| Code | Constant (`RobotError.java`) | Meaning |
|------|------------------------------|---------|
| 0 | `FAULT_NONE` | No fault |
| 100 | `FAULT_HWDRIVER` | Hardware driver error |
| 500 | `FAULT_LIDAR_TIME_OUT` | LiDAR timeout |
| 501 | `FAULT_WHEEL_UP` | Wheel lifted |
| 502 | `FAULT_LOW_START_BATTERY` | Battery too low to start |
| 503 | `FAULT_DUSTBOX_NOT_EXIST` | Dust box not installed |
| 504 | `FAULT_GEOMAGETISM_STRUCT` | Geomagnetic sensor fault |
| 505 | `FAULT_START_DOCK_FAILED` | Failed to start from dock |
| 506 | `FAULT_FOLLOWE_IR_EXCEPTION` | Follow IR sensor exception |
| 507 | `FAULT_RELOCALIZATION_FAILED` | Relocalization failed (terminal) |
| 508 | `FAULT_SLOPE_START_FAILED` | Cannot start on slope |
| 509 | `FAULT_CLIFF_IR_STRUCT` | Cliff IR sensor fault |
| 510 | `FAULT_BUMPER_STRUCT` | Bumper sensor fault |
| 511 | `FAULT_GO_DOCK_FAILED` | Failed to return to dock |
| 512 | `FAULT_PUT_MACHINE_DOCK` | Place robot on dock |
| 513 | `FAULT_NAVIGATION_FAILED` | Navigation failed |
| 514 | `FAULT_ESCAPE_FAILED` | Escape from stuck failed |
| 515 | `FAULT_DOCK_CLIP_EXCEPTION` | Dock clip exception |
| 516 | `FAULT_BATTERY_TEMPATURE` | Battery temperature fault |
| 517 | `FAULT_SYSTEM_UPGRADE` | System upgrading |
| 518 | `FAULT_WAIT_CHARGE_FINISH` | Waiting for charge to finish |
| 519 | `FAULT_ROLL_BRUSH_STALL` | Main brush stalled |
| 520 | `FAULT_SIDE_BRUSH_STALL` | Side brush stalled |
| 521 | `FAULT_WATER_BOX_NOT_EXIST` | Water box not installed |
| 522 | `FAULT_MOPPING_NOT_EXIST` | Mop not installed |
| 523 | `FAULT_HANDPPEN_DUST_BOX_FULL` | Dust box full |
| 524 | `FAULT_POWER_SWITCH_NOT_OPEN` | Power switch not on |
| 525 | `FAULT_WATER_TRUNK_EMPTY` | Water tank empty |
| 526 | `FAULT_DISHCLOTH_DIRTY` | Mop cloth dirty |
| 527 | `FAULT_FAULT_DUST_BOX_FULL` | Dust box full (alternate sensor) |
| 530 | `FAULT_BATTERY_TEMPERATURE_ABNORMAL` | Battery temperature abnormal |
| 531 | `FAULT_BATTERY_TEMPERATURE_NORMAL` | Battery temperature returned to normal |
| 2000 | `FAULT_DUSBOX_FULL` | Dust box full |
| 2001 | `FAULT_BRUSH_LEFT_BLOCK` | Left brush blocked |
| 2002 | `FAULT_BRUSH_RIGHT_BLOCK` | Right brush blocked |
| 2003 | `FAULT_NO_POWER_PLAN_DIS` | No power / plan disabled |
| 2007 | `FAULT_BROKEN_CLEANING` | Cleaning interrupted |
| 2008 | `FAULT_CLEAN_COMPLETE` | Cleaning complete |
| 2009 | `FAULT_PLAN_CLEAN_COMPLETE` | Scheduled clean complete |
| 2010 | `FAULT_TOF_ABNORMAL` | ToF sensor abnormal |
| 2100 | `FAULT_BROKEN_GO_HOME` | Return-to-dock interrupted |
| 2101 | `FAULT_BROKEN_CHARING` | Charging interrupted |
| 2102 | `FAULT_ROBOT_GLOBAL_GO_HOME` | Global return-to-dock in progress *(status, not error)* |
| 2103 | `FAULT_ROBOT_CHANGING` | Robot state changing *(status)* |
| 2104 | `FAULT_ROBOT_USER_GO_HOME` | User-initiated return to dock *(status)* |
| 2105 | `FAULT_ROBOT_CHARGE_FINISH` | Charging complete *(status)* |
| 2106 | `FAULT_BROKEN_CHARGING_WAIT` | Charging-wait interrupted |
| 2107 | `FAULT_GLOBAL_APPOINT_CLEAN` | Scheduled clean in progress *(status)* |
| 2108 | `FAULT_ROBOT_RELOCALITION_ING` | **Relocalizing** — finding position on map *(status; normal after pickup or startup)* |
| 2109 | `FAULT_ROBOT_REPEAT_CLEAN_ING` | Repeat cleaning in progress *(status)* |
| 2110 | `FAULT_ROBOT_SELF_CHECK_ING` | **Self-checking** — startup self-test *(status)* |
| 4002 | `FAULT_MAP_ERROR` | Map error |

**Codes 590–596 and 604** are Suction Station (auto-empty dock) faults — documented in
§15.4 rather than inline here, because they only occur with that accessory attached and
`RobotError.java` defines no named constants for them.

---

## 7. Known python-karcher Issues

### `DeviceProperties.net_stauts` typo

The `DeviceProperties` dataclass has a field named `net_stauts` (misspelling of `net_status`).
The library's `update()` method internally calls `getattr(self, 'net_status')` which raises
`AttributeError` on every property update. This crash propagates to the paho-mqtt thread and
kills the MQTT connection.

**Workaround in `api.py`**: wrap `original_on_message(topic, payload)` in `try/except AttributeError`.

**Workaround in `coordinator.py`**: catch `AttributeError` in `_async_update_data` and return
the cached `_device_props` value instead of raising `UpdateFailed`.

### REST request signing with list values

`KarcherHome._request` builds the signing string with `str()` on all non-string values.
For list values this produces Python repr (`[{'name': 'mode', 'value': 1}]`) instead of
JSON (`[{"name":"mode","value":1}]`), causing 892 "sign mismatch" errors from the API.
Fix: use `json.dumps(val, separators=(',', ':'))` for all non-string, non-None values.

---

## 8. Home Assistant Integration Architecture

```
custom_components/karcher_home_robots/
├── __init__.py       — async_setup_entry, async_unload_entry
├── manifest.json     — requirements: karcher-home>=0.5.1, iot_class: cloud_push
├── config_flow.py    — 3-step: region → credentials → device picker
├── coordinator.py    — DataUpdateCoordinator + polling fallback; rooms; _selected_room_id accessors
├── mqtt_adapter.py   — MQTT subscription, on_message monkey-patch, push callback dispatch
├── vacuum.py         — KarcherVacuum entity (StateVacuumEntity)
├── sensor.py         — KarcherBatterySensor (SensorDeviceClass.BATTERY)
├── select.py         — KarcherRoomSelect entity (room picker for selective cleaning)
├── api.py            — Async wrapper around KarcherHome; get_mqtt_adapter; async_send_command; get_rooms
├── const.py          — DOMAIN, VacuumState enum, state sets, CMD_* dicts, SEND_COMMAND_HANDLERS
├── entity.py         — KarcherEntity base with device_info
└── translations/en.json
```

### Library bugs and workarounds

**Bug 1 — `thing/event/property/post` payload ignored**

`karcher-home` 0.5.x processes MQTT `thing/event/property/post` messages by setting a
wait-event and returning — it never calls `_update_device_properties` with the payload.
This means real-time state pushes (battery, work_mode, etc.) do not update `_device_props`.

**Workaround in `api.py`**: the patched `on_message` handler parses the JSON payload of
`property/post` messages and manually calls `_client._update_device_properties(sn, params)`
before firing the push callback. This gives correct real-time updates without requiring
library changes.

**Bug 2 — `get_device_properties()` returns stale cache when subscribed**

`KarcherHome.get_device_properties()` returns immediately with the existing
`_device_props[sn]` entry when the device is already subscribed — without sending a
fresh `prop.get` request. On startup the cache is a default `DeviceProperties()` with
`quantity=0`, so battery always showed 0% until an MQTT push happened to arrive.

**Workaround in `api.py`** — `fetch_properties()`: always calls `request_device_update()`
followed by `_wait_for_topic(get_reply_topic, timeout=5)` to guarantee fresh data.
The coordinator's `_async_update_data` calls this instead of `get_device_properties()`.

**Bug 3 — a rejected `prop.get` reply is dropped silently**

`_process_mqtt_message` handles `thing/service/property/get_reply` with
`if data['code'] != 0: return` — leaving the registered wait event unset. A robot that
*answers* the request with an error is therefore indistinguishable from one that never
answered: the caller sees only a reply-wait timeout. It also indexes `data['code']` and
`data['data']` unguarded, so a reply of another shape raises `KeyError` on the paho
thread with the same result. (Code-read of `karcher-home` 0.5.1; no `code != 0` reply has
been captured from an RCV5 — filed against issue #124, where an RCV3 times out on every
`prop.get`.)

**Workaround in `adapter.py`** — `_prop_get_sync()` waits on the adapter's own
`_reply_listeners`, signalled by its dispatcher for every payload on the topic, and
raises with the reply's `code` when it is non-zero. Replies do carry a `msgId`, but
whether it echoes the request's or is the robot's own stamp is **unverified** (the
capture tool redacts the field), so the wait takes the newest payload rather than
matching on it; the listener is registered immediately before the publish to bound what
can land in between.

### HA version compatibility notes (tested 2026-03-28, HA 2025.x / Python 3.14)

- **`VacuumActivity` enum** replaces the removed `STATE_CLEANING` / `STATE_DOCKED` / etc.
  string constants. Use `from homeassistant.components.vacuum import VacuumActivity` and
  implement the `activity` property (not `state`) on `StateVacuumEntity`.
- **Battery as a sensor** — `VacuumEntityFeature.BATTERY` and `battery_level` on the vacuum
  entity are deprecated (removed in HA 2026.8). Battery must be a separate `SensorEntity`
  with `SensorDeviceClass.BATTERY`, linked to the same device via shared `device_info`.
- **Dependency**: use `karcher-home>=0.5.1` (PyPI) in `manifest.json`, not the git URL —
  git-based requirements fail on HA OS where the host does not have git available.

### Thread safety

paho-mqtt callbacks run in a dedicated thread separate from the HA event loop.
The MQTT push path is:

```
paho thread → api.py patched on_message
           → _on_push(props) callback (defined in __init__.py)
           → hass.loop.call_soon_threadsafe(coordinator.handle_mqtt_push, props)
           → HA event loop → coordinator.async_set_updated_data(props)
           → all entity listeners notified
```

### Polling fallback

`POLL_INTERVAL = 30` seconds. Used when MQTT push is absent or when an initial
state is needed before the first push arrives. Implemented via
`DataUpdateCoordinator.update_interval`.

### Credential storage

Email + password are stored in the config entry (not tokens). Tokens expire;
storing credentials allows the integration to re-authenticate automatically on
`ConfigEntryAuthFailed`. If credentials are rejected, HA shows a
"re-authentication required" notification which opens the reauth flow
(`async_step_reauth`) to collect new credentials without removing the entry.

### Multiple robots

Each robot is a separate config entry. The integration supports:

- **Multiple robots, same account**: run "Add Integration" once per robot; log
  in with the same credentials and pick a different device each time. One MQTT
  connection is made per config entry (one `KarcherHome` instance each).
- **Multiple robots, different accounts**: run "Add Integration" with different
  credentials; each entry is fully independent.
- **Duplicate prevention**: `async_set_unique_id(dev.device_id)` +
  `_abort_if_unique_id_configured()` in `_create_entry()` ensures the same
  device cannot be added twice.

---

## 9. Local Control Investigation

Goal: intercept `eu-gamqttaiot.3irobotix.net` with a local Mosquitto broker to
enable cloud-independent control.

### Step 1: DNS override (confirmed working)

Added to router DNS / `/etc/hosts` on Mac (used as DNS server for VLAN):
```
<router-ip>  eu-gamqttaiot.3irobotix.net
```
Verified with `dig eu-gamqttaiot.3irobotix.net @<router-ip>` → returns LAN IP.
`tcpdump` on port 8883 confirmed robot connects to Mac IP after DNS override.

### Step 2: TLS certificate generation

The real broker presents a self-signed EC P-256 wildcard cert for `*.3irobotix.net`.
Generated our own RSA 2048 CA and server cert:

```bash
# CA
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -days 3650 -out ca.crt \
  -subj "/CN=KarcherLocalCA"

# Server cert with SAN (required; CN-only was rejected)
openssl genrsa -out server.key 2048
openssl req -new -key server.key -subj "/CN=eu-gamqttaiot.3irobotix.net" \
  -addext "subjectAltName=DNS:eu-gamqttaiot.3irobotix.net" -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365 \
  -extfile <(printf "[v3_req]\nsubjectAltName=DNS:eu-gamqttaiot.3irobotix.net") \
  -extensions v3_req
```

Cert files stored in `~/karcher-mqtt-certs/` (not committed — contains CA key).

### Step 3: Mosquitto broker

`~/karcher-mqtt-certs/mosquitto.conf`:
```
listener 8883
certfile /path/to/karcher-mqtt-certs/server.crt
keyfile  /path/to/karcher-mqtt-certs/server.key
allow_anonymous true
require_certificate false

listener 1883
allow_anonymous true

log_type all
log_dest file /tmp/mosquitto-karcher.log
```

Key finding: **`cafile` must NOT be present.** When `cafile` is set, Mosquitto sends a
TLS `CertificateRequest` during handshake. The robot has no client cert for MQTT and
responds with `close_notify`, terminating the connection before sending MQTT CONNECT.

### Step 4: TLS handshake — confirmed completing

A Python raw-TLS spy server (not Mosquitto) confirmed:
```
[<robot-ip>] TLS OK  version=TLSv1.2 cipher=ECDHE-RSA-AES256-GCM-SHA384
[<robot-ip>] recv 0 bytes
[<robot-ip>] connection closed
```

TLS completes successfully. The robot then sends **zero bytes** before closing.
This means the robot validates the server certificate at the **application layer**
after the TLS handshake completes, finds it untrusted, and closes silently.

### Step 5: APK analysis — certificate pinning confirmed

#### 5a. Obtain the APK

Download from APKPure (version tested: `KHR_1.4.32_APKPure.apk`).
The package name is `com.kaercher.homerobots`.

#### 5b. Extract APK contents

```bash
mkdir apk_extract && cd apk_extract
unzip -qo ~/Downloads/KHR_1.4.32_APKPure.apk
```

Relevant files in `assets/`:
```
assets/server.bks    — BKS trust store (pinned MQTT broker cert)
assets/iot_dev.p12   — PKCS12 client cert + key (used for REST mutual TLS)
```

Confirm they exist:
```bash
ls assets/server.bks assets/iot_dev.p12
```

#### 5c. Decompile with jadx to find keystore passwords

```bash
brew install jadx   # or download from github.com/skylot/jadx
jadx -d apk_jadx ~/Downloads/KHR_1.4.32_APKPure.apk --no-res
```

Search for the keystore loading code:
```bash
grep -n "server\.bks\|iot_dev\.p12\|toCharArray\|BKS" \
  apk_jadx/sources/com/irobotix/common/network/http/encryption/SSLClient.java
```

You will find in `SSLClient.initSslSocketFactorySingleBKS()` (used for MQTT):
```java
char[] charArray = "«redacted»".toCharArray();
keyStore.load(inputStreamOpen, charArray);   // server.bks password
```

And in `SSLClient.initMqttSslSingleBKS()` (alternate path that loads both):
```java
char[] charArray2 = "«redacted»".toCharArray();
keyStore2.load(inputStreamOpen2, charArray2);  // iot_dev.p12 password
```

There is also a third password used in a fallback error branch — not needed for extraction.

#### 5d. Extract the trusted cert from server.bks

BKS format requires the BouncyCastle provider. Use `pyjks`:

```bash
pip install pyjks
python3 - << 'EOF'
import jks, subprocess

ks = jks.bks.BksKeyStore.load("assets/server.bks", "«redacted»")
for alias, entry in ks.entries.items():
    print(f"alias={alias!r}  type={type(entry).__name__}")
    cert_data = entry.cert if hasattr(entry, 'cert') else entry.certs[0]
    with open(f"server_bks_{alias}.der", "wb") as f:
        f.write(cert_data)
    subprocess.run(["openssl","x509","-inform","DER","-in",f"server_bks_{alias}.der",
                    "-out",f"server_bks_{alias}.pem"])
    subprocess.run(["openssl","x509","-in",f"server_bks_{alias}.pem","-text","-noout"])
EOF
```

This produces `server_bks_mykey.pem` — the cert the robot uses as its MQTT trust anchor.

Verify it matches the real broker:
```bash
# Real broker pubkey fingerprint:
openssl s_client -connect eu-gamqttaiot.3irobotix.net:8883 2>/dev/null \
  | openssl x509 -pubkey -noout | md5

# Extracted cert pubkey fingerprint (must match):
openssl x509 -in server_bks_mykey.pem -pubkey -noout | md5
```

Both should produce the same MD5 (fingerprint redacted).

Extracted cert details:
```
Issuer:  C=CN, ST=GD, L=SZ, O=3irobotix, OU=IOT, CN=*.3irobotix.net
Subject: C=CN, ST=GD, L=SZ, O=3irobotix, OU=IOT, CN=*.3irobotix.net
Expires: 2031-11-29
Key:     EC P-256 (256-bit), self-signed
```

#### 5e. Extract the client cert from iot_dev.p12

The P12 uses RC2-40-CBC encryption, which OpenSSL 3.x drops by default.
Use the `-legacy` flag:

```bash
# Extract certificate:
openssl pkcs12 -legacy -in assets/iot_dev.p12 \
  -passin pass:«redacted» -nokeys -out iot_dev_cert.pem

# Extract private key (no passphrase on output):
openssl pkcs12 -legacy -in assets/iot_dev.p12 \
  -passin pass:«redacted» -nocerts -nodes -out iot_dev_key.pem

# Inspect:
openssl x509 -in iot_dev_cert.pem -text -noout | grep -E "Issuer|Subject|Not After|Public-Key"
```

Result:
```
Issuer:  C=CN, ST=GD, L=SZ, O=3irobotix, OU=IOT, CN=*.3irobotix.net
Subject: C=CN, ST=GD, L=SZ, O=3irobotix, OU=IOT, CN=*.3irobotix.net
Expires: 2031-11-29 (4 seconds before server.bks cert)
Key:     EC P-256 (256-bit)
```

Confirm this is a DIFFERENT cert from the broker cert (public keys must NOT match):
```bash
openssl x509 -in iot_dev_cert.pem -pubkey -noout | md5
# → (fingerprint redacted; confirmed different from the server.bks fingerprint above)
```

This cert + key is used for REST API mutual TLS authentication. It is **not** the MQTT
broker cert and its private key cannot be used to impersonate the broker.

### Conclusion

The robot performs application-layer certificate pinning against the specific
`*.3irobotix.net` cert stored in `server.bks`. Without the private key for that cert
(which is not present anywhere in the APK), local MQTT broker impersonation is not
possible without modifying the robot's firmware.

### Paths to local control

> **See `LOCAL_CONTROL.md`** for the full post-root picture: the on-device process
> architecture (everest / nanomsg / `aiot_client`) and the ranked cloud-free paths
> (broker redirect, nanomsg agent, Valetudo port). The summary below is the original
> shell-first sketch.

1. **UART serial console** *(most reliable)*
   The robot runs Linux on a Rockchip RV1126/RV1109 SoC.
   UART test pads are typically available on the PCB (115200 baud, 3.3V).
   With root shell access:
   - Replace `/etc/ssl/certs/` or the app-specific cert store with our CA cert, OR
   - Edit the MQTT client config to point to the local broker and skip cert verification, OR
   - Patch the MQTT client binary (`strings`/`sed` on the cert validation flag).

2. **OTA firmware extraction** *(done — the image is NOT encrypted)*

   The rootfs is a plain **XZ** SquashFS wrapped in a **UBI** volume; once the UBI erase-block
   headers are stripped it extracts to cleartext (3,256 entries, including `/etc/passwd` and
   `/etc/shadow`).

   The OTA endpoint returns a firmware URL. Correct request parameters (confirmed 2026-03-28):
   ```python
   POST /upgrade-service/firmware/tryUpgrade
   {
     "productId":        dev.product_id.value,      # "1540149850806333440"
     "productModelCode": dev.product_mode_code,     # "Kaercher.KaercherRCV5Es"
     "curVersionCode":   "0",                       # returns the FACTORY BASELINE, not the latest
     "packageType":      "host_fw",                 # from RobotUpgradeActivity.java
     "username":         dev.sn,                    # device serial number
     "phoneBrand":       "android",
   }
   ```
   The package is returned under the top-level **`result`** key (not `data`), alongside
   `code: 0`. The endpoint walks an upgrade chain: **it answers with the newest build that
   supersedes the `curVersionCode` you pass.** Swept 2026-08-04 against both robots on the
   account, identical results:

   | `curVersionCode` | Offered |
   |---|---|
   | `0` | `I3.12.26` (code 26) — the 2022 **factory baseline**, 109,521,368 B, `publishDesc: 正式必经升级包` ("mandatory upgrade package") |
   | `26`, `27`, `50`, `89` | **`I3.12.90`** (code 90) — 104,808,920 B, md5 `e423237df246b08561956afbdbbc903e` |
   | `90` | error **838**, `未找到对应的包配置策略,packageType:host_fw` — no policy above the newest build |

   So `0` does **not** mean "latest": it is below the baseline, and the chain's first hop from
   there is the baseline itself. Any code in `26..89` reaches the current release. Error 838 at
   `90` is simply "already newest" — the official app receives the same error and renders it as
   "no update available" (`ControlMainActivity.java:3773` passes the robot's real
   `firmware_code`, so this is the production call path).

   Current release, verified live 2026-08-04 (`HTTP 200`, S3 `etag` equal to the advertised md5):

   ```
   https://eu-cdnupdatepkgaiot.3irobotix.net/prod/app-product/0/2025-10-10/
     Kaercher_RCV5_EU-rv1126-linux-ota-release-I3.12.90-20250709_110641_1757150218900704_1760088385006894.img
   ```

   Built 2025-07-09, published 2025-10-10. `publishDesc`: *"Please make sure the machine is in
   the charging dock and the charge is over 30% before upgrading. — Fix known issues"*. A
   parallel `packageUrlSecret` is served for the same build — see **the `_secret.img` sidecar**
   below.

   **The robot never discovers updates by itself** (APK `UpgradeVM.java:285–321`). The flow is:

   1. the **app** calls REST `tryUpgrade` and receives a `FirmwareOtaInfo`
      (`packageUrl`, `md5`, `packageSize`, `versionCode`, `versionName`, `minVersion`, `silence`);
   2. the **app** publishes MQTT `ota.upgrade.set` to the device OTA topic, passing that
      `packageUrl` through to the robot;
   3. the **robot** downloads the image from that URL.

   Consequence: `tryUpgrade` is the **single source of firmware URLs** — but it is a plain,
   unauthenticated-CDN source, so any build in the chain can simply be fetched with `curl`.

   **The `_secret.img` sidecar (analysed 2026-08-04).** Every response carries a second pair,
   `packageUrlSecret` / `md5Secret`. The URL is the plain one with `_secret` before the
   extension, and it is served from the same CDN with the same `last-modified`. It is **the
   identical firmware behind a 764-byte prefix** — the exact size difference (104,809,684 vs
   104,808,920):

   | Offset | Size | Content (for `I3.12.90`) |
   |---|---|---|
   | `0x000` | 64 B | ASCII hex, 32 bytes' worth: `4b07caa6eb71187341d8475f5a40817da06cd546964353f6efd21795d4243747` |
   | `0x040` | 4 B | big-endian length of the next field — `0x000002B8` = 696 |
   | `0x044` | 696 B | ASCII **`'0'`/`'1'` characters**, i.e. a bit-string; each 8 chars decode to one byte, giving 87 bytes of JSON:<br>`{"version":"I3.12.90","productType":"Kaercher.KaercherRCV5Es","timestamp":202503192112}` |
   | `0x2FC` | — | `RKFW` — the plain `.img`, byte for byte |

   `productType` is the same `productModelCode` the `tryUpgrade` request sends. The
   `timestamp` field reads as 2025-03-19 21:12 — **a third date, matching neither the verified
   build (2025-07-09) nor the CDN publication (2025-10-10)**; it is metadata on the sidecar, not
   a build stamp, and what it refers to is unknown.

   The 64-hex field is **unidentified**. It is not SHA-256 of the image, the JSON, the
   bit-string, or the advertised md5 in either raw or hex form, and not HMAC-SHA256 of the
   JSON under the obvious keys. *Inference, unverified:* 32 bytes is exactly one PKCS7-padded
   AES block over a 16-byte plaintext, and an md5 is exactly 16 raw bytes — consistent with an
   encrypted image md5 (which would fit the name), but equally consistent with a keyed 256-bit
   digest. Settling it needs the verifying key, which would live in the `upgrade` daemon in the
   rootfs — i.e. it folds into extracting `.90` (§9.2).

   **The app never uses it.** `FirmwareOtaInfo` (`com/irobotix/common/bean/FirmwareOtaInfo.java`)
   is a typed Gson model with no `@SerializedName` for either secret field, so Gson discards
   them; and `UpgradeVM.java:285–320` builds the `ota.upgrade.set` payload by explicit
   `map.put()` from that typed model, so there is no wholesale forwarding path either. The
   string `packageUrlSecret` occurs **zero times in all six `classes*.dex`** — a check that does
   not depend on the decompiler, since a `@SerializedName` or a `JSONObject` lookup would need
   the literal in the dex regardless (`unzip -o KHR_*.apk 'classes*.dex' -d dex/` then
   `grep -ac`; positive controls in the same run: `packageUrl` 3, `md5` 15,
   `productModelCode` 3, `md5Secret` 0).

   Related, and possibly the intended consumer: that same payload hardcodes
   **`"signed": false`** (`UpgradeVM.java:317`, and identically at `:404` / `:444` for the 330G
   `host_mcu` / `host_wifi` packages). No call site ever sets it `true`. *Inference,
   unverified:* `signed: true` is what would pair with the `_secret.img` URL and `md5Secret`,
   making the sidecar the signed-update path that this app build simply never takes. Confirming
   it means reading the robot's `upgrade` daemon — again gated on extracting `.90`.

   Reproduction — proves body identity **without downloading the 105 MB sidecar**, by
   reconstructing it from a 764-byte range request plus the plain image already on disk:

   ```python
   import hashlib
   hdr = <first 764 bytes of packageUrlSecret, via a Range request>
   h = hashlib.md5(hdr)
   with open("Kaercher_RCV5_EU-I3.12.90.img", "rb") as f:
       for chunk in iter(lambda: f.read(1 << 20), b""):
           h.update(chunk)
   assert h.hexdigest() == "483c61e6f98ca7420f5fd460763f8180"   # advertised md5Secret
   ```

   The `.img` is a **Rockchip RKFW** update image. Verified format:
   - Starts with `RKFW` magic; embedded `RKAF` package at offset `0x3D9B4`
   - RKAF part table (5 entries): `MiniLoaderAll.bin` (~246 KB), `parameter.txt`,
     `boot.img` (~7 MB, U-Boot FIT `d00dfeed`), `rootfs.img` (~97 MB)
   - `rootfs.img` is **not a bare squashfs** — it is a **UBI image** (magic `UBI#`,
     256 KiB physical erase blocks). Inside its single volume sits a **SquashFS 4.0**
     filesystem (compression id 4 = **XZ**).

   **Build date verified from binary headers, not merely inferred from the filename**
   (procedure validated 2026-08-04 against both the `.26` factory baseline and the current
   `.90` build — in both, the header timestamp lands a few seconds *before* the outer RKFW
   packaging timestamp, exactly as a build-then-package sequence should, which is why neither
   date reads as forged). Current (`I3.12.90`) values:

   | Field | Value |
   |---|---|
   | Filename stamp | `20250709_110641` |
   | RKFW header date (`u16` year at `0x0E`, then mon/day/h/m/s) | 2025-07-09 11:13:22 |
   | SquashFS `mkfs_time` (`u32` at `hsqs+8`) | `1752030800` → 2025-07-09 03:13:20 UTC (11:13:20 at UTC+8, vendor tz — 2 s before packaging) |
   | Image size | 104,808,920 B |
   | `UBI#` offset | `0xB341B4` |
   | `hsqs` offset | `0xBB61B4` |

   The RKFW chip tag at `0x15` is ASCII `6211` — `1126` stored reversed, i.e. RV1126.

   **Container format is identical to the `.26` baseline** (same RKAF offset `0x3D9B4`, same
   UBI-wrapped XZ SquashFS 4.0, same board ID string `rv1126-3irobotix-CRL350_RCV5_V1_0`), so
   the extraction procedure needed no changes beyond the `UBI#`/`hsqs` offsets — validated once
   on `.26`, then reused unmodified on `.90`. (`.90` is the *smaller* image despite a later
   rootfs start: `boot.img` and the loaders grew while the compressed rootfs shrank.)

   No version or date strings are greppable in the raw `.img` (`I3.12.` matches zero times):
   the rootfs is XZ-compressed, so only these header fields are readable without extracting
   the filesystem.

   `I3.12.90` was downloaded and md5-verified against the API's advertised
   `e423237df246b08561956afbdbbc903e` on 2026-08-04. **It is not stored in this repo** — see
   the secrets table in `CLAUDE.md`.

   **The filesystem is not encrypted — it is compressed.** The "cryptographically
   random" bytes seen previously were XZ-compressed data interleaved with UBI
   erase-block (EC/VID) headers every `0x40000`. Running `unsquashfs` directly on the
   raw partition hits those headers mid-stream, which is what produced the
   `read_block: failed to read block @0x…` garbage-pointer error — **that was the UBI
   wrapper, not a cipher.** Strip the UBI layer first and it decompresses cleanly.

   Reproduction (offline, no device needed):
   ```bash
   # carve rootfs.img from the RKAF part table, then strip UBI → plain XZ squashfs:
   ubireader_extract_images -o vol rootfs.img
   unsquashfs -d rootfs vol/*/img-*_vol-rootfs.ubifs     # 2,431 files extracted (current `.90`)
   ```
   Result: full cleartext rootfs (Buildroot 2018.02, BusyBox). `/etc/shadow` yields the root
   login and `/etc/inittab` runs an always-on `getty` on `ttyFIQ0` — see `ROOTING.md §2` for
   the password and the full access-vector implications (re-confirmed unchanged on `.90`, §9.3).

   This path is **open**: the firmware can be read and audited from the OTA image
   alone. *Modifying and re-flashing* boot/rootfs is a separate question gated by
   Rockchip verified-boot (signature, not encryption) — see `ROOTING.md §6.1`.

   ---

   **§9.3 — `I3.12.90` rootfs audit (2026-08-04).** The current shipping image was
   extracted with the unmodified `.26` procedure above (carve from `UBI#` at `0xB341B4`
   → `ubireader_extract_images` → `unsquashfs`). SquashFS 4.0 / XZ, `mkfs_time`
   2025-07-09, 2839 inodes → **2,431 files, 269 dirs, 549 symlinks**. Userland is the
   same **Buildroot 2018.02-rc3, BusyBox**. The audit **closes the version gap** that
   `ROOTING.md` flagged: the entire software attack surface is unchanged from `.26` — see
   the confirmation table in `ROOTING.md §3` (root login still valid, hash only re-salted;
   `getty`/SSH/ADB gating and the broker-cert pin all identical).

   New, non-gating detail recovered from `.90` (not previously catalogued):

   - **`/oem/sysconf` identity** — `sysVersion.ini`: `sysVersion=I3.12.90`,
     `sysVersionCode=90`, `sysProduct=3ICRL350`, `sysSecondProduct=3003`, `versionType=R`;
     `robot_release`: `2025_07_09 11:06:49`; `productMode.ini`: `vendor=Kaercher`,
     `product_mode=Kaercher.KaercherRCV5Es`, `productid=1540149850806333440`,
     `tenantid=1528983614213726208` (runtime `sn`/`mac`/`key`/`ble_mac` fields blank —
     populated from RK **vendor_storage** at boot; `aiot_client` reads
     `VENDOR_BT_MAC_ID` / `VENDOR_CUSTOM_ID_*`).
   - **`/oem/bin` inventory** — `RobotApp` (main app, 6.4 MB), `everest-server` (40 MB,
     the SLAM/AI navigation server), `Ai-server`, `AuxCtrl` (MCU link), `Monitor`
     (+`Monitor-deamon.sh`), `aiot_client.bin` (cloud bridge, mbedTLS), `log-server`,
     `upgrade`, `wifiManager`, `watchdog`, `miio_device_conf_check`, `tcping`, and `rtty`.
   - **`rtty` — a purpose-built reverse-shell remote-support tunnel (verified facts).** It
     is [zhaojh329/rtty](https://github.com/zhaojh329/rtty) compiled for this board by a
     3iRobotix developer — internal build paths `/home/xujp/Program/rtty-master/rv1126/rtty/src/{main,net,command,file,ptySession}.c`
     and the bundled `libuwsc` WebSocket client are embedded in the binary. rtty dials **out**
     over (S)SSL WebSocket to an rtty server (`-h host -t token -I id -s`) and multiplexes a
     full **root PTY shell + file transfer** back through the customer's NAT. This is
     unambiguously an intentional vendor remote-debug facility, not stray code.
     **What is *not* in the image:** no boot-time autostart (no init/`rcS` entry), no config
     carrying a server endpoint, and — unlike `tcping`, which `RobotApp` popen()s via the
     baked-in template `/oem/bin/tcping -c 8 -d %s -p 80` — **no static command template that
     launches rtty by name.** The only genuine `rtty` strings anywhere in the rootfs are
     inside the binary itself (every other hit is the `cert-type`/`nsCertType` substring).
     **So it does not run on its own, but it can be run** — the endpoint+token are supplied at
     launch time. **Disassembly settled *how* (2026-08-04):**
     - `RobotApp`'s only `popen`-based command executor is
       `everest::net::CHttpPackage::cmdShell(char*)` @ `0x496de8` — literally
       `popen(cmd,"r")` → log each output line → `pclose`. Its **7 callers are all in the
       voice/resource-pack download-and-unpack subsystem** (`CDownloadTask::dealPackage`,
       `CHttpPackage` ctor/`UnpackFile`/`CopyFile`/`LinkFile`), and every call passes a
       **fixed `sprintf` template** — `mkdir -p %s`, `unzip -o %s -d %s`, `cp %s %s`,
       `ln -s %s %s`, `find %s -type d | grep %s/ | grep -v %s | xargs rm -rf`. **No cloud
       opcode ever hands `cmdShell` a command string**, and none of these templates names
       `rtty`. The `config_diagnostics` string is a config key, not a shell dispatcher.
     - The `SetRemoteControl` cloud ops (`CAiotParseBuf::parseSetRemoteCtrlReq` @ `0x4ac8e0`,
       `CMiioSpecParse::parseSpecSetRemoteCtrlReq`) parse `direction`/`ctrlValue` into a
       `DeviceCleanCtrl` and `sendAlgorithmMsg` to the motion layer — i.e. **manual joystick
       driving, not a shell.** They never reach `popen`.
     **Conclusion: no in-firmware trigger for rtty exists.** It is a technician/support tool,
     runnable only by something that already holds a shell (UART/SSH root, or a script placed
     on writable `/userdata`). With our own root shell we can point rtty at *our* rtty server
     for a zero-hardware remote root shell.
   - **Trust anchors in `/oem/sysconf`** — the self-signed broker pin `server.crt`
     (pubkey fingerprint redacted, `*.3irobotix.net`) *plus*
     `gdroot-g2.crt` = the public **GlobalSign Root CA** (valid 1998→2028). *Inference:*
     the GlobalSign anchor validates the OTA/CDN HTTPS leg (a public-CA endpoint),
     separate from the self-signed MQTT-broker pin.

3. **No local TCP services**
   `nmap -sV -p 80,443,1883,8883,4196,6080,7080,10009 <robot-ip>` — all closed.
   On startup the robot announces itself via ARP but opens no inbound ports.
   It is a pure MQTT client with no local REST API.

---

## 10. REST API — Commands Do Not Go via REST

An early hypothesis was that commands might be sent via REST (phone → REST → cloud → MQTT → robot).
This was ruled out by:

1. mitmproxy capture showed zero REST calls triggered by pressing Start/Pause/Return in the app
   (only CDN map tile downloads and occasional heartbeats were visible in the proxy).
2. Probing 14 candidate REST endpoints returned 404 for all except
   `/smart-home-service/smartHome/device/property/set`, which returned error 892
   (signature mismatch due to the list-serialisation bug in python-karcher).
3. MQTT wildcard subscription confirmed commands appear directly on MQTT topics.

**Commands go exclusively via MQTT PUBLISH from the app to the cloud broker.**
The cloud broker forwards them to the robot's MQTT subscription.

---

## 12. Apple Home Integration via Matter

The HA integration can be exposed to Apple Home as a native **Matter RoboticVacuumCleaner**
device (type 0x0074) using the
[Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) project.
No changes to `custom_components/karcher_home_robots/` are needed.

### Why not the built-in HA Matter component

HA's built-in `matter` component is a **Matter controller only** — it pairs with Matter devices
already on your network. It does not bridge HA entities outward into Matter. A separate
bridging process is required.

### Why not the HomeKit Bridge

The native HA HomeKit bridge (`homekit` integration) can expose vacuums, but as a HomeKit
accessory (HAP protocol), not as a Matter device. Apple Home accepts both, but the
Matter path provides a proper `RoboticVacuumCleaner` tile with native start/stop/state
rather than a generic switch approximation.

### Deployment (Home Assistant OS)

Install the [HA Matter Hub add-on](https://github.com/RiDDiX/home-assistant-matter-hub)
via the HAMH add-on repository. The add-on handles networking automatically on HAOS.

The web UI is served at `http://<ha-ip>:8482`.

### Bridge configuration

1. Open `http://<ha-ip>:8482`
2. **Add Bridge** → set a name
3. Entity filter: domain = `vacuum`
4. Enable **Server Mode** — required for Apple Home. Without it the vacuum is wrapped as
   a sub-accessory which Apple Home rejects for RoboticVacuumCleaner devices.
5. Save → QR code is displayed
6. iPhone **Home app → + → Add Accessory → scan QR code**

### Battery in Apple Home

The battery sensor (`sensor.karcher_battery`) is a separate HA entity in the `sensor`
domain. The Matter Hub bridge is configured to filter on `vacuum` domain, so the battery
entity is not bridged automatically.

**Fix**: in the Matter Hub web UI, edit the bridge and add a second entity filter for the
specific battery entity (e.g. `sensor.karcher_battery`). After saving, battery % appears
in the accessory detail view in Apple Home.

### Rooms in Apple Home

Room selection works via the Matter **ServiceArea cluster** (0x0150). HA Matter Hub
already implements ServiceArea and detects rooms automatically from the vacuum entity's
`rooms` attribute.

**How it works end-to-end:**

1. The Kärcher integration fetches room names/IDs from the map protobuf at startup and
   stores them in `coordinator.rooms`.
2. `vacuum.py` exposes them in `extra_state_attributes` under `rooms` in Roborock-compatible
   format: `{"1": "Kitchen", "2": "Living Room", ...}` (numeric-string keys → room names).
3. HA Matter Hub detects this format (`isRoborockVacuum()`), creates a ServiceArea cluster
   with those rooms, and registers a mode per room in RvcRunMode.
4. Apple Home shows a room picker in the accessory detail view.
5. When the user selects rooms and presses Start, HA Matter Hub calls
   `vacuum.send_command(app_segment_clean, [room_id])`.
6. `async_send_command` in `vacuum.py` maps this to
   `set_room_clean(room_ids=[room_id], ctrl_value=1, clean_type=0)` via MQTT.

**No changes to HA Matter Hub required** — it already handles this code path.

**Restarting HA Matter Hub** is required after any room list change (rooms are read at
startup). Restart the add-on from **Settings → Add-ons → HA Matter Hub → Restart**.

**Verifying ServiceArea Apple Home support** (tested 2026-03-29):
A standalone matter.js test node (`/tmp/matter-test/rvc-test.mjs`) confirmed Apple Home
displays a room picker when a RVC device advertises the ServiceArea cluster — proving
Apple Home supports the cluster before committing to the full implementation.

### Cleaning mode and water level in Apple Home (RvcCleanMode)

HA Matter Hub builds the `RvcCleanMode` cluster from two select entities configured
via **Entity Mapping** in the HAMH bridge web UI (port 8482 → bridge → edit → Entity Mapping):

```
cleaningModeEntity  →  select.karcher_cleaning_mode
mopIntensityEntity  →  select.karcher_water_level
```

HAMH matches option strings case-insensitively. Our values are pre-compatible:

| `select.karcher_cleaning_mode` option | HAMH CleanType | Matter tags |
|---|---|---|
| `Vacuum` | Vacuum | Vacuum |
| `Vacuum & Mop` | SweepingAndMopping | Vacuum + Mop |
| `Mop` | Mopping | Mop |

| `select.karcher_water_level` option | Matter intensity tag | Apple Home label |
|---|---|---|
| `Low` | Quiet | Quiet |
| `Medium` | Auto | Automatic |
| `High` | Max | Max |

After configuring Entity Mapping, restart the Matter Hub. Apple Home will show:
- A cleaning type picker (Vacuum / Mop / Vacuum & Mop) in the vacuum tile
- Mop intensity options (Quiet / Automatic / Max) when Mop or Vacuum & Mop is selected

### Confirmed working (2026-03-29)

- Robot appears in Apple Home as a vacuum tile
- Start / Pause / Return to Base commands work end-to-end
- State updates from MQTT push reflect in Apple Home within a few seconds
- Battery % visible in Apple Home accessory detail (after adding battery entity to bridge)
- Room selection works in Apple Home via ServiceArea cluster
- Fan speed (suction level) visible as intensity options in Apple Home (Silent→Quiet, Standard/Medium→Auto, Turbo→Max)
- Cleaning mode (Vacuum / Mop / Vacuum & Mop) visible and controllable in Apple Home
- Mop intensity (Low/Medium/High → Quiet/Automatic/Max) visible in Apple Home when mop mode active

**HAMH Sub-Entry configuration** (set on the vacuum entity row in the bridge):
- `cleaningModeEntity` → `select.<name>_cleaning_mode`
- `mopIntensityEntity` → `select.<name>_water_level`

**HAMH architectural constraint — SupportedModes is static at startup (verified 2026-05-09):**
HAMH reads the HA select entity's `options` list once when it initialises the
`RvcCleanMode` cluster and never re-reads it. Consequence: dynamically filtering
`options` based on mop-attachment state does not propagate to Apple Home without a
Matter bridge restart. A restart with no mop attached would permanently hide mop modes
until the mop is attached and HAMH is restarted again — an unacceptable UX trap.
Therefore `KarcherCleaningModeSelect` keeps all three options static. Mop-mode
availability is enforced at call time via `ServiceValidationError` in
`async_select_option`. Entity `current_option` changes (mode auto-switching on
attach/detach) DO propagate live via HAMH's state subscription — only `options` is
static.

---

## 13. Map and Cleaning Path Protocol

All findings from APK decompilation of `KHR_1.4.32_APKPure.apk` (jadx), confirmed
2026-05-03. Key source files:
- `com/irobotix/common/bean/mqtt/DevProperties.java`
- `com/irobotix/common/bean/mqtt/MqttTopicUtil.java`
- `com/irobotix/common/bean/mqtt/DeviceMethod.java`
- `com/robotdraw/map/map/MapProcessUtil.java`
- `com/robotdraw/common/RobotMapApi.java`
- `com/irobotix/control/ui/ControlMainActivity.java`

---

### 13.1 Live Cleaning Path — `cur_path`

The robot pushes incremental path updates during a cleaning session. No polling needed.

**MQTT topic** (device publishes, app subscribes):
```
/mqtt/{product_id}/{sn}/thing/event/cur_path/post
```

**Payload** (JSON, same envelope as `property/post`):
```json
{
  "method": "event.cur_path.post",
  "params": { "cur_path": [<float>, ...] }
}
```

`cur_path` is a flat `List<Float>` with this layout:

| Index | Meaning |
|---|---|
| `[0]` | Starting `poseId` (integer cast to float) — sequence number for the first point |
| `[1]` | X of point 0 |
| `[2]` | Y of point 0 |
| `[3]` | Phi (heading angle, radians) of point 0 |
| `[4]` | Update flag of point 0 (int cast to float): `0` = navigating/transit, non-zero = actively cleaning [K — APK `PathMap.java`] |
| `[5..8]` | X, Y, Phi, update-flag of point 1 |
| … | Every 4 floats = one pose |
| `[last]` | End marker |

Validity check: `len >= 6` and `(len - 2) % 4 == 0`.

Each pose: `poseId = start_id + i`, coordinates in the robot's internal metric unit.

To request the current path on demand (e.g. at startup):
```
Topic:   /mqtt/{product_id}/{sn}/thing/service_invoke/get_cur_path
Payload: { "method": "service.get_cur_path", "msgId": "...", "tenantId": "...", "version": "3.0", "params": {} }
Reply:   /mqtt/{product_id}/{sn}/thing/service_invoke_reply/get_cur_path
```

---

### 13.2 Full Map — Request / Reply

The full floor map is not pushed automatically. The app requests it by map ID.

**Step 1 — know which map to fetch:**
`DevProperties` (on the `property/post` topic) includes:
- `current_map_id` — ID of the active map (int)
- `map_num` — number of stored maps
- `has_new_map` — non-zero when a new map is available

**Step 2 — request map data:**
```
Topic:   /mqtt/{product_id}/{sn}/thing/service_invoke/upload_by_mapid
Payload: { "method": "service.upload_by_mapid", "msgId": "...", "tenantId": "...", "version": "3.0", "params": {"mapId": <current_map_id>} }
```

**Step 3 — receive reply:**
```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke_reply/upload_by_mapid
```

Reply payload is **not JSON** — it is a raw binary blob:
**QuickLZ-compressed protobuf** (`MapData.RobotMap`).

Parsing sequence (from `RobotMapApi.java:651`):
1. Decompress with QuickLZ → raw bytes
2. Parse protobuf: `MapData.RobotMap.parseFrom(decompressed_bytes)`

**To list all saved maps:**
```
Topic:   /mqtt/{product_id}/{sn}/thing/service_invoke/get_map_list
Payload: { "method": "service.get_map_list", "msgId": "...", "tenantId": "...", "version": "3.0", "params": {} }
Reply:   /mqtt/{product_id}/{sn}/thing/service_invoke_reply/get_map_list
```

---

### 13.3 Map Data Binary Format

The floor map grid is embedded inside the protobuf `MapData.MapDataInfo.mapData` field
(a `ByteString`). After extracting it with `.toByteArray()`, the raw bytes carry a 6-byte
header followed by the grid:

**6-byte header** (from `MapProcessUtil.processMapData()`):

| Bytes | Meaning |
|---|---|
| `[0..1]` | `mapTaskId` — unsigned 16-bit LE |
| `[2..3]` | `allDataLen` — unsigned 16-bit LE (byte count of the remaining data) |
| `[4..5]` | `timestamp` string length — unsigned 16-bit LE |
| `[6 .. 6+timestampLen-1]` | ASCII timestamp string |
| next 2 bytes | `packageId` string length |
| next N bytes | ASCII packageId string |
| remainder | Grid bytes |

**Grid format — 120×120 cells, 3 600 bytes, 2 bits per cell:**

Byte index for cell `(row, col)`:
```python
byte_index = (row // 2) * 60 + (col // 2)
bit_slot   = (row % 2) + (col % 2) * 2   # 0..3
```

Extracting the 2-bit value for `bit_slot`:
```python
shifts = {0: 6, 1: 4, 2: 2, 3: 0}
masks  = {0: 0xC0, 1: 0x30, 2: 0x0C, 3: 0x03}
cell_type = (byte & masks[bit_slot]) >> shifts[bit_slot]
```

**Cell type values:**

| Value | Meaning |
|---|---|
| `0` | Unknown / free (unvisited) |
| `1` | Wall / obstacle |
| `3` | Cleaned area |
| other | Treated as wall (`1`) in some parse paths |

The older `parseGlobalMapData` variant (7 200 bytes, 4 bits per cell) also exists but
`parseGlobalMapData3600` is the active path for the RCV5.

**Full-resolution format (14 400 bytes, 1 byte per cell)** is what the RCV5 sends when
rooms are present — it carries room IDs and the carpet checkerboard ranges (bytes
147–196 in-room, 253 non-room). See `doc/MAP_DATA.md` §4.2 for the verified byte table.

---

### 13.4 Protobuf Schema — `MapData.RobotMap`

The `.proto` file is not in the APK. Field numbers below were verified on 2026-06-12
against (a) the `newMessageInfo` descriptor string in APK `MapData.java` (v1.4.32) and
(b) the compiled descriptor in `karcher-home` 0.5.1 (`karcher/mapdata_pb2.py`) — both
agree. **`doc/MAP_DATA.md` §3 is the authoritative, fully expanded schema** (including
`FurnitureDataInfo` carpets and the grid-byte carpet encoding); this section is a summary.

```proto
message RobotMap {
  int32                 map_type       = 1;
  MapExtInfo            map_ext_info   = 2;   // task_begin_date, map_upload_date (Unix s), map_valid, angle — see MAP_DATA.md §3.1
  MapHeadInfo           map_head       = 3;   // resolution, dimensions, origin
  MapDataInfo           map_data       = 4;   // mapData bytes (grid, see §13.3)
  repeated AllMapInfo   map_info       = 5;   // list of stored maps
  DeviceHistoryPoseInfo history_pose   = 6;   // historical cleaning path
  DevicePoseDataInfo    charge_station = 7;   // charger location
  DeviceCurrentPoseInfo current_pose   = 8;   // robot's current position

  repeated DeviceAreaDataInfo            virtual_walls     = 9;
  repeated DeviceAreaDataInfo            areas_info        = 10;
  repeated DeviceNavigationPointDataInfo navigation_points = 11;

  repeated RoomDataInfo  room_data_info = 12;  // room segments
  DeviceRoomMatrix       room_matrix    = 13;  // room boundary bitmap
  repeated RoomChainInfo room_chain     = 14;  // room perimeter polygons
  repeated AiObjectInfo  objects        = 15;  // AI-detected objects

  repeated FurnitureDataInfo furniture_info = 16;  // carpet/furniture polygons
  repeated HouseInfo         house_infos    = 17;  // multi-map house grouping
}

message MapHeadInfo {
  float resolution = 1;   // metres per cell
  int32 sizeX      = 2;   // grid width  (120)
  int32 sizeY      = 3;   // grid height (120)
  float minX       = 4;   // world-space origin X
  float minY       = 5;   // world-space origin Y
}

message MapDataInfo {
  bytes mapData = 1;   // raw grid bytes (see §13.3)
}

message RoomDataInfo {
  int32  roomId       = 1;
  string roomName     = 2;
  int32  roomTypeId   = 3;
  int32  materialId   = 4;   // proto field name has APK typo "meterialId"
  int32  cleanState   = 5;
  int32  roomClean    = 6;
  int32  roomCleanIndex = 7;
  DevicePoseDataInfo roomNamePost = 8;   // label placement, world coords
  CleanPerferenceDataInfo cleanPerfer = 9;
  int32  colorId      = 10;  // palette index 1-5 (MAP_DATA.md §6.2)
}

message DeviceHistoryPoseInfo {
  int32  poseId  = 1;
  repeated DeviceCoverPointDataInfo points = 2;
}

message DeviceCoverPointDataInfo {
  float x = 1;
  float y = 2;
}

message DeviceCurrentPoseInfo {
  float x   = 1;
  float y   = 2;
  float phi = 3;   // heading angle (radians)
}

message DevicePoseDataInfo {
  float x   = 1;
  float y   = 2;
  float phi = 3;   // heading angle (radians) — present on charge_station too,
                    // the charger's own orientation (verified jadx MapData.java
                    // DevicePoseDataInfo.PHI_FIELD_NUMBER; field was previously
                    // undocumented here and dropped by the parser)
}
```

---

### 13.5 Implementation Notes

**QuickLZ:**
The map reply payload is compressed with QuickLZ level-1 (C library).
There is no widely-maintained PyPI package. Options:
- `python-quicklz` (ctypes wrapper, GitHub only, unmaintained)
- Compile `quicklz.c` as a shared library and call via `ctypes`
- Reimplement the decompression in pure Python (spec is public)
- Check if python-karcher already handles decompression before surfacing the bytes

Decompression is in `MapProcessUtil.decCombyte()` which calls `QuickLZ.sizeCompressed()`
and `QuickLZ.decompress()` on 9-byte-header chunks in a loop — the payload may be
multiple concatenated QuickLZ frames.

**Coordinate system:**
`cur_path` X/Y and protobuf X/Y use the same internal metric space.
`MapHeadInfo.minX/minY` give the world-space origin; `resolution` converts cells to metres.
To map a world coordinate `(wx, wy)` to a grid cell:
```python
col = int((wx - min_x) / resolution)
row = int((wy - min_y) / resolution)
```

**Rendering approach** (to match other HA integrations):
1. Decode grid → 120×120 NumPy array of cell types
2. Colourize: free=dark grey, wall=white, cleaned=light blue (or room-coloured)
3. Draw `history_pose` / accumulated `cur_path` points as a polyline
4. Draw robot position as a filled circle with heading indicator
5. Draw charger as a small icon
6. Encode as PNG bytes → return from `ImageEntity.async_image()`

**Subscribing to path pushes:**
`cur_path/post` is already in the `subDevTopic()` list in `MqttTopicUtil.java` alongside
`property/post`. The existing MQTT subscription setup will receive it automatically once
the topic is wired into the message handler.

---

## 14. Room Preferences — Custom Cleaning Order and Per-Room Settings

APK-verified (`ControlVM.java`, `CustomSortRoomActivity.java`, `CustomCleanSettingsActivity.java`,
`CustomBean.java`, `GetPreferenceResp.java` — v1.4.32, 2026-06-03).

The robot stores a **preference table** per map, keyed by `map_id`. Each room has an entry
controlling cleaning order, mode, suction, water level, and repeat passes. The table is
persistent on the robot and is used automatically on the next clean — the `set_room_clean`
command carries no order information.

---

### 14.1 `set_preference` — Write room preferences

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/set_preference
```

```json
{
  "method": "service.set_preference",
  "msgId": "<timestamp_ms>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {
    "map_id": <int>,
    "prefer_type": 1,
    "room_preference": [
      [roomId, roomName, materialId, mode, wind, water, repeat, carpet, check, 0, 0, carpetAvoidance],
      ...
    ]
  }
}
```

**`room_preference` is an ordered list of 12-element arrays. The array order defines the
cleaning order** — the robot cleans rooms in the sequence provided.

| Index | Field | Type | Values |
|---|---|---|---|
| 0 | `roomId` | int | Room ID from map protobuf |
| 1 | `roomName` | str | Room name (`""` if null) |
| 2 | `materialId` | int | `0` = hard floor, `1` = carpet |
| 3 | `mode` | int | `0` = Vacuum, `1` = Vacuum+Mop, `2` = Mop |
| 4 | `wind` | int | `0` = Silent, `1` = Standard, `2` = Medium, `3` = Turbo |
| 5 | `water` | int | `0` = Low, `1` = Medium, `2` = High (0-based, same scale as §5) |
| 6 | `repeat` | int | `0` = single, `1` = double, `2` = triple |
| 7 | `carpet` | int | Unused on RCV5 (always `0`) |
| 8 | `check` | int | `1` = custom settings active for this room, `0` = use global defaults |
| 9 | *(padding)* | int | Always `0` |
| 10 | *(padding)* | int | Always `0` |
| 11 | `carpetAvoidance` | int | `0` = off, `1` = on |

The `check` field is the per-room enable toggle: when `check=0`, the robot uses global
mode/wind/water settings for that room and ignores the row's per-room overrides. This maps
to the checkbox in the app's custom-clean settings list (`CustomRoomAdapter.java:54`).

`prefer_type: 1` is always sent; other values are not observed in the RCV5 APK.

---

### 14.2 `get_preference` — Read stored preferences

```
Topic:   /mqtt/{product_id}/{sn}/thing/service_invoke/get_preference
Reply:   /mqtt/{product_id}/{sn}/thing/service_invoke_reply/get_preference
```

**Request:**
```json
{
  "method": "service.get_preference",
  "msgId": "<timestamp_ms>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": { "map_id": <int> }
}
```

**Reply payload** (JSON, same service_invoke_reply envelope):
```json
{
  "code": 0,
  "data": {
    "prefer_on": <int>,
    "material": [[...], ...],
    "room": [
      [roomId, roomName, materialId, mode, wind, water, repeat, carpet, check, 0, 0, carpetAvoidance],
      ...
    ]
  }
}
```

`data.room` uses the same 12-element array layout as `set_preference.room_preference`.

`prefer_on` indicates whether the Customise tab is active on the robot:
- `1` — Custom mode (robot cleans using stored per-room preferences; card opens on Customise tab)
- `0` (or absent) — Standard mode (whole-floor clean; card opens on Standard tab)

This field is now read by the integration and stored as `coordinator.prefer_mode`
(`"customise"` | `"standard"`), exposed as `prefer_mode` in the vacuum entity's
`extra_state_attributes`, and used to restore the Lovelace card tab on load
(APK-verified: `ControlMainActivity.java:543`, `GuideThreeFragment.java:312`, v1.4.32, 2026-06-03).

`material` is not used by the integration (purpose not fully determined).

**Empty reply:** If `data.room` is empty or absent, the robot has no stored preferences
for this map yet (first boot or after a map reset). The app falls back to building
neutral defaults from the room list (`ControlVM.java:1331` — `dataRoom.size() <= 0` branch).
The integration does the same: synthesise defaults when the reply is empty.

---

### 14.3 `erase_preference` — Clear per-room preference

Resets custom preferences for one room (or all rooms if `erase_ids` is empty).

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/erase_preference
```
```json
{
  "method": "service.erase_preference",
  "msgId": "<timestamp_ms>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {
    "map_id": <int>,
    "prefer_type": 1,
    "erase_ids": [<roomId>]
  }
}
```

Pass `erase_ids: []` to clear all rooms. Not yet exposed in the HA integration.

---

### 14.4 `set_preference_type` — Switch Standard / Customise mode

Persists the active cleaning mode (Standard = whole-floor vs Customise = per-room preferences)
on the robot. The Kärcher app calls this when the user taps the Standard or Customise tab.

```
Topic:  /mqtt/{product_id}/{sn}/thing/service_invoke/set_preference_type
```

```json
{
  "method": "service.set_preference_type",
  "msgId": "<timestamp_ms>",
  "tenantId": "1528983614213726208",
  "version": "3.0",
  "params": {
    "prefer_type": <int>
  }
}
```

| `prefer_type` | Meaning |
|---|---|
| `0` | Standard — whole-floor clean |
| `1` | Customise — per-room preferences active |

The robot persists this setting; subsequent `get_preference` replies return `prefer_on`
matching the last-set `prefer_type`. This is the same value observed in the app after
killing and relaunching it.

APK-verified: `GuideVm.setPreferenceType` (GuideVm.java:212), `DeviceMethod.SET_PREFERENCE_TYPE`
(DeviceMethod.java:66), `ControlMainActivity.java:1553` (Standard), `1674` / `1698` (Customise),
v1.4.32, 2026-06-03.

---

### 14.5 Interaction with `set_room_clean`

The `set_room_clean` command (§5) carries **no order or per-room settings** in its payload.
Once preferences are stored via `set_preference`, the robot applies them automatically
on every subsequent clean. The preference table is keyed by `map_id`, so switching maps
changes which preference set is active.

---

## 11. Robot Hardware Notes

- **SoC**: Rockchip RV1126 (Linux-based), board ID `rv1126-3irobotix-CRL350_RCV5_V1.0`, confirmed
  by firmware device tree strings and RKFW image
- **Firmware**: **`I3.12.90`** (`firmware_code` `90`) — device-reported and confirmed to be
  **the latest published build** (built 2025-07-09, published 2025-10-10; the OTA chain offers
  nothing above it), extracted and audited directly (§9.3). RKFW format (Rockchip update.img),
  `productModelCode = Kaercher.KaercherRCV5Es`. Static analysis originally started from
  `I3.12.26`, the 2022 **factory baseline** (`curVersionCode: "0"`, not a superseded release —
  see §9); that gap is closed now that `.90` itself has been audited. Wire-protocol findings
  were never in doubt regardless: they come from live traffic and the APK, and the 2026-08-04
  auto-empty capture matched APK-derived expectations exactly on `.90`.
- **Connectivity**: Wi-Fi only (2.4 GHz), no Ethernet port
- **Local ports**: none open (pure MQTT client)
- **MQTT TLS**: TLSv1.2, ECDHE-RSA-AES256-GCM-SHA384, EC P-256 server cert
- **Cert pinning**: application-layer, against specific self-signed wildcard cert

---

## 15. Auto-Empty Dock — Suction Station RCV 5

**APK-derived, not device-captured. Capture date 2026-08-03, APK v1.4.32 (versionCode 10432).**
None of the fields below have appeared in a real RCV5 capture yet — see *Open questions*.

The [Suction Station RCV 5](https://www.kaercher.com/int/accessory/suction-station-rcv-5-22696430.html)
(part 22696430) is a dock that empties the robot's dust container into a 4 L filter bag and
doubles as the charging dock. Available both as a standalone accessory (retrofits onto an
existing RCV5) and bundled in an initial pack with the robot.

### 15.1 Command — trigger a manual empty

`service.start_station_act`, published to the device service topic:

```json
{
  "method": "service.start_station_act",
  "params": { "station_act": 3, "ctrl_value": 1 }
}
```

`station_act: 3` selects dust collection; `ctrl_value: 1` starts it. Source:
`ControlVM.startDustCollection()`. The generic form is
`Control330GVM.startStationAction(action, value)` → `{"station_act": action, "ctrl_value": value}`;
no caller of the generic form exists in the APK, so values other than `3`/`1` are unknown.

Note the name collision: **`station_act` is both a command parameter and a separate device
property, with unrelated semantics.** See below.

### 15.2 Properties

Three independent fields, all parsed from `thing.event.property.post` pushes
(`MqttMessageParser`). Only `charge_station_type` also appears in the app's explicit
`prop.get` list (`ControlVM.getPropertyList()`); the other two are push-only.

| Property | Meaning |
|---|---|
| `charge_station_type` | Dock type. `0` = plain charging dock. **`1` = Suction Station attached** *(device-confirmed 2026-08-04)*. Non-zero is what the app tests; sole driver of the empty button's visibility. |
| `dust_action` | Emptying progress. **`0` = idle, `2` = emptying** *(device-confirmed)*. `1` is treated as "emptying" by the app but was **never observed** on RCV5 — see below. |
| `station_act` | **Not used by auto-empty.** Stays `0` for the entire dust-collection cycle *(device-confirmed)*. The app's "refuse to start a clean while `station_act == 1`" gate therefore never fires for emptying; the flag most likely belongs to the mop-wash/self-clean station, a different accessory. (Its toast reuses string `fault_title_2015`, "Self-cleaning… try again later!" — a UI string, **not** evidence the robot emits a fault code 2015.) |

All three are present in the property stream on a station-equipped RCV5 — contrary to the
earlier assumption that only `charge_station_type` would be readable. Observed together in a
single message while docked and fully charged:

```
charge_station_type=1  dust_action=0  station_act=0
status=4  charge_state=1  work_mode=0  fault=2105  quantity=100
```

`fault=2105` here is "Charging completed", a lifecycle *status* rather than a hardware fault
(§6) — it independently corroborates the §15.3 decode, which shows the app rendering
`fault_title_2105` in exactly this docked-and-charged state.

#### Observed empty cycle (device capture, 2026-08-04)

Progress arrives as a **sparse delta push** carrying only the changed field:

```
  service_invoke_reply/start_station_act   {"result": 1}      ← command accepted
  event/property/post                      {"dust_action": 2} ← emptying starts
  … ~20 s …
  event/property/post                      {"dust_action": 0} ← emptying done
```

- The whole cycle took **~20 seconds**.
- `dust_action` went **0 → 2 → 0**. It never passed through `1`.
- `station_act` and `fault` did not change at any point; no station fault codes appeared.
- The `start_station_act` reply (`{"result": 1}`) was delivered **twice** for a single
  published command. Any handler must be idempotent.

### 15.3 App UI gating (decompiled)

The manual-empty button (`iv_home_dust_collection`) is a map-overlay button in
`home_right_control_layout`, stacked with area-clean and spot-clean over the map view.
It is `android:visibility="gone"` in `activity_control_main.xml`.

jadx fails to decompile the method that drives it — the logic is only visible in smali
(`ControlMainActivity.smali`, method `getPropertyInitDataView`). Reconstructed:

```kotlin
if (productId == PRODUCT_RCV5) {                    // 1540149850806333440
    if (dust_action == 1 || dust_action == 2) {
        tv_dev_status.text = "Emptying the dust container"
        setButtonEnabledDustCollection(false)
    } else {
        setButtonEnabledDustCollection(status == 4)  // enabled only while docked
        if (status == 4) { ...visible() } else { ...gone() }   // dead writes, see below
    }
    // merge point of every branch — overwrites the visibility set above:
    iv_home_dust_collection.visibility =
        if (charge_station_type == 0) View.GONE else View.VISIBLE
}
```

Two consequences worth stating exactly:

- The whole block is gated on the **RCV5 product ID**. Auto-empty is an RCV5 feature in this
  app, not a feature of some other Kärcher model.
- The `visible()`/`gone()` calls driven by `status == 4` are **dead writes** — the merge point
  overwrites visibility one step later from `charge_station_type` alone. So the button is
  visible **whenever a station is attached**, docked or not. `status == 4` (docked) governs
  only whether it is *enabled* (alpha 1.0 vs 0.1).

### 15.4 Fault codes — emptying station

Handled inline in `ControlMainActivity`/`ControlMain330GActivity` via string resources;
`RobotError.java` defines no named constants for these. 590 and 591 are additionally
gated on the RCV5 product ID.

| Code | App string |
|---|---|
| 590 | Faulty emptying of the dust container — "Make sure that the cover of the Base is closed and the filter is correctly inserted" |
| 591 | Faulty emptying of the dust container — "Please replace the filter bag regularly." |
| 592 | Faulty emptying of the dust container — "Filter cleaning, please wait a moment before starting the emptying process." |
| 593 | Faulty emptying of the dust container — "Please ensure that the **RCV 5 emptying station** cover is closed." |
| 594 | Faulty emptying of the dust container — "Please confirm that the filter bag is installed." |
| 595, 596 | "Emptying has failed, please check whether the robot is correctly positioned in the station." |
| 604 | "Emptying has already been initiated." |

String 593 names the RCV 5 explicitly — independent confirmation that these belong to this
product, not a shared-code artefact.

### 15.5 Open questions

Captured with `tests/tools/capture_station_props.py` against a station-equipped RCV5.

**Resolved 2026-08-04 (idle baseline):**

1. ~~The non-zero value of `charge_station_type`~~ → **`1`**. Caveat: one sample from one
   station model. `1` means "a station is attached"; whether other dock variants use other
   non-zero values is unknown, so **test `!= 0`, never `== 1`**, exactly as the app does.
2. ~~Idle values~~ → `dust_action = 0`, `station_act = 0`.

**Also resolved 2026-08-04 (full empty cycle captured):**

3. ~~The `dust_action` transition sequence~~ → **`0 → 2 → 0`**, over ~20 s. `1` never appeared.
   Treat "emptying" as `dust_action != 0`, not `== 1 || == 2`, so an unobserved third value
   cannot read as idle.
4. ~~Whether `station_act` goes to `1` during an empty~~ → **no, it stays `0` throughout.**
   The app's clean-blocking gate does not apply to auto-empty on this hardware.

**Still open:**

5. Whether faults 590–596/604 surface as ordinary `fault` values in the property stream.
   The captured cycle completed cleanly, so no station fault was produced. Confirming this
   needs a deliberately induced fault (e.g. run an empty with the bag removed or the lid
   open) — worth doing before surfacing station faults in HA.
6. Whether `dust_action == 1` occurs at all on RCV5 (a distinct phase, or dead in firmware).
   Faults 592 ("filter cleaning") hint at a second phase that this cycle did not exercise.
