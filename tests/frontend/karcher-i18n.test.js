import { describe, it, expect, afterEach } from "vitest";
import {
  tr,
  setLang,
  roPlural,
  buttonLabels,
  primaryCleanLabel,
} from "../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js";

// The module keeps a single mutable current-language; reset to the default after
// each case so ordering can never leak a language between tests.
afterEach(() => setLang({ language: "en" }));

describe("setLang / tr", () => {
  it("defaults to English: tr returns the source key unchanged", () => {
    expect(tr("Mode")).toBe("Mode");
    expect(tr("Clean whole home")).toBe("Clean whole home");
  });

  it("switches to Romanian for a known key", () => {
    setLang({ language: "ro" });
    expect(tr("Mode")).toBe("Mod");
    expect(tr("Whole home")).toBe("Toată locuința");
  });

  it("parses region subtags (ro-RO → ro)", () => {
    setLang({ language: "ro-RO" });
    expect(tr("Settings")).toBe("Setări");
  });

  it("reads hass.locale.language when hass.language is absent", () => {
    setLang({ locale: { language: "ro" } });
    expect(tr("Settings")).toBe("Setări");
  });

  it("falls back to English for an unsupported language", () => {
    setLang({ language: "xx" });
    expect(tr("Mode")).toBe("Mode");
  });

  it("returns the source key for a missing translation entry", () => {
    setLang({ language: "ro" });
    expect(tr("Totally untranslated string")).toBe("Totally untranslated string");
  });
});

describe("roPlural (Romanian count agreement)", () => {
  const pick = (n) => roPlural(n, "cameră", "camere", "de camere");
  it("1 → singular", () => expect(pick(1)).toBe("cameră"));
  it("2–19 → plural without 'de'", () => {
    expect(pick(2)).toBe("camere");
    expect(pick(19)).toBe("camere");
  });
  it("multiples of 100 and ≥20 → 'de' form", () => {
    expect(pick(20)).toBe("de camere");
    expect(pick(100)).toBe("de camere");
  });
  it("101 (last two digits 01) → plural without 'de'", () => {
    expect(pick(101)).toBe("camere");
  });
});

describe("localized label builders", () => {
  it("buttonLabels stays English under the default language", () => {
    expect(buttonLabels("cleaning").playLabel).toBe("Pause");
    expect(buttonLabels("paused").dockLabel).toBe("Dock");
  });

  it("buttonLabels translates under Romanian", () => {
    setLang({ language: "ro" });
    expect(buttonLabels("cleaning").playLabel).toBe("Pauză");
    expect(buttonLabels("paused").playLabel).toBe("Reia");
    expect(buttonLabels("idle").dockLabel).toBe("Stație");
  });

  it("primaryCleanLabel applies Romanian plural rules to the room count", () => {
    setLang({ language: "ro" });
    expect(primaryCleanLabel("rooms", 0, false)).toBe("Curăță toată locuința");
    expect(primaryCleanLabel("rooms", 1, false)).toBe("Curăță 1 cameră");
    expect(primaryCleanLabel("rooms", 3, false)).toBe("Curăță 3 camere");
    expect(primaryCleanLabel("rooms", 20, false)).toBe("Curăță 20 de camere");
    expect(primaryCleanLabel("zone", 0, true)).toBe("Curăță zona");
  });
});
