# Kärcher RCV5 — Security & Architecture Investigation

> **Scope:** Kärcher's marketing claims, hardware design, firmware/software architecture, cloud infrastructure, security posture, data privacy, and legal/compliance analysis.
> **Method:** Traffic capture, APK static analysis, firmware analysis, official documentation review, and written correspondence with Kärcher's Data Protection Team.
> **Date:** March 2026
> **Disclaimer:** This document reflects independent technical research and personal analysis. It is not legal or professional advice. Factual claims are supported by referenced evidence; opinions and risk assessments are clearly identified as such.

---

## 1. Executive Summary

- Kärcher's "servers in Germany only" marketing claim **does not match Kärcher's own written statement** to us: their Data Protection Officer confirmed data is stored on AWS within the EEA, not Germany specifically
- The **entire product stack** — firmware, cloud infrastructure, app, and OTA updates — is authored and operated by **3iRobotix, a Chinese company** (Shenzhen)
- China's National Intelligence Law (2017, Art. 7) applies to 3iRobotix regardless of where data is stored, creating a structural compelled-cooperation risk that no contractual arrangement can neutralise
- The camera/video **on-device-only processing claim is unverifiable** — Kärcher does not control the firmware that governs camera behaviour
- Security posture is **reasonable for consumer IoT**: TLS 1.2 with certificate pinning on the device. Key weaknesses: shared client certificate embedded in the APK, MD5-based REST signing
- **Four questions put to Kärcher in writing remain unanswered** as of March 2026

---

## 2. Kärcher Marketing Claims vs. Verified Reality

| Claim | Source | Finding | Evidence |
|---|---|---|---|
| "Servers located in Germany only" | Kärcher website | **CONTRADICTED** — Kärcher's own DPO response describes EEA-wide (AWS) storage | Kärcher DPO response, Mar 2026 |
| "Entire data transfer runs via cloud to Germany-only servers" | Kärcher website | **CONTRADICTED** — same basis | Same |
| "Kärcher places great importance on data protection" | Kärcher website | **FORMALLY TRUE, STRUCTURALLY WEAK** — GDPR compliance in place; Chinese origin risks not disclosed | See §8–9 |
| "Regular updates improve security, constantly updated to match current specifications" | Kärcher website | **UNVERIFIABLE** — OTA authored and distributed entirely by 3iRobotix; no independent Kärcher audit documented | Open question |
| Camera/video processed on-device only, never uploaded | Privacy policy §4 | **UNVERIFIABLE** — firmware is 3iRobotix-controlled; any OTA update could alter this behaviour | Open question |

---

## 3. Hardware Architecture

### Sensors

| Sensor | Purpose |
|---|---|
| LiDAR (laser radar) | 2D room mapping and navigation. IEC 60825-1:2014 Class 1 — not hazardous to human body |
| 3D sensor with camera | AI-powered obstacle avoidance, object recognition, room type detection |
| Ultrasound sensor | Carpet detection — device avoids carpets during wet/combo cleaning |
| Fall sensors (×4) | Detects stairs and drops. Monthly cleaning required |
| Collision sensors | Physical obstacle impact detection |

### Connectivity

- **Wi-Fi:** IEEE 802.11b/g/n, **2.4 GHz only** (5 GHz explicitly not supported)
- Frequency range: 2400–2483.5 MHz
- Max signal strength: <20 dBm | Max EIRP: 100 mW
- EU Declaration of Conformity: Directive **2014/53/EU** (Radio Equipment Directive)
- UK Declaration of Conformity: **S.I. 2017/1206**
- Full text: www.kaercher.com/RCV5

### Power

- Battery: 14.4V Li-Ion, 5200 mAh nominal / 4800 mAh rated
- Nominal power: 36W | Charger input: 100–240V AC, 0.8A
- Runtime: ~120 min per full charge

### SoC (from firmware analysis)

- **Rockchip RV1126** (ARM-based, Linux)
- Board ID: `rv1126-3irobotix-CRL350_RCV5_V1.0`
- Firmware version: I3.12.26 (versionCode 26, released 2022-11-16) — the **factory baseline**
  image, not the shipping version. A live RCV5 runs `I3.12.90` (latest, confirmed 2026-08-04).

### Physical

- Dust container: 330 ml | Water reservoir: 240 ml

---

## 4. Firmware & Software Architecture

### Firmware format

- Container format: **Rockchip RKFW** (magic `RKFW`)
- RKAF package embedded at offset 0x3D9B4
- Partitions: MiniLoaderAll.bin, parameter.txt, boot.img, rootfs.img
- rootfs.img: **UBI image (256 KiB PEBs) wrapping a SquashFS 4.0 (XZ), NOT encrypted**
- Extractable **offline from the OTA image** — strip UBI (`ubireader_extract_images`),
  then `unsquashfs` → 2,439 cleartext files (Buildroot 2018.02). No hardware access needed.
  `/etc/shadow`'s root hash cracks to a working password (redacted — see `ROOTING.md §2`);
  `getty` on `ttyFIQ0` is enabled.
- No *documented* hardware debug access point, but the firmware ships an always-on serial
  console and OpenSSH/ADB gated behind a `/userdata/debug_mode` flag (`ROOTING.md §2`)

