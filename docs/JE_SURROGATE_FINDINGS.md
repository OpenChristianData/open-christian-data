# Jewish Encyclopedia (1901–1906) as a Non-Circular Surrogate Oracle for the SH OCR Pipeline

**Status: COMPLETE — Phases 0–4 done. 5-engine panel (all 36 pages) complete 2026-06-06;
measurements updated 2026-06-06 (post-confusion_distance fix). B8 aligner tuning complete
2026-06-06 (GAP_PENALTY=0.6 confirmed optimal; no metric change).** Adversarial review
caveats (partial-page bias, M3 framing corrected, position double-counting) apply with one
key reversal: the 4-engine finding that complete-page M3t ≈ M2 no longer holds — 5-engine
complete-page M3t=65.9% >> M2=52.3%. See §4 and §6. This document is the running deliverable. The architecture
decision (keep-matrix vs agree->escalate) stays the maintainer's call — this report
produces numbers and a trust-model verdict only.

---

## 1. Decision brief

10 articles, 24,952 aligned pairs, reference = JE.com human transcription (non-circular).
All rates are aligner-mediated — B8-tuned NW (GAP_PENALTY=0.6, confirmed optimal). This is a floor, not a ceiling.

**Key numbers (5-engine panel: ABBYY + Tesseract + Azure + Kraken + Kraken-Greek, all 36 pages):**

| Metric | Rate | N |
|---|---|---|
| M0 — consensus match (baseline) | 47.7% | 24,952 |
| M1 — any-engine match | 48.2% | 24,952 |
| M2 — ≥2 families agree | 53.8% | 19,012 |
| M3h — all-engine-attest conf ≥ 0.875 | 65.2% | 5,892 |
| M3t — all-engine-attest conf ≥ 0.99 | **69.5%** | 3,520 |

**Five findings:**

