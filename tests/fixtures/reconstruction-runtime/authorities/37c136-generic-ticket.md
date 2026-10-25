# 37c-136: Complete source-to-TEI verification for Natural Law in the Spiritual World

**Parent:** Ticket 37 whole-library verification.

**What to build:** Deliver a readable, independently verified TEI reconstruction for catalog entry `drummond-natural-law` with its supported metadata persisted in the appropriate sidecar/authority, complete declared source accounting, and recorded visual review. Resolve this entry's readiness work before claiming candidate admission or completed verification.

**Blocked by:** None to begin this entry's readiness work. Metadata persistence uses the reviewed META-002/003 contract and this entry's own batch; unrelated works or optional metadata do not gate it. Source/candidate admission and external OCR prerequisites gate only their dependent steps.

**Status:** TERMINAL — technical gates complete within the bounded source-bound scope; candidate remains nonaccepted, and human acceptance, rights, permanent admission, accepted IR, and publication are explicitly out of scope for this lane.

**Implementation owner:** [LIB-071](../../2026-08-26-whole-library-faithful-tei-completion/tickets/library/071-reconstruct-and-review-gutenberg-evangelical-works-cohort-1.md). This ticket coordinates one entry through that owner's implementation; it does not create a competing producer or require the whole family ticket to finish first.

**First concrete action:** LIB-071 existing owner: preserve the retained human-proofread Project Gutenberg text witness (individual provider corrections not independently audited), resolve edition and rights qualifiers, then package and independently verify TEI/CVW evidence; keep readiness-pending until current evidence is admitted.

## Exact evidence and scope

- Source quality: the ticket-bound retained Project Gutenberg member is positively identified as human-proofread and carries Distributed Proofreaders attribution. The provider's individual corrections have not been independently audited. This source-quality identification makes no rights-clearance or human-acceptance claim.

- Catalog identity: `drummond-natural-law`. Observed title: Natural Law in the Spiritual World. These labels are not new v2 identities.
- Existing readiness disposition: `source-bound-human-proofread-pg; edition-rights-and-package-pending`.
- Evidence row: [final identity assessment](../../2026-08-31-library-pipeline-redesign/artifacts/META-001/23-identity-assessment.json), JSON pointer `/catalog_rows/173`; selected input SHA-256 `99c97b032c2fb9413f8aed1c034d3eab0a90d3e6bbbd78721780cd86522ccb05`.
- Current source/route details and exact retained paths are in the entry's [readiness work index](../artifacts/2026-09-08-ticket37/readiness325/work-index.json) and linked owner evidence. For the two exceptional entries, use the [library status row](../artifacts/2026-09-08-ticket37/library-status.json). Verify current bindings before reuse.
- Preserve work, textual form, edition, part and witness scope separately. Reuse prior proof only where identity/hash/declared scope still match. Any missing expected material remains visible; do not reduce the intended envelope to the available files.

## Identity questions to resolve in this slice

- **work:** Does the retained source scope for Natural Law in the Spiritual World establish the same standalone work or collection boundary as catalog ID drummond-natural-law? Evidence needed: Work-specific title and boundary evidence through LIB-071; Existing route disposition: source-bound-human-proofread-pg; edition-rights-and-package-pending. LIB-071 existing owner: preserve the retained human-proofread Project Gutenberg text witness (individual provider corrections not independently audited), resolve edition and rights qualifiers, then package and independently verify TEI/CVW evidence; keep readiness-pending until current evidence is admitted.
- **textual_form:** For Natural Law in the Spiritual World, which work-specific translation/revision is represented by the observed language en and translator label not recorded? Evidence needed: Retained language/contributor/translation statements for drummond-natural-law; assess whether its recorded translator is applicable. Use the existing route, not a new ID as a prerequisite.
- **edition:** For Natural Law in the Spiritual World, which retained title/imprint evidence establishes the source-edition claim Hurst & Co., New York. Project Gutenberg PG#23334., separately from the original work date? Evidence needed: Retained title/imprint or explicit edition statement for drummond-natural-law; distinguish publication, composition, provider and download dates. Existing route disposition: source-bound-human-proofread-pg; edition-rights-and-package-pending. LIB-071 existing owner: preserve the retained human-proofread Project Gutenberg text witness (individual provider corrections not independently audited), resolve edition and rights qualifiers, then package and independently verify TEI/CVW evidence; keep readiness-pending until current evidence is admitted.
- **parts:** For Natural Law in the Spiritual World, which named volumes or constituent works correspond to the 1 stored files, and which files are only segmentation? Evidence needed: Named contents/volume/member map for drummond-natural-law using its existing retained or reviewed scope. Existing route disposition: source-bound-human-proofread-pg; edition-rights-and-package-pending. LIB-071 existing owner: preserve the retained human-proofread Project Gutenberg text witness (individual provider corrections not independently audited), resolve edition and rights qualifiers, then package and independently verify TEI/CVW evidence; keep readiness-pending until current evidence is admitted.
- **witnesses:** Which exact retained member and work-specific selector represent drummond-natural-law, beyond its observed source-hash and route association? Evidence needed: Current retained bytes and work-specific member/selector mapping for drummond-natural-law. Existing route disposition: source-bound-human-proofread-pg; edition-rights-and-package-pending. LIB-071 existing owner: preserve the retained human-proofread Project Gutenberg text witness (individual provider corrections not independently audited), resolve edition and rights qualifiers, then package and independently verify TEI/CVW evidence; keep readiness-pending until current evidence is admitted.

## Complete execution and acceptance

Follow [complete per-work requirements](../artifacts/2026-09-08-ticket37/execution-requirements.md) and the project source-to-TEI skill. All seven stages apply; a source/metadata investigation alone does not complete this ticket.

- [x] Resolve this entry's bounded readiness findings and verify the complete declared source/member envelope, ordered contents, exclusions and explicit gaps.
- [x] Persist traceable required and useful optional metadata in the reviewed sidecar/authority contract; distinguish factual support, adoption, requirement and genuine unknowns. Link actual delivered files.
- [x] Recover/integrate or reconstruct the exact TEI through LIB-071; bind independent accounting, source-quality evidence, meaningful mutation rejection, validation and deterministic reproduction.
- [x] Complete declared CVW visual coverage against the exact source/TEI pair; retain native evidence and distinguish reached from visibly inspected locations.
- [x] Record findings and friction, apply supported corrections through the owning route, independently reverify and visually recheck the affected scope; no supported technical correction remains in the declared scope.
- [x] Deliver the result and remaining limitations. The candidate remains nonaccepted; human acceptance, rights, promotion and publication are separate.

**Report home:** [technical review](../artifacts/2026-09-08-ticket37/reviews/37c-136.md). The durable [technical-completion receipt](../artifacts/2026-09-08-ticket37/reviews/37c-136-receipt.json) records the current route and its explicit limits. Substantial CVW payloads remain in the declared durable evidence home.
