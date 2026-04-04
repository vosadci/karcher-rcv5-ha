# Kärcher RCV5 — Security & Architecture Investigation

> **Scope:** Kärcher's marketing claims, hardware design, firmware/software architecture, cloud infrastructure, security posture, data privacy, and legal/compliance analysis.
> **Method:** Traffic capture, APK static analysis, firmware analysis, official documentation review, and written correspondence with Kärcher's Data Protection Team.
> **Date:** March 2026

---

## 1. Executive Summary

- Kärcher's "servers in Germany only" marketing claim is **false** — confirmed by Kärcher's own Data Protection Officer: data is stored on AWS within the EEA, not Germany specifically
- The **entire product stack** — firmware, cloud infrastructure, app, and OTA updates — is authored and operated by **3iRobotix (Zhuhai) Co. Ltd., a Chinese company**
- China's National Intelligence Law (2017, Art. 7) applies to 3iRobotix regardless of where data is stored, creating a structural compelled-cooperation risk that no contractual arrangement can neutralise
- The camera/video **on-device-only processing claim is unverifiable** — Kärcher does not control the firmware that governs camera behaviour
- Security posture is **reasonable for consumer IoT**: TLS 1.2 with certificate pinning on the device. Key weaknesses: shared client certificate embedded in the APK, MD5-based REST signing
- **Four questions put to Kärcher in writing remain unanswered** as of March 2026

---

## 2. Kärcher Marketing Claims vs. Verified Reality

| Claim | Source | Finding | Evidence |
|---|---|---|---|
| "Servers located in Germany only" | Kärcher website | **FALSE** — EEA-wide (AWS) | Kärcher DPO response, Mar 2026 |
| "Entire data transfer runs via cloud to Germany-only servers" | Kärcher website | **FALSE** | Same |
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
- Firmware version: I3.12.26 (versionCode 26, released 2022-11-16)

### Physical

- Dust container: 330 ml | Water reservoir: 240 ml

---

## 4. Firmware & Software Architecture

### Firmware format

- Container format: **Rockchip RKFW** (magic `RKFW`)
- RKAF package embedded at offset 0x3D9B4
- Partitions: MiniLoaderAll.bin, parameter.txt, boot.img, rootfs.img
- rootfs.img: **squashfs 4.0, XZ-compressed, blocks encrypted**
- Encryption key is stored in **TrustZone** — not recoverable without physical hardware access (UART/JTAG)
- No documented hardware debug access point for the RCV5

### OTA update mechanism

- Check endpoint: `https://ota.3irobotix.net:8001/service-publish/open/upgrade/try_upgrade`
- Checked on every cloud connection: productId, model code, current versionCode, device SN
- Firmware served from CDN: `eu-cdnallaiot.3irobotix.net` (also observed: `eu-cdndevaiot.3irobotix.net` — see §6d)
- **Updates authored, signed, and distributed entirely by 3iRobotix. No independent Kärcher audit is documented.**

### App

- "Kärcher Home Robots App" — Android + iOS
- Distributed via Google Play / Apple App Store
- Contains hardcoded:
  - Tenant ID: `1528983614213726208`
  - PKCS12 client certificate (`iot_dev.p12`) with password extractable via APK static analysis
  - Client cert: EC P-256, CN=`*.3irobotix.net`, self-signed 3iRobotix CA, expires 2031-11-29
- **Robot firmware pins to this cert** — cannot be bypassed without modifying encrypted firmware

---

## 5. Network Architecture & Cloud Infrastructure

**Platform operator:** 3iRobotix (Zhuhai) Co. Ltd. — Chinese company
**Brand:** Alfred Kärcher SE & Co. KG, Winnenden, Germany — OEM customer

