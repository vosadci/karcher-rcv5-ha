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
key against the specific EC P-256 cert stored in `assets/server.bks` inside the APK (keystore
password and pubkey fingerprint redacted — see `PROTOCOL.md §9`). Without the 3iRobotix
private key, the robot drops the connection before sending a single MQTT byte.

Full investigation details: `PROTOCOL.md §9`.

---

## 2. Partition Layout & Recovery

### OTA image contents (from `PROTOCOL.md §9`)

The OTA image delivered by `eu-cdnallaiot.3irobotix.net` contains:

```
MiniLoaderAll.bin   — primary bootloader (~246 KB)
parameter.txt       — partition table
boot.img            — kernel + device tree, U-Boot FIT (7 MB)
rootfs.img          — main OS: UBI volume containing an XZ SquashFS — NOT encrypted (97 MB)
```

OTA updates only flash `boot.img` and `rootfs.img`. The bootloader and recovery partitions
are written at the factory and never touched by OTA.

> **Correction (2026-07): `rootfs.img` is not encrypted.** It was previously described
> as "squashfs XZ encrypted" with a TrustZone key. That is wrong. It is a UBI image
> (256 KiB PEBs) wrapping a plain **XZ SquashFS**; stripping the UBI layer
> (`ubireader_extract_images`) yields a cleartext filesystem — 2,439 files extracted,
> `/etc/shadow` included. The whole firmware is auditable **offline from the OTA image**,
> with no device access required. Consequences propagate through the Ranked Options below
> (Option 4), §6.1, §6.3, §6.7 and §6.8 — all corrected. See `PROTOCOL.md §9.2` for the
> reproduction.
>
> **Immediate implication:** the root login is already known without any hardware — cracking
> `/etc/shadow`'s MD5-crypt hash yields a working `root` password (redacted here — a short
> dictionary word, not our infrastructure's credential), and `/etc/inittab` leaves an
> always-on `getty` on `ttyFIQ0`. SSH (`/etc/init.d/S50sshd`, OpenSSH, `PermitRootLogin yes`)
> and USB ADB (`S50usbdevice`) are present but gated behind a `/userdata/debug_mode` flag file
> on the writable `userdata` partition.
> **Confirmed on the shipping `I3.12.90` firmware (2026-08-04):** the same password still
> works (hash merely re-salted — see the CLOSED version-gap box in §3), and the
> `getty`/SSH/ADB gating is unchanged.

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

## Ranked Local Control Options

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
disassembly by removing the water tank. Voltage measurements suggest UART TX/RX on
pins 2 and 4 (see the corrected analysis in §3). If confirmed, this provides a root shell
path with no permanent modification to the robot.

**Status:** Connector identified, voltages measured. Awaiting USB-UART adapter to confirm
UART console.

---

### Option 3 — UART root + cert bypass *(depends on Option 2)*

With a root shell obtained via UART:

1. Locate `server.bks` on the live filesystem (the rootfs is plain XZ SquashFS, not
   encrypted — it can also be read straight from the OTA image without a shell).
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
In maskrom mode, `rkdeveloptool` can read/write flash partitions over USB. A raw dump of the
`rootfs.img` partition is **readable** — it is a UBI-wrapped XZ SquashFS, not encrypted — so
flash access yields the full filesystem (same content as the OTA image). Writing modified
`boot.img` (u-boot + kernel) to drop to a root shell (`init=/bin/sh`) is possible **only if
the verified-boot eFuses are unburned** (see §6.1); the barrier to modification is signature
verification, not encryption. Reads are unconstrained either way.

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

