import { computeDrawKey, drawMap, pathArcLength, revealPath, lerpAngle } from "./map-draw.js";
import { clampPan } from "./geometry.js";
import { isBusy } from "./derive.js";

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
    const mapEntity = el._config.map_entity;
    const mapState = mapEntity ? el.hass.states[mapEntity] : null;
    if (!mapState) return;

    const pic = mapState.attributes.entity_picture;
    const token = mapState.attributes.access_token || "";
    const imageTimestamp = mapState.state;

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

export function loadRobotIcon(el) {
    if (el._robotIcon || el._robotIconLoading) return;
    el._robotIconLoading = true;
    const img = new Image();
    el._robotIconLoad = img;
    img.onload = () => {
      if (el._robotIconLoad !== img) return;
      el._robotIconLoad = null;
      el._robotIcon = img;
      // Redraw if map is already shown.
      if (el._mapLoaded && el.hass && el._config) {
        const attr = el._vacState()?.attributes;
        if (attr) el._drawMap(attr);
      }
    };
    img.src = "/karcher_home_robots/static/icon.svg";
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
    if (el._lastPushTs) {
      const dt = now - el._lastPushTs;
      if (rp && el._prevPushRpx && dt > 0) {
        const d = Math.hypot(rp.x - el._prevPushRpx.x, rp.y - el._prevPushRpx.y);
        // Only learn the cruise speed while the robot is actually moving (>2px),
        // so genuine pauses/turns don't drag the average down. Long window so the
        // per-push lumpiness averages out into a stable cruise rate.
        if (d > 2) {
          const inst = d / dt; // px/ms over el push
          el._robotEmaV =
            el._robotEmaV == null ? inst : el._robotEmaV * 0.85 + inst * 0.15;
        }
      }
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
      if (el._robotDispX == null || reproj) {
        el._robotDispX = tip.x; // first sight / post-reproject: snap, no glide
        el._robotDispY = tip.y;
      }
      // Constant-velocity follower: cruise the icon at the robot's measured
      // travel speed (EMA from _onNewPath) while holding a small trailing buffer
      // behind the live tip. A bare exponential moves at speed ∝ gap, so it
      // surges on big lumps and crawls when caught up — that is the residual
      // speed variation. Here the speed is dominated by the feed-forward EMA and
      // only gently corrected toward the buffer setpoint, so the gap converges to
      // ~one push of travel and the icon cruises at an even pace.
      const dx0 = tip.x - el._robotDispX;
      const dy0 = tip.y - el._robotDispY;
      const gap = Math.hypot(dx0, dy0);
      // Feed-forward dominated: cruise at the stable long-run speed, ease to a
      // stop when caught up, and allow only a *bounded* catch-up when the robot
      // has surged ahead — never the gap-proportional surge that made earlier
      // builds pulse (that correction term ran ~3-12x the feed-forward).
      const ema = el._robotEmaV || 0;
      // buffer ≈ two pushes of travel: the routine per-push gap sawtooth (~one
      // push) stays *below* it, so during steady motion speed == ema (flat, no
      // per-push ripple). Catch-up only engages on a genuine fall-behind.
      const buffer = ema * 1600;
      const easeDist = 8; // px: glide to a stop instead of snapping on
      let speed = gap < easeDist ? ema * (gap / easeDist) : ema;
      if (gap > buffer) speed += Math.min((gap - buffer) * 0.001, ema * 0.6);
      const move = speed * dt;
      if (gap < 0.5 || move >= gap) {
        el._robotDispX = tip.x;
        el._robotDispY = tip.y;
      } else {
        el._robotDispX += (dx0 / gap) * move;
        el._robotDispY += (dy0 / gap) * move;
      }
      const rx = el._robotDispX;
      const ry = el._robotDispY;

      // Pin the trail to the follower: reveal the path up to (total − trailGap),
      // where trailGap is how far the icon now trails the tip. When the tip snaps
      // forward (int path lump), total and trailGap jump together → revealLen is
      // steady → the trail tip stays glued to the icon instead of running ahead.
      const total = el._pathArcLen ?? pathArcLength(path);
      const trailGap = Math.hypot(tip.x - rx, tip.y - ry);
      const reveal = revealPath(path, Math.max(0, total - trailGap));

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
