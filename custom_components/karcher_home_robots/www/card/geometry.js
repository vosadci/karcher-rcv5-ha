// Pure geometry / zoom / pan / zone / hit-test math (no DOM, no hass).
// (canvasCssWidth/Height in device px, image size in px) → image→canvas factors.
export function canvasScale(canvasWidthPx, canvasHeightPx, imgSize, dpr = 1) {
  return {
    scaleX: (canvasWidthPx / dpr) / imgSize.width,
    scaleY: (canvasHeightPx / dpr) / imgSize.height,
  };
}

// Uniform-fit content box for the map inside a full-bleed canvas: largest
// aspect-preserving {w,h} that fits cssW×cssH, centered ({ox,oy} letterbox
// margins in CSS px). The canvas does not match the map's aspect ratio — it
// fills the card width — so letterboxing lives here rather than in CSS
// aspect-ratio/max-width, which is what lets a zoomed map grow into the side
// margins.
export function fitContentBox(cssW, cssH, imgSize) {
  if (!imgSize || !imgSize.width || !imgSize.height) {
    return { w: cssW, h: cssH, ox: 0, oy: 0 };
  }
  const s = Math.min(cssW / imgSize.width, cssH / imgSize.height);
  const w = imgSize.width * s;
  const h = imgSize.height * s;
  return { w, h, ox: (cssW - w) / 2, oy: (cssH - h) / 2 };
}

// Click coords (client space) → image-space pixel + cell-snapped row/col.
// pan is in CSS px, applied in the same canvas matrix as drawMap: the client
// point is first un-panned, un-zoomed (both in CSS-px space), then shifted by
// the letterbox offset and converted from content-box CSS px to image px.
// When the canvas box matches the map's aspect the box offsets are 0 and this
// is unchanged from the pre-zoom behaviour. Points in the letterbox margins
// yield out-of-range image px (negative or > width) — callers already treat
// those as no-hit.
export function clientToImagePx(clientX, clientY, rect, imgSize, zoom = 1, pan = { x: 0, y: 0 }) {
  const cs = imgSize.cell_size || 1;
  const box = fitContentBox(rect.width, rect.height, imgSize);
  const cssX = (clientX - rect.left - pan.x) / zoom - box.ox;
  const cssY = (clientY - rect.top - pan.y) / zoom - box.oy;
  const px = Math.floor(cssX * (imgSize.width / box.w));
  const py = Math.floor(cssY * (imgSize.height / box.h));
  return {
    px,
    py,
    snapCol: Math.floor(px / cs) * cs,
    snapRow: Math.floor(py / cs) * cs,
  };
}

// Zoom clamp range. 1 = fit-to-frame (the pre-zoom default); 4 is enough to
// read small rooms without the base render (scale=4 PNG) going soft.
export const MIN_ZOOM = 1;
export const MAX_ZOOM = 4;

export function clampZoom(zoom) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

// Zoom toward a focal point (e.g. cursor or pinch midpoint), keeping the image
// point under that focal point fixed. focalX/Y and pan are in CSS px, relative
// to the canvas's top-left (i.e. already offset by rect.left/top).
export function zoomAtPoint(prevZoom, prevPan, nextZoom, focal) {
  const z = clampZoom(nextZoom);
  // Solve for the new pan that keeps (focal - pan) / zoom constant.
  const imgX = (focal.x - prevPan.x) / prevZoom;
  const imgY = (focal.y - prevPan.y) / prevZoom;
  return {
    zoom: z,
    pan: { x: focal.x - imgX * z, y: focal.y - imgY * z },
  };
}

// Clamp one pan axis. While the scaled content is narrower than the canvas
// on this axis it stays centered (pan pinned — the map grows outward into
// the letterbox margin as zoom rises); once it outgrows the canvas, pan is
// free within [content covers canvas] bounds.
function clampPanAxis(p, zoom, css, offset, size) {
  const scaled = zoom * size;
  // `+ 0` normalizes a -0 result (offset 0 edge) to +0 for clean equality.
  if (scaled <= css) return (css - scaled) / 2 - zoom * offset + 0;
  return Math.min(-zoom * offset, Math.max(css - zoom * (offset + size), p)) + 0;
}

