# OCD Last Session Log

Newest first.

---

## 2026-03-31 — Opus Code Review Backlog

**Branch:** main
**What we worked on:** Ran all 10 outstanding Opus code reviews across pipeline scripts that had never been reviewed. Applied all Important fixes. Added Rule 47 to CODING_DEFAULTS.md.

**What was completed:**
- `build/parsers/church_fathers.py` — skipped_files counter split into parse_errors / empty_files / empty_quotes with breakdown in summary
- `build/parsers/standard_ebooks.py` — dead `in_poem` parameter removed from `_walk()`; `[i/N]` progress counter added for `--all` mode
- `build/parsers/bible_dictionaries.py` — dry-run now returns stats dict (not {}) so `--dry-run --all` no longer reports FAILED
- `build/parsers/gutenberg_theology.py` — try/except around all 3 parse calls; datetime timezone-aware (Australia/Melbourne)
- `build/parsers/gutenberg_catechisms.py` — datetime timezone-aware (Australia/Melbourne)
- `build/scripts/download_gutenberg.py` — retry with exponential backoff (3x, 2/4/8s) for transient HTTP errors; datetime timezone-aware
- `build/scripts/inspect_sword_zld.py` — docstring note: rawLD probe uses 6-byte `<IH>`, correct format is 8-byte `<II>`
- `build/parsers/ccel_pdf_commentary.py` — entries now sorted by (chapter, verse_start) before write; note: fix applies to future pipeline runs, committed `psalms.json` still has old ordering
- `tests/test_naves_osis.py` — TestMakeUniqueId class added (3 tests); ABARIM assertion fixed to exact value with explanatory comment; 23/23 pass
- `schemas/v1/topical_reference.schema.json` — description updated to cover both Nave's and Torrey's
- `build/CODE_REVIEWS.md` — all 10 entries updated with 2026-03-31 Opus review dates and findings
- `CODING_DEFAULTS.md` — Rule 47 added (Testing and verification): run the exact fixture before changing a test assertion

**Key incident:** ABARIM test assertion was changed without running the exact fixture first. Correct output was `[{"label": "See", "references": []}]` (not `[]`). Root cause: `html.unescape()` converts `&#x2192;` to `->` which triggers the arrow-detection branch. Took 3 iterations to resolve. Led to Rule 47.

**Previously-stale items confirmed resolved:** smoke_test_pdf.py already deleted; Nave (orville-j-nave) already in author registry.

**Commits:** c66dda3 (main review fixes, 11 files), 89c3e71 (ABARIM test fix + CODE_REVIEWS Minor items)

**Where we stopped:** All work committed. Working tree has unstaged changes to email_fix_log.csv, email_last_run.txt, run_daily.py (Bob's Brittle — unrelated).

**What's next:**
1. SE `expected_count` — 8 of 9 structured_text configs still null; populate via `--list-files` after re-cloning SE repos
2. `psalms.json` sort will self-correct on next Treasury of David pipeline re-run
3. Block 2: CI pipeline (GitHub Actions)
4. Block 3: HuggingFace dataset card and publish

**Key decisions made:**
- Rule 47 scoped to "run the exact fixture" — not just "read the implementation"; the encoding/unescaping specificity is the key insight
- SE `expected_count` deferred until repos re-cloned (source XHTML files not on disk — deferral is correct, not a shortcut)

**Open questions / decisions pending:** None

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

**Additional work (same session, context-compacted continuation):**
- Researched both ThML source formats by sampling raw SWORD module bytes — discovered Wesley uses text-content `<scripRef>Luke 3:31</scripRef>` (no `passage=` attribute), not the `passage=` form that `_THML_REF_PATTERN` matches. The current regex silently misses all Wesley refs.
- Confirmed real input varieties: single refs, multi-ref with book carry-over, semicolons + commas mixed, verse ranges, known OCR typos (`1Timm`, `1Chron`, `1Kings`, `1Thes`), partial refs without book context.
- Wrote prompt for ThML normalizer — in READY_TO_PASTE_PROMPTS.md as "ThML cross-reference normalizer (Barnes + Wesley)".

**What's next:**
1. **ThML cross-reference normalizer** — prompt ready in READY_TO_PASTE_PROMPTS.md. Builds `build/lib/bible_ref_normalizer.py`; also needs `_THML_REF_CONTENT_PATTERN` added to `sword_commentary.py` to catch Wesley text-content refs. 24,886 entries currently have `cross_references: []`.
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
- `data_start` guard formula corrected: correct value is `4 + count*8 = 244` (last entry's esz slot overlaps data start); prior formula `8 + count*8 = 248` fired as false warning on every valid block

**Post-session evaluation improvements (same session, /evaluate cycle):**
- `build/parsers/naves_topical.py` — guard formula fixed (`8+count*8` → `4+count*8`); block layout docstring updated with overlap explanation
- `plans/2026-03-30-naves-topical-parser.md` — Format Discovery section appended (TEI XML vs plain text, block index overlap, eoff semantics, redirect entries)
- `data/authors/registry.json` — removed duplicate orville-j-nave entry (richer pre-existing entry preserved)
- `00 CONTEXT/LESSONS.md` — added: "A check that fires on 100% of valid inputs means your model of the invariant is wrong, not that the data is noisy"

**Validation:** `py -3 build/validate.py --all` → **0 errors**, 150 warnings, 899 files.

**Commits:** 84fc952 (download), e849125 (inspect), 1901802 (tests), 22f7f78 + 5f6e708 (parser), 030f289 (data + validate), b68aa3a (README), cb1ad37 (LAST_SESSION), 026bdf6 (guard fix + plan doc + registry dedup)

**Where we stopped:** All work committed. Working tree clean.

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
