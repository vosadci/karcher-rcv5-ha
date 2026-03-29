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

Other regions follow the same pattern: `us-appaiot`, `sg-appaiot`, `ru-appaiot`.
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

### Cancel dock return / Stop (HA "stop" action)

Cancels an in-progress dock return and leaves the robot stationary on the floor.
The official app has no dedicated "stop during cleaning" — during cleaning the only
options are Pause and Return to dock. `stop_recharge` is the closest HA equivalent
for the `stop` service call.

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
| `0` | Inactive (internal — not user-selectable; set automatically when mode=Vacuum) |
| `1` | Low |
| `2` | Medium |
| `3` | High |

The HA integration exposes this as `select.karcher_water_level` with options Low/Medium/High.
Values 0–2 confirmed via traffic capture (2026-03-29); value 3 inferred from pattern.
`water=0` is sent by the app when switching away from mop mode — it is not shown in the app UI.

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
(`VacuumEntityFeature.FAN_SPEED`). The `api.set_property()` method handles
this topic/payload format.

---

### Notes on `set_room_clean` parameters

| Field | Observed values | Meaning |
|---|---|---|
| `room_ids` | `[]` or `[id]` | Empty = clean all rooms. One or more integer room IDs for selective room clean. |
| `ctrl_value` | `1` = start/resume, `2` = pause | |
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
| `charge_state` | int | `0` = not charging, non-zero = charging/docked. |
| `fault` | int | `0` = no fault. Non-zero values can coexist with normal operation (minor warnings). Only treat as Error state when `work_mode` is in the idle set and `status` ≠ 4. |
| `quantity` | int | Battery level, 0–100. |
| `wind` | int | Suction level (fan speed). Higher = stronger. |
| `water` | int | Water level (mop feature). `0` if not a mop model or no water. |
| `cleaning_time` | int | Seconds elapsed in current cleaning session. |
| `cleaning_area` | float | Area cleaned in current session (m²). |
| `current_map_id` | str/int | ID of the currently active map. |

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
custom_components/karcher/
├── __init__.py       — async_setup_entry, async_unload_entry
├── manifest.json     — requirements: karcher-home>=0.5.1, iot_class: cloud_push
├── config_flow.py    — 3-step: region → credentials → device picker
├── coordinator.py    — DataUpdateCoordinator + MQTT push bridge; rooms + selected_room_id
├── vacuum.py         — KarcherVacuum entity (StateVacuumEntity)
├── sensor.py         — KarcherBatterySensor (SensorDeviceClass.BATTERY)
├── select.py         — KarcherRoomSelect entity (room picker for selective cleaning)
├── api.py            — Async wrapper around KarcherHome; send_command; get_rooms
├── const.py          — DOMAIN, state sets, CMD_* dicts
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

### HA version compatibility notes (tested 2026-03-28, HA 2025.x / Python 3.14)

- **`VacuumActivity` enum** replaces the removed `STATE_CLEANING` / `STATE_DOCKED` / etc.
  string constants. Use `from homeassistant.components.vacuum import VacuumActivity` and
  implement the `activity` property (not `state`) on `StateVacuumEntity`.
- **Battery as a sensor** — `VacuumEntityFeature.BATTERY` and `battery_level` on the vacuum
  entity are deprecated (removed in HA 2026.8). Battery must be a separate `SensorEntity`
  with `SensorDeviceClass.BATTERY`, linked to the same device via shared `device_info`.
