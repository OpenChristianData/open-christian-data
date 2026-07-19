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
- config_name: bible_text
  data_files:
    - path: data/bible_text.jsonl
      split: train
- config_name: catechism_qa
  data_files:
    - path: data/catechism_qa.jsonl
      split: train
- config_name: church_fathers
  data_files:
    - path: data/church_fathers.jsonl
      split: train
- config_name: commentary
  data_files:
    - path: data/commentary.jsonl
      split: train
- config_name: devotional
  data_files:
    - path: data/devotional.jsonl
      split: train
- config_name: doctrinal_document
  data_files:
    - path: data/doctrinal_document.jsonl
      split: train
- config_name: hymn_collection
  data_files:
    - path: data/hymn_collection.jsonl
      split: train
- config_name: prayer
  data_files:
    - path: data/prayer.jsonl
      split: train
- config_name: reference_entry
  data_files:
    - path: data/reference_entry.jsonl
      split: train
- config_name: sermon
  data_files:
    - path: data/sermon.jsonl
      split: train
- config_name: structured_text
  data_files:
    - path: data/structured_text.jsonl
      split: train
- config_name: topical_reference
  data_files:
    - path: data/topical_reference.jsonl
      split: train
---

# Open Christian Data

Open Christian Data (OCD) aims to be the single unified collection of all public domain Christian text. It exists to bring this collection together from across the internet and to structure it in a useful format for public use.

Beyond the Bible, Christian writing is poorly represented as a cohesive dataset or as data structured for AI training. This Hugging Face release is the AI-focused publication of the collection: consistent, downloadable JSON for model training, evaluation, retrieval, and other computational uses.

**Nearly 150 million words of Christian texts across 12 categories, including
363 books.** The collection also includes 34,904 hymns, 5,297 sermons, nine
Bible translations, and extensive commentary and reference material. That is
roughly 196 million tokens across 805,146 records.

## Why the collection exists

Most public domain Christian literature beyond the Bible is scattered across
scanned books, old websites, specialist file formats, and separate
digitization projects. Even when a text is online, it may not be available as
part of a collection in which its author, work, edition, structure, and source
history are clearly preserved.

Being online is not enough. Without that context, texts are difficult to find
together, cite accurately, compare across editions, correct against their
sources, credit properly, or use responsibly in research, study, software, and
AI systems.

The collection stands on the shoulders of the faithful people who preserved,
digitized, and published these texts before us, and it stays true to their
ethos: information about Christianity and historical Christian texts should be
freely and widely available to all. Advances in AI have made a collection of
this scale practical in a way it has not been before.

## Three questions shape the data

This dataset was the project's original goal: public domain Christian text
structured for AI use. Building it raised three questions that now govern how
every record is made:

1. **Is the text a faithful copy of its source?** A record must be checkable
   against the digital source it was taken from, so source, edition, and
   processing history travel with the text.
2. **Is the text a faithful copy of the original published work?** A digital
   source can itself diverge from the edition it transcribes. The wording and
   the structure and formatting of the original both carry information for a
   serious reader of the text, so both are recovered and checked.
3. **Is the text free to use?** Everything published here is intended to be
   public domain with no rights attached, in keeping with the public-good
   spirit of the project. Where rights questions remain, they are recorded
   openly rather than passed on silently.

