import { describe, it, expect } from "vitest";
import {
  roomColor,
  deriveCompanions,
  isBusy,
  isOccupied,
  buttonStates,
  canvasScale,
  clientToImagePx,
  buildCellLookup,
  hitTestRooms,
  roomBoundingBox,
  roomCentroid,
  parseRoomOrder,
  relativeTime,
  reconcileCustomise,
  computeListKey,
  selectionHint,
  buttonLabels,
  roomChipText,
  activeRoomId,
  computeDrawKey,
  drawMap,
  legendItems,
  minZonePx,
  clampZoneRect,
} from "../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js";

const PALETTE = ["#c9dcd2", "#e9bac0", "#e8e7e3", "#bddde0", "#b7b7b7"];

describe("roomColor", () => {
  it("maps color_id 1-5 to the palette in order", () => {
    expect(roomColor(1)).toBe(PALETTE[0]);
    expect(roomColor(5)).toBe(PALETTE[4]);
  });
  it("wraps via modulo for ids beyond the palette", () => {
    expect(roomColor(6)).toBe(PALETTE[0]);
    expect(roomColor(7)).toBe(PALETTE[1]);
  });
  it("falls back to the first colour for invalid input", () => {
    expect(roomColor(0)).toBe(PALETTE[0]);
    expect(roomColor(undefined)).toBe(PALETTE[0]);
    expect(roomColor(-3)).toBe(PALETTE[0]);
  });
});

describe("deriveCompanions", () => {
  it("derives companion entity ids from a vacuum stem", () => {
    const c = deriveCompanions("vacuum.rocky_ii");
    expect(c.battery_entity).toBe("sensor.rocky_ii_battery");
    expect(c.charging_entity).toBe("binary_sensor.rocky_ii_charging");
    expect(c.map_entity).toBe("image.rocky_ii_map");
    expect(c.cleaning_mode_entity).toBe("select.rocky_ii_cleaning_mode");
  });
  it("returns an empty object for falsy input", () => {
    expect(deriveCompanions("")).toEqual({});
    expect(deriveCompanions(undefined)).toEqual({});
  });
});

describe("isBusy", () => {
  it("is true only while cleaning or returning", () => {
    expect(isBusy("cleaning")).toBe(true);
    expect(isBusy("returning")).toBe(true);
    expect(isBusy("paused")).toBe(false);
    expect(isBusy("docked")).toBe(false);
    expect(isBusy("idle")).toBe(false);
    expect(isBusy(undefined)).toBe(false);
  });
});

describe("isOccupied", () => {
  it("is true while cleaning, returning, or paused", () => {
    expect(isOccupied("cleaning")).toBe(true);
    expect(isOccupied("returning")).toBe(true);
    expect(isOccupied("paused")).toBe(true);
    expect(isOccupied("docked")).toBe(false);
    expect(isOccupied("idle")).toBe(false);
    expect(isOccupied(undefined)).toBe(false);
  });
});

describe("buttonStates", () => {
  it("docked: only play enabled, no stop, no dock", () => {
    const s = buttonStates("docked");
    expect(s).toMatchObject({ isOffline: false, canStop: false, canDock: false });
  });
  it("idle: dock enabled, stop disabled", () => {
    const s = buttonStates("idle");
    expect(s.canDock).toBe(true);
    expect(s.canStop).toBe(false);
  });
  it("cleaning: stop and dock enabled", () => {
    const s = buttonStates("cleaning");
    expect(s).toMatchObject({ isCleaning: true, canStop: true, canDock: true });
  });
  it("paused: stop and dock enabled", () => {
    const s = buttonStates("paused");
    expect(s).toMatchObject({ isPaused: true, canStop: true, canDock: true });
  });
  it("returning: stop enabled, dock disabled", () => {
    const s = buttonStates("returning");
    expect(s).toMatchObject({ isReturning: true, canStop: true, canDock: false });
  });
  it("unavailable: offline flag set, nothing actionable", () => {
    const s = buttonStates("unavailable");
    expect(s).toMatchObject({ isOffline: true, canStop: false, canDock: false });
  });
  it("offline arg forces isOffline even when the cached activity is actionable", () => {
    // Connectivity-only outage window: vacuum still reports "cleaning" from
    // cache, but the robot is unreachable → buttons must read as offline.
    const s = buttonStates("cleaning", true);
    expect(s.isOffline).toBe(true);
  });
  it("offline=false leaves activity-driven flags intact", () => {
    expect(buttonStates("cleaning", false)).toMatchObject({ isOffline: false, canStop: true });
  });
});

