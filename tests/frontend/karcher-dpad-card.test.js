// Manual-drive D-pad card: registry-based button lookup, disabled-button
// handling, offline state, and the button.press call each arrow makes.
//
// Entity ids are literal on purpose: they are the oracle for what HA registers.

import { describe, it, expect, beforeAll } from "vitest";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

const VAC = "vacuum.lab_robot_vacuum";
const DRIVE = {
  drive_forward: "button.lab_robot_drive_forward",
  drive_backward: "button.lab_robot_drive_backward",
  drive_left: "button.lab_robot_turn_left",
  drive_right: "button.lab_robot_turn_right",
};

function makeHass({ withStates = true, vacuumState = "docked", buttonState = "unknown" } = {}) {
  const states = { [VAC]: { state: vacuumState, attributes: {} } };
  const entities = { [VAC]: { entity_id: VAC, device_id: "dev1", translation_key: "vacuum" } };
  for (const [key, id] of Object.entries(DRIVE)) {
    entities[id] = { entity_id: id, device_id: "dev1", translation_key: key };
    if (withStates) states[id] = { state: buttonState, attributes: {} };
  }
  // Same translation_key on another device must never be picked.
  entities["button.other_drive_forward"] = {
    entity_id: "button.other_drive_forward",
    device_id: "dev2",
    translation_key: "drive_forward",
  };
  states["button.other_drive_forward"] = { state: "unknown", attributes: {} };
  const calls = [];
  return { states, entities, calls, callService: (d, s, data) => calls.push([d, s, data]) };
}

async function mount(hass, config = { vacuum_entity: VAC }) {
  const el = document.createElement("karcher-dpad-card");
  el.setConfig(config);
  el.hass = hass;
  document.body.appendChild(el);
  await el.updateComplete;
  const pad = el.renderRoot.querySelector("karcher-dpad");
  if (pad) await pad.updateComplete;
  return el;
}

describe("karcher-dpad-card", () => {
  it("requires vacuum_entity", () => {
    const el = document.createElement("karcher-dpad-card");
    expect(() => el.setConfig({})).toThrow(/vacuum_entity/);
  });

  it.each([
    ["dpad-up", DRIVE.drive_forward],
    ["dpad-down", DRIVE.drive_backward],
    ["dpad-left", DRIVE.drive_left],
    ["dpad-right", DRIVE.drive_right],
  ])("%s presses the drive button on the same device", async (cls, entityId) => {
    const hass = makeHass();
    const el = await mount(hass);
    el.renderRoot.querySelector(`.${cls}`).click();
    expect(hass.calls).toEqual([["button", "press", { entity_id: entityId }]]);
  });

  it("shows the missing message when the buttons are disabled (no state)", async () => {
    const hass = makeHass({ withStates: false });
    const el = await mount(hass);
    expect(el.renderRoot.querySelector(".missing")).toBeTruthy();
    expect(el.renderRoot.querySelector("karcher-dpad")).toBeFalsy();
  });

  it("disables the arrows while the vacuum is unavailable", async () => {
    const el = await mount(makeHass({ vacuumState: "unavailable" }));
    expect(el.renderRoot.querySelector(".dpad-up").disabled).toBe(true);
  });

  it("disables the arrows while the buttons are unavailable", async () => {
    const hass = makeHass({ buttonState: "unavailable" });
    const el = await mount(hass);
    expect(el.renderRoot.querySelector(".dpad-up").disabled).toBe(true);
    el.renderRoot.querySelector(".dpad-up").click();
    expect(hass.calls).toEqual([]);
  });

  it("honours an explicit <key>_entity override", async () => {
    const hass = makeHass();
    hass.states["button.custom_forward"] = { state: "unknown", attributes: {} };
    const el = await mount(hass, { vacuum_entity: VAC, drive_forward_entity: "button.custom_forward" });
    el.renderRoot.querySelector(".dpad-up").click();
    expect(hass.calls).toEqual([["button", "press", { entity_id: "button.custom_forward" }]]);
  });
});
