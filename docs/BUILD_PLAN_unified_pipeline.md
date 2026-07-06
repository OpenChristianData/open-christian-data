# Unified Plan — Fidelity IR + Data Structure Redesign

**Status:** Sequencing keystone (authoritative ordering for both plans)
**Date:** 2026-06-18

This document unifies two in-flight plans that overlap and must be sequenced together, not run blind in parallel:

- **Structure redesign** — `docs/DESIGN_data_structure_redesign.md` + `docs/BUILD_PLAN_data_structure_redesign.md` (Codex-reviewed). Reorganizes `data/` to work-kind/author/work and makes registries the source of truth for **envelope metadata**.
- **Fidelity IR** — `plans/2026-06-18-fidelity-ir-architecture-plan.md` (Codex-reviewed; draft for approval; promote to `docs/` on approval). Introduces an intermediate representation (IR) as the source of truth for **record content and structure**, with each output a projection carrying a loss receipt.

**Phase ordering in the two source plans is superseded by §3 here.** They remain the authority for per-phase *task detail*; this doc owns the *sequence and the shared contract*.

## 1. The unifying idea — two source-of-truth layers, one projection

The two plans are not rivals; they own different layers and meet at the output file.

| Layer | Source of truth | Owns |
|---|---|---|
| **Envelope** | registries (`sources/registries/`) | who/what: author, title, dates, tradition, era, audience, `original_language` |
| **Content** | the IR | the faithful text + structure: chapters, sections, footnotes, italics, page refs, apparatus |
| **Acquisition** | the source `config.json` | where it came from: URL, hash, format, edition, date |
| **Vocabulary** | `schemas/v1/` | enum values (tradition, era, audience, work_kind) |

**The output file is the reconvergence point:** `meta` is stamped from the registries; `data` is projected from the IR; a loss receipt declares what the projection dropped. Both plans already use the word *projection* the same way — this is one model, described from two ends.

## 2. The keystone — field ownership + ID scheme (build this FIRST)

This table is the unification. Every field that appears in more than one place gets exactly one owner; overlaps the two plans would otherwise both claim are resolved here.

| Field / aspect | Owner | Resolves |
|---|---|---|
| author name, dates, slug, aliases | authors registry | structure redesign §3.1 |
| work title, slug, publication year, work_kind, tradition, era, audience | works registry | structure redesign §3.2 |
| **`original_language`** | **works registry** | **the Creeds bug** (IR Phase 1.3 hard-codes `"en"`) — fix by setting it in the registry, not the parser |
| acquisition: source_url, hash, format, edition, download_date | source `config.json` | both |
| record text + structure: chapters, sections, footnotes, italics, page refs | the IR | IR plan |
| **`scripture_references`, `related_terms`** (record apparatus) | **IR / parser extraction** (in `data[]`) | **the CE bug** (IR Phase 1.2 empties) — content layer, NOT the registry |
| controlled vocab values | `schemas/v1/` | both |
| book ↔ OSIS mapping | shared normalizer (`build/lib/`) | both |

**ID scheme (one, spanning all layers):**

- `work_id == resource_id` (the envelope key; structure redesign §9-E). One per work; `city-of-god` and `augustine-city-of-god` are a **duplicate to merge to one `work_id`** during the registry pass.
- Record-internal ids (`entry_id`, `document_id`, verse refs) are **content/parser-derived, never path-derived** (structure redesign §9-D). They must be **stable across raw → IR → output** so later structure recovery does not churn citations (IR Phase 2's "stable IDs up front").
- The IR's structural node ids (chapter/section) nest deterministically under `work_id`, so a recovered chapter gets a stable id the first time, not a renumber later.

Deliverable: `docs/OWNERSHIP_AND_IDS.md` (this table, expanded). ~half a day. **Nothing structural commits before it exists.**

## 3. Unified phase sequence

Dependency-ordered. "Source" names which plan owns the task detail.

| # | Phase | Source | Depends on | Why here |
|---|---|---|---|---|
| **U0** | Keystone: ownership + ID scheme (`docs/OWNERSHIP_AND_IDS.md`) | NEW (this doc §2) | — | both plans branch from it; cheap; prevents rival claims on `original_language` and IDs |
| **U1a** | City of God chapter recovery + **dedup the two files** | IR P1.1 | U0 (ID scheme) | live corruption; content-only; can start immediately in parallel |
| **U1b** | Catholic Encyclopedia field population | IR P1.2 | — | live corruption; content-only; fully independent — start immediately |
| **U2** | Fidelity contract (the oracle) | IR P0 | U0 (envelope vs content tagging) | audits + loss receipts check against it |
| **U3** | Envelope registries: classifier, works schema, authors+works in `sources/`, generator | redesign P0–P1 | U0 | the envelope SSOT; required before U4 |
| **U4** | Creeds `original_language` + dropped-metadata fix | IR P1.3 | U3 (registry holds the field) | routes to the registry, not the parser — so registries must exist first |
| **U5** | Audit scripts (structural diff, hardcoded-field, field-coverage, source-completeness) | IR P1 | U2 (contract) | now have a pass/fail spec |
| — | **fork: two tracks share U0 IDs + U3 registries** | | | |
| **U6-A** | IR pilot on City of God → conditional IR rollout | IR P2–P3 | U0, U2 | the multi-week lock-in; format decision (JSON-AST vs TEI-lite) pinned here |
| **U6-B** | metadata-stamp → path migration + sidecars → verification → catechisms pilot → per-category rollout | redesign P2–P6 | U3, U1 (content stable) | the restructure; **runs after content fixes** so the verification baseline is meaningful |
| **U7** | Docs + cutover (README, governance rule, anchor-doc update, status flips) | both | all | merged final phase of both plans |

## 4. What changes in each source plan as a result

- **Structure redesign:**
  - Migration baseline (BUILD_PLAN Phase 4/5) is taken **after** U1/U4, not against today's data — City of God and CE counts change.
  - The metadata-stamp re-homes as the **envelope stage of the IR projection** for any class that goes to IR (U6-A); it stays a standalone post-parser pass for the majority that don't.
  - The verification harness must handle **`data` as a dict (section tree)**, not only a list of records — confirmed in `data/structured-text/city-of-god.json`.
  - `original_language` is explicitly a registry field (closes the overlap with the Creeds fix).
- **Fidelity IR:**
  - The Creeds language fix (P1.3) sets `original_language` in the works registry, not the parser.
  - "Stable IDs up front" (P2) is the same scheme as the redesign's `work_id`/record-id rules — defined once in U0.
  - Promote the plan from `plans/` to `docs/` on approval so both committed plans sit together.

## 5. Open decisions (unchanged, now shared)

- **IR format** — JSON-AST vs TEI-lite. Decided in U6-A on real material (City of God). The 6-month lock-in.
- **Public projection shape** — apparatus inline vs optional sidecars. This directly affects the redesign's layout: sidecar apparatus means a *work folder* may hold `book-01.json` + `book-01.html` + `book-01.loss.json`, which the `work = folder of units` rule already accommodates but should state explicitly.
- **Fidelity tiering** — source-fidelity now / original-edition later; mark known-upstream-loss sources (BSB) so flatness is never read as fidelity.

## 6. The short answer to "what runs first"

`U0` (the keystone contract) gates everything structural and is cheap, so write it first — **while** `U1a`/`U1b` (the two content-only bug fixes) run in parallel, since they depend on nothing. Then `U2` (contract) and `U3` (registries), then the Creeds fix, then the two tracks fork. The file-restructure is deliberately late: it must not run until content and counts are stable.
