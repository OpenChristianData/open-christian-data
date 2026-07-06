# Build Roadmap — 2026-06-05

> **For current NSH pipeline state, read `docs/NSH_PROJECT_STATE.md` (the anchor doc) first.** This
> file is the **strategic framing** for the gold-free corrector finish (gold-as-validator, surrogate
> measurement, sequencing rationale) — useful for *why* the approach is shaped this way. For *what is
> built* use the canonical tracker `docs/BUILD_PLAN_gold_free_corrector.md` §0; for current numbers,
> `docs/JE_SURROGATE_FINDINGS.md`.

**Status: PROPOSAL / living roadmap.** Reframes the pipeline finish around one idea:
gold is a *validator*, not a *prerequisite*. Most research-attested correction is
unsupervised and can run before any human adjudication; the surrogate text (Jewish
Encyclopedia 1906) measures whether it worked. American English; relative paths.

Companion docs: `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md` (the research this rests on),
`docs/PIPELINE_BUILD_STATE.md` (what is built — the reconciler is an unweighted stub),
`docs/MEASUREMENT_REFERENCE_OPTIONS.md` (the gold gate), `docs/JE_SURROGATE_FINDINGS.md`
(surrogate oracle, when produced).

## Decision brief

- The reconciler runs in degraded mode: every signal weight is 0.0, nothing is
  auto-chosen, everything routes to human review. That is policy (the tuning embargo),
  not necessity.
- The research's highest-ROI techniques are **gold-free**: character-column voting
  (Reul 2018, ~46-53% single-engine error reduction), lexicality rescoring, in-corpus
  LM rescoring, and active-learning sample selection (+16%). We built the alignment and
  the gold-gated matrix and skipped the free middle.
- Build that gold-free corrector **before** the human gate. Use the surrogate to measure
  its false-correction rate. Human adjudication then targets the ambiguous residue, not
  the easy 77%.
- One rule amendment is required to unlock character-synthesis: attestation moves from
  whole-word to **per-character with provenance** (see §4). Evidence-gated by the surrogate.

## §1. The frame

Three correctors, in the order they switch on:

1. **Gold-free unsupervised stack** (this roadmap's new work) — character-column voting +
   lexicality + in-corpus LM. Auto-resolves the obvious. Validated, not gated, by the surrogate.
2. **Trained matrix** — confidence-weighted voting; needs the human gold set.
3. **arch6 LLM-in-loop** — queue-shrinker; needs gold + validation.

The human gold set (~300-500 adjudications) sits between 1 and 2. The gold-free stack
shrinks what the human must adjudicate and sharpens the sample (active learning).

## §2. Gold-free corrector stack (the new work — no human gold required)

Slots onto the existing WCT (which already does confusion-weighted character alignment for
slot membership; it stops before voting). Phases:

- **P1 — Character-column voting.** Align candidate readings within a position character by
  character (reuse the existing confusion costs), vote per column, compute an agreement
  score. Impossible-character filter: a non-alphabetic glyph in an alphabetic context
  (e.g. `▲`) is rejectable; prefer the alphabetic plurality. Output: a voted reading + a
  per-character provenance trail (which engines attested each character).
- **P2 — Lexicality rescore.** Score the voted reading against a domain lexicon built
  gold-free from high-agreement consensus words + public-domain dictionaries + the
  existing confusion models (`build/lib/ocr_error_models/*.yaml`). Real word = corroboration.
- **P3 — In-corpus LM rescore.** A cheap char/word n-gram model trained on the corpus's own
  high-confidence consensus text (+ similar public-domain text) scores candidate plausibility.
  No gold; the lightweight, hallucination-safe cousin of LLM post-correction.
- **P4 — Decision policy.** Auto-accept when (voted reading matches an attested whole-word
  AND scores high) OR (character-synthesized, every char attested, lexicality + LM high, AND
  the §4 amendment is adopted). Everything else -> review queue. Latin body text first;
  Greek/Hebrew stay in review (alignment noise — research gap #1).
- **P5 — Active-learning selection.** Rank the review residue by disagreement/uncertainty so
  the human gold sample is drawn from the most informative positions (+16%, Reul 2018).

**Risk discipline (the embargo's valid core):** auto-apply only where evidence is
overwhelming; false correction (damaging a correct word) is worse than an uncorrected error.
Every auto-accept tier is kept only if its surrogate-measured false-correction rate clears a
threshold set per region class.

## §3. Surrogate validation (the measurement that replaces the gate for the gold-free stack)

Run the gold-free stack on the Jewish Encyclopedia surrogate (diplomatic text + facsimiles,
same edition — non-circular, no edition offset). Produce per-tier false-correction rates and
auto-accept coverage. Keep the tiers that pass; demote the rest to review. This is the
"test with and without gold" path: the surrogate gives a real number with zero SH human time.

## §4. Rule amendment — per-character attestation (ADR-0014, accepted as model; thresholds evidence-gated)

Current locked rule: canonical text may only be selected from attested readings or human input.

Proposed: canonical text may be (a) an attested whole-word reading, (b) a **character-
synthesized** reading where every character traces to >=1 engine attestation, tagged with
per-character provenance and `synthesized: true`, or (c) human input. Synthesized tokens
carry a surrogate-measured false-correction rate and are never published without their
provenance trail.

Rationale: this refines attestation from whole-word to per-character — *more* granular
provenance, not less — and unlocks the ~half of errors where every engine fumbled a
different character. Adopt only after the surrogate shows the synthesized-tier
false-correction rate is acceptable.

## §5. The gold gate (unchanged, but smaller)

~300-500 human adjudications, drawn (via P5) from the ambiguous residue. Load-bearing twice:
non-circular measurement reference AND training labels for the matrix. Unlocks the
confidence-weighted layer and arch6. Reviewer UI + `scan_crop.py` (gold-free, buildable now)
make this fast and are reused for the surrogate.

## §6. Gold-gated layer (after §5)

Confidence-weighted character voting (the +16% on P1); matrix cell promotion (`calibration.py`);
arch6 LLM-in-loop wiring; real non-circular M2/M3; the keep-matrix decision.

## §7. End-to-end terminus

Page->article->`data/` assembler (confirm/build) -> S6 publish (currently dry-run) -> slim
public text + private audit -> scale to vols 3-13.

## §8. Sequencing — gold-free vs gated

| Work | Gold-free? | Depends on | Build now? |
|---|---|---|---|
| Complete panel vol 1+2 | yes | — | in flight |
| Surrogate (JE) acquire + run | brings own gold | panel tooling | yes |
| P1 character-column voting | yes | WCT | yes (lead) |
| P2 lexicality rescore | yes | P1 + lexicon inventory | yes |
| P3 in-corpus LM rescore | yes | P1 | yes |
| P4 decision policy + §4 amendment | yes (validate via surrogate) | P1-P3 + surrogate | yes |
| P5 active-learning selection | yes | P1 + queue | yes |
| Reviewer UI + scan_crop.py | yes | — | yes |
| Human gold set | — | reviewer UI + P5 | gate |
| Weighted matrix / arch6 | no | gold | after gate |
| Assembler / S6 publish | no | corrected text | after gate |

## §9. How the work is dispatched

Codex-driven design (CODEX-05: Codex designs/implements, Claude reviews + commits). Lead
design prompt: the gold-free corrector stack (P1-P5) as one architecture, grounded in the
research and the existing WCT/reconciler code. Per-component build prompts are authored
*after* the design lands and defines their interfaces — not before.
