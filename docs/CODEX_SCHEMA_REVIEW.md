# Open Christian Data -- Independent Schema Review

**Date:** 2026-03-27  
**Reviewer:** Codex  
**Scope reviewed:** `docs/SCHEMA_SPEC.md` v2.1.0, `schemas/v1/commentary.schema.json`, `schemas/types.ts`, `data/commentaries/matthew-henry/ezekiel.json`, `raw/bible_databases/formats/json/BSB.json`, `raw/Creeds.json`, `raw/Commentaries-Database`, and the representative samples in `raw/samples/`.

---

## 1. Executive Verdict

The v2.1.0 specification is a real improvement over v1: the source/enrichment/derived split is directionally right, the doctrinal and structured-text redesigns are much closer to the real data, and the ML/export story is materially stronger. The biggest remaining risk is not the field design inside individual records; it is the architecture around them. In particular, the spec is ahead of the actual validation layer, the verse hub currently treats OSIS as more universal than it really is, and the source layer still carries some build-time and interpretive fields that undermine the stated "source fidelity first" principle. If those three issues are tightened now, the schema family will be much harder to break later.

---

## 2. Critical Findings

### Critical 1. The v2 spec is ahead of the actual schema implementation

**Issue:** The spec says JSON Schema files in `schemas/v1/` are the source of truth, but the repo currently only has one schema file, `commentary.schema.json`, and it is still v1-shaped. `schemas/types.ts` is also still v1-only and commentary-only.

**Why it matters:** This creates false confidence. A maintainer reading the spec would assume the v2.1.0 envelope, `Reference` object, `structured_text`, `doctrinal_document`, verse hub, and enrichment split are enforceable today. They are not. That gap will produce parser drift, hand-written one-offs, and breaking migrations later.

**What I'd change:** Before publishing more schema types, create `schemas/v2/` and move the authority claim there. Add:

- `schemas/v2/meta.schema.json`
- one schema file per v2 schema type
- regenerated `schemas/types.ts` from v2 JSON Schema
- a temporary warning in `SCHEMA_SPEC.md` that v2 is design-authoritative but not yet validation-authoritative until the schema files land

### Critical 2. `meta.scope` is under-specified and will become a junk drawer

**Issue:** The spec uses `meta.scope` for file-scoped fields, but it never defines a formal contract for what belongs there beyond a few examples. `bible_text` expects `meta.scope.book_osis`; verse-keyed resources use `verse_text_source`; other types may need collection-level or document-level scope.

**Why it matters:** Undefined "scope" objects inevitably turn into catch-alls. Different parsers will add different keys, downstream consumers will not know what is stable, and schema evolution will become ad hoc.

**What I'd change:** Replace generic `meta.scope` with typed resource-scope objects. For example:

- `book_scope` for `bible_text` and book-scoped commentary
- `document_scope` for confessions/catechisms
- `collection_scope` for sermons, hymns, devotionals

At minimum, define the allowed keys for `meta.scope` per `schema_type` in JSON Schema.

### Critical 3. The verse hub overstates "verse as universal join key"

**Issue:** The spec presents the verse as the universal join primitive, but the actual data already includes verse ranges, cross-chapter spans, and multiple versification systems. Cross-tradition growth will add Psalms numbering differences, Esther/Daniel expansions, and deuterocanonical edge cases.

**Why it matters:** This is the hardest thing to reverse later. If you build the whole graph and retrieval architecture on a single verse key without a span model and versification mapping layer, you will eventually mis-join data or block entire traditions.

**What I'd change:** Make the canonical join primitive a versification-qualified span, not a single verse string. Concretely:

- add a `reference_span` shape with `raw`, `osis`, `versification`, `start_osis`, `end_osis`
- build the verse hub by expanding spans into verse rows at build time
- add a separate passage/span index for retrieval and annotation
- keep versification mapping tables as first-class build assets, not implicit parser logic

### Critical 4. The source layer still contains non-source, build-time, and interpretive fields

**Issue:** The spec says the canonical JSON is source-faithful, but the cross-cutting record fields still include `token_count`, `content_hash`, and `related_entries`. In practice, `related_entries` is interpretive enrichment, and `token_count`/`content_hash` are build diagnostics.

