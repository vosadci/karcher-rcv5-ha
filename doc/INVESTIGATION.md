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

**Camera — positive APK evidence:** at the app layer the code is consistent with Kärcher's on-device-only claim — no Android Camera API is used for robot monitoring, no HTTP or MQTT topic carries image/video data, and no cloud-vision SDK is integrated. AI obstacle recognition is a single robot-side MQTT flag (`ai_recognize: 0|1`); no image data returns to the app. This bounds the app, not the firmware — see §9.3.

**Local key-value store:** MMKV (Tencent) is used for on-device encrypted storage only — no network component. The `tencentyyb` APK flavor is a distribution-channel label (Tencent app store), not a Tencent analytics integration.

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

The RCV5 operates autonomously throughout the home — including private spaces — equipped with a camera and 3D sensor. The on-device-only processing claim cannot be independently verified: it depends on 3iRobotix not modifying firmware behaviour via OTA. Kärcher cannot audit this independently, and customers have no technical means to verify it.

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

3. **Camera enforcement** — What technical mechanism prevents 3iRobotix firmware from transmitting video or image data off-device? *Not answered. Kärcher restated the policy position (on-device processing, deleted after recognition) without describing any technical enforcement mechanism.*

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
