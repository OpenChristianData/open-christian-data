# OCD Project Journal

Permanent historical record. Newest entries at top. Never trimmed.

---

## 2026-04-01 — Basil of Caesarea source_title curation

**Branch:** main

**What we worked on:** Populated all 93 blank source_title fields in basil-of-caesarea.json. Ran /evaluate, implemented all improvements, then ran end-of-session.

**What was completed:**
- `build/scripts/patch_basil_source_titles.py` — new patch script; 93 entries patched. Confidence tiers (HIGH/MEDIUM/LOW) documented per-entry. Post-hoc verifications completed for all uncertain assignments.
- `data/church-fathers/basil-of-caesarea.json` — all 93 entries now have source_title
- `build/CODE_REVIEWS.md` — entry added (standards-reviewer pass, no Opus needed)
- `00 CONTEXT/LESSONS.md` (Cowork) — lesson added: confidence tiers in bulk curation; "grep before correcting" check
- `02 PERSONAL/PERSONAL_PROJECTS.md` — stats updated to 900 files / 143 warnings

**Assignment breakdown (93 entries):** HEXAEMERON (67), THE MORALS (10), THE LONG RULES (3), HOMILIES ON THE PSALMS (3), Letters (4), ON THE HOLY SPIRIT (2), other (4). Confidence: 8 HIGH / 81 MEDIUM / 4 LOW.

**Validation:** 0 errors, 0 warnings on basil file; 143 warnings total (--all).

**Where we stopped:** All work complete. Committed in 19e4773.

---

## 2026-03-31 — Baltimore Catechism No. 3 — blank answer fix

**Branch:** main

**What we worked on:** Data quality fix — investigated 4 reported blank answer entries in baltimore-catechism-no-3.json.

**What was completed:**
- `data/catechisms/baltimore-catechism-no-3.json` — Q630 fixed: question and answer were concatenated in the question field (parser bug from initial import); split into correct fields. `completeness` updated from `"partial"` to `"full"` (all 1,398 answers now populated; valid values are `full`/`partial`/`in-progress`).

**Finding:** Task brief said 4 blank entries (IDs 43, 59, 60, 630) — only ID 630 was actually blank. IDs 43, 59, 60 already had answers. Q630 was a parser bug: the source text Q and A were merged into the question field with answer left null.

**Validation:** `py -3 build/validate.py data/catechisms/baltimore-catechism-no-3.json` -> 0 errors, 0 warnings (was 1 warning). `py -3 build/validate.py --all` -> 0 errors, 145 warnings.

**Where we stopped:** All work complete. Not yet committed.

**What's next:**
1. Commit this fix (baltimore-catechism-no-3.json)
2. Carry-forward from prior sessions — see entries below

---

## 2026-04-01 — Augustine source_title curation (post-evaluate corrections, 3 rounds)

**Branch:** main

**What we worked on:** Three rounds of /evaluate-driven corrections. Total: 8 reassignments from initial pass.

**All reassignments (cumulative):**
- `1Sam.24.5`: City of God → **ON BAPTISM AGAINST THE DONATISTS** (chrism = anti-Donatist)
- `Col.1.6.unknown-2`: City of God → **Letters** (explicit Donatist/Africa polemic)
- `Col.4.3`: City of God → **Letters** (Donatist "we are righteous... we sanctify the unclean")
- `Matt.6.12.unknown-2`: Commentary → **Sermons** ("ye are on the point of being baptized")
- `Matt.6.9.unknown-3`: Commentary → **Sermons** ("as ye have heard and repeated in the creed")
- `1Cor.15.12`: City of God → **Letters** (quote ends with "Letter, To Vincent" — explicit, missed initial pass)
- `Col.1.12.unknown-2`: City of God → **ON BAPTISM AGAINST THE DONATISTS** ("where the unity of Christ is not" = De baptismo argument)
- `Col.2.14.unknown`: City of God → **AGAINST FAUSTUS, A MANICHAEAN** (explicit "Manichaeans believe... was spirit and not flesh")

**Enchiridion audit result:** Keyword scan (grace/faith/baptism/hope/resurrection) across all City of God entries; no genuine Enchiridion candidates found.

