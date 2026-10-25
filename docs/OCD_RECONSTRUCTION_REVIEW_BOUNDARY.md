# OCD reconstruction and review boundary

**Status:** project-boundary clarification, updated 2026-08-01. This document
does not authorize acceptance, schema migration, publication, or migration of
content-addressed artifact contracts.

## The project purpose

The project is **Open Christian Data (OCD)**. OCD's purpose is to preserve and
publish trustworthy Christian texts and resources with their work identity,
edition identity, structure, provenance, rights, and source history intact.
The project owns the canonical contracts and the authority to accept a faithful
master or publish a declared projection.

The source-to-IR reconstruction subsystem is not the project name. It is the
internal machinery that turns retained sources into candidate edition
reconstructions. Its output is evidence for OCD review until an OCD acceptance
decision says otherwise.

The plain-English operating guide for that route is
[`docs/OCD_SOURCE_TO_IR_PIPELINE.md`](OCD_SOURCE_TO_IR_PIPELINE.md).

## The three layers

| Layer | Role | Authority |
|---|---|---|
| OCD | Project, contracts, source history, rights, canonical data, accepted masters, and publication | Project authority |
| OCD source-to-IR reconstruction | Internal builders, semantic profiles, candidate packages, and verification contracts | Candidate/evidence machinery only |
| CVW | Read-only Corpus Verification Workbench for a human to inspect OCD artifacts and candidate evidence | Review surface; never acceptance or publication |

The current implementation locations follow this boundary:

- `ocd_kernel/reconstruction/` contains only the small candidate contract and
  schema. Direct source-to-TEI routes live under `build/tei/`, and
  `build/tools/reconstruct_candidate.py` is their generic Windows-local runner.
- `reports/_reconstruction/` contains regenerable, ignored candidate and review
  evidence. Its contents are not automatically OCD masters.
- `cvw_app/` contains the human-facing review application. It consumes OCD
  contracts and artifacts read-only.
- `viewer/` contains the existing standalone TEI verification viewer.
- `data/`, `ir/`, accepted package repositories, and publication outputs retain
  their existing OCD-specific authority rules.

## Naming and migration rule

Legacy `ocd-wayfinder-*` contract names, package digests, and retained report
paths are part of the identity of already-generated evidence. They must not be
rewritten in place merely to make the project boundary clearer. New code and
human-facing surfaces should use OCD source-to-IR or CVW language; a future
contract-family migration requires its own receipts and compatibility plan.

If the reconstruction subsystem later needs a different permanent name, that is
a separately reviewable compatibility and artifact-migration decision. It is not
an incidental cleanup task.

## Visual verification rule

Human review should happen in CVW using an explicitly labelled candidate-evidence
snapshot. The snapshot must:

1. identify OCD as the project and CVW as the surface;
2. state that the material is not accepted;
3. show a readable presentation derived from the retained package;
4. expose the exact TEI member as text, without executing source markup;
5. show rights, identity, source-binding, and unresolved-case status; and
6. leave source files, candidate packages, accepted masters, and publication state
   unchanged.

The current Windows review entry point is `cvw_app/launch_windows.py`. It
preflights declared work/acquisition bindings plus explicit caller-selected
candidate directories before passing the admitted application to the loopback service;
the legacy `cvw_app.review_service` module entry delegates to that same
launcher. CVW serves only Library, Read, and side-by-side Compare. It does not
persist review state or accept candidates.

See [declared review admission](RECONSTRUCTION_CONTRACT.md#declared-review-admission)
for explicit work cohorts, exact source-member matching and missing-handoff
handling. Historical catalog review requires `--catalog PATH`; no fallback is
inferred from a missing declaration.
