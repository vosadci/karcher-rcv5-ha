// Render tests for slice 5: the KarcherSelectionBadge leaf. The selection-hint
// derivation itself is already covered by the selectionHint() pure-fn tests;
// here we only check the leaf renders the pre-resolved state and emits chip-click.

import { describe, it, expect, beforeAll } from "vitest";

beforeAll(async () => {
  await import("../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js");
});

async function mount(state) {
  const el = document.createElement("karcher-selection-badge");
  el.state = state;
  document.body.appendChild(el);
  await el.updateComplete;
  return el;
}

describe("KarcherSelectionBadge (Lit leaf)", () => {
  it("is defined from the vendored Lit bundle", () => {
    expect(customElements.get("karcher-selection-badge")).toBeTruthy();
  });

  it("renders the badge text and chip label", async () => {
    const el = await mount({
      visible: true, badge: "Cleaning 1 room · Kitchen",
      chipLabel: "Select all", chipVisible: true, chipDisabled: false,
    });
    expect(el.querySelector("span").textContent).toBe("Cleaning 1 room · Kitchen");
    expect(el.querySelector(".map-chip-btn").textContent).toBe("Select all");
  });

  it("hides the host when not visible (no rooms or occupied)", async () => {
    const el = await mount({ visible: false, badge: "", chipLabel: "", chipVisible: false });
    expect(el.style.display).toBe("none");
  });

  it("shows the host when visible", async () => {
    const el = await mount({ visible: true, badge: "x", chipLabel: "Select all", chipVisible: true });
    expect(el.style.display).toBe("");
  });

  it("hides the chip when chipVisible is false (rooms absent)", async () => {
    const el = await mount({ visible: false, badge: "", chipLabel: "Select all", chipVisible: false });
    expect(el.querySelector(".map-chip-btn").style.display).toBe("none");
  });

  it("disables the chip while occupied", async () => {
    const el = await mount({
      visible: true, badge: "x", chipLabel: "Clear all", chipVisible: true, chipDisabled: true,
    });
    expect(el.querySelector(".map-chip-btn").disabled).toBe(true);
  });

  it("clicking the chip emits a bubbling chip-click event", async () => {
    const el = await mount({
      visible: true, badge: "x", chipLabel: "Select all", chipVisible: true, chipDisabled: false,
    });
    let bubbled = false;
    document.body.addEventListener("chip-click", () => { bubbled = true; }, { once: true });
    el.querySelector(".map-chip-btn").click();
    expect(bubbled).toBe(true);
  });

  it("tolerates an undefined state (renders empty, hidden)", async () => {
    const el = await mount(undefined);
    expect(el.style.display).toBe("none");
    expect(el.querySelector("span").textContent).toBe("");
  });
});
