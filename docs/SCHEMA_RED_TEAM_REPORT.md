# Open Christian Data -- Schema Red Team Report

**Date:** 2026-03-27  
**Scope reviewed:** `docs/SCHEMA_RED_TEAM_BRIEF.md`, `docs/SCHEMA_SPEC.md`, `schemas/types.ts`, `schemas/v1/commentary.schema.json`, `data/commentaries/matthew-henry/ezekiel.json`, `raw/Creeds.json`, `raw/Commentaries-Database`, `raw/bible_databases/formats/json/BSB.json`, and the source samples in `raw/samples/`.

---

## Executive Verdict

The current schema direction is strongest when it stays close to the source and weakest when it tries to be a denormalized analytics table, a source-faithful archive, and an AI-enrichment layer all at once.

The biggest problems are:

1. Required per-record provenance is too aggressive for source JSON and creates massive repetition.
2. Core schemas are carrying enrichment fields (`summary`, `key_quote`, `tags`, reviewer metadata) that do not belong in the primary source model.
3. Several schemas are designed around ideal data rather than the data actually in hand.
4. OSIS is valuable as a normalized representation, but storing only OSIS loses source fidelity for messy or ambiguous references.
5. The current set over-splits `catechism_prose` from `theological_work` and under-fits `confession`.

My recommendation is to treat the published JSON resource as the source-faithful canonical form, and then derive denormalized SQLite/Parquet/HuggingFace rows from it.

---

## Cross-Cutting Findings

### 1. The spec is mixing three layers that should be separate

Right now the schemas blend:

- source-faithful text structure
- denormalized row fields for table exports
- AI or parser enrichment

Those are different concerns. A clean model is:

1. Canonical resource JSON: faithful to the source, minimal duplication.
2. Derived tabular exports: denormalized for SQL/Parquet/HF convenience.
3. Optional enrichment layer: summaries, key quotes, tags, extracted cross-references.

### 2. Per-record provenance should be an override, not a universal requirement

For most corpora in this repo, `source_license`, `source_url`, and `translation_year` are constant across the whole file or even the whole collection. Repeating them on every record bloats output and adds noise without adding truth.

Use resource-level provenance by default. Add record-level provenance only when a record actually differs from its parent resource.

Recommended pattern:

```json
{
  "meta": {
    "license": "public-domain",
    "source": {
      "url": "https://www.gutenberg.org/ebooks/1722",
      "translation_year": 1921
    }
  },
  "data": [
    {
      "id": "chapter-1",
      "provenance_override": null
    }
  ]
}
```

### 3. Preserve raw references alongside normalized OSIS

OSIS is worth keeping, but it should not be the only representation.

Why:

- BCP uses forms like `Psalm li. 3.`
- Watts uses `Rom. 8. 33 &c.`
- Heidelberg sample includes malformed combined references like `1Cor.6.19,1Cor.6.2`
- some sources may only be partially parseable

Recommended pattern:

```json
{
  "reference": {
    "raw": "Rom. 8. 33 &c.",
    "osis": ["Rom.8.33-Rom.8.39"]
  }
}
```

### 4. Required null-heavy fields are a smell

The following are null or absent in many corpora and should not be mandatory in the canonical schema:

- `summary`
- `summary_review_status`
- `summary_source_span`
- `summary_reviewer`
- `key_quote`
- `key_quote_source_span`
- `key_quote_selection_criteria`
- `tags`
- `date_preached`
- `location`
- `series`
- `lords_day`
- `part`
- `topic_number`
- `metre`
- `tune`

If a field is not in the source and is not consistently available, make it optional or move it to enrichment.

### 5. The metadata envelope needs a base form plus extensions

The current metadata design still assumes verse-aware fields even for non-verse corpora. Use:

- a base resource envelope for all corpora
- a verse-aware extension only for verse-keyed types

### 6. License values are inconsistent across the repo

There is already an inconsistency between docs and code:

- `SCHEMA_SPEC.md` uses `public_domain` and `unlicense`
- `schemas/types.ts` uses `public-domain`
- `schemas/v1/commentary.schema.json` does not allow `unlicense`

This needs a single canonical enum before more schemas are published.

Recommended canonical style:

```json
["cc0-1.0", "public-domain", "unlicense", "cc-by-4.0", "cc-by-sa-4.0"]
```

---

## Direct Answers to the Brief Questions

### 1. Are there schema types that should be merged?

Yes.

- Merge `catechism_prose` into `theological_work`.
- More precisely, replace both with one prose/hierarchical text schema. Luther's Large Catechism is a theological prose work with catechetical purpose, not a fundamentally different structural type.

Do not merge:

- `prayer` and `liturgical_service`
- `reference_entry` and `topical_reference`
- `commentary` and `church_fathers`

### 2. Are there schema types that should be split?

