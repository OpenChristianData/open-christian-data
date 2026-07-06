# Sermons Manifest

Last updated: 2026-04-17 (Whitefield 59→61; Maclaren coverage stats updated)

## Ingested

### John Wesley — Sermons on Several Occasions
- **File**: `data/sermons/john-wesley-sermons.json`
- **Parser**: `build/parsers/ccel_sermon.py`
- **Source**: `https://www.ccel.org/ccel/wesley/sermons.xml` (ThML XML)
- **Raw**: `raw/ccel/wesley_sermons.xml` (4,239 KB, sha256 prefix: `70f4b1d4`)
- **Sermons**: 141 across 5 series (First–Fifth)
- **Schema**: OCD sermon v2.1.0, validated 0 errors
- **Status**: Complete

**ThML structure**:
- `<div1 id="v|vi|vii|viii|ix">` — 5 series containers
- `<div2>` — individual sermons (141 total; 4 index div2s in `<div1 id="xi">` skipped)
- `<h2>` — first: "Sermon N [edition]" (number line); second: title; optional third: discourse subtitle
- `<h3><scripRef osisRef="Bible:Book.ch.v">` — primary scripture reference
- `<p>` / `<verse><l>` — sermon body
- `<note>` — editorial footnotes (excluded from content_blocks)

**Known source artifacts** (handled in parser):
- Some title h2 elements contain publisher editorial notes without a separator period (e.g. Sermon 101)
- 1 sermon (Sermon 43) has ALL-CAPS title h2; possessive `'S` capitalisation in 1 case
- `<scripCom>` elements are structural placeholders (no osisRef content in Wesley)

**date_preached / location**: Left null. Occasion text is present for ~15/141 sermons in the h2 (e.g. "Preached at St. Mary's, Oxford...on June 18, 1738") but only ~3 have machine-parseable dates. Recommend a dedicated enrichment step if structured date/location data is needed.

---

