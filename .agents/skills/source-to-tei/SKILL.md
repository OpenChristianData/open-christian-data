---
name: source-to-tei
description: Reconstruct retained sources as faithful TEI, assess existing reconstructions, or perform visual verification in CVW.
---

# Source to TEI

Produce or assess a readable TEI reconstruction whose fidelity to an exact
retained source can be demonstrated. Source wording, order, and meaningful
structure are authoritative; apparent errors and uncertainty remain visible.

## Choose the task

Identify the work or edition, retained source, intended TEI scope, and requested
outcome. Use the project's current contracts and source-specific mapping or
fidelity policy where they exist. Distinguish textual witnesses from comparison,
metadata, rights, and other support evidence.

Distinguish readiness to begin review from a completed review or an acceptance
handoff; report the specific claim being assessed.

For OCD work, start with `docs/TEXT_CONTRIBUTIONS.md` and the agreed work or
issue. The public acquisition view at `docs/ACQUISITIONS.md` helps identify
source research and unfinished editions; confirm the exact copy and assignment.
In a maintainer checkout, `PROJECT_STATE.md` owns current project action. The
public checkout omits private production records; use the supplied task-owned
source/identity workspace, or record the exact missing inputs in the issue.
`docs/OCD_LIBRARY_PIPELINE_SPEC.md` governs authority. Work, state, acquisition
and acceptance sidecars own their respective facts; accepted TEI owns the
edition's complete structured text and detailed header. Generated views summarize
those authorities.

New reconstruction and review admission follow the supported sidecar-based
workflow. WorkCatalog remains available only for explicitly selected historical
compatibility work; its retirement is separately scoped.

Record the active skill package root and the reviewed project root when they
differ. Resolve this skill's relative links from its package root. For OCD
guidance, reach the [review-pattern index](../../../docs/SOURCE_TO_TEI_REVIEW_PATTERNS.md)
from that same package's checkout; it selects lessons, not the source or runtime
under review. Resolve the reviewed project's code, source and runtime paths from
the reviewed project root. If a required reference is missing, locate the active
package's copy or record the missing guidance explicitly.

Select index entries matching the source features, route, or observed symptoms.
Use their evidence and check links to target inspection. The index is the sole
catalog of learned failure patterns; it supplements the fidelity requirements
below rather than defining every possible source feature.

- **Reconstruct:** create or change a source-to-TEI result. Follow that checklist.
- **Assess:** check an existing result or its evidence, including visual review.
  Follow that checklist. A defect becomes a located finding; reconstruction is
  the next task only when repair is in scope.

Use the requested activity to choose, regardless of when the work entered the
corpus. Acquisition research, source selection, and OCR production belong to
their owning workflows. If the required retained source is absent or ambiguous,
identify the missing input before claiming source fidelity.

## Reconstruct

