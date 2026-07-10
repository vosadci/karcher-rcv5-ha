import { LitElement, html } from "../lit-core.js";
import { segmentRow } from "./derive.js";

// ---------------------------------------------------------------------------
// Lit leaf: standard-mode selector rows (Mode · Suction · Water).
//
// Light DOM (inherits .field-row / .segmented / .seg-btn CSS). Data down: the
// shell sets `.rows` to deriveSelectorRows(...)'s output. Actions up: clicking
// a segment emits `karcher-select` ({ detail: { control, value } }); the shell
// routes it to the right callService.
//
// OPTIMISTIC ACTIVE STATE: the old code protected the just-clicked highlight
// from the next poll via the _lastSelectorKey rebuild-skip. Here the leaf keeps
// a per-control `_pending` value — render highlights `pending ?? row.value`, and
// the pending entry clears once the derived value catches up (round-trip done).
// Without this the highlight would snap back to the pre-click value on the next
// poll (~1s). Same pattern as reconcileCustomise.
// ---------------------------------------------------------------------------
class KarcherSelectorRows extends LitElement {
  static properties = { rows: { attribute: false } };

  constructor() {
    super();
    this._pending = new Map(); // control -> optimistic value, until the poll confirms
  }

  createRenderRoot() { return this; }

  willUpdate() {
    // Clear any pending optimistic value the latest derived state now matches.
    for (const row of this.rows || []) {
      if (this._pending.get(row.control) === row.value) this._pending.delete(row.control);
    }
  }

  _select(control, value, optDisabled) {
    if (optDisabled) return;
    this._pending.set(control, value);
    this.requestUpdate(); // reflect the optimistic highlight immediately
    this.dispatchEvent(new CustomEvent("karcher-select", {
      detail: { control, value }, bubbles: true, composed: true,
    }));
  }

  _segment(row) {
    const active = this._pending.get(row.control) ?? row.value;
    // Compact (icon-only inactive) only when a segment is actually active;
    // with no active value (loading/unset) fall back to full labels.
    const compact = row.compactEligible && row.options.some((o) => o.value === active);
    return segmentRow({
      idBase: `seg-lbl-${row.control}`,
      label: row.label,
      rowDisabled: row.disabled,
      compact,
      active,
      options: row.options,
      onSelect: (opt, optDisabled) => this._select(row.control, opt.value, optDisabled),
    });
  }

  render() {
    const rows = this.rows || [];
    // Collapse when empty (no configured selector entities). We only force
    // `none`, never `""`, so the shell's _applyMode mode-gate (which sets
    // display:none in customise mode) is never overridden by a re-render.
    if (rows.length === 0) this.style.display = "none";
    else if (this.style.display === "none") this.style.display = "";
    return html`${rows.map((row) => this._segment(row))}`;
  }
}
if (!customElements.get("karcher-selector-rows")) {
  customElements.define("karcher-selector-rows", KarcherSelectorRows);
}