describe("canvasScale", () => {
  it("computes 1:1 scale when canvas matches image", () => {
    expect(canvasScale(400, 300, { width: 400, height: 300 }, 1))
      .toEqual({ scaleX: 1, scaleY: 1 });
  });
  it("divides device pixels by dpr before scaling", () => {
    // dpr=2 canvas is 800x600 device px backing a 400x300 css box over a 400x300 image
    expect(canvasScale(800, 600, { width: 400, height: 300 }, 2))
      .toEqual({ scaleX: 1, scaleY: 1 });
  });
  it("scales independently per axis", () => {
    expect(canvasScale(400, 300, { width: 200, height: 300 }, 1))
      .toEqual({ scaleX: 2, scaleY: 1 });
  });
});

describe("clientToImagePx", () => {
  const rect = { left: 10, top: 20, width: 200, height: 100 };
  const imgSize = { width: 400, height: 200, cell_size: 1 };

  it("maps a click to image pixels accounting for rect offset and scale", () => {
    // click at css (110, 70) → 100px into a 200px-wide box → 50% → 200 image px
    const r = clientToImagePx(110, 70, rect, imgSize);
    expect(r.px).toBe(200);
    expect(r.py).toBe(100);
  });
  it("snaps to the cell grid", () => {
    const r = clientToImagePx(110, 70, rect, { width: 400, height: 200, cell_size: 8 });
    expect(r.snapCol).toBe(Math.floor(200 / 8) * 8);
    expect(r.snapRow).toBe(Math.floor(100 / 8) * 8);
  });
  it("defaults cell_size to 1 when absent", () => {
    const r = clientToImagePx(110, 70, rect, { width: 400, height: 200 });
    expect(r.snapCol).toBe(r.px);
    expect(r.snapRow).toBe(r.py);
  });
});

describe("minZonePx", () => {
  it("is 7 cells worth of image px (one robot-width)", () => {
    expect(minZonePx(2)).toBe(14);
  });
  it("defaults cellSize to 1 when absent", () => {
    expect(minZonePx(0)).toBe(7);
    expect(minZonePx(undefined)).toBe(7);
  });
});

describe("clampZoneRect", () => {
  it("leaves a rect alone once it already meets the minimum on both sides", () => {
    const r = clampZoneRect({ x0: 0, y0: 0, x1: 20, y1: 30 }, 14);
    expect(r).toEqual({ x0: 0, y0: 0, x1: 20, y1: 30 });
  });
  it("pushes the dragged corner out to the minimum when a side is too small", () => {
    const r = clampZoneRect({ x0: 0, y0: 0, x1: 5, y1: 30 }, 14);
    expect(r).toEqual({ x0: 0, y0: 0, x1: 14, y1: 30 });
  });
  it("clamps in the direction the user dragged, including negative drags", () => {
    const r = clampZoneRect({ x0: 10, y0: 10, x1: 8, y1: 9 }, 14);
    expect(r).toEqual({ x0: 10, y0: 10, x1: -4, y1: -4 });
  });
  it("a zero-delta drag (pointer-down only) still yields the minimum size", () => {
    const r = clampZoneRect({ x0: 10, y0: 10, x1: 10, y1: 10 }, 14);
    expect(r).toEqual({ x0: 10, y0: 10, x1: 24, y1: 24 });
  });
});