- **Dependency**: use `karcher-home>=0.5.1` (PyPI) in `manifest.json`, not the git URL —
  git-based requirements can fail in Docker HA where git may not be available.

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
`ConfigEntryAuthFailed`.

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
char[] charArray = "sc2021".toCharArray();
keyStore.load(inputStreamOpen, charArray);   // server.bks password: sc2021
```

And in `SSLClient.initMqttSslSingleBKS()` (alternate path that loads both):
```java
char[] charArray2 = "hj2WtyHYYEvBTxDb".toCharArray();
keyStore2.load(inputStreamOpen2, charArray2);  // iot_dev.p12 password: hj2WtyHYYEvBTxDb
```

There is also a `"sc2018"` password used in a fallback error branch — not needed for extraction.

#### 5d. Extract the trusted cert from server.bks

BKS format requires the BouncyCastle provider. Use `pyjks`:

```bash
pip install pyjks
python3 - << 'EOF'
import jks, subprocess

ks = jks.bks.BksKeyStore.load("assets/server.bks", "sc2021")
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

Both should produce the same MD5. Confirmed: `2677dc36c9b4507b25a37c1196e814d9`.

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
  -passin pass:hj2WtyHYYEvBTxDb -nokeys -out iot_dev_cert.pem

# Extract private key (no passphrase on output):
openssl pkcs12 -legacy -in assets/iot_dev.p12 \
  -passin pass:hj2WtyHYYEvBTxDb -nocerts -nodes -out iot_dev_key.pem

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
# → 0bcdea0cba694140b0aa357333272521  (different from server.bks: 2677dc36...)
```

This cert + key is used for REST API mutual TLS authentication. It is **not** the MQTT
broker cert and its private key cannot be used to impersonate the broker.

### Conclusion

The robot performs application-layer certificate pinning against the specific
`*.3irobotix.net` cert stored in `server.bks`. Without the private key for that cert
(which is not present anywhere in the APK), local MQTT broker impersonation is not
possible without modifying the robot's firmware.

### Paths to local control

1. **UART serial console** *(most reliable)*
   The robot runs Linux on a Rockchip RV1126/RV1109 SoC.
   UART test pads are typically available on the PCB (115200 baud, 3.3V).
   With root shell access:
   - Replace `/etc/ssl/certs/` or the app-specific cert store with our CA cert, OR
   - Edit the MQTT client config to point to the local broker and skip cert verification, OR
   - Patch the MQTT client binary (`strings`/`sed` on the cert validation flag).

2. **OTA firmware extraction** *(investigated — blocked by encryption)*

   The OTA endpoint returns a firmware URL. Correct request parameters (confirmed 2026-03-28):
   ```python
   POST /upgrade-service/firmware/tryUpgrade
   {
     "productId":        dev.product_id.value,      # "1540149850806333440"
     "productModelCode": dev.product_mode_code,     # "Kaercher.KaercherRCV5Es"
     "curVersionCode":   "0",                       # 0 = always return latest
     "packageType":      "host_fw",                 # from RobotUpgradeActivity.java
     "username":         dev.sn,                    # device serial number
     "phoneBrand":       "android",
   }
   ```
   Response (truncated): firmware version `I3.12.26` (version code 26), 109 MB `.img` file at
   `https://eu-cdnallaiot.3irobotix.net/prod/app-manage/20221216/3irobotix_CRL350_Dual_Laser_AI_Factory-rv1126-linux-ota-I3.12.26-...img`

   The `.img` is a **Rockchip RKFW** update image. Format:
   - Starts with `RKFW` magic; embedded `RKAF` package at offset 0x3D9B4
   - Contains partitions: `MiniLoaderAll.bin` (250 KB), `parameter.txt`, `boot.img` (7 MB), `rootfs.img` (97 MB)
   - `rootfs.img` is a **squashfs 4.0 filesystem** (XZ compression), magic `hsqs` at offset 0x7B49B4

   **The squashfs blocks are encrypted.** All metadata (inode table, directory table) and
   data blocks contain cryptographically random bytes. The squashfs superblock is plaintext
   and internally consistent, but the decryption key is stored in the Rockchip RV1126 TrustZone
   (secure world) and is not accessible from the OTA image.

   `unsquashfs` fails with: `read_block: failed to read block @0x4f8f4e5891dd93e4`
   (garbage pointer from the encrypted id_table section).

   This path is **blocked** without UART console access to the running device.

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
2. Probing 14 candidate REST endpoints (`tools/probe_rest_commands.py`) returned 404 for all
   except `/smart-home-service/smartHome/device/property/set`, which returned error 892
   (signature mismatch due to the list-serialisation bug in python-karcher).
