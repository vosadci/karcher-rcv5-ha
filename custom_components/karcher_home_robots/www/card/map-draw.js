import { canvasScale, fitContentBox, roomBoundingBox, roomCentroid } from "./geometry.js";
import { roomChipText } from "./derive.js";

// Pure canvas renderer + draw-key + legend + reveal math (no hass/DOM state).
// Room colour palette — mirrors _ROOM_COLOR_TABLE in map_render.py (APK-verified).
// Index = (color_id - 1) % 5
const _ROOM_COLORS = [
  "#c9dcd2",  // color_id 1 — teal-green
  "#e9bac0",  // color_id 2 — pink
  "#e8e7e3",  // color_id 3 — off-white
  "#bddde0",  // color_id 4 — light blue
  "#b7b7b7",  // color_id 5 — grey
];
export function roomColor(colorId) {
  if (!colorId || colorId < 1) return _ROOM_COLORS[0];
  return _ROOM_COLORS[(colorId - 1) % _ROOM_COLORS.length];
}

// Canvas paint colours — mirror the CSS --rcv-accent/--rcv-accent-deep tokens
// (canvas fillStyle/strokeStyle can't read CSS custom properties, so these are
// the same hex values restated as JS constants, single source for the paint code).
const ACCENT_DEEP_HEX = "#E8BE00";
const ZONE_FILL = "rgba(255,212,0,0.28)";
const ROOM_SELECTED_FILL = "rgba(255,212,0,0.55)";
const PATH_COLOR = "#999";
// Robot is ~34cm wide; resolution=0.05m/cell → ~7 cells diameter → 3.5 cell radius.
const ROBOT_RADIUS_CELLS = 3.5;

// Cache key for the canvas draw: a redraw is skipped when this is unchanged.
// Covers everything the rendered overlay depends on — map token, robot/charger/
// path geometry, room names+colours (room_map is rebuilt fresh every HA update,
// so a reference check never matches), selection sets, mode, and canvas size.
export function computeDrawKey(attr, viewState) {
  const rp = attr?.robot_px;
  const cp = attr?.charger_px;
  const roomMap = attr?.room_map || {};
  const roomSig = Object.entries(roomMap)
    .map(([id, r]) => `${id}:${r.name}:${r.color_id}`)
    .join(",");
  return [
    viewState.mapToken,
    rp ? `${rp.x},${rp.y},${rp.phi ?? 0}` : "",
    cp ? `${cp.x},${cp.y}` : "",
    attr?.cur_path_px ? attr.cur_path_px.join(",") : "",
    roomSig,
    viewState.cardMode,
    viewState.detailRoomId,
    [...(viewState.selectedRooms || [])].sort().join(","),
    [...(viewState.customiseSelected || [])].sort().join(","),
    !!viewState.robotIcon,
    viewState.canvasWidth,
    viewState.canvasHeight,
    viewState.dpr,
    viewState.zoneRect
      ? `${viewState.zoneRect.x0},${viewState.zoneRect.y0},${viewState.zoneRect.x1},${viewState.zoneRect.y1}`
      : "",
    viewState.zoom || 1,
    viewState.pan ? `${Math.round(viewState.pan.x)},${Math.round(viewState.pan.y)}` : "",
  ].join("|");
}

// Interpolate between two angles (radians) along the shortest arc, so a robot
// turning across the ±π wrap glides instead of spinning the long way round.
export function lerpAngle(a, b, t) {
  let d = (b - a) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return a + d * t;
}

// Total length of a flat [x0,y0,x1,y1,...] polyline (image px).
export function pathArcLength(pts) {
  let acc = 0;
  for (let i = 0; i < pts.length / 2 - 1; i++) {
    acc += Math.hypot(pts[2 * i + 2] - pts[2 * i], pts[2 * i + 3] - pts[2 * i + 1]);
  }
  return acc;
}

