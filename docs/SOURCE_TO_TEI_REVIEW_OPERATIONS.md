# Source-to-TEI review operations

Current project guidance. The [source-to-TEI skill](../.agents/skills/source-to-tei/SKILL.md)
owns the workflow; the [pattern index](SOURCE_TO_TEI_REVIEW_PATTERNS.md) is the
single catalog of learned failures. Read the relevant section here when
recovering evidence, diagnosing admission/materialization, capturing CVW review,
or synthesizing work results. This document owns those project procedures, not
source meaning or acceptance state.

Resolve the skill, this guide, the pattern index, and retained review history
from the active package's checkout. Resolve executable code, runtime contracts,
storage configuration, and tests from `<reviewed-project-root>`, which may be a
different worktree. The explicit rooted paths below are instructions to locate
that checkout's files, not links to the package checkout. If absent there, record
the missing contract; another checkout's version does not silently substitute.

## Evidence ownership

Name the authority before using its evidence. These similarly named artifacts
answer different questions:

| Artifact | What it establishes |
| --- | --- |
| Acquisition record, such as `research/MANIFEST.md`, and retained rights evidence | Acquisition scope, source/edition research, rights questions, and unresolved acquisition work |
| Work/acquisition/state/acceptance sidecars | Declared identities, retained members, and separately governed state/acceptance facts; generated views only summarize them |
| Explicitly selected historical WorkCatalog | Historical review routes and diagnostics under their retained contract; not the default lifecycle authority |
| `SourceManifest` | Exact retained inputs and bound reconstruction route, implementation, policy and schema |
| Candidate manifest and validation sidecar | Integrity and validation of the identified candidate package |
| Bound `text-quality.json` sidecar | Advisory character observations and explicit screening coverage; apply the [text-quality review procedure](SOURCE_PREFLIGHT.md#advisory-text-observations) before handoff |
| Caller-owned review or human decision | Actual inspected scope, observations, and any separately authorized disposition |

Use `<reviewed-project-root>/docs/RECONSTRUCTION_CONTRACT.md` and that checkout's
supported interfaces. A stale derived view cannot change retained
source meaning. For default CVW routing and missing declarations, follow
[declared review admission](RECONSTRUCTION_CONTRACT.md#declared-review-admission).
Technical checks never invent a human decision.

For constituent-work metadata, name the exact work/member selector and classify
the evidence as primary, derived, catalog, or unverified. A shared-file digest
identifies bytes, while a missing catalog registration is a separate question
from whether retained evidence supports the fact; see the
[RP-14 example](SOURCE_TO_TEI_REVIEW_PATTERNS.md#rp-14-constituent-contributor-example).

When reviewing metadata evidence, read whether the cited material supports the
complete claim, not just whether its locator and excerpt match. Distinguish
author, translator, and editor; original publication, printing, translation,
and revision events; and verbatim values from derived normalization. Split
compound claims or bind every asserted component. Preserve genuine uncertainty
without repeating an unresolved label after direct evidence settles it.
Metadata adoption and required-item coverage follow the metadata owner's
maintained contract; this review does not introduce a second metadata writer.

## Accepted-master administrative handoff

After review produces a complete acceptance declaration, use the shared
administrative command from the reviewed project checkout:

```powershell
py -3 build/tools/admit_accepted_work.py --root <bounded-evidence-root> --declaration <reviewed-declaration.json> --promotion <fresh-promotion-root> --install-root <bounded-destination-root>
```

The declaration supplies the already-reviewed identity, source accounting,
candidate, scope, technical and review evidence, representation revision, and
decision. The command creates a fresh acceptance sidecar, validates its pending
record, promotes the exact candidate to a fresh destination, performs the
guarded initial installation, then resolves and validates the installed work
through the supported readback API. Completion requires exit code 0 and JSON
status `admitted-and-validated`; retain the returned installed acceptance path,
master SHA-256, and installation receipt.

Use task-owned copied evidence and a bounded destination for rehearsal. Writing
an accepted master into canonical authority requires that operation's explicit
scope and owner authorization. The command consumes review evidence; it does
not create source accounting, decide fidelity, supply a human decision, or
authorize release/publication. The XML and retained-JSONL fixture replay is
maintained in `tests/test_admit_accepted_work.py`.

## Retained-source intake

Before reconstructing or reporting a missing source, resolve the exact requested
work/edition against acquisition receipts, current sidecars, and known candidate
locations. Use the configured storage resolver for logical library paths; record
which physical roots and identities were searched. A missing local junction,
stale queue row, incidental numeric filename match, or missing candidate is not
source absence. Rebind old manifest line references using the pinned snapshot
and expected row text; unresolved grouped works remain ambiguous.

Apply the task's scope rule after discovery. In a missing-sources-only campaign,
an exact retained edition is excluded even without a candidate. A reconstruction
task may explicitly authorize that same retained source. Acquisition upgrades
need an exact current work/edition target or an explicit new-work decision.
Done when the identity, retained state, searched scope, and authorized next action
agree. Source quality and rights facts keep their separate evidence and status.

## Source media handoff

The fixed six-member candidate package remains unchanged. Bind source media in
the existing retained-source authority and accountability evidence, including
container/member identity, size/hash, each ordered body reference and its target.
Use [ZIP preflight](SOURCE_PREFLIGHT.md#zip-and-source-media-census) as discovery;
the source-local oracle checks intended placement, labels, and candidate carriers.
An archive-only cover is not a body image, and an image pointer is not retained
image bytes. Keep every other member's disposition explicit.

A typed nonrendered milestone proves only a preserved reference/boundary. When the
fidelity claim requires a readable image, retain that claim as incomplete until a
supported hash-bound presentation supplies it. Do not add undeclared package
members or represent a dangling graphic as complete. Record the asset/display
contract gap with the packaging or CVW owner; exact alternative page/image
presentations may supply bounded evidence under the existing visual procedure.
Done when reference conservation, retained bytes, and inspected image coverage
are separately evidenced or explicitly unresolved.

## Manifest and storage diagnosis

Use the [workspace and storage rules](TEXT_CONTRIBUTIONS.md#workspace-and-storage) for a public task workspace. Maintainer checkouts also use their local storage topology when paths cross worktrees, junctions or the retained library. Resolve both member and authority root
through the supported storage seam before comparing containment. Logical-path
safety, resolved containment, and caller-root containment remain separate checks.

For a failed binding, compare expected and physical size/hash, retained or
committed bytes, Git attributes/filters and LF/CRLF materialization, and the
declared executable dependencies. Classify the failure as missing/inaccessible
path, containment failure, checkout materialization, content drift, or stale
binding. A newline-only mismatch is still a failed byte binding; it is not proof
that the source's wording changed.

Use the maintained validator/rebinding tools and the exact authorized scope for
repairs. Preserve retained bytes. An unexplained current hash must not be
resealed merely to pass. When an authorized shared dependency changes, identify
its affected consumers and their owners before applying a coordinated repair;
record unrepaired consumers explicitly. Shared-file coordination does not turn
a review ticket into permission for repository-wide normalization.

## CVW admission and continuation

Use `<reviewed-project-root>/cvw_app/README.md` to admit the
exact validated candidate. Verify the candidate's work/member scope against the
route actually admitted. Candidate validity and route availability are separate
facts. When a row, generator or supported route is missing, preserve the candidate,
identify the specific missing contract and owner, and keep visual status pending.
Use supported canonical or transient admission mechanisms only when they exist
and the requested scope authorizes them; this guide creates neither mechanism.

For one evidenced edition spanning retained members, bind an explicit ordered
`retained-member-set` acquisition and carry those positions through the
member-level candidates, the `teiCorpus` composition, acceptance, CVW
admission, and the selected offline projection. Keep each complete member
separate; never choose a member implicitly or concatenate alternative editions
as continuation.

Keep runtime diagnostics with their owning launch/capture interface. For a
restart or resumed tab, verify the served candidate and implementation identity
before continuing. A PID or current on-disk file hash alone does not establish
which earlier code served a response. Legacy evidence retains only the claims
it actually bound. Retain backend errors and exact remaining coverage for a
browser continuation; test availability in each context actually used.

After a cold Compare timeout, retain the failure and allow one same-session
retry after checking readiness. Before crediting the result, inspect fresh
route/control state and both panes' actual anchors with warnings retained.
If browser capability is lost, preserve valid accounting packets and name only
the remaining visual loci for an available authorized context. Check that
context's documented APIs and browser ownership; numeric tab IDs alone do not
establish shared ownership. Follow the skill's
[visual verification steps](../.agents/skills/source-to-tei/SKILL.md#visual-verification)
to check alternative browser routes. If none is usable, record the
capability limitation and uncovered scope. The
September 8 continuation record (historical maintainer record)
keeps the reported lifecycle sequence separate from its unproven cause.

## CVW evidence profile

Use the evidence fields below for a review another person can reopen. A task may
require a named capture profile in addition; use that profile only when it is
provided and its requirements are met. The capture helper checks supplied
bindings; it does not authenticate browser observations or establish passage
identity. Keep labeled frames when equivalent bindings are unavailable.

For each current review, retain:

- Exact source selection, candidate/validation bindings, and copied CVW identity.
- Actual runtime/serving evidence supplied by the maintained interface, with any
  identity limitation made explicit.
- Declared coverage, reached artifacts/segments, and separately inspected loci.
- Each evidence image's file identity, actual media type/dimensions, capture time,
  route, viewport, warnings, and the loci visibly inspected by the reviewer.
- Findings and unreached scope, without interpreting a served segment as visual
  inspection or an agent observation as a human decision.

Before selecting a sample, verify the admitted media presentation actually exposes
source content: a PDF download link or generic archive node supplies no page
pixels. Inspect each pane at its own source-derived locus. Source and candidate
segment numbers or generated section IDs do not establish correspondence.

After inspecting the retained pixels, use the [caller-owned review template](SOURCE_TO_TEI_VISUAL_REVIEW_TEMPLATE.md)
in the existing work report to bind observations and limits to each frame. Leave
generated capture fields unchanged, including `visual_inspection: unknown`.

Use labeled frames showing the needed native source/TEI content and context.
Where the current ticket requires simultaneous terminal content/status evidence,
retain that fallback until equivalent binding is demonstrated. A crop or
status-free image is not completed evidence merely because it is cheaper.

The retained [legacy visual guide](../.agents/skills/source-to-tei/references/visual-verification.md)
is the migration baseline for detailed capture cases, especially its
"Hand off exact identity" section. Consult those cases when the applicable
capture ticket requires them; it is not the universal reconstruction workflow.
The [legacy receipt example](../.agents/skills/source-to-tei/references/cvw-receipt-template.json)
remains for existing consumers until migration. Its prefilled values are examples,
not observations: verify every populated assertion and omit inapplicable optional
sections under the consumer's contract. Do not claim a prefilled boolean as proof.
Unobserved claims must be explicitly unknown; use a supported population profile
or record a schema/consumer gap rather than invent incompatible receipt fields.
A neutral successor must start evidence assertions as unknown and migrate callers
together. Historical rejected and superseded evidence remains unchanged.

Save report fields through structured serialization and derive digests and image
media/dimensions from the saved bytes. Reject corrupted control characters;
record unavailable CSS viewport, DPR or capture time as unknown. Preflight a
fresh staging path before capture, then verify source/destination bytes when
retaining it elsewhere. A successful sandbox write does not prove host readability.
Keep selected route, actual visible source/TEI anchors and warnings separate.
Each frame binds its own session receipt; cross-session synthesis requires
explicit identity equivalence and limits, not candidate-hash equality alone.

## Synthesize findings and readiness

Record process problems and suggestions in the contribution's issue or pull
request, with a reproducing example and the affected source/candidate. Keep
detailed review evidence with that contribution. Maintainers also append to
their internal source-to-TEI friction log under its existing routing rules.
Access to that private log is not needed to contribute.

Use the existing campaign records. Record independent facts rather than forcing
one label to answer unrelated questions:

| Fact | Meaning |
| --- | --- |
| Scope and coverage | Named work/members; readiness-only, canary, partial, or whole declared scope; reached versus close-compared content |
| Technical outcome | Which bound checks passed, failed or remain unperformed |
| Textual eligibility | Known correction/proofreading quality, uncertainty, or not applicable |
| Visual and human status | Actual visual scope and limitations; separately recorded human acceptance |

A completed technical assessment can concern uncertain transcription or partial
visual coverage. Preserve source-correction, display-layer correction and source
disagreement as distinct dispositions. Bind the applicable ledger/applier evidence
to the exact claim; a display correction is support evidence, not permission to
rewrite retained wording. Preserve rights and editorial questions separately.

Group results only where scope and evidence support the common claim. Preserve
clean negative controls and no-finding boundaries without forcing them into a
defect category. Log proposed reusable lessons in the canonical friction log
for authorized synthesis; retain exact per-work outcomes in their original reviews.

### Reconcile evidence and delivery

When summarizing an interval, name its baseline and enumerate all intervening
cohorts and parallel owner work, not just the latest batch. Keep source-review
tickets, metadata subjects, and visual loci as separate populations; disclose
missing coverage instead of treating absent reports as no findings.

For a changed work or returned handoff, reconcile the existing ticket with the
exact reviewed source/config/manifest, candidate, relevant metadata receipt,
and current implementation evidence. Preserve historical bytes and outcomes;
record the successor, what changed, and which claims remain applicable. A
metadata correction can require a manifest successor without changing reviewed
TEI. Verify that dependency impact rather than silently resealing or repeating
an unaffected review.

Distinguish reported, implemented, verified, integrated in the canonical
checkout, and committed states where relevant. A commit proves neither review
completion nor a live runtime update; a stale "pending" heading does not
override a verified delivery receipt. Update current status only within the
assignment, retaining history and separately owned acceptance decisions.

Route source-specific findings to the existing source owner, metadata decisions
to its owner, and viewer defects to the app owner. A handoff names the affected
identity/locus, evidence, uncertainty, requested action, and expected return.
Sent or acknowledged is not fixed: close the affected claim against returned
verification and its current dependencies, or retain the owner and residual.
Use existing reports and trackers, with a shared receipt reference for grouped
claims where appropriate; no parallel registry or additional messaging authority
is created. Reconciliation is complete when each affected claim has current
support or a named unresolved dependency.

### Evaluate review effectiveness

When an authorized batch evaluates review effectiveness, use its existing
per-work reviews to record:

- Finding location, affected source/TEI versions, and supported layer (source,
  reconstruction, checker, viewer, or unresolved).
- First documented detector and any prior exposure to findings.
- Original mechanical outcome: passed, failed, unavailable, or unknown, with
  the check's actual coverage.
- Visual role: first discovery, prompted confirmation, separate finding, or
  not performed/unknown.
- Measured active time for mechanical checking, source inspection, visual
  review, and repair; record waits separately. Mark missing measurements unknown
  and identify overlapping work rather than summing it as sequential effort.

At batch close, report selection criteria, coverage, unresolved findings, and
measured effort. Keep original natural discoveries, repair-review findings, and
synthetic sensitivity tests distinct. Compare detection rates only when the
denominator and review coverage support the comparison; prompted confirmation
is not independent rediscovery. These fields are for an effectiveness trial,
not a new receipt schema or a prerequisite for ordinary review completion.
Historical timings and unseen findings are not reconstructed from guesses.

Use the next comparable authorized batch to check recurrence and first-pass
semantic accuracy as well as eventual repair success. Where measured, include
avoidable recaptures, restarts, binding corrections, and status-integration
effort. Report changes in selection or coverage that prevent comparison; do not
start another batch solely because this guidance names an evaluation.

### Source-completeness handoff fields

Use the existing per-work review report and current receipt contracts. The
following is the single semantic field list for campaign handoffs; acceptance
bindings follow the current [accepted-master contract](OCD_LIBRARY_PIPELINE_SPEC.md#7-accepted-master).
It does not introduce an additional registry or require incompatible fields in
an existing receipt schema.

| Field | Required meaning |
| --- | --- |
| Identity and declared scope | Work/edition identity; exact source manifest/envelope reference and digest; complete expected member inventory, ordering, included members and explicit exclusions with reasons. Distinguish a whole work from a selected volume/member. |
| Availability and completeness | Which expected members are retained/readable; missing or unknown members; source-local extent/accounting evidence and its file/digest. A valid manifest alone does not prove the expected inventory is complete. |
| Reconstruction and technical proof | Exact candidate/TEI and validation/accounting file references and digests; producer/checker identities, reproducibility/schema/closure results and commands with authoritative outcomes. State shared normalization or projection assumptions and independent corroboration. |
| Review and coverage | Review report reference/digest, reviewer identity and UTC date; actual visual loci and reached versus inspected scope; source-quality uncertainty, discrepancies and unreviewed residuals. Bind claims to the exact source and TEI versions. |
| Decision and blockers | Existing source-local disposition, acceptance blockers and their evidence, separately recorded agent assessment and human decision. Explicitly distinguish supported scope, unassessed stronger claims and unresolved claims. |

Do not narrow a declared scope to conceal missing expected members: preserve the original expected envelope, the scope-change reason/authority and explicit wider-work residuals. A justified selected-member review is allowed, but cannot silently inherit a whole-work completeness claim.

Missing members, unsupported whole-work claims, stale identities and unresolved acceptance blockers cannot be concealed by passing machine checks. Incomplete exhaustive or visual verification is honest coverage, not automatically an acceptance blocker: a master can be accepted for justified declared scope under CONTEXT. Source fidelity does not establish edition quality, rights or publication readiness.

Before status writes, verify current report/gate/receipt pins, exact input sets,
counts and acceptance-owner state. Retain the rehash result and reject stale
pins, set drift or owner mismatch. Review required prose facts semantically;
equivalent wording and numeric/path presentation do not require exact phrases.
Keep the checks that protect identities and closure sets; checker size alone
does not establish redundancy.

Whole-library completeness is accumulated through existing work-review tickets and synthesis, not a parallel campaign. Existing reviews retain their original outcomes. Reuse their bound evidence where it supports the claim; assess only the missing delta before making a stronger source-completeness claim. OCR/page-image texts retain the EzraOCR route and may receive bounded member/identity/completeness checks without an exhaustive correction campaign here.

Before promoting a sample-derived heuristic to a cross-corpus gate, require
independent positive examples, clean negatives, an explicit false-positive
boundary, a warning-only/no-write pilot, and an adopt/narrow/no-go decision in
the owning campaign. Evaluate existing checks before adding another. Acceptance
of a category skeleton does not approve later thresholds or examples. Readiness-
only examples remain evidence to assess, not durable acquisition rules.

For a recurring finding, distinguish missing guidance from guidance that was
not discovered, was misapplied, or imposed an unnecessary requirement. Individual
review tasks log evidence and suggestions in the canonical friction log,
including the proposed destination: component owner, source ticket, skill,
pattern index, or project procedure. Evaluation alone does not authorize edits
to shared guidance or changes to another owner's implementation.

A separately authorized synthesis or maintenance task considers the suggestions
together, records adopt, narrow, defer, already covered, or reject with reasons,
and makes only the approved changes. Suggestions to revise or retire ineffective
guidance follow that same route. Ordinary review tasks need neither change the
guidance nor wait for suggestion adoption to complete their assigned review.
