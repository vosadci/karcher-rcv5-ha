// Parity gates for the card's localization — the invariants that silently rot
// as strings are added later (a missing key renders English with no error).
//
// Covers: (1) every TRANSLATIONS language block shares one key set; (2) every
// tr("literal") wrapped in the card resolves in every block (the silent-fallback
// guard); (3) every language has a COUNT_LABELS entry; (4) the card's mode /
// suction / water VALUE labels equal the same entity states in that language's
// translations/<lang>.json (the dual-source invariant).
//
// Not covered here: dynamic tr(variable) sources (STATE_LABELS, OBJECT_LABELS,
// editor companions). Those are a small fixed enumeration; block parity (1)
// keeps them consistent across languages once present in the reference block.
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  TRANSLATIONS,
  COUNT_LABELS,
} from "../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js";

// vitest runs with cwd = repo root (where vitest.config.js lives), so resolve
// package files from there — happy-dom leaves import.meta.url non-file.
const PKG = "custom_components/karcher_home_robots";
const source = readFileSync(resolve(`${PKG}/www/karcher-vacuum-card.js`), "utf8");

// Card-chrome languages (English is source-keyed, so it has no block).
const LANGS = Object.keys(TRANSLATIONS);

describe("card TRANSLATIONS parity", () => {
  it("has at least the five shipped languages", () => {
    expect(LANGS).toEqual(expect.arrayContaining(["ro", "de", "fr", "it", "es"]));
  });

  it("every language block shares one identical key set", () => {
    const ref = new Set(Object.keys(TRANSLATIONS[LANGS[0]]));
    for (const lang of LANGS) {
      const keys = new Set(Object.keys(TRANSLATIONS[lang]));
      const missing = [...ref].filter((k) => !keys.has(k));
      const extra = [...keys].filter((k) => !ref.has(k));
      expect({ lang, missing, extra }).toEqual({ lang, missing: [], extra: [] });
    }
  });

  it('every tr("literal") in the card resolves in every language block', () => {
    const literals = [
      ...new Set([...source.matchAll(/\btr\("((?:[^"\\]|\\.)*)"\)/g)].map((m) => m[1])),
    ];
    expect(literals.length).toBeGreaterThan(0);
    for (const lang of LANGS) {
      const missing = literals.filter((k) => !(k in TRANSLATIONS[lang]));
      expect({ lang, missing }).toEqual({ lang, missing: [] });
    }
  });

  it("every TRANSLATIONS language has a COUNT_LABELS entry (plus the en fallback)", () => {
    expect(COUNT_LABELS.en).toBeTruthy();
    for (const lang of LANGS) {
      expect(COUNT_LABELS[lang], `COUNT_LABELS missing "${lang}"`).toBeTruthy();
      expect(typeof COUNT_LABELS[lang].cleanRooms).toBe("function");
      expect(typeof COUNT_LABELS[lang].roomsOn).toBe("function");
    }
  });
});

describe("card ↔ JSON value-label sync", () => {
  // [cardKey, select entity, state key] — the labels the card renders from its
  // own table that also appear as entity states in the more-info dialog.
  const VALUE_KEYS = [
    ["Vacuum", "cleaning_mode", "vacuum"],
    ["Vacuum & Mop", "cleaning_mode", "vacuum_and_mop"],
    ["Mop", "cleaning_mode", "mop"],
    ["Silent", "room_power", "silent"],
    ["Standard", "room_power", "standard"],
    ["Medium", "room_power", "medium"],
    ["Turbo", "room_power", "turbo"],
    ["Low", "water_level", "low"],
    ["High", "water_level", "high"],
  ];

  for (const lang of LANGS) {
    it(`${lang}: mode/suction/water labels match translations/${lang}.json`, () => {
      const json = JSON.parse(
        readFileSync(resolve(`${PKG}/translations/${lang}.json`), "utf8"),
      );
      const sel = json.entity.select;
      for (const [cardKey, entity, state] of VALUE_KEYS) {
        expect(TRANSLATIONS[lang][cardKey]).toBe(sel[entity].state[state]);
      }
      // The single card "Medium" key serves both suction and water — sound only
      // because every language uses the same word for both. Assert that holds.
      expect(TRANSLATIONS[lang].Medium).toBe(sel.water_level.state.medium);
    });
  }
});