describe("buildCellLookup", () => {
  it("expands RLE spans with cell_size into a row,col map", () => {
    const roomMap = { "3": { cells: [[10, 0, 3]] } }; // 3 cells of size 4 from col 0
    const lk = buildCellLookup(roomMap, 4);
    expect(lk.get("10,0")).toBe("3");
    expect(lk.get("10,4")).toBe("3");
    expect(lk.get("10,8")).toBe("3");
    expect(lk.get("10,12")).toBeUndefined();
  });
  it("handles rooms with no cells", () => {
    expect(buildCellLookup({ "1": {} }, 1).size).toBe(0);
    expect(buildCellLookup({}, 1).size).toBe(0);
  });
  it("defaults cell_size to 1", () => {
    const lk = buildCellLookup({ "2": { cells: [[5, 7, 2]] } }, undefined);
    expect(lk.get("5,7")).toBe("2");
    expect(lk.get("5,8")).toBe("2");
  });
});

describe("hitTestRooms", () => {
  const checkboxes = [{ id: "9", x: 100, y: 100, w: 20, h: 20 }];
  const lookup = new Map([["40,40", "5"]]);

  it("prefers a checkbox hit over the cell lookup", () => {
    expect(hitTestRooms(105, 105, 40, 40, checkboxes, lookup)).toBe("9");
  });
  it("respects checkbox half-open bounds (>= x, < x+w)", () => {
    expect(hitTestRooms(100, 100, 0, 0, checkboxes, lookup)).toBe("9");
    expect(hitTestRooms(120, 100, 0, 0, checkboxes, lookup)).toBeUndefined();
  });
  it("falls back to the cell lookup when no checkbox matches", () => {
    expect(hitTestRooms(5, 5, 40, 40, checkboxes, lookup)).toBe("5");
  });
  it("returns undefined on a total miss", () => {
    expect(hitTestRooms(5, 5, 0, 0, checkboxes, lookup)).toBeUndefined();
  });
  it("tolerates missing checkbox/lookup args", () => {
    expect(hitTestRooms(5, 5, 40, 40, undefined, lookup)).toBe("5");
    expect(hitTestRooms(5, 5, 40, 40, checkboxes, undefined)).toBeUndefined();
  });
});

describe("roomBoundingBox / roomCentroid", () => {
  it("computes the image-space bbox across multiple spans (cs scales runLen)", () => {
    const cells = [[10, 4, 2], [14, 0, 1], [12, 8, 3]];
    const bbox = roomBoundingBox(cells, 2);
    expect(bbox).toEqual({ minRow: 10, maxRow: 14, minCol: 0, maxCol: 8 + 3 * 2 });
  });
  it("handles a single cell", () => {
    const bbox = roomBoundingBox([[5, 5, 1]], 1);
    expect(bbox).toEqual({ minRow: 5, maxRow: 5, minCol: 5, maxCol: 6 });
    expect(roomCentroid(bbox)).toEqual({ cx: 5.5, cy: 5 });
  });
  it("centroid is the midpoint of the bbox", () => {
    expect(roomCentroid({ minRow: 0, maxRow: 10, minCol: 2, maxCol: 8 }))
      .toEqual({ cx: 5, cy: 5 });
  });
});

describe("parseRoomOrder", () => {
  it("sorts room ids by persisted order", () => {
    const roomMap = { a: {}, b: {}, c: {} };
    const prefs = { a: { order: 2 }, b: { order: 0 }, c: { order: 1 } };
    expect(parseRoomOrder(roomMap, prefs)).toEqual(["b", "c", "a"]);
  });
  it("sinks rooms without an order to the end (999 fallback), preserving insertion order among ties", () => {
    const roomMap = { b: {}, c: {}, a: {} };
    const prefs = { a: { order: 5 } }; // b and c both default to 999
    expect(parseRoomOrder(roomMap, prefs)).toEqual(["a", "b", "c"]);
  });
  it("tolerates empty/missing inputs", () => {
    expect(parseRoomOrder({}, {})).toEqual([]);
    expect(parseRoomOrder(undefined, undefined)).toEqual([]);
  });
});