Code alone cannot answer the first two questions, because its output is not
easy for a person to review. Each work is therefore normalized into a shared
intermediate representation that can be rendered as readable pages and
visually verified against the source. That verification work incidentally
produces human-readable editions of the texts, useful well beyond the
dataset's original AI purpose; it lives in the
[GitHub project](https://github.com/OpenChristianData/open-christian-data).

## What is in the collection

| Category | Configuration | What the collection contains |
|---|---|---|
| Books and long-form works | `structured_text` | 288 works, including theology, church history, treatises, and devotional classics, divided into 259,198 passages for publication |
| Bible translations | `bible_text` | 9 translations containing 282,395 verses |
| Commentaries | `commentary` | 34 commentaries containing 115,069 entries |
| Dictionaries and encyclopedias | `reference_entry` | 6 dictionaries and encyclopedias containing 25,682 entries |
| Topical Bibles and indexes | `topical_reference` | *Nave's Topical Bible* and *Torrey's New Topical Textbook*, containing 5,945 topics |
| Devotionals | `devotional` | 2 devotionals containing 1,464 readings |
| Sermons | `sermon` | 5,297 sermons from 7 collections |
| Creeds, confessions, and doctrinal documents | `doctrinal_document` | 33 documents published as 1,314 articles and clauses |
| Catechisms | `catechism_qa` | 15 catechisms containing 3,509 questions and answers |
| Prayers and liturgies | `prayer` | 4 sources containing 205 prayers and collects |
| Hymns | `hymn_collection` | 34,904 hymn texts |
| Church Fathers quotations | `church_fathers` | 70,164 scripture-linked quotations |

Representative works include Matthew Henry's *Exposition of the Old and New
Testament*, Spurgeon's *Metropolitan Tabernacle Pulpit*, the *Catholic
Encyclopedia*, *Nave's Topical Bible*, Augustine's *City of God*, Calvin's
*Institutes of the Christian Religion*, and editions of the *Book of Common
Prayer*.

Hugging Face publishes the collection through 12 configurations. Long-form
works are divided into passages for search, retrieval, and model use, producing
805,146 downloadable records. That record count is a technical measure rather
than the size of the library: a record may be a verse, commentary entry, sermon,
hymn, question and answer, prayer, reference entry, or passage from a book.

## What makes the collection different

- **Unified.** Books, commentaries, sermons, hymns, catechisms, prayers, and
  reference works that were scattered across archives, websites, and
  specialist formats can be found and used together.
- **Free to use.** The published dataset is released under CC0 for research,
  publishing, software, model development, and other reuse. Source-specific
  rights and the remaining audit questions are recorded below rather than
  hidden behind the collection-wide license.
- **Traceable provenance.** Source, license, edition, contributors, and
  processing history travel with the text, so users can inspect where it came
  from and credit the people and organizations that made it available.
- **Faithful to the source text.** The goal is accurate recovery of the words
  and structure of the represented edition, not merely data that passes a
  schema. Corrections are made against source evidence.
- **Texts remain connected to their context.** A passage stays attached to its
  author, work, edition or translation, place in the work, and literary form.
  That context is what makes a passage citable, historically intelligible,
  comparable with other editions, and correctable when an error is found.

## How the collection is made

Each work begins with a particular public domain source and edition. Texts that are already digital are carefully parsed; texts that survive only as scans are transcribed using OCR and corrected against the page images. The aim is an accurate digital text, not simply a large quantity of extracted words.

The text is then organized according to what it is. Books retain their divisions, sermons and hymns remain whole works, commentaries stay connected to the Bible passages they discuss, and authors, contributors, editions, translations, and source history remain attached.

The Hugging Face files are the AI-ready publication of that work. Longer books and documents are divided into usable passages, while shorter forms remain natural units such as verses, sermons, hymns, questions and answers, prayers, quotations, and reference entries. Each record carries enough information to reconnect it to its parent work and source.

The [GitHub project](https://github.com/OpenChristianData/open-christian-data) contains the texts, provenance, schemas, and construction tools, together with the developing TEI intermediate representations and visual reading and verification work from which future publication formats can be produced.

## Using the dataset

```python
from datasets import load_dataset

commentary = load_dataset(
    "OpenChristianDataOrg/open-christian-data",
    "commentary",
)

structured_text = load_dataset(
    "OpenChristianDataOrg/open-christian-data",
    "structured_text",
)
```

To reproduce a particular release, pin its Hub tag after the tags are created:

```python
commentary_v020 = load_dataset(
    "OpenChristianDataOrg/open-christian-data",
    "commentary",
    revision="v0.2.0",
)
```

### Size of each configuration

| Configuration | Records | Tokens | File size |
|---|---:|---:|---:|
| `bible_text` | 282,395 | 9.0M | 128.9 MB |
| `catechism_qa` | 3,509 | 0.9M | 6.5 MB |
| `church_fathers` | 70,164 | 16.9M | 119.9 MB |
| `commentary` | 115,069 | 54.3M | 332.9 MB |
| `devotional` | 1,464 | 0.5M | 3.3 MB |
| `doctrinal_document` | 1,314 | 0.2M | 2.0 MB |
| `hymn_collection` | 34,904 | 7.9M | 54.8 MB |
| `prayer` | 205 | 0.1M | 0.3 MB |
| `reference_entry` | 25,682 | 29.8M | 164.0 MB |
| `sermon` | 5,297 | 36.7M | 163.6 MB |
| `structured_text` | 259,198 | 39.2M | 616.1 MB |
| `topical_reference` | 5,945 | 0.2M | 9.4 MB |
| **Total** | **805,146** | **195.7M** | **1.60 GB** |

Token counts cover the text of the works themselves — verse text, commentary,
sermon and hymn text, questions and answers, entry bodies, and passages. They
exclude JSON structure, identifiers, references, URLs, and the inlined metadata
fields, so they measure the corpus rather than the file. They are computed with
the `o200k_base` encoding; another tokenizer will give a different number. File
size is the uncompressed JSONL on the Hub; the whole collection is roughly
333 MB gzipped.

Each configuration currently provides a single `train` split. The split name
describes how the files are exposed on the Hub; it is not a recommendation
that every record should be used for model training.

## Data structure

Every row combines information about its parent work with fields for the
particular verse, entry, sermon, hymn, question, or passage.

| Field | Meaning |
|---|---|
| `_source_id` | Identifier for the parent work or collection |
| `entry_id` | Identifier for the individual record |
| `author` | Author name, when known |
| `tradition` | Descriptive theological-tradition labels |
| `era` | Historical period |
| `license` | Rights status of the source text |
| `schema_type` | Kind of content and corresponding Hub configuration |

Fields specific to commentaries, sermons, hymns, Bible texts, and long-form
works vary by configuration. Full definitions are in the
[schema documentation](https://github.com/OpenChristianData/open-christian-data/blob/main/docs/SCHEMA_SPEC.md).

Bible references use [OSIS](https://crosswire.org/osis/) notation, such as
`Gen.1.1` and `Rom.9.1-Rom.9.5`. Where a source uses another reference system,
the original form is retained alongside the normalized reference when
available.

Where records carry `summary` and `key_quote` fields, those fields currently
ship empty with `summary_review_status` set to `"withheld"`. They are
placeholders for reviewed summaries, published empty rather than filled with
unreviewed generated text.

## Intended uses

Open Christian Data is intended for:

- research and digital-humanities work on historical Christian writing;
- search, retrieval, reading, and reference applications;
- comparison across authors, works, periods, and traditions;
- language-model training, evaluation, retrieval augmentation, and other
  computational uses that need openly reusable Christian texts;
- building better editions or metadata by tracing records back to their
  sources and contributing corrections.

## Coverage and limitations

- The collection is English-language and historical. It is not a balanced
  representation of global Christianity, present-day Christian belief, or
  every theological tradition.
- Coverage reflects what survives in usable public-domain editions. Some
  authors and traditions are much better represented than others.
- Historical works preserve the language, assumptions, disagreements, and
  prejudices of their authors. Inclusion is not endorsement.
- Source transcriptions and metadata can contain errors. Validation can catch
  structural problems, but it cannot prove that every reading or editorial
  description is correct.
- Editions and translations matter. Records from different editions should
  not be treated as interchangeable without checking their provenance.
- Tradition and era labels are aids to discovery, not authoritative judgments
  about contested theological or historical boundaries.
- The dataset is a research and development resource, not a doctrinal
  authority or a critical edition of every represented work.

Corrections and better source evidence are welcome through the
[source repository's issue tracker](https://github.com/OpenChristianData/open-christian-data/issues).

## Sources and acknowledgments

Open Christian Data brings together texts made available through the
[Christian Classics Ethereal Library](https://www.ccel.org/),
[Internet Archive](https://archive.org/),
[Project Gutenberg](https://www.gutenberg.org/),
[Standard Ebooks](https://standardebooks.org/),
[CrossWire SWORD](https://www.crosswire.org/sword/),
[HelloAO](https://bible.helloao.org/),
[HistoricalChristianFaith](https://github.com/HistoricalChristianFaith/Commentaries-Database),
[Scrollmapper's bible_databases](https://github.com/scrollmapper/bible_databases),
[Berean Bible](https://berean.bible/),
[The Kingdom Collective](https://thekingdomcollective.com/spurgeon/),
[New Advent](https://www.newadvent.org/cathen/), Wikisource, and other archives
and source projects.

The hymn collection was provided by [Hymnary.org](https://hymnary.org/) at
Calvin University. If you build with it, please link to Hymnary.org and tell
them about your project through [their contact page](https://hymnary.org/contact).
Many books and other texts were **sourced via
[CCEL.org](https://www.ccel.org/)**, which asks to be acknowledged for making
its files available.

The [principal-source and acknowledgment ledger](https://github.com/OpenChristianData/open-christian-data/blob/main/docs/SOURCES.md)
distinguishes historic works from modern digitizations and databases, records
source-specific credit, and links to third-party notices. Specific source and
edition information also travels with individual records.

The v0.2.0 source audit checked the rights behind the release rather than
assuming them. It found five doctrinal records whose text came from a
copyrighted modern Bible translation and so could not be released under CC0.
Those records have been removed rather than kept under a license they did not
fit. The passages themselves remain available in the public-domain or CC0 Bible
translations included here.

Three questions remain open and are recorded in the source ledger rather than
settled quietly: the license covering the JWBickel structured data, the
Wikisource transcription layer, and a translation warning carried by the
HistoricalChristianFaith source. Credit is not treated as a substitute for
permission, and anything that cannot be released cleanly will be removed or
replaced rather than relabeled.

## Versions

| Version | Date | Summary |
|---|---|---|
| **v0.2.0** (corrected upload pending) | 2026-07-17 | A substantially larger collection, with richer descriptions of works and editions and a broad correctness pass. [Full notes](https://github.com/OpenChristianData/open-christian-data/blob/main/docs/releases/v0.2.0.md) |
| v0.1.0 | 2026-04-12 | Initial public release: 11 configurations and 247,649 rows. |

Hugging Face versions are Git revisions. Once the release tags are present,
`v0.2.0` and `v0.1.0` can be used in `revision=`; immutable Hub commit hashes
can also be used for exact reproduction.

## License

- **Published data:** [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/)
- **Berean Standard Bible:** [CC0 1.0](https://berean.bible/licensing.htm)
- **Code, schemas, and tooling:** [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)

The CC0 dedication applies to the published dataset. Code, schemas, and tools
in the source repository have a separate license and are not part of that CC0
dedication.

## Citation

```bibtex
@dataset{open_christian_data_2026,
  title        = {Open Christian Data},
  author       = {OpenChristianData},
  year         = {2026},
  version      = {0.2.0},
  publisher    = {Hugging Face},
  url          = {https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data},
  license      = {CC0-1.0}
}
```

## Source repository

[github.com/OpenChristianData/open-christian-data](https://github.com/OpenChristianData/open-christian-data)
