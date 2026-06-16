import { describe, it, expect } from "vitest";
import {
  roomColor,
  deriveCompanions,
  isBusy,
  buttonStates,
  canvasScale,
  clientToImagePx,
  buildCellLookup,
  hitTestRooms,
  roomBoundingBox,
  roomCentroid,
  parseRoomOrder,
  relativeTime,
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