// Reveal a flat [x0,y0,x1,y1,...] polyline up to arc length `dist`. Returns the
// truncated path (ending at an interpolated cursor) and the cursor x/y. Arc
// length (not index) gives even spatial speed when the cursor is paced linearly.
export function revealPath(pts, dist) {
  const n = pts.length / 2;
  if (n === 0) return { path: [], x: 0, y: 0 };
  if (n === 1 || dist <= 0) return { path: [pts[0], pts[1]], x: pts[0], y: pts[1] };
  let acc = 0;
  for (let i = 0; i < n - 1; i++) {
    const x1 = pts[2 * i], y1 = pts[2 * i + 1];
    const x2 = pts[2 * i + 2], y2 = pts[2 * i + 3];
    const seg = Math.hypot(x2 - x1, y2 - y1);
    if (acc + seg >= dist) {
      const f = seg > 0 ? (dist - acc) / seg : 0;
      const cx = x1 + (x2 - x1) * f;
      const cy = y1 + (y2 - y1) * f;
      const path = pts.slice(0, 2 * i + 2);
      path.push(cx, cy);
      return { path, x: cx, y: cy };
    }
    acc += seg;
  }
  const last = pts.length - 2;
  return { path: pts.slice(), x: pts[last], y: pts[last + 1] };
}

// ---------------------------------------------------------------------------
// AI-object type id → [label, dot colour]. Colours mirror map_render._OBJECT_TYPES
// exactly so a legend dot matches the dot drawn on the map. Unknown ids fall back
// to a grey "Object".
const OBJECT_LABELS = {
  "1001": ["Sock", "rgb(220,120,60)"],
  "1002": ["Shoe", "rgb(180,100,40)"],
  "1003": ["Wire", "rgb(230,60,60)"],
  "1006": ["Cat", "rgb(160,100,200)"],
  "1007": ["Dog", "rgb(160,100,200)"],
  "1011": ["Pet waste", "rgb(200,60,60)"],
  "1017": ["Scale", "rgb(80,140,200)"],
  "1038": ["Chair", "rgb(120,120,120)"],
};

// Pure: build the dynamic map-legend rows from the vacuum entity's attributes.
// Returns only symbols actually present in the current map. Zone/object/carpet
// presence comes from the `map_legend` attribute (computed server-side); robot,
// dock and path are inferred from the px overlays the card already receives.
// Swatch colours use the zones' solid outline colours (the fills are ~18 %
// alpha and would be invisible at swatch size).
export function legendItems(attr) {
  const items = [];
  const L = (attr && attr.map_legend) || {};
  // Zone swatches mirror the map: a light fill (the ~18 % alpha overlay) with the
  // solid outline colour as the border — so they read at the same brightness as
  // the map, not as solid blocks. Dot/line colours match what drawMap paints.
  if (L.no_go) items.push({ key: "no_go", label: "No-go", kind: "swatch", fill: "rgba(220,60,60,0.20)", color: "rgb(200,40,40)", count: L.no_go });
  if (L.no_mop) items.push({ key: "no_mop", label: "No-mop", kind: "swatch", fill: "rgba(70,110,220,0.20)", color: "rgb(50,90,200)", count: L.no_mop });
  if (L.virtual_wall) items.push({ key: "wall", label: "Wall", kind: "line", color: "rgb(200,40,40)", count: L.virtual_wall });
  if (L.area_clean) items.push({ key: "area_clean", label: "Cleaning area", kind: "swatch", fill: "rgba(255,212,0,0.55)", color: "rgb(204,169,0)", count: L.area_clean });
  if (L.carpet) items.push({ key: "carpet", label: "Carpet", kind: "swatch", fill: "rgb(236,236,236)", color: "rgba(0,0,0,0.18)" });
  if (attr && attr.robot_px) items.push({ key: "robot", label: "Robot", kind: "dot", color: "#fff", ring: true });
  // drawCharger paints a teal disc with a white centre (a ring, not a filled
  // dot) — mirror that exactly rather than a solid teal fill.
  if (attr && attr.charger_px) {
    items.push({ key: "dock", label: "Dock", kind: "dot", color: "#fff", ringColor: "#4db6c4", ring: true });
  }
  if (attr && Array.isArray(attr.cur_path_px) && attr.cur_path_px.length) {
    items.push({ key: "path", label: "Path", kind: "line", color: PATH_COLOR });
  }
  const objs = L.objects || {};
  for (const typeId of Object.keys(objs)) {
    const [label, color] = OBJECT_LABELS[typeId] || ["Object", "rgb(160,160,160)"];
    items.push({ key: "obj_" + typeId, label, kind: "dot", color, count: objs[typeId] });
  }
  return items;
}