3. MQTT wildcard subscription confirmed commands appear directly on MQTT topics.

**Commands go exclusively via MQTT PUBLISH from the app to the cloud broker.**
The cloud broker forwards them to the robot's MQTT subscription.

---

## 12. Apple Home Integration via Matter

The HA integration can be exposed to Apple Home as a native **Matter RoboticVacuumCleaner**
device (type 0x0074) using the
[Home Assistant Matter Hub](https://github.com/RiDDiX/home-assistant-matter-hub) project.
No changes to `custom_components/karcher/` are needed.

### Why not the built-in HA Matter component

HA's built-in `matter` component is a **Matter controller only** — it pairs with Matter devices
already on your network. It does not bridge HA entities outward into Matter. A separate
bridging process is required.

### Why not the HomeKit Bridge

The native HA HomeKit bridge (`homekit` integration) can expose vacuums, but as a HomeKit
accessory (HAP protocol), not as a Matter device. Apple Home accepts both, but the
Matter path provides a proper `RoboticVacuumCleaner` tile with native start/stop/state
rather than a generic switch approximation.

### Deployment (Docker, no HA Supervisor)

HA running as a plain Docker container does **not** have the HA Supervisor or the Add-ons
system, so the Matter Hub cannot be installed as an add-on. It must run as a separate
Docker container.

**`docker-compose.yml`** (or Synology Container Manager):

```yaml
version: "3.8"
services:
  ha-matter-hub:
    image: ghcr.io/riddix/home-assistant-matter-hub:latest
    container_name: ha-matter-hub
    restart: unless-stopped
    network_mode: host          # required — Matter uses mDNS multicast (UDP)
    volumes:
      - /docker/ha-matter-hub:/data
    environment:
      - HAMH_HOME_ASSISTANT_URL=http://localhost:8123
      - HAMH_HOME_ASSISTANT_ACCESS_TOKEN=<long-lived-token>
      - HAMH_STORAGE_LOCATION=/data
```

`network_mode: host` is mandatory. Matter discovery uses mDNS (UDP multicast 224.0.0.251:5353)
which does not traverse Docker NAT. The Synology and iPhone must be on the same subnet/VLAN.

The web UI is served at `http://<synology-ip>:8482`.

**Note on Synology Container Manager**: the container may show "container does not exist"
in the UI when using `network_mode: host`. This is a UI quirk — the container runs
correctly and the web UI at port 8482 is accessible. Ignore the UI error.

### Bridge configuration

1. Open `http://<synology-ip>:8482`
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
startup). Since Synology Container Manager can't manage `network_mode: host` containers
via its UI, use a HA shell_command:
```yaml
# configuration.yaml
shell_command:
  restart_matter_hub: "docker restart ha-matter-hub"
```
Then call `shell_command.restart_matter_hub` from Developer Tools → Actions.

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

---

## 11. Robot Hardware Notes

- **SoC**: Rockchip RV1126 (Linux-based), board ID `rv1126-3irobotix-CRL350_RCV5_V1.0`, confirmed
  by firmware device tree strings and RKFW image
- **Firmware**: version `I3.12.26` (versionCode 26), released 2022-11-16; RKFW format (Rockchip update.img),
  `productModelCode = Kaercher.KaercherRCV5Es`
- **Connectivity**: Wi-Fi only (2.4 GHz), no Ethernet port
- **Local ports**: none open (pure MQTT client)
- **MQTT TLS**: TLSv1.2, ECDHE-RSA-AES256-GCM-SHA384, EC P-256 server cert
- **Cert pinning**: application-layer, against specific self-signed wildcard cert
