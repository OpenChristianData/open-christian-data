# Format state map — end-to-end fidelity orientation

**Status:** Living orientation doc (seeded 2026-06-18; rows filled as each format is walked)
**Purpose:** Before correcting the corpus, know where *every* source format actually stands. One row per format family → its parsers → an end-to-end walk (raw → parser → output) → a fidelity status. This is the orientation that makes correction comprehensive and prioritized instead of bug-by-bug.

## Why this exists

The fidelity-execution plan (`plans/_archive/2026-06-18-fidelity-execution/`) fixes three *confirmed* bugs (City of God, Catholic Encyclopedia, Creeds). Those were found by chance, not by a systematic sweep. This map walks every format family end-to-end so the real state is known — what is faithful, what loses structure silently, what is the wrong shape for the target model. It feeds both halves of the pipeline: the fidelity corrections and the structure redesign (registry-readiness per format).

Method per row is in `plans/_archive/2026-06-18-fidelity-execution/07-format-state-walk.md`.

## Format families (grounded in the parser + config inventory, 2026-06-18)

56 parsers cluster into these families. "Status" is the end-to-end walk result; "—" = not yet walked.

| # | Format family | Source format | Parsers (count) | Walked sample | Status |
|---|---|---|---|---|---|
| 1 | **CCEL ThML** | ThML XML (~209 configs) | ~20 `ccel_*` (npnf1/2, anf, schaff_hcc, schaff_herzog, owen_works, puritan_works, hodge, robertson, expositors, devotional, sermon, …) | `ccel_npnf1` → City of God | **Faithful** (sample) |
| 2 | **Standard Ebooks** | XHTML (9) | `standard_ebooks` | City of God | **Broken in JSON; recovered in TEI IR** (`2dd8e850`) — batch 02 superseded by the raw→TEI path |
| 3 | **Pre-structured JSON** | JSON | `creeds_json_catechism`, `creeds_json_confession`, `helloao_commentary`, `bible_text_translations` | `creeds_json_*` → Heidelberg | **Fixed** (batch 03, `f9e40d51`) — was: wrong `original_language`, dropped metadata |
| 4 | **Headword reference** | ThML/OCR/JSON | `catholic_encyclopedia`, `bible_dictionaries`, `ia_hastings_dictionary`, `naves_topical` | `catholic_encyclopedia` → vol01 | **Fixed** (batch 03, `f9e40d51`) — was: apparatus hard-coded `[]`; siblings (hastings, bible_dictionaries, naves) still to fix |
| 5 | **Gutenberg plain text** | plain text (~16) | `gutenberg_*` (anglican, catechisms, commentary, evangelical, maclaren, puritan, sermons, systematics, theology) | `gutenberg_theology` + `gutenberg_systematics` + `gutenberg_commentary` | **Fixed for JSON projection** — inline emphasis markers stripped; bare numeric `[N]` anchors tagged as `[[pg-note-anchor:N]]`; TEI still needed for true `<hi>`/note structure |
| 6 | **Internet Archive OCR** | DjVuTXT / OCR txt / OCR sidecars | `ia_abbyy`, `ia_*_dictionary`, `ia_schaff_herzog*`, `ia_fisher_marrow`, `local_schaff_tesseract` | `ia_fisher_marrow` + NSH OCR family | **Mixed** — Fisher remains partial loss; NSH legacy DjVu parser is superseded by the sidecar/rendering/WCT pipeline. English prose OCR is usually OCR-GOOD, but Greek/Hebrew apparatus stays OCR-RAW unless a richer OCR lane proves otherwise |
| 7 | **SWORD modules** | zCom / rawLD | `sword_commentary`, `sword_devotional` | Barnes/Calvin/Wesley + Daily Light | **Structure-faithful; apparatus lost** — module is itself a projection; Calvin loses 22,465 notes + 31,300 lang spans; acquire upstream OSIS/ThML for any IR |
| 8 | **Versified Bible** | JSON / DB | `bsb_bible_text`, `bible_text_translations` | BSB + KJV | **Faithful** — apparatus upstream-absent (not parser-dropped); only KJV of 8 planned PD translations built |
| 9 | **Anglican liturgy** | HTML / text | `bcp1662`, `bcp1928`, `bcp_full_text` | bcp1662/1928 collects + full-text | **Recovered in TEI IR** — 1549/1559/1662 services plus 1928 collects now have census-gated TEI preserving services, collects, labels, rubrics, and speaker units; JSON remains legacy projection |
| 10 | **Misc single-source** | CSV / wikitext / Logos / web HTML | `hymnary_pd`, `didache`, `schleitheim_confession`, `logos_schaff_herzog`, `spurgeon_mtp` | hymnary_pd + didache + schleitheim + logos + spurgeon | **Mixed** — hymnary/didache faithful for their scope; Schleitheim output is contaminated by site chrome; Logos NSHERK is a limited same-edition witness, not a second edition; Spurgeon MTP drops ordered-list sermon body blocks |

