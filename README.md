# open-christian-data

Public domain Christian literature as structured, machine-readable data — for developers and AI training.

## What this is

Commentary data is trapped in HTML and PDFs. No structured commentary dataset exists on HuggingFace. No per-chapter commentary JSON exists on GitHub.

This project processes public domain Christian literature — commentaries, confessions, catechisms, devotionals, sermons — into clean JSON datasets with full provenance metadata.

## Status

**Phase 1a — Active.**

| Resource | Type | Coverage | Entries | Summaries | License |
|---|---|---|---|---|---|
| Berean Standard Bible | Bible text | 66 books | 31,086 verses | N/A | CC0 |
| Matthew Henry's Complete Commentary | Commentary | 65 books | 18,000+ | Withheld pending review | CC0 |
| Church Fathers & Historical Authors | Church Fathers quotes | 325 authors | 70,191 quotes | None | Public domain |
| Spurgeon's Morning and Evening | Devotional | 366 days | 732 | None (enrichment layer) | Public domain |
| The Pilgrim's Progress — Bunyan | Structured text | 5 parts | 1,790 blocks / 109k words | None | Public domain |
| The City of God — Augustine | Structured text | 22 books | 1,170 blocks / 426k words | None | Public domain |
| Orthodoxy — G. K. Chesterton | Structured text | 9 chapters | 238 blocks / 64k words | None | Public domain |
| Heretics — G. K. Chesterton | Structured text | 20 chapters | 234 blocks / 64k words | None | Public domain |
| The Everlasting Man — G. K. Chesterton | Structured text | 7 parts / 21 chapters | 311 blocks / 107k words | None | Public domain |
| The Imitation of Christ — Thomas à Kempis | Structured text | 4 books / 119 chapters | 576 blocks / 61k words | None | Public domain |
| Unspoken Sermons — George MacDonald | Sermon collection | 3 series | 36 sermons / 171k words | None | Public domain |
| Practical Mysticism — Evelyn Underhill | Structured text | 11 chapters | 169 blocks / 32k words | None | Public domain |
| Paradise Lost — John Milton | Structured text | 12 books | 411 blocks / 82k words | None | Public domain |

## Data format

Each resource is a JSON file with a metadata envelope and a data array:

```json
{
  "meta": {
    "id": "matthew-henry-complete",
    "author": "Matthew Henry",
    "license": "cc0-1.0",
    "schema_type": "commentary",
    "verse_text_source": "BSB",
    "verse_reference_standard": "OSIS",
    "provenance": { ... }
  },
  "data": [
    {
      "entry_id": "matthew-henry-complete.Ezek.1.1-3",
      "book": "Ezekiel",
      "book_osis": "Ezek",
      "chapter": 1,
      "verse_range": "1-3",
      "verse_range_osis": "Ezek.1.1-Ezek.1.3",
      "verse_text": "In the thirtieth year, on the fifth day of the fourth month...",
      "commentary_text": "The circumstances of the vision which Ezekiel saw...",
      "summary": null,
      "summary_review_status": "withheld",
      "cross_references": [],
      "word_count": 2042
    }
  ]
}
```

## Schema

All verse references use OSIS format (`Gen.1.1`, `Rom.9.1-Rom.9.5`). Schema definitions are in `schemas/v1/`. TypeScript types in `schemas/types.ts`.

## Repository structure

```
data/
  bible-text/
    bsb/                      # 66 book files, one per book
      genesis.json            # 1533 verses
      psalms.json             # 2461 verses
      ...                     # 31,086 verses total
  church-fathers/
    john-chrysostom.json      # 7,398 quotes across 66 books
    augustine-of-hippo.json   # 7,673 quotes
    ...                       # 325 files, 70,191 total quotes from 335+ authors
  commentaries/
    matthew-henry/            # and 4 other commentaries
      _manifest.json          # Book index with entry counts and status
      ezekiel.json            # 132 entries, 232k words, BSB verse text
  devotionals/
    spurgeons-morning-evening/
      morning-evening.json    # 732 entries (366 days x morning + evening)
  sermons/
    george-macdonald-unspoken-sermons.json  # 36 sermons, 171k words
  structured-text/
    pilgrims-progress.json    # Bunyan — 1,790 blocks, 109k words
    city-of-god.json          # Augustine — 1,170 blocks, 426k words
    orthodoxy.json            # Chesterton — 238 blocks, 64k words
    heretics.json             # Chesterton — 234 blocks, 64k words
    the-everlasting-man.json  # Chesterton — 311 blocks, 107k words
    imitation-of-christ.json  # Thomas à Kempis — 576 blocks, 61k words
    practical-mysticism.json  # Underhill — 169 blocks, 32k words
    paradise-lost.json        # Milton — 411 blocks, 82k words
schemas/
  v1/
    bible_text.schema.json    # JSON Schema for verse-level Bible text
    church_fathers.schema.json # JSON Schema for Church Fathers quotes
    commentary.schema.json    # JSON Schema (source of truth)
    devotional.schema.json    # JSON Schema for date-keyed devotionals
    structured_text.schema.json # JSON Schema for hierarchical prose works
    sermon.schema.json        # JSON Schema for sermon collections
  types.ts                    # TypeScript types
build/
  parsers/
    bsb_bible_text.py         # BSB parser (reads raw/bible_databases/BSB.json)
    church_fathers.py         # Parser for Commentaries-Database TOML (335+ authors)
    helloao_commentary.py     # Generic parser for any HelloAO commentary
    ccel_devotional.py        # Parser for Spurgeon's M&E from CCEL ThML XML
    standard_ebooks.py        # Parser for Standard Ebooks XHTML (9 titles)
  bible_data/
    osis_book_codes.json      # Full Bible book names -> OSIS codes mapping
    verse_index.json          # Canonical verse index for OSIS existence checks
  validate.py                 # Schema + structural validation
sources/
  bible-text/
    bsb/
      config.json             # Source metadata and provenance
  commentaries/
    matthew-henry/
      config.json             # Source URLs, chapter counts, coverage notes
  devotionals/
    spurgeons-morning-evening/
      config.json             # Source metadata and provenance
```

