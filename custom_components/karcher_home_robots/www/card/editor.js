import { LitElement, html } from "../lit-core.js";
import { tr, setLang } from "./i18n.js";
import { nextEditorConfig, deriveCompanions, _EDITOR_COMPANIONS } from "./derive.js";
import { _EDITOR_CSS } from "./styles.js";

// Stable per-domain arrays for ha-entity-picker's `includeDomains` so a re-render
// passes the same reference (a fresh `[domain]` each time would force the picker
// to re-filter its list every hass tick).
const _DOMAIN_ARRAYS = {};
function _domainArr(domain) {
  if (!domain) return undefined;
  if (!_DOMAIN_ARRAYS[domain]) _DOMAIN_ARRAYS[domain] = [domain];
  return _DOMAIN_ARRAYS[domain];
}

class KarcherVacuumCardEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  // CSS as a <style> tag, not `static styles` — same constraint as the card
  // shell (a plain-string `static styles` throws a TypeError via adoptStyles).

  constructor() {
    super();
    this.hass = null;
    this._config = {};
  }

  // HA calls setConfig imperatively; _config is reactive so this re-renders.
  setConfig(config) {
    this._config = { ...config };
  }

  _onPickerChange(configKey, e) {
    this._config = nextEditorConfig(this._config, configKey, e.detail.value);
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }

  // Fixed card height (px). Blank → omit it so the card fills the height in
  // Panel view and falls back to its CSS floor in masonry.
  _onHeightChange(e) {
    const raw = e.target.value;
    const n = parseInt(raw, 10);
    const next = { ...this._config };
    if (raw === "" || isNaN(n) || n <= 0) delete next.card_height;
    else next.card_height = n;
    this._config = next;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }

  // Opt-in debug footer. Set when on, deleted when off so the config stays clean.
  _onDebugToggle(e) {
    const next = { ...this._config };
    if (e.target.checked) next.show_debug = true;
    else delete next.show_debug;
    this._config = next;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }

  _picker(configKey, domain, label, required = false) {
    const derived = deriveCompanions(this._config.vacuum_entity);
    const value = this._config[configKey] || derived[configKey] || "";
    return html`
      <div class="field">
        <label class=${required ? "required" : ""}>${label}</label>
        <ha-entity-picker
          allow-custom-entity
          .hass=${this.hass}
          .value=${value}
          .includeDomains=${_domainArr(domain)}
          @value-changed=${(e) => this._onPickerChange(configKey, e)}
        ></ha-entity-picker>
      </div>`;
  }

  render() {
    setLang(this.hass);
    return html`
      <style>${_EDITOR_CSS}</style>
      ${this._picker("vacuum_entity", "vacuum", tr("Vacuum entity"), true)}
      <div class="field">
        <label>${tr("Card height (px)")}</label>
        <ha-textfield type="number" min="320" inputmode="numeric"
          placeholder=${tr("Auto (fills Panel view)")}
          .value=${this._config.card_height != null ? String(this._config.card_height) : ""}
          @change=${(e) => this._onHeightChange(e)}
        ></ha-textfield>
      </div>
      <div class="field">
        <ha-formfield label=${tr("Show debug info footer (version, state, map)")}>
          <ha-switch
            .checked=${!!this._config.show_debug}
            @change=${(e) => this._onDebugToggle(e)}
          ></ha-switch>
        </ha-formfield>
      </div>
      <details>
        <summary>${tr("Advanced — entity overrides")}</summary>
        <div class="advanced">
          ${_EDITOR_COMPANIONS.map(({ key, label, domain }) =>
            this._picker(key, domain, tr(label)))}
        </div>
      </details>`;
  }
}

if (!customElements.get("karcher-vacuum-card-editor")) {
  customElements.define("karcher-vacuum-card-editor", KarcherVacuumCardEditor);
}
