# ADR-0020: Withdraw the vanilla-JS mandate; reopen the reviewer-UI shell decision

**Status:** Accepted (2026-07-04). Supersedes ADR-0012.

## Context

ADR-0012 (2026-05-15) mandated that the reviewer UI be static HTML + vanilla JavaScript — no framework, no build step, no `node_modules` — sized against a ~1900-LoC budget. That decision was correct for the surface it described: five interactive affordances over generated per-record HTML.

Three things have changed since:

1. **The zero-runtime-dependency premise is already void.** The TEI-native reviewer (ADR-0019; `plans/2026-07-02-tei-reviewer-architecture-plan.md` §8) adopts two vendored runtime dependencies — CETEIcean (TEI rendering) and OpenSeadragon (scan crop) — as a deliberate exception. The clean "no runtime deps" stance that several of ADR-0012's positive consequences rested on no longer holds.

2. **The surface grew from five affordances to a three-mode, eight-queue reviewer.** The arch7 synthesis (`plans/2026-05-28-arch7-reviewer-synthesis.md`) settles the reviewer as Word / Block / Page modes over eight task queues, backed by an event store. ADR-0012 named this exact scenario as its own supersession trigger: "If the Reviewer UI's complexity grows substantially … the floor of vanilla JS will eventually become a ceiling. At that point this ADR can be superseded."

3. **The maintainability rationale weakened.** ADR-0012's central positive consequence — no build step, so anyone with basic web knowledge can read and modify the JS — assumed human authorship and maintenance. The reviewer UI is now authored and maintained with a capable model in the loop, so "vanilla JS is simplest for a human to maintain" no longer governs the shell choice the way it did.

Separately, the reviewer UI sits over a store it does not yet have. The event ledger, token identification, and TEI materializer (the "spine" — batch 06 of `plans/tei-reviewer/00-execution-plan.md`) are the canonical artifacts; the UI is a swappable shell folded over them. The shell's real requirements — how many modes, what state it holds, what the materialized TEI looks like — are not fully known until the spine exists.

## Decision

**Withdraw ADR-0012's mandate that the reviewer UI be vanilla JavaScript with no framework.** The shell technology is reopened as an explicit open decision, to be made when the reviewer UI is built — after the spine lands — and decided with the store in hand rather than ahead of it.

This is a decision to reopen and defer with criteria, not a decision to adopt a framework. No replacement shell is chosen here.

### What carries forward (still binding)

ADR-0012's persistence and locality model is framework-independent and remains the architecture:

- The reviewer UI stays a **local, `file://`-openable, single-user tool** — no mandatory dev server for routine review, no hosted multi-user service for v1.
- Persistence stays **patch-download then CLI-apply**: the browser accumulates decisions in memory, downloads a review patch, and `apply_review_patch.py` is the single writer (drift-checked). The **review-patch schema is the only contract** between the UI and the CLI; either side can be swapped without touching the other. (The TEI plan amends what CLI apply does — it now also appends ledger events and materializes TEI — but not the contract shape; `plans/2026-07-02-tei-reviewer-architecture-plan.md` §6.)

### What is reopened

The shell: vanilla JS (ADR-0012's choice) versus a minimal reactive layer (Alpine.js / Petite-Vue / htmx) versus a small local single-page application. The choice is made at UI-build time against these criteria:

- **Stays `file://`-openable** — no build step required to run the reviewer for routine review. A build step that *produces* a vendored bundle is acceptable; an install-to-run dependency tree is not.
- **Carries three modes by eight queues** without the state management collapsing into unmanageable manual DOM re-render.
- **Dependency-light and vendored** — any framework is pinned and vendored in-repo alongside CETEIcean and OpenSeadragon, not fetched at runtime.
- **Preserves the patch and persistence contract** above, unchanged.

## Consequences

- ADR-0012's ~1900-LoC / 2500-tripwire budget no longer governs — it was a vanilla-JS-specific guardrail, and the shell it guarded is no longer mandated. A budget appropriate to the chosen shell is set when that choice is made.
- Until the shell is chosen, no reviewer-UI shell code is written. This aligns with build order: the spine (ledger, token identification, materializer) is built and proven first, and the UI is designed against the real materialized TEI and ledger it renders — not against a guess. The Word-mode view batch of the master execution plan is held pending this decision.
- The reviewer's purpose, queues, modes, and event model are unaffected — this ADR concerns the shell only.

## Alternatives considered

- **Keep ADR-0012 as-is.** Rejected: its zero-dependency and human-maintainability premises are void, and its own supersession trigger (complexity growth to a multi-mode surface) has fired.
- **Choose a specific shell now** (commit to a reactive framework or a SPA). Rejected: premature. The shell's requirements are not fully known until the spine exists; choosing now repeats ADR-0012's error of fixing the shell ahead of the store. Decide with evidence, at UI-build time.
- **Withdraw the mandate and reopen with criteria, deferring the positive choice.** Chosen. Lifts the vanilla-JS lock, preserves the persistence and locality invariants that remain correct, and defers the shell choice to the moment it can be made well.
