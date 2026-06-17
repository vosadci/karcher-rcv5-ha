// Tests for slice 3: deriveSelectorRows (pure option/disabled/current logic)
// and the KarcherSelectorRows Lit leaf — especially its optimistic per-control
// pending state, which protects the just-clicked highlight from being stomped
// by the next (stale) poll. Styling stays in-HA-verified.

import { describe, it, expect, beforeAll } from "vitest";
import { deriveSelectorRows } from "../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

const modeState = (state, disabled_options = []) => ({ state, attributes: { disabled_options } });
const waterState = (state) => ({ state, attributes: {} });

describe("deriveSelectorRows", () => {
  it("returns no rows when nothing is configured", () => {
    expect(deriveSelectorRows({}, null, undefined, false)).toEqual([]);
  });

  it("mode row: marks disabled_options and reflects current value", () => {
    const [mode] = deriveSelectorRows({}, modeState("vacuum", ["mop"]), undefined, false);
    expect(mode.control).toBe("mode");
    expect(mode.value).toBe("vacuum");
    const byVal = Object.fromEntries(mode.options.map((o) => [o.value, o.disabled]));
    expect(byVal).toEqual({ vacuum: false, vacuum_and_mop: false, mop: true });
  });

  it("suction row: filters options by fan_speed_list and disables in mop mode", () => {
    const attr = { fan_speed: "standard", fan_speed_list: ["silent", "standard"] };
    const [, suction] = deriveSelectorRows(attr, modeState("mop"), undefined, false);
    expect(suction.control).toBe("suction");
    expect(suction.disabled).toBe(true); // mop mode
    const byVal = Object.fromEntries(suction.options.map((o) => [o.value, o.disabled]));
    expect(byVal).toEqual({ silent: false, standard: false, medium: true, turbo: true });
  });

  it("suction row absent when fan_speed is null/undefined", () => {
    const rows = deriveSelectorRows({ fan_speed: null }, modeState("vacuum"), undefined, false);
    expect(rows.find((r) => r.control === "suction")).toBeUndefined();
  });

  it("water row: present (disabled) when configured but disabled in vacuum mode", () => {
    const [, water] = deriveSelectorRows({}, modeState("vacuum"), waterState("low"), false);
    expect(water.control).toBe("water");
    expect(water.disabled).toBe(true); // vacuum mode gates water off
  });

  it("water row: enabled with current value in mop mode", () => {
    const [, water] = deriveSelectorRows({}, modeState("mop"), waterState("high"), false);
    expect(water.disabled).toBe(false);
    expect(water.value).toBe("high");
  });

  it("water row: value null and disabled when entity unavailable", () => {
    const [, water] = deriveSelectorRows({}, modeState("mop"), waterState("unavailable"), false);
    expect(water.value).toBeNull();
    expect(water.disabled).toBe(true);
  });

  it("busy disables every control", () => {
    const attr = { fan_speed: "standard" };
    const rows = deriveSelectorRows(attr, modeState("mop"), waterState("low"), true);
    expect(rows.every((r) => r.disabled)).toBe(true);
  });
});

async function mount(rows) {
  const el = document.createElement("karcher-selector-rows");
  el.rows = rows;
  document.body.appendChild(el);
  await el.updateComplete;
  return el;
}

const modeRow = (value) => ({
  control: "mode", label: "Mode", value, disabled: false,
  options: [
    { value: "vacuum", icon: "mdi:robot-vacuum", label: "Vacuum", disabled: false },
    { value: "mop", icon: "mdi:water", label: "Mop", disabled: false },
  ],
});

function activeLabels(el) {
  return [...el.querySelectorAll(".seg-btn.active")].map((b) => b.textContent.trim());
}

describe("KarcherSelectorRows (Lit leaf)", () => {
  it("is defined and renders the current value as active", async () => {
    const el = await mount([modeRow("vacuum")]);
    expect(customElements.get("karcher-selector-rows")).toBeTruthy();
    expect(activeLabels(el)).toEqual(["Vacuum"]);
  });

  it("clicking a segment emits {control, value} and highlights it immediately", async () => {
    const el = await mount([modeRow("vacuum")]);
    let detail = null;
    el.addEventListener("karcher-select", (e) => { detail = e.detail; });
    const [, mop] = el.querySelectorAll(".seg-btn");
    mop.click();
    await el.updateComplete;
    expect(detail).toEqual({ control: "mode", value: "mop" });
    expect(activeLabels(el)).toEqual(["Mop"]); // optimistic
  });

  it("a STALE poll (value still old) does NOT stomp the optimistic highlight", async () => {
    const el = await mount([modeRow("vacuum")]);
    el.querySelectorAll(".seg-btn")[1].click(); // click Mop
    await el.updateComplete;
    expect(activeLabels(el)).toEqual(["Mop"]);

    // Next poll arrives before the robot confirmed — still reports "vacuum".
    el.rows = [modeRow("vacuum")];
    await el.updateComplete;
    expect(activeLabels(el)).toEqual(["Mop"]); // pending wins, no snap-back
  });

  it("once the poll confirms the new value, pending clears (and a later revert shows)", async () => {
    const el = await mount([modeRow("vacuum")]);
    el.querySelectorAll(".seg-btn")[1].click(); // Mop
    await el.updateComplete;

    el.rows = [modeRow("mop")]; // confirmed
    await el.updateComplete;
    expect(activeLabels(el)).toEqual(["Mop"]);

    // An external change back to vacuum now takes effect (pending was cleared).
    el.rows = [modeRow("vacuum")];
    await el.updateComplete;
    expect(activeLabels(el)).toEqual(["Vacuum"]);
  });

  it("disabled option click emits nothing", async () => {
    const row = modeRow("vacuum");
    row.options[1].disabled = true; // Mop disabled
    const el = await mount([row]);
    let fired = false;
    el.addEventListener("karcher-select", () => { fired = true; });
    el.querySelectorAll(".seg-btn")[1].click();
    expect(fired).toBe(false);
  });

  it("collapses the host when there are no rows", async () => {
    const el = await mount([]);
    expect(el.style.display).toBe("none");
    expect(el.querySelectorAll(".field-row")).toHaveLength(0);
  });
});
