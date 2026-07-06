# A2 Codex Round 1 Audit

**Date:** 2026-05-20
**Scope:** Phase A2 vacuous-pass inventory for `reference/schaff/encyclopedia/1908-1914`
**Independence:** Did not read `audits/A2-claude-round1.md`.

## Decision Brief

- The producer matrix is not clean. `historical_lexicon` and `text_suspicion` crash visibly on all 12 records, but `run_all_producers` converts those crashes into empty warning lists plus stderr.
- The dispatch harness itself exposes one extra issue: isolated `llm_triage` cannot be run with `producers=[llm_triage]` because it consumes `ocr_scanner`, so the per-producer run raises `ProducerContractError` before applicability is checked.
- The biggest vacuous-pass risk is data-shape mismatch. The Schaff files are `reconciled_record` payloads with `blocks`; several producers still inspect legacy `data` or are skipped because the dispatch meta says `resource_type: record`.
- `workbench_pending` is not resolved. The workbench file does not exist. `catalog_pending` is resolved for the current catalog because it has 2 renderings and none has role `pending`.
- Reviewer UI is vacuous for bbox review. It renders block/page controls and scan placeholders, but the records contain 0 bbox regions and there are 0 derived WebP files under the expected review output paths.

## Sources Read

- `plans/2026-05-19-phase1-adversarial-review-and-own-ocr.md`, Phase A2 section.
- `audits/A1-final.md`.
- `build/lib/warning_producers/`.
- `build/tools/reconcile_status.py`.
- `data/reference/schaff/encyclopedia/1908-1914/original/vol_01.json` through `vol_12.json`.
- `build/lib/text_extractor.py`.
- `schemas/v1/reconciled_record.schema.json`.
- Reviewer UI surfaces: `build/tools/render_review_html.py`, `build/lib/ocr_coordinates.py`, `build/tools/bootstrap_renderings.py`, `build/tools/reconcile.py`.

## Producer Inventory

18 producers were discovered. 12 records were tested: `vol_01.json` through `vol_12.json`.

The mandated call shape was:

```python
run_all_producers(record, {"resource_id": work_handle, "resource_type": "record"}, producers=[producer])
```

Stdout and stderr were captured separately per cell. Stdout was empty for every cell. Stderr was non-empty only for `historical_lexicon` and `text_suspicion`; isolated `llm_triage` raised a direct `ProducerContractError` in the harness rather than writing stderr.

## Producer x Record Matrix

Legend: `C` = CORRECT, `E` = EMPTY-OK, `S` = SUSPECT, `M` = MASKED, `V` = CRASH-VISIBLE. Values are warning counts where the producer returned normally.

| Producer | v01 | v02 | v03 | v04 | v05 | v06 | v07 | v08 | v09 | v10 | v11 | v12 | Class |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `attestation_coverage` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `attested_by_reference_resolution` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `coverage` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | C |
| `disagreement_classification` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `historical_lexicon` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | V |
| `language_confidence` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `llm_triage` | - | - | - | - | - | - | - | - | - | - | - | - | M |
| `modernisation_completeness` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `modernisation_coverage_consistency` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `ocr_scanner` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | S |
| `paired_record_invariant` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `paired_with_reference_resolution` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `source_page_coverage` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `structural_integrity` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | S |
| `taxonomy_consistency` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `text_suspicion` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | V |
| `transliteration_completeness` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |
| `within_edition_divergence` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | E |

### Matrix Notes

- `coverage` emitted one warning per record: `coverage_strategy_unset`, severity `info`, `ephemeral: true`.
- `historical_lexicon` and `text_suspicion` returned zero warnings only because the registry caught their exceptions and continued. The cells are not clean passes.
- `llm_triage` is masked by the per-producer harness. It declares `CONSUMES = ["ocr_scanner"]`; running it alone raises `ProducerContractError: llm_triage: unknown upstream producer ocr_scanner`.
- `ocr_scanner` is suspect. With the dispatch meta (`resource_type: record`), it is skipped because its `APPLIES_TO_RESOURCE_TYPES` excludes `record`. With `resource_type: encyclopedia`, it still returns zero on `vol_01.json` because it reads `record.get("data")`, while these records contain `blocks`.
- `structural_integrity` is suspect for the same data-shape reason: it reads `record.get("data")`; these files have `blocks`.

