# Westminster Standards Scraper — Design Spec

**Date:** 2026-03-28
**Status:** Draft
**Scope:** Scrape thewestminsterstandard.org to (1) add proof texts to the existing WSC data, and (2) add 5 new Westminster Standards documents not available in Creeds.json.

---

## Decision Brief

- **Goal:** Complete Westminster Standards coverage in OCD — proof texts for WSC + 5 new prose documents.
- **Source:** thewestminsterstandard.org — static HTML, no API, no rate limit concerns for 6 page fetches.
- **Architecture:** Same pipeline as existing parsers: raw source → parser → data JSON → validate.py. No new patterns.
- **Key constraint:** No API costs. All processing is deterministic + manual review.
- **Phased delivery:** Phase 1 delivers WSC proofs and all 5 documents as prose. Phase 2 adds structured proof extraction for the 3 inline-citation documents.

---

## Background

### What we have

| Document | Source | Proofs | Status |
|---|---|---|---|
| WCF (33 chapters) | Creeds.json | Yes — structured OSIS | Done |
| WLC (196 Q&A) | Creeds.json | Yes — structured OSIS | Done (Task 4) |
| WSC (107 Q&A) | Creeds.json | **No** — source lacks them | Gap |

### What we need

| Document | Source | Proofs in source | Phase |
|---|---|---|---|
| WSC proof texts | thewestminsterstandard.org | Yes — plain text in `<em>` tags | 1 |
| Directory for Public Worship | thewestminsterstandard.org | None | 1 |
| Directory for Family Worship | thewestminsterstandard.org | None | 1 |
| Form of Church Government | thewestminsterstandard.org | Yes — inline Roman numeral | 1 (prose) / 2 (proofs) |
| Solemn League and Covenant | thewestminsterstandard.org | Sparse — inline parenthetical | 1 (prose) / 2 (proofs) |
| Sum of Saving Knowledge | thewestminsterstandard.org | Yes — inline mixed format | 1 (prose) / 2 (proofs) |

### Why thewestminsterstandard.org

- NonlinearFruit confirmed Creeds.json is Unlicense — but Creeds.json simply does not contain these 5 documents or WSC proof texts.
- thewestminsterstandard.org has all Westminster Standards in one place with consistent formatting.
- License: these are 17th-century public domain texts. The site adds no original content beyond HTML formatting.

### HTML Structure (verified)

The ref.ly `data-reference` attributes referenced in earlier research are **JavaScript-injected by RefTagger at page load** and do NOT exist in the raw static HTML. The actual static HTML structure for WSC proof texts is:

```html
<p><b>Q. </b>1. What is the chief end of man?<br>
<b>A. </b>Man's chief end is to glorify God, and to enjoy him for ever.</p>
<p><em>1 Cor. 10:31; Rom. 11:36; Ps. 73:25-28.</em></p>
```

Proof texts are **plain text citation strings inside `<em>` tags**, semicolon-separated, using modern abbreviations with colons for chapter:verse.

---

## Phase 1 — WSC Proofs + 5 New Documents as Prose

### 1.1 Scraper: `build/scrapers/westminster_standard_org.py`

**Purpose:** Fetch and cache HTML from thewestminsterstandard.org.

**Behavior:**
- Fetches a URL, saves the raw HTML to `raw/westminster-standard-org/{slug}.html`
- If the cached HTML file already exists, skips the fetch (idempotent)
- `--force` flag to re-fetch
- `--all` flag to fetch all 6 pages
- Logs each fetch to `build/scrapers/westminster_standard_org.log`

**Pages to fetch:**

| Slug | URL |
|---|---|
| `westminster-shorter-catechism` | `/westminster-shorter-catechism/` |
| `directory-for-publick-worship` | `/directory-for-the-publick-worship-of-god/` |
| `directory-for-family-worship` | `/directory-for-family-worship` |
| `form-of-church-government` | `/form-of-presbyterial-church-government/` |
| `solemn-league-and-covenant` | `/the-solemn-league-and-covenant/` |
| `sum-of-saving-knowledge` | `/the-sum-of-saving-knowledge/` |

**Dependencies:** `urllib.request` (stdlib — no new dependencies for fetching). `beautifulsoup4` for HTML parsing (add to `requirements.txt` if not already present).

