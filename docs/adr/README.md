# Architecture Decision Records

Hard-to-reverse, surprising-without-context, genuine-trade-off decisions for Open Christian Data.

Each ADR captures one decision. Lightweight format: context, decision, consequences, alternatives considered.

## Index

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-linear-block-sequence.md) | Linear block sequence as universal data structure | Accepted; partially superseded by 0019 | 2026-05-15 |
| [0002](0002-within-edition-reconciliation.md) | Within-edition reconciliation only | Accepted | 2026-05-15 |
| [0003](0003-modernise-as-separate-stage.md) | Modernise as a separate pipeline stage | Accepted | 2026-05-15 |
| [0004](0004-single-public-repo.md) | Single public repo over two-repo split | Accepted | 2026-05-15 |
| [0005](0005-huggingface-two-configs.md) | HuggingFace publishes one dataset with two configs | Accepted | 2026-05-15 |
| [0006](0006-scans-local-page-level.md) | Scans stay local; page-level mapping required, bounding boxes opportunistic | Accepted | 2026-05-15 |
| [0007](0007-modernisation-rules-as-data.md) | Modernisation rules as data files | Accepted | 2026-05-15 |
| [0008](0008-built-once-no-v2-lane.md) | Built once; no "designed-for-not-built" lane | Accepted | 2026-05-15 |
| [0009](0009-transliterate-non-latin-scripts.md) | Transliterate non-Latin scripts in both HF configs; original-script bytes preserved per segment | Accepted | 2026-05-15 |
| [0010](0010-biblical-language-iso-codes.md) | Biblical-language ISO codes (`grc`, `hbo`, `arc`) over modern defaults | Accepted | 2026-05-15 |
| [0011](0011-floating-engine-versions.md) | Floating OCR engine versions; record actual version per-rendering | Accepted | 2026-05-15 |
| [0012](0012-reviewer-ui-static-html-vanilla-js.md) | Reviewer UI is static HTML + vanilla JavaScript; no framework | Accepted; superseded by 0020 | 2026-05-15 |
| [0013](0013-reconcile-scoring-and-n2-tie-breaker.md) | Reconcile scoring rubric, thresholds, edge combination, and N=2 tie-breaker | Accepted | 2026-05-16 |
| [0014](0014-composed-readings.md) | Machine-composed readings past the attestation gate | Accepted | 2026-06-05 |
| [0015](0015-surrogate-as-validator.md) | Surrogate as validator, not gold as prerequisite | Accepted | 2026-06-05 |
| [0016](0016-unify-lexicon-rename-ocr-layer.md) | Unify the shared lexicon over the NSH OCR pipeline; rename the OCR-layer vocabulary | Accepted | 2026-06-19 |
| [0017](0017-frontback-matter-into-ocr-pipeline.md) | Front/back matter enters the NSH OCR pipeline, tagged by edition section | Accepted | 2026-06-20 |
| [0018](0018-llm-review-unattested-readings.md) | LLM Review may propose unattested readings via the L3 composed-reading path | Accepted | 2026-06-25 |
| [0019](0019-ir-is-tei.md) | The intermediate representation (IR) is TEI (unconstrained P5; ODD deferred) | Accepted | 2026-07-01 |
| [0020](0020-reopen-reviewer-ui-shell.md) | Withdraw the vanilla-JS mandate; reopen the reviewer-UI shell decision | Accepted | 2026-07-04 |
| [0021](0021-ledger-import-semantics-machine-releases.md) | Ledger import semantics for machine-released corrections (`machine_release` event type) | Accepted | 2026-07-04 |
| [0022](0022-generated-static-tei-reviewer-shell.md) | Generated static shell for the TEI reviewer | Accepted | 2026-07-06 |

## When to add a new ADR

Per the grill-with-docs skill: only when a decision is

1. **Hard to reverse** — undoing it would mean significant rework.
2. **Surprising without context** — a new contributor would not arrive at it by default.
3. **A genuine trade-off** — alternatives were live; the choice was not forced.

Routine implementation choices, settled by hard requirements, or naturally consequent from prior decisions do not earn an ADR.

## When to update an existing ADR

If the decision changes, do not edit the original. Add a new ADR that supersedes it and update the original's status to `Superseded by ADR-NNNN`. The audit trail is the point.