Not by multiplying tiny schemas for every doctrinal subtype. The better move is to redesign `confession` as a hierarchical doctrinal document schema that can represent:

- chapter -> section -> proofs
- article -> content
- single creed text

The split that does matter is conceptual:

- core source schema
- enrichment schema

### 3. Is per-record provenance the right granularity?

No, not as a universal rule.

Use resource-level provenance by default. Add optional record-level overrides only where needed. Then denormalize provenance into downstream table exports if HuggingFace or SQL consumers need every row to carry it.

### 4. Should `prayer` model individual prayers or liturgical services?

Individual prayers only. Liturgical services need a separate schema with ordered elements, rubrics, speakers, optional branches, and call/response handling.

### 5. Should `reference_entry.content` be a string or array of strings?

Array of strings, or better, `definition_blocks`.

Easton's data is already paragraph-array based. Flattening it loses structure for no gain.

### 6. Are there unnecessary fields that will be null for most records?

Yes. The biggest offenders are enrichment fields and idealized descriptive fields that the sources do not actually supply.

### 7. Is OSIS the right choice?

As a normalized target, yes. As the only stored representation, no.

Store both raw and normalized references when references come from messy historical sources.

### 8. Should schemas be designed for the data we have, or ideal data we might get?

For the data we have.

Then add optional normalized/enriched fields where they can be derived reliably. Designing for hypothetical future richness is what caused several of the current mismatches.

### 9. Where is the current schema over-engineered or a bad fit?

Main mismatches:

- `confession` does not fit flat canons or single-block creeds.
- `catechism_qa` assumes integer numbering but Henry uses `1a`, `1b`.
- `church_fathers` assumes single verses, but actual files include verse ranges.
- `reference_entry` assumes one string but Easton's is paragraph-array based.
- `topical_reference` assumes labeled subtopics and topic numbers that Torrey's does not supply.
- `hymn` assumes tune/metre/author/year per hymn that the sample source does not provide.
- `sermon` assumes date/location/series data that the sample source does not provide.

### 10. Proposed schema designs?

See the next section.

---

## Recommended V2 Schema Set

I would keep the overall corpus split, but revise it to this set:

1. `bible_text`
2. `commentary`
3. `doctrinal_document` (replaces `confession`)
4. `catechism_qa`
5. `structured_text` (replaces `catechism_prose` and `theological_work`)
6. `church_fathers`
7. `sermon`
8. `devotional`
9. `prayer`
10. `liturgical_service`
11. `reference_entry`
12. `topical_reference`
13. `hymn`

That keeps the conceptual count stable while removing the one unnecessary split and fixing the biggest under-fit.

---

## Proposed Schemas by Type

### 1. `bible_text`

**Verdict:** Mostly fine, but too repetitive if each output file is scoped to one book.

If the resource file is one book per file, the record does not need `book`, `book_osis`, and `book_number` on every row.

Recommended record:

```json
{
  "osis": "Gen.1.1",
  "chapter": 1,
  "verse": 1,
  "text": "In the beginning God created the heavens and the earth."
}
```

Notes:

- trim source whitespace during ingestion
- keep translation metadata at resource level
- if a book-scoped file is guaranteed, `osis` could even be optional and derived

### 2. `commentary`

**Verdict:** Core idea is good; current form is carrying too much enrichment baggage.

Recommended record:

```json
{
  "entry_id": "matthew-henry-complete.Ezek.1.1-3",
  "anchor_ref": {
    "raw": "Ezekiel 1:1-3",
    "osis": "Ezek.1.1-Ezek.1.3"
  },
  "verse_text": "In the thirtieth year...",
  "commentary_text": "The circumstances of the vision...",
  "cross_references": [],
  "provenance_override": null
}
```

Changes:

- move `summary*` and `key_quote*` out of the core schema
- keep `verse_text` optional because it is derived from BSB, not source
- use a unified reference object instead of separate `chapter`, `verse_range`, `verse_range_osis`
- if files stay book-scoped, move repeated book metadata to `meta.scope`

### 3. `doctrinal_document`

**Verdict:** This should replace the current `confession` schema.

The real problem is not that confessions need three schemas. The problem is that they need a tree.

Recommended resource shape:

```json
{
  "document_id": "westminster-confession",
  "document_kind": "confession",
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
                { "raw": "Ps.19.1-Ps.19.3", "osis": ["Ps.19.1-Ps.19.3"] }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

Belgic then becomes:

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

Apostles' Creed becomes:

```json
{
  "document_id": "apostles-creed",
  "document_kind": "creed",
  "units": [
    {
      "unit_type": "creed_text",
      "number": "1",
      "content": "I believe in God..."
    }
  ]
}
```

### 4. `catechism_qa`

**Verdict:** Keep, but fix numbering and grouping assumptions.

Recommended record:

```json
{
  "item_id": "1",
  "sort_key": 1,
  "question": "What is the chief end of man?",
  "answer": "Man's chief end is to glorify God, and enjoy him forever.",
  "answer_with_proofs": null,
  "proofs": [],
  "sub_questions": [
    {
      "item_id": "1a",
      "question": "Is man a reasonable creature?",
      "answer": "Yes: For there is a spirit in man..."
    }
  ],
  "group": null
}
```

Changes:

- `question_number` should not be integer-only
- use string `item_id` plus numeric `sort_key`
- add optional `sub_questions`
- `group` can carry `Lord's Day` or `part` when source-backed or parser-mapped
- preserve raw proof references alongside normalized OSIS when needed

### 5. `structured_text`

**Verdict:** This should replace both `catechism_prose` and `theological_work`.

Recommended resource shape:

```json
{
  "work_id": "calvins-institutes",
  "work_kind": "theological-work",
  "sections": [
    {
      "section_type": "book",
      "label": "Book II",
      "title": "On The Knowledge Of God The Redeemer In Christ...",
      "children": [
        {
          "section_type": "chapter",
          "label": "Chapter VIII",
          "title": "An Exposition Of The Moral Law",
          "children": [
            {
              "section_type": "subsection",
              "label": "The First Commandment",
              "content_blocks": ["Paragraph 1...", "Paragraph 2..."]
            }
          ]
        }
      ]
    }
  ]
}
```

For Luther's Large Catechism:

```json
{
  "work_id": "luthers-large-catechism",
  "work_kind": "catechism-prose",
  "sections": [
    {
      "section_type": "part",
      "label": "The Ten Commandments",
      "children": [
        {
          "section_type": "chapter",
          "label": "The First Commandment",
          "content_blocks": ["A god is that to which we look...", "..."]
        }
      ]
    }
  ]
}
```

Changes:

- store paragraphs/blocks, not one giant chapter string
- support nested subdivisions
- keep translator metadata at resource level
- move summary and key-quote fields to enrichment

### 6. `church_fathers`

**Verdict:** Keep, but the current single-verse model is too narrow.

The actual files include verse ranges such as `1 Corinthians 10_1-5.toml` and `1 Chronicles 12_17-18.toml`.

Recommended record:

```json
{
  "entry_id": "john-chrysostom.1cor.10.1-5.homily-23",
  "author": "John Chrysostom",
  "anchor_ref": {
    "raw": "1 Corinthians 10:1-5",
    "osis": "1Cor.10.1-1Cor.10.5"
  },
  "quote": "\"That our fathers,\" saith he...",
  "source": {
    "title": "Homily on 1 Corinthians 23",
    "url": "https://historicalchristian.faith/by_father.php?file=..."
  },
  "attribution_suffix": null
}
```

Changes:

- replace `book_osis` + `chapter` + `verse` with `anchor_ref`
- rename `append_to_author_name` to a more generic attribution field
- keep one record per `[[commentary]]` entry
- explicitly document that book directories and author directories are different source layouts

### 7. `sermon`

**Verdict:** Keep, but strip it back to what the source actually provides.

Recommended record:

```json
{
  "sermon_id": "1",
  "title": "The Immutability Of God",
  "primary_reference": {
    "raw": "Malachi 3:6",
    "osis": ["Mal.3.6"]
  },
  "primary_reference_text": "I am the Lord, I change not...",
  "content_blocks": [
    "IT has been said by someone...",
    "Other subjects we can compass..."
  ]
}
```

Changes:

- `date_preached`, `location`, and `series` should be optional and omitted when unknown
- `tags` should be enrichment
- preserve raw heading reference and normalized OSIS separately
- store sermon body as blocks, not only one huge string

### 8. `devotional`

**Verdict:** Probably distinct enough to keep, but keep it lean until the real extraction exists.

Recommended record:

```json
{
  "entry_id": "01-01-morning",
  "month": 1,
  "day": 1,
  "period": "morning",
  "title": "January 1 -- Morning",
  "primary_reference": {
    "raw": "Genesis 1:1",
    "osis": ["Gen.1.1"]
  },
  "content_blocks": ["Devotional text..."]
}
```

Notes:

- `key_quote` should not be core
- use numeric day/month or a stable key; either is fine
- allow `period` to be optional for single-reading devotionals

### 9. `prayer`

**Verdict:** Keep, but only for standalone prayers or extracted prayer units.

Recommended record:

```json
{
  "prayer_id": "didache-9-cup",
  "title": "Concerning the Cup",
  "incipit": "We thank thee, our Father...",
  "occasion": "Eucharist",
  "content_blocks": [
    "We thank thee, our Father, for the holy vine..."
  ],
  "context": {
    "work": "Didache",
    "location": "Chapter IX.2"
  }
}
```

Changes:

- use `incipit` when no formal title exists
- `author` and `year` should stay optional
- `tags` should be enrichment

