// Tests for slice 4: deriveRoomRows (pure) and the KarcherRoomList Lit leaf.
//
// Covered here (happy-dom): row derivation, toggle/expand/pref/reorder events,
// and that the leaf is view-only (the shell owns selected/pending/detailRoomId).
// NOT covered: drag-and-drop reorder — synthetic DnD events are unreliable in
// happy-dom, so the reorder *gesture* stays in-HA-verified. We do test that the
// reorder event payload is correct when emitted programmatically.

import { describe, it, expect, beforeAll } from "vitest";
import { deriveRoomRows } from "../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

const roomMap = {
  "1": { name: "Kitchen", color_id: 1 },
  "2": { name: "Hall", color_id: 2 },
};
// prefs: order, custom (enabled), and int-coded mode/power/water/repeat
const prefs = {
  "1": { order: 0, custom: true, mode: 1, power: 2, water: 2, repeat: 1 },
  "2": { order: 1, custom: false, mode: 0, power: 1, water: 1, repeat: 0 },
};

describe("deriveRoomRows", () => {
  it("orders rows by preference order and reflects enabled state", () => {
    const rows = deriveRoomRows(roomMap, prefs, new Set(["1"]), null);
    expect(rows.map((r) => r.id)).toEqual(["1", "2"]);
    expect(rows[0]).toMatchObject({ name: "Kitchen", enabled: true, expanded: false });
    expect(rows[1]).toMatchObject({ name: "Hall", enabled: false });
  });

  it("builds the collapsed summary from mode + repeat", () => {
    const [kitchen] = deriveRoomRows(roomMap, prefs, new Set(["1"]), null);
    // mode 1 = vacuum_and_mop, repeat 1 = ×2
    expect(kitchen.summary).toMatch(/×2$/);
  });

  it("includes detail controls only for the expanded AND enabled room", () => {
    const rows = deriveRoomRows(roomMap, prefs, new Set(["1"]), "1");
    expect(rows[0].detail.map((c) => c.field)).toEqual(["repeat", "mode", "power", "water"]);
    expect(rows[1].detail).toEqual([]); // not expanded
  });

  it("omits detail when expanded but NOT enabled", () => {
    const rows = deriveRoomRows(roomMap, prefs, new Set(), "1"); // room 1 expanded but disabled
    expect(rows[0].detail).toEqual([]);
  });

  it("detail maps int-coded prefs to the current string segment values", () => {
    const [kitchen] = deriveRoomRows(roomMap, prefs, new Set(["1"]), "1");
    const byField = Object.fromEntries(kitchen.detail.map((c) => [c.field, c.value]));
    expect(byField).toEqual({ repeat: "double", mode: "vacuum_and_mop", power: "medium", water: "high" });
  });

  it("gates the Water control off in vacuum mode", () => {
    const vacuumPrefs = { "1": { order: 0, custom: true, mode: 0, power: 1, water: 1, repeat: 0 } };
    const [room] = deriveRoomRows({ "1": roomMap["1"] }, vacuumPrefs, new Set(["1"]), "1");
    const water = room.detail.find((c) => c.field === "water");
    expect(water.disabled).toBe(true);
  });
});

async function mount(rows, busy = false) {
  const el = document.createElement("karcher-room-list");
  el.rows = rows;
  el.busy = busy;
  document.body.appendChild(el);
  await el.updateComplete;
  return el;
}

const baseRows = (over = {}) => deriveRoomRows(roomMap, prefs, new Set(["1"]), over.detailRoomId ?? null);

