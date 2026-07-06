# Gold-Free Corrector Stack Design

## Decision brief

- Insert a `gold_free_corrector` pass after WCT construction and before `s3_reconciler.reconcile_degraded()`. It consumes WCT positions and emits position-level correction proposals, method tags, provenance, review ranking, and surrogate-measurement metrics.
- Keep WCT alignment as the source of slot membership. Reuse `build/lib/wct_builder.py` functions `_weighted_edit()`, `confusion_distance()`, `_load_multichar_confusions()`, and the emitted `candidate_set` / `span_records` fields. Do not change slot formation.
- Allow canonical methods L0-L3, but publish unflagged output only for method tiers whose Jewish Encyclopedia surrogate false-correction rate is about `0.1%` or better. All tiers remain built and measured.
- Route protected classes to human or VLM review regardless of agreement: proper names, numbers, dates, Scripture references, Greek, and Hebrew. This is the main coverage sacrifice.
- Treat real-word errors as a top metric, separate from CER. Lexical and LM scoring must never hide the case where the output is a valid word but the wrong word.

## Scope and current pipeline facts

The current WCT builder already performs the alignment needed for this stack. It normalizes candidates for grouping only, then emits per-position evidence. The relevant code paths are:

- `build/lib/wct_builder.py`: `_sub_cost()`, `_weighted_edit()`, and `confusion_distance()` implement confusion-weighted edit distance.
- `build/lib/wct_builder.py`: `_load_multichar_confusions()` reads `build/lib/ocr_error_models/*.yaml`, which already includes English, German, French, Greek, Hebrew, and Latin confusions.
- `build/lib/wct_builder.py`: `_candidate_sets()` groups engine attestations into `candidate_set` with `candidate_id`, `raw_reading`, `candidate_key`, `normalisation_applied`, `attesting_engines`, and later `attesting_families`.
- `build/lib/wct_builder.py`: `_emit_position()` emits `position_id`, `zone`, `script`, `candidate_set`, `span_records`, `available_engines`, `comparable_engines`, and `alignment_confidence`.
- `build/lib/wct_builder.py`: `_attesting_span_record()` emits per-engine `raw_text`, `normalized_text`, `family`, `source_spans`, confidence fields, and `candidate_id`.

The current S3 reconciler does not resolve truth. Its useful surfaces are:

- `build/lib/s3_reconciler.py`: `_best_candidate()` picks a deterministic advisory reading by attesting families and engines.
- `build/lib/s3_reconciler.py`: `reconcile_degraded()` reads WCT `positions`, classifies `dispute` or `consensus_unconfirmed`, records zero-weight `alignment_confidence`, appends every position to `reviewer_queue`, and emits matrix candidates with `not_measurement_eligible`.
- `reports/wct/vol_01/page_0010.json`: real WCT shape. Example `vol_01:page_0010:body:c1:l000:p000` has candidates `Abelard` and `▲belavd`, per-engine spans, `attesting_families`, and `alignment_confidence: 0.7`.
- `reports/reconciled/vol_01/page_0010.json`: real reconciled shape. The first page token currently chooses `▲belavd` as an advisory reading, demonstrating that the degraded reconciler needs this pre-S3 corrector.

## Architecture

Add one pure library and two tools:

- `build/lib/gold_free_corrector.py`: pure functions. Input is a WCT page and immutable resources. Output is a correction page artifact.
- `build/tools/build_gold_free_lexicon.py`: builds the domain lexicon from high-consensus WCT text, public-domain dictionaries, and OCR error model expansions.
- `build/tools/measure_gold_free_corrector.py`: runs the stack on the Jewish Encyclopedia surrogate and writes tier metrics.

No human-adjudicated labels feed this stack. Human review may consume the residue and later create gold, but gold is downstream of this design.

Proposed integration:

```text
rendering-v1 pages
  -> build_wct_page() / reports/wct/...json
  -> gold_free_corrector.correct_wct_page()
  -> reconcile_degraded(..., corrector_signals=...)
  -> reconciled record + reviewer queue + measurement artifacts
```

The S3 function should gain an optional `corrector_signals: dict[str, dict]` parameter in implementation. In degraded mode it records the corrector proposal and uses the policy result for block text only when the proposal's method tier passes surrogate policy. Until the policy snapshot exists, it keeps routing to review.

## Correction artifact

Write one artifact per WCT page:

