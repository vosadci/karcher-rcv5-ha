// Robot-follower pacing math, extracted from the reveal rAF loop.
//
// The loop itself is timing-dependent and stays in-HA-verified; this pins the
// arithmetic it runs. These constants were tuned against real hardware (the M1
// glide work), so the tests below are a REGRESSION FENCE around the shipped
// feel, not a specification anyone should retune to. If a change here fails,
// the question is whether the change was intended — not whether to relax the
// test.

import { describe, it, expect } from "vitest";
import {
  followLine,
  followerAdvance,
  followerShouldSnap,
  followerSpeed,
  updateCruiseSpeed,
} from "../../custom_components/karcher_home_robots/www/card/card-reveal.js";

const EMA = 0.05; // px/ms — a plausible cruise rate
const BUFFER = EMA * 1600; // 80px: the trailing setpoint

describe("followerSpeed", () => {
  it("cruises at the measured speed in the steady band", () => {
    // Between the ease distance and the buffer the icon runs flat at `ema` —
    // this is what stops the per-push gap sawtooth becoming visible ripple.
    for (const gap of [8, 20, 50, BUFFER]) {
      expect(followerSpeed(gap, EMA)).toBeCloseTo(EMA, 10);
    }
  });

  it("eases linearly to a stop as it catches up", () => {
    expect(followerSpeed(0, EMA)).toBe(0);
    expect(followerSpeed(4, EMA)).toBeCloseTo(EMA * 0.5, 10);
    expect(followerSpeed(7.9, EMA)).toBeLessThan(EMA);
  });

  it("adds only a bounded catch-up once the gap exceeds the buffer", () => {
    const slight = followerSpeed(BUFFER + 100, EMA);
    expect(slight).toBeGreaterThan(EMA);
    // Capped at 60% over cruise however far behind it falls — an unbounded,
    // gap-proportional correction is what made earlier builds pulse.
    const huge = followerSpeed(BUFFER + 1e6, EMA);
    expect(huge).toBeCloseTo(EMA * 1.6, 10);
    expect(followerSpeed(BUFFER + 1e9, EMA)).toBeCloseTo(EMA * 1.6, 10);
  });

  it("never moves before a cruise speed has been learned", () => {
    // Documented current behaviour, not an endorsement: with no EMA yet the icon
    // holds at its snapped position instead of guessing a speed. In practice the
    // EMA lands within about two path pushes of a clean starting. Recorded here
    // so a future change to it is a deliberate decision with a device to check.
    expect(followerSpeed(0, 0)).toBe(0);
    expect(followerSpeed(500, 0)).toBe(0);
  });

  it("is monotonic in gap", () => {
    let prev = -Infinity;
    for (let gap = 0; gap < 400; gap += 3) {
      const s = followerSpeed(gap, EMA);
      expect(s).toBeGreaterThanOrEqual(prev - 1e-12);
      prev = s;
    }
  });
});

describe("updateCruiseSpeed", () => {
  it("seeds from the first qualifying push", () => {
    expect(updateCruiseSpeed(null, 10, 100)).toBeCloseTo(0.1, 10);
  });

  it("blends later pushes on a long window", () => {
    expect(updateCruiseSpeed(0.1, 20, 100)).toBeCloseTo(0.1 * 0.85 + 0.2 * 0.15, 10);
  });

  it("ignores sub-threshold movement so pauses and turns do not drag it down", () => {
    expect(updateCruiseSpeed(0.1, 2, 100)).toBe(0.1);
    expect(updateCruiseSpeed(0.1, 0, 100)).toBe(0.1);
    expect(updateCruiseSpeed(null, 1, 100)).toBeNull();
  });

  it("ignores a non-positive interval", () => {
    // Two pushes in the same millisecond, or a clock that went backwards, would
    // otherwise divide by zero and poison the average with Infinity.
    expect(updateCruiseSpeed(0.1, 50, 0)).toBe(0.1);
    expect(updateCruiseSpeed(0.1, 50, -5)).toBe(0.1);
  });

  it("converges toward a changed cruise rate rather than jumping", () => {
    let v = updateCruiseSpeed(null, 10, 100); // 0.1
    for (let i = 0; i < 40; i++) v = updateCruiseSpeed(v, 20, 100); // toward 0.2
    expect(v).toBeGreaterThan(0.19);
    expect(v).toBeLessThan(0.2);
  });
});

describe("followerShouldSnap", () => {
  it("glides through the routine catch-up band", () => {
    expect(followerShouldSnap(BUFFER * 2, EMA)).toBe(false);
    expect(followerShouldSnap(EMA * 5000, EMA)).toBe(false);
  });

  it("snaps once the tip is more than five seconds of travel ahead", () => {
    expect(followerShouldSnap(EMA * 5000 + 1, EMA)).toBe(true);
  });

  it("never snaps a short gap on a slow robot", () => {
    expect(followerShouldSnap(60, 0.001)).toBe(false);
    expect(followerShouldSnap(61, 0.001)).toBe(true);
  });

  it("snaps past the floor while the speed is still unknown", () => {
    for (const ema of [null, undefined, 0]) {
      expect(followerShouldSnap(60, ema)).toBe(false);
      expect(followerShouldSnap(61, ema)).toBe(true);
    }
  });
});

describe("followLine", () => {
  const path = [0, 0, 10, 0, 10, 10]; // an L-shaped route around a corner

  it("follows the drawn path when the robot is at its end", () => {
    expect(followLine(path, { x: 10, y: 10 })).toBe(path);
    expect(followLine(path, { x: 11, y: 10 })).toBe(path); // within 2px
  });

  it("adds a straight last leg only to a robot off the path's end", () => {
    expect(followLine(path, { x: 20, y: 10 })).toEqual([0, 0, 10, 0, 10, 10, 20, 10]);
  });

  it("goes straight to the robot when there is no path yet", () => {
    expect(followLine([], { x: 5, y: 6 })).toEqual([5, 6]);
    expect(followLine([1, 1], { x: 5, y: 6 })).toEqual([1, 1, 5, 6]);
  });
});

describe("followerAdvance", () => {
  it("moves along the line at the follower speed", () => {
    expect(followerAdvance(0, BUFFER, EMA, 100)).toBeCloseTo(EMA * 100, 10);
  });

  it("never overshoots the end", () => {
    expect(followerAdvance(99.9, 100, EMA, 100)).toBe(100);
    expect(followerAdvance(120, 100, EMA, 16)).toBe(100);
  });

  it("jumps to the end when it trails by more than the snap distance", () => {
    expect(followerAdvance(0, EMA * 5000 + 1, EMA, 16)).toBe(EMA * 5000 + 1);
  });

  it("holds still until the cruise speed is known, short of the snap floor", () => {
    expect(followerAdvance(0, 50, null, 16)).toBe(0);
  });
});
