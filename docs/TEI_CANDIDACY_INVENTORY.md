# TEI candidacy inventory

This inventory is the decision surface for batches 04-08 of the dataset corrections and TEI
long-tail campaign. The machine-readable source is
`docs/tei-candidacy-inventory.json`; `build/tools/build_tei_candidacy_inventory.py` checks it against
the live parser, source-config, dataset-output, and IR trees.

**Campaign integration (2026-07-16):** the proof sets below exist, but no public path was cut over.
A projection-ledger PASS is necessary but not sufficient until the BCP-1549 false-accounting defect
is fixed; see `docs/DATASET_SUCCESSOR_QUEUE.md`.

The unit counted here is a production source family or a deliberately separated work grouping, not
an individual config or JSON file. A family can be `proven-partial`: named proof renderings have
passed the TEI path, but that never asserts that every work in the family is migrated. The New
Schaff-Herzog OCR rebuild and its rendering files are outside this dataset inventory and belong to
the sibling EzraOCR repository.

## Classification summary

| Classification | Families/groupings |
|---|---:|
| `tei-now` | 5 |
| `tei-later` | 4 |
| `json-native` | 4 |
| `correction-only` | 2 |
| `do-not-migrate` | 7 |
| `unknown` | 1 |
| **Total** | **23** |

Live coverage at integration: **53 production parsers, 304 in-scope source configs, 1,814 dataset
envelopes, and 30 TEI/census artifacts**. The repeatable check reports zero unclassified items.
`build/parsers/_framework.py` and `build/parsers/ia_schaff_herzog_census.py` are explicitly excluded
as non-producing helpers. `sources/local-ocr/schaff/config.json` and the NSH rendering subtree under
`data/reference/schaff/encyclopedia/1908-1914/` are excluded by the repository split.

## Decision rules

- `tei-now`: live source evidence shows meaningful structure or apparatus that JSON cannot carry,
  or the format map explicitly directs immediate IR ingestion.
- `tei-later`: TEI would recover real fidelity, but the yield is lower or a source census must
  precede migration.
- `json-native`: the upstream is already flat/structured at the same grain as the JSON projection;
  TEI would only re-encode it.
- `correction-only`: a parser/audit gap exists, but the live source does not justify an IR.
- `do-not-migrate`: the source is a downstream projection, metadata/excerpt source, incomplete
  auxiliary witness, or superseded route.
- `unknown`: reserved for genuinely missing live evidence, with the missing artifact named.

## TEI-now and proven/partial families

| Entry | Status | Priority | Batch | Decision and live evidence |
|---|---|---:|---:|---|
| `ccel-thml` | `tei-now`; proven/partial | 1 | 04 | Five selected proof renderings exist: City of God, Athanasius, Owen, and two Gregory of Nyssa works. The remaining ThML configs still lose notes, page breaks, emphasis, language spans, and other apparatus in JSON. See `docs/FORMAT_STATE_MAP.md` §1, `build/tei/ccel_work_configs.json`, and `ir/ccel/`. |
| `standard-ebooks-xhtml` | `tei-now`; proven/partial | 2 | 05 | City of God, Bunyan, and Kempis now prove recovery of nested sections, endnotes, bridgeheads, verse/song/poem blocks, lists, front/back matter, and inline semantics. The other six XHTML configs remain deferred pending higher-yield scope decisions. See `docs/FORMAT_STATE_MAP.md` §2, `build/tei/se_to_tei.py`, and `ir/census/`. |
| `ia-fisher-marrow` | `tei-now` | 3 | 06 | Raw census and TEI now agree on 2 parts, 4 chapters, 8 commandments, 41 structural sections, 6 synopsis lines, and 455 high-confidence dialogue labels. The uncorrected OCR limit is recorded and the projection is ledger-gated. See `docs/IA_BATCH06_EVIDENCE.md`, `build/tei/ia_fisher_marrow_to_tei.py`, `ir/fisher/`, and `ir/census/fisher-marrow-of-modern-divinity.ia-ocr.census.json`. |
| `spurgeon-mtp-html` | `tei-now` | 4 | 08 | **Status: proof works, 3 of 3,547.** The bounded raw-HTML proof preserves ordered-list containers, items, and one nested list; the family-wide JSON projection still flattens list semantics. See `docs/BATCH08_EVIDENCE.md`, `docs/FORMAT_STATE_MAP.md` §10d, and `raw/spurgeon_sermons/html/`. |
| `bcp-liturgy` | `tei-now`; proven/partial | 0 | 08 | Current 1549/1559/1662 services and 1928 collects have census-gated TEI, but publication cutover is blocked by projection accounting, speaker-role, nesting, and metadata defects. Keep the family status proven/partial. See `docs/FORMAT_STATE_MAP.md` §9, `docs/DATASET_SUCCESSOR_QUEUE.md`, and `ir/bcp/`. |