// Canvas map renderer — pure of card/hass state.
//
// All inputs arrive in `vs` (viewState), a plain object the card assembles by
// pre-resolving everything hass-derived (selection sets, icons).
// The renderer never touches this/_hass/_config. drawMap returns the room
// checkbox hit areas (image-space rects) for the card's click handler to store;
// it does not write them back onto any object.
//
// vs = { attr, dpr, mapImg, robotIcon, cardMode, detailRoomId, selectedRooms,
//        customiseSelected, mapToken, canvasWidth, canvasHeight,
//        zoom, pan }
// ---------------------------------------------------------------------------

export function drawMap(ctx, canvas, vs) {
  const { attr, mapImg } = vs;
  if (!mapImg || !canvas) return [];
  const dpr = vs.dpr || 1;
  const zoom = vs.zoom || 1;
  const pan = vs.pan || { x: 0, y: 0 };
  // Clear in full device space (no zoom/pan) so a zoomed-in view doesn't
  // leave stale pixels outside the transformed draw area.
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const cssW = canvas.width / dpr;
  const cssH = canvas.height / dpr;
  ctx.clearRect(0, 0, cssW, cssH);
  // The canvas is full-bleed (card width), so the map's aspect-fit letterbox
  // lives in the transform: pan/zoom first, then the centering offset. Every
  // draw* child scales via canvasScale() against the CONTENT box, not the
  // canvas — pass content-box dims so no child needs to know any of this.
  const box = fitContentBox(cssW, cssH, attr.map_image_size);
  ctx.translate(pan.x, pan.y);
  ctx.scale(zoom, zoom);
  ctx.translate(box.ox, box.oy);
  const contentDims = { width: box.w * dpr, height: box.h * dpr };
  ctx.drawImage(mapImg, 0, 0, box.w, box.h);
  const roomMap = attr.room_map || {};
  drawRoomOverlays(ctx, contentDims, roomMap, vs);
  drawCurPath(ctx, contentDims, vs);
  const hitAreas = drawRoomLabels(ctx, contentDims, roomMap, vs);
  drawCharger(ctx, contentDims, vs);
  drawRobot(ctx, contentDims, vs);
  drawZoneRect(ctx, contentDims, vs);
  return hitAreas;
}

function drawZoneRect(ctx, canvas, vs) {
  const r = vs.zoneRect;
  if (!r) return;
  const imgSize = vs.attr?.map_image_size;
  if (!imgSize) return;
  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const x = Math.min(r.x0, r.x1) * scaleX;
  const y = Math.min(r.y0, r.y1) * scaleY;
  const w = Math.abs(r.x1 - r.x0) * scaleX;
  const h = Math.abs(r.y1 - r.y0) * scaleY;
  const radius = Math.min(10, w / 2, h / 2);
  ctx.save();
  // Kärcher-yellow fill + accent stroke, matching the rest of the card's
  // accent usage (--rcv-accent / --rcv-accent-deep).
  ctx.fillStyle = ZONE_FILL;
  ctx.strokeStyle = "rgba(255,255,255,0.95)";
  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, radius);
  ctx.fill();
  ctx.stroke();
  ctx.strokeStyle = ACCENT_DEEP_HEX;
  ctx.lineWidth = 2.5;
  ctx.stroke();
  ctx.restore();

  // Handles are a resize affordance — only show them while the zone can actually
  // be edited (controls unlocked). During a clean the box stays as a static
  // "this is what's being cleaned" marker, without the dead drag handles.
  if (vs.zoneEditable) drawZoneHandles(ctx, x, y, w, h);
}

