# Kärcher RCV5 — Local Control & Rooting Investigation

> **Goal:** Achieve full local control of the RCV5 without dependency on the 3iRobotix cloud
> infrastructure. All findings are from physical inspection of the device and analysis of the
> existing protocol research in `PROTOCOL.md`.
>
> **Date:** April 2026. **Device:** Kärcher RCV5 (EU).

---

## 1. Background and Motivation

The RCV5 has no local control API. All commands and state updates transit the 3iRobotix cloud
MQTT broker (`eu-gamqttaiot.3irobotix.net:8883`). The robot is non-functional if that
infrastructure is unavailable, and all operational data (commands, cleaning sessions, maps)
flows through a platform operated by 3iRobotix (Zhuhai) Co. Ltd., a Chinese company subject
to China's National Intelligence Law.

The existing HA integration (`custom_components/karcher_home_robots/`) already reverse-engineers
the cloud protocol. The goal of this investigation is to eliminate the cloud entirely.

### Why the obvious approach (DNS + local broker) is blocked

A local Mosquitto broker impersonating `eu-gamqttaiot.3irobotix.net` was tested in full.
DNS override works and the TLS handshake completes. However, the robot performs
**application-layer certificate pinning**: after the handshake, it checks the server's public
key against the specific EC P-256 cert stored in `assets/server.bks` inside the APK (password:
`sc2021`, pubkey fingerprint: `2677dc36c9b4507b25a37c1196e814d9`). Without the 3iRobotix
private key, the robot drops the connection before sending a single MQTT byte.

Full investigation details: `PROTOCOL.md §9`.

---

## 2. Partition Layout & Recovery

### OTA image contents (from `PROTOCOL.md §9`)

The OTA image delivered by `eu-cdnallaiot.3irobotix.net` contains:

```
MiniLoaderAll.bin   — primary bootloader (250 KB)
parameter.txt       — partition table
boot.img            — kernel + device tree (7 MB)
rootfs.img          — main OS, squashfs XZ encrypted (97 MB)
```

OTA updates only flash `boot.img` and `rootfs.img`. The bootloader and recovery partitions
are written at the factory and never touched by OTA.

### Recovery partition — confirmed present

**Confirmed observation:** holding the reset button on the robot reverts the firmware to an
earlier version. This proves a separate **recovery partition** exists on the flash, containing
a factory-era firmware image that predates the current OTA version. The bootloader boots from
this partition when the reset sequence is triggered.

The full flash layout is likely:

```
MiniLoaderAll    — primary bootloader
parameter.txt    — partition table
trust.img        — TrustZone / OP-TEE firmware
boot.img         — kernel (updated by OTA)
recovery.img     — factory restore image (older firmware, never updated by OTA)
rootfs.img       — main OS (updated by OTA)
userdata         — maps, config, account data (wiped on reset)
```

> **TODO:** Obtain actual `parameter.txt` content via UART console to confirm partition
> names, offsets, and sizes.

### Implications for bricking risk

The recovery partition significantly reduces bricking risk from software modifications:

| Action | Recovery method |
|---|---|
| Corrupt / modify `rootfs.img` contents | Hold reset button → boots recovery image |
| Bad config, broken cert store, failed patches | Hold reset button |
| Corrupt `boot.img` | Likely needs maskrom + `rkdeveloptool` |
| Corrupt `recovery.img` or bootloader | Maskrom + `rkdeveloptool` required |
| Hardware damage (overvoltage on GPIO) | Not recoverable |

In practice: any modification made to the running filesystem is recoverable by reset.
Only deliberate writes to the bootloader or recovery partitions create a hard-brick risk,
and those require explicit `dd` or `flash_erase` commands targeting those specific partitions.

---

## 3. Ranked Local Control Options

Ordered from least to most invasive. Status reflects progress as of April 2026.

### Option 1 — Cloud relay daemon *(available now, no hardware)*

Run a local process that authenticates to 3iRobotix using existing credentials, subscribes to
the robot's MQTT topics, and re-publishes to a local Mosquitto broker. HA talks to the local
broker. The cloud remains in the loop for one leg but HA never touches 3iRobotix directly.
Enables local buffering, command injection, and traffic inspection.

