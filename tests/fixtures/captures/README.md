# MQTT Capture Fixtures

## Source

Hand-extracted from `doc/PROTOCOL.md` documented payload blocks (§3 onwards).
Sanitised at the source: the serial number (`SYNTH0000001`) and `msgId` timestamps
are synthetic; all other field values are taken verbatim from the protocol notes.

## Lifecycle

- **Phase 0** (current): documented captures only. They establish the wire shape
  expected by the integration but are not evidence the shape works against real
  firmware.
- **Phase 1 release**: real recorded captures from the maintainer's robot are
  committed alongside these files. Real captures augment, not replace, documented
  ones. A documented capture whose shape diverges from a recorded capture is a
  finding for `doc/PROTOCOL.md` and a lockstep update of both files.
- The two `station_*` files below are real recorded captures
  (`tests/tools/capture_station_props.py`, 2026-08-04), added ahead of a formal
  Phase 1 release because they were the only evidence available for the
  auto-empty feature. This does not by itself flip the project to Phase 1 — that
  is a separate, broader decision.

## Format

Each line in a Phase 0 `.jsonl` file is one JSON object:

```
{"topic": "...", "payload": {...}, "direction": "tx"|"rx", "ts_offset_ms": <int>}
```

- `topic`: full MQTT topic with synthetic product_id and SN
- `payload`: parsed JSON object (not the raw bytes string)
- `direction`: `"tx"` = app→broker, `"rx"` = broker→app (robot push or reply)
- `ts_offset_ms`: milliseconds since the first message in the scenario (0 for first)

The Phase 1 `station_*` files are raw `capture_station_props.py` output and omit
`ts_offset_ms`; ordering within the file is capture order. `topic`/`payload` are
redacted the same way (`_redact()` in the capture tool) — SN, IP, and MAC are
replaced before the line is ever written to disk.

## Files

| File | Scenario |
|---|---|
| `service_invoke_set_room_clean.jsonl` | Full-house start (ctrl_value=1) and pause (ctrl_value=2) with replies |
| `service_invoke_start_recharge.jsonl` | Return to dock command with reply |
| `service_invoke_stop_recharge.jsonl` | Cancel dock return (HA "stop") with reply |
| `prop_set_water_level.jsonl` | Water level set — Low (1), Medium (2), High (3) |
| `prop_set_fan_speed.jsonl` | Suction power set — Silent (0), Standard (1), Medium (2), Turbo (3) |
| `prop_set_cleaning_mode.jsonl` | Cleaning mode set — Vacuum (0), Vacuum & Mop (1), Mop (2) |
| `event_property_post_idle.jsonl` | Robot push: idle, not docked |
| `event_property_post_docked.jsonl` | Robot push: idle, docked and charging (status=4, charge_state=1) |
| `event_property_post_cleaning.jsonl` | Robot push: two successive cleaning updates (area in 0.01 m² units) |
| `station_attached_docked.jsonl` | Real capture: docked, Suction Station attached, idle (`charge_station_type=1`, `dust_action=0`) |
| `station_empty_cycle.jsonl` | Real capture: `start_station_act` command + full empty cycle (`dust_action` 0→2→0, ~20s) |

## PII and secrets policy

No PII or live tokens are permitted. The pre-commit `forbidden-strings` hook and
CI secret-grep cover this layer. Serial numbers use the `SYNTH0000001` placeholder.
