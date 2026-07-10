import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/frontend/**/*.test.js"],
    // happy-dom (not node): the card now imports vendored Lit (./lit-core.js),
    // which touches `document`/`HTMLElement` at module load. happy-dom provides
    // them; the pure-logic tests are env-agnostic and unaffected. This also
    // backs the render tests for the Lit leaves (the #2 harness).
    environment: "happy-dom",
    coverage: {
      provider: "v8",
      // Only the card itself: the thin entry plus its ES modules under www/card/.
      // The vendored ./lit-core.js bundle (in www/, not www/card/) is third-party
      // and would drown the signal; it is exercised, not owned.
      include: [
        "custom_components/karcher_home_robots/www/karcher-vacuum-card.js",
        "custom_components/karcher_home_robots/www/card/**/*.js",
      ],
      reporter: ["text", "text-summary"],
      // Floors re-baselined for vitest 4 (2026-06-17). The v8 provider switched
      // to AST-aware remapping (ast-v8-to-istanbul), which reports stricter,
      // more accurate numbers than the v2 line-based mapping — the same tests
      // now measure ~16pts lower. This is an instrument change, not a coverage
      // regression (all 160 tests still pass). Like the Python coverage gate,
      // these ratchet forward from the new baseline: raise them as coverage
      // improves, never lower them to make a red build pass.
      thresholds: {
        lines: 67,
        statements: 64,
        branches: 59,
        functions: 64,
      },
    },
  },
});
