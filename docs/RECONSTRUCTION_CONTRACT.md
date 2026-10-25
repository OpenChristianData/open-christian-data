# Faithful TEI reconstruction contract

**Status:** Current design of record for the maintained Windows reconstruction
route, 2026-08-26.

## Product boundary

Open Christian Data reconstruction has one job:

```text
retained source
  -> faithful TEI candidate
  -> validation and source accounting
  -> focused human spot checks and consequential decisions
```

Reconstruction produces a nonaccepted TEI candidate. The separate library
pipeline handles acceptance, installation and offline release assembly; see the
[command guide](LIBRARY_CONSUMER_CUTOVER.md). To contribute a text, use the
[maintained workflow](TEXT_CONTRIBUTIONS.md).

## Required properties

A reconstruction is useful only when it protects fidelity:

- Retained source bytes and their hashes are explicit.
- The TEI candidate is deterministic for the same source and implementation.
- The candidate preserves wording, order, meaningful structure, metadata, notes,
  and other source-supplied content within its declared scope.
- Source-accountability evidence detects omissions, duplications, inventions, and
  wrong-source use.
- Whole-scope mechanical checks and producer-independent verification cover every
  declared source member; human attention can focus on representative or risky
  evidence and questions that the evidence cannot decide.
- TEI is checked against the declared schema and source-specific validation
  policy.
- Provenance binds the source manifest, converter, validator, and candidate.
- Candidate generation remains separate from human acceptance.

Source-specific parsers, profiles, or independent oracles are justified only when
they protect one of these properties. Existing infrastructure, historical
acceptance, or prior effort is not a retention requirement.

The implementation uses the smallest concepts and code needed for these
properties, reusing existing seams. It does not add workflow coordination,
sampling, registry, queue, database, ledger, replay-platform, or speculative
future machinery.

## Plain-English rule for future parsers

A converter must not grade its own homework.

For every new or reopened source-to-TEI route:

1. List what is actually present in the retained source, including wording,
   order, element text and tails, meaningful attributes, notes, tables, lists,
   images and captions, comments, processing instructions, and document-shell
   material when the source contains them.
2. Convert those source features into TEI with source-specific code.
3. Have a separate reader independently make its own source and candidate
   inventories. It must not reuse the converter's traversal, mapping, or
   completeness helpers.
4. Make every observed feature either preserved or explicitly disposed. An
   unknown or unsupported feature fails closed instead of disappearing.
5. Use source-observed edge cases to choose mutation tests, and prove a second
   clean process produces the same complete candidate bytes.
6. Let the independent reader supply closed `MechanicalFacts` to
   `verify_mechanical_facts(...)` only for final mechanical-attestation
   assembly. Interpretation, fidelity policy, rejection behavior, maps, and
   source/work identity checks remain source-local. Existing historical catalog
   checks remain required where the selected source contract explicitly binds them.

This sequence is the golden path for future tickets. It is a checklist and
ownership boundary, not a new parser framework or base class. Shared machinery
owns packaging, destination safety, integrity, and final attestation. The
source-local converter and independent reader own textual meaning and fidelity.
Already accepted routes are not re-pinned solely to adopt the checklist.

## Public interface

The maintained Python interface is `ocd_kernel.reconstruction`:

- data types: `SourceManifest`, `CandidatePackage`, `ValidationReport`,
  `ReviewView`, and `CandidateDecision`;
- operations: `reconstruct`, `validate`, and `prepare_review`.

`build/tools/reconstruct_candidate.py` is the maintained Windows command-line
entry point for producing one validated, nonaccepted candidate in a
caller-selected directory outside the repository and governed storage.

New runner handoffs include advisory `text-quality.json` beside `package/` and
`validation.json`. The validation sidecar's optional `text_quality_sha256` binds
that report without changing the oracle's `report_sha256`. Review loaders verify
the screen's exact source/candidate input bindings; historical handoffs remain
valid without it. Follow the [text-quality procedure](SOURCE_PREFLIGHT.md#advisory-text-observations)
for findings, unsupported readers, and handoff completion criteria.

The candidate package is immutable review evidence. It is not an accepted master,
canonical data, canonical IR, publication state, or a durable state store.

## State and review

Work, acquisition, state, and acceptance sidecars own their respective facts.
Generated library views summarize those authorities; they do not own routes or
turn a generated candidate into an accepted text. Historical WorkCatalog remains
an explicitly selected diagnostic/review input until its dependencies retire.

Corpus Verification Workbench (CVW) is a Windows-only, read-only viewer with
Library, Read, and side-by-side Compare. It consumes declared work/acquisition
identities and explicit validated candidate directories. CVW does not reconstruct, validate, accept,
publish, store decisions, or maintain a second registry. Routine technical
generation and validation do not wait for a human disposition.

### Declared review admission

Ordinary `cvw_app/launch_windows.py` launch and materialized runtimes use declared
library admission. `--declared-library` selects that default explicitly.
Historical review requires an explicit `--catalog PATH`; missing declarations
never trigger catalog fallback.

The candidate-bound SourceManifest names either one `work_id` or a nonempty,
unique, ordered `work_ids` cohort. A primary authority may restrict membership
with its own `work_ids`, which must be a nonempty subset of that cohort. Every
declared work must have primary members matching exactly one declared
acquisition by path, byte count, and SHA-256. Duplicate or competing identities,
missing work/acquisition sidecars, and ambiguous matches fail closed. Candidate
and validation bindings remain enforced by the common review application.

An existing candidate without this handoff is an integration gap, not evidence
of defective TEI. Preserve it unchanged and record the missing identity/member
association in its ticket. Rebinding a manifest requires fresh dependent
candidate/validation evidence under the source-to-TEI contract; do not edit a
package or generated legacy JSON to force admission. Historical review can
continue only through the explicitly selected catalog route and its own verified
bindings. Neither route establishes complete review, acceptance or publication.

For visual review, CVW enumerates every manifest-bound `primary-source`
authority in deterministic manifest order and verifies its recorded path, byte
count, and SHA-256 before display. A single-source route may open that sole
authority by default. A multi-source route requires the reviewer to choose a
specific authority; CVW does not guess which member is the text to prefer.
The reconstruction `ReviewView` itself makes no source selection; callers
resolve a named, verified authority through its `source_manifest`.

`CandidateDecision` can bind a human disposition to the exact reviewed candidate
and validation report. The caller owns any decision record. The reconstruction
module has no acceptance store or publication authority.

## Explicitly retired concepts

The current architecture has no adaptive waves, case declarations, persistence
repository, shared-checkout coordination, dependency closures, durable replay
platform, sealed requests or receipts, campaign ledgers, acceptance/master store,
or agent-governance control plane. A single second clean run in a fresh process
may prove deterministic output; it is not a maintained replay platform. Completed
proof campaigns and their trackers are historical evidence, not runtime
architecture.

Retained sources, canonical data and IR, historical evidence, and publication
state remain protected. Deleting obsolete machinery does not authorize changing
any of them.
