// Render tests for the FLIPPED shell (KarcherVacuumCard is now a LitElement).
// These are the only tests that exercise the shell itself; the leaves + pure
// fns are covered elsewhere. The make-or-break assertion is canvas node
// identity across hass updates (the bitmap-preservation guarantee).

import { describe, it, expect, beforeAll } from "vitest";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

function fakeHass(activity = "docked", extra = {}) {
  return {
    states: {
      "vacuum.rcv5": {
        state: activity,
        attributes: {
          friendly_name: "Rocky",
          room_map: {}, room_preferences: {},
          ...extra,
        },
      },
    },
    entities: {},
    callService() {},
  };
}

async function mountCard(config = { vacuum_entity: "vacuum.rcv5" }) {
  const el = document.createElement("karcher-vacuum-card");
  el.setConfig(config);
  el.hass = fakeHass();
  document.body.appendChild(el);
  await el.updateComplete;
  return el;
}

describe("KarcherVacuumCard shell (flipped to LitElement)", () => {
  it("preserves the HA card API surface", () => {
    const Cls = customElements.get("karcher-vacuum-card");
    expect(typeof Cls.getConfigElement).toBe("function");
    expect(typeof Cls.getStubConfig).toBe("function");
    expect(Cls.getStubConfig().vacuum_entity).toBeTruthy();
    const el = document.createElement("karcher-vacuum-card");
    expect(typeof el.setConfig).toBe("function");
    expect(el.getCardSize()).toBe(6);
  });

  it("setConfig throws without vacuum_entity", () => {
    const el = document.createElement("karcher-vacuum-card");
    expect(() => el.setConfig({})).toThrow(/vacuum_entity/);
  });

  it("injects the stylesheet as a <style> tag, not via static styles", async () => {
    // Regression guard: `static styles = _CSS` (a plain string) routed through
    // adoptStyles()/adoptedStyleSheets and threw a TypeError in HA. The CSS must
    // be a <style> element in the shadow root instead.
    const el = await mountCard();
    const Cls = customElements.get("karcher-vacuum-card");
    expect(Cls.styles).toBeUndefined(); // no static styles
    const style = el.renderRoot.querySelector("style");
    expect(style).toBeTruthy();
    expect(style.textContent.length).toBeGreaterThan(100); // the real CSS got in
  });

  it("renders the four ha-cards and mounts every leaf", async () => {
    const el = await mountCard();
    expect(el.renderRoot.querySelectorAll("ha-card")).toHaveLength(4);
    for (const tag of [
      "karcher-stats-row", "karcher-selection-badge", "karcher-button-row",
      "karcher-selector-rows", "karcher-room-list",
    ]) {
      expect(el.renderRoot.querySelector(tag), tag).toBeTruthy();
    }
  });

  it("renders the robot name and a status label from hass", async () => {
    const el = await mountCard();
    expect(el.renderRoot.querySelector(".robot-name").textContent).toBe("Rocky");
    expect(el.renderRoot.querySelector(".status-label").textContent.trim().length).toBeGreaterThan(0);
  });

  it("passes activity down to the button-row leaf", async () => {
    const el = await mountCard();
    el.hass = fakeHass("cleaning");
    await el.updateComplete;
    expect(el.renderRoot.querySelector("karcher-button-row").activity).toBe("cleaning");
  });

  it("KEEPS THE SAME <canvas> node across hass updates (bitmap survives)", async () => {
    const el = await mountCard();
    const canvas1 = el.renderRoot.querySelector("canvas");
    expect(canvas1).toBeTruthy();
    canvas1._mark = "original";

    // Several hass updates that change unrelated state.
    el.hass = fakeHass("cleaning"); await el.updateComplete;
    el.hass = fakeHass("returning"); await el.updateComplete;
    el.hass = fakeHass("docked"); await el.updateComplete;

    const canvas2 = el.renderRoot.querySelector("canvas");
    expect(canvas2).toBe(canvas1);         // same node instance
    expect(canvas2._mark).toBe("original"); // patched, never recreated
  });

  it("shows the placeholder (map entity not in states) and hides the canvas", async () => {
    // _deriveCompanions derives a default map_entity from the vacuum id; it is
    // not present in the fake hass, so the placeholder reports it missing.
    const el = await mountCard();
    const ph = el.renderRoot.querySelector(".map-placeholder");
    expect(ph.textContent).toContain("Entity not found");
    expect(el.renderRoot.querySelector("canvas").getAttribute("style")).toContain("display:none");
  });

  it("the tab buttons reflect cardMode and switching to customise shows the room list", async () => {
    const el = await mountCard();
    // Default is standard → first tab active.
    const tabs = el.renderRoot.querySelectorAll(".tab-row .seg-btn");
    expect(tabs[0].classList.contains("active")).toBe(true);
    // Drive a prefer_mode change → customise.
    el.hass = fakeHass("docked", { prefer_mode: "customise" });
    await el.updateComplete;
    expect(el.renderRoot.querySelectorAll(".tab-row .seg-btn")[1].classList.contains("active")).toBe(true);
    expect(el.renderRoot.querySelector("karcher-room-list").classList.contains("visible")).toBe(true);
  });
});
