# Standardized metadata and information templates

Metadata adoption and label validity are separate checks. A zero-issue
consistency report does not establish complete or source-correct metadata.
Maintainers retain the audit, adoption and verification receipts. To propose a
source-backed correction, use the [contribution guide](../CONTRIBUTING.md).

Canonical labels accompany raw source wording. The versioned
[label profile](../schemas/v2/metadata-labels.json) maps reviewed language/provider
aliases and supported MARC roles. Unmapped values stay visible; no identity,
genre, rights, or equivalent historical era is guessed.

Lookup includes `metadata.normalized` and per-edition rights joins. Browse
supports `--language`, `--provider`, rights status/territory/scope, and derived
public-domain/CC0 modes. The [rights guide](RIGHTS_RECORDS.md) defines their scope.
Current work records own curated creator names, responsibilities, component/series
scope and edition language. Verify corrections against primary evidence, record
their source locators there, and let lookup/browse/export consume those fields
directly. Source witnesses preserve printed wording. Missing scope remains
incomplete until evidenced; names do not assign person authority IDs.

Use `Anonymous` as an explicit author credit when evidence establishes that the
author intentionally withheld their name. Preserve that evidence with the credit.
An unidentified writer, a missing byline, or a provider's conventional anonymous
label alone does not establish deliberate anonymity. Keep those identities
unresolved, with the examined metadata and specific missing evidence recorded.
Qualified or disputed attributions retain their qualifications; a collection's
named sender or translator is not automatically the author of every component.

Provider sets carry `kind: provider-set` and an explanation through lookup,
browse and export. Their key denotes the recorded cohort, not an organization;
querying the lead organization does not claim every supplemental member. Structured
format descriptions retain multiple carriers, encoding, packaging, production and
scope. A declared upstream format does not imply that its carrier is retained;
an OCR format does not imply correction. Unspecified details remain null.

Use `py -3 -m build.tools.report_metadata_consistency` for read-only observations
with stable issue codes. Unsupported legacy labels receive no guessed replacement.
Use `py -3 -m build.tools.export_library_metadata --output <new-file>` for a
deterministic export from the same read model. It rejects invalid rights/records
and private paths/digests. This artifact is not an integrated public bibliography
or publication.

Unknown provider/format/role values remain visible for curation. Unsupported
classification values fail validation at their owning configuration path. Leave
an unconfirmed optional era/audience field absent; current configuration must
contain a valid label or no assertion. There is no exception table for invalid
historical values. Ordinary subsets can be audited without unrelated target pins.

The current label profile is `ocd-metadata-labels-v2`; standalone metadata export
uses `ocd-library-metadata-v3` and reports the actual profile consumed by browse.
Creator output carries its canonical name, role and scope. Per-work display aliases,
creator overlays and legacy-field dispositions are retired. Their exact former
bytes and review receipts remain historical evidence under the completed packets.
The completed canonical cleanup retains its exact corrections, independent
review and verification in maintainer evidence.

Export and consistency report v3 show coverage separately from invalid data:
identity-only works, declared editions without masters, observed accepted masters,
missing assertions, scoped rights and recorded evidence dispositions. Edition
language resolves from the explicit edition, then its exact textual form. It
never borrows a different form or a nonexistent work-level language. Description
joins existing titles, responsibilities, acquisition URLs and typed decisions;
private evidence locators remain internal. Public facets use `vocabulary` for
the canonical internal authority identifier.

Legacy source configurations and generated data can still contain recorded
provider license labels. Those labels do not override scoped rights assessments
or establish release eligibility. In particular, BSB reconciliation confirms
the exact accepted witness and reuses its existing source-bound rights review,
rather than relying on a bare legacy label. Unknown creator identities, rights
holds and unassessed editions remain explicit in coverage reports.

## Local relators

`sender` maps to MARC correspondent (`crp`), preserving the witnessed sender
responsibility alongside the broader standard relationship. `ocd:dictator` is
the explicit local relator for the evidenced medieval letter-dictation role.
It asserts neither generic authorship nor stenography nor political office.
The [Library of Congress relator definitions](https://www.loc.gov/marc/relators/relaterm.html)
own the MARC meanings. Maintainers retain the source evidence and sixty
individual warning dispositions with the completed correction records.

## Bibliographic description profile

Use one evidenced edition description under its work identity. Preserve title,
responsibility wording, contributor roles/scope, language, historical imprint,
electronic provider, relationships, qualifications and applicable notices.
Unsupported values remain absent. Keep download categories separate from form,
subject and publication-form facets.

Optional facets carry kind, authority, term ID, label, evidence and adoption.
Only adopted facets enter export. Creator scope records work, edition, component
or series identity. These fields authorize no inferred classifications. Subsequent exchange/export choices require an evidenced profile; these
fields do not themselves implement a new exchange format.

## Current templates

Use the [copyable sections](examples/information-templates.md) in the existing
owner, with narrative explanations where useful. Machine rights use their schemas.

| Template | Structure and owner |
|---|---|
| Acquisition queue cataloging | One proposed work and source copy; existing IDs, bibliographic facts, extent, primary evidence, rights statement, unknowns and next action |
| Bibliographic decision | Existing metadata decision; typed subject/semantics, literal versus normalized value, exact evidence, inspection/adoption, actor/date |
| Scoped rights | Exact subject plus territorial assessments, components, basis and conditions |
| Task and completion | Current packet; triage/lifecycle/applicability, owner, typed subjects, dependencies, authorization, next action, evidence and successor |
| Source attribution | Acquisition/SourceManifest plus readable source/data notice; historical edition, electronic provider, credits, extent and exact terms |
| Finding/friction | Existing log; unique ID, observed result, separate hypothesis, layer, evidence, code/severity, owner/action and disposition |
| Release documentation | Existing generated metadata; real examples, ID lookup, readers, migration, notices, exact outgoing manifest and publication result |

Current lead upkeep already separates observed claim, intent, disposition and
identity. Keep quality/availability observations and rights references beside
their evidence; promising research is not possession. Reuse the existing upkeep
tool, `build/tools/maintain_research_lead.py`, for the library-owned
`library/acquisition-leads.jsonl` queue. The intake-and-upkeep skill supplies
additional maintainer instructions. Retired verification packets remain history; current work uses the general
campaign workflow. Immutable receipt headers retain earlier staged wording while
current navigation links their terminal adoption.
