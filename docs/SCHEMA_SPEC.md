# Open Christian Data -- Schema Specification

**Version:** 2.1.0
**Date:** 2026-03-27
**Status:** Revised -- incorporates Codex red team findings, standards research, ML/LLM infrastructure additions
**Authority:** JSON Schema files in `schemas/v1/` are the validation source of truth. This document is the human-readable companion.

---

## Design Principles

1. **One schema per content type.** A verse-keyed commentary and a date-keyed devotional have fundamentally different structures.
2. **Shared metadata envelope.** Every resource carries the same provenance and identity metadata at the resource level.
3. **Source fidelity first.** The canonical JSON is faithful to the source. Enrichment (summaries, key quotes, tags) lives in a separate layer. Denormalized exports (SQLite/Parquet/HF) are derived downstream.
4. **Resource-level provenance.** Provenance lives on the metadata envelope, not repeated on every record. Record-level `provenance_override` is available when a specific record differs from its parent.
5. **Raw + normalized references.** All verse references store both the raw source form and the normalized OSIS form: `{"raw": "Rom. 8. 33 &c.", "osis": ["Rom.8.33-Rom.8.39"]}`.
6. **BSB as verse text source.** Berean Standard Bible (CC0 since April 2023).
7. **American English in all project output.** Project uses American English for anonymity.

---

## Three-Layer Architecture

| Layer | Purpose | Storage |
|-------|---------|---------|
| **Source** | Faithful to the source data. Core schemas below. | `data/` -- committed to git |
| **Enrichment** | AI-generated summaries, key quotes, tags, reviewer metadata | `sources/{resource}/enrichment/` -- committed separately |
| **Derived** | Denormalized rows for SQL/Parquet/HF with provenance flattened per-row | `dist/` -- generated, not committed |

Enrichment records reference source records by `entry_id` and are joined at build time. This means:
- Source data ships without waiting for summaries
- Each summary can be individually reviewed, updated, or withheld
- Enrichment changes don't pollute source data git history

---

## Reference Object

Used everywhere a verse citation appears. Preserves source fidelity while enabling normalized queries.

