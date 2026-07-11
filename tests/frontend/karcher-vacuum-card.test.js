import { describe, it, expect } from "vitest";
import {
  roomColor,
  deriveCompanions,
  nextEditorConfig,
  isBusy,
  isOccupied,
  buttonStates,
  canvasScale,
  clientToImagePx,
  clampZoom,
  zoomAtPoint,
  clampPan,
  panEdgeHidden,
  pinchStep,
  dragPan,
  fitContentBox,
  TAP_SLOP_PX,
  buildCellLookup,
  hitTestRooms,
  roomBoundingBox,
  roomCentroid,
  parseRoomOrder,
  relativeTime,
  reconcileCustomise,
  targetStripLabel,
  buttonLabels,
  primaryCleanLabel,
  roomChipText,
  computeDrawKey,
  drawMap,
  legendItems,
  minZonePx,
  clampZoneRect,
  hitTestZoneRect,
  resizeZoneRect,
  moveZoneRect,
  defaultZoneRect,
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
    expect(c.fault_code_entity).toBe("sensor.rocky_ii_robot_status");
  });
  it("returns an empty object for falsy input", () => {
    expect(deriveCompanions("")).toEqual({});
    expect(deriveCompanions(undefined)).toEqual({});
  });
});

describe("nextEditorConfig", () => {
  it("sets a companion override and keeps the rest of the config", () => {
    const next = nextEditorConfig(
      { vacuum_entity: "vacuum.rcv5" }, "battery_entity", "sensor.custom_batt",
    );
    expect(next.battery_entity).toBe("sensor.custom_batt");
    expect(next.vacuum_entity).toBe("vacuum.rcv5");
  });

  it("clears a key when the picker is emptied (no undefined left behind)", () => {
    const next = nextEditorConfig(
      { vacuum_entity: "vacuum.rcv5", battery_entity: "sensor.x" }, "battery_entity", "",
    );
    expect("battery_entity" in next).toBe(false);
    expect(next).toEqual({ vacuum_entity: "vacuum.rcv5" });
  });

  it("drops companion overrides still at the old derived default when vacuum changes", () => {
    const prev = {
      vacuum_entity: "vacuum.old",
      battery_entity: "sensor.old_battery", // == old derived default → drop
      map_entity: "image.my_custom_map",    // explicit override → keep
    };
    const next = nextEditorConfig(prev, "vacuum_entity", "vacuum.new");
    expect(next.vacuum_entity).toBe("vacuum.new");
    expect("battery_entity" in next).toBe(false);
    expect(next.map_entity).toBe("image.my_custom_map");
  });

  it("does not mutate the previous config", () => {
    const prev = { vacuum_entity: "vacuum.rcv5", battery_entity: "sensor.x" };
    const snapshot = { ...prev };
    nextEditorConfig(prev, "battery_entity", "");
    expect(prev).toEqual(snapshot);
  });

  it("tolerates a missing prevConfig", () => {
    expect(nextEditorConfig(undefined, "vacuum_entity", "vacuum.rcv5"))
      .toEqual({ vacuum_entity: "vacuum.rcv5" });
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
  it("is unchanged at zoom=1/pan=0 (explicit defaults match the implicit ones)", () => {
    const a = clientToImagePx(110, 70, rect, imgSize);
    const b = clientToImagePx(110, 70, rect, imgSize, 1, { x: 0, y: 0 });
    expect(b).toEqual(a);
  });
  it("un-pans and un-zooms before converting to image space", () => {
    // zoom=2, pan={x:-50,y:-20}: css point (110,70) minus pan = (160,90),
    // divided by zoom = (80,45) — half the unzoomed offset from rect origin.
    const zoomed = clientToImagePx(110, 70, rect, imgSize, 2, { x: -50, y: -20 });
    const cssX = (110 - rect.left - -50) / 2;
    const cssY = (70 - rect.top - -20) / 2;
    expect(zoomed.px).toBe(Math.floor(cssX * (imgSize.width / rect.width)));
    expect(zoomed.py).toBe(Math.floor(cssY * (imgSize.height / rect.height)));
  });
});

describe("clampZoom", () => {
  it("clamps below MIN_ZOOM up to 1", () => {
    expect(clampZoom(0.3)).toBe(1);
  });
  it("clamps above MAX_ZOOM down to 4", () => {
    expect(clampZoom(10)).toBe(4);
  });
  it("passes through values already in range", () => {
    expect(clampZoom(2.5)).toBe(2.5);
  });
});

describe("zoomAtPoint", () => {
  it("keeps the image point under the focal point fixed when zooming in", () => {
    // At zoom=1, pan={0,0}, the focal point IS the image point (100,100).
    const { zoom, pan } = zoomAtPoint(1, { x: 0, y: 0 }, 2, { x: 100, y: 100 });
    expect(zoom).toBe(2);
    // (focal - pan) / zoom should still equal the original image point (100,100).
    expect((100 - pan.x) / zoom).toBeCloseTo(100);
    expect((100 - pan.y) / zoom).toBeCloseTo(100);
  });
  it("clamps the requested zoom to the valid range", () => {
    const { zoom } = zoomAtPoint(1, { x: 0, y: 0 }, 50, { x: 0, y: 0 });
    expect(zoom).toBe(4);
  });
});

describe("clampPan", () => {
  it("forces pan to {0,0} at zoom<=1", () => {
    expect(clampPan({ x: -40, y: 30 }, 1, 200, 100)).toEqual({ x: 0, y: 0 });
  });
  it("clamps pan so the zoomed map still fully covers the canvas", () => {
    // zoom=2 on a 200x100 canvas: valid pan.x range is [-200, 0].
    expect(clampPan({ x: 50, y: 0 }, 2, 200, 100)).toEqual({ x: 0, y: 0 });
    expect(clampPan({ x: -500, y: 0 }, 2, 200, 100)).toEqual({ x: -200, y: 0 });
    expect(clampPan({ x: -100, y: 0 }, 2, 200, 100)).toEqual({ x: -100, y: 0 });
  });
});

describe("fitContentBox", () => {
  it("centers a portrait map inside a wider canvas (side letterbox)", () => {
    // 100x100 image in a 200x100 canvas → 100x100 content, 50px side margins.
    expect(fitContentBox(200, 100, { width: 100, height: 100 }))
      .toEqual({ w: 100, h: 100, ox: 50, oy: 0 });
  });
  it("centers a wide map inside a taller canvas (top/bottom letterbox)", () => {
    expect(fitContentBox(100, 200, { width: 100, height: 100 }))
      .toEqual({ w: 100, h: 100, ox: 0, oy: 50 });
  });
  it("is a no-op when the canvas matches the map's aspect", () => {
    expect(fitContentBox(200, 100, { width: 400, height: 200 }))
      .toEqual({ w: 200, h: 100, ox: 0, oy: 0 });
  });
  it("falls back to the full canvas without an image size", () => {
    expect(fitContentBox(200, 100, null)).toEqual({ w: 200, h: 100, ox: 0, oy: 0 });
  });
});

describe("clampPan with a letterboxed content box", () => {
  // 100x100 image in a 200x100 canvas: content w=100 centered at ox=50.
  const img = { width: 100, height: 100 };
  it("keeps an under-filled axis centered while the scaled map is narrower than the canvas", () => {
    // zoom=1.5: scaled content 150 < 200 → x pinned to center regardless of input.
    const { x } = clampPan({ x: -999, y: 0 }, 1.5, 200, 100, img);
    expect(x).toBeCloseTo((200 - 150) / 2 - 1.5 * 50); // = -50
  });
  it("frees the axis once the scaled map outgrows the canvas", () => {
    // zoom=3: scaled content 300 > 200 → pan.x range [200-3*150, -3*50] = [-250, -150].
    expect(clampPan({ x: -200, y: 0 }, 3, 200, 100, img).x).toBe(-200);
    expect(clampPan({ x: 0, y: 0 }, 3, 200, 100, img).x).toBe(-150);
    expect(clampPan({ x: -999, y: 0 }, 3, 200, 100, img).x).toBe(-250);
  });
  it("clamps the fit axis exactly as before (no letterbox there)", () => {
    expect(clampPan({ x: 0, y: -500 }, 2, 200, 100, img).y).toBe(-100);
    expect(clampPan({ x: 0, y: 50 }, 2, 200, 100, img).y).toBe(0);
  });
});

describe("panEdgeHidden", () => {
  it("reports nothing hidden at or below fit zoom", () => {
    expect(panEdgeHidden({ x: 0, y: 0 }, 1, 200, 100)).toEqual({ left: 0, right: 0, top: 0, bottom: 0 });
    expect(panEdgeHidden({ x: 5, y: 5 }, 0.5, 200, 100)).toEqual({ left: 0, right: 0, top: 0, bottom: 0 });
  });

  it("splits the overhang evenly when the zoomed map is centered", () => {
    // 200x100 canvas, no image → content fills canvas. zoom=2 → scaled 400 wide,
    // 200 hidden total; centered pan.x = -100 → 100 hidden each side.
    const h = panEdgeHidden({ x: -100, y: -50 }, 2, 200, 100);
    expect(h.left).toBeCloseTo(100);
    expect(h.right).toBeCloseTo(100);
    expect(h.top).toBeCloseTo(50);
    expect(h.bottom).toBeCloseTo(50);
  });

  it("puts the whole overhang on one side when panned to an edge", () => {
    // pan.x=0 at zoom 2 = content's left edge flush → nothing left, all right.
    const h = panEdgeHidden({ x: 0, y: 0 }, 2, 200, 100);
    expect(h.left).toBe(0);
    expect(h.right).toBeCloseTo(200);
    expect(h.top).toBe(0);
    expect(h.bottom).toBeCloseTo(100);
  });

  it("accounts for the letterbox content box", () => {
    // 100x100 image in a 200x100 canvas: content w=100, ox=50. zoom=3 → scaled
    // content 300 wide, pan.x range [-250, -150]. At the max (-150) the near edge
    // is flush → left 0, right = full 100 overhang.
    const img = { width: 100, height: 100 };
    const h = panEdgeHidden({ x: -150, y: 0 }, 3, 200, 100, img);
    expect(h.left).toBe(0);
    expect(h.right).toBeCloseTo(100);
  });
});

describe("clientToImagePx with a letterboxed content box", () => {
  const img = { width: 100, height: 100, cell_size: 1 };
  const rect = { left: 0, top: 0, width: 200, height: 100 };
  it("maps the content-box top-left corner to image (0,0)", () => {
    // Letterbox ox=50: client x=50 is the map's left edge.
    const { px, py } = clientToImagePx(50, 0, rect, img);
    expect(px).toBe(0);
    expect(py).toBe(0);
  });
  it("maps the content-box center to the image center", () => {
    const { px, py } = clientToImagePx(100, 50, rect, img);
    expect(px).toBe(50);
    expect(py).toBe(50);
  });
  it("yields out-of-range px for clicks in the letterbox margin", () => {
    expect(clientToImagePx(10, 0, rect, img).px).toBeLessThan(0);
  });
  it("stays zoom/pan-consistent: un-pans and un-zooms before removing the letterbox", () => {
    // zoom=2, pan={-100,0}: screen 100 → (100+100)/2 = 100 css → -ox → 50 content → px 50.
    const { px } = clientToImagePx(100, 0, rect, img, 2, { x: -100, y: 0 });
    expect(px).toBe(50);
  });
});

describe("dragPan", () => {
  it("translates the gesture-start pan by the pointer displacement", () => {
    // zoom=2 on 200x100: valid pan.x range [-200, 0], pan.y range [-100, 0].
    expect(dragPan({ x: -50, y: -20 }, -30, 10, 2, 200, 100)).toEqual({ x: -80, y: -10 });
  });
  it("clamps the result to the map edges", () => {
    expect(dragPan({ x: -50, y: 0 }, 500, 0, 2, 200, 100)).toEqual({ x: 0, y: 0 });
    expect(dragPan({ x: -50, y: 0 }, -500, 0, 2, 200, 100)).toEqual({ x: -200, y: 0 });
  });
  it("pins to {0,0} at fit zoom (nothing to pan to)", () => {
    expect(dragPan({ x: 0, y: 0 }, 40, 40, 1, 200, 100)).toEqual({ x: 0, y: 0 });
  });
  it("exposes a positive tap-slop threshold", () => {
    expect(TAP_SLOP_PX).toBeGreaterThan(0);
  });
});

describe("pinchStep", () => {
  it("zooms toward the pinch midpoint when fingers spread apart", () => {
    // Fingers 100px apart, spreading to 200px (2x) around a fixed midpoint.
    // Zoom rate is a >1 exponent on the spread ratio (steeper than 1:1), so
    // 2x spread gives 2^PINCH_ZOOM_RATE zoom, not exactly 2x.
    const mid = { x: 100, y: 50 };
    const start = { zoom: 1, pan: { x: 0, y: 0 }, mid, dist: 100 };
    const { zoom, pan } = pinchStep(start, mid, 200, 200, 100);
    expect(zoom).toBeGreaterThan(2); // steeper than linear
    expect(zoom).toBeLessThanOrEqual(4); // MAX_ZOOM
    // Midpoint itself didn't move, so the image point under it stays fixed.
    expect((mid.x - pan.x) / zoom).toBeCloseTo(mid.x / 1);
  });
  it("carries a moving midpoint as pan (two-finger drag) on top of the zoom", () => {
    const prevMid = { x: 100, y: 50 };
    const newMid = { x: 120, y: 50 };
    const start = { zoom: 2, pan: { x: -50, y: 0 }, mid: prevMid, dist: 100 };
    // Same distance as the gesture start → no zoom change, pure pan by the midpoint's delta.
    const { zoom, pan } = pinchStep(start, newMid, 100, 400, 200);
    expect(zoom).toBe(2);
    expect(pan.x).toBeCloseTo(-50 + (newMid.x - prevMid.x));
  });
  it("does not accumulate zoom/pan drift across multiple frames of a pure two-finger pan", () => {
    // Regression case for the incremental-math bug: referencing a FIXED
    // gesture start (not the previous frame) means each frame's result
    // depends only on that frame's (mid, dist) relative to the start — small
    // per-frame distance wobble (one finger moves before the other) affects
    // only that frame's zoom by the same tiny amount every time, it never
    // compounds across frames the way frame-to-frame chaining would.
    const start = { zoom: 2, pan: { x: -30, y: -10 }, mid: { x: 100, y: 50 }, dist: 100 };
    const results = [1, 2, 3, 4, 5].map((i) => {
      const mid = { x: 100 + i * 4, y: 50 };
      const dist = 100 + (i % 2 === 0 ? 1 : -1); // wobbles ±1% around start.dist
      return pinchStep(start, mid, dist, 400, 200);
    });
    // Every frame's zoom is within the wobble's own ratio of the start zoom —
    // none of them ratchet further away as i increases (no compounding).
    for (const { zoom } of results) {
      expect(zoom).toBeCloseTo(2, 1);
    }
    // Pan roughly tracks the midpoint's translation from the gesture start
    // (small zoom wobble couples slightly into pan via the focal-point term,
    // but it doesn't compound — it stays within the same tolerance every frame).
    const lastMid = { x: 100 + 5 * 4, y: 50 };
    expect(results[4].pan.x).toBeCloseTo(start.pan.x + (lastMid.x - start.mid.x), -1);
  });
  it("leaves zoom unchanged when a distance is zero (gesture start, no divide-by-zero)", () => {
    const mid = { x: 10, y: 10 };
    const start = { zoom: 1.5, pan: { x: 0, y: 0 }, mid, dist: 0 };
    const { zoom } = pinchStep(start, mid, 50, 200, 100);
    expect(zoom).toBe(1.5);
  });
  it("clamps the result zoom and pan to the canvas bounds", () => {
    const mid = { x: 100, y: 50 };
    const start = { zoom: 1, pan: { x: 0, y: 0 }, mid, dist: 10 };
    const { zoom, pan } = pinchStep(start, mid, 1000, 200, 100);
    expect(zoom).toBe(4); // MAX_ZOOM
    expect(pan.x).toBeGreaterThanOrEqual(200 - 200 * zoom);
    expect(pan.x).toBeLessThanOrEqual(0);
  });
});

describe("minZonePx", () => {
  it("is 10 cells worth of image px (2x one-robot-width area)", () => {
    expect(minZonePx(2)).toBe(20);
  });
  it("defaults cellSize to 1 when absent", () => {
    expect(minZonePx(0)).toBe(10);
    expect(minZonePx(undefined)).toBe(10);
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

describe("hitTestZoneRect", () => {
  const rect = { x0: 10, y0: 10, x1: 50, y1: 50 };

  it("returns null when there is no rect yet", () => {
    expect(hitTestZoneRect(20, 20, null, 6)).toBeNull();
  });
  it("detects each corner handle within the hit radius", () => {
    expect(hitTestZoneRect(11, 11, rect, 6)).toBe("nw");
    expect(hitTestZoneRect(49, 11, rect, 6)).toBe("ne");
    expect(hitTestZoneRect(11, 49, rect, 6)).toBe("sw");
    expect(hitTestZoneRect(49, 49, rect, 6)).toBe("se");
  });
  it("prioritizes a corner handle over the body when both overlap", () => {
    // (11,11) is inside the body too, but within radius of the nw handle.
    expect(hitTestZoneRect(11, 11, rect, 8)).toBe("nw");
  });
  it("returns 'body' when inside the rect but away from any handle", () => {
    expect(hitTestZoneRect(30, 30, rect, 6)).toBe("body");
  });
  it("returns null outside the rect entirely", () => {
    expect(hitTestZoneRect(100, 100, rect, 6)).toBeNull();
  });
  it("works on an unnormalized rect (x1<x0, y1<y0)", () => {
    const inverted = { x0: 50, y0: 50, x1: 10, y1: 10 };
    expect(hitTestZoneRect(11, 11, inverted, 6)).toBe("nw");
    expect(hitTestZoneRect(30, 30, inverted, 6)).toBe("body");
  });
});

describe("resizeZoneRect", () => {
  const bounds = { width: 200, height: 200 };

  it("drags the se corner while the nw corner (anchor) stays fixed", () => {
    const r = resizeZoneRect({ x0: 10, y0: 10, x1: 50, y1: 50 }, "se", 80, 90, 14, bounds);
    expect(r).toEqual({ x0: 10, y0: 10, x1: 80, y1: 90 });
  });
  it("drags the nw corner while the se corner (anchor) stays fixed", () => {
    const r = resizeZoneRect({ x0: 10, y0: 10, x1: 50, y1: 50 }, "nw", 5, 8, 14, bounds);
    expect(r).toEqual({ x0: 5, y0: 8, x1: 50, y1: 50 });
  });
  it("enforces the minimum size instead of collapsing past the anchor", () => {
    const r = resizeZoneRect({ x0: 10, y0: 10, x1: 50, y1: 50 }, "se", 12, 12, 14, bounds);
    expect(r).toEqual({ x0: 10, y0: 10, x1: 24, y1: 24 });
  });
  it("clamps the dragged corner to the image bounds", () => {
    const r = resizeZoneRect({ x0: 10, y0: 10, x1: 50, y1: 50 }, "se", 999, 999, 14, bounds);
    expect(r).toEqual({ x0: 10, y0: 10, x1: 200, y1: 200 });
  });
});

describe("moveZoneRect", () => {
  const bounds = { width: 200, height: 200 };

  it("translates the rect by the given delta", () => {
    const r = moveZoneRect({ x0: 10, y0: 10, x1: 30, y1: 40 }, 5, -2, bounds);
    expect(r).toEqual({ x0: 15, y0: 8, x1: 35, y1: 38 });
  });
  it("clamps so the rect cannot move past the left/top edge", () => {
    const r = moveZoneRect({ x0: 10, y0: 10, x1: 30, y1: 40 }, -50, -50, bounds);
    expect(r).toEqual({ x0: 0, y0: 0, x1: 20, y1: 30 });
  });
  it("clamps so the rect cannot move past the right/bottom edge", () => {
    const r = moveZoneRect({ x0: 170, y0: 170, x1: 190, y1: 195 }, 50, 50, bounds);
    expect(r).toEqual({ x0: 180, y0: 175, x1: 200, y1: 200 });
  });
});

describe("defaultZoneRect", () => {
  it("centers a 5x-minimum square on the map", () => {
    // cell_size 1 → min side 10, default side 10*5=50. Map 200x200 → centered at (75,75)-(125,125).
    const r = defaultZoneRect({ width: 200, height: 200, cell_size: 1 });
    expect(r).toEqual({ x0: 75, y0: 75, x1: 125, y1: 125 });
  });
  it("scales the default side by cell_size", () => {
    // cell_size 2 → min side 20, default side 20*5=100. Map 400x400 → centered at (150,150)-(250,250).
    const r = defaultZoneRect({ width: 400, height: 400, cell_size: 2 });
    expect(r).toEqual({ x0: 150, y0: 150, x1: 250, y1: 250 });
  });
  it("clamps to the map edge on a map smaller than the default size", () => {
    const r = defaultZoneRect({ width: 8, height: 8, cell_size: 1 });
    expect(r).toEqual({ x0: 0, y0: 0, x1: 8, y1: 8 });
  });
  it("returns null when the map size isn't known yet", () => {
    expect(defaultZoneRect(null)).toBeNull();
    expect(defaultZoneRect(undefined)).toBeNull();
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

describe("targetStripLabel", () => {
  const names = (id) => ({ "1": "Kitchen", "2": "Hall", "3": "Den", "4": "Bath" }[id] || id);

  it("rooms · nothing selected → Whole home", () => {
    expect(targetStripLabel("rooms", new Set(), false, names)).toBe("Whole home");
  });

  it("rooms · one or two names listed in full", () => {
    expect(targetStripLabel("rooms", new Set(["1"]), false, names)).toBe("Kitchen");
    expect(targetStripLabel("rooms", new Set(["1", "2"]), false, names)).toBe("Kitchen, Hall");
  });

  it("rooms · three+ shows the first two and a +N overflow", () => {
    expect(targetStripLabel("rooms", new Set(["1", "2", "3", "4"]), false, names))
      .toBe("Kitchen, Hall +2");
  });

  it("zone · copy depends on whether an area is drawn", () => {
    expect(targetStripLabel("zone", new Set(), false, names)).toBe("Draw an area on the map");
    expect(targetStripLabel("zone", new Set(), true, names)).toBe("Area selected");
  });

  it("falls back to the id when no name resolver is given", () => {
    expect(targetStripLabel("rooms", new Set(["9"]), false, undefined)).toBe("9");
  });
});

describe("buttonLabels", () => {
  it("cleaning → Pause", () => {
    const l = buttonLabels("cleaning");
    expect(l.playLabel).toBe("Pause");
    expect(l.playIcon).toBe("mdi:pause");
    expect(l.playAction).toBe("pause");
  });
  it("returning → Pause (in-progress, like cleaning)", () => {
    const l = buttonLabels("returning");
    expect(l.playLabel).toBe("Pause");
    expect(l.playIcon).toBe("mdi:pause");
    expect(l.playAction).toBe("pause");
  });
  it("paused → Resume / play", () => {
    const l = buttonLabels("paused");
    expect(l.playLabel).toBe("Resume");
    expect(l.playAction).toBe("play");
  });
  it("idle/docked → Start (shell overrides with a clean label)", () => {
    expect(buttonLabels("idle").playLabel).toBe("Start");
    expect(buttonLabels("docked").playLabel).toBe("Start");
  });
  it("dock label is always 'Dock' regardless of state", () => {
    expect(buttonLabels("docked").dockLabel).toBe("Dock");
    expect(buttonLabels("cleaning").dockLabel).toBe("Dock");
  });
});

describe("primaryCleanLabel", () => {
  it("rooms · none selected → Clean whole home", () => {
    expect(primaryCleanLabel("rooms", 0, false)).toBe("Clean whole home");
  });
  it("rooms · N selected → Clean N room(s), pluralised", () => {
    expect(primaryCleanLabel("rooms", 1, false)).toBe("Clean 1 room");
    expect(primaryCleanLabel("rooms", 3, false)).toBe("Clean 3 rooms");
  });
  it("zone · drawn vs not", () => {
    expect(primaryCleanLabel("zone", 0, true)).toBe("Clean area");
    expect(primaryCleanLabel("zone", 0, false)).toBe("Draw an area first");
  });
});

describe("roomChipText", () => {
  it("returns the room name", () => {
    expect(roomChipText({ name: "Hall" })).toBe("Hall");
  });
  it("ignores area_m2 (area was removed from on-map pills)", () => {
    expect(roomChipText({ name: "Hall", area_m2: 12.5 })).toBe("Hall");
  });
  it("falls back to id when name is missing", () => {
    expect(roomChipText({ id: "7" })).toBe("7");
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
  it("changes when zoom changes (an idle pinch/wheel must still trigger a redraw)", () => {
    const v = { ...vs(), zoom: 2 };
    expect(computeDrawKey(attr, v)).not.toBe(computeDrawKey(attr, vs()));
  });
  it("changes when pan changes", () => {
    const v = { ...vs(), zoom: 2, pan: { x: -10, y: 5 } };
    const v2 = { ...vs(), zoom: 2, pan: { x: -20, y: 5 } };
    expect(computeDrawKey(attr, v)).not.toBe(computeDrawKey(attr, v2));
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
    mapToken: "t",
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

  it("hit areas shrink by 1/zoom around the room centroid (labels stay constant on-screen)", () => {
    const fit = drawMap(fakeCtx(), canvas, baseVs())[0];
    const zoomed = drawMap(fakeCtx(), canvas, baseVs({ zoom: 2, pan: { x: -100, y: -100 } }))[0];
    expect(zoomed.w).toBeCloseTo(fit.w / 2);
    expect(zoomed.h).toBeCloseTo(fit.h / 2);
    // Same anchor: both boxes are centered on the room centroid.
    expect(zoomed.x + zoomed.w / 2).toBeCloseTo(fit.x + fit.w / 2);
    expect(zoomed.y + zoomed.h / 2).toBeCloseTo(fit.y + fit.h / 2);
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
    mapToken: "t",
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

  it("draws the four zone resize handles only when the zone is editable", () => {
    const zoneRect = { x0: 10, y0: 10, x1: 50, y1: 50 };
    const editable = recordingCtx();
    drawMap(editable, canvas, baseVs({ zoneRect, zoneEditable: true }));
    const locked = recordingCtx();
    drawMap(locked, canvas, baseVs({ zoneRect, zoneEditable: false }));
    // Editable draws exactly four extra arcs (the corner handles); locked draws none.
    expect(fnCalls(editable, "arc").length - fnCalls(locked, "arc").length).toBe(4);
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