describe("relativeTime", () => {
  const now = Date.UTC(2026, 5, 16, 12, 0, 0);
  const ago = (ms) => new Date(now - ms).toISOString();
  const MIN = 60_000, HOUR = 60 * MIN, DAY = 24 * HOUR;

  it("returns null for an unparseable string", () => {
    expect(relativeTime("not-a-date", now)).toBeNull();
  });
  it("formats sub-minute as Just now", () => {
    expect(relativeTime(ago(30_000), now)).toBe("Just now");
  });
  it("formats minutes and hours", () => {
    expect(relativeTime(ago(5 * MIN), now)).toBe("5m ago");
    expect(relativeTime(ago(3 * HOUR), now)).toBe("3h ago");
  });
  it("formats one day as Yesterday and 2-6 days as Nd ago", () => {
    expect(relativeTime(ago(1 * DAY), now)).toBe("Yesterday");
    expect(relativeTime(ago(3 * DAY), now)).toBe("3d ago");
  });
  it("falls back to a date string beyond a week", () => {
    expect(relativeTime(ago(10 * DAY), now)).toMatch(/\w+ \d+/);
  });
});

describe("reconcileCustomise", () => {
  const prefs = (custom) => ({ "1": { custom } });

  it("mirrors persisted custom=true into the selected set (external change)", () => {
    const r = reconcileCustomise(["1"], prefs(true), new Map(), new Set());
    expect(r.selected.has("1")).toBe(true);
    expect(r.pending.size).toBe(0);
  });

  it("removes a room from selected when persisted custom=false (toggle off)", () => {
    const r = reconcileCustomise(["1"], prefs(false), new Map(), new Set(["1"]));
    expect(r.selected.has("1")).toBe(false);
  });

  it("keeps optimistic state while a toggle is pending and unconfirmed", () => {
    // User just enabled room 1; persisted pref still shows false (in flight).
    const r = reconcileCustomise(["1"], prefs(false), new Map([["1", true]]), new Set(["1"]));
    expect(r.selected.has("1")).toBe(true); // optimistic value wins
    expect(r.pending.has("1")).toBe(true);  // still pending
  });

  it("clears the pending entry once the persisted pref matches the expectation", () => {
    const r = reconcileCustomise(["1"], prefs(true), new Map([["1", true]]), new Set(["1"]));
    expect(r.pending.has("1")).toBe(false);
    expect(r.selected.has("1")).toBe(true);
  });

  it("clears pending and removes from selected when a pending toggle-off confirms", () => {
    const r = reconcileCustomise(["1"], prefs(false), new Map([["1", false]]), new Set(["1"]));
    expect(r.pending.has("1")).toBe(false);
    expect(r.selected.has("1")).toBe(false);
  });

  it("does not mutate the input sets/maps", () => {
    const inSel = new Set();
    const inPend = new Map();
    reconcileCustomise(["1"], prefs(true), inPend, inSel);
    expect(inSel.size).toBe(0);
    expect(inPend.size).toBe(0);
  });
});

describe("computeListKey", () => {
  const prefs = { "1": { mode: 0, power: 1, water: 2, repeat: 0 }, "2": { mode: 1 } };
  const base = () => computeListKey(["1", "2"], prefs, new Set(["1"]), null, false);

  it("is stable for identical inputs", () => {
    expect(computeListKey(["1", "2"], prefs, new Set(["1"]), null, false)).toBe(base());
  });
  it("changes when room order changes", () => {
    expect(computeListKey(["2", "1"], prefs, new Set(["1"]), null, false)).not.toBe(base());
  });
  it("changes when a per-room setting changes", () => {
    const p2 = { ...prefs, "1": { mode: 2, power: 1, water: 2, repeat: 0 } };
    expect(computeListKey(["1", "2"], p2, new Set(["1"]), null, false)).not.toBe(base());
  });
  it("changes when the selected set changes", () => {
    expect(computeListKey(["1", "2"], prefs, new Set(["2"]), null, false)).not.toBe(base());
  });
  it("changes when the expanded row changes", () => {
    expect(computeListKey(["1", "2"], prefs, new Set(["1"]), "1", false)).not.toBe(base());
  });
  it("changes when busy flips", () => {
    expect(computeListKey(["1", "2"], prefs, new Set(["1"]), null, true)).not.toBe(base());
  });
});

