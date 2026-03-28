# Westminster Standards Scraper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WSC proof texts and 5 new Westminster Standards documents to OCD.

**Architecture:** Same raw → parser → data JSON → validate pipeline as existing parsers. New shared citation parser utility in `build/lib/`. HTML scraper caches pages to `raw/westminster-standard-org/`. No new dependencies beyond `beautifulsoup4`.

**Tech Stack:** Python 3, BeautifulSoup4, existing `build/validate.py`

**Spec:** `docs/WESTMINSTER_STANDARDS_SCRAPER_SPEC.md`

**CODING_DEFAULTS:** Load `CODING_DEFAULTS.md` from the operator's Claude Cowork workspace — all scripts must follow these rules (absolute paths, logging, summaries, quality stats, utf-8 encoding, ASCII-only print output).

**Python command:** Use `py -3` (not `python`) on this Windows environment.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `build/lib/__init__.py` | Create | Empty package init |
| `build/lib/citation_parser.py` | Create | Parse plain-text citation strings → OSIS references |
| `tests/test_citation_parser.py` | Create | Unit tests for citation parser |
| `build/scrapers/westminster_standard_org.py` | Create | Fetch and cache HTML pages |
| `build/parsers/westminster_standard_parser.py` | Create | Parse cached HTML → doctrinal_document JSON + WSC proof enrichment |
| `schemas/v1/doctrinal_document.schema.json` | Modify | Add `"directory"` and `"covenant"` to `document_kind` enum |
| `data/catechisms/westminster-shorter-catechism.json` | Modify | Populate `proofs` arrays |
| `sources/catechisms/westminster-shorter-catechism/config.json` | Modify | Add secondary_sources + update notes |
| `data/doctrinal-documents/_manifest.json` | Modify | Sync to reflect all existing + new files |
| `raw/westminster-standard-org/*.html` | Create | 6 cached HTML files |
| `data/doctrinal-documents/*.json` | Create | 5 new document files |
| `sources/doctrinal-documents/*/config.json` | Create | 5 new source config directories |

---

## Task 1: Citation Parser — Book Abbreviation Table

**Files:**
- Create: `build/lib/__init__.py`
- Create: `build/lib/citation_parser.py`
- Create: `tests/test_citation_parser.py`

- [ ] **Step 1: Write failing tests for book abbreviation lookup**

```python
# tests/test_citation_parser.py
"""Tests for build.lib.citation_parser."""
import sys
from pathlib import Path

# Allow imports from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.lib.citation_parser import lookup_book


def test_simple_book():
    assert lookup_book("Gen.") == "Gen"
    assert lookup_book("Gen") == "Gen"


def test_numbered_book():
    assert lookup_book("1 Cor.") == "1Cor"
    assert lookup_book("2 Tim.") == "2Tim"
    assert lookup_book("1 John") == "1John"


def test_abbreviated_book():
    assert lookup_book("Ps.") == "Ps"
    assert lookup_book("Matt.") == "Matt"
    assert lookup_book("Rev.") == "Rev"
    assert lookup_book("Jas.") == "Jas"
    assert lookup_book("Ecc.") == "Eccl"
    assert lookup_book("Ex.") == "Exod"
    assert lookup_book("Deut.") == "Deut"


def test_full_name():
    assert lookup_book("Romans") == "Rom"
    assert lookup_book("Hebrews") == "Heb"
    assert lookup_book("Psalms") == "Ps"


def test_unknown_returns_none():
    assert lookup_book("Notabook") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_citation_parser.py -v`
Expected: ImportError — module does not exist yet.

- [ ] **Step 3: Create `build/lib/__init__.py` (empty) and implement `citation_parser.py` with `BOOK_ABBREVIATIONS` and `lookup_book()`**

The book abbreviation table should be built **empirically**: first scrape the WSC HTML (Task 3), extract all unique book abbreviations from the `<em>` tags, then ensure every abbreviation maps correctly. For now, populate from the known WSC examples visible in the spec and the raw HTML samples:

