# Adversarial Review — Codex gold-free corrector design

Reviewer: independent architect (did not author the design under review). Reviewed
against `docs/DESIGN_BRIEF_gold_free_corrector.md` (binding) and the real code on disk.

## 1. Overall verdict

**Buildable with the must-fixes.** The design is well-grounded in the real code, cites
every symbol correctly, and satisfies all eight hard requirements at the design level.
But it has two concrete defects that break it as written — a schema-invalid S3 integration
(`match_explanations.signals` cannot hold a proposal) and a flagship example whose own data
proves the within-slot voter degenerates to a 1-vs-1 tie with three abstaining engines — plus
several Insufficient gaps (no JSON schema for the artifact, hidden fixed thresholds that sit
uneasily beside the "surrogate sets the threshold" doctrine, and an unspecified surrogate
text-to-position alignment that the whole HR6 measurement rests on).

## 2. Hard requirements In/Out

| HR | Verdict | In/Out | Evidence |
|---|---|---|---|
| HR1 build on WCT alignment | Accept (minor imprecision) | **In** | Cites `_sub_cost`, `_weighted_edit`, `confusion_distance`, `_load_multichar_confusions` — all exist. Reuse is real (the cost primitives are importable). Imprecision: per-character column voting needs `_sub_cost`/`_CONFUSION` (char-level), not `confusion_distance` (string-level, `_weighted_edit/max(len)`); the design names the string-level function for a char-level job. See issue I-3. |
| HR2 L0-L3 all built, publication = measured threshold | Reject (as written) | **Out** | L0-L3 are all built (P4 table, `test_p4_levels_0_to_3_all_constructed`). But the design hardcodes `min_l0_agreement_score=0.80`, `min_l1=0.70`, `min_l2_lexicality_score=0.95` as gating thresholds *in addition to* the surrogate gate. These are exactly the "fixed doctrine" HR2 forbids. The doc never says whether a tier passes when surrogate says yes but the position scores below the fixed floor — the two gates can disagree. See issue I-2. |
| HR3 per-character provenance | Accept | **In** | Artifact carries `provenance[]` per char with `source`, `attesting_engines/families`, `candidate_ids`; provenance rules cover `engine_attestation`, `rejected_glyph`, `gap`. Covers rejected/filtered glyphs and gaps explicitly. |
| HR4 real-word-error first-class, distinct from CER | Accept | **In** | `real_word_error` and `non_word_error` defined with exact predicates; surrogate harness reports `real_word_error_rate` separate from `cer`; `test_surrogate_reports_real_word_separate_from_cer`. Matches the research synthesis Kukich/Levchenko framing. |
| HR5 protected classes route before scores | Accept | **In** | P4 step 1 detects protected classes "before deciding" and forces `route_human_or_vlm` regardless of agreement; all six classes listed; four dedicated tests. |
| HR6 surrogate per-level/region ~0.1% | Insufficient | **Partial / leaning Out** | Per-level/per-protected-class metrics and the 0.1% bar are specified, matching ADR-0015. But the surrogate→WCT-position alignment (how diplomatic JE text maps onto WCT `position_id`s so false-correction can be scored) is named as an input and never designed. Without it HR6 is not buildable. The `policy_snapshot.json` ↔ `measure_gold_free_corrector.py` ↔ P4 contract is asserted but never given a field list. See issue I-4. |
| HR7 gold-free | Accept | **In** | Lexicon seeded from consensus WCT + public dictionaries; LM trained on in-corpus consensus; no human-adjudication file read; `test_p2_lexicon_built_without_human_gold`. The consensus-selection criterion (`>=2 independent families, non-protected, Latin body, no impossible glyph`) is gold-free and not circular with the corrector's own output (it reads raw WCT candidate attestation, not corrector proposals). |
| HR8 LLM/VLM canonical text only via tagged L3 | Accept | **In** | P3 "LM must not emit arbitrary free text"; LLM/VLM rules section restricts to rank/flag/verify; any authored text is L3 with `source: lm_context_proposal`/`vlm_image_proposal` + provenance + surrogate gate; `test_llm_vlm_cannot_silent_author_text`. |

Net: 5 In, 1 Insufficient (HR6), 2 Reject-as-written (HR2 hidden doctrine, plus the HR-adjacent
S3 integration that is schema-invalid — counted under issues, not an HR row).

## 3. Code-citation verification (symbol by symbol)

All citations checked by importing the modules and reading the source.

