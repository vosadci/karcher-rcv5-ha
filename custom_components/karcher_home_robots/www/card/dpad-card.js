import { LitElement, html } from "../lit-core.js";
import { tr } from "./i18n.js";
import "./dpad.js";

// ---------------------------------------------------------------------------
// Standalone Lovelace card: manual-drive D-pad.
//
// Deliberately a SEPARATE card from karcher-vacuum-card rather than a section
// inside it. Manual drive is an occasional, deliberate action — most users
// never touch it — so it does not earn permanent space in the main card, and
// keeping it separate lets people place it where it suits them (or not at
// all). Both cards ship from the same registered resource, so adding this one
// needs no extra resource setup.
//
// The card owns the styling and the service calls; <karcher-dpad> stays a dumb
// presentational leaf (light DOM, actions up via `karcher-action`), so its
// children land in THIS card's shadow tree and the stylesheet below applies.
//
// CSS is injected as a <style> tag rather than `static styles` — matching
// card.js, where css`` CSSResults routed through adoptStyles() threw in HA.
// ---------------------------------------------------------------------------

const _CSS = `
  :host {
    display: block;
    --rcv-text2: var(--secondary-text-color, #9a9aa2);
    --rcv-text3: var(--disabled-text-color, #6c6c74);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, Helvetica, Arial, sans-serif;
  }
  .wrap { padding: 16px; display: flex; justify-content: center; }
  /* 3x3 grid: arrows on the cross, corners and centre left blank. Just the
     four arrows — no title, no hint text, no decoration. */
  .dpad {
    display: grid;
    grid-template-columns: repeat(3, 52px);
    grid-template-rows: repeat(3, 52px);
    gap: 6px;
  }
  .dpad-spacer { pointer-events: none; }
  .dpad-btn {
    width: 52px;
    height: 52px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: var(--control-button-background-color, var(--secondary-background-color, #161618));
    color: var(--rcv-text2);
    cursor: pointer;
    padding: 0;
    --mdc-icon-size: 26px;
    transition: background 0.15s ease;
  }
  .dpad-btn:not(.disabled):not(:disabled):hover {
    color: var(--primary-color);
  }
  .dpad-btn.disabled,
  .dpad-btn:disabled {
    color: var(--rcv-text3);
    cursor: default;
    opacity: 0.5;
  }
  /* Press feedback: a colour shift, not motion, so it stays regardless of the
     reduced-motion preference below. */
  .dpad-btn:not(.disabled):not(:disabled):active {
    background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.15);
  }
  @media (prefers-reduced-motion: no-preference) {
    /* One press, one nudge: a small, quick shove in the arrow's own
       direction — not a bounce or a glow, just enough to read as motion. */
    .dpad-btn:not(.disabled):not(:disabled) ha-icon { transition: transform 0.1s ease-out; }
    .dpad-up:not(.disabled):not(:disabled):active ha-icon    { transform: translateY(-3px); }
    .dpad-down:not(.disabled):not(:disabled):active ha-icon  { transform: translateY(3px); }
    .dpad-left:not(.disabled):not(:disabled):active ha-icon  { transform: translateX(-3px); }
    .dpad-right:not(.disabled):not(:disabled):active ha-icon { transform: translateX(3px); }
  }
  .missing {
    font-size: 13px;
    color: var(--error-color, #f44336);
  }
`;

// translation_key of each drive button, keyed by the leaf's action name.
const _ACTION_KEYS = {
  drive_forward: "drive_forward",
  drive_backward: "drive_backward",
  drive_left: "drive_left",
  drive_right: "drive_right",
};

class KarcherDpadCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  constructor() {
    super();
    this._config = null;
    this.hass = null;
  }

  setConfig(config) {
    if (!config?.vacuum_entity) {
      throw new Error("karcher-dpad-card: 'vacuum_entity' is required");
    }
    this._config = { ...config };
  }

  getCardSize() { return 4; }

  static getStubConfig(hass) {
    const vac = Object.keys(hass?.states || {}).find((e) => e.startsWith("vacuum."));
    return { vacuum_entity: vac || "vacuum.robot" };
  }

  // Resolve a drive button on the same device as the configured vacuum. Scans
  // the entity registry by device_id + translation_key rather than guessing an
  // entity_id stem, which breaks on renames and disambiguation suffixes. A
  // registry entry with no state is a disabled entity (the buttons ship
  // disabled), so it counts as missing.
  _resolveDrive(action) {
    const key = _ACTION_KEYS[action];
    if (!key || !this.hass) return null;
    const explicit = this._config?.[`${key}_entity`];
    if (explicit && this.hass.states[explicit]) return explicit;
    const deviceId = this.hass.entities?.[this._config?.vacuum_entity]?.device_id;
    if (!deviceId) return null;
    for (const [entityId, entry] of Object.entries(this.hass.entities || {})) {
      if (entry.device_id === deviceId && entry.translation_key === key && this.hass.states[entityId]) {
        return entityId;
      }
    }
    return null;
  }

  get _offline() {
    const st = this.hass?.states?.[this._config?.vacuum_entity]?.state;
    if (st === undefined || st === "unavailable" || st === "unknown") return true;
    // A button is "unknown" until first pressed, so only "unavailable" counts.
    const btn = this._resolveDrive("drive_forward");
    return !btn || this.hass.states[btn].state === "unavailable";
  }

  _onAction(e) {
    const entityId = this._resolveDrive(e.detail?.action);
    // Silently no-op when the button is missing rather than calling
    // button.press with undefined, which HA raises on.
    if (!entityId) return;
    this.hass.callService("button", "press", { entity_id: entityId });
  }

  render() {
    if (!this._config) return html``;
    const missing = !this._resolveDrive("drive_forward");
    return html`
      <ha-card>
        <style>${_CSS}</style>
        <div class="wrap">
          ${missing
            ? html`<div class="missing">${tr("Manual drive buttons not found for this robot.")}</div>`
            : html`<karcher-dpad
                .offline=${this._offline}
                @karcher-action=${(e) => this._onAction(e)}></karcher-dpad>`}
        </div>
      </ha-card>
    `;
  }
}

if (!customElements.get("karcher-dpad-card")) {
  customElements.define("karcher-dpad-card", KarcherDpadCard);
}
