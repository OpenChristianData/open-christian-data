# T8-1 Claude Review Report

## Executive Summary

- Corrected a major source-selection error from the first pass: the IA fallback `martinlutheronth00luthuoft` is Edward Thomas Vaughan, not the requested Henry Cole translation.
- Replaced the Bondage output with a Cole-based source from Covenanter's public-domain web transcription.
- Added source-evidence guards in `build/parsers/gutenberg_systematics.py` so named translator/year evidence must exist in the cached raw source before parsing.
- Kept provenance at the resource metadata level because `schemas/v1/structured_text.schema.json` does not allow provenance on section records.
- Validation is clean for both Luther outputs and for `validate.py --all`; full pytest still has two non-Luther failures.

## Files Changed For T8-1

- `build/parsers/gutenberg_systematics.py`
- `tests/test_luther_gutenberg_systematics.py`
- `data/structured-text/luther-bondage-of-the-will.json`
- `data/structured-text/luther-commentary-on-galatians.json`
- `sources/structured-text/luther-bondage-of-the-will/config.json`
- `sources/structured-text/luther-commentary-on-galatians/config.json`
- `data/authors/registry.json`
- `research/prompts/t8-1-census.md`
- `docs/T8-1_CLAUDE_REVIEW_REPORT.md`
- `LAST_SESSION.md`
- `raw/gutenberg/pg1549.txt`
- `raw/gutenberg/luther-bondage-of-the-will-cole-covenanter.txt`

Note: `raw/`, `research/prompts/`, and `LAST_SESSION.md` are ignored by git in this repo. This report is duplicated under `docs/` so Claude can review it through normal repo-visible files.

## Source Decisions

### Bondage Of The Will

Original prompt asked for the Cole 1823 translation and suggested PG first, IA fallback if PG was missing or poor.

What happened:

- PG search did not locate a usable official Gutenberg ebook for *Bondage of the Will*.
- First-pass IA fallback `martinlutheronth00luthuoft` looked plausible by title/year but was actually Edward Thomas Vaughan.
- Evaluation caught that translator mismatch.
- I rejected that IA source and replaced it with Covenanter's web transcription of the Henry Cole translation.

Current source:

- Index: `https://www.covenanter.org/reformed/2015/7/8/martin-luthers-book-concerning-the-bondage-of-the-will`
- Cached file: `raw/gutenberg/luther-bondage-of-the-will-cole-covenanter.txt`
- SHA-256: `5e3ce6432bd668596cca5b9ffbdfa8cb8c024dc9dbc4ab5ed109324e32e5400a`
- Required source evidence now enforced:
  - `HENRY COLE.`
  - `London, March, 1823.`
  - `Conclusion (Sections 167-168)`

Decision for Claude to review: using a non-PG/non-IA web transcription is a deliberate correction to satisfy the edition requirement. If the original source policy must be stricter than the translator requirement, this should be challenged.

### Commentary On Galatians

Current source:

- PG #1549: `https://www.gutenberg.org/ebooks/1549`
- Cached file: `raw/gutenberg/pg1549.txt`
- SHA-256: `ed00941bbe9e65b12c6619ea8a756ac053c44ec0a0c88761a83b8dff8d9a59bd`
- Required source evidence now enforced:
  - `Translator: Theodore Graebner`
  - `Translated by Theodore Graebner`
  - `CHAPTER 6`

## Parser Decisions

I extended `build/parsers/gutenberg_systematics.py` instead of adding a new parser file.

Reasons:

- Both works are `structured_text` treatises.
- The existing parser already handles analogous PG/IA/systematics prose workflows.
- The real issue was source-specific boundary detection, not a different output schema.

Bondage parser strategy:

- Parses the cached Cole transcription by source page groups.
- Emits 13 top-level sections:
  - Preface by the Translator
  - Introduction
  - Section 1
  - Sections 2-6
  - Sections 7-8
  - Sections 9-27
  - Sections 28-40
  - Sections 41-75
  - Sections 76-134
  - Sections 135-166
  - Conclusion
  - Appendix: Luther's Judgment of Erasmus
  - Appendix: Luther to Nicolas Armsdoff

Galatians parser strategy:

- Uses PG wrapper stripping.
- Emits 8 top-level sections:
  - Preface
  - From Luther's Introduction, 1538
  - Chapter 1
  - Chapter 2
  - Chapter 3
  - Chapter 4
  - Chapter 5
  - Chapter 6

## Provenance Decision

The prompt asked for provenance fields on every record. The current `structured_text` schema is resource-level provenance on `meta.provenance`; section nodes do not allow arbitrary provenance fields. Adding provenance to every section would fail schema validation unless the schema is changed.

Decision taken:

- Keep provenance at `meta.provenance`.
- Include `source_type`, `source_file`, and `translator` there.
- Test that provenance is present and non-empty at the resource level.

Claude review question: should OCD add a schema-supported `provenance_override` or section-level provenance field for `structured_text`, or should acquisition prompts stop asking for per-record provenance on recursive section trees?

## Tests Added

`tests/test_luther_gutenberg_systematics.py` now covers:

- Section counts for both works.
- No `Project Gutenberg` or `archive.org` boilerplate in output text blocks.
- Required provenance fields at `meta.provenance`.
- Schema enum guards for Luther config values.
- Raw source evidence guard for named translator/year markers.

## Verification Results

Passed:

- `py -3 -m py_compile build\parsers\gutenberg_systematics.py tests\test_luther_gutenberg_systematics.py`
- `py -3 build\validate.py data\structured-text\luther-bondage-of-the-will.json`
  - 0 errors, 0 warnings
- `py -3 build\validate.py data\structured-text\luther-commentary-on-galatians.json`
  - 0 errors, 0 warnings
- Focused text/provenance scan:
  - Bondage: 13 sections, 0 text boilerplate hits, translator Henry Cole, source_type `web_transcription`
  - Galatians: 8 sections, 0 text boilerplate hits, translator Theodore Graebner, source_type `project_gutenberg`
- Identity-protection scan across touched T8-1 files:
  - no forbidden identity strings found
- `py -3 -m pytest tests\test_luther_gutenberg_systematics.py -q`
  - 5 passed
- `py -3 build\validate.py --all`
  - 1256 files validated
  - 0 total errors
  - 111 warnings

Full pytest:

- `py -3 -m pytest -q`
  - 1320 passed
  - 2 failed

Known non-Luther failures:

- `tests/test_apply_corrections.py::test_apply_refuses_to_overwrite_existing`
- `tests/test_hooker_gutenberg_systematics.py::test_parse_hooker_ignores_selected_editorial_apparatus`

## Things Claude Should Challenge

1. Whether the Covenanter transcription is acceptable despite the prompt's PG/IA source framing.
2. Whether a web transcription should use `source_type: web_transcription`, or whether OCD wants a stricter source-type vocabulary.
3. Whether the two appendices belong in `luther-bondage-of-the-will.json` or should be excluded/deferred.
4. Whether page-group sections are granular enough for the Cole translation, or whether a later parser should split all 168 numbered sections.
5. Whether prompt templates should stop saying “provenance on every record” for `structured_text` until the schema supports it.

## Rule Suggestion

RULE: When an acquisition task names a specific edition, translator, or publication year, the parser config must include a source-evidence assertion before any output write, verified with a command like `py -3 -c "from pathlib import Path; text=Path('raw/source.txt').read_text(encoding='utf-8', errors='replace'); print('Henry Cole' in text, '1823' in text)"` and the expected output must be `True True` for the named facts. Without this, schema validation can pass while the dataset silently ships a different public-domain edition.

## Commit Note

No git staging or commit was performed. The repo `AGENTS.md` forbids VCS write commands from Codex in this workspace.
