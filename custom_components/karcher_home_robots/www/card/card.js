import { LitElement } from "../lit-core.js";
import { deriveCompanions, isOccupied, parseRoomOrder } from "./derive.js";
import { defaultZoneRect } from "./geometry.js";
import { renderCard, renderCleanTarget } from "./card-render.js";
import {
  willUpdateCard, deriveView, edgeFades, mapPlaceholderView, batteryView, statTiles,
  selectorRows, tabHelperText, roomListRows, targetLabel, cleanTargetRooms, viewState,
  resolveFaultEntity, reconcileCustomiseView,
} from "./card-view.js";
import {
  zonePx, zoneMinPx, zoneHandleRadiusPx, zoneBounds, pinchGeometry, armPanDrag,
  onMapPointerDown, onZonePointerHover, onMapPointerMove, onMapPointerUp, resetZoom,
  triggerNudge, onWheelZoom, startZoneClean, onCanvasClick,
} from "./card-gestures.js";
import {
  pulsePhase, sizeCanvasIfNeeded, updateMap, loadRobotIcon, robotMoving, pulseColor,
  drawMapFrame, staticDraw, onNewPath, ensureRevealLoop, stopReveal,
} from "./card-reveal.js";

class KarcherVacuumCard extends LitElement {
  // hass + config are reactive: HA assigns el.hass each poll, el.setConfig once.
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    // Derived display state the template binds to (set in willUpdate).
    _view: { state: true },
  };

  // NOTE: _CSS is injected as a <style> in render() (see below), NOT via Lit's
  // `static styles`. `static styles` requires css`` CSSResults and routes through
  // adoptStyles()/adoptedStyleSheets, which threw a TypeError in HA (a plain
  // string has no .styleSheet getter). A <style> tag in the shadow root styles
  // the tree — including the light-DOM leaf children — identically, and is how
  // the card worked pre-flip.

  constructor() {
    super();
    this._config = null;
    this.hass = null;
    this._view = {}; // derived display state the template binds to (see _deriveView)
    this._selectedRooms = new Set();
    this._prevActivity = null;
    this._stopped = false;               // user pressed Stop: robot is paused, but the
                                         // cycle is over — rooms editable, primary = Start
                                         // (vs Pause, which keeps the resume-in-place lock)
    this._mapLoaded = false;
    this._mapPending = false;    // map image fetch in flight
    this._mapError = false;      // last map image fetch failed
    this._needsCanvasSize = false; // size the canvas on the next updated()
    this._mapImg = null;
    this._mapImgLoad = null;     // in-flight Image() for the map, cleared on disconnect
    this._mapToken = null;
    this._robotIcon = null;
    this._robotIconLoad = null;  // in-flight Image() for the robot icon, cleared on disconnect
    this._robotIconLoading = false;
    // Reveal-cursor animation: a single timeline drives both the path draw and
    // the robot. The robot rides the tip of the progressively-revealed path, so
    // the two can never desync, and the reveal is paced to the measured push
    // interval so motion stays continuous instead of glide-then-pause.
    this._revealRaf = null;      // requestAnimationFrame handle (runs while cleaning)
    this._revealAttr = null;     // latest attrs for the loop to draw from
    // The robot icon is a 2D exponential follower toward the backend FLOAT
    // robot_px (full sub-pixel precision). cur_path_px is int()-truncated +
    // decimated, so its arc length plateaus-then-snaps; robot_px does not. The
    // trail is pinned to the follower's position so path and robot stay synced
    // (the trail tip never runs ahead of the icon).
    this._robotDispX = null;     // drawn robot pixel x (float follower)
    this._robotDispY = null;     // drawn robot pixel y
    this._robotEmaV = null;      // EMA of robot travel speed (px/ms), cruise rate
    this._prevPushRpx = null;    // robot_px at the previous push (for speed calc)
    this._revealLastTs = 0;      // last frame timestamp (for dt)
    this._robotDisplayPhi = null;// smoothed heading actually drawn
    this._robotPrevX = null;     // last position used for heading baseline
    this._robotPrevY = null;
    this._prevPathHead = null;    // path head pixel, to detect map reprojection
    this._lastPathSig = null;    // detect a new path push
    this._lastPushTs = 0;        // timestamp of last path change (for speed dt)
    this._cardMode = "standard";         // "standard" | "customise" | "area"
    this._lastPreferMode = null;         // last robot-reported prefer_mode
    this._pendingPreferMode = null;      // backend value sent but not yet confirmed by the robot
    this._pendingCardMode = null;        // UI cardMode the pending backend value should confirm into
    this._pendingPrefRefresh = false;    // request a "fresh on look" preference refetch
    this._onVisibilityChange = null;     // bound visibilitychange handler (mount/foreground)
    this._detailRoomId = null;           // string room_id when detail is open
    this._customiseSelected = new Set(); // selected room IDs in Customise mode
    this._customisePending = new Map();  // id → expected custom (optimistic) until HA confirms
    this._roomCheckboxHitAreas = [];     // [{id, x, y, size} in image-space] rebuilt each _drawRoomLabels
    this._lastDrawKey = null;
    this._zoneRect = null;               // {x0,y0,x1,y1} in image-space px, or null
    this._zoneDrag = null;               // {mode: 'create'|'move'|'resize', ...} while dragging, else null
    this._sheetOpen = false;             // bottom sheet visibility
    this._sheetTab = "target";           // "target" | "settings"
    this._lastSettingsMode = "standard"; // restored when leaving Zone back to Rooms
    this._zoom = 1;                      // map zoom level, 1 = fit-to-frame
    this._pan = { x: 0, y: 0 };           // map pan offset in CSS px, {0,0} at zoom=1
    this._activePointers = new Map();    // pointerId → {x,y} CSS px, tracked regardless of zoneMode
    this._pinch = null;                  // {mid, dist, zoom, pan} snapshot at gesture start, while 2+ pointers are down
    this._panDrag = null;                // {pointerId, start:{x,y}, pan} snapshot for a one-finger pan while zoomed
    this._gestured = false;              // a pinch/pan happened this touch sequence — swallow the trailing click
    this._hasNudged = false;             // the one-shot "map is pannable" nudge fired this zoom-in session
    this._nudgePending = false;          // zoom crossed 1 mid-pinch; nudge once the fingers lift
    this._nudgeRaf = null;               // requestAnimationFrame handle for the nudge animation
  }

  // HA calls setConfig imperatively; store config (a reactive property).
  setConfig(config) {
    if (!config.vacuum_entity) throw new Error("vacuum_entity is required");
    this._config = { ...deriveCompanions(config.vacuum_entity), ...config };
  }

  getCardSize() { return 6; }

  static getConfigElement() {
    return document.createElement("karcher-vacuum-card-editor");
  }

  static getStubConfig() {
    return { vacuum_entity: "vacuum.karcher_rcv5" };
  }

  connectedCallback() {
    super.connectedCallback();
    // "Fresh on look": pull the latest per-room preferences when the card mounts
    // (dashboard opened) and when the tab is re-foregrounded — the closest analog
    // to the Kärcher app's on-screen refetch. The coordinator throttles repeats.
    this._pendingPrefRefresh = true;
    if (!this._onVisibilityChange) {
      this._onVisibilityChange = () => {
        if (document.visibilityState === "visible") {
          this._pendingPrefRefresh = true;
          this.requestUpdate();
        }
      };
    }
    document.addEventListener("visibilitychange", this._onVisibilityChange);
    this.requestUpdate();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._onVisibilityChange) {
      document.removeEventListener("visibilitychange", this._onVisibilityChange);
    }
    if (this._mapImgLoad) {
      this._mapImgLoad.onload = null;
      this._mapImgLoad.onerror = null;
      this._mapImgLoad = null;
    }
    if (this._robotIconLoad) {
      this._robotIconLoad.onload = null;
      this._robotIconLoad = null;
    }
    this._stopReveal();
    if (this._nudgeRaf) {
      cancelAnimationFrame(this._nudgeRaf);
      this._nudgeRaf = null;
    }
    if (this._mapResizeObserver) {
      this._mapResizeObserver.disconnect();
      this._mapResizeObserver = null;
    }
  }

  // ── render (declarative; was _buildDOM) ──────────────────────────────────────

  render() { return renderCard(this); }

  // Sheet tab 1 "What gets cleaned": room chips (Rooms) or a one-line area
  // summary (Zone). Chips toggle the same selection set the map writes to, via
  // the existing _onRoomToggle path (one source of truth). The banner always
  // shows v.targetLabel — the same selection summary as the target strip below
  // the map — so it reflects the selection and never collapses (no content jump).
  _renderCleanTarget(v, mapMode) { return renderCleanTarget(this, v, mapMode); }

  firstUpdated() {
    // Grab the persistent canvas (a static literal → reused across re-renders;
    // node-identity spike confirmed the bitmap survives). The click is bound in
    // the template via @click; the ref is kept for sizing + draw.
    this._canvas = this.renderRoot.querySelector("canvas");
    // The canvas backing-buffer is sized once per image load. Its CSS width
    // changes responsively (two-column breakpoint, window resize, sidebar
    // collapse), so re-fit when the laid-out width changes — otherwise the
    // buffer goes stale and the map renders blurry/distorted.
    const mapContainer = this.renderRoot.querySelector(".map-container");
    if (mapContainer && "ResizeObserver" in window) {
      this._lastMapWidth = mapContainer.getBoundingClientRect().width;
      this._mapResizeObserver = new ResizeObserver((entries) => {
        const w = entries[0]?.contentRect?.width;
        if (!w || w === this._lastMapWidth) return;
        this._lastMapWidth = w;
        this._needsCanvasSize = true;
        this.requestUpdate();
      });
      this._mapResizeObserver.observe(mapContainer);
    }
  }

  // ── update cycle (derive _view from hass; was _updateCard) ────────────────────

  willUpdate() { return willUpdateCard(this); }

  updated() {
    // Map draw is a side effect — runs here, never in render(). _lastDrawKey
    // early-returns on updates that don't change the overlay.
    if (!this.hass || !this._config) return;
    // Size the canvas now that the re-render has made it visible (display:block).
    this._sizeCanvasIfNeeded();
    const attr = this._vacState()?.attributes;
    if (attr) this._updateMap(attr);
  }

  // 0..1 phase for the map icon's canvas pulse, synced to the header status-dot's
  // CSS `rcv-ping` animation by sampling that animation's own clock: its
  // `currentTime` (linear ms, accumulating) mod the 1600ms period. This makes the
  // canvas a slave to the exact animation the header renders, so they can't drift —
  // no cross-engine clock-origin assumptions and no writing `startTime` (which iOS
  // WebKit may not honor on a CSS-declared animation). `currentTime` is CSSNumberish
  // (a plain number today, a CSSNumericValue in some runtimes), so read `.value`
  // when it isn't a number. Falls back to the performance clock when the animation
  // is absent (reduced-motion, or the dot isn't pinging — no header pulse to match).
  _pulsePhase(now) { return pulsePhase(this, now); }

  // One-time canvas sizing after the map first becomes visible. Measured here
  // (in updated(), post-render) so getBoundingClientRect reflects the laid-out,
  // display:block canvas — never the display:none state during onload.
  _sizeCanvasIfNeeded() { return sizeCanvasIfNeeded(this); }

  _deriveView(attr, activity) { return deriveView(this, attr, activity); }

  // Per-edge scrim opacity (0..1) for the four directional "map continues this
  // way" overlays: the off-screen overhang past each edge, ramped to full over
  // EDGE_FADE_RAMP_PX. All zero at fit zoom or before the canvas is sized.
  _edgeFades() { return edgeFades(this); }

  // The map-interaction axis derived from the tri-state cardMode: "zone" ⟺ Area,
  // "rooms" otherwise. Single source for render(), _targetLabel, and primaryLabel.
  _mapMode() {
    return this._cardMode === "area" ? "zone" : "rooms";
  }

  // Area-draw mode is not separate state — it is exactly "the Area tab is
  // active". Derived so it can never drift from _cardMode.
  get _zoneMode() {
    return this._cardMode === "area";
  }

  // Selection set the map/chips/strip all read: customise → the per-room custom
  // set, otherwise the transient standard set.
  _activeSelection() {
    return this._cardMode === "customise" ? this._customiseSelected : this._selectedRooms;
  }

  // One-line target-strip summary (rooms names / "Whole home" / area copy).
  _targetLabel(attr) { return targetLabel(this, attr); }

  // Room-chip descriptors for the sheet's "What gets cleaned" tab: the derived
  // room rows (selection-aware) augmented with the room area for the chip.
  _cleanTargetRooms(attr) { return cleanTargetRooms(this, attr); }

  // The vacuum entity's state object — the single lookup every other accessor
  // below builds on (state, attributes, map_image_size all flow through here).
  _vacState() {
    return this.hass?.states[this._config?.vacuum_entity];
  }

  _imgSize() {
    return this._vacState()?.attributes?.map_image_size;
  }

  // Robot unreachable: entity unavailable, or the connectivity sensor is off.
  _isOffline() {
    const activity = this._vacState()?.state;
    const conn = this._config?.connectivity_entity;
    return activity === "unavailable" || !!(conn && this.hass.states[conn]?.state === "off");
  }

  // True when the card should present resting controls (room selection editable,
  // primary button = a fresh "Start"): the robot is genuinely resting, OR the
  // user pressed Stop and it has settled into the paused state that produced —
  // a finished cycle the card lets them re-target into a new clean.
  _restingForUx(activity) {
    return !isOccupied(activity) || (this._stopped && activity === "paused");
  }

  // Config + selection (mode tabs, settings, room list, map selection, area
  // drawing) lock whenever a job is in progress — cleaning, paused OR returning
  // (editing then would re-target the in-flight clean; Resume re-dispatches the
  // selection) — or the robot is offline (the service call can't reach it). A
  // user-initiated Stop unlocks the paused state so new rooms can be picked.
  _controlsLocked(activity) {
    return this._isOffline() || !this._restingForUx(activity);
  }

  // ── Standard / Customise mode ─────────────────────────────────────────────────

  // State-only mode switch. `mode` is "standard" | "customise" | "area" here.
  // Area rides on the robot's Standard preference (no prefer_mode value of
  // its own), so it shares Standard's branch below. Does NOT requestUpdate:
  // when called from willUpdate (prefer_mode change) the in-progress cycle
  // already re-derives _view; when called from _setCardMode (user tab) that
  // handler requests the update.
  _applyMode(mode) {
    this._cardMode = mode;
    // Remember the settings-axis value so leaving Zone (Area) via the map control
    // restores Standard/Customise rather than always snapping to Standard.
    if (mode === "standard" || mode === "customise") this._lastSettingsMode = mode;
    if (mode === "standard" || mode === "area") {
      this._detailRoomId = null;
      this._customiseSelected.clear();
    }
    if (mode === "area") {
      // Area draws its own selection; a room pick carried over from Standard
      // must not still show as selected on the map or feed the Start fallback.
      this._selectedRooms.clear();
      // Start with a centered default selection rather than an empty map —
      // the user adjusts it instead of having to draw from scratch. Only
      // seed when there's no rect yet: _applyMode("area") re-runs when the
      // backend echoes prefer_mode after the optimistic switch, and that
      // re-application must not clobber an edit made in the meantime.
      if (!this._zoneRect) {
        const imgSize = this._imgSize();
        this._zoneRect = defaultZoneRect(imgSize);
        this._lastDrawKey = null;
      }
    } else if (this._zoneRect) {
      // Only the Area tab draws — leaving it for Standard or Customise drops
      // the selection so it can't leak into another tab.
      this._zoneRect = null;
      this._lastDrawKey = null;
      if (this._canvas) this._canvas.style.cursor = "";
    }
  }

  _setCardMode(mode) {
    if (!this.hass || !this._config) return;
    const activity = this._vacState()?.state;
    if (this._controlsLocked(activity)) return;
    // Area has no robot-side preference of its own — it rides on Standard's
    // prefer_type 0. The robot will echo back prefer_mode="standard", but not
    // immediately: mark it pending so willUpdate ignores every poll (stale
    // pre-click values included) until that exact echo arrives — otherwise a
    // poll still carrying the old value (e.g. "customise") can land first and
    // knock the optimistic tab back before the real echo ever shows up.
    const backendMode = mode === "area" ? "standard" : mode;
    this.hass.callService("vacuum", "send_command", {
      entity_id: this._config.vacuum_entity,
      command: "set_preference_type",
      params: { prefer_type: backendMode === "customise" ? 1 : 0 },
    });
    this._pendingPreferMode = backendMode;
    this._pendingCardMode = mode;
    this._applyMode(mode);
    this.requestUpdate(); // user tab switch outside an update cycle → re-render
  }

  // Resolve the fault_code sensor's live entity_id. The derived/configured
  // cfg.fault_code_entity (sensor.<stem>_robot_status) is correct for installs
  // created after this entity's name changed from "Fault code" to "Robot
  // status" — but HA assigns entity_id once at first registration and never
  // renames it, so older installs kept sensor.<stem>_fault_code. If the derived
  // guess doesn't resolve to a real entity, fall back to a registry scan by
  // device_id + translation_key (mirrors vacuum.py's _pref_entity_map); if that
  // also finds nothing, fall back to the guess itself (status quo, no regression).
  _resolveFaultEntity() { return resolveFaultEntity(this); }

  // Ask the integration to refetch room preferences now (bypasses the 5-min poll;
  // coordinator throttles to ~5 s). Passes device_id when known so multi-robot
  // setups route correctly. Used by the mount/foreground "fresh on look" trigger.
  _refreshPreferences() {
    const hass = this.hass;
    const vac = this._config?.vacuum_entity;
    if (!hass || !vac) return;
    // After the iOS app is backgrounded and re-foregrounded the WebSocket is
    // briefly reconnecting; calling a service then rejects with "connection
    // lost" and HA surfaces its own action_failed toast (we can't suppress it
    // from here). Skip while disconnected and re-arm so the next hass update —
    // which fires once the socket is back — retries the best-effort refresh.
    if (hass.connection?.connected === false) {
      this._pendingPrefRefresh = true;
      return;
    }
    const deviceId = hass.entities?.[vac]?.device_id;
    hass.callService(
      "karcher_home_robots",
      "refresh_preferences",
      deviceId ? { device_id: deviceId } : {},
    );
  }

  // Reconcile the optimistic enabled-set once per render cycle (called from
  // willUpdate). Single source of truth — the map reads _customiseSelected too.
  _reconcileCustomise(attr) { return reconcileCustomiseView(this, attr); }

  _tabHelperText(attr) { return tabHelperText(this, attr); }

  _roomListRows(attr) { return roomListRows(this, attr); }

  _onRoomToggle(e) {
    const { roomId, on } = e.detail || {};
    if (this._cardMode !== "customise") {
      if (on) this._selectedRooms.add(roomId);
      else this._selectedRooms.delete(roomId);
      this.requestUpdate(); // re-derive view (leaf rows + header) and redraw map overlay
      return;
    }
    if (on) this._customiseSelected.add(roomId);
    else this._customiseSelected.delete(roomId);
    this._customisePending.set(roomId, on);
    this._toggleRoomCustom(roomId, on);
    this.requestUpdate(); // re-derive view (leaf rows + header) and redraw map overlay
  }

  _onRoomExpand(e) {
    const { roomId } = e.detail || {};
    this._detailRoomId = this._detailRoomId === roomId ? null : roomId;
    this.requestUpdate();
  }

  _onRoomReorder(e) {
    const order = e.detail?.order || [];
    const vacuumEntry = this.hass.entities?.[this._config.vacuum_entity];
    const serviceData = { room_order: order.map((rid) => parseInt(rid, 10)) };
    // device_id disambiguates when the account has more than one robot.
    if (vacuumEntry?.device_id) serviceData.device_id = vacuumEntry.device_id;
    this.hass.callService("karcher_home_robots", "set_room_preference", serviceData);
  }

  _onRoomPref(e) {
    const { roomId, field, value } = e.detail || {};
    this._setRoomPref(roomId, field, value);
  }

  // Read entity_ids from vacuum.room_preferences[roomId].entities (built by vacuum.py).
  _roomEntities(roomId) {
    const attr = this._vacState()?.attributes;
    return attr?.room_preferences?.[roomId]?.entities || {};
  }

  _setRoomPref(roomId, field, value) {
    const entityId = this._roomEntities(roomId)[field];
    if (!entityId) { console.warn(`Kärcher card: no entity for ${field} room ${roomId}`); return; }
    this.hass.callService("select", "select_option", { entity_id: entityId, option: value });
  }

  _toggleRoomCustom(roomId, on) {
    const entityId = this._roomEntities(roomId)["custom"];
    if (!entityId) { console.warn(`Kärcher card: no custom switch for room ${roomId}`); return; }
    this.hass.callService("switch", on ? "turn_on" : "turn_off", { entity_id: entityId });
  }

  // ── map ───────────────────────────────────────────────────────────────────────

  // Placeholder text + aspect-ratio + loading flag as view fields. Pure read of
  // hass/config + the _map* side-effect flags (which _updateMap maintains).
  _mapPlaceholderView(attr) { return mapPlaceholderView(this, attr); }

  // Side effect only (runs from updated()): fetch the map image, size the canvas,
  // and draw. Display/placeholder state flows through _view via _mapPlaceholderView;
  // this method flips the _map* flags and requestUpdate()s when they change.
  _updateMap(attr) { return updateMap(this, attr); }

  _loadRobotIcon() { return loadRobotIcon(this); }

  // Assemble the plain viewState the module renderer consumes: everything
  // hass-derived is pre-resolved here so the renderer never reads hass/config.
  _viewState(attr) { return viewState(this, attr); }

  // True while the robot is busy and the pulse cue should run: cleaning,
  // returning, or relocalizing ("Locating"). Cleaning/returning also glide the
  // icon along the path; locating has no live pose so the icon holds still but
  // still pulses (a "working" cue), matching the header status dot.
  _robotMoving() { return robotMoving(this); }

  // Pulse colour resolved from the active theme to match the header status dot:
  // green (--success-color) for cleaning, accent (--primary-color) for
  // returning/locating (the header renders "Locating" with the returning dot).
  _pulseColor() { return pulseColor(this); }

  _drawMap(attr) { return drawMapFrame(this, attr); }

  // Plain key-checked static draw (the pre-animation behaviour).
  _staticDraw(attr) { return staticDraw(this, attr); }

  // A new path push arrived: measure the robot's real travel speed (distance the
  // float robot_px moved / time since the last push) and EMA it. The RAF loop
  // cruises the icon at this speed, so the glide is even regardless of how lumpy
  // each individual push is.
  _onNewPath(path, sig) { return onNewPath(this, path, sig); }

  _ensureRevealLoop() { return ensureRevealLoop(this); }

  _stopReveal() { return stopReveal(this); }

  _zonePx(e) { return zonePx(this, e); }

  _zoneMinPx() { return zoneMinPx(this); }

  // Corner-handle hit radius, in image px. ZONE_HANDLE_RADIUS_PX is a fixed
  // screen-px tolerance — divide by the canvas scale (and the current zoom,
  // since zooming in shrinks the image-px-per-screen-px ratio further) so
  // handles stay equally grabbable regardless of scale or zoom level.
  _zoneHandleRadiusPx() { return zoneHandleRadiusPx(this); }

  _zoneBounds() { return zoneBounds(this); }

  // Midpoint + inter-finger distance (CSS px, canvas-relative) of the tracked
  // pointers — the shared geometry a 2+-finger touch gesture pinches/pans from.
  _pinchGeometry() { return pinchGeometry(this); }

  // Arm a one-finger drag-to-pan from this press. Only meaningful once zoomed
  // in — at fit zoom there is nothing to pan to, and vertical swipes should
  // keep scrolling the page (touch-action: pan-y). The actual pan starts in
  // pointermove once the pointer travels past TAP_SLOP_PX, so a plain tap
  // still falls through to the click handler (room select).
  _armPanDrag(e) { return armPanDrag(this, e); }

  _onMapPointerDown(e) { return onMapPointerDown(this, e); }

  // Cursor feedback while hovering an existing zone without dragging:
  // resize cursor over a corner handle, move cursor over the body.
  _onZonePointerHover(e) { return onZonePointerHover(this, e); }

  _onMapPointerMove(e) { return onMapPointerMove(this, e); }

  _onMapPointerUp(e) { return onMapPointerUp(this, e); }

  // Back to fit-to-frame. Also drops any in-flight pan/pinch/nudge gesture so a
  // finger still resting on the map can't reapply the stale snapshot, and re-arms
  // the pannability nudge for the next fresh zoom-in.
  _resetZoom() { return resetZoom(this); }

  // One-shot discoverability cue: the first time the map is zoomed past fit, ease
  // the pan a short distance toward whichever side hides the most map and back,
  // telegraphing that the map is draggable. The edge scrims already show WHERE
  // content is hidden; this shows THAT it moves. Skipped under reduced-motion (the
  // scrims remain), and bailed if the user grabs the map or resets mid-animation.
  _triggerNudge() { return triggerNudge(this); }

  // Desktop zoom + pan. Ctrl+wheel (also how browsers report trackpad pinch)
  // zooms toward the cursor so the point under the pointer stays put as the
  // map scales. Plain wheel (trackpad two-finger scroll) pans — but only once
  // zoomed in; at fit zoom it's left alone so scrolling the dashboard past
  // the map still works. Only preventDefault when we consume the gesture.
  _onWheelZoom(e) { return onWheelZoom(this, e); }

  _startZoneClean() { return startZoneClean(this); }

  _onCanvasClick(e) { return onCanvasClick(this, e); }

  // ── map-mode control · bottom sheet ─────────────────────────────────────────

  // Floating Rooms|Zone control. Maps onto the unchanged tri-state cardMode:
  // Zone ⟺ Area, Rooms ⟺ the last Standard/Customise settings value.
  _onMapMode(e) {
    const mode = e.detail?.mode;
    if (mode === "zone") {
      if (this._cardMode !== "area") this._setCardMode("area");
    } else if (this._cardMode === "area") {
      this._setCardMode(this._lastSettingsMode || "standard");
    }
  }

  _openSheet() {
    if (this._sheetOpen) return;
    this._sheetOpen = true;
    this.requestUpdate();
  }

  _closeSheet() {
    if (!this._sheetOpen) return;
    this._sheetOpen = false;
    this.requestUpdate();
  }

  _setSheetTab(tab) {
    if (this._sheetTab === tab) return;
    this._sheetTab = tab;
    this.requestUpdate();
  }

  // Battery header glyph as view fields (was imperative writes in _updateStats).
  _batteryView() { return batteryView(this); }

  _statTiles() { return statTiles(this); }

  _selectorRows(attr) { return selectorRows(this, attr); }

  _onSelectorChange(e) {
    const { control, value } = e.detail || {};
    if (control === "mode") {
      this.hass.callService("select", "select_option",
        { entity_id: this._config.cleaning_mode_entity, option: value });
    } else if (control === "suction") {
      this.hass.callService("vacuum", "set_fan_speed",
        { entity_id: this._config.vacuum_entity, fan_speed: value });
    } else if (control === "water") {
      this.hass.callService("select", "select_option",
        { entity_id: this._config.water_level_entity, option: value });
    }
  }

  _onButtonAction(e) {
    // Actions up: route the leaf's bubbling event to the existing handlers.
    const action = e.detail?.action;
    if (action === "play") this._play();
    else if (action === "pause") this._pause();
    else if (action === "stop") this._stop();
    else if (action === "dock") this._dock();
  }

  // ── actions ───────────────────────────────────────────────────────────────────

  _play() {
    const vacuumEntity = this._config.vacuum_entity;
    const paused = this.hass.states[vacuumEntity]?.state === "paused";
    // A pure Pause→Resume must never re-dispatch the current selection as a fresh
    // clean (set_room_clean with non-empty room_ids restarts those rooms rather
    // than continuing — doc/PROTOCOL.md §5 documents only room_ids:[] as the
    // resume signal). Controls are locked while paused, so the selection can't
    // have changed since the clean started — vacuum.start's own paused-state
    // handling (async_start) is always the right call here. Stop also leaves the
    // robot paused, but there the intent is to abandon the cycle and start fresh,
    // so _stopped suppresses the resume short-circuit and falls through below.
    if (paused && !this._stopped) {
      this.hass.callService("vacuum", "start", { entity_id: vacuumEntity });
      return;
    }
    // Past the resume guard the button always dispatches a fresh clean; the Stop
    // intent is now consumed.
    const fromStop = this._stopped;
    this._stopped = false;
    // A drawn area takes precedence over room selection and whole-home. The
    // redirect lives here in the card; vacuum.start stays whole-home for
    // external callers (Apple Home/HAMH dispatch a parameterless vacuum.start).
    if (this._zoneRect) {
      this._startZoneClean();
      return;
    }
    let roomIds = [...this._selectedRooms].map((id) => parseInt(id, 10));
    // Whole-home after Stop can't be a bare vacuum.start: the robot is still
    // paused, where room_ids:[] resumes the abandoned clean rather than starting
    // a fresh whole-home. Expand to every known room so it dispatches as an
    // explicit fresh clean instead.
    if (roomIds.length === 0 && fromStop && paused) {
      const roomMap = this.hass.states[vacuumEntity]?.attributes?.room_map || {};
      roomIds = Object.keys(roomMap).map((id) => parseInt(id, 10));
    }
    if (roomIds.length === 0) {
      // No selection → whole-home clean via the standard service.
      this.hass.callService("vacuum", "start", { entity_id: vacuumEntity });
      return;
    }
    // Start the selected rooms with explicit ids. app_segment_clean preserves
    // caller order, so sort into preference order here (previously the
    // coordinator reordered the selection in default_clean_room_ids()).
    //
    // Deliberately NOT set_room_selection + vacuum.start: vacuum.start must
    // stay whole-home for external callers. HAMH dispatches Apple Home's
    // "clean all rooms" as a parameterless vacuum.start, and a selection
    // pushed from here used to persist on the coordinator and turn that
    // into a single-room clean.
    const prefs = this.hass.states[vacuumEntity]?.attributes?.room_preferences || {};
    const selectedRoomMap = Object.fromEntries(roomIds.map((id) => [String(id), {}]));
    const ordered = parseRoomOrder(selectedRoomMap, prefs).map((id) => parseInt(id, 10));
    this.hass.callService("vacuum", "send_command", {
      entity_id: vacuumEntity,
      command: "app_segment_clean",
      params: ordered,
    });
  }

  _pause() {
    // Pause in place — the cycle is resumable, so clear any prior Stop intent.
    this._stopped = false;
    this.hass.callService("vacuum", "pause", { entity_id: this._config.vacuum_entity });
  }

  _stop() {
    // The device has no true stop-in-place: vacuum.stop pauses the robot. Remember
    // the Stop intent so the card treats the resulting paused state as a finished
    // cycle (rooms editable, primary = Start) instead of a resumable pause.
    this._stopped = true;
    this.hass.callService("vacuum", "stop", { entity_id: this._config.vacuum_entity });
  }

  _dock() {
    this.hass.callService("vacuum", "return_to_base", { entity_id: this._config.vacuum_entity });
  }

}

if (!customElements.get("karcher-vacuum-card")) {
  customElements.define("karcher-vacuum-card", KarcherVacuumCard);
}
