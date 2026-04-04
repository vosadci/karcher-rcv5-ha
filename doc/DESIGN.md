# Design Document
## Kärcher RCV5 — Home Assistant Integration

---

## 1. Module Responsibilities

| Module | Class(es) | Role |
|--------|-----------|------|
| `api.py` | `KarcherApi` | Async/sync boundary; all cloud I/O |
| `coordinator.py` | `KarcherCoordinator`, `derive_vacuum_state` | Owns device state; delivers updates |
| `config_flow.py` | `KarcherConfigFlow` | Setup wizard; credential validation |
| `entity.py` | `KarcherEntity` | Base for all entities; device info |
| `vacuum.py` | `KarcherVacuum` | Vacuum control + room start logic |
| `sensor.py` | `KarcherBatterySensor`, `KarcherCleaningAreaSensor`, `KarcherCleaningTimeSensor` | Read-only sensors |
| `select.py` | `KarcherRoomSelect`, `KarcherCleaningModeSelect`, `KarcherWaterLevelSelect` | Configurable selects |
| `binary_sensor.py` | `KarcherErrorBinarySensor` | Fault indicator |

---

## 2. Class Diagram

```
                    ┌────────────��─────────────────┐
                    │   DataUpdateCoordinator (HA)  │
                    └──────────────┬───────────────┘
                                   │ inherits
                    ┌──────────────▼───────────────┐
                    │      KarcherCoordinator       │
                    │  + api: KarcherApi            │
                    │  + device: Device             │
                    │  + rooms: list[dict]          │
                    │  + selected_room_id: int|None │
                    │  ──────────────────────────── │
                    │  + _async_update_data()       │
                    │  + handle_mqtt_push(props)    │
                    └──────────────┬───────────────┘
                                   │ referenced by
                    ┌──────────────▼───────────────┐
                    │     CoordinatorEntity (HA)    │
                    └─────────────���┬───────────────┘
                                   │ inherits
                    ┌──────────────▼───────────────���
                    │        KarcherEntity          │
                    │  + device_info: DeviceInfo    │
                    └──┬────────┬────────┬──────────┘
                       │        │        │
          ┌────────────▼─┐  ┌──▼──────┐ │
          │ KarcherVacuum│  │ Karcher │ │
          │              │  │Battery  │ │  (+ Area, Time sensors)
          └──────────────┘  │Sensor   │ │
                            └─────────┘ │
                              ┌─────────▼──────────┐
                              │  KarcherRoomSelect  │
                              │  KarcherCleaningMode│
                              │  KarcherWaterLevel  │
                              │  KarcherErrorBinary │
                              └────────────────────┘

                    ┌─────────────────────────��────┐
                    │         KarcherApi            │
                    │  - _client: KarcherHome       │
                    │  - _push_callbacks: dict      │
                    │  ───────────────���──────────── │
                    │  async authenticate()         │
                    │  async get_devices()          │
                    │  async get_rooms()            │
                    │  sync  subscribe_device()     │
                    │  sync  fetch_properties()     │
                    │  sync  send_command()         │
                    │  sync  set_property()         │
                    │  async async_send_command()   │
                    │  async async_set_property()   │
                    │  async close()                │
                    └──────────────┬───────────────┘
                                   │ wraps
                    ┌──────────────▼───────────────┐
                    │   KarcherHome (python-karcher) │
                    │   paho-mqtt (internal)         │
                    └──────────────────────────────┘
```

---

## 3. Config Flow State Machine

```
        ┌─────────┐
        │  Start  │
        └────┬────┘
             │
             ▼
    ┌─────────────────��┐
    │  step: user      │  Show region dropdown (EU / US / CN)
    └────────┬─────────┘
             │ region selected
             ▼
    ┌──────────────────┐
    │  step: credentials│  Show email + password form
    └────────┬──────┬───┘
             │      │ error (invalid_auth / cannot_connect / no_devices)
             │      └─���────────────────────────┐
             │                                 │ re-show form with error
             │ success                         ◄
             │
     ┌───────┴────────────────────────┐
     │ 1 device?       multiple?      │
     ▼                                ▼
 ┌──────────┐             ┌──────────────────┐
 │ _create  │             │  step: device    │  Show device picker
 │  entry   │◄────────────┤                  │
 └──────────┘  selected   └──────────────���───┘
      │
      ▼
 ┌──────────┐
 │  Done    │  Config entry created; async_setup_entry fires
 └──────────┘

Re-auth flow (triggered by ConfigEntryAuthFailed):
    ┌────────────────────────┐
    │  step: reauth_confirm  │  Show email + password
    └──────────┬────────────┘
               │ valid
               ▼
    Update entry.data → reload entry → abort(reauth_successful)
```