### OTA update mechanism

- Check endpoint: `https://ota.3irobotix.net:8001/service-publish/open/upgrade/try_upgrade`
- Checked on every cloud connection: productId, model code, current versionCode, device SN
- Firmware served from CDN: `eu-cdnallaiot.3irobotix.net` (also observed: `eu-cdndevaiot.3irobotix.net` — see §6d)
- **Updates authored, signed, and distributed entirely by 3iRobotix. No independent Kärcher audit is documented.**

### On-device process architecture (from `/oem/bin` binary analysis)

- `RobotApp` — robot brain on 3iRobotix's **`everest`** C++ framework; SLAM is **Google
  Cartographer** (`map_builder`/`trajectory_builder_2d/3d`/`sparse_pose_graph` `.lua`);
  task primitives include `LocalClean`, `CustomClean`, `GoDock`, `CollectDust`,
  `Exploration`, `ManualClean`.
- `everest-server` — internal message bus over **nanomsg** (`nn_bind`); carries map/task
  messages (`QueryDeviceMapBinData`, `DeviceCleanMapBinDataReport`).
- `aiot_client.bin` — the **cloud bridge**: **paho-mqtt.c over mbedTLS**; the only process
  that talks to the 3iRobotix broker. Verifies the broker cert against
  `/userdata/config/server.crt` (a file on the writable partition).
- `AuxCtrl` (motor/sensor MCU link), `Ai-server` (obstacle AI/camera), `upgrade` (OTA),
  `log-server` (log upload), `wifiManager`, `Monitor`, `watchdog`.

There is no local broker or local listener — control is *outbound* MQTT only. The paths to
cloud-free operation this architecture allows are documented in `LOCAL_CONTROL.md`.

### Camera pipeline & video capability (firmware analysis, I3.12.90 rootfs)

This addresses the question the app-layer analysis cannot: does the **firmware** have any
means to send camera video off-device? Findings are from the extracted `I3.12.90` root
filesystem — binary linkage (`DT_NEEDED`) and string analysis.

**The SoC is a camera-streaming platform.** The Rockchip RV1126 (§3) is a purpose-built
AI-vision / IP-camera SoC: MIPI-CSI camera inputs, a hardware ISP, a **hardware H.264/H.265
video encoder**, and an NPU. It is the same class of chip used in networked security cameras.

**The camera is actively captured on-device today.** `Ai-server` opens the camera
(`/dev/video14`) and links the ISP, 2D-scaler (RGA), NPU runtime, and OpenCV — a
computer-vision inference pipeline. It notably does **not** link the video encoder or any
streaming library; it consumes frames for obstacle/AI recognition and produces only an
on-device JPEG used for "camera covered" detection. No frames leave this process for the network.

**The encode + streaming stack is present — but as unused vendor boilerplate, not product
code.** The rootfs ships the full Rockchip media stack (`libeasymedia`, `librockchip_mpp`,
`librockchip_vpu`) built with a **live555 RTSP server**, plus Rockchip's stock sample
binaries — including `rkmedia_vi_venc_rtsp_test` (camera → H.264 → RTSP), which is
**runnable as-is** (every shared-library dependency is present in the image). However:

- **None of 3iRobotix's own binaries link the encoder or any RTSP/streaming library.**
  Verified via `DT_NEEDED`: `RobotApp`, `everest-server`, and `Ai-server` do not; the cloud
  bridge `aiot_client.bin` — the only process that talks to the 3iRobotix broker — links only
  `libc`/`libpthread` and has no media capability whatsoever.
- **Nothing auto-starts the sample binaries** (no init/service references them).

**Interpretation.** On the shipping firmware in normal operation there is **no wired
camera-to-network path anywhere** in the product's own software — a firmware-layer result that
is consistent with, and strengthens, the app-layer evidence for the on-device-only claim (§7).
But this is a property of 3iRobotix's current software choices, **not a hardware or enforced
guarantee**: the encoder exists in silicon, the encode/RTSP libraries and a runnable
camera→H.264→RTSP tool are already on the device, and the platform is 3iRobotix-controlled via
OTA (§4, "OTA update mechanism"). A future firmware update — or a firmware/root-level
vulnerability that permits code execution on the device — could activate off-device video
streaming, with no hardware interlock and no user-visible signal. No technical mechanism
prevents this (see §9.3, §10 Q3).

**Update (2026-10-03):** `everest-server` does contain a still-image collect-and-upload
staging path. It's disabled by config flags on the analysed robot. See §7, "Robot-side
data flows", item 4.

