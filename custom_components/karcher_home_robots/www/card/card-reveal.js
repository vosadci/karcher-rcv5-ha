import { companionEntity } from "./card-view.js";
import { computeDrawKey, drawMap, pathArcLength, revealPath, lerpAngle } from "./map-draw.js";
import { clampPan } from "./geometry.js";
import { isBusy, isUsableValue } from "./derive.js";

// Map draw + robot reveal animation loop (operate on the card element).

export function pulsePhase(el, now) {
    const ping = el.renderRoot?.querySelector(".status-dot-ping");
    for (const anim of ping?.getAnimations?.() ?? []) {
      if (anim.animationName !== "rcv-ping") continue;
      const ct = anim.currentTime;
      const ms = typeof ct === "number" ? ct : ct?.value;
      if (typeof ms === "number" && Number.isFinite(ms)) return (ms % 1600) / 1600;
    }
    return (now % 1600) / 1600;
  }

export function sizeCanvasIfNeeded(el) {
    if (!el._needsCanvasSize || !el._canvas) return;
    const rect = el._canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return; // not laid out yet — retry next update
    const dpr = window.devicePixelRatio || 1;
    el._canvas.width = rect.width * dpr;
    el._canvas.height = rect.height * dpr;
    el._dpr = dpr;
    el._needsCanvasSize = false;
    el._lastDrawKey = null; // force a draw on the freshly-sized canvas
    // Re-clamp pan against the new CSS size — a pan valid before a resize
    // (rotation, sidebar toggle) can expose the map edge afterward otherwise.
    el._pan = clampPan(el._pan, el._zoom, rect.width, rect.height, el._imgSize());
  }

export function updateMap(el, attr) {
    const mapEntity = companionEntity(el, "map_entity");
    const mapState = mapEntity ? el.hass.states[mapEntity] : null;
    if (!mapState) return;

    const pic = mapState.attributes.entity_picture;
    const token = mapState.attributes.access_token || "";
    const imageTimestamp = mapState.state;

    // Unavailable/unknown image entities carry no entity_picture or access
    // token; fetching /api/image_proxy with an empty token triggers HA's
    // invalid-auth ban warning. Keep the last-loaded map and skip the fetch.
    if (!isUsableValue(imageTimestamp)) return;

    if (imageTimestamp !== el._mapToken) {
      el._mapToken = imageTimestamp;
      el._mapError = false;
      el._mapPending = true;
      const url = pic
        ? `${pic}&_t=${encodeURIComponent(imageTimestamp)}`
        : `/api/image_proxy/${encodeURIComponent(mapEntity)}?token=${encodeURIComponent(token)}&_t=${encodeURIComponent(imageTimestamp)}`;
      const img = new Image();
      el._mapImgLoad = img;
      img.onload = () => {
        if (el._mapImgLoad !== img) return;
        el._mapImgLoad = null;
        el._mapImg = img;
        el._mapLoaded = true;
        el._mapPending = false;
        // Do NOT measure the canvas here: it is still display:none until the
        // re-render below applies the .mapLoaded binding, so getBoundingClientRect
        // would return 0×0 and the map would draw blank. Sizing happens in
        // updated() (_sizeCanvasIfNeeded), after the canvas is visible in layout.
        el._needsCanvasSize = true;
        el.requestUpdate();
      };
      img.onerror = () => {
        if (el._mapImgLoad !== img) return;
        el._mapImgLoad = null;
        el._mapPending = false;
        el._mapError = true;
        el.requestUpdate();
      };
      img.src = url;
    } else if (el._mapLoaded) {
      el._drawMap(attr);
    }
  }

// Attempts before giving up on the robot icon. Callers are draw-key changes and
// reveal-loop starts, not frames, so a handful of retries costs little — but an
// asset that is genuinely absent must stop being requested rather than issue one
// fetch per redraw for the life of the card.
const ROBOT_ICON_MAX_ATTEMPTS = 3;

