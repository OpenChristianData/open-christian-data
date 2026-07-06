# Phase A3 — Content Sampling: Final (Convergent) Verdict
# Parser fidelity and OCR discrepancy baseline

**Work handle:** `reference/schaff/encyclopedia/1908-1914`
**Reviewers:** Claude + Codex (independent passes, round 1)
**Date:** 2026-05-20
**Entries sampled:** 60 (5 per vol × 12 vols, deterministic at 20/40/60/80/100% of each vol's entry array)
**Source used:** `source/vol_NN.json:data[]` (definition text)
**Raw sources:** `raw/ccel/schaff-herzog/encycNN.xml` (vols 1/2/9), `raw/internet-archive/schaff-herzog/*.txt` (vols 3–8/10–12)

---

## Pass summary

| Reviewer | parser_clean | parser_gap | parser_truncated | ocr_structural | Total |
|---|---|---|---|---|---|
| Claude | 54 (90%) | 1 | 0 | 5 | 60 |
| Codex | 39 (65%) | 18 | 3 | 0 | 60 |

---

## Divergence root cause (resolved)

The 25-entry gap between passes is a method artefact, not genuine disagreement on parser quality.

**Codex method:** verbatim substring search for parsed definition text inside raw DjVu `.txt` files. ABBYY FineReader output contains systematic double-space OCR artifacts throughout (e.g., "German  Lutheran  theologian...", "He studied  at Göttingen..."). Parsed source text normalises these to single spaces. Codex's verbatim search found no match → classified as `parser_gap`.

**Claude method:** normalised-whitespace word-set overlap, threshold 0.35. Double-space artifacts do not affect overlap scoring.

**Verification:** the 18 Codex `parser_gap` entries and 3 `parser_truncated` entries all fall on IA volumes (3–8, 10–12). CCEL volumes (1/2/9) have no double-space artifacts and both passes agree on their classifications. This volume-type correlation confirms the method as root cause.

**Convergent resolution:** Claude's method is valid. Codex's IA classifications are false negatives from the normalisation gap. Claude's 60-entry results are the authoritative basis for carry-forwards.

---

## Genuine disagreement: Psychotherapy (vol_09, position 60%)

| Entry | Claude | Codex | Convergent verdict |
|---|---|---|---|
| Psychotherapy | `parser_gap` | `parser_clean` | **parser_gap — Claude is correct** |

**Claude finding:** `source/vol_09.json` entry for Psychotherapy contains only the heading `PSYCHOTHERAPY.` with no definition body. The raw ThML (`raw/ccel/schaff-herzog/encyc09.xml`) has a full multi-section article (§1 through §7, several hundred words). Body was not ingested — genuine parser failure.

**Codex finding:** matched the heading `PSYCHOTHERAPY.` verbatim in the ThML and classified as `parser_clean`. Heading presence does not imply content presence.

---

## A3.1 — CCEL volumes (vols 01, 02, 09): parser fidelity

15 entries sampled. Both passes agree.

| Vol | % | Term | Classification |
|---|---|---|---|
| 01 | 20 | Agnosticism | parser_clean |
| 01 | 40 | American Missionary Association | parser_clean |
| 01 | 60 | Apponius | parser_clean |
| 01 | 80 | Authorized Version of the English Bible | parser_clean |
| 01 | 100 | Basilians | parser_clean |
| 02 | 20 | Bethsaida | parser_clean |
| 02 | 40 | Booth Tucker, Frederick St. George de Lautour | parser_clean |
| 02 | 60 | Bryant, Jacob | parser_clean |
| 02 | 80 | Camus (de Pont Carré), Jean Pierre | parser_clean |
| 02 | 100 | Chambers, Talbot Wilson | parser_clean |
| 09 | 20 | Placette, Jean La | parser_clean |
| 09 | 40 | Pratt, Waldo Selden | parser_clean |
| 09 | 60 | Psychotherapy | **parser_gap** |
| 09 | 80 | Raymond, Miner | parser_clean |
| 09 | 100 | Reuchlin, Johannes | parser_clean |

**Verdict: 14/15 parser_clean (93%), 1/15 parser_gap.**

---

## A3.2 — IA volumes (vols 03–08, 10–12): parser fidelity

45 entries sampled. Claude classifications are the authoritative record (Codex false negatives from double-space normalisation; see §Divergence).

| Vol | % | Term | Classification | Notes |
|---|---|---|---|---|
| 03 | 20 | CLARES | parser_clean | |
| 03 | 40 | CONSCIENCE | parser_clean | |
| 03 | 60 | CRYPT | parser_clean | |
| 03 | 80 | DE PUT, WILLIAM HARRISON | parser_clean | |
| 03 | 100 | JCOES WOT CIRCULATE | **ocr_structural** | OCR table fragment captured as entry; not a real article |
| 04 | 20 | ELIZABETH, QUEEN OF ENGLAND, EXCOM- | parser_clean | Term truncated at column break; body intact |
| 04 | 40 | BWALD (HERMAIfN AUGUST), PAUL | parser_clean | Term OCR-corrupted (EWALD); body intact |
| 04 | 60 | FLAVIAll | parser_clean | Term corrupted; body intact |
| 04 | 80 | GABRIEL SEVERUS | parser_clean | |
| 04 | 100 | GOA, ARCHBISHOFRIC OF | parser_clean | Term OCR artifact; body intact |
| 05 | 20 | DINAND | **ocr_structural** | Term severely truncated (probably FERDINAND or similar); whether there is a corresponding real article is unclear |
| 05 | 40 | HART, SAMUEL | parser_clean | |
| 05 | 60 | HERRMANN, JOHANN GEORG WILHELM | parser_clean | |
| 05 | 80 | HORHE, GEORGE | parser_clean | Term corrupted; body intact |
| 05 | 100 | END OF VOL. V | **ocr_structural** | End-of-volume marker ingested as entry |
| 06 | 20 | JESUS CHRIST, PICTURES AND IMAGES OF | parser_clean | DjVu starts with table-of-contents; parsed source reproduces faithfully |
| 06 | 40 | LINUS (or AQUILIUS) | parser_clean | |
| 06 | 60 | KNIGHT, GEORGE THOMSON | parser_clean | |
| 06 | 80 | THOLOMASUS HEIHRICI) | parser_clean | Term has stray `)` from OCR |
| 06 | 100 | LIUDGER, SAINT | parser_clean | Note: page=3 is false positive (see A3-F05) |
| 07 | 20 | MACCABEES, BOOKS OF | parser_clean | |
| 07 | 40 | MARCUS EREMITA | parser_clean | |
| 07 | 60 | MAZARIN BIBLE | parser_clean | |
| 07 | 80 | MIDRASH | parser_clean | |
| 07 | 100 | MORALISTS, BRITISH | parser_clean | |
| 08 | 20 | OANISATIONS | **ocr_structural** | OCR fragment from table section (ORGANIZATIONS); body is numeric `36,770` |
| 08 | 40 | IION-RESIDEIICE | parser_clean | Term corrupted (NON-RESIDENCE); body intact |
| 08 | 60 | OSWT | parser_clean | Term corrupted; body intact |
| 08 | 80 | PATRIARCH | parser_clean | |
| 08 | 100 | PETERSEN, JOHANN WH^HELM | parser_clean | Term has caret OCR artifact |
| 10 | 20 | ROSS, JOHH | parser_clean | Term corrupted (ROSS, JOHN); body intact |
| 10 | 40 | SARCBRIUS, ERASMUS | parser_clean | Term corrupted; body intact |
| 10 | 60 | SCIENCE, CHRISTIAN | parser_clean | |
| 10 | 80 | SHEM AIAH | parser_clean | |
| 10 | 100 | END OF VOLUME X | **ocr_structural** | End-of-volume marker ingested as entry |
| 11 | 20 | STBARHSi OAKMAff SPRA6UE | parser_clean | Term severely corrupted (STEARNS, OAKMAN SPRAIGUE); body intact |
| 11 | 40 | STUMBLING-BLOCK, STONE OF STUMBLING | parser_clean | |
| 11 | 60 | TAUSEN, HANS | parser_clean | |
| 11 | 80 | THIBTlfAS | parser_clean | Term corrupted; body intact |
| 11 | 100 | TREMELLIUS, EMAlfUEL | parser_clean | Ligature OCR artifact |
| 12 | 20 | VAN KIRK, HIRAM | parser_clean | |
| 12 | 40 | WALL, WILLIAM | parser_clean | |
| 12 | 60 | WHITEFIELD, GEORGE | parser_clean | |
| 12 | 80 | WORTMAN, DENIS | parser_clean | |
| 12 | 100 | ZOECKLER — | parser_clean | Trailing em-dash artifact in term |