**Vendor comparison (context).** The same vendor's newer "Kärcher Indoor Robots" line (e.g.
RVF 7) ships **live camera and two-way audio as a product feature**, carried over the
third-party **Agora** real-time-video cloud — i.e. off-device video is already a shipping
product on this class of hardware. (The RVF 7's SoC was not independently verified; its
video path is confirmed from its app's bundled Agora SDKs.)

### App

- "Kärcher Home Robots App" — Android + iOS
- Distributed via Google Play / Apple App Store
- Contains hardcoded:
  - Tenant ID: `1528983614213726208`
  - PKCS12 client certificate (`iot_dev.p12`) with password extractable via APK static analysis
  - Client cert: EC P-256, CN=`*.3irobotix.net`, self-signed 3iRobotix CA, expires 2031-11-29
- **Robot firmware pins to this cert** — cannot be bypassed remotely; requires on-device
  changes (root via serial console / SSH). The firmware itself is not encrypted, but
  cert substitution still needs write access to the running device.

### App analytics SDKs (APK static analysis)

| SDK | Vendor | Data collected |
|---|---|---|
| Firebase Analytics | Google (USA) | 37+ named events tracked including `mqttSend` (every robot command), HTTP requests, map operations, session data; user ID linked; device model set as default event parameter |
| Umeng Analytics + Crash | Alibaba Group (China) | IMEI, Android ID, OAID (advertising ID), MAC address, IMSI, MCC/MNC (network operator code); full crash reporting (Java, native, ANR), app launch timing, memory monitoring |
| DoraemonKit | DiDi Chuxing (China) | Debug/diagnostic toolkit (network inspection, log viewer, performance monitoring); registered in production AndroidManifest.xml with 4 entries — `UniversalActivity`, `TranslucentActivity`, `CaptureActivity`, `DebugFileProvider` |

**Pre-consent collection (Umeng):** The APK's `AndroidManifest.xml` registers a `UmengPreInitProvider`, a standard Android `ContentProvider` that auto-initialises before the application `onCreate()` method is called and before any user consent dialog can be shown. Umeng device fingerprint collection begins at app launch, not at consent.

**Google Ad ID permission:** The manifest requests `com.google.android.gms.permission.AD_ID` — the Google Advertising ID permission — which is not disclosed in the official privacy policy.

**Log upload destination:** Crash logs and usage diagnostics are uploaded to Alibaba Cloud OSS. This destination is not named in the privacy policy.

**Privacy policy disclosure gap:** The privacy policy names only "data analytics providers" as a recipient category. Firebase, Umeng, DiDi, and Alibaba Cloud OSS are not individually named. The collection of hardware identifiers (IMEI, IMSI, MAC) via Umeng is not disclosed.

---

## 5. Network Architecture & Cloud Infrastructure

**Platform operator:** 3iRobotix — Chinese company (Shenzhen, Guangdong)
**Brand:** Alfred Kärcher SE & Co. KG, Winnenden, Germany — OEM customer

| Service | Hostname | Port | Protocol |
|---|---|---|---|
| REST API (EU) | eu-appaiot.3irobotix.net | 443 | HTTPS + mutual TLS |
| MQTT broker (EU) | eu-gamqttaiot.3irobotix.net | 8883 | MQTT over TLS 1.2 |
| OTA updates | ota.3irobotix.net | 8001 | HTTPS |
| Firmware CDN (production) | eu-cdnallaiot.3irobotix.net | 443 | HTTPS |
| Firmware CDN (flagged) | **eu-cdndevaiot.3irobotix.net** | 443 | HTTPS — see §6d |
| Backend cloud | AWS (EEA, specific region undisclosed by Kärcher) | — | — |
| REST API (Russia) | ru-appaiot.3irobotix.net | 443 | HTTPS (APK static analysis) |
| REST API (Singapore) | sg-appaiot.3irobotix.net | 443 | HTTPS (APK static analysis) |
| REST API (Kärcher China) | cn-appaiot.kahechina.com | 443 | HTTPS (APK static analysis) |
| REST API (test) | test-appaiot.3irobotix.net | 443 | HTTPS (APK static analysis — development) |
| Analytics | Firebase / Google Analytics | 443 | HTTPS |
| Crash & analytics | Alibaba Cloud (Umeng) | 443 | HTTPS |
| Log upload | Alibaba Cloud OSS | 443 | HTTPS |
| Robot device-log upload | aiot-devlog-prod.oss-cn-shenzhen.aliyuncs.com (CN) | 443 | HTTPS, firmware-embedded OSS key — observed, see §7 "Robot-side data flows" |
| Robot map upload | eu-cdnmapaiot.3irobotix.net → S3 eu-central-1 | 443 | HTTPS — observed |

**Tenant ID** `1528983614213726208` is embedded in all MQTT payloads and REST headers. It is a client-side identifier with no server-side secret function.

### Data flows

1. **App → REST API:** authentication, device list, room/map data
2. **App → MQTT broker → Robot:** all commands (start, stop, fan speed, cleaning mode, water level)
3. **Robot → MQTT broker → App:** state push (battery %, work mode, fault codes, sensor data)
4. **Robot → OTA server:** firmware version check on every connection

**All device control is exclusively MQTT.** No REST command endpoints exist — confirmed via exhaustive endpoint probing of the REST API.

---

## 6. Security Analysis

### 6a. Transport layer

- **TLS 1.2** on MQTT port 8883; cipher ECDHE-RSA-AES256-GCM-SHA384
- Server certificate: **self-signed EC P-256 wildcard** `*.3irobotix.net`, issued by 3iRobotix's own CA (C=CN, ST=GD, L=SZ, O=3irobotix)
- Not from a public CA — no independently audited certificate chain
- Certificate validity: issued ~2021, **expires 2031-11-29** (10-year lifetime)
- **Robot firmware pins to this cert at application layer** — provides MITM protection for device-to-cloud traffic

### 6b. Authentication & signing

- REST API: mutual TLS (PKCS12 client cert + key, hardcoded in APK) + request signing using `MD5(auth_token + timestamp + nonce + body)`
- **MD5 is cryptographically broken** for signing. The practical risk in this context is limited but it is a substandard choice.
- MQTT: username + password credentials from REST login response; no client certificate on MQTT

### 6c. Shared client certificate in APK

- A single PKCS12 cert/key pair is embedded in the Kärcher Home Robots APK, shared by all app instances globally
- The password protecting the PKCS12 container is extractable via static APK analysis
- Extraction of this credential **could enable impersonation of app clients against the 3iRobotix REST API** — account enumeration, device queries, and potential unauthorised API access
- This is a known architectural pattern for OEM IoT platforms and is not incidental to the Kärcher/3iRobotix relationship

### 6d. Dev CDN hostname — resolved

- EU production devices are observed downloading firmware updates from `eu-cdndevaiot.3irobotix.net`
- Kärcher confirmed (April 2026): this is **not a test or staging system** — `dev` is a legacy naming convention with no operational significance
- The hostname serves production EU firmware from production infrastructure

### 6e. MQTT QoS 0

- All device command messages use MQTT QoS 0 (fire-and-forget)
- No delivery acknowledgement; no automatic retry
- Commands may be silently lost under network instability — an operational concern, not a security vulnerability

### 6f. Local attack surface

- No open TCP ports confirmed on the robot during investigation
- No local control API: the device is a pure MQTT client
- Physical access: no *documented* UART/JTAG debug headers, but the firmware enables a
  serial console (`getty` on `ttyFIQ0`) and the rootfs is **not encrypted** — it extracts
  in cleartext offline, exposing a working root login (redacted — see `ROOTING.md §2`)

---

## 7. Data Collection & Privacy Analysis

### Data collected (per official privacy policy)

| Category | Specific data | Processing location |
|---|---|---|
| Account | Email, password | Cloud — 3iRobotix / AWS EEA |
| Device | MAC address, serial number, model, software version | Cloud |
| Network setup | SSID, IP address, time zone, location | Cloud |
| Usage | Cleaning history: date, time, route, area, duration, zone; schedules; mode and suction preferences | Cloud |
| Map | Floor plan, room names (LiDAR-generated) | Cloud |
| Camera | Object outlines and geometric features for obstacle avoidance | **On-device only (claimed)** — images deleted immediately after processing |
| App usage | Phone serial number, interaction logs, location (during network config) | Cloud |

### Data retention

- Device-generated data (maps, cleaning history): **deleted within 6 months of account deletion**
- Account data: deleted on account termination

### Third-party recipients

- **3iRobotix (Shenzhen)** — data processor under Art. 28 GDPR
- "Data analytics providers" — cited as a recipient category in the California consumer notice; not named individually in the privacy policy
- "Vendors for hosting, maintenance, backup, analysis" — not named individually

### App-layer data collection (APK static analysis)

The following data collection occurs at the app layer and is not fully described in Kärcher's privacy policy.

**Firebase Analytics (Google, USA):** The app logs at least 37 named analytics events to Google Firebase. These include `mqttSend` (fired on every command sent to the robot, including start, stop, fan speed changes, room selection), HTTP request events, and map data operations. The user's account ID is linked to analytics via `setUserId()`. The device model is set as a default event parameter attached to all events.

**Umeng SDK (Alibaba Group, China):** The Umeng analytics and crash reporting SDK is integrated. Umeng collects hardware identifiers including IMEI, Android ID, OAID (the Google Ad ID replacement), MAC address, IMSI, and mobile network operator codes (MCC/MNC). All crash reporting categories are enabled: Java crashes, native crashes, ANR (app-not-responding) events, app launch performance, memory monitoring, and network monitoring.

**Pre-consent initialisation:** The APK registers a `UmengPreInitProvider` — an Android `ContentProvider` that the OS initialises automatically before the app's own code runs and before any consent dialog is displayed. Hardware identifier collection begins at app launch for all users, not at the point of user consent.

**Google Advertising ID:** The manifest requests the `com.google.android.gms.permission.AD_ID` permission, allowing collection of the Google Advertising ID. This is not mentioned in the privacy policy.

**Crash log destination:** Crash and diagnostic logs are uploaded to Alibaba Cloud OSS. This is not named in the privacy policy.

### App-layer privacy controls and log uploads (APK static analysis, KHR 1.4.32, 2026-05-10)

Two cloud-upload behaviours are **on by default but user-disableable** via robot MQTT privacy flags (toggles exist in the app settings UI):

| Flag | Default | Controls |
|---|---|---|
| `map_uploads` | Enabled | Floor-map cloud backup (AWS S3 or Alibaba OSS by region) |
| `record_uploads` | Enabled | Cleaning records uploaded to Kärcher / 3iRobotix cloud |

**Opt-in only** (explicit user action): app log uploads (consent dialog shown after a crash) and feedback photos (manual feedback form).

**HTTP request/response logging:** the app's `ResponseInterceptor` is registered with no `BuildConfig.DEBUG` guard — active in the release build. It logs full request URLs and response bodies (up to 10 000 chars) to local disk, and reports URLs + error codes to Firebase on errors.

**Log-bundle contents** (when a log upload occurs):
- Runtime/crash bundle (`/log-service/log/app/report/runtime`): app/Android/device-model, user ID + username, robot serial number, tenant ID, log text, timestamp, geographic zone.
- Device bundle (`sweeper-report/app/log`): the above plus serialized MQTT message history.
- No image or binary data appears in any log bundle.

**Camera — positive APK evidence:** at the app layer the code is consistent with Kärcher's on-device-only claim — no Android Camera API is used for robot monitoring, no HTTP or MQTT topic carries image/video data, and no cloud-vision SDK is integrated. AI obstacle recognition is a single robot-side MQTT flag (`ai_recognize: 0|1`); no image data returns to the app. This bounds the app, not the firmware. Firmware analysis (§4, "Camera pipeline & video capability") independently confirms no wired camera-to-network path in the shipping firmware either — while noting the capability is present in silicon and vendor libraries and is gated only by 3iRobotix's software and OTA control (§9.3).

**Local key-value store:** MMKV (Tencent) is used for on-device encrypted storage only — no network component. The `tencentyyb` APK flavor is a distribution-channel label (Tencent app store), not a Tencent analytics integration.

### Robot-side data flows (firmware + device-log evidence, 2026-10-03)

The app-layer analysis above bounds the app, not the robot. This covers what the **robot
itself** sends. Sources:
- string analysis of the `I3.12.90` rootfs (`oem/bin`, `oem/lib`, `oem/sysconf`)
- this robot's own `/userdata` backup from 2026-09-21, taken while it was still on the
  Kärcher cloud, including `log-server`'s curl trace `logserver.temp`

**Observed** means seen in this robot's logs or config. **Static** means present in the
binaries, with use unconfirmed.

**1. Device logs are uploaded to Alibaba Cloud in Shenzhen, China (observed).**
`log-server`'s curl trace (`logserver.temp`) shows `PUT`s to
`aiot-devlog-prod.oss-cn-shenzhen.aliyuncs.com` (`39.108.31.232`, Aliyun, CN). They come
from **two separate sessions**:
- 2026-09-16, from an earlier `/userdata` dump: 7 uploads, 7 × `HTTP/1.1 200`
- 2026-09-21: about 9 distinct objects, 8 × `HTTP/1.1 200 OK`, all within roughly
  21:16–21:33, right after a reset and re-pair

Objects landed under `<tenantId>/Kaercher.KaercherRCV5Es/<robot SN>/<date>/devicelog/`.
Files included:
- `logfile.txt`, the main log
- `client_file.log`, the cloud bridge's log
- `Monitor.txt` and `wifimanager.txt`
- `console-ramoops-0.txt`, the kernel crash log

Uploads were gzipped, about 1 KB to 200 KB each. These are two short windows, so they show
the behaviour but not how often it happens.
- **The uploads are signed with an Alibaba access key built into the firmware**, not one
  from the cloud. The `Authorization: OSS LTAI5t…` header matches a key ID and secret in the
  `log-server` binary (redacted here), next to the strings `aiot-devlog-prod` and
  `oss-cn-shenzhen.aliyuncs.com`. So this path needs no 3irobotix/Kärcher cloud at all,
  only DNS and internet access.
- **There is a second, EU device-log pipeline.** The cloud's `getAccessUrl` replies
  (`serviceType` 4) named `eu-aiot-devlog-prod` on AWS S3 `eu-central-1`, with objects keyed
  `devicelog/<id>_<SN>_…`. The Shenzhen objects are keyed `devicelog/<date>_<hh>…`, which
  is a different naming scheme. Per the Valetudo dummycloud's live tests, `RobotApp` (not
  `log-server`) does the PUTs for cloud-issued URLs. Its curl calls aren't traced in these
  logs, so the EU leg is **inferred**. The Shenzhen leg is **observed**.
