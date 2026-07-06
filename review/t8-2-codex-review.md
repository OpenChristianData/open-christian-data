# T8-2 Codex Review — Flavel Remaining Works

Date: 2026-05-07
Reviewer: Claude (Sonnet 4.6)
Prompt: `prompts/t8-2-flavel-remaining.md`
Codex report: `CLAUDE_FLAVEL_T8_2_REPORT.md`
Commit verified: `60c544c` (Method of Grace), `9e7de55` (registry), `1a1d5b4` (LAST_SESSION.md)

---

## Coverage

| Deliverable | Status | Evidence / Notes |
|---|---|---|
| Mystery of Providence parsed | ✗ Missing | Valid stop — 4 CCEL URL patterns tried, all 404. Documented in LAST_SESSION.md. |
| Method of Grace JSON | ✓ Done | Committed in `60c544c`; 35 sections per test assertion. |
| Source census file | ~ Partial | `research/prompts/t8-2-census.md` exists locally but gitignored. Key findings in LAST_SESSION.md. |
| Structural census documented | ✓ Done | Parser docstring + LAST_SESSION.md (div1:39, editorial filters, 35 retained). |
| `sources/structured-text/flavel-method-of-grace/config.json` | ✓ Done | Committed in `60c544c`. |
| Parser extended (not new file) | ✓ Done | WORK_CONFIG entry + editorial regex in `ccel_puritan_works.py`. |
| Provenance fields on all records | ✓ Done | `source_type`, `source_url`, `source_file`, `source_hash`, `translator: null` all present. |
| Author registry updated | ✓ Done | `flavel-method-of-grace` added to `john-flavel.works` in `9e7de55`. |
| Tests — editorial filter | ✓ Done | `test_editorial_flavel_method_epistle_front_matter`, `test_editorial_flavel_method_dedicatory_front_matter`. |
| Tests — section count | ✓ Done | `"flavel-method-of-grace": 35` in `_EXPECTED_TOP_SECTIONS`. |
| validate.py 0 errors | ✓ Done | Confirmed in LAST_SESSION.md; `--all` shows only known Fisher Marrow error. |
| py -m pytest 0 new failures | ✓ Done | 1235 passed; 2 failures both pre-existing. |
| LAST_SESSION.md updated | ✓ Done | Committed in `1a1d5b4`; contains identifiers, counts, div structure, deferred items. |

## Correctness Issues

**`original_publication_year: 2000`** — CCEL's `DC.Date` header is the digitisation date (2000-07-09), not the historical first publication (1820 per title page). The prompt said "read pub_year from DC.Date" which is technically correct per the instruction but semantically wrong for OCD's field. Needs human decision: change to 1820 and keep the CCEL date in `source_edition` only (where it already appears), or leave as-is with a schema note.

**`source_file` uses Windows backslash** — `"raw\\ccel\\flavel\\grace.xml"` in the JSON data file. Other CCEL parsers on Windows will produce the same result. Cross-platform portability issue; POSIX-style forward slashes are conventional for data files.

**`ZoneInfo("Australia/Melbourne")` → `timezone.utc`** — Swapped because Python 3.14 in the Codex sandbox lacks `tzdata`. Global rules (principles.md) say "Melbourne timezone." Affects only the `download_date` field in source configs. The underlying issue (no tzdata in Codex Python 3.14) is documented separately.

## Out-of-Scope Changes

- `SCRIPT_VERSION` bumped to `v1.0.1` — harmless.
- Docstring title/author counts updated (18→19, Flavel x1→x2) — accurate.
- `ZoneInfo` → `timezone.utc` affects ALL future downloads through this parser, not just Method of Grace.
- `py -m pip install --force-reinstall pytest` ran outside repo to fix the Codex sandbox. Will recur on any fresh Codex run.

## Verdict

Codex delivered everything possible. Method of Grace is correctly parsed, validated, tested, and committed. Mystery of Providence correctly stopped per the 404 stop-rule. Three minor correctness issues all flagged in the Codex report and awaiting human decisions.

## Open Decisions

1. `original_publication_year`: 2000 (DC.Date) or 1820 (historical)? Recommendation: 1820 — OCD semantics clearly want the historical publication year.
2. Census file: force-add `research/prompts/t8-2-census.md` to git, or accept LAST_SESSION.md as sufficient?
3. Windows backslash in `source_file`: systemic fix in parsers, or leave?
