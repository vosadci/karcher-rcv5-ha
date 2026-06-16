// Minimal browser-global stubs so karcher-vacuum-card.js can be imported in
// Node without a DOM emulator. The card runs three side-effects at module load:
//   - `class X extends HTMLElement` (needs HTMLElement to exist)
//   - `customElements.define(...)` (twice)
//   - `window.customCards.push(...)`
// The pure helpers under test never touch any of these, so empty shims suffice.

if (typeof globalThis.HTMLElement === "undefined") {
  globalThis.HTMLElement = class {};
}

if (typeof globalThis.customElements === "undefined") {
  globalThis.customElements = { define() {} };
}

if (typeof globalThis.window === "undefined") {
  globalThis.window = globalThis;
}
