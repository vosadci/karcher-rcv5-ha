// Render tests for the first Lit leaf (KarcherButtonRow). This file also
// validates the migration harness end-to-end: that the vendored ./lit-core.js
// bundle defines a working LitElement and that it renders real DOM under
// happy-dom. The leaf is light-DOM, so we assert on querySelector (its rendered
// nodes live directly under the element), not shadowRoot.
//
// What this DOES cover: which buttons render, their labels, disabled state, and
// that clicks emit the right `karcher-action`. What it does NOT cover: visual
// styling (the shell's CSS) — that stays in-HA-verified.

import { describe, it, expect, beforeAll } from "vitest";

// Importing the card registers <karcher-button-row> as a side effect.
beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

async function mountRow(activity, opts = {}) {
  const {
    offline = false,
    playDisabled = false,
    showEmptyStation = false,
    emptyStationEnabled = false,
  } = opts;
  const el = document.createElement("karcher-button-row");
  el.activity = activity;
  el.offline = offline;
  el.playDisabled = playDisabled;
  el.showEmptyStation = showEmptyStation;
  el.emptyStationEnabled = emptyStationEnabled;
  document.body.appendChild(el);
  await el.updateComplete; // wait for Lit's first render
  return el;
}

function labels(el) {
  return [...el.querySelectorAll(".btn-label")].map((n) => n.textContent);
}

