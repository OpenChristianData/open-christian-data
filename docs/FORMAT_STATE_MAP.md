# Format state map — end-to-end fidelity orientation

**Status:** Living orientation doc (seeded 2026-06-18; rows filled as each format is walked)
**Purpose:** Before correcting the corpus, know where *every* source format actually stands. One row per format family → its parsers → an end-to-end walk (raw → parser → output) → a fidelity status. This is the orientation that makes correction comprehensive and prioritized instead of bug-by-bug.

## Why this exists

The fidelity-execution plan (`plans/_archive/2026-06-18-fidelity-execution/`) fixes three *confirmed* bugs (City of God, Catholic Encyclopedia, Creeds). Those were found by chance, not by a systematic sweep. This map walks every format family end-to-end so the real state is known — what is faithful, what loses structure silently, what is the wrong shape for the target model. It feeds both halves of the pipeline: the fidelity corrections and the structure redesign (registry-readiness per format).

Method per row is in `plans/_archive/2026-06-18-fidelity-execution/07-format-state-walk.md`.

## Format families (grounded in the parser + config inventory, 2026-06-18)

The current dataset repository has **53 production parsers** clustered into these families, plus two
excluded non-producing helpers (`_framework.py` and `ia_schaff_herzog_census.py`). This was
recomputed on 2026-07-16 from 55 `build/parsers/*.py` files; the OCR-lane `ia_abbyy` and
`local_schaff_tesseract` parsers now live in EzraOCR. "Status" is the end-to-end walk result; "—" =
not yet walked.

| # | Format family | Source format | Parsers (count) | Walked sample | Status |
|---|---|---|---|---|---|
| 1 | **CCEL ThML** | ThML XML (~209 configs) | 17 `ccel_*` production parsers | City of God; Athanasius; Owen; two Gregory of Nyssa works | **Recovered in TEI IR for five proof renderings** — full-family migration remains |
| 2 | **Standard Ebooks** | XHTML (9) | `standard_ebooks` | City of God, *The Pilgrim's Progress*, *The Imitation of Christ* | **Broken in JSON; three bounded renderings recovered in TEI IR** — batch 05 extends the raw→TEI path; six remaining works are deferred |
| 3 | **Pre-structured JSON** | JSON | `creeds_json_catechism`, `creeds_json_confession`, `helloao_commentary`, `bible_text_translations` | `creeds_json_*` → Heidelberg | **Fixed** (batch 03, `f9e40d51`) — was: wrong `original_language`, dropped metadata |
| 4 | **Headword reference** | ThML/OCR/JSON | `catholic_encyclopedia`, `bible_dictionaries`, `ia_hastings_dictionary`, `naves_topical` | `catholic_encyclopedia` → vol01; Hastings IA | **Fixed for Catholic Encyclopedia + Hastings See apparatus** — bible_dictionaries/naves still need their own walks/fixes |
| 5 | **Gutenberg plain text** | plain text (~16) | `gutenberg_*` (anglican, catechisms, commentary, evangelical, maclaren, puritan, sermons, systematics, theology) | `gutenberg_theology` + `gutenberg_systematics` + `gutenberg_commentary`; Calvin Gutenberg volumes | **Fixed for JSON projection; Calvin recovered in bounded TEI IR** — inline emphasis markers and bare numeric `[N]` anchors remain recoverable; TEI preserves Calvin's true `<hi>`, note anchors/bodies, front matter, and work boundary |
| 6 | **Internet Archive OCR** | DjVuTXT / OCR txt | `ia_fisher_marrow`, `ia_hastings_dictionary`, `ia_schaff_herzog`, plus general text parsers with IA routes | `ia_fisher_marrow`; dataset-side IA evidence | **Mixed** — Fisher has a bounded raw-to-TEI proof; general IA OCR remains work-by-work. NSH OCR-lane parsers and sidecar/rendering work live in EzraOCR |
| 7 | **SWORD modules** | zCom / rawLD | `sword_commentary`, `sword_devotional` | Barnes/Calvin/Wesley + Daily Light | **Structure-faithful; SWORD projection limits remain** — Daily Light `scripRef`s now survive; Calvin still loses note/language/emphasis/table boundaries, so upstream OSIS/ThML is needed for any IR |
| 8 | **Versified Bible** | JSON / DB | `bsb_bible_text`, `bible_text_translations` | BSB + KJV + 7 PD translations | **Faithful** — apparatus upstream-absent (not parser-dropped); BSB, KJV, ASV, YLT, Darby, Webster, KJVA, JPS, and DRC are built from scrollmapper-shaped JSON |
| 9 | **Anglican liturgy** | HTML / text | `bcp1662`, `bcp1928`, `bcp_full_text` | bcp1662/1928 collects + full-text | **Proof IR exists; cutover blocked** — 1549/1559/1662 services plus 1928 collects have census-gated TEI, but the clean-text projection loses label text and speaker roles, 1662 collect nesting is wrong, and source translator metadata is contaminated; JSON remains on the legacy public path |
| 10 | **Misc single-source** | CSV / wikitext / Logos / web HTML | `hymnary_pd`, `didache`, `schleitheim_confession`, `logos_schaff_herzog`, `spurgeon_mtp` | hymnary_pd + didache + schleitheim + logos + spurgeon | **Mixed** — hymnary/didache faithful for their scope; Schleitheim output preserves seven article boundaries and the closing imprint; Logos NSHERK is a limited same-edition witness, not a second edition; Spurgeon has a bounded TEI proof wave, while the family remains only partially represented in JSON |

