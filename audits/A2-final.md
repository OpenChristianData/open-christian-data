# Phase A2 — Final audit

**Work handle:** `reference/schaff/encyclopedia/1908-1914`
**Producers:** 18 | **Records:** 12 vol_NN.json
**Claude audit:** `audits/A2-claude-round1.md` (post-fix)
**Codex audit:** `audits/A2-codex-round1.md` (pre-fix, isolated-producer harness)
**Date:** 2026-05-20

---

## Decision brief

1. **Two crashers fixed.** `text_suspicion` and `historical_lexicon` crashed on all 12 volumes (MASKED pre-fix). Fix: guard in `text_extractor.py:extract_text()` catches `ValueError` from `effective_resource_type()` and returns an empty iterator. Both producers now return EMPTY-OK post-fix.
2. **5 producers SUSPECT.** They exit before executing their core logic on any reconciled_record. No schema-type guard documents this. A clean zero-warning result is indistinguishable from a genuine pass.
3. **No warnings from any domain logic.** The only producer that fires is `coverage` (one info-severity `coverage_strategy_unset` per volume), which is not domain checking.
4. **Reviewer UI is VACUOUS.** Zero bbox regions, zero scan images — by design until Phase B.
5. **Workbench NEVER-POPULATED.** Requires Phase B cross-rendering disagreements. Catalog is RESOLVED.

---

## Convergence table — Claude vs Codex

Both passes ran independently. Codex ran the pre-fix code using isolated per-producer harness; Claude ran post-fix using full pipeline.

| Producer | Claude | Codex | Agreed? | Note |
|---|---|---|---|---|
| `attestation_coverage` | EMPTY-OK | E | AGREE | |
| `attested_by_reference_resolution` | SUSPECT | E | **DIVERGE** | Claude: `meta.catalog` absent → guard exits. Codex: called it EMPTY-OK without flagging early exit. |
| `coverage` | CORRECT | C | AGREE | 1×info per volume both passes |
| `disagreement_classification` | EMPTY-OK | E | AGREE | |
| `historical_lexicon` | EMPTY-OK (was MASKED) | V (crash-visible) | AGREE (temporal) | Codex pre-fix: correct crash ID. Claude post-fix: confirms fix works. |
| `language_confidence` | EMPTY-OK | E | AGREE | |
| `llm_triage` | SUSPECT | M (masked) | PARTIAL | Codex isolated run → ProducerContractError. Full-pipeline run → SUSPECT (upstream ocr_scanner yields no candidates). Both agree: never exercises triage logic here. |
| `modernisation_completeness` | EMPTY-OK (filtered) | E | AGREE | Schema guard correct |
| `modernisation_coverage_consistency` | SUSPECT | E | **DIVERGE** | Claude: catalog + records absent → guard exits. Codex: called E without flagging. |
| `ocr_scanner` | EMPTY-OK | S | **DIVERGE** | Claude: `_resolve_config_stem` returns None → correct skip. Codex: reads `data[]`, never sees `blocks[]`. Both correct; different guard layers. |
| `paired_record_invariant` | EMPTY-OK (filtered) | E | AGREE | Schema guard correct |
| `paired_with_reference_resolution` | EMPTY-OK | E | AGREE | |
| `source_page_coverage` | EMPTY-OK | E | AGREE | All 899 blocks have source_pages |
| `structural_integrity` | SUSPECT | S | AGREE | Both: reads `data[]`, reconciled_record uses `blocks[]` |
| `taxonomy_consistency` | EMPTY-OK (filtered) | E | AGREE | |
| `text_suspicion` | EMPTY-OK (was MASKED) | V (crash-visible) | AGREE (temporal) | Same as historical_lexicon |
| `transliteration_completeness` | EMPTY-OK | E | AGREE | |
| `within_edition_divergence` | SUSPECT | E | **DIVERGE** | Claude: `meta.renderings` absent → guard exits immediately. Codex: called E without flagging. |