describe("KarcherButtonRow (Lit leaf, harness validation)", () => {
  it("the custom element is defined from the vendored Lit bundle", () => {
    expect(customElements.get("karcher-button-row")).toBeTruthy();
  });

  it("renders three buttons into light DOM when no station is configured", async () => {
    const el = await mountRow("docked");
    expect(el.shadowRoot).toBeNull(); // light DOM, no private shadow root
    expect(el.querySelectorAll("button.btn-wrap")).toHaveLength(3);
  });

  it("docked → Start / Stop / Dock labels (no Empty button, no station)", async () => {
    const el = await mountRow("docked");
    expect(labels(el)).toEqual(["Start", "Stop", "Dock"]);
  });

  it("renders four buttons when showEmptyStation is true", async () => {
    const el = await mountRow("docked", { showEmptyStation: true });
    expect(el.querySelectorAll("button.btn-wrap")).toHaveLength(4);
  });

  it("docked with a station → Start / Stop / Empty / Dock labels", async () => {
    const el = await mountRow("docked", { showEmptyStation: true });
    expect(labels(el)).toEqual(["Start", "Stop", "Empty", "Dock"]);
  });

  it("cleaning → Pause label, and Stop/Dock become enabled", async () => {
    const el = await mountRow("cleaning");
    expect(labels(el)).toEqual(["Pause", "Stop", "Dock"]);
    const [, stop, dock] = el.querySelectorAll("button.btn-wrap");
    expect(stop.disabled).toBe(false);
    expect(dock.disabled).toBe(false);
  });

  it("paused → Resume label", async () => {
    const el = await mountRow("paused");
    expect(labels(el)[0]).toBe("Resume");
  });

  it("unavailable (offline) → all buttons disabled", async () => {
    const el = await mountRow("unavailable", { showEmptyStation: true, emptyStationEnabled: true });
    const btns = [...el.querySelectorAll("button.btn-wrap")];
    expect(btns.every((b) => b.disabled)).toBe(true);
  });

  it("offline=true disables every button even with an actionable activity", async () => {
    // Connectivity-only outage: activity is still "cleaning" from cache.
    const el = await mountRow("cleaning", {
      offline: true, showEmptyStation: true, emptyStationEnabled: true,
    });
    const btns = [...el.querySelectorAll("button.btn-wrap")];
    expect(btns.every((b) => b.disabled)).toBe(true);
  });

  it("docked: Stop and Dock are disabled (no clean to stop, already docked)", async () => {
    const el = await mountRow("docked");
    const [, stop, dock] = el.querySelectorAll("button.btn-wrap");
    expect(stop.disabled).toBe(true);
    expect(dock.disabled).toBe(true);
  });

  it("clicking play on a docked robot emits action 'play'", async () => {
    const el = await mountRow("docked");
    let got = null;
    el.addEventListener("karcher-action", (e) => { got = e.detail.action; });
    el.querySelector("button.btn-wrap").click(); // first button = play/start
    expect(got).toBe("play");
  });

  it("clicking play while cleaning emits action 'pause'", async () => {
    const el = await mountRow("cleaning");
    let got = null;
    el.addEventListener("karcher-action", (e) => { got = e.detail.action; });
    el.querySelector("button.btn-wrap").click();
    expect(got).toBe("pause");
  });

  it("clicking a disabled button emits nothing", async () => {
    const el = await mountRow("docked"); // Stop is disabled here
    let got = null;
    el.addEventListener("karcher-action", (e) => { got = e.detail.action; });
    const [, stop] = el.querySelectorAll("button.btn-wrap");
    stop.click();
    expect(got).toBeNull();
  });

  it("playDisabled disables only Start, not Stop/Dock", async () => {
    const el = await mountRow("cleaning", { playDisabled: true });
    const [play, stop, dock] = el.querySelectorAll("button.btn-wrap");
    expect(play.disabled).toBe(true);
    expect(stop.disabled).toBe(false);
    expect(dock.disabled).toBe(false);
  });

  it("clicking a playDisabled Start button emits nothing", async () => {
    const el = await mountRow("docked", { playDisabled: true });
    let got = null;
    el.addEventListener("karcher-action", (e) => { got = e.detail.action; });
    el.querySelector("button.btn-wrap").click();
    expect(got).toBeNull();
  });

  it("the action event bubbles (so the shell can listen on the container)", async () => {
    const el = await mountRow("cleaning");
    let bubbled = false;
    document.body.addEventListener("karcher-action", () => { bubbled = true; }, { once: true });
    el.querySelector("button.btn-wrap").click();
    expect(bubbled).toBe(true);
  });

  it("showEmptyStation=false hides Empty even when emptyStationEnabled=true", async () => {
    const el = await mountRow("docked", { showEmptyStation: false, emptyStationEnabled: true });
    expect(el.querySelectorAll("button.btn-wrap")).toHaveLength(3);
    expect(labels(el)).not.toContain("Empty");
  });

  it("Empty is disabled by default (station present but not docked/attached right now)", async () => {
    const el = await mountRow("docked", { showEmptyStation: true });
    const [, , empty] = el.querySelectorAll("button.btn-wrap");
    expect(empty.disabled).toBe(true);
  });

  it("emptyStationEnabled=true enables Empty while shown", async () => {
    const el = await mountRow("docked", { showEmptyStation: true, emptyStationEnabled: true });
    const [, , empty] = el.querySelectorAll("button.btn-wrap");
    expect(empty.disabled).toBe(false);
  });

  it("offline disables Empty even when emptyStationEnabled=true", async () => {
    const el = await mountRow("docked", { offline: true, showEmptyStation: true, emptyStationEnabled: true });
    const [, , empty] = el.querySelectorAll("button.btn-wrap");
    expect(empty.disabled).toBe(true);
  });

  it("clicking an enabled Empty button emits action 'empty_station'", async () => {
    const el = await mountRow("docked", { showEmptyStation: true, emptyStationEnabled: true });
    let got = null;
    el.addEventListener("karcher-action", (e) => { got = e.detail.action; });
    const [, , empty] = el.querySelectorAll("button.btn-wrap");
    empty.click();
    expect(got).toBe("empty_station");
  });

  it("clicking a disabled Empty button emits nothing", async () => {
    const el = await mountRow("docked", { showEmptyStation: true }); // emptyStationEnabled defaults to false
    let got = null;
    el.addEventListener("karcher-action", (e) => { got = e.detail.action; });
    const [, , empty] = el.querySelectorAll("button.btn-wrap");
    empty.click();
    expect(got).toBeNull();
  });
});