export function loadRobotIcon(el) {
    if (el._robotIcon || el._robotIconLoading) return;
    if ((el._robotIconAttempts || 0) >= ROBOT_ICON_MAX_ATTEMPTS) return;
    el._robotIconAttempts = (el._robotIconAttempts || 0) + 1;
    el._robotIconLoading = true;
    const img = new Image();
    el._robotIconLoad = img;
    img.onload = () => {
      if (el._robotIconLoad !== img) return;
      el._robotIconLoad = null;
      el._robotIconLoading = false;
      el._robotIcon = img;
      // Redraw if map is already shown.
      if (el._mapLoaded && el.hass && el._config) {
        const attr = el._vacState()?.attributes;
        if (attr) el._drawMap(attr);
      }
    };
    // Without this the failure latched permanently: _robotIconLoading stayed
    // true, so every later call returned at the guard above and the robot marker
    // never appeared again for the life of the card — no error, no retry. The
    // map loader right above has always handled its own onerror; this is the
    // same treatment. A static asset can 404 while the integration's static path
    // is still being registered, or miss through a stale service worker.
    img.onerror = () => {
      if (el._robotIconLoad !== img) return;
      el._robotIconLoad = null;
      el._robotIconLoading = false;
    };
    img.src = "/karcher_home_robots/static/icon.svg";
  }

// ── robot-follower pacing (pure) ─────────────────────────────────────────────
// Extracted from the rAF loop below so the tuning can be tested. These constants
// and the shape of the curve were tuned against real hardware (the M1 glide
// work); the arithmetic here is a verbatim lift, not a re-derivation. Change the
// numbers only with a device to check them on.

const FOLLOWER_EASE_PX = 8;          // glide to a stop instead of snapping
const FOLLOWER_BUFFER_MS = 1600;     // trailing buffer ≈ two pushes of travel
const FOLLOWER_CATCHUP_GAIN = 0.001; // per-px correction past the buffer
const FOLLOWER_CATCHUP_MAX = 0.6;    // capped as a fraction of cruise speed
const FOLLOWER_MIN_MOVE_PX = 2;      // ignore sub-2px pushes when learning speed
const CRUISE_EMA_WEIGHT = 0.85;      // long window: per-push lumpiness averages out
// Past this much travel behind the tip the robot reported a jump, not motion: the
// RVM 4 sends no positions while mopping, then one 10-60 s later. Gliding that
// straight line runs the icon through walls, so it snaps instead.
const FOLLOWER_SNAP_MS = 5000;
const FOLLOWER_SNAP_MIN_PX = 60;    // floor, and the whole rule before speed is known
const FOLLOWER_JUMP_PX = 20;        // a move this large in one frame was a snap

// Icon speed (px/ms) for a given gap behind the live tip and measured cruise rate.
// Feed-forward dominated: cruise at `ema`, ease linearly to a stop inside
// FOLLOWER_EASE_PX, and add only a bounded correction once the gap exceeds the
// buffer — a gap-proportional term made earlier builds pulse.
export function followerSpeed(gap, ema) {
  const buffer = ema * FOLLOWER_BUFFER_MS;
  let speed = gap < FOLLOWER_EASE_PX ? ema * (gap / FOLLOWER_EASE_PX) : ema;
  if (gap > buffer) {
    speed += Math.min((gap - buffer) * FOLLOWER_CATCHUP_GAIN, ema * FOLLOWER_CATCHUP_MAX);
  }
  return speed;
}

// True when the icon should jump to the tip instead of gliding there.
export function followerShouldSnap(gap, ema) {
  if (!(ema > 0)) return gap > FOLLOWER_SNAP_MIN_PX;
  return gap > Math.max(FOLLOWER_SNAP_MIN_PX, ema * FOLLOWER_SNAP_MS);
}

// The line the icon travels: the drawn path, plus a straight last leg when the
// reported robot position is not the path's end (a pose newer than the path). The
// icon follows this line, so it can only cross a wall where no path exists.
const FOLLOWER_ON_PATH_PX = 2;
export function followLine(path, tip) {
  const n = path.length;
  if (n < 2) return [tip.x, tip.y];
  if (Math.hypot(tip.x - path[n - 2], tip.y - path[n - 1]) <= FOLLOWER_ON_PATH_PX) return path;
  return path.concat([tip.x, tip.y]);
}

// Advance the icon's distance along that line toward its end (`total`), at the
// follower speed, or jump to the end when it trails too far. Never overshoots.
export function followerAdvance(dispS, total, ema, dt) {
  const gap = total - dispS;
  if (followerShouldSnap(gap, ema)) return total;
  const move = followerSpeed(gap, ema || 0) * dt;
  return gap < 0.5 || move >= gap ? total : dispS + move;
}

