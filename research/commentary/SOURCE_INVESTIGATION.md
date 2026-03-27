# Commentary Source Investigation
**Date:** 2026-03-27
**Scope:** Public domain Bible commentary sources for Open Christian Data project
**Status:** Research complete — drives all future download decisions

---

## 1. Decision Brief

- **Best overall source for structured data:** HelloAO Bible API — 6 commentaries in clean JSON with PDM 1.0 license and an explicit `available_commentaries.json` endpoint. Rate-limited to 15 req/30s; their own docs say "do not use to download an entire commentary — get data from source." The source repo is `github.com/HelloAOLab/bible-api` (MIT license); self-hosting via `@helloao/cli` is the correct bulk-access path.
- **Best source for Barnes, Calvin, Wesley, Bengel, Spurgeon, Lange:** CrossWire SWORD modules — bulk ZIP download, Public Domain, no ToS prohibition found. Barnes NT + Calvin (47 books) + Wesley confirmed; Bengel, Spurgeon, Lange not present (must go elsewhere). Barnes OT is CCEL/Internet Archive only.
- **Best source for unstructured full-text (Barnes OT, Poole, Lange, Bengel):** Internet Archive — multiple formats including DjVu/plain text, true public domain scans. OCR quality is variable (Tesseract 5). Rate-limit your requests; contact IA for large projects.
- **Key gap:** Matthew Poole exists only as 17th-century scans (Internet Archive 1685 early English books digitisation) or HTML on StudyLight/grace-ebooks. No clean structured text found. Bengel's Gnomon is NT-only in English (the original Latin covers more). Lange is 26 volumes — Internet Archive has them but OCR quality unknown per volume.
- **Recommended download order:** (1) HelloAO via CLI self-host, (2) CrossWire SWORD ZIPs for Barnes NT + Calvin + Wesley, (3) CCEL .txt download for Barnes NT, (4) Internet Archive text files for Spurgeon/Lange/Bengel, (5) sacred-texts.com for Wesley and Barnes as structured HTML fallback, (6) Poole from grace-ebooks or Internet Archive 1685 scan — flag for human quality review.

---

## 2. Per-Source Findings Table