- **How this squares with Kärcher's statements.** Kärcher's marketing says data goes to
  "servers located in Germany only". Its DPO wrote in March 2026 that European customer data
  is stored "on AWS within the EEA" (§2, §12). Two readings are credible:
  - *Contradiction.* These logs carry the serial, MAC, LAN IPs, the robot's path, session
    tokens and an IP-derived city (item 2). Linked to an account, that's personal data, and
    it's stored by Alibaba in China, not by AWS in the EEA.
  - *Covered.* Kärcher could argue that diagnostic logs are the processor's operational
    data, not "customer data", and that 3iRobotix (Shenzhen) is a named Art. 28 processor
    with SCCs in place (§8).

  Neither statement *discloses* this destination either way. Which reading holds is a legal
  question this analysis can't settle.

**2. What the uploaded logs contain (observed in the backed-up logs).**
- robot serial (3,700+ lines) and MAC
- LAN IPs
- live robot path coordinates (`prop.post` `cur_path`)
- the cloud's login reply, including an IP-derived `COUNTRY_CITY` (city level)
- cloud session tokens (`AUTH`, `EMQ_TOKEN`, Bearer JWTs)

**Not** found:
- the home SSID (a strict match gave zero hits)
- Wi-Fi scan lists or nearby BSSIDs
- any latitude/longitude
- any image data

