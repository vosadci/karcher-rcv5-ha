# Kärcher Home Robots — Intent Document

> **Purpose:** Reconstructs the original problem statement, goals, and constraints as they existed before implementation began. This is the "what and why" — extracted from session history, protocol notes, and early design decisions. It is not a description of what was built; `../ARCHITECTURE.md` and `../CHANGELOG.md` are the authoritative source for that.
>
> **Date of original intent:** March 2026
> **Extracted:** April 2026

---

## 1. The Problem

A Kärcher RCV5 robot vacuum was purchased partly on the basis of Kärcher's marketing claims — specifically that data was processed on German servers, and that the device was from a trustworthy European brand. Independent investigation revealed both claims to be materially false or unverifiable: data is stored on AWS EEA (not Germany), and the entire product stack — firmware, cloud infrastructure, mobile app, and OTA updates — is authored and operated by 3iRobotix (Zhuhai) Co. Ltd., a Chinese company with no public disclosure to customers.

Despite this, the physical robot was already purchased and in use. The question became: can the device be meaningfully integrated into a Home Assistant-based smart home, and can cloud dependency be eliminated?

The first question was answered yes. The second was answered no — at least for now.

---

## 2. What the Owner Wanted

Expressed directly across sessions, the goals were:

**Primary:**
- Control the robot from Home Assistant with at least the feature parity of the official app for core functions (start, stop, return, room selection, fan speed, cleaning mode)
- Get real-time state — not polling lag, not manual refresh
- Integrate with Apple Home so the robot is accessible via Siri and Apple Home automations

**Secondary:**
- Understand what the robot and app actually collect and send — to make an informed decision about continued use
- Establish local control — independence from the 3iRobotix cloud, which can be degraded, discontinued, or compelled to share data under Chinese law

**Explicitly not wanted:**
- A fragile hack that breaks on the next app update
- Anything that required modifying the robot hardware before understanding what the software does
- A solution that required keeping the official Kärcher app installed for normal use

---

## 3. Why No Official Integration Exists

- Kärcher publishes no developer API, no cloud protocol documentation, and no Home Assistant integration
- The underlying platform (3iRobotix) is not a known commodity (not Tuya, not Xiaomi, not iRobot)
- The python-karcher library exists but is minimally documented and has known bugs
- No prior community integration existed for this device

---

## 4. The Local Control Investigation (Pre-Integration)

Before building a cloud-dependent integration, the intent was to establish whether local control was possible. A structured investigation was conducted:

| Approach | Outcome |
|---|---|
| DNS redirect to local Mosquitto broker | Robot connects but closes immediately after TLS handshake |
| Use `iot_dev.p12` cert from APK as server cert | Different public key from pinned cert — not usable |
| OTA firmware extraction and modification | Believed at the time: squashfs rootfs AES-encrypted by Rockchip TrustZone, not extractable without physical UART access. **Later found to be a misdiagnosis** — the rootfs is UBI-wrapped, XZ-*compressed* (not encrypted), and extracts to cleartext entirely offline from the OTA image, no hardware needed. See `PROTOCOL.md §9.2`. |
| Network port scan | All ports closed; robot is a pure MQTT client |
| APK analysis to find cert pinning | Confirmed: robot pins against `server.bks` (keystore password redacted — see `PROTOCOL.md §9`) — application-layer check after TLS completes |

**Conclusion reached before integration work began:** Local control is not currently possible without UART console access to the physical PCB. A cloud-dependent integration is the only viable path for now.

This was an explicit constraint accepted before writing any integration code — not a compromise made mid-implementation.

---

## 5. The Original Goals (Ordered)

1. **Understand the protocol** — before writing any HA integration code, fully document the MQTT and REST protocol through traffic capture, APK decompilation, and TLS probing. Make this reproducible by third parties.

2. **Build a working cloud-push HA integration** — real-time state via MQTT push, all core commands, room selection, fan speed, cleaning mode, water level.

3. **Enable Apple Home via Matter** — without custom firmware or additional hardware. Use HA Matter Hub as a bridge.

4. **Investigate local control** — systematically exhaust all non-invasive paths to local broker substitution. Document what was tried and why each path failed.

5. **Understand data collection** — independently verify what the robot and app actually collect and transmit, to support informed decision-making about continued use and to document findings publicly.

6. **Plan a path to full local control** — if cloud independence is eventually achieved (via UART access and cert replacement), have the protocol knowledge and tooling ready to implement a fake cloud or direct MQTT broker.

