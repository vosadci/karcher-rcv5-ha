# Product Requirements Document
## Kärcher RCV5 — Home Assistant Integration

**Version:** 0.1.x  
**Date:** March 2026  
**Status:** Active

---

## 1. Background

The Kärcher RCV5 is a robot vacuum with a mopping attachment, sold in the EU, US, and CN markets. It has no official Home Assistant integration, no local control API, and no published cloud protocol. The only supported interface is the proprietary Kärcher Home Robots mobile app, which communicates with a cloud platform operated by 3iRobotix (Zhuhai) Co. Ltd.

This integration reverse-engineers that cloud protocol to expose the robot in Home Assistant and, optionally, Apple Home via Matter.

---

## 2. Goals

- Allow users to control the Kärcher RCV5 from Home Assistant with feature parity to the official app for core functions.
- Provide real-time state updates (not just on-demand polling).
- Support Apple Home via the Home Assistant Matter Hub bridge.
- Work reliably with the existing cloud platform without requiring hardware modification or custom firmware.

## 3. Non-Goals

- Local control (no open TCP ports; certificate pinning; encrypted firmware — not possible today).
- Support for Kärcher models other than the RCV5 (untested; may work).
- Replacing the official app (credentials are still managed there).
- Offline / cloud-independent operation.

---

## 4. Users

Single intended user type: a Home Assistant user who owns a Kärcher RCV5 and wants to integrate it into their smart home. They are expected to:

- Have an existing Home Assistant installation (HA OS, Container, or Supervised).
- Have a Kärcher Home Robots app account with the RCV5 set up.
- Optionally, use Home Assistant Matter Hub to bridge to Apple Home.

---

## 5. Requirements

### 5.1 Functional

| ID | Requirement | HA | Apple Home |
|----|-------------|:--:|:----------:|
| F-01 | User can start, pause, stop, and return the robot to its dock. | ✓ | ✓ |
| F-02 | User can view battery level in real time. | ✓ | ✓ |
| F-03 | User can select which room to clean, or clean all rooms. | ✓ | ✓ |
| F-04 | User can set fan speed (suction level): Silent, Standard, Medium, Turbo. | ✓ | ✓ |
| F-05 | User can set cleaning mode: Vacuum, Vacuum and Mop, Mop. | ✓ | ✓ |
| F-06 | User can set mop water level: Low, Medium, High. | ✓ | ✓ |
| F-07 | User can view area cleaned and time elapsed for the current session. | ✓ | — |
| F-08 | A fault indicator is visible when the robot reports an error in an idle state. | ✓ | — |
| F-09 | State updates reflect robot reality within ~2 seconds under normal conditions. | ✓ | ✓ |
| F-10 | Multiple robots on the same or different accounts can be added as separate entries. | ✓ | ✓ |
| F-11 | Re-authentication is possible without removing and re-adding the integration. | ✓ | — |

### 5.2 Constraints

| ID | Constraint |
|----|------------|
| C-01 | Cloud-only: all commands and state updates go through the Kärcher/3iRobotix cloud. |
| C-02 | Credentials (email + password) must be stored to support token refresh after expiry. |
| C-03 | The integration must not block the Home Assistant event loop. |
| C-04 | Room list is sourced from the stored map on the cloud; unavailable if no map exists. |
| C-05 | Fan speed is unavailable in Mop-only mode; water level is unavailable in Vacuum-only mode. |
| C-06 | The fault indicator is suppressed during cleaning and while docked (transient warnings are normal in those states). |

### 5.3 Non-Functional

| ID | Requirement |
|----|-------------|
| N-01 | State updates via MQTT push within ~2 seconds; 30-second polling fallback. |
| N-02 | Integration setup/teardown must not hang HA startup or shutdown. |
| N-03 | HACS-compatible packaging (manifest.json, hacs.json, versioned releases). |
| N-04 | Automated test coverage for all entities, config flow, coordinator, and integration lifecycle. |

---

## 6. Entities

| Entity | Type | HA | Apple Home | Description |
|--------|------|----|------------|-------------|
| `vacuum.<name>` | StateVacuumEntity | ✓ | ✓ | Primary control: start, pause, stop, return, fan speed |
| `sensor.<name>_battery` | SensorEntity | ✓ | ✓ | Battery % |
| `sensor.<name>_cleaning_area` | SensorEntity | ✓ | — | Area cleaned this session (m²) |
| `sensor.<name>_cleaning_time` | SensorEntity | ✓ | — | Time cleaning this session (min) |
| `binary_sensor.<name>_error` | BinarySensorEntity | ✓ | — | Fault indicator (on = problem) |
| `select.<name>_room` | SelectEntity | ✓ | ✓ | Room selection; "All rooms" or named room |
| `select.<name>_cleaning_mode` | SelectEntity | ✓ | ✓ | Vacuum / Vacuum and Mop / Mop |
| `select.<name>_water_level` | SelectEntity | ✓ | ✓ | Mop water level; unavailable in Vacuum mode |

---

## 7. Configuration Flow

| Step | Input | Notes |
|------|-------|-------|
| 1. Region | EU / US / CN | Determines which cloud server to connect to |
| 2. Credentials | Email, password | Validated against Kärcher cloud |
| 3. Device | Select from account | Skipped if only one device |

Config entry stores: region, email, password, device ID, device SN, device nickname.

---

## 8. Risks and Limitations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Kärcher/3iRobotix changes cloud API | Medium | High | Monitor for breakage; pin library version |
| Token expiry causes outage | Low | Medium | Re-auth flow implemented |
| MQTT push unavailable | Low | Low | 30-second polling fallback |
| Robot map unavailable (no rooms) | Medium | Low | Room select hidden; all-rooms clean still works |
| Firmware OTA changes protocol | Low | High | Protocol documented in [PROTOCOL.md](PROTOCOL.md); no mitigation |
| Cloud service discontinuation | Low | Critical | No mitigation possible (cloud-only) |
