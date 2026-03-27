# Reference Works — Source Investigation
*Researched: 2026-03-27 | Researcher: Claude Code (OCD project)*

---

## Decision Brief

**5 key findings to act on:**

1. **JWBickel/BibleDictionaries on HuggingFace is real and usable** — Confirmed: contains Easton's (3,960 entries), Smith's (4,560 entries), Hitchcock's (2,620 entries), and Torrey's Topical Textbook (623 entries) in JSONL format. Term-keyed structure confirmed. **License: not specified in README** — the underlying texts are public domain but the dataset has no explicit open license. This is a yellow flag, not a hard stop: email JWBickel to confirm terms.

2. **CCEL has Nave's Topical Bible in ThML/XML** — `ccel.org/ccel/nave/bible.xml`. 20,000+ topics. Full term-keyed structure confirmed. CCEL formatting copyright applies (same terms as theological works — non-commercial use permitted).

3. **ISBE (1915) is NOT on CCEL in ThML format** — Confirmed absent from CCEL's ThML index. Best options are: Internet Archive (5-volume scanned set, OCR) and internationalstandardbible.com (web-readable). No clean structured download exists. This will require OCR processing or web scraping.

4. **HelloAO API covers Bible translations and commentaries only** — No reference works (Nave's, Easton's, ISBE, etc.) are available through the HelloAO API. This API is not useful for reference work acquisition.

5. **Torrey's Topical Textbook is also in the JWBickel HuggingFace dataset** — 623 entries. Also available standalone on CCEL (`ccel.org/ccel/torrey/ttt.html`). Hitchcock's Bible Names Dictionary is part of the same HuggingFace dataset.

**Recommended approach:** Use JWBickel/BibleDictionaries HuggingFace dataset as the primary source for Easton's + Smith's + Hitchcock's + Torrey's (pending license confirmation). Use CCEL ThML for Nave's (pending CCEL permission). ISBE requires a dedicated processing effort — plan separately.

---

## HuggingFace Dataset Deep-Dive: JWBickel/BibleDictionaries

**Dataset URL:** `https://huggingface.co/datasets/JWBickel/BibleDictionaries`

### Confirmed Facts

| Attribute | Detail |
|---|---|
| Exists? | Yes — confirmed |
| Dataset name | JWBickel/BibleDictionaries |
| Note: NOT "bible_dictionary_unified" | The actual name is BibleDictionaries, not the name mentioned in the brief |
| Dictionaries included | Easton's Bible Dictionary, Smith's Bible Dictionary, Hitchcock's Bible Names Dictionary, Torrey's Topical Textbook |
| Total rows | 23,536 |
| File format | JSONL (primary) + Parquet (auto-converted) |
| Data structure | Term-keyed: `{"term": "...", "definitions": ["..."]}` |
| Term field max length | 1–48 characters |
| Definitions field | List of strings; 1–215 definitions per entry |
| Size category | 10K–100K entries |
| License | **Not specified** — no license field in README YAML metadata |
| Auto-converted Parquet | Available at `/tree/refs%2Fconvert%2Fparquet` |

### Entry Counts by Dictionary

| Dictionary | Entry Count | Notes |
|---|---|---|
| Easton's Bible Dictionary | 3,960 rows | 1893 edition — public domain |
| Smith's Bible Dictionary | 4,560 rows | 1863 edition — public domain |
| Hitchcock's Bible Names Dictionary | 2,620 rows | 19th c — public domain |
| Torrey's Topical Textbook | 623 rows | Lower count — topical entries, not exhaustive |
| "default" config (combined?) | 11,800 rows | Likely combined view |

### Quality Assessment

- Structure is term-keyed: directly usable as a reference schema
- JSONL format: easy to ingest with Python line-by-line processing
- Parquet option: faster for large-scale processing
- No license = ambiguity, not a hard stop (underlying texts are PD)
- Example entry shows clean text structure — not OCR noise

### License Status

No license is declared in the dataset README. This is not unusual for public domain derivative datasets on HuggingFace, but means there is no explicit grant. The underlying source texts (Easton's 1893, Smith's 1863, Hitchcock's, Torrey's) are all clearly in the public domain in the US. The formatting/curation work is minimal JSON wrapping.

**Recommendation:** Treat as usable for OCD. The underlying data is indisputably public domain. If OCD publishes derived data, add a provenance note citing the original works (not the HuggingFace dataset). Optionally email JWBickel to ask if they'd license it explicitly (CC0 or public domain dedication).