// Fold one push into the cruise-speed EMA. Only learns while the robot is
// actually moving (>FOLLOWER_MIN_MOVE_PX), so genuine pauses and turns do not
// drag the average down. Returns `prev` unchanged when the push teaches nothing.
export function updateCruiseSpeed(prev, dist, dt) {
  if (!(dt > 0) || dist <= FOLLOWER_MIN_MOVE_PX) return prev;
  const inst = dist / dt;
  if (prev == null) return inst;
  return prev * CRUISE_EMA_WEIGHT + inst * (1 - CRUISE_EMA_WEIGHT);
}

export function robotMoving(el) {
    const v = el._vacState();
    if (isBusy(v?.state)) return true;
    return v?.attributes?.status_label === "locating";
  }

export function pulseColor(el) {
    if (!el._pulseColors) {
      const cs = getComputedStyle(el);
      el._pulseColors = {
        success: (cs.getPropertyValue("--success-color") || "").trim() || "#4caf50",
        primary: (cs.getPropertyValue("--primary-color") || "").trim() || "#03a9f4",
      };
    }
    const v = el._vacState();
    const usePrimary =
      v?.state === "returning" || v?.attributes?.status_label === "locating";
    return usePrimary ? el._pulseColors.primary : el._pulseColors.success;
  }

export function drawMapFrame(el, attr) {
    if (!el._mapImg || !el._canvas) return;
    el._revealAttr = attr;
    // Run the reveal loop whenever the robot is busy and has a pose: it glides
    // the icon along the path (cleaning/returning) and/or animates the pulse cue
    // (including locating, where the pose is static but we still want the pulse).
    // Everything else (docked/idle/paused) draws statically.
    const moving = el._robotMoving();
    const tip = attr.robot_px;
    if (!moving || !tip) {
      el._stopReveal();
      el._staticDraw(attr);
      return;
    }
    const path = attr.cur_path_px || [];
    const sig = `${path.length}:${path[path.length - 2]},${path[path.length - 1]}`;
    if (sig !== el._lastPathSig) {
      el._onNewPath(path, sig);
    }
    el._ensureRevealLoop();
  }

export function staticDraw(el, attr) {
    const vs = el._viewState(attr);
    const key = computeDrawKey(attr, vs);
    if (key === el._lastDrawKey) return;
    el._lastDrawKey = key;
    el._loadRobotIcon();
    const ctx = el._canvas.getContext("2d");
    el._roomCheckboxHitAreas = drawMap(ctx, el._canvas, vs);
  }

export function onNewPath(el, path, sig) {
    el._lastPathSig = sig;
    // Arc length only changes when the path does (same sig lifecycle), so cache
    // it here instead of re-walking the whole polyline every reveal frame.
    el._pathArcLen = pathArcLength(path);
    const now = performance.now();
    const rp = el._revealAttr?.robot_px;
    if (el._lastPushTs && rp && el._prevPushRpx) {
      const d = Math.hypot(rp.x - el._prevPushRpx.x, rp.y - el._prevPushRpx.y);
      el._robotEmaV = updateCruiseSpeed(el._robotEmaV, d, now - el._lastPushTs);
    }
    el._lastPushTs = now;
    if (rp) el._prevPushRpx = { x: rp.x, y: rp.y };
  }

