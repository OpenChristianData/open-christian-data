# OCD Last Session Log

Newest first.

---

## 2026-04-01 — Token counts backfill + prayer schema + pre-flight check

**Branch:** main

**What we worked on:** Ran `add_token_counts.py` to backfill token counts for all 41,519 records missing counts (SWORD commentaries, BCP 1928/1662, Didache, catechisms, devotionals, church fathers). Added `prayer` schema type support. Improved the script with a pre-flight schema check. Evaluated the session output, updated CODING_DEFAULTS and memory.

**What was completed:**
- `build/scripts/add_token_counts.py` — `prayer` schema type added (tokenises `content_blocks` — spec said `prayer_text` but actual schema uses `content_blocks`); `SCHEMAS_DIR`/`SCHEMA_FILES` config added; `preflight_schema_check()` added — fails hard in live mode if any supported schema doesn't declare `token_count` before any file is written. python-standards-reviewer pass run; 4 findings deferred (see CODE_REVIEWS.md)
- `schemas/v1/prayer.schema.json` — `token_count` property added (schema must be updated before data write — PIPE-14)
- `CODING_DEFAULTS.md` (Cowork) — PIPE-14 added: schema update before data write
- Memory — `feedback_schema_before_data_write.md` saved; `project_ocd_prayer_pipeline.md` updated
- 41,710 records across 151 files now have `token_count` (cl100k_base): all SWORD commentaries, catechisms, church fathers, devotionals, prayers
- Privacy fix: `patch_augustine_source_titles.py` and `patch_basil_source_titles.py` had hardcoded absolute user-path literals — replaced with `Path(__file__).parent.parent.parent / ...` before commit (caught by pre-commit hook)
- Validation: 0 errors, 142 warnings (unchanged)
- Committed: `19e4773`

**Key decisions made:**
- `prayer_text` vs `content_blocks`: spec said `prayer_text` but all prayer records use `content_blocks`. Used `content_blocks` (same as devotional extractor).
- HuggingFace tokenizers: stay with `cl100k_base`. Counts are for rough sizing, not exact context-window arithmetic for a specific model family.
- Preflight check uses literal string search (`'"token_count"' in content`) not JSON parsing — a noted limitation; low risk on current schemas.

**Standards reviewer findings deferred (add_token_counts.py):**
- OUT-01: no `OUTPUT_DIR` constant (script writes in-place by design)
- PIPE-02: no min/median/max token count in summary; no empty-text rate reported
- REL-06: progress fires every 50 files (too coarse for small batches)
- REL-02: preflight error messages could include full path and remediation hint

**Where we stopped:** All work complete and committed.

**What's next:**
1. **Deferred reviewer findings** — add_token_counts.py OUT-01/PIPE-02/REL-06/REL-02 (logged above)
2. **Opus review** — bcp1662.py, didache.py, prayer.schema.json, build_kjv_verse_index.py (flagged in CODE_REVIEWS.md)
3. **Church fathers source_title curation** — 122 warnings remain (one author per session, largest-gap-first)
4. **Cross-ref coverage** — push Barnes above 95% (currently 89.5%)
5. **CI pipeline** — GitHub Actions (Block 2)
6. **HuggingFace** — dataset card + publish (Block 3)

---

## 2026-04-01 — KJV verse index + dynamic OSIS oracle

**Branch:** main

**What we worked on:** Built a second verse index from the KJV SWORD module and wired it into `validate_osis.py` as a dynamic oracle, replacing the hardcoded `KNOWN_OMISSIONS` table.

**What was completed:**
- `build/scripts/download_sword_modules.py` — KJV entry added to MODULES list
- `build/scripts/build_kjv_verse_index.py` — NEW script. Derives verse set from KJV_CANON table (not BZV binary). BZV size check distinguishes truncated (WARN) vs extra slots (INFO). Spot-checks all 10 previously hardcoded KNOWN_OMISSIONS. python-standards-reviewer pass + findings fixed.
- `build/bible_data/kjv_verse_index.json` — NEW artifact. 66 books, 31,162 total verses. Same shape as verse_index.json.
- `build/scripts/validate_osis.py` — `KJV_INDEX_PATH` + `_load_kjv_index()` + lazy-load cache added. `KNOWN_OMISSIONS` emptied to `{}` (kept as empty fallback). Dynamic KJV lookup wired into `_validate_endpoint()` — absent-from-BSB verses checked against KJV before failing.
- `build/CODE_REVIEWS.md` — entries added for both new/modified scripts
- `00 CONTEXT/LESSONS.md` (Cowork) — lesson added: BZV size check before writing binary parser
- Memory files — two feedback memories saved: binary size check, edit collision -> Write

