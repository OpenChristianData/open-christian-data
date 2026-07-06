# Build spec — gold-free corrector code obligations

Source: the 2026-06-05 adversarial review of ADR-0014 (composed readings) and
ADR-0015 (surrogate as validator) — `docs/adr/REVIEW_0014_0015_adversarial.md`.
The ADRs were revised in place to carry the *decisions*. This file carries the
*code half* — the implementation each decision now obligates. Hand to the
parallel corrector-architecture session.

All eight review findings except F3 have both a decision half (in the ADRs) and a
code half (here). F3 is code-only.

## Anchors

- Candidate-only emitter: `build/lib/wct_builder.py` (emits all candidates + span
  evidence; "no truth choice, no LM/context scoring").
- Whole-candidate picker: `build/lib/s3_reconciler.py` — `_best_candidate` (~L163)
  picks the most-attested whole candidate; region-class assignment (~L105–135)
  detects Greek/Hebrew script and Latin/German-high-conf only.
- Canonical schema: `schemas/v1/commentary.schema.json` — `source_raw_origin` is a
  three-value enum (`observed | unavailable | reconstructed`, ~L555).
- WCT schema: `schemas/v1/word-confusion-table-v1.schema.json` — candidate =
  whole `raw_reading` with attesting engines/families; span records carry source
  spans but no per-character source array.
- Requirements: `docs/DESIGN_BRIEF_gold_free_corrector.md` (HR1–HR8).
- Regenerate `build/lib/_generated_enums.py` after any `schemas/v1/` change
  (AGENTS.md rule); drift check `py -3 build/tools/check_schema_enums_fresh.py`.

## Build order

`1 → 2 → (3, 4) → (5, 6) → 7`; item 8 can land alongside 1. Items 5–7 cannot be
certified until the Jewish Encyclopedia surrogate volume produces data, so 7's
publish path stays flagged-only until then.

### 1. Schema fields (F2) — do first; everything depends on it

Add to canonical/reconciled position records:

- `canonical_derivation_level` — enum `L0 | L1 | L2 | L3`.
- `canonical_origin_kind` — enum `observed | machine_composed | human_amended`.
  Today `source_raw_origin` cannot tell a machine-composed token from a
  human-amended one; this discriminator is required.
- `character_provenance[]` — one entry per grapheme; source type in
  `{engine_family, confusion_rule, lexicon, language_model, human}`.

Semantic validator checks: provenance-array length == grapheme count; grapheme
boundary correctness; each source type in the enum; route eligibility per level.

**Falsifiable gate test** (replaces "zero unattested tokens"): fails if any
released token with `derivation_level >= L1` has missing or malformed
`character_provenance`. This is the new ship-blocking invariant.

### 2. Composed-reading emitter (F3) — the missing middle layer

New layer between `wct_builder` (candidates only) and `s3_reconciler` (whole
`_best_candidate`). Votes at character-column granularity inside a slot; emits a
composed reading + per-character provenance + derivation level.

Failing-first tests:
- L1 emits a composed token with complete per-character provenance.
- L2/L3 emit route-to-review unless their class threshold is certified.
- The publish gate rejects any canonical token with missing/malformed provenance.

### 3. Protected-class detectors (F4)

Token-level detectors for **proper names, numbers, dates, Scripture references**.
Greek/Hebrew already route by script in `s3_reconciler`; these four classes are
not detected anywhere yet.

- Per-protected-class counters in the surrogate validation report.
- Gate: ban unflagged L2/L3 for any class whose detector is missing, unmeasured,
  or below threshold.

### 4. Stratified measurement + statistical acceptance (F5 + F6)

- False-correction thresholds keyed by `(level, method, token_class, script,
  typography_tier, source_engine_family_mix)`, each with a minimum support count.
- Statistical rule in the validator: compute an upper confidence bound on the
  false-correction rate per stratum. **"Zero observed errors" only clears if the
  denominator >= required N** — `ceil(log(0.05)/log(0.999)) = 2995` accepted
  corrections for a 95% upper bound below 0.1% (verified). Under-powered or
  above-threshold strata route to flagged/review; never silent auto-accept.

### 5. Surrogate transfer gate (F7)

- Acquire + human-adjudicate a small Schaff-Herzog transfer-check sample.
- Gate: unflagged release of a token class is blocked until the SH sample confirms
  the JE-surrogate-certified mechanism transfers (different typography, name
  density, Scripture-reference density, script mix).

### 6. Composed-token supersession contract (F8)

Parallel to ADR-0011's immutable-rendering model. Each machine-composed token
carries `decision_event_id`, `derivation_policy_version`, `validation_report_id`,
and `supersedes` / `superseded_by`. A published composed token that later changes
triggers a release note.

### 7. Publish gate (F1) — consumes 1–6

- Only L0 + human-reviewed publish unflagged; L1–L3 publish **flagged** until
  their per-class stratified threshold is certified.
- Released record exposes whole-token status beside character provenance.
- Public label for L1–L3 is `machine_composed`, never "attested" — a composed word
  can be character-traceable yet never witnessed whole by any source.
