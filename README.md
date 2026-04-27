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

State updates arrive within ~2 s via MQTT push; a 30 s polling fallback runs when the push channel is silent.

---

## Requirements

- Home Assistant 2025.1.0 or newer.
- A Kärcher Home Robots app account (EU, US, or CN region). Cloud sessions expire silently; the integration will surface a `Reauthentication required` repair when that happens.
- 2.4 GHz Wi-Fi reachable by the vacuum (the firmware does not join 5 GHz networks).
- For Apple Home: [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub).

> A dedicated Kärcher account for Home Assistant is **optional**. The 3iRobotix broker accepts the integration as an additional client alongside the mobile app, so a shared account works. If you experience the mobile app being signed out after Home Assistant connects, switch to a dedicated account and report it as a bug.

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
| `binary_sensor.<name>_error` | On when the robot reports a fault |
| `select.<name>_room` | Room to clean — "All rooms" or a specific room |
| `select.<name>_cleaning_mode` | Vacuum / Vacuum and Mop / Mop |
| `select.<name>_water_level` | Mop water level: Low / Medium / High |

Entity IDs use the device nickname from the Kärcher app.

**Room selection.** Rooms are fetched from the robot's stored map at startup. Select a room then press Start to clean only that room. Select "All rooms" to clean everything.

**Cleaning mode and water level.** Set before or during cleaning. Water level only has effect when the mop attachment is physically installed. Fan speed is unavailable in Mop-only mode.

**Multiple robots.** Each robot is a separate config entry. Run **Add Integration** once per robot. If the robots share an account, log in with the same credentials and pick a different device each time.

**Diagnostics.** Settings → Devices & Services → Kärcher Home Robots → ⋮ → Download diagnostics. Output is automatically redacted of credentials, tokens, and serials.

---

## Apple Home via Matter

Apple Home support requires [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) (HAMH). See the HAMH docs for installation.

### Create the bridge (one-time)

In the HAMH web UI, create a new bridge:

1. **Name:** anything (e.g. `Kärcher RCV5`).
2. **Server Mode:** enabled.
3. **Entity filter:** add your vacuum entity (e.g. `vacuum.karcher_rcv5`).
4. Click the vacuum entity row → set **Matter Device Type** to **Robot Vacuum Cleaner**.
5. Set **Cleaning Mode Entity** → `select.<name>_cleaning_mode`.
6. Set **Mop Intensity Entity** → `select.<name>_water_level`.

### Pair with Apple Home (one-time)

HAMH displays a Matter QR code. Open the **Home app → Add Accessory → More Options** and scan it.

### What appears in Apple Home

- Start / Stop / Return to Base
- Battery percentage
- Room picker
- Fan speed: Quiet / Automatic / Max
- Cleaning type: Vacuum / Mop / Vacuum and Mop
- Mop intensity: Quiet / Automatic / Max (when mop mode is active)

---

## Security and privacy

The RCV5 has no local API and the broker certificate is pinned, so cloud control is the only option. The integration:

- Pins TLS to the bundled 3iRobotix CA; it does not fall back to the system trust store.
- Never logs credentials, tokens, serials, or wire payloads above the `DEBUG` level.
- Sends no telemetry to anyone other than the vendor cloud the robot itself talks to.

To report a vulnerability privately, see [SECURITY.md](.github/SECURITY.md).

---

## Troubleshooting

- **Login fails with the right password.** Check the region — accounts are region-bound; an EU account will not authenticate against the US endpoint.
- **`Reauthentication required` in HA.** This means the persisted password no longer works (changed in the Kärcher app, account locked, etc.). The integration handles short-term token expiry transparently — you only see the prompt when the credentials themselves are bad. Open Settings → Devices & Services → Kärcher Home Robots → Reauthenticate. Region and device selection are preserved; only the password is collected.
- **Entities go unavailable.** The cloud is unreachable. The integration recovers automatically on reconnect; no user action is required. After **1 hour** of continuous unavailability, a `repair` issue surfaces in HA explaining the outage; this is usually a 3iRobotix vendor outage rather than your network. The repair dismisses itself on the next successful poll.
- **Rooms list is empty.** Run a full cleaning cycle once to make the robot build and upload its map; the room list appears on the next reconnect.

For deeper troubleshooting, attach the diagnostics download (above) to your issue.

---

## Acknowledgements

- [`karcher-home`](https://github.com/lafriks/karcher-home) by [@lafriks](https://github.com/lafriks) — the underlying cloud-protocol library.
- [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) by [@RiDDiX](https://github.com/RiDDiX) — Apple Home bridge.

---

## Licence

MIT — see [LICENSE](LICENSE).

Unaffiliated with Kärcher SE & Co. KG or 3iRobotix Co., Ltd. Trademarks belong to their respective owners.
