# Hymn Lyric Sources — Investigation Report

**Date:** 2026-03-27
**Scope:** Public domain Christian hymn lyrics with metadata, targeting pre-1928 corpus
**Status:** Research only — no bulk downloading performed

---

## 1. Decision Brief

**Is there an existing structured dataset?** No. There is no CC0/public domain hymn lyric corpus in JSON/CSV/database form ready to import. The closest thing (josmithua/song-data on GitHub) covers a narrow denominational selection, not a comprehensive historical corpus.

**The best path forward — in priority order:**

1. **Contact Hymnary.org directly** and request research data access. They have offered to send CSV dumps on request, they are NEH-funded and explicitly serve scholars, and their database is the most comprehensive source in existence (1M+ hymn instances, 7,144 hymnals). This is the highest-leverage first move.
2. **Use Wikisource database dumps** for key hymnals already transcribed there (Olney Hymns, Wesley's 1780 Collection, Watts' Psalms and Hymns). These are CC0 and machine-readable via the MediaWiki API or full XML dumps.
3. **Project Gutenberg** for Watts and a handful of others — clean plain text but requiring per-hymn parsing.
4. **Internet Archive** for OCR scans of pre-1928 hymnals as a long-tail source — quality varies, requires significant post-processing.
5. **Hymntime.com (Cyber Hymnal)** — 16,700+ hymns, bulk of content is public domain, but no API and scraping policy is unknown. Contact before touching.

**One recommendation:** Email Hymnary.org before building any scraping infrastructure. Their stated openness to research requests (NEH funding, CSV-on-request) and the scale of their database means a single email could unlock the whole corpus without a single scrape.

---

## 2. Per-Source Findings Table

| Source | Content scope | Format | License | API / bulk access? | robots.txt | ToS status |
|---|---|---|---|---|---|---|
| **Hymnary.org** | 1M+ hymn instances; 7,144 hymnals; 1640–present; full metadata | Web + CSV export | Varies by text (many PD) | Scripture JSON API; CSV export (5,000-line limit); full dump via request | Not confirmed — fetch blocked during research | No explicit scraping prohibition found; research use likely permitted — confirm via contact |
| **Hymntime.com (Cyber Hymnal)** | 16,700+ hymns; lyrics, MIDI, sheet music, bios | HTML per-hymn pages | Mostly PD; copyright pages marked | None known | Not confirmed | Not confirmed — contact required before any scraping |
| **Wikisource** | Key hymnals transcribed (Olney Hymns, Wesley 1780, others) | MediaWiki XML; plain text; EPUB | CC0 (public domain) | Full XML database dumps available free; MediaWiki API | Permissive (standard Wikimedia) | Open — dumps are explicitly provided for reuse |
| **Project Gutenberg** | Watts Hymns and Spiritual Songs; Toplady (Rock of Ages); hymn history books | Plain text, HTML, EPUB | Public domain | Download per-book; no bulk API | Permissive | Permits download for personal/research use; no bulk robot scraping of site |
| **Internet Archive** | Hundreds of pre-1928 hymnal scans | Scanned PDF + OCR text | Public domain scans | Bulk download possible via S3-style API | Permissive | Open for research download |
| **CCEL** | Hymn tune archive (MIDI, sheet music) — NOT lyrics | MIDI, PDF, Finale files | PD music files | Not applicable (no lyrics) | Unknown | Unknown |
| **CCLI SongSelect** | 230,000 hymns/songs; PD subset searchable | Web only | Varies; PD songs free to view | API programme retired — no new partners | Unknown | Requires account; not designed for bulk extraction |
| **pdhymns.com** | PD hymn sheet music and PowerPoint; some PDF lyrics | PDF, PPT | PD claimed | None | Unknown | Strict copyright infringement policy; no bulk access |
| **hymnstogod.org** | PD hymn sheet music + lyrics (A–Z indexed); also CC and conditional copyright sections | PDF, PPT, KEY | PD / CC | None | Unknown | Permissive for worship use; research use unclear |
| **hymnal.net** | Contemporary worship songs; limited historical coverage | Web | Mixed copyright | Unofficial API exists (ricefield/hymnalAPI on GitHub) | Unknown | Unknown — likely restricts bulk access |
| **pdinfo.com/pd-music-genres/pd-hymns.php** | PD hymn identification list | Web (HTML list) | N/A (reference list) | None | Unknown | Reference only — not a lyrics source |

