# OCD Licensing

## Default target: CC0

OCD datasets default to CC0 (Creative Commons Zero — public domain dedication).
Source rights and provenance are recorded in the fields appropriate to each
schema. These commonly include a source URL, license or rights statement,
edition or translation information, processing details, and source-file
identity. Field names and availability vary by content type.

The [source and acknowledgment ledger](SOURCES.md) records principal sources,
requested credit, third-party notices, and unresolved rights questions for the
current release.

## Publishing rules

| Input source license | Published dataset license |
|---|---|
| Public domain / CC0 | CC0 |
| CC BY 4.0 (e.g. STEPBible) | CC BY 4.0 with attribution |
| CC BY-SA | Avoid (see below) |

**For older texts:** distinguish the underlying work from the exact translation,
edition, transcription, digitization, and structured database being used. A
public-domain original does not make every modern representation of it public
domain. Prefer a verified public-domain or CC0 source so the dataset stays CC0.

**If inputs are mixed:** use HF `license: other` + a `LICENSE.md` that documents the
provenance breakdown.

## License contamination rules

1. Check the rights and provenance fields required by the applicable schema
   before publishing any new dataset.
2. A single CC BY-SA source contaminates the entire dataset output if mixed in without
   isolation — use a separate dataset or exclude the source.
3. STEPBible data (CC BY 4.0) is permissible but requires attribution in the dataset card.

## Record-level provenance

Consult the applicable JSON schema for the authoritative fields. Depending on
content type, provenance may live in a `provenance` object and in work- or
edition-level metadata rather than three universal top-level fields.

Keeping that information with the data makes it possible to replace a source
with a better-licensed or better-attested edition without losing traceability.

## Decision record

Licensing strategy decided 2026-03-27 after identifying contamination risk across
multiple source categories (STEPBible, Wikisource transcriptions, digitisation-copyrighted
OCR). Provenance fields were added to all schema types as part of that decision.
