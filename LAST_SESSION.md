# OCD Last Session Log

Newest first.

---

## 2026-04-01 — Phase 2 red team fixes + Calvin Psalms rebuild + OSIS half-verse support

**Branch:** main

**What we worked on:** Continued from context-compacted session. Completed Calvin Psalms rebuild (1812 entries re-keyed), added half-verse OSIS notation support across the validator stack, ran privacy check, wrote prompts for token counts and KJV verse index tasks.

**What was completed:**
- `build/scripts/rebuild_calvin_psalms.py` — NEW. Re-keys `data/commentaries/calvin/psalms.json` using "PSALM N" headers. Sorts entries before processing (fixes carry-forward correctness). Filters invalid cross-refs via `validate_osis_ref`. Disambiguates duplicate `verse_range_osis` via half-verse suffix on both `verse_range_osis` AND `entry_id`. Adds rebuild note to `provenance.notes`. Result: 1812 entries corrected, 215 duplicates disambiguated, `Isa.330.4` and similar section-number cross-refs stripped.
- `data/commentaries/calvin/psalms.json` — rebuilt in-place. 0 errors, 0 warnings. Known limitation: ~11 no-header Psalm 55 "interloper" entries are misassigned to Psalm 54 (SWORD module packing issue; cannot be fixed by header detection alone — documented in `provenance.notes`).
- `build/scripts/validate_osis.py` — `_find_range_dash` updated to accept letter suffix before dash (`prev_ch.islower()` added); half-verse examples added to `__main__` help text; `_validate_endpoint` strips trailing letter suffix before integer verse lookup.
- `build/validate.py` — `OSIS_REF_PATTERN` and `OSIS_SINGLE_VERSE_PATTERN` updated to accept optional trailing `[a-z]` on verse part; `OSIS_PROOF_REF_PATTERN` likewise updated.
- `READY_TO_PASTE_PROMPTS.md` (Cowork) — two new prompts added: "Token Counts — Add to All Data Files" and "KJV Verse Index — Build Second Verse Index from KJV SWORD Module".

**Privacy check:** Clean. No credentials, API keys, personal emails, or private data in any diff.

**Validation:** 0 errors, 142 warnings across 900 files (unchanged).

**Key decisions made:**
- Half-verse suffixes (`Ps.21.2b`) accepted in `verse_range_osis` and `entry_id` — standard scholarly notation for verse halves; valid in all three OSIS patterns.
- Calvin Psalms duplicate disambiguation uses half-verse suffix on `verse_range_osis` (not just `entry_id`) — this is semantically correct since the SWORD module packed two psalms' content into the same verse slot.
- ~11 residual interloper entries (Psalm 55 content in SWORD chapter 56 slot, no header, inherited Psalm 54 context) accepted as known limitation and documented in `provenance.notes`.

**Where we stopped:** All code changes complete. Not yet committed — commit is next step.

**What's next:**
1. **Commit** all uncommitted work (red team fixes, BCP 1928, prayer pipeline, source_title curations, Calvin Psalms rebuild, OSIS half-verse support — ~118 modified files + 3 new scripts)
2. **Token counts** — run prompt from READY_TO_PASTE_PROMPTS.md (41,519 records across 148 files missing counts)
3. **KJV verse index** — run prompt from READY_TO_PASTE_PROMPTS.md (replaces hardcoded KNOWN_OMISSIONS)
4. **Notify SWORD project** about Calvin Psalms misindexing bug
5. **Opus review** — bcp1662.py, didache.py, prayer.schema.json (flagged in CODE_REVIEWS.md)
6. **CI pipeline** — GitHub Actions (Block 2)
7. **HuggingFace** — dataset card + publish (Block 3)

---

## 2026-04-01 — BCP 1928 Trinity 23/24 gap fill + primary source verification

**Branch:** main

**What we worked on:** Filled the last two gaps in the BCP 1928 collect set — Trinity23 and Trinity24, which are absent from episcopalnet.org (hymn suggestions only on those pages). Verified texts against the 1928 US BCP primary scan on archive.org.

**What was completed:**
- `build/parsers/bcp1928.py` — `MANUAL_COLLECTS` dict added for trinity23/trinity24; `EXPECTED_COLLECT_COUNT = 102` assertion before write; `parse_all_pages()` returns 3-tuple (records, errors, manual_count); SCRIPT_VERSION bumped to v1.1.0; docstring updated to cite archive.org as source
- `sources/prayers/bcp-1928-collects/config.json` — `notes` field extended: cites archive.org/details/1928bookofcommon0000prot pp.222-223; documents two textual differences from 1662 BCP (semicolon after "godliness"; "for the sake of Jesus Christ" not "for Jesus Christ's sake")
- `data/prayers/bcp-1928/collects.json` — 102 collects (100 parsed, 2 manual). Trinity23 (45 words), Trinity24 (49 words) inserted.
- `README.md` — both occurrences of "98 collects" updated to "102 collects"
- `CODING_DEFAULTS.md` (Cowork) — PIPE-13 added: verbatim text from named edition requires primary source scan verification
- `00 CONTEXT/LESSONS.md` (Cowork) — entry added: "Based on the same source" ≠ "contains the same text"
- `build/CODE_REVIEWS.md` — bcp1928.py entry updated (100 → 102 collects, MANUAL_COLLECTS + EXPECTED_COLLECT_COUNT changes documented)
- `02 PERSONAL/PERSONAL_PROJECTS.md` — BCP 1928 count updated to 102; prayer schema attribution backlog item added

