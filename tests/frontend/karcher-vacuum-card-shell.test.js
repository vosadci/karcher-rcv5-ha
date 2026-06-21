// Render tests for the FLIPPED shell (KarcherVacuumCard is now a LitElement).
// These are the only tests that exercise the shell itself; the leaves + pure
// fns are covered elsewhere. The make-or-break assertion is canvas node
// identity across hass updates (the bitmap-preservation guarantee).

import { describe, it, expect, beforeAll } from "vitest";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

function fakeHass(activity = "docked", extra = {}) {
  return {
    states: {
      "vacuum.rcv5": {
        state: activity,
        attributes: {
          friendly_name: "Rocky",
          room_map: {}, room_preferences: {},
          ...extra,
        },
      },
    },
    entities: {},
    callService() {},
  };
}

async function mountCard(config = { vacuum_entity: "vacuum.rcv5" }) {
  const el = document.createElement("karcher-vacuum-card");
  el.setConfig(config);
  el.hass = fakeHass();
  document.body.appendChild(el);
  await el.updateComplete;
  return el;
}

describe("KarcherVacuumCard shell (flipped to LitElement)", () => {
  it("preserves the HA card API surface", () => {
    const Cls = customElements.get("karcher-vacuum-card");
    expect(typeof Cls.getConfigElement).toBe("function");
    expect(typeof Cls.getStubConfig).toBe("function");
    expect(Cls.getStubConfig().vacuum_entity).toBeTruthy();
    const el = document.createElement("karcher-vacuum-card");
    expect(typeof el.setConfig).toBe("function");
    expect(el.getCardSize()).toBe(6);
  });

  it("setConfig throws without vacuum_entity", () => {
    const el = document.createElement("karcher-vacuum-card");
    expect(() => el.setConfig({})).toThrow(/vacuum_entity/);
  });

  it("injects the stylesheet as a <style> tag, not via static styles", async () => {
    // Regression guard: `static styles = _CSS` (a plain string) routed through
    // adoptStyles()/adoptedStyleSheets and threw a TypeError in HA. The CSS must
    // be a <style> element in the shadow root instead.
    const el = await mountCard();
    const Cls = customElements.get("karcher-vacuum-card");
    expect(Cls.styles).toBeUndefined(); // no static styles
    const style = el.renderRoot.querySelector("style");
    expect(style).toBeTruthy();
    expect(style.textContent.length).toBeGreaterThan(100); // the real CSS got in
  });

  it("renders the four ha-cards and mounts every leaf", async () => {
    const el = await mountCard();
    expect(el.renderRoot.querySelectorAll("ha-card")).toHaveLength(4);
    for (const tag of [
      "karcher-stats-row", "karcher-selection-badge", "karcher-button-row",
      "karcher-selector-rows", "karcher-room-list",
    ]) {
      expect(el.renderRoot.querySelector(tag), tag).toBeTruthy();
    }
  });

  it("wraps the cards in .card-grid and tags each for the two-column grid", async () => {
    // The wide-screen layout (container query) repositions the map via CSS
    // grid-areas, so every ha-card needs its grid-area class and the wrapper
    // must exist. Layout itself is verified in-HA, not here.
    const el = await mountCard();
    const grid = el.renderRoot.querySelector(".card-grid");
    expect(grid).toBeTruthy();
    expect(grid.querySelectorAll("ha-card")).toHaveLength(4);
    for (const cls of ["card-status", "card-map", "card-control", "card-settings"]) {
      expect(grid.querySelector(`ha-card.${cls}`), cls).toBeTruthy();
    }
  });

  it("renders the robot name and a status label from hass", async () => {
    const el = await mountCard();
    expect(el.renderRoot.querySelector(".robot-name").textContent).toBe("Rocky");
    expect(el.renderRoot.querySelector(".status-label").textContent.trim().length).toBeGreaterThan(0);
  });

  it("passes activity down to the button-row leaf", async () => {
    const el = await mountCard();
    el.hass = fakeHass("cleaning");
    await el.updateComplete;
    expect(el.renderRoot.querySelector("karcher-button-row").activity).toBe("cleaning");
  });

  it("propagates a connectivity-only outage as offline to the button-row leaf", async () => {
    // Vacuum still reports a cached "docked" activity, but the derived
    // connectivity sensor is off → the leaf must receive offline=true so its
    // buttons disable (the connectivity-only outage window).
    const el = await mountCard();
    const hass = fakeHass("docked");
    hass.states["binary_sensor.rcv5_connectivity"] = { state: "off", attributes: {} };
    el.hass = hass;
    await el.updateComplete;
    const row = el.renderRoot.querySelector("karcher-button-row");
    expect(row.offline).toBe(true);
    await row.updateComplete;
    expect([...row.querySelectorAll("button.btn-wrap")].every((b) => b.disabled)).toBe(true);
    // And the header reflects the offline status.
    expect(el.renderRoot.querySelector(".status-label").textContent).toContain("Offline");
  });

  it("KEEPS THE SAME <canvas> node across hass updates (bitmap survives)", async () => {
    const el = await mountCard();
    const canvas1 = el.renderRoot.querySelector("canvas");
    expect(canvas1).toBeTruthy();
    canvas1._mark = "original";

    // Several hass updates that change unrelated state.
    el.hass = fakeHass("cleaning"); await el.updateComplete;
    el.hass = fakeHass("returning"); await el.updateComplete;
    el.hass = fakeHass("docked"); await el.updateComplete;

    const canvas2 = el.renderRoot.querySelector("canvas");
    expect(canvas2).toBe(canvas1);         // same node instance
    expect(canvas2._mark).toBe("original"); // patched, never recreated
  });

  it("shows the placeholder (map entity not in states) and hides the canvas", async () => {
    // _deriveCompanions derives a default map_entity from the vacuum id; it is
    // not present in the fake hass, so the placeholder reports it missing.
    const el = await mountCard();
    const ph = el.renderRoot.querySelector(".map-placeholder");
    expect(ph.textContent).toContain("Entity not found");
    expect(el.renderRoot.querySelector("canvas").getAttribute("style")).toContain("display:none");
  });

  it("the tab buttons reflect cardMode and switching to customise shows the room list", async () => {
    const el = await mountCard();
    // Default is standard → first tab active. Tabs are Standard, Customise, Area.
    const tabs = el.renderRoot.querySelectorAll(".tab-row .seg-btn");
    expect(tabs).toHaveLength(3);
    expect(tabs[0].textContent.trim()).toBe("Standard");
    expect(tabs[1].textContent.trim()).toBe("Customise");
    expect(tabs[2].textContent.trim()).toBe("Area");
    expect(tabs[0].classList.contains("active")).toBe(true);
    // Drive a prefer_mode change → customise.
    el.hass = fakeHass("docked", { prefer_mode: "customise" });
    await el.updateComplete;
    expect(el.renderRoot.querySelectorAll(".tab-row .seg-btn")[1].classList.contains("active")).toBe(true);
    expect(el.renderRoot.querySelector("karcher-room-list").classList.contains("visible")).toBe(true);
  });

  it("switching to Area hides the room list, keeps the selector rows, and shows the note", async () => {
    const el = await mountCard();
    el._setCardMode("area");
    await el.updateComplete;
    expect(el.renderRoot.querySelectorAll(".tab-row .seg-btn")[2].classList.contains("active")).toBe(true);
    expect(el.renderRoot.querySelector("karcher-room-list").getAttribute("style")).toContain("display:none");
    expect(el.renderRoot.querySelector(".standard-settings").getAttribute("style")).not.toContain("display:none");
    const note = el.renderRoot.querySelector(".area-note");
    expect(note.getAttribute("style")).not.toContain("display:none");
    expect(note.textContent).toContain("Select the area to clean on the map");
  });

  it("Area mode sends prefer_type 0 (rides on Standard) and does not snap back on the standard echo", async () => {
    const el = await mountCard();
    let sent = null;
    el.hass.callService = (domain, service, data) => { sent = { domain, service, data }; };
    el._setCardMode("area");
    expect(sent.data.params.prefer_type).toBe(0);
    expect(el._cardMode).toBe("area");
    // The robot only knows "standard"/"customise" — it echoes "standard" for Area.
    el.hass = fakeHass("docked", { prefer_mode: "standard" });
    await el.updateComplete;
    expect(el._cardMode).toBe("area");
    // A genuine external switch to customise still takes effect.
    el.hass = fakeHass("docked", { prefer_mode: "customise" });
    await el.updateComplete;
    expect(el._cardMode).toBe("customise");
  });

  it("switching from Customise to Area survives a stale 'customise' poll arriving before the robot's echo", async () => {
    const el = await mountCard();
    el.hass = fakeHass("docked", { prefer_mode: "customise" });
    await el.updateComplete;
    expect(el._cardMode).toBe("customise");
    el.hass.callService = () => {};
    el._setCardMode("area");
    expect(el._cardMode).toBe("area");
    // A poll lands carrying the pre-click value, before the robot's own
    // "standard" echo for the new preference arrives.
    el.hass = fakeHass("docked", { prefer_mode: "customise" });
    await el.updateComplete;
    expect(el._cardMode).toBe("area");
    // The real echo confirms the switch and is not mistaken for a revert.
    el.hass = fakeHass("docked", { prefer_mode: "standard" });
    await el.updateComplete;
    expect(el._cardMode).toBe("area");
  });

  it("standard mode also shows the room list, in simple (enable/disable only) form", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 }, "2": { name: "Hall", color_id: 2 } };
    const el = await mountCard();
    el.hass = fakeHass("docked", { room_map: roomMap, room_preferences: {} });
    await el.updateComplete;
    const list = el.renderRoot.querySelector("karcher-room-list");
    expect(list.simple).toBe(true);
    expect(list.rows).toHaveLength(2);
    await list.updateComplete;
    expect(list.querySelector(".room-drag-handle")).toBeNull();
    expect(list.querySelector(".room-list-footer")).toBeNull();
  });

  it("toggling a room in standard mode updates _selectedRooms, not the custom switch", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    let calledService = null;
    el.hass = fakeHass("docked", { room_map: roomMap, room_preferences: {} });
    el.hass.callService = (...args) => { calledService = args; };
    await el.updateComplete;
    const list = el.renderRoot.querySelector("karcher-room-list");
    list.dispatchEvent(new CustomEvent("room-toggle", { detail: { roomId: "1", on: true }, bubbles: true, composed: true }));
    await el.updateComplete;
    expect(el._selectedRooms.has("1")).toBe(true);
    expect(calledService).toBeNull(); // standard toggle is in-memory only, no service call
  });

  it("renders the legend from map_legend, always visible", async () => {
    // Guards the Lit template binding + classes (paint/CSS stay in-HA-verified).
    const el = await mountCard();
    el.hass = fakeHass("docked", { map_legend: { no_go: 1, no_mop: 2, carpet: true, objects: { "1003": 2 } } });
    await el.updateComplete;
    const legend = el.renderRoot.querySelector(".legend");
    expect(legend.classList.contains("legend-hidden")).toBe(false);
    const items = el.renderRoot.querySelector(".legend-items");
    // No-go, No-mop, Carpet, Wire → 4 chips; the count suffix shows for >1.
    const chips = items.querySelectorAll(".legend-chip");
    expect(chips).toHaveLength(4);
    expect(items.textContent).toContain("No-mop ×2");
  });

  it("hides the legend entirely when no map_legend symbols are present", async () => {
    const el = await mountCard();
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".legend").classList.contains("legend-hidden")).toBe(true);
  });

  it("standard tab helper always reads 'Applies to all rooms'", async () => {
    const el = await mountCard();
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".tab-helper").textContent).toContain("Applies to all rooms");
    el._selectedRooms.add("1");
    el.requestUpdate();
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".tab-helper").textContent).toContain("Applies to all rooms");
  });

  it("Area mode hides the room-selection badge (tap-a-room note + select-all chip)", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    el.hass = fakeHass("docked", { room_map: roomMap, room_preferences: {} });
    await el.updateComplete;
    expect(el.renderRoot.querySelector("karcher-selection-badge").state.visible).toBe(true);
    el._setCardMode("area");
    await el.updateComplete;
    const badge = el.renderRoot.querySelector("karcher-selection-badge");
    expect(badge.state.visible).toBe(false);
    expect(badge.state.chipVisible).toBe(false);
  });

  it("area draw: pointer drag builds a rect, Start sends app_zone_clean", async () => {
    let sent = null;
    const el = document.createElement("karcher-vacuum-card");
    el.setConfig({ vacuum_entity: "vacuum.rcv5" });
    el.hass = {
      states: { "vacuum.rcv5": { state: "docked", attributes: {
        friendly_name: "Rocky", room_map: {}, room_preferences: {},
        map_image_size: { width: 100, height: 100, cell_size: 2 },
      } } },
      entities: {},
      callService(domain, service, data) { sent = { domain, service, data }; },
    };
    document.body.appendChild(el);
    await el.updateComplete;
    // happy-dom has no layout; fake a 1:1 canvas box so image px == client px.
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    el._setCardMode("area");
    expect(el._zoneMode).toBe(true);
    el._onZonePointerDown({ clientX: 10, clientY: 20, pointerId: 1, preventDefault() {} });
    el._onZonePointerMove({ clientX: 60, clientY: 70, pointerId: 1 });
    el._onZonePointerUp({ clientX: 60, clientY: 70, pointerId: 1 });
    expect(el._zoneRect).toEqual({ x0: 10, y0: 20, x1: 60, y1: 70 });
    el._startZoneClean();
    expect(sent.service).toBe("send_command");
    expect(sent.data.command).toBe("app_zone_clean");
    expect(sent.data.params.rect_px).toEqual([10, 20, 60, 70]);
    expect(el._zoneMode).toBe(true); // Area tab stays in draw mode after Start
    expect(el._zoneRect).toBe(null);
  });

  it("area draw: a click with no drag still yields a minimum-size rect (no zero-size selection)", async () => {
    const el = await mountCard();
    await el.updateComplete;
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    // cell_size 2 → min side is 7*2 = 14px.
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 2 };
    el._setCardMode("area");
    el._onZonePointerDown({ clientX: 30, clientY: 30, pointerId: 1, preventDefault() {} });
    el._onZonePointerUp({ clientX: 31, clientY: 31, pointerId: 1 });
    expect(el._zoneRect).toEqual({ x0: 30, y0: 30, x1: 44, y1: 44 });
  });

  it("disables room selection while an area is selected", async () => {
    const el = await mountCard();
    await el.updateComplete;
    const list = el.renderRoot.querySelector("karcher-room-list");
    expect(list.classList.contains("zone-locked")).toBe(false);
    expect(list.busy).toBe(false);
    el._zoneRect = { x0: 1, y0: 1, x1: 5, y1: 5 };
    el.requestUpdate();
    await el.updateComplete;
    expect(list.classList.contains("zone-locked")).toBe(true);
    expect(list.busy).toBe(true);
  });

  it("leaving Area for Customise or Standard clears the drawn area (no leak into another tab)", async () => {
    const el = await mountCard();
    el._zoneMode = true;
    el._zoneRect = { x0: 1, y0: 1, x1: 5, y1: 5 };
    el._applyMode("customise");
    expect(el._zoneMode).toBe(false);
    expect(el._zoneRect).toBe(null);

    el._applyMode("area");
    el._zoneRect = { x0: 2, y0: 2, x1: 6, y1: 6 };
    el._applyMode("standard");
    expect(el._zoneMode).toBe(false);
    expect(el._zoneRect).toBe(null);
  });

  it("entering Area auto-enables draw mode; no separate toggle button exists", async () => {
    const el = await mountCard();
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".zone-btn")).toBeNull();
    el._setCardMode("area");
    await el.updateComplete;
    expect(el._zoneMode).toBe(true);
  });

  it("Start stays disabled in Area until an area is drawn, then enables immediately on pointer-down", async () => {
    const el = await mountCard();
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 2 };
    el._setCardMode("area");
    await el.updateComplete;
    const play = el.renderRoot.querySelector("karcher-button-row button.btn-wrap");
    expect(play.disabled).toBe(true);

    // A pointer-down alone (no move yet) already creates a minimum-size rect —
    // the card never allows a degenerate/too-small selection to exist.
    el._onZonePointerDown({ clientX: 10, clientY: 10, pointerId: 1, preventDefault() {} });
    await el.updateComplete;
    expect(play.disabled).toBe(false);

    el._onZonePointerMove({ clientX: 5, clientY: 5, pointerId: 1 });
    el._onZonePointerUp({ clientX: 5, clientY: 5, pointerId: 1 });
    await el.updateComplete;
    // Dragging back toward the anchor clamps to the minimum instead of shrinking further.
    expect(play.disabled).toBe(false);
  });

  it("switching from Standard to Area clears rooms selected in Standard", async () => {
    const el = await mountCard();
    el._selectedRooms.add("1");
    el._selectedRooms.add("2");
    el._setCardMode("area");
    expect(el._selectedRooms.size).toBe(0);
  });

  it("Area with no rect still allows Pause/Resume of an already-running clean", async () => {
    const el = await mountCard();
    el._setCardMode("area");
    await el.updateComplete;
    expect(el._zoneRect).toBe(null);

    el.hass = fakeHass("cleaning", { prefer_mode: "standard" });
    await el.updateComplete;
    let play = el.renderRoot.querySelector("karcher-button-row button.btn-wrap");
    expect(play.disabled).toBe(false); // Pause must stay enabled

    el.hass = fakeHass("paused", { prefer_mode: "standard" });
    await el.updateComplete;
    play = el.renderRoot.querySelector("karcher-button-row button.btn-wrap");
    expect(play.disabled).toBe(false); // Resume must stay enabled
  });
});
