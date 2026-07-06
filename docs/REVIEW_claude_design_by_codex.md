# Review: Claude Gold-Free Corrector Design by Codex

## Decision brief

- Overall verdict: buildable only with must-fixes. The design has the right broad components, but it is not buildable as written.
- Biggest blockers: protected-class routing has no detector, the P4/surrogate threshold contract has incompatible shapes, and provenance has no complete carrier for canonical characters or filtered glyphs.
- Code grounding is mixed. Most named reconciler symbols exist and mean roughly what the design says. The WCT reuse claim overstates what is available: `_align_engines` is token/geometry alignment, not a reusable character MSA.
- ADR-0014 and ADR-0015 are on disk and accepted. The design's dependency on them is valid.
- Family-level voting is the right direction, but the design misstates the real `page_0010` family count: the page has five engines but only four distinct families.

## Method

Evidence tags:

- Verified: checked by reading the file or running a script against the artifact.
- Inspected: checked by code/document inspection, but not executed end-to-end.

Files checked: `docs/DESIGN_gold_free_corrector_claude.md`, `docs/DESIGN_BRIEF_gold_free_corrector.md`, `build/lib/wct_builder.py`, `build/lib/s3_reconciler.py`, `schemas/v1/reconciled_record.schema.json`, `schemas/v1/word-confusion-table-v1.schema.json`, `schemas/v1/matrix-events-v1.schema.json`, `docs/adr/`, `reports/wct/vol_01/page_0010.json`, `reports/reconciled/vol_01/page_0010.json`, and `build/lib/ocr_error_models/*.yaml`.

## Hard requirement calls

| HR | In/Out | Verdict | Evidence |
|---|---:|---|---|
| HR1: build on WCT confusion-weighted alignment | Out | Insufficient | The design uses real WCT costs, but the character MSA is a new algorithm. `_align_engines` is token/geometry alignment, not a character-column API. |
| HR2: L0-L3 all built, publication by measured threshold | Out | Reject | L0-L3 are described, but the policy selects one "highest level" and the threshold/default contract can auto-accept when it claims to route. |
| HR3: per-character provenance, including filtered glyphs | Out | Reject | Winning characters get provenance, but filtered/losing glyph provenance has no schema carrier; reconciled output is block text plus disagreements, not tokenized character records. |
| HR4: real-word-error first-class and distinct from CER | In | Accept with one fix | `classify_error()` matches the brief's definition and the harness reports a separate metric. P4 still needs an explicit real-word-error bound if it is meant to gate decisions. |
| HR5: protected classes route before scores | Out | Reject | P4 has an override, but no component produces `protected_class` for proper names, numbers, dates, or Scripture refs. `Abelard` in `page_0010` has no such field. |
| HR6: surrogate validation, per-level/per-region, 0.1% bar | Out | Reject | The surrogate idea is sound, but P4/config/surrogate key shapes disagree and the all-zero default is not a safe embargo. |
| HR7: gold-free | In | Insufficient | The lexicon plan is gold-free. The LM training set must explicitly exclude L1-L3 corrector output, not just say "already-processed pages." |
| HR8: LLM/VLM canonical text only through tagged L3 | In | Insufficient | The L3 rule is stated, but the missing provenance carrier means the guarantee is not enforceable in reconciled output yet. |

## Code citation audit

Verdict: mostly real symbols, but several claims are off or over-read.

Verified hits:

