# About the collection catalogue

The [collection catalogue](https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data/blob/v1.0.0/WORK_CATALOG.md) lists every work and selected copy in this
release. Use its download group to find the category file, then match a record's
`work_id` and `edition_id` to the catalog. Different copies of the same work
have separate edition entries. Collections can contain many individual works;
the catalog does not claim a separate entry for every sermon, letter, or hymn.

The CSV has one row per selected edition. Its `creators` cell contains a JSON
list of names, roles, and responsibility scopes. `containing_source` identifies
a larger source collection when recorded. `records` counts the published rows
for that edition, including retained structural records; it does not count books.

Titles, copy descriptions, languages, and credits come from the library's
curated records, bound to the release build. Publication statements, printed-source
imprints, volume editors, and digital-source credits also come from the exact
accepted source headers and existing source notices. Inclusion, download groups, terms,
and counts come from the selected release's verified public report.
The generated catalog rejects changed metadata instead of silently combining a
new description with an older release. Unknown credits stay unfilled. A blank
does not mean anonymous; a qualified attribution keeps its qualification.

## Bibliographic exchange

The [MODS XML](https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data/blob/v1.0.0/WORK_CATALOG.mods.xml) uses the Library of Congress's MODS 3.8
format. It describes each selected electronic copy, rather than asserting that
its metadata fully identifies a historical printed edition.

| Catalog information | MODS representation |
|---|---|
| Recorded work title | `titleInfo/title` |
| Recorded names and responsibilities | `name/namePart`, `name/role`, and `name/description` for scope |
| Existing normalized role code | `roleTerm`, with `authority="marcrelator"` |
| Unmapped role wording | A textual `roleTerm`, without a controlled-code claim |
| Anonymity or unidentified responsibility | A responsibility note, rather than a fabricated personal name |
| Copy description and supplied language label | Labeled `note` elements |
| Larger containing source | `relatedItem type="host"` |
| Printed-source place, publisher, and date | `originInfo`, within the source-volume `relatedItem` when applicable |
| An imprint supplied as a statement | Source-publication `note` |
| Digital provider and source-file credits | Labeled `note` and source `location/url` |
| Work, textual form, and edition IDs | Typed `identifier` elements |
| Category download | `location/url` |
| Selected text's terms | `accessCondition type="use and reproduction"` |

Names are not assigned Library of Congress authority identities. A translator
credited only for another edition is not assigned to this one. Component and
series responsibilities retain their scope. Unrecorded publishers, publication
places, dates, and print-edition statements are omitted; an electronic provider
is not substituted for a historical publisher. The current language label is
preserved as a note rather than assigned an unverified ISO authority conversion.

Download groups describe the shape of the data. They are not bibliographic
genre, form, or subject headings. This release does not invent a new subject
classification or claim complete RDA/ISBD cataloging. The MODS export and readable
list share the same records; later source-backed descriptions can enrich them.
Complete reuse conditions remain in the [source notices](https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data/blob/v1.0.0/HUGGINGFACE_SOURCE_NOTICES.md).

The versioned download links become live when v1.0.0 is published.

## Readable bibliography

The public reading view leads with the title and recorded author or contributor
names, followed by the edition, language, containing publication when known,
and reuse terms. Omit an absent author line rather than printing an internal
missing-field message or guessing that a work is anonymous. Keep contributor
roles and component/series scope; do not promote an editor into an author.

Display "digital text" instead of "retained electronic witness" and leave file
encoding labels out of that description. CSV and MODS keep the original edition
label. Short labels such as Unlicense and CC0 receive plain-language explanations;
qualified rights statements retain their exact wording. Data IDs and record counts
remain together at the end of each entry for readers matching dataset rows.

The CSV's `publication` object keeps the printed-source information and its scope;
`digital_source` names and links the provider; `source_credits` preserves explicit
source-file contributor roles. A source volume's editor and printing date remain
attached to that volume, not to the composition of every work within it. Electronic
creation dates are not used as print-publication dates. Unknown facts stay blank.
These are generated catalog metadata, not edits to accepted texts or substitute
work identities. Do not derive dates or names from filenames or edition IDs.

References: [MODS elements](https://www.loc.gov/standards/mods/userguide/generalapp.html),
[names and roles](https://www.loc.gov/standards/mods/v3/name.html), and
[MODS 3.8 schema](https://www.loc.gov/standards/mods/v3/mods-3-8.xsd).
