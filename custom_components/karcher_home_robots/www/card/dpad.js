import { LitElement, html } from "../lit-core.js";
import { tr } from "./i18n.js";

// ---------------------------------------------------------------------------
// Lit leaf: manual-drive D-pad (forward / left / right / back).
//
// Mirrors the app's Robot Settings -> Remote control pad. Same contract as
// karcher-button-row: light DOM so the shell stylesheet applies, data down via
// `.offline`, actions up via a bubbling `karcher-action` event which the shell
// routes to `_drive()`.
//
// One press is one nudge — the robot performs a short movement and stops, it
// does not latch a heading (doc/PROTOCOL.md §17). Holding a course therefore
// means pressing repeatedly, so the buttons are deliberately cheap to hit
// repeatedly and carry no "pressed" latch state.
// ---------------------------------------------------------------------------
class KarcherDpad extends LitElement {
  static properties = {
    offline: { attribute: false },
  };

  createRenderRoot() { return this; }

  _emit(action) {
    this.dispatchEvent(new CustomEvent("karcher-action", {
      detail: { action }, bubbles: true, composed: true,
    }));
  }

  _pad(dir, icon, label, action) {
    const enabled = !this.offline;
    return html`
      <button
        class="dpad-btn dpad-${dir} ${enabled ? "" : "disabled"}"
        ?disabled=${!enabled}
        aria-label=${label}
        title=${label}
        @click=${enabled ? () => this._emit(action) : null}
      >
        <ha-icon icon=${icon}></ha-icon>
      </button>`;
  }

  render() {
    // Just the four arrows, cross-arranged — no decoration, no label text.
    // Corners and centre stay visually empty (plain spacer cells).
    return html`
      <div class="dpad" role="group" aria-label=${tr("Manual drive")}>
        <div class="dpad-spacer"></div>
        ${this._pad("up", "mdi:chevron-up", tr("Forward"), "drive_forward")}
        <div class="dpad-spacer"></div>
        ${this._pad("left", "mdi:chevron-left", tr("Left"), "drive_left")}
        <div class="dpad-spacer"></div>
        ${this._pad("right", "mdi:chevron-right", tr("Right"), "drive_right")}
        <div class="dpad-spacer"></div>
        ${this._pad("down", "mdi:chevron-down", tr("Back"), "drive_backward")}
        <div class="dpad-spacer"></div>
      </div>
    `;
  }
}
if (!customElements.get("karcher-dpad")) {
  customElements.define("karcher-dpad", KarcherDpad);
}