- `build/lib/wct_builder.py:65`: `SAME_SLOT_THRESHOLD = 0.5`.
- `build/lib/wct_builder.py:66`: `GAP_PENALTY = 0.6`. The design cites line 67, which is `LINE_BAND_PX`.
- `build/lib/wct_builder.py:171`: `_sub_cost(a, b)` exists.
- `build/lib/wct_builder.py:202`: `confusion_distance(a, b)` exists.
- `build/lib/wct_builder.py:757`: `_align_engines(...)` exists, but it aligns engine token sequences via `_merge_engine`, not characters inside a candidate string.
- `build/lib/s3_reconciler.py:100-101`: `reviewer_queue` and `post_alignment_signals` exist on `ReconcileResult`.
- `build/lib/s3_reconciler.py:104`: `assign_region_class(...)` exists.
- `build/lib/s3_reconciler.py:138`: `validate_region_class_stamp(...)` exists.
- `build/lib/s3_reconciler.py:163`: `_best_candidate(...)` exists and sorts by distinct `attesting_families` first, then engine count, then `candidate_id`.
- `build/lib/s3_reconciler.py:189`: `reconcile_degraded(...)` exists.
- `build/lib/s3_reconciler.py:254`: `reconcile_degraded` calls `_best_candidate`.
- `build/lib/s3_reconciler.py:286`: dictionary corroboration appends to `post_alignment_signals`.
- `build/lib/s3_reconciler.py:322`: `reviewer_queue.append(...)` exists.
- `build/lib/s3_reconciler.py:425`: `_assert_no_premature_matrix_labels(...)` exists.

Wrong or misleading claims:

- Verdict: Reject.
- Failure chain: `docs/DESIGN_gold_free_corrector_claude.md:24` says real `page_0010` ran five families. The WCT page lists five engines but four families: `abbyy`, `kraken`, `surya`, `tesseract`. The two Kraken lanes share family `kraken`.
- HR calls: HR5 Out on this evidence point because family independence is central to protected routing risk; HR1 still depends on distinct family counts.

- Verdict: Reject.
- Failure chain: the design cites `GAP_PENALTY` at `wct_builder.py:67`; the constant is at line 66. Line 67 is `LINE_BAND_PX`.
- HR calls: HR1 Out until citation accuracy is fixed.

- Verdict: Accept.
- Failure chain: `docs/adr/` contains `0014-composed-readings.md` and `0015-surrogate-as-validator.md`; both files say `Status: Accepted (2026-06-05)`, and `docs/adr/README.md` lists both as accepted. The design does not rest on missing or unratified ADR files.
- HR calls: HR2 In for ADR status; HR8 In for ADR status.

## Findings

### 1. HR1: the WCT reuse claim overstates the available code

- Verdict: Insufficient.
- Failure chain: P1 says to "exactly mirror" `wct_builder._align_engines` at character grain and reuse `_sub_cost` plus `GAP_PENALTY`. In the real code, `_align_engines` at `build/lib/wct_builder.py:757` orders geometry-bearing engines first, calls `_merge_engine` at line 729, and `_merge_engine` calls `_nw_align` at line 681 over token keys. `_nw_align` uses `confusion_distance(...)`, not `_sub_cost(...)`, and it handles insertions differently for geometry-bearing and geometry-less engines. A character MSA over candidate strings has no geometry-bearing seed, no `allow_insert` rule, and no public column object to reuse. On `page_0010` `vol_01:page_0010:body:c1:l005:p004`, the candidate set is `fulfil` from four families versus `fulfl` from the same `kraken` family via the Greek lane. P1 can vote this, but it is a new character-column algorithm, not a direct reuse of `_align_engines`.
- HR calls: HR1 Out. HR2 In on level intent. HR3 Insufficient because the alignment output shape is not specified enough to audit every character.
- Fix: specify a new `align_candidate_characters(...)` function that reuses `confusion_distance` or exports the weighted edit backtrace. Do not claim `_align_engines` is the reusable unit.

### 2. HR1/P2: `_sub_cost` alone drops multi-character confusion behavior

- Verdict: Reject.
- Failure chain: P1 says the substitution cost is `_sub_cost(a, b)`. P2 then relies on OCR model confusions such as `rn -> m`, `cl -> d`, and long-s cases from `build/lib/ocr_error_models/en.yaml` and `la.yaml`. In real `wct_builder.py`, `_sub_cost` at line 171 handles only single-character substitutions through `_CONFUSION`; multi-character confusions are applied inside `_weighted_edit` at lines 192-197 through `_MULTICHAR_CONFUSIONS`. A P1/P2 implementation that imports only `substitution_cost(a, b)` cannot explain or score `rnodern -> modern` with the same cost path the WCT uses.
- HR calls: HR1 Out. HR2 Out for L2 as written because the small-distance fix can diverge from WCT distance semantics.
- Fix: expose a public weighted edit operation with backtrace and multi-character confusion support, or explicitly keep P2's edit generator separate and stop saying it reuses the WCT substitution machinery.