---

## 3. Hymnary.org Deep-Dive

### What they have
- Over **1 million hymn instances** (a hymn appearing in a specific hymnal = one instance)
- **7,144 hymnals** indexed, oldest from 1640
- Incorporates the **Dictionary of North American Hymnology** — almost 5,000 hymnals, 1M+ first lines
- Full metadata per text: title, author, year, metre, tune name, scripture references, stanza count, first line, hymnal appearances
- Funded by the **National Endowment for the Humanities** and the **Hymn Society in the United States and Canada** — explicitly a scholarly resource

### What is accessible without contact
- **Scripture JSON API** at `hymnary.org/api/scripture` — returns up to 100 hymns per scripture reference range
- **Search-to-CSV**: append `&export=csv` to any search URL — returns results as CSV
- **Per-hymnal CSV export**: via the index pages of individual hymnals, scroll to "Export as CSV"
- **Full DB CSV dump**: available under the Explore section, but **limited to 5,000 lines** and does not give a complete hymnal

### What requires direct contact
- Full database dumps (texts, tunes, hymnals, people, authority records) — Hymnary has offered to send these on request via the "Contact Us" link
- Any academic data access agreement
- robots.txt content and formal scraping permissions

### Key gaps confirmed
- The CSV limit of 5,000 lines is a hard ceiling for automated export without contact
- Full hymn lyrics text (stanza-by-stanza) — unclear how much is in the database vs. indexed only. Some texts are full PD lyrics; others may be first-line index only
- No confirmed academic data partnership programme was found — contact needed to establish one

### Recommended action
Email Hymnary.org via their Contact Us page identifying OCD as an open-source data project, citing their NEH mission alignment, and requesting: (a) full CSV dump of PD texts with metadata, (b) clarification on what fields are in the full dump (does it include stanza text?), (c) robots.txt and scraping policy. Reference their existing research community role.

---

## 4. Cyberhymnal / Hymntime Status

### History
The Cyber Hymnal was founded in 1996 by Dick Adams. The original domain (cyberhymnal.org) was lost in a domain dispute. The site split:
- **The legitimate continuation is at hymntime.com/tch** — this is Dick Adams' authorised site
- **cyberhymnal.org and nethymnal.org** — separate, unaffiliated projects; not recommended as sources

### Current state of hymntime.com/tch
- Still online as of 2026
- Contains **16,700+ hymns and gospel songs** across many denominations and languages
- Includes lyrics, sheet music (MIDI), audio, author bios, and history
- The bulk of content is public domain; copyrighted pages are clearly marked
- Hymnary.org indexes it as a hymnal (code: CYBER)

### Bulk access
- No API found
- No structured data export found
- Entire site is HTML pages, one per hymn
- robots.txt not confirmed — must check `hymntime.com/robots.txt` before any automated access
- ToS not confirmed

### Mirrors / archive
- Hymnary.org has indexed the Cyber Hymnal's content as a hymnal reference
- Internet Archive has snapshots of hymntime.com content
- No standalone data mirror found

### Verdict
Do not scrape without: (1) checking robots.txt, (2) reviewing their ToS, (3) attempting contact. Given the volume (16,700 hymns) and clear PD marking, it may be worth contacting Dick Adams or the site owner directly about data access for an open-source project.

---

## 5. Existing Datasets Found

### On GitHub

| Repo | Content | Format | License | Notes |
|---|---|---|---|---|
| **josmithua/song-data** | Hymn Book JSON Data — appears to be a narrow denominational selection (BHB = British Hymn Book?) | JSON | Not clearly stated | Small scope; not a comprehensive corpus |
| **Lyrics/lyrics-database** | Open Lyrics Database — general songs, not hymn-specific | Various | Mixed | Not hymn-focused |
| **ricefield/hymnalAPI** | Simple API wrapper for hymnal.net | JavaScript | MIT | Contemporary worship; not PD historical hymns |
| **samuelpearce/christianhymns-cclisongnumber** | Mapping of Christian Hymns book to CCLI numbers | Data mapping | Not stated | Useful for PD identification; not lyrics |
| **pnlong/PDMX** | Large-scale public domain MusicXML dataset for symbolic music | MusicXML | PD | Music notation only — no lyrics |