1. **The M1 gap is negligible (+0.5pp).** Almost no positions have the correct reading available
   in some engine but missed by `_best_candidate`. The accuracy problem is structural ("no engine
   had the right answer") not a selection failure. `_best_candidate` is not the bottleneck.

2. **Family agreement alone is a weak signal (+6.1pp over baseline).** The auto-accept rule
   "≥2 independent families agree → accept" raises accuracy from 47.7% to 53.8% — and would
   auto-accept 76.2% of positions (19,012/24,952). An error rate of 46.2% on the auto-accepted
   bucket is too high for any confidence-based auto-accept scheme — even before accounting for
   aligner noise in the denominator.

3. **All-engine attestation is a better predictor than family agreement; the 5-engine panel
   confirms the signal is real in both aggregate and complete-page strata.** `alignment_confidence`
   counts all available engines including text-only Kraken — it is an all-engine consensus signal,
   not a geometry-only gate. Complete-page-only M3t = 65.9%, which exceeds M2 = 52.3% in that
   stratum by 13.6pp. The 4-engine run's adversarial finding (complete-page M3t ≈ M2 = 41.2%)
   no longer holds: Azure on all 36 pages expanded the WCT from 38,565 to 49,760 positions and
   raised alignment coverage from 73.0% to 79.5%. Aggregate M3t = 69.5% is still upward-biased
   by partial-page selection, but the direction is robust. The M3t denominator shrank from 5,107
   to 3,520 pairs because all-5-engine agreement is harder; accuracy improved to 69.5%.

4. **All-engine attestation should replace family agreement as the primary auto-accept gate,
   but calibration requires B8 aligner tuning first.** The direction is confirmed in both strata.
   Threshold calibration — the decision of what error rate is acceptable at a given coverage level
   — is deferred to B8.

5. **Per-article variance is wide (12.7%–79.2% M0).** The low-end outliers are driven by
   missing WCT pages (apologists lost pages 8–9; apostasy lost page 12; atonement lost page 283).
   atonement-day-of is now complete (page 285 builds with 5 engines after Azure provided the third
   geometry anchor). Hebrew-heavy content (baal 38.3%, atonement 48.0%) is consistently lower —
   OCR of Hebrew transliteration at this era is harder, and the NW aligner treats all script
   equally. Script-aware alignment is a future-work item.

---

## 2. Acquisition

### 2.1 Why JE, and why it is non-circular

The 10-page Schaff-Herzog (SH) run produced **circular** M2/M3: the only reference was the
CCEL alignment, whose "gold" bucket is *defined* as CCEL == OCR-reading. Scoring OCR
against that reference is correct-by-construction on the gold stratum and
wrong-by-construction on the disagreement stratum, so the pooled rates re-report the bucket
split, not accuracy (`docs/MEASUREMENT_FINDINGS_vol01_10page.md`).

The 1901–1906 Jewish Encyclopedia (Funk & Wagnalls) breaks the circularity because a
**human** diplomatic transcription of the *same edition* exists alongside the scanned
facsimiles. A reference built from human transcription is independent of what the OCR
engines produced, so scoring OCR against it at every aligned position is non-circular. This
is the best case of "Option B — independently aligned reference text" in
`docs/MEASUREMENT_REFERENCE_OPTIONS.md`: trustworthy because the edition matches (no
1951-reprint edition-offset as with CCEL), but still mediated by the B8-tuned aligner (GAP_PENALTY=0.6) — so
**alignment noise is the residual caveat**, reported with every rate.

JE is a **measurement oracle only**. It is not a Christian text and is correctly absent
from `research/MANIFEST.md`; it is never published, never added to `data/`. It is
registered as a distinct work/edition purely so the harness can score against it without
touching any SH artifact.

### 2.2 ToS / licence verdict

**Corrected from the first draft.** The initial "do-not-fetch" read of
`jewishencyclopedia.com` came from an unreliable auto-summary of `robots.txt`. The
**verbatim** file (fetched with a normal browser UA, HTTP 200) reads:

```
# See http://www.robotstxt.org/wc/norobots.html for documentation ...
# To ban all spiders from the entire site uncomment the next two lines:
User-Agent: *
```

The "ban all spiders" lines are **commented out and not activated**; there is **no
`Disallow`** directive. A `User-Agent: *` with no `Disallow` **permits crawling**. So the
site's own robots policy allows it. The content is public domain (1901–1906).

| Source | Role | Verdict | Basis |
|---|---|---|---|
| **`jewishencyclopedia.com`** | **human diplomatic transcription (the non-circular reference)** + printed-page label (`V:N P:N`) + per-page facsimiles | **Primary. Use, politely.** | robots.txt permits crawling (above). Served as clean UTF-8 (`charset=utf-8`, verified at byte level: em-dash `e2 80 94`, transliteration diacritics like `ḳ` U+1E33 preserved). Same edition as the scans (Phase 1 confirms). |
| **Internet Archive** | scan **page images** for the live engines + free **ABBYY OCR** lane (mirrors the SH ABBYY(IA) lane exactly) | **Use.** | Full 1901–1906 Funk & Wagnalls set; IA permits programmatic access. Confirmed formats: DjVuTXT (4.8M), ABBYY GZ (74.3M), single-page JP2 ZIP (1.4G), PDF (60.5M). |

**Polite-crawl contract for `jewishencyclopedia.com`:** normal browser User-Agent;
sequential requests with a ≥3 s delay; fetch **only** the sample's articles + their
facsimiles (not the whole site); local cache under `raw/jewish-encyclopedia/` so nothing is
re-fetched; honor any future `Disallow`. "Human-mimicking" here means human-paced and a
real UA — not deception to bypass access controls (there are none).

**Critical non-circularity guard:** IA's `djvu.txt` / ABBYY GZ is **ABBYY OCR**, which is a
*panel engine* (the SH ABBYY lane). It is consumed as an engine input, and must **never**
be used as the reference. The reference is the **human** `jewishencyclopedia.com`
transcription only.

### 2.3 Source roles (resolved)

- **Reference transcription + printed-page mapping:** `jewishencyclopedia.com`, per article
  (human, diplomatic, Greek/Hebrew/transliteration preserved). Each article page also lists
  every printed page it spans (`V:N P:N`) and that page's facsimile — used to cross-map IA
  leaves to printed pages (PIPE-29 mitigation: confirm via the printed folio / running
  header, never trust a leaf index blindly).
- **Scan images for live engines (Azure, Tesseract, Kraken, Kraken-Greek) + the ABBYY
  lane:** Internet Archive, one volume (cost ceiling). All live engines OCR the *same* IA
  image ABBYY saw, so the ABBYY family is consistent with the panel — a faithful mirror of
  the SH setup. (Panel per §3: Surya excluded.)

### 2.4 Reference granularity: article-keyed, aligned exactly like CCEL

Not a feasibility blocker — just a difference in the *unit* handed to the aligner. The
operation that matters (human reference text vs OCR-consensus, scored against gold) is
identical whether the reference is keyed by page or by article.

- **CCEL is page-keyed.** The SH chain consumes a pre-segmented proposal
  (`ccel_page_gold_proposal.json`, one `ccel_page_text` per `page_native_id`); CCEL's source
  marks page breaks, so the per-page split existed before alignment.
- **JE is article-keyed.** `jewishencyclopedia.com` gives the full article text plus a
  sidebar list of the pages it spans (no inline page breaks; verified on the 32-page
  "Pentateuch" article — body `<p>` in `yui3-u-17-24`, all 32 `V:N P:N` tags clustered in
  the `yui3-u-7-24` sidebar). So the split is by article.

**Plan: align per article.** Each sampled article's full transcription is aligned (the
existing Needleman-Wunsch core over `confusion_distance`) against the concatenated
OCR-consensus sequence of the pages it spans, in reading order — exactly as CCEL aligns
page-by-page, just at article granularity.

**Per-page reporting still falls out, and it is NOT circular.** Every WCT position already
records its page, so after alignment each gold token inherits the page of the OCR token it
matched. OCR page boundaries only *bucket* results into per-page strata; they never define
the reference text or the correct/incorrect decision (gold-token vs OCR-reading,
independent of the bucket). Un-placeable tokens route to *unverifiable/excluded* exactly as
the current aligner does.

Sampling selects **articles** (stratified, §2.6); "page count" = the facsimile pages those
articles span = the OCR cost knob.

### 2.5a Code-change principle: additive and modular, never destructive

A parallel session is actively editing the SH pipeline code. All JE support is built as
**new** modules / functions / parameters that leave the existing SH page-keyed behavior
unchanged:

- Reference-mode is a **new branch or parameter** in the measurement step (default stays the
  current CCEL `_ccel_refs` path, untouched) — or a new sibling module — not a rewrite.
- Article alignment **reuses** the shared NW core (`confusion_distance`, `_nw_align`) via a
  new JE-scoped entry point, not by changing `align_page`'s SH behavior.
- SH artifacts, ids, and paths are never mutated; the existing SH tests must still pass.
- Shared SH files are avoided where possible; any genuinely necessary shared-file edit is
  flagged to the maintainer first. Commits are pathspec-scoped (GIT-01b) so the parallel
  session's staged work is never swept in; the host commits after review.

### 2.5 Volume chosen — **Vol. 2, 1901** (LOCKED)

Internet Archive item **`cu31924091768196`** (Cornell scan). Chosen over the Vol. I
single-uploader item because the latter's IA derivation files carry **spaces** in their
names (`The Jewish Encyclopedia - ... _scandata.xml`), which break raw-URL fetching and
`fetch_ia_pages.py` unmodified; the Cornell Vol. 2 item has clean filenames. Verified:

- Clean derivation filenames; full derivation: `_scandata.xml`, `_jp2.zip`, `_abbyy.gz`
  (ABBYY OCR **with word geometry** — needed for ABBYY to vote in the WCT), `_djvu.txt`.
- 740 leaves, 677 numbered printed pages, printed-page range **10–685**.
- Scandata leaf map usable: printed page 38 → leaf 73, contiguous (`10→41, 11→42, …`).
  Matches JE.com Apostasy `V:2 P:38`, so that article is the first edition-match +
  leaf-verification cross-check (Phase 1).
- **PIPE-29 caveat:** the scandata `pageNumber` is upstream metadata. Before any scoring,
  each sampled printed page is confirmed against its IA scan's printed folio / running
  header and the JE.com facsimile — never trusting the leaf index blindly (the SH pipeline
  lost 6 pages to exactly this).

Strata available in Vol. 2: Hebrew-dense (Atonement, Baal, Babylon, Ab/Av), Greek
(Apocrypha, Aristotle), normal body (biographical/place entries), reference/running-head-
heavy (short-article pages), footnote/table, and low-quality/light scans (to be located).

### 2.6 Sample + strata

**11 articles, 36 unique printed pages (IA-accessible). Never silently capped.**

JE.com article IDs are database integers; the slug in the URL is ignored by the server
(only the numeric ID routes). All IDs confirmed by live fetch 2026-06-05.

| JE.com ID | Article title | Vol 2 pages | Stratum |
|---|---|---|---|
| 1644 | APOCRYPHA | 1–6 | Greek-heavy (NOTE: pp 1–6 below IA scan floor) |
| 1651 | APOLOGISTS | 8–11 | Normal body (pp 8–9 below IA floor; pp 10–11 accessible) |
| 1654 | APOSTASY AND APOSTATES FROM JUDAISM | 12–18 | Normal body |
| 1675 | AQUILINO, RAFFAELE | 38 | Running-head-heavy (PIPE-29 anchor page) |
| 1676 | AQUIN, LOUIS-HENRI D' | 38 | Running-head-heavy |
| 1678 | AQUINAS, THOMAS | 38–40 | Footnote/cross-ref heavy |
| 1680 | ARABAH | 40 | Short geographic entry |
| 1685 | ARABIC-JEWISH PHILOSOPHY, GENERAL VIEW OF | 45–49 | Long theological |
| 2092 | ATONEMENT | 275–284 | Hebrew-dense (10 pages) |
| 2093 | ATONEMENT, DAY OF | 284–289 | Hebrew-dense (Yom Kippur) |
| 2236 | BA'AL AND BA'AL-WORSHIP | 378–381 | Hebrew-dense B-section |

**IA-accessible pages fetched:** 10–18, 38–40, 45–49, 275–289, 378–381 = **36 pages**.

**PIPE-29 finding:** The IA scandata for cu31924091768196 has no leaf mapping for printed
pages 1–9 (only body pages 10–685 are mapped). JE.com "V:2 P:1" for APOCRYPHA refers to
physical page 1 of the volume, which is an unnumbered preliminary leaf in the IA scan.
Accessible via `--include-unnumbered` but excluded from the current sample. The APOCRYPHA
text was fetched from JE.com for reference; its IA scan pages require separate handling.

The leaf offset is NOT constant across the volume (Phase 0 claim of "contiguous" was
optimistic). Confirmed offsets: pp 10–18 → leaves +31; pp 38–49 → leaves +35; pp 275–289
→ leaves +37; pp 378–381 → leaves +45. The jumps indicate inserted fold-out plates/maps
between printed sections. PIPE-29 cross-check on pp 38–40 passed (see §2.7).

**Low-quality / abnormal stratum (visual inspection, Phase 3):** The following pages
contain abnormal content identified by visual inspection of the fetched scans. All are
excluded from the Phase 3 WCT build (LayoutEscalation or near-blank); all exclusions are
explicit — no pages silently dropped (SCALE-02).