**3. Maps go to the EU (observed).** Map uploads (`serviceType` 2, `map/temp/…`) used the
cloud-issued URL: `eu-cdnmapaiot.3irobotix.net` → `eu-aiot-map-prod` on S3 `eu-central-1`.
Note that `device_config.ini` had `map_uploads=0`. The app treats `0` as uploads *enabled*
(`PrivacySecurityActivity.java`: `setChecked(getMap_uploads() == 0)`), so this matches the
default "on".

**4. Camera still-image collection exists, but was switched off (static + observed config).**
- `everest-server` has a camera data-collection path: `EM_AI_COLLECTION_IMAGE_UPLOAD`,
  `AICOllectionImg`, `TakePhotoParam`, `processFamilyTestDataCollection`.
- It saves `data_collection/RGB200W_…` frames (2 MP RGB) and moves them into a
  `data_upload/` folder ("mv upload file", `rm -rf …data_upload/*`).
- `Ai-server` has a matching `/tmp/AI/ai_collection_data/` and an `ImageDataCollect`
  protobuf message.

This refines §4's camera finding: no *video* path is wired up, but a staging path for
still images is. On this robot:
- `pcl_data.ini` had `ai_image_data_collect=0`, `ai_image_save=0` and the other three
  `*_data_collect=0` flags
