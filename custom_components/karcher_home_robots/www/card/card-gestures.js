import {
  clientToImagePx, minZonePx, fitContentBox, ZONE_HANDLE_RADIUS_PX, hitTestZoneRect,
  clampZoneRect, pinchStep, dragPan, TAP_SLOP_PX, moveZoneRect, resizeZoneRect,
  panEdgeHidden, clampPan, zoomAtPoint, buildCellLookup, hitTestRooms,
} from "./geometry.js";

// Map pointer/zoom/pan/zone gesture handlers (operate on the card element).

export function zonePx(el, e) {
    const imgSize = el._imgSize();
    if (!imgSize || !el._canvas) return null;
    const rect = el._canvas.getBoundingClientRect();
    const { px, py } = clientToImagePx(e.clientX, e.clientY, rect, imgSize, el._zoom, el._pan);
    return {
      x: Math.max(0, Math.min(imgSize.width, px)),
      y: Math.max(0, Math.min(imgSize.height, py)),
    };
  }

export function zoneMinPx(el) {
    const cellSize = el._imgSize()?.cell_size;
    return minZonePx(cellSize);
  }

export function zoneHandleRadiusPx(el) {
    const imgSize = el._imgSize();
    if (!imgSize || !el._canvas) return ZONE_HANDLE_RADIUS_PX;
    const dpr = el._dpr || 1;
    // Content-box scale, not raw canvas scale — the full-bleed canvas is wider
    // than the aspect-fit map it letterboxes.
    const box = fitContentBox(el._canvas.width / dpr, el._canvas.height / dpr, imgSize);
    const scaleX = box.w / imgSize.width;
    return ZONE_HANDLE_RADIUS_PX / (scaleX || 1) / (el._zoom || 1);
  }

export function zoneBounds(el) {
    const imgSize = el._imgSize();
    return imgSize ? { width: imgSize.width, height: imgSize.height } : { width: 0, height: 0 };
  }

export function pinchGeometry(el) {
    const pts = [...el._activePointers.values()];
    const [a, b] = pts;
    return {
      mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
      dist: Math.hypot(b.x - a.x, b.y - a.y),
    };
  }

export function armPanDrag(el, e) {
    if (el._zoom <= 1) return;
    const pt = el._activePointers.get(e.pointerId);
    if (!pt) return;
    el._panDrag = { pointerId: e.pointerId, start: { ...pt }, pan: el._pan };
  }

export function onMapPointerDown(el, e) {
    if (!el._canvas) return;
    const rect = el._canvas.getBoundingClientRect();
    el._activePointers.set(e.pointerId, { x: e.clientX - rect.left, y: e.clientY - rect.top });
    el._canvas.setPointerCapture?.(e.pointerId);
    // Fresh single-finger touch starting a new sequence — clear any leftover
    // swallow flag from a prior pinch that ended without a synthetic click,
    // so el new tap isn't silently eaten too.
    if (el._activePointers.size === 1) el._gestured = false;

    if (el._activePointers.size >= 2) {
      // A second finger landing always starts/continues a pinch/pan, even if
      // a zone drag or one-finger pan was mid-gesture on the first finger —
      // never resume those once pinch takes over (would require lift +
      // re-press). Snapshot the gesture's starting geometry once here;
      // pinchStep references el FIXED start every frame rather than the
      // previous frame (see pinchStep for why the incremental version
      // ratchets/drifts).
      e.preventDefault();
      el._zoneDrag = null;
      el._panDrag = null;
      el._gestured = true;
      el._pinch = { ...el._pinchGeometry(), zoom: el._zoom, pan: el._pan };
      return;
    }

    if (!el._zoneMode) {
      el._armPanDrag(e);
      return;
    }
    const activity = el._vacState()?.state;
    if (el._controlsLocked(activity)) {
      el._armPanDrag(e);
      return;
    }
    const p = el._zonePx(e);
    if (!p) return;
    e.preventDefault();

    const hit = hitTestZoneRect(p.x, p.y, el._zoneRect, el._zoneHandleRadiusPx());
    if (hit === "body") {
      // Grab offset from the rect's top-left, fixed for the whole gesture —
      // an incremental delta would drift once the rect clamps at a map edge.
      const x0 = Math.min(el._zoneRect.x0, el._zoneRect.x1);
      const y0 = Math.min(el._zoneRect.y0, el._zoneRect.y1);
      el._zoneDrag = { mode: "move", grabDX: p.x - x0, grabDY: p.y - y0 };
    } else if (hit) {
      el._zoneDrag = { mode: "resize", corner: hit };
    } else if (!el._zoneRect) {
      // No selection yet at all (map not loaded when Area was entered) —
      // draw a fresh one. Once a selection exists, a tap outside it is a
      // no-op: the selection always stays present, never replaced by a click.
      el._zoneDrag = { mode: "create" };
      el._zoneRect = clampZoneRect({ x0: p.x, y0: p.y, x1: p.x, y1: p.y }, el._zoneMinPx());
    } else {
      // Outside the existing selection: never replaces the rect, but while
      // zoomed in the drag can still pan the map.
      el._armPanDrag(e);
      return;
    }
    el._lastDrawKey = null;
    el.requestUpdate();
  }

