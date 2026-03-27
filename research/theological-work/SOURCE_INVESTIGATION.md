# Theological Works — Source Investigation
*Researched: 2026-03-27 | Researcher: Claude Code (OCD project)*

---

## Decision Brief

**5 key findings to act on:**

1. **CCEL is the primary source for almost all works** — ThML/XML available for Calvin, Edwards, Owen, Baxter, Bunyan, Augustine (Confessions), Athanasius. ThML gives structured chapter-level markup, but CCEL asserts copyright on *their formatting* even though the underlying texts are public domain. Permission is granted for "personal, educational, or non-profit" use; for an open-source data project, contact CCEL to confirm before bulk use.

2. **Calvin's Institutes: best structured source is CCEL ThML** — CCEL at `/ccel/calvin/institutes.xml`. Also on Wikisource (1845 Beveridge, chapter-structured, CC BY-SA), and Project Gutenberg (ebooks 45001 + 64392, epub/txt, no chapter metadata in the raw text). Wikisource is cleanest open-license option; CCEL ThML is richest structurally.

3. **Hodge's Systematic Theology: CCEL only for structured text** — NOT on Project Gutenberg (that result is Augustus Hopkins Strong, a different author). CCEL has all 3 volumes in ThML/XML format. Internet Archive has scanned OCR copies — usable but noisier.

4. **Pilgrim's Progress: Standard Ebooks is the best clean text** — CC0 licensed, carefully typeset, available on GitHub with full epub source. Project Gutenberg #131 is also fine for plain text.

5. **Yale Edwards edition is NOT bulk-downloadable** — edwards.yale.edu is a research interface, not a data source. CCEL has Edwards' major treatises in ThML. Digital Puritan Press has Owen's complete works (16+ volumes) in txt/epub/mobi via Internet Archive.

**Recommended start:** CCEL ThML for Calvin + Edwards + Owen + Baxter + Athanasius. Standard Ebooks GitHub for Bunyan. Project Gutenberg for Augustine Confessions. Contact CCEL about license before production use.

---

## robots.txt Findings

| Source | robots.txt Status | Crawl Delay |
|---|---|---|
| ccel.org | Allows all bots (no Disallow for `*`). Meta-externalagent blocked. | 10 seconds default |
| gutenberg.org | Cannot confirm directly — policy page states bulk download must use mirror/harvest endpoint, not scrape pages | 2 sec minimum (wget `-w 2`) |
| archive.org | Cannot confirm directly — generally permissive for research use, API available | Use API, not scraping |
| wikisource.org | Cannot confirm directly — MediaWiki API is the approved access method | Use API |

**Project Gutenberg bulk download:** Use the official harvest endpoint (`/robot/harvest?filetypes[]=txt`) or rsync mirror. Do NOT scrape individual pages. RDF/XML catalog available for metadata.

---

## Per-Work Findings

### 1. Calvin's Institutes of the Christian Religion (Beveridge, 1845)

| Attribute | Detail |
|---|---|
| Best source | CCEL ThML (primary); Wikisource (open license) |
| CCEL URL | `https://www.ccel.org/ccel/calvin/institutes.html` |
| CCEL formats | ThML/XML, PDF, epub, Kindle, plain text (UTF-8), MP3, Word HTML |
| CCEL XML path | `/ccel/calvin/institutes.xml` |
| Project Gutenberg | Ebook #45001 (Vol. 1) + #64392 (Vol. 2) — epub, txt, HTML |
| Wikisource | `en.wikisource.org/wiki/Institutes_of_the_Christian_Religion_(1845)` — chapter-structured, CC BY-SA |
| Internet Archive | Scanned OCR copies available, lower text quality |
| Structure quality | **High** — 4 books, many chapters; ThML preserves hierarchy; Wikisource has chapter-level navigation |
| License | CCEL: public domain text, CCEL asserts copyright on formatting (non-commercial use permitted). Wikisource: CC BY-SA. PG: public domain. |
| Access method | CCEL: direct XML download (login may be required for some formats); PG: direct download; Wikisource: MediaWiki API |

**Notes:** The Beveridge translation (1845, 2-volume set) is the one on PG. CCEL may have a different edition. Wikisource has the Beveridge 1845 version with proper book/chapter hierarchy.

