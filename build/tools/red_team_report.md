# Red Team Report — Data Accuracy & Content Integrity
Generated: 2026-04-12
Audit report consumed: `build/tools/data_accuracy_report.md` (generated 2026-04-07 22:35:27)

## Executive Summary
The automated audit did its job on structural integrity; the red-team issues are concentrated elsewhere. I found two publish-blocking content-loss problems in the HelloAO-derived commentary corpus: book introductions present in the raw source are being dropped entirely, and explicit scripture citations visible in commentary text are not being serialized into `cross_references` at all. I also found a second-order assignment issue in the same pipeline: chapter introductions and section front matter are being merged into verse-scoped entries, which makes some `entry_id` values look more precise than the attached text really is.

Outside the commentary pipeline, the corpus held up much better. I sampled 33 source-to-output comparisons total: 25 across the five requested pipeline types, plus 8 additional category-specific checks covering bible text, church fathers, creeds/catechisms, and reference data. I did not find new content-loss blockers in Gutenberg, Standard Ebooks, scraper, bible-text, catechism, doctrinal-document, church-fathers, devotional, sermon, reference, or topical-reference samples.

## Investigation Log
- Read `build/tools/data_accuracy_report.md` first and treated its 8,831 commentary-coverage P2s as expected selective coverage rather than new defects.
- Read these parsers before sampling: `build/parsers/sword_commentary.py`, `build/parsers/helloao_commentary.py`, `build/parsers/gutenberg_catechisms.py`, `build/parsers/gutenberg_theology.py`, `build/parsers/standard_ebooks.py`, `build/parsers/bcp1662.py`, `build/parsers/bcp1928.py`, `build/parsers/church_fathers.py`, `build/parsers/sword_devotional.py`, `build/parsers/bible_dictionaries.py`, `build/parsers/bsb_bible_text.py`, `build/parsers/naves_topical.py`, and `build/validate.py`.
- Built a category census from on-disk JSON outputs. Categories investigated: `commentaries`, `catechisms`, `church-fathers`, `devotionals`, `doctrinal-documents`, `prayers`, `reference`, `sermons`, `structured-text`, `topical-reference`, `bible-text`.
- Source-to-output comparisons performed: 33 total.
- Requested pipeline minimum met: 25 comparisons.
- `SWORD`: 5 samples.
- `HelloAO`: 5 samples.
- `Gutenberg`: 5 samples.
- `Standard Ebooks`: 5 samples.
- `Scraper`: 5 samples.
- Additional category checks: 8 samples across bible-text, church-fathers, Creeds.json-backed catechisms/doctrinal documents, and reference JSONL.
- Content assignment spot-checks: 10 commentary entries across Barnes, Wesley, Adam Clarke, Jamieson-Fausset-Brown, John Gill, and Keil-Delitzsch.
- Cross-reference completeness checks: 12 commentary entries across Barnes, Wesley, Jamieson-Fausset-Brown, John Gill, Keil-Delitzsch, and Matthew Henry.
- Metadata spot-checks: 10 authors.
- Training-knowledge fact-checks: 10 claims.

## Findings by Category
### Commentaries
**Source comparisons performed:** 10 formal raw-to-output comparisons in this category (5 SWORD, 5 HelloAO), plus 10 content-assignment checks and 12 cross-reference completeness checks.

**P1 — Must fix: HelloAO book introductions are dropped from the published commentary files**

Impact:
- Quantified across the raw corpus: 292/292 HelloAO book files with a non-empty `book.introduction` have no matching text anywhere in the corresponding exported JSON.
- Breakdown: Adam Clarke 57 books, Jamieson-Fausset-Brown 66, John Gill 66, Keil-Delitzsch 38, Matthew Henry 65.

Evidence:
- Raw source: `raw/helloao_local/api/c/jamieson-fausset-brown/ROM/1.json`, JSON key `book.introduction`
  > "THE GENUINENESS of the Epistle to the Romans has never been questioned. It has the unbroken testimony of all antiquity..."
- Parsed output: `data/commentaries/jamieson-fausset-brown/romans.json`, entry `jamieson-fausset-brown.Rom.1.1`
  > "INTRODUCTION. (Rom. 1:1-17) Paul--(See on Act 13:9). a servant of Jesus Christ..."
- Raw source: `raw/helloao_local/api/c/adam-clarke/NUM/1.json`, JSON key `book.introduction`
  > "This, which is the fourth book in order of the Pentateuch, has been called Numbers..."
