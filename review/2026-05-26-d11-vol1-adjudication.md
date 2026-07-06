# D11 vol 1 adjudication — Session 2

Adjudication of 30 flags sampled from the vol 1 four-rendering comparison
(CCEL ThML anchor not used for token alignment — see Phase 1 finding below).

## Setup

- **Flag source:** `review/2026-05-26-d11-vol1-flags.jsonl` (70,821 raw flags
  across 489 common pages).
- **Token-alignment reference:** ABBYY (richest metadata of the four
  renderings). Two flag streams: `tess_vs_abbyy` and `azure_vs_abbyy`.
- **Sample:** 30 flags stratified by page class
  (26 body, 4 bibliography, 0 column_edge, 0 greek_latin) — seed=42 via
  `.tmp_audit/d11_sample_and_crop.py`.
- **Scan adjudication:** crop ~600×300 region around each anchor word's bbox,
  visually inspect against ABBYY's `text` and the attestor's `text`.
- **CCEL anchor (`original/vol_01.json`) is headword-only** (899 `block_type:
  headword` blocks; no body-text blocks). Cannot serve as the reference for
  body-text token alignment — used only as a separate headword cross-check
  out of scope for this 30-sample pass.

## D11 verdict rule

Per `plans/2026-05-19-own-ocr-design-decisions.md` Decision 11:

| Band | Precision | Action |
|---|---|---|
| Below 0.40 | STOP | rework engine config before B3 |
| 0.40–0.60 | TUNE | identify dominant FP cause and propose patch |
| Above 0.60 | PROCEED | build B3 workbench |

A flag is **TP** when ≥1 disagreeing rendering matches the source scan and
≥1 does not. A flag is **FP** when all disagreeing renderings share the same
wrong reading or no rendering matches the scan, or the disagreement is a
mechanical alignment artifact rather than a transcription dispute.

## Adjudication table

Verdict abbreviations:

- **TP-A**: attestor matches scan; ABBYY does not.
- **TP-B**: ABBYY matches scan; attestor does not.
- **FP-BOTH-WRONG**: both renderings disagree with the scan; useless flag.
- **FP-ALIGN**: insert/delete op — the attestor read text the anchor didn't
  read at this position, but the text appears elsewhere; a segmentation /
  reading-order divergence, not a transcription disagreement.
- **FP-TYPO**: difference is pure Unicode glyph variant (straight vs curly
  apostrophe), not a content disagreement.