### 10. `liturgical_service`

**Verdict:** Necessary separate schema.

Recommended resource shape:

```json
{
  "service_id": "bcp-1662-morning-prayer",
  "title": "The Order for Morning Prayer",
  "elements": [
    {
      "sequence": 10,
      "element_type": "section_heading",
      "label": "Sentences of Scripture"
    },
    {
      "sequence": 20,
      "element_type": "rubric",
      "text": "At the beginning of Morning Prayer..."
    },
    {
      "sequence": 30,
      "element_type": "sentence",
      "text": "When the wicked man turneth away...",
      "references": [
        { "raw": "Ezek. xviii. 27.", "osis": ["Ezek.18.27"] }
      ]
    },
    {
      "sequence": 40,
      "element_type": "prayer",
      "label": "General Confession",
      "speaker": "congregation",
      "text": "Almighty and most merciful Father..."
    },
    {
      "sequence": 50,
      "element_type": "response_pair",
      "speaker": "minister",
      "text": "O Lord, open thou our lips.",
      "response_text": "And our mouth shall show forth thy praise."
    }
  ]
}
```

Key requirements:

- ordered sequence
- rubrics
- speaker roles
- optional alternatives
- call/response support
- section boundaries

### 11. `reference_entry`

**Verdict:** Keep, but make it paragraph-array based and dictionary-only.

Recommended record:

```json
{
  "term": "Aaron",
  "definition_blocks": [
    "The eldest son of Amram and Jochebed...",
    "When the ransomed tribes fought their first battle..."
  ]
}
```

Changes:

- replace `content` with `definition_blocks`
- move extracted scripture refs and related terms to enrichment
- do not force Torrey's into this schema

### 12. `topical_reference`

**Verdict:** Keep separate, but redesign around the actual Torrey shape.

Recommended record:

```json
{
  "topic": "Access to God",
  "lines": [
    {
      "text": "Is of God",
      "reference": {
        "raw": "Ps 65:4.",
        "osis": ["Ps.65.4"]
      }
    },
    {
      "text": "Is by Christ",
      "reference": {
        "raw": "Joh 10:7, 14:6, Eph 2:13, 3:12, Heb 7:19,25, 10:19,20.",
        "osis": [
          "John.10.7",
          "John.14.6",
          "Eph.2.13",
          "Eph.3.12",
          "Heb.7.19",
          "Heb.7.25",
          "Heb.10.19",
          "Heb.10.20"
        ]
      }
    }
  ]
}
```

Changes:

- remove required `topic_number`
- replace `subtopics` with `lines` or `claims`
- keep `cross_references` optional and derived

### 13. `hymn`

**Verdict:** Keep, but use source-faithful hymn metadata rather than ideal hymnology metadata.

Recommended record:

```json
{
  "hymn_id": "1:14",
  "book_number": 1,
  "hymn_number": 14,
  "title": "The triumph of faith; or, Christ's unchangeable love",
  "scripture_references": [
    {
      "raw": "Rom. 8. 33 &c.",
      "osis": ["Rom.8.33-Rom.8.39"]
    }
  ],
  "stanzas": [
    {
      "number": 1,
      "lines": [
        "Who shall the Lord's elect condemn?",
        "'Tis God that justifies their souls,",
        "And mercy like a mighty stream",
        "O'er all their sins divinely rolls."
      ]
    }
  ]
}
```

Changes:

- `tune`, `metre`, `year`, and per-hymn `author` should be optional only when present
- add structured hymn numbering from the source
- store stanza lines as arrays or keep stanza text with line breaks; either works

---

## Immediate Changes I Would Make Before Publishing More Schemas

1. Canonicalize license enums across docs, TypeScript, and JSON Schema.
2. Stop requiring universal per-record provenance in the canonical JSON format.
3. Move summaries, key quotes, tags, and reviewer metadata into an enrichment layer.
4. Replace `confession` with a hierarchical `doctrinal_document`.
5. Merge `catechism_prose` and `theological_work` into `structured_text`.
6. Change `church_fathers` to support verse ranges.
7. Change `reference_entry.content` to `definition_blocks`.
8. Change `topical_reference` to reflect Torrey's actual line-based structure.
9. Add `raw` plus normalized reference fields anywhere biblical citations are parsed.
10. Treat JSON resource files and SQLite/Parquet rows as separate modeling targets.

---

## Bottom Line

The project is directionally right, but the current spec is trying to standardize too early and too hard.

If you optimize the canonical JSON for source fidelity first, most of the current pain disappears:

- fewer fake nulls
- less repeated provenance
- better fit for historical sources
- cleaner downstream derivations

If you keep the current approach, the repo will accumulate schemas that are technically valid but semantically awkward, and each new parser will end up doing schema-shaped guesswork instead of source-shaped extraction.
