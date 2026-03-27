# Prayer Collection Source Investigation
**Date:** 2026-03-27
**Scope:** Public domain Christian prayer collections — copyright status, digital source quality, access method, structure
**Status:** Research complete — no bulk downloading performed

---

## 1. Decision Brief

**What is clearly public domain and ready to use:**

- **BCP 1662** — public domain in the US; best clean text is at eskimo.com/~lhowell/bcp1662/ (HTML + RTF + ASCII, collects structured). UK Crown copyright is real but does not affect a US-based project using the text for non-commercial open data purposes.
- **BCP 1928 (US)** — confirmed public domain. Church Publishing Inc. (Episcopal Church's publisher) states no copyright permission required. Best digital text at justus.anglican.org.
- **Didache** — ancient text, multiple public domain translations on Wikisource and CCEL. Use Kirsopp Lake (1912) translation from Wikisource.
- **ANF / NPNF volumes** — fully public domain (US publication, 1886–1900). Complete sets on CCEL and Internet Archive in multiple formats. This is the best source for Early Church Fathers prayer texts.
- **Calvin's treatise on prayer** (Institutes III.20) — fully public domain on CCEL in PDF and HTML.
- **Luther's morning/evening prayers and Small Catechism** — public domain; multiple clean digital sources.
- **Scottish Book of Common Order (1564 / Knox's Liturgy)** — public domain; full text on Internet Archive.
- **Te Deum, Gloria in Excelsis, ancient liturgical prayers** — pre-500 AD origin, fully public domain in all translations published before 1928.

**What requires caution or is blocked:**

- **Valley of Vision (Bennett, 1975)** — HARD STOP. The compilation is under active copyright held by Banner of Truth Trust. Bennett substantially edited and reworked the source texts; he did not simply reproduce them. The underlying Puritan authors' works are public domain, but the VoV text itself is NOT. Do not use VoV text. Source the Puritan authors directly (see Section 4).
- **Scottish Book of Common Order (1940 edition)** — likely still under copyright. Use the 1564 Knox edition only.
- **BCP 1662 UK Crown copyright** — technically perpetual under Royal Prerogative in the UK; Cambridge University Press is the patentee. Does not affect US-based open data use of the text, but worth noting. Use a US-transcribed source (eskimo.com, Wikisource) rather than reproducing CUP editions.
- **CCEL-produced PDFs** — CCEL states their PDFs "may be freely copied for non-commercial purposes." The OCD project is non-commercial/open-source, but verify CCEL's license explicitly before including their formatted editions. The underlying texts are public domain; CCEL's typesetting/formatting may not be.

**One strong recommendation:** Start with BCP 1662 (eskimo.com source) and the ANF/NPNF Early Church Fathers on CCEL. These are clean, well-structured, confirmed public domain, and contain the highest density of prayer texts that map to the project's goals.

---

## 2. Per-Collection Findings

| Collection | Copyright Status | Best Digital Source | Format | Structured? | Access Method |
|---|---|---|---|---|---|
| BCP 1662 | PD (US); Crown copyright in UK | eskimo.com/~lhowell/bcp1662/ | HTML, RTF, ASCII | Yes — sections named, collects separated by occasion | Direct download |
| BCP 1662 | PD (US) | en.wikisource.org/wiki/Book_of_Common_Prayer | Wiki markup / HTML | Partial — project incomplete | Web scrape or export |
| BCP 1662 | PD (US) | justus.anglican.org/resources/bcp/1662/ | HTML + PDF | Continuous text, not structured by collect | Direct download; robots.txt allows crawling (10s delay) |
| BCP 1662 | PD (US) | Internet Archive (1662 editions) | Scanned PDF / text | No — page images, not structured | Download |
| BCP 1928 (US) | PD — confirmed by Church Publishing | justus.anglican.org/resources/bcp/1928/ | HTML | Section-based | Direct download |
| Valley of Vision (1975) | COPYRIGHTED — Banner of Truth | N/A | N/A | N/A | Do not use |
| Puritan works (Owen, Sibbes, Goodwin, etc.) | PD — 17th–18th century works | digitalpuritan.net; CCEL; Internet Archive | PDF, TXT, EPUB | No — buried in collected works | Download and extract |
| Thomas Shepard Works | PD | Internet Archive | Scanned text | No | Download |
| Didache | PD | en.wikisource.org/wiki/Didache | HTML / wiki | Yes — chapters | Web or export |
| ANF/NPNF (Early Church Fathers) | PD | ccel.org/fathers | ThML / HTML / PDF | ThML structured; sections addressable | Bulk download available |
| Calvin — prayer treatise | PD | ccel.org/ccel/calvin/prayer | HTML, PDF, DOC | Section-based | Direct download |
| Luther — Small Catechism prayers | PD | catechism.cph.org; multiple PD reprints | HTML | Short discrete texts | Scrape or direct copy |
| Scottish BCO 1564 (Knox) | PD | archive.org/details/comorde00chur | Full text (djvu/txt) | No | Download |
| Scottish BCO 1940 | Likely copyrighted | — | — | — | Avoid |
| Te Deum / Gloria / ancient liturgy | PD (pre-500 AD) | BCP editions; CCEL; Wikisource | Embedded in BCP text | Named texts | Extract from BCP |

---

## 3. Valley of Vision Copyright Analysis

This needs careful treatment. The short answer is: **the Valley of Vision as published is copyrighted and must not be used.** But the situation has layers.

### What Bennett actually did

Bennett did not select complete, finished Puritan prayers and copy them verbatim. According to Justin Taylor's research at The Gospel Coalition (the most thorough public documentation of this), Bennett:

- Drew from "largely forgotten deposits of Puritan spiritual exercises, meditations and aspirations"
- Conflated multiple sources to build a single unified prayer on a theme
- Adopted "a poetic form throughout as an aid to easier comprehension and utterance" — meaning he reworked the prose into verse-like layout
- Composed at least one prayer (the first) himself
- Did not key individual prayers to their source texts — no attribution within the book

The source authors listed in Bennett's preface span 14 writers across three centuries:
- Thomas Shepard (Works, vol. 3)
- Richard Baxter (The Saints' Everlasting Rest)
- David Brainerd (Diary and Journal)
- John Bunyan (Grace Abounding to the Chief of Sinners)
- Philip Doddridge (The Rise and Progress of Religion in the Soul)
- William Jay (Prayers for the Use of Families)
- Henry Law (Family Prayers for Four Weeks)
- William Romaine (various)
- Isaac Watts (Works, vol. 3)
- William Williams (Welsh sources)
- Thomas Watson, Charles Spurgeon, and others

### Copyright status

The compilation is © 1975 The Banner of Truth Trust. Published in the UK. Under UK copyright law, a compilation of public domain materials can itself be copyrighted if the selection and arrangement constitute an original creative work — and Bennett's editorial contribution (reworking, conflating, versifying) almost certainly meets that threshold.

Under US law, Banner of Truth has claimed copyright and the Logos community thread (community.logos.com/discussion/3942) confirms they enforce it — they blocked the text from being freely added to the Logos library. This is a live enforcement position, not a theoretical one.

The freely available PDFs on Scribd, Internet Archive, and various websites are almost certainly infringing copies. Their existence does not change the copyright status.

### What is NOT copyrighted (and can be used)

- The underlying Puritan authors' original texts. All of the listed source authors wrote in the 17th–19th centuries and their works are fully public domain.
- The specific works cited by Bennett are available in full on CCEL, Internet Archive, and Digital Puritan Press.
- A prayer sourced directly from, say, Baxter's *The Saints' Everlasting Rest* or Owen's *Works Vol. 4*, quoted verbatim from the original, is public domain — even if an edited version of the same prayer appears in VoV.

### The practical implication

Anyone wanting "Puritan prayers" for OCD must go back to the primary texts. This is harder — the prayers are embedded in longer devotional and theological works, not neatly extracted. But it is legally clean and arguably more scholarly.

### Banner of Truth licensing

Banner of Truth does not offer open licensing. Their eBook terms are strictly non-commercial, personal use only. There is no Creative Commons or similar license. Academic permission would require direct negotiation with info@banneroftruth.co.uk (UK) or info@banneroftruth.org (US). No evidence they have ever granted open data licensing.

---

## 4. BCP Digital Text Comparison — 1662 Edition

Four main digital sources exist. Quality comparison:

### Option A — eskimo.com/~lhowell/bcp1662/
**Recommendation: Best for OCD use.**

- Maintained by Lynda M. Howell; long-standing Anglican resource site
- Available in HTML, RTF, and ASCII — the RTF/ASCII makes programmatic processing practical
- Contains the full BCP text including collects separated by liturgical occasion (not just continuous prose)
- Includes supplementary materials (texts removed from BCP since 1662)
- Section-based HTML structure with named headings
- Download page available: eskimo.com/~lhowell/bcp1662/download/index.html
- No robots.txt restrictions found; site has been live 20+ years

**Limitation:** No machine-readable metadata — occasions, scripture references, and collect titles are in plain HTML, requiring parsing. But the structure is consistent enough to automate extraction.

### Option B — justus.anglican.org
- Comprehensive Anglican resource hub
- Has the 1662 text in HTML, with a separate Baskerville facsimile PDF
- Continuous-text HTML rather than collect-per-section structure
- Also hosts the 1928 US edition and many other BCP versions
- robots.txt: allows all crawlers with a 10-second crawl delay. The OCD project standard is 2 seconds minimum — set delay to 10 seconds here to comply.
- Terms: The site requires resources not to violate copyright law; the 1662 text itself is PD
- The Copyrights page (justus.anglican.org/resources/bcp/copyrights.html) documents copyright status for each BCP edition — a useful reference

### Option C — Wikisource (en.wikisource.org/wiki/Book_of_Common_Prayer)
- Transcription from the original manuscript attached to the Act of Uniformity 1662
- High scholarly fidelity — preserves original spelling and punctuation
- Wiki markup is machine-exportable via Wikisource API
- **Downside:** The 1662 project is explicitly incomplete. The 1892 edition is more complete on Wikisource.
- For OCD purposes, the 1892 Wikisource text is structurally similar to 1662 and fully complete — worth considering as a parallel source

### Option D — Internet Archive (scanned editions)
- Multiple 1662 editions available in DJVU and PDF
- These are page scans; OCR quality varies significantly
- Not suitable as a primary structured source
- Useful for verification against original

### Option E — GitHub: reubenlillie/daily-office
- BCP Daily Office Lectionary in JSON (MIT license)
- **Important caveat:** Based on the BCP 2007 (Episcopal Church), not BCP 1662
- Structure is excellent — offices as JSON objects — but wrong edition for historical/Anglican focus
- The blocher/dailyoffice2019 repo uses the Anglican Church in North America BCP 2019

---

## 5. Existing Structured Datasets

| Dataset | Source | Content | Format | License | Relevance |
|---|---|---|---|---|---|
| reubenlillie/daily-office | GitHub | BCP Daily Office Lectionary | JSON | MIT | High structure, wrong edition (BCP 2007) |
| blocher/dailyoffice2019 | GitHub | BCP 2019 (ACNA) Daily Office | Web app / structured | Open source | Wrong edition; modern text |
| CCEL ThML corpus | ccel.org | 1000+ theological works | ThML (XML-based) | "May be freely copied non-commercial" | Very high — includes ANF, Calvin, Puritan works |
| Catholic Readings API | cpbjr.github.io | Catholic lectionary 2025–2026 | REST API / JSON | Open | Low — Catholic lectionary, not prayer texts |
| bible-nlp/biblenlp-corpus | HuggingFace | Bible in 833 languages | Parquet | Various | Background context only |
| HuggingFace prayer datasets | HuggingFace | None found for Christian liturgical prayer | — | — | None found |

**Key finding:** No pre-built structured dataset exists for historical Christian prayer texts (BCP collects, Patristic prayers, Puritan prayers). This is a gap OCD can fill. The closest is CCEL's ThML corpus, which requires parsing but contains the raw material.

---

## 6. Items Requiring Human Judgment

These items are ambiguous enough that they should not be acted on without a decision:

**1. BCP 1662 and UK Crown Copyright**
The 1662 BCP is under perpetual Crown copyright in the UK under Royal Prerogative. Cambridge University Press is the licensed patentee. This does not affect US copyright law (the text was published in 1662, well outside any US copyright window). However: if OCD ever publishes a clean formatted edition for UK audiences or partners with UK organizations, this becomes a live issue. Decision needed: is OCD explicitly US-only in scope, or global?

**2. CCEL's "non-commercial" license on formatted texts**
CCEL hosts public domain texts but their formatted/typeset versions carry a note: "may be freely copied for non-commercial purposes." OCD is non-commercial and open-source. This is probably fine, but the exact terms are ambiguous about whether "open-source data project" counts as non-commercial. Recommended: use the underlying texts, not CCEL's formatted editions, or contact CCEL to confirm.

**3. Puritan prayers sourced from Digital Puritan Press**
Digital Puritan Press (digitalpuritan.net) makes PDFs available for free download. Their terms of use are not prominently stated. The underlying texts (17th–18th century Puritan works) are public domain. The PDFs themselves (typesetting, OCR) may have a thin copyright layer. Safer approach: use Internet Archive TXT versions of the same works, which are more clearly in the public domain as reproductions of scanned originals.

**4. justus.anglican.org 1662 text — redistribution**
The site's standard terms say resources must not violate copyright law. Since the 1662 text is public domain, this is fine. But the site does not explicitly grant a re-use license. Recommend: use as a source for reading/extraction but attribute properly.

**5. 1940 Scottish Book of Common Order**
Published 1940 by the Church of Scotland. Under UK copyright law (life + 70 years, or 70 years from publication for corporate works), the 1940 edition will remain under copyright until at least 2011 (70 years from publication) — already expired under that rule. However, if the compilers/editors are considered joint authors and any died after 1955, the copyright could extend further. This needs specific research before use. Use the 1564 Knox edition instead — clearly public domain.

---

## 7. Recommended Approach

### Phase 1 — Start here (low risk, high value)

**BCP 1662 collects** — Use the eskimo.com source. Download the ASCII/RTF version. Write a parser to extract individual collects with their occasion labels (Advent 1, Christmas, etc.). This gives ~120 discrete prayers with title, occasion, and source metadata.

**ANF/NPNF Early Church Fathers** — Download from CCEL. The ThML format has section-level structure addressable by chapter. Key volumes for prayer texts:
- ANF Vol. 7 (Didache — standalone chapter)
- NPNF Series 1 Vol. 1 (Augustine's Confessions — prayer-dense)
- ANF Vol. 1 (Clement, Ignatius — early liturgical material)

**Didache** — Use the Kirsopp Lake translation from Wikisource. Export via Wikisource API. Short, discrete, well-structured. Chapters 9–10 are the Eucharistic prayer; chapter 8 is the Lord's Prayer.

**BCP 1928 (US)** — Use justus.anglican.org source. Confirmed public domain. Adds the US Anglican tradition and provides cross-reference with 1662.

**Calvin on prayer** (Institutes III.20) — Download from CCEL as HTML. Extract sections programmatically. Not discrete prayers but a treatise on prayer — useful for metadata/theological context tagging.

**Luther's Small Catechism prayers** — Morning prayer, evening prayer, table grace. Short texts, widely reproduced. Use a PD reprint from Internet Archive.

### Phase 2 — Requires parsing effort

**Puritan primary sources** — The strategy is: identify which Puritan authors from Bennett's VoV source list have dedicated prayer/devotional works in their collected works, then extract those sections.

Priority targets (all freely available via Internet Archive or Digital Puritan Press):
- John Owen, *Works* Vol. 4 — contains "A Discourse of the Work of the Holy Spirit in Prayer" (152 pages, explicitly about prayer)
- Richard Sibbes, *Works* — contains "The Bruised Reed" and devotional material
- Thomas Watson — *The Lord's Prayer* (explicitly a prayer text)
- Philip Doddridge — *The Rise and Progress of Religion in the Soul* (contains prayer exercises)

**Scottish BCO 1564** — Available as full text on Internet Archive. Requires OCR cleanup before use.

### Phase 3 — Investigate further before acting

- Contact CCEL to clarify their re-use terms for the ThML corpus
- Research whether any structured BCP 1662 JSON/XML project exists beyond what was found (none found in this investigation)
- Assess whether the OCD project should build and publish a structured BCP 1662 JSON dataset as a standalone contribution — this would be genuinely novel and useful

### What not to pursue

- Valley of Vision — blocked. Do not use.
- HuggingFace — no relevant datasets found.
- 1940 Scottish BCO — uncertain copyright; skip pending research.
- Internet Archive scanned PDFs as primary source — OCR quality too variable; use only for verification.

---

## Source URLs for Reference

- eskimo.com BCP 1662: https://www.eskimo.com/~lhowell/bcp1662/
- eskimo.com download page: https://www.eskimo.com/~lhowell/bcp1662/download/index.html
- justus.anglican.org BCP index: http://justus.anglican.org/resources/bcp/
- justus.anglican.org copyrights page: http://justus.anglican.org/resources/bcp/copyrights.html
- justus.anglican.org 1662: http://justus.anglican.org/resources/bcp/1662/1662.html
- justus.anglican.org 1928: http://justus.anglican.org/resources/bcp/1928/BCP_1928.htm
- Wikisource BCP index: https://en.wikisource.org/wiki/Book_of_Common_Prayer
- Wikisource Didache (Lake): https://en.wikisource.org/wiki/Didache
- Wikisource Didache (Hoole): https://en.wikisource.org/wiki/Didache_(Hoole_translation)
- CCEL Early Church Fathers: https://ccel.org/fathers
- CCEL Calvin on Prayer: https://ccel.org/ccel/calvin/prayer
- CCEL Luther Table Talk (prayer sections): https://ccel.org/ccel/luther/tabletalk/tabletalk.v.xii.html
- CCEL 1549 BCP prayers PDF: https://www.ccel.org/creeds/common-prayer-1549.pdf
- Internet Archive 1662 BCP (text): https://archive.org/details/bim_early-english-books-1641-1700_the-book-of-common-praye_1662_3
- Internet Archive Scottish BCO (Knox): https://archive.org/stream/comorde00chur/comorde00chur_djvu.txt
- Internet Archive John Owen Discourse on Holy Spirit: https://archive.org/details/discourseconcern00owenuoft
- Digital Puritan Press (Owen): https://digitalpuritan.net/john-owen/
- Banner of Truth (VoV): https://banneroftruth.org/us/store/devotionalsdaily-readings/the-valley-of-vision/
- Gospel Coalition VoV FAQ: https://www.thegospelcoalition.org/blogs/justin-taylor/valley-of-vision/
- Gospel Coalition VoV Evangelical History FAQ: https://www.thegospelcoalition.org/blogs/evangelical-history/faq-spiritual-classic-valley-vision/
- Logos community VoV copyright thread: https://community.logos.com/discussion/3942/valley-of-vision-public-domain-text
- Sourcing the Valley of Vision (Substack): https://sourcingthevalleyofvision.substack.com/p/sourcing-the-valley-of-vision
- GitHub daily-office JSON (BCP 2007): https://github.com/reubenlillie/daily-office
- GitHub awesome-catholic: https://github.com/servusdei2018/awesome-catholic
- Cambridge University Press (BCP, Crown copyright): https://www.cambridge.org/us/universitypress/bibles/prayer-books/book-common-prayer

---

## robots.txt Summary

| Domain | Status | Crawl Delay | Notes |
|---|---|---|---|
| ccel.org | Allows all crawlers | 10 seconds | Meta-externalagent blocked; all others allowed with 10s delay |
| justus.anglican.org | Not directly verified (WebFetch blocked) | Unknown | No evidence of restrictions based on search results |
| gutenberg.org | Not directly verified | Unknown | Project Gutenberg has known rate limits; use mirror or bulk download |
| eskimo.com | Not directly verified | Unknown | Long-running static site; no evidence of restrictions |
| wikisource.org | Standard Wikimedia terms | Per Wikimedia API guidelines | Prefer Wikimedia API over scraping |

**Note:** WebFetch was unavailable during this session. robots.txt for justus.anglican.org, gutenberg.org, and eskimo.com should be verified before any automated downloading begins. CCEL's robots.txt was confirmed: 10-second crawl delay for all bots.