## Record Shape Check

All 12 records have top-level keys `meta`, `blocks`, and `match_explanations`. None has a legacy `data` array.

| Record | Blocks | Data entries |
|---|---:|---:|
| `vol_01.json` | 899 | 0 |
| `vol_02.json` | 895 | 0 |
| `vol_03.json` | 625 | 0 |
| `vol_04.json` | 752 | 0 |
| `vol_05.json` | 760 | 0 |
| `vol_06.json` | 619 | 0 |
| `vol_07.json` | 536 | 0 |
| `vol_08.json` | 618 | 0 |
| `vol_09.json` | 592 | 0 |
| `vol_10.json` | 658 | 0 |
| `vol_11.json` | 525 | 0 |
| `vol_12.json` | 678 | 0 |

## Root Cause: `historical_lexicon`

`historical_lexicon.run()` calls `extract_text(record, SCHEMAS_DIR)`. `extract_text()` calls `effective_resource_type()`. `effective_resource_type()` first checks `record["meta"]["resource_type"]`; the Schaff records do not have it. It then loads `schemas/v1/reconciled_record.schema.json` because `meta.schema_type` is `reconciled_record`, and expects the schema to contain `x-ocd-default-resource-type`. That schema has no such annotation. The producer is therefore trying to use the legacy schema-default path on a new `reconciled_record` shape. Correct fix is not in this pass, but the fix needs to make text extraction understand `reconciled_record` blocks or give reconciled records an explicit effective resource type. A generic `x-ocd-default-resource-type` of `reference` would not be enough unless `extract_text()` also knows how to extract text from `blocks`.

Traceback path confirmed:

```text
run_all_producers() -> producer.run() -> extract_text(record, SCHEMAS_DIR)
-> effective_resource_type() -> ValueError: schemas/v1/reconciled_record.schema.json has no x-ocd-default-resource-type
```

## Root Cause: `text_suspicion`

`text_suspicion.run()` has the same failure path. It calls `list(extract_text(record, SCHEMAS_DIR))`, which reaches `effective_resource_type()` and fails on missing `x-ocd-default-resource-type` in `reconciled_record.schema.json`. The schema/record mismatch is the same: the producer expects resource-neutral text extraction to resolve a legacy resource type, but the live records are reconciled block records. The correct fix should teach the text extractor to handle `reconciled_record` block text directly, or set a real `meta.resource_type` plus an extraction branch that handles `blocks`.

## Workbench and Catalog Zero Check

`review/state/reference/schaff/encyclopedia/1908-1914/workbench.json` does not exist. `reconcile_status.py` treats a missing workbench as `[]`, so `workbench_pending` reports clean without evidence that any workbench item was populated or resolved.

Classification: **INFRASTRUCTURE-GAP**.

`data/reference/schaff/encyclopedia/1908-1914/catalog.json` exists and contains 2 renderings. No rendering has `role == "pending"`. Grep found catalog pending roles are written in `build/tools/ocr_pipeline/build_rendering.py` and cleared/promoted by `build/tools/bootstrap_renderings.py` / `build/tools/reconcile.py`.

Classification: **RESOLVED** for current catalog state.

## Reviewer UI Surface Check

Tool found: `build/tools/render_review_html.py`.

The UI renders split-pane controls for reconciled records, including `.hocr-block` buttons and `.bbox-overlay` containers. It does not render meaningful bbox regions for these volumes because every `source_pages` entry lacks `bbox`, and the expected `scans-derived/<rendering_id>/pN.webp` files are absent under `review/reference/schaff/encyclopedia/1908-1914/original/vol_NN/scans-derived/`.