---

### 2. Hodge's Systematic Theology (1871–1873, 3 volumes)

| Attribute | Detail |
|---|---|
| Best source | CCEL ThML |
| CCEL URLs | Vol 1: `ccel.org/ccel/hodge/theology1.html` | Vol 2: `ccel.org/ccel/hodge/theology2/` | Vol 3: `ccel.org/ccel/hodge/theology3/` |
| CCEL formats | ThML/XML, PDF, epub, Kindle, plain text, Word HTML |
| CCEL XML paths | `/ccel/h/hodge/theology1.xml`, `/theology2.xml`, `/theology3.xml` |
| Project Gutenberg | **NOT available** — PG "Systematic Theology" search results return Augustus Hopkins Strong (different author) |
| Internet Archive | Multiple OCR scans available — lower text quality, variable OCR accuracy |
| Structure quality | **High** on CCEL — TOC pages confirm chapter-level navigation (`theology1.toc.html`) |
| License | CCEL: public domain text, CCEL asserts copyright on formatting |
| Access method | CCEL direct XML download |

**Notes:** Hodge's 3-volume work is a substantial download — verify all three XML files are complete before processing.

---

### 3. Jonathan Edwards' Treatises

| Attribute | Detail |
|---|---|
| Works covered | Religious Affections (1746), Freedom of the Will (1754) |
| Best source | CCEL ThML for both |
| Religious Affections URL | `ccel.org/ccel/edwards/affections.html` |
| Religious Affections XML | `/ccel/e/edwards/affections.xml` |
| Freedom of the Will URL | `ccel.org/ccel/edwards/will.html` |
| CCEL formats | ThML/XML, PDF, epub, Kindle, plain text (UTF-8) |
| Yale Edwards edition | edwards.yale.edu — research interface only, not bulk-downloadable; contains full Yale edition (26 vols) plus unpublished manuscripts, but no data export |
| Digital Puritan Press | Works available via Internet Archive in PDF, epub, mobi, txt |
| Structure quality | **High** on CCEL — section-level markup in ThML |
| License | CCEL: public domain text, CCEL formatting copyright |
| Access method | CCEL direct XML download |

**Notes:** The Yale Edwards Online (edwards.yale.edu) is the definitive scholarly edition but is a read-only research interface. No API, no bulk export. CCEL Edwards texts are likely from the earlier Dwight/Worcester editions, not the Yale critical edition — adequate for most uses.

---

### 4. John Owen's Major Works

| Attribute | Detail |
|---|---|
| Works covered | Mortification of Sin (1656), Glory of Christ (1684) |
| Best source | CCEL ThML for individual works; Digital Puritan Press for complete works in plain text |
| CCEL Mortification URL | `ccel.org/ccel/owen/mort.html` |
| CCEL Mortification XML | `/ccel/o/owen/mort.xml` |
| CCEL Glory of Christ URL | `ccel.org/ccel/owen/glory.html` |
| CCEL formats | ThML/XML, PDF, epub, Kindle, plain text (UTF-8), MP3 |
| Digital Puritan Press | Complete Works of John Owen — 16+ volumes in PDF, epub, mobi, txt via Internet Archive |
| Digital Puritan Press URL | `digitalpuritan.net/john-owen/` |
| Structure quality | **High** on CCEL — both works chapter-structured in ThML |
| License | CCEL: public domain text, CCEL formatting copyright. Digital Puritan: public domain. |
| Access method | CCEL direct XML download; Digital Puritan via Internet Archive (direct file links) |

**Notes:** Digital Puritan Press links directly to files at `digitalpuritan.net/Digital%20Puritan%20Resources/Owen,%20John/`. The complete works include Mortification (Vol 6) and Glory of Christ (various). Plain .txt files are available and are clean text (not OCR scans).

---

### 5. Richard Baxter's Reformed Pastor (1656)

