# Architecture
## Kärcher RCV5 — Home Assistant Integration

---

## 1. System Context

```
┌─────────────────────────────────────────────────────────────┐
│                     User's Home Network                     │
│                                                             │
│  ┌──────────────┐        ┌─────────────────────────────┐   │
│  │ Home         │        │ Home Assistant              │   │
│  │ Assistant    │◄──────►│ karcher_home_robots         │   │
│  │ UI / App     │        │ (this integration)          │   │
│  └──────────────┘        └────────────┬────────────────┘   │
│                                       │ HTTPS / MQTT TLS    │
└───────────────────────────────────────┼─────────────────────┘
                                        │ (outbound only)
                         ┌──────────────▼──────────────┐
                         │  3iRobotix Cloud (EU/US/CN)  │
                         │  REST: eu-appaiot.*          │
                         │  MQTT: eu-gamqttaiot.*:8883  │
                         └──────────────┬───────────────┘
                                        │ MQTT TLS (cloud-brokered)
                         ┌──────────────▼───────────────┐
                         │       Kärcher RCV5            │
                         │  (connects to same MQTT broker│
                         │   from anywhere on internet)  │
                         └──────────────────────────────┘
```

There is no direct LAN connection between Home Assistant and the robot. All communication is routed through the 3iRobotix cloud broker. The robot and the integration both maintain persistent MQTT connections to the same broker; the broker relays messages between them.

---

## 2. Component Overview

```
custom_components/karcher_home_robots/
│
├── __init__.py          Entry point: setup and teardown
├── config_flow.py       UI wizard: region → credentials → device
├── coordinator.py       State management: polling + MQTT push
├── api.py               Cloud wrapper: REST auth + MQTT commands
├── entity.py            Shared base: device info, coordinator binding
│
├── vacuum.py            Entity: vacuum control + room start
├── sensor.py            Entities: battery, cleaning area, cleaning time
├── select.py            Entities: room, cleaning mode, water level
├── binary_sensor.py     Entity: error/fault indicator
│
└── const.py             Constants: commands, state maps, config keys
```

### Responsibilities

| Module | Responsibility |
|--------|---------------|
| `__init__.py` | Orchestrates setup: authenticate, subscribe MQTT, start coordinator, load platforms |
| `config_flow.py` | Multi-step config wizard; validates credentials; stores config entry |
| `api.py` | Async/sync wrapper around `python-karcher`; patches MQTT push handler |
| `coordinator.py` | Owns device state; delivers updates to all entities via DataUpdateCoordinator |
| `entity.py` | Base class; wires all entities to a single coordinator and device info block |
| `vacuum.py` | Translates HA vacuum service calls to MQTT commands; room logic |
| `sensor.py` | Read-only sensors: battery, area, time |
| `select.py` | Select entities: room (in-memory), cleaning mode and water level (API) |
| `binary_sensor.py` | Fault indicator with suppression logic |
| `const.py` | All magic numbers: work_mode sets, command payloads, value maps |

---

## 3. Layer Diagram

```
┌─────────────────────────────────────────────┐
│              Home Assistant Core            │
│  DataUpdateCoordinator  ConfigFlow  Entity  │
└──────────────────┬──────────────────────────┘
                   │ inherits / uses
┌──────────────────▼──────────────────────────┐
│           Integration Layer                 │
│  coordinator.py   config_flow.py  entity.py │
│  vacuum.py  sensor.py  select.py            │
│  binary_sensor.py                           │
└──────────────────┬──────────────────────────┘
                   │ calls
┌──────────────────▼──────────────────────────┐
│             API Wrapper (api.py)            │
│  async authenticate / get_devices / close   │
│  sync  subscribe / fetch / send / set       │
└──────────────────┬──────────────────────────┘
                   │ wraps
┌──────────────────▼──────────────────────────┐
│        python-karcher library               │
│  KarcherHome  Device  DeviceProperties      │
│  paho-mqtt (internal)                       │
└──────────────────┬──────────────────────────┘
                   │ TCP/TLS
┌──────────────────▼──────────────────────────┐
│         3iRobotix Cloud                     │
│  REST (eu-appaiot.*)  MQTT (eu-gamqttaiot.*)│
└─────────────────────────────────────────────┘
```

---

## 4. Threading Model

The integration runs across three thread contexts:

| Context | What runs there |
|---------|----------------|
| **HA event loop** | All `async` code: entity property reads, coordinator refresh, callback dispatch, platform setup/teardown |
| **Executor thread pool** | Blocking library calls: `subscribe_device`, `fetch_properties`, `send_command`, `set_property` |
| **paho-mqtt thread** | MQTT message reception and the patched `on_message` handler |

The paho-mqtt thread cannot call HA APIs directly. The bridge is:

```
paho-mqtt thread
  └─ _on_push(props)
       └─ hass.loop.call_soon_threadsafe(coordinator.handle_mqtt_push, props)
                                          └─ runs in HA event loop
```

Blocking library calls run in an executor to avoid freezing the event loop:

```python
await hass.async_add_executor_job(api.subscribe_device, device, callback)
await loop.run_in_executor(None, api.fetch_properties, device)
```

