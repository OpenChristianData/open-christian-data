# ADR-0021: Ledger import semantics for machine-released corrections

**Status:** Accepted (2026-07-04). Specializes ADR-0014 into the decision ledger; touches
`decision-event-v1`. Ratified by the maintainer before the first live ledger mint (batch 02).

## Context

The corrector emits `corrected-page` sidecars whose accepted positions (`chosen_action:
release_accepted`) must be imported into the append-only, hash-chained decision ledger
(`decision-event-v1`) so the TEI can be materialized from the ledger (the reviewer architecture's
authority order: ledger → TEI → HF). For the first corpus (Jewish Encyclopedia vol_02) this is
44,160 events — the first live ledger the project mints, and append-only means its semantics are
permanent.

`decision-event-v1`'s thirteen `event_type` values are human-review verbs (`choose_attestation`,
`amend_text`, `mark_gold`, …) plus system workflow events (`auto_rebind_system`, …). None describes
a machine corrector releasing a reading. The corrector's output includes both `observed` readings
(text equals an engine attestation) and `machine_composed` readings (L1+ per ADR-0014, text
differing from every attestation). ADR-0014 admits composed readings with character provenance and
derivation levels; it does not say how they enter the ledger.

## Decision

Add **one new event type, `machine_release`**, to `decision-event-v1`
(`event_category: authority_decision`), used for every corrector-released position regardless of
`origin_kind` — the act recorded is "the corrector released this reading," and the observed/composed
distinction is carried in the payload, not the verb. Required semantics:

- `actor_id: "system:corrector"` (mirroring the schema's existing `system:*` actors).
- `status_authority: "consensus"` (the deterministic corrector; `llm_resolved` if a future corrector
  run uses the LLM path — the field records which machine authority, never `reviewed`).
- `measurement_eligible: false` — always. The accuracy harness measures *human-confirmed* readings;
  a machine release is the thing being measured, and counting it would measure the corrector
  against itself.
- `evidence_seen` carries the WCT page sha, the chosen candidate text, and the decision-policy
  input id (the thresholds file), so replay validation has the context the architecture requires
  of authority events.
- `decision_extras_carried` holds `origin_kind`, `derivation_method`, `chosen_action`, and
  `chosen_reading_index` — the lossless round-trip payload: folding the ledger must reproduce the
  corrected page exactly.
- Event ids reuse the deterministic `decision_event_id` already minted on each corrected position;
  importer idempotency dedupes on them.
- Human review later supersedes a `machine_release` through the existing supersession machinery
  (`supersedes_event_id`); a human event, not an edit to the machine event, changes a reading's
  authority.

Schema change ships with the importer in one batch: enum addition + a conditional required-fields
branch for `machine_release`, regenerated enums, and tests that pin the mapping.

## Consequences

**Positive:** ledger queries stay honest — "human decisions" is an event-type filter, never an
actor-field heuristic; the ADR-0014 public claim (machine-composed is never presented as attested
or reviewed) is structural in the ledger; the round-trip guarantee makes `corrected-page` files
disposable per the reviewer architecture's plane split.

**Negative:** a schema change to a contract already under adversarial review (small, additive, and
made before any live ledger exists — the cheapest moment it will ever be); every future consumer
must handle a fourteenth event type.

## Alternatives considered

- **Reuse `choose_attestation` (observed) + `amend_text` (composed) with `actor_id:
  system:corrector`.** Rejected: no schema change, but it overloads human verbs — every future
  consumer must join event_type with actor_id to avoid misreading 44,160 machine events as human
  decisions, and the append-only record would carry that ambiguity forever. Workable fallback if
  schema stability is judged to outweigh semantic clarity at ratification time.
- **A third `event_category` for machine authority.** Rejected: category answers "does this set
  reading status?" (it does); multiplying categories fragments the fold logic for no added honesty.
- **Import nothing; materialize TEI directly from corrected pages.** Rejected: re-creates the
  parallel-authority problem the plane split exists to prevent (round-1 finding 4 of the reviewer
  architecture review).
