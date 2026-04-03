# Kärcher RCV5 — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Tests](https://github.com/vosadci/karcher-rcv5-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/vosadci/karcher-rcv5-ha/actions/workflows/tests.yml)

> **Personal project** — This is an unofficial, community-built integration. It is not affiliated with or endorsed by Kärcher. It may have bugs, break with cloud updates, or cause unexpected behaviour. Use at your own risk.

A custom [Home Assistant](https://www.home-assistant.io/) integration for the **Kärcher RCV5** robot vacuum, with full **Apple Home support via Matter**.

The Kärcher RCV5 uses the **3irobotix** cloud platform. There is no official Home Assistant integration and no local control API. This integration reverse-engineers the cloud protocol (MQTT + REST) to provide real-time control and state updates, and bridges the robot into Apple Home via Matter using [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub).

> Full protocol documentation — all captured MQTT commands, state fields, local control investigation — is in [PROTOCOL.md](PROTOCOL.md).

---

## What you get

| Feature | Home Assistant | Apple Home |
|---|---|---|
| Start / Pause / Stop | ✓ | ✓ |
| Return to base (dock) | ✓ | ✓ |
| Battery level | ✓ | ✓ |
| Room selection | ✓ | ✓ |
| Fan speed (Silent / Standard / Medium / Turbo) | ✓ | ✓ |
| Cleaning mode (Vacuum / Vacuum & Mop / Mop) | ✓ | ✓ |
| Mop water level (Low / Medium / High) | ✓ | ✓ |

State updates arrive within ~2 seconds via MQTT push. A 30-second polling fallback is used if MQTT is unavailable.

---

## Installation

### Option A — HACS (recommended)

1. In Home Assistant, go to **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/vosadci/karcher-rcv5-ha` as an **Integration**
3. Search for **Kärcher** in HACS and install it
4. Restart Home Assistant

### Option B — Manual

Copy `custom_components/karcher_home_robots/` into your HA config directory and restart:

```bash
cp -r custom_components/karcher_home_robots /config/custom_components/
```

---

## Configuration

After restarting HA, go to **Settings → Integrations → Add Integration → Kärcher Home Robots** and follow the steps:

1. **Region** — EU, US, or CN
2. **Email and password** — your Kärcher Home Robots app credentials
3. **Device** — select your RCV5 (skipped if only one device is on the account)
4. **HAMH URL** *(optional)* — if you use Home Assistant Matter Hub, enter its URL (e.g. `http://192.168.1.10:8482`). The bridge is created automatically. Leave blank to skip and configure later.

That's it. The integration connects, subscribes to MQTT push updates, and creates all entities automatically.

---

## Entities

| Entity | Description |
|---|---|
| `vacuum.<name>` | Main vacuum — start, pause, stop, return to base, fan speed |
| `sensor.<name>_battery` | Battery level (%) |
| `sensor.<name>_cleaning_area` | Area cleaned in current session (m²) |
| `sensor.<name>_cleaning_time` | Duration of current cleaning session (s) |
| `binary_sensor.<name>_error` | On when the robot reports a fault |
| `select.<name>_room` | Room to clean — "All rooms" or a specific room |
| `select.<name>_cleaning_mode` | Vacuum / Vacuum & Mop / Mop |
| `select.<name>_water_level` | Mop water level: Low / Medium / High |

Entity IDs use the device nickname from the Kärcher app.

**Multiple robots:** Each robot is set up as a separate config entry. Run **Add Integration** once per robot. If the robots share the same account, log in with the same credentials and pick a different device each time. If they are on different accounts, log in with different credentials. The same robot cannot be added twice (duplicate prevention is built in).

**Room selection:** Rooms are fetched from the robot's stored map at startup. Select a room then press Start to clean only that room. Select "All rooms" to clean everything.

**Cleaning mode and water level:** Set before or during cleaning. Water level only has effect when the mop attachment is physically installed.

---

## Apple Home via Matter

Apple Home support requires [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) (HAMH), which bridges HA entities to Matter. This is a one-time setup.

### 1. Deploy HAMH (one-time)

**Option A — HA OS add-on (recommended for HA OS users)**

1. Go to **Settings → Add-ons → Add-on Store**
2. Search for **Home Assistant Matter Hub** and install it
3. Start it and enable **Start on boot** and **Watchdog**
4. The default port is **8482** — use `http://<ha-ip>:8482` as the HAMH URL

**Option B — Docker**

```yaml
# docker-compose.yml
services:
  ha-matter-hub:
    image: ghcr.io/riddix/home-assistant-matter-hub:latest
    network_mode: host
    environment:
      HAMH_HOME_ASSISTANT_URL: "http://<ha-ip>:8123"
      HAMH_HOME_ASSISTANT_ACCESS_TOKEN: "<long-lived-token>"
      HAMH_STORAGE_LOCATION: "/data"
    volumes:
      - ./data:/data
```

> **Synology NAS:** Container Manager cannot restart `network_mode: host` containers via the UI. Add this to `configuration.yaml` to restart from HA instead:
> ```yaml
> shell_command:
>   restart_matter_hub: "docker restart ha-matter-hub"
> ```

### 2. Enter HAMH URL during integration setup (one-time)

When adding the integration, the last step asks for your HAMH URL (e.g. `http://192.168.1.10:8482`). This is optional — leave it blank to skip and enter it later via **Settings → Integrations → Kärcher Home Robots → Configure**.

### 3. Press "Configure HAMH Bridge" (one-time)

On your Kärcher device card (**Settings → Devices → Kärcher RCV5**), press the **Configure HAMH Bridge** button. This automatically:
- Creates a server-mode bridge named "Kärcher RCV5" filtered to your vacuum
- Configures cleaning mode and mop intensity entity mappings

The button is idempotent — pressing it again updates the bridge safely (e.g. after reinstalling HAMH).

> **Manual fallback:** If you prefer to configure HAMH by hand, open the web UI at `http://<host>:8482` and create a bridge with **Domain filter:** `vacuum`, **Server Mode:** enabled. Then add `cleaningModeEntity` = `select.<name>_cleaning_mode` and `mopIntensityEntity` = `select.<name>_water_level` via Entity Mappings.

### 4. Pair with Apple Home (one-time)

In the HAMH web UI, a Matter QR code is shown. Open the **Home app → Add Accessory → More Options** and scan it.

### What appears in Apple Home

- Start / Stop / Return to Base
- Battery percentage
- Room picker
- Fan speed: Quiet / Automatic / Max
- Cleaning type: Vacuum / Mop / Vacuum & Mop
- Mop intensity: Quiet / Automatic / Max (when mop mode is active)
- Cleaning area (m²) — if added to the bridge
- Cleaning time (s) — if added to the bridge
- Fault indicator — if `binary_sensor.<name>_error` is added to the bridge

---

## How it works

- Authenticates with the Kärcher/3irobotix cloud using your app credentials
- Subscribes to MQTT push updates for real-time state (battery, work mode, errors)
- Sends commands (start, stop, fan speed, cleaning mode, water level) as MQTT PUBLISH messages
- Room layout is fetched from the stored map at startup

---

## Technical notes

- **Protocol:** 3irobotix cloud, tenant `1528983614213726208`. REST: `eu-appaiot.3irobotix.net`. MQTT: `eu-gamqttaiot.3irobotix.net:8883` (TLS 1.2)
- **Library:** [`karcher-home`](https://pypi.org/project/karcher-home/) — two bugs are worked around in `api.py` (stale property cache; ignored MQTT push payloads)
- See [PROTOCOL.md](PROTOCOL.md) for the full protocol reference

## Testing

```bash
make install   # install test dependencies (one-time)
make test      # run all 77 automated tests
make test-cov  # run tests with coverage report (currently 82%)
```

The automated suite uses `pytest-homeassistant-custom-component` with a real (in-memory) HA instance. It covers the config flow, integration setup/teardown, coordinator polling and MQTT push, all vacuum commands, the battery sensor, and all three select entities.

A full manual test matrix (device states, commands, fan speed, cleaning mode, Apple Home, resilience, reauth) is in [tests/README.md](tests/README.md).

---

## Local control

Currently **not possible** — no open TCP ports, certificate pinning blocks MQTT interception, firmware is encrypted. See [PROTOCOL.md §9](PROTOCOL.md) for details.

---

## Acknowledgements

- [`karcher-home`](https://github.com/lafriks/python-karcher) by [@lafriks](https://github.com/lafriks)
- [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) by [@RiDDiX](https://github.com/RiDDiX)
