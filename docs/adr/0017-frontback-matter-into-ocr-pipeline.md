# ADR-0017: Front/back matter enters the NSH OCR pipeline, tagged by edition section

Status: accepted (2026-06-20)

## Context

The NSH pipeline was built body-only: `nsh_leaf_model.ocr_input` returned `kind == "body"` leaves,
`page_order.volume_image_paths` fed only body images to the S1 engines, and front/back matter (title
pages, prefaces, contributor lists, indices, appendices) never reached OCR, S2, the word-confusion
table (WCT), or the gold-free corrector. The working invariant was that front/back stay out of the
pipeline — they were neither imaged uniformly nor positioned in the leaf sequence.

Lane B changed the substrate. Phase 0–3 of the leaf-sequence + edition-page-key program gave every
physical leaf a position, an image (where non-blank), and a required `edition_page_key`
(`{section, anchor, ordinal}`, `section ∈ {front_matter, body, back_matter}`) on all four leaf-keyed
schemas. Phase 2a discarded operator-classified junk front/back leaves and recorded the image-less
ones as blanks, leaving ~203 kept front/back leaves that have a real image AND real content. The
maintainer's goal: get the corrected text of those pages too — there is no reason to treat a
contributor list or a preface differently from body prose.

## Decision

Front/back matter that is kept (present image, real content, not discarded, not blank) **enters the
full pipeline — S1 → S2 → WCT → reconciler → corrector — exactly like body pages, distinguished only
by `edition_page_key.section`.** Concretely:

- The OCR-input gateway `page_order.volume_image_paths(vol_dir, include_front_back=False)` gains the
  opt-in; the NSH S1 runners pass `include_front_back=True`, so the next scheduled OCR run picks up the
  kept front/back leaves (the currentness gates skip already-covered body pages — no re-OCR).
- The body/non-body distinction travels inline on every record via the already-required
  `edition_page_key.section` — **no new `leaf_kind` field was added** (it would have duplicated
  `section`).
- Aggregates that pool pages stay body-scoped by construction: `ocr_inventory`'s denominator and
  `verify_leaf_keying`'s `body_leaf_nums` both derive from body-only `ocr_input`, so front/back never
  dilute a body coverage figure (they surface as `extra` / a dedicated front/back bucket).

This **reverses the prior "front/back stay out of the WCT" invariant.**

## Considered options

- **Keep front/back out of the pipeline** (status quo). Rejected: their corrected text has real value
  (indices, contributor attributions, prefaces), and the edition-key substrate now lets them be
  reconciled without being confused for article body.
- **Admit them as a separate product / separate corrector lane.** Rejected: it duplicates the whole
  S1→corrector stack for pages that the existing stack handles once `section` tags them; the earlier
  separate-product proposal (`prompts/2026-06-17-1345-…`) was superseded.
- **Add a new `leaf_kind` marker** to carry body-vs-non-body. Rejected: `edition_page_key.section`
  already carries it on every leaf-keyed record; a second field is drift waiting to happen.

## Why this is safe (the reversal does not weaken the corrector's guarantees)

- **Per-page leaf-keying.** WCT and corrector output are keyed per page (`canonical_leaf_id` /
  `edition_page_key`); a noisy front/back page cannot corrupt a body page's reconciliation.
- **Protected-class routing is correct behavior, not exclusion.** Proper names in a contributor list
  route to human review (HR5); the L0 multi-engine consensus reading still stands, it just carries a
  "verify" flag rather than a "machine fixed this" claim — exactly the desired behavior for scholar
  names.
- **No measurement pollution.** The corrector's certification rates are measured on the JE oracle (a
  separate text with a human diplomatic transcription), stratified by token class/script/typography;
  NSH front matter never enters that measurement.
- **Gold-free fail-safe.** A two-column contributor list is an unproven layout regime for the WCT
  geometry aligner, but the corrector fails safe — a noisy WCT yields review flags, never false
  corrections. Tagging by `section` keeps front-matter quality separately observable.

## Consequences

- The OCR-input gateway is the single front/back-capable seam; the next OCR run OCRs the ~203 kept
  leaves incrementally (no body re-OCR).
- The completeness gate's front/back half is now exercised (front/back coverage/orphan accounting in
  `verify_nsh_page_accounting`), not stubbed.
- Front/back are **not published** with this change — they live in the gitignored OCR stores until a
  separate publish step decides their dataset treatment, so the published data shape (and `README.md`)
  is unchanged.
- Phase 2c (real-word-ratio noise sweep over the kept leaves) is a gated follow-up that can only run
  after the next OCR pass produces their text.
- `../EzraOCR/docs/NSH_PROJECT_STATE.md` invariant 8 / the milestone banner are updated to record that front/back
  now enter the pipeline, tagged by `section`.
