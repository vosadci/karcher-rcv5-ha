// computeDrawKey completeness: every input drawMap consumes must be keyed.
//
// The canvas is only repainted when computeDrawKey's output changes. A field
// drawMap reads but the key omits produces SILENT STALENESS — the canvas keeps
// showing the old value with no error anywhere, until some unrelated field
// happens to change and forces a redraw. That is how zoneEditable was missed:
// masked whenever the robot was moving (robot_px changes constantly), visible
// only when it went offline, which is exactly when no other field moves either.
//
// The oracle is the source of map-draw.js, parsed rather than imported — the
// point is a check that cannot agree with the code by construction, the same
// reasoning tests/unit/test_translations.py uses for config_flow's error keys.

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = readFileSync(
  resolve("custom_components/karcher_home_robots/www/card/map-draw.js"),
  "utf8",
);

// Fields read somewhere in map-draw.js that deliberately need no key entry.
// Every entry is a decision, not an oversight — adding one should require
// writing down why, which is the whole value of this list.
const EXCLUDED = new Map([
  ["attr", "the container itself; its members are keyed individually"],
  [
    "map_legend",
    "consumed by legendItems() for the DOM legend, not by drawMap's canvas — " +
      "Lit re-renders it on every hass update",
  ],
  [
    "pulse",
    "animation state; the reveal loop repaints every frame and bypasses the key",
  ],
  ["pulsePhase", "animation state, as above"],
  ["pulseColor", "animation state, as above"],
]);

function fieldsReadByDrawCode() {
  const found = new Set();
  for (const m of SRC.matchAll(/\b(?:vs|attr)\.([a-zA-Z_][a-zA-Z0-9_]*)/g)) {
    found.add(m[1]);
  }
  return found;
}

function drawKeyBody() {
  const start = SRC.indexOf("export function computeDrawKey");
  expect(start).toBeGreaterThan(-1);
  const end = SRC.indexOf("\n}", start);
  return SRC.slice(start, end);
}

describe("computeDrawKey", () => {
  it("keys every field the draw code reads", () => {
    const body = drawKeyBody();
    const missing = [...fieldsReadByDrawCode()].filter(
      (f) => !EXCLUDED.has(f) && !body.includes(f),
    );
    expect({ missing }).toEqual({ missing: [] });
  });

  it("has no stale exclusions", () => {
    // An exclusion for a field nothing reads any more is dead documentation that
    // will mislead the next person; drop it when the read goes.
    const read = fieldsReadByDrawCode();
    const stale = [...EXCLUDED.keys()].filter((f) => !read.has(f));
    expect({ stale }).toEqual({ stale: [] });
  });

  it("changes when zoneEditable flips", async () => {
    // The regression this file was written for. Offline flips zoneEditable to
    // false while every other input holds still, so only the key entry can
    // trigger the repaint that drops the resize handles.
    const { computeDrawKey } = await import(
      "../../custom_components/karcher_home_robots/www/card/map-draw.js"
    );
    const attr = { map_image_size: { width: 100, height: 80, cell_size: 4 } };
    const vs = { zoneRect: { x0: 1, y0: 2, x1: 3, y1: 4 }, zoneEditable: true };

    expect(computeDrawKey(attr, vs)).not.toBe(
      computeDrawKey(attr, { ...vs, zoneEditable: false }),
    );
  });

  it("changes when the rendered image size changes", async () => {
    const { computeDrawKey } = await import(
      "../../custom_components/karcher_home_robots/www/card/map-draw.js"
    );
    const vs = { zoneEditable: true };
    expect(
      computeDrawKey({ map_image_size: { width: 100, height: 80, cell_size: 4 } }, vs),
    ).not.toBe(
      computeDrawKey({ map_image_size: { width: 120, height: 80, cell_size: 4 } }, vs),
    );
  });

  it("is stable when nothing relevant changed", async () => {
    const { computeDrawKey } = await import(
      "../../custom_components/karcher_home_robots/www/card/map-draw.js"
    );
    const attr = { robot_px: { x: 1, y: 2, phi: 0.5 }, room_map: {} };
    const vs = { cardMode: "standard", zoom: 1 };
    expect(computeDrawKey(attr, vs)).toBe(computeDrawKey({ ...attr }, { ...vs }));
  });
});
