# Open Christian Data -- Semantic Cross-Reference and Specialist LLM Notes

**Date:** 2026-03-27  
**Purpose:** Capture ML-first schema and architecture ideas for semantically cross-referencing the corpus and eventually training or grounding a specialist Christian LLM.

---

## Executive Take

If Open Christian Data eventually powers a specialist Christian LLM, the biggest wins will not come from adding more blob fields to each record. They will come from adding better identity, better spans, better semantic annotations, and better evaluation data.

The current direction is strong: source/enrichment/derived is a good base. But for semantic retrieval, graph construction, and future fine-tuning, I would extend that into a richer architecture with:

1. a source layer
2. an authority/ontology layer
3. a semantic annotation graph layer
4. an editorial enrichment layer
5. a derived ML/export layer
6. an evaluation/benchmark layer

The key idea is simple: **keep source text clean, and put semantics in auditable stand-off records.**

---

## Recommended Architecture

### 1. Source

Canonical JSON in `data/`:

- faithful to the source text
- stable IDs
- minimal editorial interpretation
- clean provenance

### 2. Authority and Ontology

Registry-like data in `data/authorities/` or `data/ontology/`:

- authors
- works
- editions / translations
- concepts / doctrines / topics
- traditions / denominational families
- liturgical elements
- biblical entities, places, events

This is where canonical naming and concept normalization should live.

### 3. Semantic Annotation Graph

Stand-off annotations in `annotations/`:

- citation relationships
- proof-text links
- quote / allusion / paraphrase links
- doctrinal claim annotations
- agreement / disagreement edges
- concept assignments
- span-level evidence

This should be separate from source records and separate from summaries.

### 4. Editorial Enrichment

The current enrichment layer is still good:

- summaries
- key quotes
- tags
- reviewer metadata

But it should stay distinct from the semantic graph. Summaries are editorial outputs; semantic edges are structured knowledge.

### 5. Derived ML / Export Layer

Generated outputs in `dist/`:

- SQLite
- Parquet
- chunked retrieval corpora
- graph CSV / JSON-LD
- instruction-tuning pairs
- eval-ready splits

### 6. Evaluation Layer

Benchmarks in `eval/` or `benchmarks/`:

- retrieval evaluation sets
- citation resolution evaluation
- doctrinal stance classification
- author attribution
- cross-tradition comparison tasks
- hallucination / attribution tests

---

## What I Would Add to the Data Model

### A. Multi-Level Identity

Add identity fields beyond `author_id`:

- `work_id` -- the abstract work
- `expression_id` -- a particular revision / translation / recension
- `manifestation_id` -- the concrete publication or digitized manifestation
- `source_instance_id` -- the exact fetched instance used in this build

This is the single most useful identity improvement for deduplication, retrieval, split policy, and theological provenance.

### B. Reference Spans, Not Just Verse Strings

The future semantic key should be a `reference_span`, not just a verse string:

```json
{
  "raw": "Rom. 8. 33 &c.",
  "osis": ["Rom.8.33-Rom.8.39"],
  "versification": "KJV",
  "start_osis": "Rom.8.33",
  "end_osis": "Rom.8.39"
}
```

Then derive:

- verse rows
- passage rows
- verse hub entries
- passage hub entries

### C. Stable Chunk IDs

Every long text should be chunkable into stable ML units:

- `chunk_id`
- `entry_id`
- `chunk_index`
- `section_path`
- `char_start`
- `char_end`
- `token_start`
- `token_end`

Chunking is not optional if you want good retrieval.

### D. Concept IDs

Introduce concept normalization for things like:

- Trinity
- justification
- baptism
- Eucharist / Lord's Supper / Communion
- covenant
- sanctification
- election
- atonement models

Each concept should have:

- `concept_id`
- preferred label
- alternative labels
- broader concept
- related concepts
- optional tradition notes

### E. Claim IDs

If the long-term goal is a specialist LLM, claims matter:

- `claim_id`
- `claim_text`
- `claim_type`
- `concept_ids`
- `stance`
- `evidence_spans`
- `tradition`
- `confidence`
- `review_status`

Examples:

- doctrinal definition
- exegetical interpretation
- historical claim
- moral exhortation
- liturgical instruction

### F. Semantic Edge Records

Replace weak free-form cross-links with auditable edge records:

```json
{
  "annotation_id": "ann-0001",
  "source_entry_id": "matthew-henry-complete.Ezek.1.1-3",
  "target_entry_id": "westminster-confession.chapter-1.section-1",
  "relationship": "proof_text_for",
  "evidence_span": {
    "source_paragraph": 2,
    "char_start": 144,
    "char_end": 201
  },
  "annotator_type": "human-reviewed-ai",
  "confidence": 0.91,
  "review_status": "approved"
}
```

This is much stronger than a plain `related_entries` array.

---

## ML-Specific Improvements

### 1. Keep Fine-Tuning Secondary to Retrieval and Graph Grounding

A specialist Christian LLM should probably be:

- retrieval-first
- graph-aware
- attribution-heavy
- tradition-aware

Pure fine-tuning on raw theological text will compress voices and disagreements too aggressively.

### 2. Publish Two Text Fields

For each record or chunk, publish:

- `text_for_embedding` -- clean body text only
- `retrieval_text` -- body text plus lightweight context

Example `retrieval_text`:

```text
Matthew Henry | Ezekiel 1:1-3 | Reformed / Puritan | Commentary
The circumstances of the vision which Ezekiel saw...
```

### 3. Add Hard Negatives

A Christian retrieval model will benefit from hard negatives like:

- same verse, different doctrinal point
- same topic, different tradition
- same author, different work
- same work, different edition
- same citation string, different interpretation

### 4. Add Benchmark Tasks Early

Useful benchmark families:

- verse -> retrieve best commentary chunks
- doctrine -> retrieve contrasting traditions
- citation string -> resolve to canonical references
- quote -> identify source author/work
- claim -> find supporting and opposing texts
- answer generation -> must cite retrieved evidence

### 5. Make Disagreement First-Class

Theological disagreement is not noise. It is part of the corpus.

Add fields or graph edges for:

- `agrees_with`
- `contradicts`
- `qualifies`
- `reframes`
- `inherits_from`
- `responds_to`

### 6. Add Evaluation Split Policy

Do not split randomly by record. Split by:

- work family
- edition / translation family
- or author family, depending on the task

Otherwise you will leak near-duplicates into validation and test data.

### 7. Add Span-Level Attribution

If summaries, claims, or semantic edges are future training targets, they need exact evidence anchors:

- paragraph IDs
- section IDs
- character offsets
- optional token offsets

This improves auditability and RAG grounding.

---

## Concrete Changes I Would Make to the Current Spec

### Change 1. Add a Separate Semantic Annotation Layer

Current source + enrichment is not quite enough.

Add:

- `annotations/semantic/`
- typed relationship records
- concept assignment records
- claim records

### Change 2. Add a Concept Registry

Add a controlled vocabulary file for doctrines, topics, and traditions.

Minimal first version:

- `concept_id`
- `pref_label`
- `alt_labels`
- `broader`
- `related`

### Change 3. Add a Work / Edition Registry

The author registry is useful, but the next missing identity layer is:

- work
- expression / edition
- manifestation

### Change 4. Add a Passage Hub Alongside the Verse Hub

Keep the verse hub, but add a passage-oriented index for:

- commentary on ranges
- sermons on a text
- multi-verse proof chains
- passage-level retrieval

### Change 5. Move Operational Fields Out of Canonical Source

Prefer to keep fields like:

- `token_count`
- `content_hash`
- ML chunk metadata

out of the canonical source layer and in derived or diagnostic outputs.

### Change 6. Keep `prayer` Prose-Friendly

Do not force prose prayers into hymn-like stanza structures. Use `content_blocks` or `segments`, and only use `lines[]` where the source is genuinely lineated.

### Change 7. Add a `retrieval_text` Export

This is a simple change with high ML value.

---

## Roughly Equivalent Non-Religious Text Types

| OCD type | Rough non-religious equivalent |
|----------|-------------------------------|
| `commentary` | legal commentary, annotated statutes, scholarly annotation on canonical texts |
| `doctrinal_document` | constitutions, bylaws, legal codes, standards documents, manifestos |
| `catechism_qa` | assessment item banks, exam prep, FAQ corpora, flashcards |
| `structured_text` | monographs, treatises, manuals, philosophical works |
| `church_fathers` | quotation corpora, literary annotations, excerpt/commentary databases |
| `sermon` | speeches, lectures, talks, orations |
| `devotional` | daily meditations, dated newsletters, almanac-style readings |
| `prayer` | poems, scripted readings, ritualized speech |
| `hymn` | songs, lyric sheets, poems |
| `liturgical_service` | screenplays, theater scripts, event programs, performance cue sheets |
| `reference_entry` | dictionaries, encyclopedias, glossary entries |
| `topical_reference` | thesauri, subject heading systems, topical indexes |

---

## External Standards Worth Borrowing From

I checked current official docs for these on 2026-03-27. These are the strongest analogs I found.

### 1. MusicBrainz

Link: <https://musicbrainz.org/doc/MusicBrainz_Database/Schema>

Why it matters:

- strong `work` vs `recording` / instance separation
- aliases and alternate titles
- relationship tables
- annotation model

Best fit for:

- hymns
- author/work identity
- edition / manifestation modeling

### 2. OpenLyrics

Link: <https://docs.openlyrics.org/en/latest/dataformat.html>

Why it matters:

- stanza and verse naming
- multilingual lyric handling
- clean song-text structure

Best fit for:

- hymns
- future song / chant / liturgical lyric data

### 3. Akoma Ntoso

Link: <https://docs.oasis-open.org/legaldocml/akn-core/v1.0/os/part1-vocabulary/akn-core-v1.0-os-part1-vocabulary.pdf>