`1 Cor.`, `Rom.`, `Ps.`, `2 Tim.`, `Eph.`, `John`, `1 John`, `Matt.`, `Deut.`, `Jer.`, `Gen.`, `Heb.`, `Ex.`, `Jas.`, `Ecc.`, `Rev.`, `Gal.`, `Acts`, `Col.`, `Exod.`, `Isa.`, `Prov.`, `Neh.`, `Dan.`, `Luke`, `Job.`, `2 Cor.`, `Phil.`, `1 Pet.`, `2 Pet.`, `1 Thess.`, `2 Thess.`, `Lev.`, `Num.`, `Josh.`, `1 Sam.`, `2 Sam.`, `1 Chr`, `Mark`, `Titus`, `1 Tim.`, `2 Sam.`

Map each to the OSIS book code used in the existing data (check `build/validate.py` `KNOWN_BOOK_NUMBERS` dict for the canonical codes).

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_citation_parser.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add build/lib/__init__.py build/lib/citation_parser.py tests/test_citation_parser.py
git commit -m "feat: add citation parser with book abbreviation lookup table"
```

---

## Task 2: Citation Parser — Reference Parsing

**Files:**
- Modify: `build/lib/citation_parser.py`
- Modify: `tests/test_citation_parser.py`

- [ ] **Step 1: Write failing tests for `parse_single_reference()`**

```python
from build.lib.citation_parser import parse_single_reference


def test_simple_reference():
    result = parse_single_reference("Rom. 11:36")
    assert result == {"raw": "Rom. 11:36", "osis": ["Rom.11.36"]}


def test_verse_range():
    result = parse_single_reference("Ps. 73:25-28")
    assert result == {"raw": "Ps. 73:25-28", "osis": ["Ps.73.25-Ps.73.28"]}


def test_comma_separated_verses():
    result = parse_single_reference("Eph. 1:4,11")
    assert result == {"raw": "Eph. 1:4,11", "osis": ["Eph.1.4", "Eph.1.11"]}


def test_chapter_only():
    result = parse_single_reference("Gen. 1")
    assert result == {"raw": "Gen. 1", "osis": ["Gen.1"]}


def test_numbered_book():
    result = parse_single_reference("1 Cor. 10:31")
    assert result == {"raw": "1 Cor. 10:31", "osis": ["1Cor.10.31"]}


def test_verse_list_with_range():
    # "Ps. 51:1-2, 7, 9" -- range + individual verses in same chapter
    result = parse_single_reference("Ps. 51:1-2, 7, 9")
    assert result == {"raw": "Ps. 51:1-2, 7, 9", "osis": ["Ps.51.1-Ps.51.2", "Ps.51.7", "Ps.51.9"]}


