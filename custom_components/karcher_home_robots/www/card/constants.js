// Versions the Lovelace card only, not the HA integration (manifest.json) or
// the Python package (pyproject.toml). Intentionally divergent — do not unify.
export const VERSION = "1.33.5";

// Map-mode -> icon, single source for the floating control, the map-hint icon,
// and the target-strip icon (previously hand-duplicated at each call site).
export const MAP_MODE_ICON = { rooms: "mdi:view-grid-outline", zone: "mdi:select-drag" };