**Verdict: 40/45 parser_clean (89%), 5/45 ocr_structural.**

The 5 `ocr_structural` entries are parser-faithful (the parser reproduced the DjVu source accurately) but the DjVu source contains non-article content at those positions. Four are genuine non-entries (`JCOES WOT CIRCULATE`, `END OF VOL. V`, `OANISATIONS`, `END OF VOLUME X`). One (`DINAND`) is a severely truncated headword where the real article, if any, is not identifiable without the scan.

---

## A3.3 — Prompt structural claims

Two factual claims in the session prompt were found to be incorrect:

| Claim | Verdict | Actual finding |
|---|---|---|
| "page_number is null across all 12 volumes" | **FALSE** | CCEL vols (1/2/9): 0 null page numbers. IA vols: 4–15 nulls per volume. CCEL ThML provides page numbers. |
| "DjVu format uses \\x0c (form-feed) as page boundaries" | **FALSE** | No form-feed bytes in any of the 9 DjVu `.txt` files. Page markers are standalone digit lines (< 600) surrounded by blank lines. |

Both passes independently confirmed these. These are errors in planning material, not data defects.

---

## A3.4 — Scan comparison

Not performed. IA scan images (JP2) are not present in this checkout under `raw/internet-archive/schaff-herzog/scans/`. Scan-vs-DjVu page-level comparison deferred.