**Final counts:** City of God (59), Commentary on Sermon on the Mount (55), Letters (16), ON THE TRINITY (15), Sermons (12), On the Work of Monks (7), AGAINST FAUSTUS (4), ON BAPTISM AGAINST THE DONATISTS (2), Confessions (1), HARMONY OF THE GOSPELS (1).

**Validation:** 0 errors, 0 warnings. Idempotent. Not yet committed.

---

## 2026-03-31 — westminster_standard_parser Opus review + fixes

**Branch:** main
**Commit:** df66637

**What we worked on:** Full Opus code review of `westminster_standard_parser.py`. Two-stage: Sonnet CODING_DEFAULTS pass first, then Opus domain-specific review. Implemented all findings. Ran `/evaluate` skill mid-session which caught two omissions (Rule 54, `assert` vs `raise`), both fixed.

**What was completed:**
- `build/parsers/westminster_standard_parser.py` — 7 Sonnet standards fixes + Opus fix (`skipped_not_in_html` counter + mismatch assert). Content plausibility check added. `assert` replaced with `raise SystemExit`.
- `build/CODE_REVIEWS.md` — westminster_standard_parser row updated
- `build/parsers/bcp1928.py`, `build/parsers/sword_commentary.py`, `build/scripts/download_sword_modules.py`, `data/prayers/bcp-1928/collects.json` — carried from prior session, committed

**Key decisions:** `raise SystemExit` over `assert` (silenced by `python -O`). `_WRONG_BLOCK_OPENERS` blocklist scans first word of every section.

**Where we stopped:** All work committed (df66637). Working tree clean.

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
- **ThML cross-references → `[]`:** Barnes and Wesley `<scripRef passage="...">` attributes contain human-readable multi-ref strings. Cannot be reliably normalized to OSIS without a full Bible reference normalizer — deliberate data loss; deferred to future enrichment pipeline.
- **Schema gate pattern:** First-unit gate in both parsers calls validate in-memory before any files are written. Raises `SchemaValidationError` on failure.

**Validation:** `py -3 build/validate.py --all` → 0 errors, 472 warnings, 887 files.

**Where we stopped:** All work committed.

**What's next:**
1. ThML cross-reference normalizer — prompt ready in READY_TO_PASTE_PROMPTS.md
2. Opus code review — `sword_commentary.py`, `download_sword_modules.py`
3. Token counts — run `add_token_counts.py` across new commentary and devotional files
4. Block 2 — CI pipeline + HuggingFace publish

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
- `FIFTIETH` was returning 0 — added `"FIFTIETH": 50` to TENS dict
- `EIGHTIETH` was being corrupted to `EIGHTHETH` — OCR correction loop changed from `.replace()` to `re.sub(r"\b" + re.escape(bad) + r"\b", good, name)`

*Other:*
- `build/lib/pdf_normalizer.py` docstring: "to 2 blank lines" → "to 1 blank line"
- `sources/commentaries/treasury-of-david/config.json`: added 3 keys
- `tests/probe_ordinal_parser.py`: new file — independent generator for psalms 1-150; all 150 pass
- `tests/test_ordinal_parser.py`: expanded from 10 to 14 tests; full-range regression test added

**Key decisions made:**
- `_TeeWriter` duplication between extract_pdf.py and ccel_pdf_commentary.py deferred — extract to `build/lib/` when a 3rd script needs it
- OCR correction tables: always use `re.sub(r"\b...\b")` not `.replace()`
- Probe-before-tests pattern for finite-domain parsers

**Commits:** 7d95608

---

## 2026-03-31 — SWORD Commentaries + Daily Light Devotional

**Branch:** main

**What we worked on:** Completed the SWORD commentary pipeline (Barnes, Calvin, Wesley) and Daily Light devotional parser. Session was a context-compacted continuation — previous session had written the parsers; this session fixed schema mismatches, ran validation to 0 errors, added schema gates, and ran a post-task evaluation cycle.

**What was completed:**
- `build/parsers/sword_commentary.py` — schema fixed; first-unit schema gate added; word count stats; failed module tracking; sample entry display in dry-run
- `build/parsers/sword_devotional.py` — schema fixed; `_check_output_schema()` gate added; `SchemaValidationError` raised instead of `sys.exit`
- `build/validate.py` — devotional primary_reference completeness check distinguishes explicit `null` from missing key (`_ABSENT` sentinel)
- `data/commentaries/barnes/` — 27 NT books, 7,322 entries
- `data/commentaries/calvin/` — 49 books, 13,338 entries
- `data/commentaries/wesley/` — 66 books, 17,564 entries
- `data/devotionals/daily-light/daily-light.json` — 732 entries
- `README.md` — SWORD sources added

