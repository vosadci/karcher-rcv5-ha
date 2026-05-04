# Kärcher RCV5 App — Feature Inventory

Source: decompiled `KHR_1.4.32_APKPure.apk` via jadx, inspected 2026-05-03.
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
| `edge_clean` | Edge/perimeter clean |
| `start_station_act` | Dock station action (auto-empty, electrolysis, etc.) |
| `set_calibration` | Robot calibration |
| `set_direction` | Directional movement |
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
| `tank_state` | Water tank state |
| `cloth_state` | Mop cloth state |
| `mop_life` | Mop pad remaining life |
| `main_brush` | Main brush remaining life |
| `side_brush` | Side brush remaining life |
| `hypa` | HEPA filter remaining life |
| `cleaning_time` | Session duration |
| `cleaning_area` | Session area covered |
| `quantity` | Session count |
| `current_map_id` | Active map ID |
| `map_num` | Number of maps |
| `build_map` | Map-building status |
| `quiet_is_open` | Quiet mode enabled |
| `quiet_begin_time` | Quiet mode start time |
| `quiet_end_time` | Quiet mode end time |
| `volume` | Speaker volume |
| `sound` | Sound setting |
| `voice_type` | Voice pack selection |
| `net_status` | Network connectivity |
| fault codes | Error/fault state |
| station activity | Dock activity status |

## Features Not Yet in the HA Integration (potential additions)

- `set_direction` / `set_calibration` commands — purpose unclear, worth investigating
- `start_station_act` — dock control (auto-empty, electrolysis/self-clean)
- `tank_state` and `cloth_state` — additional binary sensors or sensors
- Per-room suction/water level preferences
- Zone clean and point clean with coordinate payloads
- Edge clean mode
- Quiet mode time window as configurable settings
- Device sharing / multi-user (cloud-side, likely not HA-relevant)
- OTA firmware upgrade trigger