- Parsed output: `data/commentaries/adam-clarke/numbers.json`, entry `adam-clarke.Num.1.1-54`
  > "Introduction to the book, Deu 1:1, Deu 1:2. Moses addresses the people in the fortieth year..."

Assessment:
- This is real missing content, not just alternate segmentation. The raw source exposes both `book.introduction` and `chapter.introduction`; the exported data only serializes chapter-level material.
- The current parser path explains the loss: `build/parsers/helloao_commentary.py:293` begins the chapter-introduction handling path, but there is no equivalent serialization path for `book.introduction`.

Recommended fix:
- Preserve `book.introduction` explicitly. The least risky options are:
- Emit a dedicated preface/introduction record per book.
- Or store it in metadata with a clear field name if the schema cannot yet represent non-verse commentary blocks.

**P1 — Must fix: HelloAO commentary files lose all structured cross references even when the text visibly contains them**

Impact:
- Quantified across HelloAO-derived commentaries: 44,500 entries contain visible scripture-citation patterns in `commentary_text`.
- 44,500/44,500 of those entries have an empty `cross_references` array.

Evidence:
- Raw source: `raw/helloao_local/api/c/john-gill/JHN/1.json`, `chapter.introduction`
  > "...Luke, Luk 1:2, the Apostle Paul, Act 20:32 and the Apostle Peter, Pe2 3:5..."
- Parsed output: `data/commentaries/john-gill/john.json`, entry `john-gill.John.1.1`
  > "John 1:1 ... Luke, Luk 1:2, the Apostle Paul, Act 20:32 and the Apostle Peter, Pe2 3:5..."
  `cross_references`: `[]`
- Raw source: `raw/helloao_local/api/c/keil-delitzsch/GEN/1.json`, `chapter.content[0]`
  > "...(Exo 20:9-11; Exo 31:12-17)... (Psa 8:1-9)..."
- Parsed output: `data/commentaries/keil-delitzsch/genesis.json`, entry `keil-delitzsch.Gen.1.1`
  > "The Creation of the World - Genesis 1:1-2:3 ... (Exo 20:9-11; Exo 31:12-17)... (Psa 8:1-9)..."
  `cross_references`: `[]`
- Parsed output: `data/commentaries/matthew-henry/matthew.json`, entry `matthew-henry-complete.Matt.1.1-17`
  > "...for it was foretold that he should be the son of David, and yet David's Lord. Mic 5:2; Gen 12:3; Gen 22:18; Psa 89:3..."
  `cross_references`: `[]`

Assessment:
- This is structured-content loss, not a cosmetic issue. The citations are in the text, but the machine-readable reference graph is absent from the data.
- The parser currently hardcodes `cross_references` to an empty list at `build/parsers/helloao_commentary.py:234`.

Recommended fix:
- Add a text-scan normalization pass for HelloAO commentary text before `make_entry()`.
- Reuse the existing bible-ref normalization utilities already used elsewhere in the repo rather than inventing a new parser.

**P2 — Review needed: chapter introductions and section front matter are being merged into verse-scoped entries**

Impact:
- 28 first-entry samples across HelloAO-derived commentary files matched intro/front-matter patterns such as `INTRODUCTION`, `Preface to`, `This chapter contains`, or wide-ranging sectional headings.
- In a 10-entry manual content-assignment spot-check, 5 mid-chapter commentary entries were verse-local and 5 first-entry samples were not.

Evidence:
- Raw source: `raw/helloao_local/api/c/jamieson-fausset-brown/ROM/1.json`, `chapter.introduction`
  > "INTRODUCTION. (Rom. 1:1-17) Paul--(See on Act 13:9)..."
- Parsed output: `data/commentaries/jamieson-fausset-brown/romans.json`, entry `jamieson-fausset-brown.Rom.1.1`
  > "INTRODUCTION. (Rom. 1:1-17) Paul--(See on Act 13:9)..."
- Raw source: `raw/helloao_local/api/c/keil-delitzsch/GEN/1.json`, `chapter.content[0]`
  > "The Creation of the World - Genesis 1:1-2:3 ..."
- Parsed output: `data/commentaries/keil-delitzsch/genesis.json`, entry `keil-delitzsch.Gen.1.1`
  > "The Creation of the World - Genesis 1:1-2:3 ..."
- Parsed output: `data/commentaries/john-gill/romans.json`, entry `john-gill.Rom.1.1`
  > "This chapter contains the inscription of the epistle, and salutation, the preface to it..."

