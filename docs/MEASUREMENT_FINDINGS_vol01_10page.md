# vol_01 Measurement Findings: 10-Page Run

## Decision Brief

- The 10-page reconciled run is complete (9 pages OCR'd + reconciled + CCEL-aligned, page_0010 reused; 9 S1, 9 S2, 0 failed). The numbers below are measurements, not an architecture decision.
- **The M2 auto-accept and M3 truth-rule headline rates are circular and must not be read as accuracy/error.** An adversarial review (Codex, 2026-06-02) and an independent recomputation confirmed that both are dominated by the aligner's gold-vs-disagreement bucketing, which is itself defined as "CCEL token equals the OCR reading." On gold positions the result is correct by construction; on disagreement positions it is wrong by construction. The pooled "29.0% error" (M2) and "54.9% accuracy" (M3) mostly report the bucket mix, not independent OCR or reconciler quality. See "What M2/M3 measure" below.
- **What does survive the review** and can inform the architecture call: the family-independence result and the calibration result. The five engine lineages resolve to **three independent blocks** — ABBYY and Tesseract collapse together on a *measured* co-error rate of 0.41 (threshold 0.30); both Kraken lineages collapse; Surya stands alone but is borderline (co-error 0.26–0.28 with ABBYY and Tesseract, just under threshold). Kraken is the best-calibrated engine (ECE 0.18); Tesseract and Kraken-Greek are the worst (~0.41).
- A non-circular accuracy answer needs a reference that is not conditioned on OCR agreement: human-adjudicated gold, or an independently aligned reference text. The CCEL proposal alone (1951 reprint vs 1908–14 scans, PIPE-29) cannot provide it.
- The keep-matrix vs agree->escalate vs verification-spine decision is the maintainer's, made on this evidence — not here.

## Run Status

Scope: 10 `vol_01` pages through S1 -> WCT -> reconcile -> adjudication queue, then M0–M3 plus the adjudication queue, scored against the CCEL alignment proposal (`PROPOSAL_NOT_GOLD`).

| Stage | Result |
|---|---|
| S1 OCR (5 engines) | 9 pages produced, 0 failed |
| S2 rendering | 9 produced |
| Reconcile + CCEL align | 9 pages + page_0010 baseline = 10 measured |
| Determinism | The hash-seed nondeterminism fix (`6e90715a`) was verified in a prior session. This run reused page_0010 and skips existing reconciled pages by default (`--force` not passed), so byte-identical reproduction was **not re-verified in this run** — the claim is carried from the prior fix, not re-demonstrated here. |

Engine wall-clock for the live S1 run (9 pages): Surya 1740.4s (the long pole), Kraken 606.1s, Kraken-Greek 548.5s. Tesseract (0.2s) and ABBYY (8.2s) were reused/imported, not run live — their cached sidecars postdate the last parser and schema change, so the reuse is current.

## What M2/M3 Measure (and the circularity)

The scoring reference is built from the alignment proposal's `gold_candidates` *and* `reviewer_queue` ccel_tokens (`measure_reconciliation.py` `_ccel_refs`, lines 197–205). The aligner appends a `gold_candidate` only when the CCEL token equals the OCR reading after normalization (`align_ccel_to_wct.py` line 258); otherwise the position goes to the queue as `ccel_ocr_disagreement` (line 268). The M2 circularity guard (line 328) only excludes positions where CCEL is itself an *attesting family* — it does not neutralize this consensus-conditioned reference.

Consequence, confirmed by recomputation against the artifacts:

| Stratum | M2 rows | M2 errors | M3 rows | M3 wrong |
|---|---|---|---|---|
| gold (CCEL == OCR reading) | 3440 | 9 | 880 | 0 |
| ccel_ocr_disagreement (CCEL != OCR reading) | 1408 | 1396 | 722 | 722 |
| **pooled (headline)** | **4848** | **1405 → 0.2898** | **1602** | **722 → 0.5493 acc** |

- **M3 is fully circular.** Every gold position scores correct (880/880), every disagreement position scores wrong (722/722). The reported 54.9% accuracy is exactly the gold fraction (880/1602); it says nothing about how well the reconciler chooses. The matrix-vs-agree->escalate A/B in this run is not interpretable as reconciler quality.
- **M2 is bucket-dominated.** Only 21 of 4848 positions carry independent signal: 9 gold positions where two independent blocks agreed on a reading *other* than the CCEL-matching one (genuine multi-engine agreement errors), and 12 disagreement positions where the agreed reading matched CCEL anyway. The "29% error" is essentially the disagreement-bucket share (1408/4848 = 29.0%).
- The transcription of these numbers from the JSON is correct; the interpretation in the prior draft was not. Treat M2/M3 as not-yet-answered pending a non-circular reference.

## Page Selection and Coverage

The sample spans the failure surface. Two distinct coverage views matter: **CCEL-align%** = aligned/CCEL tokens (how much of the CCEL text maps to the page) and **CCEL/WCT%** = aligned/WCT positions (how much of the page CCEL actually covers). A high CCEL-align% with a low CCEL/WCT% means CCEL covers only a thin slice of the page.

| Page | Type | CCEL tok | WCT pos | Aligned | CCEL/WCT% | CCEL-align% | Disagreement |
|---|---|---|---|---|---|---|---|
| 10 | body (baseline) | 1073 | 1142 | 846 | 74.1% | 78.8% | 0.501 |
| 37 | footnote | 1048 | 1159 | 828 | 71.4% | 79.0% | 0.860 |
| 82 | Greek | 1027 | 1086 | 732 | 67.4% | 71.3% | 0.835 |
| 90 | Greek | 1331 | 1560 | 855 | 54.8% | 64.2% | 0.800 |
| 136 | Greek + Hebrew | 1103 | 1186 | 862 | 72.7% | 78.2% | 0.519 |
| 137 | Greek-dense | 1042 | 1083 | 586 | 54.1% | 56.2% | 0.762 |
| 241 | Greek-dense | 1069 | 1115 | 849 | 76.1% | 79.4% | 0.604 |
| 256 | Greek | 1058 | 1105 | 726 | 65.7% | 68.6% | 0.800 |
| 300 | body | 1019 | 1052 | 638 | 60.6% | 62.6% | 0.793 |
| 381 | low-quality / light | 158 | 706 | 157 | **22.2%** | 99.4% | 0.880 |

**Alignment-risk pages, not OCR-difficulty pages:**
- **Page 381** aligns 157/158 CCEL tokens (99.4%), but CCEL covers only 22.2% of its 706 WCT positions — 549 positions are `ccel_omits_token`. Any rate computed on page 381 rests on 158 tokens of a much larger page; its 0.88 disagreement is not evidence of OCR difficulty. Flag as coverage-asymmetric.
- **Page 137** is low on both axes (54.1% WCT coverage, 56.2% CCEL-align) — treat as an alignment-risk page too.

The prior draft's edition-offset screen (CCEL-align% vs 60% of median) found no suspects, but that screen is blind to WCT-side coverage. The aligner itself warns gap reasons must not be read as OCR error (`align_ccel_to_wct.py` line 312).

## Measurements

Reference for M0–M2: CCEL ThML page text aligned to WCT, `PROPOSAL_NOT_GOLD`. M3 reference: the existing S3 reconciler `chosen_reading` scored against that same proposal.

### M0 — Single-Best Baseline Quality

Population: engine span records with word geometry and a CCEL-aligned WCT position. Only ABBYY and Tesseract carry word geometry, so only those two are measurable here.

- `tesseract-py314-v1`: N=6710, WER=0.4668, CER=0.5027.
- `ia-abbyy-v1`: N=6615, WER=0.5067, CER=0.5075.

This shares the proposal-not-gold caveat (part of the ~50% is edition difference, not OCR error) and a milder version of the gold-bucket conditioning — read it as a loose bound on single-engine quality, not a clean WER/CER.

### M1 — Confidence Calibration (Expected Calibration Error)

Population: engine span records with raw confidence and a CCEL-aligned WCT position.

| Engine | N | ECE |
|---|---|---|
| `kraken-py312-v1` | 2821 | 0.1779 |
| `surya-py312-v1` | 4604 | 0.2968 |
| `ia-abbyy-v1` | 6605 | 0.3201 |
| `tesseract-py314-v1` | 6710 | 0.4053 |
| `kraken-greek-py312-v1` | 1385 | 0.4140 |

Kraken is the best-calibrated engine; Tesseract and Kraken-Greek are the worst. Unlike the earlier single-page run, Kraken now appears in the WCT and is measurable.

### M2 — Auto-Accept Audit

Headline: N=4848, pooled_error_rate_circular=0.2898, with `circular_subset_present=false` and `circular_subset_excluded_from_headline=true` (CCEL never counted as an attesting family). **But see "What M2/M3 measure": the pooled rate is dominated by the gold/disagreement bucket split, and only ~21 positions carry independent signal.** The defensible reading is narrow: across 10 pages, ~9 positions show two independent family blocks agreeing on a reading that still disagrees with CCEL — i.e. genuine multi-engine agreement errors do exist, but this run cannot put a reliable rate on them.

### M3 — Truth-Rule A/B

Headline: N=1602, matrix-rule pooled_auto_choice_accuracy_circular=0.5493, reviewer_queue 11194; agree->escalate auto-choices=0, queue=1602. **This is circular (gold 880/880 correct, disagreement 722/722 wrong) and is withdrawn as a reconciler-quality measure.** It cannot distinguish the matrix rule from agree->escalate on this run.

### Family Independence

Pairwise co-error (both families wrong *and* identical) over shared CCEL-aligned positions; collapse threshold 0.30:

| Pair | Denominator | Same-wrong | Rate | Verdict |
|---|---|---|---|---|
| abbyy / tesseract | 6246 | 2560 | **0.4099** | dependent → collapse |
| surya / tesseract | 4463 | 1236 | 0.2769 | independent (borderline) |
| abbyy / surya | 4431 | 1142 | 0.2577 | independent (borderline) |
| abbyy / kraken | 2973 | 253 | 0.0851 | independent |
| kraken / tesseract | 3015 | 263 | 0.0872 | independent |
| kraken / surya | 2489 | 172 | 0.0691 | independent |

Result: five lineages resolve to **three independent blocks** — {ABBYY, Tesseract} (a *measured* dependence at 0.41), {Kraken, Kraken-Greek} (one family by design), {Surya}. Surya's independence from the ABBYY+Tesseract block is marginal (0.26–0.28, just under the 0.30 threshold), so the effective independent-vote count is closer to "between 2 and 3" than a clean 3. Independence claims downstream should use the block count, not the engine count, and should note Surya's borderline status.

## Adjudication Queue

Artifact: `reports/measurement/vol_01/adjudication_queue.json`.

- Items: **4198** across 10 pages (~420/page).
- Population: every CCEL-aligned position where engine families disagree, or where engines agree and CCEL dissents.
- Each item carries the source image path, reference bbox, candidate readings, family labels, independent-block labels, and the CCEL proposal value.

## Bugs and Gaps Flushed by Real Data

- **M2/M3 are circular against the CCEL proposal.** The biggest finding: the auto-accept error and truth-rule accuracy are conditioned on the same CCEL==OCR agreement that defines the gold bucket, so they re-report the bucket split rather than measure accuracy. The architecture decision needs a non-circular reference (human-adjudicated gold or independent alignment) before M2/M3 can answer it.
- **5-engine independence is 3-block independence, and Surya is borderline.** ABBYY+Tesseract are measurably dependent (co-error 0.41); Surya's separation from them is marginal (0.26–0.28). Counting five independent votes overstates redundancy; even three is optimistic.
- **CCEL-align% can mask WCT coverage.** Page 381 (22.2% WCT coverage) and page 137 are alignment-risk pages whose disagreement rates should not be read as OCR difficulty.
- **M0 is blind to non-geometry engines.** Only ABBYY and Tesseract carry word geometry, so Surya/Kraken/Kraken-Greek have no single-best WER/CER here.
- **Prior coverage gaps resolved.** The earlier run noted only ~2 pages had CCEL proposals and S2; all 10 now have both, and Kraken — absent from the page_0010 WCT — is now measured and calibration-rankable.

## Verification

- M2/M3 strata, family-independence pairwise rates, and page-381 coverage were independently recomputed from the artifacts (not taken from the harness summary), reproducing the JSON headline values exactly.
- M2 circularity guard confirmed present in code but insufficient (it excludes CCEL-as-attesting-family only, not the consensus-conditioned reference bucket).
- Determinism for this run was **not** re-verified (page_0010 reused; skip-existing default). The claim rests on the prior `6e90715a` verification.
- Test suite (full, from repo root): green at the commit that recorded the prior draft.