### George Whitefield — Selected Sermons
- **File**: `data/sermons/george-whitefield-sermons.json`
- **Parser**: `build/parsers/ccel_whitefield_sermon.py`
- **Source**: `https://www.ccel.org/ccel/whitefield/sermons.xml` (ThML XML)
- **Raw**: `raw/ccel/whitefield_sermons.xml` (1,998 KB)
- **Sermons**: 61 (59 from CCEL; 2 supplementary from PG#77041 — see below)
- **Schema**: OCD sermon v2.1.0, validated 0 errors
- **Status**: Complete

**ThML structure** (differs from Wesley):
- `<div1>` — one sermon per div1 (62 total; first two and last one skipped)
- `<h1>` — sermon title (may include occasion text "Preached..." and/or trailing parenthetical)
- `<scripCom>` — present but `osisRef` is **empty** (no OSIS refs in CCEL Whitefield)
- First `<p>` — scripture ref + quote: `"Book N:M -- 'quote...'"` (dash separator) or `"Book N:M, 'quote'"` (comma separator, 1 case)
- Remaining `<p>` / `<verse><l>` — sermon body
- `<note>` — editorial footnotes (excluded from content_blocks)

**Known source variations** (handled in parser):
- 11/59 sermons have no scripture reference paragraph — their first `<p>` is body text; all 11 confirmed by XML inspection to have no hidden ref in any element
- 1/59 sermons (sermon 47, "Charity") uses a comma separator instead of a dash in the ref paragraph
- Some `<h1>` elements include occasion text "Preached at..." or trailing parenthetical notes — both stripped
- `osisRef` is always empty → `primary_reference.osis` is `[]` for all entries with refs

**Word count distribution**: min=2149, median=5691, max=10155. Three sermons exceed 8000 words (legitimately long — Whitefield was known for extended preaching): sermon 12 "Christ the Believer's Husband" (10155), sermon 39 "The Resurrection of Lazarus" (9187), sermon 24 "What Think Ye of Christ?" (8175).

**date_preached / location**: Left null. Occasion text present in some `<h1>` elements but inconsistent.

**Supplementary entries (sermon_id 60-61)**: "Peter's Denial of his Lord" (Matt 26:75) and "The True Way of Beholding the Lamb of God" (John 1:35-36) extracted from PG#77041 (Works Vol 6, 1771) via `build/scripts/add_pg_whitefield_sermons.py`. These are genuine 1771 Works sermons absent from the CCEL Selected Sermons source. Word counts: 6,462 and 7,172.

---

### C. H. Spurgeon — Metropolitan Tabernacle Pulpit
- **File**: `data/sermons/spurgeon-mtp.json`
- **Primary parser**: `build/parsers/spurgeon_mtp.py`
- **Supplementary parser**: `build/parsers/spurgeon_mtp_missing.py`
- **Primary source**: `https://thekingdomcollective.com/spurgeon/` (HTML)
- **Raw**: `raw/spurgeon_sermons/html/` (3,547 files, gitignored)
- **Supplementary raw**: `raw/spurgeon_sermons/missing/` (3 HTML files cached 2026-04-13)
- **Sermons**: 3,550 of 3,563 numbered slots (as of 2026-04-13)
- **Schema**: OCD sermon v2.1.0
- **Status**: Complete for all transcribed sermons; 13 gaps are intentional (non-sermon content)

**Supplementary entries added 2026-04-13** (via `spurgeon_mtp_missing.py`):

| # | Title | Scripture | Source |
|---|-------|-----------|--------|
| 708 | The Blood Of Abel And The Blood Of Jesus | Gen 4:10 | answersingenesis.org |
| 1698 | The Star And The Wise Men | Matt 2:1-2, 9-10 | archive.spurgeon.org |
| 3032 | The Fashion Of This World | 1 Cor 7:31 | answersingenesis.org |

**Intentional gaps** (13 numbers — not independent sermons):

| # | Nature | Notes |
|---|--------|-------|
| 8 | Duplicate number | Second half of paired entry with #7 (NPSP Vol 1, 1855) |
| 40 | Duplicate number | Joint entry with #39 — same sermon, two sequential numbers |
| 42 | Duplicate number | Joint entry with #41 — same sermon, two sequential numbers |
| 62 | Exposition (62e) | Running exposition of 1 John 3:1-10, not a titled sermon |
| 67 | Exposition (67e) | Running exposition of 1 Cor 15:1-58, not a titled sermon |
| 82 | Tracts (82t) | Two short evangelistic tracts appended to NPSP Vol 2 |
| 142 | Duplicate number | Second half of paired entry with #141 (2 Cor 5:21) |
| 155 | Duplicate number | Second half of paired entry with #154 (Mic 6:9) |
| 269 | Ceremonial proceedings | Laying of first stone of Metropolitan Tabernacle (combined with #268–270) |
| 270 | Ceremonial proceedings | Same event as #269 |
| 298 | Duplicate number | Second half of paired entry with #297 (2 Kgs 5:12) |
| 332 | Meeting proceedings | Great Meeting in the Metropolitan Tabernacle |
| 390 | Duplicate/continuation | Continuation of #389 Nonconformity proceedings (MTP Vol 7, 1861) |

**Source reference for gap determination**: http://www.romans45.org/spurgeon/index/cindex.htm

---

### Alexander Maclaren — Expositions of Holy Scripture
- **File**: `data/sermons/maclaren-expositions.json`
- **Parser**: `build/parsers/gutenberg_maclaren.py`
- **Source**: 15 Project Gutenberg plain-text files (PG#7069, 8068, 7883, 7925, 8069, 15836, 7351, 8071, 8200, 8070, 8381, 8397, 13601, 21190, 24674). Canonical URL pattern: `https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt`
- **Raw**: `raw/gutenberg/sermons/maclaren/` (15 files, gitignored). Inventory: `raw/gutenberg/sermons/PG_SERMON_INVENTORY.md`
- **Sermons**: 1263 expositions across 15 volumes (Genesis through the General Epistles)
- **Schema**: OCD sermon v2.1.0, validated 0 errors
- **Status**: Complete

**Volume breakdown** (actual counts from `data/sermons/maclaren-expositions.json` grouped by `series`):

| PG# | Bible Books | Expositions |
|-----|-------------|-------------|
| 7069 | Genesis, Exodus, Leviticus and Numbers | 100 |
| 8068 | Deuteronomy, Joshua, Judges, Ruth, Samuel and Kings (to 2 Kings VII) | 106 |
| 7883 | 2 Kings VIII-End, Chronicles, Ezra, Nehemiah, Esther, Job, Proverbs, Ecclesiastes | 103 |
| 7925 | Psalms | 76 |
| 8069 | Isaiah and Jeremiah | 111 |
| 15836 | Ezekiel, Daniel, Minor Prophets, Matthew I-VIII | 90 |
| 7351 | Matthew IX-XXVIII | 71 |
| 8071 | Mark | 73 |
| 8200 | Luke | 94 |
| 8070 | John I-XIV | 71 |
| 8381 | John XV-XXI | 39 |
| 8397 | The Acts | 85 |
| 13601 | Romans and Corinthians (to 2 Cor V) | 84 |
| 21190 | 2 Cor, Galatians, Philippians, Colossians, Thessalonians, 1 Timothy | 83 |
| 24674 | Ephesians, 1 Peter and 1 John | 77 |

**Parsing method**: All-caps heading detection (`is_all_caps_heading`: ≥85% uppercase alpha, ≤12 words, ≥4 alpha chars, no leading quote). Word count threshold ≥100 filters ToC entries and book-name dividers.

**Scripture reference extraction** (three-priority chain):
1. Parenthetical in heading: `THE TITLE (Genesis i. 26)` → `Genesis i. 26`
2. Standalone parenthetical block immediately after heading: `(Genesis i. 26--ii. 3)`
3. `--BOOK ref.` marker at end of opening scripture quotation (checked in first 3 content blocks)

**Scripture reference coverage**: 1246/1263 (98.7%) have `primary_reference` (after parser fix 2026-04-17; original parser recovered 880/1263). The remaining 17 (1.3%) have no extractable reference in any position checked — `primary_reference` is omitted (not null) for these.

**Word count distribution**: min=105, avg=2741, max=12920.

**Whitefield note**: PG Works vols 5-6 (59 sermons) evaluated and skipped. Verification 2026-04-17: |A|=57 matched, |B|=2 PG-only, |C|=2 CCEL-only; body text verified sermons 8, 30, 52. Skip confirmed. **Source clarification:** CCEL source is *Selected Sermons of George Whitefield* (independent CCEL curation, 2001) — not a digitisation of the 1771 Works. Sermons 58-59 differ: PG has "Peter's Denial of his Lord" + "The True Way of Beholding the Lamb of God" (genuine 1771 Works sermons); CCEL has "The Method of Grace" + "The Good Shepherd" (sourced outside the Works). These 2 PG-unique sermons were added to `george-whitefield-sermons.json` as sermon_ids 60-61 (see supplementary entries in the Whitefield section above). See `raw/gutenberg/sermons/PG_SERMON_INVENTORY.md` for full record.

---

### George MacDonald — Unspoken Sermons
- **File**: `data/sermons/george-macdonald-unspoken-sermons.json`
- **Parser**: `build/parsers/standard_ebooks.py`
- **Sermons**: 36 across 3 series
- **Status**: Complete

---

## Glob gotcha — Spurgeon is sharded

Spurgeon Metropolitan Tabernacle Pulpit is the only sermon collection stored as a directory of shard files: `data/sermons/spurgeon-mtp/sermons-<start>-<end>.json` (36 files, ~3 MB each, 3,547 sermons total).

All other collections (`george-whitefield-sermons.json`, `john-wesley-sermons.json`, etc.) are single JSON files at the top level.

```python
glob("data/sermons/*.json")          # silently misses all Spurgeon
glob("data/sermons/spurgeon-mtp/*.json")  # Spurgeon only
```

Always handle Spurgeon separately or ls-check before counting. The split happened 2026-04-15 when the monolithic `spurgeon-mtp.json` (118 MB) exceeded GitHub's 100 MB limit.

13 intentional gap numbers across the collection: 8, 40, 42, 62, 67, 82, 142, 155, 269, 270, 298, 332, 390.

Supplementary sermons 708, 1698, 3032 from AiG and archive.spurgeon.org; merged into the per-shard counts.