| Citation in design | Status | Evidence (file:line) |
|---|---|---|
| `wct_builder._sub_cost()` | FOUND, correct | `wct_builder.py:171` — char-pair substitution cost from `_CONFUSION`. |
| `wct_builder._weighted_edit()` | FOUND, correct | `wct_builder.py:177` — confusion-weighted Levenshtein over strings. |
| `wct_builder.confusion_distance()` | FOUND, correct (but see I-3) | `wct_builder.py:202` — normalized **string**-level distance, not char-level. |
| `wct_builder._load_multichar_confusions()` | FOUND, **partially misdescribed** | `wct_builder.py:91` loads only `("en","la")`. Design line 16 claims the model "already includes English, German, French, Greek, Hebrew, and Latin confusions." The YAML files for all six exist, but only en+la are loaded into `_MULTICHAR_CONFUSIONS`; de/fr/grc/hbo are never consumed by the live distance function. See I-3. |
| `wct_builder._candidate_sets()` | FOUND, correct | `wct_builder.py:896` — groups by `candidate_key` → `candidate_id`, `raw_reading`, `candidate_key`, `normalisation_applied`, `attesting_engines`. |
| `wct_builder._emit_position()` | FOUND, correct | `wct_builder.py:1108` — emits `position_id`, `zone`, `script`, `candidate_set`, `span_records`, `available_engines`, `comparable_engines`, `alignment_confidence`. |
| `wct_builder._attesting_span_record()` | FOUND, correct | `wct_builder.py:1184` — per-engine `raw_text`, `normalized_text`, `family`, `source_spans`, confidence, `candidate_id`. |
| `s3_reconciler._best_candidate()` | FOUND, correct | `s3_reconciler.py:163` — `max` by (families, engines, `candidate_id`). |
| `s3_reconciler.reconcile_degraded()` | FOUND, correct | `s3_reconciler.py:189`. |
| WCT fields `candidate_set/candidate_id/raw_reading/candidate_key/normalisation_applied/attesting_engines/attesting_families` | All present | Verified on `page_0010.json` position 0 candidate_set. `attesting_families` is added in `_emit_position` at `:1152`. |
| WCT fields `span_records, alignment_confidence, available_engines, comparable_engines` | All present | Verified on real position 0 (`alignment_confidence: 0.7`, 5 span_records). |
| `SAME_SLOT_THRESHOLD` | FOUND = 0.5 | `wct_builder.py:65`; matches design `max_internal_distance=0.50`. |
| Abelard / `▲belavd` example | PRESENT, but see I-1 | Real `body:c1:l000:p000`: `cand_001 Abelard` (tesseract only) vs `cand_002 ▲belavd` (abbyy only); surya+kraken+kraken-greek all **skip**; reconciled chose `▲belavd`. |

Symbol citations are accurate — this design was written against the real code, not a hallucinated
version. The only citation defect is the en/la-only loading scope (I-3).

## 4. Issues (verdict + failure chain)

### I-1. The flagship example degenerates the within-slot voter — Reject (as the worked example), Accept (as motivation)

The design's headline case is `Abelard` vs `▲belavd`. On the real page that position has **two**
attesting strings (one per family) and **three skips** (surya, kraken, kraken-greek). P1's
"vote per column by family, then engine as tie-break" (design step 3) produces, at column 0,
`A` (tesseract/1 family) vs `▲` (abbyy/1 family) — a 1-1 family tie with no plurality. The voter's
only escape is the impossible-glyph filter (step 4), which rejects `▲` because it is non-alphabetic
in an alphabetic context. So P1 *can* recover `Abelard` here — but **only** because of the glyph
filter, not the vote. The design presents this as a voting win; it is a filter win. **Failure chain:**
take any 1-vs-1 slot where both readings are alphabetic (e.g. a long-s `f`/`s` confusion: `chrift`
vs `christ`) — the vote ties, the glyph filter does not fire, and P1 has no defined tie-break that
isn't `agreement_score` penalization → routes. That is acceptable behavior, but the design must
state that 1-vs-1 alphabetic slots route by construction, because on this corpus only **74 of 1142**
positions (6.5%) have >1 attesting family at all... wait — inverted: **1068 of 1142 have >1 family**,
74 have ≤1. So most positions DO have multi-family attestation; but the *disputed* ones the corrector
exists to resolve are exactly the low-agreement 1-vs-1 cases the example shows. The example proves the
voter cannot decide its own motivating case without the filter. Fix: add a worked multi-engine slot
(3+ families agree on most columns, one dissents) as the L1 example, and state the 1-vs-1 routing rule.