**Key orientation finding so far:** fidelity varies by *parser*, not just by format. Within one work (City of God) the CCEL edition is faithful and the Standard Ebooks edition is broken. The walk must be per-parser, and the same work can exist at two fidelity levels (a curation question, below).

## Walked rows (detail)

### 1 — CCEL ThML · `ccel_npnf1` · City of God — **Structure-faithful; apparatus lost** (grain corrected 2026-07-02)
- Raw: `https://www.ccel.org/ccel/schaff/npnf102.xml` (ThML). Output: `data/structured-text/augustine-city-of-god.json`.
- Structure: 22 books → ~29 chapters each, real chapter titles, 683 total nodes. Full hierarchy preserved.
- **Apparatus grain (added 2026-07-02, from the TEI-pilot census):** the JSON parser's `_SKIP_TAGS`
  silently drops all 1,698 footnotes and 515 page breaks; 899 italic runs and 141 language spans
  flatten to plain strings (the schema's `content_blocks` are strings and cannot carry them). The
  original "Faithful" verdict judged structure only. The TEI IR
  (`ir/augustine/city-of-god.ccel-npnf102.tei.xml`, built from raw, census-gated) preserves all of
  it. Future walks must record BOTH grains: structure and apparatus.
- Right shape: dict-shaped `data` (`{work_id, work_kind, sections}`), nested `children`. Schema-valid.
- Issues: none structural. (CCEL family is large/varied — one faithful sample does not clear all ~20 `ccel_*` parsers; walk the high-volume ones: npnf2, anf, schaff_hcc, owen_works, puritan_works.)

### 2 — Standard Ebooks · `standard_ebooks` · City of God — **Broken in JSON; recovered in TEI IR** (2026-07-02)
- Raw: Standard Ebooks XHTML (Dods translation). Output: `data/structured-text/city-of-god.json`.
- Structure: 3 top sections, 0 chapter titles, for a 22-book work. Same-file nested `<section>` chapters flattened into book-level blobs.
- **Recovered via the TEI pilot (2026-07-02):** `ir/augustine/city-of-god.standard-ebooks.tei.xml`
  carries the full nested structure (22 books; book 1 = preface + 36 chapters, heads + arguments)
  plus all 1,691 endnotes inlined — census-gated. Batch 02's standalone parser patch is superseded
  by the raw→TEI path; the published JSON regenerates as a TEI projection when the dataset flips to
  projected output.

### 3 — Pre-structured JSON · `creeds_json_*` · Heidelberg / confessions — **Partial loss**
- `original_language` hard-coded `"en"` though the source declares it (non-English for ~23 of ~41); `OriginStory` + 4 other metadata fields never read.
- Fixed: batch 03 (`f9e40d51`, 2026-07-02) — language map fails loudly on unmapped values; dropped fields recorded in provenance notes. NB: `original_language` is an **envelope field** the works registry will own (unified plan §2) — the parser fix is interim and seeds the registry later.

### 4 — Headword reference · `catholic_encyclopedia` · vol01 — **Partial loss**
- `scripture_references` / `related_terms` / `alt_terms` hard-coded `[]` for all 317 vol01 entries (3,674 corpus-wide); non-ASCII headword keys drop the leading letter (`Æons` → `ons`).
- Fixed: batch 03 (`f9e40d51`, 2026-07-02) — refs via shared OSIS normalizer (86/317); related_terms = explicit See/See-also apparatus only (141/317; digitizer in-prose links excluded); negative provenance in meta notes; ligature transliteration for headword keys.

### 5 — Gutenberg plain text · `gutenberg_theology` · Confessions (+ Calvin 2nd sample) — **Structure-faithful; apparatus partial loss** (2026-07-03)
- Raw: `raw/gutenberg/pg3296.txt` (Augustine, Confessions, Pusey trans.). Parser: `build/parsers/gutenberg_theology.py::parse_augustine`. Output: `data/structured-text/augustines-confessions.json`.
- Structure: raw 13 `BOOK` headings, 0 chapters (Pusey edition omits them — parser notes document this); output 13 books, 462 content_blocks, 111,775 words. Exact match.
- **Apparatus grain (from the Calvin 2nd sample, pg64392 — Confessions is an apparatus-free outlier; only ~4 of 22 raw files carry none):** fixed in batch 01 (2026-07-05): the nine `gutenberg_*` parsers share a plain-text inline decoder. `_italic_` markers are stripped from JSON text fields, and bare numeric `[N]` anchors are preserved recoverably as `[[pg-note-anchor:N]]`. This is a JSON projection fix only: true emphasis structure and note bodies still require a richer upstream/TEI path. Front-matter title/translator block remains dropped but captured in meta. Encoding faithful (true UTF-8, U+201D preserved).
- Right shape: dict-shaped `data` (nested `children`) — harness must handle dict form. Schema-valid. Envelope fields present, `original_language: la` correct.
- Duplicate-edition: none — Confessions unique to this family.
- Correction result: semantic scan across regenerated `gutenberg_*` outputs found 0 bare `[N]` anchors and 0 `_..._` emphasis markers. `gutenberg_systematics` and `gutenberg_commentary` were walked as risky siblings; both validate after the shared decoder. Regeneration surfaced two pre-existing count drifts outside the inline-markup fix: Baltimore Catechism #3 `1400 -> 1398`, Maclaren `1257 -> 1255`.
- TEI candidacy: low-yield for clean works, higher for marked-up ones (IR gains `<hi rend="italic">`, explicit dangling-anchor `<ref>`s, `<front>`); weaker candidate than CCEL/SE.
- Sibling status: all nine `gutenberg_*` parser families now route text projection through the shared decoder; systematics/commentary were the high-risk walk targets for this batch.

### 7 — SWORD modules · `sword_commentary` + `sword_devotional` · Barnes / Calvin / Wesley / Daily Light — **Structure-faithful; apparatus lost** (2026-07-03)
- Raw: CrossWire SWORD binaries under `raw/sword_modules/` (commentaries zCom, Daily Light rawLD). `.conf` `SourceType`: Barnes/Wesley/Daily = ThML, Calvin = OSIS. Outputs: `data/commentaries/{barnes,calvin,wesley}/*.json`, `data/devotionals/daily-light/daily-light.json`.
- Structure counts, both ends, all exact: Barnes 7,322 / Wesley 17,564 / Calvin 13,338 verse entries; Daily Light 366 days -> 732 morning+evening records. No structural loss.
- **Apparatus grain:** the parser keeps only cross-references (`<scripRef>`/`<reference osisRef>` -> OSIS arrays). Everything else flattens to plain text with 0 residual markup (host-verified): Calvin (the heavy case) loses **22,465 `<note>` footnote boundaries, 31,300 `<foreign>` language spans, 196,065 `<hi>` emphasis runs, ~7,000 tables** — note bodies survive as undifferentiated inline prose, so translator-note vs commentary is no longer separable. Barnes loses 52,532 `<i>` italics. Daily Light's 1,218 per-quotation `<scripRef>` refs are dropped entirely (`primary_reference` hard-coded None, per config intent, but the refs the module carries leave no trace).
- Right shape: list `data`, schema-valid, envelope registry-clean, `verse_text_source: "none"` correct.
- Duplicate-edition: none (witnesses.json scaffolds empty).
- Correction implied: none against the module — **the SWORD binary is itself a downstream projection**; the high-value move is acquiring the upstream OSIS/ThML editions (esp. Calvin) and building any TEI IR from those; at minimum a SWORD-path fix would preserve Calvin notes/foreign and Daily Light scripRefs.
- Unwalked residue: Calvin OSIS `x-p` paragraph divs (305k markers) may flatten paragraphing — not quantified; `naves_topical` zLD reader (family #4/#10-adjacent); unused KJV ztext module.

### 8 — Versified Bible · `bsb_bible_text` + `bible_text_translations` · BSB + KJV — **Faithful; apparatus upstream-absent, not parser-dropped** (2026-07-03)
- Raw: `raw/bible_databases/formats/json/{BSB,KJV}.json` -> parsers -> `data/bible-text/{bsb,kjv}/*.json` (66 files each).
- Structure counts, both ends: each raw 66 books / 1,189 chapters / 31,102 verses. BSB out 31,086 (Δ16 = genuinely empty textual-critical verses, enumerated in config notes — dropped-with-provenance). KJV out 31,102 (Δ0).
- **Apparatus grain:** raw verse schema is `{verse, text}` only — censused across all 31,102 verses. Poetry lines, headings, and KJV supplied-word italics are **stripped upstream** (1 bracketed word survives in 31,102 KJV verses); the parser is a faithful passthrough of an already-flat source. One benign silent loss: BSB's latent poetry indent (leading whitespace on 3,261 verses, 10.5%) is `.strip()`ed — the only structural signal the raw carries; ambiguous, defensibly dropped, recorded here.
- Right shape: flat list `data` of `{osis, chapter, verse, text, ...}`; schema-valid; envelope clean; `original_language: "en"` correct here (contrast family #3's bug). `token_count` is injected downstream of the parser.
- Duplicate-edition: KJV exists once as an edition; commentary `verse_text_source` references are not editions.
- Correction implied: none. Poetry/italics need a tagged upstream (USFM/OSIS), not a parser patch. Scope note: only KJV of the 8 planned PD translations is built.
- **TEI position: this family stays JSON-native.** The flat `{osis, verse, text}` list is already the lossless projection of what the raw carries; a TEI IR would re-encode the same information with zero recovered fidelity. If OCD later ingests a tagged Bible source, that source gets an IR; this one does not need it.

### 9 — Anglican liturgy · `bcp1662` / `bcp1928` / `bcp_full_text` · BCP editions — **Recovered in TEI IR; JSON legacy remains lossy** (updated 2026-07-06)
- Outputs: `data/prayers/bcp-1662/collects.json` (85 records), `data/prayers/bcp-1928/collects.json` (102), `data/structured-text/bcp-{1549,1559,1662}.json` (34/14/20 sections).
- Structure: collect counts match raw markers (85=85; 99->102 documented). Full-text 1662: **15 of 20 services collapse to a single prose blob** (Holy Communion = one 7,187-word block) — rubrics, versicles, psalms, creed, responses flattened into undifferentiated prose.
- **Apparatus grain:** rubrics merged into prose with no marker (and the 1662 collect parser actively deletes repetition-note rubrics); versicle/response speaker labels (`Priest.`, `Answer.`) survive only as inline text with no speaker structure; `scripture_references` hard-coded `[]` for all 187 collect records; italics stripped.
- **Broken (new confirmed data bug, host-verified):** 5 of 20 full-text 1662 sections are **HTTP 404 error pages ingested as content** (Public Baptism of Infants, Baptism of Adults, Confirmation, Visitation of the Sick, Forms of Prayer at Sea) — wrong hardcoded URL paths + no content-sanity gate. They pass schema validation. New correction batch.
- Right shape: **wrong model, schema-valid** — full-text services emit `structured_text` (`work_kind: devotional-classic`), but SCHEMA_SPEC §13's deferred `liturgical_service` type describes exactly what these need (ordered elements, rubrics, speaker roles, call/response). The `edition` field is absent from all 5 outputs (1549/1559/1662/1928 are editions of one work-family).
- Duplicate-edition: 1662 exists as both collects and full text from the same source (content overlap, no cross-link); 1662 vs 1928 correctly keyed as distinct editions.
- Corrections implied: (1) fix the 5 URL paths + add an HTTP-status/content gate (generalizable parser hardening); (2) un-collapse service bodies; (3) populate collect scripture_references; (4) add `edition`.
- **TEI recovery (batch 03, 2026-07-06):** the raw BCP HTML family now has committed TEI IRs at
  `ir/bcp/book-of-common-prayer.bcp-{1549,1559,1662,1928-collects}.tei.xml`, with matching census
  files under `ir/census/` and HF clean-text projections/loss receipts under `ir/bcp/hf/`.
  The census gate covers service nodes, collect nodes, collect/source labels, rubrics, and
  speaker/response units. Viewer screenshots for 1549 and 1662 are committed beside the IRs.
- **Remaining JSON position:** the existing `data/` JSON outputs remain legacy lossy projections for this
  family until publication flips to TEI-derived output. Do not build a separate `liturgical_service`
  schema before consuming the TEI IR.

### 10 — Misc single-source · `hymnary_pd` (CSV) + `didache` (wikitext) — **Faithful (both grains); one intentional partial scope** (2026-07-03)
- **hymnary_pd — Faithful.** Raw CSV 34,918 rows / 8 columns -> 34,904 records (14 empty-text rows skipped and logged). All 8 columns mapped; a hymn CSV carries no note/pb/emphasis apparatus, so the apparatus must-preserve list is empty. Two documented normalizations (multi-author years -> null, 2,390 rows; non-integer Year-written -> null, 2,505 of 9,097) lose derived numeric precision only — raw author strings kept. Schema-valid; list `data`; required Hymnary attribution README present (host-verified). Verdict: Faithful.
- **didache — Faithful within a declared partial scope.** Raw wikitext (16 chapters, 100 verse markers, 10 Wikisource editorial refs) -> 4 prayer records by design (`completeness="partial"`, `expected_count=4`, parser fails hard on any other count). Stripped refs/table markup are Wikisource container apparatus, not the prayer text's. `scripture_references` hard-coded `[]` (minor, 4 records). **Duplicate-edition flag:** a full Didache exists at `data/church-fathers/didache.json` via `church_fathers.py` — same document at two scopes, distinct work_ids; curation note.
- Siblings now walked below: `schleitheim_confession`, `logos_schaff_herzog`, and `spurgeon_mtp`. The Logos duplicate-edition question resolves to same-edition witness, not publish-both edition.
- **TEI position: do not IR this family.** Metadata tables and curated excerpts have no nested structure or apparatus for the IR to preserve; the flat JSON is already lossless for what these sources carry.

### 10b — Misc single-source · `schleitheim_confession` · Schleitheim Confession — **Partial loss / contaminated output** (2026-07-06)
- Source: `https://www.anabaptists.org/history/the-schleitheim-confession.html`; config at `sources/doctrinal-documents/schleitheim-confession-1527/config.json` records source hash `sha256:5a7f3b112e2bd074c9eb8626fd58d13086870ebb0be52a3036781ce9077f3750`. Parser: `build/parsers/schleitheim_confession.py`. Output: `data/doctrinal-documents/schleitheim-confession-1527.json`.
- Evidence limit: no cached raw HTML exists under `raw/`; the parser fetches live. Source-shape checks therefore used the committed parser fixture in `tests/test_schleitheim_confession.py`, which mirrors the real green-font article-header structure, plus the committed source config and output JSON for end-to-end counts.
- Counts verified by read-only `py -3 -` probes and direct output inspection: config says 7 articles / 2,545 words; output has 7 units / 2,545 words; fixture has 7 green `<font color="#008000"><b>...` article headers and 10 paragraph separators. Output has article numbers I-VII and no pre-Article-I preamble text, but Article VII also contains post-document site chrome: typed-by note, site navigation, share widgets, Amazon affiliate disclosure, analytics script text, and recommended-reading footer.
- Structure grain: partial. The seven article boundaries survive as seven `unit_type: "article"` records with Roman numerals and titles, but the parser does not stop at the document terminus.
- Apparatus grain: source-shape evidence shows only header styling (`font` + `b`) and paragraph separators; those are structural carriers, not substantive apparatus. The output intentionally normalizes old HTML styling away, but the site-chrome contamination means the final content block is not faithful to the confession text.
- Right shape: dict-shaped `data` (`document_id`, `document_kind`, `units`), schema-aligned for a doctrinal document; envelope fields are present and registry-ready.
- Duplicate-edition: none found in current data.
- Correction implied: parser-local correction batch for `schleitheim_confession.py`: stop extraction after the document terminus / "The Seven Articles..." close, strip post-document site chrome, and cache the raw HTML under `raw/` so future walks can compare against the actual source, not only the synthetic fixture.

### 10c — Misc single-source · `logos_schaff_herzog` · Logos NSHERK limited HTML — **Partial loss; same-edition witness, not a second edition** (2026-07-06)
- Raw: `raw/logos/nsherk/articles/*.html` from the Logos web reader. Config: `sources/reference/logos-schaff-herzog/config.json`. Parser: `build/parsers/logos_schaff_herzog.py`. Output: merged into `data/reference/schaff-herzog-encyclopedia.json`.
- Counts verified by read-only `py -3 -` / BeautifulSoup probe: 44 raw HTML fragments parse to 44 entries; 37 parsed entry ids are present in the combined output. Raw fragments contain 100 paragraphs: 53 body paragraphs, 16 attribution paragraphs, 31 bibliography paragraphs, 64 Bible-reference links, 36 article links, 322 `<em>` tags, 80 popup links, and 54 `<strong>` tags. Matched output carries 74 `definition_blocks`, 81 scripture references, 16 related terms, and 0 `alt_terms`.
- Structure grain: partial. Headword articles parse, and scripture/article links are partly mapped, but the source set is only a limited 44-fragment Logos scrape, not a complete 13-volume source.
- Apparatus grain: partial loss. Bibliography and attribution paragraphs are excluded from `definition_blocks`; `<em>`/popup markup is flattened or removed; the output cannot distinguish bibliography, author attribution, typographic emphasis, popup abbreviations, and ordinary body text.
- Right shape: output entries match the reference-entry schema inside the shared Schaff-Herzog file, but the source is too incomplete to stand as its own published edition.
- Duplicate-edition verdict: **not a distinct edition**. The Logos and CCEL configs plus shared output metadata identify the same 1908-1914 New Schaff-Herzog edition; `sources/schaff-herzog-encyclopedia/witnesses.json` currently records CCEL-vs-IA only. Logos NSHERK should be treated as a same-edition auxiliary witness/extractor, not a publish-both rendering beside the NSH OCR rebuild.
- Correction implied: no immediate parser fix. Curation should dedupe Logos under the Schaff-Herzog witness model; if Logos is kept, a future batch should either preserve bibliography/attribution/emphasis in an IR/witness layer or mark those losses explicitly.

### 10d — Sermon HTML · `spurgeon_mtp` · Metropolitan Tabernacle Pulpit — **Partial loss** (2026-07-06)
- Raw: `raw/spurgeon_sermons/html/*.html` plus 3 supplemental files under `raw/spurgeon_sermons/missing/`. Config: `sources/sermons/spurgeon-mtp/config.json`. Parser: `build/parsers/spurgeon_mtp.py`. Output: chunked JSON under `data/sermons/spurgeon-mtp/`.
- Counts verified by read-only `py -3 -` / BeautifulSoup probe: 3,547 cached sermon HTML files; 36 output chunks; 3,547 output sermon entries. Raw HTML has 3,547 `<article class="sermon">` blocks, 3,547 `<h1>` titles, 3,521 first blockquotes, 13,597 blockquotes total, 178,407 paragraphs, 3,425 scripture reference spans, 3,766 ordered lists, and 3,767 list items. Output has 3,425 entries with `primary_reference`, 3,521 with `primary_reference_text`, 171,459 content blocks, and word counts from 1,530 to 21,650.
- Structure grain: partial. The one-sermon-per-entry collection shape is faithful and counts match the cached HTML set. Primary scripture references and the opening reference blockquote mostly survive. Later body blockquotes survive as content blocks.
- Apparatus grain: broken for ordered lists. The parser walks only direct `<p>` and `<blockquote>` children for `content_blocks`; it ignores direct `<ol>`/`<li>` sermon body structure. A follow-up probe sampled sermons 1-5 and confirmed the first `<li>` text was not found in output content. Typographic apparatus is light in this source (only 2 `<em>` and 10 `<strong>` tags corpus-wide), so the meaningful apparatus failure is the lost numbered sermon outline/list structure and its text.
- Right shape: list-shaped sermon data split into chunk files; envelope fields are registry-ready; `completeness: "partial"` is correct because the source has about 3,000-plus of 3,563 MTP sermons, not every sermon in the original run.
- Duplicate-edition: no duplicate MTP edition found in current data. Other Spurgeon resources (`spurgeon-all-of-grace`, `spurgeon-lectures-to-my-students`, `spurgeons-morning-evening`) are different works.
- Correction implied: new parser-local correction batch for `spurgeon_mtp.py`: include ordered/unordered list blocks in source order, preserving list boundaries or at least the list item text with a provenance note; then regenerate the chunked output with a writer manifest.

### 6 — Internet Archive OCR · `ia_fisher_marrow` · Marrow of Modern Divinity — **Partial loss** (walked 2026-07-03, light)
- Raw: `raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt` (Google Books DjVuTXT, ABBYY). Parser: `build/parsers/ia_fisher_marrow.py`. Output: `data/structured-text/fisher-marrow-of-modern-divinity.json`.
- **Scope:** `ia_abbyy`, `ia_schaff_herzog*`, `local_schaff_tesseract` feed the NSH OCR rebuild (separate subproject), which supersedes the raw-DjVuTXT path for Schaff-Herzog; NSH text enters the TEI IR through its own facsimile-bearing converter. This row covers the non-NSH uses only.
- Structure: Part I faithful (4 chapters -> 34 sections, matching the raw's 4 real chapter headings + 36 Sect. markers); **Part II (Ten Commandments) flattened to one 662-block / 52k-word blob with 0 children** (host-verified) — the raw has no Sect. headings there and the parser accepts the flattening; the commandment divisions are real content, silently lost.
- Text grain: ~1,500 OCR line-end hyphenations never rejoined (`command- ments`); running headers and page-number lines correctly dropped; this DjVuTXT has no form feeds, so no page anchors exist to preserve. Speaker labels (Evan./Nom./Ant./Neo.) preserved as bold prefixes — real apparatus kept. Footnote markers left inline un-segregated (declared in the parser); `scripture_references` empty throughout.
- Right shape: dict-tree `data`, schema-valid, envelope registry-ready.
- Corrections implied (one batch, parser-local): de-hyphenation pass before paragraph assembly; detect Part II commandment divisions.
- Reclassification: `ia_hastings_dictionary` belongs to family #4 by output shape (headword list, same hard-coded-`[]` apparatus class as catholic_encyclopedia) — route its fix to the family-#4 batch.
- **TEI position: ingest uncorrected OCR into the IR now for this family** — NSH-style multi-engine correction is justified only at encyclopedia scale; a single-scan 1828 dialogue gets its two cheap parser fixes, then IR ingestion with residual OCR error recorded on the census as an inherent-limit property. Gate the projection, not the IR ingestion.

### 6b — Internet Archive OCR · `ia_abbyy` / `local_schaff_tesseract` / `ia_schaff_herzog` · NSH OCR family — **Superseded legacy path; OCR sidecar/rendering layer captured** (2026-07-06)
- Raw: `raw/internet-archive/schaff-herzog/` (`*_djvu.txt` + `_abbyy.gz`), `raw/internet-archive/schaff-herzog-haucgoog/`, `raw/internet-archive/schaff-herzog-dli/`, and page manifests under `raw/internet-archive/schaff-herzog-pages/`. Parsers: `build/parsers/ia_schaff_herzog.py`, `build/parsers/ia_abbyy.py`, `build/parsers/local_schaff_tesseract.py`. Outputs: legacy combined `data/reference/schaff-herzog-encyclopedia.json`; OCR renderings under `data/reference/schaff/encyclopedia/1908-1914/*/vol_NN.json`; page sidecars under `raw/internet-archive/schaff-herzog-pages/vol_NN/`.
- Counts verified by read-only `py -3 -` probe over raw, sidecar, and output trees: 9 NSH-main DjVuTXT files, 13 NSH-main ABBYY GZ files, 37 haucgoog ABBYY GZ files, 7 DLI ABBYY GZ files; 30,145 `ia-abbyy` sidecars and 535 `oss-tesseract` sidecars; renderings currently include `ia-abbyy-v1` for 13 volumes, `ia-abbyy-haucgoog-v1` for 12, `ia-abbyy-dli-v1` for 7, and `oss-tesseract-v1` for 1.
- Structure grain: the legacy `ia_schaff_herzog.py` path emits 8,351 combined reference entries and is **not** the future Schaff-Herzog publication path. The NSH pipeline supersedes it: page sidecars preserve OCR text, word geometry, confidence, page identity, and engine provenance; volume renderings carry page text and page-level confidence for downstream WCT/reconciliation.
- Apparatus grain: plain DjVuTXT has no dependable page geometry or apparatus carriers; ABBYY/Tesseract sidecars do carry word boxes and confidence, but not editorial footnote/bibliography semantics. The family prior is split: English prose OCR is often usable/OCR-GOOD after sampling, while Greek/Hebrew apparatus in 19th-century IA scans remains OCR-RAW and should not be treated as faithful text without the richer NSH-style OCR/reconciliation lane.
- Right shape: sidecar/rendering JSON is the right shape for the OCR layer, not the final public reference-entry shape. The legacy combined `data/reference/schaff-herzog-encyclopedia.json` is schema-valid but frozen as a superseded route.
- Duplicate-edition verdict: NSH IA OCR, CCEL ThML, and Logos NSHERK all represent the same 1908-1914 New Schaff-Herzog edition. They are alternate source/witness lanes, not publish-both editions.
- Correction implied: no parser correction inside this walk. Future IA OCR acquisitions with dense Greek/Hebrew apparatus need an OCR-pipeline batch, not a straight DjVuTXT parser pass.

## Open curation question — RESOLVED by the TEI IR model (2026-07-02)

**Two editions of City of God.** Under ADR-0019 both are renderings of the same work (both Dods;
CCEL prints it inside NPNF, SE as a standalone ebook): each gets its own faithful TEI IR
(`ir/augustine/city-of-god.<rendering>.tei.xml`), neither is retired, and the question of a single
canonical text becomes an optional later reconcile across renderings. The cross-rendering signal is
already strong: both IRs project to exactly 666 clean-text records (665 chapters + one preface).

## How this feeds the rest

- **Drives correction priority.** A "broken"/"partial-loss" row is a correction target; the three current batches are the first three. New rows surface new targets (or clear formats as faithful, so no work is spent there).
- **Feeds the fidelity contract** (`docs/FIDELITY_CONTRACT.md`, batch 01): the per-class must-preserve list is checked against what each walk found.
- **Feeds the structure redesign.** Each row records the output *shape* (envelope fields present, `data` list-vs-dict, registry-readiness) — input to the works/authors registry seeding and the verification harness (which must handle dict-shaped `data`, per this map's row 1).
- **Feeds the IR decision.** Formats whose parser cannot meet the contract (silent structural loss the parser can't recover) are the candidates for the IR (fidelity-IR Phase 2/3); faithful formats are not.
