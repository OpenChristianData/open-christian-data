# ADR-0014: Machine-composed readings past the attestation gate

**Status:** Accepted (2026-06-05) — model accepted; per-level publication thresholds deferred to surrogate measurement. Revised 2026-06-05 after adversarial review ([REVIEW_0014_0015_adversarial.md](REVIEW_0014_0015_adversarial.md)): schema-first preconditions, public labeling, the protected-class gate, stratified thresholds, and a supersession contract were added.

## Context

Released canonical text is constrained by the **no-unattested-words attestation gate** — a ship-blocking precleaning layer (L9) whose falsifiable check is "exactly zero unattested released tokens" (`plans/2026-05-26-precleaning-architecture-comparison.md`, reinforced by the arch6 LLM-in-loop dispatch invariants). This ADR is the first to record that gate as an ADR; it does so to amend one part of it.

The arch3 output schema already distinguishes a token whose canonical text equals a chosen attestation (`source_raw_origin: observed`) from one whose canonical text differs from every attestation (`reconstructed`) — see `plans/2026-05-27-arch3-output-schema-synthesis.md`. Today the gate admits a `reconstructed` token by exactly one route: a human typing it via `amend_text` (archC integration lock, matrix-training-eligibility item 2).

A machine can reach a correct reading that no single engine produced whole — character-column voting assembles `Abelard` from `Abelarb` + `▲belard`, where each character is independently engine-attested. The OCR-voting literature (Reul et al. 2018) puts this class at roughly 46–53% of single-engine error, recoverable without human gold. The current gate forces every such case to the single human reviewer, who is the binding bootstrap bottleneck.

## Decision

Extend the `reconstructed` source-origin from human-only to **machine-composed**. A *composed reading* (per `SHARED-LEXICON.md`) may pass the attestation gate when it carries **character provenance** — a per-character source (engine family, confusion rule, lexicon, language model, or human) — and a derivation level:

- **L0** attested whole-word (`observed`)
- **L1** composed, every character engine-attested
- **L2** composed, includes confusion+lexicon-corrected characters (small edit distance to a known word)
- **L3** composed, includes language-model/context-proposed characters

**Schema preconditions (not a reuse).** A composed reading is not admitted by reusing the `reconstructed` slot alone — that enum (`observed | unavailable | reconstructed`) cannot tell a machine-composed token from a human-amended one. The decision is that the canonical schema must, before this gate change is live, carry three discriminators: a derivation level, an origin kind that distinguishes machine-composed from human-amended, and per-character provenance (one source per grapheme). The exact field names, enum values, and validator checks are implementation and live in the build spec (`docs/BUILD_SPEC_corrector_code_from_review.md`). The gate's falsifiable check becomes "zero released tokens with derivation level ≥ L1 lacking complete, well-formed character provenance" — testable only once those fields exist.

**Public claim.** L1–L3 readings are labeled `machine_composed`, never "attested". A composed word is individually character-traceable yet may never have been witnessed whole by any source; the released record must expose the whole-token status beside the character provenance, so a reader can tell "a source printed this word" apart from "this word was assembled from character evidence".

**Publication policy.** Only L0 (attested whole-word) and human-reviewed readings publish unflagged. L1–L3 publish flagged until their false-correction rate is certified below threshold — and that threshold is *stratified*, not a single per-level aggregate (see ADR-0015): auto-accept requires the rate to clear within each `(level, method, token-class, script, typography, engine-mix)` stratum that has enough measured support, with under-powered or above-threshold strata routed to flagged output or review. The model is accepted now; the publish-unflagged thresholds wait on Jewish Encyclopedia surrogate data.

**Protected-class gate.** Protected classes (proper names, numbers, dates, Scripture references, Greek, Hebrew) route to human review regardless of level — a gate precondition, not a hope. Unflagged L2/L3 is banned for any protected class whose detector is missing, unmeasured, or below threshold. Greek and Hebrew are detected today by script; proper names, numbers, dates, and Scripture references are not yet detected and must be before their tokens can be measured or published unflagged.

**Recall contract.** A composed reading is a canonical decision, not an immutable OCR rendering, so it needs its own supersession path parallel to ADR-0011 for renderings: a published composed token that later changes must be traceable to the decision and policy that produced it, and must trigger a release note. The supersession metadata fields are implementation and live in the build spec (`docs/BUILD_SPEC_corrector_code_from_review.md`).

A language or vision model may rank, flag, or verify candidates; it authors canonical characters only via the tagged, provenance-tracked L3 path.

## Consequences

**Positive**
- Recovers roughly half the single-engine error without human gold, before any review time is spent.
- Keeps every released character traceable to evidence — but note this is per-character, not whole-word, witness: a composed word can be character-traceable while no source witnessed it whole (hence the `machine_composed` public label above).
- Turns the strict-versus-permissive choice into a measured number rather than a doctrine.
- Protected classes (proper names, numbers, dates, Scripture references, Greek, Hebrew) route to human review regardless of level.

**Negative**
- The gate's falsifiable check changes from "zero unattested tokens" to "zero tokens lacking character provenance" — a new invariant to enforce in code and tests, and it cannot be tested until the schema fields above exist.
- Adds derivation-level, origin-kind, and per-character-provenance fields to the canonical schema; reusing `reconstructed` alone does not satisfy the gate.
- Makes the real-word-error metric and *stratified* surrogate measurement mandatory, not optional — a single per-level aggregate can pass while a protected token-class fails within it.
- The composed-reading emitter, the four missing protected-class detectors, and the supersession path do not exist yet; the publication policy stays flagged-only until they do.
- A composed-but-valid-wrong token (a real-word error) is the residual danger; it must be measured explicitly, never assumed away.

## Alternatives considered

- **Keep the human-only route to `reconstructed`.** Rejected: forfeits the largest gold-free accuracy gain and forces every fumbled-character case onto the single human reviewer.
- **Overload "attested" to character granularity.** Rejected per the lexicon's one-term-one-concept rule; "composed reading" and "character provenance" were coined instead.
- **Allow free language-model correction without levels or provenance.** Rejected: reintroduces genuinely unattested text and the real-word-error injection the surrogate exists to bound.
