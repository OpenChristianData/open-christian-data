# Claude Review Handoff: Text Accuracy and Reviewability Phases 3-8

Date: 2026-05-06
Repository: `C:\ocd\`

## Decision Brief

- I implemented the remainder of `prompts/2026-05-06-text-accuracy-reviewability-next-phases.md` through Phase 8. Phase 8 is the final phase in that prompt file.
- The work adds reviewability tooling only. It does not rewrite final `data/` JSON, does not download sources, and does not apply corrections.
- Focused phase tests pass: `63 passed` with `python -m pytest -p no:cacheprovider`.
- Full repo pytest is blocked before test execution by local missing `tzdata`: `ZoneInfoNotFoundError: 'No time zone found with key Australia/Melbourne'`.
- Main review focus: conservative semantics. Check that warning severity, confidence tier rules, witness registry fields, and ledger statuses are neither overclaiming nor too loose.

## Prompt Contract

Source prompt:

```text
prompts/2026-05-06-text-accuracy-reviewability-next-phases.md
```

Executed sections:

- Phase 3: Implement Shared Review Warnings and Queue
- Phase 4: Implement Historical Lexicon and Variant Detection
- Phase 5: Implement Source Witness Registry
- Phase 6: Implement OCR Ensemble Comparison Prototype
- Phase 7: Implement Correction Ledger and Review Status
- Phase 8: Implement Confidence Tiers and Reference-Grade Report

Phase 2 files already existed when this work started. I integrated Phase 5 registry metadata into the Phase 2 comparison tool.

## Files Added or Changed

Core libraries and tools:

- `build/lib/review_warnings.py`
- `build/lib/historical_lexicon.py`
- `build/tools/render_review_html.py`
- `build/tools/compare_text_witness.py`
- `build/tools/witness_registry.py`
- `build/tools/ocr_ensemble_compare.py`
- `build/tools/correction_ledger.py`
- `build/tools/text_confidence_report.py`
- `sources/witnesses/registry.json`

Tests:

- `tests/test_review_warnings.py`
- `tests/test_render_review_html.py`
- `tests/test_compare_text_witness.py`
- `tests/test_historical_lexicon.py`
- `tests/test_witness_registry.py`
- `tests/test_ocr_ensemble_compare.py`
- `tests/test_correction_ledger.py`
- `tests/test_text_confidence_report.py`

Generated review artefacts from smoke checks:

- `review/commentaries/adam-clarke/2-john/index.html`
- `review/commentaries/adam-clarke/2-john/review-queue.json`
- `review/commentaries/adam-clarke/2-john/text-confidence.json`
- `review/commentaries/adam-clarke/2-john/text-confidence.md`

## Phase 3: Shared Review Warnings and Queue

What changed:

- Added `ReviewWarning` dataclass with:
  - `code`
  - `severity`
  - `message`
  - `entry_id`
  - `field`
  - `evidence`
- Moved renderer warning logic into `build/lib/review_warnings.py`.
- Added `warning_counts_by_severity`.
- Added queue JSON output to `render_review_html.py` via `--queue-json`.

Implemented warning checks:

- duplicate `entry_id`
- missing `entry_id`
- missing or blank `commentary_text`
- verse entry missing `verse_range_osis`
- intro entry with unexpected `verse_range_osis`
- replacement character
- possible broken hyphenation
- odd number of double quotes
- repeated paragraph within the same file
- suspiciously short commentary entry
- suspiciously long commentary entry
- `word_count` mismatch using `text.split()`
- `cross_references` present but not a list
- non-string cross reference
- summary present but `summary_review_status` missing or withheld
- likely OCR junk sequences, using conservative punctuation/junk patterns only

Decisions:

- Missing identifiers/text are `error`.
- Structural and text-integrity suspicion checks are `warning`.
- Short/long text and lexicon findings are `info`.
- Queue timestamps use `datetime.now(timezone.utc).isoformat()`.
- `--queue-json` is restricted to single-file rendering. This avoids ambiguous output when rendering a directory.

Review concerns:

- Thresholds are intentionally simple: short `< 3` words, long `> 1500` words.
- The repeated paragraph check normalises whitespace only. It does not fuzzy-match.
- `word_count` uses simple whitespace tokenisation because the prompt specified simple whitespace tokenisation.

## Phase 4: Historical Lexicon and Variant Detection

What changed:

- Added `build/lib/historical_lexicon.py`.
- Added `LexiconEntry` and `LexiconMatch`.
- Integrated matches into `review_warnings.py` as info-level `historical_lexicon_variant` warnings.

Seed lexicon:

- `Esaias -> Isaiah`
- `Elias -> Elijah`
- `Noe -> Noah`
- `Apocalypse -> Revelation`
- `Canticles -> Song of Songs`
- `shew -> show`
- `shewed -> showed`
- `connexion -> connection`
- `publick -> public`
- `compleat -> complete`
- `Chrysostome -> Chrysostom`
- `Chrysostom -> Chrysostom`
- `Jeremias -> Jeremiah`

Decisions:

- Matching is exact word-boundary matching with case-insensitive detection.
- The reported `surface` preserves the source text exactly as found.
- `Apocalypse` and `Canticles` require biblical-book context:
  - preceding context like `Book of`
  - or following reference context such as `1:1`
- The lexicon never rewrites source text.

Review concerns:

- `Chrysostom -> Chrysostom` is included as a patristic-name authority signal even though normalised is identical. Claude should decide whether that is useful or noisy.
- The biblical-book context heuristic is deliberately narrow. It will miss valid cases where context is less explicit.

## Phase 5: Source Witness Registry

What changed:

- Added `sources/witnesses/registry.json` as the default registry location.
- Added `build/tools/witness_registry.py`.
- Updated `build/tools/compare_text_witness.py` to accept registry metadata by `--witness-id`.

Registry record fields:

- `witness_id`
- `related_resource_id`
- `related_work_title`
- `author`
- `witness_title`
- `source_url`
- `source_type`
- `rights_status`
- `edition_note`
- `provider`
- `local_path`
- `notes`

Supported source types:

- `scan`
- `OCR`
- `HTML`
- `EPUB`
- `hand-corrected text`
- `transcription`
- `unknown`

Supported rights statuses:

- `public-domain-source`
- `comparison-only`
- `unknown`

Decisions:

- Registry format is:

```json
{
  "witnesses": []
}
```

- The real registry starts empty. Test fixtures carry synthetic examples.
- Registry stores metadata only. It does not copy witness text.
- CLI overrides remain possible when using `--witness-id`.

Review concerns:

- `local_path` is validated as string or null, but existence is not checked. That is intentional because some witnesses are remote-only candidates.
- The registry currently has no JSON Schema. A schema may be worth adding once the format stabilises.

## Phase 6: OCR Ensemble Comparison Prototype

What changed:

- Added `build/tools/ocr_ensemble_compare.py`.

Capabilities:

- Accepts two or more local OCR text files.
- Optional repeated `--label`.
- Optional `--output-html`.
- Optional `--output-json`.
- Preserves source snippets in reports.
- Escapes HTML output.
- Emits JSON disagreement records.

Classification:

- `whitespace-only`
- `case-only`
- `punctuation-only`
- `likely OCR character confusion`
- `content disagreement`

Decisions:

- Whole-text normalisation checks run first.
- If whole-text classification cannot explain the difference, token-position comparison runs against all sources.
- OCR skeleton uses a small map:
  - `rn -> m`
  - `1 -> l`
  - `0 -> o`
  - `5 -> s`
  - `8 -> b`
  - `vv -> w`

Review concerns:

- Token-position alignment is intentionally primitive. It is useful for prototype review, not edition-grade collation.
- Insertions/deletions can shift later token comparisons. A future version should use sequence alignment zones.

## Phase 7: Correction Ledger and Review Status

What changed:

- Added `build/tools/correction_ledger.py`.

Ledger format:

- JSONL, one correction record per line.
- Intended path pattern: `review/corrections/<resource-id>.jsonl`.

Record fields:

- `correction_id`
- `resource_id`
- `entry_id`
- `field`
- `original_value`
- `proposed_value`
- `correction_type`
- `reason`
- `evidence_source`
- `evidence_quote_or_locator`
- `reviewer`
- `status`
- `confidence`
- `created_at`
- `updated_at`

Supported statuses:

- `proposed`
- `approved`
- `rejected`
- `applied`

Supported correction types:

- `text`
- `structure`
- `metadata`
- `witness-note`

Decisions:

- Timestamps must be timezone-aware.
- Confidence must be numeric from 0 to 1.
- The tool validates and reports. It does not apply corrections to final data.
- Optional HTML rendering escapes values.

Review concerns:

- `original_value` and `proposed_value` are required strings. This is simple and diffable, but structure corrections may eventually need object values or JSON pointers.
- The ledger has no schema yet. Like witness registry, it may deserve a schema after one or two real use cases.

## Phase 8: Confidence Tiers and Reference-Grade Report

What changed:

- Added `build/tools/text_confidence_report.py`.

Outputs:

- JSON report
- Markdown report

Evidence read locally:

- commentary JSON metadata/provenance
- review warning counts from a queue JSON when supplied, otherwise live warning generation
- witness registry records
- OCR ensemble JSON
- correction ledger records

Tier rules:

- `raw-imported`: valid commentary JSON with provenance but no comparison/review evidence.
- `machine-compared`: at least one witness record exists.
- `ocr-ensemble`: OCR ensemble evidence exists.
- `human-reviewed`: approved or applied correction/review records exist.
- `reference-grade`: human-reviewed plus provenance, at least one witness, zero error warnings, and at most five warning-level warnings.

Decisions:

- The report does not store the tier back into `data/`.
- The report explicitly says it does not certify textual correctness.
- `reference-grade` does not require OCR ensemble evidence. I treated OCR ensemble as valuable but not always necessary when a witness plus human review exists.

Review concerns:

- The prompt says reference-grade requires human-reviewed plus low warnings plus provenance and at least one usable witness. It does not explicitly require OCR ensemble, so I excluded OCR from that hard gate. Claude should confirm this interpretation.
- Witness evidence currently means registry records. Phase 2 HTML reports are not parsed for evidence.
- Approved/applied corrections are used as human-review evidence. A dedicated review-status ledger may eventually be cleaner.

## Verification Performed

Compile:

```text
python -m py_compile build/lib/historical_lexicon.py build/lib/review_warnings.py build/tools/render_review_html.py build/tools/compare_text_witness.py build/tools/witness_registry.py build/tools/ocr_ensemble_compare.py build/tools/correction_ledger.py build/tools/text_confidence_report.py tests/test_historical_lexicon.py tests/test_review_warnings.py tests/test_render_review_html.py tests/test_compare_text_witness.py tests/test_witness_registry.py tests/test_ocr_ensemble_compare.py tests/test_correction_ledger.py tests/test_text_confidence_report.py
```

Focused phase tests:

```text
python -m pytest -p no:cacheprovider tests/test_compare_text_witness.py tests/test_review_warnings.py tests/test_render_review_html.py tests/test_historical_lexicon.py tests/test_witness_registry.py tests/test_ocr_ensemble_compare.py tests/test_correction_ledger.py tests/test_text_confidence_report.py -v
```

Result:

```text
63 passed
```

Smoke checks:

- Historical lexicon direct scan over `Esaias shewed this to Chrysostome.`
- Witness registry validation of `sources/witnesses/registry.json`
- OCR ensemble comparison of `modern mercy` vs `modem mercy`
- Correction ledger validation and HTML rendering with a synthetic approved record
- Confidence report against `data/commentaries/adam-clarke/2-john.json`

Full repo pytest:

```text
python -m pytest -p no:cacheprovider
```

Result:

```text
collected 1259 items / 1 error
```

Blocker:

```text
ZoneInfoNotFoundError: 'No time zone found with key Australia/Melbourne'
```

The error occurs while collecting `tests/test_gutenberg_anglican.py`, before the full suite runs.

## Data Safety Check

I ran:

```text
git diff -- data/commentaries data/authors/registry.json
```

It produced no diff.

I did not intentionally edit final `data/` JSON. Existing unrelated dirty/untracked `data/structured-text` files were already present in the worktree and are outside this task.

## Known Worktree Notes

Git status showed permission warnings for the user-global git ignore:

```text
warning: unable to access '[user]/.config/git/ignore': Permission denied
```

Relevant status at the end showed new/modified reviewability files, generated review artefacts, and no targeted `data/commentaries` or `data/authors/registry.json` diffs.

## Reviewer Questions for Claude

1. Are the `ReviewWarning` severities appropriate?
   - Especially whether missing `entry_id` and missing text should be `error`, and whether lexicon findings should stay `info`.

2. Are the historical lexicon matches too noisy?
   - Pay special attention to `Chrysostom -> Chrysostom`.

3. Is `reference-grade` too permissive without requiring OCR ensemble evidence?
   - I read the prompt as not requiring OCR if witness and human review evidence exist.

4. Should witness registry and correction ledger get JSON Schemas now?
   - I left them as validated tool formats to avoid premature schema churn.

5. Should `text_confidence_report.py` parse Phase 2 comparison reports?
   - Current implementation only uses registry metadata as witness evidence.

6. Is token-position OCR comparison good enough for the prototype?
   - It meets the phase prompt but will misalign after insertions/deletions.

## Rule Suggestions

Suggested project rules for future OCD work:

1. For any reviewability or text-accuracy tool, final `data/` JSON must remain read-only unless the prompt explicitly asks for parser output regeneration or correction application.

2. Any tool that claims review status, confidence, or source quality must include explicit missing-evidence fields and must not use language that certifies textual correctness from automated checks alone.

3. Any registry or ledger format introduced under `sources/` or `review/` must include a validator and tests before real records are added.

4. Any comparison against external witness text must store metadata and derived reports only. Do not copy comparison-only witness text into final source data.

5. For Windows Codex runs in this repo, use `python -m pytest -p no:cacheprovider` by default because the cache provider and temp/cache paths can fail under sandbox permissions.

6. If full pytest fails during collection on missing `tzdata` / `ZoneInfo`, report it as an environment blocker and still run focused tests for the touched files.

7. Generated review artefacts under `review/` should be treated as inspection outputs. Before committing, decide explicitly whether each generated artefact belongs in source control or should be regenerated locally.

## Suggested Next Review Command Set

```text
python -m py_compile build/lib/historical_lexicon.py build/lib/review_warnings.py build/tools/render_review_html.py build/tools/compare_text_witness.py build/tools/witness_registry.py build/tools/ocr_ensemble_compare.py build/tools/correction_ledger.py build/tools/text_confidence_report.py
python -m pytest -p no:cacheprovider tests/test_compare_text_witness.py tests/test_review_warnings.py tests/test_render_review_html.py tests/test_historical_lexicon.py tests/test_witness_registry.py tests/test_ocr_ensemble_compare.py tests/test_correction_ledger.py tests/test_text_confidence_report.py -v
python build/tools/text_confidence_report.py data/commentaries/adam-clarke/2-john.json --review-queue review/commentaries/adam-clarke/2-john/review-queue.json --output-json review/commentaries/adam-clarke/2-john/text-confidence.json --output-md review/commentaries/adam-clarke/2-john/text-confidence.md
```