1. **Account for the source.** Bind the retained input by identity and content
   hash. Inspect its complete declared envelope before selecting content for
   conversion, including enclosing members, front/back matter, and support
   material. Choose source-native **carriers**: units that expose loss, duplication, changed
   order, and wrong attachment. Record each unit's identity, position, meaningful
   relationships, and preservation or exclusion policy in the existing source
   profile or accounting evidence. Include heading ownership, note targets,
   field roles, and work boundaries where present. Done when the inventory covers
   the declared input, its relationships, and exclusions; unexplained material
   remains an open gap.

   **Resolve work boundaries:** classify each top-level title as a complete
   work, a container, or a part using title hierarchy, contents, explicit
   boundaries, established work identity, and other source evidence. A heading
   alone does not establish another work. Determine whether nested titles identify
   distinct works from that evidence. If source evidence cannot resolve a title's
   role or work boundary, state the ambiguity and hold that scope before
   conversion. Set boundaries from source evidence rather than file size, token
   counts, or eventual public dataset rows.

   Record collection relationships, source order, and exact selectors in the
   existing sidecars and mapping evidence. Give shared front/back matter, notes,
   media, and cross-work links explicit destinations and ownership, preserving
   context and accounting for any intentional repetition.

   Done when every scoped work has a defined identity and source boundary, shared
   material has an explicit disposition, and unresolved work boundaries are
   named and held before conversion.

   Compare inherited completeness claims with the actual declared member set
   and scope. Use [inventory strategies](references/inventory-strategies.md)
   for the source formats present, including the maintained preflight tools.
   Reconcile retained-source discovery with the task's inclusion/exclusion rule
   before conversion; candidate absence alone does not authorize work.
   Preserve source-supplied correction/rights
   statements and flag relevant electronic-header contact details for the
   separate disclosure decision; neither implies permission to change the source.

   If a complete already-TEI member is retained unchanged, independently verified
   byte equality can establish conservation of that member without a second node
   ledger. It does not establish edition identity, schema validity, or claims
   about transformations and other members.

   **Screen text quality:** follow the [text-quality evidence procedure](../../../docs/SOURCE_PREFLIGHT.md#advisory-text-observations)
   for retained text and authored correction-map readings. Done when each
   text-bearing input has a hash-bound screen or an explicit source-specific
   reader disposition, and inherited uncertainty is recorded before mapping.

2. **Map faithfully.** Preserve the declared source content as readable TEI,
   including meaningful structure, metadata, notes, links, tables, and images
   where present. Explain transformations and exclusions in the mapping policy.

   **Emit exactly one candidate TEI per top-level title classified as a complete
   work in step 1.** Keep its chapters, nested sections, source members, files,
   and volumes in that TEI. Titles classified as containers or parts produce no
   TEI; create another TEI only when source evidence establishes a distinct
   complete work.

   Check the representation against the bound schema, including placement and
   attachment. Done when every source-attested work in scope has a faithful TEI
   representation and every inventoried unit and relationship has a TEI
   representation or explicit disposition. Embedded source bytes or machine
   ledgers can support this proof; the readable reconstruction must stand on its own.

3. **Check independently.** Read the retained source itself in context and
   independently derive its intended structure within the declared scope before
   inspecting the candidate or consulting producer findings where possible;
   record prior exposure rather than claiming blind discovery. Identify hierarchy,
   boundaries, order, headings, and meaningful relationships, such as
   question/answer groups, note attachment, tables, verse lines, and mixed inline
   order. Record the source locations and textual evidence supporting these
   expectations. Source markup, inventories, contents lists, and automated
   extraction can guide or corroborate the reading, but do not replace it; resolve
   their interpretation against the source text and preserve ambiguity where the
   evidence is inconclusive. Have a checker compare these source-derived
   expectations with the actual readable TEI. Keep its
   selection, traversal, mapping, and completeness logic independent of the
   converter. For URI links, check [local closure](../../../docs/SOURCE_PREFLIGHT.md#candidate-link-closure)
   and independently verify the intended source target. Derive expected grouping and attachment from the source before
   adopting the converter's interpretation. Identify shared dependencies,
   including parser recovery and inventory logic, that could conceal the same
   failure; corroborate affected claims through a route independent of that
   assumption. Check omissions, duplication, invention,
   ordering, attachment, and readable meaning against the source. Reuse checks
   whose inputs, independence, and coverage support the claim; text equality
   establishes text conservation alone. Done when source-derived structure and
   its evidence locations are recorded, every observed unit and meaningful
   relationship has a source-grounded representation check, every discrepancy
   or coverage gap is explained or reported,
   and shared producer/checker assumptions and their corroboration are recorded.

4. **Challenge the proof.** Choose mutations from the source features and claims
   actually governed: for example, omit a unit, move a note, change an attribute,
   invent content, or substitute another source. Confirm the baseline passes and
   each mutation actually changes the claimed property, then verify rejection
   for the intended reason. Validate the candidate and reproduce it in a second
   clean process.
   Done when the required checks pass and candidate bytes reproduce, with any
   permitted nondeterminism explicitly accounted for.

5. **Deliver the candidate.** Use the project's supported generation and packaging
   interface. Bind the source, converter, checker, policy, schema, candidate, and
   verification results to each independent output unit. Reconcile their combined
   coverage against the complete declared source envelope, checking omissions,
   duplication, order, and cross-unit relationships.

   Link each candidate to its exact work, edition, and acquisition through the
   supported sidecar interfaces. Update the relevant target state when the task
   advances or blocks it, recording the evidence and remaining gaps. Record
   acceptance separately under the project's acceptance procedure. When a reviewed
   acceptance declaration is ready for an authorized bounded destination, follow
   the project [accepted-master administrative
   handoff](../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md#accepted-master-administrative-handoff).
   Inspect the
   generated `text-quality.json` alongside validation before review or acceptance
   handoff; for routes outside the supported candidate runner, retain equivalent
   source/override/actual-TEI screens. Apply the linked text-quality procedure's
   finding and coverage dispositions in the existing review evidence. Done when
   every screen input is accounted for and its findings or limits are visible
   in the handoff; a fidelity pass alone does not close source-quality findings.

   For a visual-review or acceptance handoff, check the
   documented package layout, required validation sidecar, and exact work/member
   route using the project's
   [admission procedure](../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md#cvw-admission-and-continuation)
   before browser review. When shared converter dependencies change, use
   [binding reconciliation](../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md#manifest-and-storage-diagnosis)
   to identify affected consumers and required evidence refreshes. Done when
   combined unit coverage is reconciled, another reviewer can reopen each unit
   with its evidence and establish its place in the retained source, candidate
   readiness is distinguished from accepted-master status, and any admission or
   dependent-binding gaps are explicit. Continue below for the requested review.

Present technical completion only after all required fidelity and validation
checks pass; report remaining gaps as partial or failed evidence.

## Assess an existing result

1. **Recover the exact evidence.** Locate the retained source, TEI result, declared
   scope, and available generation, accounting, validation, and review evidence.
   Verify that the evidence refers to these artifacts. Done when each binding is
   verified or its absence, staleness, or mismatch is explicitly recorded.

   Before declaring evidence absent, inspect the task's known candidate/report
   locations. Classify recovered artifacts by exact identities, method and scope;
   discovery or prior approval alone does not make them current proof. Name what
   each authority establishes using the project
   [evidence ownership guide](../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md#evidence-ownership).

2. **Evaluate the claimed proof.** Determine which fidelity requirements in
   Reconstruct are already supported and which need checking. Reuse evidence
   whose identity, method, and coverage support the present claim. Run the checks
   needed to resolve gaps within the assignment; a historical completion label
   alone is insufficient. Done when each requested claim has supporting evidence
   or a named unresolved gap. Rebuilding the converter is not a prerequisite for
   inspecting an existing candidate.

   Check inherited completeness against the actual source/member scope, and
   require the same recorded independence assessment when reusing checker proof.
   For text-quality claims, apply the [text-quality evidence procedure](../../../docs/SOURCE_PREFLIGHT.md#advisory-text-observations)
   to retained inputs, authored overrides and actual TEI. Done when screen hashes,
   finding dispositions and unsupported coverage support the claimed scope;
   historical results retain their original as-run evidence.

3. **Review the requested scope.** For visual verification, follow the section
   below. Record source/candidate discrepancies separately from source ambiguity,
   edition questions, and viewer limitations. Done when each finding identifies
   its location, evidence, and consequence for the requested claim.

   **For a repaired candidate,** compare affected source and actual TEI directly,
   including neighboring structures whose grouping, order, or attachment could
   change. Check the checker's expectations against the source separately from
   the producer implementation. Reuse earlier evidence only with a stated
   artifact-comparison and behavioral basis; refresh checks and visual evidence
   for affected claims. Synthetic mutations demonstrate checker sensitivity,
   not natural discoveries. Done when the original discrepancy and affected
   neighboring relationships are verified, or remaining gaps are reported, and
   each reused receipt has an explicit basis for continued applicability.

4. **Report the result.** State what remains valid, what failed, what was not
   checked, and the next evidence or repair needed. When repairs or owner
   handoffs have changed the evidence, use the project
   [delivery reconciliation](../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md#reconcile-evidence-and-delivery)
   before assigning current status. Done when another reviewer
   can distinguish a completed assessment from a fully verified reconstruction.

## Visual verification

Use this section when visual verification is requested or when preparing a
candidate for a human acceptance decision.

1. **Declare coverage.** Follow the task's review policy. Where none is specified,
   define a bounded scope suited to the claim and risks: whole content, a stated
   sample, or named exceptions. Identify opening/ending boundaries, meaningful
   transitions, unusual features, and ordinary content relevant to that scope.
   Where bounded sampling is permitted, select source-located examples of each
   distinct high-risk feature present within the declared scope (tables, verse,
   complex notes, mixed inline content, and work boundaries), plus ordinary
   content. Explain the selection in the existing review. Expand affected
   coverage when a finding suggests a repeated mapping failure, a sibling
   structure at risk, or unreliable navigation; report any expansion beyond the
   assignment as a needed follow-up. Record each work or member covered. Done
   when each selected feature has a planned locus or explicit coverage gap,
   and coverage of one part cannot be mistaken for coverage of its siblings.

2. **Open the exact pair.** Follow the reviewed checkout's `cvw_app/README.md`
   to admit and launch the exact candidate in Corpus Verification Workbench
   (CVW). Use an available browser-control route that can render CVW, navigate
   both panes, and capture their visible content. The in-app Browser and
   standalone Playwright are both eligible; follow the chosen route's setup
   instructions and applicable permissions. Verify it by opening and capturing
   the review page. For evidence requirements, use the project
   [CVW evidence profile](../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md#cvw-evidence-profile).
   Verify the displayed source and candidate identities, then locate each side
   independently from the source. Use linked navigation only with explicit
   correspondence evidence. Done when the exact pair and requested locations
   are visible, with warnings and presentation limits recorded.

3. **Inspect and record.** Compare wording, order, attachment, and meaningful
   structure in the declared scope. Bind observations to the actual source and
   TEI locations. Inspect actual TEI when a displayed discrepancy could arise in
   reconstruction or rendering; classify the layer from evidence or leave it
   unresolved. Inspect the captured pixels and retain screenshots bound to the
   source, candidate, runtime, route, and visible locations. Record API traversal
   and DOM/text checks as mechanical evidence; visual credit requires the
   reviewer's actual inspection of rendered content. Done when each selected
   feature has an inspected locus or explicit gap, observations have retained
   visual evidence, and finding layers are supported or explicitly unresolved.

4. **Handle limitations.** Classify the failed layer before choosing the next step.
   If a browser-control route is missing or fails, check another available route
   against step 2. Report which routes were checked and their observed results;
   a missing named tool or a worker's failure establishes only that context's
   limitation. The coordinator checks its own routes before declaring the review
   blocked. When no usable route remains, preserve exact identities, existing
   evidence, and uncovered locations for continuation.

   If CVW cannot admit the work, retain the source-local candidate, name the
   admission gap and owner, and leave visual review pending. Use authorized
   generators for repairs; admission failure does not authorize fabricated
   catalog rows or hand edits to generated data. If CVW admits the work but
   cannot display a required feature, an exact alternative presentation may
   supply evidence for that feature. Record its identity, inspected locations,
   and limits separately, leaving the CVW display gap explicit. Done when every
   limitation names the affected coverage and the next action needed to resolve it.

5. **Hand off.** Report artifact and segment reachability separately from actual
   close visual comparison. Identify whether observations were made by an agent
   or a human. Include exact artifact identities, inspected locations, findings,
   evidence references, and unresolved coverage. Done when the review can be
   reopened without reconstructing the session from memory.

Technical verification and agent review supply evidence. Acceptance follows the
project's [evidence-backed acceptance procedure](../../../docs/OCD_LIBRARY_PIPELINE_SPEC.md#7-accepted-master)
and may be performed by an authorized agent. Record human verification separately.
Rights clearance, source correction, and publication remain separate decisions
under the project's authority. Preserve their actual status in every handoff.

For manifest/materialization failures or cross-work synthesis, use the matching
section of the project [review operations](../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md).