Why it matters:

- recursive hierarchical documents
- revisions and lifecycle concepts
- strong legal / constitutional document modeling

Best fit for:

- confessions
- canons
- creeds
- church orders

### 4. W3C Web Annotation Data Model

Link: <https://www.w3.org/TR/annotation-model/>

Why it matters:

- stand-off annotations
- bodies and targets
- selectors for sub-spans
- interoperable semantic linking

Best fit for:

- commentary cross-links
- proof-text edges
- quote / allusion / paraphrase annotations
- review metadata

### 5. SKOS

Link: <https://www.w3.org/2006/07/SWD/SKOS/reference/master.html>

Why it matters:

- preferred labels
- alternate labels
- broader / narrower / related concepts

Best fit for:

- topic vocabularies
- doctrine taxonomies
- tradition vocabularies

### 6. MADS/RDF

Link: <https://www.loc.gov/standards/mads/rdf/>

Why it matters:

- richer authority modeling than SKOS alone
- names, titles, organizations, places

Best fit for:

- author registry
- work titles
- alternate forms and honorifics

### 7. OntoLex-Lemon

Link: <https://www.w3.org/2016/04/ontolex/>

Why it matters:

- lexical forms linked to concepts
- multilingual and alternate-expression support

Best fit for:

- doctrine labels
- reference entries
- topic normalization

### 8. BIBFRAME

Link: <https://www.loc.gov/bibframe/>

Why it matters:

- bibliographic identity and instances
- contributor roles
- library-grade resource modeling

Best fit for:

- work / edition / manifestation
- structured bibliographic metadata

### 9. DataCite Relation Types

Links:

- <https://schema.datacite.org/>
- <https://support.datacite.org/docs/connecting-to-works>

Why it matters:

- explicit relation vocabulary
- versioning and work-to-work links

Best fit for:

- edition relationships
- source / derived relationships
- citation semantics

### 10. CiTO

Link: <https://sparontologies.github.io/cito/current/cito>

Why it matters:

- typed citation relationships

Best fit for:

- `quotes`
- `supports`
- `disagrees_with`
- `uses_as_evidence`
- richer semantic edges

### 11. QTI

Link: <https://www.1edtech.org/standards/qti/index>

Why it matters:

- item-bank thinking
- structured question/answer ecosystems

Best fit for:

- catechisms
- pedagogical exports
- future educational interfaces

### 12. TEI and EPUB

Links:

- <https://tei-c.org/>
- <https://www.w3.org/TR/epub-ssv-11/>

Why they matter:

- structured books, verse, drama, dictionaries, speeches
- rich section and semantic text markup

Best fit for:

- structured prose
- prayers
- sermons
- dictionaries
- liturgical materials

### 13. IIIF Presentation API

Link: <https://iiif.io/api/presentation/3.0/>

Why it matters:

- page / canvas / range modeling
- future facsimile alignment
- image-to-text anchoring

Best fit for:

- scanned source auditability
- page-level citation
- future scholarly workflows

---

## Most Useful Borrow, by OCD Schema Type

| OCD type | Best external analogs |
|----------|-----------------------|
| `commentary` | Web Annotation, CiTO |
| `doctrinal_document` | Akoma Ntoso |
| `catechism_qa` | QTI |
| `structured_text` | TEI, EPUB, BIBFRAME |
| `church_fathers` | Web Annotation, passage/span indexing |
| `sermon` | TEI, EPUB |
| `devotional` | EPUB, chunk/eval design more than external schema |
| `prayer` | TEI prose / verse, not song schemas by default |
| `hymn` | OpenLyrics, MusicBrainz |
| `liturgical_service` | TEI drama + performance/script ideas, eventually IIIF for facsimiles |
| `reference_entry` | OntoLex-Lemon, MADS/RDF, TEI dictionaries |
| `topical_reference` | SKOS, OntoLex-Lemon |

---

## Suggested Near-Term Roadmap

### Phase 1 -- Identity and Spans

- add `work_id`, `expression_id`, `manifestation_id`
- add `reference_span`
- add passage hub

### Phase 2 -- Semantic Layer

- add concept registry
- add semantic annotation records
- seed a small human-reviewed relation set

### Phase 3 -- ML Exports

- add stable chunk export
- add `retrieval_text`
- add split policy
- add first retrieval benchmark

### Phase 4 -- Scholarly / Audit Extensions

- add page anchors
- add IIIF-ready facsimile alignment
- add claim / disagreement annotations

---

## Bottom Line

If the long-term goal is a specialist Christian LLM, the best upgrade is **not** "more metadata on each source record." It is:

- better identity
- better spans
- better semantic annotations
- better concept normalization
- better chunking and evaluation

That will make the dataset far more reusable for:

- RAG
- graph retrieval
- contrastive training
- instruction tuning
- attribution-safe answer generation
- cross-tradition comparison

And it will do so without sacrificing the clean canonical JSON model the project is already moving toward.
