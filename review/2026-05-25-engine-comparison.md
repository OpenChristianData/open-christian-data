# Engine comparison — Schaff-Herzog vol 1 (10-page sample)

*Session 1A, 2026-05-25. Engines: Tesseract 5.5 PSM=1, Azure AI Vision v4.0, GCV v1, AWS Textract. DocInt blocked — `secrets/azure-docint.env` missing.*

Sample pages: 10, 60, 110, 160, 210, 260, 310, 360, 410, 460 — spans A–F headword range plus mid-article continuations.

## Confidence scores

| Page | Tess  | Azure | GCV   | Textract |
|-----:|------:|------:|------:|---------:|
|   10 | 90.6% | 95.8% | 97.1% |    97.6% |
|   60 | 94.6% |   n/a | 97.5% |    99.1% |
|  110 |   n/a |   n/a | 97.3% |    98.0% |
|  160 |   n/a |   n/a | 97.6% |    99.1% |
|  210 |   n/a |   n/a | 97.0% |    98.2% |
|  260 |   n/a |   n/a | 97.8% |    98.7% |
|  310 |   n/a |   n/a | 97.5% |    99.0% |
|  360 |   n/a |   n/a | 97.5% |    98.8% |
|  410 |   n/a |   n/a | 97.6% |    99.4% |
|  460 |   n/a |   n/a | 97.8% |    99.7% |
| **Mean** | **92.6%** | **95.8%** | **97.5%** | **98.8%** |

*Tesseract and Azure are still running the full 491-page volume — n/a means the page hasn't been processed yet, not a failure.*

## Block structure (column separation)

| Page | Tess blocks | Azure blocks | GCV blocks | Textract blocks |
|-----:|------------:|-------------:|-----------:|----------------:|
|   10 |           7 |            1 |          6 |               1 |
|   60 |           8 |          n/a |         16 |               1 |
|  110 |         n/a |          n/a |          8 |               1 |
|  160 |         n/a |          n/a |         13 |               1 |
|  210 |         n/a |          n/a |         14 |               1 |
|  260 |         n/a |          n/a |          9 |               1 |
|  310 |         n/a |          n/a |          8 |               1 |
|  360 |         n/a |          n/a |          5 |               1 |
|  410 |         n/a |          n/a |         12 |               1 |
|  460 |         n/a |          n/a |          8 |               1 |

---

## Per-engine findings

### Tesseract 5.5 PSM=1

**Headword detection.** Identifies headwords correctly on pages 10 and 60: "Abelard", "Abhedananda", "Afra", "Africa". One OCR error on page 10: "Abhedananda" rendered as "Abbedananda". Small-caps glyph shape still detected correctly as a separate line, but character accuracy is slightly lower than cloud engines. The `is_article_heading()` form 4/5 patterns catch cross-reference forms (e.g., "GETHSEMANE. See JERUSALEM, V., § 5.").

**Two-column reading order.** Excellent. PSM=1 (auto OSD) produces 7–8 blocks per page. The running header ("THE NEW SCHAFF-HERZOG") is filtered by `is_running_header()` in the sidecar, so it does not appear in parsed output. Left column is read before right column on verified pages.

**Confidence on small-caps / mixed-language.** Per-page mean 90–95%, lower than cloud engines. Small-caps headword lines register lower word confidence because Tesseract measures actual glyph height — the `x_size` bimodal signal (50–60px headwords vs 65–74px body) comes from this measurement and is unique to Tesseract. No multi-language detection in the parsed sidecar (only eng).

**Bbox accuracy at column boundary.** Word-level axis-aligned bboxes only (no polygon). The column boundary is implicitly captured through the block structure, but no per-word polygon data is available for sub-word alignment.

**Where it won.** Running-header filtering is unique to Tesseract (post-parse). The `x_size` per-line metric enables headword detection without relying on text patterns alone. Seven blocks shows accurate column separation.

**Where it failed.** Occasional per-character OCR errors (e.g., "Abbedananda" for "Abhedananda") and lower overall confidence vs cloud engines. No polygon per word.

**Recommended routing.** Full-volume baseline (unlimited quota). Structural analysis (heading detection via `x_size`). Skew measurement via per-line `baseline` polynomial.

---

### Azure AI Vision v4.0

**Headword detection.** Correctly identifies "Abelard" and "Abhedananda" on page 10. Running header appears in output (not filtered at engine level). 4-point polygon per word is available.

**Two-column reading order.** Poor. Single block on page 10 — Azure does not separate columns. Output interleaves left and right column text, making sequential reading unreliable for two-column content.

**Confidence.** 95.8% on page 10 (only page with completed sidecar at comparison time). Higher than Tesseract, lower than GCV/Textract.

**Bbox.** 4-point polygon per word — most accurate geometry for diagonal/skewed glyphs.

