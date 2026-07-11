import { LitElement, html } from "../lit-core.js";
import { tr } from "./i18n.js";

// ---------------------------------------------------------------------------
// Lit leaf: last-run stat tiles (area cleaned · duration · finished).
//
// Light DOM (inherits the shell's .stat-* CSS). Data down: the shell sets
// `.tiles` to deriveStatTiles(...)'s output (all branching is in that pure fn).
// The host collapses to display:none when there are no tiles, so an empty row
// leaves no gap/margin band — the old code did this via _statsEl.style.display.
// ---------------------------------------------------------------------------
class KarcherStatsRow extends LitElement {
  static properties = { tiles: { attribute: false } };

  createRenderRoot() { return this; }

  render() {
    const tiles = this.tiles || [];
    // Collapse the host itself when empty (light DOM has no wrapper to hide).
    this.style.display = tiles.length ? "" : "none";
    return html`${tiles.map((t) => html`
      <div class="stat-block">
        <span class="stat-label-header">
          ${t.icon ? html`<ha-icon icon=${t.icon}></ha-icon>` : null}
          <span>${tr(t.label)}</span>
        </span>
        <span class="stat-value">${t.value}</span>
      </div>`)}`;
  }
}
if (!customElements.get("karcher-stats-row")) {
  customElements.define("karcher-stats-row", KarcherStatsRow);
}
