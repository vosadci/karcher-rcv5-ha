import { LitElement, html } from "../lit-core.js";
import { tr } from "./i18n.js";
import { buttonStates, buttonLabels } from "./derive.js";

// ---------------------------------------------------------------------------
// Lit leaf: control button row (Play/Pause/Resume · Stop · Dock).
//
// Light DOM (createRenderRoot returns `this`) so
// the shell's `.btn-wrap` CSS applies with no duplication. Data
// down: the shell sets `.activity`. Actions up: clicking emits a bubbling
// `karcher-action` event ({ detail: { action } }); the shell routes it to its
// existing _play/_pause/_stop/_dock handlers. The button enable/label decisions
// stay in the already-tested buttonStates()/buttonLabels() pure functions.
// ---------------------------------------------------------------------------
class KarcherButtonRow extends LitElement {
  static properties = {
    activity: { attribute: false },
    offline: { attribute: false },
    playDisabled: { attribute: false },
    // Optional primary-label override (shell's context-aware clean label); when
    // unset the row uses buttonLabels (Start/Pause/Resume).
    playLabel: { attribute: false },
    // Suction Station manual empty. showEmptyStation gates whether the button
    // renders at all (station presence — near-permanent); emptyStationEnabled
    // gates whether it's clickable once shown (docked right now or not). Both
    // default to false so a card with no station configured renders nothing.
    showEmptyStation: { attribute: false },
    emptyStationEnabled: { attribute: false },
  };

  // Light DOM: inherit the shell's stylesheet instead of a private shadow root.
  createRenderRoot() { return this; }

  _emit(action) {
    this.dispatchEvent(new CustomEvent("karcher-action", {
      detail: { action }, bubbles: true, composed: true,
    }));
  }

  _btn(icon, label, variant, enabled, action) {
    return html`
      <button
        class="btn-wrap ${variant} ${enabled ? "" : "disabled"}"
        ?disabled=${!enabled}
        @click=${enabled ? () => this._emit(action) : null}
      >
        <ha-icon icon=${icon}></ha-icon>
        <span class="btn-label">${label}</span>
      </button>`;
  }

  render() {
    const activity = this.activity;
    const { isOffline, canStop, canDock } = buttonStates(activity, this.offline);
    const { playIcon, playLabel, playAction, dockLabel } = buttonLabels(activity);
    const primaryLabel = this.playLabel ?? playLabel;
    return html`
      ${this._btn(playIcon, primaryLabel, "primary", !isOffline && !this.playDisabled, playAction)}
      ${this._btn("mdi:stop", tr("Stop"), "danger", !isOffline && canStop, "stop")}
      ${this.showEmptyStation
        ? this._btn("mdi:delete-empty", tr("Empty"), "secondary",
            !isOffline && !!this.emptyStationEnabled, "empty_station")
        : ""}
      ${this._btn("mdi:home-import-outline", dockLabel, "secondary", !isOffline && canDock, "dock")}
    `;
  }
}
if (!customElements.get("karcher-button-row")) {
  customElements.define("karcher-button-row", KarcherButtonRow);
}
