<h1 align="center">Open Christian Data</h1>

<p align="center"><strong>Repository of Public Domain Christian Texts</strong></p>

[![CI](https://github.com/OpenChristianData/open-christian-data/actions/workflows/ci.yml/badge.svg)](https://github.com/OpenChristianData/open-christian-data/actions/workflows/ci.yml)

## What is Open Christian Data?

Open Christian Data (OCD) aims to be the single unified collection of all public domain Christian text. It exists to bring this collection together from across the internet and to structure it in a useful format for public use.

Most public domain Christian literature beyond the Bible is scattered across scanned books, old websites, specialist file formats, and separate digitization projects. Even when a text is online, it may not be available as part of a collection in which its author, work, edition, structure, and source history are clearly preserved. We stand on the shoulders of the faithful saints who have come before to build on their work and stay true to their ethos that information about Christianity and historical Christian texts should be freely and widely available to all. Many of those who have come before, we believe, forged their work in this spirit and dreamed of a project like this one day existing, and we hope to honor and carry on those dreams. We believe advances in AI have made this project possible on a scale that has never been possible before.

The original goal of the project was to make a dataset for AI use, which you can find [on Hugging Face](https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data), and that is still a primary goal of the project. However development on that project raised at least three issues to resolve that lead to a larger project with expanded usefulness:

1. How do you verify that the text is a faithful copy of its source?
2. How do you verify that the text is a faithful copy of the original published work itself? This raises the issue of both text structure and formatting of the original published work but also the accuracy of the text to the original work. Seeing as both provide information to a true scholar of the text, both issues come into view.
3. How do you ensure the text is usable for AI? It has to be public domain with no rights attached, aligned in any case with the motivating spirit of this project which is the public good. This work is produced in the hopes that it will be useful in ways the producers can not even yet envision.

Code can only take you so far and is not human friendly for review, so we determined it useful and necessary to have an intermediate step that we normalized all text into so that it can be visually verified. It then became obvious that this work will incidentally produce useful renderings of the texts in human readable formats that can be useful for purposes beyond the original intended purpose of the project.

**Current Release: V0.2.0:**

**Nearly 150 million words of Christian texts across 12 categories, including 363 books.** The collection also includes 34,904 hymns, 5,297 sermons, nine Bible translations, and extensive commentary and reference material.

## How the collection is made

1. **Find a reliable source.** We identify a particular work and edition, find the best available copy, and confirm that the text can be included in a public domain collection.
2. **Create an accurate digital text.** Some sources are already digital and can be carefully parsed. Others survive only as scanned books and must be transcribed using OCR and then corrected against the page images. The aim is to reproduce the text and structure of the chosen edition faithfully.
3. **Keep the work intact.** We record who wrote and contributed to the work, which edition or translation is represented, how the work is divided, and where the text came from. Books remain books, sermons remain sermons, hymns remain hymns, and commentaries remain connected to the Bible passages they discuss.
4. **Build a verifiable master copy.** The project is moving each work into a shared intermediate representation (IR) using the Text Encoding Initiative (TEI) standard. This master copy preserves more of the work than any one published format and can be rendered as a readable page so that people can compare it with the original source and correct errors.
5. **Publish useful versions.** The texts, provenance, developing TEI representations, and visual verification tools live in this GitHub project. From the master text we can produce simpler versions for particular uses, including the JSON dataset published on Hugging Face for AI training and development.

## Where the collection is published

This GitHub repository is the home of the texts in all their forms, their source history, and the tools used to build and check them.

The [Open Christian Data dataset on Hugging Face](https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data) is the home of the AI-focused dataset publication. It presents the collection as downloadable JSON records organized by format, making it straightforward to use for model training, evaluation, retrieval, and other computational work.

## Current collection

The collection currently includes books, Bible translations, commentaries, topical indexes, devotionals, sermons, doctrinal documents, catechisms, prayers, hymns, dictionaries and encyclopedias, and scripture-linked quotations from the Church Fathers. The Hugging Face publication divides some long works into smaller passages so they can be searched, retrieved, and used in AI systems.

Counts below are generated from current `data/` by:

```bash
py -3 build/tools/count_dataset_records.py
```

| Category                                     | What the collection contains                                                                                                     |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Books and long-form works                    | 288 works, including theology, church history, treatises, and devotional classics, divided into 259,198 passages for publication |
| Bible translations                           | 9 translations containing 282,395 verses                                                                                         |
| Commentaries                                 | 34 commentaries containing 115,069 entries                                                                                       |
| Dictionaries and encyclopedias               | 6 dictionaries and encyclopedias containing 25,682 entries                                                                       |
| Topical Bibles and indexes                   | *Nave's Topical Bible* and *Torrey's New Topical Textbook*, containing 5,945 topics                                              |
| Devotionals                                  | 2 devotionals containing 1,464 readings                                                                                          |
| Sermons                                      | 5,297 sermons from 7 collections                                                                                                 |
| Creeds, confessions, and doctrinal documents | 33 documents published as 1,314 articles and clauses                                                                             |
| Catechisms                                   | 15 catechisms containing 3,509 questions and answers                                                                             |
| Prayers and liturgies                        | 4 sources containing 205 prayers and collects                                                                                    |
| Hymns                                        | 34,904 hymn texts                                                                                                                |
| Church Fathers quotations                    | 70,164 scripture-linked quotations                                                                                               |

The Hugging Face files contain 805,146 downloadable records. That is a technical loading statistic: depending on the category, a record may be a verse, passage, sermon, hymn, question and answer, prayer, quotation, or reference entry. The generated work catalog and metadata audit live at [`docs/WORK_CATALOG.md`](docs/WORK_CATALOG.md). A browser-friendly review surface is available at [`docs/WORK_CATALOG.html`](docs/WORK_CATALOG.html).

Examples include *An Exposition of the Old and New Testament*, *The Metropolitan Tabernacle Pulpit*, *The Catholic Encyclopedia*, *Nave's Topical Bible*, *The City of God*, *Institutes of the Christian Religion*, and editions of *The Book of Common Prayer*.

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

All verse references use OSIS format (`Gen.1.1`, `Rom.9.1-Rom.9.5`). TypeScript types are in `schemas/types.ts`.

Schema definitions live in two places. Dataset-specific schemas are in `schemas/v1/`; schemas shared with the project's OCR repository are in `ocd_kernel/schemas/v1/`. Resolve either by name with `resolve_schema_path()` from `ocd_kernel.lib.schema_enums` rather than hardcoding a directory, and read enum values from `build.lib._generated_enums` rather than redeclaring them. Allowed values for `tradition`, `era`, `audience`, and `work_kind` are documented in [`docs/SCHEMA_SPEC.md`](docs/SCHEMA_SPEC.md).

## Repository structure

```
data/
  bible-text/
    bsb/                      # book-scoped Bible text resources
  church-fathers/             # source-scoped verse-reference quotation resources
  commentaries/
    matthew-henry/            # book-scoped files for one commentary work
    calvin/                   # book-scoped files for one commentary collection
    expositors-bible/         # work/author-scoped commentary files
    ...
  doctrinal-documents/        # creeds, confessions, and statements
  structured-text/            # theology, devotion, church history, and related works
    augustine-*.json
    john-owen-*.json
    schaff-history-vol-*.json
    calvins-institutes.json
    ...
  sermons/
    spurgeon-mtp/
    maclaren-expositions.json
    john-wesley-sermons.json
    ...
  catechisms/
    westminster-shorter-catechism.json
    westminster-larger-catechism.json
    heidelberg-catechism.json
    ...
  devotionals/
    spurgeons-morning-evening/morning-evening.json
    daily-light/daily-light.json
  hymns/
    hymnary-pd/collection.json  # hymn texts provided by Hymnary.org
  prayers/
    bcp-1662/collects.json
    bcp-1928/collects.json
    andrewes-private-devotions/prayers.json
    didache/prayers.json
  reference/
    schaff-herzog-encyclopedia.json
    eastons-bible-dictionary.json
    smiths-bible-dictionary.json
    hitchcocks-bible-names-dictionary.json
    torreys-topical-textbook.json
  topical-reference/
    naves/naves-topical-bible.json
  authors/
    registry.json             # author registry shared across resources
  lexicon/                    # historical English lexicon used by checking
                              # tools (see data/lexicon/README.md)
schemas/
  v1/                         # dataset JSON schemas (one per record type)
  types.ts                    # TypeScript types
ocd_kernel/
  schemas/v1/                 # shared schemas used across the project's repos
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

Requires Python 3.11 or newer; CI runs 3.12. Install dependencies with `pip install -r requirements.txt`.

Most parsers and `build/validate.py` need only the standard library. The extra dependencies are narrow: `jsonschema` for schema validation, `beautifulsoup4` for the HTML sources, `pymupdf4llm` for the PDF sources, and `datasets` with `huggingface_hub` for publishing to Hugging Face.

## Sources

The collection depends on the work of libraries, archives, digitization
projects, editors, and software communities. Principal sources include CCEL,
Internet Archive, Project Gutenberg, Standard Ebooks, CrossWire, HelloAO,
Hymnary.org, HistoricalChristianFaith, Scrollmapper, Berean Bible, The Kingdom
Collective, New Advent, Wikisource, and specialist source sites.

The hymn collection was provided by [Hymnary.org](https://hymnary.org/) at
Calvin University. If you build with it, please link to Hymnary.org and tell
them about your project through [their contact page](https://hymnary.org/contact).
Many books and other texts were **sourced via
[CCEL.org](https://www.ccel.org/)**.

The [principal-source and acknowledgment ledger](docs/SOURCES.md) maps sources
to the material represented in the release, records requested credit and legal
notices, distinguishes old works from modern digitizations and databases, and
documents unresolved rights questions. Specific source and edition information
also travels with individual records. See [Third-Party Notices](THIRD_PARTY_NOTICES.md)
and the [licensing policy](docs/LICENSING.md) for additional detail.

## Contributing

The most useful contribution is adding a new source — a public-domain text that isn't yet in the dataset.

**Adding a new source:**

1. Establish the rights of the exact work, translation, edition, transcription, and source file; an author's death date alone is not enough
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

- **Published dataset** (Hugging Face): [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/) — intended for unrestricted reuse; see the [source and acknowledgment ledger](docs/SOURCES.md) for source-specific rights and open follow-up.
- **Everything else** (code, schemas, intermediate data, tooling): [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — free for non-commercial use with attribution; commercial use requires a license.

For commercial licensing: openchristiandata@gmail.com
