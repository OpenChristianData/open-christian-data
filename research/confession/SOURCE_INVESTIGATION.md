# Confessional Documents — Source Investigation

**Date:** 2026-03-27
**Status:** Research only — no bulk downloading conducted
**Scope:** 21 confessional documents across Reformed, Baptist, Lutheran, Anglican, and Ecumenical categories

---

## 1. Decision Brief

### Key Findings

- **Wikisource is the primary go-to source** for most documents. It provides public domain texts via CC-BY-SA, has a fully open MediaWiki API for programmatic download, and covers ~16 of 21 target documents. The main limitation: proof texts are generally absent from Wikisource editions — the confession text only.

- **Proof texts are the hard problem.** No clean, open-licensed, structured digital source combines chapter/article text AND proof text references for more than a handful of documents. The best proof-text source (OPC's editions) is under full copyright. Creeds.json has structured proof texts but no license on the repo.

- **Creeds.json (NonlinearFruit/Creeds.json) covers most of what we need in JSON** — 43 documents, structured chapters/questions/proof texts. **CORRECTION (post-investigation):** Direct inspection of the repo README revealed 35 of 43 documents are explicitly under the Unlicense (PD equivalent). Only 8 documents are copyrighted (Chicago Statement, Crossway ESV texts, Helvetic Consensus, Savoy Declaration). The 35 Unlicense documents are usable immediately — this is our primary source for confessions and catechisms.

- **CCEL is valuable for ThML-formatted scholarly texts** including Philip Schaff's *Creeds of Christendom* (Vols. 1-3) which covers most confessions in a historically rigorous edition. CCEL asserts copyright on its formatting/encoding but underlying texts are public domain. Usable with care.

- **The Savoy Declaration, Abstract of Principles, and Ten Theses of Berne** lack clean structured digital sources. EEBO (CC0) has Savoy; SBTS has Abstract of Principles; creedsandconfessions.org has Berne (CC BY 4.0).

- **Lutheran documents require two separate sources:** bookofconcord.org (Concordia Publishing House translation — not freely reusable) for modern scholarly editions; Wikisource for public domain translations.

- **CRCNA's Three Forms translations (Belgic, Dort, Heidelberg) are copyrighted** (Faith Alive Christian Resources, 2011). Must use older translations from Wikisource or Schaff's *Creeds of Christendom*.

### Recommended Source Hierarchy

1. **Wikisource** — confession text, no proof texts, CC-BY-SA, fully programmable API
2. **Philip Schaff, Creeds of Christendom Vol. III** (CCEL + Internet Archive) — scholarly editions of nearly all documents; CCEL formatting copyright but underlying text public domain; Internet Archive provides freely downloadable scans
3. **creedsandconfessions.org** — Ten Theses of Berne CC BY 4.0 translation; check others on the site
4. **EEBO/University of Michigan** — Savoy Declaration (CC0)
5. **SBTS website** — Abstract of Principles (plain text, no explicit license but widely republished as public domain)
6. **Denomination websites** (reformed.org, opc.org, apuritansmind.com) — for plain text with proof text references; copyright is murky but these are public domain documents; each needs individual assessment

---

## 2. Per-Document Findings

| Document | Best Source | Format | Proof Texts? | Quality | Access Method | License |
|---|---|---|---|---|---|---|
| **Apostles' Creed** | Wikisource | Wikitext/HTML | No | Reliable (multiple translations; short text) | MediaWiki API | CC-BY-SA (digital); PD text |
| **Nicene Creed (381)** | Wikisource (via NPNF series) | Wikitext | No | Reliable — from Nicene and Post-Nicene Fathers Vol. XIV | MediaWiki API | CC-BY-SA (digital); PD text |
| **Athanasian Creed** | Wikisource (standalone page) | Wikitext | No | Reliable | MediaWiki API | CC-BY-SA (digital); PD text |
| **Chalcedonian Definition (451)** | Wikisource (via NPNF series) | Wikitext | No | Reliable; also in Schaff Vol. II | MediaWiki API | CC-BY-SA (digital); PD text |
| **Westminster Confession of Faith** | Wikisource | Wikitext | No | Reliable; 1647 text; also CCEL text version available | MediaWiki API | CC-BY-SA (digital); PD text |
| **Westminster Shorter Catechism** | Wikisource | Wikitext | No | Reliable | MediaWiki API | CC-BY-SA (digital); PD text |
| **Westminster Larger Catechism** | Wikisource | Wikitext | No | Reliable | MediaWiki API | CC-BY-SA (digital); PD text |
| **Belgic Confession** | Wikisource | Wikitext | No | Reliable; older translation (not CRCNA 2011) | MediaWiki API | CC-BY-SA (digital); PD text |
| **Canons of Dort** | Schaff, Creeds Vol. III (CCEL/Internet Archive) | ThML/HTML/PDF | Partial (articles only) | Scholarly; also some denomination sites | Internet Archive download; CCEL web | PD text; CCEL formatting copyright |
| **Heidelberg Catechism** | Wikisource | Wikitext | No | Reliable; note CRCNA 2011 translation is copyrighted — use older Wikisource version | MediaWiki API | CC-BY-SA (digital); PD text |
| **Savoy Declaration** | EEBO (Univ. Michigan) + Internet Archive | HTML/EPUB/PDF | No | Scholarly (original 1658 text); also CCEL via Schaff | CC0 (EEBO TCP); PD (Archive.org) | CC0 |
| **London Baptist Confession 1689** | Wikisource (check); khornberg/lbcf-1689 (GitHub) | JSON + Markdown | JSON version has references | Reliable; JSON repo has no explicit license — check | git clone (schema study) | JSON repo: no license; text PD |
| **New Hampshire Baptist Confession** | Wikisource | Wikitext | No | Reliable; also CCEL via Schaff Vol. III | MediaWiki API | CC-BY-SA (digital); PD text |
| **Abstract of Principles (1858)** | SBTS website / apuritansmind.com | HTML/PDF | No | Widely republished; original text PD (1858) | Web scrape or manual | No explicit license; PD text |
| **Augsburg Confession** | Wikisource | Wikitext | Partial (article headings) | Reliable; scholarly Schaff edition also available | MediaWiki API | CC-BY-SA (digital); PD text |
| **Luther's Small Catechism** | Wikisource (Concordia Triglotta) | Wikitext | No | Bente/Dau translation (1921); PD; bookofconcord.org has CPH translation (not free) | MediaWiki API | CC-BY-SA (digital); PD text |
| **Luther's Large Catechism** | Wikisource (via Lutheranism portal) | Wikitext | No | Bente/Dau translation (1921); PD | MediaWiki API | CC-BY-SA (digital); PD text |
| **Thirty-Nine Articles** | Wikisource (standalone page) | Wikitext | No | Reliable; 1571 text | MediaWiki API | CC-BY-SA (digital); PD text |
| **Scots Confession (1560)** | Wikisource (standalone page) | Wikitext | No | Reliable | MediaWiki API | CC-BY-SA (digital); PD text |
| **Canons and Decrees of Trent** | Wikisource | Wikitext | No | Reliable; also EEBO (CC0) and Internet Archive | MediaWiki API | CC-BY-SA (digital); PD text |
| **Ten Theses of Berne (1528)** | creedsandconfessions.org | HTML | No | English translation by Peter Chapman, CC BY 4.0 | Web scrape | CC BY 4.0 |

### Notes on Proof Texts

Proof texts are the most significant gap across all sources. The Westminster standards (WCF, WSC, WLC) are the documents with the most structured proof text traditions. Where proof texts appear in the research:

- **OPC editions** (opc.org/wcf.html and related PDFs): Full proof texts with KJV scripture references. Copyright OPC — all rights reserved. Cannot use directly.
- **Creeds.json**: Structured JSON with chapter/article/question arrays and proof text citation arrays (verse references only, not full text). Repo as a whole has no license — cannot use data.
- **thewestminsterstandard.org**: Has proof texts inline but no stated license.
- **Schaff's Creeds of Christendom Vol. III**: Contains confession text and historical notes; proof texts referenced but not exhaustively listed in the Schaff edition.

**For the Canons of Dort specifically:** The canons have scripture references embedded in some article-level editions, but Wikisource and Schaff editions may not include all of them.

---

## 3. Schema Considerations

### Structural Patterns

**Confession/chapter-based documents** (WCF, Belgic, Augsburg, 39 Articles, etc.):
```
Confession → Chapters → Articles/Sections → [Proof text references]
```

**Catechism documents** (Heidelberg, WSC, WLC, Luther's Catechisms):
```
Catechism → Questions → [Question number, Question text, Answer text, Proof text references]
```

**Creed documents** (Apostles', Nicene, Athanasian, Chalcedonian):
```
Creed → [Full text as single block, or Clauses/Articles]
```
Note: Ecumenical creeds have no proof texts by tradition.

**Canons of Dort** is structurally distinctive:
```
Canons → Heads of Doctrine → [Positive Articles, Rejection of Errors, each with their own potential proof texts]
```

**Council of Trent** is the most complex:
```
Session → [Decrees on doctrine, Canons] → individual canons (anathemas)
```

### Proof Text Reference Formats Observed

Standard format across Reformed confessions: `BookAbbrev Chapter:Verse` with multiple references separated by semicolons. Example from WLC Q.11:
```
Isa. 6:3, 5, 8; John 12:41; Acts 28:25; 1 John 5:20; Acts 5:3-4
```

Key schema design choices to resolve before ingestion:
1. Store proof texts as **array of verse reference strings** vs. array of structured objects (book, chapter, verse_start, verse_end)?
2. Handle **multiple proof text traditions** for WCF (1647 British, 1894 PCUSA, 1910 PCUS) — the references differ between editions.
3. Distinguish **structural levels**: some documents use chapter/section (WCF), others use head/article/rejection (Dort), others use session/decree/canon (Trent).
4. The Heidelberg Catechism also has **Lord's Day groupings** as a secondary structural layer above questions — whether to model this depends on use case.

### Translation Versioning

Multiple English translations exist for most documents. Tracking translation provenance is essential:
- WCF: 1647 text vs. American revisions (1789, 1887 for chapters 20, 23, 31)
- Heidelberg: Older PD translation vs. CRCNA 2011 (copyrighted)
- Lutheran documents: Bente/Dau 1921 (PD) vs. modern CPH translations (copyrighted)
- Belgic Confession: Pre-2011 translation (PD) vs. CRCNA 2011 (copyrighted)

The schema needs a `translation_source` and `translation_year` field per document.

---

## 4. Recommended Approach

### Phase 1 — Wikisource Bulk Download (no proof texts)
Download all 16+ documents available on Wikisource using the MediaWiki API. This gives clean, reliable, freely licensed text for the confession body. No proof texts, but gets the core structure into the dataset quickly.

**API endpoint:** `https://en.wikisource.org/w/api.php?action=parse&page=Westminster_Confession_of_Faith&prop=wikitext&format=json`

Documents to get from Wikisource:
- Apostles' Creed, Nicene Creed, Athanasian Creed, Chalcedonian Definition
- WCF, WSC, WLC
- Belgic Confession, Heidelberg Catechism
- Augsburg Confession
- Luther's Small Catechism, Luther's Large Catechism
- Thirty-Nine Articles, Scots Confession
- New Hampshire Baptist Confession
- Canons and Decrees of Trent

**Robots.txt check required** before scripting: `https://en.wikisource.org/robots.txt` — Wikisource API is the preferred/intended access method and is generally open.

### Phase 2 — Fill Gaps (structured or missing documents)
- **Canons of Dort**: Use Schaff Vol. III from Internet Archive (free download) or ccel.org. More structurally complex than most.
- **Savoy Declaration**: EEBO/University of Michigan (CC0) or Internet Archive.
- **Abstract of Principles**: SBTS website — manual transcription likely required; the document is short (20 articles).
- **Ten Theses of Berne**: creedsandconfessions.org (CC BY 4.0) — check robots.txt first.
- **London Baptist Confession 1689**: Wikisource if available; fallback to khornberg/lbcf-1689 (schema study only unless license clarified) or manual transcription from a clearly PD source.

### Phase 3 — Proof Texts (hardest problem)
No clean open-licensed structured proof text source exists. Options:
1. **Manual transcription** from OPC printed edition (public text, asserted copyright — murky). Least scalable.
2. **Contact NonlinearFruit/Creeds.json maintainer** to request data under Unlicense or CC0 for the non-copyrighted documents (issue #59 has been open — could offer to contribute). This would unlock the most valuable existing structured source.
3. **Extract from thewestminsterstandard.org** — has proof texts inline. Check ToS and robots.txt before any scraping.
4. **WCF proof text only**: opc.org publishes the proof texts in a PDF (SCLayout.pdf, WCFcombined.pdf). These are publicly accessible PDFs — copyright is asserted but PDF parsing for dataset creation may be fair use for research purposes. Flag for legal review before use.

### Documents Likely Needing Manual Transcription
- Abstract of Principles (short — 20 articles, feasible)
- Ten Theses of Berne (short — 10 theses, feasible; or use CC BY 4.0 translation)
- Proof texts for any document not covered by Creeds.json schema resolution

### Download Order (suggested)
1. Wikisource batch (Phase 1) — highest ROI, cleanest licensing
2. Internet Archive / EEBO for gap documents (Phase 2)
3. Proof text strategy decision (Phase 3) — requires a deliberate choice on acceptable risk or community engagement

---

## 5. Unlicensed Repos to Study for Schema

These repos have useful schemas and data that cannot be used directly due to missing or problematic licenses. Study the structure only.

| Repo | URL | What to Study | License Status |
|---|---|---|---|
| **Creeds.json** | github.com/NonlinearFruit/Creeds.json | Best-in-class JSON schema for confessions + catechisms + proof texts. Chapter/article/question arrays; citation arrays with verse refs. 43 documents. | No license on repo as a whole (issue #59 open). 8 documents explicitly copyrighted (Crossway, Alliance of Confessing Evangelicals). |
| **khornberg/lbcf-1689** | github.com/khornberg/lbcf-1689 | JSON + Markdown representations of 1689 LBCF. Study structure for chapter-level JSON design. | No license file observed in search results — confirm before use. |
| **sound_doctrine** | github.com/json469/sound_doctrine | Flutter app; MIT license on *code*, but document data sourced from external sites (CARM, Ligonier, etc.) — data license unclear. | MIT on code; underlying document data license unclear. |

### Schema Patterns to Extract from Creeds.json (observation only)

Based on publicly visible file names and structure (london_baptist_1689.json, canons_of_dort.json, westminster_larger_catechism.json, athanasian_creed.json):

- Separate JSON files per confession
- Likely top-level keys: title, year, document metadata
- Chapter-structured documents: array of chapters, each with array of articles/sections
- Catechism documents: array of Q&A pairs with question number
- Proof texts: array of citation strings per article/answer
- ~24,385 tests validating the structure — implies a strict schema enforced across all files

---

## 6. Source Reference URLs

**Wikisource documents confirmed:**
- Westminster Confession: https://en.wikisource.org/wiki/Westminster_Confession_of_Faith
- Westminster Shorter Catechism: https://en.wikisource.org/wiki/Westminster_Shorter_Catechism
- Westminster Larger Catechism: https://en.wikisource.org/wiki/Westminster_Larger_Catechism
- Belgic Confession: https://en.wikisource.org/wiki/Belgic_Confession
- Heidelberg Catechism: https://en.wikisource.org/wiki/The_Heidelberg_Catechism
- Augsburg Confession: https://en.wikisource.org/wiki/Augsburg_Confession
- Scots Confession: https://en.wikisource.org/wiki/Scots_Confession
- Thirty-Nine Articles: https://en.wikisource.org/wiki/Thirty-Nine_Articles
- New Hampshire Baptist Confession: https://en.wikisource.org/wiki/New_Hampshire_Baptist_Confession_of_Faith_(1833)
- Athanasian Creed: https://en.wikisource.org/wiki/Athanasian_Creed
- Luther's Small Catechism: https://en.wikisource.org/wiki/Luther%27s_Small_Catechism
- Canons and Decrees of Trent: https://en.wikisource.org/wiki/Canons_and_Decrees_of_the_Council_of_Trent

**Wikisource — to confirm individually (returned in search, not verified for completeness):**
- Nicene Creed: https://en.wikisource.org/wiki/Nicene_and_Post-Nicene_Fathers:_Series_II/Volume_XIV/The_Second_Ecumenical_Council/The_Holy_Creed
- Luther's Large Catechism: via Wikisource Lutheranism portal
- Chalcedonian Definition: via NPNF series on Wikisource
- London Baptist Confession 1689: check https://en.wikisource.org/wiki/Confession_of_Faith_(1689)

**CCEL / Schaff:**
- Schaff, Creeds of Christendom Vol. III (CCEL): https://ccel.org/ccel/schaff/creeds3.toc.html
- Schaff Vol. III (Internet Archive, free download): https://archive.org/details/TheCreedsOfChristendomV3

**Other gap sources:**
- Savoy Declaration (EEBO, CC0): https://quod.lib.umich.edu/e/eebo/A89790.0001.001
- Savoy Declaration (Internet Archive): https://archive.org/details/savoydeclaration0000unse
- Abstract of Principles (SBTS): https://www.sbts.edu/abstract-of-principles/
- Abstract of Principles (PDF): https://nobts.edu/baptist-center-theology/confessions/1858_Abstract_of_Principles.pdf
- Ten Theses of Berne (CC BY 4.0): https://creedsandconfessions.org/berne-theses.html
- Canons of Dort (Schaff Vol. III): https://ccel.org/ccel/schaff/creeds3.toc.html

**Wikisource API:**
- API base: https://en.wikisource.org/w/api.php
- WS Export tool (EPUB/PDF): https://wikisource.org/wiki/Wikisource:WS_Export

**Schema study only (no data use):**
- Creeds.json: https://github.com/NonlinearFruit/Creeds.json
- khornberg/lbcf-1689: https://github.com/khornberg/lbcf-1689
