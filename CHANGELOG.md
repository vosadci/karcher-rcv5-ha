# Changelog

## [0.1.2] — Unreleased

### Changed
- Removed HAMH auto-configuration entirely (config flow HAMH step, options flow, button entities). Apple Home setup is now documented as a manual process in the README.
- README Apple Home section replaced with clear step-by-step manual HAMH bridge setup.

### Fixed
- MQTT topic SN matching now uses exact segment comparison instead of substring search, preventing false matches when one device SN is a prefix of another.
- `assert` statements in `api.py` replaced with `RuntimeError` guards so unauthenticated calls fail correctly in all Python execution modes.
- Import ordering fixed in `vacuum.py` and `select.py` (module-level assignments moved after all imports).
- Removed unused `CONF_DEVICE_SN` import from `__init__.py`.

### Tests
- Tightened binary sensor unavailability assertion (`unknown` vs `unavailable`).
- Added test for `async_send_command` with a scalar room ID parameter.

---

## [0.1.1] — 2026-03-30

### Added
- Error (`binary_sensor.<name>_error`) entity: reports fault state, suppressed during cleaning and when docked.
- Cleaning area (`sensor.<name>_cleaning_area`, m²) and cleaning time (`sensor.<name>_cleaning_time`, min) sensors.
- Water level and fan speed selects are disabled when not applicable to the active cleaning mode.

### Fixed
- All-rooms clean now sends all known room IDs to the firmware instead of an empty list.
- Cleaning area and cleaning time unit conversions corrected.
- Integration domain renamed from `karcher` to `karcher_home_robots` to avoid conflicts.

---

## [0.1.0] — 2026-03-28

### Added
- Initial release.
- Vacuum entity with start, pause, stop, return to base, and fan speed control.
- Battery sensor.
- Room select entity populated from stored map at startup.
- Cleaning mode select (Vacuum / Vacuum and Mop / Mop).
- Real-time state updates via MQTT push; 30-second polling fallback.
- Re-authentication flow.
- HACS-compatible packaging.