| Pin | Voltage | Interpretation (corrected 2026-07) |
|-----|---------|----------------|
| 1   | −0.09 V | floating / GND candidate (noisy near-0, not the clean 0 of pin 7) |
| 2   | +3.09 V | **UART TX** — idles high at V_OH, just below the rail |
| 3   | +3.21 V | **VCC 3.3 V rail** — highest and stiffest; the regulated supply |
| 4   | −0.08 V | **UART RX** candidate — floating input, no pull-up |
| 5   | −0.08 V | floating logic I/O (RX / boot / reset / USB D± candidate) |
| 6   | −0.08 V | floating logic I/O (RX / boot / reset / USB D± candidate) |
| 7   |  0.00 V | **GND** — a clean 0.00 is a solid ground reference |

**Key observations (corrected):**

- Pin 2 (3.09 V) vs pin 3 (3.21 V): the earlier revision had these backwards. A UART TX line
  is a push-pull output **powered from the 3.3 V rail**, so its idle-high level (V_OH) cannot
  exceed that rail — it sits *at or just below* it. The highest, stiffest reading is therefore
  the rail itself: **pin 3 (3.21 V) = VCC**, and **pin 2 (3.09 V) = TX** idling ~0.1 V under
  the rail. The prior claim that pin 3 "idles slightly above rail" is not physically possible
  for a driver fed from that rail.
- **This VCC/TX assignment cannot be settled by a static multimeter reading alone.** Confirm
  empirically: meter pin 2 while powering the robot on — **TX dips and jitters** as the boot
  log streams, then settles high; **VCC (pin 3) stays rock-steady**. That flicker uniquely
  identifies TX.
- Pins 1, 4, 5, 6 all read ≈ −0.08 V — high-impedance/floating inputs (meter noise), not a
  solid ground. Only **pin 7 reads a clean 0.00 V**, so pin 7 is the reliable GND; pin 1 is a
  GND candidate but should be buzzed for continuity before use. **UART RX** is one of the
  floating pins (4/5/6) — it floats near 0 with no pull-up; identify it as the one that makes
  the device respond when bytes are sent at the right baud.
- Do **not** assume pins 5/6 are USB D±; that was a guess. They are just as likely RX, boot-
  select, or reset. Confirm with a USB host / logic analyser before treating them as USB.

### Hypothesised pinout

```
Pin 1 — GND candidate (buzz for continuity; noisier than pin 7)
Pin 2 — UART TX  (robot → host)   ← idles 3.09 V, confirm by boot-time flicker
Pin 3 — VCC 3.3V (leave disconnected)
Pin 4 — UART RX  (host → robot)   ← floating-input candidate
Pin 5 — floating I/O (RX / boot / reset / USB D± — unconfirmed)
Pin 6 — floating I/O (RX / boot / reset / USB D± — unconfirmed)
Pin 7 — GND  (clean 0.00 V — use this as the ground reference)
```

UART parameters: **8N1, 3.3 V logic**. Baud: try **1500000** first (the RV1126 FIQ-debugger
console default; `getty` in the firmware runs on `ttyFIQ0` with baud `0` = keep-current), then
fall back to **115200** if the boot log is garbled.

### Supporting context