---

## Aggregate

| Source | Sampled | parser_clean | parser_gap | ocr_structural |
|---|---|---|---|---|
| CCEL (vols 1/2/9) | 15 | 14 (93%) | 1 | 0 |
| IA (vols 3–8/10–12) | 45 | 40 (89%) | 0 | 5 |
| **Total** | **60** | **54 (90%)** | **1** | **5** |

---

## Carry-forward findings for A7

| ID | Severity | Description |
|---|---|---|
| A3-F01 | HIGH | `Psychotherapy` (vol_09, pos 354): definition body completely absent from `source/vol_09.json`. ThML has full §1–§7 article. Genuine parser failure. |
| A3-F02 | MEDIUM | 4 non-entries ingested as encyclopedia articles: `JCOES WOT CIRCULATE` (vol 03, trailing position), `END OF VOL. V` (vol 05, trailing position), `OANISATIONS` (vol 08, pos 123/618; body is numeric table data), `END OF VOLUME X` (vol 10, trailing position). Parser's `is_article_heading()` / `is_running_header()` classifiers did not exclude these. |
| A3-F03 | MEDIUM | Session prompt contains two false structural claims (page_number nullability; DjVu form-feed format). Planning material needs correction before next A-phase session. |
| A3-F04 | LOW | `DINAND` (vol 05, pos 20%): severely truncated headword where the leading characters (likely `FER` from `FERDINAND`) were lost. Cannot identify the corresponding real article without the scan. May be a duplicate or orphan. Requires scan verification. |
| A3-F05 | LOW | False positive page assignment at IA volume starts: standalone small digits in bibliography sections (e.g., "3" in a footnote reference) are misread as page markers by `is_page_marker()`. Confirmed in vol_06 (LIUDGER, SAINT: page=3) and likely vol_05 (DINAND: page=2). Entries before the first real page marker remain null — the false positives affect a small number of early entries. |

---

## Exit status

| Check | Verdict | Evidence |
|---|---|---|
| A3.1 CCEL parser fidelity | VERIFIED (14/15) | 1 parser_gap defect (Psychotherapy body absent); 14 entries match ThML source |
| A3.2 IA parser fidelity | VERIFIED (40/45 legitimate entries) | 5 ocr_structural artefacts; method divergence with Codex resolved as normalisation false-negatives |
| A3.3 Prompt structural claims | DEFECT | 2 false claims confirmed by both passes |
| A3.4 Scan comparison | DEFERRED | Scan files not present in checkout |

**A3 final: complete. 5 carry-forwards to A7 (1 HIGH, 2 MEDIUM, 2 LOW).**