**Key orientation finding so far:** fidelity varies by *parser*, not just by format. Within one work (City of God) the CCEL edition is faithful and the Standard Ebooks edition is broken. The walk must be per-parser, and the same work can exist at two fidelity levels (a curation question, below).

**Projection-ledger caveat (2026-07-16):** a ledger PASS is necessary but not sufficient. The
BCP-1549 receipt passes while 287 of 332 `<label>` texts are absent from projected output because
`check_ledger` does not require text evidence for every projected node. Ledger PASS statements below
must be read together with each batch's independent census, carrier probes, visual smokes, and
semantic spot-checks. No TEI projection was cut over or published in this campaign.

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

### 1b — CCEL ThML config-driven proof works — **Recovered in TEI IR; not full-family migration** (2026-07-15)
- Proof outputs: `ir/ccel/athanasius-on-the-incarnation.ccel-npnf204.tei.xml` and
  `ir/ccel/owen-mortification.ccel-owen-mort.tei.xml`, plus the Batch 04 NPNF2 wave outputs
  `ir/ccel/gregory-of-nyssa-against-eunomius.ccel-npnf205.tei.xml` and
  `ir/ccel/gregory-of-nyssa-on-the-soul-and-resurrection.ccel-npnf205.tei.xml`, with census files
  under `ir/census/` and HF projection loss ledgers under `ir/ccel/hf/`.
- Converter scope is selected by `build/tei/ccel_work_configs.json`, not hard-coded to City of God.
  The selected proof works cover NPNF2 book/letter divisions, an NPNF2 dialogue with an argument
  division, and an Owen work shape, including divisions, paragraphs, notes, page breaks, scripture
  refs, italics, language spans, headings, names, citations, arguments, and tables where the source
  carries them.
- Batch 10 revalidated the proof works and reran their ledger checks; all returned PASS, subject to
  the global ledger caveat above. Earlier viewer evidence remains on disk.
  This proves the method, not the whole family: the remaining CCEL configs still need per-work
  config, census, validation, projection, and ledger before public cutover.

### 2 — Standard Ebooks · `standard_ebooks` · City of God — **Broken in JSON; recovered in TEI IR** (2026-07-02)
- Raw: Standard Ebooks XHTML (Dods translation). Output: `data/structured-text/city-of-god.json`.
- Structure: 3 top sections, 0 chapter titles, for a 22-book work. Same-file nested `<section>` chapters flattened into book-level blobs.
- **Recovered via the TEI pilot (2026-07-02):** `ir/augustine/city-of-god.standard-ebooks.tei.xml`
  carries the full nested structure (22 books; book 1 = preface + 36 chapters, heads + arguments)
  plus all 1,691 endnotes inlined — census-gated. Batch 02's standalone parser patch is superseded
  by the raw→TEI path; the published JSON regenerates as a TEI projection when the dataset flips to
  projected output.

### 2b — Standard Ebooks · Batch 05 accepted renderings — **Recovered in TEI IR; not family-wide migration** (2026-07-15)

