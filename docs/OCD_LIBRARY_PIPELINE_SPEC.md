# Open Christian Data library and publication pipeline specification

**Status:** Approved governing design
**Decision date:** 2026-08-31
**Current reconciliation:** 2026-09-26
**Implementation status:** Core work/state sidecar, accepted-master, projection,
release, and offline verification machinery is implemented. PROJECT_STATE.md
is the single current status source for library counts, installed masters,
remaining acceptance and rights work, release readiness, and work order. This
specification defines the durable pipeline and release rules; it does not
duplicate those changing totals.
**Authority:** This specification governs pipeline design. `library/works/**`
is the machine authority for installed works and accepted masters; generated
corpus manifests are views. `PROJECT_STATE.md` records current priorities and
remaining work. Campaign tickets and receipts provide scoped evidence and do
not replace those authorities.

Read PROJECT_STATE.md for the current first-release selection, OCR exclusions,
and acquisition handoff status. OCR identities remain in library accounting;
the seven-work release is implementation evidence, not the selected cohort.

## Problem statement

OCD currently has several partly overlapping ways to describe a text, its source,
its processing state, and its public output. The original JSON datasets, the
expanded `WorkCatalog`, research manifests, source manifests, candidate manifests,
TEI candidates, and the first offline TEI-to-Hugging-Face assembler each solve a
real local problem, but together they do not form one simple authority chain.

This makes basic questions harder than they should be:

- What works does OCD know about?
- Which textual form and edition does a file represent?
- What exact source was acquired, and when?
- Which TEI is the current accepted master?
- What is the current project state of each acquisition or edition target?
- Which public rows came from which accepted text units?
- What was excluded from a release, and why?

The redesign must answer those questions without creating another central registry,
a second text representation, an exhaustive metadata warehouse, or a release
system that silently decides what Robbie meant to publish.

## Solution

OCD will use one direct authority chain:

```text
evidenced project-relevant work
  -> stable work identity and current project state
  -> exact acquisition evidence and retained source
  -> source-specific reconstruction
  -> evidence-backed accepted TEI master for one edition
  -> category-specific public row projection
  -> private projection receipt and independent mechanical check
  -> manually chosen offline release snapshot
  -> finished public Hugging Face files
```

TEI is the sole complete internal representation of ordered text. JSON is used only
for small identity/state/evidence sidecars, generated reports and receipts, and the
finished public dataset. Public JSON is always regenerated from accepted TEI and
upstream facts; it is never a parallel text authority.

Each in-scope work has one stable identity sidecar and one narrow mutable state
sidecar. Exact acquisition evidence belongs to the acquisition. Accepted TEI owns
the edition's full structured text and detailed edition header. A durable
whole-corpus manifest is regenerated from those authorities and checked into the
repository so the complete library can be inspected at a known revision. Status
reports, acquisition queues, and release manifests are also generated views.

The public product is one Hugging Face repository with configurations based on the
text's actual form. Each row is directly useful to a machine-learning user, is cut
at a trustworthy source-defined boundary, contains a compact self-contained
metadata envelope, and remains connected to its work, textual form, edition, and
source location.

## User stories

