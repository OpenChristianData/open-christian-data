# DESIGN (LOCKED) — Gold-Free Corrector Stack

**Status:** Reconciled from two independent architect designs under the cross-architect pattern
(DEL-02). American English; relative paths.

> **Vocabulary pointer (ADR-0016, 2026-06-25).** This locked design uses code-level names — `WCT` /
> `build_wct_page` → **word alignment table**, `corrected-page` sidecar → **reconciled page**, stages
> `S1` / `render_s2` / `build_wct_page`. The canonical human-facing vocabulary + the ten-stage
> taxonomy live in `SHARED-LEXICON.md` (§"NSH OCR pipeline — Layer 1"); rename map in
> `docs/adr/0016`. Name-layer only — schema ids and filenames are unchanged. LLM Review scope:
> `docs/adr/0018`.

This document reconciles:
- `docs/DESIGN_gold_free_corrector_codex.md` (Codex independent design)
- `docs/DESIGN_gold_free_corrector_claude.md` (Claude independent design)
- `docs/REVIEW_codex_design_by_claude.md` (Claude reviews Codex)
- `docs/REVIEW_claude_design_by_codex.md` (Codex reviews Claude)

against the binding brief `docs/DESIGN_BRIEF_gold_free_corrector.md` (HR1–HR8) and decisions
ADR-0014 (composed readings) and ADR-0015 (surrogate-as-validator), both marked
**Accepted (2026-06-05)** on disk (`docs/adr/`).

> **Update 2026-06-05.** The ADR-0014/0015 adversarial review is RESOLVED — both ADRs were
> revised in place (Accepted; F1–F8 decision-half folded in) and the code-half is in
> `docs/BUILD_SPEC_corrector_code_from_review.md`. Build sequencing has moved on from the
> thin-slice framing below: the decision is to **build everything, modular, test each**, with the
> surrogate gate as a publication policy (per tier, per text), not a build gate. The authoritative
> build order, dependency DAG, and parallelization are in `docs/BUILD_PLAN_gold_free_corrector.md`.
> §9's M1/M2/M3 are answered by measurement (run on JE *and* SH), not by maintainer choice.

---

## Decision brief

- **Verdict: one architecture, buildable with the must-fixes.** Both independent designs reached
  the same shape — a new gold-free corrector layer between the frozen WCT page and the reconciler,
  emitting per-position L0–L3 readings with character provenance, validated (not gated) by the JE
  surrogate. Neither is buildable exactly as written; the union of the two reviews is the build
  contract (§8).
- **The two reviews converged on the load-bearing fixes**, often catching complementary halves of
  the same defect: the "reuse WCT alignment" claim is imprecise in *both* directions (string-level
  vs char-level cost; `_align_engines` is token/geometry alignment, not a character MSA); the
  threshold defaults are unsafe in *both* designs (fixed floors vs an all-zero sentinel that
  auto-accepts); and the provenance carrier / schema contract is underspecified in both.
- **Independence held** — §1 lists 10 substantive disagreements (the DEL-02 bar is ≥3).
- **Build to measure, don't guess (§9).** The open questions — multi-level selection (M1), whether
  fixed agreement floors earn their keep (M2), the protected-class detector source (M3) — are
  *empirical*, not maintainer judgment calls. The surrogate harness measures the alternatives; data
  decides. The build is sequenced so a thin end-to-end slice produces that data early (§9, §12).
- **Provisional on ADR-0014/0015**, which are under adversarial review (see the lock note above).

---

## 1. Independence evidence — substantive disagreements surfaced

