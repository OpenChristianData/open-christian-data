# Codex Schema Review Prompt

Paste this entire document into Codex for an independent schema review.

---

## Context

You are reviewing the schema specification for **Open Christian Data** -- an open-source project that processes public domain Christian literature (commentaries, confessions, catechisms, sermons, hymns, prayers, devotionals, theological works, dictionaries, topical indexes) into structured, machine-readable datasets (JSON, SQLite, Parquet) for developers and AI/ML training.

The project has already:
1. Published Matthew Henry's commentary on Ezekiel (132 entries, 232k words) as structured JSON with BSB verse text and OSIS references
2. Downloaded and inspected representative samples of every schema type from real sources
3. Run one round of red-teaming (by you), which led to a major v2 revision
4. Researched 15+ non-religious schema standards (OSIS, SWORD, OpenLyrics, Akoma Ntoso, W3C Web Annotation, SKOS, MusicBrainz, TEI, PoetryDB, Wiktextract, Fountain, Atom, QTI, SQuAD, USFM/USX)
5. Added ML infrastructure: token counts, content hashing, verse hub index, author registry, cross-reference graph, text-for-embedding field, reading complexity scores

## Your Task

Review the schema specification below with these goals:

1. **Find structural weaknesses** -- schemas that don't fit real data, fields that will cause problems at scale, architectural decisions that will be hard to reverse
2. **Find gaps** -- content types, metadata fields, or cross-cutting concerns we haven't thought of
3. **Find over-engineering** -- complexity that doesn't earn its keep for the stated audience (developers + ML/AI training)
4. **Evaluate ML readiness** -- will this dataset be genuinely useful for fine-tuning, RAG, embeddings, and knowledge graph construction? What's missing?
5. **Evaluate interoperability** -- will consumers in the Bible software ecosystem (SWORD, Logos, BibleGateway), digital humanities (TEI), and ML (HuggingFace) be able to use this without friction?
6. **Cross-reference with your own knowledge** -- are there schema standards, dataset formats, or ML best practices we haven't considered?
7. **Challenge the three-layer architecture** -- is source/enrichment/derived the right split? Are there cases where it breaks down?
8. **Stress-test the verse hub concept** -- is OSIS as universal join key robust enough? What about versification differences, verse ranges, passages that span chapter boundaries?
9. **Evaluate the deduplication policy** -- is the distinction between true duplicates and parallel texts well-defined enough?
10. **Propose specific improvements** -- not just "consider X" but "change field Y to Z because W"

## Constraints

- The project ships CC0 public domain data. No copyrighted content.
- Protestant/Reformed priority for active development, but all traditions welcome as contributions.
- Monorepo structure. JSON is the canonical format; SQLite/Parquet/CSV are derived.
- Build pipeline is Python. Validation uses JSON Schema (Draft 2020-12).
- The first consumer is a personal Daily Devotional App. External adoption validates public value.
- American English in all project output (anonymity protocol).
- This is a curation project, not just a data project. Summaries and editorial decisions require theological care.

## Output Format

Structure your review as:

1. **Executive verdict** (3-5 sentences)
2. **Critical findings** (things that will cause real problems)
3. **Major findings** (things worth changing before more schemas are published)
4. **Minor findings** (nice-to-haves, polish)
5. **ML-specific findings** (gaps or improvements for training/RAG/embedding use)
6. **Proposed schema changes** (specific field-level recommendations with rationale)
7. **Missing content types or infrastructure** (anything we haven't thought of)
8. **Questions for the maintainer** (things you can't evaluate without more context)

For each finding, state:
- What the issue is
- Why it matters
- What you'd change (specific, not vague)

---

## Schema Specification (v2.1.0)

[PASTE THE FULL CONTENTS OF docs/SCHEMA_SPEC.md BELOW THIS LINE]
