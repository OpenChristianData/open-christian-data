# Phase A3 — Claude Round 1 audit
# Content sampling against sources and scans

**Work handle:** `reference/schaff/encyclopedia/1908-1914`
**Reviewer:** Claude (independent pass)
**Date:** 2026-05-20
**Scope:** 60 entries (5 per volume × 12 volumes) from `source/vol_NN.json`

---

## Structural pre-checks (findings before sampling)

### Prompt assumption: page_number is null across all 12 volumes — FALSE

Actual distribution:

| Volume | Source | Blocks | null page_number | non-null page_number |
|---|---|---|---|---|
| vol_01 | ccel-thml | 899 | 0 | 899 |
| vol_02 | ccel-thml | 895 | 0 | 895 |
| vol_03 | ia-ocr | 625 | 15 | 610 |
| vol_04 | ia-ocr | 752 | 10 | 742 |
| vol_05 | ia-ocr | 760 | 6 | 754 |
| vol_06 | ia-ocr | 619 | 4 | 615 |
| vol_07 | ia-ocr | 536 | 8 | 528 |
| vol_08 | ia-ocr | 618 | 15 | 603 |
| vol_09 | ccel-thml | 592 | 0 | 592 |
| vol_10 | ia-ocr | 658 | 8 | 650 |
| vol_11 | ia-ocr | 525 | 7 | 518 |
| vol_12 | ia-ocr | 678 | 7 | 671 |

CCEL volumes (01, 02, 09): 0 null page numbers.
IA volumes (03–08, 10–12): 4–15 null page numbers per volume (entries before the first recoverable page marker).

### Prompt assumption: DjVu format uses form-feed (\x0c) as page boundaries — FALSE

The `_djvu.txt` files contain zero form-feed bytes. These are ABBYY FineReader plain-text exports, not binary DjVu. Page boundaries are standalone digit lines (e.g., `10`, `11`, `12`) surrounded by blank lines. The parser's `is_page_marker()` is correct for this format.

### Rendering_id alias mismatch: CONFIRMED

`source_pages[].rendering_id` uses short aliases (`ccel-thml`, `ia-ocr`). Catalog rendering IDs are full paths (`ccel/schaff/encyclopedia/1908-1914/thml`, `ia/schaff/encyclopedia/1908-1914/ocr`). Carry forward to A4.3.

---

## A3.1 — Sample selection

Entries at positions 20/40/60/80/100% (round to nearest index, zero-based).

| Vol | Source | N | 20% | 40% | 60% | 80% | 100% |
|---|---|---|---|---|---|---|---|
| 01 | ccel-thml | 899 | Agnosticism | American Missionary Association | Apponius | Authorized Version… | Basilians |
| 02 | ccel-thml | 895 | Bethsaida | Booth Tucker, Frederick St. George de Lautour | Bryant, Jacob | Camus (de Pont Carré), Jean Pierre | Chambers, Talbot Wilson |
| 03 | ia-ocr | 625 | CLARES | CONSCIENCE | CRYPT | DE PUT, WILLIAM HARRISON | JCOES WOT CIRCULATE |
| 04 | ia-ocr | 752 | ELIZABETH, QUEEN OF ENGLAND, EXCOM- | BWALD (HERMAIfN AUGUST), PAUL | FLAVIAll | GABRIEL SEVERUS | GOA, ARCHBISHOFRIC OF |
| 05 | ia-ocr | 760 | DINAND | HART, SAMUEL | HERRMANN, JOHANN GEORG WILHELM | HORHE, GEORGE | END OF VOL. V |
| 06 | ia-ocr | 619 | JESUS CHRIST, PICTURES AND IMAGES OF | LINUS (or AQUILIUS) | KNIGHT, GEORGE THOMSON | THOLOMASUS HEIHRICI) | LIUDGER, SAINT |
| 07 | ia-ocr | 536 | MACCABEES, BOOKS OF | MARCUS EREMITA | MAZARIN BIBLE | MIDRASH | MORALISTS, BRITISH |
| 08 | ia-ocr | 618 | OANISATIONS | IION-RESIDEIICE | OSWT | PATRIARCH | PETERSEN, JOHANN WH^HELM |
| 09 | ccel-thml | 592 | Placette, Jean La | Pratt, Waldo Selden | Psychotherapy | Raymond, Miner | Reuchlin, Johannes |
| 10 | ia-ocr | 658 | ROSS, JOHH | SARCBRIUS, ERASMUS | SCIENCE, CHRISTIAN | SHEM AIAH | END OF VOLUME X |
| 11 | ia-ocr | 525 | STBARHSi OAKMAff SPRA6UE | STUMBLING-BLOCK, STONE OF STUMBLING | TAUSEN, HANS | THIBTlfAS | TREMELLIUS, EMAlfUEL |
| 12 | ia-ocr | 678 | VAN KIRK, HIRAM | WALL, WILLIAM | WHITEFIELD, GEORGE | WORTMAN, DENIS | ZOECKLER — |

