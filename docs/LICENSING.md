# OCD Licensing

## Default target: CC0

OCD datasets default to CC0 (Creative Commons Zero — public domain dedication). Every
record carries `source_license`, `source_url`, and `translation_year` provenance fields
to enable per-record license tracking.

## Publishing rules

| Input source license | Published dataset license |
|---|---|
| Public domain / CC0 | CC0 |
| CC BY 4.0 (e.g. STEPBible) | CC BY 4.0 with attribution |
| CC BY-SA | Avoid (see below) |

**For pre-1928 texts:** a PD original always exists somewhere. A CC BY-SA on Wikisource
reflects their transcription effort, not the underlying text. Prefer a PD source so the
dataset stays CC0.

**If inputs are mixed:** use HF `license: other` + a `LICENSE.md` that documents the
provenance breakdown.

## License contamination rules

1. Check `source_license` before publishing any new dataset.
2. A single CC BY-SA source contaminates the entire dataset output if mixed in without
   isolation — use a separate dataset or exclude the source.
3. STEPBible data (CC BY 4.0) is permissible but requires attribution in the dataset card.

## Per-record provenance fields

`source_license` — SPDX identifier (e.g. `CC0-1.0`, `CC-BY-4.0`) or `public-domain`
`source_url` — canonical URL of the source file used
`translation_year` — year of the specific translation used (for edition disambiguation)

The provenance fields allow upgrading datasets to CC0 later when better-licensed sources
are found without losing traceability.

## Decision record

Licensing strategy decided 2026-03-27 after identifying contamination risk across
multiple source categories (STEPBible, Wikisource transcriptions, digitisation-copyrighted
OCR). Provenance fields were added to all schema types as part of that decision.
