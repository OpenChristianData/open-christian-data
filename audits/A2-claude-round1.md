# Phase A2 — Claude audit (round 1)

**Work handle:** `reference/schaff/encyclopedia/1908-1914`
**Records:** 12 × `data/reference/schaff/encyclopedia/1908-1914/original/vol_NN.json`
**Producers:** 18 (from `build/lib/warning_producers/`)
**Date:** 2026-05-20
**Status:** post-fix run (crashers resolved before audit)

---

## Fix applied before this audit

**File:** `build/lib/text_extractor.py` — `extract_text()`

Both `text_suspicion` and `historical_lexicon` crashed on all 12 volumes with:

```
ValueError: schemas/v1/reconciled_record.schema.json has no x-ocd-default-resource-type
```

Root cause: `effective_resource_type()` loads the record's schema and reads `x-ocd-default-resource-type`. `reconciled_record.schema.json` intentionally omits that key (it is a generic container, not a typed resource). The crash was caught by `run_all_producers()`'s exception handler, which logs to stderr and sets `upstream_outputs[pid] = {"warnings": [], "crashed": True}` — but `results[pid]` stays `[]`. This is **MASKED** behavior: the producer appears to have run and found nothing, when it crashed before any logic executed.

**Fix:** Guard in `extract_text()` catches `ValueError` from `effective_resource_type()` and returns an empty iterator. The fix aligns `text_suspicion` and `historical_lexicon` with other schema-type-guarded producers: they silently yield nothing for records without a text-extraction contract.

Post-fix tests: 45 passed (all `text_extractor`, `text_suspicion`, `historical_lexicon` tests), 0 failures.

---

## Producer × record matrix

18 producers × 12 records. `coverage` is the only producer that returns a non-empty result. Columns below show vol_01 representative status; pattern holds for all 12 unless noted.

| Producer | vol_01 | All 12 | Classification | Notes |
|---|---|---|---|---|
| `attestation_coverage` | OK:0 | OK:0 | EMPTY-OK | Checks structural_disagreements + attested_by; vol_01 has 0 structural_disagreements |
| `attested_by_reference_resolution` | OK:0 | OK:0 | SUSPECT | Exits at line 28 — `meta.get("catalog")` absent in invocation meta; logic never runs |
| `coverage` | OK:1 | OK:1 each | **CORRECT** | 1 real warning: `coverage_strategy_unset` (info) on every volume |
| `disagreement_classification` | OK:0 | OK:0 | EMPTY-OK | vol_01 has 0 total disagreements across 899 blocks |
| `historical_lexicon` | OK:0 | OK:0 | EMPTY-OK (was MASKED) | Post-fix: gracefully skips reconciled_record |
| `language_confidence` | OK:0 | OK:0 | EMPTY-OK | No `und`-language blocks, no sub-threshold confidence scores |
| `llm_triage` | OK:0 | OK:0 | SUSPECT | Upstream `ocr_scanner` yields no candidates (no config stem for reconciled_record); triage never fires |
| `modernisation_completeness` | OK:0 | OK:0 | EMPTY-OK (filtered) | Schema guard at line 56: exits for non-`modernised_record`; correct |
| `modernisation_coverage_consistency` | OK:0 | OK:0 | SUSPECT | Requires `catalog` + `original_records`/`modernised_records` in meta; all absent |
| `ocr_scanner` | OK:0 | OK:0 | EMPTY-OK | `_resolve_config_stem()` returns None for reconciled_record; correct skip |
| `paired_record_invariant` | OK:0 | OK:0 | EMPTY-OK (filtered) | Schema guard: exits for non-`modernised_record`; correct |
| `paired_with_reference_resolution` | OK:0 | OK:0 | EMPTY-OK | No `paired_with` in record.meta; correct skip |
| `source_page_coverage` | OK:0 | OK:0 | EMPTY-OK | All 899 blocks have source_pages covering pd_anchor (`ccel-thml`) |
| `structural_integrity` | OK:0 | OK:0 | SUSPECT | Checks `record.get("data")`; reconciled_record uses `blocks[]` not `data[]`; exits line 45 |
| `taxonomy_consistency` | OK:0 | OK:0 | EMPTY-OK (filtered) | No `resource_type` override in record.meta; correct skip |
| `text_suspicion` | OK:0 | OK:0 | EMPTY-OK (was MASKED) | Post-fix: gracefully skips reconciled_record |
| `transliteration_completeness` | OK:0 | OK:0 | EMPTY-OK | No blocks with Hebrew/Greek/Aramaic source-script characters |
| `within_edition_divergence` | OK:0 | OK:0 | SUSPECT | Requires `meta.get("renderings")` list with ≥2 entries; absent in invocation meta |

**Summary:** 1 CORRECT, 10 EMPTY-OK (including 2 formerly MASKED), 5 FILTERED-OK, 5 SUSPECT. 0 crashes post-fix.

### SUSPECT detail

All five SUSPECT producers return `{"warnings": []}` without executing their core logic. They are not vacuous by accident — each has a specific guard that exits early due to missing context in the invocation meta:

| Producer | Guard condition | Missing context |
|---|---|---|
| `attested_by_reference_resolution` | `meta.get("catalog")` absent | No catalog injected |
| `structural_integrity` | `record.get("data")` not a list | reconciled_record uses `blocks[]` |
| `within_edition_divergence` | `len(meta.get("renderings")) < 2` | No renderings in meta |
| `modernisation_coverage_consistency` | `catalog` + `original_records` absent | No catalog/record paths in meta |
| `llm_triage` | `ocr_scanner` upstream has no candidates | Follows from `ocr_scanner` skip |

These producers are **not wrong** — they have valid reasons to exit early. The concern is that no code ever signals "this producer cannot fire for this record type", so a reviewer looking at the zero-warning output cannot distinguish a genuine pass from a structural never-fire.

---

## Workbench pending — classification

`review/state/reference/schaff/encyclopedia/1908-1914/workbench.json` — **does not exist**.

`reconcile_status.py:_workbench_pending()` reads this file; returns `[]` if missing. `workbench_pending` is **NEVER-POPULATED** for this work.

**Root cause:** `workbench.json` is populated by `build/tools/apply_review_patch.py` when a reviewer adjudicates a cross-rendering disagreement. A disagreement requires two renderings to diverge. Schaff-Herzog has one pd_anchor rendering (`ccel-thml`) and one pd_attestor (`ia-ocr`). The reconciler aligns them but no reviewer decisions have been recorded. Without a decision record, the file is never created.

**Classification: NEVER-POPULATED.** Infrastructure is correct; input state has not reached the threshold that would populate it.

---

## Catalog pending — classification

`catalog.json` has 2 renderings:
- `ccel/schaff/encyclopedia/1908-1914/thml` (role: `pd_anchor`)
- `ia/schaff/encyclopedia/1908-1914/ocr` (role: `pd_attestor`)

Neither has `role: "pending"`. `catalog_pending` returns `[]`. **EMPTY-OK** — correct.

---

## Reviewer UI surface check

**File:** `review/reference/schaff-herzog-encyclopedia.html`

Counts:
- `data-bbox` attributes: 0
- `hocr-block` elements: 0
- `bbox-overlay` elements: 0
- `scans-derived/` WebP images: none found

**Classification: VACUOUS.**

`render_review_html.py` emits `data-bbox` attributes from `source_pages[].bbox` in blocks. Vol_01 blocks have `source_pages` with rendering IDs but no `bbox` dicts. Bbox coordinates require the scans-derived pipeline (Phase B: own OCR), which has not run. Without scan images and bbox coordinates, the Reviewer UI renders text only — zero interactive bbox regions.

This is expected, not a regression. The UI surface is structurally sound; it is waiting for Phase B input.

---

## Historical dead-letter evidence

`review/dead-letter/reference/schaff/encyclopedia/1908-1914.jsonl` confirms the pre-fix crash history:

- `text_suspicion`: 196 crash entries (all `ValueError: reconciled_record.schema.json has no x-ocd-default-resource-type`)
- `historical_lexicon`: 196 crash entries (same)
- 11 other producers: 13 entries each — `FileNotFoundError` in `_write_producer_metrics()` when creating the metrics output path for a slash-containing `resource_id`. Directories now exist from prior runs; this no longer triggers.

---

## Defects

| Severity | ID | Description |
|---|---|---|
| HIGH | A2-D01 | 5 SUSPECT producers have no schema-type guard — cannot signal "does not apply to reconciled_record". Currently indistinguishable from genuine zero-warning passes. |
| MEDIUM | A2-D02 | `structural_integrity` checks `data[]` not `blocks[]`. It can never fire for any reconciled_record regardless of actual structural problems. |
| MEDIUM | A2-D03 | `_write_producer_metrics()` does not create parent directories before writing. Historically caused FileNotFoundError for slash-containing resource IDs (mitigated by now-existing dirs; not permanently fixed). |
| LOW | A2-D04 | `coverage_strategy_unset` fires as info on every volume. The strategy field is genuinely unset in these records' meta. Not a bug, but worth documenting before bulk resolution. |
| INFO | A2-D05 | Reviewer UI is VACUOUS — expected until Phase B (own OCR) produces scans-derived images + bbox coordinates in source_pages. |
| INFO | A2-D06 | workbench.json NEVER-POPULATED — expected until a second rendering produces cross-rendering disagreements requiring adjudication. |

---

## Convergence flags for Codex

1. **SUSPECT count** — does the independent pass agree on 5 SUSPECT producers? Or does Codex identify the same five via a different path?
2. **`structural_integrity` scope** — Codex should confirm whether this producer is designed to apply to `blocks[]`-style records in future or is legitimately commentary/encyclopedia-only.
3. **`_write_producer_metrics` bug** — does Codex find the same FileNotFoundError pattern in the dead-letter and trace it to the same code path?
4. **Fix correctness** — does Codex agree the `try/except ValueError` guard in `extract_text()` is the right fix scope (rather than fixing `effective_resource_type` itself or adding a guard in each producer)?
