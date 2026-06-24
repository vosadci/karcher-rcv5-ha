# Kärcher Home Robots — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![CI](https://github.com/vosadci/karcher-rcv5-ha/actions/workflows/ci.yml/badge.svg)](https://github.com/vosadci/karcher-rcv5-ha/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![HA Version](https://img.shields.io/badge/HA-2026.6.0%2B-blue.svg)](https://www.home-assistant.io/)

Unofficial community-built integration for the **Kärcher RCV5** robot vacuum. Provides real-time control and state via the same MQTT/REST cloud protocol the official app uses, with optional **Apple Home support via Matter**.

> **Not affiliated with or endorsed by Kärcher or 3iRobotix.** May break with cloud-side changes; use at your own risk.

> **Considering buying an RCV5?** Read [doc/READ_BEFORE_BUYING.md](doc/READ_BEFORE_BUYING.md) first.

**Contents:** [Features](#features) · [Requirements](#requirements) · [Installation](#installation) · [Configuration](#configuration) · [Entities](#entities) · [Lovelace Card](#lovelace-card) · [Apple Home](#apple-home-via-matter) · [Known Limitations](#known-limitations) · [Known Issues](#known-issues) · [Troubleshooting](#troubleshooting) · [Security](#security) · [Contributing](#contributing)

---

## Features

| Feature | Home Assistant | Apple Home |
|---|:---:|:---:|
| Start / Pause / Stop | ✓ | ✓ |
| Return to base | ✓ | ✓ |
| Battery level | ✓ | ✓ |
| Charging state | ✓ | ✓ |
| Locate robot | ✓ | ✓ |
| Room selection | ✓ | ✓ |
| Fan speed (Silent / Standard / Medium / Turbo) | ✓ | ✓ |
| Cleaning mode (Vacuum / Vacuum & Mop / Mop) | ✓ | ✓ |
| Mop water level (Low / Medium / High) | ✓ | ✓ |
| Consumable life sensors (brush, filter, mop pad) | ✓ | — |
| Consumable reset buttons | ✓ | — |
| Live floor plan map image with room area labels | ✓ | — |
| Custom Lovelace card with room-tap UI | ✓ | — |
| Per-room cleaning preferences (mode, fan speed, order, repeat) | ✓ | — |
| Area cleaning | ✓ | — |
| Per-room progress rings | — | ✓ |

![Apple Home](img/Apple_Home_screenshot.jpg)

---

## Requirements

- **Home Assistant** 2026.6.0 or newer
- **Kärcher Home Robots app account** — EU, US, or CN region
- **2.4 GHz Wi-Fi** reachable by the vacuum (the firmware does not support 5 GHz)
- **Apple Home** (optional): [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) v2.0.46 or newer and iOS/tvOS 26 or newer

> Earlier versions of these dependencies may work but have not been tested.

---

## Installation

### HACS — Custom Repository (recommended)

1. In Home Assistant, open **HACS → Integrations**.
2. Click the **⋮** menu in the top-right corner and choose **Custom repositories**.
3. Enter `https://github.com/vosadci/karcher-rcv5-ha` and set the category to **Integration**.
4. Search for **Kärcher Home Robots** and click **Download**.
5. Restart Home Assistant.

### Manual

1. Download or clone this repository.
2. Copy the `custom_components/karcher_home_robots/` folder into your Home Assistant configuration directory:

```bash
cp -r custom_components/karcher_home_robots /config/custom_components/
```

3. Restart Home Assistant.

---

## Configuration

After restarting, go to **Settings → Devices & Services → Add Integration** and search for **Kärcher Home Robots**. The setup wizard has three steps:

| Step | What to enter |
|---|---|
| **Region** | EU, US, or CN — must match the region of your Kärcher Home app account |
| **Credentials** | Email and password for your Kärcher Home app account |
| **Device** | Select your RCV5 from the list (skipped if only one device is on the account) |

The integration authenticates, subscribes to MQTT push updates, and creates all entities automatically. No YAML configuration is required.

### Running multiple robots

Each robot requires its own config entry. Run **Add Integration** once per robot. If they share an account, use the same credentials and pick a different device at the last step.

### Reauthentication

Token expiry is handled transparently. A **Reauthentication required** prompt only appears when the password itself is invalid (changed in the app, account locked, etc.). Go to **Settings → Devices & Services → Kärcher Home Robots → Reauthenticate** — region and device selection are preserved.

---

## Entities

| Entity | Description |
|---|---|
| `vacuum.<name>` | Main vacuum — start, pause, stop, dock, locate, fan speed |
| `sensor.<name>_battery` | Battery level (%) |
| `sensor.<name>_cleaning_area` | Area cleaned in the current session (m²) |
| `sensor.<name>_cleaning_time` | Duration of the current cleaning session (min) |
| `sensor.<name>_current_room` | Name of the room the robot is currently cleaning |
| `binary_sensor.<name>_charging` | On while the robot is charging |
| `binary_sensor.<name>_error` | On when the robot reports a fault |
| `sensor.<name>_fault_code` | Robot status — named fault states (e.g. "Dust box full", "LiDAR timeout"); no fault when idle (diagnostic) |
| `select.<name>_room` | Room to clean — "All rooms" or a specific room name |
| `select.<name>_cleaning_mode` | Vacuum / Vacuum & Mop / Mop |
| `select.<name>_water_level` | Mop water level — Low / Medium / High |
| `sensor.<name>_main_brush` | Main brush remaining life (%) |
| `sensor.<name>_side_brush` | Side brush remaining life (%) |
| `sensor.<name>_hypa` | Filter remaining life (%) |
| `sensor.<name>_mop_life` | Mop pad remaining life (%) |
| `button.<name>_reset_main_brush` | Reset main brush timer after replacement |
| `button.<name>_reset_side_brush` | Reset side brush timer after replacement |
| `button.<name>_reset_hypa` | Reset filter timer after replacement |
| `button.<name>_reset_mop_life` | Reset mop pad timer after replacement |
| `image.<name>_map` | Live floor plan rendered as a PNG |
| `select.<name>_room_<room>_mode` | Per-room cleaning mode — Vacuum / Vacuum & Mop / Mop |
| `select.<name>_room_<room>_power` | Per-room fan speed — Silent / Standard / Medium / Turbo |
| `number.<name>_room_<room>_order` | Per-room cleaning order (1 = first) |
| `switch.<name>_room_<room>_custom` | Enable per-room custom settings for this room |
| `select.<name>_room_<room>_repeat` | Per-room repeat passes — Single / Double |

Entity IDs use the device nickname set in the Kärcher app.

**Room selection.** Rooms are loaded from the robot's stored map at startup. Select a room and press Start to clean only that room; select "All rooms" to clean everything. The selection applies to the next start only — it is consumed when cleaning begins and the entity resets to "All rooms". This keeps `vacuum.start` whole-home for external callers (automations, voice assistants, Apple Home via HAMH). The room list updates automatically whenever the robot builds a new map.

**Mop attachment gating.** Cleaning modes that require the mop (Vacuum & Mop, Mop) are blocked unless the water tank and mop cloth are both physically installed. The water level selector is unavailable in Vacuum-only mode.

**Diagnostics.** Go to **Settings → Devices & Services → Kärcher Home Robots → ⋮ → Download diagnostics**. The output is automatically redacted of credentials, tokens, device identifiers, and serial numbers.

---

## Lovelace Card

The integration ships a custom map card — no separate HACS step required. The card resource is registered automatically on first startup.

> **YAML resource mode:** If your Lovelace configuration uses `resource_mode: yaml`, add the resource manually: URL `/karcher_home_robots/static/karcher-vacuum-card.js`, type `JavaScript Module`.

### Add to a dashboard

In the dashboard editor, add a **Manual** card and paste:

```yaml
type: custom:karcher-vacuum-card
vacuum_entity: vacuum.karcher_rcv5
```

The card auto-derives all companion entities from the vacuum entity stem (e.g. `vacuum.karcher_rcv5` → `sensor.karcher_rcv5_battery`, `image.karcher_rcv5_map`, etc.). Override individual entities only if your names differ:

```yaml
type: custom:karcher-vacuum-card
vacuum_entity: vacuum.karcher_rcv5
battery_entity: sensor.karcher_rcv5_battery          # override if name differs
map_entity: image.karcher_rcv5_map
current_room_entity: sensor.karcher_rcv5_current_room
cleaning_time_entity: sensor.karcher_rcv5_cleaning_time
cleaning_area_entity: sensor.karcher_rcv5_cleaning_area
cleaning_mode_entity: select.karcher_rcv5_cleaning_mode
water_level_entity: select.karcher_rcv5_water_level
error_entity: binary_sensor.karcher_rcv5_error
```

### Card capabilities

- Renders the live floor plan; refreshes automatically when the map updates
- Room pills on the map show the room name and its mapped area (m²)
- **Standard tab** — tap a room to select it (highlights); tap again to deselect; **Start** cleans the selected room or all rooms if none are selected
- **Customise tab** — set per-room cleaning order, mode, fan speed, repeat passes, and custom-settings toggle; drag to reorder rooms
- The active tab (Standard / Customise) is persisted on the robot and restored automatically on page reload, matching the behaviour of the official Kärcher app
- State-aware control buttons: Play/Pause · Stop · Dock · Locate
- Fan speed and cleaning mode selectors (fan speed is disabled in Mop-only mode)
- Mop water level selector (disabled in Vacuum-only mode; requires `water_level_entity`)
- Battery level, status line (including current room when `current_room_entity` is set), cleaning time and area
- Error banner when the robot reports a fault

---

## Apple Home via Matter

Requires [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) (HAMH) **v2.0.46 or newer** and **iOS/tvOS 26 or newer**. Note: the multi-room fix for [HAMH #367](https://github.com/RiDDiX/home-assistant-matter-hub/issues/367) (see Known Issues) is not yet in a stable release — it requires the alpha channel (`v2.1.0-alpha.721`+).

### Bridge setup (one-time)

In the HAMH web UI, create a new bridge:

1. Give it any name (e.g. `Kärcher RCV5`).
2. Enable **Server Mode**.
3. Add your vacuum entity (e.g. `vacuum.karcher_rcv5`) to the entity filter.
4. Click the vacuum row and set **Matter Device Type** to **Robot Vacuum Cleaner**.
5. Map the optional entities:
   - **Cleaning Mode** → `select.<name>_cleaning_mode`
   - **Mop Intensity** → `select.<name>_water_level`
   - **Current Room** → `sensor.<name>_current_room`

### Map rooms to Home areas (one-time, enables room picker)

For the Apple Home room picker to work, each vacuum room must be mapped to a Home Assistant area:

1. In Home Assistant, go to **Settings → Devices & Services → Entities** and open `vacuum.<name>`.
2. In the entity detail, find **Vacuum area mapping** and click **Configure**.
3. Assign each room reported by the robot to a matching Home Assistant area (create areas first if needed).

HAMH reads this mapping at startup and exposes the rooms as selectable areas in Apple Home. Without it the room picker is not shown.

### Pair with Apple Home (one-time)

HAMH shows a Matter QR code. In the **Home** app, tap **Add Accessory → More Options** and scan it.

### What appears in Apple Home

- Start / Stop / Return to Base
- Locate — plays a sound on the robot to find it (Home app *Identify*)
- Battery percentage
- Room picker — select one or more rooms before pressing Start
- Fan speed: Quiet / Automatic / Max
- Cleaning type: Vacuum / Mop / Vacuum and Mop
- Mop intensity: Quiet / Automatic / Max (visible when a mop mode is active)
- Per-room progress rings: each selected room shows a spinner while being cleaned, then a filled ring when complete

---

## Known Limitations

- **Cloud-only.** The RCV5 has no local API; all control goes through the 3iRobotix cloud. An internet outage or vendor-side maintenance will make the robot unreachable from Home Assistant.
- **One robot per config entry.** Multi-robot accounts are supported but require adding the integration once per robot.
- **Map requires a completed clean.** The robot only uploads its floor plan after finishing a full cleaning cycle. Run one complete clean before expecting the map image or room list to appear.
- **2.4 GHz Wi-Fi only.** The RCV5 firmware does not connect to 5 GHz.
- **No schedule management.** Cleaning schedules can only be set in the Kärcher app; they are not exposed as Home Assistant entities.
- **No zone or custom-path cleaning.** Only full-home and per-room modes are supported.

---

## Known Issues

**Apple Home: starting a clean with all rooms selected cleans only one room (random), HAMH older than v2.1.0-alpha.720.**
When the Matter bridge still reports a stale `currentArea` left over from a previous run, the Home app treats the vacuum as busy and silently truncates the `SelectAreas` command it sends to a single room — the Home app UI keeps showing all rooms as selected, and HAMH then dispatches a one-room clean. Each truncated clean leaves fresh stale state behind, so the room differs on every attempt. This is [HAMH issue #367](https://github.com/RiDDiX/home-assistant-matter-hub/issues/367); fixed upstream in HAMH `v2.1.0-alpha.720` (clear `currentArea` on new selection) and `v2.1.0-alpha.721` (batch area merge), building on the `currentArea` cleanup fixes for [#335](https://github.com/RiDDiX/home-assistant-matter-hub/issues/335). Nothing in this integration can work around it — the truncation happens inside Apple Home before HAMH calls Home Assistant. Update the HAMH add-on to `v2.1.0-alpha.721` or newer and restart it.

**Apple Home: room progress rings mark a transit room as cleaned.**
The per-room progress rings in Apple Home are driven by the `current_room` sensor: when the robot leaves a room, HAMH marks that room as cleaned. This means a room the robot merely passes through on its way to another room can be incorrectly marked as cleaned in Apple Home, even though it was never vacuumed. The underlying cause is that HAMH infers completion from robot position changes, not from the grid-level cell data that tracks which floor area has actually been covered.

---

## Troubleshooting

**Login fails with the correct password.**
Check the region setting. Accounts are region-bound — an EU account will not authenticate against the US endpoint. If the region is correct, try logging in through the Kärcher Home Robots app to verify the credentials.

**`Reauthentication required` banner appears.**
The saved password is no longer valid. Go to **Settings → Devices & Services → Kärcher Home Robots → Reauthenticate** and enter the current password. The integration handles normal token expiry automatically; you only see this prompt when the credentials themselves have changed.

**Entities go unavailable.**
The 3iRobotix cloud is unreachable. The integration recovers automatically when the connection is restored — no user action is needed. After one hour of continuous unavailability, a **repair** issue appears in Home Assistant with details; it dismisses itself on the next successful poll.

**Room list is empty.**
Run a complete cleaning cycle so the robot builds and uploads its map. The room list populates on the next successful update after the cycle finishes.

**Fan speed shows as unavailable.**
This is expected when Mop-only cleaning mode is selected — the RCV5 has no suction in that mode.

**Map image does not update.**
The map image refreshes on dock and every 10 s during active cleaning. If it never appears, check that the robot has completed at least one full clean (see above) and that `image.<name>_map` is enabled in the entity registry.

For anything not covered here, download diagnostics (**Settings → Devices & Services → Kärcher Home Robots → ⋮ → Download diagnostics**) and attach them when opening an issue.

---

## Security

- TLS is pinned to the bundled 3iRobotix CA certificate; the integration does not fall back to the system trust store.
- Credentials, tokens, serial numbers, and MQTT payloads are never logged above the `DEBUG` level.
- No telemetry is sent anywhere other than the vendor cloud the robot itself communicates with.

To report a vulnerability privately, see [SECURITY.md](.github/SECURITY.md).

---

## Contributing

- [ARCHITECTURE.md](ARCHITECTURE.md) — module map, layer rules, error taxonomy
- [CLAUDE.md](CLAUDE.md) — development commands and constraints

---

## Acknowledgements

- [`karcher-home`](https://github.com/lafriks/karcher-home) by [@lafriks](https://github.com/lafriks) — underlying cloud-protocol library
- [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) by [@RiDDiX](https://github.com/RiDDiX) — Apple Home bridge

---

## Licence

MIT — see [LICENSE](LICENSE).

*Not affiliated with Kärcher SE & Co. KG or 3iRobotix Co., Ltd. All trademarks are the property of their respective owners.*