describe("selectionHint", () => {
  const names = (id) => ({ "1": "Kitchen", "2": "Hall", "3": "Den" }[id] || id);

  it("flips the chip label to 'Clear all' when every room is selected", () => {
    const all = selectionHint(["1", "2"], new Set(["1", "2"]), "default", names);
    expect(all.chipLabel).toBe("Clear all");
    const some = selectionHint(["1", "2"], new Set(["1"]), "default", names);
    expect(some.chipLabel).toBe("Select all");
  });

  it("default mode: empty vs selected badge text", () => {
    expect(selectionHint(["1"], new Set(), "default", names).badge)
      .toBe("Tap a room to select · cleans all if none selected");
    expect(selectionHint(["1", "2"], new Set(["1"]), "default", names).badge)
      .toBe("Cleaning 1 room · Kitchen");
  });

  it("customise mode: empty vs enabled badge text", () => {
    expect(selectionHint(["1"], new Set(), "customise", names).badge)
      .toBe("Tap a room to select");
    expect(selectionHint(["1", "2"], new Set(["1", "2"]), "customise", names).badge)
      .toBe("2 rooms enabled · Kitchen, Hall");
  });

  it("previews the first two names and counts the overflow", () => {
    expect(selectionHint(["1", "2", "3"], new Set(["1", "2", "3"]), "default", names).badge)
      .toBe("Cleaning 3 rooms · Kitchen, Hall +1");
  });

  it("falls back to the id when no name is available", () => {
    expect(selectionHint(["9"], new Set(["9"]), "default", undefined).badge)
      .toBe("Cleaning 1 room · 9");
  });
});

describe("buttonLabels", () => {
  it("cleaning → Pause", () => {
    const l = buttonLabels("cleaning");
    expect(l.playLabel).toBe("Pause");
    expect(l.playIcon).toBe("mdi:pause");
    expect(l.playAction).toBe("pause");
  });
  it("paused → Resume / play", () => {
    const l = buttonLabels("paused");
    expect(l.playLabel).toBe("Resume");
    expect(l.playAction).toBe("play");
  });
  it("idle/docked → Start", () => {
    expect(buttonLabels("idle").playLabel).toBe("Start");
    expect(buttonLabels("docked").playLabel).toBe("Start");
  });
  it("dock label reflects the docked state", () => {
    expect(buttonLabels("docked").dockLabel).toBe("Docked");
    expect(buttonLabels("cleaning").dockLabel).toBe("Dock");
  });
});

describe("roomChipText", () => {
  it("name only when area is unknown", () => {
    expect(roomChipText({ name: "Hall" })).toBe("Hall");
  });
  it("appends an area line when area_m2 is set", () => {
    expect(roomChipText({ name: "Hall", area_m2: 12.5 })).toBe("Hall\n12.5 m²");
  });
  it("falls back to id when name is missing", () => {
    expect(roomChipText({ id: "7" })).toBe("7");
  });
});

describe("activeRoomId", () => {
  const roomMap = { "1": { name: "Kitchen" }, "2": { name: "Hall" } };

  it("returns the id of the room whose name matches the current room", () => {
    expect(activeRoomId(roomMap, "Hall", true)).toBe("2");
  });
  it("returns null when not cleaning", () => {
    expect(activeRoomId(roomMap, "Hall", false)).toBeNull();
  });
  it("returns null for unknown/unavailable/empty current room", () => {
    expect(activeRoomId(roomMap, "unknown", true)).toBeNull();
    expect(activeRoomId(roomMap, "unavailable", true)).toBeNull();
    expect(activeRoomId(roomMap, null, true)).toBeNull();
  });
  it("returns null when no room name matches", () => {
    expect(activeRoomId(roomMap, "Garage", true)).toBeNull();
  });
});