| # | Question | Codex design | Claude design | Reconciled position |
|---|---|---|---|---|
| D1 | Reconciler hook | optional `corrector_signals` param on `reconcile_degraded` | new `reconcile_corrected` entry point, leave degraded untouched | **Extract shared internals first**, then a thin second entry point (§5). Both reviews agree a fork is the real risk. |
| D2 | Module shape | single `gold_free_corrector.py` | `gold_free_corrector/` package (5 modules) | **Package** (5 components + P0 + per-module tests; CLAUDE.md test rule). |
| D3 | Corrector artifact | loose JSON, no schema file | formal `corrected-page-v1.schema.json` sidecar | **Schema-backed sidecar** is authoritative; repo validates every inter-stage contract (§4). |
| D4 | Provenance into reconciled record | copy proposal into `match_explanations.signals` | additive fields on `reconciled_record` (`derivation_method`, `character_provenance`, …) | **Neither as written.** `signals` is `additionalProperties:false`; block `original_text` can't carry per-char provenance. Reconciled record **references the sidecar by position ID** (§5.3). |
| D5 | P1 alignment | per-slot Needleman–Wunsch citing `confusion_distance`/`_weighted_edit` | progressive MSA "mirroring `_align_engines`" citing `_sub_cost`/`GAP_PENALTY` | **New char-column algorithm** reusing WCT *distance* primitives (single + multi-char), not `_align_engines` (§3 P1). |
| D6 | Threshold defaults | concrete floors (L0≥0.80, L1≥0.70, L2 lex≥0.95) + surrogate gate | all thresholds `accept=0.0` until surrogate fills table | **Route-until-measured via explicit flag/null**, not a `0.0` sentinel; fixed floors → surrogate-overridable priors at most (§6, M2). |
| D7 | Protected-class producer | P4 "detect before deciding" + classes listed | `protected_class` field + recall-first detector noted as risk R5 | **Both lack a real detector.** Add a dedicated P0 component (§3 P0). |
| D8 | LM training set | in-corpus consensus, WCT attestation (gold-free, non-circular) | "already-processed pages" (ambiguous → can ingest own L1–L3) | **WCT-only, L0-only, current-run-excluding**, with a test (§3 P3). |
| D9 | Surrogate→position alignment | named as input, not designed | named as input, not designed | **Must be specified** — the whole 0.1% measurement rests on it (§7). |
| D10 | Fixture family count | (n/a) | "five families" on `page_0010` | **Wrong:** 5 engines, **4 families** (kraken+kraken-greek→`kraken` via `_FAMILY_MAP`). Verified on disk. |

---

## 2. Locked architecture

A new package `build/lib/gold_free_corrector/` consumes a **frozen WCT page** and emits a
**schema-validated corrected-page sidecar**. The corrector makes no edit to `wct_builder.py`
beyond one additive public accessor, and no edit to reconciler behavior in degraded mode.

```
S1 engines ─► render_s2 ─► build_wct_page  ─►  WCT page (frozen Layer-1 contract; no irreversible choice)
                                                  │
                                                  ▼
                           build/lib/gold_free_corrector/        (NEW)
                             P0 protect   (protected-class detector — runs first)
                             P1 column_vote   (new char-column algo; reuses WCT distance)
                             P2 lexicality
                             P3 lm_rescore
                             P4 decide    (level selection + measured-threshold policy)
                             P5 select    (active-learning residue ranking)
                                                  │
                                                  ▼
                           corrected-page-v1 sidecar  (schemas/v1/, position-keyed, authoritative)
                                                  │
                                                  ▼
                  s3_reconciler: shared internals extracted, then reconcile_corrected
                                                  │
                                                  ▼
                  reconciled record (references sidecar by position_id) + reviewer queue
                                                  │
                                                  ▼
                  surrogate harness  (JE 1906 — validation only; ADR-0015)
```

**Layer boundary (ADR-0014, `wct_builder` docstring):** voting *is* a choice, so it stays out of
`build_wct_page`. The WCT remains the source of slot membership; the corrector is the unsupervised
middle the brief calls for.

---

## 3. Components (locked)

### P0 — Protected-class detector (NEW — both designs lacked a producer)

**Module:** `build/lib/gold_free_corrector/protect.py`. Runs before P4 reads any score (HR5).

**Produces** `protected_class: str | None` per position for all six classes: proper names,
numbers, dates, Scripture references, Greek, Hebrew.

- **Greek/Hebrew:** from the WCT `script` / biblical-language-lane routing already emitted
  (ADR-0009/0010). On `page_0010` only `latin`/`unknown` text labels appear, so the non-Latin path
  is not exercised by that fixture — needs a Greek/Hebrew fixture for its test.
