import { canvasScale, fitContentBox, roomBoundingBox, roomCentroid, normalizeRect } from "./geometry.js";
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
const ACCENT_RGB = "255,212,0";                  // --rcv-accent, for alpha fills below
const accentFill = (alpha) => `rgba(${ACCENT_RGB},${alpha})`;
const ZONE_FILL = accentFill(0.28);              // while drawing/editing the area
const ZONE_FILL_ACTIVE = accentFill(0.55);       // during the clean — matches ROOM_SELECTED_FILL
const ROOM_SELECTED_FILL = ZONE_FILL_ACTIVE;
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
    attr?.object_px ? attr.object_px.map((o) => `${o.x},${o.y},${o.type_id}`).join(";") : "",
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
// AI-object type id → { label, color, d }. `d` is a Material Design Icon path on
// a 24×24 viewBox — the SINGLE glyph source, shared by the canvas markers
// (Path2D) and the legend (inline <svg>), so the two can never drift and neither
// depends on Home Assistant's pinned MDI version. Unknown ids fall back to
// OBJECT_ICON_FALLBACK. Type 1005 (carpet) is excluded server-side.
const OBJECT_ICONS = {
  // mdi:stocking
  "1001": { label: "Sock", color: "rgb(220,120,60)", d: "M17,2A2,2 0 0,1 19,4V7A2,2 0 0,1 17,9V17C17,17.85 16.5,18.57 15.74,18.86L9.5,21.77C8.5,22.24 7.29,21.81 6.83,20.81L6,19C5.5,18 5.95,16.8 6.95,16.34L10,14.91V9A2,2 0 0,1 8,7V4A2,2 0 0,1 10,2H17M10,4V7H17V4H10Z" },
  // mdi:shoe-sneaker
  "1002": { label: "Shoe", color: "rgb(180,100,40)", d: "M2 15C2 15 2 12 4 12C4.68 12 5.46 11.95 6.28 11.82C7.2 12.54 8.5 13 10 13H10.25L8.56 11.29C8.91 11.18 9.25 11.05 9.59 10.91L11.5 12.82C11.89 12.74 12.25 12.63 12.58 12.5L10.55 10.45C10.85 10.28 11.14 10.11 11.43 9.91L13.5 12C13.8 11.79 14.04 11.56 14.25 11.32L12.22 9.29C12.46 9.07 12.7 8.83 12.92 8.58L14.79 10.45C14.91 10.14 15 9.83 15 9.5C15 8.65 14.55 7.89 13.84 7.28C13.89 7.19 13.95 7.1 14 7L15.53 6.23C16.38 7.17 18.14 7.84 20.25 7.97L20.3 8H21C21 8 22 9 22 12.5C22 13.07 22 13.57 21.96 14H19C17.9 14 16.58 14.26 15.3 14.5C14.12 14.76 12.9 15 12 15H2M21 17C21 17 21.58 17 21.86 15H19C17 15 14 16 12 16H2.28C2.62 16.6 3.26 17 4 17H21Z" },
  // mdi:power-plug
  "1003": { label: "Wire", color: "rgb(230,60,60)", d: "M16,7V3H14V7H10V3H8V7H8C7,7 6,8 6,9V14.5L9.5,18V21H14.5V18L18,14.5V9C18,8 17,7 16,7Z" },
  // mdi:cat
  "1006": { label: "Cat", color: "rgb(160,100,200)", d: "M12,8L10.67,8.09C9.81,7.07 7.4,4.5 5,4.5C5,4.5 3.03,7.46 4.96,11.41C4.41,12.24 4.07,12.67 4,13.66L2.07,13.95L2.28,14.93L4.04,14.67L4.18,15.38L2.61,16.32L3.08,17.21L4.53,16.32C5.68,18.76 8.59,20 12,20C15.41,20 18.32,18.76 19.47,16.32L20.92,17.21L21.39,16.32L19.82,15.38L19.96,14.67L21.72,14.93L21.93,13.95L20,13.66C19.93,12.67 19.59,12.24 19.04,11.41C20.97,7.46 19,4.5 19,4.5C16.6,4.5 14.19,7.07 13.33,8.09L12,8M9,11A1,1 0 0,1 10,12A1,1 0 0,1 9,13A1,1 0 0,1 8,12A1,1 0 0,1 9,11M15,11A1,1 0 0,1 16,12A1,1 0 0,1 15,13A1,1 0 0,1 14,12A1,1 0 0,1 15,11M11,14H13L12.3,15.39C12.5,16.03 13.06,16.5 13.75,16.5A1.5,1.5 0 0,0 15.25,15H15.75A2,2 0 0,1 13.75,17C13,17 12.35,16.59 12,16V16H12C11.65,16.59 11,17 10.25,17A2,2 0 0,1 8.25,15H8.75A1.5,1.5 0 0,0 10.25,16.5C10.94,16.5 11.5,16.03 11.7,15.39L11,14Z" },
  // mdi:dog
  "1007": { label: "Dog", color: "rgb(160,100,200)", d: "M18,4C16.29,4 15.25,4.33 14.65,4.61C13.88,4.23 13,4 12,4C11,4 10.12,4.23 9.35,4.61C8.75,4.33 7.71,4 6,4C3,4 1,12 1,14C1,14.83 2.32,15.59 4.14,15.9C4.78,18.14 7.8,19.85 11.5,20V15.72C10.91,15.35 10,14.68 10,14C10,13 12,13 12,13C12,13 14,13 14,14C14,14.68 13.09,15.35 12.5,15.72V20C16.2,19.85 19.22,18.14 19.86,15.9C21.68,15.59 23,14.83 23,14C23,12 21,4 18,4M4.15,13.87C3.65,13.75 3.26,13.61 3,13.5C3.25,10.73 5.2,6.4 6.05,6C6.59,6 7,6.06 7.37,6.11C5.27,8.42 4.44,12.04 4.15,13.87M9,12A1,1 0 0,1 8,11C8,10.46 8.45,10 9,10A1,1 0 0,1 10,11C10,11.56 9.55,12 9,12M15,12A1,1 0 0,1 14,11C14,10.46 14.45,10 15,10A1,1 0 0,1 16,11C16,11.56 15.55,12 15,12M19.85,13.87C19.56,12.04 18.73,8.42 16.63,6.11C17,6.06 17.41,6 17.95,6C18.8,6.4 20.75,10.73 21,13.5C20.75,13.61 20.36,13.75 19.85,13.87Z" },
  // mdi:emoticon-poop
  "1011": { label: "Pet waste", color: "rgb(200,60,60)", d: "M11.36,2C11.15,2 10.87,2.12 10.57,2.32C10,2.7 8.85,3.9 8.4,5.1C8.06,6 8.05,6.82 8.19,7.43C7.63,7.53 7.22,7.71 7.06,7.78C6.55,8 5.47,8.96 5.37,10.45C5.34,10.97 5.41,11.5 5.57,12C4.91,12.19 4.53,12.43 4.5,12.44C4.18,12.56 3.65,12.93 3.5,13.13C3.15,13.53 2.92,14 2.79,14.5C2.5,15.59 2.6,16.83 3.13,17.83C3.42,18.39 3.82,19 4.26,19.43C5.7,20.91 8.18,21.47 10.14,21.79C12.53,22.19 15.03,22.05 17.26,21.13C20.61,19.74 21.5,17.5 21.64,16.89C21.93,15.5 21.57,14.19 21.42,13.87C21.2,13.41 20.84,12.94 20.25,12.64C19.85,12.39 19.5,12.26 19.24,12.2C19.5,11.25 19.13,10.5 18.62,9.94C17.85,9.12 17.06,9 17.06,9V9C17.32,8.5 17.42,7.9 17.28,7.32C17.12,6.61 16.73,6.16 16.22,5.86C15.7,5.55 15.06,5.4 14.4,5.28C14.08,5.22 12.75,5.03 12.2,4.27C11.75,3.65 11.74,2.53 11.62,2.2C11.57,2.07 11.5,2 11.36,2M16,9.61C16.07,9.61 16.13,9.62 16.19,9.62C17.62,9.78 18.64,11.16 18.47,12.69C18.3,14.22 17,15.34 15.57,15.18V15.18C14.14,15 13.12,13.65 13.29,12.11C13.45,10.66 14.64,9.56 16,9.61M8.62,9.61C9.95,9.65 11.06,10.78 11.16,12.21C11.28,13.75 10.21,15.08 8.78,15.19H8.77C7.34,15.3 6.08,14.14 5.96,12.6V12.6C5.85,11.06 6.92,9.73 8.35,9.62V9.62C8.44,9.61 8.53,9.61 8.62,9.61M8.64,11.31C8.6,11.31 8.57,11.31 8.53,11.32C7.97,11.39 7.57,11.9 7.64,12.45C7.7,13 8.21,13.39 8.77,13.32C9.33,13.25 9.73,12.74 9.67,12.19C9.61,11.67 9.15,11.3 8.64,11.31M15.94,11.33C15.42,11.35 15,11.75 14.96,12.28C14.92,12.83 15.35,13.31 15.91,13.34C16.5,13.38 16.96,12.95 17,12.4C17.04,11.84 16.61,11.36 16.05,11.33C16,11.33 16,11.33 15.94,11.33M8.71,16.15C9,16.14 9.26,16.23 9.5,16.28C10.68,16.5 11.7,16.53 12.19,16.53C12.68,16.53 13.69,16.5 14.86,16.28C15.27,16.2 15.74,16.03 16.11,16.28C16.59,16.6 16.24,17.75 15.5,18.53C15.04,19 13.97,19.91 12.19,19.91C10.41,19.91 9.33,19 8.88,18.53C8.14,17.75 7.79,16.6 8.26,16.28C8.4,16.19 8.55,16.15 8.71,16.15Z" },
  // mdi:scale-bathroom
  "1017": { label: "Scale", color: "rgb(80,140,200)", d: "M5,2H19A2,2 0 0,1 21,4V20A2,2 0 0,1 19,22H5A2,2 0 0,1 3,20V4A2,2 0 0,1 5,2M12,4A4,4 0 0,0 8,8H11.26L10.85,5.23L12.9,8H16A4,4 0 0,0 12,4M5,10V20H19V10H5Z" },
  // mdi:chair-rolling
  "1038": { label: "Chair", color: "rgb(120,120,120)", d: "M22 10V13H19V10H22M2 13H5V10H2V13M17 5C17 3.9 16.1 3 15 3H9C7.9 3 7 3.9 7 5V13H17V5M7 15H6V17H11V18L7 22H9.8L12 19.8L14.2 22H17L13 18V17H18V15H7Z" },
};

