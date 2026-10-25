# Queryable rights records

Rights version 2.1 addresses the four reviewed prototype gaps: exact material,
territorial outcomes, included components and conditional terms, and assessment
basis. It is registered with the library validator and read by lookup, browse,
and standalone metadata export. Existing source-bound findings have been adopted
into current records; missing or unresolved coverage remains explicit. Fresh
release reconciliation is described below. Prior review receipts remain private
maintainer evidence, not prerequisites for making a public proposal. Use the
[contribution guide](../CONTRIBUTING.md) to report an evidenced correction.

## Assessment approach

Assess U.S. use first and record the strongest supported positive scope. Other
territories are additional findings, not prerequisites for a U.S. conclusion.
Use reasonable conclusions from primary publication evidence, relevant renewal
searches, and source-specific declarations or grants; proof against hypothetical
contrary facts is not required. Apply common source rules to evidenced cohorts
without repeating text reviews.

For U.S. assessments, faithful scanning, OCR and format conversion alone do not
establish a new creative copyright layer. Investigate actual added expression
and source exceptions. Keep OCR accuracy, release preparation and publication
decisions separate. Provider declarations stay attributable declarations. An
empty territory or an unperformed assessment is not a restriction.

## Subjects and assessments

An edition keeps assessment files in `rights/`, with subject definitions in
`rights-subjects/`. A subject names work, edition, scope, and an exact existing
material decision or selection with SHA-256 and a JSON pointer. Selected-text
requires an explicit pointer. The full accepted master is not the identity of
an extracted historical subset. Subjects declare their included component IDs.

Each subject also carries `public_scope`: structured include/exclude selectors
using public record IDs, source anchors, division numbers or exact source labels.
Metadata export preserves those selectors and assessment qualifications while
omitting internal evidence paths/hashes. Author them from the bound decision;
do not invent a public boundary from a title or role label.

A non-positive subject may have an empty inclusion array when no eligible subset
has been established. A public-domain, licensed or mixed assessment requires
explicit included material; an invalid positive sibling invalidates the joined
edition. Keep supported partial findings on their own exact subjects.

Rights-subject identity is separate from representation revision. Existing
acceptance/projection records own OCR corrections; those do not automatically
create new rights findings. Materially changed selection requires explicit
subject reconciliation. Changed bound evidence fails stale.

One assessment has a unique record ID, subject binding, outcome, territory,
grant identifier where applicable, basis, condition, evidence, actor and date.
Countries with equal findings can share a record; differing outcomes coexist.
Overlapping incompatible findings invalidate the join rather than selecting the
last file read. Missing assessments remain missing, not restricted.

| Field | Controlled meaning |
|---|---|
| `rights_status` | public-domain, licensed, mixed, restricted, undetermined, not-assessed |
| `scope` | whole-edition, selected-text, original-text, translation, editorial-material, digital-contribution, compilation |
| `basis` | statutory-assessment, provider-declaration, dedication, license, permission, not-assessed |
| `condition` | unconditional, if-protectable |
| `jurisdictions` | Uppercase country codes or evidenced worldwide; empty only for provider declarations or not-assessed |
| `license_ids` | One identifier per atomic grant; empty for expiration-based public domain. Multiple layer terms join through component subjects. |

Mixed material declares components. Every included component needs coverage for
the parent's queried territory. Incomplete joins cannot establish a public-domain
whole. Conditional electronic-contribution grants stay conditional; preserving
a recorded condition does not require a new protectability investigation.
An unspecified mixed parent can report that its component findings are present
without asserting a shared territory. Country queries still require an explicit
territorial finding; they cannot borrow a child's country for the parent.

Evidence binds actual research/decision bytes. Markdown arguments are hashed
without interpreting prose; JSON pointers select structured evidence. Ordinary
lookup reads small records, not retained text or master XML. Bind an existing
receipt when source-body evidence is needed. Original notices and license texts
remain required deliverables; identifiers do not replace them.

## Fresh release reconciliation

Fresh assembly and verification require a positive normalized finding covering
the exact selected public record IDs. The selected license and notice bindings
must agree with that finding's reviewed normalization receipt. The immutable
receipt records the adopted tuple, components, material binding and public-scope
digest through existing evidence fields. It proves faithful adoption of the
reviewed decision; it is not a second editable rights catalog. A changed finding
needs a reviewed successor. Current projection checks still verify the accepted
master; stable public IDs alone do not establish unchanged text.

The gate preserves all territorial assessments. Unresolved material, added rows,
stale evidence, altered normalized terms or omitted notices fail closed. Rights,
text quality, preparation and publication approval remain separate decisions.

## Queries

Use existing browse with `--rights public-domain`, `--rights cc0`, or
`--rights public-domain-or-cc0`, alongside `--jurisdiction US` and
`--rights-scope selected-text`. These are derived modes, not stored eligibility
states. CC0 remains licensed under CC0-1.0; it is not copyright expiration.

`--rights-status licensed` can show conditional grants. General browsing can
show a provider statement without a country; country-specific queries never
match unspecified territory. Malformed, stale, conflicting and incomplete joins
cannot satisfy positive rights queries.

Browse returns matching works with edition alternatives. Inspect the exact
assessment's subject and scope; one matching copy does not label every edition.
Whole-library rights queries require complete subject coverage, not just examples.

## Existing real example

The [Bounds assessment](examples/rights-record.json) and
[subject definition](examples/rights-subject.json) encode the existing October 13
selected historical-text decision. They bind that decision; they do not install
a canonical edition assessment or make a new rights determination. Copy-based
demonstrations establish reader behavior under the frozen-input boundary.

The [assessment schema](../schemas/v2/rights-record.schema.json) and
[subject schema](../schemas/v2/rights-subject.schema.json) own the fields.
Identifier syntax is validated locally; checking the identifier and actual grant
against the [SPDX registry](https://spdx.org/licenses/) belongs to the evidenced
assessment. Original attribution, actual conditions, quality and publication
approval retain their existing owners.
