# Code Reviews — Open Christian Data

## 2026-04-16 -- OCR scanner Phase 2 Opus review

Files reviewed: `models.py`, `patterns.py`, `scanner.py`, `report.py`, `selftest.py`, `apply_approved_corrections.py`

Violations found:
- PY-07 in `scanner.py`: `REASON_CODES` imported but never used -- removed
- PY-07 in `selftest.py`: `REASON_CODES` imported but never used -- removed

Fixed in: commit `review(ocr-scanner): Phase 2 Opus review + PY-07 fixes` (see below)

All other standards checked: PY-05 PASS, PY-06 PASS, PY-08 PASS, REL-09 PASS, DATE-01 PASS, TEST-09 PASS (selftest: 20/20 -- 7 TP + 5 TN + 8 regex sanity), API-01 PASS.

Selftest: PASS (20/20)
Full test suite: PASS (355 tests)
Discovery threshold (Tier 1 known positives): THE0T0K08 confirmed TP (digit_in_letter); (E ligature_bracket: 1,980 hits / 385 unique values across full corpus

| Script | Last Reviewed | Notes |
|---|---|---|
| build/extract_pdf.py | 2026-03-31 | Opus reviewed, no critical issues |
| build/tools/ocr_scanner/apply_approved_corrections.py | 2026-04-16 | Opus reviewed. Pre-fixup: removed dead _LOG + logging import. No remaining violations. |
| build/tools/ocr_scanner/models.py | 2026-04-16 | Opus reviewed. No violations. |
| build/tools/ocr_scanner/patterns.py | 2026-04-16 | Opus reviewed. No violations. |
| build/tools/ocr_scanner/report.py | 2026-04-16 | Opus reviewed. No violations. |
| build/tools/ocr_scanner/scanner.py | 2026-04-16 | Opus reviewed. PY-07 fix: removed dead REASON_CODES import. |
| build/tools/ocr_scanner/selftest.py | 2026-04-16 | Opus reviewed. PY-07 fix: removed dead REASON_CODES import. TEST-09 PASS (7 TP + 5 TN). |
| build/lib/bible_ref_normalizer.py | 2026-04-15 | parse_maclaren_ref() + _clean_maclaren_verse_part() + habbakkuk alias + PIPE-07 logging.warning. Standards pass. Opus pending |
| build/lib/citation_parser.py | 2026-03-28 | Standards pass + subagent review |
| build/lib/pdf_normalizer.py | 2026-03-31 | Opus reviewed. Deferred: footnote regex edge case (no current impact) |
| build/lib/pdf_quality_gate.py | 2026-03-31 | Opus reviewed, no issues |
| build/parsers/bcp1662.py | 2026-04-01 | Standards not run. Opus pending |
| build/parsers/bcp1928.py | 2026-04-01 | Opus reviewed 2026-03-31. Deferred: I1 dedup, I2 log file |
| build/parsers/bible_dictionaries.py | 2026-03-31 | Opus reviewed, no critical issues |
| build/parsers/bsb_bible_text.py | 2026-03-28 | Standards pass |
| build/parsers/ccel_devotional.py | 2026-03-28 | Standards pass |
| build/parsers/ccel_hodge_systematic.py | 2026-04-12 | Standards pass. Opus pending |
| build/parsers/ccel_pdf_commentary.py | 2026-03-31 | Opus reviewed, no critical issues. Deferred: PSALM_VERSE_COUNTS validation |
| build/parsers/ccel_whitefield_sermon.py | 2026-04-12 | Standards pass. Fully validated |
| build/parsers/church_fathers.py | 2026-03-31 | Opus reviewed, no critical issues |
| build/parsers/creeds_json_catechism.py | 2026-03-28 | Opus reviewed, no critical issues |
| build/parsers/creeds_json_confession.py | 2026-03-28 | Opus reviewed, no critical issues |
| build/parsers/didache.py | never | Standards not run. Opus pending |
| build/parsers/gutenberg_catechisms.py | 2026-03-31 | Opus reviewed, no critical issues |
| build/parsers/gutenberg_anglican.py | 2026-04-26 | Standards-reviewer pass (T6-4). 41 tests. strip_pg_contributors + integration count tests added post-evaluate. Opus pending. |
| build/parsers/gutenberg_evangelical.py | 2026-04-26 | Standards-reviewer pass this session (PY-07 dup hashlib, REL-06 progress, REL-02/08 error msg, REL-00 tradition assertion). Opus pending. |
| build/parsers/gutenberg_maclaren.py | 2026-04-15 | Standards-reviewer pass (REL-03/07/08, API-04, PIPE-02, PY-03 fixes applied). Opus pending. |
| build/parsers/gutenberg_theology.py | 2026-03-31 | Opus reviewed, no critical issues |
| build/parsers/helloao_commentary.py | 2026-04-13 | Hebrew versification integration. Opus pending |
| build/parsers/naves_topical.py | 2026-03-31 | Opus reviewed, no critical issues |
| build/parsers/standard_ebooks.py | 2026-03-31 | Opus reviewed, no critical issues. Deferred: expected_count for 8/9 SE configs |
| build/parsers/ccel_puritan_works.py | 2026-04-23 | Standards pass (prior session). extract_heading() pattern confirmed correct via Owen port in Opus review (87cd69b). Opus pending |
| build/parsers/spurgeon_mtp.py | 2026-04-13 | Standards pass (python-standards-reviewer). Opus pending |
| build/parsers/spurgeon_mtp_missing.py | 2026-04-13 | Two HTML parsers (AiG + archive.spurgeon.org). Standards pass. Opus pending |
| build/parsers/sword_commentary.py | 2026-04-13 | Hebrew versification integration. Opus pending |
| build/parsers/sword_devotional.py | 2026-04-12 | Modified since Opus review (2026-03-31). Opus pending |
| build/parsers/westminster_standard_parser.py | 2026-03-31 | Opus reviewed, no critical issues. Deferred: no automated tests |
| build/scrapers/westminster_standard_org.py | 2026-03-28 | Standards pass + subagent review |
| build/scripts/add_token_counts.py | 2026-04-01 | Standards pass. Opus pending |
| build/scripts/build_kjv_verse_index.py | 2026-04-01 | Standards pass. Opus pending |
| build/scripts/build_verse_index.py | 2026-03-28 | Standards pass |
| build/scripts/download_gutenberg.py | 2026-03-31 | Opus reviewed, no critical issues |
| build/scripts/download_sword_modules.py | 2026-03-31 | Opus reviewed |
| build/scripts/export_huggingface.py | 2026-04-12 | Standards pass. Opus pending |
| build/scripts/extend_registry_non_cf.py | 2026-03-31 | Standards pass. One-shot data script |
| build/scripts/inspect_sword_zld.py | 2026-03-31 | Exploratory script. Opus reviewed |
| build/scripts/sample_church_fathers.py | 2026-03-28 | Read-only, low risk |
| build/scripts/upload_huggingface.py | 2026-04-12 | Standards pass. Opus pending |
| build/scripts/validate_osis.py | 2026-04-14 | 10 versification cases incl. double-super Ps, Hos 2, Job 40, LXX Esth/Dan. Standards pass. Opus pending |
| build/tools/audit_data_accuracy.py | 2026-04-07 | Standards pass. Opus pending |
| build/tools/inspect_bcp1928_structure.py | 2026-03-31 | Read-only, low risk |
| build/validate.py | 2026-04-13 | Hygiene fixes: _ABSENT module-level + OSIS asymmetry comment. Opus pending |
| schemas/v1/author_registry.schema.json | 2026-03-28 | Reviewed |
| schemas/v1/bible_text.schema.json | 2026-03-28 | Opus reviewed |
| schemas/v1/catechism_qa.schema.json | 2026-03-28 | Opus reviewed |
| schemas/v1/church_fathers.schema.json | 2026-03-28 | Reviewed |
| schemas/v1/commentary.schema.json | 2026-04-12 | Modified. Opus pending |
| schemas/v1/devotional.schema.json | 2026-03-28 | Reviewed |
| schemas/v1/doctrinal_document.schema.json | 2026-03-28 | Reviewed |
| schemas/v1/prayer.schema.json | never | Opus pending |
| schemas/v1/reference_entry.schema.json | 2026-03-30 | Reviewed |
| schemas/v1/sermon.schema.json | 2026-03-28 | Reviewed |
| schemas/v1/structured_text.schema.json | 2026-03-28 | Reviewed |
| schemas/v1/topical_reference.schema.json | 2026-03-31 | Reviewed |
| tests/probe_ordinal_parser.py | 2026-03-31 | 150 psalms pass |
| tests/test_gutenberg_evangelical.py | 2026-04-26 | 40 tests, all pass. Standards pass. Opus pending. |
| tests/test_bible_ref_normalizer.py | 2026-04-14 | 159 tests (29 TestTranslateHebrewToEnglish), all pass. Opus pending |
| tests/test_citation_parser.py | 2026-03-28 | 17 tests, all pass |
| tests/test_naves_osis.py | 2026-03-31 | 23 tests, all pass |
| tests/test_ordinal_parser.py | 2026-03-31 | 14 tests, all pass |
| tests/test_osis_integration.py | 2026-03-28 | 33 tests, all pass |

One-time patch scripts and data file patches are not tracked — see `git log -- 'build/scripts/patch_*.py' 'build/patch_*.py'`.

Retired: `build/parsers/matthew_henry_helloao.py` → `_archive/` (replaced by helloao_commentary.py, 2026-03-28).