// Clamp pan so the zoomed map can't be dragged past its own edges. At zoom=1
// the only valid pan is {0,0} (nothing to pan to). With imgSize the clamp is
// content-box aware (full-bleed canvas, letterbox inside); without it the
// content is assumed to fill the canvas exactly (pre-full-bleed behaviour,
// kept for callers/tests without an image).
export function clampPan(pan, zoom, cssW, cssH, imgSize = null) {
  if (zoom <= 1) return { x: 0, y: 0 };
  const box = fitContentBox(cssW, cssH, imgSize);
  return {
    x: clampPanAxis(pan.x, zoom, cssW, box.ox, box.w),
    y: clampPanAxis(pan.y, zoom, cssH, box.oy, box.h),
  };
}

// How much scaled content (CSS px) is hidden past the near/far edge of one axis.
// Same clamp geometry as clampPanAxis: the valid pan range is [minP, maxP]; at
// maxP the content's near edge is flush (nothing hidden before), at minP the far
// edge is flush (nothing hidden after). The distance from the current pan to each
// bound is exactly the off-screen overhang on that side.
function panAxisHidden(p, zoom, css, offset, size) {
  if (zoom * size <= css) return { before: 0, after: 0 };
  const maxP = -zoom * offset;
  const minP = css - zoom * (offset + size);
  return { before: Math.max(0, maxP - p), after: Math.max(0, p - minP) };
}

// Off-screen overhang (CSS px) past each edge of the zoomed map, so the card can
// fade in a directional "there's more this way" scrim only where content is
// actually hidden. Zero on every edge at fit zoom (nothing to pan to). Pure —
// unit-tested directly; the content-box math mirrors clampPan.
export function panEdgeHidden(pan, zoom, cssW, cssH, imgSize = null) {
  if (zoom <= 1) return { left: 0, right: 0, top: 0, bottom: 0 };
  const box = fitContentBox(cssW, cssH, imgSize);
  const x = panAxisHidden(pan.x, zoom, cssW, box.ox, box.w);
  const y = panAxisHidden(pan.y, zoom, cssH, box.oy, box.h);
  return { left: x.before, right: x.after, top: y.before, bottom: y.after };
}

// Off-screen overhang ramps a fade from 0 to full over this many CSS px, so an
// edge with only a sliver hidden shows a faint hint and a deep overhang is solid.
export const EDGE_FADE_RAMP_PX = 40;

// One step of a two-finger touch pinch/pan gesture. `start` is a snapshot
// taken once when the gesture began (second finger down): { zoom, pan, mid,
// dist }. Every move frame recomputes from that FIXED start, not from the
// previous frame — an incremental frame-to-frame version telescopes: a pure
// pan slightly changes the inter-finger distance each frame (one finger
// necessarily moves before the other), so per-frame zoom ratios drift below
// 1 and back, and clampZoom's floor at MIN_ZOOM truncates the dip asymmetrically,
// ratcheting zoom down and wiping the accumulated pan via clampPan every time
// it touches the floor. Referencing the gesture start instead makes a pure
// pan produce curDist≈start.dist → zoom pinned, pan = pure translation — no
// drift to accumulate. start.dist<=0 or newDist<=0 (degenerate geometry)
// leaves zoom at start.zoom.
// Rate exponent > 1 steepens zoom response to finger-spread ratio. Must satisfy
// pow(1, RATE) === 1 (i.e. any exponent works here) so a pure pan — spread
// ratio staying ~1 — never introduces zoom drift; a flat multiplier (scale*k)
// would NOT have this property and would re-zoom on every pan gesture.
const PINCH_ZOOM_RATE = 1.3;

