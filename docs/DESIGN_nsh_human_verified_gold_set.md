# NSH human-verified gold set — shared-sample integration design (2026-06-19)

**Purpose.** Define ONE human-verified Schaff-Herzog ground-truth set that multiple workstreams
consume, so the expensive part — a human reading the true word off a page-image crop — is done once
and serves every consumer. This doc is the integration contract between the **ABBYY-lineage value
study** (`plans/2026-06-19-abbyy-lineage-value-study-design.md`) and the project's existing
**human-corrected-samples / Track C** work.

**Status:** design / handoff. No human review has run yet. The pure-function scoring core for the
ABBYY study is built and green (`build/tools/ocr_pipeline/abbyy_lineage_value_study.py`); the
worksheet-generation + crop + review layer is not built.

---

## 1. The insight that lets the streams overlap

Every consumer wants ground truth **where the OCR engines disagree** — that is where information lives:

| Consumer | What it needs from a verified position | Why hard (disagreement) positions |
|---|---|---|
| ABBYY-lineage study | does an alternate ABBYY scan supply the true word the baseline panel lacks? | the value only appears where the baseline panel fails |
| Track C (corrector transfer-check) | a small SH sample with human-adjudicated true readings, per token class | calibrates whether JE-certified tiers transfer to SH on the hard cases |
| Corrector threshold calibration / M15 | true reading at positions the corrector would act on | the gate is decided on disagreement positions, not trivially-agreed ones |

So a **single stratified sample of hard (panel-disagreement) positions, read once by a human**, is the
shared substrate. The ABBYY study adds extra columns (each alternate scan's reading) to each record;
Track C and the corrector calibration ignore those columns. Same read, three analyses.

## 2. Shared record schema (the contract)

One JSONL record per reviewed position. `reports/nsh-gold/<batch>/positions.jsonl` (gitignored data);
a committed `schemas/v1/nsh_gold_position-v1.schema.json` and a committed summary table.

```
{
  "position_id": "vol_05:page_0100:body:c1:l012:p004",   // stable WCT position key
  "volume": 5, "page": 100, "canonical_leaf_id": 122,     // leaf-key join (R4b)
  "crop_ref": "crops/vol_05/page_0100/p004.png",          // small image of just this word
  "stratum": "degraded",                                  // greek_hebrew|degraded|dense|clean
  "script": "latin",                                      // latin|greek|hebrew|mixed
  "token_class": "proper_name",                           // HR5 class; see open question Q1
  "baseline_candidates": {                                // panel readings (family -> reading)
    "tesseract": "modem", "ia-abbyy-v1": "modem",
    "azure": "modern", "kraken": null
  },
  "alternate_candidates": {                               // ABBYY-study columns; other consumers ignore
    "ia-abbyy-haucgoog-v1": "modern", "ia-abbyy-haucgoog-c2-v1": "modern"
  },
  "true_reading": "modern",                               // BLANK until a human fills it
  "verdict": "U",                                         // U|R|N|easy-correct|easy-wrong (derived)
  "reviewer": "<initials>", "reviewed_at": "2026-06-19T..Z"
}
```

The load-bearing shared fields: `position_id` + `canonical_leaf_id` (the join key), `baseline_candidates`,
`true_reading`, `script`, `token_class`, `stratum`. `alternate_candidates` is the ABBYY study's
private extension; it does not affect the other consumers.

## 3. How each consumer reads a record

- **ABBYY study** — `score_position(baseline_candidates, alternate_candidates, true_reading)` →
  unique / redundant / noise (the built core). Decision: do alternates recover correct words the panel
  lacks (§5 of the study design).
- **Track C** — group by `token_class` x `script`; report human-vs-engine agreement per class; this is
  the transfer-check the corrector plan (`docs/BUILD_PLAN_gold_free_corrector.md` §0b TC) has marked as
  not started.
- **Corrector calibration / M15** — at each position, simulate the tier's chosen reading and compare to
  `true_reading`, stratified by `token_class`; feeds the per-`(level, region_class)` false-correction /
  real-word-error bounds the locked design requires.

## 4. Selection that satisfies all three

1. Build baseline WCT positions for the sample pages (panel = tesseract, ia-abbyy-v1, azure, kraken).
2. `triage_position` → keep **hard** (panel-disagreement) positions as the primary review pool.
3. `stratify` across greek_hebrew / degraded / dense / clean; draw ~150–300 hard positions.
4. Add a smaller **easy** sample (proxy-agreed) to bound triage error (how often "easy" is actually wrong).
5. Tag each with `script` + `token_class` so Track C / calibration can slice without a second review.
6. Emit one crop per position; a human fills `true_reading`; verdicts derive automatically.

Sample volumes: **vol_01 + vol_05** (full baseline panel + alternates present). vol_09 is deferred
(no tesseract/kraken baseline yet).

## 5. Open questions for the human-corrected-samples stream

- **Q1 — token-class taxonomy.** The corrector's HR5 protected classes (proper name, number, date,
  Scripture reference, Greek, Hebrew) must be the `token_class` enum so one review certifies
  protected-class routing too. Confirm the exact label set from the locked design before the schema is
  committed.
- **Q2 — reviewer adjudication for genuinely-ambiguous OCR.** When the crop itself is unreadable (torn /
  blotted), the record needs a `true_reading: null, verdict: illegible` state, not a forced guess —
  mirrors the corrector's "route to human" rather than a fabricated label.
- **Q3 — batch reuse.** Whether the other stream already has partial SH human samples on disk to fold in
  (avoid re-reading positions already adjudicated). Reconcile by `position_id` before drawing.

## 6. Handoff — what's built, what's next, the gate

**Built this session (green):** the ABBYY study's decisive pure-function core —
`triage_position`, `score_position` (unique/redundant/noise), `stratify`, `wilson_ci` —
test-first, 16 tests in `tests/test_abbyy_lineage_value_study.py`.

**Not built (next):**
1. The shared `schemas/v1/nsh_gold_position-v1.schema.json` (after Q1 is answered).
2. The integration layer in `abbyy_lineage_value_study.py`: baseline-position build via
   `wct_builder.build_from_files`, alternate readings via `build/lib/text_alignment`, crop emit,
   worksheet write. **Unverified assumption to check first:** that `build_from_files` runs cleanly on a
   single page with the Set-A engine list — read but not yet executed.
3. The actual human review pass (the gated cost already approved).

**Gate:** no heavy compute and no human-review run until the shared schema is agreed with the
human-corrected-samples stream (so both produce/consume the same records) and Q1–Q3 are settled.

**Related, still gated separately:** the render/WCT full-coverage rebuild
(`docs/RENDER_WCT_full_coverage_plan_2026-06-16.md`) and its six maintainer decisions. The WCT
engine-set decision (include alternate ABBYY scans?) is what this gold set ultimately answers.