```json
{
  "raw": "Rom. 8. 33 &c.",
  "osis": ["Rom.8.33-Rom.8.39"]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `raw` | string | Yes | Reference as it appears in the source |
| `osis` | array of strings | Yes | Normalized OSIS. May be empty if unparseable. Multiple entries for compound refs |

When the source is already clean OSIS (e.g., HelloAO, Creeds.json), `raw` and `osis[0]` will be identical. That's fine -- consistency matters more than deduplication.

---

## License Enum (Canonical)

One set, used everywhere:

```json
["cc0-1.0", "public-domain", "cc-by-4.0", "cc-by-sa-4.0"]
```

- `cc0-1.0` -- Creative Commons Zero (explicit dedication)
- `public-domain` -- public domain by age or jurisdiction (no explicit CC0 dedication)
- `cc-by-4.0` -- Creative Commons Attribution
- `cc-by-sa-4.0` -- Creative Commons Attribution-ShareAlike

---

## Metadata Envelope (Resource-Level)

Every output file wraps records in this envelope:

```json
{
  "meta": {
    "id": "matthew-henry-complete",
    "title": "Matthew Henry's Complete Commentary",
    "author": "Matthew Henry",
    "author_birth_year": 1662,
    "author_death_year": 1714,
    "contributors": [],
    "original_publication_year": 1706,
    "language": "en",
    "original_language": "en",
    "tradition": ["reformed", "puritan", "nonconformist"],
    "tradition_notes": "Henry was a Nonconformist minister shaped by Puritan covenant theology.",
    "era": "post-reformation",
    "audience": "pastoral",
    "license": "public-domain",
    "schema_type": "commentary",
    "schema_version": "2.1.0",
    "completeness": "partial",
    "versification": "KJV",
    "provenance": {
      "source_url": "https://bible.helloao.org/api/c/matthew-henry/EZK/1.json",
      "source_format": "JSON",
      "source_edition": "HelloAO digitization of CCEL/Matthew Henry",
      "download_date": "2026-03-27",
      "source_hash": "sha256:abc123...",
      "processing_method": "automated",
      "processing_script_version": "build/parsers/matthew_henry_helloao.py@v1.0.0",
      "processing_date": "2026-03-27",
      "notes": null
    },
    "scope": {
      "verse_text_source": "BSB",
      "verse_reference_standard": "OSIS"
    }
  },
  "data": []
}
```

**New envelope fields (v2.1):**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `original_language` | string | No | ISO 639-1 code of original composition language (distinct from `language` which is this edition). `"la"` for Calvin's Institutes, `"en"` for Spurgeon |
| `era` | string | No | `"apostolic"`, `"patristic"`, `"medieval"`, `"reformation"`, `"post-reformation"`, `"modern"` |
| `audience` | string | No | `"scholarly"`, `"pastoral"`, `"lay"`, `"children"` |
| `versification` | string | No | Which verse numbering system references assume. Default `"KJV"`. Values from SWORD: `"KJV"`, `"LXX"`, `"Catholic"`, `"Lutheran"`, `"Vulgate"`, `"MT"` (Masoretic). Critical for cross-tradition accuracy -- Catholic Psalms are numbered differently |
| `author_id` | string | No | Canonical author ID linking to the author registry (see Author Registry section) |

**Changes from v1:**
- `verse_text_source` and `verse_reference_standard` moved into optional `scope` object (only for verse-keyed types)
- `license` uses canonical enum (no more `unlicense` or `public_domain` with underscore)
- `summary_metadata` removed from envelope (moved to enrichment layer)

---

## Cross-Cutting Record Fields

These optional fields appear on records across all schema types. They enable ML pipelines, deduplication, and cross-resource linking.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `token_count` | integer | No | Token count using cl100k_base (OpenAI tiktoken). Computed at build time. Published alongside `word_count` in all exports. ML pipelines need tokens, not words |
| `content_hash` | string | No | SHA-256 of normalized text content (lowercased, whitespace-collapsed, punctuation-stripped). Enables near-duplicate detection across resources. **Not for automatic dedup** -- flags candidates for human review. See Deduplication Policy |
| `related_entries` | array | No | Cross-resource links. `[{entry_id, relationship}]`. Relationship vocabulary: `"quotes"`, `"cites"`, `"expounds"`, `"echoes"`, `"responds_to"`, `"contradicts"`, `"parallels"`. Enrichment-layer work -- populated by AI or human annotation, not parsers |

### Deduplication Policy

`content_hash` enables detection, but deduplication decisions are manual:

| Scenario | Duplicate? | Action |
|----------|-----------|--------|
| Same commentary in HelloAO and CCEL | Yes | Deduplicate -- keep better provenance |
| Same verse in BSB and WEB | **No** -- parallel translations | Keep both. Parallel translations are valuable paired data for paraphrase learning |
| Spurgeon quoting Matthew Henry verbatim | **No** -- citation | Keep both, link via `related_entries` with `"quotes"` |
| Same catechism Q&A in two Creeds.json files | Yes | Deduplicate |
| Church Father quote appearing in multiple TOML files for different verses | **No** -- different verse anchors | Keep both. Same quote applied to different passages is distinct usage |

---

## Schema Types (13)

### 1. `bible_text` -- Verse-level Bible text

For: BSB, WEB, other translations

```json
{
  "osis": "Gen.1.1",
  "chapter": 1,
  "verse": 1,
  "text": "In the beginning God created the heavens and the earth."
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `osis` | string | Yes | OSIS verse ref (e.g., `Gen.1.1`) |
| `chapter` | integer | Yes | |
| `verse` | integer | Yes | |
| `text` | string | Yes | Verse text, whitespace-trimmed |

Book identity (`book`, `book_osis`, `book_number`) lives at the file level since files are book-scoped. Envelope `meta.scope.book_osis` carries this.

**Validated against:** `raw/bible_databases/formats/json/BSB.json`

---

### 2. `commentary` -- Verse-keyed commentary (EXISTING)

For: Matthew Henry, JFB, Gill, Clarke, Keil-Delitzsch, Barnes, Calvin, Poole

```json
{
  "entry_id": "matthew-henry-complete.Ezek.1.1-3",
  "book": "Ezekiel",
  "book_osis": "Ezek",
  "book_number": 26,
  "chapter": 1,
  "verse_range": "1-3",
  "anchor_ref": {
    "raw": "Ezekiel 1:1-3",
    "osis": ["Ezek.1.1-Ezek.1.3"]
  },
  "verse_text": "In the thirtieth year, in the fourth month...",
  "commentary_text": "The book of the prophet Ezekiel...",
  "commentary_type": "exegetical",
  "cross_references": [
    {"raw": "Jer.29.1", "osis": ["Jer.29.1"]},
    {"raw": "Dan.1.1-6", "osis": ["Dan.1.1-Dan.1.6"]}
  ],
  "word_count": 1523,
  "token_count": 2104,
  "content_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "related_entries": [],
  "provenance_override": null
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `entry_id` | string | Yes | `{resource-id}.{book_osis}.{chapter}.{verse_range}` |
| `book` | string | Yes | Full English name |
| `book_osis` | string | Yes | OSIS code |
| `book_number` | integer (1-66) | Yes | Canonical order |
| `chapter` | integer | Yes | |
| `verse_range` | string | Yes | e.g., `"1"`, `"1-3"`, `"26-28"` |
| `anchor_ref` | Reference | Yes | Raw + OSIS reference for the passage |
| `verse_text` | string/null | No | BSB verse text. Optional -- derived from BSB, not source |
| `commentary_text` | string | Yes | Full commentary text |
| `commentary_type` | string/null | No | `"exegetical"`, `"devotional"`, `"linguistic"`, `"historical"`, `"practical"`, or `null` |
| `cross_references` | array of Reference | Yes | May be empty |
| `word_count` | integer | Yes | |
| `provenance_override` | object/null | No | Only when this entry differs from resource-level provenance |

**Changes from v1:** Removed `summary*`, `key_quote*` (moved to enrichment). Added `anchor_ref` (raw + OSIS). Added `commentary_type` (from W3C Web Annotation motivation vocabulary). Changed `cross_references` to Reference objects.

**Validated against:** `data/commentaries/matthew-henry/ezekiel.json` (132 entries)

---

### 3. `doctrinal_document` -- Hierarchical confessional/creedal document

Replaces v1 `confession`. Handles chapter/section (WCF), flat articles (Belgic), single-block creeds (Apostles'), and canons (Dort) with one recursive tree.

Inspired by Akoma Ntoso's flexible legal document hierarchy.

```json
{
  "document_id": "westminster-confession",
  "document_kind": "confession",
  "revision_history": [
    {"year": 1903, "body": "American Presbyterian", "description": "Chapter XXIII.3 revised (civil magistrate)"}
  ],
  "units": [
    {
      "unit_type": "chapter",
      "number": "1",
      "title": "Of the Holy Scriptures",
      "children": [
        {
          "unit_type": "section",
          "number": "1",
          "content": "Although the light of nature...",
          "content_with_proofs": "Although the light of nature...[1]",
          "proofs": [
            {
              "id": 1,
              "references": [
                {"raw": "Ps.19.1-3", "osis": ["Ps.19.1-Ps.19.3"]},
                {"raw": "Rom.1.19-20", "osis": ["Rom.1.19-Rom.1.20"]}
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

Belgic (flat articles):
```json
{
  "document_id": "belgic-confession",
  "document_kind": "canon",
  "units": [
    {
      "unit_type": "article",
      "number": "1",
      "title": "The Only God",
      "content": "We all believe..."
    }
  ]
}
```

Apostles' Creed (single block):
```json
{
  "document_id": "apostles-creed",
  "document_kind": "creed",
  "units": [
    {
      "unit_type": "text",
      "content": "I believe in God the Father Almighty..."
    }
  ]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `document_id` | string | Yes | Kebab-case |
| `document_kind` | string | Yes | `"confession"`, `"canon"`, `"creed"`, `"declaration"` |
| `revision_history` | array | No | `[{year, body, description}]`. From Akoma Ntoso lifecycle tracking |
| `units` | array | Yes | Recursive tree |
| `units[].unit_type` | string | Yes | `"chapter"`, `"section"`, `"article"`, `"text"` |
| `units[].number` | string | No | String to handle "1a" or Roman numerals |
| `units[].title` | string | No | |
| `units[].content` | string | No | Plain text (leaf nodes) |
| `units[].content_with_proofs` | string | No | Text with `[N]` markers |
| `units[].proofs` | array | No | Proof text references |
| `units[].children` | array | No | Nested units (recursive) |

**Validated against:** WCF, LBC 1689 (chapter/section), Belgic, Scots (flat articles), Apostles' Creed (single block)

---

### 4. `catechism_qa` -- Question and answer catechism

For: Westminster Shorter, Westminster Larger, Heidelberg, Keach's, Baptist, Henry's

```json
{
  "document_id": "westminster-shorter-catechism",
  "item_id": "1",
  "sort_key": 1,
  "question": "What is the chief end of man?",
  "answer": "Man's chief end is to glorify God, and to enjoy him for ever.",
  "answer_with_proofs": "Man's chief end is to glorify God,[1] and to enjoy him for ever.[2]",
  "proofs": [
    {
      "id": 1,
      "references": [
        {"raw": "Rom.11.36", "osis": ["Rom.11.36"]},
        {"raw": "1Cor.10.31", "osis": ["1Cor.10.31"]}
      ]
    }
  ],
  "group": null,
  "sub_questions": null
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `document_id` | string | Yes | Kebab-case |
| `item_id` | string | Yes | String -- handles `"1"`, `"1a"`, `"1b"` |
| `sort_key` | integer | Yes | Numeric for ordering |
| `question` | string | Yes | |
| `answer` | string | Yes | Plain text |
| `answer_with_proofs` | string/null | No | With `[N]` markers |
| `proofs` | array | Yes | May be empty |
| `proofs[].references` | array of Reference | Yes | Raw + OSIS |
| `group` | string/null | No | `"Lord's Day 1"`, `"Part I: The Ten Commandments"`, etc. Source-backed or parser-mapped |
| `sub_questions` | array/null | No | For Henry's catechisms: `[{item_id, question, answer}]` |

**Changes from v1:** `question_number` (integer) replaced with string `item_id` + numeric `sort_key`. `lords_day` and `part` merged into generic `group`. Added `sub_questions` for Henry's format.

---

### 5. `structured_text` -- Hierarchical prose work

Replaces v1 `catechism_prose` AND `theological_work`. Luther's Large Catechism and Calvin's Institutes are structurally identical: hierarchical prose with nested sections.

```json
{
  "work_id": "calvins-institutes",
  "work_kind": "theological-work",
  "sections": [
    {
      "section_type": "book",
      "label": "Book II",
      "title": "On The Knowledge Of God The Redeemer In Christ",
      "children": [
        {
          "section_type": "chapter",
          "label": "Chapter VIII",
          "title": "An Exposition Of The Moral Law",
          "content_blocks": ["Paragraph 1...", "Paragraph 2..."],
          "scripture_references": [
            {"raw": "Exod.20.1-17", "osis": ["Exod.20.1-Exod.20.17"]}
          ]
        }
      ]
    }
  ]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `work_id` | string | Yes | Kebab-case |
| `work_kind` | string | Yes | `"theological-work"`, `"catechism-prose"`, `"treatise"`, `"devotional-classic"` |
| `sections` | array | Yes | Recursive tree |
| `sections[].section_type` | string | Yes | `"book"`, `"part"`, `"chapter"`, `"subsection"` |
| `sections[].label` | string | No | Source label (e.g., "Book II", "Part I") |
| `sections[].title` | string | No | Section title |
| `sections[].content_blocks` | array of strings | No | Paragraphs (leaf nodes). Array, not blob |
| `sections[].scripture_references` | array of Reference | No | |
| `sections[].children` | array | No | Nested sections (recursive) |
| `sections[].word_count` | integer | No | Word count for this section |

**Not yet validated** -- PG sources downloaded but not parsed.

---

### 6. `church_fathers` -- Verse-keyed patristic commentary quote

For: HistoricalChristianFaith/Commentaries-Database (58,675 records, 335+ authors)

```json
{
  "entry_id": "john-chrysostom.1Cor.10.1-5.homily-23",
  "author": "John Chrysostom",
  "anchor_ref": {
    "raw": "1 Corinthians 10:1-5",
    "osis": ["1Cor.10.1-1Cor.10.5"]
  },
  "quote": "\"That our fathers,\" saith he...",
  "source_title": "Homily on 1 Corinthians 23",
  "source_url": "",
  "attribution_note": null,
  "word_count": 42
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `entry_id` | string | Yes | `{author-slug}.{osis}.{source-slug}` |
| `author` | string | Yes | |
| `anchor_ref` | Reference | Yes | Raw + OSIS. Supports verse ranges |
| `quote` | string | Yes | Quote text |
| `source_title` | string | Yes | Title of the source work |
| `source_url` | string | No | May be empty |
| `attribution_note` | string/null | No | Replaces `append_to_author_name` |
| `word_count` | integer | Yes | |

**Changes from v1:** `book_osis` + `chapter` + `verse` (single verse only) replaced with `anchor_ref` (supports ranges). `append_to_author_name` renamed to `attribution_note`.

**Validated against:** `raw/Commentaries-Database/` -- confirmed verse ranges in filenames (e.g., `1 Corinthians 10_1-5.toml`)

---

### 7. `sermon` -- Individual sermon

For: Spurgeon (3,000+), Edwards, Wesley (141), Whitefield

```json
{
  "collection_id": "spurgeons-sermons",
  "sermon_id": "1",
  "title": "The Immutability Of God",
  "primary_reference": {
    "raw": "Malachi 3:6",
    "osis": ["Mal.3.6"]
  },
  "primary_reference_text": "I am the Lord, I change not...",
  "content_blocks": ["IT has been said by someone...", "Other subjects we can compass..."],
  "date_preached": "1855-01-07",
  "location": "New Park Street Chapel, London",
  "series": null,
  "word_count": 4250
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `collection_id` | string | Yes | Kebab-case |
| `sermon_id` | string | Yes | String -- handles numbered and unnumbered |
| `title` | string | Yes | |
| `primary_reference` | Reference/null | No | Raw + OSIS |
| `primary_reference_text` | string/null | No | BSB text of the scripture ref |
| `content_blocks` | array of strings | Yes | Paragraphs. Array when source supports paragraph breaks, single-element array otherwise |
| `date_preached` | string/null | No | ISO 8601 or null if unknown |
| `location` | string/null | No | |
| `series` | string/null | No | |
| `word_count` | integer | Yes | |

**Changes from v1:** Removed `summary*`, `key_quote`, `tags` (enrichment). Changed `content` to `content_blocks` (paragraphs). Changed `scripture_ref_osis` to Reference object. Made `date_preached`, `location`, `series` truly optional (omit when unknown, don't require null).

**Validated against:** Spurgeon sermon 1 from Kingdom Collective (title + scripture ref available, no date/location in HTML)

---

### 8. `devotional` -- Date-keyed daily reading

For: Spurgeon's Morning & Evening, Daily Light, Faith's Checkbook

```json
{
  "collection_id": "spurgeons-morning-evening",
  "entry_id": "01-01-morning",
  "month": 1,
  "day": 1,
  "period": "morning",
  "title": "January 1 -- Morning",
  "primary_reference": {
    "raw": "Genesis 1:1",
    "osis": ["Gen.1.1"]
  },
  "primary_reference_text": "In the beginning, God created the heavens and the earth.",
  "content_blocks": ["This is the first day of a new year...", "Let us begin it with God..."],
  "word_count": 412
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `collection_id` | string | Yes | Kebab-case |
| `entry_id` | string | Yes | `{MM}-{DD}-{period}` or `{MM}-{DD}` for single-reading |
| `month` | integer | Yes | 1-12 |
| `day` | integer | Yes | 1-31 |
| `period` | string/null | No | `"morning"`, `"evening"`, or null for single-reading |
| `title` | string | Yes | Display title |
| `primary_reference` | Reference/null | No | Raw + OSIS |
| `primary_reference_text` | string/null | No | BSB text |
| `content_blocks` | array of strings | Yes | Paragraphs |
| `word_count` | integer | Yes | |

**Changes from v1:** Removed `key_quote` (enrichment). Changed `content` to `content_blocks`. Changed `verse_ref_osis` to Reference object. Added `month`/`day` as integers alongside `entry_id` for easier querying.

---

### 9. `prayer` -- Standalone prayer text

For: Didache prayers, Puritan collected prayers, individual collects, standalone historical prayers. NOT liturgical services (see separate type, future).

```json
{
  "collection_id": "didache-prayers",
  "prayer_id": "9-cup",
  "title": "Eucharistic Prayer over the Cup",
  "incipit": "We thank thee, our Father...",
  "author": null,
  "year": null,
  "occasion": "Eucharist",
  "content_blocks": [
    "We thank thee, our Father, for the holy vine of David Thy servant, which Thou madest known to us through Jesus Thy Servant; to Thee be the glory for ever."
  ],
  "scripture_references": [],
  "context": {
    "work": "Didache",
    "location": "Chapter IX.2"
  },
  "word_count": 35
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `collection_id` | string | Yes | Kebab-case |
| `prayer_id` | string | Yes | Unique within collection |
| `title` | string/null | No | Formal title if one exists |
| `incipit` | string/null | No | Opening words -- used as identifier when no title exists |
| `author` | string/null | No | |
| `year` | integer/null | No | Year of composition |
| `occasion` | string/null | No | `"Morning Prayer"`, `"Eucharist"`, `"Confession"`, etc. |
| `content_blocks` | array of string | Yes | Prose paragraphs or sections. Use one string per natural paragraph/section. Reserve `stanzas[].lines[]` for `hymn` where lineation is authored structure |
| `scripture_references` | array of Reference | No | |
| `context` | object/null | No | `{work, location}` -- where this prayer comes from within a larger work |
| `word_count` | integer | Yes | |

**Changes from v1:** `content` (blob) replaced with `content_blocks[]` (prose-friendly). `stanzas[].lines[]` was considered but rejected -- most prayers are prose, not verse, and line breaks are transcription artifacts rather than authored structure (per Codex review). Added `incipit` for untitled prayers. Added `context` for prayers extracted from larger works. Removed `tags` (enrichment).

---

### 10. `reference_entry` -- Dictionary/encyclopedia term

For: Easton's Bible Dictionary, Smith's Bible Dictionary, Hitchcock's Names. NOT Torrey's (see `topical_reference`).

```json
{
  "dictionary_id": "eastons-bible-dictionary",
  "term": "Aaron",
  "alt_terms": ["Aharon"],
  "definition_blocks": [
    "The eldest son of Amram and Jochebed, a daughter of Levi...",
    "When the ransomed tribes fought their first battle..."
  ],
  "scripture_references": [
    {"raw": "Exod.6.16-20", "osis": ["Exod.6.16-Exod.6.20"]}
  ],
  "related_terms": ["Moses", "Levites", "Priesthood"],
  "word_count": 1240
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `dictionary_id` | string | Yes | Kebab-case |
| `term` | string | Yes | Headword |
| `alt_terms` | array of strings | No | Alternative forms/spellings. From SKOS `altLabel` pattern |
| `definition_blocks` | array of strings | Yes | Paragraph array. From Wiktextract/JWBickel source format |
| `scripture_references` | array of Reference | No | |
| `related_terms` | array of strings | No | Cross-referenced terms |
| `word_count` | integer | Yes | |

**Changes from v1:** `content` (string) replaced with `definition_blocks` (array) -- matches JWBickel source. Added `alt_terms` (from SKOS `altLabel`). Changed `scripture_references` to Reference objects.

---

### 11. `topical_reference` -- Topic-keyed verse index

For: Nave's Topical Bible, Torrey's New Topical Textbook

```json
{
  "index_id": "torreys-topical-textbook",
  "topic": "Access to God",
  "alt_topics": [],
  "subtopics": [
    {
      "label": "Is of God",
      "references": [
        {"raw": "Ps 65:4.", "osis": ["Ps.65.4"]}
      ]
    },
    {
      "label": "Is by Christ",
      "references": [
        {"raw": "Joh 10:7, 14:6", "osis": ["John.10.7", "John.14.6"]}
      ]
    }
  ],
  "related_topics": ["Prayer", "Faith"]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `index_id` | string | Yes | Kebab-case |
| `topic` | string | Yes | Primary topic label. SKOS `prefLabel` |
| `alt_topics` | array of strings | No | Alternative labels. SKOS `altLabel` |
| `subtopics` | array | Yes | Labeled groups of verse references |
| `subtopics[].label` | string | Yes | Subtopic heading |
| `subtopics[].references` | array of Reference | Yes | Raw + OSIS |
| `related_topics` | array of strings | No | Cross-referenced topic names. SKOS `related` |

**Changes from v1:** Removed required `topic_number`. Added `alt_topics` (SKOS). Changed `references` to Reference objects. Renamed `cross_references` to `related_topics` for clarity. Renamed `dictionary_id` to `index_id`.

---

### 12. `hymn` -- Individual hymn text

For: Pre-1928 public domain hymns. Schema informed by OpenLyrics standard and MusicBrainz Work/Instance model.

```json
{
  "collection_id": "olney-hymns",
  "hymn_id": "1:14",
  "book_number": 1,
  "hymn_number": 14,
  "title": "The triumph of faith; or, Christ's unchangeable love",
  "author": "William Cowper",
  "year": 1779,
  "metre": "C.M. (8.6.8.6)",
  "tune": "NEW BRITAIN",
  "scripture_references": [
    {"raw": "Rom. 8. 33 &c.", "osis": ["Rom.8.33-Rom.8.39"]}
  ],
  "stanzas": [
    {
      "number": 1,
      "type": "verse",
      "lines": [
        "Who shall the Lord's elect condemn?",
        "'Tis God that justifies their souls,",
        "And mercy like a mighty stream",
        "O'er all their sins divinely rolls."
      ]
    }
  ],
  "word_count": 180
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `collection_id` | string | Yes | Kebab-case (hymnal or collection) |
| `hymn_id` | string | Yes | Source numbering, e.g., `"1:14"` (book:hymn) |
| `book_number` | integer/null | No | Book/part within collection |
| `hymn_number` | integer | Yes | Hymn number within book or collection |
| `title` | string | Yes | |
| `author` | string/null | No | Per-hymn author when collection has multiple authors |
| `year` | integer/null | No | Year of composition |
| `metre` | string/null | No | Poetic metre |
| `tune` | string/null | No | Associated tune name. From OpenLyrics `<songbooks>` pattern |
| `scripture_references` | array of Reference | No | Raw + OSIS |
| `stanzas` | array | Yes | Ordered stanza array |
| `stanzas[].number` | integer | Yes | Stanza number |
| `stanzas[].type` | string | No | `"verse"`, `"chorus"`, `"bridge"`, `"refrain"`. From OpenLyrics verse naming |
| `stanzas[].lines` | array of strings | Yes | Lines as array. From PoetryDB/TEI pattern |
| `word_count` | integer | Yes | |

**Changes from v1:** `stanzas[].text` (string with `\n`) replaced with `stanzas[].lines` (array). Added `stanzas[].type` (OpenLyrics). Added `hymn_id` and `hymn_number` from source. Removed `source_hymnal` (redundant with `collection_id`). Removed `tags` (enrichment).

---

### 13. `liturgical_service` -- Structured worship order (FUTURE)

For: BCP 1662 Morning/Evening Prayer, Communion service

This schema type is defined directionally but not finalized. Real data from BCP 1662 shows this needs: ordered elements, rubrics, speaker roles, alternatives, call/response support. Informed by Fountain screenplay format (typed elements with speaker attribution).

**Status:** Deferred until a parser is built for BCP source material.

---

## Enrichment Layer (Separate from Source)

Enrichment records live in `sources/{resource}/enrichment/` and are joined to source records by `entry_id` at build time.

```json
{
  "entry_id": "matthew-henry-complete.Ezek.1.1-3",
  "summary": "Henry introduces Ezekiel as a priest-turned-prophet...",
  "summary_review_status": "ai-generated-spot-checked",
  "summary_source_span": "paragraphs 1-3",
  "summary_reviewer": null,
  "key_quote": "It was the honour of Ezekiel that he had his business...",
  "key_quote_source_span": "paragraph 2, sentence 7",
  "key_quote_selection_criteria": "Most concise statement of the chapter's central theological claim",
  "tags": ["exile", "prophetic call", "Babylon"]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `entry_id` | string | Yes | Matches source record's `entry_id` |
| `summary` | string/null | No | AI-generated summary |
| `summary_review_status` | string | Yes | `"withheld"`, `"ai-generated-unreviewed"`, `"ai-generated-spot-checked"`, `"ai-generated-seminary-reviewed"`, `"human-written"` |
| `summary_source_span` | string/null | No | Which part of the source the summary covers |
| `summary_reviewer` | object/null | No | `{reviewer_id, credentials, review_date, review_notes}` |
| `key_quote` | string/null | No | |
| `key_quote_source_span` | string/null | No | |
| `key_quote_selection_criteria` | string/null | No | |
| `tags` | array of strings | No | Topic tags |

**Enrichment metadata** (generation model, prompt version, date) lives in the enrichment file's own metadata envelope, not on each record.

---

## Derived Exports

The build pipeline joins source + enrichment and denormalizes for downstream consumers:

| Format | Audience | What's different from source JSON |
|--------|---------|----------------------------------|
| **SQLite** | Developers, app builders | Provenance flattened per-row. Enrichment joined. Foreign keys across tables |
| **Parquet** | ML/AI training, HuggingFace | Provenance flattened per-row. Enrichment joined. One table per schema type |
| **CSV** | Non-developers, spreadsheet users | Flattened, simplified |
| **Plain text** | AI training pipelines | Just the text, no metadata |

Per-row provenance (which the Codex red team flagged as too aggressive for source JSON) is correct in these derived formats. HuggingFace dataset cards need per-row licensing. The source JSON stays clean; the exports carry the noise.

---

## Verse Hub Index (Build-Time Derivation)

The verse is the universal join key across all schema types. The verse hub aggregates every reference to every verse across all resources into a single lookup:

```json
{
  "osis": "Rom.3.28",
  "book_osis": "Rom",
  "chapter": 3,
  "verse": 28,
  "references": [
    {
      "resource_id": "matthew-henry-complete",
      "schema_type": "commentary",
      "entry_id": "matthew-henry-complete.Rom.3.21-31",
      "role": "anchor"
    },
    {
      "resource_id": "westminster-confession",
      "schema_type": "doctrinal_document",
      "unit_path": "chapter.11.section.1",
      "role": "proof_text"
    },
    {
      "resource_id": "john-chrysostom",
      "schema_type": "church_fathers",
      "entry_id": "john-chrysostom.Rom.3.28.homily-7",
      "role": "anchor"
    },
    {
      "resource_id": "spurgeons-sermons",
      "schema_type": "sermon",
      "entry_id": "spurgeons-sermons.142",
      "role": "primary_text"
    },
    {
      "resource_id": "naves-topical-bible",
      "schema_type": "topical_reference",
      "topic": "Justification",
      "role": "reference"
    }
  ],
  "reference_count": 5,
  "tradition_coverage": ["reformed", "puritan", "patristic", "baptist"],
  "era_coverage": ["patristic", "reformation", "post-reformation", "modern"]
}
```

**Role vocabulary:**
- `"anchor"` -- this verse is the primary subject of the entry (commentary, church father quote)
- `"proof_text"` -- this verse is cited as evidence for a doctrinal claim
- `"primary_text"` -- this verse is the sermon/devotional's primary scripture
- `"reference"` -- this verse is referenced within the entry
- `"cross_reference"` -- this verse appears in a cross-reference list

**Published as:** `dist/verse_hub.json` (full) and `dist/verse_hub.sqlite` (queryable). Not a schema type -- a build output derived from all resources.

**Why this matters for LLM training:** For any verse, a model can retrieve multi-perspective commentary spanning traditions and centuries. This is the foundation for a specialist Christian LLM that understands theological diversity, not just the majority view.

---

## Canonical Verse Index

Validation currently pattern-matches OSIS refs but cannot verify that a reference resolves to a real verse. `Ezek.48.36` exists; `Ezek.48.40` does not.

**Source:** Derived from BSB data (already on disk). One entry per verse in the Protestant canon (31,102 verses).

```json
{
  "osis": "Gen.1.1",
  "book": "Genesis",
  "book_osis": "Gen",
  "book_number": 1,
  "chapter": 1,
  "verse": 1,
  "chapter_verse_count": 31,
  "book_chapter_count": 50
}
```

**Published as:** `build/bible_data/verse_index.json`. Used by validation pipeline to reject invalid OSIS references. Also used by verse hub construction.

---

## Author Registry

Authors appear across schema types. Spurgeon has sermons, devotionals, and a commentary. Calvin has a commentary and the Institutes. An author registry enables author-consistent retrieval, tradition-aware filtering, and future influence graph construction.

**Location:** `data/authors/registry.json`

```json
{
  "authors": [
    {
      "author_id": "charles-spurgeon",
      "name": "Charles Haddon Spurgeon",
      "alt_names": ["C.H. Spurgeon", "The Prince of Preachers"],
      "birth_year": 1834,
      "death_year": 1892,
      "era": "modern",
      "tradition": ["reformed", "baptist"],
      "nationality": "English",
      "resources_in_dataset": [
        "spurgeons-sermons",
        "spurgeons-morning-evening",
        "treasury-of-david"
      ],
      "influenced_by": ["john-calvin", "john-bunyan", "puritan-tradition"],
      "contemporaries": ["d-l-moody", "j-c-ryle"]
    },
    {
      "author_id": "matthew-henry",
      "name": "Matthew Henry",
      "alt_names": [],
      "birth_year": 1662,
      "death_year": 1714,
      "era": "post-reformation",
      "tradition": ["reformed", "puritan", "nonconformist"],
      "nationality": "Welsh",
      "resources_in_dataset": ["matthew-henry-complete"],
      "influenced_by": ["philip-henry", "puritan-tradition"],
      "contemporaries": []
    }
  ]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `author_id` | string | Yes | Kebab-case canonical ID. Referenced by envelope `author_id` field |
| `name` | string | Yes | Canonical full name |
| `alt_names` | array of strings | No | Alternative names, titles, honorifics |
| `birth_year` | integer/null | No | |
| `death_year` | integer/null | No | |
| `era` | string | No | Same enum as envelope |
| `tradition` | array of strings | No | Same enum as envelope |
| `nationality` | string/null | No | |
| `resources_in_dataset` | array of strings | Yes | Resource IDs of their works in OCD |
| `influenced_by` | array of strings | No | Author IDs or tradition labels. Enrichment -- populated over time |
| `contemporaries` | array of strings | No | Author IDs |

**Build-time validation:** Every `author_id` referenced in a metadata envelope must resolve to an entry in the registry. Every `resources_in_dataset` entry must resolve to an actual resource.

**Not built now.** Populated incrementally as resources are added. First entries created when Matthew Henry and BSB are the only resources.

---

## ML Infrastructure (Build-Time Exports)

These are derived outputs optimized for ML/AI consumers. Not schema types -- build pipeline products.

### Text-for-Embedding Field

Published in Parquet/HF exports. A flat, clean text field per record stripped of reference markers, inline citations, and formatting noise. Optimized for vector search and RAG.

| Schema type | `text_for_embedding` contents |
|-------------|------------------------------|
| `commentary` | `commentary_text` with inline `[N]` markers stripped |
| `sermon` | `content_blocks` joined, cleaned |
| `devotional` | `content_blocks` joined, cleaned |
| `catechism_qa` | `"Q: {question} A: {answer}"` |
| `church_fathers` | `quote` text |
| `reference_entry` | `definition_blocks` joined |
| `prayer` | `content_blocks` joined |
| `hymn` | `stanzas[].lines` joined |

### Reading Complexity Score

Flesch-Kincaid grade level computed at build time. Published in Parquet exports.

| Author | Typical FK Grade |
|--------|-----------------|
| Spurgeon | ~8-10 (accessible) |
| Matthew Henry | ~12-14 (educated lay) |
| Calvin | ~14-16 (advanced) |
| Hodge | ~16-18 (seminary) |
| Church Fathers (translated) | Varies widely |

Enables filtering: "give me only commentary that a lay reader can follow."

### Instruction-Tuning Pairs (Future -- Requires Theological Review)

Commentary and catechism data naturally form instruction pairs. **This is a future project requiring careful theological review** -- not a mechanical format conversion.

| Schema type | Natural pair shape | Theological sensitivity |
|-------------|-------------------|----------------------|
| `commentary` | "Explain [verse]" -> [commentary] | Medium -- tradition-specific interpretations |
| `catechism_qa` | [question] -> [answer] | High -- doctrinal precision matters |
| `church_fathers` | "What did [author] say about [verse]?" -> [quote] | Medium -- attribution accuracy |
| `reference_entry` | "Define [term]" -> [definition] | Low -- factual/historical |
| `sermon` | "Preach on [verse]" -> [sermon] | High -- pastoral voice, theological stance |

**Not published until:** A theological review framework is defined, and the instruction format is validated against actual fine-tuning results.

### Cross-Reference Graph

Published as `dist/graph/cross_references.csv`:

```csv
source_osis,target_osis,resource_id,schema_type,relationship
Ezek.1.1,Jer.29.1,matthew-henry-complete,commentary,cross_reference
Rom.3.28,Gal.2.16,westminster-confession,doctrinal_document,proof_text_sibling
```

Enables graph ML: verse similarity via node2vec, GNN, knowledge graph construction. No other dataset has a multi-resource biblical cross-reference graph.

---

## Open Issues

### #1: Migrate existing ezekiel.json to v2 schema
The existing `data/commentaries/matthew-henry/ezekiel.json` uses v1 schema (no `anchor_ref`, no `commentary_type`, has `summary*` and `key_quote*` fields). Migration needed but not blocking -- v1 data is valid and published.

### #2: Metadata envelope JSON Schema
Need to create `schemas/v2/meta.schema.json` with optional `scope` object. Current `schemas/v1/commentary.schema.json` inlines the envelope.

### #3: Heidelberg Lord's Day mapping
Not in Creeds.json source. Must be hardcoded in parser as a mapping table. Well-defined (canonical groupings) but parser adds structure not in source.

### #4: HenrysCatechism sub_questions
Three documents use `SubQuestions` arrays. Handled by optional `sub_questions` in `catechism_qa`.

### #5: Liturgical service schema
Deferred. BCP 1662 data downloaded but schema design needs more work. Fountain/FDX patterns identified as structural inspiration.

### #6: Build canonical verse index from BSB
Need `build/bible_data/verse_index.json` derived from BSB data. Required for OSIS reference validation and verse hub construction.

### #7: Author registry bootstrap
Create `data/authors/registry.json` with initial entries for Matthew Henry and BSB contributor metadata. Populate incrementally.

### #8: Token count pipeline
Add `tiktoken` (cl100k_base) computation to build pipeline. Publish `token_count` alongside `word_count` in all records and exports.

### #9: Content hash implementation
Define normalization rules for `content_hash`: lowercase, collapse whitespace, strip punctuation, NFC normalize, then SHA-256. Document in build pipeline.

### #10: Lectionary schema (future)
Liturgical calendar -> scripture reading mappings (e.g., Revised Common Lectionary). Small dataset, high utility. Design when liturgical content work begins.

---

## Schema Type Summary

| # | Schema Type | Replaces (v1) | Record Count (est.) | Source Status |
|---|-------------|---------------|-------------------|---------------|
| 1 | `bible_text` | -- | ~31,102 | On disk |
| 2 | `commentary` | -- | 132+ | Partial on disk |
| 3 | `doctrinal_document` | `confession` | ~35 documents | On disk |
| 4 | `catechism_qa` | -- | ~500+ | On disk |
| 5 | `structured_text` | `catechism_prose` + `theological_work` | TBD | Downloaded, not parsed |
| 6 | `church_fathers` | -- | ~58,675 | On disk |
| 7 | `sermon` | -- | TBD | Partial download |
| 8 | `devotional` | -- | ~730 | Not extracted |
| 9 | `prayer` | -- | TBD | Downloaded |
| 10 | `reference_entry` | -- | ~11,763 | Downloaded |
| 11 | `topical_reference` | -- | ~20,000 | Not acquired |
| 12 | `hymn` | -- | TBD | Downloaded |
| 13 | `liturgical_service` | *(new, deferred)* | TBD | Downloaded, schema TBD |

---

## Standards Referenced

| Standard | What we took | URL |
|----------|-------------|-----|
| OSIS | Verse reference format | crosswire.org/osis/ |
| SWORD .conf | Metadata field vocabulary | wiki.crosswire.org/DevTools:conf_Files |
| OpenLyrics | Hymn stanza types, verse naming | docs.openlyrics.org |
| Akoma Ntoso | Flexible document hierarchy, revision tracking | docs.oasis-open.org/legaldocml/ |
| W3C Web Annotation | Commentary type/motivation vocabulary | w3.org/TR/annotation-model/ |
| SKOS | Multi-label terms, topic relationships | w3.org/TR/skos-reference/ |
| MusicBrainz | Work/Instance separation concept | musicbrainz.org/doc/MusicBrainz_Database/Schema |
| TEI P5 (Verse, Dictionary) | Line-level granularity, sense nesting | tei-c.org/guidelines/ |
| PoetryDB | Lines-as-arrays pattern | poetrydb.org |
| Wiktextract | JSONL dictionary format, paragraph arrays | github.com/tatuylonen/wiktextract |
| Fountain | Typed elements for dialogue/scripts | fountain.io/syntax/ |
| Atom RFC 4287 | Content type declaration | ietf.org/rfc/rfc4287 |