| Source | Content | Format | License | Access Method | Quality | robots.txt | ToS / Bulk Download |
|---|---|---|---|---|---|---|---|
| **HelloAO Bible API** (bible.helloao.org) | 6 commentaries: Adam Clarke (57 books), JFB (66), Gill (66), Keil-Delitzsch (39 OT), Matthew Henry (65), Tyndale Open Study Notes (69) | JSON, verse-keyed | PDM 1.0 (public domain) for PD commentaries; CC BY-SA 4.0 for Tyndale | REST API (`/api/c/{id}/{book}/{chapter}.json`); CLI tool for self-hosting | Clean, structured, machine-readable | Redirects robots.txt to docs homepage — no explicit disallow found | Rate limited 15 req/30s per IP. Explicit instruction: "do not use API to download an entire commentary — use CLI to self-host instead." MIT-licensed source code on GitHub. |
| **CCEL** (ccel.org) | 231+ commentaries total; confirmed: Barnes NT (11 vols), Calvin Complete (45+ vols), Matthew Henry (6 vols), Gill (partial), Spurgeon "Commenting and Commentaries" (not Treasury). Barnes OT volumes confirmed available. | ThML/XML (source), plain .txt and HTML (derived) | Most texts PD in USA; CCEL claims copyright on formatting/editions. Non-commercial use permitted; contact required for republication. | Per-work .txt download URL pattern: `/ccel/b/{author}/{work}/cache/{work}.txt`. No bulk API. ThML XML available per-work. | High — scholarly digitisations, not OCR-dependent for most works | crawl-delay: 10 for all agents | "Used for personal, educational, or non-profit purposes. Contact us for permission to republish or use commercially." No explicit prohibition on programmatic per-work download. |
| **CrossWire SWORD** (crosswire.org) | English commentaries confirmed: Abbott (NT), Barnes (NT only, 5.82 MB installed), Burkitt (NT), CalvinCommentaries (47 books — see coverage below), Clarke, Darby Notes, Family Bible Notes, Geneva Notes, Lightfoot, Luther (selected), NETnotesfree, People's NT, RWP, Scofield (1917), TSK, **Wesley** (whole Bible). No Spurgeon Treasury, Bengel, Poole, or Lange modules found. | SWORD binary format (ZCom driver). ZIP download per module. Python: `pysword` library reads all known SWORD formats. | Public Domain (confirmed for Barnes and Calvin modules). | Direct ZIP download per module from `/sword/servlet/SwordMod.Verify?modName={name}&pkgType=raw`. No API key required. | Clean — sourced from CCEL and similar scholarly sources. | No robots.txt blocking found | No bulk download prohibition found. Install Manager is recommended but manual ZIP download is explicitly supported. |
| **Project Gutenberg** (gutenberg.org) | Barnes NT Notes: Revelation confirmed (ebook 55228). Likely only select volumes — not a complete Barnes set. Wesley Notes: not found in search results. Calvin: not found. | HTML, plain text, EPUB, Kindle | Public Domain | Direct file download via gutenberg.org/files/{id}/. Bulk mirrors available (see gutenberg.org/policy/robot_access.html) | Clean typed text — not OCR | crawl-delay: 10 for most bots; bulk mirrors recommended over direct scraping | Strongly prefers use of official mirrors for bulk access. Direct scraping is tolerated with crawl-delay compliance but mirrors are the stated preference. |
| **Internet Archive** (archive.org) | Barnes NT and OT (multiple vols confirmed), Calvin complete commentaries (45-vol set confirmed), Spurgeon Treasury of David (multiple editions, including combined single-volume), Bengel's Gnomon NT (multiple editions), Lange's Commentary 26 vols (complete set confirmed at `CommentaryOnTheHolyScripturesCriticalDoctrinalAndHomilectical.Lange`), Matthew Poole 1685 scan | DjVu, PDF, EPUB (Full Text), plain text (`_djvu.txt`). OCR processed by Tesseract 5 or ABBYY. | Public Domain Mark 1.0 on pre-1928 texts | Search API + per-item download. `archive.org/download/{identifier}/{file}`. Bulk: contact IA directly for large projects. | Variable. Google-digitised volumes (e.g. Calvin) tend to be cleaner. Post-IA digitisation varies. Gutter/margin clipping noted for some Barnes volumes. | Does not use robots.txt to restrict crawlers. Internal rate limiting via Cloudflare. Recommends "start slowly and ramp up." | No ToS prohibition on bulk download of PD texts. Rate limiting enforced technically. For large projects, contact IA. |
| **Sacred-Texts** (sacred-texts.com) | Barnes NT and OT Notes (complete, verse-indexed HTML), Wesley's Explanatory Notes on the Whole Bible (complete) | HTML, one page per chapter/section | PD texts permitted for non-commercial copying with attribution. ISTA-produced texts need attribution retained. | Page-by-page HTML scraping only — no bulk download or API. | Clean typed text — high quality, human-proofread | Allows general crawling; no broad disallow found | **ToS Section 10:** "web robots permitted only to: (1) create/update a search engine index, OR (2) download one copy of one text per day." Bulk scraping of entire site is explicitly prohibited. Single-book scraping at slow rate appears within ToS. |
| **StudyLight** (studylight.org) | 144+ commentaries including Poole, Barnes, Wesley, Calvin, Clarke, Gill, Henry, Bengel, Lange (all in HTML, verse-by-verse) | HTML only — no API, no bulk download | Site claims copyright on all materials; underlying PD texts are PD but StudyLight's formatting/layout is protected | HTML scraping only | Clean presentation; text quality good | robots.txt: general crawl allowed (Disallow: /cgi-bin/, /ajax/, etc.); blocks specific SEO bots (Ahrefs, Semrush, GPTBot, etc.). Custom User-Agent not blocked. | Rights and Permissions page: "All materials on StudyLight.org are protected by copyright. Permission required to reuse content. Submit request by email." — **Stop: bulk scraping conflicts with ToS. Flag for human decision.** |
| **HistoricalChristianFaith/Commentaries-Database** (GitHub) | Collection of commentaries organised by author/verse from historical Christianity. Covers many Church Fathers and Reformers. Specific coverage of target commentaries unconfirmed — repo requires direct inspection. | TOML files, one per verse/passage, containing multiple commentary snippets | Data sourced from PD works; TOML format is CC-compatible. `source_url` field links to PD originals. | `git clone` — full bulk access | Structured and clean by design | N/A (GitHub) | MIT/open — designed for bulk use |
| **BibleHub** (biblehub.com) | 30+ commentaries per verse including Poole, Barnes, Wesley, Calvin, Bengel, Lange (in HTML snippets) | HTML only — verse-level snippets, not full chapters | PD underlying texts; BibleHub's compilation/formatting under their copyright | HTML scraping only — no API | Good for spot-checking; but snippets may be truncated | Not investigated — excluded from priority list | Unknown; not a priority given other sources |

