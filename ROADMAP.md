# Roadmap

## Done

- **Phase 0** — Scaffold: empty package, CI, tooling
- **Phase 1** — MVP: vacuum + battery + error indicator, adapter, coordinator
- **Phase 2** — Sensors and selects: area/time sensors, cleaning-mode, water-level, fan-speed
- **Phase 3** — Rooms, region routing, Apple Home via HAMH
- **Phase 4** — Hardening to Silver: diagnostics, migration, reauth robustness, outage repair (closed 2026-05-02)

## Next

- **Phase 5** — Map image entity (optional): floor plan as `ImageEntity`, Lovelace calibration points

## Backlog

- Investigate whether `clean_type != 0` has useful semantics
- Track `karcher-home` upstream; simplify adapter workarounds if public API improves
- HAMH compatibility smoke test (blocked on container environment)