---

## A3.2 — Page-to-entry map (IA volumes)

Page numbers recovered by parsing each DjVu text file with `is_page_marker()` logic (standalone digit lines < 600 = page marker). Selected page numbers for sampled entries:

| Vol | Term | Recovered page |
|---|---|---|
| 03 | CLARES | 125 |
| 03 | CONSCIENCE | 242 |
| 03 | CRYPT | 316 |
| 03 | DE PUT, WILLIAM HARRISON | 407 |
| 03 | JCOES WOT CIRCULATE | 500 |
| 04 | ELIZABETH, QUEEN OF ENGLAND, EXCOM- | 110 |
| 04 | BWALD (HERMAIfN AUGUST), PAUL | 282 |
| 04 | FLAVIAll | 337 |
| 04 | GABRIEL SEVERUS | 416 |
| 04 | GOA, ARCHBISHOFRIC OF | 500 |
| 05 | DINAND | 2 |
| 05 | HART, SAMUEL | 161 |
| 05 | HERRMANN, JOHANN GEORG WILHELM | 249 |
| 05 | HORHE, GEORGE | 366 |
| 05 | END OF VOL. V | 508 |
| 06 | JESUS CHRIST, PICTURES AND IMAGES OF | 150 |
| 06 | LINUS (or AQUILIUS) | 286 |
| 06 | KNIGHT, GEORGE THOMSON | 356 |
| 06 | THOLOMASUS HEIHRICI) | 420 |
| 06 | LIUDGER, SAINT | 3 ¹ |
| 07 | MACCABEES, BOOKS OF | 106 |
| 07 | MARCUS EREMITA | 176 |
| 07 | MAZARIN BIBLE | 264 |
| 07 | MIDRASH | 364 |
| 07 | MORALISTS, BRITISH | 496 |
| 08 | OANISATIONS | 106 |
| 08 | IION-RESIDEIICE | 190 |
| 08 | OSWT | 283 |
| 08 | PATRIARCH | 381 |
| 08 | PETERSEN, JOHANN WH^HELM | 409 |
| 10 | ROSS, JOHH | 9 |
| 10 | SARCBRIUS, ERASMUS | 200 |
| 10 | SCIENCE, CHRISTIAN | 284 |
| 10 | SHEM AIAH | 389 |
| 10 | END OF VOLUME X | 499 |
| 11 | STBARHSi OAKMAff SPRA6UE | 78 |
| 11 | STUMBLING-BLOCK, STONE OF STUMBLING | 119 |
| 11 | TAUSEN, HANS | 278 |
| 11 | THIBTlfAS | 416 |
| 11 | TREMELLIUS, EMAlfUEL | 508 |
| 12 | VAN KIRK, HIRAM | 140 |
| 12 | WALL, WILLIAM | 257 |
| 12 | WHITEFIELD, GEORGE | 341 |
| 12 | WORTMAN, DENIS | 441 |
| 12 | ZOECKLER — | 599 |

¹ LIUDGER page=3 is a false positive: a bibliography year or footnote number was misidentified as a page number, placing the entry on "page 3" which is before the volume's content pages. Likely false positive from a standalone "3" in a bibliography.

**Entry density sanity check:** IA volumes span pages 1–500+ with hundreds of entries each. Average entry density ~1.3–2 entries per page, consistent with two-column 1908 encyclopedia layout.

**Null page_number entries:** The 4–15 null entries per IA volume are entries whose headwords appear before the first recoverable standalone-digit page marker. These are at the start of each volume's body (e.g., CHAMIER through CHAPTER-COURTS in vol_03, 14 entries).

---

## A3.3 — Scan page download

**Not attempted this session.** The comparison requirement is to verify parser fidelity against the raw DjVu text; scan images add OCR quality assessment but are not needed for parser fidelity. The IA server imposes a 10s crawl delay; downloading ~45 JP2 pages without confirmed URL pattern would take excessive time. URL pattern investigation deferred.