1. As an ML user, I can stream a category configuration and use each row without joining a private metadata table first.
2. As an ML user, I can group every row belonging to the same intellectual work using a stable work identifier.
3. As an ML user, I can distinguish translations, substantial revisions, abridgments, and other recognizably different textual forms.
4. As an ML user, I can distinguish publication editions that a human reader would plainly regard as different editions.
5. As an ML user, I can split a dataset by work or edition without accidental train/test leakage.
6. As an ML user, I can reconstruct larger source units because row order and source-defined locators are explicit.
7. As an ML user, I receive the edition's actual wording, spelling, punctuation, and meaningful structure rather than silently modernized text.
8. As an ML user, I can identify the language and compact public provenance of a row.
9. As an ML user, I am not forced to process speculative tradition, audience, era, theme, or topic labels.
10. As an ML user, I can tell quotations, sermons, hymns, liturgies, reference entries, and other materially different forms apart.
11. As an ML user, commentary rows preserve the original commentary unit instead of duplicating it into artificial verse rows.
12. As an ML user, prose rows follow trustworthy source divisions and never fixed token or character counts.
13. As an ML user, a genuine source paragraph or block may be a prose row when no named division exists.
14. As an ML user, sermon rows distinguish the passage primarily preached on from other scripture references.
15. As an ML user, hymn rows keep title and first line distinct and preserve source-attested stanza, refrain, tune, contributor, and hymnal facts.
16. As an ML user, quotation rows represent individual quotation occurrences and retain their anthology or source-edition location.
17. As an ML user, liturgy rows preserve speaker roles, rubrics, alternatives, branches, and call-and-response relationships.
18. As a curator, I can create a stable work identity when evidence establishes a relevant work even before a usable source is acquired.
19. As a curator, I do not create identities for every book in existence; the library contains only evidenced works OCD actually intends to assess, acquire, or include.
20. As a curator, I can leave unknown or ambiguous facts absent instead of guessing them.
21. As a curator, I can correct a title or contributor name without changing an immutable work identifier.
22. As a curator, I can distinguish stable identity facts from changing acquisition and processing state.
23. As a curator, I can see separate current states for multiple acquisition or edition targets belonging to one work.
24. As a curator, I update a target's state in the same change that advances, blocks, abandons, reopens, or invalidates it.
25. As a curator, I rely on Git for detailed history rather than maintaining an unbounded lifecycle event ledger.
26. As a curator, I can regenerate and commit one durable whole-corpus manifest from the sidecars and accepted texts without manually repairing a separate catalog.
27. As a curator, a generated status report exposes contradictions between declared state and physical evidence.
28. As a curator, acquisition research that is not yet a stable work remains visible without becoming a universal bibliography.
29. As a researcher, I can trace an edition to the exact acquired source, URL, provider, access date, retained files, and hashes.
30. As a researcher, I can distinguish an intellectual work, textual form, edition, acquisition, and accepted representation revision.
31. As an authorized agent, I can accept a TEI master when the defined evidence, validation, and accounting requirements pass, without waiting for Robbie to inspect it personally.
32. As a reviewer, I can record exactly what human eyes inspected, at what scope, when, and with what result, without making human verification a prerequisite for acceptance.
33. As an agent, I can record researched facts, cited evidence, uncertainty, and conflicts provisionally without claiming human verification.
34. As Robbie, I see material warnings, unresolved issues, and explicit exclusions before choosing a release.
35. As Robbie, I decide when and what to publish; the assembler does not silently substitute a rights rule or automated release judgment for that choice.
36. As a release builder, I select current accepted masters rather than transient candidate directories or a catalog-owned reconstruction route.
37. As a release builder, I create a fresh deterministic staging directory containing only the finished public product.
38. As a release builder, private TEI, local paths, assessments, reviews, source hashes, and internal receipts cannot enter the public upload by accident.
39. As a verifier, I can independently compare projected rows with accepted TEI for identity, order, count, duplication, locators, and text hashes.
40. As an operator, every failed, warned, excluded, and included item is visibly accounted for; nothing disappears silently.
41. As a maintainer, I can regenerate all public rows after an upstream correction without preserving a parallel legacy JSON product.
42. As a maintainer, I can apply the already-settled keep, rename, derive, or retire decisions to every legacy schema field and consumer before cutover.
43. As an OCD maintainer, I can change OCD's library and publication code without importing EzraOCR's runtime kernel.
44. As an EzraOCR maintainer, I can change OCR-specific code without importing OCD's runtime kernel.
45. As an integration maintainer, I can test the cross-repository handoff with small versioned boundary fixtures rather than shared runtime code.

## Implementation decisions

### 1. Text authority

TEI is the sole complete internal ordered-content core. There is no generic JSON
intermediate representation. The public JSON dataset is a lossy, consumer-oriented
projection whose relationship to TEI is explicitly receipted.

### 2. Repository boundary

