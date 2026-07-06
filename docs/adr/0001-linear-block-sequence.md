# ADR-0001: Linear block sequence as universal data structure

**Status:** Accepted (2026-05-15); partially superseded by [ADR-0019](0019-ir-is-tei.md) 2026-07-01 — the IR / published shape is now TEI, not a flat block sequence. This ADR's principle (structure as annotation; never fabricate hierarchy the source lacks) still informs how the project uses TEI. Whether the OCR-fusion internal working schemas remain JSON is left open by ADR-0019.

## Context

The pre-rearchitecture OCD schemas are resource-type-shaped. Commentary records are `data: array of verse-keyed entries`; reference records are arrays of term-keyed entries; devotionals are date-keyed. Each schema dictates the shape of its resource type and makes structural metadata (verse, term, date) the organising key.

This works for resource types that match the schema's assumption. It breaks for works that do not — Calvin's *Institutes* is chapter/section-organised, Augustine's *Confessions* is book/paragraph-organised, a thematic commentary may have no verse keys at all. Such works either get jammed into a schema that does not fit, or get a new schema, fragmenting the architecture.

The deeper problem: structural metadata is overlay information, not the spine of the data. The spine is the text and its natural blocks. The schema mistakenly let an overlay become the organising structure.

## Decision

Adopt a single universal data shape for all reconciled records: a **linear sequence of blocks in source order**. A block is a unit of source text (paragraph, heading, list item, footnote, lemma, verse line, headword, quote, table row). Each block carries `block_type`, `original_text`, `language`, optional `language_segments`, `annotations`, `source_pages`, `attested_by`, `disagreements`, `structural_disagreements`, and (when modernised) `modernisations`.

Structural metadata that used to drive the schema (verse references, dates, terms, section paths, chapter numbers) becomes per-block **annotations**. Different resource types differ only in which annotations are conventionally present, not in the schema's overall shape.

## Consequences

**Positive**
- One reconciled-record schema covers every resource type. New resource types do not need new schemas; they need annotation conventions.
- The Reconcile algorithm is one algorithm operating on linear block sequences. Per-resource-type code only declares which annotations are expected.
- Source structure is preserved exactly — if Wesley's source has a heading before each verse, the heading is a block; if not, no fake heading is invented.
- Different structures across renderings (one merges where another splits) are handled by structural-disagreement records, not by data loss or fabrication.
- Annotations can be added, corrected, or extended post-reconstruction without touching the text.

**Negative**
- Every existing record migrates to a new shape. The transformation is mechanical (existing structured-key entries flatten into annotated blocks) but touches all 688 records.
- Existing per-resource-type schemas evolve into resource-type-specific *annotation validators* on a shared block-sequence core. Validation moves from schema-shape to schema-content.
- Consumers expecting the old verse-keyed / term-keyed shape need to migrate. None are in production today; future-cost prevention.

## Alternatives considered

- **Keep per-resource-type schemas; bolt multi-source onto each.** Rejected because the structural rigidity is the underlying problem. Multi-source-on-top-of-rigid-schemas keeps the structural mismatch and adds provenance noise.
- **Per-resource-type schemas, all of which extend a common core.** Considered. Rejected because the "common core" turned out to be the universal shape; the per-type extensions reduced to annotation conventions, not structural variation. One schema covers it.
- **Hierarchical block-tree** (nested blocks: chapter contains sections contains paragraphs). Rejected because nesting is itself a structural assumption that some works do not share. Annotations capture nesting metadata (section path, depth) without forcing it into the data shape.
