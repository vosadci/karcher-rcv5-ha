# Kärcher Home Robots — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![CI](https://github.com/vosadci/karcher-rcv5-ha/actions/workflows/ci.yml/badge.svg)](https://github.com/vosadci/karcher-rcv5-ha/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Considering buying an RCV5?** Read [doc/READ_BEFORE_BUYING.md](doc/READ_BEFORE_BUYING.md) first — it covers Kärcher's marketing claims and what independent investigation found.

> **Personal project** — Unofficial, community-built integration. Not affiliated with or endorsed by Kärcher or 3iRobotix. May break with cloud-side changes; use at your own risk.

A custom [Home Assistant](https://www.home-assistant.io/) integration for the **Kärcher RCV5** robot vacuum, with optional **Apple Home support via Matter**.

There is no official Home Assistant integration and no local API. The RCV5 communicates only with the 3iRobotix cloud, so this integration speaks the same wire protocol — MQTT for control and state, REST for authentication — to give you real-time control and state updates.

![Apple Home](img/Apple_Home_screenshot.jpg)

---

## What you get

| Feature | Home Assistant | Apple Home |
|---|---|---|
| Start / Pause / Stop | ✓ | ✓ |
| Return to base (dock) | ✓ | ✓ |
| Battery level | ✓ | ✓ |
| Room selection | ✓ | ✓ |
| Fan speed (Silent / Standard / Medium / Turbo) | ✓ | ✓ |
| Cleaning mode (Vacuum / Vacuum and Mop / Mop) | ✓ | ✓ |
| Mop water level (Low / Medium / High) | ✓ | ✓ |
| Live floor plan map | ✓ | — |
| Custom Lovelace card with room selection UI | ✓ | — |

State updates arrive within ~2 s via MQTT push; a 30 s polling fallback runs when the push channel is silent.

---

## Requirements

- Home Assistant 2026.1.3 or newer.
- A Kärcher Home Robots app account (EU, US, or CN region). Cloud sessions expire silently; the integration will re-login automatically with the saved email and password when that happens.
- 2.4 GHz Wi-Fi reachable by the vacuum (the firmware does not join 5 GHz networks).
- For Apple Home: [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub).

---

## Installation

### HACS (recommended)

1. In Home Assistant, go to **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/vosadci/karcher-rcv5-ha` as an **Integration**.
3. Search for **Kärcher Home Robots** in HACS and install it.
4. Restart Home Assistant.

### Manual

Copy `custom_components/karcher_home_robots/` into your Home Assistant config directory and restart:

```bash
cp -r custom_components/karcher_home_robots /config/custom_components/
```

---

## Setup

After restarting Home Assistant, go to **Settings → Devices & Services → Add Integration → Kärcher Home Robots** and follow the steps:

1. **Region** — EU, US, or CN.
2. **Email and password** — your Kärcher Home Robots app credentials.
3. **Device** — pick your RCV5 (skipped if only one device is on the account).

The integration authenticates, subscribes to MQTT push updates, and creates all entities automatically.

---

## Entities

| Entity | Description |
|---|---|
| `vacuum.<name>` | Main vacuum — start, pause, stop, return to base, fan speed, locate |
| `sensor.<name>_battery` | Battery level (%) |
| `sensor.<name>_cleaning_area` | Area cleaned in current session (m²) |
| `sensor.<name>_cleaning_time` | Duration of current cleaning session (min) |
| `sensor.<name>_current_room` | Name of the room the robot is currently in |
| `binary_sensor.<name>_error` | On when the robot reports a fault |
| `select.<name>_room` | Room to clean — "All rooms" or a specific room |
| `select.<name>_cleaning_mode` | Vacuum / Vacuum and Mop / Mop |
| `select.<name>_water_level` | Mop water level: Low / Medium / High |
| `sensor.<name>_main_brush` | Main brush remaining life (%) |
| `sensor.<name>_side_brush` | Side brush remaining life (%) |
| `sensor.<name>_hypa` | HEPA filter remaining life (%) |
| `sensor.<name>_mop_life` | Mop pad remaining life (%) |

Entity IDs use the device nickname from the Kärcher app.

**Room selection.** Rooms are fetched from the robot's stored map at startup. Select a room then press Start to clean only that room. Select "All rooms" to clean everything.

**Cleaning mode and water level.** Set before or during cleaning. Water level only has effect when the mop attachment is physically installed. Fan speed is unavailable in Mop-only mode.

**Multiple robots.** Each robot is a separate config entry. Run **Add Integration** once per robot. If the robots share an account, log in with the same credentials and pick a different device each time.

**Diagnostics.** Settings → Devices & Services → Kärcher Home Robots → ⋮ → Download diagnostics. Output is automatically redacted of credentials, tokens, and serials.

---

## Apple Home via Matter

Apple Home support requires [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) (HAMH) **v2.0.38 or newer** and **iOS/tvOS 18.4 or newer**. See the HAMH docs for installation.

### Create the bridge (one-time)

In the HAMH web UI, create a new bridge:

1. **Name:** anything (e.g. `Kärcher RCV5`).
2. **Server Mode:** enabled.
3. **Entity filter:** add your vacuum entity (e.g. `vacuum.karcher_rcv5`).
4. Click the vacuum entity row → set **Matter Device Type** to **Robot Vacuum Cleaner**.
5. Set **Cleaning Mode Entity** → `select.<name>_cleaning_mode`.
6. Set **Mop Intensity Entity** → `select.<name>_water_level`.
7. Set **Current Room Entity** → `sensor.<name>_current_room`.

### Pair with Apple Home (one-time)

HAMH displays a Matter QR code. Open the **Home app → Add Accessory → More Options** and scan it.

### What appears in Apple Home

- Start / Stop / Return to Base
- Battery percentage
- Room picker — select one or more rooms before pressing Start
- Fan speed: Quiet / Automatic / Max
- Cleaning type: Vacuum / Mop / Vacuum and Mop
- Mop intensity: Quiet / Automatic / Max (when mop mode is active)
- Per-room progress rings (requires iOS 18.4+): each selected room shows a spinner while being cleaned, then a filled ring when complete

### How per-room progress rings work

Apple Home uses the Matter ServiceArea cluster, not numeric percentages. Each room shows one of four states:

- **Empty ring** — Pending (queued but not started)
- **Spinning ring** — Operating (currently being cleaned)
- **Filled ring** — Completed

The `Current Room Entity` sensor tells HAMH which room the robot is in so it can advance the correct ring in real time. Without it, all rings stay pending until the robot docks.

---

## Security and privacy

The RCV5 has no local API and the broker certificate is pinned, so cloud control is the only option. The integration:

- Pins TLS to the bundled 3iRobotix CA; it does not fall back to the system trust store.
- Never logs credentials, tokens, serials, or wire payloads above the `DEBUG` level.
- Sends no telemetry to anyone other than the vendor cloud the robot itself talks to.

To report a vulnerability privately, see [SECURITY.md](.github/SECURITY.md).

---

## Lovelace card

The integration includes a custom map card that renders the floor plan, lets you tap rooms to select them, and provides control buttons — all in one tile.

### Register the resource (one-time)

Go to **Settings → Dashboards → ⋮ → Resources → Add resource**:

| Field | Value |
|---|---|
| URL | `/karcher_home_robots/static/karcher-vacuum-card.js` |
| Resource type | JavaScript Module |

Reload the browser tab after saving.

### Add to a dashboard

In the Lovelace dashboard editor, add a **Manual** card with this YAML:

```yaml
type: custom:karcher-vacuum-card
vacuum_entity: vacuum.karcher_rcv5
battery_entity: sensor.karcher_rcv5_battery
map_entity: image.karcher_rcv5_map
current_room_entity: sensor.karcher_rcv5_current_room  # optional
cleaning_time_entity: sensor.karcher_rcv5_cleaning_time  # optional
cleaning_area_entity: sensor.karcher_rcv5_cleaning_area  # optional
cleaning_mode_entity: select.karcher_rcv5_cleaning_mode  # optional
```

Replace entity names with your actual entity IDs (use the device name as shown in HA).

### What the card does

- Renders the live map PNG; refreshes automatically when the map updates.
- Overlays room areas. **Tap a room** to select it (highlights yellow); tap again to deselect. Multiple rooms can be selected simultaneously.
- **Start** sends a room-specific clean command for selected rooms, or cleans all rooms if none are selected.
- Shows current status, battery level, current room while cleaning, cleaning time and area.
- Fan speed and cleaning mode selectors (fan speed is hidden in Mop-only mode).
- Error banner when the robot reports a fault.

---

## Troubleshooting

- **Login fails with the right password.** Check the region — accounts are region-bound; an EU account will not authenticate against the US endpoint.
- **`Reauthentication required` in HA.** This means the persisted password no longer works (changed in the Kärcher app, account locked, etc.). The integration handles short-term token expiry transparently — you only see the prompt when the credentials themselves are bad. Open Settings → Devices & Services → Kärcher Home Robots → Reauthenticate. Region and device selection are preserved; only the password is collected.
- **Entities go unavailable.** The cloud is unreachable. The integration recovers automatically on reconnect; no user action is required. After **1 hour** of continuous unavailability, a `repair` issue surfaces in HA explaining the outage; this is usually a 3iRobotix vendor outage rather than your network. The repair dismisses itself on the next successful poll.
- **Rooms list is empty.** Run a full cleaning cycle once to make the robot build and upload its map; the room list appears on the next reconnect.

For deeper troubleshooting, attach the diagnostics download (above) to your issue.

---

## For contributors

- [ARCHITECTURE.md](ARCHITECTURE.md) — module map, layer rules, error taxonomy, private-API allowlist.
- [ROADMAP.md](ROADMAP.md) — what's done and what's next.
- [CLAUDE.md](CLAUDE.md) — development commands, hard constraints, collaboration rules.

---

## Acknowledgements

- [`karcher-home`](https://github.com/lafriks/karcher-home) by [@lafriks](https://github.com/lafriks) — the underlying cloud-protocol library.
- [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) by [@RiDDiX](https://github.com/RiDDiX) — Apple Home bridge.

---

## Licence

MIT — see [LICENSE](LICENSE).

Unaffiliated with Kärcher SE & Co. KG or 3iRobotix Co., Ltd. Trademarks belong to their respective owners.