export function ensureRevealLoop(el) {
    if (el._revealRaf) return;
    el._loadRobotIcon();
    const step = (now) => {
      if (!el._canvas || !el._mapImg || !el._robotMoving()) {
        el._revealRaf = null;
        return;
      }
      const attr = el._revealAttr;
      const path = attr?.cur_path_px || [];
      const tip = attr?.robot_px;
      if (!tip) {
        el._revealRaf = requestAnimationFrame(step);
        return;
      }

      // A whole-path reprojection (map refresh) moves every pixel including the
      // robot; snap the follower onto the new frame so it doesn't glide across
      // the discontinuity. Detected via the path head pixel changing.
      const head = path.length >= 2 ? `${path[0]},${path[1]}` : null;
      const reproj = head != null && el._prevPathHead != null && head !== el._prevPathHead;
      el._prevPathHead = head;

      const dt = el._revealLastTs ? Math.min(100, now - el._revealLastTs) : 16;
      el._revealLastTs = now;
      // The icon travels along the drawn path, not straight at the tip: the path
      // is the robot's real route, so the icon never cuts through a wall. Its
      // place is a distance along that line, paced by the feed-forward follower
      // (followerSpeed — cruise at the measured speed, ease to a stop, bounded
      // catch-up) and snapped to the end when it trails too far behind.
      const line = followLine(path, tip);
      const pathLen = el._pathArcLen ?? pathArcLength(path);
      const total = line === path ? pathLen : pathArcLength(line);
      if (el._robotDispS == null || reproj) {
        el._robotDispS = total; // first sight / post-reproject: snap, no glide
      }
      el._robotDispS = followerAdvance(
        Math.min(el._robotDispS, total), total, el._robotEmaV, dt
      );
      const cursor = revealPath(line, el._robotDispS);
      const snapped = el._robotDispS >= total && el._robotDispX != null &&
        Math.hypot(cursor.x - el._robotDispX, cursor.y - el._robotDispY) >
          FOLLOWER_JUMP_PX;
      el._robotDispX = cursor.x;
      el._robotDispY = cursor.y;
      if (snapped) {
        // A jump's direction says nothing about the robot's heading.
        el._robotPrevX = cursor.x;
        el._robotPrevY = cursor.y;
        if (tip.phi != null) el._robotDisplayPhi = tip.phi;
      }
      const rx = el._robotDispX;
      const ry = el._robotDispY;

      // The trail ends at the icon: the path is revealed up to its distance.
      const reveal = revealPath(path, Math.min(el._robotDispS, pathLen));

      // Heading from the icon's actual travel over a ≥2px baseline (not the
      // per-segment direction), so decimation zig-zag doesn't make it twitch.
      // Below the baseline the heading holds steady.
      if (el._robotPrevX == null) {
        el._robotPrevX = rx;
        el._robotPrevY = ry;
      } else {
        const dx = rx - el._robotPrevX;
        const dy = ry - el._robotPrevY;
        if (Math.hypot(dx, dy) >= 2) {
          const target = Math.atan2(-dy, dx); // image y flipped → world phi
          el._robotDisplayPhi =
            el._robotDisplayPhi == null ? target : lerpAngle(el._robotDisplayPhi, target, 0.2);
          el._robotPrevX = rx;
          el._robotPrevY = ry;
        }
      }
      const vs = el._viewState(attr);
      vs.attr = {
        ...attr,
        cur_path_px: reveal.path,
        robot_px: { x: rx, y: ry, phi: el._robotDisplayPhi ?? 0 },
      };
      // Pulse cue: the loop only runs while the robot is busy, so flag it and
      // hand drawRobot a looping 0..1 phase + theme colour. Phase is sampled from
      // the header status dot's rcv-ping animation so the two stay in sync.
      vs.pulse = true;
      vs.pulsePhase = el._pulsePhase(now);
      vs.pulseColor = el._pulseColor();
      // Repaint every frame while moving so the pulse keeps animating even when
      // the robot is momentarily stationary.
      const ctx = el._canvas.getContext("2d");
      el._roomCheckboxHitAreas = drawMap(ctx, el._canvas, vs);
      el._revealRaf = requestAnimationFrame(step);
    };
    el._revealRaf = requestAnimationFrame(step);
  }

export function stopReveal(el) {
    if (el._revealRaf) {
      cancelAnimationFrame(el._revealRaf);
      el._revealRaf = null;
    }
    el._robotDispX = null;
    el._robotDispY = null;
    el._robotDispS = null;
    el._robotEmaV = null;
    el._prevPushRpx = null;
    el._revealLastTs = 0;
    el._lastPathSig = null;
    el._pathArcLen = null;
    el._robotDisplayPhi = null;
    el._robotPrevX = null;
    el._robotPrevY = null;
    el._prevPathHead = null;
    // Reset pacing too: no pushes fire while docked, so a carried-over timestamp
    // makes the first push of the next clean measure a huge bogus interval (the
    // whole idle gap).
    el._lastPushTs = 0;
  }