export function onZonePointerHover(el, e) {
    if (!el._zoneMode || !el._zoneRect || !el._canvas) return;
    // Controls locked (a clean is running): the box is a static marker, not
    // editable — keep the default cursor so it doesn't imply drag/resize. Mirrors
    // the pointer-down guard, which arms a pan instead of a zone drag here.
    if (el._controlsLocked(el._vacState()?.state)) {
      el._canvas.style.cursor = "default";
      return;
    }
    const p = el._zonePx(e);
    if (!p) return;
    const hit = hitTestZoneRect(p.x, p.y, el._zoneRect, el._zoneHandleRadiusPx());
    const cursor =
      hit === "nw" || hit === "se" ? "nwse-resize" :
      hit === "ne" || hit === "sw" ? "nesw-resize" :
      hit === "body" ? "move" : "default";
    el._canvas.style.cursor = cursor;
  }

export function onMapPointerMove(el, e) {
    if (!el._canvas) return;
    if (el._activePointers.has(e.pointerId)) {
      const rect = el._canvas.getBoundingClientRect();
      el._activePointers.set(e.pointerId, { x: e.clientX - rect.left, y: e.clientY - rect.top });
    }

    if (el._activePointers.size >= 2 && el._pinch) {
      e.preventDefault();
      const { mid, dist } = el._pinchGeometry();
      const dpr = el._dpr || 1;
      const cssW = el._canvas.width / dpr;
      const cssH = el._canvas.height / dpr;
      // Reference the FIXED gesture-start snapshot every frame (not the
      // previous frame) — see pinchStep for why the incremental version drifts.
      const { zoom, pan } = pinchStep(el._pinch, mid, dist, cssW, cssH, el._imgSize());
      // Crossing 1 mid-pinch arms the nudge, but the fingers are still driving
      // pan/zoom — defer the animation to pointerup so it can't fight the gesture.
      if (el._zoom <= 1 && zoom > 1 && !el._hasNudged) el._nudgePending = true;
      el._zoom = zoom;
      el._pan = pan;
      el._lastDrawKey = null;
      el.requestUpdate();
      return;
    }

    if (el._panDrag && el._panDrag.pointerId === e.pointerId) {
      const pt = el._activePointers.get(e.pointerId);
      const dx = pt.x - el._panDrag.start.x;
      const dy = pt.y - el._panDrag.start.y;
      // Within the slop radius el may still turn out to be a tap — hold off.
      // Past it once, the whole sequence is a pan (and the trailing click is
      // swallowed), even if the finger later re-enters the slop radius.
      if (!el._gestured && Math.hypot(dx, dy) < TAP_SLOP_PX) return;
      el._gestured = true;
      e.preventDefault();
      const dpr = el._dpr || 1;
      el._pan = dragPan(
        el._panDrag.pan, dx, dy, el._zoom,
        el._canvas.width / dpr, el._canvas.height / dpr, el._imgSize()
      );
      el._lastDrawKey = null;
      el.requestUpdate();
      return;
    }

    if (!el._zoneMode) return;
    if (!el._zoneDrag || !el._zoneRect) {
      el._onZonePointerHover(e);
      return;
    }
    const p = el._zonePx(e);
    if (!p) return;
    const d = el._zoneDrag;
    if (d.mode === "create") {
      const { x0, y0 } = el._zoneRect;
      el._zoneRect = clampZoneRect({ x0, y0, x1: p.x, y1: p.y }, el._zoneMinPx());
    } else if (d.mode === "move") {
      const x0 = Math.min(el._zoneRect.x0, el._zoneRect.x1);
      const y0 = Math.min(el._zoneRect.y0, el._zoneRect.y1);
      const dx = (p.x - d.grabDX) - x0;
      const dy = (p.y - d.grabDY) - y0;
      el._zoneRect = moveZoneRect(el._zoneRect, dx, dy, el._zoneBounds());
    } else if (d.mode === "resize") {
      el._zoneRect = resizeZoneRect(el._zoneRect, d.corner, p.x, p.y, el._zoneMinPx(), el._zoneBounds());
    }
    el._lastDrawKey = null;
    el.requestUpdate();
  }

