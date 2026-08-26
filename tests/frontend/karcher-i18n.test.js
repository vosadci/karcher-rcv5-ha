import { describe, it, expect, afterEach } from "vitest";
import {
  tr,
  setLang,
  roPlural,
  buttonLabels,
  primaryCleanLabel,
  COUNT_LABELS,
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

describe("German / French / Italian / Spanish / Dutch", () => {
  it("setLang selects each language and tr returns its translation", () => {
    setLang({ language: "de" });
    expect(tr("Settings")).toBe("Einstellungen");
    setLang({ language: "fr" });
    expect(tr("Settings")).toBe("Paramètres");
    setLang({ language: "it" });
    expect(tr("Settings")).toBe("Impostazioni");
    setLang({ language: "es" });
    expect(tr("Settings")).toBe("Ajustes");
    setLang({ language: "nl" });
    expect(tr("Settings")).toBe("Instellingen");
  });

  it("resolves region subtags (fr-CA → fr, es-419 → es, nl-BE → nl)", () => {
    setLang({ language: "fr-CA" });
    expect(tr("Mode")).toBe("Mode");
    setLang({ language: "es-419" });
    expect(tr("Whole home")).toBe("Toda la casa");
    setLang({ language: "nl-BE" });
    expect(tr("Whole home")).toBe("Hele woning");
  });

  it("buttonLabels translates per language", () => {
    setLang({ language: "de" });
    expect(buttonLabels("cleaning").playLabel).toBe("Pause");
    expect(buttonLabels("idle").dockLabel).toBe("Station");
    setLang({ language: "es" });
    expect(buttonLabels("paused").playLabel).toBe("Reanudar");
    setLang({ language: "nl" });
    expect(buttonLabels("cleaning").playLabel).toBe("Pauze");
    expect(buttonLabels("paused").playLabel).toBe("Hervatten");
    expect(buttonLabels("idle").dockLabel).toBe("Naar station");
  });

  it("primaryCleanLabel: German/Italian/Spanish/Dutch singular vs plural on n===1", () => {
    setLang({ language: "de" });
    expect(primaryCleanLabel("rooms", 1, false)).toBe("1 Raum reinigen");
    expect(primaryCleanLabel("rooms", 3, false)).toBe("3 Räume reinigen");
    setLang({ language: "it" });
    expect(primaryCleanLabel("rooms", 1, false)).toBe("Pulisci 1 stanza");
    expect(primaryCleanLabel("rooms", 2, false)).toBe("Pulisci 2 stanze");
    setLang({ language: "es" });
    expect(primaryCleanLabel("rooms", 1, false)).toBe("Limpiar 1 habitación");
    expect(primaryCleanLabel("rooms", 4, false)).toBe("Limpiar 4 habitaciones");
    setLang({ language: "nl" });
    expect(primaryCleanLabel("rooms", 0, false)).toBe("Hele woning schoonmaken");
    expect(primaryCleanLabel("rooms", 1, false)).toBe("1 kamer schoonmaken");
    expect(primaryCleanLabel("rooms", 3, false)).toBe("3 kamers schoonmaken");
  });

  it("primaryCleanLabel: French treats n<=1 as singular, n>=2 as plural", () => {
    setLang({ language: "fr" });
    expect(primaryCleanLabel("rooms", 1, false)).toBe("Nettoyer 1 pièce");
    expect(primaryCleanLabel("rooms", 2, false)).toBe("Nettoyer 2 pièces");
    expect(primaryCleanLabel("rooms", 0, false)).toBe("Nettoyer tout le logement");
  });

  it("roomsOn ('N of M rooms on') plural/gender agreement per language", () => {
    expect(COUNT_LABELS.en.roomsOn(1, 3)).toBe("1 of 3 rooms on");
    expect(COUNT_LABELS.en.roomsOn(1, 1)).toBe("1 of 1 room on");
    expect(COUNT_LABELS.ro.roomsOn(2, 5)).toBe("2 din 5 camere active");
    expect(COUNT_LABELS.de.roomsOn(2, 1)).toBe("2 von 1 Raum aktiv");
    expect(COUNT_LABELS.de.roomsOn(2, 3)).toBe("2 von 3 Räumen aktiv");
    expect(COUNT_LABELS.fr.roomsOn(2, 1)).toBe("2 sur 1 pièce active");
    expect(COUNT_LABELS.fr.roomsOn(2, 4)).toBe("2 sur 4 pièces actives");
    expect(COUNT_LABELS.it.roomsOn(1, 1)).toBe("1 di 1 stanza attiva");
    expect(COUNT_LABELS.it.roomsOn(2, 3)).toBe("2 di 3 stanze attive");
    expect(COUNT_LABELS.es.roomsOn(1, 1)).toBe("1 de 1 habitación activa");
    expect(COUNT_LABELS.es.roomsOn(2, 3)).toBe("2 de 3 habitaciones activas");
    expect(COUNT_LABELS.nl.roomsOn(1, 1)).toBe("1 van 1 kamer actief");
    expect(COUNT_LABELS.nl.roomsOn(2, 3)).toBe("2 van 3 kamers actief");
  });
});