EzraOCR and OCD own separate runtime kernels. EzraOCR is the acquisition route for
texts requiring OCR. Its handoff to OCD is accepted TEI plus exact identity and
evidence bindings. Born-digital sources reach the same OCD acceptance boundary.
Only small versioned boundary schemas and fixtures may be duplicated across the
repositories.

**OCR and publication:** OCD does not publish known uncorrected OCR defects.
`OCR-GOOD`/`OCR-RAW` labels, readable samples, parser success, or OCR output alone
do not establish public-text fidelity. This is a release gate, not an installation
gate: a usable, evidence-backed TEI may be accepted and installed with known OCR
uncertainty or an explicitly partial scope. Preserve those defects and gaps in
work-local evidence and exclude affected public text with an explicit reason.
For an OCR-derived witness, acceptance can establish faithful representation of
the retained OCR text; it does not certify that the OCR matches the printed page.
State that distinction and quarantine known or unreviewed scan discrepancies.
General OCR correction is outside the current release-preparation pass.

**Mixed and partial source scopes:** A TEI may cover only a supported part of a
work, or use multiple members of one retained member-set. Bind every contribution
to its source and locator; record omissions, overlaps, edition differences, and
unresolved conflicts. Name a composite representation accurately instead of
presenting it as one historical edition. Each acceptance currently binds one
acquisition, so portions from independent acquisitions remain separately scoped
masters until acceptance and projection can validate per-segment source bindings.
This modeling limit does not block installing a supported partial scope. Public
eligibility is assessed separately for the declared scope, source credits/notices,
rights, fidelity, and reader checks; one held scope does not block other works.

### 3. Identity hierarchy

The identity hierarchy is work, textual form, edition, and acquisition:

- A work is the intellectual work.
- A textual form is a translation, substantial revision, abridgment, or other recognizably different wording.
- An edition is a particular publication of a textual form.
- An acquisition is the exact scan, file, copy, or source instance OCD located or retained.

These distinctions are created only when evidence supports them. Ambiguity is
surfaced for human resolution rather than merged by title similarity.

### 4. Stable work sidecar

Each in-scope work has one small validated identity sidecar. It owns stable IDs,
relationships, readable titles, evidenced creators, textual-form identities, and
known edition identities. It does not contain the text body, workflow state,
subjective classifications, or open-ended metadata maps.

### 5. Mutable state sidecar

Each work has one narrow state sidecar containing separate entries for relevant
acquisition and edition targets. Each entry contains its target identifier, current
stage, update time, a short reason only when needed, and evidence references. A
work with no exactly established acquisition or edition may have an empty target
list; do not invent a planned edition merely to fill it. The empty list means no
target is currently declared, not that source reconstruction or publication is
complete. The stage is explicit; objective milestones are derived or validated
against physical evidence. Git provides detailed history.

### 6. Acquisition evidence

The acquisition record owns exact provider, URL, access date, retained-file
identity, hashes, and source scope. Relevant facts may be repeated in TEI history or
public provenance as validated projections, but corrections begin at acquisition
evidence.

An archive such as a ZIP is a retained acquisition package, never the source
itself. The acquisition's source path, size, hash, and scope identify verified
extracted text or a canonical set of extracted source members. Keep the package
and support files separately hash-bound in the retained-file inventory or a
linked acquisition receipt and work evidence, with their distinct roles. A ZIP
without verified extracted source members does not establish a usable source
binding.

### 7. Accepted master

The accepted TEI master is the current faithful representation of one edition. A
representation revision is a deliberately accepted change set, not one literal
edit. The TEI revision history records the revision identifier, date, and concise
note; Git records the detailed changes.

Acceptance is evidence-backed project authority, not a requirement that Robbie
personally inspect the text. An authorized agent may accept a master when the
defined source accounting, TEI validation, identity binding, fidelity checks, and
acceptance record all pass. The acceptance record identifies who or what accepted
it and the evidence used. A later human verification is recorded separately and
does not retrospectively create the acceptance.

### 8. Metadata rule

