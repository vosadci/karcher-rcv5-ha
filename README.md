# Kärcher RCV5 — Home Assistant Integration

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

## How it works

1. On startup the integration authenticates with the Kärcher cloud (3irobotix EU endpoint) using your app credentials.
2. It subscribes to the robot's MQTT topics to receive real-time property updates (state, battery, mode, etc.).
3. Commands (start, stop, fan speed, cleaning mode, etc.) are sent as MQTT PUBLISH messages to the cloud broker, which relays them to the robot.
4. Room layout is fetched from the stored map protobuf once at startup.
5. The integration exposes a standard HA `vacuum` entity plus `sensor`, and `select` entities — which Home Assistant Matter Hub then bridges to Apple Home as a Matter `RoboticVacuumCleaner` device.

---

## Requirements

- Home Assistant 2025.x or later
- [`karcher-home`](https://pypi.org/project/karcher-home/) ≥ 0.5.1 — installed automatically from PyPI
- A **Kärcher Home Robots** account with the RCV5 registered in the app
- For Apple Home: [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) running as a Docker container

---

## Installation

### 1. Copy the integration

Copy `custom_components/karcher/` into your HA configuration directory:

```
/config/custom_components/karcher/
```

If you're running HA in Docker on a Synology NAS (like this setup), the config directory is typically `/docker/homeassistant/`:

```bash
cp -r custom_components/karcher /docker/homeassistant/custom_components/
```

### 2. Restart Home Assistant

### 3. Add the integration

Go to **Settings → Integrations → Add Integration**, search for **Kärcher Home Robots**, and complete the three-step setup flow:

1. **Region** — select EU, US, or CN (determines which cloud endpoint to use)
2. **Credentials** — enter your Kärcher Home Robots app email and password
3. **Device** — select your RCV5 (skipped automatically if you only have one device)

Your credentials are stored in the config entry so the integration can re-authenticate when tokens expire.

---

## Entities

After setup, the following entities are created (entity IDs use the device nickname set in the app):

| Entity | Description |
|---|---|
| `vacuum.<name>` | Main vacuum — start, pause, stop, return to base, fan speed |
| `sensor.<name>_battery` | Battery level (%) |
| `select.<name>_room` | Room to clean next — "All rooms" or a specific room name |
| `select.<name>_cleaning_mode` | Cleaning type: Vacuum / Vacuum & Mop / Mop |
| `select.<name>_water_level` | Mop water level: Low / Medium / High |

**Room selection:** Rooms are loaded from the robot's stored map at startup. Select a room from `select.<name>_room`, then press Start — the robot cleans only that room. Select "All rooms" to clean everything. Room selection also works directly from Apple Home.

**Cleaning mode and water level:** These are independent of the Start command — set them before or during cleaning. Water level only has effect when the mop attachment is physically installed.

---

## Apple Home via Matter

Apple Home support requires [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) (HAMH), a separate Docker container that bridges HA entities to Matter devices.

### Step 1 — Deploy Home Assistant Matter Hub

```yaml
# docker-compose.yml
services:
  ha-matter-hub:
    image: ghcr.io/riddix/home-assistant-matter-hub:latest
    network_mode: host          # required for mDNS multicast
    environment:
      HAMH_HOME_ASSISTANT_URL: "http://<ha-ip>:8123"
      HAMH_HOME_ASSISTANT_ACCESS_TOKEN: "<long-lived-token>"
      HAMH_STORAGE_LOCATION: "/data"
    volumes:
      - ./data:/data
```

> **Synology NAS:** Container Manager cannot stop/restart `network_mode: host` containers via its UI. Add a shell command to HA so you can restart the container from Developer Tools:
> ```yaml
> # configuration.yaml
> shell_command:
>   restart_matter_hub: "docker restart ha-matter-hub"
> ```

### Step 2 — Create a bridge

Open the HAMH web UI at `http://<host>:8482` and create a bridge:

- **Domain filter:** `vacuum`
- **Server Mode:** enabled (required — Apple Home rejects bridge mode for vacuum devices)

Then add the battery sensor as a separate entity filter:
- Entity ID: `sensor.<name>_battery`

### Step 3 — Configure cleaning mode and mop intensity

On the vacuum entity row in the bridge, click **Add Sub-Entry** and add:

| Key | Value |
|---|---|
| `cleaningModeEntity` | `select.<name>_cleaning_mode` |
| `mopIntensityEntity` | `select.<name>_water_level` |

### Step 4 — Pair with Apple Home

The HAMH web UI shows a Matter QR code. In the Home app: **Add Accessory → More Options → scan the QR code**.

### What Apple Home shows

- Vacuum tile with Start / Stop / Return to Base
- Battery percentage in the accessory detail view
- Room picker (Matter ServiceArea cluster)
- Fan speed: Quiet (Silent) / Automatic (Standard, Medium) / Max (Turbo)
- Cleaning type: Vacuum / Mop / Vacuum & Mop
- Mop intensity: Quiet (Low) / Automatic (Medium) / Max (High) — shown when mop mode is active

---

## Technical notes

- **Protocol:** 3irobotix cloud platform, tenant `1528983614213726208`. REST base: `eu-appaiot.3irobotix.net`. MQTT broker: `eu-gamqttaiot.3irobotix.net:8883` (TLS 1.2).
- **Commands** are sent as MQTT PUBLISH to `service_invoke` topics (version 3.0) or `property/set` topics (version 1.0 — used for fan speed, cleaning mode, water level).
- **Two bugs** in the `karcher-home` library are worked around in `api.py`: stale cached properties returned by `get_device_properties()` (fixed by a custom `fetch_properties()` that waits for a fresh reply), and MQTT push payloads on `thing/event/property/post` being silently ignored (fixed by patching `on_message`).
- See [PROTOCOL.md](PROTOCOL.md) for the full protocol reference.

## Local control

Local control is currently **blocked**:

- The robot has no open TCP ports (confirmed by nmap)
- DNS redirect + local MQTT broker is blocked by app-layer certificate pinning (`server.bks`)
- Firmware squashfs is encrypted by Rockchip TrustZone — extraction is not possible without physical UART access

See [PROTOCOL.md §9](PROTOCOL.md) for the full investigation.

---

## Acknowledgements

- [`karcher-home`](https://github.com/lafriks/python-karcher) by [@lafriks](https://github.com/lafriks) — Python client for the 3irobotix cloud API
- [Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) by [@RiDDiX](https://github.com/RiDDiX) — Matter bridge for HA entities
