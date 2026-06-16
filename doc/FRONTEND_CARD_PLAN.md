# Frontend Card — Architecture Improvement Plan

Captured 2026-06-16. Deferred — the card works and is not on fire; execute when
the render layer next generates fix-commits or before a major card feature.

Subject: `custom_components/karcher_home_robots/www/karcher-vacuum-card.js`
(~2436 lines, single file, served raw — **no build step**).

---

## Context: what is already done (do not redo)

The card has two layers:

- **Pure logic layer** — 17 exported functions at the top of the file
  (`roomColor`, `hitTestRooms`, `buttonStates`, `reconcileCustomise`,
  `computeListKey`, `selectionHint`, `buttonLabels`, …). Fully unit-tested:
  59 vitest tests in `tests/frontend/karcher-vacuum-card.test.js`.
- **Class layer** — `KarcherVacuumCard` (~40 methods) + `KarcherVacuumCardEditor`,
  hand-rolled vanilla custom elements doing manual DOM.

Findings #1–#4 from the 2026-06-16 review are **closed**:
- #1/#2 (coordinator owns map-overlay projection) — done in `coordinator.py`.
- #3 (`extra_state_attributes` god-method) — resolved as a side effect.
- #4 Tiers 1–3 — the reliability-critical class logic (optimistic customise
  reconciliation, list dedup key, selection-hint text, button labels) was
  extracted into the pure functions above and tested.

**This plan covers what Tiers 1–3 deliberately did NOT do: the structural debt
in the class layer itself.**

---

## The structural problem (measured 2026-06-16)

- `set hass()` → `_updateCard()` fans out to ~12 `_update*` / `_draw*` methods
  on **every** HA state poll.
- Each method re-renders by hand: `appendChild` ×90, `_el(` ×80,
  `textContent =` ×38, inline `.style.` ×19.
- Re-render is throttled only by ad-hoc, self-computed string dedup keys
  (`_lastListKey`, `_lastDrawKey`, `_lastSelectorKey`, `_lastPreferMode`,
  `_prevActivity`). **Most of the recent card fix-commits were bugs in this
  dedup logic** — wrong key ⇒ missed update or stomped optimistic edit.
- The canvas/DOM **render output is untestable** without a browser; only the
  extracted pure logic is covered. The sole real check on rendering today is
  loading the card in HA.

Tiers 1–3 tested *around* the dedup logic. The structural fixes below remove the
*need* for it.

---

## Proposed changes, ranked by benefit-per-risk

### 1. Migrate the render layer to Lit  — highest leverage *(rewrite, days)*

Replace the imperative `_el`/`appendChild`/`textContent`/manual-dedup render with
declarative `render()` templates and Lit's automatic, efficient DOM diffing.

**Benefit:** deletes the entire `_lastXKey` dedup-bug class structurally — Lit
only patches what changed, so the hand-rolled guards disappear. Lit is the
HA-standard frontend library. Shrinks the file substantially.

**Blocking caveat — spike first.** This assumes `import { LitElement, html } from "lit"`
resolves against the HA frontend's served modules **without a bundler** (this is
how mainstream HACS cards do it, but it is *inferred*, not verified for this
serve-raw setup in `__init__.py`). **Do a small spike — a one-component Lit card
loaded via the existing static path — and confirm it renders in a real HA
instance before committing to the migration.** If Lit will not load without a
build step, stop here and reassess (it would pull in change #4's tradeoff).

**Migration shape (once the spike passes):**
- Convert `KarcherVacuumCard` to extend `LitElement`; move `_buildDOM` +
  `_update*` text/attr writes into `render()` returning `html\`…\``.
- Keep the canvas/map drawing imperative (see change #3) — Lit owns the DOM
  chrome, a `<canvas>` ref stays manually drawn.
- Delete `_lastListKey` / `_lastSelectorKey` / `_lastPreferMode` dedup; keep
  `reconcileCustomise` (state decision, still needed) — it now feeds reactive
  properties instead of mutating instance fields ad hoc.
- The 59 existing pure-logic tests must stay green throughout (proves the
  extracted decisions are unchanged).

### 2. Add render-output tests  — *(contingent on #1)*

With Lit + a light DOM env (`@open-wc/testing` or jsdom in vitest), assert
"given this `hass` state, `render()` produces these buttons / labels / room
rows." **This closes the gap Tiers 1–3 could not** — rendering becomes testable
instead of browser-only. The benefit is the main reason #1 is worth more than it
looks; do not count #1 as complete without it.

### 3. Extract the canvas renderer into its own module/class  — *(independent, ~1 day)*

The `_draw*` methods — `_drawMap`, `_drawRoomOverlays`, `_drawRoomLabels`,
`_drawCurPath`, `_drawRobot`, `_drawCharger` (~400 lines) — are cohesive canvas
code with a clean single input (`attr`). Pull them into a `MapRenderer` class /
module with a `draw(ctx, attr)` entry point.

**Benefit:** both halves become comprehensible independently; the map logic can
be tested against a canvas mock (`getContext` stub asserting draw calls). Does
**not** require Lit — can be done first as a standalone, lower-risk win, and it
makes the eventual Lit migration smaller (the canvas stays out of `render()`).

**Constraint:** no bundler — if extracted to a separate served `.js`, it needs an
import-map / second static path. Cheaper to keep it a class *in the same file*
unless #1 introduces module loading anyway.

### 4. TypeScript — *(lower priority, only bundled with #1)*

Real benefit: `attr` shapes, `hass.states` access, and the card↔integration
contract are all untyped. **But TS introduces a build step**, which the current
architecture deliberately avoids and which currently lets vitest import source
directly. That tradeoff is large — only do TS *together with* a Lit migration
that already adds tooling, never standalone.

### 5. Typed card↔integration contract — *(lower urgency, cross-cutting)*

The card reads `attr.room_map`, `attr.robot_px`, `attr.cur_path_px`,
`attr.room_preferences`, etc. by convention. A shared schema / constants file (or
a documented contract in `ARCHITECTURE.md`) would catch silent drift when the
Python side renames or reshapes an attribute. The attribute surface is defined in
`vacuum.py:extra_state_attributes` and consumed across the card's `_update*` /
`_draw*` methods.

---

## Explicitly out of scope (decided 2026-06-16)

- **File-split for its own sake without Lit.** Splitting the current vanilla code
  into multiple raw served `.js` files needs import-maps / multiple static paths
  — cost without structural payoff. The split only pays off riding on #1 or #3.
- **jsdom/canvas pixel-diff tests** of the existing imperative renderer — no
  framework, no stable seam; not worth it until #1/#3 provide one.
- **Decomposing `_buildDOM` / `_drawRoomLabels` "for cleanliness"** — linear
  DOM/canvas, no tests gained, churn on working code.

---

## Recommendation

- If the card keeps generating fix-commits: **#1 + #2** (Lit migration) is the
  lasting fix — start with the load-in-HA spike.
- For benefit without committing to a framework: **#3** (`MapRenderer` extraction)
  is the standalone low-risk win.
- **#4 / #5** only alongside a migration that already pays the tooling cost.

## Verification bar (any change here)

- All existing pure-logic tests stay green (behavior-preserving proof).
- `npx eslint` + `npx vitest run` clean.
- `node --check` parses the card.
- Manual: load in a real HA instance, hard-refresh (browser caches the served
  JS), exercise map tap / room reorder / customise toggle / start-pause-dock.
  **No automated test substitutes for this until change #2 lands.**