## Usage

```python
import json

with open("data/commentaries/matthew-henry/ezekiel.json", encoding="utf-8") as f:
    resource = json.load(f)

# All entries for Ezekiel chapter 37
ch37 = [e for e in resource["data"] if e["chapter"] == 37]

# All entries for a specific verse range
valley = [e for e in resource["data"] if "37" in e["verse_range_osis"]]
```

## Running the pipeline

```bash
# Validate a data file
py -3 build/validate.py data/bible-text/bsb/genesis.json
py -3 build/validate.py data/commentaries/matthew-henry/ezekiel.json
py -3 build/validate.py data/devotionals/spurgeons-morning-evening/morning-evening.json

# Validate everything
py -3 build/validate.py --all

# Generate BSB bible text (all 66 books from local raw/bible_databases/BSB.json)
py -3 build/parsers/bsb_bible_text.py --dry-run
py -3 build/parsers/bsb_bible_text.py

# Process a single book for any commentary
py -3 build/parsers/helloao_commentary.py --commentary matthew-henry --book EZK

# Process all books for a commentary
py -3 build/parsers/helloao_commentary.py --commentary jamieson-fausset-brown --all-books

# Generate Spurgeon's Morning and Evening (downloads CCEL source on first run)
py -3 build/parsers/ccel_devotional.py --dry-run
py -3 build/parsers/ccel_devotional.py

# Process Church Fathers quotes (reads raw/Commentaries-Database/, all 335+ authors)
py -3 build/parsers/church_fathers.py --author "John Chrysostom" --dry-run
py -3 build/parsers/church_fathers.py --all-authors

# Process Standard Ebooks titles (reads raw/standard_ebooks/, XHTML sources)
py -3 build/parsers/standard_ebooks.py --id john-bunyan_the-pilgrims-progress --dry-run
py -3 build/parsers/standard_ebooks.py --all
```

Requires Python 3.9+. No external dependencies for the pipeline. `pip install jsonschema` for schema validation.

## Sources

- **Bible text**: [Berean Standard Bible](https://berean.bible) — CC0 since April 2023. 31,086 verses across 66 books. Sourced from [bible-databases](https://github.com/thiagobodruk/bible).
- **Commentary text**: [HelloAO Bible API](https://bible.helloao.org) — 5 commentaries (Matthew Henry, Jamieson-Fausset-Brown, John Gill, Adam Clarke, Keil-Delitzsch), all PDM 1.0 (public domain)
- **Church Fathers quotes**: [HistoricalChristianFaith/Commentaries-Database](https://github.com/HistoricalChristianFaith/Commentaries-Database) — 58,675 TOML files, 335+ authors (Augustine, Chrysostom, Jerome, Origen, Aquinas...), public domain
- **Devotional text**: [Christian Classics Ethereal Library](https://www.ccel.org) — Spurgeon's Morning and Evening in ThML XML, public domain
- **Structured texts & sermons**: [Standard Ebooks](https://standardebooks.org) — 9 titles (Bunyan, Augustine, Chesterton ×3, Thomas à Kempis, MacDonald, Underhill, Milton) in CC0-annotated XHTML; underlying texts public domain
- All authors died before 1928; texts are unambiguously public domain.

## Summaries

Each entry has `summary` and `key_quote` fields. These are `null` and `summary_review_status: "withheld"` in Phase 1a — they ship empty rather than unreviewed. Summaries will be generated and added incrementally as they're reviewed.

## License

- **Code** (build scripts, schemas, tooling): MIT
- **Data** (processed datasets): CC0 1.0 Universal

The underlying texts are public domain. Our value-add is the structuring and provenance tracking, dedicated to the public domain.
