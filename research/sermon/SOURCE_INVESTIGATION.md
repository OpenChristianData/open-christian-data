# Sermon Source Investigation
*Research session: 2026-03-27. RESEARCH ONLY — no bulk downloading performed.*

---

## 1. Decision Brief

**The five critical findings, in priority order:**

1. **Spurgeon clean text does exist — at The Kingdom Collective.** Over 3,000 sermons are available as individual HTML pages at `thekingdomcollective.com/spurgeon/sermon/[N]/`. This is the single most important finding. The site has no robots.txt. The content was originally extracted from SpurgeonGems PDFs by Emmett O'Donnell. The source GitHub repo (`bjcy/tcs.sc`) is gone, so the HTML is the only accessible version. This is the realistic path to a Spurgeon text corpus without an OCR pipeline.

2. **CCEL is the best single source for Wesley, Edwards (selected), Whitefield, and Maclaren.** CCEL's robots.txt explicitly permits crawling (all crawlers, 10-second crawl delay, no Disallow). Wesley has a direct XML download. Others have clean HTML read-online versions. CCEL should be treated as the primary structured source for all non-Spurgeon collections.

3. **Project Gutenberg covers Maclaren and Whitefield cleanly.** Maclaren's Expositions of Holy Scripture are available across multiple volumes as clean HTML/text — one of the easiest ingestions in this project. Whitefield's 6-volume Works are also on Gutenberg. No robots.txt friction, no rate limit concerns.

4. **Wesley Center Online is freely mirrorable.** The site explicitly states text may be freely used for personal or scholarly purposes, or mirrored. The 1872 edition (141 sermons) is available as individual HTML pages. CCEL's XML is a cleaner structural option.

5. **No pre-existing sermon corpus exists on HuggingFace or GitHub.** No dedicated public-domain sermon text dataset was found. The closest relevant find is the William Branham golden-dataset (metadata only, not useful here). This project would be the first structured public-domain sermon corpus at this scale.

**Recommendation:** Pursue The Kingdom Collective for Spurgeon and CCEL for all others. Defer Internet Archive OCR and the WJE Yale archive pending further access assessment.

---

## 2. Per-Collection Findings

| Collection | Clean Text Available? | Format | Best Source | Metadata Available | Count | Access Method |
|---|---|---|---|---|---|---|
| Spurgeon (MTP + PSP) | **Yes — partial** | HTML (per sermon) | The Kingdom Collective | Sermon number, title, scripture ref | ~3,000 of 3,563 | Web scrape (HTML pages) |
| Spurgeon (MTP + PSP) | **Yes — poor quality** | DJVU OCR text | Internet Archive | Volume, year | All 63 vols | Direct download (.djvu.txt) |
| Jonathan Edwards | Yes — selected only | ThML/XML + HTML | CCEL | Title | ~30 select sermons | XML direct download |
| Jonathan Edwards | Yes — 1,200+ sermons | HTML (web interface) | WJE Online (Yale) | Date, scripture, title | 1,200+ | Web scrape (terms unclear) |
| John Wesley | **Yes — complete** | XML + HTML | CCEL | Title, number | 141 (5 series) | XML direct download |
| John Wesley | **Yes — complete** | HTML (per sermon) | Wesley Center Online | Title, number, theme | 141 | Web scrape (mirroring permitted) |
| George Whitefield | Yes — selected | ThML/XML + HTML | CCEL | Title | 59 | XML direct download |
| George Whitefield | Yes — complete works | HTML/text | Project Gutenberg | Title | ~75 in 6 vols | Direct download |
| Alexander Maclaren | **Yes — extensive** | HTML/text | Project Gutenberg | Title, scripture ref | Hundreds across 17+ vols | Direct download |
| Alexander Maclaren | Yes | ThML/XML + HTML | CCEL | Title, scripture | Multiple vols | XML download + HTML |
| Robert Murray M'Cheyne | **Yes — tiny** | HTML (per sermon) | mcheyne.info | Title, scripture ref | 6 sermons + 3 tracts | Web scrape |
| Robert Murray M'Cheyne | Yes | PDF/DJVU | Internet Archive | Volume | ~200 known | OCR required |

---

## 3. Spurgeon Deep-Dive

### The core question: does clean text exist for more than a handful of Spurgeon sermons?

**Answer: Yes — approximately 3,000 sermons exist as clean HTML at The Kingdom Collective.**

### Sources checked and conclusions:

**SpurgeonGems.org**
- All 3,563 sermons available as individual PDFs (`/sermon/chs[N].pdf`)
- PDF-only. No HTML text. robots.txt not confirmed (WebFetch unavailable) but pattern is clear from search results.
- Conclusion: PDF source only. Requires OCR for bulk text extraction.