// mdi:help-circle-outline — unknown / newly-added detection types.
const OBJECT_ICON_FALLBACK = { label: "Object", color: "rgb(160,160,160)", d: "M11,18H13V16H11V18M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,20 12,20M12,6A4,4 0 0,0 8,10H10A2,2 0 0,1 12,8A2,2 0 0,1 14,10C14,12 11,11.75 11,15H13C13,12.75 16,12.5 16,10A4,4 0 0,0 12,6Z" };

function objectIcon(typeId) {
  return OBJECT_ICONS[String(typeId)] || OBJECT_ICON_FALLBACK;
}

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
  const g = objectMarkerGeom(LEGEND_MARKER_R);
  for (const typeId of Object.keys(objs)) {
    const ic = objectIcon(typeId);
    items.push({
      key: "obj_" + typeId,
      label: ic.label,
      kind: "icon",
      color: ic.color,
      d: ic.d,
      count: objs[typeId],
      // Same disc/rim/glyph composition as the map marker (drawObjects), derived
      // from the shared ratios. Glyph is centred in the 24×24 viewBox (disc
      // centre 12): offset = 12 − 12·glyphScale.
      discR: LEGEND_MARKER_R,
      rimWidth: g.rimWidth,
      glyphScale: g.glyphScale,
      glyphOffset: 12 - 12 * g.glyphScale,
    });
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
  drawObjects(ctx, contentDims, vs);
  drawCharger(ctx, contentDims, vs);
  // Zone box under the robot so the robot icon + pulse (the primary "where is it"
  // signal) always reads on top of the translucent area fill.
  drawZoneRect(ctx, contentDims, vs);
  drawRobot(ctx, contentDims, vs);
  return hitAreas;
}

