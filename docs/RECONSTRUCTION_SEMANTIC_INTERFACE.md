# Reconstruction interface

**Status:** Current maintained interface, 2026-08-26.

**Governing contract:** `docs/RECONSTRUCTION_CONTRACT.md`

## One small seam

`ocd_kernel.reconstruction` exposes the complete public reconstruction seam:

```python
from ocd_kernel.reconstruction import (
    CandidateDecision,
    CandidatePackage,
    ReviewView,
    SourceManifest,
    ValidationReport,
    prepare_review,
    reconstruct,
    validate,
)
```

### Types

| Type | Responsibility |
| --- | --- |
| `SourceManifest` | Loads and verifies the retained source, converter, schema, profile, and independent-validator authority bindings. |
| `CandidatePackage` | Provides a read-only handle to one deterministic, sealed, nonaccepted TEI candidate package. |
| `ValidationReport` | Binds the independent validation result and its attestation to the source manifest and candidate hashes. |
| `ReviewView` | Provides the small manifest/candidate handoff retained for caller-owned review decisions. It does not choose a retained source member. |
| `CandidateDecision` | Records a caller-owned human disposition bound to the exact candidate and validation report. |

### Operations

```python
candidate = reconstruct(source_manifest, destination, converter)
validation = validate(source_manifest, candidate, oracle)
review = prepare_review(source_manifest, candidate, validation)
```

- `reconstruct` verifies authority bindings and writes exactly one nonaccepted
  candidate to an explicit empty destination outside the repository and governed
  storage.
- `validate` runs the separately bound oracle and returns a deterministic report.
- `prepare_review` verifies the bindings again and returns a read-only review
  shape. Callers explicitly resolve a retained source with
  `review.source_manifest.authority_path(name)`; the review has no default or
  inferred source path.

The seam does not accept a candidate, write canonical data or IR, retain a durable
candidate root, publish, or manage workflow state.

For every new or reopened route, the validator independently reads the retained
source and candidate without reusing converter traversal or mapping helpers. It
supplies closed `MechanicalFacts` to the internal
`verify_mechanical_facts(...)` assembler only after source-specific fidelity,
mutation, determinism, map, and source/work identity checks have passed.
Historical catalog checks remain required where the selected source contract
explicitly binds them. The assembler is
deliberately not part of this package's public interface.

## Candidate handoff

The maintained command is:

```powershell
py -3 build/tools/reconstruct_candidate.py `
  --manifest PATH\TO\source-manifest.json `
  --destination PATH\TO\EMPTY-CANDIDATE-DIRECTORY `
  --repository-root "."
```

The runner resolves the converter and validator declared by the source manifest,
calls the three-operation seam, and creates this handoff:

```text
candidate-directory/
├── package/
│   ├── content.tei.xml
│   ├── source-accountability.json
│   ├── provenance.json
│   ├── unresolved.jsonl
│   ├── README.source.md
│   └── manifest.json
└── validation.json
```

The package and sidecar remain nonaccepted review evidence. Candidate directories
are caller-selected and regenerable; they are not a second library or state store.

## Human review boundary

Work/acquisition sidecars and candidate-bound source declarations supply default
CVW identities; state and acceptance have separate sidecar authorities. See
[declared review admission](RECONSTRUCTION_CONTRACT.md#declared-review-admission).
Explicit candidate directories provide Windows-only Library, Read and Compare.
Historical catalog review requires explicit `--catalog PATH`.
Missing or mismatched validation fails closed.
CVW does not infer acceptance or correspondence and does not persist decisions.
CVW reads the verified `SourceManifest` directly to enumerate every
`primary-source` authority in deterministic manifest order. It defaults only a
sole source member; multiple members remain explicitly unselected until the
reviewer chooses one. Every offered member remains bound to its exact manifest
name, repository-relative path, byte count, and SHA-256.

A human may create a `CandidateDecision` only after reviewing the exact
`ReviewView`. Human attention is targeted at representative or risky evidence and
consequential questions; routine per-work sign-off is not a prerequisite for
technical generation, validation, or independent review. What happens to an
accepted TEI after that belongs to the separate maintained library/release
pipeline; see the [command guide](LIBRARY_CONSUMER_CUTOVER.md).

## Deliberate omissions

There are no compatibility adapters for the retired wave, declaration,
persistence, closure, durable replay-platform, shared-checkout, sealed-request,
receipt, campaign, or acceptance-store APIs. A single second clean run in a
fresh process may prove deterministic output, but it is not a replay API. If a
future requirement cannot show that it protects faithful TEI reconstruction or
review, it does not belong in this module.