### 3. HR5: protected-class routing has no producer

- Verdict: Reject.
- Failure chain: `CorrectedPosition` has `protected_class`, and P4 routes when it is non-null. No P1-P5 component defines how to set it for proper names, numbers, dates, or Scripture references. The real WCT position `vol_01:page_0010:body:c1:l000:p000` has candidates `Abelard` and `▲belavd`, script routing `normal-latin`, and zone type `body`; it has no `protected_class` field. Without an explicit detector before P4, `Abelard` reaches score evaluation instead of mandatory human routing. Greek/Hebrew have a partial route through `script.text_level.label`, but `page_0010` has only `latin` and `unknown` text labels, so the design does not prove the full protected-class path on the fixture.
- HR calls: HR5 Out. HR4 Out in consequence because the main real-word-error reservoir is not guaranteed to route. HR6 Out because protected classes could enter threshold evaluation.
- Fix: add a P0 or P4a protected-class classifier with input fields, exact regex/gazetteer/script rules, precedence, and tests for all six protected classes.

### 4. HR6: P4, config, and surrogate output use incompatible key shapes

- Verdict: Reject.
- Failure chain: P4 pseudocode reads `t = thresholds[region_class][level]` and `surrogate_false_correction[level][region_class]`. Section 4 says `config/corrector_thresholds.json` has shape `{region_class: {level: {accept, flag, score_accept}}}`. Section 5 says the surrogate emits `reports/surrogate/corrector_rates.json` keyed `{level: {region_class: {...}}}` and calls that "exactly the table P4 loads as `surrogate_false_correction`." There is no adapter that maps metrics into the threshold table or validates both shapes. A real loader will either key-error or silently compare the wrong cells.
- HR calls: HR6 Out. HR2 Out because publication policy is not a coherent measured threshold.
- Fix: define two distinct schemas: one for measured rates and one for decision thresholds, or make both use the same canonical key order and name the exact loader.

### 5. HR6: the all-zero default does not guarantee "route everything"

- Verdict: Reject.
- Failure chain: Section 2/P4 says default thresholds ship at `accept = 0.0`, so nothing auto-accepts until the surrogate fills the table. The pseudocode auto-accepts when `surrogate_false_correction[level][region_class] <= t.accept` and `score >= t.score_accept`. If the measured or default false-correction value is `0.0` and the score is `1.0`, then `0.0 <= 0.0` passes. That contradicts `test_default_thresholds_route_everything`.
- HR calls: HR6 Out. HR2 Out because the threshold policy is not the policy the design claims.
- Fix: represent unmeasured rates as missing/null and route on missing, or use an explicit `auto_accept_enabled` flag per `(level, region_class)`.

### 6. HR3: filtered glyph provenance has no complete carrier

- Verdict: Reject.
- Failure chain: P1 says impossible filtered characters are recorded against the losing candidate. `CorrectedPosition.readings` only carries `LevelReading.char_provenance` for the level readings, and `CharProvenance` describes the voted character or deletion. There is no field for rejected candidate-character evidence. On `page_0010` `vol_01:page_0010:body:c1:l000:p000`, filtering `▲` from `▲belavd` can produce `Abelard`, but the corrected page schema described in Section 1.2 has no place to retain "ABBYY supplied `▲`; P1 rejected it as impossible in a Latin alphabetic column." The prompt explicitly asks for provenance complete and auditable, including filtered glyphs.
- HR calls: HR3 Out. HR5 Out in consequence because protected proper-name examples depend on the same evidence trail.
- Fix: add a `column_evidence` or `rejected_evidence` structure keyed by candidate, column, family, raw char, normalized char, filter reason, and decision.

### 7. HR3/schema: reconciled output cannot enforce per-character provenance as written