- The firmware build string is `3irobotix_CRL350_Dual_Laser_AI_Factory-rv1126-linux-ota-I3.12.26`.
  The `Factory` substring suggests the firmware image is a factory/production build, which
  commonly ships with reduced authentication on debug interfaces.

  > **Version gap — CLOSED 2026-08-04.** The static findings here were originally derived from
  > the `I3.12.26` **factory baseline** (obtained by passing `curVersionCode: "0"` to the OTA
  > endpoint, `PROTOCOL.md §9`). A live RCV5 runs **`I3.12.90`** (built 2025-07-09) — two years
  > eight months later — so every credential, layout, and gating claim below was flagged as
  > possibly stale. **`I3.12.90` has now been extracted and audited (procedure in
  > `PROTOCOL.md §9.3`), and the entire software attack surface is unchanged.** Point-by-point
  > confirmation on the shipping firmware:
  >
  > | Finding (from `.26`) | State on `.90` |
  > |---|---|
  > | Root login (password redacted) | **Still valid.** Hash merely re-salted between builds; reproduced exactly with the known password and the new salt — same password, fresh Buildroot salt. |
  > | Always-on UART `getty` on `ttyFIQ0` | **Unchanged** — active `::respawn` line in `/etc/inittab`, no debug gate. |
  > | SSH gated behind `/userdata/debug_mode`, `PermitRootLogin yes` | **Unchanged** (`S50sshd`, `sshd_config`). |
  > | USB ADB gated behind `debug_mode` | **Unchanged** (`S50usbdevice`). |
  > | `debug_mode` auto-enable `touch` line | **Still commented out** in `S88scinit` — flag is not auto-created. |
  > | Broker cert pin `/oem/sysconf/server.crt` | **Byte-identical key** (fingerprint redacted) — same as `.26` and the APK's `server.bks`; self-signed `*.3irobotix.net`, valid 2021-12-01 → 2031-11-29. Cert-replace bypass (§5-A) unchanged. |
  > | Cloud bridge `aiot_client.bin` = mbedTLS | **Unchanged** (now carries TLS 1.3 symbols); statically linked libcurl+libssh for outbound SFTP/log/OTA, no inbound shell. |
  > | OS userland | **Unchanged** — Buildroot 2018.02-rc3, BusyBox. |
  >
  > **Net: the 2y8m firmware jump hardened nothing reachable from software.** The only claims
  > still device-only (not settleable from any OTA image) are the verified-boot **eFuse** state
  > (§6.1) and the physical partition table — those need UART/maskrom on hardware. New non-gating
  > detail from the `.90` audit (binary inventory, config identity) is in `PROTOCOL.md §9.3`.
- The prior generation CRL-200S (Allwinner A33, Android) exposed unauthenticated ADB via
  micro-USB with no password. The same engineering culture at 3iRobotix may apply here.
- The RV1126 UART0 is the primary Linux console on all known RV1126 reference boards.
  Community reports confirm that interrupting u-boot during the boot countdown provides
  access to the u-boot prompt, and that the standard Linux login prompt follows.

---

## 4. Next Steps

### Immediate (hardware)

1. **Acquire a 3.3V USB-UART adapter** — FT232R or CP2102/CP2104 preferred (they clock the
   1.5 Mbaud console reliably; a CH340 may not lock 1.5 M — 115200 fallback still works).
   Confirm 3.3 V logic before connecting. Required connections: `adapter GND → pin 7`,
   `adapter RX → pin 2` (robot TX). **Leave pin 3 (VCC) disconnected** — do not connect
   adapter VCC to any robot pin.

2. **Confirm UART TX** — power-cycle the robot with the adapter connected and a terminal open
   on the **call-out** device (macOS: `/dev/cu.usbserial-*`, not `/dev/tty.*`):
   `picocom -b 1500000 /dev/cu.usbserial-XXXX` (fall back to `115200`). The boot log should
   stream from pin 2. Sanity check before soldering: metering pin 2 during power-on shows the
   TX flicker; pin 3 (VCC) stays flat.

3. **Attempt interactive console** — once TX is confirmed, add `adapter TX → pin 4` (the most
   likely RX; if silent, try pins 5 then 6). Power-cycle again. The root login is already known
   from the firmware image (cracked from `/etc/shadow`, redacted here — see §2). If a login
   prompt does not appear, interrupt u-boot during the countdown and append `init=/bin/sh`
   (see below).

4. **Test USB (unconfirmed)** — pins 5/6 as USB D± is a *guess*, not established. If a logic
   analyser or `dmesg`/`lsusb` probe confirms them as D+/D−, an ADB or CDC-ACM gadget would be
   an alternative shell path — but note the firmware only starts `adbd` when
   `/userdata/debug_mode` exists (`S50usbdevice`), which itself needs prior root.

### If UART shell is obtained

1. Locate the MQTT client binary and `server.bks` asset:
   ```bash
   find / -name "server.bks" 2>/dev/null
   ps aux | grep -i mqtt
   ```
