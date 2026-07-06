# Measurement Reference Options: Getting a Non-Circular Reference for M2/M3

*Scoping note. Not an implementation, and not the architecture decision (keep-matrix
vs agree->escalate vs verification-spine stays the maintainer's call). This note scopes
how to build a reference that is not conditioned on OCR agreement, so M2 and M3 can
actually answer the truth-rule question.*

## Decision Brief

- **The problem.** M2 (auto-accept error) and M3 (truth-rule A/B) score readings against
  a CCEL-derived reference whose "gold" bucket is *defined* as CCEL == OCR-reading after
  normalization. On gold positions the score is correct by construction; on disagreement
  positions it is wrong by construction. The pooled rate is the bucket mix, not accuracy.
  (The harness now reports the two strata separately; see
  `m2_auto_accept_audit.strata` and `m3_truth_rule_ab.matrix_rule.strata`.)
- **The fix requires truth, not agreement.** A reference that breaks circularity cannot be
  derived from CCEL-vs-OCR consensus. The two viable sources are (A) a human-adjudicated
  gold set built from the existing adjudication queue, and (B) an independently aligned
  reference text.
- **Recommendation: Option A**, scoped to a stratified sample of roughly 300-500
  positions across the existing 10 pages. M3's population (positions where families
  disagree) is *fully framed* by the adjudication queue, so a queue sample gives a clean,
  non-circular M3 directly. M2 needs a small supplementary random sample of auto-accept
  positions that are not in the queue.
- **Option B as triage, not reference.** A non-panel OCR engine is useful to *rank* which
  queue items to adjudicate first, but it is silver (it has its own errors) and cannot
  replace human truth for a decision this load-bearing. An independent edition text
  reintroduces the edition-offset problem (PIPE-29) and measures OCR-vs-edition, not
  accuracy.
- **Cost.** Option A is roughly 1.5-3 hours of adjudication for vol_01 at the recommended
  sample size, because the queue already stages the scan crop, candidate readings, and
  block labels for every item. It scales linearly if extended past vol_01.

## Why the Current Reference Is Circular

`align_ccel_to_wct.py` emits a `gold_candidate` only when the CCEL token equals the OCR
consensus reading after normalization; every other aligned position becomes a
`ccel_ocr_disagreement` reviewer-queue item. `measure_reconciliation.py` then builds its
scoring reference from both buckets. Scoring an OCR or reconciler reading against that
reference is therefore predetermined by the bucket: the gold stratum agrees with the
reading by definition, the disagreement stratum disagrees with it by definition. No
choice the reconciler makes can move the gold-stratum number, and on the disagreement
stratum the matrix rule that picks the OCR consensus is wrong by definition.

Breaking this needs a reference whose truth value at each position is established
*independently of whether the engines agreed* — that is, from the scan image itself, or
from a source that is not the same CCEL-vs-consensus comparison.

## Option A: Human-Adjudicated Gold From the Adjudication Queue

### What exists already

`reports/measurement/vol_01/adjudication_queue.json` holds 4198 items across the 10
measured pages (about 420 per page). Each item carries the source image path, the
reference bbox, the candidate readings, the family labels, the independent-block labels,
and the CCEL proposal value. The queue is exactly the set of contested positions:
`families_disagree` (the engines produced different readings) or
`engines_agree_ccel_dissents` (the engines agreed and CCEL disagreed). Every field an
adjudicator needs to decide the true reading from the scan crop is already staged.

### Coverage of each measurement

- **M3 is fully framed by the queue.** M3's population is "positions where independent
  family candidate readings disagree" — every such position is a `families_disagree`
  queue item. Adjudicating a sample of the queue and scoring the matrix rule and the
  agree->escalate rule against the adjudicated reading gives a non-circular M3 directly,
  and it can finally distinguish the two rules.
- **M2 is partially framed by the queue.** M2's population is positions where two or more
  independent non-CCEL family blocks agree on a reading. Auto-accept errors live where
  the engines agreed but were wrong — those surface as `engines_agree_ccel_dissents`
  queue items, so the *error-bearing* subset of M2 is in the queue. The
  agree-and-match-CCEL subset is not in the queue and is near-certainly correct, but to
  bound the auto-accept error honestly it needs a small supplementary random sample drawn
  from non-queue auto-accept positions.

### Sampling strategy

- **Stratify** by page type (body, footnote, Greek, Greek-dense, Greek+Hebrew,
  low-quality), by reason (`families_disagree` vs `engines_agree_ccel_dissents`), and by
  independent-block count. The existing 10-page set was chosen to span the failure
  surface, so the strata are already present.
- **Size.** Around 300-500 adjudicated positions gives a simple-random worst-case 95%
  half-width of roughly 4.4 percentage points (n=500) to 5.7 points (n=300) before
  stratification. Set the final n after choosing the decision threshold and the per-stratum
  minimums; the range above is a starting bound, not a target. Allocate proportionally to
  stratum size, but
  oversample the two rare, high-signal strata: `engines_agree_ccel_dissents` (the M2 error
  signal) and `families_disagree` on Greek/Greek-dense pages (where the matrix rule is
  most likely to misfire).
