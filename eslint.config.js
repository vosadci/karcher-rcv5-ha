import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    // Vendored, minified third-party bundle — not our source to lint.
    ignores: ["custom_components/karcher_home_robots/www/lit-core.js"],
  },
  {
    files: ["custom_components/karcher_home_robots/www/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, customCards: "writable" },
    },
    rules: {
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      // Deliberate sparse arrays used as int->symbol lookup tables (index 0 = no symbol).
      "no-sparse-arrays": "off",
    },
  },
  {
    files: ["tests/frontend/**/*.js", "eslint.config.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      // node for vitest; browser because render tests run in happy-dom and
      // touch document/customElements.
      globals: { ...globals.node, ...globals.browser },
    },
  },
];