**Why it matters:** This weakens the most important design principle in the document. It also makes canonical JSON less stable across rebuilds and less pleasant to diff or curate.

**What I'd change:** Move these out of source records:

- `token_count` -> derived exports and chunk exports
- `content_hash` -> diagnostics/dedup sidecar or derived exports
- `related_entries` -> enrichment/graph layer with evidence and confidence

If you keep any of them in canonical JSON, explicitly say canonical JSON is "source-faithful plus stable operational metadata," not purely source-faithful.

---

## 3. Major Findings

### Major 1. `prayer` still overfits poetic lineation

**Issue:** The prayer schema models prayers as `stanzas[].lines[]`, borrowing from hymn/poetry standards. But the Didache and BCP samples are prose prayers embedded in liturgical or prose contexts. Their line breaks are transcription/layout artifacts, not authored poetic lines.

**Why it matters:** You risk preserving the wrong structure. Two transcriptions of the same prayer will produce different line arrays even when the prayer itself is identical.

**What I'd change:** Use `content_blocks` or typed `segments` for `prayer`, and reserve stanza/line modeling for `hymn`. If a prayer is genuinely verse-like, add an optional `presentation: "verse"` hint instead of making verse layout the core model.

### Major 2. The spec needs a work/edition model, not just an author registry

**Issue:** The author registry is useful, but it is not enough to support deduplication, parallel editions, translated witnesses, revised confessions, or multiple manifestations of the same work.

**Why it matters:** "Same work, different edition/translation/source" is going to recur constantly. Without explicit work/expression/edition IDs, the deduplication policy will stay fuzzy and derived exports will collapse concepts that should stay distinct.

**What I'd change:** Add resource-level identity fields:

- `work_id` -- abstract work
- `edition_id` or `expression_id` -- specific text version/translation/revision
- `source_instance_id` -- the fetched manifestation used by this dataset build

This does not need full FRBR complexity. A lightweight three-level identity model is enough.

### Major 3. `related_entries` needs annotation provenance, not just a relationship label

**Issue:** The relationship vocabulary is promising, but edges like `"echoes"`, `"contradicts"`, and `"responds_to"` are interpretive and potentially controversial.

**Why it matters:** Without provenance, confidence, and evidence spans, consumers cannot trust or audit the graph. The project is explicitly curated, which means editorial edges need editorial accountability.

**What I'd change:** Define relationship edges as annotation records with:

- `source_entry_id`
- `target_entry_id`
- `relationship`
- `evidence_span`
- `annotator_type` (`human`, `ai`, `human-reviewed-ai`)
- `confidence`
- `review_status`

### Major 4. The current verse hub should be paired with a passage hub

**Issue:** Verse-level aggregation is powerful, but many entries are naturally passage-based: commentary on Rom. 3:21-31, sermons on Mal. 3:6, catechism proofs spanning multiple verses, and patristic quotes on ranges.

**Why it matters:** Pure verse expansion is good for cross-linking, but poor for retrieval, chunking, and human navigation. Users often want "all material on Romans 3:21-31," not eleven separate verse rows.

**What I'd change:** Keep the verse hub, but add a `passage_hub` or `reference_span_index` with:

- normalized span ID
- start/end verse
- versification
- all source entries anchored to that span

### Major 5. Editorial classifications need controlled vocab guidance and provenance

**Issue:** Fields like `commentary_type`, `audience`, `era`, and some future tags are not source facts; they are curation judgments.

**Why it matters:** These are useful, but they will become inconsistent quickly unless there is a written policy. "Pastoral" vs "lay" vs "scholarly" is not objective. The same goes for `commentary_type`.

**What I'd change:** Keep these fields, but treat them as curated metadata with:

- a controlled vocabulary file
- short definitions and examples
- optional `classification_confidence`
- human-review expectation for anything not parser-obvious

### Major 6. The current deduplication policy needs edition-aware wording

**Issue:** The policy distinguishes duplicates from parallels and citations, which is good, but it does not yet clearly separate work identity from expression identity.