**Key technical decision:** Canon table used as authoritative versification source (not BZV binary) because CrossWire NT BZV is truncated at Rev.19.1 — 86 entries short of the expected 8332.

**Validation:** `py -3 build/validate.py --all` -> 0 errors, 142 warnings (unchanged). `Matt.17.21`, `Mark.9.44`, `John.5.4` all return `OK (in KJV/TR - not in BSB critical text)`.

**Where we stopped:** All work complete. Committed in 19e4773.

**What's next:**
1. **Opus review** — bcp1662.py, didache.py, prayer.schema.json, build_kjv_verse_index.py (flagged in CODE_REVIEWS.md)
2. **Prayer schema** — add per-record source attribution field (prayer.schema.json uses additionalProperties:false; interim fix is collection-level notes in config.json)
3. **Cross-ref coverage** — push Barnes above 95% (currently 89.5%)
4. **CI pipeline** — GitHub Actions (Block 2)
5. **HuggingFace** — dataset card + publish (Block 3)

**Key decisions made:**
- KJV_CANON table is the authoritative source for KJV versification — do not use BZV binary for versification (module defect known, documented)
- OT BZV +19 extra entries = benign apocrypha placeholder slots
- NT BZV truncated = WARNING logged; rebuild hint embedded in log message

---

## 2026-04-01 — Phase 2 red team fixes + Calvin Psalms rebuild + OSIS half-verse support

**Branch:** main

**What we worked on:** Continued from context-compacted session. Completed Calvin Psalms rebuild (1812 entries re-keyed), added half-verse OSIS notation support across the validator stack, ran privacy check, wrote prompts for token counts and KJV verse index tasks.

**What was completed:**
- `build/scripts/rebuild_calvin_psalms.py` — NEW. Re-keys `data/commentaries/calvin/psalms.json` using "PSALM N" headers. Sorts entries before processing (fixes carry-forward correctness). Filters invalid cross-refs via `validate_osis_ref`. Disambiguates duplicate `verse_range_osis` via half-verse suffix on both `verse_range_osis` AND `entry_id`. Adds rebuild note to `provenance.notes`. Result: 1812 entries corrected, 215 duplicates disambiguated, `Isa.330.4` and similar section-number cross-refs stripped.
- `data/commentaries/calvin/psalms.json` — rebuilt in-place. 0 errors, 0 warnings. Known limitation: ~11 no-header Psalm 55 "interloper" entries are misassigned to Psalm 54 (SWORD module packing issue; cannot be fixed by header detection alone — documented in `provenance.notes`).
- `build/scripts/validate_osis.py` — `_find_range_dash` updated to accept letter suffix before dash (`prev_ch.islower()` added); half-verse examples added to `__main__` help text; `_validate_endpoint` strips trailing letter suffix before integer verse lookup.
- `build/validate.py` — `OSIS_REF_PATTERN` and `OSIS_SINGLE_VERSE_PATTERN` updated to accept optional trailing `[a-z]` on verse part; `OSIS_PROOF_REF_PATTERN` likewise updated.
- `READY_TO_PASTE_PROMPTS.md` (Cowork) — two new prompts added: "Token Counts -- Add to All Data Files" and "KJV Verse Index -- Build Second Verse Index from KJV SWORD Module".

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
- `00 CONTEXT/LESSONS.md` (Cowork) — entry added: "Based on the same source" != "contains the same text"
- `build/CODE_REVIEWS.md` — bcp1928.py entry updated (100 -> 102 collects, MANUAL_COLLECTS + EXPECTED_COLLECT_COUNT changes documented)
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
3. CI pipeline (GitHub Actions) -- Block 2
4. Fix Calvin Psalms misalignment (carry-forward from red team session)
5. HuggingFace dataset card and publish -- Block 3

