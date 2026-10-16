// Versions the Lovelace card only, not the HA integration (manifest.json) or
// the Python package (pyproject.toml). Intentionally divergent — do not unify.
export const VERSION = "1.38.0";

// Opt-in stock Home Assistant look (config key card_style: "ha"); anything else
// keeps the classic Kärcher look.
export const isHaStyle = (config) => config?.card_style === "ha";

// Map-mode -> icon, single source for the floating control, the map-hint icon,
// and the target-strip icon.
export const MAP_MODE_ICON = { rooms: "mdi:view-grid-outline", zone: "mdi:select-drag" };
