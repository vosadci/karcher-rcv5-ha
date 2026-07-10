import { LitElement, html } from "../lit-core.js";
import { tr } from "./i18n.js";
import { MAP_MODE_ICON } from "./constants.js";

// ---------------------------------------------------------------------------
// Lit leaf: floating Rooms|Zone map-mode control (top-left of the map hero).
//
// The map-interaction axis, split out from the old 3-way settings tab. Light DOM
// (inherits .map-mode CSS). Data down: the shell sets `.mode` ("rooms" | "zone")
// and `.locked`. Up: a click emits `karcher-map-mode` ({ detail: { mode } }); the
// shell maps "zone" onto its existing Area cardMode and "rooms" back to the last
// non-area settings mode — the prefer_type wiring underneath is unchanged.
// ---------------------------------------------------------------------------
class KarcherMapMode extends LitElement {
  static properties = {
    mode: { attribute: false },
    locked: { attribute: false },
  };

  createRenderRoot() { return this; }

  _emit(mode) {
    if (this.locked) return;
    this.dispatchEvent(new CustomEvent("karcher-map-mode", {
      detail: { mode }, bubbles: true, composed: true,
    }));
  }

  _btn(value, label, icon) {
    const on = this.mode === value;
    return html`
      <button class="map-mode-btn ${on ? "active" : ""}" aria-pressed=${on}
        @click=${() => this._emit(value)}>
        <ha-icon icon=${icon}></ha-icon><span>${label}</span>
      </button>`;
  }

  render() {
    return html`
      <div class="map-mode-inner ${this.locked ? "locked" : ""}" role="group" aria-label=${tr("Map mode")}>
        ${this._btn("rooms", tr("Rooms"), MAP_MODE_ICON.rooms)}
        ${this._btn("zone", tr("Zone"), MAP_MODE_ICON.zone)}
      </div>`;
  }
}
if (!customElements.get("karcher-map-mode")) {
  customElements.define("karcher-map-mode", KarcherMapMode);
}
