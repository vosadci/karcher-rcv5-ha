# Kärcher Home Robots — Constraints

> Consolidates every bound on the solution space: technology choices, deployment target, platform requirements, integration requirements, and external dependencies. Constraints are distinguished from requirements — a requirement says what the system must do; a constraint says what the system must work within, regardless of preference.
>
> **Hard constraint:** cannot be changed without changing the deployment target, the physical device, or a third-party system.
> **Soft constraint:** reflects a current decision that could in principle be revisited.

---

## 1. Physical Device

| Constraint | Type | Detail |
|---|---|---|
| Wi-Fi 2.4 GHz only | Hard | IEEE 802.11b/g/n; 5 GHz not supported by hardware |
| No open TCP ports | Hard | Confirmed by nmap; robot opens no inbound services |
| No local control API | Hard | Robot is a pure MQTT client; there is no REST, WebSocket, or UDP local interface |
| Certificate pinning | Hard | Robot verifies MQTT broker cert against `server.bks` at application layer after TLS; DNS redirect alone is not sufficient for local broker substitution |
| Encrypted firmware | Hard | squashfs rootfs is AES-encrypted with a Rockchip RV1126 TrustZone key; OTA images cannot be extracted or modified without UART console access |
| Single robot per MQTT session | Hard | Each physical robot has one MQTT connection to the 3iRobotix broker; the integration connects as an additional app client, not in place of one |

---

## 2. Cloud Platform (3iRobotix)

| Constraint | Type | Detail |
|---|---|---|
| All control is MQTT | Hard | Confirmed: no REST command endpoints exist (exhaustive probe). Commands go exclusively via MQTT PUBLISH from client to broker to robot |
| MQTT broker: 3iRobotix | Hard | `eu-gamqttaiot.3irobotix.net:8883` (EU); US and CN regions have equivalent endpoints |
| TLS 1.2 required | Hard | Broker accepts only TLS 1.2; cipher ECDHE-RSA-AES256-GCM-SHA384 |
| Self-signed server cert | Hard | `*.3irobotix.net`, issued by 3iRobotix CA; not from a public CA; cannot be verified by a standard trust store |
| REST API for auth only | Hard | Authentication, device list, and map data go via REST; no other REST paths are relevant to integration operation |
| REST signing: MD5 | Hard | `MD5(auth_token + timestamp + nonce + body_string)`; required by platform; cannot be changed |
| Tenant ID hardcoded | Hard | `1528983614213726208`; embedded in all MQTT payloads and REST headers; client-side routing metadata |
| No token refresh mechanism | Hard | Auth tokens expire; the library provides no refresh endpoint; email + password must be stored to re-authenticate |
| OTA check on every connection | Hard | Robot hits `ota.3irobotix.net:8001` on every MQTT connection; a stub response is required if running a fake cloud |
| MQTT QoS 0 | Hard | All device command messages use QoS 0 (fire-and-forget); no delivery acknowledgement; no automatic retry |
| map data available via REST | Hard | Floor plan and room list are available via `get_map_data()` REST call; protobuf (`RobotMap`) format |

---

## 3. python-karcher Library

| Constraint | Type | Detail |
|---|---|---|
| Required dependency | Hard | No alternative library exists; the integration cannot function without it |
| Version pin: `>=0.5.1,<1.0.0` | Soft | Lower bound: first version with the features relied upon. Upper bound: protects against a hypothetical breaking 1.x release. Can be revised when 1.x is released and tested |
| PyPI package only | Hard | The HA OS host environment does not have git available; `git+https://` requirements fail silently. Must use the PyPI release |
| Blocking calls | Hard | All library calls are synchronous blocking; must be dispatched via `run_in_executor` in HA |
| paho-mqtt foreign thread | Hard | Library uses paho-mqtt in a background thread; `on_message` callbacks run outside the HA event loop; all state mutations must cross via `hass.loop.call_soon_threadsafe` |
| Internal API access required | Hard | The library does not expose a sufficient public API; `_mqtt`, `_update_device_properties`, `_wait_for_topic`, `get_timestamp_ms`, `TENANT_ID` are accessed directly. These are private library internals documented as a boundary layer in `api.py` and `mqtt_adapter.py` |
| `net_stauts` typo bug | Hard | `DeviceProperties.net_stauts` (misspelled) causes `AttributeError` on every property update that includes nested objects; must be worked around by stripping nested props before calling `_update_device_properties` |
| `get_device_properties()` stale cache | Hard | Returns cached default `DeviceProperties` when already subscribed; must be worked around by always calling `request_device_update()` + waiting for `get_reply` topic |
| `thing/event/property/post` ignored | Hard | Library's `on_message` sets a wait-event for `property/post` but never calls `_update_device_properties` with the payload; real-time push updates require manual parsing and injection in the patched `on_message` handler |
| REST list serialisation bug | Hard | Library serialises list values using Python `str()` instead of JSON, producing sign mismatch (error 892); must pre-serialise list values via `json.dumps` before passing to the library |

---

## 4. Home Assistant Platform