**Key decisions made:**
- ThML cross-references → `[]`: cannot reliably normalize to OSIS without a full Bible reference normalizer. Deferred.
- Calvin OSIS refs: `Bible:` prefix stripped, chapter-only refs filtered.
- Schema gate pattern: first-unit gate validates in-memory before any files written.

**Validation:** `py -3 build/validate.py --all` → 0 errors, 472 warnings, 887 SWORD-related files.

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

---

## 2026-03-31 — Registry catch-up + source_title patch

**Branch:** main

**What we worked on:** Ran "Registry: Non-Church-Fathers authors (13 missing + source_title gaps)" prompt. Task 1 was already complete (all 13 authors in registry from prior session). Task 2: investigated source_title warnings across church_fathers dataset and patched what was automatable.

**What was completed:**
- Task 1 (13 missing authors): confirmed all 13 already present in registry (370 entries). No action needed.
- Investigation: 2,249 entries missing source_title across 129 files. 247 were inferable from same-verse sibling blocks; 2,002 are genuinely absent in upstream HistoricalChristianFaith TOML data.
- build/scripts/patch_source_title.py -- idempotent patch script; fills source_title from same-verse siblings where all siblings share a single consistent title. 247 entries patched across 37 files.
- CODING_DEFAULTS.md -- Rule 50 added: idempotent patch scripts must be run twice before review (Rule 49 already existed; duplicate caught in wrap-up).
- READY_TO_PASTE_PROMPTS.md -- Church Fathers: source_title editorial curation prompt added for the 2,002-entry remaining gap; registry prompt marked done in Skip list.
- build/CODE_REVIEWS.md -- patch_source_title.py entry added.
- PERSONAL_PROJECTS.md -- stats updated (150 to 146 warnings, note on upstream gap).
- PROJECT_JOURNAL.md -- created; oldest LAST_SESSION entry (Church Fathers registry) moved here.

**Validation:** py -3 build/validate.py --all -> 0 errors, 146 warnings (down from 150).

**Key finding:** source_title warnings reduced from 129 file-level warnings to 125. The 4 files fully resolved: chromatius-of-aquileia, hilary-of-arles, paterius, pseudo-augustine. Remaining 125 warnings are unavoidable upstream gaps.

**Where we stopped:** All work committed (c835d52).

**What was next:**
1. Church fathers source_title editorial curation -- prompt in READY_TO_PASTE_PROMPTS.md. Top authors: thomas-aquinas (325 missing), augustine-of-hippo (~176), basil-of-caesarea (~93). Do one author per session.
2. Commit pending build/validate.py changes (from prior Opus review session)
3. Commit or clean up bcp1928.py (check if it was mid-session work)
4. Opus code review backlog -- see CODE_REVIEWS.md
5. Block 2: CI pipeline + HuggingFace publish

## 2026-03-31 -- Augustine source_title curation (initial pass)

**Branch:** main

**What we worked on:** Populated all 176 blank source_title fields in augustine-of-hippo.json.

**What was completed:**
- build/scripts/patch_augustine_source_titles.py -- new patch script; 176 entries filled
- data/church-fathers/augustine-of-hippo.json -- all 176 entries now have source_title
- build/CODE_REVIEWS.md -- entry added

**High-confidence calls:** Rev.1.7.unknown-2 -> ON THE TRINITY (explicit cite); Rev.20.1 -> City of God (explicit); Mark.11.18 -> HARMONY OF THE GOSPELS (explicit); 1Cor.9 block -> On the Work of Monks; Col.2.14.unknown-2 -> Confessions (Monica).

---

## 2026-03-31 -- BCP 1928 Collects Parser

**Branch:** main

**What we worked on:** Built the complete BCP 1928 collects parser from scratch -- source investigation, HTML inspection, parser, config, output, validation, README, evaluate skill, and post-evaluate improvements (census script, content spot-check, CODING_DEFAULTS rules).

