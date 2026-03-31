# OCD Last Session Log

Newest first.

---

## 2026-03-31 — PDF Pipeline Code Review + Bug Fixes

**What we worked on:** Batch Sonnet code review of 5 PDF extraction pipeline files against CODING_DEFAULTS.md. Fix cycle across two retrospective loops: H-level issues first, then M-level, then parser bugs discovered during test expansion.

**What was completed:**

*Critical fixes (H):*
- `build/lib/pdf_quality_gate.py` line 81: `{total_pages}` NameError → `{total_pages_processed}` (note: review brief said "already fixed" — it was not; read the file first)
- `build/extract_pdf.py`: ZeroDivisionError when PDF has 0 pages — `chars / pages_processed` → guard expression

*M-level fixes (extract_pdf.py):*
- Multi-PDF loop wrapped in try/except with error counting + summary line
- Ad-hoc `--pdf` mode also wrapped in try/except with `sys.exit(1)`
- `_TeeWriter` class added; `run()` renamed `_run()`; new `run()` opens `LOG_FILE` and wraps with tee
- `LOG_FILE` and `RAW_OUTPUT_BASE` constants added at top of file

*M-level fixes (ccel_pdf_commentary.py):*
- `build_meta()` un-hardcoded: now reads `source_edition`, `archive_org_identifier`, `psalm_range_note` from config with empty-string fallbacks
- `_TeeWriter` + LOG_FILE + OUTPUT_BASE constants added (same pattern as extract_pdf.py)

