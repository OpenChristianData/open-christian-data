# ADR-0006: Scans stay local; page-level mapping required, bounding boxes opportunistic

**Status:** Accepted (2026-05-15)

## Context

The Reviewer needs visual access to original scan images during structural review (is that a heading or body text?) and during textual review of unusual or mangled words. The architectural question is where scans live, how they reach the Reviewer, and how finely the block-to-scan mapping is recorded.

Storage options ranged from "include scans in the published dataset" (large; bandwidth-heavy for consumers who only want text) through "companion HuggingFace dataset for scans" through "URL-referenced only, no local copy."

Mapping options ranged from "bounding box per token" (precise; high schema cost) through "bounding box per block" (moderate) through "page number per block" (cheap; coarse).

## Decision

**Scans stay local-only.** They live in `scans/<rendering_id>/p<page>.jp2` on the local filesystem, gitignored, never published. The published dataset is text-only.

**Block-to-scan mapping is page-level required; bounding boxes are opportunistic.** Each block records `source_pages: [{rendering_id, page_number, bbox?}]`. Page number is required (or `null` with a note for renderings that have no page info, e.g. CCEL ThML structured XML). Bounding boxes are preserved **when the parser produces them as a natural side effect** — Tesseract hOCR and ALTO XML both emit per-word bboxes — and left `null` otherwise. We do not invest effort to *create* bbox data we don't have; we do not discard bbox data we do.

The Reviewer UI's split-pane view scrolls the scan to the relevant page when a block is in focus, and highlights the bbox region when bbox data is available. Without bbox, the human eye locates the block on the page — still fast at page level.

## Consequences

**Positive**
- The published dataset stays lean. Consumers who want text get text; no JP2 images they did not ask for.
- No companion-repo publishing infrastructure to maintain.
- The Reviewer UI implementation stays simple. Page-level mapping is the floor; bbox-highlight is added only where the parser already provides bbox, so the work is "render an overlay rectangle when the field is non-null" rather than "compute bbox from scratch."
- Storage is local, addressable with normal disk planning. No bandwidth or HuggingFace storage costs.
- Scans are working aids, not data products. Treating them that way preserves the distinction between what we publish and what we use to produce what we publish.

**Negative**
- Scans are not available to readers of the published dataset. Anyone who wants to verify a reconciliation decision against the scan must re-acquire the scan from its source.
- Bounding-box-level visual review is unavailable for renderings whose parsers do not produce bbox data (CCEL ThML, plain text). For those, the human eye locates the block on the page — still fast at page level. For renderings that do produce bbox (Tesseract hOCR, ALTO XML), the Reviewer UI highlights the region.
- Community contribution involving scan-verification is not supported under the local-only constraint. A future ADR could lift this; today's constraint reflects the project's text-first scope.

## Alternatives considered

- **Scans in the main published dataset.** Rejected. Tens of gigabytes for a text-focused dataset penalises consumers who only want text. The HuggingFace storage profile is wrong for binary scan archives at this scale.
- **Companion HuggingFace dataset for scans.** Rejected. Doubles publishing infrastructure for a non-essential output; the project scope excludes scans as a published product entirely.
- **URL-referenced scans, fetched on demand.** Rejected. Brittle: external URLs change; sources go offline. For a PD-anchored dataset whose value rests on citation integrity, depending on external hosts forever is risky.
- **Per-token bounding boxes created from scratch** (e.g. running layout analysis on every scan to derive bboxes for ThML or plain-text renderings). Rejected on the principle that the human eye does this work fine at page level; the effort to derive bboxes for renderings whose parsers don't produce them is not justified.
- **Discarding bbox data when the parser does produce it** (e.g. flattening Tesseract hOCR to text-only). Rejected — the data is free; preserving it lets the Reviewer UI highlight regions for renderings that have it, with no extra parser work. The opportunistic-bbox policy is captured in the Decision above.