// One-finger (or trackpad two-finger-scroll) pan: translate the gesture-start
// pan by the pointer's total displacement, clamped to the map edges. Pure
// translation — zoom is untouched. At zoom<=1 clampPan pins the result to
// {0,0} (nothing to pan to).
export function dragPan(startPan, dx, dy, zoom, cssW, cssH, imgSize = null) {
  return clampPan({ x: startPan.x + dx, y: startPan.y + dy }, zoom, cssW, cssH, imgSize);
}

// A press that moves less than this (CSS px) is still a tap: it must fall
// through to the click handler (room select) instead of becoming a pan.
export const TAP_SLOP_PX = 5;

export function pinchStep(start, newMid, newDist, cssW, cssH, imgSize = null) {
  const scale = start.dist > 0 && newDist > 0 ? newDist / start.dist : 1;
  const zoom = clampZoom(start.zoom * Math.pow(scale, PINCH_ZOOM_RATE));
  // Keep the image point under the gesture's start midpoint fixed at zoom0,
  // then re-center on the current midpoint — same derivation as zoomAtPoint,
  // applied relative to the gesture start rather than the previous frame.
  const imgX = (start.mid.x - start.pan.x) / start.zoom;
  const imgY = (start.mid.y - start.pan.y) / start.zoom;
  const pan = {
    x: newMid.x - imgX * zoom,
    y: newMid.y - imgY * zoom,
  };
  return { zoom, pan: clampPan(pan, zoom, cssW, cssH, imgSize) };
}

// Smallest area-clean rectangle worth sending: one robot-width square.
// Robot is ~34cm wide; resolution=0.05m/cell → ~7 cells per side (see drawRobot).
// Matches the Kärcher app's own AreaMap.AREA_MIN_SIZE clamp-while-dragging
// approach (no zero-size rect ever exists, rather than validating on release).
// Side length scaled by √2 so the minimum *area* is 2x the one-robot-width square.
const MIN_ZONE_CELLS = 10;

export function minZonePx(cellSize) {
  return MIN_ZONE_CELLS * (cellSize || 1);
}

// Default starting rect is 5x the minimum drag side — big enough to read as
// a real selection rather than the smallest-possible square.
const DEFAULT_ZONE_SCALE = 5;

// Centered starting rect for a freshly entered Area tab, so the user edits
// a real selection instead of an empty map. Falls back to null when the map
// size isn't known yet.
export function defaultZoneRect(imgSize) {
  if (!imgSize) return null;
  const side = minZonePx(imgSize.cell_size) * DEFAULT_ZONE_SCALE;
  const x0 = Math.max(0, (imgSize.width - side) / 2);
  const y0 = Math.max(0, (imgSize.height - side) / 2);
  return { x0, y0, x1: Math.min(imgSize.width, x0 + side), y1: Math.min(imgSize.height, y0 + side) };
}

// Push the dragged corner (x1,y1) out from the anchor (x0,y0) so neither side
// of the rect can shrink below minPx — same live-clamp behavior as the
// Kärcher app's corner-drag handler, applied to a fresh drag gesture.
export function clampZoneRect(rect, minPx) {
  const { x0, y0, x1, y1 } = rect;
  const dx = x1 - x0;
  const dy = y1 - y0;
  const sign = (v) => (v < 0 ? -1 : 1);
  const cx1 = Math.abs(dx) < minPx ? x0 + sign(dx) * minPx : x1;
  const cy1 = Math.abs(dy) < minPx ? y0 + sign(dy) * minPx : y1;
  return { x0, y0, x1: cx1, y1: cy1 };
}

// Handle hit-radius, in image px — converted from a fixed screen-px radius
// via the same scale the canvas uses, so handles stay grabbable at any zoom.
export const ZONE_HANDLE_RADIUS_PX = 14;

// Normalize a possibly-inverted drag rect to (x0,y0) top-left / (x1,y1) bottom-right.
export function normalizeRect(rect) {
  return {
    x0: Math.min(rect.x0, rect.x1),
    x1: Math.max(rect.x0, rect.x1),
    y0: Math.min(rect.y0, rect.y1),
    y1: Math.max(rect.y0, rect.y1),
  };
}

