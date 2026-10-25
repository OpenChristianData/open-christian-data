# OCD Licensing

For standardized, queryable assessment fields, see [rights records](RIGHTS_RECORDS.md). Current library records and fresh release reconciliation use those scoped assessments; missing or unresolved findings remain explicit.

## Rights labels and release profiles

OCD maintains one acquisition catalog with explicit rights labels. Public-domain
status, CC0, and other copyright licenses are distinct facts and must not be
collapsed into a generic "open" or "CC0" label.

The acquisition catalog may contain works and source layers carrying:

- `public-domain` — no known copyright restriction for the relevant jurisdiction;
- `cc0-1.0` — an explicit Creative Commons Zero dedication;
- `cc-by-4.0` or another versioned CC BY license;
- `cc-by-sa-4.0` or another versioned CC BY-SA license;
- `cc-by-nc-4.0` and `cc-by-nc-sa-4.0` or their applicable versions;
- `cc-by-nd-4.0` and `cc-by-nc-nd-4.0` or their applicable versions;
- explicit permission or another documented grant;
- `restricted`, `all-rights-reserved`, or `unverified`.

The exact license, version, jurisdiction, source layer, attribution requirements,
ShareAlike requirements, NonCommercial term, NoDerivatives term, and third-party
exclusions belong in provenance. The rights label describes the source; it does
not make a downstream decision for consumers.

The historical v0.2.0 Hugging Face artifact used a **public-domain/CC0 release
profile**. The published v1.0.0 release uses item-level terms,
including supported CC BY, CC BY-SA, and other documented grants alongside
public-domain material. Read the exact dataset's delivered README, item terms and notices for its selected
scope. Keep territory and modern source-layer terms explicit; private preparation
does not authorize public upload.

The [source and acknowledgment ledger](SOURCES.md) preserves historical v0.2.0
source credits and its former release posture. For current mixed item-level
terms, use the [data terms](DATA_TERMS.md) and [source notices](SOURCE_NOTICES.md).
The v1.0.0 GitHub release supplies the TEI masters as a download; the repository
contains software, documentation and legacy/example data. The [release command guide](LIBRARY_CONSUMER_CUTOVER.md)
explains that boundary.

## Public domain is not CC0

`public-domain` records a legal status, usually arising from expiration or
non-applicability of copyright. `cc0-1.0` records an explicit dedication by a
rights holder. A public-domain work should remain labeled `public-domain` unless
the source layer carries an actual CC0 dedication. A CC0 source should remain
labeled `cc0-1.0` even when the underlying work is also old enough to be public
domain.

The underlying work, translation, edition, editorial apparatus, transcription,
markup, database, scan, and repository terms are separate rights objects. A
public-domain original does not automatically make a modern representation public
domain, and a CC license on a digital transcription does not automatically license
third-party content embedded in it.

Assess U.S. use first. For U.S. assessments, faithful scanning, OCR and format
conversion alone do not establish a new creative copyright layer; identify
actual added expression. Use the reasonable evidence standard in the
[rights assessment approach](RIGHTS_RECORDS.md#assessment-approach).

## Publishing rules

| Source rights class | Appropriate OCD release treatment |
|---|---|
| Public domain / CC0 | Eligible after item-bound provenance, territory, source, and release checks |
| CC BY | Publish with the exact CC BY license and required attribution |
| CC BY-SA | Publish in a compatible, clearly labeled ShareAlike profile |
| CC BY-NC | Publish in a clearly labeled NonCommercial profile |
| CC BY-NC-SA | Publish in a clearly labeled NonCommercial ShareAlike profile |
| CC BY-ND / CC BY-NC-ND | Preserve the NoDerivatives label. OCD may correct evident OCR/transcription errors as part of faithful reproduction; release treatment remains separately documented |
| Explicit permission | Follow the exact scope, duration, attribution, territory, and distribution terms |
| Restricted, all-rights-reserved, or unverified | Keep in research or permission workflow until the rights position is documented |

Consumers determine how a labeled source fits their own use. OCD's job is to
identify the work and source accurately, preserve the applicable rights evidence,
and avoid granting more rights than the source provides.

## Release-profile separation

Rights classes are kept with source and record metadata. When a release combines
different classes, the release documentation must identify the class of every
included source and any obligations that follow from it. A mixed release may use
`license: other` or an equivalent profile declaration together with a complete
license manifest.

The historical production schemas and Hugging Face artifact remain the contract
for v0.2.0. The maintained v2 selection and release machinery carries each selected
item's exact license and source-bound notices. Use that route for later
mixed releases; do not retrofit the historical artifact or treat an unassessed
NonCommercial, NoDerivatives, or third-party layer as cleared by a generic label.

For an OCR or transcription source carrying NoDerivatives terms, OCD's editorial
policy permits correction of evident transcription errors when the purpose is a
faithful reproduction of the represented work. This records OCD's production
intent; it is not a blanket claim about every legal consequence of the source
license.

## Record-level provenance

Consult the applicable JSON schema for the authoritative production fields.
Depending on content type, provenance may live in a `provenance` object and in
work- or edition-level metadata rather than three universal top-level fields.

Keeping rights information with the data makes it possible to replace a source
with a better-licensed or better-attested edition without losing traceability.

## Decision record

The initial licensing strategy was decided 2026-03-27 after identifying mixing risk
across source categories. The 2026-07-22 acquisition-research closure broadened
the catalog policy: CC0 remains a distinct rights class and a release profile, while
public-domain, CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA, CC BY-ND, CC BY-NC-ND,
permission, and unresolved rights remain separately labeled source states.
