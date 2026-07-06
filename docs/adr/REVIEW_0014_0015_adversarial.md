# ADR-0014 / ADR-0015 adversarial review

## Verdicts

ADR-0014: Reject in current form. It swaps a word-level attestation gate for a character-provenance gate before the schema, validator, and recall path exist.

ADR-0015: Insufficient-evidence. A surrogate validator is a sound direction, but the ADR does not prove that one surrogate can set a corpus-wide 0.1% auto-accept bar for Schaff-Herzog.

## Findings

### F1. ADR-0014 creates a provenance illusion

Attack: In

Severity: Blocker

Failure chain:

1. The old rule is easy to falsify: every released word must be `consensus`, `llm_resolved`, or `maintainer_reviewed`.
2. ADR-0014 replaces that with "zero tokens lacking character provenance".
3. L2 and L3 allow characters not attested by any engine: confusion+lexicon correction and LM/context proposal.
4. A token can now be assembled from individually labelled character sources while no source ever witnessed the word.
5. The public output can look audited while the scholarly claim has changed from "this word was witnessed or reviewed" to "this word was assembled by rules".

Evidence:

- `plans/2026-05-26-precleaning-architecture-comparison.md:31` says every shipped word must be `consensus | llm_resolved | maintainer_reviewed`.
- `docs/adr/0014-composed-readings.md:15-22` allows machine-composed readings with character provenance and L1-L3 derivation levels.
- `docs/adr/0014-composed-readings.md:34` changes the falsifiable gate to "zero tokens lacking character provenance".
- `docs/DESIGN_BRIEF_gold_free_corrector.md:34-40` requires L0-L3 and per-character provenance, but the brief asserts auditability rather than proving equivalence to whole-word attestation.

Proposed amendment:

Supersede or amend ADR-0014 with a narrower decision: L1 character-voted readings may be generated and stored, but only L0 and human-reviewed readings may publish unflagged until a new ADR defines a stronger public claim for L1-L3. Rename the public field away from "attested" for L1-L3, for example `machine_composed`, and require the released record to expose whole-token status beside character provenance.

### F2. The current schema does not carry the new invariant

Attack: In

Severity: Blocker

Failure chain:

1. ADR-0014 says it can reuse `reconstructed`.
2. The existing `source_raw_origin` enum only says `observed`, `unavailable`, or `reconstructed`.
3. That enum does not identify machine-composed versus human-amended text.
4. The WCT schema records candidates, attesting engines, attesting families, and source spans, but not character-level derivation.
5. Since WCT and reconciled output reject undeclared properties at key nodes, character provenance is not a trivial payload addition. It is a schema change.
6. A validator cannot falsify "zero tokens lacking character provenance" if the canonical schema has no required per-character provenance field.

Evidence:

- `docs/adr/0014-composed-readings.md:30` says it reuses the existing `reconstructed` schema slot.
- `docs/adr/0014-composed-readings.md:35` concedes that derivation-level and character-provenance fields must be added.
- `schemas/v1/commentary.schema.json:532-562` defines `source_raw_origin` as a three-value enum, with no machine-composed discriminator.
- `schemas/v1/word-confusion-table-v1.schema.json:254-282` defines a candidate as a whole `raw_reading` with attesting engines and families.
- `schemas/v1/word-confusion-table-v1.schema.json:284-323` defines span records with source spans, but no per-character source array.
- `schemas/v1/word-confusion-table-v1.schema.json:425-460` makes position-level `alignment_confidence` slot-membership confidence, not truth, and rejects per-span alignment confidence outside the schema.

Proposed amendment:

ADR-0014 needs a schema-first amendment. Add required fields before accepting the gate change: `canonical_derivation_level`, `canonical_origin_kind`, `character_provenance[]` with one entry per Unicode grapheme or explicitly normalised character, and a semantic validator that checks string length, grapheme boundaries, provenance source type, and route eligibility. If the field changes the canonical-token contract, add a superseding ADR per `docs/adr/README.md:37-39`.

### F3. The implementation still chooses whole candidates, not composed readings

Attack: In

Severity: Serious

Failure chain:

1. ADR-0014 assumes a middle layer that votes inside a slot and emits a composed reading.
2. `wct_builder.py` explicitly stops before truth choice and emits candidates and span evidence only.
3. `s3_reconciler.py` currently picks the most-attested whole candidate.
4. Every dispute still routes to reviewer queue in degraded mode.
5. There is no code path that emits L1/L2/L3 composed canonical text, no derivation tag, and no gate test for character provenance.
6. The ADR can be accepted on paper while the pipeline cannot produce or audit the thing it accepts.

Evidence:

- `build/lib/wct_builder.py:23-34` says WCT does alignment and candidate grouping only, with no truth choice, no LM/context scoring, and correction downstream.
- `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md:175-180` says character-column voting, lexicality rescoring, LM rescoring, and active-learning selection were not built before the 2026-06-05 direction.
- `build/lib/s3_reconciler.py:163-170` picks `_best_candidate` by attesting families, attesting engines, then candidate id.
- `build/lib/s3_reconciler.py:248-331` chooses `chosen["raw_reading"]`, classifies disputes, writes a reviewer queue entry, and records match explanations with total score 0.0.
- `build/lib/s3_reconciler.py:403-405` fail-closes on region-class stamps and no premature matrix labels, not character provenance.

Proposed amendment:

Downgrade ADR-0014 from "Accepted" to "Accepted for design exploration, not publish policy" until failing-first tests exist: L1 emits a composed token with complete per-character provenance, L2/L3 emit route-to-review unless their class threshold is certified, and the publish gate rejects any canonical token with missing or malformed provenance.

### F4. Protected-class routing is stated but not operational

Attack: In

Severity: Serious

Failure chain:

1. ADR-0014 relies on protected classes routing to human review.
2. The design brief names proper names, numbers, dates, Scripture references, Greek, and Hebrew as protected classes.
3. Current code has explicit routing for Greek and Hebrew script labels, and pending review for unknown region classes.
4. It does not identify proper names, numbers, dates, or Scripture references at token level in the shown WCT/reconciler path.
5. L2/L3 can therefore be measured and thresholded on a pool that undercounts the hardest real-word-error classes.
6. The surrogate's aggregate pass rate can clear while high-risk token classes remain unsafe.

Evidence:

- `docs/adr/0014-composed-readings.md:31` says protected classes route to human review regardless of level.
- `docs/DESIGN_BRIEF_gold_free_corrector.md:41-50` makes real-word-error rate first-class and routes protected classes away from unflagged publication.
- `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md:184-190` says lexical filtering concentrates real-word-error danger and that protected classes are the reservoir.
- `build/lib/s3_reconciler.py:105-135` assigns region class from Greek/Hebrew script, Latin/German high-confidence override, block hint, or zone type.
- `build/lib/s3_reconciler.py:260-331` routes positions on pending region class or candidate dispute, not on proper-name, number, date, or Scripture-reference detection.

Proposed amendment:

ADR-0014 must define protected-class detectors and make them part of the gate, not a prose consequence. Require per-protected-class counters in the surrogate report and ban unflagged L2/L3 for any class whose detector is missing, unmeasured, or below threshold.

### F5. Per-level aggregate measurement is the wrong granularity

Attack: In

Severity: Blocker

Failure chain:

1. ADR-0014 and ADR-0015 both use per-level false-correction thresholds.
2. Real-word errors are not evenly distributed across levels or token classes.
3. Lexicality and LM scoring are weakest on valid-but-wrong words, especially names, dates, references, and mixed scripts.
4. A per-level aggregate can pass because common low-risk words dominate the denominator.
5. The published corpus can still contain concentrated scholarly errors in the classes users care about most.

Evidence:

- `docs/adr/0014-composed-readings.md:22` sets publication policy by surrogate-measured false-correction rate per level.
- `docs/adr/0015-surrogate-as-validator.md:13` measures per-method and per-level false-correction, coverage, and real-word-error rate.
- `docs/DESIGN_BRIEF_gold_free_corrector.md:41-50` defines real-word-error rate and says tiers above threshold are flagged or routed.
- `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md:186-190` says the last fraction of a percent is the dangerous class and that protected classes are the reservoir.
- `docs/adr/0013-reconcile-scoring-and-n2-tie-breaker.md:136-142` uses calibration gates and cross-type fixtures when distributions may differ; ADR-0014/0015 do not specify an equivalent stratified gate.

Proposed amendment:

Amend ADR-0014 and ADR-0015 together: auto-accept requires thresholds by `(level, method, token_class, script, typography_tier, source_engine_family_mix)`, with a minimum support count and confidence interval for each stratum. Missing strata route to flagged output or review. A new ADR should record this because it changes the publication decision, not just an implementation detail.

### F6. The 0.1% surrogate bar is likely not measurable per class

Attack: In

Severity: Blocker

Failure chain:

1. ADR-0015 targets roughly 0.1% false-correction.
2. At that rate, one observed false correction in 1,000 accepted corrections already equals 0.1%.
3. With zero observed errors, a 95% upper bound below 0.1% needs about 2,995 accepted corrections in the same measured class.
4. ADR-0015 needs this per method, per level, and, if F5 is accepted, per protected class or region class.
5. A single surrogate volume or thin class slice may not supply enough accepted examples to certify the threshold.
6. The pipeline can end up treating "no observed errors" as "safe" when the sample is too small.