### I-2. Hidden fixed-threshold doctrine conflicts with HR2 — Reject (as written)

P4 lists `min_l0_agreement_score=0.80`, `min_l1_agreement_score=0.70`, `min_l2_lexicality_score=0.95`
as parameters, and the auto-publication conditions in the L0-L3 table require BOTH the surrogate
threshold AND (implicitly) these floors. HR2 is explicit: "Publication policy is a threshold on
surrogate-measured error per method, NOT a fixed doctrine." **Failure chain:** suppose the surrogate
measures L1 false-correction at 0.0005 (passes the 0.1% bar) for slots scoring `agreement_score=0.72`.
The surrogate says publish; `min_l1_agreement_score=0.70` also says publish — fine. Now a slot scores
0.68 with the same measured tier error: surrogate says publish, the fixed floor says route. Which wins?
The design never says. If the floors are hard gates they ARE the fixed doctrine HR2 bans; if they are
only initial review-priority features they should not appear as P4 publication thresholds. Fix: state
that the fixed floors are *priors overridden by the surrogate snapshot once it exists*, or remove them
from the publication path and keep them only in P5 ranking.

### I-3. "Reuse WCT confusion costs" is real but the description is imprecise and overstates language coverage — Insufficient

Two sub-defects. (a) Char-level vs string-level: the design says P1 aligns characters "with the
existing WCT confusion costs" and names `confusion_distance()`. `confusion_distance` is string-level
(`_weighted_edit(a,b)/max(len(a),len(b))`); the correct char-column primitive is `_sub_cost(a_char,
b_char)` reading `_CONFUSION`. The design must name `_sub_cost`/`_CONFUSION` as the per-column cost,
or it will reuse the wrong granularity. (b) Language coverage: design line 16 claims the model
"already includes English, German, French, Greek, Hebrew, and Latin confusions." `_load_multichar_confusions()`
loads only `("en","la")`; de/fr/grc/hbo YAML exist but are never loaded into the live `_MULTICHAR_CONFUSIONS`.
P2's "confusion expansions from the YAML models" must therefore either load those files itself (new code,
fine) or it inherits the en/la-only scope. State which. **Failure chain:** a German bibliography token
(`Geschichte`) needing a de-specific confusion gets no expansion because the WCT never loaded de.yaml,
and the design implied it had.

### I-4. S3 integration is schema-invalid — Reject

