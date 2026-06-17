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

**Blocking caveat — spike first.** Lit must load **without a CI build step AND
without a runtime external dependency** (an internet-dependent CDN import is
disqualified by this project's offline-first thesis — see `INTENT.md` /
`READ_BEFORE_BUYING.md`). Correction to an earlier draft: bare `import … from
"lit"` is the *least* likely to work — a raw-served Lovelace card does not inherit
HA's import map, so bare specifiers only resolve inside HA's own bundled frontend.

**Spike status (2026-06-16): RESOLVED in a real HA instance. Decision: adopt vendored.**

In-HA results — vendored: **PASS** · bare `"lit"`: FAIL · borrow: FAIL · CDN: PASS
(disqualified by values). The vendored `lit-core.js` loads and renders with no CI
build step and no runtime dependency, so #1 proceeds on that basis. The spike card
`karcher-lit-spike.js` is to be deleted now that the decision is recorded;
`lit-core.js` is kept (it is the migration's Lit source).

- **Candidate chosen: vendored relative ESM.** `www/lit-core.js` is a committed
  15.5 KB self-contained Lit 3.3.3 ESM bundle (zero external imports), imported as
  `import { LitElement, html, css } from "./lit-core.js"`. No CI bundler, no
  runtime dep. Verified locally: parses, self-contained (grep), and evaluates past
  module init under Node (stops only at `createTreeWalker`, i.e. needs a real DOM).
- **How `lit-core.js` was produced (dev-time only, reproducible):**
  ```
  npm install lit@3.3.3            # in a scratch dir
  echo 'export { LitElement, html, css } from "lit";' > entry.js
  npx esbuild entry.js --bundle --format=esm --minify --target=es2020 --outfile=lit-core.js
  ```
  esbuild is already a transitive dev dep (via vite/vitest). Note: esm.sh
  `?bundle` and jsDelivr `+esm` both emit re-export stubs with absolute internal
  imports — they do NOT yield a single self-contained file; a one-shot local
  esbuild does.
- **The spike artifact: `www/karcher-lit-spike.js`** (temporary; delete after the
  decision). Add `type: custom:karcher-lit-spike` as a Manual card. It renders a
  PASS/FAIL grid for four strategies — vendored (the candidate), bare `"lit"`
  (negative control, expected FAIL), borrow-from-loaded-HA-element (fragile;
  usually no `html`), CDN (disqualified) — and mounts a real `LitElement` to prove
  *rendering*, not just import.

**Decision gate.** If **vendored = PASS** (expected), adopt it and proceed to the
migration shape below. If the only thing that works is CDN or nothing without a
bundler, **stop**: #1 then costs a build step (#4's tradeoff) and that is a
user-level decision, not something to push through. After the decision, delete
`karcher-lit-spike.js`; keep or remove `lit-core.js` per whether #1 proceeds.

**Migration shape — strangler-fig, NOT big-bang (revised 2026-06-16).**
The render layer has no automated safety net (rendering is browser-only) and
every increment needs in-HA eyeballing, so a single giant `extends LitElement`
flip is the wrong move. Convert **leaves → shell**, smallest components first;
the shell (`KarcherVacuumCard`) stays vanilla and flips LAST.

- **Each Lit leaf:** data **down** via a property, actions **up** via
  `dispatchEvent` — the child must never reach back into parent methods. Mounted
  in the still-vanilla shell via the existing `appendChild`; the shell listens for
  the child's events and routes them to its existing handlers.
- **Canvas stays in the vanilla shell, untouched, until the very end** (possibly
  never). The #3 `drawMap(ctx, canvas, vs)` already makes the shell the canvas
  owner regardless of base class, so "canvas-inside-Lit re-render preservation" —
  the scariest hazard — is in NO early increment.
- **Per-leaf dedup retires as it converts:** Lit diffing replaces the relevant
  `_lastXKey` guard. `reconcileCustomise` etc. stay (state decisions) and feed
  reactive properties.
- **Preserve the HA card API on the shell** (`setConfig`, `getCardSize`,
  `getConfigElement`, `getStubConfig`, `customCards.push`) until the final flip.
  Leave `KarcherVacuumCardEditor` entirely alone — out of scope.
- **Order:** (1) button row first — it's backed by tested `buttonStates` +
  `buttonLabels` AND exercises the data-down/events-up contract needed everywhere;
  (2) stats / selection hint / selectors; (3) room list; (4) map chrome; (5) shell
  flip. Each slice ships and is verified in HA independently.
- The existing pure-logic tests stay green throughout.

**Slice tracking:**
- [x] Slice 1 — button-row Lit leaf (`KarcherButtonRow`, light DOM) + render-test
      harness (happy-dom). Code + 11 render tests landed; harness validated
      (vendored Lit renders under happy-dom). **Awaiting in-HA visual confirm:**
      buttons appear, the **disabled** button greys/dims and the **primary**
      button keeps its accent fill (these ride on the shell CSS crossing into the
      light-DOM leaf — happy-dom can't check paint). Once confirmed, proceed.
- [x] Slice 2 — stat-tiles row (`KarcherStatsRow`, light DOM) + `deriveStatTiles`
      pure fn (all branching). Code + 12 tests landed. **Awaiting in-HA confirm:**
      tiles render with values/icons, the row **collapses cleanly when empty** (no
      gap band), and the **battery glyph still updates** (it shares `_updateStats`
      and was deliberately left in the shell — verify it didn't fall out).
- [x] Slice 3 — standard-mode selector rows (`KarcherSelectorRows`, light DOM) +
      `deriveSelectorRows` pure fn. The leaf keeps a **per-control optimistic
      `_pending`** value so a just-clicked highlight survives the next (stale)
      poll instead of snapping back — the `_lastSelectorKey` rebuild-skip did this
      before; Lit diffing replaces only its perf half. Code + 14 tests (incl. the
      stale-poll stomp case). **Awaiting in-HA confirm:** each control highlights
      instantly AND stays highlighted through the next poll; water disables in
      vacuum mode; standard↔customise switching strands nothing; **and the
      customise per-room detail panel still works** (it shares the imperative
      `_makeFieldRow`/`_makeSegmented` helpers — kept until the room-list slice;
      no render test covers that still-imperative path).
- [x] Slice 4 — customise room list (`KarcherRoomList`, light DOM) +
      `deriveRoomRows` pure fn. Biggest, most stateful leaf. Key decision: the
      shell keeps `_customiseSelected`/`_customisePending`/`_detailRoomId` (the
      still-vanilla map reads them too — one source of truth, two readers); the
      leaf is view+events, its only private state being the transient drag. A
      `shouldUpdate` guard suppresses re-render mid-drag (the role the retired
      `_lastListKey` dedup played). Detail-panel segments keep their own
      `${roomId}:${field}` optimistic pending (parity with the slice-3 selectors).
      Retired `_makeFieldRow`/`_makeSegmented` (last callers gone) and the dead
      `_lastListKey`/shell `_dragSrcId`. `computeListKey` is now unused by the card
      (kept exported + tested; harmless). 16 new tests. **Conscious deviations:**
      (a) the header "N of M rooms on" count now derives from the reconciled
      enabled-set rather than raw `prefs.custom` — tracks the optimistic toggles,
      arguably more correct; (b) `room-reorder` is emitted via DnD, which
      happy-dom can't exercise, so the *gesture* is in-HA-only (the payload is
      unit-tested via a direct `_onDrop` call).
      **Awaiting in-HA confirm:**
      - toggle a room → it greys on the map instantly AND survives the next poll;
      - reorder by drag persists; a drag spanning a poll tick doesn't jump;
      - expand/collapse; a per-room detail change highlights instantly + survives a poll;
      - the two rewired imperative callers (no test coverage): **tap a room on the
        map canvas in customise mode** and the **"Select all" chip in customise
        mode** both still toggle + refresh the list.
- [x] Slice 5 — map selection badge (`KarcherSelectionBadge`, light DOM) using
      the already-tested `selectionHint` pure fn. Correction to an earlier
      assumption: the chip and badge text are **one** contiguous region
      (`_mapChipBtn` is a child of `_badgeEl`), so this is a clean single leaf, not
      the feared one-fn→two-leaves case. Shell computes the hint state and sets
      `.state`; the chip's `chip-click` routes to `_onMapChipClick`. Removed the
      dead `_badgeTextEl`/`_mapChipBtn`/`_badgeIconEl` shell fields (the icon was
      already built-but-never-appended in the original — not restored). 8 new
      tests. **Awaiting in-HA confirm:** badge text reads correctly, the chip
      flips Select all ↔ Clear all and is disabled while cleaning, and tapping a
      room on the map in standard mode updates the selection + badge.
- [ ] Slices 6+ — map chrome, shell flip (the last vanilla pieces).

**Deferred bug-surface (forward note):** the battery glyph had its own fix-commit
(`5b9d454`). When its slice comes, extract its pure logic too.

**Harness note:** vitest now runs the whole `tests/frontend` suite under
`happy-dom` (was `node`) because importing the card pulls in Lit, which touches
`document` at load. The old `tests/frontend/setup.js` node-stub is deleted.
`lit-core.js` is ESLint-ignored (vendored/minified).

### 2. Add render-output tests  — *(harness stands up with the FIRST Lit leaf)*

With Lit + a light DOM env (`happy-dom` in vitest — lighter than jsdom; verify Lit
3 support holds), assert "given this property, the leaf's `render()` produces these
buttons / labels / rows." **This closes the gap Tiers 1–3 could not** — DOM
rendering becomes testable instead of browser-only. Correction: #2 is NOT blocked
until the whole migration; the harness is buildable the moment one leaf exists, and
it ships *with* slice 1. The DOM env covers templates + text, **not** canvas or
layout — the map stays in-HA-verified.

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
