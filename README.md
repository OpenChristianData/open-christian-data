# open-christian-data

[![CI](https://github.com/OpenChristianData/open-christian-data/actions/workflows/ci.yml/badge.svg)](https://github.com/OpenChristianData/open-christian-data/actions/workflows/ci.yml)

541,000+ structured records spanning Bible text, commentaries, sermons, catechisms, church fathers, theology, prayer, and reference works — all public domain, all clean JSON.

## What this is

Open Christian Data is a structured dataset of public domain Christian literature: Bible text, commentaries, sermons, catechisms, confessions, theology, prayer, and reference works, all formatted as clean, consistent JSON.

All content is written by authors who died before 1928. All texts are in the public domain. The published training dataset is CC0; code, schemas, and tooling are CC BY-NC 4.0.

**The problem it solves.** The public domain contains centuries of Christian thought, but almost none of it is machine-readable. Commentaries sit in scanned PDFs. Sermons are buried in proprietary Bible software formats. Catechisms live in WordPress pages. This project converts those sources into structured JSON with consistent schemas and full provenance metadata, so developers and AI systems can actually use them.

## How it works

1. **Sources** — texts are downloaded from Project Gutenberg, the Christian Classics Ethereal Library (CCEL), CrossWire Bible modules (SWORD), Standard Ebooks, and other public domain archives.
2. **Parsers** — Python scripts in `build/parsers/` convert each source into JSON following a shared schema. Each parser has a corresponding test file and source config.
3. **Validation** — every output file is validated against a JSON Schema before it can be committed. CI runs validation on every push.
4. **Output** — clean JSON committed to `data/`, published to HuggingFace Datasets as flattened Parquet at [OpenChristianData/open-christian-data](https://huggingface.co/datasets/OpenChristianData/open-christian-data).

## Status

### Bible Text

| Resource | Coverage | Entries | License |
|---|---|---|---|
| Berean Standard Bible | 66 books | 31,086 verses | CC0 |

### Commentaries

| Resource | Coverage | Entries | License |
|---|---|---|---|
| Matthew Henry's Complete Commentary | 66 books | 5,344 entries | CC0 |
| Barnes' Notes on the NT | 27 books | 7,322 entries | Public domain |
| Calvin's Collected Commentaries | 49 books | 13,338 entries | Public domain |
| Wesley's Notes on the Bible | 66 books | 17,564 entries | Public domain |
| Jamieson-Fausset-Brown, John Gill, Adam Clarke, Keil-Delitzsch, Expositor's Bible, Treasury of David | Various | Various | Public domain |

### Church Fathers

| Resource | Coverage | Entries | License |
|---|---|---|---|
| Church Fathers & Historical Authors | 325 authors | 70,164 quotes | Public domain |
| Augustine — Complete Works, NPNF1 (vols 1–8) | 49 treatises | 49 works | Public domain |

### Structured Texts — 165 works total

Selected highlights:

| Author / Collection | Works | Notable titles |
|---|---|---|
| John Owen | 31 | Mortification, Communion with God, Death of Death, Pneumatologia, Justification... |
| Thomas Watson | 5 | Body of Divinity, Beatitudes, Ten Commandments, Lord's Prayer, Divine Contentment |
| Charles Hodge — Systematic Theology | 3 vols | — |
| A.H. Strong — Systematic Theology | 3 vols | — |
| W.G.T. Shedd — Dogmatic Theology | 3 vols | — |
| John Miley — Systematic Theology | 2 vols | — |
| Philip Schaff — History of the Christian Church | 8 vols | — |
| Eusebius, Socrates, Sozomen, Theodoret — Church Histories | 5 works | — |
| Puritan Classics | 12 | Charnock ×2, Baxter ×3, Gurnall, Flavel, Sibbes, Brooks, Burroughs, Watson ×5 |
| Jonathan Edwards | 3 | Freedom of the Will, Religious Affections, Select Sermons |
| Anglican Classics | 6 | Donne, Taylor ×2, Andrewes, Ryle ×2, Newman (Apologia) |
| Calvin's Institutes of the Christian Religion | 1 | 4 books / 80 chapters / 7,430 blocks / 646k words |
| Classic literature & devotion | 11 | Bunyan ×3, Chesterton ×3, Pascal, à Kempis, Milton, Underhill, MacDonald |
| Reformed / Evangelical | 10 | Pink, Machen, Spurgeon ×2, Murray ×3, Carey, Wilberforce, Drummond ×2 |
| Finney, Bounds | 6 | Lectures on Revivals, Systematic Theology, Power Through Prayer, + 4 more |

Full list: [`data/structured-text/`](data/structured-text/)

### Sermons

| Resource | Coverage | Entries | License |
|---|---|---|---|
| Spurgeon's Metropolitan Tabernacle Pulpit | 63 volumes | 3,547 sermons | Public domain |
| Maclaren's Expositions of Holy Scripture | Full Bible | 1,257 expositions | Public domain |
| John Wesley's Standard Sermons | — | 141 sermons | Public domain |
| Newman's Parochial and Plain Sermons | 8 volumes | 135 sermons | Public domain |
| Luther's Church Postil (Lenker trans.) | 8 volumes | 122 sermons | Public domain |
| Whitefield's Sermons | — | 61 sermons | Public domain |
| George MacDonald's Unspoken Sermons | 3 series | 36 sermons / 171k words | Public domain |

### Catechisms — 15 catechisms

| Resource | Entries | License |
|---|---|---|
| Westminster Shorter Catechism | 107 Q&A | Public domain |
| Westminster Larger Catechism | 196 Q&A | Public domain |
| Luther's Small Catechism | 45 Q&A | Public domain |
| Luther's Large Catechism | 419 blocks / 48k words | Public domain |
| Heidelberg Catechism | 129 Q&A | Public domain |
| Baltimore Catechism No. 1 | 206 Q&A | Public domain |
| Baltimore Catechism No. 2 | 421 Q&A | Public domain |
| Baltimore Catechism No. 3 | 1,400 Q&A | Public domain |
| + 7 more (Keach's, Puritan, 1695 Baptist, Catechism for Young Children, A.A. Hodge Outlines...) | — | Public domain |

### Doctrinal Documents — 37 documents

Creeds, confessions, and statements spanning the ecumenical and Reformed traditions: Westminster Confession, Belgic Confession, Canons of Dort, London Baptist Confession 1689, Savoy Declaration, Second Helvetic Confession, Apostles' Creed, Nicene Creed, Athanasian Creed, Chalcedonian Definition, and more.

### Reference Works

| Resource | Coverage | Entries | License |
|---|---|---|---|
| Schaff-Herzog Encyclopedia of Religious Knowledge | Full (A–Z) | 16,508 entries | Public domain |
| Easton's Bible Dictionary | Full (A–Z) | 3,963 entries | Public domain |
| Smith's Bible Dictionary | Full (A–Z) | 4,560 entries | Public domain |
| Hitchcock's Bible Names Dictionary | Full (A–Z) | 2,622 entries | Public domain |
| Torrey's New Topical Textbook | 623 topics | 21,580 scripture refs | Public domain |
| Nave's Topical Bible | 5,322 topics | 76,957 scripture refs | Public domain |

### Devotionals

| Resource | Coverage | Entries | License |
|---|---|---|---|
| Spurgeon's Morning and Evening | 366 days | 732 entries | Public domain |
| Daily Light on the Daily Path | 366 days | 732 entries | Public domain |

### Prayers

| Resource | Entries | License |
|---|---|---|
| BCP 1662 Collects | 85 collects | Public domain |
| BCP 1928 Collects | 102 collects | Public domain |
| Andrewes' Private Devotions | 14 prayers | Public domain |
| Didache Prayers (Lake trans.) | 4 prayers | Public domain |

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
    bsb/                      # 66 book files — 31,086 verses total
  church-fathers/             # 325 files — 70,165 quotes from 325 authors
  commentaries/
    matthew-henry/            # 66 books, 5,344 entries (HelloAO)
    barnes/                   # NT only — 27 books, 7,322 entries (SWORD)
    calvin/                   # 49 books, 13,338 entries (SWORD)
    wesley/                   # Full Bible — 66 books, 17,564 entries (SWORD)
    jamieson-fausset-brown/   # Full Bible (HelloAO)
    john-gill/                # Full Bible (HelloAO)
    adam-clarke/              # Full Bible (HelloAO)
    keil-delitzsch/           # OT (HelloAO)
    expositors-bible/         # Various books (HelloAO)
    treasury-of-david/        # Psalms — Spurgeon (HelloAO)
  doctrinal-documents/        # 37 creeds, confessions, and statements
  structured-text/            # 165 works — theology, devotion, church history
    augustine-*.json          # 49 Augustine works from NPNF1 (vols 1–8)
    john-owen-*.json          # 31 John Owen works
    schaff-history-vol-*.json # Philip Schaff Church History (8 vols)
    hodge-systematic-*.json   # Charles Hodge Systematic Theology (3 vols)
    strong-systematic-*.json  # A.H. Strong Systematic Theology (3 vols)
    shedd-dogmatic-*.json     # W.G.T. Shedd Dogmatic Theology (3 vols)
    calvins-institutes.json   # 7,430 blocks / 646k words
    watson-*.json             # Thomas Watson (5 works)
    ...                       # See data/structured-text/ for full list
  sermons/
    spurgeon-mtp/             # 3,547 sermons across 36 chunk files (MTP vols 1–63)
    maclaren-expositions.json # 1,257 expositions (full Bible)
    john-wesley-sermons.json  # 141 Standard Sermons
    newman-parochial-sermons.json  # 135 sermons (8 volumes)
    luther-lenker-sermons.json     # 122 sermons (Church Postil, 8 vols, Lenker trans.)
    george-whitefield-sermons.json # 61 sermons
    george-macdonald-unspoken-sermons.json  # 36 sermons / 171k words
  catechisms/                 # 15 catechisms
    westminster-shorter-catechism.json  # 107 Q&A
    westminster-larger-catechism.json   # 196 Q&A
    heidelberg-catechism.json           # 129 Q&A
    luthers-small-catechism.json        # 45 Q&A
    baltimore-catechism-no-{1,2,3}.json # 206 / 421 / 1,400 Q&A
    ...                       # + 8 more
  devotionals/
    spurgeons-morning-evening/morning-evening.json  # 732 entries
    daily-light/daily-light.json                    # 732 entries (Bagster)
  prayers/
    bcp-1662/collects.json              # 85 collects
    bcp-1928/collects.json              # 102 collects
    andrewes-private-devotions/prayers.json  # 14 prayers
    didache/prayers.json                # 4 eucharistic prayers
  reference/
    schaff-herzog-encyclopedia.json          # 8,351 entries
    eastons-bible-dictionary.json            # 3,963 entries
    smiths-bible-dictionary.json             # 4,560 entries
    hitchcocks-bible-names-dictionary.json   # 2,622 entries
    torreys-topical-textbook.json            # 623 topics, 21,580 refs
  topical-reference/
    naves/naves-topical-bible.json      # 5,322 topics, 76,957 refs
schemas/
  v1/
    bible_text.schema.json
    church_fathers.schema.json
    commentary.schema.json
    devotional.schema.json
    structured_text.schema.json
    sermon.schema.json
    prayer.schema.json
    catechism.schema.json
    reference_entry.schema.json
    topical_reference.schema.json
    doctrinal_document.schema.json
  types.ts                    # TypeScript types
build/
  parsers/                    # One parser per source type
  validate.py                 # Schema + structural validation
sources/                      # config.json per resource (source URLs, provenance)
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

# Download SWORD modules (Barnes, Calvin, Wesley, Daily Light)
py -3 build/scripts/download_sword_modules.py

# Parse SWORD commentary modules (reads raw/sword_modules/)
py -3 build/parsers/sword_commentary.py --module barnes --dry-run
py -3 build/parsers/sword_commentary.py --all

# Parse Daily Light devotional (SWORD rawLD format)
py -3 build/parsers/sword_devotional.py --dry-run
py -3 build/parsers/sword_devotional.py

# Process Church Fathers quotes (reads raw/Commentaries-Database/, all 335+ authors)
py -3 build/parsers/church_fathers.py --author "John Chrysostom" --dry-run
py -3 build/parsers/church_fathers.py --all-authors

# Process Standard Ebooks titles (reads raw/standard_ebooks/, XHTML sources)
py -3 build/parsers/standard_ebooks.py --id john-bunyan_the-pilgrims-progress --dry-run
py -3 build/parsers/standard_ebooks.py --all

# Generate BCP 1662 Collects (downloads eskimo.com HTML on first run)
py -3 build/parsers/bcp1662.py --dry-run
py -3 build/parsers/bcp1662.py

# Generate BCP 1928 collects (downloads 100 HTML pages from episcopalnet.org on first run)
py -3 build/parsers/bcp1928.py --dry-run
py -3 build/parsers/bcp1928.py

# Generate Didache prayers (downloads Wikisource wikitext on first run)
py -3 build/parsers/didache.py --dry-run
py -3 build/parsers/didache.py

# Process Bible dictionaries (reads raw/bible_dictionaries/*.jsonl)
py -3 build/parsers/bible_dictionaries.py --dictionary eastons --dry-run
py -3 build/parsers/bible_dictionaries.py --all

# Download Project Gutenberg texts (Luther, Baltimore Catechisms, Calvin, Augustine)
py -3 build/scripts/download_gutenberg.py --dry-run
py -3 build/scripts/download_gutenberg.py

# Parse PG catechisms (reads raw/gutenberg/)
py -3 build/parsers/gutenberg_catechisms.py --dry-run
py -3 build/parsers/gutenberg_catechisms.py

# Parse PG theology works (reads raw/gutenberg/)
py -3 build/parsers/gutenberg_theology.py --dry-run
py -3 build/parsers/gutenberg_theology.py

# Parse Nave's Topical Bible (reads raw/sword_modules/Nave.zip)
py -3 build/parsers/naves_topical.py --dry-run
py -3 build/parsers/naves_topical.py
```

Requires Python 3.9+. No external dependencies for the pipeline. `pip install jsonschema` for schema validation.

## Sources

- **Bible text**: [Berean Standard Bible](https://berean.bible) — CC0 since April 2023. 31,086 verses across 66 books. Sourced from [bible-databases](https://github.com/thiagobodruk/bible).
- **Commentary text (HelloAO)**: [HelloAO Bible API](https://bible.helloao.org) — Matthew Henry, Jamieson-Fausset-Brown, John Gill, Adam Clarke, Keil-Delitzsch, Expositor's Bible, Treasury of David; all PDM 1.0 (public domain).
- **Commentary text (SWORD)**: [CrossWire SWORD modules](https://www.crosswire.org/sword/) — Barnes' Notes on the NT (7,322 entries), Calvin's Collected Commentaries (13,338 entries), Wesley's Notes on the Bible (17,564 entries); public domain.
- **Church Fathers quotes**: [HistoricalChristianFaith/Commentaries-Database](https://github.com/HistoricalChristianFaith/Commentaries-Database) — 325 authors (Augustine, Chrysostom, Jerome, Origen, Aquinas...), public domain.
- **Augustine — NPNF1**: [Christian Classics Ethereal Library](https://www.ccel.org) — 49 works from Nicene and Post-Nicene Fathers vol. 1–8, ThML XML source; public domain.
- **Structured texts**: [Standard Ebooks](https://standardebooks.org) — Bunyan, Chesterton ×3, Thomas à Kempis, MacDonald, Underhill, Milton, and others in CC0-annotated XHTML; underlying texts public domain. [CCEL](https://www.ccel.org) — Owen (32 works), Watson, Baxter, Flavel, Edwards, Ryle, Charles Hodge (Systematic Theology), Philip Schaff (History of the Christian Church), Finney, Bounds, Pascal, Wesley, and others; ThML XML; public domain. [Project Gutenberg](https://www.gutenberg.org) — A.H. Strong (Systematic Theology), Charnock, and others; plain text; public domain. [Internet Archive](https://archive.org) — W.G.T. Shedd (Dogmatic Theology), John Miley, R.L. Dabney, Gurnall, Brooks, Sibbes, and others; DjVuTXT; public domain.
- **Sermons**: [The Kingdom Collective](https://www.thekingdomcollective.com) — Spurgeon's Metropolitan Tabernacle Pulpit (3,547 sermons); public domain. [CCEL](https://www.ccel.org) — Whitefield's Sermons; ThML XML; public domain. [Project Gutenberg](https://www.gutenberg.org) — Luther's Church Postil (Lenker trans.), Wesley, Newman, MacDonald; plain text; public domain. [CrossWire SWORD](https://www.crosswire.org/sword/) — Maclaren's Expositions; public domain.
- **Catechisms & confessions**: [Project Gutenberg](https://www.gutenberg.org), [Creeds.json](https://github.com/NonExistentUsername/creeds) — Westminster standards, Heidelberg, Baltimore, Luther, and 30+ more; all public domain.
- **Devotionals**: [CCEL](https://www.ccel.org) — Spurgeon's Morning and Evening (ThML XML); [CrossWire SWORD](https://www.crosswire.org/sword/) — Daily Light on the Daily Path (Bagster); public domain.
- **Prayers**: [eskimo.com](https://eskimo.com/~lhowell/bcp1662/) — BCP 1662 (Lynda M. Howell digitization); [episcopalnet.org](https://www.episcopalnet.org/1928bcp/) — BCP 1928; [Wikisource](https://en.wikisource.org/wiki/Didache_(Lake_translation)) — Didache (Lake 1912 trans.); [Project Gutenberg](https://www.gutenberg.org) — Andrewes' Private Devotions; all public domain.
- **Reference works**: [JWBickel/BibleDictionaries](https://huggingface.co/datasets/JWBickel/BibleDictionaries) — Easton's (1893), Smith's (1863), Hitchcock's (1874), Torrey's (1897); public domain. [Project Gutenberg](https://www.gutenberg.org) — Schaff-Herzog Encyclopedia of Religious Knowledge (1914 ed., 8,351 entries); public domain. [CrossWire SWORD](https://www.crosswire.org/sword/) — Nave's Topical Bible (1896); public domain.
- All authors died before 1928; texts are unambiguously public domain.

## Contributing

The most useful contribution is adding a new source — a public domain text that isn't yet in the dataset.

**Adding a new source:**
1. Check that the author died before 1928 (public domain requirement)
2. Identify the source format (Project Gutenberg, CCEL ThML, SWORD module, Standard Ebooks, HTML, PDF)
3. Create a parser in `build/parsers/<name>.py` — see existing parsers for patterns; shared utilities live in `build/lib/`
4. Add source metadata in `sources/<type>/<slug>/config.json`
5. Write tests in `tests/test_<name>.py` (required — the pre-commit hook will block a commit without them)
6. Run `py -3 build/validate.py --all` to confirm 0 errors
7. Open a PR

**Schema and enum values** are documented in `docs/SCHEMA_SPEC.md`. Read it before writing a parser — it defines allowed values for `tradition`, `era`, `audience`, `work_kind`, and the reference object format.

**Data quality fixes** (wrong section splits, missing entries, OCR errors) go directly in the relevant parser and its test file.

## Summaries

Each entry has `summary` and `key_quote` fields. These are `null` and `summary_review_status: "withheld"` — they ship empty rather than unreviewed. Summaries will be generated and added incrementally as they're reviewed.

## License

- **Training dataset** (published to HuggingFace): [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/) — public domain, use for any purpose including commercial AI training
- **Everything else** (code, schemas, intermediate data, tooling): [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — free for non-commercial use with attribution; commercial use requires a license

For commercial licensing: openchristiandata@gmail.com
