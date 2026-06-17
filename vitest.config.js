import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/frontend/**/*.test.js"],
    // happy-dom (not node): the card now imports vendored Lit (./lit-core.js),
    // which touches `document`/`HTMLElement` at module load. happy-dom provides
    // them; the pure-logic tests are env-agnostic and unaffected. This also
    // backs the render tests for the Lit leaves (the #2 harness).
    environment: "happy-dom",
  },
});
