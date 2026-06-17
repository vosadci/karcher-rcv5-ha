# doc/ — reverse-engineering reference

Authoritative notes on the Kärcher RCV5 / 3iRobotix stack, produced
during the investigation that preceded this integration.
`ARCHITECTURE.md` and `ROADMAP.md` at the repo root distil
architecture and constraints from this material; this directory
remains the source of truth for the wire format and the device
behaviour.

## Contents

| File | Purpose |
|---|---|
| `PROTOCOL.md` | MQTT topics, REST endpoints, payload schemas, TLS details, dated capture entries — authoritative on the wire |
| `INVESTIGATION.md` | APK static analysis, privacy findings, cert extraction procedure |
| `ROOTING.md` | Physical / firmware access notes; out of scope for the integration |
| `CONSTRAINTS.md` | Hard and soft bounds carried into `ARCHITECTURE.md` |
| `GAP_ANALYSIS.md` | Known divergences, undefined behaviour, implicit decisions |
| `INTENT.md` | Why this work was undertaken and what blocked local control |
| `READ_BEFORE_BUYING.md` | User-facing summary of cloud dependence and privacy posture |

The earlier `spec/` set and `adr/` apparatus were consolidated into
`ARCHITECTURE.md` and `ROADMAP.md` at the repo root, which are now the
source of truth; the prior material is recoverable from git history if
needed for archaeology.

## Maintenance

When new wire-level facts are discovered (HIL captures, payload
fields, error codes), record them in `PROTOCOL.md` with the date and
the reproduction command. When the pinned MQTT broker certificate or
the embedded `iot_dev.p12` rotates, update `INVESTIGATION.md` with
the extraction procedure used. Architectural decisions made during
and after the rewrite live in `ARCHITECTURE.md` at the repo root.