| Service | Hostname | Port | Protocol |
|---|---|---|---|
| REST API (EU) | eu-appaiot.3irobotix.net | 443 | HTTPS + mutual TLS |
| MQTT broker (EU) | eu-gamqttaiot.3irobotix.net | 8883 | MQTT over TLS 1.2 |
| OTA updates | ota.3irobotix.net | 8001 | HTTPS |
| Firmware CDN (production) | eu-cdnallaiot.3irobotix.net | 443 | HTTPS |
| Firmware CDN (flagged) | **eu-cdndevaiot.3irobotix.net** | 443 | HTTPS — see §6d |
| Backend cloud | AWS (EEA, specific region undisclosed by Kärcher) | — | — |

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
- Extraction of this credential **enables impersonation of app clients against the 3iRobotix REST API** — account enumeration, device queries, and potential command injection
- This is a known architectural pattern for OEM IoT platforms and is not incidental to the Kärcher/3iRobotix relationship

### 6d. Flagged: dev CDN in production firmware path

- EU production devices are observed downloading firmware updates from `eu-cdndevaiot.3irobotix.net`
- The `dev` substring in a production-serving hostname typically indicates a development or staging infrastructure
- Development and staging environments are generally held to lower security standards: looser access controls, less hardening, potentially reduced change management
- **Kärcher has not responded to the question of whether this is a legacy naming convention or an active development environment serving production EU devices**

### 6e. MQTT QoS 0

- All device command messages use MQTT QoS 0 (fire-and-forget)
- No delivery acknowledgement; no automatic retry
- Commands may be silently lost under network instability — an operational concern, not a security vulnerability

### 6f. Local attack surface

- No open TCP ports confirmed on the robot during investigation
- No local control API: the device is a pure MQTT client
- Physical access: no documented UART/JTAG debug headers; rootfs encrypted

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

- **3iRobotix (Zhuhai)** — data processor under Art. 28 GDPR
- "Data analytics providers" — cited as a recipient category in the California consumer notice; not named individually in the privacy policy
- "Vendors for hosting, maintenance, backup, analysis" — not named individually

### Claims that cannot be independently verified

- **Camera on-device only** — entirely contingent on 3iRobotix not modifying firmware behaviour, which Kärcher cannot audit or enforce
- **No individual user profiling** — analytics described as pseudonymized; unverifiable independently
- **No sale or sharing of personal data** — stated under CCPA §12; unverifiable independently

---

## 8. Legal & Compliance Analysis

### GDPR

- **Data controller:** Alfred Kärcher SE & Co. KG (Winnenden, Germany)
- **Data processor:** 3iRobotix (Zhuhai, China) under Art. 28 GDPR
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

3iRobotix (Zhuhai) Co. Ltd. is subject to Chinese domestic law. The 2017 National Intelligence Law (Art. 7) creates a compelled-cooperation obligation that no private contractual arrangement can override. This risk is structural: it is a property of the product architecture, not a compliance failure by either Kärcher or 3iRobotix.

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

### 5. Dev CDN in firmware delivery path

Firmware updates for EU production devices are observed being served from a hostname containing `dev`. If this is not legacy naming, firmware trusted by EU customers' devices may be delivered from infrastructure that does not meet production security standards.

---

## 10. Unanswered Questions (put to Kärcher in writing, Mar 2026)

1. **Marketing correction** — Will Kärcher correct its "Germany only" marketing materials to accurately reflect EEA-wide data storage?

2. **Firmware audit** — Does Kärcher conduct independent technical audits of 3iRobotix firmware before OTA distribution to EU customers? If so: by whom, under what methodology, and what is the scope of verification?

3. **Camera enforcement** — What technical mechanism prevents 3iRobotix firmware from transmitting video or image data off-device? How is this enforced and independently verified, beyond 3iRobotix's own assurances?

4. **Dev CDN** — Is `eu-cdndevaiot.3irobotix.net` a development or staging environment serving EU production devices, or is "dev" a legacy naming convention with no operational significance?

---

## 11. Conclusions

### Confirmed true

- GDPR compliance is formally in place: Art. 28 processor agreement, SCCs Module 3, privacy policy with all required disclosures (Art. 13), CCPA notice for California residents
- Radio Equipment Directive compliance declared: EU 2014/53/EU, UK S.I. 2017/1206
- Camera on-device processing is documented as policy in the official privacy policy
- Transport security is reasonable for consumer IoT: TLS 1.2, cert pinning on device

### Confirmed false

> **"The entire data transfer between the Home Robots app on your smartphone and your robotic vacuum cleaner and mop runs via a cloud to servers located in Germany only."**