---

## 4. State Derivation

The robot reports a `work_mode` integer. Multiple values map to the same logical state (firmware encodes sub-states such as room count, mode variant, etc.).

```
work_mode ────────────────���─────────────────────────────────────────┐
                                                                    │
  ∈ WORK_MODE_CLEANING                                              │
  {1,7,25,30,36,81}         ──────────────────────► Cleaning        │
                                                                    │
  ∈ WORK_MODE_PAUSE                                                  │
  {4,9,27,31,37,82}         ──────────────────────► Paused          │
                                                                    │
  ∈ WORK_MODE_GO_HOME                                               │
  {5,10,11,12,21,26,32,38,47}──► docked? ──Yes──► Docked            │
                                           │                        │
                                          No                        │
                                           └──────────────────────► Returning
                                                                    │
  ∈ WORK_MODE_IDLE                                                   │
  {0,14,23,29,35,40,85}    ───► docked? ──Yes──► Docked             │
                                          │                        │
                                         No                        │
                                          └──► fault != 0? ──Yes──► Error
                                                          │        │
                                                         No        │
                                                          └───────► Idle
                                                                    │
  (fallback)                ───────────���──────────────────────────► Unknown
                                                                    │
docked = (status == STATUS_DOCKED) OR (charge_state > 0)            │
                                                                    ◄
```

---

## 5. Sequence Diagram: Integration Setup

```
HA Core          __init__.py       KarcherApi        KarcherHome       3iRobotix Cloud
   │                  │                │                  │                  │
   │ setup_entry()    │                │                  │                  │
   │─────────────────►│                │                  │                  │
   │                  │ authenticate() │                  │                  │
   │                  │───────────────►│ KarcherHome.create()               │
   │                  │                │─────────────────►│ GET /domains     │
   │                  ���                │                  │─────────────────►│
   │                  │                │                  │◄─────────────────│
   │                  │                │                  │ login(email,pw)  │
   │                  │                │                  │─────────────────►│
   │                  │                │                  │◄────────────��────│
   │                  │◄──────────────��│                  │                  │
   │                  │ get_devices()  │                  │                  │
   │                  │───────────────►│ get_devices()    │                  │
   │                  │                │─────────────────►│ GET /devices     │
   │                  │                │                  │─────────────────►│
   │                  │                │                  │◄────────────��────│
   │                  │◄─────────────��─│                  │                  │
   │                  │ get_rooms()    │                  │                  │
   │                  │───────────────►│ get_map_data()   │                  │
   │                  │                │─────────────────►│ GET /map         │
   │                  │                │                  │─────────────────►│
   │                  │                │                  │◄─────────────────│
   │                  │◄───────────────│                  │                  │
   │                  │ subscribe(noop)│                  │                  │
   │                  │───��───────────►│ subscribe_device()                  │
   │                  │                │────��────────────►│ MQTT CONNECT     │
   │                  │                │                  │─────────────────►│
   │                  │                │                  │◄────────────���────│
   │                  │◄───────────────│                  │                  │
   │                  │ first_refresh()│                  │                  │
   │                  │────────────────────────────────────────────────────► │
   │                  │                │ fetch_properties()                   │
   │                  │                │─────────────────►│ MQTT prop.get    │
   │                  │                │                  │─────────────────►│
   │                  │                │                  │◄── get_reply ────│
   │                  │◄───────────���───│                  │                  │
   │                  │ set_push_callback(real_cb)         │                  │
   │                  │─────────────���─►│                  │                  │
   �� forward_entry_setups()           │                  │                  │
   │────────���────────►│                │                  │                  ���
   │◄────────────���────│ True           │                  │                  │
```

---

## 6. Sequence Diagram: MQTT Push Update

```
Robot      3iRobotix MQTT     paho-mqtt thread      HA event loop
  │               │                  │                    │
  │ state changes │                  │                    │
  │──property/post►│                  │                    │
  │               │──on_message()────►│                    │
  │               │                  │ parse JSON         │
  │               │                  │ _update_device_props│
  │               │                  │ push_callback(props)│
  │               │                  │ call_soon_threadsafe►│
  │               │                  │                    │ handle_mqtt_push(props)
  │               │                  │                    │ async_set_updated_data(props)
  │               │                  │                    │ → all entities re-render
```