**Key error caught and fixed:**
- Initial draft used 1662 Church of England BCP text (from CoE website) for both collects. Primary source verification via archive.org Playwright navigation revealed two differences in the actual 1928 US text: Trinity23 uses semicolon after "godliness" (not colon); Trinity24 uses "for the sake of Jesus Christ" (not "for Jesus Christ's sake"). Both texts corrected before commit.

**Schema limitation identified:**
- `prayer.schema.json` uses `additionalProperties: false` on both item and context objects — no field exists for per-record source attribution. Interim fix: collection-level `notes` in config.json. Proper fix (per-record provenance field in prayer schema) logged in PERSONAL_PROJECTS.md backlog.

**Validation:** 0 errors, 142 warnings across 900 files (unchanged — warnings are pre-existing Barnes/Calvin cross-reference issues in working tree, not committed).

**Where we stopped:** All code changes complete. Not committed.

**What's next:**
1. Commit BCP 1928 Trinity23/24 changes + all pending uncommitted work
2. Token counts: `add_token_counts.py` across SWORD + BCP 1928 files (still pending)
3. CI pipeline (GitHub Actions) — Block 2
4. Fix Calvin Psalms misalignment (carry-forward from red team session)
5. HuggingFace dataset card and publish — Block 3

---

## 2026-04-01 — Phase 2 red team digest + all fixes + Calvin Psalms misalignment

**Branch:** main

**What we worked on:** Digested the Phase 2 red team output (5 files, 16 findings). Fixed all 16 findings across `bible_ref_normalizer.py`, `sword_commentary.py`, `validate.py`, `build_verse_index.py`, `validate_osis.py`, `extract_pdf.py`. Rebuilt Barnes, Wesley, Calvin. Discovered Calvin Psalms misalignment as a bonus finding.

**What was completed:**
- `build/lib/bible_ref_normalizer.py` — `jud`→Judges fix; stale-context clear on failed tokens; new `_BOOK_CHAP_ONLY_RE` handler for chapter-only tokens (root cause of `1Kgs.104.3`); added aliases: `co→Col`, `re→Rev`, `so→Song`, `actsts→Acts`, `hen→Heb`
- `build/parsers/sword_commentary.py` — `_split_ref_candidates()` for multi-ref Wesley strings; both ThML patterns always collected (removed else branch); per-entry `clean_markup` try/except; `_filter_osis_refs()` strips impossible refs at build time (fixes Calvin section-number refs)
- `build/validate.py` — `jsonschema` ImportError now `sys.exit(1)`; string cross_refs queued for existence checks + hard errors; range-end overshoots downgraded to warnings; doctrinal tree leaf/non-leaf invariants
- `build/scripts/validate_osis.py` — explicit verse sets (not max-verse); `KNOWN_OMISSIONS` table (Matt 17:21/18:11/23:14, Mark 7:16/9:44,46/11:26/15:28, Luke 17:36/23:17, John 5:4, Acts 8:37/15:34/24:7/28:29, Rom 16:24); range-end lenient validation
- `build/scripts/build_verse_index.py` — hard abort on skipped files, duplicate book_osis, malformed rows; assert 66 books before write
- `build/extract_pdf.py` — quality gate blocks on <10% text pages; `--force` override; OCR detection samples 5 pages by majority vote; per-PDF `_extraction_report.json`
- `requirements.txt` — `jsonschema==4.26.0` added
- Rebuilt Barnes (7322 entries, 89.5% refs), Wesley (17564 entries, 15.2% refs), Calvin (13338 entries, 75.0% refs)
- Validation: **0 errors, 142 warnings** across 900 files

**Bonus finding — Calvin Psalms misalignment:**
- Calvin's Psalms commentary is systematically misindexed in the SWORD module. Entries are tagged with the wrong OSIS chapter (e.g. `Ps.22.*` contains Calvin's commentary on LXX Psalm 20/21, not MT Psalm 22). The offset is inconsistent (not a clean +1 shift) and affects most of the 150 Psalms.
- **Action required:** Rebuild `calvin/psalms.json` using the "PSALM N" header in Calvin's own text to assign the correct chapter. ✅ Done in next session.
- **External note needed:** Notify the SWORD project about the misindexing in the Calvin Psalms module.

**KJV verse index (discussed, not built):**
- Proposed: download KJV SWORD module, build a second verse index, update `validate_osis_ref` to check BSB then KJV — would replace the hardcoded `KNOWN_OMISSIONS` table. Prompt written in READY_TO_PASTE_PROMPTS.md.

**Where we stopped:** Code changes complete, not committed.

**What's next:** See top entry.

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
- BCP 1928 already exists (100 collects, built and Opus-reviewed 2026-03-31 per CODE_REVIEWS.md). Context compaction summary showed it as deferred — corrected during wrap-up by reading CODE_REVIEWS.md and git diff.
- justus.anglican.org confirmed back online (was offline at compaction time).
- Catechism errors confirmed pre-existing fix — no action needed.

**Process note:** Wrap-up initially run without reading END_OF_SESSION.md. Caught and re-run: memories saved before sign-off corrected; CODE_REVIEWS.md updated; BCP 1928 already-built state surfaced.

**Where we stopped:** All files modified, not committed. Uncommitted pile: prayer pipeline files, source_title patches (Augustine/Basil/Aquinas), baltimore-catechism-no-3 fix, bcp1928.py post-Opus fix.

**What's next:** See top entry.

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

**Where we stopped:** All work complete. Not yet committed.

**What's next:** See top entry.