Metadata is included when it materially helps a user identify, cite, order,
connect, interpret, or legally use the text and OCD can model it clearly,
objectively, and consistently. The goal is maximum usefulness and fidelity, not
maximum field count. Unknown facts are absent.

New source-metadata decisions are authored under `metadata/decisions/` and
projected by `build.lib.source_metadata`; generated
`metadata/source-evidence/` files do not replace their unique authored owner.
Historical decision files remain at their original evidence-bound locators.

### 9. Explicit exclusions from the metadata model

The target public schemas exclude tradition, tradition notes, intended audience,
era, inferred themes or topics, summaries, key quotations, vague context, generic
source labels, untyped extras, and machine-written relevance justifications.
Specific source-attested structure remains eligible.

### 10. Public configurations

The public Hugging Face repository has these form-based configurations:

1. bible
2. commentary
3. quotations
4. prose
5. poetry
6. sermons
7. catechisms
8. doctrinal documents
9. reference entries
10. topical indexes
11. devotionals
12. prayers
13. hymns
14. liturgies

There is no universal plain-text configuration at launch. Modernized spelling is
a possible future product, not an alternate core or automatic sibling.

### 11. Public row envelope

Every public row includes a stable record identifier, sequence, work identifier,
textual-form identifier, edition identifier, category, readable text, language,
category-specific locator, compact public provenance, and representation revision.
Only category-required structure extends this common envelope.

### 12. Row boundaries

Rows follow trustworthy boundaries in accepted TEI. The system never manufactures
fixed-size chunks. Where prose has no named division, genuine source paragraphs or
blocks are valid rows; the complete work is used only when no trustworthy internal
boundary exists.

### 13. Category profiles

The overarching rule is:

> Standardize equivalent concepts and their representation wherever appropriate,
> while preserving TEI's extensible usefulness for genuine source variation. Never
> standardize source texts into structures they did not possess.

TEI P5 is intentionally flexible, so a file being valid generic TEI is not enough
to make projection predictable. OCD therefore defines a narrower common TEI profile
covering the permitted ordered structures, identifiers, nesting, notes, references,
and source locators. Each category then has a thin category profile, projection
mapping, public schema, and semantic validator.

Not every text within a category must fit one rigid profile. A category may admit
several real structural patterns or a documented source-specific extension. The
common vocabulary still gives one preferred representation to equivalent concepts,
so separate sessions do not invent different words for the same thing.

Variation is allowed when it reflects the source, but it must use an existing
pattern or a declared extension with a defined meaning, owner, real example, and
projection or explicit nonprojection behavior. A projector must reject or visibly
exclude an unrecognized pattern; it may not guess how to flatten it. The common
profile standardizes equivalent structures, while category rules preserve genuine
differences.

Specific settled corrections include:

- commentary retains the source commentary unit and target scope;
- quotations use one source-listed quotation occurrence per row and explicit source location;
- sermons distinguish primary scripture from other scripture references;
- hymns distinguish hymn-text identity, hymnal occurrence, title, and first line;
- liturgies preserve roles, rubrics, alternatives, branches, and responses;
- doctrinal documents retain their materially different normative structure.

Native mixed content represents TEI `unclear` as `uncertain-text`, retaining
its supplied reading, inline position, and supported source attributes (`reason`,
`cert`, `resp`, `rend`, and `xml:lang`). The readable text uses the retained
reading; uncertainty remains explicit in structured content. The independent
observer checks this carrier and rejects changed readings, certainty, attributes,
or attachment. TCP A47235 supplies the readings `bear` and `that` as a real
example. Unsupported attributes continue to fail closed.

### 14. Liturgy projection

Liturgy is a public configuration, not a permanently internal-only category. Its
first public schema must be the smallest shape that preserves role, rubric,
sequence, branch or alternative membership, and response relationships. Until that
schema passes review, liturgy is a visible unsupported target, never a silent
omission.

### 15. Projection receipt