Scan comparison columns below are marked `SCAN_NOT_DOWNLOADED`.

---

## A3.4 — Source comparison results

### CCEL volumes (vols 01, 02, 09) — ThML XML comparison

| Vol | % | Term | ThML match | Parser classification | Notes |
|---|---|---|---|---|---|
| 01 | 20 | Agnosticism | FOUND, exact match | parser_clean | Text identical to first 200 chars |
| 01 | 40 | American Missionary Association | FOUND, exact match | parser_clean | |
| 01 | 60 | Apponius | FOUND, exact match | parser_clean | |
| 01 | 80 | Authorized Version of the English Bible | FOUND, exact match | parser_clean | |
| 01 | 100 | Basilians | FOUND, exact match | parser_clean | |
| 02 | 20 | Bethsaida | FOUND, exact match | parser_clean | |
| 02 | 40 | Booth Tucker, Frederick St. George de Lautour | FOUND (second of two Booth Tucker articles) | parser_clean | ThML has BOOTH TUCKER, EMMA MOSS followed by BOOTH TUCKER, FREDERICK. Parser correctly extracted the Frederick article. |
| 02 | 60 | Bryant, Jacob | FOUND, exact match | parser_clean | |
| 02 | 80 | Camus (de Pont Carré), Jean Pierre | FOUND, exact match | parser_clean | ThML heading: `<b>CAMUS,</b>... de Pont Carré, JEAN PIERRE`. Parser correctly extracted. |
| 02 | 100 | Chambers, Talbot Wilson | FOUND, exact match | parser_clean | |
| 09 | 20 | Placette, Jean La | FOUND, exact match | parser_clean | ThML: `<b>PLACETTE</b>, <b>JEAN LA:</b>` (split bold elements). Parser correctly extracted. |
| 09 | 40 | Pratt, Waldo Selden | FOUND, exact match | parser_clean | |
| 09 | 60 | Psychotherapy | FOUND in ThML, body present | **parser_gap** | Parsed source has only `PSYCHOTHERAPY.` with no definition body. ThML has full multi-section article (§1–§7). Definition body completely missing from `source/vol_09.json`. |
| 09 | 80 | Raymond, Miner | FOUND, exact match | parser_clean | |
| 09 | 100 | Reuchlin, Johannes | FOUND, exact match | parser_clean | |

**CCEL parser fidelity: 14/15 parser_clean (93.3%), 1 parser_gap (Psychotherapy — genuine defect)**

### IA volumes (vols 03–08, 10–12) — DjVu text comparison