---

## 3. Per-Commentary Recommendation

### Barnes' Notes (1832–1851)

- **NT:** CrossWire SWORD (module `Barnes`, Public Domain, ZIP download, 5.82 MB installed) — **primary**. Clean and structured. NT only.
- **OT:** Internet Archive (`archive.org/details/barnesnotesonnew0000unse` and related OT volumes). Download as plain text (`_djvu.txt`). Quality note: some volumes have gutter clipping.
- **Fallback:** CCEL `.txt` download for NT (`/ccel/b/barnes/ntnotes/cache/ntnotes.txt`) — single combined file, simpler to process.
- **Do not use:** Sacred-texts (ToS limits to 1 file/day), StudyLight (copyright claim on format).
- **Gap:** OT is not one combined file — expect 20+ individual volumes on Internet Archive. Needs assembly script.

### Wesley's Notes (1755–1765)

- **Primary:** CrossWire SWORD module `Wesley` — "John Wesley's Notes on the Bible," whole Bible, Public Domain, ZIP download.
- **Fallback:** Sacred-texts (`sacred-texts.com/bib/cmt/wesley/index.htm`) — complete, clean HTML, but ToS limits to one file/day.
- **Quality note:** SWORD module is the cleanest bulk access path. Confirm coverage (OT + NT) before relying on it.

### Calvin's Commentaries (1540s–1564)