---

## 5. Data Flow: State Updates

### MQTT Push (fast path, ~2s)

```
Robot changes state
  └─ Publishes: /mqtt/{product_id}/{sn}/thing/event/property/post
       └─ paho-mqtt thread receives message
            └─ _patched_on_message():
                 ├─ Calls original on_message (library cache update)
                 ├─ Parses payload JSON → params dict
                 ├─ Calls _update_device_properties(sn, params)
                 └─ Fires push_callback(DeviceProperties)
                      └─ call_soon_threadsafe(coordinator.handle_mqtt_push, props)
                           └─ coordinator.async_set_updated_data(props)
                                └─ All entities re-render
```

### Polling Fallback (every 30s)

```
30s interval elapses
  └─ coordinator._async_update_data()
       └─ async_add_executor_job(api.fetch_properties, device)
            └─ Executor: publish prop.get → wait for get_reply (5s)
                 └─ Return DeviceProperties
                      └─ coordinator stores result → entities re-render
```

---

## 6. Data Flow: Commands

All commands originate in an entity's `async_*` method, dispatch to an executor, and publish to MQTT:

```
Entity method (HA event loop)
  └─ api.async_send_command(dev, service, params)   ← for service commands
  └─ api.async_set_property(dev, params)            ← for property-set commands
       └─ loop.run_in_executor(None, sync_method)
            └─ Executor: _client._mqtt.publish(topic, json_payload)
                 └─ coordinator.async_request_refresh()  ← schedule re-poll
```

Two MQTT payload formats are used:

| Type | Topic suffix | Method | Version |
|------|-------------|--------|---------|
| Service command | `thing/service_invoke/{name}` | `service.{name}` | `3.0` |
| Property set | `thing/service/property/set` | `prop.set` | `1.0` |

---

## 7. Config Entry Lifecycle

```
Add Integration
  └─ config_flow: region → credentials → device → create entry
       └─ async_setup_entry:
            ├─ KarcherApi.authenticate()
            ├─ KarcherApi.get_devices() → validate device_id
            ├─ KarcherCoordinator created
            ├─ api.get_rooms() → coordinator.rooms
            ├─ subscribe_device(noop)       ← MQTT connection established
            ├─ first_refresh()              ← initial poll; starts 30s loop
            ├─ set_push_callback(real_cb)   ← MQTT push now active
            ├─ hass.data[DOMAIN][entry_id] = coordinator
            └─ forward to platforms (vacuum, sensor, select, binary_sensor)

Normal operation
  └─ MQTT pushes arrive → handle_mqtt_push → entities update
  └─ 30s interval → _async_update_data → entities update
  └─ User actions → entity methods → MQTT commands

Token expiry
  └─ _async_update_data raises ConfigEntryAuthFailed
       └─ HA triggers re-auth flow → user re-enters credentials
            └─ entry.data updated → entry reloaded

Remove Integration
  └─ async_unload_entry:
       ├─ Unload platforms
       ├─ coordinator.api.close()   ← MQTT disconnect
       └─ Remove from hass.data
```

---

## 8. External Dependencies

### python-karcher (`karcher-home` on PyPI)

The integration wraps the `karcher-home` library. Two known bugs in version 0.5.x are worked around in `api.py`:

| Bug | Workaround |
|-----|-----------|
| `thing/event/property/post` messages ignored (library sets a wait-event and returns without updating `_device_props`) | Patched `on_message` manually calls `_update_device_properties` |
| `get_device_properties()` returns stale cached data when device is already subscribed | `fetch_properties()` always calls `request_device_update()` and waits for the reply topic |

### Home Assistant Framework

Key HA abstractions used:

| Class | Purpose |
|-------|---------|
| `DataUpdateCoordinator` | Manages polling interval, last-update-success, and entity fan-out |
| `CoordinatorEntity` | Subscribes entities to coordinator updates automatically |
| `ConfigEntry` | Persists configuration and credentials |
| `ConfigEntryAuthFailed` | Signals HA to trigger re-auth flow |
| `ConfigEntryNotReady` | Signals HA to retry setup with backoff |

---

## 9. Key Design Decisions

### No direct library subclassing
`KarcherApi` wraps `KarcherHome` by composition rather than inheritance. This isolates the integration from library internals and makes the executor/async boundary explicit.

### Two-phase MQTT subscription
MQTT is subscribed with a no-op callback before `first_refresh()`, then upgraded to the real callback after. This prevents a race where a push arrives before `coordinator.data` is initialised.

### Room selection is in-memory
`coordinator.selected_room_id` is not persisted. Room selection resets on HA restart. This avoids stale state (e.g. room deleted from map after a remap) and keeps the config entry data clean.

### All-rooms send explicit IDs
An empty `room_ids: []` causes the firmware to clean a single room semi-randomly. The integration explicitly sends all known room IDs to trigger a full clean.

### Fault suppression
`binary_sensor._error` only activates when `fault != 0` AND the robot is idle AND not docked. Non-zero fault values are normal during cleaning and charging and would cause false positives.