Evidence:

- `docs/adr/0015-surrogate-as-validator.md:13` sets the auto-accept threshold near 0.1%.
- `docs/DESIGN_BRIEF_gold_free_corrector.md:47-50` repeats the same threshold and says above-threshold tiers are flagged or routed.
- Programmatic check in this review: `ceil(log(0.05) / log(0.999)) = 2995`, so zero errors need about 2,995 observations for a 95% upper bound below 0.1%.
- `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md:42-44` says multi-column encyclopedia layout ground truth does not exist and a Schaff-Herzog-specific gold sample is unavoidable.

Proposed amendment:

ADR-0015 must define a statistical acceptance rule: minimum denominator, confidence interval, and fallback route when a stratum lacks power. Do not allow "zero observed false corrections" to clear any auto-accept threshold unless the denominator is large enough for the chosen confidence bound.

### F7. One surrogate does not prove transfer to Schaff-Herzog

Attack: In

Severity: Serious

Failure chain:

1. ADR-0015 chooses Jewish Encyclopedia as a non-circular validator because it has same-edition facsimiles and transcription.
2. Same-edition reference quality solves circularity, not transfer.
3. Schaff-Herzog has its own typography, name density, article conventions, Scripture-reference density, Greek/Hebrew mix, and OCR engine error profile.
4. A method can pass on the surrogate and fail on Schaff-Herzog classes that the surrogate underrepresents.
5. The ADR bans runtime reference dependence, so once transferred there is no per-text reference to catch the drift.

Evidence:

- `docs/adr/0015-surrogate-as-validator.md:9` argues the Jewish Encyclopedia is non-circular and same-edition.
- `docs/adr/0015-surrogate-as-validator.md:15` bans a per-text reference at runtime.
- `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md:15-26` says engine behaviour differs across scripts and confidence-weighted voting needs calibration.
- `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md:42-44` says a Schaff-Herzog-specific gold sample is unavoidable.
- `plans/2026-05-26-precleaning-architecture-comparison.md:33` says Schaff-Herzog bibliographies contain Latin, German, Hebrew, and Greek transliterations, and language ID affects confusion-table choice.

Proposed amendment:

ADR-0015 should say the surrogate can certify the mechanism, not the corpus-wide publish threshold. Require a small Schaff-Herzog human adjudication sample as a transfer check before unflagged publication, even if JE remains the primary non-circular validator. This amends the "not gold as prerequisite" decision: human gold is not required to build the unsupervised stack, but it is required to certify transfer before unflagged release.

### F8. Recall and repair are under-specified for composed canonical text

Attack: Out

Severity: Serious

Failure chain:

1. ADR-0011 has a clean repair model for OCR renderings: new rendering IDs, supersedes links, bytes-change warnings, and preserved old bytes.
2. ADR-0014 introduces composed canonical tokens that may later be found wrong.
3. The wrong object is no longer only an OCR rendering; it is a published canonical decision made by a rule, lexicon, LM, or surrogate threshold.
4. ADR-0014 does not define how to supersede a composed-token decision, notify downstream users, or rebuild slim/public artifacts.
5. If an L2/L3 token ships and is later recalled, the dataset lacks the same clean repair path ADR-0011 gives to OCR bytes.

Evidence:

- `docs/adr/0011-floating-engine-versions.md:31-35` defines runtime capture, immutable renderings, supersession, and changed-bytes warnings.
- `docs/adr/0014-composed-readings.md:22` permits L3 model-authored canonical characters through a tagged path.
- `docs/adr/README.md:37-39` says changed decisions must be superseded by a new ADR, not edited in place.
- `plans/2026-05-27-arch3-output-schema-synthesis.md:1390-1392` treats `published-v1` as the authoritative full-evidence record while destination is open.

Proposed amendment:

Add an ADR-0014 amendment for canonical-token supersession: every machine-composed token needs a decision-event id, derivation policy version, validation-report id, supersedes/superseded_by fields, and a release-note requirement when a published token changes. Without that, L2/L3 should not publish unflagged.

## Could not assess

- I did not assess the Jewish Encyclopedia surrogate corpus itself. The ADR claims same-edition diplomatic text, but the review prompt did not include the surrogate acquisition files or spot-check evidence.
- I did not assess actual L1/L2/L3 output quality because the current code paths inspected here do not emit those levels yet.
- I did not assess whether a future schema branch already exists outside the specified files. In the current `schemas/v1` and generated enum surface inspected, the required character-provenance fields are not present.