---

## 7. Sequence Diagram: Room Clean Command

```
User (HA UI)    KarcherRoomSelect    KarcherVacuum      KarcherApi       MQTT Broker
     │                 │                  │                  │                │
     │ select "Kitchen"│                  │                  │                │
     │────────────────►│                  │                  │                │
     │                 │ selected_room_id=2                   │                │
     │                 │─────────────���────────────────────────────────────────│
     │                 │ (no API call)    │                  │                │
     │                 │                  │                  │                │
     │ press Start     │                  │                  ��                │
     │──────────────────────────────────►│                  │                │
     │                 │                  │ async_send_command(               │
     │                 │                  │  "set_room_clean",                │
     │                 │                  │  {room_ids:[2], ctrl_value:1})    │
     │                 │                  │─────────────────►│                │
     │                 │                  │  [executor]      │ publish()      │
     │                 │                  │                  │───────────────���│
     │                 │                  │                  │                │──► Robot
     │                 ���                  │ async_request_refresh()           │
     │                 │                  │───────────────���──────────────────►│
```

---

## 8. Entity Availability and Dependency

```
Always available (when coordinator has data):
  vacuum.<name>
  sensor.<name>_battery
  sensor.<name>_cleaning_area
  sensor.<name>_cleaning_time
  binary_sensor.<name>_error
  select.<name>_room           (options = ["All rooms"] if no map)
  select.<name>_cleaning_mode

Conditionally available:
  select.<name>_water_level    ← ONLY when cleaning_mode != "Vacuum"
                                 (i.e., DeviceProperties.mode != 0)

Fan speed (vacuum entity):
  fan_speed property           ← returns None when mode == "Mop" (mode == 2)
  fan_speed_list               ← returns [] when mode == "Mop"
```

---

## 9. Data Model

### Config Entry (`entry.data`)

```python
{
    "country":          str,   # "EU" | "US" | "CN"
    "email":            str,   # Kärcher account email
    "password":         str,   # Kärcher account password
    "device_id":        str,   # Unique device identifier
    "device_sn":        str,   # Device serial number
    "device_nickname":  str,   # User-assigned name from app
}
```

### DeviceProperties (from python-karcher)

| Field | Type | Meaning |
|-------|------|---------|
| `quantity` | int | Battery level (0–100) |
| `work_mode` | int | Primary state signal (see state derivation) |
| `mode` | int | Always 0; not used for state mapping |
| `status` | int | Secondary: 4 = docked |
| `charge_state` | int | Non-zero = charging/docked |
| `fault` | int | 0 = no fault |
| `water` | int | Water level: 0=inactive, 1=Low, 2=Medium, 3=High |
| `wind` | int | Fan speed: 0=Silent, 1=Standard, 2=Medium, 3=Turbo |
| `cleaning_area` | int | Raw area in cm² (divide by 100 for m²) |
| `cleaning_time` | int | Cleaning duration (minutes) |
| `current_map_id` | int | Active map ID |

### Coordinator Runtime State

```python
coordinator.data              # DeviceProperties | None
coordinator.rooms             # [{"id": int, "name": str}, ...]
coordinator.selected_room_id  # int | None  (in-memory; not persisted)
```

---

## 10. Error Handling

| Exception | Where caught | Action |
|-----------|-------------|--------|
| `KarcherHomeInvalidAuth` | `async_setup_entry` | Raise `ConfigEntryAuthFailed` → re-auth flow |
| `KarcherHomeException` | `async_setup_entry` | Raise `ConfigEntryNotReady` → retry with backoff |
| Device not in account | `async_setup_entry` | Raise `ConfigEntryNotReady` |
| `KarcherHomeTokenExpired` | `_async_update_data` | Raise `ConfigEntryAuthFailed` → re-auth flow |
| `KarcherHomeAccessDenied` | `_async_update_data` | Raise `ConfigEntryAuthFailed` → re-auth flow |
| Any other exception | `_async_update_data` | Raise `UpdateFailed` → coordinator retries |
| Map fetch failure | `get_rooms` | Return `[]`; room select shows "All rooms" only |
| MQTT parse error | `_patched_on_message` | Log debug; continue (push silently dropped) |