| Record | Blocks | Source page links | JSON bbox regions | Rendered hOCR buttons | Rendered `data-bbox` attrs | Unique scan pages | Derived WebPs |
|---|---:|---:|---:|---:|---:|---:|---:|
| `vol_01.json` | 899 | 899 | 0 | 899 | 0 | 281 | 0 |
| `vol_02.json` | 895 | 895 | 0 | 895 | 0 | 287 | 0 |
| `vol_03.json` | 625 | 625 | 0 | 610 | 0 | 247 | 0 |
| `vol_04.json` | 752 | 752 | 0 | 742 | 0 | 185 | 0 |
| `vol_05.json` | 760 | 760 | 0 | 754 | 0 | 274 | 0 |
| `vol_06.json` | 619 | 619 | 0 | 615 | 0 | 152 | 0 |
| `vol_07.json` | 536 | 536 | 0 | 528 | 0 | 156 | 0 |
| `vol_08.json` | 618 | 618 | 0 | 603 | 0 | 185 | 0 |
| `vol_09.json` | 592 | 592 | 0 | 592 | 0 | 207 | 0 |
| `vol_10.json` | 658 | 658 | 0 | 650 | 0 | 168 | 0 |
| `vol_11.json` | 525 | 525 | 0 | 518 | 0 | 167 | 0 |
| `vol_12.json` | 678 | 678 | 0 | 671 | 0 | 264 | 0 |

Verdict: **VACUOUS** for bbox review. The UI surface exists, but it has no actual bbox geometry to render for these records.

Rendering `vol_01.json` also emitted the same `historical_lexicon` and `text_suspicion` stderr tracebacks through the warning queue path, so UI rendering currently hides producer failures inside an otherwise generated page.

## Defects Flagged

### High: caught producer crashes masquerade as zero-warning cells

`run_all_producers()` catches the `historical_lexicon` and `text_suspicion` exceptions, writes stderr and dead-letter records, and returns an empty warning list for each crashed producer. Any caller that only reads the returned dict sees a clean zero. This is a silent-success risk unless callers inspect stderr, dead letters, or the upstream `crashed` metadata that is not exposed in the returned result.

### High: text extraction does not support `reconciled_record` block payloads

The live Schaff records are `reconciled_record` payloads with `blocks`. `extract_text()` uses legacy resource-type resolution and legacy extraction branches. That breaks `historical_lexicon` and `text_suspicion`, and likely prevents text-based producers from checking the actual reviewed surface.

### High: Reviewer UI bbox review has zero geometry

The UI emits `hocr-block` controls but no `data-bbox` attributes and no derived scan images. For the Phase A2 question "how many bbox regions does it render per volume?", the answer is zero for all 12 volumes.

### Medium: producer applicability is inconsistent with dispatch/resource shape

`ocr_scanner`, `llm_triage`, `modernisation_completeness`, and `paired_record_invariant` are skipped under `resource_type: record`. That may be correct for the literal dispatch meta, but it is not a meaningful check of Schaff encyclopedia content. Using `resource_type: encyclopedia` makes `ocr_scanner` run, but it still reads `data` and returns zero.

### Medium: missing workbench passes as clean

`reconcile_status.py` returns no pending workbench entries when the workbench file is absent. That is not equivalent to "review workbench resolved". It is an infrastructure gap.

### Medium: isolated dependent producers cannot be probed by the dispatch harness

`llm_triage` cannot be tested with `producers=[llm_triage]` because validation rejects the missing upstream `ocr_scanner`. The probe harness needs either dependency closure or an explicit skipped/dependency-missing classification.

## Convergence Flags

- **CF-1:** Does Claude also classify missing `workbench.json` as infrastructure gap rather than resolved?
- **CF-2:** Does Claude agree the correct text-extraction fix is block-aware `reconciled_record` support rather than only adding `x-ocd-default-resource-type` to the schema?
- **CF-3:** Does Claude count Reviewer UI bbox renderability from actual `data-bbox`/derived assets, or only from block/page buttons?
- **CF-4:** How should the convergence loop classify producers skipped by `resource_type: record` when the tested payload is semantically an encyclopedia reconciled record?

## Verification Commands Run

- Producer matrix: inline Python using `discover_producers()` and per-cell stdout/stderr capture around the mandated `run_all_producers(..., producers=[producer])` call.
- Root-cause traceback: direct `vol_01.json` crasher run and source read of `build/lib/text_extractor.py` plus schema grep for `x-ocd-default-resource-type`.
- Pending counts: inline Python for workbench and catalog.
- Pending writers: `rg -n 'workbench_pending|catalog_pending|"pending"' build -g '*.py'`.
- Reviewer UI: inline Python importing `render_resource_html()` and counting JSON bbox regions, rendered `.hocr-block` buttons, rendered `data-bbox` attributes, unique scan pages, and derived WebP files.