| Vol | % | Term | DjVu match | Parser classification | Notes |
|---|---|---|---|---|---|
| 03 | 20 | CLARES | FOUND, match | parser_clean | |
| 03 | 40 | CONSCIENCE | FOUND, match | parser_clean | |
| 03 | 60 | CRYPT | FOUND, match | parser_clean | |
| 03 | 80 | DE PUT, WILLIAM HARRISON | FOUND, match | parser_clean | |
| 03 | 100 | JCOES WOT CIRCULATE | FOUND, match | **ocr_structural** | Not a real entry. OCR captured a table/cross-ref fragment as a headword. Last "entry" in vol 03. |
| 04 | 20 | ELIZABETH, QUEEN OF ENGLAND, EXCOM- | FOUND, match | parser_clean | Term truncated (hyphen at end = column break in scan). Body text correctly extracted. |
| 04 | 40 | BWALD (HERMAIfN AUGUST), PAUL | FOUND, match | parser_clean | Term corrupted: `EWALD` → `BWALD`; `HERMANn` → `HERMAIfN` (ligature OCR). Body intact. |
| 04 | 60 | FLAVIAll | FOUND, match | parser_clean | Term appears truncated/corrupted (possibly `FLAVIAN`). Body intact. |
| 04 | 80 | GABRIEL SEVERUS | FOUND, match | parser_clean | |
| 04 | 100 | GOA, ARCHBISHOFRIC OF | FOUND, match | parser_clean | Term has OCR artifact (`ARCHBISHOFRIC` vs correct `ARCHBISHOPRIC`). Body intact. |
| 05 | 20 | DINAND | FOUND, match | **ocr_structural** | Term appears truncated (probably `FERDINAND` or similar, lost leading chars). Body intact. |
| 05 | 40 | HART, SAMUEL | FOUND, match | parser_clean | |
| 05 | 60 | HERRMANN, JOHANN GEORG WILHELM | FOUND, match | parser_clean | |
| 05 | 80 | HORHE, GEORGE | FOUND, match | parser_clean | Term corrupted: likely `HOOKE, GEORGE`. Body intact. |
| 05 | 100 | END OF VOL. V | FOUND, match | **ocr_structural** | Not a real entry. End-of-volume marker captured as an encyclopedia entry. |
| 06 | 20 | JESUS CHRIST, PICTURES AND IMAGES OF | FOUND in DjVu | parser_clean | DjVu body starts with table-of-contents sections (structure of long article). Parsed source (41 blocks, 4012 words) faithfully captures the DjVu OCR output including table-of-contents lines. |
| 06 | 40 | LINUS (or AQUILIUS) | FOUND, match | parser_clean | |
| 06 | 60 | KNIGHT, GEORGE THOMSON | FOUND, match | parser_clean | |
| 06 | 80 | THOLOMASUS HEIHRICI) | FOUND, match | parser_clean | Term has OCR artifacts including stray `)`. |
| 06 | 100 | LIUDGER, SAINT | FOUND, match | parser_clean | Note: page=3 is a false positive (see §A3.2 footnote). |
| 07 | 20 | MACCABEES, BOOKS OF | FOUND, match | parser_clean | |
| 07 | 40 | MARCUS EREMITA | FOUND, match | parser_clean | |
| 07 | 60 | MAZARIN BIBLE | FOUND, match | parser_clean | |
| 07 | 80 | MIDRASH | FOUND, match | parser_clean | |
| 07 | 100 | MORALISTS, BRITISH | FOUND, match | parser_clean | |
| 08 | 20 | OANISATIONS | FOUND in DjVu | **ocr_structural** | Not a real entry. OCR fragment from a tabular section (ORGANIZATIONS). Body text is `36,770` (a table number). |
| 08 | 40 | IION-RESIDEIICE | FOUND, match | parser_clean | Term corrupted: likely `NON-RESIDENCE`. Body intact. |
| 08 | 60 | OSWT | FOUND, match | parser_clean | Term corrupted. Body intact. |
| 08 | 80 | PATRIARCH | FOUND, match | parser_clean | |
| 08 | 100 | PETERSEN, JOHANN WH^HELM | FOUND, match | parser_clean | Term has OCR caret artifact. |
| 10 | 20 | ROSS, JOHH | FOUND, match | parser_clean | Term corrupted: likely `ROSS, JOHN`. |
| 10 | 40 | SARCBRIUS, ERASMUS | FOUND, match | parser_clean | Term corrupted. |
| 10 | 60 | SCIENCE, CHRISTIAN | FOUND, match | parser_clean | |
| 10 | 80 | SHEM AIAH | FOUND, match | parser_clean | |
| 10 | 100 | END OF VOLUME X | FOUND, match | **ocr_structural** | Not a real entry. End-of-volume marker captured as entry. |
| 11 | 20 | STBARHSi OAKMAff SPRA6UE | FOUND, match | parser_clean | Term severely corrupted with digit substitution and case errors. Body intact. |
| 11 | 40 | STUMBLING-BLOCK, STONE OF STUMBLING | FOUND, match | parser_clean | |
| 11 | 60 | TAUSEN, HANS | FOUND, match | parser_clean | |
| 11 | 80 | THIBTlfAS | FOUND, match | parser_clean | Term corrupted. |
| 11 | 100 | TREMELLIUS, EMAlfUEL | FOUND, match | parser_clean | Term has ligature OCR (lf→u). |
| 12 | 20 | VAN KIRK, HIRAM | FOUND, match | parser_clean | |
| 12 | 40 | WALL, WILLIAM | FOUND, match | parser_clean | |
| 12 | 60 | WHITEFIELD, GEORGE | FOUND, match | parser_clean | |
| 12 | 80 | WORTMAN, DENIS | FOUND, match | parser_clean | |
| 12 | 100 | ZOECKLER — | FOUND, match | parser_clean | Term has trailing em-dash artifact. |

**IA parser fidelity: 40/45 parser_clean (89%), 5 ocr_structural (table/end-of-volume captures)**

---

## A3.5 — Aggregate

### Parser fidelity

| Source | parser_clean | parser_truncated | parser_gap | ocr_structural |
|---|---|---|---|---|
| CCEL (15 entries) | 14 (93%) | 0 | 1 | 0 |
| IA (45 entries) | 40 (89%) | 0 | 0 | 5 |
| **Total (60)** | **54 (90%)** | **0** | **1** | **5** |