**What was completed:**
- sources/prayers/bcp-1928-collects/config.json -- episcopalnet.org chosen over justus.anglican.org (PDF-only)
- build/parsers/bcp1928.py -- 98 collects (Trinity21-24 skipped: no collect HTML confirmed); content spot-check added post-evaluate
- data/prayers/bcp-1928/collects.json -- 98 records, 81 KB
- README.md -- 5 sections updated
- build/tools/inspect_bcp1928_structure.py -- structural census tool
- CODING_DEFAULTS.md -- Rule 53 (structural census) + Rule 54 (content plausibility) added

**Validation:** 0 errors, 146 warnings (900 files).

**Key decisions:** Source: episcopalnet.org; Trinity21-24 silently skipped; Good Friday 3 collects split with -2/-3 suffixes.

**Key lessons:** Grepping a sample is not sufficient -- census script on ALL files before regex. Schema validation != correct text -- content spot-check now wired into parser.


---

## 2026-04-01 — Thomas Aquinas source_title curation

**Branch:** main

**What we worked on:** Populated all 325 blank source_title fields in thomas-aquinas.json. Ran post-task evaluate which surfaced that the required Wikipedia/CCEL research step was skipped. Followed up with WebFetch verification of uncertain assignments (Genesis, Acts, Revelation).

**What was completed:**
- `data/church-fathers/thomas-aquinas.json` — all 325 entries now have source_title
- Validation: 0 errors, 0 warnings (down from 325 source_title warnings)
- `CODING_DEFAULTS.md` (Cowork) — Rule 67 added: verify domain-knowledge inferences against primary source before bulk-writing
- `READY_TO_PASTE_PROMPTS.md` — Thomas Aquinas, Augustine, and Basil marked done in Skip list; warning count updated to 122

**Assignment breakdown:** Commentary on Lamentations (114), Romans (68), Hebrews (54), Summa Theologiae (43 — Genesis/Rev/Isa/Amos/Jonah/Dan), Acts (22), Philemon (19), Psalms (3), Titus (2).

**Verification findings:** Genesis/Revelation → Summa correct (no dedicated commentaries). Acts → *Lectura super Acta Apostolorum* confirmed. Isaiah 11:9 entry contains "(George Haydock)" — likely upstream misattribution; flagged for provenance audit.

**Key decisions:** Acts entries → "Commentary on Acts" not Summa (verse-by-verse structure). Genesis/Revelation → Summa Theologiae (no dedicated commentary confirmed).

---

## 2026-04-01 — Prayer pipeline completion (BCP 1662 + Didache fixes)

**Branch:** main

**What we worked on:** Completed BCP 1662 and Didache prayer parsers. Post-evaluate fixes. End-of-session wrap-up (discovered missed steps and re-ran properly).

**What was completed:**
- `build/parsers/bcp1662.py` — boundary regex fixed (`For the Epistle.` variant in saints.html); docstring updated to document all HTML variants across all 5 pages; word count alarm added (>150 words prints prayer_id)
- `data/prayers/bcp-1662/collects.json` — 85 collects, word count min=30 median=56 max=91
- `data/prayers/didache/prayers.json` — 4 eucharistic prayers generated
- `schemas/v1/prayer.schema.json` — new schema, enums consistent with all other schemas
- `build/validate.py` — `schema_type: prayer` dispatch added
- `README.md` — prayer collections added to status table, repo structure, parsers, sources
- `build/CODE_REVIEWS.md` — entries added: bcp1662.py, didache.py, prayer.schema.json (all pending Opus review)
- Validation: 0 errors across 899 files (`--all`)

**Key decisions made:**
- BCP 1928 already exists (100 collects, built and Opus-reviewed 2026-03-31 per CODE_REVIEWS.md). Context compaction summary showed it as deferred -- corrected during wrap-up by reading CODE_REVIEWS.md and git diff.
- justus.anglican.org confirmed back online (was offline at compaction time).
- Catechism errors confirmed pre-existing fix -- no action needed.

**Process note:** Wrap-up initially run without reading END_OF_SESSION.md. Caught and re-run: memories saved before sign-off corrected; CODE_REVIEWS.md updated; BCP 1928 already-built state surfaced.

**Where we stopped:** All files modified, not committed. Uncommitted pile: prayer pipeline files, source_title patches (Augustine/Basil/Aquinas), baltimore-catechism-no-3 fix, bcp1928.py post-Opus fix.

**What's next:** See top entry.
