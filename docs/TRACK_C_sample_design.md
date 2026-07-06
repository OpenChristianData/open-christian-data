# Track C — SH Transfer-Check Sample Design

**Phase A checkpoint. Last updated: 2026-06-10.**

This document is the Phase-A deliverable for Track C (TC row in the build tracker,
`docs/BUILD_PLAN_gold_free_corrector.md`). It covers the inventory, strata mapping,
proposed sample, adjudication workflow, and tooling. Phase B (emitting gold files)
begins only after the maintainer signs off the design below.

---

## 0. Precondition — facsimile must match the WCT leaf (content-position gate)

**Update 2026-06-17.** When this design was written (2026-06-10), vol_01's `page_*.jpg` images
were mis-named from ~p96 onward (the phantom-page corruption), so a human shown `page_NNNN.jpg`
beside a WCT page sampled by `page_id` would have adjudicated against the wrong facsimile —
silently corrupting the one non-circular SH signal this track exists to produce. That corruption
has since been resolved: the leaf-rekey chain keyed every sidecar/WCT page on `canonical_leaf_id`
and content-verified all body sidecars (0 mismatch / 30,429 body sidecars; vol_01 confirmed), and
the duplicate terminal images were re-fetched (see `docs/NSH_PROJECT_STATE.md`,
`docs/NSH_CONTENT_POSITION_VERIFICATION.md`).

The premise is therefore no longer "vol_01 is the worst-corrupted volume" — but the **gate stands
as a hard precondition** rather than an assumption: before Phase B generates the worksheet, the
builder MUST verify that the image displayed for each sampled page is the one the WCT page was
built from. Adjudicate against `canonical_leaf_id`, not the raw `page_NNNN.jpg` filename, and
cross-check the sidecar-embedded running header against the leaf's expected printed page. A
sustained constant offset across a contiguous run is a relabel bug (PIPE-29) — stop and re-verify
before emitting any gold. Do not pool pages whose image↔leaf consistency is unverified.

---

## 1. Inventory

**Disk state verified 2026-06-10.** The task prompt described "10 pages (page_0010–page_0019)";
the actual disk has 478 WCT pages and 498 scan images for vol_01. All numbers below are
from disk ground truth, not the prompt's estimates.

### Original 10-page run (pages 0010–0019)

| page_id | positions | latin | greek | hebrew | unknown | disagree (>1 cand) |
|---------|-----------|-------|-------|--------|---------|---------------------|
| page_0010 | 1,142 | 1,037 | 0 | 0 | 105 | 299 |
| page_0011 | 1,527 | 1,378 | 0 | 1 | 148 | 157 |
| page_0012 | 1,574 | 1,439 | 0 | 0 | 135 | 148 |
| page_0013 | 1,512 | 1,396 | 1 | 0 | 115 | 156 |
| page_0014 | 1,598 | 1,537 | 0 | 0 | 61 | 86 |
| page_0015 | 1,579 | 1,504 | 1 | 1 | 73 | 159 |
| page_0016 | 1,411 | 1,313 | 2 | 0 | 96 | 161 |
| page_0017 | 1,676 | 1,543 | 0 | 0 | 133 | 244 |
| page_0018 | 1,545 | 1,461 | 0 | 0 | 84 | 147 |
| page_0019 | 1,501 | 1,412 | 0 | 1 | 88 | 163 |

### Selected Greek-rich and Hebrew-rich pages

| page_id | positions | latin | greek | hebrew | unknown | disagree |
|---------|-----------|-------|-------|--------|---------|----------|
| page_0241 | 1,115 | 1,004 | **60** | 0 | 51 | 200 |
| page_0349 | 1,694 | 1,491 | **45** | 1 | 157 | 254 |
| page_0381 | 706 | 250 | **20** | **20** | 416 | 74 |
| page_0230 | 1,509 | 1,450 | 9 | 0 | 50 | 87 |
| page_0089 | 1,744 | 1,600 | 0 | 5 | 139 | 267 |

### Corpus totals (all 478 pages)

| metric | count | pct |
|--------|-------|-----|
| Total positions | 744,936 | 100% |
| Latin | 700,936 | 94.1% |
| Unknown | 43,491 | 5.8% |
| Greek | 373 | 0.05% |
| Hebrew | 136 | 0.02% |
| Disagreement (candidate_set > 1) | 70,673 | 9.5% |
| Pages with any Greek | 164 of 478 | — |
| Pages with any Hebrew | 89 of 478 | — |

---

## 2. Strata