- *The Pilgrim's Progress* (`ir/bunyan/pilgrims-progress.standard-ebooks.tei.xml`) preserves 10
  content sections, 1,010 endnote links/bodies, semantic and typographic emphasis, lists, 56 body
  verse/song/poem blocks, and front/back sections. The 39 verse/song/poem blocks inside endnotes
  are also retained in the resolved note bodies.
- *The Imitation of Christ* (`ir/kempis/imitation-of-christ.standard-ebooks.tei.xml`) preserves
  130 content sections, 183 endnote links/bodies, bare `bridgehead` arguments, `hgroup` headings,
  lists, emphasis, verse blocks, and front/back sections.
- The converter now maps the observed long-tail vocabulary: additional section types, bare
  bridgeheads, `hgroup`, `ol`/`ul`/`li`, `strong`, `q`, and `z3998:song`/`z3998:poem`. Practical
  Mysticism, Heretics, Orthodoxy, The Everlasting Man, George MacDonald's *Unspoken Sermons*, and
  *Paradise Lost* remain deferred for lower yield or distinct sermon/poetry handling.

### 3 — Pre-structured JSON · `creeds_json_*` · Heidelberg / confessions — **Partial loss**
- `original_language` hard-coded `"en"` though the source declares it (non-English for ~23 of ~41); `OriginStory` + 4 other metadata fields never read.
- Fixed: batch 03 (`f9e40d51`, 2026-07-02) — language map fails loudly on unmapped values; dropped fields recorded in provenance notes. NB: `original_language` is an **envelope field** the works registry will own (unified plan §2) — the parser fix is interim and seeds the registry later.

### 4 — Headword reference · `catholic_encyclopedia` · vol01 — **Partial loss**
- `scripture_references` / `related_terms` / `alt_terms` hard-coded `[]` for all 317 vol01 entries (3,674 corpus-wide); non-ASCII headword keys drop the leading letter (`Æons` → `ons`).
- Fixed: batch 03 (`f9e40d51`, 2026-07-02) — refs via shared OSIS normalizer (86/317); related_terms = explicit See/See-also apparatus only (141/317; digitizer in-prose links excluded); negative provenance in meta notes; ligature transliteration for headword keys.
- Hastings IA sibling fixed in batch 02 (`22caf402`, 2026-07-06): conservative See/See-also
  extraction now populates 835 related-term links across 479 of 2,512 entries, while
  `scripture_references` remains empty because this batch did not implement OCR Bible-reference
  extraction. The `--all` path now rebuilds in memory before writing so suffix IDs do not inflate
  across reruns.
- Bible-dictionaries JSONL audit fixed 2026-07-16: the full census found only `term` and
  `definitions` in all 11,768 upstream records. Embedded citations now populate
  `scripture_references` for Easton's and Smith's through the shared OSIS normalizer; explicit
  See/See-also assertions populate `related_terms` for all three reference dictionaries; Torrey
  subtopic citations now carry normalized OSIS and explicit `related_topics`. `alt_terms` and
  `alt_topics` remain empty because no alternate-label apparatus exists in the upstream field
  sets. Full counts and the conservative unparseable-citation boundary are recorded in
  `build/parsers/bible_dictionaries_fields.md`.

### 5 — Gutenberg plain text · `gutenberg_theology` · Confessions (+ Calvin 2nd sample) — **Structure-faithful; apparatus partial loss** (2026-07-03)
- Raw: `raw/gutenberg/pg3296.txt` (Augustine, Confessions, Pusey trans.). Parser: `build/parsers/gutenberg_theology.py::parse_augustine`. Output: `data/structured-text/augustines-confessions.json`.
- Structure: raw 13 `BOOK` headings, 0 chapters (Pusey edition omits them — parser notes document this); output 13 books, 462 content_blocks, 111,775 words. Exact match.
- **Apparatus grain (from the Calvin 2nd sample, pg64392 — Confessions is an apparatus-free outlier; only ~4 of 22 raw files carry none):** fixed in batch 01 (2026-07-05): the nine `gutenberg_*` parsers share a plain-text inline decoder. `_italic_` markers are stripped from JSON text fields, and bare numeric `[N]` anchors are preserved recoverably as `[[pg-note-anchor:N]]`. This is a JSON projection fix only: true emphasis structure and note bodies still require a richer upstream/TEI path. Front-matter title/translator block remains dropped but captured in meta. Encoding faithful (true UTF-8, U+201D preserved).
- Right shape: dict-shaped `data` (nested `children`) — harness must handle dict form. Schema-valid. Envelope fields present, `original_language: la` correct.
- Duplicate-edition: none — Confessions unique to this family.
- Correction result: semantic scan across regenerated `gutenberg_*` outputs found 0 bare `[N]` anchors and 0 `_..._` emphasis markers. `gutenberg_systematics` and `gutenberg_commentary` were walked as risky siblings; both validate after the shared decoder. Regeneration surfaced two pre-existing count drifts outside the inline-markup fix: Baltimore Catechism #3 `1400 -> 1398`, Maclaren `1257 -> 1255`.
- TEI candidacy: low-yield for clean works, higher for marked-up ones (IR gains `<hi rend="italic">`, explicit dangling-anchor `<ref>`s, `<front>`); weaker candidate than CCEL/SE.
- Sibling status: all nine `gutenberg_*` parser families now route text projection through the shared decoder; systematics/commentary were the high-risk walk targets for this batch.

