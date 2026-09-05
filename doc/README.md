# doc/ — reverse-engineering reference

Authoritative notes on the Kärcher RCV5 / 3iRobotix stack, produced
during the investigation that preceded this integration.
`ARCHITECTURE.md` at the repo root distils architecture and
constraints from this material; this directory remains the source
of truth for the wire format and the device behaviour.

## Contents

| File | Purpose |
|---|---|
| `PROTOCOL.md` | MQTT topics, REST endpoints, payload schemas, TLS details, dated capture entries — authoritative on the wire. §16 covers app scoping (`projectType`), the live product catalog, and the model-ID catalogs |
| `MAP_DATA.md` | Map wire format — grid encoding, `RobotMap` protobuf schema, room chains, coordinate system, render pipeline |
| `API_SWAGGER.yaml` | OpenAPI 3.0 spec of the 3iRobotix REST API, extracted from the APK |
| `API_GAP_ANALYSIS.md` | Integration vs. app — REST/MQTT call coverage comparison |
| `APP_FEATURES.md` | App feature inventory and gap analysis, mapped to HA entities |
| `INVESTIGATION.md` | APK static analysis, privacy findings, cert extraction procedure |
| `ROOTING.md` | Physical / firmware access notes; out of scope for the integration |
| `LOCAL_CONTROL.md` | On-device process architecture and the cloud-free control paths (A/B/C) that open up post-root |
| `CONSTRAINTS.md` | Hard and soft bounds carried into `ARCHITECTURE.md` |
| `INTENT.md` | Why this work was undertaken and what blocked local control |
| `READ_BEFORE_BUYING.md` | User-facing summary of cloud dependence and privacy posture |

The earlier `spec/` set and `adr/` apparatus were consolidated into
`ARCHITECTURE.md` at the repo root, which is now the source of truth;
the prior material (including the retired `ROADMAP.md`) is recoverable
from git history if needed for archaeology.

## Maintenance

When new wire-level facts are discovered (HIL captures, payload
fields, error codes), record them in `PROTOCOL.md` with the date and
the reproduction command. When the pinned MQTT broker certificate or
the embedded `iot_dev.p12` rotates, update `INVESTIGATION.md` with
the extraction procedure used. Architectural decisions made during
and after the rewrite live in `ARCHITECTURE.md` at the repo root.