def test_acts_with_comma_verses():
    result = parse_single_reference("Acts 2:42, 46-47")
    assert result == {"raw": "Acts 2:42, 46-47", "osis": ["Acts.2.42", "Acts.2.46-Acts.2.47"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_citation_parser.py::test_simple_reference -v`
Expected: ImportError or AttributeError.

- [ ] **Step 3: Implement `parse_single_reference()`**

Logic:
1. Strip whitespace
2. Identify book abbreviation (try longest match first for numbered books)
3. Remaining string has `chapter:verse` or `chapter` only
4. If `:` present, split chapter and verse portion
5. Parse verse portion: handle ranges (`25-28`), comma-separated (`4,11`), mixed (`1-2, 7, 9`)
6. Build OSIS strings

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_citation_parser.py -v`
Expected: All pass.

- [ ] **Step 5: Write failing tests for `parse_citation_string()` (the full `<em>` content parser)**

```python
from build.lib.citation_parser import parse_citation_string


def test_semicolon_separated():
    result = parse_citation_string("1 Cor. 10:31; Rom. 11:36; Ps. 73:25-28.")
    assert len(result) == 3
    assert result[0] == {"raw": "1 Cor. 10:31", "osis": ["1Cor.10.31"]}
    assert result[2] == {"raw": "Ps. 73:25-28", "osis": ["Ps.73.25-Ps.73.28"]}


def test_with_conjunction():
    # "with" should split into two separate references
    result = parse_citation_string("Gen. 17:10 with Col. 2:11-12; 1 Cor. 7:14.")
    assert len(result) == 3
    assert result[0]["osis"] == ["Gen.17.10"]
    assert result[1]["osis"] == ["Col.2.11-Col.2.12"]


def test_trailing_period_stripped():
    result = parse_citation_string("Heb. 11:3.")
    assert len(result) == 1
    assert result[0]["osis"] == ["Heb.11.3"]


def test_chapter_only_ref():
    result = parse_citation_string("Gen. 1; Heb. 11:3.")
    assert len(result) == 2
    assert result[0]["osis"] == ["Gen.1"]
```

- [ ] **Step 6: Implement `parse_citation_string()`**

Logic:
1. Strip trailing period
2. Replace ` with ` with `;` (normalizes conjunction to semicolon separator)
3. Split on `; ` or `;`
4. For each part, call `parse_single_reference()`
5. Return list of reference dicts

- [ ] **Step 7: Run all tests**

Run: `py -3 -m pytest tests/test_citation_parser.py -v`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add build/lib/citation_parser.py tests/test_citation_parser.py
git commit -m "feat: add citation string parser with OSIS conversion"
```

---

## Task 3: HTML Scraper

**Files:**
- Create: `build/scrapers/westminster_standard_org.py`

- [ ] **Step 1: Implement the scraper**

Follow CODING_DEFAULTS: absolute paths via `REPO_ROOT = Path(__file__).resolve().parents[2]`, log file in same directory as script, summary at end, `encoding='utf-8'` on all `open()` calls, ASCII-only print output.

Features:
- `PAGES` dict mapping slug → URL path (6 entries from spec)
- `--slug <name>` to fetch one page
- `--all` to fetch all 6
- `--force` to re-fetch even if cached
- Saves to `raw/westminster-standard-org/{slug}.html`
- Creates directory if needed
- Logs each action
- Uses `urllib.request` with a User-Agent header
- Prints summary: "Fetched N pages, skipped N cached"

- [ ] **Step 2: Run the scraper to fetch all pages**

Run: `py -3 build/scrapers/westminster_standard_org.py --all`
Expected: 6 HTML files in `raw/westminster-standard-org/`. Verify file sizes are reasonable (>10KB each).

- [ ] **Step 3: Verify cached HTML contains expected content**

Run: `py -3 -c "from pathlib import Path; html = Path('raw/westminster-standard-org/westminster-shorter-catechism.html').read_text(encoding='utf-8'); print(html.count('<em>'), 'em tags found')"` (run from repo root)
Expected: ~107 `<em>` tags (one per question with proofs, minus any questions without proofs).

- [ ] **Step 4: Empirically verify the book abbreviation table**

Extract all unique book abbreviations from the WSC `<em>` tags and confirm every one maps in the citation parser. Fix any gaps.

Run a script that: parses all `<em>` tags from the cached HTML, splits on semicolons, extracts the book abbreviation portion, deduplicates, and checks each against `lookup_book()`. Print any unmapped abbreviations.

If any gaps are found, update the table in `build/lib/citation_parser.py` and re-run Task 1 + Task 2 tests: `py -3 -m pytest tests/test_citation_parser.py -v`

- [ ] **Step 5: Add `beautifulsoup4` to `requirements.txt`**

Create `requirements.txt` at repo root if it does not exist. Add `beautifulsoup4>=4.12`.

- [ ] **Step 6: Commit**

```bash
git add build/scrapers/westminster_standard_org.py raw/westminster-standard-org/
git commit -m "feat: add westminster standard scraper, cache 6 HTML pages"
```

---

## Task 4: Schema Update + Manifest Sync

**Files:**
- Modify: `schemas/v1/doctrinal_document.schema.json`
- Modify: `data/doctrinal-documents/_manifest.json`

- [ ] **Step 1: Add `"directory"` and `"covenant"` to `document_kind` enum**

In `schemas/v1/doctrinal_document.schema.json`, find the `document_kind` enum array and add the two new values. Keep alphabetical order.

Before: `["confession", "canon", "creed", "declaration"]`
After: `["canon", "confession", "covenant", "creed", "declaration", "directory"]`

- [ ] **Step 2: Run validate.py to confirm no regressions**

Run: `py -3 build/validate.py --all`
Expected: 0 errors. Existing files still pass (enum additions don't break anything).

- [ ] **Step 3: Sync the manifest**

Write a script (or inline) that scans all `data/doctrinal-documents/*.json` files (excluding `_manifest.json`), reads each file's `meta.id`, `meta.title`, `data.document_kind`, and generates a manifest entry. Output the synced manifest. Should produce ~33 entries for existing files.

- [ ] **Step 4: Verify manifest entry count**

Run: `py -3 -c "import json; m = json.load(open('data/doctrinal-documents/_manifest.json', encoding='utf-8')); print(len(m['documents']), 'entries')"` (run from repo root)
Expected: 33 entries (all existing doctrinal documents).

- [ ] **Step 5: Commit**

```bash
git add schemas/v1/doctrinal_document.schema.json data/doctrinal-documents/_manifest.json
git commit -m "feat: add directory/covenant document kinds, sync manifest to 33 files"
```

---

## Task 5: WSC Proof Text Enrichment

**Files:**
- Create: `build/parsers/westminster_standard_parser.py` (start with WSC enrichment, extend for documents in Task 6)
- Modify: `data/catechisms/westminster-shorter-catechism.json`
- Modify: `sources/catechisms/westminster-shorter-catechism/config.json`

- [ ] **Step 1: Implement WSC enrichment in `westminster_standard_parser.py`**

The parser should:
1. Read `raw/westminster-standard-org/westminster-shorter-catechism.html`
2. Parse with BeautifulSoup
3. Find all Q&A paragraphs (pattern: `<p>` containing `<b>Q. </b>`)
4. For each Q&A, find the next `<p>` sibling containing `<em>` — that is the proof text
5. Extract the `<em>` text content
6. Pass to `parse_citation_string()` from `build.lib.citation_parser`
7. Read existing `data/catechisms/westminster-shorter-catechism.json`
8. Match proofs to Q&A entries by question number (1-indexed sort_key)
9. Write updated file with proofs populated
10. Update `provenance.notes` with thewestminsterstandard.org source info
11. Print quality stats: questions with proofs, questions without, total references, any parse errors

Follow CODING_DEFAULTS: logging, summary, quality stats, ASCII-only output, `encoding='utf-8'`.

CLI: `py -3 build/parsers/westminster_standard_parser.py --enrich-wsc`

- [ ] **Step 2: Run the enrichment**

Run: `py -3 build/parsers/westminster_standard_parser.py --enrich-wsc`
Expected: Summary showing 107 questions processed, proof counts per question, total references.

- [ ] **Step 3: Validate the enriched file**

Run: `py -3 build/validate.py --all`
Expected: 0 errors. WSC file still validates.

- [ ] **Step 4: Spot-check proof text accuracy**

Manually verify 3 questions against the source page:
- Q1: should have `1 Cor. 10:31; Rom. 11:36; Ps. 73:25-28`
- Q4: should have `John 4:24; Job 11:7-9; Ps. 90:2; Jas. 1:17; Ex. 3:14; Ps. 147:5; Rev. 4:8; 15:4; Ex. 34:6-7`
- Q107 (last): check it matches the source

Run: `py -3 -c "import json; d = json.load(open('data/catechisms/westminster-shorter-catechism.json', encoding='utf-8')); e = d['data'][0]; print('Q1 proofs:', len(e['proofs'][0]['references']), 'refs'); print([r['raw'] for r in e['proofs'][0]['references']])"` (run from repo root)

- [ ] **Step 5: Verify `answer_with_proofs` remains null**

Run: `py -3 -c "import json; d = json.load(open('data/catechisms/westminster-shorter-catechism.json', encoding='utf-8')); awp = [e for e in d['data'] if e.get('answer_with_proofs') is not None]; print(f'{len(awp)} entries with answer_with_proofs set (expect 0)')"` (run from repo root)
Expected: `0 entries with answer_with_proofs set (expect 0)`

- [ ] **Step 6: Update WSC source config**

Update `sources/catechisms/westminster-shorter-catechism/config.json`:
- Add `"secondary_sources"` array with thewestminsterstandard.org entry
- Update `"parser"` field from `"build/parsers/wsc_parser.py"` to `"build/parsers/westminster_standard_parser.py"`
- Update `notes` to reflect proofs are now populated
- Update `license_notes` to reflect NonlinearFruit confirmed Unlicense (issue #59 resolved)

- [ ] **Step 6: Commit**

```bash
git add build/parsers/westminster_standard_parser.py data/catechisms/westminster-shorter-catechism.json sources/catechisms/westminster-shorter-catechism/config.json
git commit -m "feat: add WSC proof texts from thewestminsterstandard.org (107 questions)"
```

---

## Task 6: Five New Westminster Standards Documents

**Files:**
- Modify: `build/parsers/westminster_standard_parser.py`
- Create: 5 data files in `data/doctrinal-documents/`
- Create: 5 source configs in `sources/doctrinal-documents/`
- Modify: `data/doctrinal-documents/_manifest.json`

This is the largest task. Each document requires inspecting the cached HTML structure, writing the parser config, generating output, and validating.

- [ ] **Step 1: Inspect HTML structure for each document**

Before writing any parser code, inspect 2-3 sections of each cached HTML file to understand the actual heading/paragraph structure. Print the first few HTML elements to confirm section boundaries. Don't assume — verify per CODING_DEFAULTS rule 42.

Per-document inspection script pattern:
```python
from bs4 import BeautifulSoup
from pathlib import Path
html = Path(f"raw/westminster-standard-org/{slug}.html").read_text(encoding="utf-8")  # run from repo root
soup = BeautifulSoup(html, "html.parser")
# Find main content area, print headings and first paragraph of each section
for h in soup.find_all(["h2", "h3", "h4", "strong"]):
    print(h.name, "|", h.get_text(strip=True)[:80])
```

Run this for each of the 5 document slugs. Document the actual structure found.

- [ ] **Step 2: Add DOCUMENT_CONFIGS to the parser**

Based on the HTML inspection, add a config dict per document to `westminster_standard_parser.py`. Each config specifies:
- `document_id` (kebab-case)
- `document_kind` (`"directory"`, `"declaration"`, or `"covenant"`)
- `tradition`, `tradition_notes`
- `original_publication_year`
- `completeness` — explicit mapping:

| Document | `completeness` | Reason |
|---|---|---|
| Directory for Public Worship | `"full"` | No proofs to extract |
| Directory for Family Worship | `"full"` | No proofs to extract |
| Form of Church Government | `"partial"` | Inline proofs deferred to Phase 2 |
| Solemn League and Covenant | `"partial"` | Sparse inline proofs deferred to Phase 2 |
| Sum of Saving Knowledge | `"partial"` | Inline proofs deferred to Phase 2 |

- HTML parsing hints (heading tag for section boundaries, content extraction pattern)

- [ ] **Step 3: Implement document parsing**

For each document type:
- Parse the cached HTML with BeautifulSoup
- Identify section boundaries (heading tags)
- Extract section titles and content text
- Build `doctrinal_document` schema JSON with `units` array
- Set all metadata fields per the spec

CLI: `py -3 build/parsers/westminster_standard_parser.py --document {slug}` or `--all-documents`

Follow CODING_DEFAULTS: print quality stats (section count, word count, empty sections).

- [ ] **Step 4: Start with the simplest document — Directory for Family Worship**

It is the shortest (~3,000 words, 14 sections, no proofs). Parse it first to validate the approach.

Run: `py -3 build/parsers/westminster_standard_parser.py --document directory-for-family-worship`

Verify output file exists and has reasonable content:
```
py -3 -c "import json; d = json.load(open('data/doctrinal-documents/directory-for-family-worship.json', encoding='utf-8')); print(len(d['data']['units']), 'units'); print(d['meta']['title'])"  # run from repo root
```

- [ ] **Step 5: Validate**

Run: `py -3 build/validate.py --all`
Expected: 0 errors on all files including the new one.

- [ ] **Step 6: Commit the first document**

```bash
git add data/doctrinal-documents/directory-for-family-worship.json
git commit -m "feat: add Directory for Family Worship"
```

- [ ] **Step 7: Process remaining 4 documents one at a time**

For each: run the parser, validate, spot-check content, commit. Order by complexity:
1. Solemn League and Covenant (~4,200 words, 6 articles)
2. Directory for Public Worship (~25,000 words, ~16 sections)
3. Form of Church Government (~13,000 words, ~20 sections, `completeness: partial`)
4. Sum of Saving Knowledge (~20,000 words, hierarchical, `completeness: partial`)

Each gets its own commit.

- [ ] **Step 8: Create source config files for all 5 documents**

Follow the pattern in `sources/doctrinal-documents/westminster-confession-of-faith/config.json`. Each config needs:
- `id`, `title`, `author`, `original_publication_year`
- `source.name`: `"thewestminsterstandard.org"`
- `source.url`: canonical page URL
- `source.repository`: `null`
- `source.format`: `"HTML"`
- `source.license`: `"Public Domain"`
- `source.license_notes`: `"17th-century text; no copyrightable original content added by host site."`
- `source.download_date`: actual date of scrape
- `source.source_hash`: SHA-256 of the cached HTML file
- `stats`: section/word counts from parser output
- `notes`: relevant notes (completeness, Phase 2 plans)

- [ ] **Step 9: Sync manifest with all 38 files**

Re-run the manifest sync to include the 5 new documents (33 existing + 5 new = 38).

- [ ] **Step 10: Final validation**

Run: `py -3 build/validate.py --all`
Expected: 113 files, 0 errors. (108 existing + 5 new)

- [ ] **Step 11: Commit remaining files**

```bash
git add data/doctrinal-documents/ sources/doctrinal-documents/ build/parsers/westminster_standard_parser.py
git commit -m "feat: add 5 Westminster Standards documents from thewestminsterstandard.org"
```

---

## Task 7: Final Review + Cleanup

- [ ] **Step 1: Run full validation suite**

Run: `py -3 build/validate.py --all`
Expected: 113 files, 0 errors, 3 existing warnings (1695 Baptist Catechism empty answers).

- [ ] **Step 2: Check for any citation parser gaps**

Run: `py -3 -m pytest tests/test_citation_parser.py -v`
Expected: All pass.

- [ ] **Step 3: Run python-standards-reviewer on all new/modified Python files**

Files to review:
- `build/lib/citation_parser.py`
- `build/scrapers/westminster_standard_org.py`
- `build/parsers/westminster_standard_parser.py`
- `tests/test_citation_parser.py`

Fix any violations found.

- [ ] **Step 4: Commit any fixes from review**

- [ ] **Step 5: Update LAST_SESSION.md**

Record what was completed, decisions made, and what is next (Phase 2: inline citation extraction).
