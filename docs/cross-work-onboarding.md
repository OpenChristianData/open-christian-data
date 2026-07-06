# Cross-work onboarding policy

This policy covers transfer of matrix priors when a second Open Christian Data
work onboards. The planned tool is `build/tools/onboard_cross_work_priors.py`.
Implementation is deferred until the second-work activation trigger.

## Purpose

Cross-work onboarding lets a new work reuse carefully approved matrix priors
from an existing work without pretending those priors are observations in the
target work. It accelerates early calibration while preserving the distinction
between transferred belief and observed evidence.

## Required inputs

- A source matrix snapshot and its content hash.
- A target work identifier and target policy bundle.
- A human-approval decision-event.
- A pinned evaluation-manifest hash on that approval event.
- Cross-work linkage through `canonical-identity-map-v1`, with token ids scoped
  per volume.

> Note: `canonical-identity-map-v1` does not yet exist on disk as a schema. It
> is the documented future input. Item 13 implementation is deferred to its
> activation trigger: a second work onboards.

## Approval gate

No transfer may run without explicit human approval. The approval must be a
decision-event and must pin the evaluation-manifest hash used to justify the
transfer. Missing approval fails with `missing_approval`. Approval without a
manifest hash fails with `approval_missing_manifest_hash`.

## Prior strength cap

Transferred prior strength has a hard cap of `k=5`, regardless of source
confidence. If a source proposes `k>5`, the transfer clamps it to 5 and records
`k_clamped_to_5` in the output.

## Priors only

Transferred values apply as priors only. They never increment observed correct
or incorrect counts. Target observed counts must remain entirely sourced from
target-work observations.

## Fail-closed mismatch rules

The transfer must fail closed when any of these differ between source and
target:

- family
- region_class
- schema version
- transcription policy

## Planned outputs

The deferred tool will write:

- `reports/onboarding/cross_work_prior_transfer_<target>.json`
- `reports/onboarding/cross_work_prior_transfer_<target>.md`