**Summary:** No comprehensive PD hymn lyric dataset exists on GitHub. The closest is josmithua/song-data but scope is narrow and licensing unclear.

### On HuggingFace

No hymn-specific lyric dataset found. Existing datasets (brunokreiner/genius-lyrics, asigalov61/Lyrics-MIDI-Dataset) are general music — not Christian hymnody.

### OpenLyrics format (relevant for output)
OpenLyrics (openlyrics.org) is a free, open XML standard for Christian worship songs, used by OpenLP and other presentation software. If OCD builds a hymn corpus, publishing in OpenLyrics XML alongside JSON/CSV would maximise compatibility with existing church software.

---

## 6. Recommended Approach

### Phase 1 — Contact before building (Week 1)
1. **Email Hymnary.org** requesting research data access (see Deep-Dive above for what to ask). This one action could unlock the whole corpus.
2. **Email hymntime.com** (Cyber Hymnal) requesting permission and/or data export for a PD open-data project.
3. Check `hymnary.org/robots.txt` and `hymntime.com/robots.txt` directly.

### Phase 2 — High-quality structured sources (no scraping required)
4. **Wikisource XML dumps** — download from `dumps.wikimedia.org/enwikisource` and extract:
   - Olney Hymns (1840) — Newton and Cowper; all PD
   - A Collection of Hymns for the Use of the People Called Methodists (Wesley 1780) — PD
   - Scottish Psalter — PD
   - Any other hymnals confirmed present