- **Coverage-asymmetric pages.** Page 381 aligns only 158 CCEL tokens against 706 WCT
  positions, and page 137 is low on both coverage axes. Cap their contribution so the
  sample is not dominated by alignment-risk positions; record the cap rather than letting
  it pass silently (SCALE-02).

### Who adjudicates, and the quality bar

The maintainer adjudicates by reading the scan crop. Double-adjudicate a 10-15% overlap
subset to measure self-consistency. Where the true reading cannot be established from the
image (ambiguous glyph, torn scan, a script the adjudicator cannot read), mark the
position *unverifiable* and exclude it from scoring rather than guess — this follows the
project's "blank over unverifiable guess" rule. Greek and Hebrew positions need a reader
competent in those scripts; otherwise they are marked unverifiable.

### How it plugs into the harness

- Human adjudication produces verified `gold-record-v1` entries minted through the
  existing `ccel_gold` mark/withdraw/supersede authority events. The tuning embargo
  forbids *machine-authored* gold `ground_truth_text`; human-authored truth is exactly
  what `gold-record-v1`'s `verified` state is for, so this is the sanctioned path
  (`align_ccel_to_wct.py` already documents minting gold this way).
- `measure_reconciliation.py` gains a reference mode that reads
  `position_id -> ground_truth_text` from the human gold instead of from the CCEL
  alignment. In human-reference mode the gold/disagreement bucketing does not apply: every
  adjudicated position is simply truth, so the pooled M2 error and M3 accuracy become real
  numbers on the adjudicated sample. Scoring is restricted to adjudicated positions, and
  the report states the adjudicated coverage.
- The Task-1 `strata` fields stay relevant only in CCEL-reference mode, where they keep
  the circularity visible. They become inert (single stratum) under a human reference.

### Trade-offs

| | |
|---|---|
| Strengths | Yields actual truth, not silver. Fully frames M3. Reuses queue infrastructure and the existing mint authority. Non-circular by construction. |
| Costs | Human time, linear in sample size and in pages. M2's full auto-accept population needs a supplementary non-queue sample. Single-adjudicator bias, mitigated by overlap double-adjudication and blank-on-unsure. Greek/Hebrew need a competent reader. |

## Option B: Independently Aligned Reference Text

The idea is to score against a second reference that is not the CCEL-vs-consensus
comparison. Three sub-variants, each with a distinct failure mode:

1. **Full CCEL alignment, not just the gold bucket.** Use the CCEL token at every aligned
   position as the reference regardless of agreement. This removes the *bucket*
   conditioning but reintroduces the edition-offset problem: CCEL is a 1951 reprint and
   the scans are the 1908-14 edition (PIPE-29), so CCEL differs from the scan at many
   positions for legitimate edition reasons. This measures OCR-vs-CCEL-edition, not OCR
   accuracy. Rejected as a primary reference.
2. **A different digital edition aligned by the same method.** If a second independent
   digital edition of the same text exists, align it to the page and score against it.
   This still measures OCR-vs-that-edition (edition offset again) and adds the alignment
   noise of the un-tuned Needleman-Wunsch aligner (B8-gated). Useful only if the second
   edition matches the *scanned* edition, which removes most of the offset.
3. **Re-OCR with a non-panel engine as a silver reference.** Run a high-accuracy engine
   outside the five-engine panel (for example a commercial document-AI service) and treat
   its output as an independent silver reference. This breaks the specific circularity
   because the engine is independent of both the panel and CCEL. It is silver, not gold:
   it has its own errors, so it measures agreement, not truth, unless its disagreements
   are themselves adjudicated — at which point this collapses back into Option A. The
   engine's independence must be checked with the existing family-independence logic; if
   it collapses into an existing block, it is not independent enough to serve as a
   reference.

### Trade-offs

| | |
|---|---|
| Strengths | No per-position human adjudication for the silver-engine route. Scales cheaply across many pages. |
| Costs | Silver, not gold — measures agreement, not accuracy. Edition-offset for the edition-text routes (PIPE-29). Alignment noise from the un-tuned aligner. The silver-engine route only yields truth once its disagreements are adjudicated, which is Option A. |

## Recommendation

Build **Option A**: a stratified, human-adjudicated gold set of roughly 300-500 positions
drawn from the existing adjudication queue, scoring M3 on a queue sample (a complete frame
for its population) and M2 on the queue's `engines_agree_ccel_dissents` items plus a small
random sample of non-queue auto-accept positions. Mint the adjudicated readings as
`gold-record-v1` `verified` entries through the existing `ccel_gold` authority, and add a
human-reference mode to `measure_reconciliation.py`.

Use **Option B**'s non-panel-engine route only as a triage signal: rank queue items so the
positions where an independent engine disagrees with *both* the panel consensus and CCEL
are adjudicated first, since those carry the most information about auto-accept error. The
human adjudication remains the reference; the silver engine only orders the work.

This is the only path that produces actual truth, it is the only one that fully and
non-circularly frames the keep-matrix vs agree->escalate question, and the marginal cost
per adjudication is low because the queue already stages everything an adjudicator needs.