describe("computeDrawKey", () => {
  const attr = {
    robot_px: { x: 1, y: 2, phi: 0.5 },
    charger_px: { x: 3, y: 4 },
    cur_path_px: [1, 2, 3, 4],
    room_map: { "1": { name: "Hall", color_id: 2 } },
  };
  const vs = () => ({
    mapToken: "t1", cardMode: "standard", detailRoomId: null,
    selectedRooms: new Set(["1"]), customiseSelected: new Set(),
    robotIcon: null, canvasWidth: 400, canvasHeight: 300, dpr: 2,
  });

  it("is stable for identical inputs", () => {
    expect(computeDrawKey(attr, vs())).toBe(computeDrawKey(attr, vs()));
  });
  it("changes when a room is renamed (room_map rebuilt fresh each update)", () => {
    const renamed = { ...attr, room_map: { "1": { name: "Foyer", color_id: 2 } } };
    expect(computeDrawKey(renamed, vs())).not.toBe(computeDrawKey(attr, vs()));
  });
  it("changes when the robot pose moves", () => {
    const moved = { ...attr, robot_px: { x: 9, y: 2, phi: 0.5 } };
    expect(computeDrawKey(moved, vs())).not.toBe(computeDrawKey(attr, vs()));
  });
  it("changes when the selection set changes", () => {
    const v = { ...vs(), selectedRooms: new Set(["2"]) };
    expect(computeDrawKey(attr, v)).not.toBe(computeDrawKey(attr, vs()));
  });
  it("changes when the map token changes", () => {
    const v = { ...vs(), mapToken: "t2" };
    expect(computeDrawKey(attr, v)).not.toBe(computeDrawKey(attr, vs()));
  });
});

describe("drawMap hit areas", () => {
  // Minimal 2D-context stub: the renderer makes many calls, but the hit-area
  // geometry only depends on measureText().width + canvasScale. We assert the
  // RETURNED hit areas (what the click handler consumes), not draw calls.
  function fakeCtx() {
    return new Proxy({ font: "", measureText: () => ({ width: 20 }) }, {
      get: (t, k) => (k in t ? t[k] : () => {}),
      set: (t, k, v) => { t[k] = v; return true; },
    });
  }
  const canvas = { width: 400, height: 400 };
  const imgSize = { width: 100, height: 100, cell_size: 5 };
  const baseVs = (over = {}) => ({
    attr: {
      map_image_size: imgSize,
      room_map: { "1": { name: "Hall", color_id: 1, cells: [[10, 10, 4]] } },
      room_preferences: {},
    },
    dpr: 1, mapImg: {}, robotIcon: null, cardMode: "standard",
    detailRoomId: null, selectedRooms: new Set(), customiseSelected: new Set(),
    activeRoomId: null, currentRoomName: null, mapToken: "t",
    canvasWidth: 400, canvasHeight: 400, ...over,
  });

  it("returns no hit areas when there is no map image", () => {
    expect(drawMap(fakeCtx(), canvas, baseVs({ mapImg: null }))).toEqual([]);
  });

  it("emits one hit area per labelled room, with an id", () => {
    const hits = drawMap(fakeCtx(), canvas, baseVs());
    expect(hits).toHaveLength(1);
    expect(hits[0].id).toBe("1");
  });

  it("hit areas are in image space (inverse of the canvas→image scale)", () => {
    // scaleX = (400/1)/100 = 4, so image-space width = pixel width / 4.
    const hits = drawMap(fakeCtx(), canvas, baseVs());
    const h = hits[0];
    // Hit area covers the whole pill, so w/h are positive (pill is wider than tall).
    expect(h.w).toBeGreaterThan(0);
    expect(h.h).toBeGreaterThan(0);
    // The hit box must sit within the image bounds (0..100).
    expect(h.x).toBeGreaterThanOrEqual(0);
    expect(h.x + h.w).toBeLessThanOrEqual(imgSize.width);
  });

  it("skips rooms with no cells", () => {
    const vs = baseVs();
    vs.attr.room_map = { "1": { name: "Empty", cells: [] } };
    expect(drawMap(fakeCtx(), canvas, vs)).toEqual([]);
  });

  it("draws the area-selection rectangle when zoneRect is set", () => {
    const vs = baseVs({ zoneRect: { x0: 10, y0: 10, x1: 50, y1: 50 } });
    expect(() => drawMap(fakeCtx(), canvas, vs)).not.toThrow();
    // No zoneRect → drawZoneRect is a no-op (still no throw).
    expect(() => drawMap(fakeCtx(), canvas, baseVs())).not.toThrow();
  });

  it("customise mode emits a hit area for a room without a pref", () => {
    const vs = baseVs({ cardMode: "customise" });
    // Customise reuses the standard pill, so room "1" gets a chip + hit area
    // even with no entry in room_preferences.
    const hits = drawMap(fakeCtx(), canvas, vs);
    expect(hits).toHaveLength(1);
    expect(hits[0].id).toBe("1");
  });
});