The harness (`measure_corrector.py`) reports on `StratumKey(level, protected_class)` pairs.

### Protected classes (from `build/lib/gold_free_corrector/protect.py`)

| protected_class | schema_label | Detection signal |
|-----------------|-------------|------------------|
| `greek` | `greek` | `script.text_level.label = "greek"` |
| `hebrew` | `hebrew` | `script.text_level.label = "hebrew"` |
| `scripture_ref` | `scripture_reference` | `bible_ref_normalizer.extract_refs_from_text` |
| `date` | `date` | date regex fullmatch |
| `number` | `number` | number regex fullmatch (Arabic + Roman numerals) |
| `proper_name` | `proper_name` | capitalization + gazetteer + not sentence-initial |
| _(none)_ | `none` | everything else |

`level` values: `L0` (consensus, no correction), `L1` (column vote), `L2` (lexicality rescore),
`L3` (LM rescore). Determined at corrector runtime — not visible in the WCT pages.

### Transfer gate coverage requirements

| Stratum | SH vol_01 supply | Sample can cover? |
|---------|-----------------|-------------------|
| `(*, none)` Latin unprotected | 700,936 positions | Yes — amply |
| `(*, greek)` | 373 positions | Yes — 40 sampled |
| `(*, hebrew)` | 136 positions | Yes — 20 sampled (near-exhaustive for the corpus) |
| `(*, scripture_reference)` | Requires running M3 on text | Under-powered — see §3 |
| `(*, date)` | Requires running M3 on text | Under-powered |
| `(*, number)` | Requires running M3 on text | Under-powered |
| `(*, proper_name)` | Requires running M3 on text | Under-powered |

**Key limitation for proper_name/number/date/scripture_ref:** these classes are detected
at corrector runtime (not observable from the WCT script label alone). A greek/hebrew split
is directly observable from the WCT `script` field; the other four classes are not. The sample
deliberately over-indexes on disagreement positions (where corrections happen) because those
concentrate the M3 classification and false-correction signal — but individual sub-class
transfer verification within the latin stratum is not achievable at this sample size.

---

## 3. Proposed sample

### Selection rule

| Stratum | Selection criterion | Target N | Actual (seed=42) |
|---------|---------------------|---------|-----------------|
| `latin_disagree` | `script=latin AND candidate_set > 1` | 80 | 80 |
| `latin_agree` | `script=latin AND candidate_set == 1` | 40 | 40 |
| `greek` | `script=greek` | 40 | 40 (38 agree, 2 disagree) |
| `hebrew` | `script=hebrew` | 20 | 20 (all agree — most Hebrew tokens have 1 candidate) |
| `unknown_disagree` | `script=unknown AND candidate_set > 1` | 20 | 20 |
| **Total** | | **200** | **200** |

Pool: all 478 vol_01 WCT pages (subject to the §0 content-position gate — each sampled page's
facsimile must be confirmed to match its `canonical_leaf_id` before it enters a worksheet).
Random sample with `seed=42` for reproducibility.
Greek drawn preferentially from page_0241 (60 available) and page_0349 (45 available).
Hebrew drawn from page_0381 (20 available) — near-exhaustive for that page.

### Gold directory

```
data/gold/sh_transfer_check/
```

One file per WCT page that has human-adjudicated positions:
`data/gold/sh_transfer_check/<page_id>.gold.json`

The proposed sample spans approximately 15–20 distinct pages (distributed across the
478-page corpus plus the 3 targeted rich pages). The exact page list is fixed by seed=42
and visible in `plans/track_c_worksheet_sample.csv`.

### Power statement

**What 200 positions can conclude:** At N=80 latin-disagree positions, a false-correction
rate of 5% is detectable at >98% power (P(observe 0 | FCR=5%) = 0.95^80 = 1.7%). For the
greek stratum (N=40), the same threshold applies at ~96% power. Zero observed false corrections
at these Ns gives a 95% upper-confidence bound of ~3.7% (latin-disagree) and ~7.2% (greek).

**What it under-powers:**
- Individual latin protected-class sub-strata (proper_name, number, date, scripture_ref):
  no sub-class breakdown — depends on M3 runtime classification, not pre-selectable.
- Hebrew rate estimation (N=20; 95% UCB ~14% at 0 observed errors).
- Full statistical certification: `ceil(log(0.05)/log(0.999)) = 2,995` positions for
  95% upper bound < 0.1% (from BUILD_SPEC §4). This sample is a **transfer check** —
  it validates that the JE-certified mechanism does not visibly degrade on SH. Full
  per-stratum certification happens at M15 after U11 measurement.

