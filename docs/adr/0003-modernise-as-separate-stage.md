# ADR-0003: Transliterate and Modernise as separate pipeline stages

**Status:** Accepted (2026-05-15; amended 2026-05-16 to split Transliterate out of Modernise)

## Context

Most works in OCD's corpus are 200–400 years old and use archaic English: `hath`, `doth`, `saith`, `thou`, long s `ſ`, archaic spelling (`Heav'n`). Modern readers, and especially modern LLMs trained on contemporary text, work much better against modernised prose. Many consumers (training corpora, RAG systems) will overwhelmingly prefer a modernised version.

The hard requirement names two final outputs per work: original-spelling and modernised-spelling sibling records. ADR-0009 adds a third constraint: both HF configs are Latin-script throughout, with original-language bytes preserved per segment in `language_segments[].original_script`.

The architectural question is where each concern runs in the pipeline. Three viable shapes emerged:

1. **Inline with Reconcile.** Each reconciled block gets both `original_text` and `modern_text` filled in during Reconcile.
2. **Single Modernise stage after Reconcile, owning both transliteration and modernisation.** Modernise produces both the Latin-script `original` config and the `modernised` sibling.
3. **Two distinct stages after Reconcile: Transliterate (mandatory) then Modernise (optional).** Transliterate produces Latin-script bytes for every block while preserving per-segment original-language bytes; Modernise produces the `modernised` sibling when a work is to be modernised.

Cross-architect reconciliation surfaced that shape (2) overloaded Modernise: transliteration must always run for any block with non-Latin script, while modernisation is optional per work. Reviewer-clean reconciled originals that need transliteration but no English modernisation had no clean stage to run in. The "Modernise is optional" clause and "Modernise produces Latin-script bytes" clause were in tension.

## Decision

Run Transliterate and Modernise as **two separate pipeline stages** after Reconcile.

The pipeline is:

`Fetch → Parse → Reconcile → Transliterate → Check → Modernise → Check → Publish`

**Transliterate** is mandatory. It runs immediately after Reconcile and immediately before the first Check. It writes Latin-script bytes into `original_text` for every block while preserving the source's original-language bytes exactly in `language_segments[].original_script`. For blocks with no non-Latin script, Transliterate is a no-op; the contract is the same. Per-language transliteration rulesets live at `build/lib/modernisation/rulesets/transliteration/<lang>.yaml` (SBL-style for Greek and Hebrew, etc.) per ADR-0007's rules-as-data pattern. Editorial overrides recorded the same way as other modernisation overrides.

**Modernise** is optional per work. It reads a Reviewer-clean (post-Transliterate, first-Check-clean) record and produces the `modernised` sibling at `data/<type>/<author>/<work>/<edition>/modernised/`. Modernise applies English-modernisation rules (and equivalent rulesets in other languages) to produce `modern_text`. When Modernise is skipped, only the `original` config publishes; Transliterate has already produced the consumer-facing Latin-script text. The original record is unchanged in either case.

**The first Check** validates the post-Transliterate state: schema validation (including the "no non-Latin in consumer text fields" invariant), PD gate, attestation coverage, disagreement classification, language confidence, and source-page coverage. Reviewer adjudicates flagged blocks before Modernise can run.

**The second Check** validates the modernised sibling: ruleset-version presence, paired-record invariants, modernisation-completeness, span consistency between siblings.

**Preservation guarantee.** The author's original-language bytes are preserved exactly in `language_segments[].original_script` for every block that has non-Latin source content. The published `original_text` (Latin script) and the metadata-preserved `original_script` (non-Latin source bytes) together let any future consumer recover the source faithfully. No editorial fabrication of `original_script` from a reference copy is permitted; the field is either the source's own non-Latin bytes or null (with `transliterated_from` set when the source itself was already in Latin script).

## Consequences

**Positive**
- Reconcile, Transliterate, and Modernise have distinct, single concerns. Reconcile establishes what the source says (preserving source bytes); Transliterate normalises script while preserving original-language bytes; Modernise applies editorial transformation.
- The first Check validates a well-defined schema state — post-Transliterate, Latin-script-throughout in `original_text`. No "pre-Modernise vs post-Modernise" schema ambiguity.
- Per-work opt-out of modernisation is clean — works whose value depends on archaic register (some devotionals) skip Modernise; the `original` config still publishes because Transliterate already ran.
- Re-Transliterate (after transliteration-ruleset bumps) does not touch English-modernisation outputs; re-Modernise (after English-ruleset bumps) does not touch transliteration. Independent re-runs, independent audit-log streams.
- Two independent review streams. Reviewer can sign off on transliteration correctness separately from modernisation correctness.
- The modernised record is regeneratable from the post-Transliterate record + ruleset version + editorial-decision list. The post-Transliterate record is regeneratable from the reconciled record + transliteration-ruleset version + editorial-decision list.
- Original-language preservation is structurally enforced: `language_segments[].original_script` is the only field carrying source bytes for non-Latin spans; consumer-facing text fields never carry non-Latin bytes; the boundary cannot be blurred by a Modernise-overload code path.

**Negative**
- The pipeline has eight stages instead of seven. One more stage to wire up, test, and document.
- Transliterate-only re-runs are a new operational pattern. Catalog metadata records the actual transliteration-ruleset version per record (just like Modernise records its ruleset version).
- Editorial-override surface grows. Transliterate overrides and Modernise overrides are recorded in distinct `modernisations`-style entries (with a `kind` discriminator), preserving the audit pattern across both stages.
- "Optional per work" applies to Modernise only — never to Transliterate. A work with non-Latin script where transliteration is not desired would need a new ADR; this ADR does not provide an opt-out.

## Alternatives considered

- **Inline with Reconcile.** Rejected because Reconcile must stay source-byte-faithful for debugging tools, audit fidelity, and the contract that re-Reconcile produces the same canonical original given the same parse inputs. Mixing transliteration into Reconcile blurs that contract.
- **Single Modernise stage owning both transliteration and modernisation.** Rejected during cross-architect reconciliation. Forces the "Modernise optional" and "Modernise produces Latin-script bytes for `original`" clauses into a contradiction whenever a work has non-Latin content but no English-modernisation needs.
- **Transliterate at Parse time.** Rejected per ADR-0009's existing analysis. Parse stays source-byte-faithful per rendering; transliteration is editorial and belongs after Reconcile so it operates on the canonical reconciled text.
- **Modernise as a downstream post-processor on the published dataset.** Rejected because it would push editorial decisions outside the pipeline's audit trail. Modernisations need to live in the change log and audit log the same way Reconcile decisions do.
- **Single record with both `original_text` and `modern_text` on each block, no sibling record.** Rejected because it collapses the two-outputs hard requirement and prevents per-modernised-record metadata (e.g. `modernisation_ruleset_version`) from being recorded distinctly.

## Walkthrough trail

This ADR was originally accepted 2026-05-15 as "Modernise as a separate pipeline stage" with Modernise owning transliteration via ADR-0009. The 2026-05-16 cross-architect reconciliation walkthrough (item R1) surfaced the Modernise-overload tension named above. The split between Transliterate (mandatory) and Modernise (optional) was applied here; ADR-0009's "transliteration runs as part of Modernise" clause was amended in place to "transliteration runs in the Transliterate stage."