describe("drawMap canvas draw calls (recording ctx)", () => {
  // Unlike the hit-area block above, this asserts the ctx call sequence the
  // renderer emits — the layer that was previously browser-only. The recording
  // proxy logs every method call so we can assert what got drawn.
  function recordingCtx() {
    const calls = [];
    const target = { font: "", measureText: () => ({ width: 20 }) };
    const ctx = new Proxy(target, {
      get: (t, k) => (k in t ? t[k] : (...args) => { calls.push({ fn: k, args }); }),
      set: (t, k, v) => { t[k] = v; return true; },
    });
    ctx._calls = calls;
    return ctx;
  }
  const fnCalls = (ctx, name) => ctx._calls.filter((c) => c.fn === name);

  const canvas = { width: 400, height: 400 };
  const imgSize = { width: 100, height: 100, cell_size: 5 };
  const MAP = { _isMap: true };
  const baseVs = (over = {}) => ({
    attr: {
      map_image_size: imgSize,
      room_map: { "1": { name: "Hall", color_id: 1, cells: [[10, 10, 4]] } },
      room_preferences: {},
    },
    dpr: 1, mapImg: MAP, robotIcon: null, cardMode: "standard",
    detailRoomId: null, selectedRooms: new Set(), customiseSelected: new Set(),
    activeRoomId: null, mapToken: "t",
    canvasWidth: 400, canvasHeight: 400, ...over,
  });

  it("draws the map bitmap and clears the canvas first", () => {
    const ctx = recordingCtx();
    drawMap(ctx, canvas, baseVs());
    expect(fnCalls(ctx, "clearRect")).toHaveLength(1);
    const drawn = fnCalls(ctx, "drawImage");
    expect(drawn.length).toBeGreaterThanOrEqual(1);
    expect(drawn[0].args[0]).toBe(MAP); // the map image itself
  });

  it("emits no ctx calls at all when there is no map image", () => {
    const ctx = recordingCtx();
    drawMap(ctx, canvas, baseVs({ mapImg: null }));
    expect(ctx._calls).toHaveLength(0);
  });

  it("fills a room overlay rect for a selected room in customise mode", () => {
    const ctx = recordingCtx();
    const vs = baseVs({ cardMode: "customise", customiseSelected: new Set(["1"]) });
    vs.attr.room_preferences = { "1": { mode: 0, power: 1, water: 1, repeat: 0, custom: true } };
    drawMap(ctx, canvas, vs);
    expect(fnCalls(ctx, "fillRect").length).toBeGreaterThanOrEqual(1);
  });

  it("draws the cur-path stroke only when a path is present", () => {
    const without = recordingCtx();
    drawMap(without, canvas, baseVs());
    const withPath = recordingCtx();
    const vs = baseVs();
    vs.attr.cur_path_px = [10, 10, 20, 20, 30, 10];
    drawMap(withPath, canvas, vs);
    expect(fnCalls(withPath, "stroke").length).toBeGreaterThan(fnCalls(without, "stroke").length);
  });

  it("draws the robot (fallback circle) only when robot_px is present", () => {
    const without = recordingCtx();
    drawMap(without, canvas, baseVs());
    const withRobot = recordingCtx();
    const vs = baseVs();
    vs.attr.robot_px = { x: 50, y: 50, phi: 0 };
    drawMap(withRobot, canvas, vs);
    // The robot glyph adds arc() calls (fallback disc) that aren't there otherwise.
    expect(fnCalls(withRobot, "arc").length).toBeGreaterThan(fnCalls(without, "arc").length);
  });

  it("draws the charger marker when charger_px is present", () => {
    const without = recordingCtx();
    drawMap(without, canvas, baseVs());
    const withCharger = recordingCtx();
    const vs = baseVs();
    vs.attr.charger_px = { x: 20, y: 20 };
    drawMap(withCharger, canvas, vs);
    expect(fnCalls(withCharger, "arc").length).toBeGreaterThan(fnCalls(without, "arc").length);
  });
});