Assessment:
- Some of this front matter is genuinely present in the source, so this is not a fidelity bug.
- It is still a content-assignment problem for consumers who treat `entry_id` as verse-local. The exported ids imply verse-scoped commentary; the attached prose is sometimes chapter-level or section-level exposition.
- The current implementation explicitly causes this by prepending `chapter.introduction` to the first section or by synthesizing verse-range entries from introduction text: `build/parsers/helloao_commentary.py:293`.

Recommended fix:
- Represent chapter introductions separately from verse commentary, or flag them explicitly so downstream consumers do not mistake them for strict verse notes.

**P2 — Review needed: SWORD-derived prose loses paragraph boundaries during normalization**

Evidence:
- Raw source: SWORD Barnes Acts 1:5, binary offset `bzv_index=3880`
  > `Verse 5.... <scripRef passage="Mt 3:11, Jn 1:33">... </scripRef> ... <br /><br /> Not many days hence ... <br /><br /> (c) "John truly"...`
- Parsed output: `data/commentaries/barnes/acts.json`, entry `barnes-nt-notes.Acts.1.5`
  > `Verse 5. For John truly baptized ... Mt 3:11, Jn 1:33 ... See Acts 2 . Not many days hence ...`
- Raw source: SWORD Daily Light 01.01 morning, `daily.idx[1]`
  > `<i>Morning</i>:<br /> ... [This] one thing [I do] ... <br /><br /> Father, I will ... <br /><br /> Know ye not that they who run...`
- Parsed output: `data/devotionals/daily-light/daily-light.json`, entry `01-01-morning`
  > `[This] one thing [I do] ... Father, I will ... Know ye not that they who run...`

Assessment:
- I did not find word loss in the sampled entries, but I did find discourse-boundary loss. This matters for readability and for training uses that rely on paragraph structure.
- The relevant normalization points are `build/parsers/sword_commentary.py:573` and `build/parsers/sword_devotional.py:76`.

**Confirmed correct in sampled commentary data**
- Barnes Acts 1:5 and Acts 1:10 matched raw SWORD module text at the word level after markup stripping.
- Wesley Genesis 1:2 matched the raw SWORD module text at the word level.
- SWORD commentaries do populate `cross_references`; they are incomplete in some samples, but they are not universally blank the way HelloAO outputs are.

### Catechisms
**Source comparisons performed:** 4 raw-to-output checks plus training-knowledge checks.

**Confirmed correct**
- `data/catechisms/westminster-shorter-catechism.json`: Q1 matches the Creeds.json source wording and the expected catechetical text.
- `data/catechisms/heidelberg-catechism.json`: Q1 begins with the expected wording and answer opening.
- `data/catechisms/baltimore-catechism-no-1.json` and `baltimore-catechism-no-2.json`: sampled Q1 matched raw Gutenberg text.
- The already-fixed Baltimore No. 3 and 1695 Baptist Catechism issues were not re-flagged.

### Church Fathers
**Source comparisons performed:** 1 raw TOML comparison plus metadata review.

**Confirmed correct**
- Raw source: `raw/Commentaries-Database/Augustine of Hippo/1 Chronicles 11_17.toml`
  > "The observance of Lent becomes not the curbing of old passions but an opportunity for new pleasures..."
- Parsed output: `data/church-fathers/augustine-of-hippo.json`, entry `augustine-of-hippo.1Chr.11.17.sermon-2072`
  > "The observance of Lent becomes not the curbing of old passions but an opportunity for new pleasures..."
- I did not find quote drift in the sampled church-fathers entry.

**Known-but-not-new**
- `source_title` gaps remain a real metadata issue in this category, but they are already being worked in a separate curation track and were not reopened here as new red-team findings.

### Devotionals
**Source comparisons performed:** 1 formal SWORD rawLD comparison plus structural spot-checks.

**Confirmed correct**
- `data/devotionals/daily-light/daily-light.json`: morning/evening split is preserved; no missing half-entry was found in sampled days.
- The main issue here is paragraph flattening, already noted above.

### Doctrinal Documents
**Source comparisons performed:** 3 raw Creeds.json spot-checks.

**Confirmed correct**
- `data/doctrinal-documents/apostles-creed.json` contains the expected clauses: "I believe in God, the Father almighty", "the communion of saints", and "the forgiveness of sins."
- No new doctrinal-document text corruption surfaced in the sampled creeds.

