# Kärcher RCV5 — Local Control Paths

> **Goal:** run the RCV5 without the 3iRobotix cloud, keeping (or improving on)
> the existing HA integration. This doc consolidates the on-device architecture
> and the concrete paths to cloud-free control that open up once root is
> obtained. Prerequisite: a root shell — see `ROOTING.md`.
>
> **Status of the enabling facts (2026-07):** the firmware is **not encrypted**
> and extracts offline (`PROTOCOL.md §9.2`); `/etc/shadow` gives `root` /
> `3irobotix`; a serial console runs on `ttyFIQ0` (`ROOTING.md §2`). Everything
> below follows from having root on the device.

---

## 1. On-device architecture

Extracted from the `/oem/bin` binaries (symbol/string analysis of the factory
image `I3.12.26`). The robot is a Buildroot/Linux system whose processes talk
over a **local nanomsg bus**, with a single process bridging out to the cloud:

```
        ┌──────────────────────────────────────────────────────────┐
        │  RV1126 (Linux, Buildroot 2018.02)                         │
        │                                                            │
        │  AuxCtrl ── UART ── motor/sensor MCU                       │
        │     │                                                      │
        │  RobotApp  (everest C++ framework)                         │
        │   • SLAM: Google Cartographer (map_builder / trajectory_   │
        │     builder_2d/3d / sparse_pose_graph .lua in /oem/sysconf)│
        │   • task engine: NavigationMode, LocalClean, CustomClean,  │
        │     GoDock, CollectDust, SelfCheck, Exploration, ManualClean│
        │     │                                                      │
        │     │  nanomsg IPC (nn_bind; QueryDeviceMapBinData,        │
        │     ▼  DeviceCleanMapBinDataReport, task compose msgs)     │
        │  everest-server ── Ai-server (obstacle recognition)        │
        │     │                                                      │
        │     ▼                                                      │
        │  aiot_client.bin  (paho-mqtt.c + mbedTLS)  ───TLS 1.2────► 3iRobotix
        │                                                     cloud MQTT
        └──────────────────────────────────────────────────────────┘
```

Key process facts:

| Process | Role | Notes |
|---|---|---|
| `RobotApp` | Robot brain (`everest` framework) | Task primitives listed above; owns Cartographer SLAM and the map |
| `everest-server` | Internal message bus | **nanomsg** (`CNanomsgSocket nn_bind`); carries map/task messages between processes |
| `aiot_client.bin` | **Cloud bridge** | **paho-mqtt.c** over **mbedTLS**; the only process that talks to the 3iRobotix broker |
| `AuxCtrl` | Motor/sensor MCU link | Serial protocol to the low-level controller |
| `Ai-server` | Obstacle/AI recognition | Camera pipeline |
| `wifiManager`, `upgrade`, `Monitor`, `watchdog`, `log-server` | Support daemons | `upgrade` = OTA client; `log-server` = log upload |

Consequences of this shape:

- **No local broker, no local listener.** Control is *outbound* MQTT from
  `aiot_client` to the cloud (matches the closed-port nmap in `PROTOCOL.md §9`).
  An external app cannot talk to the robot locally as shipped.
- **The cloud protocol you already reverse-engineered lives at the
  `aiot_client` ⇄ broker seam.** Redirect that seam and the existing integration
  keeps working (Path A).
- **The cloud-independent seam is the nanomsg bus** to `RobotApp` (Paths B/C).

### The cloud dependency (what to defeat)

`aiot_client` verifies the broker's certificate against a **file on the
writable userdata partition**:

- Cert file: **`/userdata/config/server.crt`** (seeded from
  `/oem/sysconf/server.crt` by `S88scinit`, which runs
  `cp -rf /oem/sysconf/* /userdata/config/` on boot).
- TLS stack: **mbedTLS** (not OpenSSL) — so an OpenSSL `LD_PRELOAD`
  (`SSL_CTX_load_verify_locations` no-op) does **not** affect `aiot_client`.
  Defeat the pin by **replacing the cert file**, not by preloading.
- Region endpoints: `/oem/sysconf/sysConfig.ini` (`eu-ota.3irobotix.net`,
  `euftp-log.3irobotix.net`, …). The MQTT broker host is redirected at the
  name-resolution layer regardless of where it is configured.
- Broker port is configurable (`mqtt_port=%d`).

---

## 2. Path A — redirect the cloud MQTT to a local broker *(fastest; hours–days)*

Reuses the protocol the integration already speaks. Net result: the robot dials
into **your** Mosquitto instead of 3iRobotix, and HA points at that broker.

1. **Stand up a local broker** — Mosquitto on the LAN, TLS listener on 8883 with
   a cert whose chain you control.
2. **Trust your cert on the robot** — replace `/userdata/config/server.crt` with
   your CA/leaf. To survive reboots, also replace `/oem/sysconf/server.crt`
   (the seed `S88scinit` copies from) — either bind-mount `/oem` writable via
   the `/userdata/sys_debug_mode` flag (`S88scinit`), or edit the copy step.
3. **Redirect the broker hostname** — add the broker's FQDN to the robot's
   `/etc/hosts` pointing at the LAN IP, or serve it from the robot's dnsmasq.
   This is host-agnostic, so it works whether the host is in `sysConfig.ini`
   or derived in the binary.