| Page | Article | Abnormality | WCT outcome | Future-work note |
|---|---|---|---|---|
| 0012 | Apostasy | Horizontal table at page bottom with **sideways column headers**. Remaining page is normal 2-column body text. | LayoutEscalation: `spanning_lines` (table header box crosses gutter) | Tables with rotated/sideways headers need a table-zone detector that separates them from body columns before layout authority runs. |
| 0283 | Atonement | **Large picture** occupying the centre of the page; article text continues at top and bottom in two columns. | LayoutEscalation: `engine_disagreement` (ABBYY detects 2 cols, Tesseract detects 1 due to picture breaking the column evidence) | **Recoverable text is lost here.** A picture-aware layout pass (detect image zones first, detect columns only over text regions) would let this page build correctly. |
| 0285 | Atonement, Day of | **Large picture**, near-blank from OCR perspective (ABBYY: 1 word '?', Tesseract: 0 words). | LayoutEscalation: `zero_geometry` / `single_provider` | No useful text to measure regardless. Skip is correct. |
| 0287 | Atonement, Day of | **Large picture**; only visible text is the image title/caption. | WCT built (passes column detection; caption text forms sparse positions). | Caption-only pages produce very low position counts; measurement weight is negligible but positions are not excluded. Flagging these automatically would require a "sparse content" heuristic. |
| 0289 | Atonement, Day of | Page contains **music notation** (staff, notes). OCR engines attempt to read it as text. | WCT built (column detection unaffected by music zone). | Musical notation is completely outside OCR scope. Positions derived from music-zone OCR are noise in the alignment. A music-zone detector would route these positions to `unverifiable/excluded`. |

Several other pages in the sample contain **smaller inline pictures** (single-column
illustrations). These do not disrupt column detection and their WCTs build normally.

The leaf-offset jumps in the PIPE-29 note (+31/+35/+37/+45 across page ranges) are consistent
with inserted fold-out plates between sections — these plates are the source of the picture
pages above.

**ABBYY source selection — DECIDED.** Two IA lineages found for JE Vol 2:

| Item ID | GZ size | Leaves 73–75 mean confidence |
|---|---|---|
| `cu31924091768196` (Cornell) | 66.6 MB | **64.0** |
| `TheJewishEncyclopediaFunkWagnallVolIIApocryphaBenash1902` (2017 HTML5 upload) | 41.9 MB | 37.1 |

Cornell is 27 confidence points higher. **Winner: `cu31924091768196` as the ABBYY engine input.**
Probe tool: `build/tools/probe_abbyy_confidence.py`. Leaves 73–75 = printed pages 38–40 (PIPE-29, offset +35).

### 2.7 Edition-match evidence

**PASSES.** Checked on 3 pages (38, 39, 40) — the same 1901 Funk & Wagnalls printing.

| Page | JE.com article (excerpt) | Tesseract OCR text (excerpt) | Match |
|---|---|---|---|
| 38 | AQUILINO: "Italian apostate who renounced his religion in 1545" | Running headers "Aquilino Aquinas"; AQUILA article body with Hebrew רקמה, Greek φυλακτήριον, and Ezekiel xvi reference | ✓ Same edition — Greek and Hebrew chars preserved in both |
| 39 | AQUINAS: "contradiction to the divine wisdom and can not proceed from God ('Contra Gentiles,' i. 7)" | "contradiction to the divine wisdom and can not pro- ceed from God ('Contra Gentiles,' i. 7)" (word-for-word match across line break) | ✓ Verbatim match |
| 40 | AQUINAS bib entry references Maimonides | "Thomas v. Aquina zu Maimonides, in Theol. Quartalschrift, xxxi. 553" | ✓ Same edition |

**JE.com character encoding verified:** UTF-8 clean; ḳ (U+1E33), ḧ (U+1E27), Greek αποκρύπτω,
Hebrew עֲבוֹדָה — all preserved in the JE.com diplomatic transcription. The IA scan OCR also
preserves these (Tesseract output confirms). No edition-offset issue detected. This is the
same 1901 printing the IA scanned, confirming non-circularity of the reference.

---

## 3. Engine-voting table (does each panel engine contribute geometry on JE?)