Kärcher's own Data Protection Team confirmed in writing (March 2026) that European customer data is stored on AWS within the EEA — not Germany specifically. This is a materially inaccurate marketing claim. At least one documented purchasing decision was made on the basis of this claim.

### Structurally unresolvable by contractual means

The Chinese National Intelligence Law creates a structural compelled-cooperation obligation for 3iRobotix that cannot be neutralised by SCCs, EEA data residency, or GDPR compliance formalities. This is not a criticism of Kärcher's legal diligence — it is a structural property of any product whose full technology stack is controlled by a Chinese company. The risk is proportional to the sensitivity of the data involved and the trust placed in the product's stated data minimisation claims.

### Security posture

Reasonable for consumer IoT. Certificate pinning protects device-to-cloud traffic from network-level interception. Notable weaknesses:
- Shared PKCS12 client certificate with extractable password embedded in APK
- MD5-based REST request signing (cryptographically broken hash function)
- Dev-labelled CDN in the firmware delivery path (status unconfirmed)
- No independently audited OTA process

---

## 9. Written Correspondence with Kärcher Data Protection Team (March 2026)

A written exchange was conducted with Alfred Kärcher SE & Co. KG's Data Protection Team in March 2026. The original correspondence has been removed from this repository; a factual summary is preserved here.

### Questions put to Kärcher (first message)

Five specific technical questions were asked:

1. Which AWS region(s) serve as the backend for the Global Accelerator endpoint resolving from `eu-cdndevaiot.3irobotix.net`, and is this exclusively `eu-central-1` (Frankfurt)?
2. What is the nature of the relationship between Kärcher and 3iRobotix with respect to data processing — is 3iRobotix acting as a data processor under GDPR?
3. Is 3iRobotix's infrastructure disclosed as a sub-processor in Kärcher's privacy policy or data processing documentation?
4. Under which GDPR transfer mechanism (adequacy decision, SCCs) is data handled where it transits or is processed outside the EEA?
5. Given that AWS Global Accelerator makes backend data residency opaque to end users, how does Kärcher substantiate and demonstrate its "Germany-only server storage" marketing claim?

### Kärcher's response

1. European customer data is stored on AWS within the EEA. No specific region was named.
2. 3iRobotix is a data processor under Art. 28 GDPR.
3. 3iRobotix is listed as a sub-processor in Kärcher's internal data processing documentation; the privacy policy references categories of service providers including 3iRobotix.
4. Data transfers to 3iRobotix are governed by Standard Contractual Clauses (Module 3).
5. "Besides contractual safeguards Kärcher has access to the Server." No technical substantiation was provided.

### Follow-up (second message)

A follow-up raised three further issues:

1. **Marketing accuracy:** Kärcher's own response confirmed EEA-wide storage, not Germany specifically. The "Germany only" marketing claim was highlighted as materially inaccurate, with the explicit statement that the purchasing decision had been made partly on the basis of that claim.
2. **Chinese National Intelligence Law:** China's 2017 National Intelligence Law (Art. 7) imposes a compelled-cooperation obligation on 3iRobotix regardless of data residency or contractual arrangements. SCCs are instruments of EU law and cannot override Chinese domestic legal obligations on a Chinese entity.
3. **Camera/video processing:** Kärcher claims video is processed exclusively on-device. This assurance is entirely contingent on 3iRobotix's ongoing adherence — Kärcher cannot independently audit or enforce firmware behaviour at the OTA level.

Four specific requests were made: (1) correct the marketing claim; (2) clarify whether independent firmware audits are conducted before OTA distribution; (3) describe the technical mechanism that prevents video exfiltration; (4) respond from both the DPO and relevant technical teams.

### Third message

A further technical question was raised: the hostname `eu-cdndevaiot.3irobotix.net` contains the substring "dev", which typically denotes a development or staging environment. Kärcher was asked to confirm whether EU customer devices connect to a non-production environment, and if so, what security and stability standards apply.

### Status

As of March 2026, the follow-up questions (marketing correction, firmware audit, camera mechanism, dev hostname) remain unanswered.