Every projection build creates a private receipt binding accepted master hashes,
mapping and assembler versions, output hashes and row counts, row-to-TEI anchors,
source locators, text hashes, ordering, warnings, exclusions, and independent-check
results. It is an audit result, not a metadata authority or public file.

### 16. Assessment and review

Agent assessment, human review, and publication action are separate. Agent
assessment records evidence and uncertainty provisionally. Human review records
only what a human actually inspected. Neither is inferred from passing tests, and
human verification is not required before an evidence-backed agent acceptance.

The four TEI-standardization outputs are a deliberate human-approval checkpoint.
Agents may audit, draft vocabulary rules, build conformance tests, and exercise
projection checks while those outputs are provisional. None of the audit findings,
preferred vocabulary, conformance rules, or TEI-to-public-row mapping becomes the
adopted project authority until Robbie has reviewed and explicitly approved that
ticket's result. Pending approval is a promotion gate, not a reason to stop the
tickets from progressing.

### 17. Publication decision

The assembler presents current accepted material, assessments, warnings, and
exclusions. Robbie chooses the snapshot and decides whether to publish it. The
system may identify issues intelligently but does not turn one issue class into an
automatic substitute for that decision.

### 18. Generated views

The whole-corpus manifest is a generated, version-controlled snapshot listing every
in-scope work and its connected textual forms, editions, acquisitions, accepted
masters, and current target states. It is durable and easy to inspect, but its facts
are regenerated from the per-work authorities rather than authored independently.
A freshness check fails when it no longer matches those authorities.

Project-status reports, acquisition queues, and release manifests are separate
generated views with distinct purposes. None is an authored identity or workflow
authority. The generic word "manifest" is reserved for the whole-corpus inventory
or qualified by its precise purpose, such as a release manifest.

### 19. Release assembly

A release selection names accepted edition masters and public configurations. The
assembler writes to a new destination, produces public files and private evidence
in separate roots, fails visibly, and cannot publish remotely. Live publication is
a separate explicit action.

A whole-library selection also declares a `work_coverage` partition of every
current canonical work ID into included works and excluded works with reasons.
Each selected text item names its work ID; the assembler checks that binding
against the accepted record and records missing or invalid acceptance evidence as
a failed item. The assembler rejects missing, unknown, duplicate, or text-selected
excluded IDs and writes a deterministic private `internal/work-coverage.json`;
the independent verifier reconstructs that file from the selection and verified
text-item results. This accounts for identity-only works without inventing public
text rows. Public rows remain derived from accepted edition masters and retain
their work, form, edition, source, and text links. Small proof selections may omit
`work_coverage`.

### 20. Legacy cutover and retirement

The old JSON datasets and schemas are not retained as a compatibility product.
Before removal, every legacy field, producer, and consumer receives an explicit
keep, rename, derive, or retire disposition. Useful behavior and fixtures may be
reused, but legacy JSON never becomes a source for the new product. This is a
one-time cutover and retirement, not an indefinitely maintained migration layer.

A bounded real-library pilot proves the design across a reviewed set of materially
different structures. It is not corpus-completeness evidence. Final retirement of
the old JSON or expanded WorkCatalog additionally requires a whole-corpus offline
rehearsal in which every in-scope target and supported consumer is accounted for as
included, excluded, blocked, failed, replaced, or deliberately retired.

### 21. Current implementation attempts

The expanded WorkCatalog, current research manifest, source manifests, candidate
packages, and first accepted-TEI-to-Hugging-Face assembler are evidence about useful
requirements and failure modes. They do not constrain the target architecture.
Useful properties to preserve include exact evidence binding, deterministic fresh
destinations, complete accounting, private/public separation, and fail-visible
verification.

### 22. Executable schema completion

The conceptual schema design is settled. Implementation still requires exact field
names, closed required/optional rules, identifiers, enumerations, semantic
invariants, category locator shapes, and the final liturgy row contract. These are
implementation design details to be completed against representative fixtures and
accepted as a coherent versioned schema package.

## Testing decisions

