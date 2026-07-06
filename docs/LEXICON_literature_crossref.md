# OCD pipeline vocabulary — literature cross-reference

Built 2026-06-18. **Purpose:** a menu, not a mandate. For each object in the OCD / NSH OCR
pipeline, this records what the surrounding literature calls it — so the canonical names chosen
for `SHARED-LEXICON.md` can adapt established terms where they fit and coin plainer ones where they
don't. The chosen naming rule is **the simplest functional description that captures what the thing
is, distinctly** (no overload with any other term).

Four literatures touch this pipeline:
- **OCR output formats** — ALTO XML, PAGE XML, hOCR (the standard structured-OCR encodings).
- **Multi-system fusion** — ROVER and word confusion networks (from speech recognition, applied to OCR).
- **Post-OCR correction** — the sub-field that fixes OCR after the fact.
- **Textual criticism / digital scholarly editing** — TEI critical apparatus, CollateX, Juxta.

Sources are listed at the foot.

---

## The cross-reference table

`Verdict`: **keep** = current OCD name is already clear and/or literature-aligned; **rename** =
collides or is vague, needs a new canonical name.

| # | What it is (function) | Current OCD name | OCR-fusion / format literature | Textual-criticism (TEI) | Verdict + proposed name |
|---|---|---|---|---|---|
| 1 | digital photo of one page | scan / `page_NNNN.jpg` | page image, document image | facsimile | **keep** — page image |
| 2 | stable label for a physical page shared across every engine and scan | `canonical_leaf_id` / `leaf_num` | page id | **leaf** (recto+verso), folio | **keep** — already the correct bibliographic term |
| 3 | one OCR program that reads page images | engine / `source_lineage_id` | OCR engine, recognizer, OCR system | the "hand" that produced a witness | **keep** — engine |
| 4 | a group of engines whose agreement is not independent | `engine_family` | correlated systems | **family** / recension (manuscripts grouped in a stemma) | **keep** — engine family (and it is TC-aligned) |
| 5 | what one engine read on one page (words + boxes + confidence) | **sidecar** / `sidecar-page-v1` | OCR result, OCR output, **hypothesis** (ASR); an ALTO/PAGE/hOCR file | **witness**; **diplomatic transcription** | **rename** — proposed: **engine page-read** (or "page read") |
| 6 | the index of all of one engine's page-reads for a volume | `sidecar-manifest-v1` / manifest | OCR document/volume manifest | — | **rename** — proposed: **read index** |
| 7 | an engine page-read re-expressed in the house schema | **rendering** / `rendering-v1` | normalised OCR output | **normalised transcription** (vs diplomatic) | **rename** (collides with dataset "Rendering") — proposed: **normalised read** |
| 8 | the set of engines compared on a page | `available_engines` / panel | system ensemble, recognizer set | the collated witnesses | **keep** — engine panel |
| 9 | different photographs of the same edition | alternate scans / lineages (`dli`, `haucgoog`, …) | — | copies, **exemplars** | **keep** — alternate scans |
| 10 | the act of lining up engines word by word | `build_wct` (and dataset `Reconcile`) | **ROVER alignment**, multiple-sequence alignment | **collation** | **keep** — (dataset half already calls it Reconcile) |
| 11 | the per-page table of every word-slot with each engine's reading | **WCT** / `word-confusion-table-v1` | **word confusion network (WCN)** — a sequence of bins | **critical apparatus**, collation table | **rename** (acronym, opaque) — proposed: **word-comparison table** |
| 12 | one place on the page where engines give readings | `position` | **bin** / confusion bin / slot; Word / String (formats) | **apparatus entry** (`<app>`), variation site | **rename** — proposed: **word slot** |
| 13 | what one engine read at one slot | **candidate** / `candidate_set` | hypothesis token, arc; `ALTERNATIVE` (ALTO) | **reading** (`<rdg>`), variant reading | **rename** — proposed: **reading** |
| 14 | which engines produced a given reading | `attesting_engines` / `attesting_families` / `witness_coverage` | votes, support | **witnesses** (`wit`), **attestation** | **keep** — attestation (already a lexicon term) |
| 15 | turning the comparison table into one chosen text | gold-free corrector | **post-OCR correction**, post-hoc correction; consensus decoding | establishing the text, editing | **keep** — corrector (note: literature = "post-OCR correction") |
| 16 | the corrector's per-page output (chosen reading per slot + provenance) | `corrected-page` (also mislabelled "sidecar") | consensus hypothesis, 1-best output | **established text**, critical text; `<lem>` (lemma) | **rename the label** — proposed: **corrected page** (drop "sidecar") |
| 17 | a composed reading no single engine produced | composed reading / `machine_composed` (L1+) | synthesised hypothesis | **conjecture** / conjectural **emendation** | **keep** — composed reading (already a lexicon term) |
| 18 | which source produced each character of a composed reading | `character_provenance` | — | per-reading provenance | **keep** — character provenance |
| 19 | an engine's certainty in a reading | `confidence` | OCR confidence, recognition confidence | — | **keep** — confidence |

---

## What this says at a glance

- **Most of the vocabulary is already fine** — 12 of 19 are "keep," and several (`leaf`, `engine family`,
  `attestation`, `composed reading`) are already textual-criticism-aligned without anyone planning it.
- **Only ~6 objects actually need renaming:** the S1 "sidecar" (5), its manifest (6), the S2 "rendering"
  (7), the "WCT" (11), the "position" (12), the "candidate" (13) — plus dropping the stray "sidecar"
  label off `corrected-page` (16).
- **The forced one is "rendering" (7)** — the dataset lexicon already owns that word, so the NSH S2 object
  must move regardless of taste.
- **The whole chain is, in literature terms, automated collation of OCR witnesses into a critical
  apparatus, then establishing a corrected text** — which is exactly what the pipeline does.

## Proposed canonical set (one consistent, plain family — for review, not locked)

> page image -> [engine] -> **engine page-read** -> **normalised read** -> collated into the
> **word-comparison table** (made of **word slots**, each holding one **reading** per engine,
> with **attestation**) -> the **corrector** composes the **corrected page** (an **established**
> reading per slot; a **composed reading** where no engine had it).

---

## Sources

- ROVER (recognizer output voting error reduction): [Fiscus 1997, ResearchGate](https://www.researchgate.net/publication/2397671_A_Post-Processing_System_To_Yield_Reduced_Word_Error_Rates_Recognizer_Output_Voting_Error_Reduction_ROVER)
- Word confusion networks: [Mangu, Brill, Stolcke, "Finding consensus in speech recognition", arXiv cs/0010012](https://arxiv.org/pdf/cs/0010012)
- Lexicon-verified ROVER: [LV-ROVER, arXiv 1707.07432](https://arxiv.org/pdf/1707.07432)
- OCR output formats (ALTO / PAGE / hOCR): [UB-Mannheim ocr-fileformat](https://github.com/UB-Mannheim/ocr-fileformat), [ALTO XML overview](https://easydataworld.com/alto-xml/)
- Post-OCR correction: [Neural OCR Post-Hoc Correction of Historical Corpora, arXiv 2102.00583](https://arxiv.org/pdf/2102.00583)
- OCR-D ground-truth / transcription: [OCR-D GT guidelines](https://ocr-d.de/en/gt-guidelines/trans/)
- TEI critical apparatus (app / lem / rdg / wit): [TEI Guidelines ch. 13](https://www.tei-c.org/release/doc/tei-p5-doc/en/html/TC.html)
- Textual-criticism terms (witness, collation, diplomatic, critical edition): [Textual criticism, Wikipedia](https://en.wikipedia.org/wiki/Textual_criticism)