- Verdict: Reject.
- Failure chain: `schemas/v1/reconciled_record.schema.json` stores canonical text as block-level `original_text` string at line 157 and disagreements as an array at lines 169-171. The disagreement object allows extra fields, but it is not a token stream. The design says to add `derivation_method`, `character_provenance`, `synthesized`, and `surrogate_false_correction` "on the disagreement/token level," but there is no canonical token object in this schema. A block can contain accepted composed text in `original_text` while no schema-level invariant ties each character in that string to a `character_provenance` record. The proposed `validate_character_provenance(record)` is necessary, but the design does not define enough IDs/spans to implement it.
- HR calls: HR3 Out. HR8 Insufficient because tagged L3 authorship cannot be enforced. HR2 Out because derivation tags do not attach to every canonical token.
- Fix: define a tokenization/provenance carrier with stable spans into `original_text`, or keep the corrected page as the authoritative canonical-token sidecar and make reconciled output reference it by position IDs.

### 8. Reconciler integration reuses an engine field for family provenance

- Verdict: Reject.
- Failure chain: Current `reconcile_degraded` writes `chosen_reading_attested_by` from `chosen["attesting_engines"]` at `build/lib/s3_reconciler.py:316`. The design says `reconcile_corrected` will store attesting families from character provenance in the same field. The schema only says the items are strings, but current data and code semantics are engine IDs. Reusing the field for family IDs breaks existing consumer assumptions and makes mixed per-character provenance impossible for a composed reading where different characters have different family sets.
- HR calls: HR3 Out. HR1 Out for integration with current reconciler semantics.
- Fix: leave `chosen_reading_attested_by` as engine IDs for whole-candidate readings and add explicit `chosen_reading_attested_families` plus per-character provenance spans.

### 9. HR2: "highest level present" collapses the measured level policy

- Verdict: Insufficient.
- Failure chain: P4 says `level = highest level present for this position # L0 > L1 > L2 > L3`. HR2 requires L0-L3 to be built and publication policy to be a threshold per method. Selecting one level before checking thresholds can discard a safer or better-measured alternative. For example, if L0 is present but below the region/method threshold while L1 is also present and measured safe, the pseudocode gives no path to evaluate L1. If "highest" means L0 first, the synthesized tiers do not participate; if it means L3 first, it over-prefers the most synthetic path.
- HR calls: HR2 Out. HR6 Out because per-level thresholds cannot work if only one level is considered before threshold evaluation.
- Fix: evaluate all present levels in deterministic priority order after applying measured thresholds, and define whether the policy prefers lower derivation, higher confidence, or higher coverage.

### 10. HR7: LM training set is still ambiguous enough to become circular

- Verdict: Insufficient.
- Failure chain: P3 says the LM trains on high-consensus consensus text, then says the training corpus is "the WCT/corrected output of already-processed pages" and bootstraps from L0 consensus only. Those are not the same contract. If a volume is processed sequentially and prior pages' `corrected output` includes L1-L3 decisions, the LM can learn its own corrections and feed them into later L3 proposals. That is circular for HR7 even without human gold.
- HR calls: HR7 Insufficient. HR8 Insufficient for L3 because LM authorship depends on the training set contract.
- Fix: define the training extractor as WCT-only, L0-only, and current-run-output-excluding, with a test that L1-L3 outputs never enter LM counts.

### 11. New `reconcile_corrected` entry point risks a maintenance fork

- Verdict: Insufficient.
- Failure chain: `reconcile_degraded` is one monolithic function from `build/lib/s3_reconciler.py:189` to line 412. It interleaves reading selection, block assembly, region-class stamping, match explanations, matrix candidates, reviewer queue, and validation. The design says a second entry point will "reuse" block assembly and queue machinery but does not specify any extraction boundary. If implemented by copying `reconcile_degraded`, region-class logic and matrix gates will drift between degraded and corrected modes.
- HR calls: HR1 In on intended reuse; HR6 Insufficient because matrix-gate preservation depends on shared code, not intent.
- Fix: keep a second public entry point only if shared internals are extracted first: ordered positions, block assembly, region stamping, matrix candidate creation, and final invariant checks.

### 12. Schema migration is not safe as "additive" without consumer checks

