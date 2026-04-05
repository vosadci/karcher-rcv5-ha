# Changelog

## [0.1.0] — Unreleased

### Added
- Vacuum entity with start, pause, stop, return to base, and fan speed control.
- Battery sensor.
- Cleaning area (`sensor.<name>_cleaning_area`, m²) and cleaning time (`sensor.<name>_cleaning_time`, min) sensors.
- Error (`binary_sensor.<name>_error`) entity: reports fault state, suppressed during cleaning and when docked.
- Room select entity populated from stored map at startup.
- Cleaning mode select (Vacuum / Vacuum and Mop / Mop).
- Mop water level select (Low / Medium / High), disabled when mop attachment is not active.
- Fan speed select disabled in Mop-only cleaning mode.
- Real-time state updates via MQTT push; 30-second polling fallback.
- Re-authentication flow.
- HACS-compatible packaging.

### Fixed
- MQTT topic SN matching uses exact segment comparison, preventing false matches when one device SN is a prefix of another.
- All-rooms clean sends all known room IDs explicitly — empty list caused firmware to clean one room semi-randomly.
- Resume (Start while paused) sends `room_ids: []` to continue the current job; sending room IDs restarted the clean from the beginning.
- `assert` statements in `api.py` replaced with `RuntimeError` guards so unauthenticated calls fail correctly in all Python execution modes.
- Cleaning area and cleaning time unit conversions corrected.