// Where on an existing zone rect did the pointer land? Corner handles take
// priority over the body so a drag started near an edge always resizes
// rather than moves. Returns 'nw'|'ne'|'sw'|'se'|'body'|null.
export function hitTestZoneRect(px, py, rect, handleRadius) {
  if (!rect) return null;
  const { x0, x1, y0, y1 } = normalizeRect(rect);
  const near = (ax, ay) => Math.hypot(px - ax, py - ay) <= handleRadius;
  if (near(x0, y0)) return "nw";
  if (near(x1, y0)) return "ne";
  if (near(x0, y1)) return "sw";
  if (near(x1, y1)) return "se";
  if (px >= x0 && px <= x1 && py >= y0 && py <= y1) return "body";
  return null;
}

// Resize by dragging one corner; the opposite corner stays fixed (anchor).
// Re-clamps to the minimum size and to the image bounds afterward.
export function resizeZoneRect(rect, corner, px, py, minPx, bounds) {
  const { x0, x1, y0, y1 } = normalizeRect(rect);
  const fx = corner.includes("e") ? x0 : x1;
  const fy = corner.includes("s") ? y0 : y1;
  const nx = Math.max(0, Math.min(bounds.width, px));
  const ny = Math.max(0, Math.min(bounds.height, py));
  return normalizeRect(clampZoneRect({ x0: fx, y0: fy, x1: nx, y1: ny }, minPx));
}

// Translate the whole rect by (dx,dy), clamped so it stays fully on the map.
export function moveZoneRect(rect, dx, dy, bounds) {
  const { x0, x1, y0, y1 } = normalizeRect(rect);
  const w = x1 - x0;
  const h = y1 - y0;
  const nx0 = Math.max(0, Math.min(bounds.width - w, x0 + dx));
  const ny0 = Math.max(0, Math.min(bounds.height - h, y0 + dy));
  return { x0: nx0, y0: ny0, x1: nx0 + w, y1: ny0 + h };
}

// Expand each room's RLE spans into a "row,col" → roomId lookup.
export function buildCellLookup(roomMap, cellSize) {
  const cs = cellSize || 1;
  const lookup = new Map();
  for (const [id, room] of Object.entries(roomMap || {})) {
    for (const [row, colStart, runLen] of (room.cells || [])) {
      for (let i = 0; i < runLen; i++) {
        lookup.set(`${row},${colStart + i * cs}`, id);
      }
    }
  }
  return lookup;
}

// Checkbox hit areas take priority over the cell lookup. Returns roomId|undefined.
export function hitTestRooms(px, py, snapRow, snapCol, checkboxHitAreas, cellLookup) {
  for (const cb of (checkboxHitAreas || [])) {
    if (px >= cb.x && px < cb.x + cb.w && py >= cb.y && py < cb.y + cb.h) {
      return cb.id;
    }
  }
  return cellLookup ? cellLookup.get(`${snapRow},${snapCol}`) : undefined;
}

// Image-space bounding box of a room's RLE cells (cs = cell_size).
export function roomBoundingBox(cells, cs = 1) {
  let minRow = Infinity, maxRow = -Infinity, minCol = Infinity, maxCol = -Infinity;
  for (const [row, colStart, runLen] of (cells || [])) {
    if (row < minRow) minRow = row;
    if (row > maxRow) maxRow = row;
    if (colStart < minCol) minCol = colStart;
    const colEnd = colStart + runLen * cs;
    if (colEnd > maxCol) maxCol = colEnd;
  }
  return { minRow, maxRow, minCol, maxCol };
}

export function roomCentroid(bbox) {
  return {
    cx: (bbox.minCol + bbox.maxCol) / 2,
    cy: (bbox.minRow + bbox.maxRow) / 2,
  };
}