Design line 93: "The reconciler should copy the chosen proposal into `match_explanations.signals`
with non-matrix status." The `reconciled_record` schema `$defs.match_explanation.signals.items` has
`additionalProperties: false` and requires exactly `{name: string, raw_score: number, weight: number,
contribution: number}`. A corrector proposal (a dict with `reading`, `derivation_method`,
`publication_state`, `provenance[]`) **cannot be copied into a signal** — it would fail schema
validation, and OCD's convention is schema-validated output. **Failure chain:** S3 builds a signal
`{name:"corrector_proposal", ...the proposal dict...}` → `validate.py` rejects the record →
`reconcile_degraded` already calls `validate_region_class_stamp` and asserts invariants before
returning, so the page fails closed. Fix: either (a) define a new top-level field on the reconciled
record (schema change, the project's normal path) to carry corrector evidence, or (b) flatten the
proposal into conforming numeric signals (`name:"corrector_agreement_score", raw_score:0.5, weight:0,
contribution:0`) and store the rich proposal in the separate `gold-free-corrector-v1` artifact only.
The design picked the one place it does not fit.

### I-5. `corrector_signals` threaded through `reconcile_degraded` — Accept (with caveat)

Adding `corrector_signals: dict[str,dict] | None = None` is safe and has direct precedent: the
function ALREADY takes `dictionary_signals: dict | None = None` and records it as zero-weight
post-alignment evidence (`s3_reconciler.py:284-296`), never as a matrix label. The design did not cite
this precedent but its proposed shape matches it exactly. Caveat: the design says S3 "uses the policy
result for block text only when the proposal's method tier passes surrogate policy." That changes
degraded-mode `original_text` assembly (currently `" ".join(chosen_readings)` from `_best_candidate`,
`:355`). Writing a corrector-chosen reading into `original_text` while the embargo holds all matrix
weights at 0.0 risks blurring the degraded contract: degraded mode must still emit zero-weight signals
and route everything (`_assert_no_premature_matrix_labels`). The corrector text must go to a NEW field
(e.g. `corrector_text`/`canonical_candidate`), not overwrite `original_text`, or degraded-mode behavior
silently changes. State this boundary.

### I-6. No JSON schema for the `gold-free-corrector-v1` artifact — Insufficient

The artifact is specified as a JSON example only. Every other inter-stage contract in this repo has a
schema in `schemas/v1/` (rendering-v1, word-confusion-table-v1, matrix-events-v1, reconciled_record,
gold-record-v1, etc.). The design's own test inventory opens with
`test_p1_...` against fixtures but item 1 of the implementation sequence is "Add artifact schema tests
for `gold-free-corrector-v1`" — yet no schema file is named, and `schemas/v1/` has none. **Failure
chain:** P1/P2/P3 each write into `proposals[]` with different optional keys; with no schema, drift
between producers and the surrogate harness consumer is silent (PIPE-18/PIPE-21 class). Fix: add
`schemas/v1/gold-free-corrector-v1.schema.json` before any producer code, per project convention.

### I-7. Matrix-gate guard respected? — Accept

The design says signals carry "non-matrix status" and "must not emit trained matrix labels."
`s3_reconciler` enforces this at `_assert_no_premature_matrix_labels` (only rejects `labels_emitted`
*matrix-event* outcomes), and `match_explanations` signals are unconstrained by that guard. So copying
corrector signals into `match_explanations` does not trip the matrix gate. The gate is on
`matrix_event_candidates`, which the corrector does not touch. The design's claim is correct — the only
problem with the `match_explanations` route is schema shape (I-4), not the matrix gate.

### I-8. Active-learning queue reorder vs surrogate ordering — Accept

P5 "Replace the current queue ordering only after the corrector artifact exists" and "Keep S3 queue
fields intact and add `review_features`" is consistent with the real `reviewer_queue` dict shape
(`position_id, reason, region_class, candidates, chosen_reading` at `:322-331`). `test_p5_review_features_added_without_removing_s3_fields` pins it. Sound.

## 5. Prioritized fix list

**MUST-FIX (design is not buildable without these):**
1. I-4 — redesign the S3 carrier: corrector evidence cannot live in `match_explanations.signals`
   (schema `additionalProperties:false`). Add a schema-backed field or keep rich data in the
   corrector artifact only.
2. I-6 — author `schemas/v1/gold-free-corrector-v1.schema.json` before any producer; the artifact is
   a real inter-stage contract and the repo validates all of them.
3. I-2 — resolve the fixed-threshold vs surrogate-threshold conflict (HR2). State that the floors are
   surrogate-overridable priors, or move them out of the publication gate.
4. I-4/HR6 — design the surrogate-text → WCT-position alignment. The entire 0.1% measurement depends
   on it and it is currently only named as an input.

**SHOULD-FIX:**
5. I-1 — replace the worked example with a genuine multi-family voting slot, and state the 1-vs-1
   alphabetic routing rule explicitly.
6. I-3 — name `_sub_cost`/`_CONFUSION` as the per-column primitive; correct the "all six languages
   loaded" claim and say where P2 loads de/fr/grc/hbo.
7. I-5 — pin the degraded-mode boundary: corrector text goes to a new field, never overwrites
   `original_text`; cite `dictionary_signals` as the precedent for the new param.

**NICE-TO-HAVE:**
8. Specify the `policy_snapshot.json` field list (sample size, CI, date, corpus slice, code version
   are named in prose — make it a schema or a typed dict).
9. The two-Kraken-lanes risk the design raises is already handled: both `kraken-py312-v1` and
   `kraken-greek-py312-v1` map to `family:"kraken"` via `_FAMILY_MAP`, so the WCT already counts them
   as one family. The design's "vote model must not count them as independent" is satisfied upstream;
   note that P1 voting by `family` (not `engine_id`) inherits this for free.

## 6. Buildable?

**Buildable with the must-fixes.** The architecture is correct, gold-free, and faithful to the real
code — no rethink needed. But it is not buildable exactly as written: the S3 carrier is schema-invalid
(I-4), the artifact has no schema (I-6), the HR2 publication gate is internally contradictory (I-2),
and the HR6 surrogate alignment — the measurement the whole publication policy hangs on — is
unspecified (I-4/HR6). Fix those four and the remaining items are tightening, not redesign.
