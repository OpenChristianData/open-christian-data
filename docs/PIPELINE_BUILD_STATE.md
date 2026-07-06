# Schaff-Herzog OCR Pipeline — Build State (2026-06-02)

> **For current NSH pipeline state, read `docs/NSH_PROJECT_STATE.md` (the anchor doc) first.** This
> file is **base-pipeline (S0–S6) built-state detail** captured 2026-06-02 — useful for the stage
> table and the two findings (unweighted S3 reconciler, unwired arch6 LLM-in-loop), which the anchor
> doc summarizes and points back to here. It predates the gold-free corrector build; for module
> status use the canonical tracker `docs/BUILD_PLAN_gold_free_corrector.md` §0.

Current state of the multi-engine OCR reconciliation pipeline, captured because the
arch design map (`ARCHITECTURE_CONTEXT.md`, dated 2026-05-28) is now stale and
understates build progress. This note records what is actually built, tested, and
proven end-to-end, plus two findings that change how the remaining work should be read.

## Stage status

| Stage | Tool | Status |
|---|---|---|
| S0 ingest / bijection | `run_s0_ingest.py` | Built; `reports/ingest/s0_bijection_vol_*.json` for 13 volumes |
| S1 OCR fan-out (5 engines) | `run_ocr_pipeline.py` + `s1_{surya,tesseract,abbyy,kraken,kraken_greek}` | Built + tested |
| S2 rendering | `render_s2.py`, `build_rendering.py` | Built + tested |
| WCT (word-cell table / alignment) | `build_wct.py`, `wct_builder` | Built; reading-order un-tuned (B8-gated) |
| Reconcile (matrix S3) | `reconcile_s3.py`, `reconcile/assemble.py` | Built, but **unweighted** — see below |
| CCEL alignment | `align_ccel_to_wct.py` | Built + tested |
| Measurement (M0–M3 + queue) | `measure_reconciliation.py` | Built; de-circularized 2026-06-02 |
| Review / adjudication | `update_review_state.py`, `apply_review_patch.py`, `bulk_review_writer.py`, `build_gold_sample.py`, `render_review_html.py` | Built (tooling); not yet exercised on a gold set |
| LLM-in-loop (arch6) | `build/lib/llm_evidence_provider.py` (660 lines), `class1_gate.py`, `weak_evidence_table.py` | Built + tested as a library; **not wired into the live reconciliation chain** (gated behind the tuning embargo) |
| Typography / structure (arch8) | `build/lib/typography_snapshot.py` | Built + tested; wired into S2 rendering (`render_s2.py`) |
| Article assembly → `data/` records | `reconcile/assemble.py` (reconcile-internal) | Output schemas (`reconciled_record`, etc.) exist; a page→article→`data/` assembler was not located this session — confirm before relying on it |
| S6 publish | `publish_s6_dryrun.py`, `verify_publish_provenance.py` | Dry-run only; `reports/publish/` empty |

Proven end-to-end on 10 real vol_01 pages this session: 9 S1, 9 S2, reconcile, align,
measure — 0 failures. Full test suite green (2531 passed). 38 schemas now exist. The
build plan's batches (B0–B17) all landed 2026-05-31, so most stages have library code;
`ARCHITECTURE_CONTEXT.md` (2026-05-28) predates that and reads as if nothing is built —
that map is the stale artifact, not the code.

## Finding 1 — the reconciler is an unweighted stub

Across all 1142 positions of `page_0010`, the reconciler's only signal
(`alignment_confidence`) carries **weight 0.0**, so every `total_score` is 0.0. It does
not score or choose between candidate readings. It classifies each position as
`consensus_unconfirmed` (engines agree) or `dispute` (engines differ), records an
advisory pick with no scoring behind it, and routes everything to the review queue.

Consequence: the "chosen" reading on a dispute is arbitrary. On `page_0010`,
`['Abelard', '▲belavd']` recorded `▲belavd` as chosen — not a wrong correction, a
non-decision. **Automatic correction does not happen today; the only working correction
path is human review.** The weight matrix (arch4/arch5) that would actually correct
needs training data, which is the gold set (below). This is a second, independent reason
the M3 "truth-rule" measurement was uninterpretable: there is no trained reconciler to
measure.

## Finding 2 — what the review queue actually contains

Categorizing all ~11,200 reviewer-queue positions across the 10 pages by the *kind* of
difference (an approximate, gold-free heuristic — aggressive-normalized comparison):

- **~77% consensus** — engines already agree, awaiting confirmation. Not errors.
- **~3% cosmetic** — disputes differing only by punctuation / accent / case.
- **~20% genuine** — engines read different letters (the real correction work).

The headline "29% error" (M2) and "~50% WER" (M0) are scored against the CCEL proposal,
which is not ground truth (1951 reprint vs 1908–14 scans, PIPE-29), and are circular
besides. They do not measure OCR quality. The honest signal is the breakdown above:
OCR consensus is strong; the open question is reconciler/correction quality on the ~20%.

## The gold set is load-bearing twice

A small stratified human-adjudicated gold set (~300–500 positions, scoped in
`docs/MEASUREMENT_REFERENCE_OPTIONS.md`) is required for two distinct purposes:

1. **Measurement reference** — the non-circular yardstick to get a real auto-accept
   error rate (the number that decides keep-matrix vs agree→escalate vs verification-spine).
2. **Training data** — the labels that give the weight matrix real weights so the
   reconciler can begin auto-correcting obvious cases.

Until it exists, correction stays 100% manual and the architecture decision stays open.

## Open sequencing question

The correction layers (the weight matrix, and the already-built LLM-in-loop) cannot be
tuned or safely activated until the gold set exists — there is no non-circular reference
to tune against, which is what the tuning embargo encodes. So the gold set is the gating
step before the reconciler can be weighted or the LLM-in-loop wired into the live chain.
Resolve it before investing further in the layers downstream of it.
