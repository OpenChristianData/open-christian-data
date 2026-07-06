# ADR-0009: Transliterate non-Latin scripts in both HF configs; original-script bytes preserved per segment

**Status:** Accepted (2026-05-15); amended 2026-05-16 (R14 — `language_segments[].language` enum reduced to the Phase 1 active set per ADR-0010 amended)

## Context

The prior grilling session locked a hard requirement: **never transliterate non-Latin scripts in the dataset**. The rationale was original-script preservation — Greek, Hebrew, Aramaic, Syriac, and Coptic bytes should appear exactly as the source presents them. The pipeline was constrained accordingly: a `transliterated_from` field flagged segments where the *source itself* had transliterated, but the pipeline never produced a transliteration of its own.

Plan walkthrough surfaced a course-correction. The dataset's **primary purpose is LLM consumption** — training corpora, retrieval-augmented generation, model fine-tuning. Modern LLMs handle Latin script fine and handle non-Latin scripts poorly. Keeping non-Latin bytes in the consumer-facing text fields, while making the data unusable for the actual goal, is the wrong trade-off.

The North Star is unchanged: *"Recreate the original text accurately first, with its natural structure."* The reframing is that **transliteration is content-faithful** — the same words rendered in a different script. Recreating the content accurately is satisfied even when the script is normalised. Bytes-level preservation is a per-segment concern, not a primary-text concern.

## Decision

Reverse the prior "never transliterate" requirement. **Transliterate non-Latin scripts in both HF configs**, and **preserve the original-script bytes per segment** so any future consumer can recover them.

Concretely:

- **`original` HF config → `original_text`**: source-faithful spelling, archaic forms, capitalisation, and structure — rendered in **Latin script throughout** (transliteration applied to every non-Latin segment).
- **`modernised` HF config → `modern_text`**: modernised spelling and forms; Latin-script throughout. Transliteration applied identically; English-modernisation rules applied additionally.

The distinction between configs is **spelling and morphology only** — both deliver Latin-script text.

Per-segment fields preserve everything needed to recover non-Latin bytes:

- `language_segments[].original_script` — the non-Latin bytes for the segment, preserved exactly. The recovery path for any future consumer wanting raw script.
- `language_segments[].transliteration` — the Latin-script form used in both `original_text` and `modern_text`.
- `language_segments[].language` — the underlying language. The Phase 1 schema enum is the ADR-0010 Phase 1 active set: `grc`, `hbo`, `la`, `en`, `fr`, `de`. (Latin-script segments — a French quotation in an English block, a Latin phrase like `sola fide` — are valid segment languages too.) `arc`, `syr`, `cop` re-enter the enum under the staged-introduction rule in ADR-0010 amended (2026-05-16) when real corpus input arrives.
- `language_segments[].transliterated_from` — flag for segments where the source itself transliterated.

Transliteration runs as part of the **Transliterate stage**, not Parse and not Modernise. Per ADR-0003 (amended 2026-05-16), Transliterate is a separate mandatory pipeline stage between Reconcile and the first Check. Per-language transliteration rulesets at `build/lib/modernisation/rulesets/transliteration/<lang>.yaml` (SBL-style for Greek and Hebrew, etc.). Rule-driven by default; editorial overrides recorded the same way as other modernisation overrides (ADR-0007's pattern). Transliterate writes Latin-script text into `original_text` for every block; Modernise, when it runs, writes Latin-script `modern_text` (applying English-modernisation rules) into the `modernised` sibling. The first Check validates the post-Transliterate `original` record; the second Check validates the modernised sibling.

## Consequences

**Positive**
- Both HF configs are immediately usable for LLM training and RAG out of the box. No consumer needs to handle non-Latin script.
- The `original` vs `modernised` distinction is clean and consumer-meaningful: "source spelling, archaic forms preserved" vs "modernised spelling." No mixed-script-vs-Latin-script confusion.
- Original-script bytes remain fully recoverable per segment. A future scholarly consumer pulls `language_segments[].original_script`; the bytes are still there.
- North Star is honoured — the *content* of every block is preserved accurately; only the *script* is normalised. Transliteration is content-faithful by construction.
- Per-language transliteration schemes are content (YAML), not code. Adding a new language or refining a scheme is a content edit (ADR-0007's pattern).
- Editorial overrides handle edge cases (transliterations the rule-driven scheme gets wrong) the same way as other modernisation overrides — preserved across ruleset version bumps.

**Negative**
- The `original` config is no longer bytes-faithful — non-Latin spans appear in Latin script in `original_text`. Anyone wanting the raw Greek/Hebrew/Syriac bytes must read `language_segments[].original_script`, not `original_text`. This is the trade-off and it is deliberate.
- Each non-Latin segment now carries two byte representations (`original_script` + `transliteration`) plus metadata. Per-segment record size grows; absolute dataset size remains small since most segments are short.
- A reviewer encountering a transliteration mistake sees it in both configs. The mistake propagates equally; the fix propagates equally. Net wash.
- Reviewer attention now extends to transliteration correctness. Editorial calls on borderline transliterations (which SBL convention to use for an ambiguous Hebrew vowel) are real work.

## Alternatives considered

- **Keep the "never transliterate" hard requirement.** Rejected. Preservation is recovered via `original_script` per segment; the requirement was solving the wrong problem at the wrong level — defending bytes-level fidelity in the primary text field at the cost of making the dataset directly unusable for its primary purpose.
- **Transliterate in `modernised` only; keep `original` source-faithful in bytes.** Rejected (was the first-pass design). Splits consumer mental model unhelpfully — half the dataset is unusable for the primary use case while the other half is fine. The script-preservation concern is fully addressed by per-segment `original_script`; there is no need to also keep non-Latin bytes in the primary text of one config.
- **Instead-of transliteration: replace original script with transliteration at Parse time; discard non-Latin bytes.** Rejected. Loses original-language scholarly use entirely; trades one preservation problem for a worse one. Original-script bytes are cheap to keep; discarding them is irreversible.
- **Block-level `transliteration` field instead of per-segment.** Rejected. Most non-Latin spans in the corpus are single-word or short-phrase inline (a Greek word in an English paragraph); per-segment is the natural shape. Whole-block non-Latin passages are the same per-segment shape with one segment spanning the block.
- **Transliterate at Parse time, not Modernise.** Rejected. Parse is per-rendering and should stay source-faithful in bytes for debugging tools and Reconcile fidelity. Transliteration is editorial and belongs in Modernise with its audit trail, ruleset versioning, and editorial-override mechanism (ADR-0003 + ADR-0007).
- **Reword the North Star to "Recreate the original *content* accurately first, with its natural structure."** Considered. Rejected — the existing North Star is already content-focused; "text" can reasonably be read as content rather than bytes. The plan and CONTEXT.md make the framing explicit without disturbing the North Star wording.

## Supersedes

This ADR reverses the implicit hard requirement (never transliterate) carried forward from the prior grilling session. No prior ADR captured that requirement; this ADR documents the reversal so the audit trail is complete.