2. Replace `server.bks` with a custom BKS keystore (see `PROTOCOL.md §9` for the cert
   generation procedure).
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

For reference once shell access is confirmed, several bypass approaches are available.
See `LOCAL_CONTROL.md §1` for the full architecture and `§2` for the end-to-end
broker-redirect procedure.

> **Note (2026-07):** `server.bks` is the **Android app's** keystore. On the **robot**,
> the cloud bridge `aiot_client.bin` uses **mbedTLS** (not OpenSSL) and verifies the broker
> against a PEM file: **`/userdata/config/server.crt`** (seeded from `/oem/sysconf/server.crt`
> by `S88scinit`). Therefore approach A below is the robot-side method; the OpenSSL
> `LD_PRELOAD` in approach B does **not** affect `aiot_client` (wrong TLS library).

**A. Replace the robot's broker cert (persistent, clean)**

Replace `/userdata/config/server.crt` with your own CA/leaf (PEM). To survive reboots, also
replace the seed `/oem/sysconf/server.crt` (bind-mount `/oem` writable via the
`/userdata/sys_debug_mode` flag, or edit the `S88scinit` copy step), since `S88scinit`
re-copies `sysconf → config` on every boot. Then redirect the broker hostname via the
robot's `/etc/hosts` or dnsmasq to your local Mosquitto.

**B. LD_PRELOAD override (OpenSSL processes only — NOT `aiot_client`)**

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

**If the eFuses are unburned:** `rkdeveloptool` can dump every partition (the rootfs dump is
readable — plain UBI+XZ SquashFS, no decryption needed), write arbitrary `boot.img`, and
chain-load a modified `init=/bin/sh` u-boot argument. This is more invasive than UART
(requires PCB access + shorting a flash-disable pin to enter maskrom) but gives a stronger
primitive: **write access to every partition** including `boot.img`.

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
yields the raw partition images. The `rootfs.img` partition is UBI-wrapped XZ SquashFS and is
**readable** (not encrypted). The chip-off dump is therefore **identical, readable content to
what `rkdeveloptool` would produce** (see 6.1) — and, for that matter, to the OTA image — so
chip-off adds no information over a maskrom dump unless maskrom is itself locked. It has no
advantage for reading the firmware.

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
| Client cert | No | Yes (`iot_dev.p12`, password redacted — see `PROTOCOL.md §9`) |

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
2. The OTA payload is **not encrypted** (plain UBI+XZ SquashFS), so we can read and modify
   its contents freely. The real barrier is **image signing / verified boot**: an OTA the
   bootloader will accept must carry a valid RKFW/FIT signature (`sha256,rsa2048`). Without
   the signing key, a modified `rootfs.img` is rejected on flash **if the eFuses are burned**
   (§6.1). If they are unburned, a modified image could in principle be accepted — but at that
   point maskrom write (§6.1) is the simpler route than MITM.

**Rollback attack** (push an older, more vulnerable OTA) is gated by the same signing/anti-
rollback scheme, not by encryption.

**Conclusion:** OTA MITM is strictly worse than UART or maskrom; no unique value.

### 6.8 Side channels (low priority)

- **Power analysis (SPA/DPA):** not applicable to the rootfs — it is not encrypted, so
  there is no per-block decryption to attack. The only key-bearing operation is the
  verified-boot RSA signature check (relevant only for *writing* modified images on an
  eFuse-burned unit), and that is better attacked by fault injection (§6.2) than by DPA.
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
| 7 | Chip-off eMMC dump (6.3) | rework station | high, destructive | readable flash (no gain over maskrom/OTA) |
| 8 | Side channels (6.8) | specialist kit | very high | verified-boot signing key (write-only; only if eFuses burned) |

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
- `INVESTIGATION.md §4` — Firmware format (UBI + XZ SquashFS, not encrypted)
- `PROTOCOL.md §9.2` — OTA image extraction (reproduction; rootfs is not encrypted)
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