export function onMapPointerUp(el, e) {
    el._activePointers.delete(e.pointerId);
    el._canvas?.releasePointerCapture?.(e.pointerId);
    if (el._panDrag?.pointerId === e.pointerId) el._panDrag = null;
    if (el._activePointers.size < 2) {
      // Dropping below 2 fingers ends the pinch outright — never resume it
      // or fall back into a zone drag from the remaining finger; that finger
      // must be lifted and re-pressed to start a fresh gesture.
      el._pinch = null;
    }
    // Fire the deferred pinch-zoom nudge only once every finger is off the map,
    // so the animated pan can't fight a still-active gesture.
    if (el._nudgePending && el._activePointers.size === 0) {
      el._nudgePending = false;
      el._triggerNudge();
    }
    el.requestUpdate();
    if (!el._zoneMode || !el._zoneDrag) return;
    el._zoneDrag = null;
    el._lastDrawKey = null;
  }

export function resetZoom(el) {
    el._zoom = 1;
    el._pan = { x: 0, y: 0 };
    el._panDrag = null;
    el._pinch = null;
    el._hasNudged = false;
    el._nudgePending = false;
    if (el._nudgeRaf) {
      cancelAnimationFrame(el._nudgeRaf);
      el._nudgeRaf = null;
    }
    el._lastDrawKey = null;
    el.requestUpdate();
  }

export function triggerNudge(el) {
    if (el._hasNudged) return;
    el._hasNudged = true;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    if (!el._canvas || el._zoom <= 1) return;
    const dpr = el._dpr || 1;
    const cssW = el._canvas.width / dpr;
    const cssH = el._canvas.height / dpr;
    const imgSize = el._imgSize();
    const hidden = panEdgeHidden(el._pan, el._zoom, cssW, cssH, imgSize);
    const totalX = hidden.left + hidden.right;
    const totalY = hidden.top + hidden.bottom;
    if (totalX < 1 && totalY < 1) return; // fully framed — nothing to reveal
    // Nudge on the dominant axis, toward the side hiding more (guaranteed room to
    // move, so the clamp can't swallow the animation). Revealing the right/bottom
    // means panning content the other way → negative offset.
    const AMP = 24; // px peak displacement
    const horiz = totalX >= totalY;
    const dx = horiz ? (hidden.right >= hidden.left ? -AMP : AMP) : 0;
    const dy = horiz ? 0 : (hidden.bottom >= hidden.top ? -AMP : AMP);
    const base = { ...el._pan };
    const DURATION = 540;
    const start = performance.now();
    const tick = (now) => {
      // A real gesture or a reset takes over — abandon and restore.
      if (el._panDrag || el._pinch || el._zoom <= 1) {
        el._nudgeRaf = null;
        return;
      }
      const t = Math.min(1, (now - start) / DURATION);
      const k = Math.sin(t * Math.PI); // 0 → 1 → 0: out and back to rest
      el._pan = clampPan(
        { x: base.x + dx * k, y: base.y + dy * k },
        el._zoom, cssW, cssH, imgSize,
      );
      el._lastDrawKey = null;
      el.requestUpdate();
      if (t < 1) {
        el._nudgeRaf = requestAnimationFrame(tick);
        return;
      }
      el._pan = base; // land exactly where we started
      el._nudgeRaf = null;
      el._lastDrawKey = null;
      el.requestUpdate();
    };
    el._nudgeRaf = requestAnimationFrame(tick);
  }

