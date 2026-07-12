import { LitElement, html } from "../lit-core.js";
import { tr } from "./i18n.js";
import { optimisticSegment, roomSummaryParts, NO_ROOMS_MESSAGE } from "./derive.js";
import { roomColor } from "./map-draw.js";

// ---------------------------------------------------------------------------
// Lit leaf: customise-mode room list (reorder · enable/disable · per-room detail).
//
// Light DOM (inherits .room-row / .field-row / .segmented CSS). View + events
// only — the shell owns selected/pending/detailRoomId because the still-vanilla
// MAP reads them too (one source of truth, two readers). The leaf's ONLY private
// state is the transient drag (`_dragSrcId`), and `shouldUpdate` suppresses
// re-renders mid-drag so a poll can't clobber the drag (the role the retired
// _lastListKey dedup used to play).
//
// Data down: shell sets `.rows` (deriveRoomRows output) and `.busy`. Events up:
//   room-toggle  { roomId, on }      room-expand { roomId }
//   room-reorder { order:[id,...] }  room-pref   { roomId, field, value }
// ---------------------------------------------------------------------------
class KarcherRoomList extends LitElement {
  static properties = {
    rows: { attribute: false },
    busy: { attribute: false },
  };

  constructor() {
    super();
    this._dragSrcId = null;
    // Optimistic per-detail-segment value, keyed `${roomId}:${field}`, so a
    // clicked mode/power/water/repeat highlights immediately and survives the
    // next poll — same pattern as the standalone selector leaf. Cleared once the
    // derived (persisted) value catches up.
    this._prefPending = new Map();
  }

  createRenderRoot() { return this; }

  willUpdate() {
    // Drop any optimistic detail value the latest derived rows now match.
    for (const row of this.rows || []) {
      for (const c of row.detail) {
        const key = `${row.id}:${c.field}`;
        if (this._prefPending.get(key) === c.value) this._prefPending.delete(key);
      }
    }
  }

  connectedCallback() {
    super.connectedCallback();
    // Drag handlers live on the host (light DOM): rows are direct flex children
    // of .room-list, so container-level DnD avoids child elements swallowing it.
    this.addEventListener("dragover", (e) => this._onDragOver(e));
    this.addEventListener("drop", (e) => this._onDrop(e));
    this.addEventListener("dragleave", (e) => this._onDragLeave(e));
  }

  shouldUpdate() {
    // A hass poll mid-drag would re-render and destroy the drag state — suppress.
    return this._dragSrcId === null;
  }

  _emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
  }

  _order() {
    return (this.rows || []).map((r) => r.id);
  }

  _onDragStart(e, id) {
    if (this.busy) { e.preventDefault(); return; }
    this._dragSrcId = id;
    e.currentTarget.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", id);
  }

  _onDragEnd(e) {
    e.currentTarget.classList.remove("dragging");
    this._dragSrcId = null;
    this._clearIndicators();
    this.requestUpdate(); // drag suppressed updates; refresh now it has ended
  }

  _clearIndicators() {
    this.querySelectorAll(".drop-indicator").forEach((d) => d.remove());
  }

  _rowUnder(target) {
    let el = target;
    while (el && el !== this) {
      if (el.dataset && el.dataset.roomId) return el;
      el = el.parentNode;
    }
    return null;
  }

  _onDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const row = this._rowUnder(e.target);
    if (row && row.dataset.roomId !== this._dragSrcId) {
      this._clearIndicators();
      const ind = document.createElement("div");
      ind.className = "drop-indicator";
      row.parentNode.insertBefore(ind, row);
    }
  }

  _onDrop(e) {
    e.preventDefault();
    this._clearIndicators();
    const row = this._rowUnder(e.target);
    const srcId = this._dragSrcId;
    if (!row || !srcId) return;
    const tgtId = row.dataset.roomId;
    const order = this._order();
    const from = order.indexOf(srcId);
    const to = order.indexOf(tgtId);
    if (from === -1 || to === -1 || from === to) return;
    order.splice(from, 1);
    order.splice(to, 0, srcId);
    this._emit("room-reorder", { order });
  }

  _onDragLeave(e) {
    if (!this.contains(e.relatedTarget)) this._clearIndicators();
  }

  _onPref(roomId, field, value, disabled) {
    if (disabled) return;
    this._prefPending.set(`${roomId}:${field}`, value); // optimistic highlight
    this.requestUpdate();
    this._emit("room-pref", { roomId, field, value });
  }

  _detailRow(roomId, c) {
    return optimisticSegment({
      pending: this._prefPending,
      key: `${roomId}:${c.field}`,
      row: c,
      idBase: `rseg-lbl-${roomId}-${c.field}`,
      onSelect: (opt) => this._onPref(roomId, c.field, opt.value, c.disabled),
    });
  }

  _roomRow(r) {
    const cls = `room-row${r.expanded ? " expanded" : ""}${!r.enabled ? " disabled-room" : ""}`;
    return html`
      <div class="${cls}" data-room-id=${r.id} draggable="true"
        @dragstart=${(e) => this._onDragStart(e, r.id)}
        @dragend=${(e) => this._onDragEnd(e)}>
        <div class="room-row-header" draggable="false">
          <span class="room-drag-handle" title=${tr("Drag to reorder")}>⠿</span>
          <span class="room-color-dot" style="background:${roomColor(r.colorId)}"></span>
          <div class="room-text room-row-select" @click=${(e) => this._onTextClick(e, r)}>
            <div class="room-text-inner">
              <span class="room-name">${r.name}</span>
              ${r.hasPref && !r.expanded ? html`<div class="room-summary">${roomSummaryParts(r.summary)}</div>` : null}
            </div>
            <span class="room-chevron ${r.expanded ? "open" : ""}"
              style=${r.enabled ? "" : "visibility:hidden"}>›</span>
          </div>
          <button class="room-toggle ${r.enabled ? "on" : ""}"
            aria-label=${r.enabled ? tr("Disable room") : tr("Enable room")}
            @click=${(e) => this._onToggle(e, r)}>
            <span class="room-toggle-knob"></span>
          </button>
        </div>
        ${r.detail.length ? html`<div class="room-inline-detail">
          ${r.detail.map((c) => this._detailRow(r.id, c))}
        </div>` : null}
      </div>`;
  }

  _onTextClick(e, r) {
    e.stopPropagation();
    if (!r.enabled || this.busy) return;
    this._emit("room-expand", { roomId: r.id });
  }

  _onToggle(e, r) {
    e.stopPropagation();
    if (this.busy) return;
    this._emit("room-toggle", { roomId: r.id, on: !r.enabled });
  }

  render() {
    const rows = this.rows || [];
    if (rows.length === 0) {
      return html`<div class="room-summary" style="padding:16px 4px">${tr(NO_ROOMS_MESSAGE)}</div>`;
    }
    return html`
      ${rows.map((r) => this._roomRow(r))}
      <div class="room-list-footer">⠿ ${tr("Drag to set cleaning order")}</div>`;
  }
}
if (!customElements.get("karcher-room-list")) {
  customElements.define("karcher-room-list", KarcherRoomList);
}