### 1.2 Citation Parser: `build/lib/citation_parser.py`

**Purpose:** Parse plain-text scripture citation strings (as found in `<em>` tags) into structured OSIS references.

**Input format (WSC `<em>` tag content):**
```
"1 Cor. 10:31; Rom. 11:36; Ps. 73:25-28."
"Eph. 1:4,11; Rom. 9:22-23."
"Gen. 17:10 with Col. 2:11-12; 1 Cor. 7:14."
"Gen. 1; Heb. 11:3."
```

**Processing steps:**
1. Strip trailing period
2. Split on semicolons → individual citation strings
3. For each citation string, parse into OSIS:
   - Identify book abbreviation via lookup table
   - Extract chapter number (Arabic — the WSC uses modern format, not Roman numerals)
   - Extract verse(s): single (`31`), range (`25-28`), list (`1-2, 7, 9`), or absent (chapter-only ref like `Gen. 1`)
4. Handle special cases:
   - Comma-separated verses within one chapter: `Eph. 1:4,11` → `["Eph.1.4", "Eph.1.11"]`
   - Verse ranges: `Ps. 73:25-28` → `["Ps.73.25-Ps.73.28"]`
   - Chapter-only: `Gen. 1` → `["Gen.1"]`
   - `with` conjunction: `Gen. 17:10 with Col. 2:11-12` → treat as two separate references
   - Comma-separated chapter refs within same book: `Ps. 51:1-2, 7, 9` → `["Ps.51.1-Ps.51.2", "Ps.51.7", "Ps.51.9"]`

**Components:**
- `BOOK_ABBREVIATIONS: dict[str, str]` — maps abbreviation forms to OSIS book codes. Build empirically by extracting all unique book abbreviations from the scraped WSC HTML, then extend as needed for other documents. Covers standard forms: `1 Cor.`, `Ps.`, `Gen.`, `Matt.`, `Rev.`, `Eph.`, `Heb.`, `Jas.`, `Ecc.`, `Deut.`, `Exod.`, `Prov.`, `Neh.`, etc.
- `parse_citation_string(raw: str) -> list[dict]` — takes one semicolon-delimited citation block (the full `<em>` content), returns list of `{"raw": "...", "osis": ["..."]}` reference objects.
- `parse_single_reference(ref: str) -> dict` — takes one reference like `"1 Cor. 10:31"`, returns `{"raw": "1 Cor. 10:31", "osis": ["1Cor.10.31"]}`.

**Not in scope for Phase 1:**
- Roman numeral chapter conversion (Form of Church Government, Phase 2)
- Free-text citation boundary detection in running prose (Phase 2)
- Back-reference resolution (`ver. 10`) (Phase 2)

### 1.3 WSC Proof Text Enrichment

**Purpose:** Add proof texts to the existing WSC data file.

**Approach:**
1. Read cached HTML for `westminster-shorter-catechism`
2. Parse the Q&A + proof text structure:
   - Each question is a `<p>` containing `<b>Q. </b>` followed by number and text
   - Each answer follows in the same `<p>` after `<b>A. </b>`
   - Proof texts are in the next sibling `<p>` inside `<em>` tags
   - Proof text content is plain text: `"1 Cor. 10:31; Rom. 11:36; Ps. 73:25-28."`