function drawZoneRect(ctx, canvas, vs) {
  const r = vs.zoneRect;
  if (!r) return;
  const imgSize = vs.attr?.map_image_size;
  if (!imgSize) return;
  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  const n = normalizeRect(r);
  const x = n.x0 * scaleX;
  const y = n.y0 * scaleY;
  const w = (n.x1 - n.x0) * scaleX;
  const h = (n.y1 - n.y0) * scaleY;
  const radius = Math.min(10, w / 2, h / 2);
  ctx.save();
  // Kärcher-yellow fill + accent stroke, matching the rest of the card's
  // accent usage (--rcv-accent / --rcv-accent-deep). While editing it's the
  // lighter draw fill; during the clean it deepens to the room-highlight alpha
  // so the cleaned area reads at the same brightness as a highlighted room.
  ctx.fillStyle = vs.zoneEditable ? ZONE_FILL : ZONE_FILL_ACTIVE;
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

// Object-marker proportions — the SINGLE source of the disc/rim/glyph look,
// shared by the canvas markers (drawObjects) and the legend swatch (legendItems
// → card-render). Only these two ratios define the composition; each target does
// its own centring off glyphScale, so there are no drift-prone baked literals.
const OBJECT_RIM_FACTOR = 0.14; // white rim width ÷ disc radius
const OBJECT_GLYPH_SPAN = 1.5; // white glyph width ÷ disc radius
// Disc radius inside the 24×24 legend viewBox (legend swatch only).
const LEGEND_MARKER_R = 11;
function objectMarkerGeom(r) {
  return {
    rimWidth: Math.max(1, r * OBJECT_RIM_FACTOR),
    glyphScale: (r * OBJECT_GLYPH_SPAN) / 24,
  };
}

// Path2D is immutable once built; cache one per type so the animation loop
// doesn't re-parse the path string every frame.
const _objPathCache = new Map();
function objectPath(d) {
  let p = _objPathCache.get(d);
  if (!p) {
    p = new Path2D(d);
    _objPathCache.set(d, p);
  }
  return p;
}

// Detected AI objects (wire, pet, shoe, …) as coloured discs with a white MDI
// glyph, drawn from the object_px overlay. Snapshot-derived like the dock — no
// path-style persistence. Drawn under the dock and robot so the "where is it"
// signal always reads on top.
function drawObjects(ctx, canvas, vs) {
  const objs = vs.attr?.object_px;
  const imgSize = vs.attr?.map_image_size;
  if (!objs || !objs.length || !imgSize) return;

  const dpr = vs.dpr || 1;
  const { scaleX, scaleY } = canvasScale(canvas.width, canvas.height, imgSize, dpr);
  // Same footprint as the robot icon (drawRobot) so markers scale with the map
  // and read at a matching size at every zoom level.
  const r = imgSize.cell_size * scaleX * ROBOT_RADIUS_CELLS;
  const { rimWidth, glyphScale } = objectMarkerGeom(r);

  for (const o of objs) {
    const ic = objectIcon(o.type_id);
    ctx.save();
    ctx.translate(o.x * scaleX, o.y * scaleY);

    // Coloured disc with a white rim — keeps the per-type colour coding and
    // separates the marker from a busy map background.
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fillStyle = ic.color;
    ctx.fill();
    ctx.lineWidth = rimWidth;
    ctx.strokeStyle = "rgba(255,255,255,0.92)";
    ctx.stroke();

    // White glyph centred on the disc: scale the 24×24 path, then shift its
    // centre (12,12) to the origin.
    ctx.scale(glyphScale, glyphScale);
    ctx.translate(-12, -12);
    ctx.fillStyle = "#fff";
    ctx.fill(objectPath(ic.d));
    ctx.restore();
  }
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

  // Accent tint for the active selection (customise's picks or standard's
  // selected/queued rooms — same fill either way).
  const selected = vs.cardMode === "customise" ? vs.customiseSelected : vs.selectedRooms;
  for (const [id, room] of Object.entries(roomMap)) {
    const cells = room.cells;
    if (!cells || cells.length === 0) continue;
    if (selected.has(id)) fillCells(cells, ROOM_SELECTED_FILL);
  }
}

// Per-room label geometry — bbox-over-cells + measureText per room — is the only
// static op that runs unconditionally over every room each reveal frame, yet it
// depends solely on the room data and the content scale, both stable between HA
// pushes. Memoize it keyed on the room_map object plus scaleX/cs.
//
// LOAD-BEARING: this cache is only correct because room_map is rebuilt into a
// fresh object on every HA push (see computeDrawKey), so any room rename/reshape
// arrives as a new key and busts the entry. If room_map ever became
// reference-stable across pushes, stale label text/size would render — invalidate
// explicitly then. scaleX (canvas resize) and cs (cell_size) both feed fontSize
// and the bbox, so both are in the key; zoom is applied live below, so it isn't.
// measureText is unaffected by the ctx transform, so measuring with the live ctx
// is exact.
const _labelLayoutCache = new WeakMap();

function roomLabelLayouts(ctx, roomMap, scaleX, cs) {
  const hit = _labelLayoutCache.get(roomMap);
  if (hit && hit.scaleX === scaleX && hit.cs === cs) return hit.layouts;
  const layouts = [];
  for (const [id, room] of Object.entries(roomMap)) {
    const cells = room.cells;
    if (!cells || cells.length === 0) continue;
    const centroid = roomCentroid(roomBoundingBox(cells, cs));
    const chipText = roomChipText({ ...room, id });
    const fontSize = Math.max(16, Math.min(24, cs * scaleX * 2.1));
    ctx.font = `bold ${fontSize}px sans-serif`;
    const tw = ctx.measureText(chipText).width;
    layouts.push({
      id,
      cxImg: centroid.cx,
      cyImg: centroid.cy,
      chipText,
      fontSize,
      ph: fontSize * 1.65, // one 1.25em text line + 0.4em vertical padding
      pw: tw + fontSize * 1.8,
    });
  }
  _labelLayoutCache.set(roomMap, { scaleX, cs, layouts });
  return layouts;
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

  for (const { id, cxImg, cyImg, chipText, fontSize, ph, pw } of roomLabelLayouts(ctx, roomMap, scaleX, cs)) {
    const cx = cxImg * scaleX;
    const cy = cyImg * scaleY;

    const isSelected = isCustomise ? vs.customiseSelected.has(id) : vs.selectedRooms.has(id);

    ctx.save();
    // Labels keep a constant on-screen size: anchor at the room centroid
    // (which pans/zooms with the map), then locally undo the zoom so the
    // pill/text render at 1:1 regardless of zoom level. All pill geometry
    // below is relative to this origin.
    ctx.translate(cx, cy);
    ctx.scale(1 / zoom, 1 / zoom);
    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.textBaseline = "middle";

    const pillX = -pw / 2;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.35)";
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 1;
    ctx.fillStyle = isSelected ? accentFill(0.75) : "rgba(255,255,255,0.7)";
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