describe("legendItems", () => {
  it("returns empty when no map data", () => {
    expect(legendItems(undefined)).toEqual([]);
    expect(legendItems({})).toEqual([]);
  });

  it("includes only present zones, with counts and outline colours", () => {
    const items = legendItems({
      map_legend: { no_go: 1, no_mop: 2, virtual_wall: 0, carpet: false, objects: {} },
    });
    const byKey = Object.fromEntries(items.map((i) => [i.key, i]));
    expect(Object.keys(byKey).sort()).toEqual(["no_go", "no_mop"]);
    // Swatches carry a light fill + solid outline (color) so they match the map.
    expect(byKey.no_go).toMatchObject({ label: "No-go", kind: "swatch", count: 1, color: "rgb(200,40,40)", fill: "rgba(220,60,60,0.20)" });
    expect(byKey.no_mop).toMatchObject({ label: "No-mop", count: 2, color: "rgb(50,90,200)" });
  });

  it("maps object type ids to labels/colours and counts", () => {
    const items = legendItems({ map_legend: { objects: { "1003": 2, "9999": 1 } } });
    const wire = items.find((i) => i.key === "obj_1003");
    const unknown = items.find((i) => i.key === "obj_9999");
    expect(wire).toMatchObject({ label: "Wire", kind: "dot", color: "rgb(230,60,60)", count: 2 });
    expect(unknown).toMatchObject({ label: "Object", color: "rgb(160,160,160)" });
  });

  it("derives robot/dock/path from px overlays, not map_legend", () => {
    const items = legendItems({
      robot_px: { x: 1, y: 2 },
      charger_px: { x: 3, y: 4 },
      cur_path_px: [{ x: 0, y: 0 }],
      map_legend: { carpet: true },
    });
    const keys = items.map((i) => i.key);
    expect(keys).toContain("robot");
    expect(keys).toContain("dock");
    expect(keys).toContain("path");
    expect(keys).toContain("carpet");
    // drawCharger paints a teal disc with a white centre — a ring, not a
    // filled dot — so the legend swatch is white with a teal ring border.
    const dock = items.find((i) => i.key === "dock");
    expect(dock.color).toBe("#fff");
    expect(dock.ringColor).toBe("#4db6c4");
    expect(dock.ring).toBe(true);
    // Path colour matches drawCurPath's grey stroke, not orange.
    expect(items.find((i) => i.key === "path").color).toBe("#999");
    // Path absent when the overlay is empty.
    expect(legendItems({ cur_path_px: [] }).some((i) => i.key === "path")).toBe(false);
  });
});
