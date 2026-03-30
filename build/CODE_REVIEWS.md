# Code Reviews — Open Christian Data

| Script | Last Reviewed | Notes |
|---|---|---|
| build/parsers/matthew_henry_helloao.py | 2026-03-28 | RETIRED to _archive/ -- replaced by generic helloao_commentary.py. Opus review: no critical issues. H3 grand summary added, M1 whitespace fix applied. |
| build/parsers/helloao_commentary.py | 2026-03-28 | Opus review: H1 config key validation added, H2 --book validation against available data added, M1 books_with_summaries made dynamic. M2 coverage-gap detection deferred (discover_books is intentional design). L1-L5 noted, no action needed. |
| build/parsers/creeds_json_confession.py | 2026-03-28 | Opus review: M1 VALID_TRADITIONS missing particular-baptist -- fixed. L1/L2 map_proofs+log duplication noted (defer to shared module when parser count grows). |
| build/parsers/creeds_json_catechism.py | 2026-03-28 | Opus review: H1 author null (fixed in schema). M2 _parse_sort_key now warns on non-numeric Number (fixed). M3 --all wrapped in try/finally (fixed). L1-L3 duplication noted (defer). |
| build/validate.py | 2026-03-28 | Opus review (2nd pass): no new issues. Partial completeness logic correct. Previous M4/M7 still accepted. |
| schemas/v1/commentary.schema.json | never | Phase 1a |
| schemas/v1/catechism_qa.schema.json | 2026-03-28 | Opus review: H1 author type changed from string to ["string", "null"] to match doctrinal_document pattern and handle empty Authors in source. |
| schemas/v1/doctrinal_document.schema.json | never | Task 3 |
| build/parsers/ccel_devotional.py | 2026-03-28 | Standards-reviewer pass + fixes: Rule 8 try/except in parse loop, Rule 43 quality reporting, Rule 44 dry-run coverage, nav link filtering, encoding fallback. |
| schemas/v1/devotional.schema.json | 2026-03-28 | New schema for Task 7. Tradition/license enums match other schemas (consistency check passes). |
| build/validate.py | 2026-03-28 | Updated: added validate_devotional_file() + dispatch. Opus review (2nd pass) + standards-reviewer recheck. |
| build/lib/citation_parser.py | 2026-03-28 | New (Westminster Standards). Standards-reviewer pass + two-stage subagent review. Dead code removed, import placement fixed, degenerate input guard added. |
| build/scrapers/westminster_standard_org.py | 2026-03-28 | New (Westminster Standards). Standards-reviewer pass + two-stage subagent review. ZoneInfo timezone added, beautifulsoup4 pinned. No retry logic (Rule 21 -- deferred, one-off scraper). |
| build/parsers/westminster_standard_parser.py | 2026-03-28 | New (Westminster Standards). 935 lines. Standards-reviewer pass + two-stage subagent review. Logging bug fixed, return type annotation fixed, _build_osis_entries deduped, license_notes updated. **Full Opus review recommended before Phase 2.** |
| tests/test_citation_parser.py | 2026-03-28 | New (Westminster Standards). 17 tests. Standards-reviewer pass. |
| schemas/v1/doctrinal_document.schema.json | 2026-03-28 | Updated: added "directory" and "covenant" to document_kind enum. Subagent review confirmed alphabetical order and no regressions. |
| build/parsers/bsb_bible_text.py | 2026-03-28 | New (Prompt 0a). Standards-reviewer pass (6 issues fixed). Logger.info format bug caught in retrospective and fixed. |
| schemas/v1/bible_text.schema.json | 2026-03-28 | New (Prompt 0a). Opus review: M1 original_language pattern added for consistency with devotional. M6 doctrinal_document minItems:0 noted (pre-existing, not fixed). L3/L4/L8 informational. |
| build/validate.py | 2026-03-28 | Updated (Prompt 0b + fixes): added validate_bible_text_file(), OSIS existence checking for commentary/catechism/doctrinal, fixed commentary cross_references to handle Reference objects (was TypeError on dict). Standards-reviewer pass. |
| build/scripts/build_verse_index.py | 2026-03-28 | New (Prompt 0b). Standards-reviewer pass (4 issues fixed: hardcoded date, elapsed time, 2x silent exception swallows). |
| build/scripts/validate_osis.py | 2026-03-28 | New (Prompt 0b). Importable utility. Standards-reviewer pass. Updated 2026-03-28: DEUTEROCANONICAL_BOOK_CODES frozenset added; known apocryphal codes return (True, "deuterocanonical - not in verse index") instead of failing. Covered by test_osis_integration.py section 6 (10 tests). |
| build/scripts/test_osis_integration.py | 2026-03-28 | New (Prompt 0b post-session). Updated 2026-03-28: section 6 added -- 10 deuterocanonical tests. 33/33 pass. |
| build/scripts/add_token_counts.py | 2026-03-28 | New (Prompt 0c). Standards-reviewer pass. Idempotent, --dry-run mode. 105,413 records updated across 407 files. |
| schemas/v1/commentary.schema.json | 2026-03-28 | Updated (0c): token_count added as optional integer. |
| schemas/v1/catechism_qa.schema.json | 2026-03-28 | Updated (0c): token_count added as optional integer. |
| schemas/v1/doctrinal_document.schema.json | 2026-03-28 | Updated (0c): token_count added as optional integer in $defs/unit. |
| schemas/v1/devotional.schema.json | 2026-03-28 | Updated (0c): token_count added as optional integer. |
| build/validate.py | 2026-03-28 | Updated (0d): added check_author_registry() + [AUTHOR REGISTRY] block in --all run. Subagent-written; manual spot-check confirmed structure. No python-standards-reviewer run on 0d additions specifically — flag for next Opus pass. |
| schemas/v1/author_registry.schema.json | 2026-03-28 | New (0d). Tradition enum matches commentary schema. nationality + notes fields added (not in original spec but sensible additions). |
| build/parsers/church_fathers.py | 2026-03-28 | New (Church Fathers T1-3). Standards-reviewer pass (4 issues fixed: error messages, magic numbers, aggregate stats, try/except). Post-eval fixes: aggregate null_osis + empty_source_title in summary. Dedup bug fixed (set not dict). No Opus review yet — flag for next pass. |
| schemas/v1/church_fathers.schema.json | 2026-03-28 | New (Church Fathers). Tradition/license enums match commentary schema (consistency check passes). anchor_ref, attribution_note, context fields. |
| build/scripts/sample_church_fathers.py | 2026-03-28 | New (post-eval). Sanity check script — samples N random authors, prints key fields, checks for non-ASCII filenames. Standards-reviewer pass not run — simple read-only script, low risk. |
| build/parsers/standard_ebooks.py | 2026-03-28 | New (T1-4). Standards-reviewer pass not run. Post-eval fixes applied: SKIP_PREFIXES filter, --list-files flag, expected_count assertion. No Opus review yet — flag for next pass. |
| schemas/v1/structured_text.schema.json | 2026-03-28 | New (T1-4). Recursive section tree. Tradition/license enums match other schemas (consistency check passes). |
| schemas/v1/sermon.schema.json | 2026-03-28 | New (T1-4). Data is array of sermon entries. Tradition/license enums match other schemas. |
| build/validate.py | 2026-03-28 | Updated (T1-4): added validate_structured_text_file(), validate_sermon_file(), _check_sections(). 0 errors on --all (741 files). |
| build/extract_pdf.py | never | New (PDF pipeline). pymupdf4llm wrapper, GlyphLessFont OCR detection, batch processing, dry-run. **Opus review pending -- use written prompt.** |
| build/lib/pdf_quality_gate.py | never | New (PDF pipeline). Post-extraction quality checks. **Opus review pending.** |
| build/lib/pdf_normalizer.py | never | New (PDF pipeline). 8 Markdown transforms. **Opus review pending.** |
| build/parsers/ccel_pdf_commentary.py | never | New (Treasury of David). 550+ lines. 3 bugs fixed during end-to-end test. **Opus review pending -- highest priority.** |
| tests/test_ordinal_parser.py | 2026-03-28 | New (PDF pipeline). 10 unit tests for ordinal converter. Covers regression cases for all 3 parser bugs. No Opus review needed. |
| build/validate.py | 2026-03-28 | Updated (PDF pipeline): verse_text_source "none" bypass for verse_text completeness check. |
| build/parsers/bible_dictionaries.py | 2026-03-30 | New (T1-5 JWBickel). Standards-reviewer pass (logging, error messages, N-of-M counter, quality stats, summary). Separator bug fixed (regex not string literal, Rule 46). No Opus review yet — flag for next pass. |
| schemas/v1/reference_entry.schema.json | 2026-03-30 | New (T1-5). Easton's, Smith's, Hitchcock's. Tradition/license enums match other schemas. |
| schemas/v1/topical_reference.schema.json | 2026-03-30 | New (T1-5). Torrey's. Subtopics array with label + references. Tradition/license enums match. |
| build/validate.py | 2026-03-30 | Updated (T1-5): added validate_reference_entry_file() + validate_topical_reference_file() + dispatch cases. 0 errors on --all (891 files). |
| build/scripts/download_gutenberg.py | 2026-03-31 | New (PG pipeline). Respectful downloader: 2s delay, User-Agent, SHA-256, skip-if-cached. Standards-reviewer pass 2026-03-31. H fixes: error message now embeds PG ID + URL, delay logic fixed to fire after errors (downloaded+errors>0). M/L violations (no retry, cosmetic log gap) noted but deferred — downloads are complete. |
| build/parsers/gutenberg_catechisms.py | 2026-03-31 | New (PG catechisms). Luther Small (45 Q&A) + Baltimore #1/2/3 (2,070 Q&A). Standards-reviewer pass 2026-03-31. H fixes: parse call wrapped in try/except, error message embeds source_path. M violations (question-mark truncation in LSC, no item_id dedup guard for Baltimore) noted — low risk given source data, defer to next Opus review. |
| build/parsers/gutenberg_theology.py | 2026-03-31 | New (PG theology). Luther Large (now 25 sections — Article I/II/III added), Calvin 2-vol merge (646k words), Augustine (112k words, book-level only). Standards-reviewer pass 2026-03-31. H fixes: strip_pg_wrapper wrapped in try/except for all 3 runners, error messages embed full path. Bug fix: Article I./II./III. regex added to _LLC_SUBSECTION_RES. M violations (Calvin Vol 2 chapter title heuristic, error handling inside parsers) noted for next Opus review. |
