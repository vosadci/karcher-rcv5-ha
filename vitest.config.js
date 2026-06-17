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
      // Only the card itself. The vendored ./lit-core.js bundle is third-party
      // and would drown the signal; it is exercised, not owned.
      include: ["custom_components/karcher_home_robots/www/karcher-vacuum-card.js"],
      reporter: ["text", "text-summary"],
      // Floors set to the measured baseline (2026-06-17). Like the Python
      // coverage gate, these ratchet forward: raise them as coverage improves,
      // never lower them to make a red build pass.
      thresholds: {
        lines: 83,
        statements: 83,
        branches: 74,
        functions: 72,
      },
    },
  },
});
