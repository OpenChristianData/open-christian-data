# Inventory strategies

Read the section for the source format present. These are carrier starting
points, not a universal serializer contract. The retained source and declared
fidelity claims determine the final inventory. Historical failures and their
checks are cataloged only in the project's review-pattern index.

## Maintained discovery and comparison

Use [source preflight](../../../../docs/SOURCE_PREFLIGHT.md) for retained XML/JSON
occurrences, ZIP members and HTML image references; use its source-profile
comparison for supported mappings. For logical library paths, pass the reviewed
checkout as `--repository-root`. A usable inventory is discovery, not a fidelity
pass. Unsupported features retain explicit dispositions. For retained text or
text overrides, follow the [text-quality evidence procedure](../../../../docs/SOURCE_PREFLIGHT.md#advisory-text-observations)
before mapping and at candidate handoff; account for source-specific reader limits.

## XML, HTML, and TEI

Inspect the complete document envelope as well as the parsed body. Account for
declarations, comments, processing instructions, meaningful pre/post-root bytes,
and content a tolerant parser discards. Preserve ordered element text, child
tails, attributes and parent attachment needed to reconstruct the source.

Inventory document-shell and head metadata independently from body selection.
Give navigation, scripts, styles and acquisition wrappers explicit dispositions.
Choose source-native identities for notes, references, tables, lists, links and
milestones; visible text alone cannot establish their attachment or semantics.
Check proposed TEI mappings against the bound local schema, including mixed
content, allowed attributes, placement and work/header/body structure.

Profile source roles before mapping: class-derived notes/verse, heading ownership,
front/body/back boundaries, and semantic attribute values. Compare source IDs,
printed page labels, and target attachment separately. Empty milestones can begin
an ordered stream whose content is in following siblings, as in USFX; descendant
text alone cannot define that scope. Count recursive text/division scopes as well
as direct children. A migration stylesheet is a transform, not its own oracle.

## JSON and record-oriented text

Inspect the actual object/collection shape, keys, scalar values, collection
positions and ordering rule. Bind a comparison to its specific parent and field.
Preserve missing/null/empty/zero distinctions where meaningful. Give repeated
keys or records separate occurrence identities. Use physical order unless the
source declares a different comparator; alphabetizing is a transformation.

For CSV or line formats, include headers, fields, continuations and meaningful
blank lines. For marked-up text such as USFM, include markers, milestones,
notes, supplied-text conventions and their source-defined location identities.

## Plain text

Bind encoding, newline convention and original bytes. Inventory stable lines,
paragraphs, headings, separators and wrapper regions before normalization. State
how whitespace, dehyphenation or page-header handling affects source fidelity.

## Archives and multiple files

Inventory members before selecting or extracting content: names, occurrences,
order, sizes, hashes and relevant container metadata. Identify unreadable,
encrypted, nested and unexpected members. Separate textual members from indexes,
metadata, licenses and other support material without losing either category.
Bind derived presentations to original members and source ranges.

Reconcile container indexes and extracted members in both directions. Inspect
compression/envelope details when they affect the completeness claim or the
extractor can silently discard material. An unexplained gap remains a finding;
not every byte region must become readable prose. Declare the exact selected
subset and disposition of the enclosing material.

Distinguish directory entries from file payloads. For HTML bundles, reconcile
ordered body media references with member hashes; archive-only artwork is not a
body occurrence. For machine datasets, follow references from every record family
and account separately for aggregate exports. For linked editions, distinguish
navigation pages from required text pages and retain revision/attribution evidence.
Use the [media handoff](../../../../docs/SOURCE_TO_TEI_REVIEW_OPERATIONS.md#source-media-handoff)
when the fixed candidate package cannot embed assets.

## Databases and binary modules

Independently enumerate relevant tables, indexes, keys, record order and payloads.
Reconcile indexes and records in both directions, including orphaned entries,
sentinels, reserved slots, separators, padding and terminal regions. For
compressed blocks, account for record/block boundaries before mapping text.
Whole-file identity alone does not prove completeness of a decoded projection.

## Page images and OCR handoffs

Inventory pages/canvases/images and their text handoffs in source order. Keep
each printed milestone occurrence even when several point to one image. Bind
page-level text to its supplied image/handoff authority and record unresolved
facsimile targets explicitly.

For archive scan handoffs, reconcile original leaves, page-map access flags,
PDF pages and OCR page objects. A provider's `Delete` flag is a claim: inspect
excluded leaves before classifying them as duplicates or nontextual. Preserve
unique pages and unknown dispositions. OCR traversal and correction remain with
EzraOCR. A transcription-derived PDF is not an independent print witness.

Mechanical page accounting does not establish correct wording, layout or image
interpretation. OCR production and correction belong to their owning workflow;
visual observations remain limited to images actually available and inspected.

## Multiple witnesses and editions

Name each witness's role and inventory it independently. Record the selection
or combination policy; preserve disagreements rather than choosing silently.
Distinguish textual witnesses from rights/support members, compare part order
and work boundaries, and retain each member's identity across a combined edition.