- **Numbers/dates:** regex on the voted reading.
- **Scripture references:** reuse the existing citation parser in `build/lib/` (open question R5 —
  confirm the parser's surface before depending on it).
- **Proper names:** recall-first (capitalized non-sentence-initial tokens + a gazetteer of
  consensus capitalized words). False positives cost only review time; false negatives leak the
  real-word-error reservoir, so tune for recall.

**Binding:** `protected_class is not None` ⇒ P4 forces routing regardless of every score.

### P1 — Character-column voting

**Module:** `build/lib/gold_free_corrector/column_vote.py`

**This is a new character-column algorithm that reuses the WCT distance *primitives*** — it is
**not** a reuse of `_align_engines` (which aligns engine *token sequences* by geometry via
`_merge_engine`/`_nw_align`, not characters inside a candidate string). Both reviews converged here.

- **Cost model:** expose a public weighted-edit-with-backtrace over candidate strings that uses
  **both** single-char confusions (`_sub_cost`/`_CONFUSION`, `wct_builder.py:171`) **and**
  multi-char confusions (`_MULTICHAR_CONFUSIONS`, applied in `_weighted_edit`, `wct_builder.py:177`).
  `confusion_distance` (`:202`) is string-level and is the wrong granularity for per-column work;
  `_sub_cost` alone drops `rn→m`/`cl→d`/long-s multi-char behavior. The locked design adds a
  backtrace-returning helper (see §5.1) rather than claiming either existing function is a drop-in.
- **Vote** per column by **distinct family** (not engine); ties broken by total confusion proximity,
  then lexicographically (determinism, PY-09).
- **Impossible-glyph filter:** drop a non-alphabetic glyph in an alphabetic column (the real
  `▲belavd`/`Abelard` case). **Recorded as a known limitation:** on `page_0010` l000 p000 this is a
  1-family-vs-1-family case recovered by the *filter*, not by the vote. The design must state that
  **1-vs-1 alphabetic slots route by construction** (no plurality, filter does not fire) and use a
  genuine multi-family slot as the L1 worked example.
- **Output:** an L1 `LevelReading` when every voted char is engine-attested, plus the complete
  column structure for P2/P3, plus `agreement_score`.

### P2 — Lexicality rescore

**Module:** `build/lib/gold_free_corrector/lexicality.py`

- **Lexicon (gold-free, HR7):** consensus words = positions where **≥2 distinct families** agree on
  an alphabetic `candidate_key`, length ≥3; plus public-domain dictionaries (Webster's 1913 EN,
  PD Latin headwords). Built from raw WCT attestation, never from corrector output.
- **Language scope is explicit:** the WCT loads only `en`+`la` multi-char confusions
  (`_load_multichar_confusions`, `wct_builder.py:91`); `de/fr/grc/hbo` YAML exist but are **not**
  loaded into the live model. P2 must **load the language files it needs itself** (new code) or
  inherit en/la-only — and say which. The earlier "all six languages already loaded" claim is false.
- **L2 path:** when a char no engine attested reaches a known lexicon word within a small confusion
  distance, emit an L2 reading; the corrected chars are tagged `confusion_lexicon`, `families=()`.
- **HR4 caution:** lexicality raises confidence in real words *including real-word errors* — it is
  one signal into P4, never a sole accept.

### P3 — In-corpus LM rescore

**Module:** `build/lib/gold_free_corrector/lm_rescore.py`

- **Model:** cheap char n-gram (order 5) + word bigram, add-k smoothed, pure-Python deterministic
  (KenLM optional behind the same interface).
- **Training set is locked to remove circularity (HR7):** WCT-only, **L0 consensus only**,
  excluding the current run's own L1–L3 output. A test asserts no L1–L3 output ever enters LM
  counts. ("Already-processed pages' corrected output" is explicitly disallowed.)
- **Authorship:** ranks plausibility; may author a canonical char only on the explicit L3 path,
  tagged `method="lm"`, single-char, landing on a lexicon word, surrogate-gated (HR8). Never silent.

### P4 — Decision policy

**Module:** `build/lib/gold_free_corrector/decide.py`. See §6 for the threshold contract.

### P5 — Active-learning selection

**Module:** `build/lib/gold_free_corrector/select.py`

Rank the `route`/`flag` residue by informativeness (Reul 2018, +16%):
`(1 − agreement) × family_disagreement_entropy × level_penalty`, protected classes pinned to top.
Keep all existing reviewer-queue fields (`position_id`, `reason`, `region_class`, `candidates`,
`chosen_reading`, `s3_reconciler.py:322`) and add `review_features`; P5 sets the order only.

---

## 4. Corrector artifact (schema-backed)

Add `schemas/v1/corrected-page-v1.schema.json` **before any producer code** (repo convention:
every inter-stage contract is schema-validated — rendering-v1, word-confusion-table-v1,
matrix-events-v1, reconciled_record). Position-keyed; per position it carries:
`protected_class`, the derivable `L0..L3` readings (each with text, `agreement`, `lexicality`,
`lm_score`, and **complete `character_provenance`**), the chosen `action`/`action_level`,
`derivation_method`, and a **`column_evidence` / `rejected_evidence`** block that retains filtered
losing glyphs (e.g. "ABBYY supplied `▲`; rejected as impossible in a Latin alphabetic column") so
HR3 provenance is complete and auditable, not just for winners.

---

## 5. Reconciler integration (locked)

### 5.1 WCT side — additive only (HR1)

Add a public weighted-edit-with-backtrace accessor to `wct_builder.py` (P1 needs the per-column
cost path and the alignment backtrace; the private `_sub_cost`/`_weighted_edit`/`_MULTICHAR_CONFUSIONS`
must not be reached into directly). No change to `build_wct_page`, `_align_engines`,
`_emit_position`, `_candidate_sets`. The WCT determinism tests must stay green unchanged — that is
the HR1 guard. Citation fix: `GAP_PENALTY` is `wct_builder.py:66` (not 67 = `LINE_BAND_PX`);
`SAME_SLOT_THRESHOLD = 0.5` is `:65`.

### 5.2 Extract shared internals before a second entry point

`reconcile_degraded` (`s3_reconciler.py:189`–~412) is one monolithic function interleaving reading
selection, block assembly, region-class stamping (`assign_region_class` `:104`,
`validate_region_class_stamp` `:138`), match explanations, matrix candidates, reviewer queue
(`:322`), and final invariant checks (`_assert_no_premature_matrix_labels` `:425`). **Extract the
shared internals first** (ordered positions, block assembly, region stamping, matrix-candidate
creation, invariant checks). Only then add `reconcile_corrected`, so region logic and the matrix
gate cannot drift between degraded and corrected modes. The `corrector_signals` param has direct
precedent: `reconcile_degraded` already takes `dictionary_signals` and records it as zero-weight
`post_alignment_signals` (`:286`) — corrector evidence follows that precedent, never a matrix label.

### 5.3 Carrier (resolves D4)

- Corrector evidence does **not** go into `match_explanations.signals` (schema
  `additionalProperties:false`, requires exactly `{name, raw_score, weight, contribution}` — a
  proposal dict fails closed).
- The **corrected-page sidecar is the authoritative provenance surface.** The reconciled record
  **references it by `position_id`**; it does not try to carry per-char provenance inside block
  `original_text`.
- Do **not** overload `chosen_reading_attested_by` (currently engine IDs from `attesting_engines`,
  `s3_reconciler.py:316`) with family IDs. Add an explicit `chosen_reading_attested_families` if a
  whole-candidate family list is needed.
- Degraded mode is untouched: corrector-chosen text must never overwrite degraded `original_text`.
  `_assert_no_premature_matrix_labels` is preserved verbatim; the corrector touches no matrix event.
- Any reconciled-schema field additions ship with a named consumer list and a compatibility test
  (degraded output unchanged + new corrected output valid) — "additive" is not safe by assertion.

---

## 6. Decision policy + threshold contract (locked)

**Two distinct schemas, one canonical key order.** Both reviews found the P4/config/surrogate key
shapes incompatible (`thresholds[region_class][level]` vs `surrogate_false_correction[level][region_class]`
— transposed, no adapter).

- `config/corrector_thresholds.json` — decision thresholds, keyed `[region_class][level]`.
- `reports/surrogate/corrector_rates.json` — measured rates, **same canonical key order**.
- A named loader validates both shapes and maps measured → decision; no silent cell mismatch.

**Route-until-measured is an explicit state, not `0.0`.** The all-zero default is a bug: with
`accept = 0.0`, `surrogate_false_correction <= accept` evaluates `0.0 <= 0.0 = True` and
auto-accepts — contradicting the intended embargo. Use a per-`(level, region_class)`
`auto_accept_enabled` flag (default false) or `null` measured rate that routes on missing. This is
the HR6 embargo's valid core, encoded correctly.

**Protected classes (P0) route before any threshold read** (HR5).

**Real-word-error bound is a first-class gate:** P4 carries an explicit
`max_real_word_error_rate` per `(level, region_class)`; a tier that clears CER but fails the
real-word bound is demoted to `flag`/`route` (Levchenko 2025; HR4).

**MAINTAINER DECISION (M1) — multi-level selection.** When several levels are present and pass
their thresholds, the policy must say which wins. "Highest level present" (either direction)
collapses the per-method intent: L0-first never lets safe synthesized tiers participate; L3-first
over-prefers the most synthetic path. The locked rule is: **evaluate all present levels against
measured thresholds, then choose by a stated preference.** Which preference is M1 (§9).

**MAINTAINER DECISION (M2) — fixed floors.** The concrete agreement/lexicality floors
(L0≥0.80, L1≥0.70, L2≥0.95) are the "fixed doctrine" HR2 forbids if they hard-gate publication.
Options in §9.

---

## 7. Surrogate measurement harness (locked)

**Module:** `build/tools/ocr_pipeline/measure_corrector_surrogate.py`. Reference: Jewish
Encyclopedia 1906, edition-matched diplomatic text + facsimiles (ADR-0015,
`docs/JE_SURROGATE_FINDINGS.md`). Non-circular: the corrector never sees the diplomatic text; the
harness uses it only to score.

**Must specify the surrogate→WCT-position alignment** (D9 — unspecified in both designs and the
foundation of every metric): how a JE diplomatic token maps onto a WCT `position_id` so
false-correction can be counted. Either reuse the WCT alignment machinery against the diplomatic
token stream, or consume JE token offsets where provided; name the method and its failure handling.

**Metrics, per `(level, region_class)`:** `coverage`, `false_correction_rate` (denominator =
auto-accepted positions only), `cer`, **`real_word_error_rate` (HR4, distinct from CER)**,
`non_word_error_rate`, `route_rate`, `protected_class_leak_rate` (target 0).

```python
def classify_error(output, gold, lexicon):
    if output == gold:
        return "correct"
    return "real_word_error" if lexicon.contains(output) else "non_word_error"
```

**Standing oracle (ADR-0015):** re-run on every corrector change; a tier whose real-word-error or
false-correction rate breaches its region bound is demoted by regenerating the threshold table — a
parameter change, no code change. Set `auto_accept` where the surrogate false-correction rate
reaches ~0.1% (HR6). Snapshot carries sample size, CI, date, corpus slice, and code version.

---

## 8. Build contract — must-fix list (union of both reviews)

These are binding for the per-component build prompts (roadmap §9). Each maps to a failing-first
test in §10.

**MUST-FIX**
1. **P0 protected-class detector** — a real producer for all six classes, before P4 (HR5; both designs lacked it).
2. **Schema-backed carrier** — `corrected-page-v1` sidecar is authoritative; reconciled record references it by `position_id`; nothing goes into `match_explanations.signals`; no per-char provenance crammed into `original_text`.
3. **`corrected-page-v1.schema.json` authored before any producer** (repo convention).
4. **Threshold contract** — two schemas (measured rates / decision thresholds), one canonical key order, a validating loader.
5. **Route-until-measured** via explicit flag/null, never a `0.0` sentinel.
6. **P1 alignment honesty** — a new char-column algorithm using a public weighted-edit-with-backtrace that reuses single **and** multi-char WCT confusions; do not claim `_align_engines` reuse; state the 1-vs-1 alphabetic routing rule and use a multi-family worked example.
7. **Provenance completeness** — winners, synthesized chars, deletions, **and filtered losing glyphs** (`column_evidence`/`rejected_evidence`); a `validate_character_provenance` guard with stable position spans (HR3).
8. **Do not overload `chosen_reading_attested_by`** with family IDs; add `chosen_reading_attested_families`.
9. **Level-selection semantics** — evaluate all present levels against measured thresholds (resolution of the policy detail is M1).

**SHOULD-FIX**
10. Extract shared `s3_reconciler` internals before adding `reconcile_corrected` (avoid a maintenance fork).
11. Lock the LM training extractor to WCT-only / L0-only / current-run-excluding + a test (HR7).
12. Name the reconciled-record consumers touched + a degraded-output-unchanged compatibility test.
13. Fix the fixture fact: **5 engines / 4 families**; `GAP_PENALTY` at line 66.

**NICE-TO-HAVE**
14. A worked column-alignment table for a genuine multi-family slot.
15. A typed `policy_snapshot.json` (sample size, CI, date, corpus slice, code version).
16. The two-Kraken-lanes risk is already handled upstream (`_FAMILY_MAP` collapses both to
    `kraken`); P1 voting by family inherits it for free — note, don't re-solve.

---

## 9. Open questions — build to measure, don't guess

These were first framed as maintainer decisions; they are not. Each is an empirical question the
surrogate harness answers. The design's own premise (HR2/HR6, ADR-0015) is that the surrogate sets
policy, not doctrine — so picking these by recommendation would contradict the architecture. The
build is sequenced (§12) so the harness produces the deciding data on a thin end-to-end slice
*before* the expensive components are built on an assumption.

**M1 — Multi-level selection.** When L0–L3 are all present and all pass their thresholds, which
reading wins?
- *Candidates:* lowest derivation (L0>L1>L2>L3, most attestation); highest measured confidence;
  highest coverage.
- *Measurement that decides it:* the harness emits per-`(level, region_class)` false-correction,
  real-word-error, and coverage. Simulate each selection policy over the JE surrogate and pick the
  one with the lowest real-word-error at acceptable coverage. (`test_all_levels_evaluated_then_preference`
  pins that all levels are evaluated; the *preference* is a harness output, not a constant.)

**M2 — Do the fixed agreement floors (0.80 / 0.70 / 0.95) earn their keep?**
- *Experiment:* run the surrogate with floors-on vs floors-off. If floors-on does not reduce
  false-correction beyond the surrogate threshold alone, the floors are dead weight and are
  dropped (keeping them only as P5 review-priority features). If they do cut false-correction,
  keep them as surrogate-overridable priors with an explicit precedence rule + a test that the
  snapshot overrides. Hard floors are rejected regardless (HR2).

**M3 — Protected-class / Scripture-ref detector source.** Build P0's Scripture-ref path from the
existing citation parser in `build/lib/`, or a regex first pass?
- *Measurement:* score recall (and false-positive cost) of each on the corpus / surrogate. P0 is
  recall-first, so the higher-recall option wins unless its false-positive load is prohibitive.

**The only genuinely non-empirical dependency** is ADR-0014/0015 (under adversarial review). If the
composed-readings model is narrowed, fewer levels are built and M1 shrinks; if surrogate-as-validator
is rejected, the whole measurement premise changes. That is the lock's real risk, not M1–M3.

---

## 10. Failing-first test inventory (union)

P0 — `tests/test_corrector_protect.py`
- `test_proper_name_detected_recall_first` — RED: `Abelard` not flagged proper_name.
- `test_number_date_scripture_detected` — RED: a numeric/date/ref token not flagged.
- `test_greek_hebrew_flagged_from_script` — RED: a Greek-lane position not flagged (needs Greek fixture).

P1 — `tests/test_corrector_column_vote.py`
- `test_uses_public_weighted_edit_backtrace` — RED: import of the new WCT accessor fails.
- `test_multichar_confusion_scored_like_wct` — RED: `rnodern→modern` not scored via `_MULTICHAR_CONFUSIONS` path.
- `test_one_vs_one_alphabetic_slot_routes` — RED: a 1-vs-1 alphabetic tie auto-resolves instead of routing.
- `test_multifamily_slot_votes` — RED: a 3-family-agree/1-dissent slot does not vote the plurality.
- `test_char_provenance_complete_incl_filtered` — RED: a filtered `▲` has no `rejected_evidence`.
- `test_vote_deterministic_across_hashseed` — RED: tie output differs under PYTHONHASHSEED 0 vs 1.

P2 — `tests/test_corrector_lexicality.py`
- `test_consensus_lexicon_excludes_singletons` — RED: a single-family word enters the lexicon.
- `test_l2_fix_tagged_confusion_lexicon_no_engine_family` — RED: an L2-fixed char claims engine attestation.
- `test_language_load_scope_explicit` — RED: P2 silently inherits en/la-only while claiming de/fr.
- `test_lexicality_does_not_auto_accept_realword` — RED: a lexical reading accepted on lexicality alone.

P3 — `tests/test_corrector_lm_rescore.py`
- `test_lm_trains_wct_l0_only_excludes_current_run` — RED: an L1–L3 output enters LM counts.
- `test_l3_single_char_on_lexicon_word_only` — RED: L3 emits multi-char/non-lexicon free text.
- `test_l3_tagged_method_lm` — RED: an L3 reading lacks `method="lm"` provenance.

P4 — `tests/test_corrector_decide.py`
- `test_protected_routes_before_scores` — RED: a protected position reaches threshold evaluation.
- `test_route_until_measured_not_zero_sentinel` — RED: `0.0 <= 0.0` auto-accepts under the default table.
- `test_all_levels_evaluated_then_preference` — RED: only the highest level is considered.
- `test_realword_bound_demotes_tier` — RED: a tier failing the real-word bound still auto-accepts.
- `test_derivation_method_on_every_decision` — RED: an accepted token lacks `derivation_method`.

P5 — `tests/test_corrector_select.py`
- `test_residue_ranked_by_disagreement` — RED: a high-agreement position outranks a max-disagreement one.
- `test_protected_pinned_to_top` — RED: a protected position ranks below a body position.
- `test_s3_queue_fields_preserved` — RED: an existing reviewer-queue field is dropped.

Reconciler — `tests/test_reconcile_corrected.py`
- `test_degraded_unchanged` — RED: `reconcile_degraded` output differs from the committed `page_0010` baseline.
- `test_corrector_evidence_not_in_match_explanations` — RED: a proposal is written into `signals` (schema fails closed).
- `test_reconciled_references_sidecar_by_position_id` — RED: per-char provenance crammed into `original_text`.
- `test_attested_families_field_separate_from_engines` — RED: `chosen_reading_attested_by` holds family IDs.
- `test_matrix_gate_preserved` — RED: a corrected position trips `_assert_no_premature_matrix_labels`.

Surrogate — `tests/test_measure_corrector_surrogate.py`
- `test_surrogate_position_alignment_specified` — RED: harness has no diplomatic→position mapping.
- `test_real_word_error_distinct_from_cer` — RED: real-word errors folded into CER.
- `test_classify_error_realword_vs_nonword` — RED: `modem/modern` (real-word) vs `m0dern/modern` (non-word) misclassified.
- `test_false_correction_denominator_auto_accepted_only` — RED: routed/flagged positions in the denominator.
- `test_threshold_keys_match_loader` — RED: measured-rate keys don't map to the decision-threshold loader.

Schema — `tests/test_corrected_page_schema.py`
- `test_corrected_page_v1_validates_real_page` — RED: a `CorrectedPage` from `page_0010` fails the new schema.

---

## 11. Corrections to the record

- **ADR-0014 / ADR-0015 are on disk and Accepted (2026-06-05)** (`1de8ff2c`). The Claude design's
  dependency on them is valid; an earlier orchestration note that called them missing was based on a
  stale pre-parallel-session listing and is retracted.
- **`page_0010` has 5 engines and 4 families** (kraken + kraken-greek → `kraken`), verified on disk.
  The Claude design's "five families" is corrected.
- **`GAP_PENALTY` is at `wct_builder.py:66`**; line 67 is `LINE_BAND_PX`. Verified on disk.

---

## 12. Next step — build-to-measure sequence + dispatch model

**Sequence (thin end-to-end slice first, to get data on §9 before building on assumptions):**

1. `schemas/v1/corrected-page-v1.schema.json` + its validation test.
2. P0 (protected-class detector) and P1 (char-column vote with the new WCT backtrace accessor) —
   they exercise the most design decisions and produce L0/L1 readings.
3. A **minimal P4** (route-until-measured, all levels evaluated, no fixed floors yet) + a
   **minimal surrogate harness** (§7) on a small JE slice. This is the data-acquisition slice: it
   measures per-level rates and lets M1/M2 be answered from numbers, not opinion.
4. Read the surrogate numbers → settle M1 (selection policy) and M2 (floors) from data.
5. Then build P2, P3, P5 and the full reconciler integration (§5) against the settled policy.

This deliberately defers P2/P3 sophistication until the slice shows which alternatives the data
favors — "build to acquire the data of alternative approaches rather than guess."

**Dispatch model (CODEX-05, reaffirmed 2026-06-05):** Claude orchestrates and writes the build
prompts; **Codex implements** each component to its spec at `model_reasoning_effort="medium"` (the
coding tier); **Claude reviews Codex's code, runs `standards_check.py` + the §10 tests, and
commits.** Reserve `"high"`/extra-high for reasoning passes, not these implementation dispatches.
Never ask Codex to commit. Per-component build prompts are authored from this locked design, each
carrying its §10 failing-first tests.