**Why it matters:** "Same catechism Q&A in two files" and "same commentary in two sources" are not enough. The real hard cases are revised editions, modernized spelling, partial abridgments, and collections that reprint an older work with new headings.

**What I'd change:** Rewrite the dedup policy around three questions:

1. Is this the same work?
2. Is this the same expression/edition?
3. Is this the same manifestation/source instance?

Only the third category should be aggressively deduplicated by default.

---

## 4. Minor Findings

### Minor 1. `Reference` needs a parse-status convention

**Issue:** The `Reference` object allows empty `osis`, which is good, but it does not say how parse failures are recorded or triaged.

**Why it matters:** For messy historical references, an empty array is not enough to debug parser quality or manual cleanup needs.

**What I'd change:** Add either:

- `parse_status` (`parsed`, `partial`, `unparseable`)
- or a separate parser diagnostics file keyed by record and raw reference

### Minor 2. `text_for_embedding` should usually include minimal context

**Issue:** A clean text field is useful, but raw body text alone can be semantically thin for retrieval. "Explain [verse]" data is more useful when author/title/reference context is also available.

**Why it matters:** Embeddings and RAG quality often improve when the text carries lightweight context, especially across many homogeneous records.

**What I'd change:** Publish both:

- `text_for_embedding` -- plain cleaned text
- `retrieval_text` -- metadata-prefixed text such as `"Matthew Henry on Ezekiel 1:1-3: ..."`

### Minor 3. The author registry should handle unknown, collective, and translator roles explicitly

**Issue:** Many resources have collective authorship, disputed authorship, editors, or translators that matter semantically.

**Why it matters:** Long-term, "author" alone will not be enough for attribution or influence tracking.

**What I'd change:** Add support for:

- `contributors` with role labels
- `translator_ids`
- collective authors
- uncertain attribution flags

### Minor 4. The standards section would be stronger with concrete mapping notes

**Issue:** The spec lists standards, but not the exact fields or concepts adopted from each.

**Why it matters:** Future contributors will know which standards were consulted, but not how strictly the repo follows them.

**What I'd change:** Add a one-line "borrowed concept" note per standard in a separate appendix or design memo.

---

## 5. ML-Specific Findings

### ML 1. Chunked retrieval exports are missing

**Issue:** The spec defines record-level `text_for_embedding`, but many records are too long for optimal embeddings and RAG, especially commentary, sermons, and structured prose.

**Why it matters:** Real retrieval systems do not embed 4,000-word sermons as a single vector and expect good results.

**What I'd change:** Add a chunk export with:

- `chunk_id`
- `entry_id`
- `chunk_index`
- `token_start`
- `token_end`
- `text`
- `retrieval_text`
- `section_path`
- `anchor_ref` or primary reference context

### ML 2. A split/leakage policy is missing

**Issue:** The spec discusses deduplication but not train/validation/test separation.

**Why it matters:** Without a leakage policy, the same text or near-duplicate can end up in multiple splits, especially once multiple sources, reprints, and derived instruction pairs are added.

**What I'd change:** Define split rules now:

- split by work/edition family, not by random row
- keep parallel translations together or explicitly mark them
- keep derived instruction pairs tied to their source split

### ML 3. Graph outputs need edge confidence and source provenance

**Issue:** The cross-reference graph is valuable, but graph ML is only as good as its edges.

**Why it matters:** Interpretive or parser-generated edges without provenance will create noisy training signals.

**What I'd change:** Add:

- `edge_source` (`parser`, `human`, `ai`, `human-reviewed-ai`)
- `confidence`
- `evidence_type`

### ML 4. Span offsets would materially improve attribution in RAG

**Issue:** The enrichment layer stores summary and key-quote source spans as text descriptions, not machine-usable offsets.

**Why it matters:** For auditability and answer grounding, byte/token/paragraph offsets are much stronger than prose labels like `"paragraphs 1-3"`.

**What I'd change:** Standardize paragraph IDs or span offsets per record and reuse them across enrichment, chunking, and graph annotation.

---

## 6. Proposed Schema Changes

### Change 1. Replace generic `meta.scope` with typed scope schemas

**Issue:** Generic scope is underspecified.

**Why it matters:** It will drift.

**Change:** Define schema-specific scope objects, for example:

```json
{
  "book_scope": {
    "book_osis": "Gen",
    "book_number": 1,
    "verse_text_source": "BSB"
  }
}
```

### Change 2. Introduce a `reference_span` contract

**Issue:** `raw` + `osis[]` is not enough for universal join semantics.

**Why it matters:** Versification and spans need explicit structure.

**Change:** Extend references with:

```json
{
  "raw": "Rom. 8. 33 &c.",
  "osis": ["Rom.8.33-Rom.8.39"],
  "versification": "KJV",
  "start_osis": "Rom.8.33",
  "end_osis": "Rom.8.39"
}
```

### Change 3. Move operational fields out of source records

**Issue:** `token_count`, `content_hash`, `related_entries` muddy source fidelity.

**Why it matters:** Rebuild churn and architectural leakage.

**Change:** Publish them in derived outputs or sidecars, not `data/`.

### Change 4. Change `prayer.stanzas` to prose-friendly content blocks

**Issue:** Many prayers are not verse texts.

**Why it matters:** False structure is worse than coarse structure.

**Change:** Replace:

```json
"stanzas": [{"lines": [...]}]
```

with:

```json
"content_blocks": ["We thank thee, our Father...", "..."]
```

and keep verse-style segmentation optional.

### Change 5. Add work/edition identity fields to the metadata envelope

**Issue:** Author identity is not enough for dedup and retrieval.

**Why it matters:** Same work, different edition is a recurring reality.

**Change:** Add optional envelope fields:

- `work_id`
- `edition_id`
- `translation_id`

### Change 6. Upgrade relationship edges into auditable annotation records

**Issue:** Simple `related_entries` arrays are too thin.

**Why it matters:** They cannot support trustworthy curation or graph ML.

**Change:** Store relationship annotations as separate records with evidence and review metadata.

### Change 7. Add a chunk export contract now, not later

**Issue:** ML usability depends on chunking.

**Why it matters:** It influences entry IDs, span offsets, and graph references.

**Change:** Define a derived chunk schema in the spec appendix even if the pipeline lands later.

---

## 7. Missing Content Types or Infrastructure

### Missing infrastructure 1. Work/edition registry

The author registry is helpful, but a work/edition registry is the more urgent missing identity layer.

### Missing infrastructure 2. Versification mapping tables

If cross-tradition content is genuinely welcome, mapping tables cannot stay implicit.

### Missing infrastructure 3. Passage/span index

The verse hub should be complemented by a passage-oriented index for retrieval and UI.

### Missing infrastructure 4. Chunk registry

If chunk exports are added, chunk IDs and span boundaries should be stable and reproducible.

### Missing content type 1. Lectionary / liturgical calendar mappings

Already noted in open issues, and I agree it is high-utility once liturgical materials expand.

### Missing content type 2. Biblical passage/pericope index

Not a source corpus, but useful infrastructure for grouping commentary, sermons, and devotionals around common passages rather than only verses.

---

## 8. Questions for the Maintainer

1. Is non-Protestant canon support a real planned outcome, or only a theoretical future possibility? The answer affects whether versification mapping is a now problem or a later problem.
2. Do you want canonical JSON in `data/` to be reproducible and stable across rebuilds, or are build-derived fields allowed to churn those files?
3. Should editorial classification fields like `commentary_type`, `audience`, and `era` be parser-generated, human-curated, or mixed with review?
4. Is the deduplication target "same manifestation," "same edition," or "same work"? The spec currently hints at all three.
5. Will retrieval in the Daily Devotional app be verse-first, passage-first, or author/work-first? That choice should shape the passage hub and chunk export design.
6. Do you want enrichment annotations to be auditable at the paragraph/span level? If yes, paragraph IDs or offsets should become first-class now.

---

## Bottom Line

The v2 revision fixes most of the obvious schema-shape problems from v1. The remaining hard problems are not about whether `hymn` should have `lines[]`; they are about whether the architecture can survive scale, multiple editions, multiple versification systems, and ML/RAG production use without painting itself into a corner. I would not redesign the schema family again from scratch. I would tighten the implementation contract, formalize identity and reference spans, and keep the source layer cleaner than it currently is.