**Status:** Not yet implemented. The existing `api.py` / `coordinator.py` is ~80% of the way
there — it is a small refactor to split it into a standalone daemon.

---

### Option 2 — Debug connector access *(primary hardware path — in progress)*

**See §3 below.** A 7-pin debug connector was found on the robot body, accessible without
disassembly by removing the water tank. Voltage measurements strongly suggest UART TX/RX on
pins 3 and 4. If confirmed, this provides a root shell path with no permanent modification
to the robot.

**Status:** Connector identified, voltages measured. Awaiting USB-UART adapter to confirm
UART console.

---

### Option 3 — UART root + cert bypass *(depends on Option 2)*

With a root shell obtained via UART:

1. Locate `server.bks` on the live (decrypted) filesystem.
2. Replace with a custom BKS keystore containing a locally-controlled CA cert.
3. Override the MQTT broker hostname via `/etc/hosts` on the robot or by editing
   the MQTT client config.
4. DNS-spoof `eu-gamqttaiot.3irobotix.net` to the local Mosquitto instance (already
   confirmed working from `PROTOCOL.md §9`).

Alternatively, use `LD_PRELOAD` to inject a shared library overriding
`SSL_CTX_load_verify_locations` with a no-op, avoiding any permanent file modification.

**Status:** Blocked on Option 2.

---

### Option 4 — Rockchip maskrom mode *(USB, no shell required)*

The RV1126 supports maskrom boot mode, accessible by shorting specific pins during power-on.
In maskrom mode, `rkdeveloptool` can read/write flash partitions over USB. The `rootfs.img`
partition is squashfs with block-level encryption (key in TrustZone, not recoverable from the
image), so raw flash access does not yield readable filesystem content. The `boot.img`
partition (u-boot + kernel) is not encrypted and could be modified to drop to a root shell
before the encrypted rootfs mounts (`init=/bin/sh` kernel argument).

**Status:** Requires identifying a USB port or maskrom pins on the PCB. No internal
disassembly has been performed yet.

---

### Option 5 — Valetudo port for CRL350 *(long-term, significant effort)*

