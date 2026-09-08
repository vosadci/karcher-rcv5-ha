// Robot-icon loading: a failed fetch must not permanently disable the marker.
//
// loadRobotIcon guards on `_robotIcon || _robotIconLoading`, so the flag it sets
// before the request is a latch: whatever clears it decides whether a later draw
// can ever try again. It had an onload but no onerror, so one failed fetch left
// the flag true forever and the robot marker never appeared again for the life of
// the card — silently, with no error surfaced and no retry.
//
// These drive the real exported function against a stubbed Image so onload and
// onerror can be fired deterministically; happy-dom will not load the asset.

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadRobotIcon } from "../../custom_components/karcher_home_robots/www/card/card-reveal.js";

let created;
let OriginalImage;

beforeEach(() => {
  created = [];
  OriginalImage = globalThis.Image;
  globalThis.Image = class {
    constructor() {
      this.onload = null;
      this.onerror = null;
      this._src = null;
      created.push(this);
    }
    set src(value) {
      this._src = value;
    }
    get src() {
      return this._src;
    }
  };
});

afterEach(() => {
  globalThis.Image = OriginalImage;
});

function fakeEl() {
  return {
    _robotIcon: null,
    _robotIconLoad: null,
    _robotIconLoading: false,
    _robotIconAttempts: 0,
    _mapLoaded: false,
    hass: null,
    _config: null,
    _drawMap: () => {},
    _vacState: () => null,
  };
}

describe("loadRobotIcon", () => {
  it("requests the icon once while a load is in flight", () => {
    const el = fakeEl();
    loadRobotIcon(el);
    loadRobotIcon(el);
    expect(created).toHaveLength(1);
    expect(el._robotIconLoading).toBe(true);
  });

  it("clears the in-flight flag on success so the guard rests on _robotIcon", () => {
    const el = fakeEl();
    loadRobotIcon(el);
    created[0].onload();
    expect(el._robotIcon).toBe(created[0]);
    expect(el._robotIconLoading).toBe(false);
    expect(el._robotIconLoad).toBeNull();
  });

  it("retries after a failed load instead of latching forever", () => {
    const el = fakeEl();
    loadRobotIcon(el);
    created[0].onerror();

    // The regression: without onerror this stayed true and every later call
    // returned at the guard, so the marker never came back.
    expect(el._robotIconLoading).toBe(false);

    loadRobotIcon(el);
    expect(created).toHaveLength(2);
    created[1].onload();
    expect(el._robotIcon).toBe(created[1]);
  });

  it("stops retrying once the attempt cap is reached", () => {
    const el = fakeEl();
    for (let i = 0; i < 6; i++) {
      loadRobotIcon(el);
      created[created.length - 1]?.onerror?.();
    }
    // Bounded: callers are draw-key changes, so an asset that is genuinely gone
    // must not issue a fetch per redraw for the life of the card.
    expect(created).toHaveLength(3);
    expect(el._robotIcon).toBeNull();
  });

  it("ignores a late callback from a superseded request", () => {
    const el = fakeEl();
    loadRobotIcon(el);
    const stale = created[0];
    el._robotIconLoad = null; // a disconnect cleared the in-flight handle

    stale.onload();

    expect(el._robotIcon).toBeNull();
  });
});