---

## 6. Constraints Known Before Implementation

### Technical constraints (discovered through investigation)

- **No local API** — the robot opens no TCP ports and cannot be communicated with directly
- **Certificate pinning** — the robot checks the MQTT broker's public key after TLS completes; DNS redirect alone is insufficient
- **Encrypted firmware** — the squashfs rootfs is AES-encrypted with a Rockchip TrustZone key; OTA images cannot be extracted or modified without physical UART access
- **paho-mqtt thread boundary** — the python-karcher library uses paho-mqtt in a background thread; all HA state changes require crossing the thread boundary via `call_soon_threadsafe`
- **Library bugs** — python-karcher has at least two active bugs requiring workarounds: a `net_stauts` typo that causes `AttributeError` on every property update, and a `get_device_properties()` cache that returns stale data when subscribed

### Platform constraints (Home Assistant)

- Battery level must be a separate `SensorEntity` — `VacuumEntityFeature.BATTERY` is deprecated from HA 2025.x and removed in 2026.8
- State must use `VacuumActivity` enum and the `activity` property — `STATE_*` string constants are removed
- The integration must not block the HA event loop — all blocking calls via `run_in_executor`
- HACS compatibility requires specific `manifest.json` and `hacs.json` structure

### Deployment constraints

- HA runs on Home Assistant OS with Supervisor
- `karcher-home` must be installed as a PyPI package (not a git URL) — the HA OS host does not have git available

### Business constraints

- Credentials (email + password) must be stored, not tokens — tokens expire and the library provides no refresh mechanism
- The integration must support re-authentication without removing the integration — token expiry is routine
- Multiple robots on the same or different accounts must be supported as separate config entries

---

## 7. What "Success" Meant

Defined before implementation, success was:

1. The robot appears in Home Assistant and responds to commands within ~2 seconds
2. State changes on the physical robot (charging, cleaning, docking) are reflected in HA within ~2 seconds
3. Room selection, fan speed, cleaning mode, and water level are all controllable from HA
4. The robot appears in Apple Home with room picker, fan speed, cleaning mode, and water/mop controls
5. The integration installs via HACS without manual file copying
6. The integration survives HA restarts and token expiry without user intervention
7. Two robots on the same account can be added independently

Success explicitly did **not** include:
- Local control (accepted as blocked)
- Map display (deferred to a later phase)
- Offline operation
- Historical cleaning records beyond the current session

---

## 8. The Privacy Investigation Intent

The APK investigation was not part of the original integration scope. It was initiated as a separate question: *given that the cloud dependency cannot be eliminated, what is the full surface of data collection by the app and robot?*

The specific intent was:
- Verify whether the app collects data beyond what the privacy policy discloses
- Identify any third-party SDKs active in the production app
- Determine whether any collection occurs before user consent
- Document all findings publicly so other users can make informed decisions

This investigation was conducted independently of the integration work and its findings were documented in `INVESTIGATION.md` and `READ_BEFORE_BUYING.md` — not in the integration codebase itself.

---

## 9. What Was Left Deliberately Open

Two questions were left open as of the end of the initial implementation phase, with intent to return to them:

**Map display:** The robot's LiDAR data is available via the 3iRobotix cloud API as a protobuf (`RobotMap`), and the schema was fully reverse-engineered. A map image entity rendering the floor plan as a PNG for HA was designed and planned but deferred. All prerequisite knowledge is documented.

**Full local control:** The fake-cloud approach — running a local Mosquitto broker with replaced certs on the robot — is fully specified and ready to implement once UART console access to the robot's PCB is obtained. The protocol knowledge, tooling, and cert infrastructure are all in place. This was not a failed goal; it was a correctly scoped one.

---

## 10. Relationship to Kärcher Correspondence

In parallel with the technical investigation, four questions were put to Kärcher's Data Protection Team in writing. These were not part of the integration project but were part of the same broader inquiry — understanding what the product actually does versus what it claims.

The questions were:
1. Will Kärcher correct its "Germany only" marketing claim?
2. Does Kärcher conduct independent firmware audits before OTA distribution?
3. What technical mechanism prevents camera/video exfiltration?
4. Is `eu-cdndevaiot.3irobotix.net` a development environment serving production devices?

Kärcher responded partially in April 2026: the dev CDN question was resolved (confirmed production infrastructure, legacy naming). The marketing correction, firmware audit, and camera enforcement questions remain without substantive answers. The intent to continue this correspondence is open.
