# Open Christian Data — Source Investigation Synthesis

**Date:** 2026-03-27
**Scope:** Full analysis across 8 category investigations + 6 GitHub repo inspections
**Purpose:** What did we learn? What changes? What's next?

---

## 1. What We Learned — The Big Picture

### The landscape is better than expected

Before this investigation, the working assumption was that acquiring structured Christian literature data would require extensive web scraping, OCR pipelines, and months of manual effort. The reality:

- **Four categories can start processing immediately** with data we already have on disk from GitHub clones
- **Two categories require a single email** before proceeding (Hymnary.org, CCEL)
- **Two categories have genuine gaps** but workable alternatives exist
- **No pre-existing datasets exist** on HuggingFace for sermons, hymns, prayers, or patristic commentary — OCD would be genuinely first in every category

### Three sources dominate everything

| Source | Categories It Covers | Access Method | License |
|--------|----------------------|---------------|---------|
| **CCEL** | Commentaries, theological works, reference works, devotionals, prayers, sermons | ThML/XML download | PD text, CCEL formatting copyright — contact needed |
| **CrossWire SWORD** | Commentaries (Barnes, Calvin, Wesley), devotionals (M&E, Daily Light) | ZIP download per module | Public Domain |
| **Project Gutenberg** | Theological works, catechisms, hymns, sermons (Maclaren) | Bulk harvest endpoint | Public Domain |

CCEL is the single most important source. Nearly every investigation recommended CCEL ThML as either primary or secondary. **The single highest-leverage action for the entire project is emailing CCEL for explicit permission.**

---

## 2. Category-by-Category Status

### READY NOW (data on disk, clear licensing)

| Category | Source | Data Available | Next Step |
|----------|--------|---------------|-----------|
| **Confessions & Creeds** | Creeds.json (cloned, 35/43 docs Unlicense) | 35 documents in clean JSON with proof texts | Write ingest script, exclude 8 copyrighted docs |
| **Catechisms** | Creeds.json + Project Gutenberg | WSC (107 Q&A), WLC (196 Q&A), Heidelberg, Keach, Baptist Catechism, Baltimore | Ingest from Creeds.json; PG for Luther |
| **Church Fathers** | Commentaries-Database (cloned, PD) | 58,675 verse-keyed TOML quotes, 335+ authors | Write TOML→JSON parser |
| **Bible Text (BSB)** | bible_databases (cloned, CC0) | BSB.json with all 66 books | Direct ingest |
| **Cross-references (TSK)** | bible_databases (cloned) | 7 SQLite files in extras/ | Query schema, merge, convert to Parquet |
| **Reference works** | JWBickel/BibleDictionaries (HuggingFace) | Easton's (3,960), Smith's (4,560), Hitchcock's (2,620), Torrey's (623) in JSONL | Download JSONL, ingest |
| **Pilgrim's Progress** | Standard Ebooks (CC0, GitHub) | Clean epub with semantic markup | Clone and extract |

### NEEDS ONE EMAIL