4. **Point HA at the local broker** — the integration's cloud transport now
   terminates on your box; no protocol changes.
5. **Stop OTA/telemetry leakage** — null-route `eu-ota.3irobotix.net` and the
   log/ftp hosts (Path D).

**Effort:** low. **Independence:** the robot still "dials out", but only to your
LAN; no traffic reaches 3iRobotix. **Risk:** low — all changes are file swaps and
name resolution, reversible; `userdata` is wiped by factory reset (recovery).

**To verify on-device before relying on it:** confirm `aiot_client` actually
loads `/userdata/config/server.crt` (vs a fallback), and capture one successful
handshake against the local broker.

---

## 3. Path B — local agent on the nanomsg bus *(clean independence; 1–2 weeks)*

Bypass the cloud protocol entirely. Write a small armhf binary that speaks
nanomsg to `RobotApp`/`everest-server`, issues the everest task commands
(`LocalClean`, `GoDock`, `CustomClean`, …), reads map data
(`QueryDeviceMapBinDataReq`), and exposes a clean LAN API (HTTP or MQTT).

- **Upside:** no broker, no cert games, no dependence on the cloud message
  schema; the robot becomes a self-contained LAN device.
- **Work:** reverse the nanomsg message schema and the everest task/enum set.
  The message names are unobfuscated in `everest-server`/`RobotApp`, and the map
  wire format is already documented in `MAP_DATA.md` (QuickLZ + `RobotMap`
  protobuf) — a substantial head start.
- **Deploy:** cross-compile for RV1126 (armhf, glibc/Buildroot toolchain), run
  from `/userdata`, disable `aiot_client` (or leave it firewalled).

Think of this as a purpose-built "mini-Valetudo" for the everest platform.

---

## 4. Path C — Valetudo port for CRL350 *(best UX; weeks; community-first)*

No CRL350 (RV1126) support exists in Valetudo or DustBuilder — this would be the
first port of this hardware generation (`ROOTING.md §6.6`).

- **Integration seam:** either hook the nanomsg bus (as Path B, cleanest) or
  MITM the `aiot_client` ⇄ `RobotApp` link and speak the cloud MQTT locally
  (Valetudo already has MQTT machinery).
- **Write a Valetudo `Robot` class** for the everest platform, mapping Valetudo
  capabilities (`BasicControl`, `FanSpeed`, `Zone`/`Segment` cleaning, `MapData`,
  `Consumables`) onto the everest tasks.
- **Port the map parser** — reuse the `RobotMap`/QuickLZ work from `MAP_DATA.md`.
- **Deploy on the robot**, disable `aiot_client`, block OTA.

**Payoff:** full Valetudo web UI + MQTT + native HA, zero cloud. **Cost:** a real
project; depends on Path B-level protocol understanding first.

---

## 5. Path D — hardening wins with root *(independent of A/B/C)*

- **Persist access:** `touch /userdata/debug_mode` → OpenSSH on boot
  (`S50sshd`, `PermitRootLogin yes`).
- **Freeze firmware:** null-route `eu-ota.3irobotix.net` (and the `upgrade`
  daemon) so 3iRobotix cannot change behaviour under you.
- **Cut telemetry:** stop `aiot_client`/`log-server` cloud upload; firewall
  `euftp-log.3irobotix.net`.
- **Audit the camera claim empirically:** with root you can observe exactly what
  `everest-server`/`Ai-server` emit, turning the unverifiable on-device-only
  claim in `INVESTIGATION.md §9.3` into a measurement.

---

## 6. Recommendation

For the project goal (eliminate the cloud, keep the integration working):

1. **Do Path A now** — cloud-free local control with code you already have.
2. **Path B** as the upgrade toward true independence (no cloud protocol at all).
3. **Path C** only if you want the Valetudo UI and to publish a port.

Path D hardening applies immediately regardless of which control path you pick.

---

## 7. Verification status

| Claim | Basis | Confirmed? |
|---|---|---|
| Root shell obtainable (UART / creds `root`/`3irobotix`) | `/etc/shadow`, `/etc/inittab` | ✅ from image |
| Firmware not encrypted; extractable offline | `PROTOCOL.md §9.2` | ✅ reproduced |
| `aiot_client` = paho-mqtt/mbedTLS cloud bridge | binary strings | ✅ from image |
| Internal bus = nanomsg | `nn_bind` symbols | ✅ from image |
| Pinned cert = `/userdata/config/server.crt` | `aiot_client` strings + `S88scinit` | ⚠ confirm load path on-device |
| Broker host redirectable via hosts/dnsmasq | `sysConfig.ini` + standard resolver | ⚠ confirm on-device |
| everest task/nanomsg schema (for Paths B/C) | symbol names only | ✗ needs on-device reversing |

---

## 8. References

- `ROOTING.md` — obtaining the root shell (UART, creds, maskrom)
- `PROTOCOL.md §9` — cloud protocol, TLS/pinning, OTA image extraction
- `MAP_DATA.md` — `RobotMap` protobuf + QuickLZ map format (reused by B/C)
- `INVESTIGATION.md §4` — firmware/app architecture and privacy findings
- [Valetudo](https://valetudo.cloud) — cloud-free vacuum firmware project
- [dustbuilder / robotinfo.dev](https://dustbuilder.dontvacuum.me) — robot rooting resources
