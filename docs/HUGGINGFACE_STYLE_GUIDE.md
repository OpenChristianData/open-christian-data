# Hugging Face Dataset Card and Release Note Style Guide

This guide defines how Open Christian Data should present itself on Hugging
Face. It applies to the dataset card, version history, and full release notes.

The central rule is simple: **lead with the purpose and character of the
collection; use technical details to support that story.**

## What the dataset card is for

The Hugging Face README is the permanent front door to the collection. It
should help a new reader understand:

1. what Open Christian Data is;
2. why it exists;
3. what texts, authors, and traditions it contains;
4. what makes the collection useful and trustworthy;
5. how to load and interpret it;
6. what it can and cannot responsibly be used for;
7. where the texts came from and how they are licensed;
8. what the current version is.

It is not a build report. File counts, checksums, upload steps, validation
totals, and intermediate commit states should not lead the card. Include them
only when they help a dataset user reproduce or evaluate the release.

Hugging Face describes dataset cards as contextual documentation for
understanding a dataset's contents, creation, responsible use, biases, and
limitations. The YAML metadata also controls Hub discovery and presentation.
See [Hugging Face: Dataset Cards](https://huggingface.co/docs/hub/datasets-cards)
and the [official dataset-card guide](https://github.com/huggingface/datasets/blob/main/templates/README_guide.md).

## The project's public story

The shared project description is:

> Open Christian Data (OCD) aims to be the single unified collection of all
> public domain Christian text. It exists to bring this collection together
> from across the internet and to structure it in a useful format for public
> use.

Keep that identity consistent, then write for the platform. GitHub focuses on
the texts themselves, their sources, the developing TEI intermediate
representation, and the visual reading and verification work. Hugging Face
focuses on the AI-ready JSON publication: what can be loaded, how records are
organized, and how the data can be used responsibly in model development.

This purpose should shape the card's language:

- Talk first about people, works, history, access, and use.
- Present the collection as a library or corpus, not as a pile of rows.
- Explain that authorship, edition, provenance, and historical setting affect
  how a text should be read.
- Treat open licensing and traceability as part of the collection's identity,
  not as boilerplate.
- Explain correction and validation through the trust they make possible.

## Recommended dataset-card structure

### 1. Identity and purpose

Open with the shared project description above, followed by the Hugging
Face-specific AI purpose, the current version, and meaningful scale in words,
books, and the natural units of the collection.

Do not open with JSONL files, source-file counts, flattened rows, hashes,
schemas, validation tools, or upload history.

### 2. What is in the collection

Describe genres, periods, traditions, representative authors, and
representative works. Give counts only when their units are clear.

Use this headline structure:

> Nearly 150 million words of Christian texts across 12 categories, including
> 363 books.

Follow it with natural units such as 34,904 hymns, 5,297 sermons, nine Bible
translations, 34 commentaries, and the number of reference entries or
quotations.

Order the public categories by human significance:

1. Books and long-form works
2. Bible translations
3. Commentaries
4. Dictionaries and encyclopedias
5. Topical Bibles and indexes
6. Devotionals
7. Sermons
8. Creeds, confessions, and doctrinal documents
9. Catechisms
10. Prayers and liturgies
11. Hymns
12. Church Fathers quotations

The historical English lexicon is a project tool, not a category of Christian
text. If it is mentioned publicly, explain that the checking and modernization
tools use it to recognize archaic names and spellings. Do not include it in the
public category count or present it as a Hugging Face configuration.

Qualify heterogeneous row counts. A row can mean a verse, commentary entry,
sermon, hymn, question and answer, or passage from a book. Never imply that
rows are interchangeable measures of intellectual or literary coverage.

### 3. What makes it distinctive

State the collection's public promises in language readers care about:

- **Unified:** scattered books and collections can be found and used together.
- **Free to use:** the published dataset is released under CC0, while
  source-specific rights and unresolved audit questions are stated plainly.
- **Traceable provenance:** source, license, edition, contributors, and
  processing history travel with the text.
- **Faithful to source texts:** correctness means accurate words and structure,
  not merely schema-valid output.
- **Texts remain in context:** passages remain attached to authors, books,
  editions or translations, their place in the work, and their literary form.
  This makes them citable, historically intelligible, comparable, and
  correctable.
- **Source stewardship:** source organizations, digitizers, and archives receive
  visible credit, especially where they have requested it.

Schema design belongs here only through its effect. Prefer “contributors and
their roles are represented clearly” over “the contributor schema was
refactored.”

### 4. How the collection is made

Give a concise account of source selection, parsing, organization, correction,
validation, and provenance. Name major source families when useful.

Keep internal architecture, campaign terminology, pipeline stages, test
counts, and implementation history in technical documentation unless they
materially affect how a user should interpret the published data.

### 5. Using the dataset

Include:

- a minimal `load_dataset` example;
- an example pinned to a version tag;
- an explanation of configurations and splits;
- a plain-language description of what a row represents;
- the most important shared fields;
- links to full schema documentation.

### 6. Intended uses

Name real uses rather than listing generic machine-learning tasks. These may
include research, digital humanities, search, retrieval, reading and reference
applications, textual comparison, model training, evaluation, and retrieval
augmentation.

### 7. Coverage and limitations

State limitations plainly. For Open Christian Data these include:

- English-language and historical focus;
- uneven representation across periods, traditions, regions, and authors;
- dependence on surviving usable public-domain editions;
- historical language, assumptions, disagreements, and prejudices;
- possible transcription and metadata errors;
- edition and translation differences;
- descriptive tradition and era labels that do not settle contested questions;
- the fact that the dataset is neither a doctrinal authority nor a critical
  edition of every work.

Schema-valid does not mean editorially definitive. Say so.

### 8. Sources and acknowledgments

Credit the principal source organizations and projects visibly. Do not rely on
provenance fields alone. Reproduce requested wording or link to the relevant
source-specific README, and distinguish legal requirements from voluntary
acknowledgments.

At minimum, preserve the requested Hymnary.org link and application-submission
request, and the established “sourced via CCEL.org” acknowledgment. Link to the
principal-source and acknowledgments document.

### 9. Licensing, citation, and corrections

Distinguish clearly between:

- the **CC0 published dataset**;
- source-specific rights recorded in provenance;
- the **CC BY-NC 4.0 code, schemas, and tooling**.

Provide a citation and a direct route for reporting errors or offering better
source evidence.

### 10. Versions

Keep a compact table in the card with:

- semantic version;
- date;
- current/default status;
- one sentence explaining the human significance of the release;
- a link to full notes.

Do not turn the card's version table into an upload ledger.

## What full release notes are for

Full notes explain the movement from one edition to the next. They should not
repeat the whole dataset card.

Use this order:

1. **Why the release matters** — one short paragraph connecting the release to
   the project's purpose.
2. **A larger or richer collection** — important additions in authors, works,
   genres, and traditions.
3. **A clearer account of the works** — improvements to authorship,
   contributors, editions, structure, and provenance.
4. **More trustworthy data** — concrete corrections and their consequences for
   readers or downstream users.
5. **Compatibility** — added, renamed, removed, or changed configurations and
   fields; migration advice where needed.
6. **Known limitations** — what remains incomplete, uneven, or uncertain.
7. **Version details** — release date, tag, immutable revision, and licensing.

Detailed statistics may appear after the release story. Verification logs,
checksums, and exhaustive file counts belong in a technical appendix when they
provide genuine value.

Avoid phrases such as “all reviewed files,” “final card-inclusive state,” or
“verified payload” unless they are defined, substantiated, and meaningful to a
dataset user.

## Versioning on Hugging Face

Hugging Face dataset repositories are Git repositories. Stable releases should
use semantic-version tags such as `v0.2.0`. A user can load a tag, branch, or
commit hash with the `revision=` argument.

Use:

```python
from datasets import load_dataset

dataset = load_dataset(
    "OpenChristianDataOrg/open-christian-data",
    "commentary",
    revision="v0.2.0",
)
```

Versioning policy:

- **Patch (`v0.2.1`)** — metadata, card, or data corrections that do not change
  the public structure materially.
- **Minor (`v0.3.0`)** — new works, new configurations, or additive schema
  capabilities.
- **Major (`v1.0.0`)** — breaking changes to identifiers, configurations,
  fields, or the basic interpretation of records.

Use one tag for the release users should cite and load. Intermediate uploads
are not separate versions. Preserve their commit history when useful, but do
not present it as release history.

See [Hugging Face Hub: branches and tags](https://huggingface.co/docs/huggingface_hub/guides/repository#branches-and-tags)
and [Hugging Face Datasets: loading a revision](https://huggingface.co/docs/datasets/loading#hugging-face-hub).

## Voice and language

- Use American English.
- Prefer ordinary nouns: author, work, edition, sermon, hymn, commentary,
  passage, and source.
- Avoid internal abstractions such as “work unit,” “payload,” “surface,”
  “artifact,” and “technical record” in reader-facing prose.
- Use active, concrete sentences.
- Explain the consequence of technical work rather than celebrating the
  machinery itself.
- Be confident without claiming perfection.
- Name remaining errors plainly.
- Avoid marketing superlatives unless they are independently supportable.

Prefer:

> The data now preserves contributors and editions more clearly.

Avoid:

> The contributor and edition schemas received substantial improvements.

Prefer:

> Corrected Bible-book routing restored 1,166 commentary entries.

Avoid:

> The export passed a broad correctness and verification campaign.

## Pre-publication checklist

Before publishing a card or release note, confirm that:

- [ ] The opening explains why the collection exists.
- [ ] Authors, works, editions, and sources appear before implementation details.
- [ ] Counts use understandable, non-conflicting units.
- [ ] Representative works or collections are named.
- [ ] Intended uses and limitations are present.
- [ ] Historical and representational imbalance is acknowledged.
- [ ] Data and code licenses are distinguished.
- [ ] Source provenance is explained.
- [ ] Requested source acknowledgments are visible, including Hymnary.org and
      CCEL, with a link to the complete source ledger.
- [ ] Claims about public-domain status distinguish old works from modern
      editions, transcriptions, digitizations, and databases.
- [ ] Loading and version-pinning examples work.
- [ ] The card has a compact, user-relevant version history.
- [ ] Full notes explain the human significance of changes.
- [ ] Internal upload or validation language has been removed or translated.
- [ ] Every correctness claim has concrete support.
- [ ] The canonical card and upload-ready README are synchronized.
- [ ] YAML metadata parses and lists every published configuration.

## Reference examples

These examples are useful models, not templates to copy mechanically:

- [PleIAs Common Corpus](https://huggingface.co/datasets/PleIAs/common_corpus) —
  leads with openness, traceability, cultural heritage, and curation.
- [Hugging Face FineWeb](https://huggingface.co/datasets/HuggingFaceFW/fineweb) —
  strong one-line identity, practical loading guidance, construction details,
  limitations, and a concise changelog.
- [AI2 Dolma](https://huggingface.co/datasets/allenai/dolma) — clear versions
  table with short, meaningful descriptions.
- [BigCode The Stack](https://huggingface.co/datasets/bigcode/the-stack/blob/v1.1/README.md) —
  provenance, licensing, intended use, and responsible-use limitations.
- [OpenAssistant OASST1](https://huggingface.co/datasets/OpenAssistant/oasst1) —
  opens with purpose and the people behind the corpus, then makes its structure
  understandable.
- [Wikimedia Wikipedia](https://huggingface.co/datasets/wikimedia/wikipedia) —
  a lean example covering loading, fields, source, processing, and licensing.

The supporting comparison and source notes are in
[`research/2026-07-17-huggingface-dataset-card-style-survey.md`](../research/2026-07-17-huggingface-dataset-card-style-survey.md).