| Category | Who to Contact | What to Ask | What It Unlocks |
|----------|---------------|-------------|-----------------|
| **Hymns** | Hymnary.org | Full CSV dump of PD texts + metadata | 1M+ hymn instances, 7,144 hymnals, full metadata |
| **Theological Works + Commentaries + Reference (Nave's)** | CCEL | Permission for ThML/XML use in open-source project | Calvin's Institutes, Hodge (3 vols), Edwards, Owen, Baxter, Athanasius, Nave's (20k topics), Wesley sermons |

### NEEDS DOWNLOADING (settled sources, clear path)

| Category | Source | Method | Estimated Effort |
|----------|--------|--------|-----------------|
| **Commentaries (HelloAO 5)** | HelloAO CLI self-host | Install @helloao/cli, generate static JSON | 1 session |
| **Commentaries (Barnes, Calvin, Wesley)** | CrossWire SWORD ZIPs | Download 3 ZIPs, extract via pysword/diatheke | 1 session |
| **Devotionals (M&E, Daily Light)** | CrossWire SWORD | Download 2 ZIPs, extract via diatheke (WSL) | 1 session |
| **Sermons (Spurgeon ~3,000)** | The Kingdom Collective | Scrape HTML pages with 2s delay | 1 long session |
| **Sermons (Wesley 141)** | CCEL XML | Direct download: ccel.org/ccel/wesley/sermons.xml | 1 request |
| **Sermons (Maclaren 17+ vols)** | Project Gutenberg | Bulk harvest endpoint | 1 session |
| **Sermons (Whitefield)** | CCEL + Project Gutenberg | XML download + PG | 1 session |
| **Prayer (BCP 1662)** | eskimo.com | Download ASCII/RTF version | 1 request |
| **Prayer (BCP 1928)** | justus.anglican.org | Download HTML | 1 request |
| **Prayer (Didache)** | Wikisource API | Single API call | 1 request |
| **Catechisms (Luther Small/Large)** | Project Gutenberg #1670, #1722 | Direct download | 2 requests |
| **Devotional (Imitation of Christ)** | Project Gutenberg #26222 | Direct download | 1 request |
| **Theological (Augustine, Calvin)** | Project Gutenberg | Direct download | Several requests |

### GENUINE GAPS / DEFERRED

| Item | Why It's Hard | Status |
|------|-------------|--------|
| **Matthew Poole's Commentary** | Only exists as 1685 scans or HTML behind ToS walls | Deferred — inspect grace-ebooks.com ZIPs manually |
| **ISBE (5 volumes)** | No structured digital version exists; Internet Archive OCR is the only path | Multi-week OCR project — defer to Phase 3 |
| **Spurgeon remaining ~500 sermons** | Not on The Kingdom Collective; SpurgeonGems PDFs are the only source | Defer pending OCR pipeline |
| **Edwards full sermon corpus (1,200+)** | Yale WJE Online is read-only; no bulk export | Contact Yale Edwards Center for data partnership |
| **M'Cheyne sermons (~200)** | Only 6 in HTML; rest requires OCR from Internet Archive | Low priority — defer |
| **Streams in the Desert (1925)** | Copyright renewal status needs verification | Search US Copyright Office renewal database first |
| **Bengel's Gnomon (5 volumes)** | Internet Archive OCR only; no structured version | Medium priority — spot-check quality first |
| **Lange's Commentary (26 volumes)** | Internet Archive OCR; massive scope | Low priority — spot-check before committing |
| **Puritan prayers (primary sources)** | Buried in collected works; requires extraction | Medium effort — Owen Vol.4, Watson, Doddridge |

---

## 3. What Needs to Change

### DL-1 prompt (HelloAO download) needs rewriting

The investigation found HelloAO's docs explicitly say **"do not use the API to download an entire commentary."** The correct path is:
1. Clone the `HelloAOLab/bible-api` repo (MIT license)
2. Install `@helloao/cli`
3. Self-host to generate static JSON files locally

The DL-1 prompt currently scripts direct API calls with 2-second delays. This needs to be replaced with the CLI self-host approach.

### Schema needs two additions

1. **Luther's Large Catechism is NOT a Q&A document** — it's continuous theological prose. The catechism schema doesn't fit. Add a "prose catechism" or "treatise" schema type.
2. **Heidelberg Catechism has Lord's Day groupings** — the catechism schema needs a `lords_day` field (1-52) in addition to `question_number` (1-129).

### CCEL approach needs a licensing decision BEFORE downloading

Multiple investigations flagged the same issue: CCEL asserts copyright on their formatting even though the underlying texts are PD. The options are:
- **Email CCEL for permission** (recommended — they're responsive and the project is non-commercial)
- **Use alternative sources** (Project Gutenberg for plain text, CrossWire for SWORD modules)
- **Use CCEL only for structure reference**, then source the actual text from PD-only origins

### Translation copyright traps identified

Several investigations flagged the same pattern: modern translations of ancient texts are copyrighted even though the originals are PD. Specific traps:
- Heidelberg Catechism: Faith Alive 2011 CRC/RCA translation is copyrighted → use 1879 RCA translation
- Luther's catechisms: CPH modern translations are copyrighted → use Bente/Dau 1921 from Project Gutenberg
- Augustine's Confessions: Outler translation on CCEL may be 20th century → use Pusey translation (PG #3296)
- Athanasius: C.S. Lewis-prefaced Mackmurdo translation is NOT PD → use Robertson 1891 (NPNF)
- Hymns: modern translations of ancient hymns are copyrighted → check translation date, not just original authorship

### Hard stops confirmed

| Item | Why | Status |
|------|-----|--------|
| My Utmost for His Highest | US first pub 1935, copyright renewed 1963, not PD until ~2030 | Remove from project scope |
| Valley of Vision | Banner of Truth copyright, actively enforced, Bennett substantially reworked texts | Remove — source Puritan prayers from originals instead |
| StudyLight.org | Explicit permission required for all reuse | Do not scrape |
| Sacred-Texts.com | ToS: 1 file/day for robots | Use for verification only, not acquisition |

---

## 4. Is There Anything We Missed?

### Sources to investigate that weren't covered

1. **Standard Ebooks** — only came up for Pilgrim's Progress, but they have many more CC0 Christian texts. Worth a broader catalog check.
2. **OpenBible.info** — not investigated. May have topical/cross-reference data.
3. **BibleGateway.com** — not investigated (likely copyrighted content), but worth checking for any PD offerings.
4. **Logos Bible Software free resources** — Logos distributes some free modules; some may be PD.
5. **e-Sword modules** — free Bible software with downloadable modules; some commentary modules may be PD.
6. **Blue Letter Bible API** — has some structured data; API access needs investigation.
7. **eBible.org** — World English Bible and other open-license translations.

### Data types not yet investigated

- **Church history texts** (Eusebius, Foxe's Book of Martyrs, etc.) — mentioned in the design spec but no INV prompt was run
- **Lectionary data** — structured reading plans (some GitHub repos found incidentally)
- **Biblical geography/archaeology reference** — Smith's Dictionary partially covers this

### Contact opportunities not yet pursued

1. **Hymnary.org** — email for full dump (highest leverage)
2. **CCEL** — email for ThML permission (second highest leverage)
3. **Yale Edwards Center** — data partnership for 1,200+ Edwards sermons
4. **JWBickel** — license confirmation for HuggingFace Bible dictionaries
5. **NonlinearFruit/Creeds.json** — issue #59 resolution (35 docs are usable regardless, but full resolution would be clean)

---

## 5. What Could Be Better?

### Process improvements for next round

1. **The INV-2 (confessions) agent didn't know about our Creeds.json clone findings.** It treated Creeds.json as "no license, schema study only" — but our direct inspection showed 35/43 documents are explicitly Unlicense. Future investigations should have the clone inspection results as input context.

2. **Multiple agents independently discovered the same CCEL licensing constraint.** This is the most critical cross-cutting issue. A shared "known constraints" document would prevent 5 agents from each spending tokens re-discovering the same thing.

3. **robots.txt checking was inconsistent.** Some agents couldn't fetch robots.txt (WebFetch failures). A dedicated pre-check of all target site robots.txt would have been more efficient.

4. **The "respectful downloading" preamble was effective.** Every agent followed it. No agent attempted unauthorized bulk downloads. This validates the approach.

### Architecture improvements

1. **Source-oriented download prompts are the right next step.** Now that we know the best source per category, the download prompts should be organized by source site (one session per CCEL, one per CrossWire, one per Project Gutenberg, etc.) to respect rate limits.

2. **A shared OSIS book code mapping is needed.** Multiple categories (commentaries, cross-references, confessions with proof texts) need to normalize verse references to OSIS format. Build this utility once.

3. **A shared ThML parser is needed.** CCEL ThML powers theological works, commentaries, reference works, devotionals, and sermons. One parser serves all categories.

---

## 6. Recommended Priority Order

### Tier 1 — This week (data on disk, zero friction)

1. Creeds.json → confessions + catechisms (35 docs, Unlicense)
2. Commentaries-Database → Church Fathers (58,675 TOML entries, PD)
3. bible_databases/BSB.json → Bible text (CC0)
4. JWBickel/BibleDictionaries → reference works (HuggingFace download)
5. Standard Ebooks → Pilgrim's Progress (git clone, CC0)

### Tier 2 — This week (simple downloads, settled sources)

6. CrossWire SWORD → Barnes NT + Calvin + Wesley commentaries (3 ZIPs)
7. CrossWire SWORD → Morning & Evening + Daily Light devotionals (2 ZIPs)
8. Project Gutenberg → Luther's catechisms (#1670, #1722), Baltimore Catechism (#14552), Imitation of Christ (#26222), Augustine Confessions (#3296)
9. BCP 1662 → eskimo.com download

### Tier 3 — Send emails (highest leverage per token spent)

10. Email Hymnary.org (unlocks hymns)
11. Email CCEL (unlocks theological works, Nave's, sermon XML)
12. Email Yale Edwards Center (unlocks 1,200+ sermons)
13. Email JWBickel (confirms reference work license)

### Tier 4 — Longer downloads (rate-limited, need scripts)

14. HelloAO CLI self-host → 5 commentaries
15. The Kingdom Collective → Spurgeon ~3,000 sermons
16. Wikisource API → confessional documents (gap fill)
17. Project Gutenberg → Maclaren + Whitefield sermons

### Tier 5 — Defer (needs OCR or human judgment)

18. Internet Archive → Spurgeon Treasury of David, Bengel, Lange (spot-check quality first)
19. ISBE → 5-volume OCR processing project
20. Streams in the Desert → copyright verification first
21. Puritan prayers from primary sources (Owen, Watson, Doddridge)
22. Matthew Poole → inspect grace-ebooks.com ZIPs

---

## 7. Emails to Draft

| To | Subject | Key Ask | Priority |
|----|---------|---------|----------|
| Hymnary.org | Research data access for open-source hymn dataset | Full CSV dump of PD hymn texts + metadata | HIGH |
| CCEL | ThML/XML use in open-source non-commercial project | Permission to use ThML files for OCD | HIGH |
| Yale Edwards Center | Data partnership for sermon corpus | Bulk access to WJE Online transcripts | MEDIUM |
| JWBickel | License for BibleDictionaries HuggingFace dataset | Would they add CC0/PD dedication? | LOW |

---

*This synthesis covers 8 source investigations, 6 GitHub repo inspections, and cross-category analysis. All findings are documented in individual reports under research/{category}/SOURCE_INVESTIGATION.md and raw/{repo}/INSPECTION_REPORT.md.*

---

## 8. Round 2 Findings (2026-03-27)

Three additional investigations were run to address gaps identified during the main synthesis.

---

### 8a. Standard Ebooks — Full Christian Catalog

**Finding:** Standard Ebooks has 19 confirmed, downloadable Christian titles — not just Pilgrim's Progress. All carry SE's CC0 dedication on their editorial work; underlying texts are US public domain.

**High-priority titles for OCD:**

| Title | Author | Category | Notes |
|---|---|---|---|
| The City of God | Augustine | Theological | 444k words; published Jan 2026 — highest priority |
| The Imitation of Christ | Thomas à Kempis | Devotional | Better markup than PG #26222 — replace PG source |
| Orthodoxy | G.K. Chesterton | Theological | |
| Heretics | G.K. Chesterton | Theological | Companion to Orthodoxy |
| The Everlasting Man | G.K. Chesterton | Theological | 107k words |
| Unspoken Sermons | George MacDonald | Sermon/Devotional | 175k words, 3 series |
| Practical Mysticism | Evelyn Underhill | Devotional | |
| A Day at a Time | Archibald Alexander | Devotional | Daily meditations (1916) |
| Paradise Lost | John Milton | Theological Poetry | |
| The Consolation of Philosophy | Boethius | Philosophy/Theology | |
| The Kingdom of God Is Within You | Tolstoy | Theological | |
| The Pilgrim's Progress | John Bunyan | Allegory | (already in Tier 1) |

**Source format:** No plain `.txt` download — source XHTML is on GitHub at `github.com/standardebooks/{se-identifier}`. This is parseable and cleaner than PG raw text.

**C.S. Lewis / Narnia:** The agent found Narnia listed but this needs verification. Narnia was published 1950-1956; these would not be US public domain until ~2046-2051. SE only publishes US PD works — these are likely placeholder/wanted pages, not published books. Do not use without confirming.

**Placeholder pages (SE's wanted list — not yet produced):**
- Calvin's Institutes, Augustine's Confessions, Augustine's On Christian Doctrine, Aquinas's Summa Theologica

**Collaboration opportunity:** These placeholder pages are SE's equivalent of a wanted list. OCD's ThML cleaning work on these texts could feed directly into SE's typesetting pipeline. Reciprocally, SE's editorial quality on completed books (proofreading, structural markup) would improve our source text quality. **Add SE to emails to draft.**

**Tier 1 update:** Replace "Pilgrim's Progress only" with the full SE catalog above. Also move Imitation of Christ from Tier 2 (Project Gutenberg) to Tier 1 (Standard Ebooks has better markup).

---

### 8b. Nave's Topical Bible — Source Investigation

**Gap confirmed:** No structured Nave's dataset exists on HuggingFace. First-mover opportunity.

**Best source now (no CCEL permission needed):**

**navestopicalbible.org** — purpose-built developer download with 20,000+ topics. Custom markup format:
- `$$topic_number` precedes each topic
- `\TOPIC NAME\` wraps topic heading
- `#` begins verse reference list
- `|` terminates the entry
- `»` prefixes cross-references to other topic numbers

Custom markup is documented within the download. ~100-line Python parser sufficient. Data quality: >99% clean (passed systematic error-pattern checking).

**MetaV (GitHub, multiple forks):** CSV relational schema with Topics + TopicIndex tables. Key limitation: Nave's and Torrey's topics are **merged with no distinguishing flag** and likely stores topic name + verse list only (no full text). Use as cross-reference skeleton only, not as primary source.

**rcdilorenzo/ecce:** GPL-3, only ~4,200 topics (ESV-intersected), incomplete. Skip.

**CCEL ThML:** Remains the authoritative validation source once permission arrives. Same ThML parsing approach used for other works applies here.

**Recommended approach:**
1. Download from navestopicalbible.org now (developer download, PD text, no permission blocker)
2. Write parser for the custom markup → OCD schema
3. Cross-check verse coverage against MetaV TopicIndex
4. Validate against CCEL ThML once email resolves
5. Publish to HuggingFace (genuine first structured Nave's dataset on the platform)

**Add to Tier 2 downloads** (needs a parser script, not just a download).

---

### 8c. HuggingFace Dataset Publishing Requirements

**Format:** Publish as JSONL. HF auto-converts to Parquet for the viewer (via `parquet-converter` bot) — no manual Parquet generation needed.

**Repository structure (recommended):**
```
open-christian-data/          ← one repo per thematic grouping
├── README.md                 ← dataset card with YAML configs block
├── LICENSE.md                ← per-subset license details
├── origen/
│   └── train.jsonl
├── tertullian/
│   └── train.jsonl
```

**Dataset card YAML frontmatter (CC0 example):**
```yaml
---
license: cc0-1.0
language:
  - en
pretty_name: "Open Christian Data — Patristic Commentary"
tags:
  - text
  - religion
  - theology
  - public-domain
  - christianity
size_categories:
  - 10K<n<100K
configs:
  - config_name: origen
    data_files: "origen/*.jsonl"
    default: true
  - config_name: tertullian
    data_files: "tertullian/*.jsonl"
---
```

**Mixed licenses:** No native HF support. Use `license: other` + `LICENSE.md` documenting source license per sub-dataset. This is the correct approach for datasets that mix CC0 (Creeds.json) with CC BY 4.0 (STEPBible).

**License identifiers:**
| License | HF Identifier |
|---|---|
| CC0 1.0 | `cc0-1.0` |
| CC BY 4.0 | `cc-by-4.0` |
| Mixed | `other` (+ LICENSE.md) |

**No loading script needed.** The `configs` YAML block handles multi-dataset repos. Loading: `load_dataset("open-christian-data/patristics", "origen")`.

**Size:** Free tier handles OCD's expected volume comfortably. Files >10MB go through Git LFS (handled automatically by `huggingface_hub` library).

**Action items:**
1. Create HF org `open-christian-data`
2. All JSONL records must have consistent schema (same keys, same types) for viewer to work
3. Add `source_license` field to every record schema — records the input material's license

---

### 8d. Schema Addition — Source Provenance

Every record in every dataset needs a `source_license` field documenting the input material's license. This enables:
- Correct HuggingFace license declaration per sub-dataset
- Ability to upgrade to CC0 later when better-licensed sources are found
- Transparency for downstream users

Required fields to add to all schemas:
- `source_license`: e.g. `"public_domain"`, `"cc0"`, `"cc_by_4.0"`, `"unlicense"`
- `source_url`: canonical URL of the input file
- `translation_year` (for translated texts): year of the specific translation used

---

### 8e. Updated Emails to Draft

| To | Subject | Key Ask | Priority |
|----|---------|---------|----------|
| Hymnary.org | Research data access for open-source hymn dataset | Full CSV dump of PD hymn texts + metadata | HIGH |
| CCEL | ThML/XML use in open-source non-commercial project | Permission to use ThML files for OCD | HIGH |
| Yale Edwards Center | Data partnership for sermon corpus | Bulk access to WJE Online transcripts | MEDIUM |
| JWBickel | License for BibleDictionaries HuggingFace dataset | Would they add CC0/PD dedication? | LOW |

Note: Standard Ebooks does not require an email — their GitHub repos are openly accessible and CC0. We use their output as input; if our cleaned texts happen to be useful to them, fine, but no extra collaboration effort is warranted.