---

## 4. Adjudication workflow

### Human task per row

1. Open `plans/track_c_worksheet_sample.csv` (UTF-8 CSV; editable in Excel, LibreOffice, or any text editor).
2. For each row, locate the token in the scan image:
   - `scan_path` — path to the page scan (relative to repo root)
   - `bbox_x`, `bbox_y`, `bbox_w`, `bbox_h` — pixel bounding box of the token
3. Read the token directly from the scan image.
4. Type the reading into the `gold_text` column.
5. If the token cannot be read confidently, **leave `gold_text` blank** — do not guess, do not copy from `engine_guesses_do_not_copy`.
6. `engine_guesses_do_not_copy` shows what the OCR engines produced — use it to locate the token in the scan, never as a source for `gold_text`.
7. Save as UTF-8 CSV.

### Phase B command (after adjudication is complete)

```powershell
py -3 build/tools/ocr_pipeline/emit_track_c_gold.py `
    --worksheet plans/track_c_worksheet_sample.csv `
    --gold-dir data/gold/sh_transfer_check
```

The emitter writes one `.gold.json` per page, validates each file, and reports filled vs
omitted positions.

---

## 5. Tooling landed

| File | Purpose | Test file |
|------|---------|-----------|
| `build/tools/ocr_pipeline/build_track_c_worksheet.py` | Samples WCT positions, emits adjudication CSV | `tests/test_track_c_worksheet.py` |
| `build/tools/ocr_pipeline/emit_track_c_gold.py` | Converts completed worksheet -> `.gold.json` + validates | `tests/test_track_c_emitter.py` |
| `plans/track_c_worksheet_sample.csv` | Proposed 200-position worksheet (blank `gold_text`) | — |

### Test inventory (44 tests, all passing)

**`tests/test_track_c_worksheet.py`** (26 tests):
- `TestBuildWorksheetRow`: required columns present; gold_text always blank regardless of
  candidate count, agreement level, or all-engine consensus (3 cases enforcing the
  non-circularity invariant); engine guesses populated/empty; script label extraction;
  bbox fields; position/page/scan_path correctness
- `TestGetScriptLabel`: text_level precedence over image_level; image_level fallback;
  string script; missing script → `unknown`; None script → `unknown`
- `TestGetCandidateReadings`: multiple candidates; single candidate; empty set; dedup;
  raw_reading vs candidate_key precedence; fallback to candidate_key
- `TestSamplePositions`: stratum counts respected; gold_text blank invariant across
  all sampled rows; Greek positions included; capped at available supply

**`tests/test_track_c_emitter.py`** (18 tests):
- `TestEmitGoldPage`: positions key present; filled positions included with correct text;
  blank gold_text omitted (core non-circularity invariant); whitespace-only omitted;
  engine guesses never bleed into gold_text; all-blank produces empty dict; gold_text
  stripped; only "positions" key in output
- `TestValidateGoldFile`: valid file passes; missing positions key raises; empty gold_text
  raises; missing gold_text key raises; harness loader roundtrip (reproduces
  `measure_corrector.py` lines 190–192 exactly)
- `TestEmitGoldCorpus`: groups by page_id; all-blank page produces no file; written files
  pass validation; JSON structure exact; blank positions within multi-position page excluded

### Fast suite result

44/44 new tests pass. Pre-existing baseline preserved (2,575 passing; no new failures
attributable to these changes). Pre-existing flaky failures in `test_s1_surya_runner.py`
pass in isolation — test-interaction issue, unrelated.

---

## 6. Decision for the maintainer

The design is ready. One question before starting adjudication:

**Accept this 200-position stratified sample (80 latin-disagree / 40 latin-agree / 40 Greek /
20 Hebrew / 20 unknown-disagree, from the full 478-page vol_01 corpus, seed=42)? Or adjust N,
strata weights, or page scope?**

Trade-offs:
- **Larger N (e.g. 400):** detects 1–2% false-correction rates; human burden doubles.
- **Smaller N (e.g. 100):** faster adjudication; Greek stratum under-powered (N=20, UCB widens to ~14%).
- **Restrict to pages 0010–0019 only:** drops Greek to 5 positions and Hebrew to 3 — insufficient
  for those strata. Not recommended.
- **Current (200):** a practical first-pass transfer check. If U11 shows a concerning SH delta,
  expand the gold set before M15.

If the design is acceptable: open `plans/track_c_worksheet_sample.csv`, adjudicate, save, then
run the Phase B command in §4.