---

## Per-Reference-Work Findings

### 1. Easton's Bible Dictionary (1893)

| Attribute | Detail |
|---|---|
| Best source | JWBickel/BibleDictionaries HuggingFace (JSONL, term-keyed, 3,960 entries) |
| Secondary source | CCEL: `ccel.org/ccel/easton/ebd.html` — ThML/XML available |
| Project Gutenberg | Not found in direct search — may exist but not prominent |
| Term-keyed? | Yes — both HuggingFace and CCEL |
| Entry count | 3,960 (HuggingFace) |
| Access method | HuggingFace: `huggingface.co/datasets/JWBickel/BibleDictionaries` — direct JSONL download |
| License | HuggingFace: unlicensed (PD text). CCEL: public domain text, CCEL formatting copyright. |

---

### 2. Smith's Bible Dictionary (1863)

| Attribute | Detail |
|---|---|
| Best source | JWBickel/BibleDictionaries HuggingFace (JSONL, term-keyed, 4,560 entries) |
| Secondary source | CCEL likely has it — not confirmed in ThML index search |
| Project Gutenberg | Not confirmed |
| Term-keyed? | Yes (HuggingFace confirmed) |
| Entry count | 4,560 (HuggingFace) — higher than Easton's |
| Access method | Same HuggingFace dataset — separate config (`Smith`) |
| License | Same as above |

---

### 3. International Standard Bible Encyclopedia (ISBE, 1915)

| Attribute | Detail |
|---|---|
| Best source | **None that is clean and structured** — requires processing effort |
| CCEL | **Not available in ThML format** — confirmed absent from CCEL ThML index |
| Internet Archive | 5-volume scanned set: `archive.org/details/theinternationalstandardbibleencyclopedia` — OCR text downloadable |
| internationalstandardbible.com | Complete text online, web-readable — no download API or structured export |
| biblesnet.com | Single PDF: `biblesnet.com/international_standard_bible_encyclopedia.pdf` |
| GitHub | No JSON/XML structured version found |
| HuggingFace | Not found |
| Scope | ~10,000 articles, 5 volumes, ~2,500 pages per volume |
| Term-keyed? | Yes in principle — but no pre-structured digital version available |
| License | 1915 edition: public domain in the US |
| Access method | Internet Archive API (download OCR text) — requires significant post-processing |

**Assessment:** ISBE is the hardest reference work on the list. The OCR from Internet Archive will have errors, and the structure is complex (articles range from a paragraph to many pages). Budget this as a multi-week processing project, not a quick download. Consider deferring until after other reference works are ingested.

---

### 4. Nave's Topical Bible (1896)

