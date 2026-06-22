// Render tests for the KarcherMapMode leaf (floating Rooms|Zone control). Light
// DOM, like the other leaves: assert on querySelector and emitted events, not
// shadowRoot. Visual styling (the floating pill) stays in-HA-verified.

import { describe, it, expect, beforeAll } from "vitest";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

async function mount(mode = "rooms", locked = false) {
  const el = document.createElement("karcher-map-mode");
  el.mode = mode;
  el.locked = locked;
  document.body.appendChild(el);
  await el.updateComplete;
  return el;
}

describe("KarcherMapMode (Lit leaf)", () => {
  it("is defined and renders light DOM", async () => {
    const el = await mount();
    expect(customElements.get("karcher-map-mode")).toBeTruthy();
    expect(el.shadowRoot).toBeNull();
    expect(el.querySelectorAll(".map-mode-btn")).toHaveLength(2);
  });

  it("marks the active mode", async () => {
    const el = await mount("zone");
    const [rooms, zone] = el.querySelectorAll(".map-mode-btn");
    expect(rooms.classList.contains("active")).toBe(false);
    expect(zone.classList.contains("active")).toBe(true);
    expect(zone.getAttribute("aria-pressed")).toBe("true");
  });

  it("emits karcher-map-mode with the clicked mode", async () => {
    const el = await mount("rooms");
    let got = null;
    el.addEventListener("karcher-map-mode", (e) => { got = e.detail.mode; });
    el.querySelectorAll(".map-mode-btn")[1].click(); // Zone
    expect(got).toBe("zone");
  });

  it("the event bubbles so the shell can listen on the container", async () => {
    const el = await mount("rooms");
    let bubbled = false;
    document.body.addEventListener("karcher-map-mode", () => { bubbled = true; }, { once: true });
    el.querySelectorAll(".map-mode-btn")[0].click();
    expect(bubbled).toBe(true);
  });

  it("emits nothing while locked (running)", async () => {
    const el = await mount("rooms", true);
    let got = null;
    el.addEventListener("karcher-map-mode", (e) => { got = e.detail.mode; });
    el.querySelectorAll(".map-mode-btn")[1].click();
    expect(got).toBeNull();
    expect(el.querySelector(".map-mode-inner").classList.contains("locked")).toBe(true);
  });
});