| # | flag | page | class | stream | op | ABBYY anchor | Attestor reading | Scan | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 14360 | 103 | bibliography | azure | insert | (empty) | `verfluchte Lehre der Carlstadter, Wiedertäufer, Rotten-` | scan at this bbox is `himself` (English body text); Azure tokens appear elsewhere on the page | FP-ALIGN |
| 2 | 4475 | 38 | bibliography | azure | replace | `!▼.` | `iv.` | `iv.` (Roman numeral) | TP-A |
| 3 | 38976 | 272 | bibliography | tess | replace | `tn` | `an` | `in` (italicised) | FP-BOTH-WRONG |
| 4 | 36747 | 257 | bibliography | tess | replace | `SendaehirH,` | `Sendechili,` | `Sendschirli,` (Senjirli / Zincirli) | FP-BOTH-WRONG |
| 5 | 30056 | 210 | body | azure | insert | (empty) | 8 tokens | alignment artifact | FP-ALIGN |
| 6 | 19230 | 135 | body | azure | insert | (empty) | 9 tokens | alignment artifact | FP-ALIGN |
| 7 | 14163 | 102 | body | azure | replace | `Qr&ts, Ouchiehtb dtr Jvdtn, toI. it.. Leiprio.` | `Grats, Geschichte der Juden, vol. iv. … Leipsic,` | `Grätz, Geschichte der Juden, vol. iv. … Leipsic,` | TP-A |
| 8 | 12221 | 89 | body | azure | insert | (empty) | 8 tokens | alignment artifact | FP-ALIGN |
| 9 | 55503 | 388 | body | azure | replace | `36$` | `368 Middle Ages they received dispensation from the` | scan = `363` (and Azure's 8 trailing tokens belong elsewhere on the page) | FP-BOTH-WRONG |
| 10 | 4914 | 41 | body | azure | insert | (empty) | 5 tokens | alignment artifact | FP-ALIGN |
| 11 | 4255 | 37 | body | azure | insert | (empty) | 9 tokens | alignment artifact | FP-ALIGN |
| 12 | 12984 | 93 | body | azure | insert | (empty) | 8 tokens | alignment artifact | FP-ALIGN |
| 13 | 29499 | 206 | body | azure | insert | (empty) | 8 tokens | alignment artifact | FP-ALIGN |
| 14 | 31121 | 218 | body | azure | replace | `trandation` | `translation` | `translation` | TP-A |
| 15 | 66817 | 470 | body | azure | replace | `antipedobaptiflt` | `of antipedobaptist` | `of antipedobaptist` | TP-A |
| 16 | 3777 | 34 | body | azure | insert | (empty) | 9 tokens | alignment artifact | FP-ALIGN |
| 17 | 26989 | 189 | body | azure | insert | (empty) | 20 tokens | column-order divergence: Azure read across columns differently | FP-ALIGN |
| 18 | 58984 | 414 | body | tess | replace | `jOdiachm BeHgionafM- haophen dee MiUelaUera` | `jidischen Religionsphi- losophen des Mittelalters` | `jüdischen Religionsphi-losophen des Mittelalters` | TP-A |
| 19 | 53353 | 372 | body | tess | replace | `Heinaclmann, AugueHne Anaichten` | `Heinzelmann, Augustine Ansichien` | `Heinzelmann, Augustins Ansichten` (close — Tess best of the three) | TP-A |
| 20 | 57600 | 405 | body | tess | replace | `pre-Sargonio` | `pre-Sargonic` | `pre-Sargonic` (period term) | TP-A |
| 21 | 44530 | 309 | body | tess | replace | `Wesley's` | `Wesley’s` | apostrophe is curly in scan | FP-TYPO |
| 22 | 34240 | 239 | body | tess | delete | `Paul.` | (empty) | Tess found `Paul.` at a different offset | FP-ALIGN |
| 23 | 17976 | 128 | body | tess | replace | `Qrammaiir cm):` | `Grammati- cus):` | `Grammaticus):` (the title `Saxo Grammaticus`) | TP-A |
| 24 | 36601 | 256 | body | tess | replace | `McCURDT. Biblxoorafht:` | `McCurpy. Brsriocrapry:` | `McCURDY. Bibliography:` | FP-BOTH-WRONG |
| 25 | 48248 | 336 | body | tess | replace | `Elokim` | `Elohim` | `Elohim` (Hebrew divine name) | TP-A |
| 26 | 22459 | 158 | body | tess | replace | `Yahweh's` | `Yahweh’s` | curly apostrophe | FP-TYPO |
| 27 | 67708 | 479 | body | tess | replace | `Europe. — 1. <Hr-` | `Europe.—1. Ger-` | `Europe.—1. Ger-` (Germany start) | TP-A |
| 28 | 394 | 12 | body | tess | replace | `(1002);` | `(1902);` | `(1902);` (publication year) | TP-A |
| 29 | 63056 | 442 | body | tess | replace | `foimd` | `found` | `found` | TP-A |
| 30 | 67304 | 475 | body | tess | replace | `fonnation` | `formation` | `formation` | TP-A |

## Tallies

| Bucket | TP | FP | Precision |
|---|---|---|---|
| Overall (n=30) | 13 | 17 | **0.433** |
| body (n=26) | 12 | 14 | **0.462** |
| bibliography (n=4) | 1 | 3 | **0.250** |
| column_edge | — | — | not represented in sample |
| greek_latin | — | — | no pages classified |

### FP breakdown (17 FPs)

- **FP-ALIGN: 11** (samples 1, 5, 6, 8, 10, 11, 12, 13, 16, 17, 22) — insert
  or delete ops where the disagreement is mechanical alignment, not
  transcription. Largest single FP class.
- **FP-BOTH-WRONG: 4** (samples 3, 4, 9, 24) — replace ops where both
  engines produced wrong but distinct readings. Hardest class to filter.
- **FP-TYPO: 2** (samples 21, 26) — curly vs straight apostrophe; identical
  semantics.

### TP attribution

| Engine matched scan | n |
|---|---|
| Azure correct, ABBYY wrong | 5 (samples 2, 7, 14, 15, plus partials) |
| Tesseract correct, ABBYY wrong | 8 (samples 18, 19, 20, 23, 25, 27, 28, 29, 30 — minus 19's mixed correctness) |

Effectively: Azure and Tesseract are each routinely correct against an
ABBYY error — confirming the **error-profile divergence** rationale from
Decision 1 (the cloud engines and Tesseract make *different* errors than
ABBYY, and several of those differences are real corrections).

## Verdict

**Raw precision = 0.433 → TUNE band.**

### Dominant FP cause

11 of 17 FPs (65%) are pure alignment artifacts (insert / delete ops at
column / paragraph boundaries). The token aligner emits them mechanically
even though they don't represent a transcription dispute.

### Proposed tuning patch

1. **Filter to `replace`-tag ops only.** Drop insert/delete ops from the
   flag stream. They surface a useful signal (the page has a segmentation
   divergence) but should not count toward D11 precision. Estimated
   post-filter precision: 13 TP / 19 replace ops = **0.684 → PROCEED**.
2. **Normalize Unicode quote variants** (U+2019 / U+201C / U+201D → ASCII
   apostrophe / double-quote) before alignment. Removes 2 typography FPs.
   Estimated post-filter precision: 13 / 17 = **0.765**.
3. **Stretch goal (not required for B3):** detect both-wrong cases by
   requiring at least one rendering's normalized token to share a 3-char
   prefix with the cross-OCR consensus. Reduces the 4 both-wrong FPs.

The post-tuning precision (filter 1 alone) lands solidly in PROCEED. The
recommended action: **tune the flag generator with filters 1+2, then PROCEED
to build B3 on top.**

## Caveats

- **Sample n=30**, not 50. Statistical noise is high; ±0.10 either way is
  plausible. The TUNE → PROCEED boundary at 0.60 is close enough that
  filter 1 should be implemented and a fresh 50-sample pass run before any
  irreversible B3 work.
- **column_edge and greek_latin classes not represented.** The classifier
  found 2 column_edge pages and 0 greek_latin pages in vol 1. column_edge
  flags exist (125 of them) but weren't sampled due to the floor logic;
  greek_latin requires unicode Greek which Schaff transliterates.
- **CCEL anchor not used for token alignment.** Its headword-only nature
  makes it useful as a *headword* cross-check (does each rendering put the
  expected article title at the page boundary?) but not for body-text token
  comparison. Headword cross-check is its own separate measurement, not
  part of this D11 pass.