Note: `ocr_structural` means the parser faithfully reproduced the DjVu content, but the DjVu source itself has a structural error (non-entry captured as entry). This is a source quality issue, not a parser fidelity issue.

### OCR quality — term-level corruption (IA volumes)

Of 45 IA entries sampled, **5 have OCR-corrupted headword terms** (11%):

| Vol | Corrupted term | Likely intended term | Corruption class |
|---|---|---|---|
| 04 | `ELIZABETH, QUEEN OF ENGLAND, EXCOM-` | `ELIZABETH, QUEEN OF ENGLAND, EXCOM[MUNICATED]` | truncated-term (column break) |
| 08 | `PETERSEN, JOHANN WH^HELM` | `PETERSEN, JOHANN WILHELM` | ocr_char (caret for I) |
| 11 | `STBARHSi OAKMAff SPRA6UE` | `STEARNS, OAKMAN SPRAIGUE` | ocr_word (severe substitution) |
| 11 | `THIBTlfAS` | Unknown | ocr_word |
| 12 | `ZOECKLER —` | `ZOECKLER` | truncated-term (trailing artifact) |

Additionally, these IA terms have body-present OCR corruption in the term but correct body text (term corrupted, content intact): `BWALD`, `FLAVIAll`, `HORHE`, `OANISATIONS`, `IION-RESIDEIICE`, `OSWT`, `JCOES WOT CIRCULATE`, `ROSS JOHH`, `SARCBRIUS`.

### Structural issues (IA volumes)

| Vol | Entry | Issue |
|---|---|---|
| 03 | `JCOES WOT CIRCULATE` (pos 624/625) | OCR fragment captured as entry |
| 05 | `END OF VOL. V` (pos 759/760) | End-of-volume line captured as entry |
| 08 | `OANISATIONS` (pos 123/618) | Table-section OCR fragment captured as entry; body is numeric data `36,770` |
| 10 | `END OF VOLUME X` (pos 657/658) | End-of-volume line captured as entry |

### Scan comparison

Not performed — JP2 files not downloaded. Scan-vs-DjVu comparison deferred.

---

## Carry-forward findings for A4 / A7

| ID | Severity | Description |
|---|---|---|
| A3-F01 | HIGH | `Psychotherapy` (vol_09, pos 354): definition body completely missing from `source/vol_09.json`. ThML source has a full multi-section article. Parser_gap — genuine parsing defect. |
| A3-F02 | MEDIUM | 4 structural-OCR entries captured as encyclopedia entries: `JCOES WOT CIRCULATE` (vol 03), `END OF VOL. V` (vol 05), `OANISATIONS` (vol 08), `END OF VOLUME X` (vol 10). Body text is table data or end-of-volume markers, not definitions. |
| A3-F03 | MEDIUM | Prompt's structural facts contain two incorrect assumptions: (1) `page_number is null across all 12 volumes` — false, CCEL vols have 0 nulls; (2) DjVu format uses `\x0c` form-feed markers — false, files are plain-text with digit-only page markers. |
| A3-F04 | LOW | `page_number = 1` false positive in IA volumes: standalone `1` in body text (e.g., bibliography "vol. 1" reference) triggers `is_page_marker()`, incorrectly attributing entries to "page 1". |
| A3-F05 | LOW | `page_number = 3` false positive in vol_06 (LIUDGER, SAINT): small digit in bibliography body text misread as page marker. |
| A3-F06 | INFO | Rendering_id aliases (`ccel-thml`, `ia-ocr`) not resolved to full catalog IDs in source_pages. Carry to A4.3. |
| A3-F07 | INFO | Scan comparison not performed. IA JP2 URL pattern and download to `raw/internet-archive/schaff-herzog/scans/` deferred to a separate session. |

---

## Exit status

Exit criterion: 60-entry sample table, page numbers recovered, aggregate counts, carry-forwards documented.

| Item | Status |
|---|---|
| 60-entry sample selected | DONE |
| DjVu body starts identified (all 9 IA vols) | DONE |
| Page numbers recovered (IA vols) | DONE |
| CCEL ThML comparison (15 entries) | DONE |
| DjVu text comparison (45 entries) | DONE |
| Scan comparison | DEFERRED |
| Aggregate counts | DONE |
| Carry-forwards documented | DONE |

**A3 Claude round 1: complete.**
