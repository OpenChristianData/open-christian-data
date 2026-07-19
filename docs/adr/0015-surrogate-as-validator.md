# ADR-0015: Surrogate as validator, not gold as prerequisite

**Status:** Accepted (2026-06-05) — revised 2026-06-05 after adversarial review ([REVIEW_0014_0015_adversarial.md](REVIEW_0014_0015_adversarial.md)): stratified thresholds, a statistical acceptance rule, and a Schaff-Herzog transfer check were added.

## Context

The build treated a human-adjudicated gold set as the gate for all correction. The tuning embargo holds the reconciler in degraded mode — every signal weight is 0.0, nothing is auto-chosen, everything routes to review — until a non-circular reference exists (`../EzraOCR/docs/PIPELINE_BUILD_STATE.md`).

Two facts reframe this. First, the highest-return research-attested techniques — character-column voting, lexicality rescoring, in-corpus language-model rescoring, and active-learning sample selection — are unsupervised; they need no human gold. Second, the Jewish Encyclopedia (1906) provides a paired diplomatic transcription and page facsimiles of the same edition: a non-circular reference with no edition offset (unlike the CCEL proposal, a 1951 reprint scored against 1908–1914 scans). The embargo conflated "the confidence-weighted matrix needs gold" with "all correction needs gold."

## Decision

The gold-free corrector stack runs before human adjudication. Gold — both human-adjudicated Schaff-Herzog positions and the Jewish Encyclopedia surrogate — is a validator, not a runtime prerequisite. It measures per-method false-correction rate, coverage, and real-word-error rate.

**The surrogate certifies the mechanism, not a single corpus-wide bar.** The auto-accept threshold targets surrogate-measured false-correction near 0.1% (the 99.9% first-pass bar), but that target is applied *per stratum* — `(level, method, token-class, script, typography, engine-mix)` — not as one per-level aggregate, because real-word errors concentrate in classes (names, dates, references, mixed scripts) that a pooled rate hides.

**A statistical acceptance rule, not a raw count.** "Zero observed false corrections" never clears a threshold on its own. Auto-accept requires the stratum's denominator to support the chosen confidence bound — a 95% upper bound below 0.1% needs roughly 3,000 accepted corrections in that stratum with zero errors. Under-powered strata route to flagged output or review; they are never auto-accepted on a thin sample.

**Transfer is not assumed.** Same-edition facsimiles make the Jewish Encyclopedia non-circular, but non-circular is not the same as transferable: Schaff-Herzog has its own typography, name density, Scripture-reference density, and script mix. The surrogate certifies that the machinery works; a small human-adjudicated Schaff-Herzog transfer-check sample gates unflagged release of each token class. Human gold is therefore not required to *build* the unsupervised stack, but a bounded human sample is required to *certify transfer* before any L1–L3 class publishes unflagged.

The pipeline must never require a per-text reference at runtime, because future texts will lack one. The human gold set remains required for the confidence-weighted matrix and the LLM-in-loop layer, but it no longer gates unsupervised correction.

## Consequences

**Positive**
- Most correctable error is recovered before any human time is spent.
- Human adjudication shrinks to the active-learning-selected ambiguous residue.
- The surrogate answers the keep-matrix and auto-accept questions that the circular within-corpus reference could not.
- The architecture generalises to future texts that have no gold.

**Negative**
- The surrogate becomes a standing validation oracle, re-run on corrector changes — aggressive correction levels can inject real-word errors, so a one-time pass is not enough.
- Two reference regimes must be kept distinct: the surrogate for the unsupervised stack, human gold for the weighted layer.
- A surrogate that is not truly diplomatic to its edition would silently mislead; mitigated by a facsimile spot-check before adoption.
- Per-stratum certification at a 0.1% bar needs thousands of accepted corrections per stratum; a single surrogate volume may not supply that power for thin classes, which then stay flagged rather than auto-accepted.
- A bounded human-adjudicated Schaff-Herzog transfer sample is now a required input before unflagged release — less than a full gold set, but not zero human gold.

## Alternatives considered

- **Gold-first (the status-quo embargo on all correction).** Rejected: leaves roughly half the gold-free gain unrealised and makes human time the bottleneck before the easy wins are taken.
- **Surrogate as a production input.** Rejected: it is a different text; it validates the machinery and never feeds canonical output, and a runtime reference dependence is banned.
- **Silver re-OCR engine as the reference.** Rejected: measures agreement, not truth, unless its disagreements are themselves adjudicated — which collapses back to human gold.