Named proof renderings and sets are exactly: five CCEL renderings (City of God, Athanasius *On the
Incarnation*, Owen *Mortification*, and two Gregory of Nyssa works); three Standard Ebooks
renderings (City of God, *The Pilgrim's Progress*, and *The Imitation of Christ*); Calvin's
two-volume Gutenberg *Institutes* rendering; the bounded Fisher *Marrow* IA OCR witness; Spurgeon
MTP sermons 1, 15, and 317 in one proof artifact; and BCP 1549, 1559, 1662, and 1928 collects. Their
census files are under `ir/census/`. None of these statements makes its source family TEI-backed.

## Batch 05 candidate decisions

The raw-source census accepted three bounded works:

| Family | Decision | Raw carrier evidence | Artifacts |
|---|---|---|---|
| Standard Ebooks — *The Pilgrim's Progress* | accepted | 10 content sections; 1,010 endnote references/bodies; 15 semantic `<em>` runs; 21 typographic `<i>` runs; 1,075 bold runs; 1 list with 16 items; 56 body verse/song/poem blocks plus 39 note-body verse blocks; 6 front and 2 back sections | `ir/bunyan/`, `ir/census/pilgrims-progress.standard-ebooks.census.json` |
| Standard Ebooks — *The Imitation of Christ* | accepted | 130 content sections; 183 endnote references/bodies; 5 semantic `<em>` runs; 22 typographic `<i>` runs; 6 bold runs; 1 list with 4 items; 3 body verse blocks; 5 front and 2 back sections; bare `bridgehead` and `hgroup` carriers | `ir/kempis/`, `ir/census/imitation-of-christ.standard-ebooks.census.json` |
| Project Gutenberg — Calvin, *Institutes of the Christian Religion* | accepted | `pg45001` + `pg64392`; 4 logical books and 80 chapters; 539 direct raw underscore-emphasis pairs (573 normalized TEI carriers); Vol. I has 2,016 sequential `(N)` refs resolving to 2,016 note bodies; Vol. II has 1,489 refs resolving to 1,490 note bodies (one unreferenced); two front-matter blocks; Vol. II index excluded at the work boundary | `ir/calvin/`, `ir/census/calvins-institutes.gutenberg.census.json` |

The remaining Standard Ebooks works are deferred: Practical Mysticism (9 verse, 32 `<em>`, 11
`<i>`, 12 blockquotes), Heretics (8 verse, 6 `<em>`, 59 `<i>`, 9 blockquotes), Orthodoxy (6
verse, 70 `<em>`, 19 `<i>`, 6 blockquotes), The Everlasting Man (2 verse, 47 `<em>`, 35 `<i>`, 2
blockquotes), George MacDonald's *Unspoken Sermons* (6 notes, 18 verse, 501 `<em>`, 32 `<i>`, 58
blockquotes), and *Paradise Lost* (1 verse, 11 `<br>` line-break carriers, 3 `<i>`). They need
separate scope decisions or broader sermon/poetry handling before another bounded wave.

Gutenberg *Confessions* (`pg3296`) is rejected for this wave because its raw text has no
underscore emphasis or numeric note anchors. Luther's Large Catechism (`pg1722`) is also rejected
as low-yield (one underscore pair and no numeric anchors). Other Gutenberg witnesses with richer
markers remain deferred until their note/heading boundaries are censused; there is no bulk clean-text
TEI migration.

## TEI-later families

| Entry | Priority | Batch | Decision and live evidence |
|---|---:|---:|---|
| `gutenberg-clean-text` | 5 | 05 | JSON structure is generally sound after the inline decoder fix. Calvin's two-volume Gutenberg rendering now proves a bounded TEI path for true `_italic_` emphasis, front matter, work-boundary exclusions, and two honest per-volume apparatus shapes: Vol. I's 2,016 sequential refs resolve to its 2,016 notes; Vol. II's 1,489 refs resolve to 1,490 notes, leaving one body unreferenced. Apparatus-free or low-yield witnesses remain rejected/deferred. `docs/FORMAT_STATE_MAP.md` §5 explicitly ranks this below CCEL/SE. |
| `ia-ocr-general` | 7 | 06 | Batch 06 remains evidence-only: 10 general text/PDF parser routes are heterogeneous, so no family-wide raw structure count is valid. Preserve the MANIFEST's OCR-GOOD/OCR-RAW distinction and census each work before ingestion. Evidence: `docs/IA_BATCH06_EVIDENCE.md`, `docs/FORMAT_STATE_MAP.md` §6, `research/MANIFEST.md`, and the live parsers. |
| `ia-hastings-dictionary` | 8 | 06 | Batch 06 remains evidence-only: the source config has 5 raw volume files; the downstream output carries 835 See/See-also links across 479 of 2,512 entries, while OCR Bible-reference extraction remains absent. Census headwords before choosing TEI carriers. Evidence: `docs/IA_BATCH06_EVIDENCE.md`, `docs/FORMAT_STATE_MAP.md` §4, and `build/parsers/ia_hastings_dictionary.py`. |
| `catholic-encyclopedia-html` | 10 | 08 | Scripture and explicit related links now survive JSON. A later HTML census may justify inline/link carriers, but it does not outrank the proven rich-text families. Evidence: `docs/FORMAT_STATE_MAP.md` §4 and `build/parsers/catholic_encyclopedia.py`. |