**Panel for JE = ABBYY (IA), Azure (azure_read), Tesseract, Kraken, Kraken-Greek.** Only
**Surya** is excluded (too compute-heavy for this surrogate run, per the maintainer).
Dropping Surya costs no WCT geometry — in the SH run only ABBYY and Tesseract carried word
geometry (Surya's words sat inside `blocks`).

**Smoke test: WCT built for pages 38 and 39 (2026-06-05), panel = Tesseract + Azure + Kraken.**
ABBYY lane deferred to Phase 2 (requires per-page extraction from IA GZ file, 74.3 MB;
new extraction tool needed). Surya excluded by design. Kraken-Greek excluded from this
smoke test (no Greek pages in the p38–39 cluster; will be confirmed on a Greek-heavy page
in Phase 2).

| Engine | Family in WCT | Geometry positions (page 38) | Geometry positions (page 39) | Verdict |
|---|---|---|---|---|
| Tesseract (tesseract-py314-v1) | `tesseract` | 902 | — | ✓ Votes with geometry |
| Azure AI Vision (azure-ai-vision-v1) | `azure-ai-vision` | 909 | — | ✓ Votes with geometry |
| Kraken (kraken-py312-v1) | `kraken` | 0 (text-only) | — | Text-only, no geometry (expected) |
| ABBYY (ia-abbyy-v1) | `abbyy` | **1058** (all words) | — | **✓ Votes with geometry** — 1058/1058 words have bbox_native; 36/36 pages done |
| Kraken-Greek (kraken-greek-py312-v1) | `kraken` | 0 (text-only) | — | **✓ Confirmed.** 1248 words p38 (vs 1029 Kraken), 75 with Greek-range codepoints; geometry=False. Standard Kraken finds 0 Greek words. |

**Key Phase 1 finding:** Azure AI Vision contributes **word-level bounding-box geometry** to
the WCT (909 geometry positions on page 38), qualifying it as a geometry anchor alongside
Tesseract. This was the critical open question from Phase 0 — Azure was absent from the SH
10-page WCT. For JE it votes normally.

**ABBYY geometry (Phase 2 confirmed):** 1058/1058 words on page 38 have `bbox_native` →
ABBYY votes with geometry, as expected from the SH run. WCT with ABBYY+Tesseract+Azure
has 1263 positions (vs 1160 without ABBYY). `s1_abbyy_normalizer_je.py` passes render_s2
schema validation.

**Kraken as text-only:** Confirmed. Kraken carries no bbox (1029 words, geometry=False on
page 38), consistent with SH findings. Contributes candidate readings via text alignment only.

**Kraken-Greek (Phase 2 confirmed):** 36/36 sidecars. p38: 1248 words, geometry=False,
75 words with Greek-range codepoints. Standard Kraken finds 0 Greek words on the same page —
Kraken-Greek is the specialist for Greek script and expands candidate readings on Greek content.
engine_family = "kraken" (collapses to same independence block as Kraken, per family_independence.py).

**Layout authority (Phase 2):** WCT built with ABBYY+Tesseract+Azure as geometry anchors,
Kraken as text-only. No `LayoutEscalation` triggered on page 38. Surya not needed.

**WCT for pages 38–39:** Phase 1: 1160 positions (Tesseract+Azure+Kraken). Phase 2: 1263
positions (ABBYY+Tesseract+Azure+Kraken), confirming ABBYY adds alignment coverage.

**Phase 2 panel progress (2026-06-05):**

| Engine | S1 sidecars | Pages covered |
|---|---|---|
| ABBYY | 36 / 36 | All sample pages — new `s1_abbyy_normalizer_je.py` |
| Tesseract | 36 / 36 | All sample pages |
| Kraken | in progress | 36 target |
| Kraken-Greek | in progress | 36 target |
| Azure | **36 / 36** | All 36 sample pages — `s1_azure_normalizer_je.py` (added 2026-06-06). |

**ABBYY S1 format note:** `s1_abbyy_normalizer_je.py` emits JE-correct `work_id`, `edition_id`, and `rendering_id` (unlike the Tesseract/Kraken sidecars which still embed SH constants). Full clean-up of Tesseract/Kraken work_id is a Phase 3 item.

**Smoke test work_meta note (Phase 1):** The Phase 1 smoke test sidecars embed `work_id:
"schaff-herzog-encyclopedia"` because `s1_azure_normalizer.py` imports SH-specific
constants. ABBYY sidecars are now correct; Tesseract/Kraken/Azure are Phase 3 clean-up.

---

## 4. M0 / M1 / M2 / M3

Measured 2026-06-06. Tool: `build/tools/measure_je.py`. Source: `reports/je-gold/vol_02/`.

### Population and exclusions

| Count | Description |
|---|---|
| 11 articles | Total sample |
| 1 excluded (1644-apocrypha) | n_aligned = 0 — all pages below IA scan floor (pp 1–6), no WCT |
| 10 articles measured | |
| 30,918 reference tokens | Total across 10 articles |
| 49,760 WCT positions | Total across pages with WCT (34 built; pages 0012 and 0283 LayoutEscalation) |
| **24,952 aligned pairs** | 80.7% of ref tokens; 50.1% of WCT positions |
| 6,329 ref tokens unaligned | Aligner-gap (no WCT match) |
| 25,171 WCT positions unaligned | Aligner-gap (no ref match) |

**Circular-subset flag:** zero. The reference (JE.com) is never derived from engine output.
**Alignment noise caveat:** all rates are floor estimates. The NW aligner uses B8-tuned
`confusion_distance` (GAP_PENALTY=0.6, confirmed optimal 2026-06-06) for the alignment path.
Misaligned pairs inflate the mismatch count. The B8 sweep showed no M0 improvement within
the coverage constraint — these numbers are the aligner floor.

### Per-article results

| Article | M0 | M1 | M2 | M3h | M3t | Missing WCT pages |
|---|---|---|---|---|---|---|
| apologists | 11.7% | 11.7% | 13.2% | 18.5% | 21.7% | 8, 9 |
| apostasy | 71.8% | 72.3% | 78.9% | 88.4% | 91.2% | 12 |
| aquilino | 56.4% | 56.8% | 60.7% | 89.2% | 87.3% | — |
| aquin-louis-henri | 79.2% | 79.2% | 84.0% | 25.0% | 16.7% | — |
| aquinas | 22.7% | 23.0% | 24.3% | 17.6% | 18.3% | — |
| arabah | 57.8% | 57.8% | 62.0% | 47.1% | 50.0% | — |
| arabic-jewish-philosophy | 42.7% | 43.3% | 46.8% | 45.4% | 47.0% | — |
| atonement | 45.5% | 46.2% | 51.7% | 63.2% | 66.6% | 283 |
| atonement-day-of | 67.1% | 67.9% | 74.4% | 86.5% | 90.6% | — |
| baal-and-baal-worship | 37.0% | 37.5% | 41.9% | 42.9% | 47.0% | — |

**Metric definitions:**

- **M0** — consensus match: `ocr_norm == ref_norm` for the `_best_candidate` reading.
- **M1** — any-engine match: any candidate in the WCT position's `candidate_set` has
  `norm(raw_reading) == ref_norm`. Denominator = M0 denominator (aligned pairs where WCT
  position file was found — all 24,952 in this run).
- **M2** — multi-family consensus accuracy: population = aligned pairs where the best candidate
  is attested by ≥2 distinct independent engine families; numerator = those with `match=True`.
  19,012 of 24,952 positions (76.2%) qualify. `alignment_confidence` formula:
  `0.5 + 0.5 * (attesting_engines / available_engines)`, capped at 0.99.
- **M3h** — high-attestation accuracy: `alignment_confidence ≥ 0.875` (≥75% of available
  engines attest the position; in a 5-engine run this means ≥4 engines attest the position —
  readings may still differ). 5,892 positions. **Note: this includes text-only Kraken lanes**
  — it is all-engine attestation, not geometry agreement.
- **M3t** — top-attestation accuracy: `alignment_confidence ≥ 0.99` (all available engines
  attest this position — readings may still differ). 3,520 pairs (14.1% of aligned pairs).
  All M3t positions include Kraken text-only attesters; the cap of 0.99 applies when all 5
  engines (ABBYY + Tesseract + Azure + Kraken + Kraken-Greek) attest the position. 41% of
  M3t positions have candidate_set > 1 (engines attest but disagree on the reading).

### Aggregate

| Metric | Rate | N |
|---|---|---|
| M0 | 47.7% | 24,952 |
| M1 | 48.2% | 24,952 |
| M2 | 53.8% | 19,012 |
| M3h | 65.2% | 5,892 |
| M3t | **69.5%** | 3,520 |

### Complete-page-only aggregate (adversarial review cross-check)

7 articles with no missing WCT pages: aquilino, aquin-louis-henri, aquinas, arabah,
arabic-jewish-philosophy, atonement-day-of, baal. (atonement-day-of joins because page 285
now builds with 5 engines — Azure provided the third geometry anchor, resolving the
`zero_geometry/single_provider` escalation.) Run: `py -3 build/tools/measure_je.py --complete-only`.

| Metric | Complete-page only | All-article aggregate | Difference |
|---|---|---|---|
| M0 | 46.8% | 47.7% | -0.9pp |
| M1 | 47.5% | 48.2% | -0.7pp |
| M2 | 52.3% | 53.8% | -1.5pp |
| M3h | 61.0% | 65.2% | -4.2pp |
| M3t | **65.9%** | 69.5% | -3.6pp |

The 4-engine finding that M3t ≈ M2 in the complete-page stratum no longer holds:
complete-page M3t (65.9%) exceeds M2 (52.3%) by 13.6pp. Partial-page selection bias still
exists (aggregate 69.5% vs complete-page 65.9%), but the magnitude is now 3.6pp rather than
the 26.1pp gap in the 4-engine run. The all-engine attestation signal is robust in both strata.

**Why the aggregate–complete gap shrank:** in the 4-engine run, 4 partial-page articles (including
atonement-day-of with missing page 285) drove a large gap by concentrating measurement on
clean prose pages. With 5 engines, page 285 now builds; atonement-day-of moves to the complete
stratum and its high M3t (90.3%) now appears in both aggregates. The remaining partial articles
(apologists, apostasy, atonement) still inflate the aggregate, but their weight is smaller.

**Position double-counting:** 245 aligned pairs share a `position_id` with another article
(same physical page 38 spanned by aquilino, aquin-louis-henri, and aquinas; complete-page
stratum only — 837 pairs when partial articles are included). M3t denominator is overstated
by ~26 pairs in the complete-page stratum (1360 → 1334 after dedup). This is transparent rather than silent —
`measure_je.py` reports the overlap count and dedup aggregate on every run.

**Practical implications:**
- Complete-page M3t (65.9%) is now a usable lower bound for the trust-model signal.
  It is still downward-biased by the aquinas bibliography anomaly (M3t=18.3% < M0=22.7%).
- Aggregate M3t (69.5%) is upward-biased by partial-page selection; use with caution.
- B8 aligner tuning is complete (GAP_PENALTY=0.6 confirmed optimal; sweep showed no M0 improvement within the coverage constraint). These rates are the post-confusion_distance-fix tuned floor.

### Notable per-article anomalies

**aquinas M3h/M3t (16.8%/17.1%) < M0 (22.8%):** The high-attestation positions for this article
are predominantly bibliography entries (dense abbreviations, Roman numerals, German/Latin
journal names). These positions are highly attested by all engines — all agreeing on a complex
multi-token abbreviation string — but the reference transcription also has the abbreviation,
just with different hyphenation or spacing after NFKC normalization. The M3 stratum for
aquinas is not more accurate; it is more consistently wrong in a specific way (abbreviated
citation patterns that survive normalization differently). This anomaly persists across both
4-engine and 5-engine runs.

**aquilino/apostasy M3h/M3t > 85%:** Short entries, clean English body text, minimal Hebrew.
High-geometry positions land on normal prose tokens where OCR is reliable. Confirms that M3t
≥ 85% is achievable for OCR-friendly content.

**atonement-day-of M3t=90.3% (complete-page stratum):** This article joins the complete-page
stratum in the 5-engine run. Page 285 (a large-picture near-blank page) now builds — Azure
provides the third geometry anchor, yielding 7 positions. The article's high M3t is consistent
with clean Hebrew-transliteration prose pages where OCR engines agree strongly.

**apologists across the board (~12–22%):** Pages 8–9 (the article's main body) are below the
IA scan floor. Only pages 10–11 have WCT. The reference text is the full article
(~3,000 tokens). The NW aligner distributes all reference tokens proportionally — including
the body that is not in any WCT page. Those pairs align to whatever positions happen to be
at the right proportional offset, producing systematic noise. The article-level rates for
apologists are unreliable; exclude from trust-model calibration.

---

## 5. Family independence on JE

**Panel:** ABBYY (IA), Tesseract, Azure AI Vision, Kraken, Kraken-Greek. Surya excluded
by design (compute ceiling; geometry not needed from Surya for this run).

| Engine | `engine_family` | Geometry | Independence block |
|---|---|---|---|
| ABBYY (ia-abbyy-v1) | `abbyy` | ✓ word-level bbox | Block A |
| Tesseract (tesseract-py314-v1) | `tesseract` | ✓ word-level bbox | Block B |
| Azure AI Vision (azure-ai-vision-v1) | `azure-ai-vision` | ✓ word-level bbox | Block C |
| Kraken (kraken-py312-v1) | `kraken` | ✗ text-only | Block D |
| Kraken-Greek (kraken-greek-py312-v1) | `kraken` | ✗ text-only | Block D |

Kraken and Kraken-Greek share `engine_family = "kraken"` → same independence block (D).
They agree on Latin-script tokens and diverge on Greek-script tokens (that's the point of
Kraken-Greek). Family-level deduplication treats them as a single vote.

**Three geometry anchors (ABBYY + Tesseract + Azure)** on JE vs two on SH (ABBYY + Tesseract
only, because Azure credentials weren't wired to the SH page set). All 34 built JE pages now
have 5 engines; `alignment_confidence` counts ALL available engines — not just the geometry
anchors. `available_engines = 5` throughout; `confidence = 0.99` requires all five
(ABBYY + Tesseract + Azure + Kraken + Kraken-Greek). `confidence ≥ 0.875` (M3h) requires
≥4 engines. Pages 0012 and 0283 have no WCT (LayoutEscalation); they contribute no M3 pairs.
The claim that M3t measures "geometry family agreement" is incorrect; it measures all-engine
reading agreement. The metric is still a useful quality signal, but for a different reason
than previously described.

**M2 denominator interpretation:** 19,012/24,952 = 76.2% of aligned positions have a best
candidate attested by ≥2 families. That means 76.2% of aligned positions reach multi-family
consensus. The M2 population is large, which dilutes the signal — M2 is a floor on the queue
the trust model would auto-accept, not a tight precision stratum.

---

## 6. Trust-model verdict

**The simple "≥2 families agree → auto-accept" rule is not calibrated.**

**Caveat before reading the table:** aggregate rates are upward-biased by partial-page
selection (see §4 caveats). Complete-page-only rates are the more conservative estimate.

| Auto-accept gate | Aggregate coverage | Aggregate accuracy | Complete-page accuracy |
|---|---|---|---|
| ≥2 families agree (M2) | 76.2% | 53.8% | 52.3% |
| conf ≥ 0.875 (M3h) | 23.6% | 65.2% | 61.0% |
| conf ≥ 0.99 (M3t) | 14.1% | 69.5% | **65.9%** |
| baseline (accept all) | 100% | 47.7% | 46.8% |

In the aggregate, M3t beats M2 by 15.7pp. In the complete-page stratum, M3t (65.9%) exceeds
M2 (52.3%) by 13.6pp — the 4-engine adverse finding (M3t ≈ M2 in the complete-page stratum)
is reversed. The all-engine attestation signal is robust in both strata.

The M2 gate remains clearly wrong: 46.2% error rate on 76.2% of positions is near-baseline
acceptance. The complete-page stratum (52.3% accuracy on 76.2% coverage) does not
rehabilitate it.

**Verdict for SH pipeline work:**

- Do not use ≥2-family agreement as the sole auto-accept gate. In both strata it performs
  near-baseline.
- **Aggregate M3t=69.5% is still upward-biased by partial-page selection.** Use complete-page
  M3t=65.9% as the more conservative estimate. The 5-engine panel closes the 4-engine gap
  substantially (was 26.1pp, now 3.6pp), but partial articles (apologists, apostasy, atonement)
  still inflate the aggregate.
- All-engine attestation (conf ≥ 0.99) is the best available gate, and its advantage over M2
  is now confirmed in the complete-page stratum (+13.6pp). The 4-engine uncertainty about
  magnitude is resolved: the signal is real.
- **B8 complete (2026-06-06).** GAP_PENALTY=0.6 was already optimal — sweep showed no M0
  improvement within the 3pp coverage constraint. Complete-page M3t=65.9% is the
  B8-confirmed floor (post-confusion_distance fix).
- **Alignment distance metric corrected (2026-06-06).** The NW distance table in
  `align_je_to_wct.py` was using plain Levenshtein (`_align_dist`) instead of
  `confusion_distance`. The difference matters for short tokens: ci/cl = 0.125
  (confusion) vs 0.500 (Levenshtein), enough to flip alignment decisions. Fixed.
- **Residual: folio cross-check guard (A6).** The folio-range check that confirms ABBYY
  GZ folios are drawn only from actual body pages was performed on 3 of 36 built pages
  (leaves 73–75). The unchecked ranges (leaves 40–72 and 76–109) are a known open risk.
  A full guard would read OCR sidecars for running-header text and confirm body-page
  membership before accepting a folio range. Not yet implemented. Proceed to threshold
  calibration but note this as a residual data-quality caveat.
- A trust matrix that ignores `alignment_confidence` and uses only family-vote counts cannot
  do better than M2 = 53.8% (aggregate) / 52.3% (complete-page).

Note: `alignment_confidence` is all-engine consensus (including text-only Kraken), not a
geometry-only gate. The practical recommendation is unchanged — use the metric — but
interpret it as "all engines agree on this reading" rather than "geometry confirms it."

---

## 7. What transfers to SH, what doesn't

**Transfers:**

- **All-engine-attestation gate architecture.** The `alignment_confidence ≥ 0.99` metric
  (all available engines agree on the reading) is a better gate than family agreement. The
  aggregate advantage (15.7pp) is upward-biased by partial-page selection; the complete-page
  estimate (M3t=65.9% vs M2=52.3%, +13.6pp) confirms the signal is real. Direction and
  magnitude are both robust; absolute threshold calibration is deferred (B8 is now complete).
  The SH WCT already computes `alignment_confidence` with the same formula. The gating logic
  requires no code changes — only a calibration decision on the threshold.

- **M1 ≈ M0 finding.** `_best_candidate` is not the accuracy bottleneck. The reading that
  maximizes attesting-family count is already the correct reading wherever any engine is
  correct. This transfers: don't invest in consensus algorithms until the OCR quality floor
  rises.

- **Script heterogeneity as a stratification axis.** Latin-script content (normal body text)
  achieves ~65–90% M3t on clean articles. Hebrew/Greek-heavy articles land at ~40–68% M3t.
  In SH, the German-language academic content (bibliographies, citations) will be the analog
  hard stratum. A script-aware or content-type-aware gate would let the trust model
  apply selectively to the easier stratum first.

- **Aligner noise as a confound.** The ~22pp gap between M0 (47.7%) and M3t (69.5%) includes
  both real OCR error and aligner noise. For SH, the CCEL-aligned gold has the same confound
  (CCEL alignment errors inflate the mismatch count). B8 is complete; GAP_PENALTY=0.6 is confirmed
  optimal for the JE oracle. The same parameter applies for SH alignment.

**Does not transfer directly:**

- **JE absolute rates.** JE Vol. 2 spans the A–B section of an early-20th-century Jewish
  reference work. SH is an early-20th-century German/English Protestant encyclopedia. OCR
  error profiles differ (SH has more German, diacritics, and academic German abbreviations;
  JE has more Hebrew transliteration). The absolute M0 of 47.7% for JE is not a prediction
  for SH — it is the B8-tuned floor for this oracle (GAP_PENALTY=0.6 confirmed optimal).

- **Azure engine count contribution.** JE has three geometry anchors (ABBYY, Tesseract, Azure)
  on all 34 built pages. The SH 10-page run had two (ABBYY, Tesseract) — Azure credentials
  weren't routed to those pages. In the JE run, conf=0.99 requires all 5 engines
  (ABBYY + Tesseract + Azure + Kraken + Kraken-Greek) throughout. The JE M3t population is
  therefore stricter than the SH 2-engine M3t equivalent would be. The 69.5% aggregate M3t
  (biased by partial-page selection — see §4 caveats) is not a direct comparison point for SH.

- **Apologists-style outliers.** The worst JE outlier (apologists, M0=12.7%) is pathological:
  half the article spans pages that don't exist in the WCT. SH articles are shorter and fully
  page-covered, so this distortion mode shouldn't occur at comparable scale.

**B8 tuning confirmed:** GAP_PENALTY=0.6 was already at or near the optimum (sweep over [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0] showed max M0 improvement of 0.0pp within the ≤3pp ref_coverage-drop constraint; lower gap values achieve higher M0 only by sacrificing coverage below threshold).

---

## 8. pytest result

```
py -3 -m pytest -p no:cacheprovider -m "not slow" -q tests/test_align_je_to_wct.py tests/test_build_je_wct_batch.py tests/test_s1_azure_normalizer_je.py
44 passed, 1 warning in 11.93s
```

(16 aligner tests + 11 batch-builder tests + 17 Azure normalizer tests. Full suite not run
in this branch — SH fast suite passes at the merge base commit before this branch diverged.)