### Prayers
**Source comparisons performed:** 6 raw HTML comparisons across BCP 1662 and BCP 1928.

**Confirmed correct**
- `data/prayers/bcp-1662/collects.json`: Advent 1, Advent 2, and Advent 3 matched the scraped HTML after drop-cap reconstruction and markup stripping.
- `data/prayers/bcp-1928/collects.json`: Advent 1, Advent 2, and Good Friday samples matched the scraped HTML.
- I did not find dropped collects or truncated Good Friday splits in the sampled entries.

### Reference
**Source comparisons performed:** 1 JSONL comparison plus metadata spot-check.

**Confirmed correct**
- Raw source: `raw/bible_dictionaries/eastons.jsonl`
  > `"term": "A", "definitions": ["Alpha, the first letter of the Greek alphabet..."]`
- Parsed output: `data/reference/eastons-bible-dictionary.json`, entry `eastons-bible-dictionary.a`
  > "Alpha, the first letter of the Greek alphabet..."
- No new definition corruption surfaced in the sampled reference entry.

### Sermons
**Source comparisons performed:** 1 Standard Ebooks XHTML comparison inside the broader 5-sample SE set.

**Confirmed correct**
- `data/sermons/george-macdonald-unspoken-sermons.json`, sermon `1-1`, matched `raw/standard_ebooks/george-macdonald_unspoken-sermons/src/epub/text/chapter-1-1.xhtml` on the sampled opening paragraph.

### Structured Text
**Source comparisons performed:** 6 combined Gutenberg + Standard Ebooks structured-text checks inside the broader pipeline sampling.

**Confirmed correct**
- Gutenberg samples matched: Augustine's *Confessions*, Luther's *Large Catechism*.
- Standard Ebooks samples matched: *Orthodoxy*, *Heretics*, *City of God*, *The Imitation of Christ*, and the sampled sermon file above.
- I did not find dropped paragraphs or section-to-section misassignment in the sampled long-form prose outputs.

### Topical Reference
**Source comparisons performed:** parser/raw-format review plus factual spot-check.

**Confirmed correct**
- Nave’s topical data passed the factual spot-check for expected topics like `AARON`.
- I did not find a new content-integrity blocker here, though I did not do line-addressable raw binary quote extraction for the zLD payload.

### Bible Text
**Source comparisons performed:** 3 direct comparisons to raw `BSB.json`.

**Confirmed correct**
- `John.1.1`, `Ps.23.1`, and `Rev.21.1` matched the raw BSB JSON wording after trimming wrapper whitespace.
- No new bible-text content issue surfaced in the sample.

## Cross-cutting Findings
- The highest-risk content problems are not distributed evenly across the corpus; they cluster very heavily in the HelloAO commentary pipeline.
- Metadata spot-checks for 10 authors found birth/death dates and tradition labels broadly plausible.
- `era` is populated in structured-text and sermon files but absent in sampled commentary/reference/topical-reference outputs. That is not a new blocker, but it does mean metadata richness is inconsistent across categories.
- `completeness` labels were mostly defensible in sampled files, except that HelloAO commentaries are materially more incomplete than their current `partial` label suggests because book introductions are missing wholesale.

## Recommended Fix Order
1. **Restore book introductions in HelloAO commentaries**
   - File: `build/parsers/helloao_commentary.py`
   - Why first: this is the clearest case of wholesale missing content, affecting 292 book files.
   - Minimal fix: serialize `book.introduction` into a dedicated preface/introduction record or explicit metadata field.

2. **Populate `cross_references` for HelloAO commentaries**
   - File: `build/parsers/helloao_commentary.py:234`
   - Why second: 44,500 entries visibly contain citations that are currently absent from the structured graph.
   - Minimal fix: add a text-scan normalization pass before `make_entry()`, reusing the repo’s existing reference normalizers.

3. **Separate verse commentary from chapter/section front matter**
   - File: `build/parsers/helloao_commentary.py:293`
   - Why third: this is currently making `entry_id` precision look better than the text assignment really is.
   - Minimal fix: emit chapter-introduction records separately, or tag first-entry records as non-verse-local front matter.

4. **Preserve paragraph boundaries where the schema allows it**
   - Files: `build/parsers/sword_commentary.py:573`, `build/parsers/sword_devotional.py:76`
   - Why fourth: sampled text was faithful at the word level, but paragraph structure is being flattened.
   - Minimal fix: preserve double-breaks as `\n\n` in prose strings, or use multiple blocks where the schema already supports it.