3. For each question, extract the `<em>` text → pass to `parse_citation_string()` → get OSIS references
4. Store as a single flat proof group per question (no numbered groups — the source doesn't have them)

**Dual provenance:** After enrichment, the WSC data has two sources: Creeds.json for Q&A text, thewestminsterstandard.org for proof texts. The `provenance` object in `meta` keeps Creeds.json as the primary source (Q&A text). The `provenance.notes` field documents that proof texts were sourced from thewestminsterstandard.org with download date. In `sources/catechisms/westminster-shorter-catechism/config.json`, add a `secondary_sources` array with one entry: `{"name": "thewestminsterstandard.org", "url": "https://thewestminsterstandard.org/westminster-shorter-catechism/", "contribution": "proof_texts", "download_date": "YYYY-MM-DD"}`.

**`answer_with_proofs`:** Remains `null`. The source does not embed `[1]`, `[2]` proof markers in the answer text — proofs are in a separate paragraph. This is different from the WLC pattern (which has `answer_with_proofs` populated) and is correct for the WSC source.

**Output:** Updates `data/catechisms/westminster-shorter-catechism.json` — populating the `proofs` array on each Q&A entry. The existing Q&A text is preserved unchanged. `completeness` remains `"full"`.

**Proof schema mapping (catechism_qa):**
```json
{
  "proofs": [
    {
      "id": 1,
      "references": [
        { "raw": "1 Cor. 10:31", "osis": ["1Cor.10.31"] },
        { "raw": "Rom. 11:36", "osis": ["Rom.11.36"] },
        { "raw": "Ps. 73:25-28", "osis": ["Ps.73.25-Ps.73.28"] }
      ]
    }
  ]
}
```

Since the source has no numbered proof groups, every question gets a single proof with `"id": 1` containing all references for that question. The `raw` field preserves the original citation text as it appears on the source page (before OSIS conversion).

**Validation:** All 107 questions must have proof counts matching the source page. Any question with zero proofs where the source has proofs is an error.

### 1.4 New Document Parsers

**Purpose:** Parse the 5 additional documents into `doctrinal_document` schema JSON.

**Single parser file:** `build/parsers/westminster_standard_parser.py` with per-document config (same pattern as `creeds_json_confession.py`).

#### Schema Changes Required

**`document_kind` enum** — add new values:
- `"directory"` — for Directory for Public Worship and Directory for Family Worship
- `"covenant"` — for Solemn League and Covenant

Existing values `"confession"`, `"canon"`, `"creed"`, `"declaration"` are unchanged. Note: `creeds_json_confession.py` has a hardcoded `VALID_DOCUMENT_KINDS` check — this does NOT need updating since the new documents use a different parser, but this drift should be noted in `validate.py` which reads the schema as source of truth.

**`unit_type` enum** — defer `"paragraph"` addition to Phase 2. In Phase 1, all documents use existing unit types (`section`, `article`). The `"paragraph"` type is only needed when Form of Church Government and Sum of Saving Knowledge get child units for numbered propositions in Phase 2.

#### Per-Document Structure

**Directory for Public Worship** (~16 sections, ~25,000 words)
- `document_kind`: `"directory"`
- Structure: flat list of `section` units, each with `content` (prose text)
- No `proofs`, no `content_with_proofs`
- `tradition`: `["reformed", "presbyterian"]`

**Directory for Family Worship** (~14 sections, ~3,000 words)
- `document_kind`: `"directory"`
- Structure: `section` units numbered I–XIV with `content`
- No `proofs`, no `content_with_proofs`
- `tradition`: `["reformed", "presbyterian"]`

**Form of Church Government** (~20 sections, ~13,000 words)
- `document_kind`: `"declaration"` (doctrinal assertion of polity, not a confession or creed)
- Structure: `section` units with `content` (prose text, inline citations preserved verbatim)
- Phase 1: `content` only — no proof extraction
- Phase 2: `content` + `content_with_proofs` + `proofs` array
- `completeness`: `"partial"` (proofs deferred)
- `tradition`: `["reformed", "presbyterian"]`

**Solemn League and Covenant** (~4,200 words, 6 articles)
- `document_kind`: `"covenant"`
- Structure: `article` units numbered I–VI with `content`
- Phase 1: `content` only (sparse citations not extracted)
- Phase 2: extract the few citations into `proofs`
- `completeness`: `"partial"` (proofs deferred)
- `tradition`: `["reformed", "presbyterian"]`

**Sum of Saving Knowledge** (~20,000 words, hierarchical: 4 Heads + practical use divisions)
- `document_kind`: `"declaration"` (theological exposition)
- Structure: hierarchical `section` units (Heads I–IV, Practical Use divisions) with `section` children
- Phase 1: `content` only
- Phase 2: `content` + `content_with_proofs` + `proofs` array
- `completeness`: `"partial"` (proofs deferred)
- `tradition`: `["reformed", "presbyterian"]`

#### Metadata

All 5 documents share:
- `author`: `"Westminster Assembly"`
- `original_publication_year`: 1645 (Directories, Form of Govt), 1643 (Solemn League), or 1650 (Sum of Saving Knowledge)
- `language`: `"en"`
- `license`: `"public-domain"`
- `schema_version`: `"2.1.0"` (matching existing files)
- `provenance.source_url`: canonical thewestminsterstandard.org URL
- `provenance.source_format`: `"html"`
- `provenance.processing_method`: `"automated"`

#### Source Config Files

Each new document gets a `sources/doctrinal-documents/{document-id}/config.json` following the existing convention (same structure as `sources/doctrinal-documents/westminster-confession-of-faith/config.json`). Fields: `source.name`, `source.url`, `source.repository` (null — not from a repo), `source.license_notes`, `stats` (section/word counts), `notes`.

### 1.5 Manifest Sync

**Prerequisite:** The current `data/doctrinal-documents/_manifest.json` lists only the WCF (1 entry) despite 33 doctrinal-document files existing. Before adding 5 new entries, update the manifest to reflect all existing files. Approach: add a `--sync-manifest` flag to `westminster_standard_parser.py` (or a standalone script) that scans all `data/doctrinal-documents/*.json` files and regenerates the manifest from their `meta` fields. This runs once as a prerequisite, then again after the 5 new files are added.

### 1.6 File Outputs

**New files:**
- `raw/westminster-standard-org/` — 6 cached HTML files
- `build/scrapers/westminster_standard_org.py`
- `build/lib/__init__.py` (empty, makes it a package)
- `build/lib/citation_parser.py`
- `build/parsers/westminster_standard_parser.py`
- `data/doctrinal-documents/directory-for-publick-worship.json`
- `data/doctrinal-documents/directory-for-family-worship.json`
- `data/doctrinal-documents/form-of-church-government.json`
- `data/doctrinal-documents/solemn-league-and-covenant.json`
- `data/doctrinal-documents/sum-of-saving-knowledge.json`
- `sources/doctrinal-documents/` — 5 new `{id}/config.json` directories

**Modified files:**
- `data/catechisms/westminster-shorter-catechism.json` — proofs added
- `sources/catechisms/westminster-shorter-catechism/config.json` — provenance notes updated for dual-source
- `schemas/v1/doctrinal_document.schema.json` — `document_kind` enum extended with `"directory"` and `"covenant"`
- `data/doctrinal-documents/_manifest.json` — synced to all files + 5 new entries
- `build/validate.py` — no changes expected (reads schema as source of truth for enum validation)

---

## Phase 2 — Inline Citation Extraction (Future)

**Scope:** Extract structured OSIS proof references from the 3 inline-citation documents (Form of Church Government, Solemn League, Sum of Saving Knowledge).

**Three distinct citation formats across these documents:**
- Form of Church Government: `Acts vi. 2, 3, 4, and xx. 36` (Roman numeral chapters, bare inline)
- Solemn League: `Jer. 50:5` (modern format, parenthetical, sparse)
- Sum of Saving Knowledge: `Hos 13.9`, `Rom. 10:5, Gal 3:10,12` (mixed period/colon, no tags)

**Approach:** Use `pythonbible` library (MIT, actively maintained, has built-in Roman numeral support) with a thin preprocessing wrapper. Phase 2 will get its own spec once Phase 1 is complete. The `citation_parser.py` module from Phase 1 provides the OSIS conversion layer that Phase 2 will extend.

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| thewestminsterstandard.org HTML structure changes | Cached in `raw/` — parser reads from cache, not live site |
| Book abbreviation variants not in lookup table | Build lookup table empirically from scraped data; log unknown abbreviations |
| WSC proof text count mismatch | Parser validates proof count per question against source; any mismatch is a hard error |
| Schema enum changes break existing files | Enum additions only — no removals or renames. Existing files unaffected. |
| Copyright concern on scraped content | These are 17th-century public domain texts. The site adds no copyrightable original content. |
| `urllib.request` HTTPS certificate issues on Windows | Fall back to `requests` if certificate chain fails; document in README |

---

## Success Criteria

**Phase 1 complete when:**
1. All 107 WSC questions have proof texts matching the source
2. 5 new doctrinal-document files validate clean against schema
3. All existing files still validate (no regressions)
4. Manifest synced — reflects all doctrinal-document files
5. Total data file count: current 108 + 5 new = 113, 0 errors, 0 new warnings