## JSON-native families

| Entry | Why JSON is native | Evidence |
|---|---|---|
| `versified-bible-json` | The raw and output are both flat OSIS/verse/text records; the format map explicitly says TEI would recover zero fidelity. | `docs/FORMAT_STATE_MAP.md` §8; `raw/bible_databases/formats/json/KJV.json`; `build/parsers/bible_text_translations.py` |
| `creeds-json` | Upstream JSON already declares catechism Q&A or confession units; prior defects were metadata corrections. | `docs/FORMAT_STATE_MAP.md` §3; `raw/Creeds.json/creeds`; `build/parsers/creeds_json_catechism.py` |
| `helloao-commentary-json` | The API is already verse-keyed structured JSON at the same grain as commentary records. | `build/parsers/helloao_commentary.py`; `raw/helloao_local/` |
| `church-fathers-toml` | Each TOML block is already a flat quotation with Bible reference and attribution. | `build/parsers/church_fathers.py`; `raw/Commentaries-Database/` |

## Unknown - evidence missing

| Entry | Missing evidence | Next action |
|---|---|---|
| `westminster-html` | Five canonical pages are now hash-pinned and exactly reproduce their current parser outputs; Directory for Publick Worship remains unpinned after repeated 403 responses and failed alternative-witness checks. No complete six-page inline/structural census exists. | Keep `unknown`; acquire an edition-matched Directory for Publick Worship witness, then census all six pages before classifying. See `docs/BATCH08_EVIDENCE.md`. |

## Correction-only and do-not-migrate families

| Entry | Classification | Batch | Rationale and evidence |
|---|---|---:|---|
| `bible-dictionaries-jsonl` | `correction-only` | 08 | Raw JSONL is already headword plus definition. The parser hard-codes empty `alt_terms`, `scripture_references`, and `related_terms`; this is a correction audit, not TEI evidence. `docs/BATCH08_EVIDENCE.md`; `build/parsers/bible_dictionaries.py`; `raw/bible_dictionaries/eastons.jsonl`. |
| `schleitheim-confession` | `correction-only` | 08 | The parser preserves all seven article boundaries and the Article VII closing imprint; remaining HTML is presentation/container markup. `docs/BATCH08_EVIDENCE.md`; `docs/FORMAT_STATE_MAP.md` §10b; cached raw manifest. |
| `sword-commentary` | `do-not-migrate` | 07 | Confirmed downstream zCom projection. Calvin's CCEL component XML is acquired on disk and belongs to the CCEL queue; Barnes and Wesley upstream routes are identified but not acquired. `docs/SWORD_BATCH07_EVIDENCE.md`; `docs/FORMAT_STATE_MAP.md` §7. |
| `sword-devotional` | `do-not-migrate` | 07 | Confirmed rawLD projection. The Daily Light `.conf` names only a site-level `TextSource`; no edition-matched upstream artifact is acquired. `docs/SWORD_BATCH07_EVIDENCE.md`; `docs/FORMAT_STATE_MAP.md` §7. |
| `sword-naves-topical` | `do-not-migrate` | 07 | Confirmed zLD projection. The `.conf` names CCEL's Nave XML route, but that upstream is not acquired; the future IR start point is the named CCEL XML, not the binary. `docs/SWORD_BATCH07_EVIDENCE.md`; `build/parsers/naves_topical.py`. |
| `ia-schaff-herzog-legacy` | `do-not-migrate` | 06 | The combined dataset JSON has 8,351 reference entries but is a frozen superseded route. NSH rendering artifacts are excluded from this repository and batch. `docs/IA_BATCH06_EVIDENCE.md`; `docs/FORMAT_STATE_MAP.md` §6b. |
| `logos-schaff-herzog` | `do-not-migrate` | 08 | The 44 fragments are an incomplete auxiliary witness of the same edition, not a separate rendering. `docs/FORMAT_STATE_MAP.md` §10c. |
| `hymnary-csv` | `do-not-migrate` | 08 | A metadata table has no nested textual apparatus; JSON is lossless for all source columns. `docs/FORMAT_STATE_MAP.md` §10. |
| `didache-prayer-excerpts` | `do-not-migrate` | 08 | Intentional four-prayer scope; stripped Wikisource references are container apparatus. `docs/FORMAT_STATE_MAP.md` §10. |

