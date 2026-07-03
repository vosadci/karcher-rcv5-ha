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

  it("renders the single-surface shell and mounts every leaf", async () => {
    const el = await mountCard();
    // The mobile shell is one continuous ha-card (no internal card gaps).
    expect(el.renderRoot.querySelectorAll("ha-card")).toHaveLength(1);
    expect(el.renderRoot.querySelector("ha-card.card-shell")).toBeTruthy();
    for (const tag of [
      "karcher-stats-row", "karcher-map-mode", "karcher-button-row",
      "karcher-selector-rows", "karcher-room-list",
    ]) {
      expect(el.renderRoot.querySelector(tag), tag).toBeTruthy();
    }
    // The retired selection badge is gone.
    expect(el.renderRoot.querySelector("karcher-selection-badge")).toBeNull();
  });

  it("lays out the four shell regions: header, map hero, target strip, action bar", async () => {
    // Region structure the no-scroll layout depends on (visual sizing stays
    // in-HA-verified). The bottom sheet overlays them.
    const el = await mountCard();
    const shell = el.renderRoot.querySelector("ha-card.card-shell");
    expect(shell).toBeTruthy();
    for (const sel of [".top-bar", ".rcv-map", ".target-strip", ".action-bar", ".sheet"]) {
      expect(shell.querySelector(sel), sel).toBeTruthy();
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

  it("_resolveFaultEntity uses the derived id directly when it resolves", async () => {
    const el = await mountCard();
    const hass = fakeHass("docked");
    hass.states["sensor.rcv5_robot_status"] = { state: "bumper_fault", attributes: {} };
    el.hass = hass;
    await el.updateComplete;
    expect(el._resolveFaultEntity()).toBe("sensor.rcv5_robot_status");
  });

  it("_resolveFaultEntity falls back to a registry scan when the derived id doesn't resolve", async () => {
    // Older installs kept the entity's pre-rename entity_id (sensor.<stem>_fault_code);
    // the derived guess (sensor.<stem>_robot_status) doesn't exist for them.
    const el = await mountCard();
    const hass = fakeHass("docked");
    hass.entities["vacuum.rcv5"] = { device_id: "dev1" };
    hass.entities["sensor.rcv5_fault_code"] = { device_id: "dev1", translation_key: "fault_code" };
    hass.states["sensor.rcv5_fault_code"] = { state: "bumper_fault", attributes: {} };
    el.hass = hass;
    await el.updateComplete;
    expect(el._resolveFaultEntity()).toBe("sensor.rcv5_fault_code");
  });

  it("_resolveFaultEntity falls back to the derived guess when neither resolves nor scans", async () => {
    const el = await mountCard();
    expect(el._resolveFaultEntity()).toBe("sensor.rcv5_robot_status");
  });

  it("shows the placeholder (map entity not in states) and hides the canvas", async () => {
    // deriveCompanions derives a default map_entity from the vacuum id; it is
    // not present in the fake hass, so the placeholder reports it missing.
    const el = await mountCard();
    const ph = el.renderRoot.querySelector(".map-placeholder");
    expect(ph.textContent).toContain("Entity not found");
    expect(el.renderRoot.querySelector("canvas").getAttribute("style")).toContain("display:none");
  });

  it("shows a warning instead of a blank shell when vacuum_entity doesn't resolve", async () => {
    const el = await mountCard({ vacuum_entity: "vacuum.does_not_exist" });
    expect(el.renderRoot.textContent).toContain("vacuum.does_not_exist");
    expect(el.renderRoot.querySelector(".top-bar")).toBeNull();
  });

  it("renders the normal shell when vacuum_entity resolves", async () => {
    const el = await mountCard();
    expect(el.renderRoot.querySelector(".top-bar")).not.toBeNull();
  });

  it("the settings tabs reflect cardMode; customise shows the room list and the map control reads Rooms", async () => {
    const el = await mountCard();
    // Settings axis is now two tabs (Standard, Customise) in the sheet; the
    // Rooms|Zone axis lives in the floating map-mode control.
    const tabs = el.renderRoot.querySelectorAll(".tab-row .seg-btn");
    expect(tabs).toHaveLength(2);
    expect(tabs[0].textContent.trim()).toBe("Standard");
    expect(tabs[1].textContent.trim()).toBe("Customise");
    expect(tabs[0].classList.contains("active")).toBe(true);
    expect(el.renderRoot.querySelector("karcher-map-mode").mode).toBe("rooms");
    // Drive a prefer_mode change → customise.
    el.hass = fakeHass("docked", { prefer_mode: "customise" });
    await el.updateComplete;
    expect(el.renderRoot.querySelectorAll(".tab-row .seg-btn")[1].classList.contains("active")).toBe(true);
    const list = el.renderRoot.querySelector("karcher-room-list");
    expect(list.getAttribute("style")).not.toContain("display:none");
  });

  it("Zone (Area) hides the room list, keeps the selector rows, shows the note, and the map control reads Zone", async () => {
    const el = await mountCard();
    el._setCardMode("area");
    await el.updateComplete;
    expect(el.renderRoot.querySelector("karcher-map-mode").mode).toBe("zone");
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

  it("standard settings shows the selector rows and hides the customise room list", async () => {
    // Room selection in Standard now lives in the target-strip chips; the
    // per-room room list is the Customise editor only (hidden in Standard).
    const roomMap = { "1": { name: "Kitchen", color_id: 1 }, "2": { name: "Hall", color_id: 2 } };
    const el = await mountCard();
    el.hass = fakeHass("docked", { room_map: roomMap, room_preferences: {} });
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".standard-settings").getAttribute("style")).not.toContain("display:none");
    expect(el.renderRoot.querySelector("karcher-room-list").getAttribute("style")).toContain("display:none");
    // The target tab renders a chip per room.
    expect(el.renderRoot.querySelectorAll(".room-chip")).toHaveLength(2);
  });

  it("target-strip chips toggle room selection through the shared _onRoomToggle path", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    let calledService = null;
    el.hass = fakeHass("docked", { room_map: roomMap, room_preferences: {} });
    el.hass.callService = (...args) => { calledService = args; };
    await el.updateComplete;
    el.renderRoot.querySelector(".room-chip").click();
    await el.updateComplete;
    expect(el._selectedRooms.has("1")).toBe(true);
    expect(calledService).toBeNull(); // standard selection is in-memory only
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

  it("Zone mode swaps the target strip and map hint to the draw-an-area copy", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    el.hass = fakeHass("docked", { room_map: roomMap, room_preferences: {} });
    await el.updateComplete;
    // Rooms mode: strip names the selection (none → Whole home).
    expect(el.renderRoot.querySelector(".target-strip-label").textContent).toContain("Whole home");
    el._setCardMode("area");
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".target-strip-label").textContent).toContain("Draw an area");
    expect(el.renderRoot.querySelector(".map-hint span").textContent).toContain("Drag to draw");
  });

  it("clean-target banner stays present and reflects the selection (no content jump)", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 }, "2": { name: "Hall", color_id: 2 } };
    const el = await mountCard();
    el.hass = fakeHass("docked", { room_map: roomMap, room_preferences: {} });
    await el.updateComplete;
    const banner = () => el.renderRoot.querySelector(".whole-home-banner span");
    expect(banner().textContent).toContain("Whole home");
    el._selectedRooms.add("1");
    el.requestUpdate();
    await el.updateComplete;
    // Banner still rendered, now naming the selection (mirrors the target strip).
    expect(banner()).not.toBeNull();
    expect(banner().textContent).toContain("Kitchen");
  });

  it("keeps the room selection in the target strip once cleaning starts, even if prefer_mode echoes during the run", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    el.hass = fakeHass("idle", { room_map: roomMap, room_preferences: {}, prefer_mode: "standard" });
    await el.updateComplete;
    el._selectedRooms.add("1");
    el.requestUpdate();
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".target-strip-label").textContent).toContain("Kitchen");

    // Start cleaning; a custom_type push mid-run can make the robot echo
    // prefer_mode="customise" before the run ends — the card must not let
    // that flip _cardMode and swap the strip to the Customise selection.
    el.hass = fakeHass("cleaning", { room_map: roomMap, room_preferences: {}, prefer_mode: "customise" });
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".target-strip-label").textContent).toContain("Kitchen");
    expect(el._cardMode).toBe("standard");

    // Once the run ends, the deferred echo applies and the selection clears
    // (existing run-end behavior) — mode tracks the robot again.
    el.hass = fakeHass("idle", { room_map: roomMap, room_preferences: {}, prefer_mode: "customise" });
    await el.updateComplete;
    expect(el._cardMode).toBe("customise");
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
    // Start drawing from scratch rather than editing the auto-seeded default.
    el._zoneRect = null;
    el._onMapPointerDown({ clientX: 10, clientY: 20, pointerId: 1, preventDefault() {} });
    el._onMapPointerMove({ clientX: 60, clientY: 70, pointerId: 1 });
    el._onMapPointerUp({ clientX: 60, clientY: 70, pointerId: 1 });
    expect(el._zoneRect).toEqual({ x0: 10, y0: 20, x1: 60, y1: 70 });
    el._startZoneClean();
    expect(sent.service).toBe("send_command");
    expect(sent.data.command).toBe("app_zone_clean");
    expect(sent.data.params.rect_px).toEqual([10, 20, 60, 70]);
    expect(el._zoneMode).toBe(true); // Area tab stays in draw mode after Start
    // The drawn rect stays put after Start so the user can see/re-run it.
    expect(el._zoneRect).toEqual({ x0: 10, y0: 20, x1: 60, y1: 70 });
  });

  it("area draw: a click with no drag still yields a minimum-size rect (no zero-size selection)", async () => {
    const el = await mountCard();
    await el.updateComplete;
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    // cell_size 2 → min side is 10*2 = 20px.
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 2 };
    el._setCardMode("area");
    // Start drawing from scratch rather than editing the auto-seeded default.
    el._zoneRect = null;
    el._onMapPointerDown({ clientX: 30, clientY: 30, pointerId: 1, preventDefault() {} });
    el._onMapPointerUp({ clientX: 31, clientY: 31, pointerId: 1 });
    expect(el._zoneRect).toEqual({ x0: 30, y0: 30, x1: 50, y1: 50 });
  });

  it("area draw: clicking outside an existing rect is a no-op — the selection always stays present", async () => {
    const el = await mountCard();
    await el.updateComplete;
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 1 };
    el._setCardMode("area");
    el._zoneRect = { x0: 10, y0: 10, x1: 30, y1: 30 };
    // (80,80) is well outside the rect and its corner handles.
    el._onMapPointerDown({ clientX: 80, clientY: 80, pointerId: 1, preventDefault() {} });
    el._onMapPointerMove({ clientX: 90, clientY: 95, pointerId: 1 });
    el._onMapPointerUp({ clientX: 90, clientY: 95, pointerId: 1 });
    expect(el._zoneRect).toEqual({ x0: 10, y0: 10, x1: 30, y1: 30 });
  });

  it("area draw: dragging inside an existing rect moves it instead of resizing", async () => {
    const el = await mountCard();
    await el.updateComplete;
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 1 };
    el._setCardMode("area");
    el._zoneRect = { x0: 10, y0: 10, x1: 30, y1: 30 };
    // (20,20) is the rect's body, away from any corner handle.
    el._onMapPointerDown({ clientX: 20, clientY: 20, pointerId: 1, preventDefault() {} });
    el._onMapPointerMove({ clientX: 25, clientY: 28, pointerId: 1 });
    el._onMapPointerUp({ clientX: 25, clientY: 28, pointerId: 1 });
    expect(el._zoneRect).toEqual({ x0: 15, y0: 18, x1: 35, y1: 38 });
  });

  it("area draw: moving into a wall and back does not drift the rect (grab-offset, not incremental)", async () => {
    const el = await mountCard();
    await el.updateComplete;
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 1 };
    el._setCardMode("area");
    el._zoneRect = { x0: 10, y0: 10, x1: 30, y1: 30 };
    // Grab at (20,10) — body, offset 10px from the left edge.
    el._onMapPointerDown({ clientX: 20, clientY: 10, pointerId: 1, preventDefault() {} });
    // Drag past the left wall: clamps to x0=0.
    el._onMapPointerMove({ clientX: 0, clientY: 10, pointerId: 1 });
    expect(el._zoneRect.x0).toBe(0);
    // Drag back to the original grab point: must return to the original position exactly.
    el._onMapPointerMove({ clientX: 20, clientY: 10, pointerId: 1 });
    el._onMapPointerUp({ clientX: 20, clientY: 10, pointerId: 1 });
    expect(el._zoneRect).toEqual({ x0: 10, y0: 10, x1: 30, y1: 30 });
  });

  it("area draw: dragging a corner handle resizes from the opposite corner", async () => {
    const el = await mountCard();
    await el.updateComplete;
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 1 };
    el._setCardMode("area");
    el._zoneRect = { x0: 10, y0: 10, x1: 30, y1: 30 };
    // (30,30) is the se handle; the nw corner (10,10) is the fixed anchor.
    el._onMapPointerDown({ clientX: 30, clientY: 30, pointerId: 1, preventDefault() {} });
    el._onMapPointerMove({ clientX: 60, clientY: 50, pointerId: 1 });
    el._onMapPointerUp({ clientX: 60, clientY: 50, pointerId: 1 });
    expect(el._zoneRect).toEqual({ x0: 10, y0: 10, x1: 60, y1: 50 });
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
    el._cardMode = "area"; // _zoneMode derives from cardMode
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

  it("entering Area seeds a centered default selection instead of an empty map", async () => {
    const el = await mountCard();
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 200, height: 200, cell_size: 1 };
    el._setCardMode("area");
    // cell_size 1 → min side 10, default side 10*5=50. Map 200x200 → centered at (75,75)-(125,125).
    expect(el._zoneRect).toEqual({ x0: 75, y0: 75, x1: 125, y1: 125 });
  });

  it("a redundant _applyMode('area') re-run (e.g. the backend echo) does not clobber an edited rect", async () => {
    const el = await mountCard();
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 200, height: 200, cell_size: 1 };
    el._applyMode("area");
    expect(el._zoneRect).toEqual({ x0: 75, y0: 75, x1: 125, y1: 125 });
    // user drags the default rect somewhere else
    el._zoneRect = { x0: 0, y0: 0, x1: 10, y1: 10 };
    // prefer_mode echo lands and re-applies the same mode
    el._applyMode("area");
    expect(el._zoneRect).toEqual({ x0: 0, y0: 0, x1: 10, y1: 10 });
  });

  it("Start keeps the drawn rect in place instead of resetting it", async () => {
    let sent = null;
    const el = await mountCard();
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 200, height: 200, cell_size: 1 };
    el.hass.callService = (domain, service, data) => { sent = { domain, service, data }; };
    el._setCardMode("area");
    el._zoneRect = { x0: 10, y0: 10, x1: 40, y1: 40 };
    el._startZoneClean();
    expect(sent.data.params.rect_px).toEqual([10, 10, 40, 40]);
    expect(el._zoneMode).toBe(true);
    // The user's selection persists after Start so it can be seen/re-run.
    expect(el._zoneRect).toEqual({ x0: 10, y0: 10, x1: 40, y1: 40 });
  });

  it("entering Area auto-enables draw mode; no separate toggle button exists", async () => {
    const el = await mountCard();
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".zone-btn")).toBeNull();
    el._setCardMode("area");
    await el.updateComplete;
    expect(el._zoneMode).toBe(true);
  });

  it("Start is enabled immediately in Area thanks to the default centered selection", async () => {
    const el = await mountCard();
    el._canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 2 };
    el._setCardMode("area");
    await el.updateComplete;
    const play = el.renderRoot.querySelector("karcher-button-row button.btn-wrap");
    // Entering Area seeds a default rect — nothing to draw before Start works.
    expect(play.disabled).toBe(false);

    el._onMapPointerDown({ clientX: 10, clientY: 10, pointerId: 1, preventDefault() {} });
    el._onMapPointerMove({ clientX: 5, clientY: 5, pointerId: 1 });
    el._onMapPointerUp({ clientX: 5, clientY: 5, pointerId: 1 });
    await el.updateComplete;
    expect(play.disabled).toBe(false);
  });

  it("switching from Standard to Area clears rooms selected in Standard", async () => {
    const el = await mountCard();
    el._selectedRooms.add("1");
    el._selectedRooms.add("2");
    el._setCardMode("area");
    expect(el._selectedRooms.size).toBe(0);
  });

  it("keeps the Standard room selection across pause/resume, clears it when the run ends", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    el.hass = fakeHass("cleaning", { room_map: roomMap });
    await el.updateComplete;
    el._selectedRooms.add("1");
    // Pause must NOT drop the selection.
    el.hass = fakeHass("paused", { room_map: roomMap });
    await el.updateComplete;
    expect(el._selectedRooms.has("1")).toBe(true);
    // Resume keeps it.
    el.hass = fakeHass("cleaning", { room_map: roomMap });
    await el.updateComplete;
    expect(el._selectedRooms.has("1")).toBe(true);
    // Run ends (docked) → selection clears.
    el.hass = fakeHass("docked", { room_map: roomMap });
    await el.updateComplete;
    expect(el._selectedRooms.size).toBe(0);
  });

  it("recovers the active-clean room highlight from the backend after a reload", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 }, "2": { name: "Bath", color_id: 2 } };
    // Fresh card (empty _selectedRooms) mounted mid-clean, as on a browser reload.
    const el = await mountCard();
    el.hass = fakeHass("cleaning", { room_map: roomMap, active_clean_room_ids: [1] });
    await el.updateComplete;
    // Selection is re-seeded from the backend so the map/note reflect the real clean.
    expect(el._selectedRooms.has("1")).toBe(true);
    expect(el._selectedRooms.has("2")).toBe(false);
  });

  it("does not re-seed selection for a whole-home clean (empty active set)", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    el.hass = fakeHass("cleaning", { room_map: roomMap, active_clean_room_ids: [] });
    await el.updateComplete;
    expect(el._selectedRooms.size).toBe(0); // stays "whole home"
  });

  it("locks the room list and disables the target strip while paused", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    el.hass = fakeHass("paused", { room_map: roomMap });
    await el.updateComplete;
    expect(el.renderRoot.querySelector("karcher-room-list").busy).toBe(true);
    expect(el.renderRoot.querySelector(".target-strip").disabled).toBe(true);
  });

  it("ignores a tab switch while paused", async () => {
    const el = await mountCard();
    el.hass = fakeHass("paused");
    await el.updateComplete;
    el._setCardMode("customise");
    expect(el._cardMode).toBe("standard");
  });

  it("treats a Stop→paused robot as a finished cycle: room list editable again", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    el.hass = fakeHass("cleaning", { room_map: roomMap });
    await el.updateComplete;
    el._stop(); // user presses Stop while cleaning
    el.hass = fakeHass("paused", { room_map: roomMap }); // robot settles into paused
    await el.updateComplete;
    expect(el._stopped).toBe(true);
    expect(el.renderRoot.querySelector("karcher-room-list").busy).toBe(false);
    expect(el.renderRoot.querySelector(".target-strip").disabled).toBe(false);
    // The status chip reads "Stopped" (resting), not "Paused".
    const label = el.renderRoot.querySelector(".status-label");
    expect(label.textContent.trim()).toBe("Stopped");
    expect(label.className).toContain("label-idle");
  });

  it("Start after Stop dispatches a fresh room clean, not a resume", async () => {
    const roomMap = { "1": { name: "Kitchen" }, "2": { name: "Bath" } };
    const el = await mountCard();
    const calls = [];
    const hass = fakeHass("paused", { room_map: roomMap });
    hass.callService = (domain, service, data) => calls.push({ service, data });
    el._stopped = true; // stopped earlier
    el._selectedRooms.add("2"); // user picks a new room
    el.hass = hass;
    await el.updateComplete;
    el._play();
    expect(calls).toHaveLength(1);
    expect(calls[0].service).toBe("send_command");
    expect(calls[0].data.command).toBe("app_segment_clean");
    expect(calls[0].data.params).toEqual([2]);
    expect(el._stopped).toBe(false); // intent consumed
  });

  it("Start after Stop with no selection expands to all rooms (avoids the paused resume)", async () => {
    const roomMap = { "1": { name: "Kitchen" }, "2": { name: "Bath" } };
    const el = await mountCard();
    const calls = [];
    const hass = fakeHass("paused", { room_map: roomMap });
    hass.callService = (domain, service, data) => calls.push({ service, data });
    el._stopped = true;
    el.hass = hass;
    await el.updateComplete;
    el._play();
    expect(calls).toHaveLength(1);
    expect(calls[0].service).toBe("send_command");
    expect(calls[0].data.command).toBe("app_segment_clean");
    expect([...calls[0].data.params].sort()).toEqual([1, 2]);
  });

  it("Resume after a plain Pause issues a bare vacuum.start (no Stop intent)", async () => {
    const el = await mountCard();
    const calls = [];
    const hass = fakeHass("paused", { room_map: {} });
    hass.callService = (domain, service, data) => calls.push({ service, data });
    el.hass = hass; // _stopped stays false
    await el.updateComplete;
    el._play();
    expect(calls).toHaveLength(1);
    expect(calls[0].service).toBe("start");
    expect(calls[0].data).toEqual({ entity_id: "vacuum.rcv5" });
  });

  it("Pause clears any prior Stop intent (resume-in-place semantics)", async () => {
    const el = await mountCard();
    el._stopped = true;
    el._pause();
    expect(el._stopped).toBe(false);
  });

  it("refresh_preferences is skipped (and re-armed) while the WebSocket is reconnecting", async () => {
    const el = await mountCard();
    const calls = [];
    const hass = fakeHass("docked");
    hass.connection = { connected: false }; // app just re-foregrounded, socket down
    hass.callService = (domain, service, data) => calls.push({ service, data });
    el.hass = hass;
    el._pendingPrefRefresh = false; // ignore the mount-time refresh
    el._refreshPreferences();
    expect(calls).toHaveLength(0); // no call → no "connection lost" toast
    expect(el._pendingPrefRefresh).toBe(true); // re-armed for the next update
  });

  it("refresh_preferences fires once the connection is back", async () => {
    const el = await mountCard();
    const calls = [];
    const hass = fakeHass("docked");
    hass.connection = { connected: true };
    hass.callService = (domain, service, data) => calls.push({ service, data });
    el.hass = hass;
    el._refreshPreferences();
    expect(calls).toHaveLength(1);
    expect(calls[0].service).toBe("refresh_preferences");
  });

  it("clears the Stop intent once a new clean begins", async () => {
    const roomMap = { "1": { name: "Kitchen" } };
    const el = await mountCard();
    el.hass = fakeHass("paused", { room_map: roomMap });
    await el.updateComplete;
    el._stopped = true;
    el.hass = fakeHass("cleaning", { room_map: roomMap }); // new clean starts
    await el.updateComplete;
    expect(el._stopped).toBe(false);
  });

  it("locks the mode tabs and room list when offline", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 } };
    const el = await mountCard();
    el.hass = fakeHass("unavailable", { room_map: roomMap });
    await el.updateComplete;
    expect(el.renderRoot.querySelector("karcher-room-list").busy).toBe(true);
    const tabs = [...el.renderRoot.querySelectorAll(".tab-row .seg-btn")];
    expect(tabs.every((b) => b.disabled)).toBe(true);
  });

  it("caps the map height so the card fits one screen (full-bleed width, max-height cap)", async () => {
    const el = await mountCard();
    const hass = fakeHass("docked", { map_image_size: { width: 100, height: 160 } });
    // Map entity must exist for the placeholder/aspect view to resolve.
    hass.states["image.rcv5_map"] = { state: "t0", attributes: { entity_picture: "/x", access_token: "t" } };
    el.hass = hass;
    await el.updateComplete;
    const style = el.renderRoot.querySelector(".map-container").getAttribute("style");
    expect(style).toContain("aspect-ratio:100 / 160");
    expect(style).toContain("max-height:var(--rcv-map-max-height, 60dvh)");
    // Full-bleed: no width cap — the canvas keeps the card's width and the
    // aspect-fit letterbox lives inside the canvas (fitContentBox).
    expect(style).not.toContain("max-width");
  });

  it("card_height config pins an explicit shell height; omitting it leaves the shell to fill/floor", async () => {
    const fixed = await mountCard({ vacuum_entity: "vacuum.rcv5", card_height: 720 });
    const style = fixed.renderRoot.querySelector("ha-card.card-shell").getAttribute("style");
    expect(style).toContain("height:720px");
    const auto = await mountCard();
    expect(auto.renderRoot.querySelector("ha-card.card-shell").getAttribute("style") || "")
      .not.toContain("height:");
  });

  it("primary button shows a context-aware clean label (whole home / N rooms / area), Pause while running", async () => {
    const roomMap = { "1": { name: "Kitchen", color_id: 1 }, "2": { name: "Hall", color_id: 2 } };
    const el = await mountCard();
    el.hass = fakeHass("docked", { room_map: roomMap, room_preferences: {} });
    await el.updateComplete;
    const label = () => el.renderRoot.querySelector("karcher-button-row .btn-label").textContent;
    expect(label()).toBe("Clean whole home");
    el._selectedRooms.add("1");
    el.requestUpdate();
    await el.updateComplete;
    expect(label()).toBe("Clean 1 room");
    // Zone with nothing drawn → disabled prompt; running → Pause.
    el._setCardMode("area");
    await el.updateComplete;
    expect(label()).toBe("Draw an area first");
    el.hass = fakeHass("cleaning", { room_map: roomMap });
    await el.updateComplete;
    expect(label()).toBe("Pause");
  });

  it("the target strip opens the sheet; the scrim closes it", async () => {
    const el = await mountCard();
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".sheet").classList.contains("open")).toBe(false);
    el.renderRoot.querySelector(".target-strip").click();
    await el.updateComplete;
    expect(el._sheetOpen).toBe(true);
    expect(el.renderRoot.querySelector(".sheet").classList.contains("open")).toBe(true);
    el.renderRoot.querySelector(".sheet-scrim").click();
    await el.updateComplete;
    expect(el._sheetOpen).toBe(false);
  });

  it("the sheet tabs switch between What gets cleaned and Settings", async () => {
    const el = await mountCard();
    el._openSheet();
    await el.updateComplete;
    const [target, settings] = el.renderRoot.querySelectorAll(".sheet-tab");
    expect(target.classList.contains("active")).toBe(true);
    settings.click();
    await el.updateComplete;
    expect(el._sheetTab).toBe("settings");
    expect(el.renderRoot.querySelectorAll(".sheet-tab")[1].classList.contains("active")).toBe(true);
  });

  it("the map-mode control drives cardMode: Zone → area, Rooms → last settings mode", async () => {
    const el = await mountCard();
    // Land in Customise, then go to Zone and back to Rooms — must restore Customise.
    el.hass = fakeHass("docked", { prefer_mode: "customise" });
    await el.updateComplete;
    expect(el._cardMode).toBe("customise");
    el.hass.callService = () => {};
    el._onMapMode({ detail: { mode: "zone" } });
    expect(el._cardMode).toBe("area");
    el._onMapMode({ detail: { mode: "rooms" } });
    expect(el._cardMode).toBe("customise");
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

  it("reset-zoom button appears only while zoomed in and resets zoom/pan on click", async () => {
    const el = await mountCard();
    el._mapLoaded = true;
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".map-reset")).toBeNull(); // fit zoom → hidden

    el._zoom = 2.5;
    el._pan = { x: -40, y: -20 };
    el.requestUpdate();
    await el.updateComplete;
    const btn = el.renderRoot.querySelector(".map-reset");
    expect(btn).toBeTruthy();
    expect(btn.textContent).toContain("Reset");

    btn.click();
    await el.updateComplete;
    expect(el._zoom).toBe(1);
    expect(el._pan).toEqual({ x: 0, y: 0 });
    expect(el.renderRoot.querySelector(".map-reset")).toBeNull(); // hides itself
  });

  it("reset-zoom button stays hidden while zoomed if no map has loaded", async () => {
    const el = await mountCard();
    el._mapLoaded = false;
    el._zoom = 2;
    el.requestUpdate();
    await el.updateComplete;
    expect(el.renderRoot.querySelector(".map-reset")).toBeNull();
  });

  it("directional edge scrims fade in only where the zoomed map overflows", async () => {
    const el = await mountCard();
    el._mapLoaded = true;
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 1 };
    el.requestUpdate();
    await el.updateComplete;
    // Fit zoom: all four scrims transparent.
    const opacityOf = (sel) => el.renderRoot.querySelector(sel).style.opacity;
    expect(el.renderRoot.querySelectorAll(".map-edge")).toHaveLength(4);
    for (const s of [".map-edge-l", ".map-edge-r", ".map-edge-t", ".map-edge-b"]) {
      expect(opacityOf(s)).toBe("0");
    }
    // Zoom in, pan flush to the top-left → content hidden only right + bottom.
    el._zoom = 3;
    el._pan = { x: 0, y: 0 };
    el.requestUpdate();
    await el.updateComplete;
    expect(opacityOf(".map-edge-l")).toBe("0");
    expect(opacityOf(".map-edge-t")).toBe("0");
    expect(Number(opacityOf(".map-edge-r"))).toBeGreaterThan(0);
    expect(Number(opacityOf(".map-edge-b"))).toBeGreaterThan(0);
  });

  it("fires the pannability nudge once per zoom-in session and re-arms on reset", async () => {
    const el = await mountCard();
    el._mapLoaded = true;
    el._zoom = 2.5;
    el.hass.states["vacuum.rcv5"].attributes.map_image_size = { width: 100, height: 100, cell_size: 1 };
    await el.updateComplete;
    expect(el._hasNudged).toBe(false);
    el._triggerNudge();
    expect(el._hasNudged).toBe(true);
    // A second call while still zoomed is a no-op (guarded by the flag).
    const raf = el._nudgeRaf;
    el._triggerNudge();
    expect(el._nudgeRaf).toBe(raf);
    // Reset re-arms so the next fresh zoom-in nudges again.
    el._resetZoom();
    expect(el._hasNudged).toBe(false);
  });
});