- `/userdata/log/perception/data_collection` and `data_upload` were empty
- no image files appeared anywhere in `/userdata/log`

Two things remain unconfirmed:
- whether `log-server` ever packs `perception/data_upload` into a log bundle
- whether the cloud can flip these flags remotely

**5. Remote shell client shipped in firmware (static).** `oem/bin/rtty` is the open-source
rtty 6.6.1 remote-terminal agent, built by a 3iRobotix developer (`/home/xujp/…/rv1126/rtty`).
It has a **hardcoded server, `39.108.250.100`** (Aliyun Shenzhen), and identifies the device
by its wlan0 MAC (`ws://…/ws?device=1&devid=…`). Nothing in init scripts, the Monitor
supervisor or the other binaries launches it, and it never appears in the logs.
**How it could be started remotely is unknown.**

**6. Fallback addresses that bypass DNS (static).** These IP literals sit in the binaries.
A hosts-file block can't stop them:

| Binary | IP | Owner (whois) | Likely role (inferred) |
|---|---|---|---|
| `aiot_client.bin` | `203.107.1.1`, `.33`–`.35` | Aliyun, CN | Alibaba HTTPDNS resolvers |
| `aiot_client.bin` | `8.219.58.10`, `8.219.89.41` | Alibaba Cloud Singapore | fallback cloud endpoints |
| `log-server` | `120.78.95.51` | Aliyun, CN | `log_server_ip`, fallback for `test-devlog.3irobotix.net` (set in `/userdata/config/log-server.ini`) |
| `rtty` | `39.108.250.100` | Aliyun, CN | rtty server |

None of these IPs appear in the 2026-09-21 logs.

**7. DNS and connectivity fallbacks (static).**
- If DHCP supplies no nameserver, `oem/bin/dhcp_dns.sh` writes `114.114.114.114` (114DNS, CN)
  and `8.8.8.8` into `/tmp/resolv.conf`.
- `ntpd` uses `0–3.pool.ntp.org`.
- `libDeviceIo.so` has a ping-based connectivity check against `www.baidu.com`,
  `114.114.114.114` and `8.8.8.8`, but no `oem/bin` binary links it.
- `librbt_sdk.so` holds a map-upload URL, `https://testiot.kahechina.com/api/lab/hm/device/data/map/upload`
  (Kärcher China, test). It's also not linked by any `oem/bin` binary.

**8. Camera calibration frames left on disk (observed).** The 2026-09-16 dump has
`/userdata/camera/rgb_result/image_src.png` (642×362) and `image_res.png` (321×181).
`AuxCtrl`'s "start rgb calibration" routine writes them, and their 1970 timestamps put them
before first clock sync, so they're factory or calibration captures. Their content wasn't
viewed. No upload path refers to them. They weren't in the 2026-09-21 backup, which
didn't include that folder.

**9. Other channels present in code, not seen in use (static).**
- FTP log upload, plaintext `USER`/`PASS`/`STOR`, to `log.3irobotics.net:21`
- `aiot_client` endpoints: `/device-shadow-service/device-statistics-report/report_new`,
  `/network-service/domains/list` (a server-supplied domain list), Baidu voice/`devicechat`
  and RTC video endpoints. These are probably shared SDK code across 3iRobotix products.
- three variants of the storage-URL request: `storage/aws/…`, `storage/oss/…` (Alibaba) and
  `storage/yandex/…`. This EU-paired robot used only the AWS variant (271 calls logged, none
  to the others). The Yandex variant is probably for Russian-region robots, given the
  `ru-appaiot.3irobotix.net` backend (§5) and Russia's data-localisation rules (inferred).
  No Yandex host, IP or key appears in the firmware.
- an NTP list that includes `cn.ntp.org.cn` and `cn.pool.ntp.org`