| Attribute | Detail |
|---|---|
| Best source | CCEL ThML |
| CCEL URL | `ccel.org/ccel/baxter/pastor.html` |
| CCEL XML | `/ccel/b/baxter/pastor.xml` |
| CCEL formats | ThML/XML, PDF, epub, Kindle, plain text (UTF-8), Word HTML |
| Project Gutenberg | Available (listed as "Christian Ecclesiastics" — confirm it's the Reformed Pastor text) |
| Internet Archive | Scanned copy: `archive.org/details/reformedpastor00baxt` |
| Digital Puritan Press | `digitalpuritan.net/richard-baxter/` — PDF, epub, mobi, txt |
| Structure quality | **High** on CCEL — chapter-structured in ThML |
| License | CCEL: public domain text, CCEL formatting copyright |
| Access method | CCEL direct XML download |

---

### 6. John Bunyan's Pilgrim's Progress (1678)

| Attribute | Detail |
|---|---|
| Best source | **Standard Ebooks** — CC0, production-quality, GitHub source available |
| Standard Ebooks URL | `standardebooks.org/ebooks/john-bunyan/the-pilgrims-progress` |
| Standard Ebooks license | CC0 1.0 (contributions) — underlying text is public domain |
| Standard Ebooks GitHub | `github.com/standardebooks/john-bunyan_the-pilgrims-progress` — epub source files |
| Project Gutenberg | Ebook #131 — epub, txt, HTML — clean proofread text, public domain |
| CCEL | Available in ThML/XML |
| Structure quality | **High** — Part 1 and Part 2 are clearly delineated in all versions; Standard Ebooks adds semantic markup |
| License | Standard Ebooks: CC0. Project Gutenberg: public domain. |
| Access method | Standard Ebooks: direct download or clone GitHub repo. PG: direct download. |

**Notes:** This is the most widely digitised work on the list. Standard Ebooks is the clear winner for clean, openly licensed text with semantic structure. If structure depth matters (e.g. Part 1/Part 2 sections), use Standard Ebooks epub source from GitHub.

---

### 7. Augustine's Confessions and City of God

| Attribute | Detail |
|---|---|
| **Confessions** | |
| Best source for Confessions | CCEL ThML (Outler translation, CC-compatible); or Project Gutenberg (Pusey translation, public domain) |
| CCEL Confessions — Outler | `ccel.org/ccel/augustine/confessions.html` (Outler translation) |
| CCEL Confessions — Pusey | `ccel.org/ccel/augustine/confess.html` (older Pusey translation) |
| Project Gutenberg Confessions | Ebook #3296 — Pusey translation — epub, txt, HTML |
| Structure quality | **High** — 13 books, chapter-structured in ThML; PG version also preserves book divisions |
| **City of God** | |
| Best source for City of God | CCEL via NPNF series (Dods translation) |
| CCEL City of God URL | `ccel.org/ccel/schaff/npnf102.html` (NPNF1-02, Dods/Wilson/Smith translations) |
| Project Gutenberg City of God | Ebooks #45304 + #45305 (2 vols, Glasgow 1871 edition) |
| Translations available (PD) | Dods (1871, via NPNF) — public domain. Pusey/various (Glasgow 1871). Henry Bettenson (1972) — NOT public domain. |
| License | CCEL: public domain text, CCEL formatting copyright. PG: public domain. |
| Access method | CCEL direct XML download; PG direct download |

**Notes:** The Outler translation of the Confessions (CCEL-specific) is a 20th-century translation — check CCEL copyright terms carefully before using in an open dataset, as it may not be fully public domain. The Pusey/older translations are safely public domain. For City of God, the Dods 1871 translation (used in NPNF) is public domain.

---

### 8. Athanasius' On the Incarnation

| Attribute | Detail |
|---|---|
| Best source | CCEL ThML (Schaff NPNF2-04 edition) |
| CCEL standalone URL | `ccel.org/ccel/athanasius/incarnation.html` |
| CCEL XML | `/ccel/a/athanasius/incarnation.xml` |
| CCEL NPNF2-04 | `ccel.org/ccel/schaff/npnf204.html` — full Athanasius volume |
| CCEL formats | ThML/XML, PDF, epub, plain text (ASCII), MP3 |
| Translation | Robertson translation (NPNF series, 1891) — public domain |
| Internet Archive | Scanned copy: `archive.org/details/stathanasiusonin0000atha` |
| Structure quality | **Moderate** — relatively short work; CCEL ThML preserves chapter sections |
| License | CCEL: public domain text (Robertson 1891 translation), CCEL formatting copyright |
| Access method | CCEL direct XML download |

**Notes:** The C.S. Lewis-prefaced translation (Mackmurdo/Macquarrie, published by Mowbray) is NOT public domain — it's a 20th-century translation. The NPNF Robertson translation is the safe public domain option.

---

## Structure Analysis

### How CCEL ThML Is Structured

ThML (Theological Markup Language) is an XML application developed by CCEL. Key structural elements:

- `<div1>`, `<div2>`, `<div3>` for hierarchical book/chapter/section divisions
- `<scripCom>` for scripture comments
- `<scripRef>` for inline scripture references
- `<index>` for index entries
- Works are single XML files — the entire work in one file with nested divs

**What this means for ingestion:**
- A single XSLT or Python XML parser can extract all chapters with their headings and body text
- Scripture references are tagged inline — useful for cross-referencing
- Much richer than plain text but requires XML parsing

### Structure Quality Ratings

| Work | Structure Quality | Chapter-Level Navigation | Section Headers Preserved |
|---|---|---|---|
| Calvin's Institutes | High | Yes (4 books, ~80 chapters) | Yes |
| Hodge's Systematic Theology | High | Yes (TOC confirmed) | Yes |
| Edwards' Religious Affections | High | Yes (3 parts + chapters) | Yes |
| Edwards' Freedom of the Will | High | Yes | Yes |
| Owen's Mortification of Sin | High | Yes (16 chapters) | Yes |
| Owen's Glory of Christ | High | Yes | Yes |
| Baxter's Reformed Pastor | High | Yes | Yes |
| Bunyan's Pilgrim's Progress | High | Yes (Part 1/Part 2) | Yes (Standard Ebooks) |
| Augustine's Confessions | High | Yes (13 books) | Yes |
| Augustine's City of God | High | Yes (22 books, NPNF) | Yes |
| Athanasius' On the Incarnation | Moderate | Yes (57 sections) | Yes |

---

## CCEL Licensing — Key Finding

CCEL explicitly states: texts may be used for **personal, educational, or non-profit purposes**. Commercial use requires permission. CCEL asserts copyright on their ThML formatting markup even when the underlying text is public domain.

**For an open-source data project:** The OCD project is non-commercial. However, "non-profit" and "open-source" are not identical, and the copyright assertion on formatting is a real constraint. **Recommended action before bulk download:** Email CCEL (through their contact page) stating the OCD project's nature (open-source, non-commercial, public domain texts only) and ask for explicit permission to use their ThML files.

**Alternative path:** Use Project Gutenberg plain text (clearly public domain, no formatting copyright), then process chapter structure from the text itself using headings. Less precise but legally cleaner.

---

## Recommended Download Sequence

Priority order based on coverage, structure quality, and license clarity:

1. **Bunyan's Pilgrim's Progress** — Clone Standard Ebooks GitHub repo now. CC0, no friction, best quality. `git clone https://github.com/standardebooks/john-bunyan_the-pilgrims-progress`

2. **Project Gutenberg downloads** — Calvin Institutes (45001 + 64392), Augustine Confessions (3296), Augustine City of God (45304 + 45305), Baxter Reformed Pastor. Use PG harvest endpoint or direct txt download. All clearly public domain.

3. **Contact CCEL** — Request permission for ThML XML use in OCD project (open-source, non-commercial). If granted, download: Calvin, Hodge (all 3 vols), Edwards (Affections + Will), Owen (Mortification + Glory), Baxter, Athanasius.

4. **Digital Puritan Press** — Owen's complete works in plain txt via Internet Archive. Check robots.txt before accessing. Text is public domain; formatting from Goold's 1850-1855 edition.

5. **Wikisource API** — Calvin's Institutes (CC BY-SA) as an alternative if CCEL permission is unclear. Use MediaWiki API for structured chapter-by-chapter export.

6. **CCEL NPNF series** — Augustine City of God (npnf102) and Athanasius (npnf204) in ThML/XML if CCEL permission is granted.

7. **Yale Edwards — do not attempt bulk download** — read-only research interface. No data export path.

---

*Sources consulted: ccel.org, gutenberg.org, standardebooks.org, archive.org, edwards.yale.edu, digitalpuritan.net, en.wikisource.org*
