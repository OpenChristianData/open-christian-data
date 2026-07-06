# ADR-0002: Within-edition reconciliation only

**Status:** Accepted (2026-05-15)

## Context

A multi-source reconstruction pipeline can reconcile renderings at one of two levels:

1. **Within-edition.** All renderings being reconciled are renderings of one specific edition. Disagreements between them are OCR / transcription / typographic noise. The reconcile algorithm denoises.
2. **Across editions.** Renderings span multiple historical editions of the work. Disagreements include real textual variants (the author or a later editor changed something). The reconcile algorithm must distinguish noise from signal — a much harder problem and the territory of scholarly textual collation.

Both modes are valid for different projects. The choice shapes the algorithm, the publishing surface, and the project's scope.

## Decision

OCD reconciles **within-edition only**. Each published record cites one specific edition; the renderings reconciled for that record are all renderings of that edition. Cross-edition variants are out of scope as a Reconcile output.

A work may have multiple published records corresponding to multiple editions (Calvin's *Institutes* could publish a 1559-Latin record and a 1845-Beveridge-English record as siblings), but each record is internally a within-edition reconciliation. Cross-edition apparatus across those records is not produced.

When a work has only one PD rendering, single-source publication is permitted (see ADR coverage in the rearchitecture plan). Reconcile runs trivially in that case; the architecture handles it the same way as multi-rendering reconciliation.

## Consequences

**Positive**
- The Reconcile algorithm is much simpler. Disagreements can be assumed mostly noise; OCR-skeleton normalisation and per-language error models handle the common cases.
- No need for scholarly-collation libraries (e.g. CollateX). Existing OCD primitives (`text_alignment.py`) extended to N-way are sufficient.
- The publishing story stays clean: one record per published edition; PD-anchored citation is unambiguous.
- Matches the non-goal of not building a competing critical edition.

**Negative**
- A consumer who wants cross-edition variants will not find them in OCD. They must compare records (one per edition) themselves.
- Edition selection (the PD anchor decision per work) is consequential; we deliberately do not surface variants across editions, so the choice of which edition to publish matters more.
- Future pivot toward cross-edition apparatus would mean a real architectural extension, not just a configuration toggle.

## Alternatives considered

- **Across-edition reconciliation with apparatus output.** Rejected because (i) it is the territory of scholarly textual criticism, which the non-goals exclude; (ii) the algorithm is materially harder and would pull in heavy collation libraries; (iii) the published surface would become a variant apparatus, not a clean text — a different product.
- **Within-edition for v1, across-edition deferred.** Rejected as a framing; ADR-0008 (built once; no v2 lane) makes "deferred" not a valid lane. Either ship the capability or rule it out. We rule it out.