- Verdict: Insufficient.
- Failure chain: The design calls the reconciled schema changes additive. The schema's `disagreement` allows additional properties, so adding optional fields there is technically schema-additive, but the real change is semantic: the gate changes from "zero unattested tokens" to "zero tokens lacking character provenance." That requires changing validators and downstream consumers of `original_text`, `disagreements`, reviewer queue rows, and matrix candidates. The design references `TEST-03` grep but does not name real consumers or required schema validation changes.
- HR calls: HR2 Insufficient. HR3 Out until the validator contract is specified. HR6 Insufficient for matrix-gate safety.
- Fix: list each consumer touched and define a compatibility test for existing degraded output plus new corrected output.

## Accepted points

### HR4: real-word-error classification is correctly separated

- Verdict: Accept.
- Failure chain: Section 5 defines `classify_error(output, gold, lexicon)` as `correct`, `real_word_error`, or `non_word_error`. That matches HR4's definition: output is a valid lexical word and output differs from gold. It is also reported per level and region class in the surrogate metrics.
- HR calls: HR4 In. HR6 In for metric availability, but Out for threshold wiring.
- Required fix: add an explicit real-word-error bound to the P4 threshold schema if the policy is meant to demote on that metric.

### HR5/family-level voting: the architecture call is directionally right

- Verdict: Accept with correction.
- Failure chain: `_best_candidate` at `s3_reconciler.py:163-172` counts distinct families before engines, and the WCT fixture collapses both Kraken lanes into one family. That supports family-level voting over engine-level voting. The design's "five families" statement is wrong, but the architecture call is still right.
- HR calls: HR5 In for family-level weighting principle; HR5 Out for protected-class routing implementation.

### HR8: L3-only authorship is the right rule

- Verdict: Accept with enforcement gap.
- Failure chain: P3 and P4 state that LM/context-proposed characters only emit through L3 with `method="lm"` provenance and surrogate measurement. That satisfies the brief at design-intent level. The enforcement gap is the missing reconciled provenance carrier described above.
- HR calls: HR8 In on rule; HR8 Insufficient on buildability.

## Contested architecture calls

### New package plus new reconciler entry point

Verdict: accept the new package; require shared reconciler internals before adding the second entry point.

Reason: `build/lib/gold_free_corrector/` is a clean boundary because WCT output is a frozen artifact and the corrector is a new layer. A second public `reconcile_corrected` entry point is reasonable only if `reconcile_degraded` is decomposed first. Otherwise it becomes a maintenance fork across region stamping, reviewer queue, and matrix-event invariants.

### Reconciled schema migration

Verdict: not safe as written.

Reason: adding optional fields to `disagreement` is easy, but it does not enforce per-character provenance for block-level `original_text`. The design needs stable token/character spans or a corrected-page sidecar as the authoritative provenance surface.

### Family-level voting

Verdict: accept, after fixing the fixture facts.

Reason: real code already prioritizes distinct families, and the fixture has two Kraken engines in one family. The design should say five engines/four families, not five families.

## Prioritized fixes

### MUST-FIX

1. Define protected-class detection before P4, covering proper names, numbers, dates, Scripture references, Greek, and Hebrew.
2. Make P4 thresholds, surrogate measurements, and config use one coherent key contract.
3. Replace the all-zero default with an explicit route-until-measured state.
4. Define a complete provenance carrier for winning characters, synthesized characters, deletions, and filtered losing glyphs.
5. Fix the WCT reuse claim: expose a real character-alignment/backtrace API or present P1 as a new algorithm that reuses WCT distance functions.
6. Stop reusing `chosen_reading_attested_by` for family provenance.
7. Specify level-selection semantics so L0-L3 are all evaluated by measured thresholds.

### SHOULD-FIX

1. Extract shared reconciler internals before adding `reconcile_corrected`.
2. Add explicit real-word-error bounds to the threshold schema.
3. Lock the LM training extractor to WCT-only L0 inputs and add a test that L1-L3 output never enters training.
4. Replace the "five families" fixture claim with five engines/four families.
5. List actual reconciled-record consumers affected by the schema and validator change.

### NICE-TO-HAVE

1. Add a citation table to the design with exact current line numbers.
2. Add a small worked column-alignment table for `Abelard`/`▲belavd`.
3. Name the threshold schema files for measured rates versus decision policy separately.

## Overall verdict

Buildable with the must-fixes. As written, the design will fail HR1, HR2, HR3, HR5, and HR6 before implementation starts.