**The Kingdom Collective (`thekingdomcollective.com/spurgeon/`)**
- 3,000+ sermons available as individual HTML pages at `/spurgeon/sermon/[N]/`
- Text was extracted from SpurgeonGems PDFs by Emmett O'Donnell, then parsed into HTML by Benry Yip using a custom PDF-parse script (site notes mention spelling errors from the extraction).
- Sermon URL pattern: `/spurgeon/sermon/[number]/` — predictable, sequential from 1 to ~3,500+
- robots.txt: returns 404 — no robots.txt file exists. Site is hosted on Netlify.
- Source GitHub repo (`bjcy/tcs.sc`) is 404 — deleted, cannot retrieve the raw data files directly.
- Site appears dormant since 2014, but pages are still live and accessible.
- Caveat: text quality reflects PDF extraction — some parsing artefacts noted by the site owner (mis-parsed headers, spelling errors from OCR). Not perfectly clean, but far better than re-OCR'ing the PDFs.
- Conclusion: **Best available Spurgeon text source. Crawlable. Use 2-second minimum delay.**

**archive.spurgeon.org**
- Index-only site (Scripture index, title index, chronological index)
- Does NOT host full sermon text — links out to SpurgeonGems PDFs and other sources
- Administered by Midwestern Baptist Theological Seminary
- Conclusion: No text content here. Index resource only.

**CCEL (`ccel.org/ccel/spurgeon/sermons[NN]`)**
- 60 volumes confirmed present (sermons01 through sermons60, at least)
- Available formats per volume page: HTML (read online), PDF download, MP3
- ThML/XML: The CCEL ThML index lists Spurgeon works, but the XML file URL (`/cache/sermons01.xml`) returns 404. ThML is either not served publicly for Spurgeon or uses a different URL pattern. Wesley's XML at `ccel.org/ccel/wesley/sermons.xml` was indexed as accessible, suggesting CCEL's ThML coverage is inconsistent across authors.
- CCEL robots.txt: crawl permitted, 10-second crawl delay required.
- Conclusion: HTML available volume-by-volume, but must scrape chapter-by-chapter. Not a clean bulk text source. ThML not confirmed accessible for Spurgeon specifically.

**Internet Archive**
- Multiple volume scans available (both the Metropolitan Tabernacle Pulpit series and earlier "Sermons of Rev. C.H. Spurgeon" series)
- DJVU OCR text available as `.djvu.txt` files — bulk-downloadable without rate limits
- OCR quality: **Poor.** Confirmed errors from search result snippets: "SPERGEON'S SERMOIS" (Spurgeon's Sermons), "BEYISED BT TUl KEY" (Revised by The Rev.), "C. H. SPUEGEON" (C. H. Spurgeon). Typical Victorian scan OCR — character substitutions and spacing issues throughout.
- Not all 63 volumes have equivalent scan quality — some are better than others.
- Conclusion: Technically accessible but requires significant OCR post-processing. Low priority without an OCR correction pipeline.

**GitHub/HuggingFace**
- No dedicated Spurgeon sermon text dataset found on either platform.
- No NLP research group Spurgeon corpus found.
- Conclusion: Does not exist as a pre-packaged dataset.

**SWORD modules**
- CrossWire SWORD module "SME" = Spurgeon's *Morning and Evening* daily devotionals only. Not sermons.
- SwordSearcher Bible Software has a full sermon module (`chsSermons`) covering all 3,561 sermons (Park Street Pulpit 1-347, Metropolitan Tabernacle Pulpit 348-3561). However, SwordSearcher's license does not permit format shifting or redistribution — confirmed from forum discussion.
- Conclusion: SWORD/SwordSearcher is not a viable path for this project.

**Project Gutenberg**
- Spurgeon works on Gutenberg: "Around the Wicket Gate," "The Art of Illustration," "Talks to Farmers" — no sermon collections.
- Conclusion: Not a source for Spurgeon sermons.

### Spurgeon conclusion:
The Kingdom Collective is the only source of clean text for a large Spurgeon sermon corpus (~3,000 sermons). The text has some parsing artefacts from its origin as PDF extraction, but is far superior to re-OCR'ing 63 volumes of Victorian print scans. The remaining ~500+ sermons (those not extracted by O'Donnell) would require OCR from SpurgeonGems PDFs.

---

## 4. OCR Feasibility

For sources where PDF/scan is the only option:

| Source | Volume | OCR Complexity | Notes |
|---|---|---|---|
| Internet Archive — Spurgeon DJVU | 63 vols | High | Victorian typeset, poor existing OCR, header/footer noise, double-column layouts unlikely but possible |
| SpurgeonGems PDFs — uncovered sermons | ~500 sermons | Medium-High | Digitally typeset PDFs (not scanned) — much better OCR candidates than IA scans |
| Internet Archive — M'Cheyne | ~200 sermons | Medium | 19th century, single column, single volume confirmed |
| Grace eBooks — M'Cheyne | 2 vols PDF | Medium | Clean modern PDF — OCR likely straightforward |

**Assessment:** SpurgeonGems PDFs appear to be digitally typeset (not scans), which makes them far better OCR candidates than the Internet Archive DJVU files. If the ~500 sermons missing from The Kingdom Collective are needed, OCR of the SpurgeonGems PDFs (not the IA scans) is the right approach. Sample 2-3 PDFs first to confirm.