## Post-campaign TEI queue

This is the remaining migration queue, separate from the blocking fidelity defects in
`docs/DATASET_SUCCESSOR_QUEUE.md`:

1. **CCEL ThML** — extend the five-rendering config-driven proof where apparatus loss is largest;
   the family remains work-by-work.
2. **Remaining Standard Ebooks XHTML** — six renderings remain after City of God, Bunyan, and
   Kempis; each needs an explicit scope decision and gates.
3. **Gutenberg clean text** — migrate only marked-up, high-yield works after a per-work census;
   Calvin is the bounded proof, not a family migration.
4. **General IA OCR** — census and triage per work; never promote OCR-quality claims by family.
5. **Hastings IA dictionary** — decide headword/reference carriers after a focused census.
6. **Catholic Encyclopedia HTML** — later census for link/inline apparatus after higher-yield work.
7. **Spurgeon MTP HTML** — expand beyond proof sermons 1, 15, and 317 only with family-scale gates.

BCP publication is not a migration-queue item: its proof IR exists, but cutover is blocked by the
P1/P2 successor defects. Westminster HTML remains `unknown`, not a TEI candidate, until a witness is
acquired.

## Per-batch queues and handoffs

### Batch 04 — CCEL

Consume entry `ccel-thml` and the **TEI-now and proven/partial families** table. Start from
`build/tei/ccel_work_configs.json`; treat City of God, Athanasius, and Owen as proof works only.
Prioritize remaining work configs by live feature census. Calvin Commentaries must use the acquired
CCEL component XML, not the SWORD projection.

### Batch 05 — Standard Ebooks and Gutenberg

Consume entries `standard-ebooks-xhtml` and `gutenberg-clean-text`, plus the relevant items in
**Post-campaign TEI queue**. Extend the proven SE converter only after separately scoping the six
remaining configs.
For Gutenberg, select marked-up works first and preserve true emphasis/note/front carriers; do not
bulk-migrate apparatus-free clean text merely for format uniformity.

### Batch 06 — Internet Archive OCR

Consume entries `ia-fisher-marrow`, `ia-ocr-general`, `ia-hastings-dictionary`, and
`ia-schaff-herzog-legacy`, plus queue items 3, 6, and 7. Fisher is the only completed
raw-to-TEI migration: its census, TEI, projection, and ledger are recorded in
`docs/IA_BATCH06_EVIDENCE.md`. The other three entries remain evidence-only or
frozen. For all other IA works, retain the MANIFEST OCR-GOOD/OCR-RAW split and require a
work census. Do not touch NSH artifacts or migrate the frozen Schaff-Herzog legacy route.

### Batch 07 — SWORD upstream decisions

Consume entries `sword-commentary`, `sword-devotional`, and `sword-naves-topical`. All three SWORD
binary families are `do-not-migrate` as raw IR sources. Record upstream OSIS/ThML acquisition or a
named missing upstream source per resource. Route acquired Calvin CCEL XML to entry `ccel-thml`.

### Batch 08 — residual reference, hymn, sermon, and misc

Consume entries `bcp-liturgy`, `spurgeon-mtp-html`, `catholic-encyclopedia-html`,
`bible-dictionaries-jsonl`, `versified-bible-json`, `creeds-json`, `westminster-html`,
`helloao-commentary-json`, `church-fathers-toml`, `hymnary-csv`, `didache-prayer-excerpts`,
`schleitheim-confession`, and `logos-schaff-herzog`. The only residual immediate migration is
Spurgeon MTP. Preserve the JSON-native/do-not-migrate decisions and route dictionary field gaps as
corrections. For Westminster, cache a source-hash-matching raw HTML witness and census its
inline/structural apparatus before classification. Treat BCP as proven/partial with publication
cutover blocked by `docs/DATASET_SUCCESSOR_QUEUE.md`, not as a new migration.

## Repeatable verification

Run:

```powershell
py -3 build/tools/build_tei_candidacy_inventory.py
py -3 -m pytest -p no:cacheprovider tests/test_tei_candidacy_inventory.py -v
py -3 -m py_compile build/tools/build_tei_candidacy_inventory.py tests/test_tei_candidacy_inventory.py
```

The checker fails on an unclassified top-level production parser, unmatched source config, dataset
envelope without an owning inventory entry, or TEI/census artifact without a proven/partial family.
