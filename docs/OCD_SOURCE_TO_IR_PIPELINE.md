# Retained source to faithful TEI candidate

> **Target continuation (2026-08-31):** This remains the current reconstruction
> route. The approved target for stable work/state sidecars, accepted edition
> masters, generated catalog views, and TEI-to-Hugging-Face publication is
> `docs/OCD_LIBRARY_PIPELINE_SPEC.md`, with its proposed file layout in
> `docs/OCD_LIBRARY_PIPELINE_TOPOLOGY.md`. Approval of that target does not by
> itself accept existing candidates or change current reconstruction evidence.

**Status:** Current operational route, 2026-08-26. The historical filename is
retained so existing navigation continues to work; reconstruction now stops at a
reviewed TEI candidate rather than writing canonical IR.

## Route

```text
retained source bytes
  -> source manifest verifies exact authorities
  -> source-specific converter reconstructs content.tei.xml
  -> candidate package records provenance and source accountability
  -> independent oracle validates TEI, fidelity, and declared source coverage
  -> human spot-checks representative/risky evidence and decides consequential questions
```

Accepted TEI will eventually feed a separate Hugging Face publication pipeline.
That downstream route is not implemented here and is not part of the present
work.

## Per-text inputs

Each maintained route has only the inputs needed to protect fidelity:

- retained source files;
- a source manifest with exact hashes and implementation bindings;
- a reconstruction profile and candidate-package schema;
- a TEI validation schema and source-specific validation policy;
- a direct converter under `build/tei/`;
- a producer-independent oracle under `build/tei/`; and
- focused fixtures and tests for known fidelity risks.

Metadata remains blank or unresolved when the retained evidence does not justify
it. Source-specific rules—such as trusting Fisher's title page—belong in the
route and its tests, not in a general workflow framework.

The implementation stays as small as the specified route requires: reuse the
existing reconstruction seam, and add no workflow service, state machine,
sampling framework, registry, queue, database, ledger, replay platform, or
speculative abstraction for agent coordination or hypothetical future needs.

## Generate one candidate on Windows

Choose an empty destination outside the repository, `raw`, `data`, `ir`,
`reports`, `exports`, acceptance, and publication storage. Then run:

```powershell
py -3 build/tools/reconstruct_candidate.py `
  --manifest PATH\TO\source-manifest.json `
  --destination "C:\Scratch\Open Christian Data\ocd-candidate" `
  --repository-root "."
```

The result contains `package/` plus `validation.json`. A successful run means the
declared deterministic checks passed. It does not mean that a human accepted the
text or that it is publishable. To prove one candidate identity, regenerate the
same pinned inputs once in a fresh process into an empty location and compare the
complete package path set and per-file bytes; this second clean run is not a
durable replay system.

## Review and state

Library sidecars own work identity, acquisition, state and acceptance facts;
generated views summarize them. Validation, focused human spot checks, human
acceptance and publication remain distinct. Historical WorkCatalog is retained
for explicitly selected review and diagnostic use.

CVW is the Windows-only visual surface for Library, Read, and unlinked
side-by-side Compare. It reads declared work/acquisition bindings and caller-selected
validated candidate directories through [declared review admission](RECONSTRUCTION_CONTRACT.md#declared-review-admission).
Validation and source accounting happen before CVW; human spot
checks happen in CVW or another read-only viewer. Decisions remain
caller-owned.

## What is not in the route

The reconstruction module does not own the former wave/declaration campaign
framework, durable replay platform, special candidate store, or an acceptance
registry. Historical campaign evidence remains archived and restorable. Current
work/acquisition declarations, candidate evidence, and the separate downstream
acceptance pipeline retain the authorities described above; they are not removed
by this module boundary.

The route also does not modify canonical `data/` or `ir/`, accept candidates,
publish to Hugging Face, stage or commit Git changes, or alter retained sources.

For the supported authority and publication boundaries, see the
[library pipeline specification](OCD_LIBRARY_PIPELINE_SPEC.md). Exploratory
comparisons and dated campaign research remain maintainer background evidence.