**Convergence divergences (4):** `attested_by_reference_resolution`, `modernisation_coverage_consistency`, `within_edition_divergence`, `ocr_scanner`. The first three are classification judgment calls (SUSPECT vs EMPTY-OK) rather than factual disagreements — both audits observed the same guard firing; they differ on whether an early-exit guard warrants SUSPECT. Reconciled below.

---

## Reconciled matrix (authoritative)

Post-fix, full-pipeline, classification agreed between both passes or resolved below.

| Producer | Status | Evidence |
|---|---|---|
| `attestation_coverage` | EMPTY-OK | 0 blocks with structural_disagreements (vol_01: 899 blocks, 0 structural_disagreements) |
| `attested_by_reference_resolution` | **SUSPECT** | Guard fires on missing `meta.catalog` — resolution: Codex under-classified; this is structurally never-fireable for Schaff with current invocation |
| `coverage` | **CORRECT** | `coverage_strategy_unset` (info) — 1×per volume, all 12 volumes |
| `disagreement_classification` | EMPTY-OK | 0 disagreements in blocks (vol_01: 0 total) |
| `historical_lexicon` | EMPTY-OK (post-fix) | pre-fix: MASKED (crash on all 12); fix confirmed by 45-test suite |
| `language_confidence` | EMPTY-OK | No blocks with `language==und` or sub-threshold confidence |
| `llm_triage` | **SUSPECT** | Full pipeline: ocr_scanner returns no candidates; triage exits line 80. Isolated: ProducerContractError. Either way, never exercises triage logic |
| `modernisation_completeness` | EMPTY-OK (filtered) | Schema guard: exits for non-`modernised_record` — correct |
| `modernisation_coverage_consistency` | **SUSPECT** | Guard fires on missing `catalog` + `original_records` in meta — same resolution as `attested_by_reference_resolution` |
| `ocr_scanner` | EMPTY-OK | `_resolve_config_stem()` returns None for reconciled_record — correct skip via config layer, not data-shape check |
| `paired_record_invariant` | EMPTY-OK (filtered) | Schema guard: exits for non-`modernised_record` — correct |
| `paired_with_reference_resolution` | EMPTY-OK | No `paired_with` in record.meta — correct skip |
| `source_page_coverage` | EMPTY-OK | All 899 blocks have source_pages covering `ccel-thml` pd_anchor |
| `structural_integrity` | **SUSPECT** | Reads `record.get("data")` — reconciled_record has `blocks[]` not `data[]`; exits line 45 always |
| `taxonomy_consistency` | EMPTY-OK (filtered) | No `resource_type` override — correct skip |
| `text_suspicion` | EMPTY-OK (post-fix) | pre-fix: MASKED (crash on all 12); fix confirmed |
| `transliteration_completeness` | EMPTY-OK | No source-script blocks in vol_01 (Schaff is predominantly Latin-alphabet) |
| `within_edition_divergence` | **SUSPECT** | Guard fires on `len(renderings) < 2`; `meta.renderings` absent in invocation — never fires for any reconciled_record with current call shape |

**Final counts:** 1 CORRECT, 9 EMPTY-OK, 3 EMPTY-OK (filtered/schema-guarded), 5 SUSPECT, 0 CRASH post-fix.

---

## Fix scope — Claude/Codex divergence

Codex's preferred fix is block-aware text extraction (teach `extract_text()` to handle `reconciled_record` blocks). Claude applied the minimal guard (catch ValueError, return empty iterator).

**Resolution:** both are correct at different scopes.

- The guard is the right Phase A2 fix: it stops MASKED behavior without requiring new text extraction design. `text_suspicion` and `historical_lexicon` operate on `data[]` entries (encyclopedia terms, commentary text); they have no logic for `blocks[]` anyway — even if the crash were fixed by other means, they'd yield nothing. The guard documents this explicitly.
- Block-aware text extraction is the right Phase B/C fix: it enables text-based producers to analyze reconciled block content. This requires new extraction logic (`_extract_reconciled_record()`) plus producer logic updates. Out of Phase A2 scope.

