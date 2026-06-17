// Tests for slice 2: the deriveStatTiles pure function and the KarcherStatsRow
// Lit leaf. Pure-fn tests cover the branching (the value of the slice); render
// tests cover the leaf incl. the empty-state collapse. Styling stays
// in-HA-verified.

import { describe, it, expect, beforeAll } from "vitest";
import { deriveStatTiles } from "../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

const stateOf = (state, attrs) => ({ state, attributes: attrs || {} });

describe("deriveStatTiles", () => {
  it("returns no tiles when both entities are missing", () => {
    expect(deriveStatTiles(undefined, undefined, false)).toEqual([]);
  });

  it("ignores unknown/unavailable states", () => {
    expect(deriveStatTiles(stateOf("unknown"), stateOf("unavailable"), false)).toEqual([]);
  });

  it("emits an area tile only when area > 0", () => {
    expect(deriveStatTiles(stateOf("0"), undefined, false)).toEqual([]); // 0 m² → no tile
    const tiles = deriveStatTiles(stateOf("12.34"), undefined, false);
    expect(tiles).toHaveLength(1);
    expect(tiles[0]).toMatchObject({ value: "12.3 m²", label: "Area cleaned" });
  });

  it("skips a NaN area state", () => {
    expect(deriveStatTiles(stateOf("not-a-number"), undefined, false)).toEqual([]);
  });

  it("emits a duration tile but not for time '0'", () => {
    expect(deriveStatTiles(undefined, stateOf("0"), false)).toEqual([]);
    const tiles = deriveStatTiles(undefined, stateOf("42"), false);
    expect(tiles).toHaveLength(1);
    expect(tiles[0]).toMatchObject({ value: "42 min", label: "Duration" });
  });

  it("adds a Finished tile only when not occupied and finished_at is present", () => {
    const now = Date.UTC(2026, 0, 1, 12, 0, 0);
    const fin = new Date(now - 5 * 60000).toISOString(); // 5 min ago
    // occupied → no Finished tile
    const busy = deriveStatTiles(undefined, stateOf("42", { finished_at: fin }), true, now);
    expect(busy.map((t) => t.label)).toEqual(["Duration"]);
    // not occupied → Finished tile appears
    const idle = deriveStatTiles(undefined, stateOf("42", { finished_at: fin }), false, now);
    expect(idle.map((t) => t.label)).toEqual(["Duration", "Finished"]);
    expect(idle[1].value).toBe("5m ago");
  });

  it("omits Finished when finished_at is absent", () => {
    const tiles = deriveStatTiles(undefined, stateOf("42"), false);
    expect(tiles.map((t) => t.label)).toEqual(["Duration"]);
  });

  it("combines area + duration + finished in order", () => {
    const now = Date.UTC(2026, 0, 1, 12, 0, 0);
    const fin = new Date(now - 60 * 60000).toISOString(); // 1h ago
    const tiles = deriveStatTiles(stateOf("8.0"), stateOf("30", { finished_at: fin }), false, now);
    expect(tiles.map((t) => t.label)).toEqual(["Area cleaned", "Duration", "Finished"]);
    expect(tiles[2].value).toBe("1h ago");
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
      { value: "8.0 m²", label: "Area cleaned", icon: "mdi:floor-plan" },
      { value: "30 min", label: "Duration", icon: "mdi:clock-outline" },
    ]);
    const blocks = el.querySelectorAll(".stat-block");
    expect(blocks).toHaveLength(2);
    expect(el.querySelector(".stat-value").textContent).toBe("8.0 m²");
    expect([...el.querySelectorAll(".stat-block span:not(.stat-value) span")].map((n) => n.textContent))
      .toEqual(["Area cleaned", "Duration"]);
  });

  it("collapses the host (display:none) when there are no tiles", async () => {
    const el = await mountRow([]);
    expect(el.querySelectorAll(".stat-block")).toHaveLength(0);
    expect(el.style.display).toBe("none");
  });

  it("expands the host again when tiles return", async () => {
    const el = await mountRow([]);
    expect(el.style.display).toBe("none");
    el.tiles = [{ value: "1.0 m²", label: "Area cleaned", icon: "mdi:floor-plan" }];
    await el.updateComplete;
    expect(el.style.display).toBe("");
    expect(el.querySelectorAll(".stat-block")).toHaveLength(1);
  });
});