**Status of the Valetudo decoupling.** `karcher-cloud-switch.sh` blackholes the 3irobotix
hostnames. It does **not** cover:
- `*.oss-cn-shenzhen.aliyuncs.com`, the observed log destination
- `ota.3irobotics.net`, the "c" spelling that appears in `RobotApp` and `log-server`
- any of the IP literals above

The robot's kernel has no netfilter, so blocking IP literals needs a firewall rule on the
network side.

**Live check, 2026-10-03 (observed, Valetudo-mode unit).** The Shenzhen upload path kept
running after decoupling, with no vendor cloud involved:
- `netstat` showed connections to `39.108.31.232:443`.
- `log-server`'s trace, covering about 20 hours (2026-10-02 20:00 to 2026-10-03 16:00
  CST), showed 110 completed uploads (about 24 MB). That's 85 × `HTTP 200` and 828
  timed-out attempts that were retried.
- Uploaded files: device logs, the cloud bridge's logs, AI-server and app logs, the kernel
  crash log, 7 raw SLAM map files (`relo_globalSlam.rawlog`) and 4 map scheme files.
- No images were sent, and the camera-collection flags were still `0`.

This shows the upload depends only on internet access, not on the vendor cloud or an
account. The bucket host and `ota.3irobotics.net` were then added to the blackhole list,
and the robot was cut off from the internet at the router.

### Claims that cannot be independently verified (official privacy policy)

- **Camera on-device only** — entirely contingent on 3iRobotix not modifying firmware behaviour, which Kärcher cannot audit or enforce
- **No individual user profiling** — analytics described as pseudonymized; unverifiable independently
- **No sale or sharing of personal data** — stated under CCPA §12; unverifiable independently

---

## 8. Legal & Compliance Analysis

### GDPR

- **Data controller:** Alfred Kärcher SE & Co. KG (Winnenden, Germany)
- **Data processor:** 3iRobotix (Shenzhen, China) under Art. 28 GDPR
- **Cross-border transfer mechanism:** Standard Contractual Clauses, Module 3 (controller-to-processor)
- **Competent supervisory authority:** Baden-Württemberg Commissioner for Data Protection and Freedom of Information, Stuttgart
- **Legal basis:** Art. 6(1)(b) — performance of a contract; Art. 6(1)(f) — legitimate interests (product analytics, improvement)

### The structural limitation of SCCs Module 3

Standard Contractual Clauses are an instrument of EU law. They impose contractual obligations on 3iRobotix enforceable under EU legal frameworks. They **cannot override** obligations imposed on 3iRobotix by Chinese domestic law.

**China's National Intelligence Law (2017), Article 7:**
> *"Any organization or citizen shall support, assist, and cooperate with the state intelligence work in accordance with the law."*

This obligation applies to 3iRobotix regardless of:
- Where data is physically stored (EEA or otherwise)
- What contractual arrangements exist between Kärcher and 3iRobotix
- What the SCCs require

**SCCs create legal obligations and civil remedies under EU law. They do not create technical protection against state-compelled access to data held by a Chinese company.**

### North America (Terms of Use)

- Governing law: **Colorado, USA**
- **Mandatory arbitration** with class action and jury trial waiver (§12)
- Kärcher NA may terminate service **at any time without notice** (§7)
- Kärcher NA may modify or replace the app **at any time** (§2.4, §2.6)

---

## 9. Structural Risks

### 1. Chinese origin — intelligence law

3iRobotix (Shenzhen) Co. Ltd. is subject to Chinese domestic law. The 2017 National Intelligence Law (Art. 7) creates a compelled-cooperation obligation that no private contractual arrangement can override. This risk is structural: it is a property of the product architecture, not a compliance failure by either Kärcher or 3iRobotix.

### 2. Full-stack OEM dependency

Kärcher has no independent technical visibility into or control over:
- Firmware content or behaviour
- OTA update payloads before delivery to EU customers
- Cloud infrastructure operations at 3iRobotix
- Data access at 3iRobotix

Kärcher's assurances to customers rest entirely on 3iRobotix's contractual compliance.

### 3. Camera in private spaces

The RCV5 operates autonomously throughout the home — including private spaces — equipped with a camera and 3D sensor. The on-device-only processing claim cannot be independently *enforced*: it depends on 3iRobotix not modifying firmware behaviour via OTA. Kärcher cannot audit this independently, and customers have no technical means to verify it on an ongoing basis.

Firmware analysis (§4, "Camera pipeline & video capability") refines this. In the shipping firmware there is **no wired camera-to-network path** in 3iRobotix's own software, so in normal operation video does stay on-device — a finding that supports the claim for the current build. But the underlying hardware is a camera-streaming SoC with a hardware H.264/H.265 encoder, and the device already carries the Rockchip encode + RTSP libraries and a runnable camera→H.264→RTSP tool; only 3iRobotix's software choices keep them idle. Because the platform is 3iRobotix-controlled via OTA, a routine firmware update — **or a firmware/root-level vulnerability that permits code execution on the device** — could turn on off-device video streaming without any hardware interlock or user-visible indication. The on-device-only property is therefore a matter of vendor trust and software state, not a guarantee.

### 4. Cloud-only architecture — no local fallback