The guard comment in `text_extractor.py` already notes: "Schema has no x-ocd-default-resource-type (e.g. reconciled_record). Text extraction is not defined for this schema type — yield nothing." That framing is the correct bridge between the phases.

---

## Workbench and catalog

| Dimension | Status | Classification | Notes |
|---|---|---|---|
| `workbench_pending` | 0 (file absent) | NEVER-POPULATED | `review/state/reference/schaff/encyclopedia/1908-1914/workbench.json` does not exist. Written by `apply_review_patch.py` after cross-rendering disagreements — none yet. |
| `catalog_pending` | 0 | RESOLVED | 2 renderings (pd_anchor, pd_attestor); 0 with `role: pending`. Correct. |

Both passes agree.

---

## Reviewer UI

`review/reference/schaff-herzog-encyclopedia.html` — **VACUOUS**.

| Metric | Count |
|---|---|
| `data-bbox` attributes | 0 |
| `hocr-block` elements | 0 |
| Derived WebP images | 0 |
| Blocks with source_pages | 8,957 (all 12 volumes) |
| JSON bbox regions in blocks | 0 |

Both passes agree. `render_review_html.py` emits `data-bbox` from `source_pages[].bbox`. The reconciled blocks have `source_pages` with rendering references but no `bbox` dicts. Bbox coords require the scans-derived pipeline (Phase B: own OCR). Expected, not a regression.

---

## Defects

| ID | Severity | Description | Carry-forward |
|---|---|---|---|
| A2-D01 | HIGH | 5 SUSPECT producers (`attested_by_reference_resolution`, `structural_integrity`, `within_edition_divergence`, `modernisation_coverage_consistency`, `llm_triage`) have no schema-type guard. Zero-warning output is indistinguishable from genuine pass. | Phase B |
| A2-D02 | HIGH | `structural_integrity` reads `data[]` — can never check block-based records. Should either add `blocks[]` support or an explicit `reconciled_record` guard with SKIP status. | Phase B |
| A2-D03 | MEDIUM | Text extraction for reconciled_record blocks not implemented. `text_suspicion` and `historical_lexicon` are structurally excluded from block text analysis. Guard is correct minimal fix; block extraction is Phase B. | Phase B |
| A2-D04 | MEDIUM | `_write_producer_metrics()` does not create parent dirs for slash-containing `resource_id`. Pre-existing crash history in dead-letter (11 producers × 13 entries). Currently mitigated by existing dirs — not permanently fixed. | Phase B |
| A2-D05 | LOW | `coverage_strategy_unset` info fires on all 12 volumes. Not a bug; the strategy field genuinely unset. Needs bulk resolution before warning counts are meaningful for coverage analysis. | Phase B |
| A2-D06 | INFO | Reviewer UI VACUOUS — expected until Phase B (own OCR) produces bbox coords + scan images. | Phase B |
| A2-D07 | INFO | Workbench NEVER-POPULATED — expected until second rendering produces cross-rendering disagreements. | Phase B |

---

## Phase A2 exit status

Exit criterion from `plans/2026-05-19-phase1-adversarial-review-and-own-ocr.md`: complete vacuous-pass inventory, fix crashers, produce this audit.

| Item | Status |
|---|---|
| Producer × record matrix (18×12) | DONE |
| Root-cause `text_suspicion` + `historical_lexicon` | DONE |
| Fix applied and tested (45 tests pass) | DONE |
| Workbench/catalog check | DONE |
| Reviewer UI surface check | DONE |
| `audits/A2-claude-round1.md` | DONE |
| `audits/A2-codex-round1.md` | DONE |
| `audits/A2-final.md` (this file) | DONE |
| Codex/Claude convergence | DONE (4 minor divergences resolved) |

**Phase A2 complete.** All exit criteria met. Phase B entry point: implement block-aware text extraction + scans-derived pipeline.
