// Kärcher Vacuum Card — custom Lovelace card for the RCV5 integration.
// Single plain-JS file, no CI build toolchain. Lit is vendored as a committed
// self-contained ESM bundle (./lit-core.js) — no runtime CDN/import-map needed.
//
// Architecture: one Lit shell (<karcher-vacuum-card>) renders the whole card
// declaratively; presentational leaves (button row, stats, selectors, room
// list, map mode) render into LIGHT DOM (createRenderRoot returns `this`) so
// they inherit the shell's _CSS sheet — they carry no `css` of their own.
// Data flows DOWN via properties; actions flow UP via dispatchEvent. The map
// is a <canvas> painted imperatively by the pure drawMap renderer below (the
// one deliberate non-Lit island, plus the transient drag-and-drop indicators).

import { VERSION } from "./card/constants.js";

// Re-export every pure symbol the test suite imports from this path.
export * from "./card/i18n.js";
export * from "./card/geometry.js";
export * from "./card/derive.js";
export * from "./card/map-draw.js";

// Side-effect imports: run each component's customElements.define exactly once,
// leaf components before the shell.
import "./card/button-row.js";
import "./card/stats-row.js";
import "./card/selector-rows.js";
import "./card/room-list.js";
import "./card/map-mode.js";
import "./card/card.js";
import "./card/editor.js";

console.info(`%c karcher-vacuum-card %c ${VERSION} `, "color:#fff;background:#ffd400", "color:#ffd400;background:#333");

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "karcher-vacuum-card")) {
  window.customCards.push({
    type: "karcher-vacuum-card",
    name: "Kärcher Vacuum Card",
    description: "Map, room selection, controls for the Kärcher RCV5",
    preview: false,
    version: VERSION,
  });
}