### 5b — Gutenberg plain text · Calvin *Institutes* — **Bounded TEI recovery for marked-up volumes** (2026-07-15)

- Raw: `raw/gutenberg/pg45001.txt` and `raw/gutenberg/pg64392.txt`. The selected scope begins after
  each first all-caps `BOOK` heading, preserves four logical books and 80 chapters, and excludes
  Project Gutenberg wrapper text plus the Vol. II index after `END OF THE INSTITUTES.`.
- The raw census records 539 direct underscore-emphasis pairs (the TEI census emits 573 emphasis
  carriers), 3,505 numeric note anchors—2,016 parenthetical refs in Vol. I and 1,489 bracketed refs
  in Vol. II—3,506 note bodies, and two front-matter blocks. The TEI artifact is
  `ir/calvin/calvins-institutes.gutenberg.tei.xml`; the raw census is
  `ir/census/calvins-institutes.gutenberg.census.json`.
- `build/tei/gutenberg_to_tei.py` maps `_italic_` to `<hi rend="italic">`, Vol. I `(N)` and Vol. II
  `[N]` markers to explicit note refs, and both volumes' `FOOTNOTES` blocks to per-volume `<back>`
  note containers. `project_hf.py` produces the clean-text projection; its ledger check passes,
  subject to the global ledger caveat above.
- Confessions (`pg3296`) is an apparatus-free negative for this TEI wave; Luther's Large Catechism
  (`pg1722`) is too low-yield. Other Gutenberg witnesses remain work-by-work candidates, not a
  bulk migration target.

### 7 — SWORD modules · `sword_commentary` + `sword_devotional` + `naves_topical` · Barnes / Calvin / Wesley / Daily Light / Nave — **Structure-faithful only at the projection grain; upstream TEI is required for IR** (updated 2026-07-16)
- Raw: CrossWire SWORD binaries under `raw/sword_modules/` (commentaries zCom, Daily Light rawLD) and `raw/naves_topical/` (Nave zLD). `.conf` `SourceType`: Barnes/Wesley/Daily = ThML, Calvin = OSIS, Nave = TEI. Outputs: `data/commentaries/{barnes,calvin,wesley}/*.json`, `data/devotionals/daily-light/daily-light.json`, and `data/topical-reference/naves/naves-topical-bible.json`.
- Structure counts at the parser's projection grain: Barnes 7,322, Wesley 17,564, and Calvin 13,338 nonempty verse records; Daily Light 366 days -> 732 morning/evening records; Nave 5,322 topics -> 5,322 output entries. Calvin's mapped book names require a coverage audit because the dry-run yields 49 while the module/config metadata describes 47 and excludes Acts.
- **Apparatus grain:** the parsers keep selected cross-references but flatten markup to plain text. Fresh raw scans found Calvin's 22,465 `<note>`, 31,300 `<foreign>`, 196,065 `<hi>`, and 7,045 `<table>` opening tags, plus Barnes's 52,532 `<i>` tags; all three commentary outputs had 0 residual XML/HTML tags. Daily Light's 1,218 `<scripRef>` tags survive as 1,218 cross-reference objects across 732 records, but its 732 `<i>` section labels and 20,313 `<br>` tags are not carried as markup. Nave's raw XML has 15,019 subtopic divisions, 77,935 `<ref osisRef>` tags, and 4,368 related-topic targets; output has 15,019 subtopics, 76,957 refs, and 4,368 related links, with 978 pre-arrow refs dropped by the current parser.
- Right shape: list `data`, schema-valid, envelope registry-clean, `verse_text_source: "none"` correct.
- Duplicate-edition: none (witnesses.json scaffolds empty).
- Correction implied: none against the module for rich commentary apparatus — **the SWORD binary is itself a downstream projection**. Calvin's acquired CCEL component XML belongs to the CCEL queue; Barnes, Wesley, Daily Light, and Nave have no acquired upstream artifact in this batch. Build any future TEI IR from a verified upstream source, not from the SWORD payload.
- Unwalked/successor residue: Calvin's zCom position mapping conflicts with its module/config coverage metadata; Nave's parser drops 978 pre-arrow refs; Daily Light has only a site-level `TextSource` pointer. See `docs/SWORD_BATCH07_EVIDENCE.md`.