The CRL-200S (3iRobotix, Allwinner A33, Android) is supported by Valetudo via
[valetudo-crl200s-root](https://github.com/Hypfer/valetudo-crl200s-root). The CRL350
(RV1126, Linux) is a different hardware generation — no existing Valetudo support exists.
Porting would require reverse-engineering the internal serial protocol between the RV1126
main CPU and the motor controller MCU, implementing a robot abstraction layer in Valetudo,
and porting the map processing pipeline.

**Status:** Not started. Depends on first achieving a root shell (Option 2/3) to inspect
the running system and identify the internal protocol.

---

## 3. Debug Connector — Physical Investigation

### Location

The connector is located on the **robot body**, in the recess normally covered by the
water tank. It is **not** the charging interface (charging pads are on the underside of the
robot and are separate). In normal consumer use, the connector is inaccessible with the
water tank attached.

The water tank has a matching plastic housing on its underside with guides for the connector
housing, but **no electrical contacts** — the tank does not use this connector for any
functional purpose.

This placement (hidden in normal use, exposed only by removing a user-accessible component)
is consistent with a factory debug/diagnostic connector, not a user-facing interface.

### Physical description

- Single-row connector, **7 pins**
- Gold spring-loaded contacts (pogo-pin style)
- Protective plastic housing with individual dividers between pins
- Oriented horizontally in the robot body

### Voltage measurements

Measured with robot powered on, multimeter black probe referenced to the **charging pads on
the underside** of the robot (confirmed ground reference). All values DC:

| Pin | Voltage | Interpretation |
|-----|---------|----------------|
| 1   | −0.09 V | **GND** |
| 2   | +3.09 V | VCC 3.3V rail (regulated supply) |
| 3   | +3.21 V | **UART TX** — idle high (GPIO output driver, slightly above rail) |
| 4   | −0.08 V | **UART RX** — input, no internal pull-up, floating low |
| 5   | −0.08 V | GND or USB D− (0V with no host connected) |
| 6   | −0.08 V | GND or USB D+ (0V with no host connected) |
| 7   |  0.00 V | **GND** |

**Key observations:**

- Pin 2 (3.09 V) vs pin 3 (3.21 V): two distinct 3.3V sources. Pin 2 is consistent with a
  regulated power rail; pin 3 is consistent with a GPIO output driver idling high — the
  characteristic resting state of a UART TX line with no data being transmitted.
- Pin 4 at ~0V is consistent with a UART RX input pin with no external pull-up, waiting for
  an external driver.
- Pins 5 and 6 at 0V are consistent with USB D+/D− with no host enumeration in progress.
  Cannot rule out additional GND lines until tested with a USB host.
- Multiple GND pins (1, 4–7 candidates) are normal on debug connectors for noise/return path
  redundancy.

### Hypothesised pinout

```
Pin 1 — GND
Pin 2 — VCC 3.3V
Pin 3 — UART TX  (robot → host)
Pin 4 — UART RX  (host → robot)
Pin 5 — USB D−  (or GND)
Pin 6 — USB D+  (or GND)
Pin 7 — GND
```

UART parameters expected: **115200 baud, 8N1, 3.3V logic** (standard for RV1126).

### Supporting context

- The firmware build string is `3irobotix_CRL350_Dual_Laser_AI_Factory-rv1126-linux-ota-I3.12.26`.
  The `Factory` substring suggests the firmware image is a factory/production build, which
  commonly ships with reduced authentication on debug interfaces.
- The prior generation CRL-200S (Allwinner A33, Android) exposed unauthenticated ADB via
  micro-USB with no password. The same engineering culture at 3iRobotix may apply here.
- The RV1126 UART0 is the primary Linux console on all known RV1126 reference boards.
  Community reports confirm that interrupting u-boot during the boot countdown provides
  access to the u-boot prompt, and that the standard Linux login prompt follows.

---

## 4. Next Steps

### Immediate (hardware)

1. **Acquire a 3.3V USB-UART adapter** — CP2102, CH340G, or FTDI FT232RL. Confirm 3.3V
   logic level before connecting. Required connections: `GND → pin 1`, `RX → pin 3`.
   Do not connect adapter VCC to any robot pin.

2. **Confirm UART TX** — power-cycle robot with adapter connected, `screen /dev/tty.usbserial-* 115200`
   open. Boot log should appear immediately on pin 3.

3. **Attempt interactive console** — once TX confirmed, add `TX → pin 4`. Power-cycle again.
   Interrupt u-boot with any key during countdown. Test login with: no password, `root`,
   `root/root`, `root/3irobotix`, `root/1234`.

4. **Test USB** — if pins 5/6 are USB D+/D−, connect a USB cable to pins 5, 6, and GND.
   Run `lsusb` / `dmesg` on host. An `ADB` or CDC-ACM device would provide an alternative
   shell path.

### If UART shell is obtained

1. Locate the MQTT client binary and `server.bks` asset:
   ```bash
   find / -name "server.bks" 2>/dev/null
   ps aux | grep -i mqtt
   ```
2. Replace `server.bks` with a custom BKS keystore (see `PROTOCOL.md §9` for cert
   generation procedure and known passwords).
3. Edit `/etc/hosts` on the robot to redirect `eu-gamqttaiot.3irobotix.net` to the
   LAN IP running local Mosquitto.
4. Verify full local operation — robot connects to local broker, HA integration works
   unchanged, no outbound traffic to 3iRobotix.

### If login is password-protected

1. At u-boot prompt, append `init=/bin/sh` to kernel boot arguments:
   ```
   => setenv bootargs ${bootargs} init=/bin/sh
   => boot
   ```
   This drops to a root shell before any init process runs, bypassing password authentication.
2. From that shell, change the root password or directly apply the cert bypass above.

---

## 5. Certificate Pinning Bypass — Technical Reference

For reference once shell access is confirmed, three bypass approaches are available, in
order of preference:

**A. Replace server.bks (persistent, clean)**

Generate a BKS keystore containing a local CA cert using the BouncyCastle provider, using
the known keystore password (`sc2021`). Replace the file on the robot. Survives reboots.

**B. LD_PRELOAD override (no file modification)**

```c
// bypass_pin.c — override SSL CA loading with a no-op
#include <openssl/ssl.h>
int SSL_CTX_load_verify_locations(SSL_CTX *ctx, const char *CAfile, const char *CApath) {
    return 1;
}
```

Compile for ARM, inject via `LD_PRELOAD` in the MQTT client launch script. No permanent
modification to the robot binary or assets. Easy to revert.

**C. Frida ARM server (runtime, no persistence)**

Run `frida-server` (ARM Linux build) on the robot. Hook the SSL verify function from the
host. Useful for one-off testing before committing to a permanent approach.

---

## 6. Wider Access-Vector Survey

Beyond the UART path in §3, the following vectors were researched for completeness. Each
lists the underlying assumption, the attack technique, the expected effort, and whether it
is worth attempting before, during, or after the UART path.

### 6.1 Rockchip maskrom — unsigned-code execution (pre-boot)

The RV1126 BootROM implements a Rockusb recovery protocol (USB VID:PID `2207:????`). In
maskrom mode, the host uploads two ARM blobs over USB: a DDR init stub (`ddrplug`) and a
flash-access stub (`usbplug`). The BootROM does **not** verify these blobs unless secure
boot eFuses have been burned.

**The critical question for RCV5 is whether 3iRobotix burned the secure-boot eFuses at
the factory.** The available evidence suggests they did **not**:

- Rockchip's own application note advises that if eFuse programming is not required, the
  eFuse power pin should be tied to GND. Burning eFuses is an extra factory step with cost
  and yield implications; vendors routinely skip it.
- The CRL-200S prior generation shipped with unauthenticated ADB, indicating 3iRobotix's
  engineering baseline does not prioritise secure-boot hardening.
- The `Factory` substring in the build-ID and the presence of a hidden debug connector
  both suggest a development-friendly rather than production-locked security posture.
- Pen Test Partners' writeup on the Rockchip boot flow confirms that on eFuse-unburned
  RK devices, maskrom accepts arbitrary unsigned code over the Rockusb protocol.

**If the eFuses are unburned:** `rkdeveloptool` can dump every partition (including the
encrypted rootfs ciphertext), write arbitrary `boot.img`, and chain-load a modified
`init=/bin/sh` u-boot argument — all without ever obtaining the TrustZone decryption key.
This is more invasive than UART (requires PCB access + shorting a flash-disable pin to
enter maskrom) but gives a stronger primitive: **write access to every unencrypted
partition** including `boot.img`.

**If the eFuses are burned:** maskrom still enters, but any uploaded blob is signature-
checked against the key in eFuse. Unsigned execution is blocked. This would leave only
UART and fault-injection as options.

**Verification path:** once UART access is obtained, read `/sys/class/misc/rockchip-otp*`
or run Rockchip's `rk_provision_tool` / `efuse-read` from u-boot to dump eFuse contents.
If the Secure-Boot bits (`SECURE_BOOT_EN`) are 0, maskrom is wide open.

### 6.2 Voltage glitching / fault injection (SoC-level)

If the eFuses **are** burned and UART is padlocked, the remaining hardware path is to
glitch the signature check. Voltage fault injection works by briefly pulling the core
rail below spec during the RSA-verify loop, skipping the branch-if-invalid. This is a
well-published technique against Allwinner, Amlogic, and early Rockchip parts.

**Not recommended as a first step.** Requires a ChipWhisperer / PicoEMP-class glitcher
(≈ €300–€1000), sub-µs trigger timing on the SPI-NOR / eMMC command stream, and a decap
or PCB tap on the VDD_CORE rail of the RV1126. Published glitch timings for RV1126
specifically do not appear in public literature — parameter search would take weeks.
Only worth considering if both 6.1 and UART fail.

### 6.3 eMMC / NAND chip-off

Desoldering the on-PCB flash and reading it on an eMMC programmer (EasyJTAG, Medusa Pro)
yields the raw partition images. The `rootfs.img` partition is squashfs-XZ with
block-level encryption whose key lives in the RV1126 TrustZone. The chip-off dump is
therefore **identical ciphertext to what `rkdeveloptool` would produce** (see 6.1) —
chip-off adds no information over maskrom dump unless maskrom is itself locked.

Chip-off is destructive (the device is off-network during the operation, and re-balling
the BGA for reinstallation requires lab-grade rework). Not worth it unless every other
path fails.

### 6.4 WiFi / BLE pairing flow

The RCV5 setup uses Rockchip's standard WiFi provisioning over a temporary AP the robot
hosts during onboarding. The Karcher Home app connects to this AP and posts SSID/PSK to
a local HTTP endpoint on the robot. Research question: does that endpoint expose more
than the documented provisioning fields?

**Parallel precedents:**

- Ecovacs Deebot X1/T10/T20/T30 (CISA ICSA-25-135-19): provisioning BLE pairing PIN was
  a hardcoded `888888`; reachable from 450 feet.
- DJI Romo (2026 incident): authenticated device tokens were not topic-scoped at the
  MQTT broker, so one compromised token granted subscription to every device's feeds.
- Tuya-based robots: provisioning AP typically exposes a `/v1/device/upgrade` or
  `/v1/device/config` endpoint reachable only during the ~60 s pairing window.

**Not yet tested on RCV5.** Worth doing: during a factory reset, scan for the robot's
AP, enumerate open TCP ports, capture the Karcher app's provisioning traffic with
mitmproxy. Effort: low, risk: zero. Could reveal an unauthenticated HTTP endpoint that
exposes a shell or config write primitive.

### 6.5 3iRobotix cloud — platform-wide weaknesses

The DJI Romo incident is architecturally identical to the 3iRobotix platform:

| Aspect | DJI Romo | 3iRobotix (assumed) |
|---|---|---|
| Transport | MQTT over TLS | MQTT over TLS |
| Auth | Per-device token | Per-device token |
| Topic scoping | **None** — any token could subscribe to any device | Unknown — needs testing |
| Client cert | No | Yes (`iot_dev.p12`, password `hj2WtyHYYEvBTxDb`) |

The presence of a client certificate on 3iRobotix helps, but the *broker ACL* is the
real control. A test is possible **today, from the cloud leg**, without any rooting:

1. Extract `iot_dev.p12` from the APK (already done; see `PROTOCOL.md §9`).
2. Connect to `eu-gamqttaiot.3irobotix.net:8883` using paho-mqtt with that cert.
3. Attempt `SUBSCRIBE` to wildcard topic `#` or to a topic belonging to a device that
   is **not** ours (requires knowing another device ID — guessable or via the app's
   REST API).
4. If the broker permits the subscription: same class of vulnerability as DJI Romo.

This test is **ethically and legally sensitive** — must only be performed against our
own device. Using wildcard subscription or attempting to enumerate other customers'
devices would cross into unauthorised access. Stick to publishing/subscribing to our
own topics and observing whether the broker enforces isolation.

### 6.6 Shared-platform rooting (CRL350 siblings)

The CRL350 reference hardware is not an exclusively Kärcher product. 3iRobotix licenses
it to multiple brands (Proscenic, Kyvol, and others use the earlier CRL-200S; the CRL350
OEM list is not yet mapped). If a sibling brand sells the same hardware with an easier
entry point — for example an unauthenticated ADB port, or an unlocked OTA with signed
images we could lift — the root payload is directly portable.

**Action:** search `robotinfo.dev` and `dustbuilder.dontvacuum.me` for CRL350-derived
products. At time of writing, no CRL350 entry exists in the Valetudo or DustBuilder
supported-robot lists — we would be the first public rooting of this hardware
generation.

### 6.7 OTA server MITM / downgrade

OTA image is delivered over HTTPS from `eu-cdnallaiot.3irobotix.net`. If we can MITM
this leg (pinning is identical to the MQTT broker — same EC P-256 cert), we could serve
a modified `rootfs.img`. Two problems:

1. Same cert-pinning wall as the MQTT path. Bypass requires either a root shell (which
   is what we are trying to obtain in the first place) or CA-store subversion via UART.
2. The OTA payload is squashfs-XZ-encrypted with the TrustZone key. Even if we MITM'd
   the transfer, we cannot produce a valid replacement image without the key.

**Rollback attack** (push an older, more vulnerable OTA) is blocked by the same
encryption and signing scheme.

**Conclusion:** OTA MITM is strictly worse than UART; no unique value.

### 6.8 Side channels (low priority)

- **Power analysis (SPA/DPA)** on the TrustZone key during rootfs decryption: feasible
  in principle (Riscure / ChipWhisperer territory), requires deep expertise, probably
  weeks of work. Only relevant if every other path fails.
- **Cold-boot RAM dump**: RV1126 DDR is on-package; not accessible without decap.
- **JTAG**: RV1126 exposes JTAG on GPIOs that are typically mux'd for other functions
  in shipping products. Would require PCB-level probing after UART is ruled out.

### 6.9 Ranked summary of new vectors

| Rank | Vector | Prereq | Effort | Expected yield |
|------|--------|--------|--------|----------------|
| 1 | UART console (§3) | 3.3V TTL adapter | low | root shell |
| 2 | Maskrom + `rkdeveloptool` (6.1) | PCB access, secure boot unburned | low-medium | full flash read/write |
| 3 | WiFi AP provisioning attack (6.4) | app + mitmproxy during pairing | low | possible unauth endpoint |
| 4 | MQTT broker ACL test (6.5) | extracted client cert (already have) | low | possible cross-tenant read |
| 5 | CRL350 sibling-brand port (6.6) | identify OEM cousin | low-medium | alternative entry point |
| 6 | Voltage glitching (6.2) | glitcher, lab time | high | boot-verify bypass if eFuses burned |
| 7 | Chip-off eMMC dump (6.3) | rework station | high, destructive | ciphertext only |
| 8 | Side channels (6.8) | specialist kit | very high | TrustZone key |

**Immediate action items derived from this survey** (none of which block the UART path):

- Pair the robot while capturing its provisioning AP traffic with mitmproxy; enumerate
  open ports on the robot during the pairing window (§6.4).
- Check whether the 3iRobotix MQTT broker enforces topic-level ACLs by subscribing with
  the extracted device cert only to our own device's topics and observing whether the
  broker rejects out-of-scope subscriptions (§6.5).
- Once UART shell is obtained, immediately read eFuse state (§6.1 verification) to
  determine whether maskrom is open as a secondary path.

---

## 7. References

- `PROTOCOL.md §9` — Local control investigation (DNS spoof, Mosquitto, TLS analysis,
  APK cert extraction)
- `INVESTIGATION.md §6f` — Local attack surface assessment
- `INVESTIGATION.md §4` — Firmware format, squashfs encryption, TrustZone key
- [valetudo-crl200s-root](https://github.com/Hypfer/valetudo-crl200s-root) — 3iRobotix
  CRL-200S rooting tooling (prior generation, different SoC)
- [codetiger/VacuumRobot](https://github.com/codetiger/VacuumRobot) — CRL-200S protocol
  reverse engineering
- [OWASP MASTG-TECH-0012](https://mas.owasp.org/MASTG/techniques/android/MASTG-TECH-0012/)
  — Certificate pinning bypass techniques
- [Pen Test Partners — A dive into the Rockchip Bootloader](https://www.pentestpartners.com/security-blog/a-dive-into-the-rockchip-bootloader/)
  — Rockusb / maskrom protocol, unsigned `ddrplug`/`usbplug` upload
- [3mdeb — Enabling Secure Boot on RockChip SoCs](https://blog.3mdeb.com/2021/2021-12-03-rockchip-secure-boot/)
  — eFuse burning procedure and why most vendors skip it
- [Rockchip Secure Boot Application Note v1.9](http://resource.milesight-iot.com/files/Rockchip-Secure-Boot-Application-Note-V1.9.pdf)
  — Official guidance: tie eFuse VCC to GND when not burning
- [CISA ICSA-25-135-19](https://www.cisa.gov/news-events/ics-advisories/icsa-25-135-19)
  — Ecovacs Deebot BLE pairing (PIN 888888, 450 ft range)
- [Malwarebytes — DJI Romo 7000-device hijack](https://www.malwarebytes.com/blog/news/2026/02/hobby-coder-accidentally-creates-vacuum-robot-army)
  — MQTT broker ACL failure, architectural parallel to 3iRobotix
- [Synacktiv — How to voltage fault injection](https://www.synacktiv.com/en/publications/how-to-voltage-fault-injection)
  — VFI methodology, applicable to secure-boot bypass on locked SoCs
- [VoidStar — UART Discovery and Firmware Extraction via U-Boot](https://voidstarsec.com/blog/uart-uboot-and-usb)
  — Methodology for the path planned in §3–§4