**Where it won.** Highest free quota (5,000/month), reliable availability, polygon per word.

**Where it failed.** Column interleaving on two-column pages. No structural classification (that requires DocInt).

**Recommended routing.** Full-volume cloud cross-check (largest free quota). Hard-page fallback when Tesseract fails. Not suitable for column-aware reading-order tasks.

---

### Google Cloud Vision

**Headword detection.** Excellent. Correctly identifies headwords in the correct position on all 10 pages. "Archdall" and "Archeology" appear as the first two lines on page 260 — correct reading order. Second headword is always positioned before running header in the left-column block.

**Two-column reading order.** Excellent. GCV produces 5–16 blocks per page (highest of all engines), correctly segmenting left and right columns into separate blocks. Left-column content precedes right-column content in output. The running header does appear in output (not pre-filtered) but is easily detectable as a separate block.

**Confidence on small-caps / mixed-language.** 97.0–97.8% across all 10 pages (mean 97.47%). Consistent. GCV's raw response includes `detectedLanguages` per word, which is not currently extracted to the sidecar but is available in `.gcv.raw.json` — useful for identifying embedded Latin, Greek, and German without re-calling the API.

**Bbox accuracy at column boundary.** 4-point polygon per word (also per block). Block polygons accurately reflect column boundaries. Best available geometry for post-processing column detection.

**Where it won.** Best block segmentation for two-column content. Correct headword order. Consistent 97%+ confidence. `detectedBreak == HYPHEN` available in raw for hyphenated cross-column words (not yet extracted). Language detection per word in raw.

**Where it failed.** One Unicode rendering artifact observed (em-dash in "iv. 642–643" rendered inconsistently in raw JSON). Running header appears in output (minor — easily filtered). Monthly quota limited to 950/month.

**Recommended routing.** Hard pages where Tesseract and Azure disagree. Best choice for layout-aware post-processing (column detection, hyphenation resolution). Word-level language detection tasks.

---

### AWS Textract

**Headword detection.** The headword itself is correctly OCR'd (e.g., "Afra", "Africa" on page 60, "Amulet", "Anabaptists" on page 160). However, reading order places the second headword AFTER the running header on page 10 ("Abelard", then "THE NEW SCHAFF-HERZOG", then "10", then "Abhedananda") — incorrect column order.

**Two-column reading order.** Poor. All 10 pages produce a single block. Output consistently interleaves left and right column lines, alternating between the two columns. On page 60, line 5 is left-column ("AFRA, SAINT: An early female martyr, con-"), line 6 is right-column ("the older. It is said that she was dedicated by"), alternating throughout. This pattern renders the text unusable for sequential parsing.

**Confidence.** Highest of all engines (97.6–99.7%, mean 98.76%). The high confidence is misleading — it reflects per-character recognition accuracy, not structural integrity. Textract recognizes individual characters well but has no column awareness.

**Bbox.** 4-point polygon per word and per line. Textract provides `TextType` (PRINTED/HANDWRITING) and page-level `RotationAngle`.

**Where it won.** Highest raw character confidence. `text_type` field (PRINTED/HANDWRITING) distinguishes typeset from handwritten content — useful as a pre-filter for image pages or marginalia. Page rotation angle from `PAGE` block geometry.

**Where it failed.** Column interleaving makes output unsuitable for two-column text extraction without post-processing re-sorting by bbox coordinates. High confidence scores mask structural failures and should not be used to choose between engines on Schaff-Herzog content.

**Recommended routing.** Not recommended as primary engine for Schaff-Herzog (two-column prose). If used, post-processing must re-sort words/lines by bbox `x` coordinate to reconstruct column order from geometry. Suitable for single-column content or image-only pages where column detection is not needed. `text_type` field useful as a page-type classifier.

---

## Summary recommendation

| Task | Engine | Reason |
|---|---|---|
| Full-volume text baseline | Tesseract | Unlimited quota, column-aware, filtered headers |
| Full-volume cloud cross-check | Azure | 5,000/month free quota |
| Hard page, Tess+Azure disagree | GCV | Best column segmentation, highest structural accuracy |
| Layout / paragraph roles | DocInt | Blocked — `secrets/azure-docint.env` missing |
| Hyphenated-word detection | GCV | `detectedBreak == HYPHEN` in raw (not yet extracted) |
| Language detection (Latin/Greek) | GCV | `detectedLanguages` per word in raw (not yet extracted) |
| Page rotation detection | Textract or DocInt | Only engines exposing `RotationAngle` |
| Two-column content do NOT use | Textract | Single block, column interleaving |

The B2.2 probe result (GCV mean 97.7%) is confirmed here across all 10 comparison pages. DocInt cannot be evaluated until `secrets/azure-docint.env` is provisioned.