export function onWheelZoom(el, e) {
    if (!el._canvas) return;
    const imgSize = el._imgSize();
    if (!imgSize) return;
    const dpr = el._dpr || 1;
    const cssW = el._canvas.width / dpr;
    const cssH = el._canvas.height / dpr;
    if (!e.ctrlKey) {
      if (el._zoom <= 1) return;
      e.preventDefault();
      el._pan = dragPan(el._pan, -e.deltaX, -e.deltaY, el._zoom, cssW, cssH, imgSize);
      el._lastDrawKey = null;
      el.requestUpdate();
      return;
    }
    e.preventDefault();
    const rect = el._canvas.getBoundingClientRect();
    const focal = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    // Negative deltaY (scroll up / pinch out) zooms in. Rate tuned +30% per
    // user feedback that the original 0.0015 felt sluggish.
    const factor = Math.exp(-e.deltaY * 0.00195);
    const { zoom, pan } = zoomAtPoint(el._zoom, el._pan, el._zoom * factor, focal);
    const crossedIntoZoom = el._zoom <= 1 && zoom > 1;
    el._zoom = zoom;
    el._pan = clampPan(pan, zoom, cssW, cssH, imgSize);
    el._lastDrawKey = null;
    el.requestUpdate();
    // No pointers to wait on for a wheel/trackpad zoom — nudge as soon as it
    // crosses into zoom (the flag guards the once-per-session behaviour).
    if (crossedIntoZoom) el._triggerNudge();
  }

export function startZoneClean(el) {
    const r = el._zoneRect;
    if (!r) return;
    el.hass.callService("vacuum", "send_command", {
      entity_id: el._config.vacuum_entity,
      command: "app_zone_clean",
      params: { rect_px: [r.x0, r.y0, r.x1, r.y1] },
    });
    // Keep the drawn rect in place after starting so the user can see and
    // re-run what they selected, rather than resetting to the centered default.
  }

export function onCanvasClick(el, e) {
    // A pinch/pan gesture can end with a synthesized trailing click — swallow
    // exactly that one so it doesn't also toggle whatever room was underneath.
    if (el._gestured) {
      el._gestured = false;
      return;
    }
    if (el._zoneMode) return;
    if (!el.hass || !el._config) return;
    const vacState = el._vacState();
    const activity = vacState?.state;
    if (el._controlsLocked(activity)) return;
    const attr = vacState?.attributes;
    const roomMap = attr?.room_map;
    const imgSize = attr?.map_image_size;
    if (!roomMap || !imgSize) return;

    const cs = imgSize.cell_size || 1;
    const rect = el._canvas.getBoundingClientRect();
    const { px, py, snapCol, snapRow } = clientToImagePx(
      e.clientX, e.clientY, rect, imgSize, el._zoom, el._pan
    );

    if (!el._cellLookup || el._cellLookupAttr !== attr) {
      el._cellLookup = buildCellLookup(roomMap, cs);
      el._cellLookupAttr = attr;
    }

    const hitId = hitTestRooms(
      px, py, snapRow, snapCol, el._roomCheckboxHitAreas, el._cellLookup
    );
    if (hitId === undefined) return;

    // Same toggle path as the sheet's room chips and the room-list leaf — one
    // handler owns the selection/pending/service-call logic. The draw key
    // covers the selection sets, so the overlay redraws without forcing it.
    el._onRoomToggle({ detail: { roomId: hitId, on: !el._activeSelection().has(hitId) } });
  }