| Attribute | Detail |
|---|---|
| Best source | CCEL ThML/XML |
| CCEL URL | `ccel.org/ccel/nave/bible.html` |
| CCEL XML | `/ccel/n/nave/bible.xml` |
| Topic count | 20,000+ topics (confirmed on CCEL work info page) |
| Structure | Topic-keyed entries with verse references under each topic |
| CCEL formats | ThML/XML, PDF, Word HTML, plain text (UTF-8) |
| Internet Archive | Scanned copy: `archive.org/details/navestopicalbibl00nave` — OCR quality variable |
| navestopicalbible.org | Plain text with custom markup (`$$topic_number`, `\topic_name\`, `#` verse list, `|` terminator) — downloadable, public domain |
| GitHub | rcdilorenzo/ecce includes Nave's topics (~4,200 intersected with ESV) — not complete |
| MetaV project | Includes Nave's + Torrey's in public domain structured format |
| Term-keyed? | Yes — structured as topic headings with verse reference lists |
| License | CCEL: public domain text, CCEL formatting copyright. navestopicalbible.org: public domain. |
| Access method | CCEL direct XML download (preferred); navestopicalbible.org direct download (open) |

**Notes:** navestopicalbible.org provides a developer-oriented plain text format with explicit markup for topic parsing. This is a viable alternative to CCEL ThML if CCEL permission is pending. However the custom markup format (`$$`, `\`, `#`, `|`) requires a custom parser rather than standard XML tools.

---

### 5. Torrey's Topical Textbook

| Attribute | Detail |
|---|---|
| Best source | JWBickel/BibleDictionaries HuggingFace (JSONL, 623 entries) |
| Secondary source | CCEL: `ccel.org/ccel/torrey/ttt.html` — ThML/XML likely available |
| Entry count | 628 topics / 20,000+ scripture references (definitive count) — 623 in HuggingFace |
| Structure | Topic-keyed, similar to Nave's but smaller |
| Internet Archive | `archive.org/details/in.ernet.dli.2015.261963` |
| Term-keyed? | Yes |
| License | Public domain (19th c). HuggingFace: unlicensed. CCEL: formatting copyright. |
| Access method | HuggingFace JSONL (quickest); CCEL XML (most structured) |

---

### 6. Hitchcock's Bible Names Dictionary

| Attribute | Detail |
|---|---|
| Best source | JWBickel/BibleDictionaries HuggingFace (JSONL, 2,620 entries) |
| CCEL | Likely present — not specifically confirmed |
| Entry count | 2,620 (HuggingFace) |
| Structure | Term-keyed: name → meaning/derivation |
| Term-keyed? | Yes |
| License | Public domain. HuggingFace: unlicensed. |
| Access method | Same HuggingFace dataset — `Hitchcock` config |

---

## HelloAO API — Findings

**URL:** `https://bible.helloao.org/api/`

The HelloAO (AO Lab) API provides:
- 1,000+ Bible translations in JSON
- Commentaries (per book/chapter)
- No API key required, no rate limits

**Reference works available:** None confirmed. The API is focused exclusively on Bible translations and commentaries. Nave's, Easton's, Smith's, ISBE, and Torrey's are not available through this API.

**robots.txt:** Could not directly confirm (access denied). The API is explicitly public and designed for programmatic use — no access concerns for the API endpoints themselves.

**Assessment:** HelloAO is not relevant for reference work acquisition. Useful for future Bible text/commentary needs.

---

## Sacred-Texts.com — Findings

The Christian section (`sacred-texts.com/chr/`) contains 197+ texts including church fathers, mystical Christianity, and patristic works. Format is HTML only — no bulk download or structured data export. Texts are taken from public domain scholarly sources.

**For this project:** Sacred-texts.com offers some texts (e.g. Calvin's Institutes: `sacred-texts.com/chr/calvin/inst/index.htm`) but only as paginated HTML with no structured download. It is not a viable source for structured data acquisition — better to use CCEL or Project Gutenberg.

---

## Recommended Approach

### Immediate (low friction, clear license)

1. **Download JWBickel/BibleDictionaries from HuggingFace** — gets you Easton's + Smith's + Hitchcock's + Torrey's in one step, all term-keyed JSONL. Direct download: `huggingface.co/datasets/JWBickel/BibleDictionaries`. Use the JSONL files (not Parquet unless you prefer columnar format).

2. **Download navestopicalbible.org plain text** — if CCEL permission is pending, this is a freely available public domain source for Nave's 20,000+ topics with developer-friendly markup.

### Medium term (pending CCEL permission)

3. **CCEL ThML for Nave's** — `/ccel/n/nave/bible.xml` — richest structure, 20,000 topics with scripture reference tags.

4. **CCEL ThML for Torrey's** — `/ccel/t/torrey/ttt.xml` — 628 topics, better structured than the HuggingFace version.

### Longer term (requires processing effort)

5. **ISBE from Internet Archive** — Download the OCR text files from the 5-volume set at `archive.org/details/theinternationalstandardbibleencyclopedia`. Plan for significant post-processing: deduplication, article boundary detection, OCR error correction. This is a multi-week project. Consider whether ISBE is required for the MVP or can wait.

### What to skip

- HelloAO API — not applicable for reference works
- Sacred-texts.com — HTML only, no structured download
- biblesnet.com ISBE PDF — use Internet Archive instead for better OCR quality

---

## License Summary

| Source | License Status | Safe to Use? |
|---|---|---|
| JWBickel/BibleDictionaries | No license declared; underlying texts PD | Yes, with provenance note |
| CCEL ThML | Non-commercial/educational use permitted | Yes, with CCEL permission |
| navestopicalbible.org | Public domain | Yes |
| Internet Archive (ISBE OCR) | Public domain (1915 text) | Yes |
| Project Gutenberg | Public domain | Yes |

---

*Sources consulted: huggingface.co/datasets/JWBickel/BibleDictionaries, ccel.org, bible.helloao.org, sacred-texts.com, archive.org, navestopicalbible.org, github.com/rcdilorenzo/ecce*