describe("KarcherRoomList (Lit leaf)", () => {
  it("is defined and renders a row per room plus the footer", async () => {
    const el = await mount(baseRows());
    expect(customElements.get("karcher-room-list")).toBeTruthy();
    expect(el.querySelectorAll(".room-row")).toHaveLength(2);
    expect(el.querySelector(".room-list-footer")).toBeTruthy();
  });

  it("renders an empty-state message when there are no rows", async () => {
    const el = await mount([]);
    expect(el.querySelectorAll(".room-row")).toHaveLength(0);
    expect(el.textContent).toContain("No rooms found");
  });

  it("toggling a room emits room-toggle {roomId, on}", async () => {
    const el = await mount(baseRows());
    let detail = null;
    el.addEventListener("room-toggle", (e) => { detail = e.detail; });
    // room 2 is disabled → toggling turns it on
    el.querySelectorAll(".room-row")[1].querySelector(".room-toggle").click();
    expect(detail).toEqual({ roomId: "2", on: true });
  });

  it("clicking an enabled room's text emits room-expand", async () => {
    const el = await mount(baseRows());
    let detail = null;
    el.addEventListener("room-expand", (e) => { detail = e.detail; });
    el.querySelector(".room-row .room-text").click();
    expect(detail).toEqual({ roomId: "1" });
  });

  it("a disabled room does not emit expand", async () => {
    const el = await mount(baseRows());
    let fired = false;
    el.addEventListener("room-expand", () => { fired = true; });
    el.querySelectorAll(".room-row")[1].querySelector(".room-text").click(); // room 2 disabled
    expect(fired).toBe(false);
  });

  it("busy suppresses toggle and expand", async () => {
    const el = await mount(baseRows(), true);
    let fired = false;
    el.addEventListener("room-toggle", () => { fired = true; });
    el.addEventListener("room-expand", () => { fired = true; });
    el.querySelector(".room-toggle").click();
    el.querySelector(".room-text").click();
    expect(fired).toBe(false);
  });

  it("changing a detail segment emits room-pref {roomId, field, value}", async () => {
    const el = await mount(baseRows({ detailRoomId: "1" }));
    let detail = null;
    el.addEventListener("room-pref", (e) => { detail = e.detail; });
    // First detail control is repeat; click the ×1 option (single)
    const seg = el.querySelector(".room-inline-detail .segmented");
    seg.querySelector(".seg-btn").click();
    expect(detail).toEqual({ roomId: "1", field: "repeat", value: "single" });
  });

  it("a clicked detail segment highlights immediately and survives a stale poll", async () => {
    const el = await mount(baseRows({ detailRoomId: "1" }));
    // repeat row: current is "double" (×2). Click ×1 (single).
    const seg = el.querySelector(".room-inline-detail .segmented");
    const [single] = seg.querySelectorAll(".seg-btn");
    single.click();
    await el.updateComplete;
    expect(single.classList.contains("active")).toBe(true); // optimistic

    // A poll arrives before the robot confirmed — rows still report "double".
    el.rows = deriveRoomRows(roomMap, prefs, new Set(["1"]), "1");
    await el.updateComplete;
    const [singleAfter] = el.querySelectorAll(".room-inline-detail .segmented")[0].querySelectorAll(".seg-btn");
    expect(singleAfter.classList.contains("active")).toBe(true); // pending still wins
  });

  it("suppresses re-render mid-drag (shouldUpdate guard)", async () => {
    const el = await mount(baseRows());
    el._dragSrcId = "1"; // simulate an in-flight drag
    el.rows = []; // a poll arrives that would normally blank the list
    await el.updateComplete;
    // The list is NOT rebuilt while dragging — old rows remain.
    expect(el.querySelectorAll(".room-row")).toHaveLength(2);
  });

  it("emits room-reorder with the new order array", async () => {
    const el = await mount(baseRows());
    let detail = null;
    el.addEventListener("room-reorder", (e) => { detail = e.detail; });
    // Drive the reorder path directly (the DnD gesture is in-HA-verified).
    el._dragSrcId = "2";
    el._onDrop({ preventDefault() {}, target: el.querySelectorAll(".room-row")[0] });
    expect(detail).toEqual({ order: ["2", "1"] });
  });
});