The highest-value seam is one offline end-to-end build over a tiny fixture library.
The fixture library contains one representative accepted work for each materially
different structural family, including at least prose, sermon, quotation, hymn, and
liturgy. The test begins with work/state/acquisition sidecars and accepted TEI, then
generates library views, projects category rows, creates private receipts, assembles
the public release tree, and runs the independent checker.

That seam must prove:

1. every selected accepted text is included or explicitly excluded;
2. row identity, order, locators, text, and counts correspond to TEI;
3. the durable whole-corpus manifest and state views agree with their authorities;
4. no legacy JSON or WorkCatalog state is needed to create the public files;
5. no private evidence can cross the public allowlist;
6. rebuilding from identical inputs is byte-for-byte deterministic;
7. unsupported or invalid structure fails visibly; and
8. liturgy functionality is preserved by its reviewed row shape.

Focused schema, semantic-validator, category-mapping, and negative tests support
this seam. Each legacy consumer cutover has a test proving its replacement before
the old path is retired. Cross-repository boundary fixtures run independently in
both repositories and do not import either runtime kernel.

The proposed acceptance seam for Robbie's review is therefore:

> One command builds and independently verifies a complete private/public offline
> release fixture from accepted TEI and sidecars, with no WorkCatalog or legacy JSON
> dependency and no silent omission.

## Out of scope

- Publishing or uploading a live Hugging Face release.
- Automatically deciding whether Robbie should publish.
- Creating or accepting real TEI masters as part of the architecture cutover.
- Reconstructing source texts or changing source-faithfulness rules.
- Building a universal bibliography of Christian works or ISBNs.
- Creating subjective enrichment, inferred tags, summaries, or audience labels.
- Maintaining backward-compatible public legacy JSON alongside the replacement.
- Creating a generic event ledger, central workflow database, or second text IR.
- Modernized spelling, universal plain-text, or speculative future configurations.
- Making detailed OCR working state part of OCD's runtime model.

## Further notes

The earlier schema discussion did resolve the product and domain model. It did not
produce executable schemas ready to merge. The ticket sequence deliberately starts
with the end-to-end seam and representative fixtures so the literal schema package
is designed against required functionality rather than speculative completeness.

The prior TEI-to-Hugging-Face assembler is a useful prototype. It demonstrated an
offline, deterministic, receipt-bearing release build, but its candidate-path,
WorkCatalog, publication-declaration, English-only, and CC0-only assumptions are not
the approved long-term contract.

The prior WorkCatalog audit is also useful evidence. It showed that a generated
inventory became difficult to trust after absorbing reconstruction routes and
lifecycle control. The replacement keeps stable identity and current state beside
the work, lets source and acceptance evidence own their narrower facts, and makes
catalogs disposable generated views again.

## Source-located literary carriers

Native literary projection preserves source-whitespace blocks, including blank strings, and the source numeric `n` attributes on `list`, `floatingText`, `label`, and source-placeholder `figure` as `number`. These admissions preserve retained literary structure; they do not authorize dropping source text, changing boundaries, or accepting unknown attributes. Work-level source accounting and independent verification must reject altered text, carrier types, coordinates, attachment, or unsupported attributes. Current implementation evidence and schema bindings belong in the work receipts and PROJECT_STATE.md.

The explicit `ab@type=source-inline-container` wrapper is also preserved as a native source block when a retained inline carrier appears directly in a source division. Its ordered children, reference attributes and text/tails remain represented; empty carriers remain structural evidence. This admission does not change source reference classification or permit unknown block types. Producer-independent checks must detect wrapper removal, changed targets, text/tails or ordering.

Complete ThML source-projection standOff evidence uses closed five-field records binding ordered original attributes, target IDs and source parent/ordinal relationships. Validated mapped source-header descendants and ordered inert prolog comments remain private receipt evidence. Literal source heading renditions and empty globalSubject index names/subjects are preserved. The generic checker establishes handoff structure and exact-master correspondence; independent retained-source fidelity remains separately required. Active processing instructions, DTD/entities, unknown evidence/ordinary-header structures and unsupported index names fail closed.
