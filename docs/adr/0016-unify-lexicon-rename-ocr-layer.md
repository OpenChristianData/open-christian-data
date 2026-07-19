# ADR-0016: Unify the shared lexicon over the NSH OCR pipeline; rename the OCR-layer vocabulary

Status: accepted (2026-06-19); rename map extended and the three pending terms resolved 2026-06-25 (the one change beyond naming is ADR-0018).

## Decision

The NSH OCR pipeline (S1–S2.5) had grown its own vocabulary that collided with the 2026-05-14 dataset
lexicon — most damagingly `rendering` (two unrelated meanings) and `sidecar` (three meanings, and already
retired in the dataset half). We unify both halves under one `SHARED-LEXICON.md` and rename the OCR-layer
objects to the simplest distinct functional descriptions, anchored to the OCR-fusion and textual-criticism
literature where useful (see `../EzraOCR/docs/LEXICON_literature_crossref.md`). We change the human-facing language now
(lexicon, docs, comments) but keep the frozen schema ids, filenames, and stage numbers unchanged; the
physical rename and the stage renumber are a deferred migration driven by the map below.

## Considered options

- **Fork a second bounded-context lexicon (LEXICON-MAP.md)** so `rendering` could legitimately mean two
  things, one per context. Rejected: the collision is an accident of naming, not a real context split, and
  forking blesses the exact one-word-two-meanings failure the lexicon exists to prevent.
- **Physical rename now** (schema ids, filenames, enum/stage numbers, plus data migration). Rejected for
  now: multi-day, breaks every validator and the on-disk data, and the schemas were mid-flight on the
  leaf-rekey R-final work. Deferred to a dedicated migration session.

## Consequences

- The lexicon and all human-facing docs use the new names immediately; schema ids stay stable, so nothing
  breaks.
- A future migration session runs the rename map below as a mechanical find-and-replace plus data
  migration, and renumbers the stages into single cohesive units (no S2.5 half-step; split the compound
  stages S5 reviewer+LLM and S6 typography+publication).
- The three terms left **pending** on 2026-06-19 (the per-position word, the correction/consensus stage
  name, the S3–S6 taxonomy) were **resolved 2026-06-25** — see the extended rename map below and
  `SHARED-LEXICON.md`. The clean ten-stage taxonomy splits S5 (LLM Review + Human Review) and S6
  (Typography + Publication) and moves Typography before Human Review. The only change beyond naming —
  the LLM may propose unattested readings, gated by Human Review in v1 — is **ADR-0018**.

## Rename map (canonical name locked; physical rename pending)

| Old (id / name) | New canonical name | Physical-rename status |
|---|---|---|
| `sidecar` / `sidecar-page-v1` | page transcription | pending |
| per-engine volume `sidecar` folder | volume transcription bundle | pending |
| `sidecar-manifest` / `sidecar-manifest-v1` | transcription manifest | pending |
| `rendering` / `rendering-v1` | standardised transcription | pending |
| `word-confusion-table-v1` (WCT) | word alignment table | pending |
| stage S0 Ingest | clean stage 1 · Ingest | pending |
| stage S1 OCR | clean stage 2 · Transcription (gloss "OCR") | pending |
| stage S2 "pre-cleaning + rendering" | clean stage 3 · Normalisation and Standardisation | pending |
| stage S2.5 (half-step) | clean stage 4 · Alignment (half-step promoted) | pending |
| `candidate` (per-position cell) | candidate (KEPT) — `hypothesis` reserved for the post-correction system pick | n/a (no rename) |
| stage S3 "reconciler" | clean stage 5 · Reconciliation (umbrella; `consensus` kept narrow for the agreement-event) | pending |
| `corrected-page` "sidecar" label | reconciled page ("corrected" rejected — implies final; review/publication follow) | pending |
| stage S4 "weight matrix" | clean stage 6 · Engine Reliability Scoring (artifact: weight matrix) | pending |
| stage S5 "reviewer + LLM" (compound) | **split** → clean stage 7 · LLM Review + clean stage 9 · Human Review | pending |
| stage S6 "typography + publication" (compound) | **split** → clean stage 8 · Typography + clean stage 10 · Publication | pending |
| stage order S6 typography after review | typography moved **before** Human Review (so the reviewer ratifies it) | pending |
| `zone_type` / `wct_zone_type` (frozen) | canonical noun: **Geometry zone** (layout axis — where on the page, classified from page geometry) | n/a (prose discipline; enum frozen) |
| `region_class` (frozen) | canonical noun: **reliability class** (scoring axis — which trust bucket) | n/a (prose discipline; enum frozen) |
| OCR `attestations[]` (per-token per-engine reading) | **OCR engine attestation** (qualify vs dataset **rendering attestation**) | pending |
| `confidence_raw` (per-word, from engine) | canonical noun: **OCR confidence** (engine self-report; diagnostic only) | n/a (prose discipline) |
| `weight` (matrix cell value) | canonical noun: **engine reliability score** (the vote weight) | pending |
| `weight_confidence` (effective sample size) | canonical noun: **reliability-score maturity** (NOT "confidence") | pending |
| the weighted-vote method / `resolution_path` + `weight_cells_used` | **weighted vote** (method) + **resolution path** (per-token receipt) | n/a (concepts; fields kept) |