- **Primary:** CrossWire SWORD module `CalvinCommentaries` (20.62 MB installed, version 1.1 dated 2022-08-01). Public Domain. Sourced from CCEL, converted by Luke Plant.
- **Books confirmed:** Genesis, Exodus, Leviticus, Numbers, Deuteronomy, Joshua, Psalms, Isaiah, Jeremiah, Lamentations, Ezekiel, Daniel, Hosea–Malachi (all 12 minor prophets), Matthew, Mark, Luke, John, Romans, 1–2 Corinthians, Galatians, Ephesians, Philippians, Colossians, 1–2 Thessalonians, 1–2 Timothy, Titus, Philemon, Hebrews, James, 1–2 Peter, 1 John, Jude.
- **Missing:** Ruth, Judges, Samuel, Kings, Chronicles, Ezra, Nehemiah, Esther, Job, Proverbs, Ecclesiastes, Song of Solomon, Revelation, Acts (these were not in Calvin's completed commentary output — this is a source gap, not a data gap).
- **Also available:** CCEL Calvin complete commentaries (`ccel.org/ccel/calvin/commentaries.html`) with `.txt` download — same underlying text, different format.

### Spurgeon's Treasury of David (1869–1885)

- **Coverage:** Psalms only — this is by design, not a gap.
- **Primary:** Internet Archive — multiple clean editions. Best option: `archive.org/details/ch-spurgeon-the-treasury-of-david-in-one-volume` (single combined volume, PD Mark 1.0). Also individual original volumes digitised by Google available.
- **Secondary:** `archive.spurgeon.org/treasury/treasury.php` — web HTML, one Psalm at a time, clean text put online by Phil Johnson. Useful for spot-checking.
- **Quality risk:** The one-volume Internet Archive item was digitised by a volunteer (Liz-Ridolfo) — verify OCR quality before committing. Original Google-digitised volumes may be cleaner.
- **Note:** This is verse-level annotation of Psalms 1–150 only. Plan accordingly — it will not produce full-Bible coverage.

### Matthew Poole's Commentary (1685)

- **Status: Hard gap.** No clean structured text source found.
- **Internet Archive:** 1685 original English scan available (`archive.org/details/bim_early-english-books-1641-1700_annotations-upon-the-hol_poole-matthew_1685`). Early modern English, OCR quality on 17th-century type will be poor. Not machine-readable without significant cleaning.
- **grace-ebooks.com:** Has Annotations organised by Bible book with ZIP downloads. Format unknown (likely PDF). Requires human inspection.
- **Monergism.com:** 66 individual PDF files (one per Bible book). PDF → text extraction possible but lossy.
- **StudyLight:** HTML version available but bulk access requires permission (see ToS).
- **BibleHub:** Has Poole snippets per verse — HTML scraping only.
- **Recommendation:** This is a human-action item. Inspect grace-ebooks ZIP files first — if they contain clean text, this becomes tractable. Otherwise treat as a low-priority, high-effort source.

### Bengel's Gnomon (1742)

- **Coverage:** New Testament only (English translation). The original Latin covers NT only as well.
- **Primary:** Internet Archive — multiple editions. Recommended: `archive.org/details/cu31924092350523` (Google-digitised Cornell copy). Plain text (`_djvu.txt`) available. 5-volume set.
- **Quality:** Google-digitised tends to be cleaner than post-IA scanning. Verify before processing.
- **No SWORD module found.** No CCEL entry found. Internet Archive is the only viable bulk source.
- **Note:** Bengel is NT-only. Do not expect OT coverage — it does not exist in English.

### Lange's Commentary (1857–1876)

- **Primary:** Internet Archive — complete 26-volume set confirmed at `archive.org/details/CommentaryOnTheHolyScripturesCriticalDoctrinalAndHomilectical.Lange`. Full text (`_djvu.txt`) available. 1.3 GB collection.
- **Individual volumes:** Also available as separate items on IA for both OT and NT sections.
- **Quality:** Mix of Google-digitised and other sources. Quality will vary by volume. Must spot-check before bulk processing.
- **Note:** This is the largest and most complex acquisition. 26 volumes, translated from German by Schaff et al., 1865–1899. Expect significant OCR cleaning work.

---

## 4. Gaps and Risks

| Item | Gap / Risk | Action Required |
|---|---|---|
| **HelloAO rate limit** | API says "do not download entire commentary via API." Must use CLI to self-host. | Human: set up `@helloao/cli` to generate static JSON files locally. This is the correct path. |
| **Barnes OT assembly** | 20+ separate Internet Archive volumes, not a single combined file | Script to fetch and combine — confirm volume list before building |
| **Matthew Poole clean text** | No confirmed clean text source found | Human: inspect grace-ebooks.com ZIPs. If PDF, test PDF-to-text extraction quality on 1–2 books before committing. |
| **CCEL copyright on editions** | CCEL claims copyright on its formatting/editions even though underlying texts are PD. "Contact us for commercial use." For non-commercial OCD purposes, per-work download appears permitted, but redistribution of CCEL-formatted text may require notification. | Prefer using CCEL as a source of record to verify data, but use CrossWire or Internet Archive as primary for redistribution. |
| **Sacred-texts ToS** | Explicit limit: 1 file/day for robots. Barnes and Wesley are available there but ToS makes bulk scraping non-compliant. | Use as verification only, not bulk source. |
| **StudyLight ToS** | Copyright claim on all materials; permission required for reuse. Has many commentaries not available elsewhere (Bengel HTML, Lange HTML, Poole HTML). | Do not scrape. If specific text is needed, submit email permission request — or use Internet Archive originals instead. |
| **SWORD format complexity** | SWORD binary format requires `pysword` library or SWORD C++ API to read. Not trivial to parse. | Test `pysword` against Barnes and Calvin modules before committing to this path. |
| **Spurgeon one-volume OCR quality** | Volunteer digitisation — quality unverified | Spot-check 5–10 Psalms against known good text before committing |
| **Bengel 5-volume split** | 5 separate volumes on Internet Archive — need to identify all volume IDs | Human: search `archive.org` for all 5 Bengel Gnomon volumes before scripting |
| **Lange OCR quality** | 26 volumes, variable digitisation quality, mix of sources | Spot-check 3–5 volumes across OT/NT before bulk processing |
| **Calvin missing books** | No English Calvin commentary exists for ~16 OT books and Acts/Revelation | Not a source gap — Calvin simply did not write these. Document as known coverage limitation. |
| **Wesley SWORD OT coverage** | SWORD module says "whole Bible" but OT notes are brief — verify depth | Download and spot-check before marking as complete |
| **HuggingFace/GitHub datasets** | HistoricalChristianFaith/Commentaries-Database on GitHub has structured TOML commentary data — coverage and which target authors are included is unconfirmed | Human: `git clone` and inspect directory structure to confirm which authors are present |

---

## 5. Recommended Download Sequence

### Phase 1 — Clean bulk downloads (no scraping required)

1. **HelloAO CLI self-host** — Install `@helloao/cli`, generate static JSON for all 6 commentaries locally. Gives Adam Clarke, JFB, Gill, Keil-Delitzsch, Matthew Henry, Tyndale in clean JSON. No rate limit issues when self-hosted.

2. **CrossWire SWORD ZIPs** — Download three ZIP files:
   - `Barnes` — NT Notes, Public Domain
   - `CalvinCommentaries` — 47 books, Public Domain
   - `Wesley` — whole Bible, Public Domain
   - Install `pysword` and test extraction before processing all three.

3. **HistoricalChristianFaith/Commentaries-Database** — `git clone https://github.com/HistoricalChristianFaith/Commentaries-Database`. Inspect directory structure. Map which authors are present. If Poole, Lange, or Bengel are there in structured TOML, this becomes a tier-1 source.

### Phase 2 — Internet Archive text files (rate-limited, sequential)

4. **Spurgeon Treasury of David** — Download `ch-spurgeon-the-treasury-of-david-in-one-volume` plain text from Internet Archive. Spot-check quality. If poor, fall back to individual original Google-digitised volumes.

5. **Bengel's Gnomon NT** — Identify all 5 volume IDs on Internet Archive. Download `_djvu.txt` plain text for each. Concatenate.

6. **Lange's Commentary** — Assess scope first. All 26 volumes as `_djvu.txt` from the main collection. This is the largest and most risky acquisition — do a quality pilot on 2 volumes before committing to full 26.

7. **Barnes OT** — Identify all OT volume IDs on Internet Archive. Download and concatenate. Note gutter-clipping quality risk on some volumes.

### Phase 3 — Structured HTML fallback (only if Phase 1/2 quality is insufficient)

8. **CCEL `.txt` downloads** — Use for Barnes NT as quality verification against SWORD version. URL pattern: `https://ccel.org/ccel/b/barnes/ntnotes/cache/ntnotes.txt`

9. **Sacred-texts.com** — Manually download (one file/day, per ToS) specific Wesley or Barnes chapters where Internet Archive OCR is poor. Not for bulk use.

### Phase 4 — Human review items (cannot be automated without permission decision)

10. **Matthew Poole** — Inspect grace-ebooks.com ZIPs. Decision required: are the files clean text or PDF? If PDF, test extraction quality. Flag result.

11. **StudyLight permission request** — If Bengel, Lange, or Poole from Internet Archive are too noisy to use, consider submitting a formal permission request to StudyLight for structured HTML access. Low probability of success but worth one attempt.

---

## Source URLs for Reference

- HelloAO commentary list: `https://bible.helloao.org/api/available_commentaries.json`
- HelloAO GitHub: `https://github.com/HelloAOLab/bible-api`
- CrossWire commentary modules: `https://crosswire.org/sword/modules/ModDisp.jsp?modType=Commentaries`
- Barnes SWORD download: `https://crosswire.org/sword/servlet/SwordMod.Verify?modName=Barnes&pkgType=raw`
- CalvinCommentaries SWORD download: `https://crosswire.org/sword/servlet/SwordMod.Verify?modName=CalvinCommentaries&pkgType=raw`
- Wesley SWORD download: `https://crosswire.org/sword/servlet/SwordMod.Verify?modName=Wesley&pkgType=raw`
- CCEL Barnes NT: `https://www.ccel.org/ccel/barnes/ntnotes.html` → `.txt` at `/ccel/b/barnes/ntnotes/cache/ntnotes.txt`
- CCEL Calvin: `https://www.ccel.org/ccel/calvin/commentaries.html`
- CCEL copyright policy: `https://ccel.org/about/copyright.html`
- Sacred-texts Barnes: `https://sacred-texts.com/bib/cmt/barnes/index.htm`
- Sacred-texts Wesley: `https://sacred-texts.com/bib/cmt/wesley/index.htm`
- Sacred-texts ToS: `https://sacred-texts.com/tos.htm`
- StudyLight rights page: `https://www.studylight.org/site-resources/rights-and-permissions.html`
- HistoricalChristianFaith GitHub: `https://github.com/HistoricalChristianFaith/Commentaries-Database`
- Internet Archive Lange (complete): `https://archive.org/details/CommentaryOnTheHolyScripturesCriticalDoctrinalAndHomilectical.Lange`
- Internet Archive Spurgeon combined: `https://archive.org/details/ch-spurgeon-the-treasury-of-david-in-one-volume`
- Internet Archive Bengel: `https://archive.org/details/cu31924092350523`
- Internet Archive Poole 1685: `https://archive.org/details/bim_early-english-books-1641-1700_annotations-upon-the-hol_poole-matthew_1685`
- pysword (Python SWORD reader): `https://pypi.org/project/pysword/`
- grace-ebooks Poole: `https://www.grace-ebooks.com/library/index.php?dir=Matthew+Poole/Annotations+-+Files+by+Bible+Book/`
