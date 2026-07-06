---
license: cc0-1.0
language:
- en
pretty_name: Open Christian Data
size_categories:
- 100K<n<1M
task_categories:
- text-generation
- question-answering
- text-classification
- feature-extraction
tags:
- christian
- theology
- bible
- commentary
- sermon
- catechism
- confession
- church-fathers
- public-domain
- religion
configs:
- config_name: original
  data_files:
    - path: original/records.jsonl
      split: train
- config_name: modernised
  data_files:
    - path: modernised/records.jsonl
      split: train
---

# Open Christian Data

A free, structured dataset of public domain Christian literature — Bible text, commentaries, sermons, catechisms, confessions, theology, prayer, and reference works, all formatted as clean, consistent records with full provenance metadata. Intentionally designed for developers and AI/LLM training.

All content is written by authors who died before 1928. All texts are in the public domain. The dataset is CC0.

## What `original` means here (R60)

`original` and `modernised` split on spelling and morphology, not script. Both configs are Latin-script throughout because transliteration is applied under ADR-0009. Original-script bytes, including Greek and Hebrew script, are preserved per segment in `language_segments[].original_script`; consumers that need the source's printed bytes should read `language_segments`.

## Schemas (R64)

The `original` config uses `schemas/v1/reconciled_record.schema.json`. The `modernised` config uses `schemas/v1/modernised_record.schema.json`.

## Modernisation coverage (R65)

Modernise is optional under ADR-0003. A work present in `original` but absent from `modernised` is a deliberate omission for the current release, not an implied missing upload.

| work_handle | original | modernised | rationale |
|---|---|---|---|
| reference/schaff/encyclopedia/1908-1914 | present | absent | R43 — Modernise corpus-application deferred to Phase 2 |
<!-- R65_TABLE_ROWS -->

## What's included

| Config | Description | Size |
|---|---|---|
| `commentary` | Verse-by-verse commentary on the Bible | 113,585 entries across 10 commentaries |
| `church_fathers` | Verse-anchored quotes from 325 patristic and medieval authors | 70,164 quotes |
| `structured_text` | Full-text theological works — Owen, Calvin, Hodge, Spurgeon, Bunyan, and 160+ more | 165 works |
| `sermon` | Individual sermons from 7 collections | 5,299 sermons (Spurgeon, Maclaren, Wesley, Luther, Newman, Whitefield, MacDonald) |
| `catechism` | Q&A catechisms from 15 traditions | Westminster, Heidelberg, Baltimore, Luther, and more |
| `doctrinal_document` | Creeds, confessions, and statements | 37 documents (Westminster, Belgic, Dort, Nicene, Chalcedonian...) |
| `reference` | Bible dictionaries and encyclopedias | 30,155 entries (Easton's, Smith's, Schaff-Herzog...) |
| `topical_reference` | Topic-keyed scripture indexes | 5,945 topics (98,500+ scripture references) |
| `devotional` | Date-keyed devotional readings | 1,464 entries (Spurgeon M&E, Daily Light) |
| `prayer` | Collected prayers | 205 prayers (BCP 1662, BCP 1928, Andrewes, Didache) |
| `bible_text` | Bible text | 31,086 verses (BSB, CC0) |

## Loading the data

```python
from datasets import load_dataset

# Load a single config
original = load_dataset("OpenChristianData/open-christian-data", "original")
modernised = load_dataset("OpenChristianData/open-christian-data", "modernised")

# Filter to a specific author
wesley = [r for r in modernised["train"] if r["meta"]["author_slug"] == "wesley"]

# Filter to works with no modernised sibling by reading the coverage table above
```

## Data structure

Every record is a flattened row combining the resource-level metadata with entry-level fields. Key fields present on all records:

| Field | Description |
|---|---|
| `_source_id` | Unique identifier for the parent resource (e.g., `matthew-henry-complete`) |
| `entry_id` | Unique identifier for this entry (e.g., `matthew-henry-complete.Ezek.1.1-3`) |
| `author` | Author name |
| `tradition` | Array of theological tradition labels (e.g., `["reformed", "puritan"]`) |
| `era` | Historical era (`patristic`, `medieval`, `reformation`, `post-reformation`, `modern`) |
| `license` | `cc0-1.0` or `public-domain` |
| `schema_type` | Content type — one of the config names above |

Schema-specific fields vary by content type. Full field documentation is in the [source repository](https://github.com/OpenChristianData/open-christian-data/blob/main/docs/SCHEMA_SPEC.md).

## Provenance

Every record carries full provenance — the source URL, source format, download date, processing script, and a SHA-256 hash of the source file. This is stored in the `provenance_*` fields in the flattened export.

## Verse references

All verse references use [OSIS format](https://crosswire.org/osis/) (`Gen.1.1`, `Rom.9.1-Rom.9.5`). Where sources use non-standard reference formats, both the raw form and the normalized OSIS form are stored.

## License

- **Data**: [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/) — all underlying texts are public domain; the structuring and provenance tracking are dedicated to the public domain
- **Bible text (BSB)**: [CC0 1.0](https://berean.bible/licensing.htm)
- **Code and schemas**: [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — free for non-commercial use; commercial use requires a license (see [source repository](https://github.com/OpenChristianData/open-christian-data))

## Citation

```bibtex
@dataset{open_christian_data_2026,
  title        = {Open Christian Data},
  author       = {OpenChristianData},
  year         = {2026},
  publisher    = {HuggingFace},
  url          = {https://huggingface.co/datasets/OpenChristianData/open-christian-data},
  license      = {CC0-1.0}
}
```

## Source repository

[github.com/OpenChristianData/open-christian-data](https://github.com/OpenChristianData/open-christian-data)