| Constraint | Type | Detail |
|---|---|---|
| Minimum HA version: 2026.6.0 | Soft | Declared in `hacs.json`. Set to the version against which the integration was developed and tested. Can be lowered if tested on earlier versions |
| Python 3.13 | Soft | HA OS runs Python 3.13; type annotations and standard library usage must be compatible. No Python-version-specific APIs used that would break on 3.12+ |
| `VacuumActivity` enum | Hard | `STATE_*` string constants (`STATE_CLEANING`, `STATE_DOCKED`, etc.) are removed. `VacuumActivity` enum and `activity` property on `StateVacuumEntity` are required |
| Battery as separate `SensorEntity` | Hard | `VacuumEntityFeature.BATTERY` and `battery_level` on the vacuum entity are removed in HA 2026.8. Battery must be a separate `SensorEntity` with `SensorDeviceClass.BATTERY` |
| Non-blocking event loop | Hard | HA runs on a single asyncio event loop. Any blocking call (I/O, library call, sleep) must be dispatched via `hass.async_add_executor_job` or `loop.run_in_executor`. Blocking the event loop causes HA to become unresponsive |
| `DataUpdateCoordinator` pattern | Soft | The coordinator pattern is the standard HA mechanism for `cloud_push` integrations and is expected by HACS quality scale reviewers. An alternative (direct entity polling) would work technically but is non-standard |
| Config entry architecture | Hard | HA's integration loading model requires a `ConfigEntry` per device. Shared state across entries is not supported by the HA data model |
| `config_flow: true` required | Hard | Integrations without a config flow cannot be set up via the UI and cannot be listed on HACS |
| HACS packaging requirements | Hard | `manifest.json` must include `domain`, `version`, `documentation`, `issue_tracker`, `codeowners`, `config_flow`, `iot_class`, `requirements`. `hacs.json` must include `name` and `homeassistant` minimum version |

---

## 5. Apple Home / Matter

| Constraint | Type | Detail |
|---|---|---|
| Requires HA Matter Hub | Hard | HA's built-in Matter support bridges *inward* (Matter devices into HA). Bridging HA entities *outward* to Apple Home requires a separate bridge: [HA Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) |
| Rooms in Roborock format | Hard | HAMH's ServiceArea cluster implementation expects rooms as `{"id_as_string": "room_name"}`. The integration must expose rooms in this format on the vacuum entity's `extra_state_attributes` |
| `app_segment_clean` send_command | Hard | HAMH sends room-clean commands via `vacuum.send_command("app_segment_clean", [room_id])`. The integration must handle this command name and parameter format |
| Server Mode required | Hard | Apple Home requires the Matter bridge to operate in Server Mode (not Client Mode). Must be enabled in HAMH bridge configuration |
| Battery sensor separate entity filter | Hard | HAMH does not automatically discover battery sensors linked to a vacuum. The `sensor.<name>_battery` entity must be added explicitly as a separate entity filter in the HAMH bridge |

---

## 6. Development and Tooling

| Constraint | Type | Detail |
|---|---|---|
| Language: Python | Hard | Home Assistant custom integrations must be written in Python |
| Type annotations required | Soft | All public methods and module-level variables should be type-annotated. `mypy` is used for type checking in CI |
| Linter: ruff | Soft | `ruff check` and `ruff format --check` run in CI. Standard HA community tooling choice |
| Test framework: pytest | Soft | `pytest` with `pytest-homeassistant-custom-component`, `pytest-asyncio` (mode=auto), `pytest-cov` |
| Python for tools: local venv with `karcher-home` | Hard (local) | `karcher-home` is installed only in a dedicated dev environment; system `python3` does not have it. All `tools/*.py` scripts must be run with that interpreter. The exact path is machine-specific — see `.claude/CLAUDE.md` |
| No git-URL requirements | Hard | See §3: PyPI packages only in `manifest.json requirements` |
| Secrets not committed | Hard | `karcher-mqtt-certs/` is gitignored. `iot_dev.p12`, `server.bks`, and derived cert files are not committed. Passwords (`sc2021`, `hj2WtyHYYEvBTxDb`) appear only in `PROTOCOL.md` as research documentation |

---

## 7. Scope Constraints (What Is Out of Bounds)

These are not failures or gaps — they are explicit boundaries set before implementation began.

| Out of scope | Reason |
|---|---|
| Local control | All local control paths exhausted (DNS redirect, cert substitution, firmware extraction, nmap). UART console is the only remaining path and requires physical PCB access |
| Offline / cloud-independent operation | Structurally impossible without local control |
| Support for Kärcher models other than RCV5 | Untested; protocol may be similar but room/mode mappings, work_mode values, and feature availability are unverified |
| Replacing the Kärcher app | Credentials must still be created via the official app; account management (password change, device registration) is out of scope |
| Historical cleaning records | The 3iRobotix REST API does not expose historical session data in a form the integration can consume |
| OTA interception or blocking | The robot checks for OTA on every connection; the integration does not intercept, defer, or block firmware updates |