```json
{
  "schema_version": "gold-free-corrector-v1",
  "wct_page_id": "vol_01:page_0010",
  "policy_version": "gold-free-corrector-policy-v1",
  "positions": [
    {
      "position_id": "vol_01:page_0010:body:c1:l000:p000",
      "protected_class": {"is_protected": true, "classes": ["proper_name"]},
      "proposals": [
        {
          "reading": "Abelard",
          "derivation_method": "L0_attested_whole_word",
          "publication_state": "route_human_or_vlm",
          "agreement_score": 0.50,
          "lexicality_score": 1.0,
          "lm_score": 0.64,
          "provenance": [
            {
              "char_index": 0,
              "char": "A",
              "source": "engine_attestation",
              "attesting_engines": ["tesseract-py314-v1"],
              "attesting_families": ["tesseract"],
              "candidate_ids": ["cand_001"]
            }
          ]
        }
      ],
      "review_features": {
        "disagreement_score": 0.93,
        "real_word_risk": 0.90,
        "priority_reason": "protected_proper_name"
      }
    }
  ]
}
```

The reconciler should copy the chosen proposal into `match_explanations.signals` with non-matrix status. The fields must not emit trained matrix labels.

## P1: Character-column voting

Inputs:

- WCT position: `candidate_set`, `span_records`, `script`, `zone`, `alignment_confidence`, `available_engines`, and `comparable_engines`.
- WCT confusion functions: `confusion_distance()` and the same cost tables used by `_weighted_edit()`.
- Engine family map as already emitted in `span_records.family` and `candidate_set.attesting_families`.

Outputs:

- `voted_reading`.
- `agreement_score`.
- `char_provenance[]`, one record per output character.
- `rejected_chars[]` for impossible-character filtering.
- Candidate alignment diagnostics for test and audit.

Algorithm:

1. Gather each non-skip span from `span_records` and keep `engine_id`, `family`, `candidate_id`, `normalized_text`, `raw_text`, and `source_spans`.
2. Align candidate strings inside the WCT slot using a Needleman-Wunsch character alignment with the existing WCT confusion costs. This reuses the WCT distance model but applies it inside one slot.
3. For each column, count votes by family first, then by engine as a tie-break. Do not treat the two Kraken lanes as independent families.
4. Apply the impossible-character filter. In an alphabetic token context, reject a non-alphabetic glyph such as `▲` unless every alphabetic alternative also fails the protected-class policy. Record the rejected glyph in provenance.
5. Emit the plurality character when it is attested by at least one engine. Emit a gap only if the gap wins and the resulting token remains non-empty.
6. Compute `agreement_score` as the mean per-column family support divided by comparable family count, with a penalty for insertions, deletions, rejected glyphs, and single-family support.

Parameters:

| Parameter | Initial value | Meaning |
|---|---:|---|
| `min_family_support_l1` | `1` | L1 allows any character attested by at least one engine. |
| `min_auto_family_support_l1` | `2` | Unflagged L1 publication needs at least two families unless surrogate policy says otherwise. |
| `glyph_reject_penalty` | `0.40` | Subtracted from agreement score when a glyph is rejected. |
| `max_internal_distance` | `0.50` | Uses the WCT `SAME_SLOT_THRESHOLD` value as the default intra-slot bound. |
| `same_family_weight` | `0.50` | Extra engines in the same family add less than a new family. |

Integration point:

- Runs after `build_wct_page()` emits `positions`.
- Does not alter `candidate_set` or `span_records`.
- Feeds S3 as `corrector_signals[position_id].p1`.

Provenance rules:

- `engine_attestation`: character appears in at least one candidate string. Include engines, families, candidate IDs, span IDs, and source span token IDs where available.
- `rejected_glyph`: character was seen but rejected by context.
- `gap`: no character emitted for an aligned column.

## P2: Lexicality rescore

Inputs:

- P1 `voted_reading` and all WCT candidate strings.
- Domain lexicon from high-confidence consensus WCT words. A consensus word qualifies when one candidate has at least two independent families, no protected class, Latin body text, and no impossible glyph.
- Public-domain dictionaries for English, German, French, Latin, and known theological abbreviations.
- Confusion expansions from `build/lib/ocr_error_models/*.yaml`.

Outputs:

- `lexicality_score` in `[0, 1]`.
- `lexicon_status`: `known_word`, `known_name`, `abbreviation`, `nonword`, `script_foreign`, `protected`.
- `near_lexicon_matches[]` with distance, confusion rules used, and whether a correction would be L2.
- `real_word_risk` flag when two or more candidate readings are valid lexical words.

Algorithm:

1. Normalize for lookup only: case-fold, strip surrounding punctuation, preserve apostrophes and internal hyphenation.
2. Look up exact forms in the domain lexicon and public-domain dictionaries.
3. Expand one-step and two-step OCR confusions using the YAML models. A confusion correction may create an L2 proposal only if the target is known and the change is within `max_l2_confusion_distance`.
4. Mark any proper-name candidate as protected. The lexicon may identify it; it may not auto-publish it.
5. Raise `real_word_risk` when the top alternatives are both known words or known names, because lexicality cannot decide between them.

Parameters:

| Parameter | Initial value | Meaning |
|---|---:|---|
| `consensus_min_families` | `2` | Lexicon seed threshold. |
| `domain_min_count` | `2` | Corpus frequency needed for a new domain word unless public dictionary backs it. |
| `max_l2_confusion_distance` | `0.34` | Normalized WCT confusion distance for lexicon-backed L2. |
| `max_l2_edits` | `2` | Hard cap for edits in one token. |
| `proper_name_min_signal` | `1` | Any proper-name signal routes protected. |

Integration point:

- Runs after P1.
- Feeds P4 via `lexicality_score`, `lexicon_status`, `near_lexicon_matches`, and `real_word_risk`.

## P3: In-corpus LM rescore

Inputs:

- Consensus text selected without gold: high-family WCT consensus, Latin body text, non-protected, no impossible glyphs.
- P1 and P2 candidates: attested whole-word candidates, P1 voted reading, L2 lexicon corrections.
- Local context from WCT `reading_order`, previous and next positions, zone type, and page metadata.

Outputs:

- `lm_score` per candidate.
- `lm_rank`.
- `context_flags`: `fits_context`, `context_weak`, `context_conflict`.
- Optional L3 proposal with full provenance.

Algorithm:

1. Train a cheap character 5-gram model and word trigram model on the corpus's own high-confidence consensus text.
2. Score only candidates supplied by P1/P2 or explicit L3 context proposals. The LM must not emit arbitrary free text.
3. Combine char and word scores with length-normalized log probability.
4. Use LM as a ranker. It may promote among existing candidates or flag low plausibility. It may author canonical text only as L3, with `source: "lm_context_proposal"`, and only after surrogate measurement approves that method tier.

Parameters:

| Parameter | Initial value | Meaning |
|---|---:|---|
| `char_order` | `5` | Character n-gram order. |
| `word_order` | `3` | Word n-gram order. |
| `lm_min_delta_for_rank` | `0.15` | Minimum normalized score gap to affect ranking. |
| `l3_default_publication_state` | `route_human_or_vlm` | L3 exists, but starts flagged until surrogate metrics pass. |

Integration point:

- Runs after P2.
- Feeds P4 ranking and P5 review features.

## P4: Decision policy and canonical levels

Inputs:

- P1 character vote output and `char_provenance`.
- P2 `lexicality_score`, `lexicon_status`, `near_lexicon_matches`, and `real_word_risk`.
- P3 `lm_score`, `lm_rank`, and any L3 proposal.
- Protected-class detector output.
- Surrogate `policy_snapshot.json` with per-level false-correction and real-word-error thresholds.

Outputs:

- One selected proposal per position, or an explicit `review_only` result.
- `derivation_method` in L0-L3.
- `publication_state`.
- `decision_reasons[]`.
- Policy signals for S3 `match_explanations`.

Each canonical token carries `derivation_method`, `publication_state`, and per-character provenance. The four levels are all built:

| Level | Method tag | Allowed source | Auto-publication condition |
|---|---|---|---|
| L0 | `L0_attested_whole_word` | A WCT candidate in `candidate_set.raw_reading` | Candidate is attested, not protected, no real-word risk, and its method tier passes surrogate threshold. |
| L1 | `L1_character_voted` | P1 output where every character has `engine_attestation` | Every emitted character is attested by at least one engine, not protected, lexicality and LM agree, and L1 tier passes surrogate threshold. |
| L2 | `L2_confusion_lexicon` | P2 small-distance correction to a known lexical form | Non-attested characters are justified by named OCR confusion rules and lexicon membership; starts flagged until surrogate approves L2. |
| L3 | `L3_lm_context` | P3 context proposal | LM/VLM may rank or verify; canonical text authored here remains tagged, measured, and usually routed. |

Policy steps:

1. Detect protected classes before deciding. If protected, set `publication_state = route_human_or_vlm` regardless of agreement. Classes: proper names, numbers, dates, Scripture references, Greek, Hebrew.
2. If one whole-word candidate has independent-family consensus and no protected class, emit L0.
3. If P1 creates a reading whose every character has engine attestation, emit L1.
4. If P2 proposes a known-word correction using only small-distance OCR confusions, emit L2.
5. If P3 proposes a context-only token, emit L3.
6. Apply the surrogate policy snapshot per level and protected class. A level can be built and still not published unflagged.