### 8 — Versified Bible · `bsb_bible_text` + `bible_text_translations` · BSB + PD translations — **Faithful; apparatus upstream-absent, not parser-dropped** (updated 2026-07-07)
- Raw: `raw/bible_databases/formats/json/{BSB,KJV}.json` -> parsers -> `data/bible-text/{bsb,kjv}/*.json` (66 files each).
- Structure counts, both ends: each raw 66 books / 1,189 chapters / 31,102 verses. BSB out 31,086 (Δ16 = genuinely empty textual-critical verses, enumerated in config notes — dropped-with-provenance). KJV out 31,102 (Δ0).
- **Apparatus grain:** raw verse schema is `{verse, text}` only — censused across all 31,102 verses. Poetry lines, headings, and KJV supplied-word italics are **stripped upstream** (1 bracketed word survives in 31,102 KJV verses); the parser is a faithful passthrough of an already-flat source. One benign silent loss: BSB's latent poetry indent (leading whitespace on 3,261 verses, 10.5%) is `.strip()`ed — the only structural signal the raw carries; ambiguous, defensibly dropped, recorded here.
- Right shape: flat list `data` of `{osis, chapter, verse, text, ...}`; schema-valid; envelope clean; `original_language: "en"` correct here (contrast family #3's bug). `token_count` is injected downstream of the parser.
- Duplicate-edition: each built translation exists once as an edition; commentary `verse_text_source` references are not editions.
- Correction implied: none for the scrollmapper-shaped JSON source family. Poetry/italics need a
  tagged upstream (USFM/OSIS), not a parser patch.
- Acquisition/build update: batch 04 built ASV, YLT, Darby, Webster, KJVA, JPS, and DRC through
  the existing scrollmapper-shaped JSON parser path. DRC emits 73 books because 5 source books have
  zero verse text and are skipped with provenance; KJVA includes apocrypha.
- **TEI position: this family stays JSON-native.** The flat `{osis, verse, text}` list is already the lossless projection of what the raw carries; a TEI IR would re-encode the same information with zero recovered fidelity. If OCD later ingests a tagged Bible source, that source gets an IR; this one does not need it.

### 9 — Anglican liturgy · `bcp1662` / `bcp1928` / `bcp_full_text` · BCP editions — **Proof IR exists; publication cutover blocked** (updated 2026-07-16)
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
  speaker/response units. Viewer screenshots for all four renderings are committed beside the IRs;
  the 1559 and 1928 captures were rendered against distinctive body text and passed the viewer's
  DOM/content assertions.
- **Remaining JSON position:** the existing `data/` JSON outputs remain legacy lossy projections for this
  family until publication flips to TEI-derived output. Do not build a separate `liturgical_service`
  schema before consuming the TEI IR.
- **Successor correction status (2026-07-16):** strict-v2 receipts now verify delivered label text;
  the 124/137/233 BCP `<sp>` units project as ordered speaker-role spans; all 85 BCP-1662 collects
  are body peers; and all 257 current BCP rows use rendering-specific metadata with no unsupported
  translator. The 1559 and 1928 viewer smokes are present. The 1559 grain is fully reconciled in
  `docs/FIDELITY_CONTRACT.md`: 14 legacy sections - 1 legacy-only 1623 PDF notice + 3 current-only
  source-page carriers = the intended 16 TEI services / 16 clean rows, four of which are empty.

### 10 — Misc single-source · `hymnary_pd` (CSV) + `didache` (wikitext) — **Faithful (both grains); one intentional partial scope** (2026-07-03)
- **hymnary_pd — Faithful.** Raw CSV 34,918 rows / 8 columns -> 34,904 records (14 empty-text rows skipped and logged). All 8 columns mapped; a hymn CSV carries no note/pb/emphasis apparatus, so the apparatus must-preserve list is empty. Two documented normalizations (multi-author years -> null, 2,390 rows; non-integer Year-written -> null, 2,505 of 9,097) lose derived numeric precision only — raw author strings kept. Schema-valid; list `data`; required Hymnary attribution README present (host-verified). Verdict: Faithful.
- **didache — Faithful within a declared partial scope.** Raw wikitext (16 chapters, 100 verse markers, 10 Wikisource editorial refs) -> 4 prayer records by design (`completeness="partial"`, `expected_count=4`, parser fails hard on any other count). Stripped refs/table markup are Wikisource container apparatus, not the prayer text's. `scripture_references` hard-coded `[]` (minor, 4 records). **Duplicate-edition flag:** a full Didache exists at `data/church-fathers/didache.json` via `church_fathers.py` — same document at two scopes, distinct work_ids; curation note.
- Siblings now walked below: `schleitheim_confession`, `logos_schaff_herzog`, and `spurgeon_mtp`. The Logos duplicate-edition question resolves to same-edition witness, not publish-both edition.
- **TEI position: do not IR this family.** Metadata tables and curated excerpts have no nested structure or apparatus for the IR to preserve; the flat JSON is already lossless for what these sources carry.

### 10b — Misc single-source · `schleitheim_confession` · Schleitheim Confession — **Faithful JSON projection; correction-only** (2026-07-15)
- Raw: `raw/anabaptists.org/schleitheim-confession-1527.html`; source: `https://www.anabaptists.org/history/the-schleitheim-confession.html`; config at `sources/doctrinal-documents/schleitheim-confession-1527/config.json` records source hash `sha256:5a7f3b112e2bd074c9eb8626fd58d13086870ebb0be52a3036781ce9077f3750`. Parser: `build/parsers/schleitheim_confession.py`. Output: `data/doctrinal-documents/schleitheim-confession-1527.json`.
- Counts verified by cached-witness parser tests and direct output inspection: the raw has seven green `<font color="#008000"><b>...` article headers; output has seven `unit_type: "article"` units numbered I-VII. Article VII retains its real close, “The Seven Articles of Schleitheim / Canton Schaffhausen, Switzerland / February 24, 1527,” and excludes the subsequent typed-by note, site navigation, Share widgets, Amazon disclosure, analytics script text, and recommended-reading footer.
- Structure grain: faithful for this source. The seven article boundaries, Roman numerals, titles, paragraph text, and document terminus survive in the doctrinal-document projection.
- Apparatus grain: the source carries only header styling (`font` + `b`) and paragraph separators as meaningful document structure; these are represented by article records and paragraph breaks. The remaining HTML after the closing imprint is site chrome rather than confession apparatus and is intentionally excluded.
- Right shape: dict-shaped `data` (`document_id`, `document_kind`, `units`), schema-aligned for a doctrinal document; envelope fields are present and registry-ready.
- Duplicate-edition: none found in current data.
- Correction landed: batch 02 caches the raw witness and stops Article VII at the source-content closing imprint, not at a site-chrome selector. No TEI migration is indicated by this source shape.

### 10c — Misc single-source · `logos_schaff_herzog` · Logos NSHERK limited HTML — **Partial loss; same-edition witness, not a second edition** (2026-07-06)
- Raw: `raw/logos/nsherk/articles/*.html` from the Logos web reader. Config: `sources/reference/logos-schaff-herzog/config.json`. Parser: `build/parsers/logos_schaff_herzog.py`. Output: merged into `data/reference/schaff-herzog-encyclopedia.json`.
- Counts verified by read-only `py -3 -` / BeautifulSoup probe: 44 raw HTML fragments parse to 44 entries; 37 parsed entry ids are present in the combined output. Raw fragments contain 100 paragraphs: 53 body paragraphs, 16 attribution paragraphs, 31 bibliography paragraphs, 64 Bible-reference links, 36 article links, 322 `<em>` tags, 80 popup links, and 54 `<strong>` tags. Matched output carries 74 `definition_blocks`, 81 scripture references, 16 related terms, and 0 `alt_terms`.
- Structure grain: partial. Headword articles parse, and scripture/article links are partly mapped, but the source set is only a limited 44-fragment Logos scrape, not a complete 13-volume source.
- Apparatus grain: partial loss. Bibliography and attribution paragraphs are excluded from `definition_blocks`; `<em>`/popup markup is flattened or removed; the output cannot distinguish bibliography, author attribution, typographic emphasis, popup abbreviations, and ordinary body text.
- Right shape: output entries match the reference-entry schema inside the shared Schaff-Herzog file, but the source is too incomplete to stand as its own published edition.
- Duplicate-edition verdict: **not a distinct edition**. The Logos and CCEL configs plus shared output metadata identify the same 1908-1914 New Schaff-Herzog edition; `sources/schaff-herzog-encyclopedia/witnesses.json` currently records CCEL-vs-IA only. Logos NSHERK should be treated as a same-edition auxiliary witness/extractor, not a publish-both rendering beside the NSH OCR rebuild.
- Correction implied: no immediate parser fix. Curation should dedupe Logos under the Schaff-Herzog witness model; if Logos is kept, a future batch should either preserve bibliography/attribution/emphasis in an IR/witness layer or mark those losses explicitly.

### 10d — Sermon HTML · `spurgeon_mtp` · Metropolitan Tabernacle Pulpit — **Bounded TEI proof wave; family-wide list-boundary loss remains** (2026-07-16)
- Raw: `raw/spurgeon_sermons/html/*.html` plus 3 supplemental files under `raw/spurgeon_sermons/missing/`. Config: `sources/sermons/spurgeon-mtp/config.json`. Parser: `build/parsers/spurgeon_mtp.py`. Output: chunked JSON under `data/sermons/spurgeon-mtp/`.
- Counts verified by read-only `py -3 -` / BeautifulSoup probe: 3,547 cached sermon HTML files; 36 output chunks; 3,547 output sermon entries. Raw HTML has 3,547 `<article class="sermon">` blocks, 3,547 `<h1>` titles, 3,521 first blockquotes, 13,597 blockquotes total, 178,407 paragraphs, 3,425 scripture reference spans, 3,766 ordered lists, and 3,767 list items. Output has 3,425 entries with `primary_reference`, 3,521 with `primary_reference_text`, 175,216 content blocks, and word counts from 1,530 to 21,650.
- Structure grain: partial. The one-sermon-per-entry collection shape is faithful and counts match the cached HTML set. Primary scripture references and the opening reference blockquote mostly survive. Later body blockquotes survive as content blocks.
- Apparatus grain: partial for the family, with a bounded TEI proof. The proof converter reads raw HTML directly and selects sermons 1, 15, and 317: the first multi-list case, the first nested-list case, and the first plain control. Its census records 3,766 article `ol`, 0 article `ul`, 3,767 `li`, and 9 nested list elements across the family; the selected TEI preserves 5 ordered lists, 5 items, and 1 nested list. **Status: proof works, 3 of 3,547.** This does not imply family-wide TEI coverage. The JSON parser still walks direct `<ol>` and `<ul>` sermon-body children into string-only `content_blocks`, so container type and ordinal/bullet boundaries remain flattened outside the proof artifact.
- Right shape: list-shaped sermon data split into chunk files; envelope fields are registry-ready; `completeness: "partial"` is correct because the source has about 3,000-plus of 3,563 MTP sermons, not every sermon in the original run.
- Duplicate-edition: no duplicate MTP edition found in current data. Other Spurgeon resources (`spurgeon-all-of-grace`, `spurgeon-lectures-to-my-students`, `spurgeons-morning-evening`) are different works.
- Correction landed: batch 01 preserves direct ordered/unordered list-item text in source order, regenerates the chunked output, and records the unavoidable list-boundary projection loss in provenance. Batch 08 adds the bounded TEI proof artifacts under `ir/spurgeon/` and `ir/census/`; see `docs/BATCH08_EVIDENCE.md`.

### 6 — Internet Archive OCR · `ia_fisher_marrow` · Marrow of Modern Divinity — **Raw OCR now carried in TEI; residual OCR limits remain** (updated 2026-07-16)
- Raw: `raw/internet-archive/fisher-marrow/marrowmoderndiv00bostgoog_djvu.txt` (Google Books DjVuTXT, ABBYY). Parser: `build/parsers/ia_fisher_marrow.py`. Output: `data/structured-text/fisher-marrow-of-modern-divinity.json`.
- **Scope:** `ia_abbyy`, `ia_schaff_herzog*`, `local_schaff_tesseract` feed the NSH OCR rebuild (separate subproject), which supersedes the raw-DjVuTXT path for Schaff-Herzog; NSH text enters the TEI IR through its own facsimile-bearing converter. This row covers the non-NSH uses only.
- Structure: the legacy JSON parser projects 4 chapters and 34 sections, but a fresh raw census finds 47 `Sect`-prefixed lines: 41 structural boundaries and 6 synopsis lines. The bounded raw-to-TEI converter carries 2 parts, 4 chapters, 41 section divs, and all 8 standalone Part II commandment headings (`I`, `IF`, `HI`, `IV-`, `VI`, `VHI`, `IX`, `X`) exactly as observed. Commands III and V are not fabricated because no standalone recoverable headings exist.
- Text grain: the TEI converter preserves the raw line text and OCR errors; it does not apply the legacy parser's de-hyphenation or speaker normalization. The raw scope has 0 Greek/Hebrew code points, no table carrier, no form-feed page breaks, 2,039 asterisks, and 44 section marks. Running headers and page-number lines are excluded as OCR wrapper noise, while inline markers remain inline because note boundaries are not recoverable.
- Dialogue grain: the raw classifier promotes 455 high-confidence OCR speaker starts to 455 `<sp>`/`<speaker>` pairs. It leaves 123 ambiguous speaker-like starts as prose. Exact OCR labels and punctuation remain visible; no damaged label is silently repaired.
- TEI artifacts: `build/tei/ia_fisher_marrow_to_tei.py`, `ir/census/fisher-marrow-of-modern-divinity.ia-ocr.census.json`, and `ir/fisher/fisher-marrow-of-modern-divinity.ia-ocr.tei.xml`. The TEI validates against the vendored RelaxNG schema. Projection: `ir/fisher/hf/fisher-marrow-of-modern-divinity.ia-ocr.jsonl` plus its loss receipt; the independent ledger check passes.
- Right shape: TEI is now the fidelity-preserving intermediate representation for this bounded raw witness; the existing dict-tree JSON remains a legacy downstream projection until publication cutover.
- Corrections landed: the earlier cheap parser fixes remain in the JSON route, while this batch adds raw census, uncorrected TEI ingestion, explicit OCR-quality evidence, speaker carriers, and projection gating. Further OCR correction belongs to a separate OCR/IR decision, not this converter.
- Reclassification: `ia_hastings_dictionary` belongs to family #4 by output shape (headword list, same hard-coded-`[]` apparatus class as catholic_encyclopedia). Its See/See-also apparatus fix landed in batch 02; Bible-reference extraction is still unimplemented.
- **TEI position: ingest uncorrected OCR into the IR now for this family** — NSH-style multi-engine correction is justified only at encyclopedia scale; a single-scan 1828 dialogue gets its two cheap parser fixes, then IR ingestion with residual OCR error recorded on the census as an inherent-limit property. Gate the projection, not the IR ingestion.

### 6b — Internet Archive OCR · `ia_abbyy` / `local_schaff_tesseract` / `ia_schaff_herzog` · NSH OCR family — **Superseded legacy path; OCR sidecar/rendering layer captured** (2026-07-06)
- Raw (2026-07-09: all Schaff-Herzog raw material lives in the EzraOCR repo — SH is in use only by the OCR side at present): `../EzraOCR/raw/internet-archive/schaff-herzog/` (`*_djvu.txt` + `_abbyy.gz`), `-haucgoog/`, `-dli/`, and the page store + manifests (`schaff-herzog-pages/`). Nothing SH remains under local `raw/`. Parsers here: `build/parsers/ia_schaff_herzog.py` (the OCR-lane parsers `ia_abbyy.py` / `local_schaff_tesseract.py` live in EzraOCR `ezra/parsers/`). Outputs: legacy combined `data/reference/schaff-herzog-encyclopedia.json`; OCR renderings under `data/reference/schaff/encyclopedia/1908-1914/*/vol_NN.json`; page sidecars under `../EzraOCR/reports/s1-sidecars/`.
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
- **Feeds the active successor campaign.** The post-batch-08 correction and TEI long-tail work is
  decomposed in `plans/2026-07-07-dataset-corrections-and-tei-long-tail/`; batch 03 turns this map
  into a TEI candidacy inventory before any bulk migration rows run.