*Parser bug fixes:*
- `FIFTIETH` was returning 0 — added `"FIFTIETH": 50` to TENS dict (FIFTY ends in Y, so FIFTIETH didn't match FIFTY prefix)
- `EIGHTIETH` was being corrupted to `EIGHTHETH` — OCR correction loop changed from `.replace()` to `re.sub(r"\b" + re.escape(bad) + r"\b", good, name)` (short bad-form `EIGHTI` fired inside `EIGHTIETH` as substring)

*Other:*
- `build/lib/pdf_normalizer.py` docstring: "to 2 blank lines" → "to 1 blank line" (regex produces 1)
- `sources/commentaries/treasury-of-david/config.json`: added 3 keys: `source_edition`, `archive_org_identifier`, `psalm_range_note`
- `tests/probe_ordinal_parser.py`: new file — independent generator for psalms 1-150; all 150 pass; imported by test suite
- `tests/test_ordinal_parser.py`: expanded from 10 to 14 tests; added full-range regression test (all 150 via probe)
- 5 memories saved with sign-off

**Where we stopped:** All code changes complete. Memories saved. CODE_REVIEWS.md updated. Session wrap-up committed (7d95608). Dry-run validated against real data — clean.

**Dry-run result (validated end of session):**
- `py -3 build/parsers/ccel_pdf_commentary.py --commentary treasury-of-david --all-books --dry-run`
- 493 entries parsed, Psalms 53-78 (all 26 expected), 0 errors, 21 short-entry warnings (pre-existing, known)
- Raw Markdown confirmed present at `raw/ccel/treasury-of-david/markdown/treasury-of-david-vol1.md`
- Parser is ready to run for real

**What's next:**
1. Run parser for real: `py -3 build/parsers/ccel_pdf_commentary.py --commentary treasury-of-david --all-books`
2. Delete `smoke_test_pdf.py` (carried from prior session — bash rm was denied)
3. Opus code review of `naves_topical.py` (never reviewed)
4. Block 2: CI pipeline + HuggingFace publish

**Key decisions made:**
- `_TeeWriter` duplication between extract_pdf.py and ccel_pdf_commentary.py is deferred — extract to `build/lib/` when a 3rd script needs it
- OCR correction tables: always use `re.sub(r"\b...\b")` not `.replace()` (now in memory)
- Probe-before-tests pattern for finite-domain parsers (now in memory)

**Open questions / decisions pending:** None.

---

## 2026-03-31 — SWORD Commentaries + Daily Light Devotional

**Branch:** main

**What we worked on:** Completed the SWORD commentary pipeline (Barnes, Calvin, Wesley) and Daily Light devotional parser. Session was a context-compacted continuation — previous session had written the parsers; this session fixed schema mismatches, ran validation to 0 errors, added schema gates, and ran a post-task evaluation cycle.

**What was completed:**
- `build/parsers/sword_commentary.py` — schema fixed (meta fields, entry fields, cross_references type); first-unit schema gate added (`_check_first_book_schema`); word count stats in quality report; failed module tracking in summary; sample entry display in dry-run
- `build/parsers/sword_devotional.py` — schema fixed (removed cross_references not in schema); `_check_output_schema()` gate added; `SchemaValidationError` raised instead of `sys.exit`; `build_meta()` moved before dry-run exit so validation runs in both modes
- `build/validate.py` — semantic fix: devotional primary_reference completeness check now distinguishes explicit `null` (intentionally absent) from missing key; `_ABSENT` sentinel pattern
- `sources/commentaries/barnes/config.json`, `calvin/`, `wesley/` — new source configs
- `sources/devotionals/daily-light/config.json` — new; fixed `nondenominational` → `non-denominational`
- `data/commentaries/barnes/` — 27 NT books, 7,322 entries
- `data/commentaries/calvin/` — 49 books, 13,338 entries (OSIS format, verse-level cross_references)
- `data/commentaries/wesley/` — 66 books, 17,564 entries
- `data/devotionals/daily-light/daily-light.json` — 732 entries (366 days × morning/evening)
- `README.md` — SWORD sources added to directory listing, pipeline commands, and attribution

**Key decisions made:**
- **ThML cross-references → `[]`:** Barnes and Wesley `<scripRef passage="...">` attributes contain human-readable multi-ref strings (e.g. `"Lev 4:3, 6:20, Ex 28:41, 29:7"`). Cannot be reliably normalized to OSIS without a full Bible reference normalizer — emitting invalid strings would fail validation. Deliberate data loss; deferred to future enrichment pipeline.
- **Calvin OSIS refs:** Space-separated tokens in `osisRef` attribute (e.g. `"Jer.27.20 Bible:Jer.28.4"`) split per token, `Bible:` prefix stripped, chapter-only refs (e.g. `Rom.8`) filtered out (not verse-level, fail strict OSIS pattern).
- **validate.py null vs missing:** Explicit `primary_reference: null` means "intentionally no anchor verse" (Daily Light is pure scripture compilation). Previously counted as "missing" and triggered completeness error. Fixed with `_ABSENT` sentinel.
- **Schema gate pattern:** First-unit gate in both parsers calls `validate_commentary_file`/`validate_devotional_file` in-memory before any files are written. Raises `SchemaValidationError` on failure. Prevents bulk-writing N files with the same schema defect.

**Validation:** `py -3 build/validate.py --all` → **0 errors**, 472 warnings, 887 SWORD-related files. (898 total with unrelated catechism additions from separate work; baltimore-catechism-no-3.json has 1 pre-existing empty answer — not from this session.)

**Where we stopped:** All work committed. All schema gates active and tested.

**What's next:**
1. **ThML cross-reference normalizer** — build a Bible reference parser to convert Barnes/Wesley `passage=` attributes to OSIS. Currently `cross_references: []` for all 24,886 Barnes+Wesley entries. High value: these refs are dense (Barnes especially).
2. **Opus code review** — `sword_commentary.py`, `download_sword_modules.py` (both pending; sword_devotional.py optional). See CODE_REVIEWS.md.
3. **Token counts** — run `add_token_counts.py` across new commentary and devotional files (not yet done for SWORD additions).
4. **Block 2** — CI pipeline + HuggingFace publish.

---

## 2026-03-31 — Nave's Topical Bible (CrossWire SWORD)

**Branch:** main
**What we worked on:** End-to-end pipeline for Nave's Topical Bible from CrossWire SWORD zLD module — binary format reverse-engineering, unit tests, parser, validation, README.

**What was completed:**
- `research/reference/request_log.csv` — download log for Nave.zip (SHA-256 recorded)
- `build/scripts/inspect_sword_zld.py` — probes zLD binary format (zdx/zdt), revealed 5,322 entries and TEI XML content
- `tests/test_naves_osis.py` — 20 unit tests: `extract_osis_refs`, `extract_cross_refs`, `parse_subtopics`, `slugify`
- `build/parsers/naves_topical.py` — full parser; `_decode_zld()` + `get_entry_from_block()` + `parse_subtopics()` + `extract_osis_refs()` + `extract_cross_refs()`; CLI `--dry-run` + `--limit N`
- `data/topical-reference/naves/naves-topical-bible.json` — 5,322 entries, 76,957 scripture refs, 12,343 KB
- `build/validate.py` — relaxed: empty subtopics is WARNING (not error) when `related_topics` non-empty (handles redirect-only entries)
- `README.md` — status table row, data directory listing, pipeline commands, source attribution

**Key discoveries:**
- OSIS refs pre-computed in TEI XML attributes — no book abbreviation lookup needed
- `eoff` in block internal index is entry size (not offset); cumulative sum gives position
- 2 redirect-only entries (SHOMER, TRADE): empty subtopics + non-empty related_topics — validator relaxed
- `data_start=244` fires block validation guard on all valid blocks (SWORD format quirk) — kept as warning

**Validation:** `py -3 build/validate.py --all` → **0 errors**, 164 warnings, 899 files.

**Commits:** 84fc952 (download), e849125 (inspect), 1901802 (tests), 22f7f78 + 5f6e708 (parser), 030f289 (data + validate), b68aa3a (README)

**Where we stopped:** All work committed (wrap-up 2026-03-31). Working tree clean except smoke_test_pdf.py.

**What's next:**
1. Delete smoke_test_pdf.py manually (bash rm was denied in prior session)
2. Add Nave (Orville J. Nave, 1841–1917) to author registry
3. Opus code review of naves_topical.py (never reviewed)
4. Ongoing Opus review backlog — see CODE_REVIEWS.md (7 scripts pending)
5. Block 2: CI pipeline + HuggingFace publish

---

## 2026-03-31 — Registry: Church Fathers (317 missing authors)

### What was done

Extended `data/authors/registry.json` from 40 to 357 entries by adding all
317 church fathers authors that were producing "Author not in registry" warnings
from the validator.

**Scripts written:**
- `build/scripts/extend_author_registry.py` — adds 317 entries, idempotent
- `build/scripts/patch_author_registry.py` — 17 sourced corrections from
  external verification pass (Wikipedia, Britannica, CCEL, OrthodoxWiki)

**Corrections applied during verification:**
- `andreas-of-caesarea` — dates cleared to null (637 unsupported)
- `arethas-of-caesarea` — death year 935 -> 939
- `theophylact-of-ohrid` — death year 1126 -> null (unsupported)
- `haimo-of-auxerre` — birth year 840 -> null (fabricated)
- `walafrid-strabo` — removed false attribution of Glossa Ordinaria to him
- `agapius-of-hierapolis` — tradition ["patristic"] -> ["orthodox"] (10th-c. Melkite, post-schism)
- `severus-of-antioch`, `jacob-of-edessa`, `cosmas-of-maiuma`, `abba-poemen`,
  `isaac-of-nineveh` — removed "orthodox" (all pre-1054; no strong exception)
- `john-wesley` — added "wesleyan" and "anglican" to tradition
- `cs-lewis` — nationality "British" -> "Irish" (self-identified)
- `gk-chesterton` — display_name corrected to "G. K. Chesterton"; "GK Chesterton"
  demoted to alias (to match structured-text data files)

**Pre-1054 "strong reason" exceptions kept as ["patristic", "orthodox"]:**
John Damascene, Maximus the Confessor, Andrew of Crete, Romanos the Melodist,
Sophronius of Jerusalem, Photios I, Desert Fathers.

### Final state

`py -3 build/validate.py --all` -- 0 errors, 163 warnings.

Remaining warnings:
- ~150 x "missing source_title" completeness warnings (pre-existing, across many datasets)
- 13 x "Author not in registry" from non-church-fathers datasets

### Next session prompt

Prompt ready in:
`02 PERSONAL/Open Christian Data/READY_TO_PASTE_PROMPTS.md`
-- "Registry: Non-Church-Fathers authors (13 missing + source_title gaps)"
