// Tests for slice 2: the deriveStatTiles pure function and the KarcherStatsRow
// Lit leaf. Pure-fn tests cover the branching (the value of the slice); render
// tests cover the leaf incl. the always-3-tiles layout. Styling stays
// in-HA-verified.

import { describe, it, expect, beforeAll } from "vitest";
import { deriveStatTiles } from "../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

const stateOf = (state, attrs) => ({ state, attributes: attrs || {} });

describe("deriveStatTiles", () => {
  it("always returns 3 tiles, all '-' when both entities are missing", () => {
    const tiles = deriveStatTiles(undefined, undefined, false);
    expect(tiles.map((t) => t.label)).toEqual(["Area", "Duration", "Finished"]);
    expect(tiles.map((t) => t.value)).toEqual(["-", "-", "-"]);
  });

  it("treats unknown/unavailable states as '-'", () => {
    const tiles = deriveStatTiles(stateOf("unknown"), stateOf("unavailable"), false);
    expect(tiles.map((t) => t.value)).toEqual(["-", "-", "-"]);
  });

  it("emits an area value only when area > 0, else '-'", () => {
    expect(deriveStatTiles(stateOf("0"), undefined, false)[0].value).toBe("-"); // 0 m² → "-"
    const tiles = deriveStatTiles(stateOf("12.34"), undefined, false);
    expect(tiles[0]).toMatchObject({ value: "12.3 m²", label: "Area" });
  });

  it("treats a NaN area state as '-'", () => {
    expect(deriveStatTiles(stateOf("not-a-number"), undefined, false)[0].value).toBe("-");
  });

  it("emits a duration value but '-' for time '0'", () => {
    expect(deriveStatTiles(undefined, stateOf("0"), false)[1].value).toBe("-");
    const tiles = deriveStatTiles(undefined, stateOf("42"), false);
    expect(tiles[1]).toMatchObject({ value: "42 min", label: "Duration" });
  });

  it("fills Finished only when not occupied and finished_at is present", () => {
    const now = Date.UTC(2026, 0, 1, 12, 0, 0);
    const fin = new Date(now - 5 * 60000).toISOString(); // 5 min ago
    // occupied → Finished stays "-"
    const busy = deriveStatTiles(undefined, stateOf("42", { finished_at: fin }), true, now);
    expect(busy[2]).toMatchObject({ label: "Finished", value: "-" });
    // not occupied → Finished tile filled in
    const idle = deriveStatTiles(undefined, stateOf("42", { finished_at: fin }), false, now);
    expect(idle[2]).toMatchObject({ label: "Finished", value: "5m ago" });
  });

  it("leaves Finished as '-' when finished_at is absent", () => {
    const tiles = deriveStatTiles(undefined, stateOf("42"), false);
    expect(tiles[2]).toMatchObject({ label: "Finished", value: "-" });
  });

  it("combines area + duration + finished in order", () => {
    const now = Date.UTC(2026, 0, 1, 12, 0, 0);
    const fin = new Date(now - 60 * 60000).toISOString(); // 1h ago
    const tiles = deriveStatTiles(stateOf("8.0"), stateOf("30", { finished_at: fin }), false, now);
    expect(tiles.map((t) => t.label)).toEqual(["Area", "Duration", "Finished"]);
    expect(tiles.map((t) => t.value)).toEqual(["8.0 m²", "30 min", "1h ago"]);
  });
});

async function mountRow(tiles) {
  const el = document.createElement("karcher-stats-row");
  el.tiles = tiles;
  document.body.appendChild(el);
  await el.updateComplete;
  return el;
}

describe("KarcherStatsRow (Lit leaf)", () => {
  it("is defined from the vendored Lit bundle", () => {
    expect(customElements.get("karcher-stats-row")).toBeTruthy();
  });

  it("renders one .stat-block per tile, with value + label", async () => {
    const el = await mountRow([
      { value: "8.0 m²", label: "Area", icon: "mdi:floor-plan" },
      { value: "30 min", label: "Duration", icon: "mdi:clock-outline" },
      { value: "-", label: "Finished", icon: "mdi:calendar-check-outline" },
    ]);
    const blocks = el.querySelectorAll(".stat-block");
    expect(blocks).toHaveLength(3);
    expect([...el.querySelectorAll(".stat-value")].map((n) => n.textContent))
      .toEqual(["8.0 m²", "30 min", "-"]);
    expect([...el.querySelectorAll(".stat-block span:not(.stat-value) span")].map((n) => n.textContent))
      .toEqual(["Area", "Duration", "Finished"]);
  });

  it("collapses the host (display:none) when there are no tiles", async () => {
    const el = await mountRow([]);
    expect(el.querySelectorAll(".stat-block")).toHaveLength(0);
    expect(el.style.display).toBe("none");
  });

  it("expands the host again when tiles return", async () => {
    const el = await mountRow([]);
    expect(el.style.display).toBe("none");
    el.tiles = [{ value: "1.0 m²", label: "Area", icon: "mdi:floor-plan" }];
    await el.updateComplete;
    expect(el.style.display).toBe("");
    expect(el.querySelectorAll(".stat-block")).toHaveLength(1);
  });
});