// Corner resize handles — small accent-ringed circles, matching the
// prototype's drag handles, drawn in canvas (device) space.
function drawZoneHandles(ctx, x, y, w, h) {
  const corners = [[x, y], [x + w, y], [x, y + h], [x + w, y + h]];
  ctx.save();
  for (const [hx, hy] of corners) {
    ctx.beginPath();
    ctx.arc(hx, hy, 9, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,255,255,0.55)";
    ctx.fill();
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = ACCENT_DEEP_HEX;
    ctx.stroke();
  }
  ctx.restore();
}

function drawCurPath(ctx, canvas, vs) {
  const { attr } = vs;
  const pts = attr.cur_path_px;
  const imgSize = attr.map_image_size;
  if (!pts || pts.length < 4 || !imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const lineW = Math.max(1, imgSize.cell_size * scaleX * 0.66);

  ctx.save();
  ctx.globalAlpha = 0.55;
  ctx.strokeStyle = PATH_COLOR;
  ctx.shadowColor = "#555";
  ctx.shadowBlur = 4;
  ctx.lineWidth = lineW;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  const x0 = pts[0] * scaleX, y0 = pts[1] * scaleY;
  ctx.moveTo(x0, y0);
  if (pts.length === 4) {
    ctx.lineTo(pts[2] * scaleX, pts[3] * scaleY);
  } else {
    for (let i = 2; i < pts.length - 2; i += 2) {
      const cx = pts[i] * scaleX, cy = pts[i + 1] * scaleY;
      const nx = pts[i + 2] * scaleX, ny = pts[i + 3] * scaleY;
      const mx = (cx + nx) / 2, my = (cy + ny) / 2;
      ctx.quadraticCurveTo(cx, cy, mx, my);
    }
    const last = pts.length - 2;
    ctx.lineTo(pts[last] * scaleX, pts[last + 1] * scaleY);
  }
  ctx.stroke();
  ctx.shadowBlur = 0;
  ctx.restore();
}

function drawCharger(ctx, canvas, vs) {
  const cp = vs.attr.charger_px;
  const imgSize = vs.attr.map_image_size;
  if (!cp || !imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const cx = cp.x * scaleX;
  const cy = cp.y * scaleY;
  const r = Math.max(6, imgSize.cell_size * scaleX * ROBOT_RADIUS_CELLS);

  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = "#4db6c4";
  ctx.fill();

  ctx.beginPath();
  ctx.arc(cx, cy, r * 0.55, 0, Math.PI * 2);
  ctx.fillStyle = "#fff";
  ctx.fill();
}

function drawRobot(ctx, canvas, vs) {
  const rp = vs.attr.robot_px;
  const imgSize = vs.attr.map_image_size;
  if (!rp || !imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const cx = rp.x * scaleX;
  const cy = rp.y * scaleY;
  const r = imgSize.cell_size * scaleX * ROBOT_RADIUS_CELLS;
  const phi = rp.phi ?? 0;

  ctx.save();
  ctx.translate(cx, cy);

  // Pulse cue: a filled "radar ping" disc expands and fades from the robot,
  // mirroring the header status dot (CSS @keyframes rcv-ping): scale 1→2.5,
  // opacity 0.75→0, ease-out, 1.6s, themed colour. Circular → rotation-
  // independent, so drawn before the heading rotate below. baseR is floored in
  // device px so the cue stays visible when the icon is tiny (zoomed out).
  if (vs.pulse) {
    const p = vs.pulsePhase || 0;
    const e = 1 - Math.pow(1 - p, 3); // ease-out, ~cubic-bezier(0,0,.2,1)
    const baseR = Math.max(r, 9 * dpr);
    const alpha = 0.75 * (1 - e);
    if (alpha > 0) {
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = vs.pulseColor || "#4caf50";
      ctx.beginPath();
      ctx.arc(0, 0, baseR * (1 + 1.5 * e), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }

  // SVG front (camera bump) is at upper-right: atan2(-21.79, 13.13) = -1.029 rad from east.
  // Canvas target angle for world phi (Y-flipped) = -phi. Required rotation:
  // θ = -phi - SVG_rest_angle = -phi + 1.029. If icon.svg's camera-bump geometry
  // ever changes, recompute this constant — see www/icon.svg.
  ctx.rotate(-phi + 1.029);

  if (vs.robotIcon) {
    ctx.drawImage(vs.robotIcon, -r, -r, r * 2, r * 2);
  } else {
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#333";
    ctx.lineWidth = 1;
    ctx.fill();
    ctx.stroke();
  }
  ctx.restore();
}

function drawRoomOverlays(ctx, canvas, roomMap, vs) {
  const imgSize = vs.attr?.map_image_size;
  if (!imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const cs = imgSize.cell_size || 1;
  const cellH = cs * scaleY;

  const fillCells = (cells, style) => {
    ctx.fillStyle = style;
    for (const [row, colStart, runLen] of cells) {
      ctx.fillRect(colStart * scaleX, row * scaleY, runLen * cs * scaleX, cellH);
    }
  };

  if (vs.cardMode === "customise") {
    for (const [id, room] of Object.entries(roomMap)) {
      const cells = room.cells;
      if (!cells || cells.length === 0) continue;
      if (vs.customiseSelected.has(id)) fillCells(cells, ROOM_SELECTED_FILL);
    }
    return;
  }

  // Standard mode: accent tint for selected/queued rooms.
  for (const [id, room] of Object.entries(roomMap)) {
    const cells = room.cells;
    if (!cells || cells.length === 0) continue;
    if (vs.selectedRooms.has(id)) fillCells(cells, ROOM_SELECTED_FILL);
  }
}

function drawRoomLabels(ctx, canvas, roomMap, vs) {
  const hitAreas = [];
  const imgSize = vs.attr?.map_image_size;
  if (!imgSize) return hitAreas;
  const isCustomise = vs.cardMode === "customise";
  const dpr = vs.dpr || 1;
  const zoom = vs.zoom || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const cs = imgSize.cell_size || 1;

  for (const [id, room] of Object.entries(roomMap)) {
    const cells = room.cells;
    if (!cells || cells.length === 0) continue;

    const bbox = roomBoundingBox(cells, cs);
    const centroid = roomCentroid(bbox);
    const cx = centroid.cx * scaleX;
    const cy = centroid.cy * scaleY;

    const chipText = roomChipText({ ...room, id });

    const isSelected = isCustomise ? vs.customiseSelected.has(id) : vs.selectedRooms.has(id);

    const fontSize = Math.max(16, Math.min(24, cs * scaleX * 2.1));
    ctx.save();
    // Labels keep a constant on-screen size: anchor at the room centroid
    // (which pans/zooms with the map), then locally undo the zoom so the
    // pill/text render at 1:1 regardless of zoom level. All pill geometry
    // below is relative to this origin.
    ctx.translate(cx, cy);
    ctx.scale(1 / zoom, 1 / zoom);
    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.textBaseline = "middle";
    const tw = ctx.measureText(chipText).width;
    const ph = fontSize * 1.65; // one 1.25em text line + 0.4em vertical padding
    const pw = tw + fontSize * 1.8;

    const pillX = -pw / 2;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.35)";
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 1;
    ctx.fillStyle = isSelected ? "rgba(255,212,0,0.75)" : "rgba(255,255,255,0.7)";
    ctx.beginPath();
    ctx.roundRect(pillX, -ph / 2, pw, ph, ph / 2);
    ctx.fill();
    ctx.restore();
    ctx.strokeStyle = "rgba(0,0,0,0.15)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.textAlign = "left";
    ctx.fillStyle = "#1b1c1f";
    ctx.fillText(chipText, pillX + fontSize * 0.9, 0);
    ctx.restore();

    // Hit area: the whole pill, in image-space. The pill's constant screen
    // size means its image-space footprint shrinks by 1/zoom as zoom rises —
    // matching exactly what's painted.
    hitAreas.push({
      id,
      x: (cx + pillX / zoom) / scaleX,
      y: (cy - ph / 2 / zoom) / scaleY,
      w: pw / zoom / scaleX,
      h: ph / zoom / scaleY,
    });
  }
  return hitAreas;
}
