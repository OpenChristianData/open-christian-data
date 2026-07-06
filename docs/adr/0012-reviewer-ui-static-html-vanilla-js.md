# ADR-0012: Reviewer UI is static HTML + vanilla JavaScript; no framework

**Status:** Superseded by ADR-0020 (2026-07-04); Accepted (2026-05-15)

## Context

Today's Reviewer UI is the HTML output of `build/lib/render_review_html.py` — static HTML files generated per record, opened locally. No JavaScript; no build step; no runtime dependencies.

The rearchitecture extends the Reviewer UI with five new affordances:

1. Split-pane view (reconstructed text + scan image) with bbox highlight when bbox is available (ADR-0006).
2. Per-disagreement adjudication affordance (side-by-side per-rendering readings; chosen-reading picker).
3. Structural-disagreement affordance.
4. Modernisation review affordance (original vs modernised side-by-side; per-token accept/override).
5. Rendering catalog management (promote `pending` to `pd_attestor` / `reference_only`).

At least the bbox highlight, per-disagreement click handlers, and modernisation accept/override controls require client-side interactivity that static HTML alone doesn't deliver. The architectural question: how do we deliver that interactivity?

Three viable shapes:

1. **Static HTML + vanilla JavaScript.** Extend `render_review_html.py` to emit small JS snippets alongside the HTML for the interactive bits.
2. **Static HTML + a minimal framework** (Alpine.js, Petite-Vue, htmx). Lightweight reactive bindings, no build step.
3. **Single-page application** (React, Vue, Svelte). Full client-side framework with a build pipeline.

## Decision

Option 1: **static HTML + vanilla JavaScript**. Keep the existing `render_review_html` machinery; add vanilla JS for the interactive affordances. No framework, no build step, no `node_modules` directory in the OCD repo.

Each interactive affordance ships as a small JS module embedded in or sibling to the generated HTML.

### LoC budget — tiered (R48 amendment, 2026-05-16)

The affordances are not uniform in complexity; the original "~200 LoC per affordance" estimate underweights the harder ones. Realistic ceilings:

- **Simple affordances** (~200 LoC): modernisation accept/override per block, opportunistic bbox highlight on the split-pane scan.
- **Complex affordances** (~400 LoC): structural-disagreement view (side-by-side rendering diff, accept/override per disagreement kind, split/merge interactions per R49), filterable adjudication queue, rendering-catalog management (promote/demote/record rationale).
- **Shared infrastructure** (~300 LoC total): persistence layer (review-patch accumulator + JSON download trigger), router / state, scan loader (`scans-derived/` WebP fetch + page-mapping resolution).

Aggregate ceiling under this breakdown: ~1900 LoC. Tripwire triggers:

- **Per-affordance overage.** Any single complex affordance exceeding ~600 LoC, inspect for accidental complexity before continuing — overruns are usually localised and a single affordance ballooning rarely indicates a framework problem.
- **Aggregate overage.** Total interactive JS exceeding ~2500 LoC re-opens this ADR for whether vanilla JS is still right (versus minimal reactive framework like Alpine.js / Petite-Vue / htmx, or a SPA shape).

The budget is grounded in the affordance breakdown, not picked off the shelf; treat it as a real ceiling, not a soft estimate.

### Persistence: review patches (amended 2026-05-16)

A static HTML page opened from a `file://` URL cannot write to local files without a helper. The Reviewer UI therefore does not write directly to `review/audit.jsonl`, `catalog.json`, or workbench files. Instead:

1. **In-browser accumulation.** As you click through adjudication affordances (disagreement choice, structural resolution, modernisation accept/override, catalog promotion/demotion), the UI accumulates decisions in browser memory.
2. **Patch download.** A persistent "Save review patch" control downloads a JSON **review patch** file via `<a download>`. The patch carries record IDs, block IDs, audit entries, catalog deltas, workbench deltas, and a tool-version stamp. Schema lives at `schemas/v1/review_patch.schema.json`.
3. **CLI apply.** `build/tools/apply_review_patch.py <patch.json>` validates the patch against the current `data/` state, appends to `review/audit.jsonl`, updates `catalog.json` and workbench files, and refuses to apply if any target file has drifted since the patch was generated (drift detected by content hash on the relevant block / record). `build/tools/inspect_review_patch.py <patch.json>` shows you what would change without applying.

This keeps the Reviewer UI as a local, file-based tool that opens from disk in a browser — no dev server, no Chromium-only API — at the cost of a two-step ceremony per Reviewer session (download → CLI-apply). The CLI step is also the natural place for `careful`-style guardrails on destructive changes (catalog demotion of `pd_anchor`, audit-log append, workbench overwrites).

The patch format is the only contract between the UI and the CLI; either side can be swapped without touching the other. A future helper-server or File-System-Access-API path could write the same patch shape if the two-step ceremony ever becomes a bottleneck.

## Consequences

**Positive**

- No build step. A contributor checking out OCD doesn't run `npm install`; the Reviewer UI is ready to open.
- No framework version drift. A framework adopted in 2026 may be unmaintained by 2030; vanilla JS doesn't have this failure mode.
- The contribution barrier stays low. Anyone with basic web knowledge can read and modify the JS; no React / Vue / Svelte familiarity required.
- The Reviewer UI remains a *local, file-based* tool. It opens from disk in a browser; no dev server required for routine review work.
- File size of generated HTML stays small. A SPA bundles ~50-200KB of framework code before any application code; vanilla JS adds only what the affordance needs.

**Negative**

- Vanilla JS doesn't have reactive data binding; state changes that need to update multiple parts of the DOM require explicit re-render calls. The affordances are simple enough that this is fine, but more elaborate future affordances may strain the approach.
- Component reuse is harder without a framework's component model. The five affordances above are distinct enough that the cost is small; future affordances may want shared structure.
- Testing client-side JS without a framework's test ecosystem is more bespoke. We accept a `jsdom`-based unit-test approach if testing becomes necessary.
- If the Reviewer UI's complexity grows substantially (live multi-user adjudication, real-time agreement scoring, etc.), the floor of vanilla JS will eventually become a ceiling. At that point this ADR can be superseded.

## Alternatives considered

- **Static HTML + Alpine.js / Petite-Vue / htmx (minimal reactive framework).** Considered. Each adds 5-20KB and reactive declarative bindings, with no build step. The trade-off: contributors must learn the framework's syntax (`x-data`, `v-on`, etc.), and the framework itself is one more dependency to track. For the five affordances we need, vanilla JS handles them cleanly; the reactive layer doesn't earn its cost.
- **Single-page application (React, Vue, Svelte).** Rejected. Framework sticky for years; build pipeline; `node_modules`; framework version drift; bundle size. The Reviewer UI is a local audit tool, not a hosted product — the SPA shape is wrong for the surface.
- **Hosted Reviewer service (server-side rendering, real-time multi-user).** Rejected for v1. The Reviewer is one operator working locally; a hosted service is bureaucracy that solves problems we don't have. Could be reconsidered if OCD ever has multiple concurrent Reviewers — a different project at that point.
- **Stick with static HTML only; defer interactivity to a future ADR.** Rejected. The interactive affordances are part of the rearchitecture's built-once scope (ADR-0008); deferring them creates exactly the v2 lane that ADR is written to prevent.
