# 01 — Vision and Scope

## 1. Problem statement

The Kärcher RCV5 has no official Home Assistant integration, no local control
API, no open TCP ports, encrypted firmware, and MQTT broker certificate pinning
enforced at the application layer on the device. Control is only possible via
the 3iRobotix cloud. A working integration exists (`custom_components/karcher_home_robots`)
but has been grown ad-hoc on top of a third-party library (`karcher-home`)
with known bugs that must be worked around through private-API access. The
objective of this rewrite is to replace that code with a production-grade
integration that is clean, typed, documented, fully tested, and free of
third-party private-API dependencies.

## 2. Users and stakeholders

- **Primary user:** a Home Assistant operator who owns one or more RCV5 robots
  and wants full control, state observability, and Apple Home compatibility.
- **Secondary user:** a contributor or reviewer auditing the integration for
  HACS Silver quality scale and for security posture before merging.
- **Platform stakeholders** (outside the integration's control): the Kärcher
  cloud account holder, 3iRobotix platform, HA Core maintainers.

## 3. Goals

G1. Full local-facing parity with the current integration at feature-complete
    state: vacuum control, battery/area/time sensors, error indicator,
    room/mode/water selects, Matter-compatible room exposure.

G2. No private-API access to any third-party Python package. The cloud protocol
    is re-implemented in a dedicated, typed, in-tree client.

G3. Meet HACS Silver quality requirements on the first public release:
    config-flow, reauth, diagnostics, full test coverage, integration-type
    declared correctly.

G4. Every behaviour traceable from requirement (`02-requirements.md`) through
    architecture (`04-architecture.md`) to a test (`06-test-strategy.md`).

G5. Reproducibility: a maintainer with no prior context can run the test
    suite, read the ADRs, and continue development within one working day.

## 4. Non-goals

NG1. Local control or offline operation. The cloud constraint is structural
     and irremovable without device rooting (out of scope, see
     `doc/ROOTING.md`).

NG2. Support for Kärcher models other than RCV5. The protocol may be similar
     but mappings, work-mode values and feature availability are unverified.

NG3. Mobile-app replacement. Credential creation and account management
     remain in the Kärcher app.

NG4. OTA interception, blocking or firmware modification.

NG5. Historical session storage. The REST API does not expose session history
     in a form the integration can consume.

## 5. MVP definition (Phase 1 exit criterion)

| Entity | Capability |
|---|---|
| `vacuum.<name>` | `start`, `stop`, `pause`, `return_to_base`, `locate` commands; `activity` property reflecting Cleaning / Paused / Returning / Docked / Idle / Error |
| `sensor.<name>_battery` | Battery percentage, updated on MQTT push |
| `binary_sensor.<name>_error` | Error indicator per §4.4 of `02-requirements.md` |

Excluded from MVP, deferred to later phases:
- Room selection and `app_segment_clean` (Phase 3)
- Cleaning-area and cleaning-time sensors (Phase 2)
- Cleaning-mode, fan-speed, water-level selects (Phase 2)
- Diagnostics (Phase 4)
- Map image (Phase 5, if at all)

## 6. Success criteria

S1. All Phase-1 entities respond to a state change on the robot within 2 s
    (MQTT push) and within 30 s (polling fallback).

S2. Integration recovers automatically from MQTT disconnect, HA restart, and
    Kärcher-cloud transient outage, without user intervention, when the
    cause clears.

S3. Credentials never appear in any log line at any severity and never on
    disk outside HA's encrypted config-entry store.

S4. Test suite passes on HA 2026.1.3 on CI, with
    ≥ 90 % line coverage and ≥ 85 % branch coverage on the integration
    package.

S5. `ruff check`, `ruff format --check`, `mypy --strict` and `pytest` all
    succeed on a clean checkout with no warnings.

S6. No `_`-prefixed attributes of third-party packages are imported or
    accessed anywhere in the integration package. Validated by a CI grep.

S7. HACS validation workflow passes; `manifest.json` declares the quality
    scale tier that actually matches the implemented features.

## 7. Out-of-scope explicit list

See `03-constraints-and-deltas.md` §7 for the authoritative list. Any request
that falls under that list must be rejected at triage or deferred to a future
major version.

## 8. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 3iRobotix protocol change breaks the in-tree client | Medium | High | Keep `05-protocol-reference.md` pointer to `doc/PROTOCOL.md` current; integration test harness replays recorded traffic |
| Kärcher cloud outage | Medium | Medium | Entities marked unavailable; recovers automatically |
| MQTT reconnect storms against broker | Low | Medium | Exponential backoff mandatory in the in-tree client (30 s → 60 s → 120 s → 300 s cap) |
| HA breaking change (e.g. `VacuumActivity` further changes) | Medium | Medium | CI matrix runs against HA `latest` and `dev` channels |
| In-tree client has a latent parity bug vs karcher-home | Medium | High | Dual-run regression harness during Phase 1 — run requests through both clients and diff responses |
| Cert pinning password or client cert asset rotates in a future APK | Low | High | Re-extraction procedure documented in `doc/INVESTIGATION.md`; integration surfaces a clear error |
