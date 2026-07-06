# OCR scanner — source-agnostic OCR-error triage

Location: `build/tools/ocr_scanner/` in the OCD repo.

## Architecture

| File | Responsibility |
|---|---|
| `models.py` | `Candidate`, `ScanResult`, `REASON_CODES` (single source of truth for tier mapping) |
| `patterns.py` | `DetectorContext`, `DictionaryStack`, all detectors (Tier 1 + Tier 2 + Tier 3 + ccel_thml) |
| `scanner.py` | `load_config`, `scan_entries`, `_DETECTORS_BY_PATTERN_SET` + `_TIER3_DETECTORS_BY_PATTERN_SET` dispatch |
| `report.py` | `write_report` (JSON + Markdown pair, one per scan) |
| `apply_approved_corrections.py` | Reads approvals, writes to `corrections/<source>.json`. `DRY_RUN = True` by default |
| `selftest.py` | 20/20 passes |
| `configs/schaff-herzog.json` | whitelist_terms ~40 entries (incl. 20 citation abbrevs), tier3_enabled=False |
| `configs/spurgeon-mtp.json` | pattern_set: "html_transcription" (clean HTML, no OCR detectors) |
| `configs/ccel-thml-placeholder.json` | Placeholder |
| `corrections/schaff-herzog.json` | 3 bootstrap corrections (THE0T0K0S, THE0T0K08, THE ATINES) + 789 LLM-applied corrections |
| `lexicons/theological_seed.txt` | Empty placeholder (not yet seeded from Naves) |

## Key design facts

- `DictionaryStack(whitelist_terms: set, lexicon_terms: Optional[set] = None, enable_enchant: bool = True)` — takes `set`s, not file paths
- `_strip_for_whitelist()` strips `()[]{}.,;:!?` from token before whitelist_terms check; dual-form check prevents suppression miss for tokens like `(MPL,`
- Tier 3 detectors gated by `tier3_enabled` in config; `ligature_ae_loss` demoted to Tier 3 (was Tier 1 — 0% precision on SH)
- `detect_apparent_space_insertion` length bound 3..12
- `whitelist_pattern` validation errors raise `ValueError` early (silent swallow fixed)

## State as of 2026-04-28

**Test count:** 518 tests passing (`py -3 -m pytest -v`). Selftest: 20/20.

**Corpus scan baseline (2026-04-22):**
- Total: 6,322 | Tier 1: 3,121 | Tier 2: 3,201 | Tier 3: 0 (gated off)

**2026-04-23 suppression fixes (commit f05146c):**
- Added `^[IVXLCDM]+\.?$` Roman numeral pattern (covers XL, IL, DC etc.)
- Added `^[A-Z][,;:]$` pattern (covers ~1,200 single-letter+comma author initials)
- Added `DU`, `LA`, `LE`, `IB`, `OP` to whitelist_terms
- Fixed `detect_unusual_bigram` to produce `reason="unusual_bigram"` candidates (extracted `_detect_joined_word` helper)
- Confirmed Tier 2 after suppression: 1,941 (from 3,201, −1,260); total: 5,059

**LLM triage pipeline (2026-04-28) — complete:**
- All 5,059 SH candidates classified by NVIDIA Llama 3.3 70B (primary) + Gemini 2.5 Flash (97 uncertain cases)
- Results: 2,619 error / 2,343 not_error / 53 still uncertain after both models
- 789 corrections applied (1 same-fix duplicate skipped); 792 total in `corrections/schaff-herzog.json`
- `llm_triage/human_review.csv`: 1,926 rows (1,873 confirmed errors without fix + 53 uncertain)
- `llm_triage/suggested_whitelist.txt`: 1,511 not_error tokens to curate into config whitelist_terms
- Future directions doc: `FUTURE_DIRECTIONS.md`
- LLM provider reference: `~/.claude/projects/.../memory/reference_free_llm_apis.md`

**Pre-existing Opus review issues (partial):**
- I1: Golden fixture confidence values — no automated sync (not actioned)
- I2: RESOLVED — `detect_unusual_bigram` reason label fixed
- I3: `reason` column in dispatch table is decorative — not actioned
- I4: `whitelist_patterns` field has no JSON Schema validation — not actioned

## What's next

1. **Curate `suggested_whitelist.txt`** — review 1,511 not_error tokens, add legitimate ones to `configs/schaff-herzog.json` `whitelist_terms`.
2. **Work through `human_review.csv`** — open in Excel, set `approve = y` on rows to correct, re-run `apply_approved_corrections.py` with the CSV.
3. **Check all-caps orphan list-marker case** — `short_allcaps_orphan` (most uncertain category): could these be alphabetical list markers (A. point B. point)? Add to classifier prompt if so.
4. **Run pipeline on next source** — scanner is source-agnostic; write config, scan, triage.

## Source expansion strategy (decided 2026-04-26)

After SH review is proven end-to-end, expand one source at a time. No bulk multi-source scans. T6 batches and NPNF1 are unscanned; `ccel-thml` config is a placeholder.

## Ensemble OCR — deferred

Full analysis in `FUTURE_DIRECTIONS.md`. Targeted re-OCR of error-region images is architecturally sound but needs bounding box metadata from original scan ingestion (not currently stored).
