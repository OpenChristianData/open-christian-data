# ADR-0018: LLM Review may propose unattested readings via the L3 composed-reading path

**Status:** Accepted (2026-06-25)

## Context

The grill-with-docs lexicon pass (ADR-0016) split the old S5 "reviewer + LLM-in-loop" into two clean stages: **LLM Review** (stage 7) and **Human Review** (stage 9). Naming the LLM stage surfaced a substantive design question the maintainer flagged: the locked architecture (arch6, `plans/2026-05-28-archC-integration-locked-architecture.md`) constrains the LLM to "evidence provider, never authority: output selects or explains against existing attestations, **never creates unattested canonical text**." The maintainer's objection: when every engine misreads the same word (the architecture's own "no-engine-correct" class), binding the LLM to engine outputs guarantees the error survives — an artificial limit on the LLM's most useful case.

This sits in tension with **ADR-0014** (machine-composed readings), which already permits a model to author canonical characters: "A language or vision model may rank, flag, or verify candidates; it authors canonical characters only via the tagged, provenance-tracked **L3** path." ADR-0014 already supplies the machinery for an unattested reading to exist safely — character provenance, the `machine_composed` public label, the protected-class → human-review gate, flagged-until-certified publication, and a supersession contract. The capability the maintainer wants is largely already designed; arch6's blanket prohibition is the part out of step.

## Decision

1. **The LLM may propose a reading no engine produced** — a conjecture — when it judges the engines collectively wrong. This is realized as an **L3 composed reading under ADR-0014**, not a new mechanism: it carries character provenance, is labeled `machine_composed`, and is subject to the ADR-0014 protected-class gate.

2. **v1 posture — LLM-composed readings route to Human Review before release.** This is *stricter* than ADR-0014's generic "L1–L3 publish flagged": for the LLM composer specifically, no LLM-authored reading ships (flagged or otherwise) without passing Human Review (stage 9) while the approach is being calibrated. Reason (SCALE-02 temporary constraint, named in the design): there is no LLM-conjecture calibration data yet, so no trustworthy confidence bar exists to auto-accept — or even to flag-and-ship — an LLM conjecture. We need reviewer-adjudicated outcomes first.

3. **Guardrails (the load-bearing part of arch6, preserved):**
   - **Never auto-canonical** — v1: every LLM conjecture clears Human Review.
   - **Never trains** — an LLM conjecture never updates Engine Reliability Scoring (stage 6) on its own; unchanged from arch6.
   - **Marked in provenance** — recorded as an LLM conjecture (ADR-0014 character provenance + `machine_composed`), auditable, never merged into "the engines said."

4. **Revisit trigger (v2).** Once enough reviewer-adjudicated LLM-conjecture outcomes exist to calibrate a false-correction rate per stratum (per the ADR-0014 / ADR-0015 stratified thresholds), evaluate relaxing the v1 human-review-all posture toward ADR-0014's flagged / stratified-auto-accept path. Until that data exists, human-review-all stands. Build-to-measure, not guess.

## Consequences

- arch6's "never creates unattested canonical text" is **amended** to "may propose unattested readings via the ADR-0014 L3 path; never canonical without human ratification (v1)." arch6's other constraints stand (LLM-resolved never trains; calibration ledger; vision default off).
- This ADR **specializes**, does not supersede, ADR-0014: it adds the LLM as an L3 composer and sets a stricter v1 review posture for that composer.
- LLM Review (stage 7) feeds Human Review (stage 9); the Human Review → LLM Review calibration loop (the `SHARED-LEXICON.md` feedback-loops note) is where the v2 calibration data accrues.
- Human Review throughput is the binding bottleneck (single reviewer, per the locked arch); routing all LLM conjectures through review is consistent with that bottleneck being exactly where calibration data is generated.
- Schema and field details (the LLM-conjecture provenance marker) are implementation, owned by the build spec / arch3 pass, not this ADR.

## Alternatives considered

- **Keep arch6's blanket prohibition.** Rejected: forfeits the LLM's most useful case (all engines wrong together) and contradicts ADR-0014's existing L3 path.
- **Adopt ADR-0014's "L3 publishes flagged" directly for the LLM composer.** Rejected for v1: ships LLM-authored text on a flag with no per-token human check before any calibration data exists. The stricter human-review-all posture is the data-gathering phase that earns the right to relax later.
- **Let the LLM auto-accept its conjectures under a confidence bar now.** Rejected: no measured false-correction rate exists yet to set the bar; this is precisely the v2 decision the revisit trigger defers.
