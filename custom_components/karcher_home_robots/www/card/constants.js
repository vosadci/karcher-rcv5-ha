// Versions the Lovelace card only, not the HA integration (manifest.json) or
// the Python package (pyproject.toml). Intentionally divergent — do not unify.
export const VERSION = "1.36.1";

// Map-mode -> icon, single source for the floating control, the map-hint icon,
// and the target-strip icon.
export const MAP_MODE_ICON = { rooms: "mdi:view-grid-outline", zone: "mdi:select-drag" };