For the Internet Archive Spurgeon scans: the OCR quality is too poor to use directly and would require significant post-processing. This is not recommended without a dedicated OCR correction pipeline.

---

## 5. Recommended Approach

### Pursue now (clean text, no OCR required):

1. **The Kingdom Collective → Spurgeon (~3,000 sermons)**
   - Scrape `/spurgeon/sermon/[1..3561]/` with 2-second delay
   - User-Agent: `OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)`
   - Expected metadata per sermon: sermon number, title (from page heading), scripture text (from page)
   - Expect parsing artefacts — build a light cleaning step

2. **CCEL → Wesley XML**
   - Direct download: `ccel.org/ccel/wesley/sermons.xml`
   - 141 sermons, ThML structure (XML), includes titles and sermon numbers
   - 10-second delay between any subsequent requests to CCEL

3. **CCEL → Whitefield XML**
   - Check `ccel.org/ccel/whitefield/sermons.xml` — search results indexed this format
   - 59 selected sermons

4. **CCEL → Maclaren (multiple volumes)**
   - Check `ccel.org/ccel/maclaren/[book].xml` for each volume
   - If XML not publicly served, fall back to HTML scrape per chapter
   - 10-second delay

5. **Project Gutenberg → Maclaren (17+ volumes)**
   - Multiple volumes already on Gutenberg as clean HTML/text
   - No rate limit concerns — Project Gutenberg bulk downloads are permitted with appropriate User-Agent
   - Richest text corpus in this list after Spurgeon

6. **Wesley Center Online → Wesley (fallback or supplement)**
   - Text explicitly freely mirrorable per site notice
   - 141 sermons in HTML, individually indexed
   - Use if CCEL XML has structural issues

### Defer until OCR pipeline exists:

- Internet Archive Spurgeon DJVU scans (poor OCR quality)
- M'Cheyne from Internet Archive (only ~6 sermons in HTML elsewhere — this corpus is too small to prioritise)
- WJE Yale Online for Edwards (bulk access terms not confirmed — contact Yale Edwards Center before scraping)

### Contact required before proceeding:

- **Yale Edwards Center** (edwards.yale.edu): Email to ask about bulk data access for the WJE Online. They have 1,200+ Edwards sermons as transcripts but bulk download/API terms are unconfirmed. A data partnership enquiry is more appropriate than scraping.

---

## 6. Existing Datasets

No pre-built public-domain sermon text dataset was found on HuggingFace or GitHub. Relevant adjacent finds:

| Resource | What it is | Relevance |
|---|---|---|
| `bible-nlp/biblenlp-corpus` (HuggingFace) | Bible translations in 833 languages | Bible text only, no sermons |
| `branham-player/golden-dataset` (GitHub) | William Branham sermon metadata (names, dates, locations) | Metadata only, modern preacher, not public domain |
| `jcuenod/awesome-bible-data` (GitHub) | Curated list of Bible data sources | No sermon collections listed |
| CCEL ThML index (`ccel.org/index/format/ThML`) | Full list of CCEL texts with ThML/XML | Includes Wesley, Edwards, Whitefield, Maclaren — useful checklist for XML availability |
| Digital Puritan Press (`digitalpuritan.net`) | Edwards, Whitefield in various formats | PDF/ePub — not clean text |

**Conclusion:** This project would produce the first structured, machine-readable public-domain sermon corpus at meaningful scale. No prior work to build on.

---

## 7. robots.txt and ToS Summary

| Source | robots.txt | Key Rule | ToS/Notes |
|---|---|---|---|
| CCEL (ccel.org) | Present | All crawlers permitted; 10-second crawl delay; Meta external agent blocked | No explicit ToS prohibition found; academic/research use standard |
| The Kingdom Collective | None (404) | No restrictions stated | No ToS page found; content is public domain (Spurgeon pre-1928) |
| SpurgeonGems.org | Not confirmed (WebFetch unavailable) | Assume conservative: 10-second delay minimum | PDF content is public domain; bulk PDF download discouraged |
| Wesley Center Online (wesley.nnu.edu) | Not confirmed | Site explicitly states: "Text may be freely used for personal or scholarly purposes or mirrored on other web sites, provided this notice is left intact" | Mirroring explicitly permitted |
| archive.spurgeon.org | Not confirmed | Index only — no full text to harvest | N/A |
| Internet Archive | Permissive | Standard IA access; no crawl delay on text files | Bulk text download supported; DJVU OCR available directly |
| Project Gutenberg | Permissive | Standard PG access with appropriate User-Agent | Bulk downloads supported; mirror list available |
| edwards.yale.edu | Not confirmed | No bulk access terms found | Contact required before any scraping |
| mcheyne.info | Not confirmed | WordPress site; only 6 sermons available | Too small to matter |

---

*Research conducted 2026-03-27. No downloading performed. All findings from public search results and single-page navigation only.*