Parameters:

| Threshold | Initial value |
|---|---:|
| `surrogate_false_correction_target` | `0.001` |
| `min_l0_agreement_score` | `0.80` |
| `min_l1_agreement_score` | `0.70` |
| `min_l2_lexicality_score` | `0.95` |
| `min_lm_score_delta` | `0.15` |
| `max_real_word_error_rate_unflagged` | `0.001` |

Publication states:

- `publish_unflagged`: method tier is below the surrogate error ceiling and position is not protected.
- `publish_flagged`: method tier has acceptable false-correction rate for internal assembly but not for public text.
- `route_human_or_vlm`: protected or above threshold.
- `review_only`: no canonical proposal beats review.

Integration point:

- Runs after P1-P3 for each WCT position.
- Feeds `corrector_signals[position_id].policy` into S3.
- S3 records the policy as non-matrix evidence and uses `publication_state` to choose whether block text can receive the proposed canonical token.

## P5: Active-learning selection

Inputs:

- WCT disagreement shape: candidate count, family split, alignment confidence, script, region, and skips.
- P1-P4 outputs: agreement score, lexicality score, LM rank gap, protected class, rejected glyphs, real-word risk, publication state.
- Existing S3 reviewer queue fields: `position_id`, `reason`, `region_class`, `candidates`, and `chosen_reading`.

Outputs:

- `review_priority_score`.
- `review_priority_reason`.
- `sample_stratum`.
- A ranked queue for gold sampling and human review.

Algorithm:

Score residue with this ordered model:

```text
protected_class_bonus
+ real_word_risk_bonus
+ high_family_disagreement
+ low_p1_agreement
+ small_lm_delta
+ rejected_glyph_bonus
+ rare_confusion_bonus
+ region_class_pending_bonus
```

Initial weights:

| Feature | Weight |
|---|---:|
| Protected class | `1.00` |
| Real-word risk | `0.90` |
| Two valid lexical alternatives | `0.80` |
| Candidate families split 1-vs-1 | `0.60` |
| Rejected impossible glyph | `0.55` |
| Low P1 agreement | `0.50` |
| Low LM delta | `0.35` |
| Rare OCR confusion | `0.25` |

Integration point:

- Replace the current queue ordering only after the corrector artifact exists.
- Keep S3 queue fields intact and add `review_features`.
- Use the ranked residue to draw the first human gold sample from the highest-information positions, matching the Reul 2018 active-learning result noted in `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md`.

## Surrogate measurement harness

Use the Jewish Encyclopedia surrogate as a non-circular measurement reference. It must use edition-matched diplomatic text and page images for the surrogate corpus, not Schaff-Herzog human gold.

Inputs:

- Surrogate WCT pages built through the same S1/S2/WCT path.
- Surrogate diplomatic text aligned to WCT positions.
- Corrector output for the surrogate pages.

Metrics per level and per protected class:

- `coverage`: positions receiving each method tag.
- `false_correction_rate`: positions where the corrector changes an already-correct source/candidate into a wrong output.
- `cer`: character error rate against surrogate text.
- `non_word_error_rate`: output is not a valid lexical token and differs from surrogate.
- `real_word_error_rate`: output is a valid lexical token and differs from surrogate.
- `route_rate`: positions routed to human/VLM.
- `protected_class_leak_rate`: protected positions published unflagged. Target is zero.

Real-word-error definition:

```text
real_word_error = is_valid_lexical_word(output)
                  and normalize_for_eval(output) != normalize_for_eval(surrogate_gold)
```

Non-word error:

```text
non_word_error = not is_valid_lexical_word(output)
                 and normalize_for_eval(output) != normalize_for_eval(surrogate_gold)
```

Threshold policy:

1. Measure L0-L3 separately.
2. Set `publish_unflagged` only for method tiers with surrogate `false_correction_rate <= 0.001` and `real_word_error_rate <= 0.001`.
3. If a tier clears CER but fails real-word-error rate, route it. This is the Levchenko 2025 failure mode from `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md`.
4. Save the policy snapshot with sample size, confidence interval, date, corpus slice, and exact code version.

Reports:

- `reports/gold_free_corrector/surrogate_metrics.json`
- `reports/gold_free_corrector/surrogate_by_level.csv`
- `reports/gold_free_corrector/policy_snapshot.json`

## LLM and VLM rules

LLM/VLM can do three things:

- Rank candidate plausibility.
- Flag protected or risky positions.
- Verify an image crop against a proposed candidate.

LLM/VLM cannot silently author canonical text. If it supplies text, the token is L3 with `source: "lm_context_proposal"` or `source: "vlm_image_proposal"`, full provenance, and surrogate-measured policy. Protected classes still route unless a future policy snapshot proves a safe image-verification tier.

## Risks and open questions

- Proper-name detection will over-route titlecase words at line starts. That is acceptable for the first pass because proper names are a real-word-error reservoir.
- L1 character voting can create plausible but wrong words. The surrogate real-word metric decides whether any L1 sub-tier can publish unflagged.
- L2 may correct historical spellings into modern dictionary forms. The lexicon builder must preserve historical and domain forms and treat modernization as out of scope.
- Greek and Hebrew need grapheme-level handling later. This design routes them instead of pretending the Latin character voter is enough.
- Two Kraken lanes share a family. The vote model must not count them as independent evidence.
- JE surrogate transfer may understate Schaff-specific name risk. Report Schaff protected-class coverage separately before trusting broad publication.

## Failing-first test inventory

| Test name | Slot covered | Expected failing condition before implementation |
|---|---|---|
| `test_p1_reuses_wct_confusion_distance_for_columns` | P1 / HR1 | Character voter does not call the same confusion-cost behavior as WCT. |
| `test_p1_impossible_glyph_rejected_in_alpha_context` | P1 | `▲belavd` beats `Abelard` in an alphabetic slot without rejection evidence. |
| `test_p1_char_provenance_for_every_output_char` | P1 / HR3 | A voted character lacks engine, family, candidate, or source span provenance. |
| `test_p1_same_family_not_double_counted` | P1 | `kraken` and `kraken-greek` count as independent families. |
| `test_p2_lexicon_built_without_human_gold` | P2 / HR7 | Lexicon builder reads human adjudication files. |
| `test_p2_l2_requires_named_confusion_rule` | P2 / HR2 | L2 correction emits a non-attested character without a YAML confusion rule. |
| `test_p2_real_word_risk_when_two_valid_words` | P2 / HR4 | Two dictionary-valid alternatives do not raise real-word risk. |
| `test_p3_lm_scores_only_supplied_candidates` | P3 / HR8 | LM emits free text outside P1/P2/L3 proposal path. |
| `test_p3_l3_provenance_marks_lm_source` | P3 / HR2 / HR3 | L3 text lacks `L3_lm_context` and per-character source tags. |
| `test_p4_levels_0_to_3_all_constructed` | P4 / HR2 | Policy omits any of L0, L1, L2, or L3 from output. |
| `test_p4_protected_name_routes_despite_agreement` | P4 / HR5 | Proper name publishes unflagged because engines agree. |
| `test_p4_numbers_dates_scripture_route` | P4 / HR5 | Numeric/date/reference tokens publish unflagged. |
| `test_p4_greek_hebrew_route` | P4 / HR5 | Greek or Hebrew token publishes through Latin policy. |
| `test_p4_policy_uses_surrogate_threshold_not_fixed_doctrine` | P4 / HR2 / HR6 | Publication state ignores per-level surrogate false-correction rates. |
| `test_p5_ranks_real_word_risk_above_consensus` | P5 / HR4 | Active-learning queue ranks safe consensus above a valid-word dispute. |
| `test_p5_review_features_added_without_removing_s3_fields` | P5 | Reviewer queue loses existing `position_id`, `reason`, `candidates`, or `chosen_reading`. |
| `test_surrogate_reports_false_correction_by_level` | HR6 | Metrics aggregate levels and cannot tune policy per method. |
| `test_surrogate_reports_real_word_separate_from_cer` | HR4 / HR6 | Metrics report only CER/WER and hide real-word errors. |
| `test_surrogate_threshold_demotes_failed_tier` | HR6 | A tier above `0.1%` false-correction still publishes unflagged. |
| `test_llm_vlm_cannot_silent_author_text` | HR8 | LLM/VLM text appears without L3 tag and provenance. |

## Implementation sequence

1. Add artifact schema tests for `gold-free-corrector-v1`.
2. Implement P1 character voting against WCT fixture positions, starting with `reports/wct/vol_01/page_0010.json` cases.
3. Build the lexicon generator and P2 scoring.
4. Add P3 n-gram scoring as a ranker only.
5. Add P4 policy and protected-class routing.
6. Add P5 review ranking and thread it into S3 as non-matrix corrector signals.
7. Build the JE surrogate measurement tool and freeze the first `policy_snapshot.json`.