5. **Project Gutenberg** — download plain text for:
   - Watts, *Hymns and Spiritual Songs* (PG #13341)
   - Toplady, *Rock of Ages* (PG #26874)
   - Parse stanzas from plain text with a script

### Phase 3 — Hymnary CSV data (if contact succeeds)
6. If Hymnary provides a full dump — ingest texts, tunes, and metadata. Cross-reference against PD criteria (author death >70 years or publication pre-1928).
7. If only 5,000-line export is available — use `&export=csv` exports against filtered searches (e.g., by author date range) to build the corpus incrementally.

### Phase 4 — Internet Archive OCR (long tail, lower quality)
8. Target hymnals with good OCR scores on archive.org. Priority candidates:
   - *Hymns Ancient and Modern* (1861) — full text available
   - Denominational hymnals pre-1900
   - Use archive.org's plain text OCR downloads (available per-item as `.txt`)
9. OCR cleanup will be required — budget significant time per hymnal.

### Phase 5 — Manual curation for key authors
10. For Watts, Wesley, Newton, Cowper, Toplady, Crosby, Havergal, Bonar, Montgomery, Heber, Keble — verify text against Wikisource and Project Gutenberg first. These authors' texts are extensively transcribed.

---

## 7. Copyright Complexity Notes

### The three-component rule
Each hymn has three independently copyrightable components: **text (lyrics)**, **tune (music)**, and **arrangement**. For OCD purposes (lyrics only), the text component is what matters. A pre-1928 text paired with a post-1928 tune is fine — the text itself is PD.

**Current US threshold (as of 2026):** Works published in 1930 or earlier are public domain. This extends the pre-1928 rule slightly — check the current year's threshold when building automated PD filters.

### Tune name vs. tune copyright
Tune names (e.g., "LOBE DEN HERREN", "TERRA BEATA") are identifiers, not protected. Using a tune name in metadata is not a copyright issue. The underlying melodic composition may be PD or protected — irrelevant for a lyrics-only dataset.

### Translation copyright
A modern English translation of a Latin hymn (e.g., a 1950 translation of an 8th-century Latin text) is copyrighted as a new work, even though the source text is ancient. For OCD: use pre-1928 translations only, or originals in their source language. Notable examples:
- "O Sacred Head Now Wounded" — Latin/German original ancient; many popular translations are 19th century (PD) or 20th century (copyrighted)
- Check translation date, not just original authorship

### Author death date vs. publication date
For determining PD status: in the US, **publication date before 1928** (currently 1930) is the controlling factor — not author death date. The 70-years-after-death rule applies in the UK/EU but not the US. OCD should use US publication date as the primary criterion, with author death date as a secondary cross-check.

### Hymnal editorial additions
A pre-1928 hymnal may contain editor's notes, arrangement descriptions, or minor textual alterations that a publisher added and copyrighted. The underlying hymn text is PD; the editorial apparatus may not be. When extracting from scans, take the poem text only.

### CCLI's PD list as a verification tool
CCLI SongSelect maintains a searchable public domain catalogue at `songselect.ccli.com/search/results?list=catalognames_Public+Domain`. While the API is closed, this is a useful manual cross-reference for verifying PD status of specific hymns before inclusion.

---

## Sources Consulted

- [Hymnary.org — Download hymns/hymnals? (forum)](https://hymnary.org/node/31691)
- [Hymnary.org — Download CSV format? (forum)](https://hymnary.org/node/42784)
- [Hymnary.org — Wikipedia](https://en.wikipedia.org/wiki/Hymnary.org)
- [Hymnary.org — Scripture JSON API](https://hymnary.org/api/scripture)
- [Hymnary.org — Public Domain node](https://hymnary.org/node/42069)
- [The Cyber Hymnal — hymntime.com](http://hymntime.com/tch/)
- [HymnWiki — Cyber Hymnal history](https://www.hymnwiki.org/The_Cyber_Hymnal%E2%84%A2)
- [Hymnary.org — Cyber Hymnal as hymnal](https://hymnary.org/hymnal/CYBER)
- [Project Gutenberg — Watts, Hymns and Spiritual Songs](https://www.gutenberg.org/ebooks/13341)
- [Project Gutenberg — Toplady, Rock of Ages](https://www.gutenberg.org/ebooks/26874)
- [Internet Archive — Hymns Ancient and Modern (OCR text)](https://archive.org/stream/hymnsancientand01unkngoog/hymnsancientand01unkngoog_djvu.txt)
- [Internet Archive — Olney Hymns (Newton)](https://archive.org/details/olneyhymnsinth00newt)
- [Internet Archive — Wesley's Hymns and Sacred Poems](https://archive.org/details/hymnsandsacredpo00wesliala)
- [Wikisource — Olney Hymns (1840)](https://en.wikisource.org/wiki/Olney_Hymns_(1840))
- [Wikisource — Wesley's Collection of Hymns for Methodists](https://en.wikisource.org/wiki/A_Collection_of_Hymns,_for_the_Use_of_the_People_Called_Methodists)
- [Wikisource — Database dump](https://en.wikisource.org/wiki/Wikisource:Database_dump)
- [CCEL — Hymn tune archive](https://www.ccel.org/cceh/index.htm)
- [CCEL — Wesley Collection of Hymns](https://www.ccel.org/ccel/wesley/hymn.html)
- [GitHub — josmithua/song-data](https://github.com/josmithua/song-data)
- [GitHub — openlyrics/openlyrics](https://github.com/openlyrics/openlyrics/)
- [OpenLyrics documentation](https://docs.openlyrics.org/)
- [CCLI SongSelect — Public Domain songs](https://songselect.ccli.com/search/results?list=catalognames_Public+Domain)
- [CCLI SongSelect Partner API (retired)](https://documenter.getpostman.com/view/604633/TzseGkmA)
- [hymnstogod.org — Complete PD hymn list](https://www.hymnstogod.org/Hymns-PD/ZZ-CompletePDHymnList.html)
- [pdhymns.com](https://www.pdhymns.com/)
- [UMC — How to identify public domain hymns](https://www.umc.org/en/content/ask-the-umc-how-can-i-identify-public-domain-hymns)
- [One License — Understanding public domain](https://news.onelicense.net/2023/09/21/understanding-public-domain/)
- [Hymnary.org — Calvin Digital Commons academic paper](https://digitalcommons.calvin.edu/cgi/viewcontent.cgi?article=1241&context=uni-cicw-symposium)