The device is **non-functional without 3iRobotix cloud connectivity**. There is no local control API. Service continuity depends entirely on 3iRobotix's continued operation. Customers have no contractual relationship with 3iRobotix and no recourse if service is degraded or withdrawn.

### 5. Dev CDN in firmware delivery path — resolved

Firmware updates for EU production devices are served from `eu-cdndevaiot.3irobotix.net`. Kärcher confirmed (April 2026) that `dev` is legacy naming only — this is production infrastructure. Risk resolved.

### 6. Production build includes a debug toolkit (DiDi DoraemonKit)

The production APK includes DoraemonKit, a debug and diagnostic toolkit developed by DiDi Chuxing (China). It is registered with four entries in the production `AndroidManifest.xml`: `UniversalActivity`, `TranslucentActivity`, `CaptureActivity`, and `DebugFileProvider`. DoraemonKit provides network traffic inspection, real-time log access, file system browsing, and performance monitoring within the application. The presence of an active debug toolkit in a production build distributed via Google Play is unusual and inconsistent with standard secure software development practices.

### 7. App-layer data collection not disclosed in privacy policy

Firebase Analytics, Umeng (Alibaba), and Alibaba Cloud OSS are active in the production app. Collection of hardware identifiers (IMEI, IMSI, MAC, OAID) by Umeng occurs before user consent via automatic ContentProvider initialisation. None of these SDKs or their specific data collection activities are named in Kärcher's privacy policy. The Google Advertising ID is collected without disclosure. Undisclosed recipients include Google (Firebase), Alibaba Group (Umeng), and DiDi Chuxing (DoraemonKit).

---

## 10. Open Questions (as of April 2026)

The following questions were put to Kärcher in writing. One was resolved; three remain open.

1. **Marketing correction** — Will Kärcher correct its "Germany only" marketing materials to accurately reflect EEA-wide data storage? *Kärcher responded that no final decision has been taken on when or how to change them. The claim remains live.*

2. **Firmware audit** — Does Kärcher conduct independent technical audits of 3iRobotix firmware before OTA distribution to EU customers? *Not answered. Response cited contractual agreements (SCCs) only.*

3. **Camera enforcement** — What technical mechanism prevents 3iRobotix firmware from transmitting video or image data off-device? *Not answered. Kärcher restated the policy position (on-device processing, deleted after recognition) without describing any technical enforcement mechanism. Firmware analysis (§4, "Camera pipeline & video capability") now answers it directly: there is **no such mechanism**. The shipping firmware happens not to wire the camera to the network, but the hardware encoder and the encode/RTSP libraries are present on the device, and only 3iRobotix's software state keeps them idle — an OTA update or a firmware/root-level vulnerability could enable streaming with no hardware interlock and no user-visible signal.*

4. **Dev CDN** — ~~Is `eu-cdndevaiot.3irobotix.net` a development or staging environment?~~ **Resolved (April 2026):** Kärcher confirmed this is production infrastructure; `dev` is legacy naming only.

---

## 11. Conclusions

### Confirmed true

- GDPR compliance is formally in place: Art. 28 processor agreement, SCCs Module 3, privacy policy with all required disclosures (Art. 13), CCPA notice for California residents
- Radio Equipment Directive compliance declared: EU 2014/53/EU, UK S.I. 2017/1206
- Camera on-device processing is documented as policy in the official privacy policy
- Transport security is reasonable for consumer IoT: TLS 1.2, cert pinning on device

### Contradicted by Kärcher's own written statement

> **"The entire data transfer between the Home Robots app on your smartphone and your robotic vacuum cleaner and mop runs via a cloud to servers located in Germany only."**

Kärcher's own Data Protection Team stated in writing (March 2026) that European customer data is stored on AWS within the EEA — not Germany specifically, which is inconsistent with the marketing claim above. At least one documented purchasing decision was made on the basis of this claim.

### Structurally unresolvable by contractual means

The Chinese National Intelligence Law creates a structural compelled-cooperation obligation for 3iRobotix that cannot be neutralised by SCCs, EEA data residency, or GDPR compliance formalities. This is not a criticism of Kärcher's legal diligence — it is a structural property of any product whose full technology stack is controlled by a Chinese company. The risk is proportional to the sensitivity of the data involved and the trust placed in the product's stated data minimisation claims.

### Security posture

Reasonable for consumer IoT at the device/transport layer. Certificate pinning protects device-to-cloud traffic from network-level interception. Notable weaknesses:
- Shared PKCS12 client certificate with extractable password embedded in APK
- MD5-based REST request signing (cryptographically broken hash function)
- No independently audited OTA process (Kärcher has not described any audit process)
- Production APK includes DiDi DoraemonKit debug toolkit (network inspector, log viewer, file browser)
- Hardware identifier collection (IMEI, IMSI, MAC, OAID) via Umeng begins before user consent

---

## 12. Written Correspondence with Kärcher Data Protection Team (March 2026)

A written exchange was conducted with Alfred Kärcher SE & Co. KG's Data Protection Team in
March–April 2026, covering data residency, the GDPR processor relationship with 3iRobotix, and
the camera on-device-processing claim. The original correspondence was never committed to this
repository. A detailed record is kept privately rather than in this public document; the
questions asked and their resolution status are summarized in §10 above.
