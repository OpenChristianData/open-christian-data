# Code Reviews — Open Christian Data

| Script | Last Reviewed | Notes |
|---|---|---|
| build/parsers/ccel_owen_works.py | 2026-04-23 | Opus reviewed 2026-04-23 (9 major findings). extract_heading multi-pass fix applied (87cd69b). Deferred: download retry, Appendices hoisting, section-type inference from heading, lang= detection, scripRef dedup. |
| build/parsers/tests/test_ccel_owen_works.py | 2026-04-23 | 79 cases. test_extract_heading_chapter_h2_with_title_attr updated (87e913b): assertion now tests correct behaviour (subtitle from title= attr, not ''). |
| build/scripts/add_pg_whitefield_sermons.py | 2026-04-17 | One-shot patch script (adds 2 PG-unique Whitefield sermons). Standards-reviewer pass. |
| build/scripts/patch_haimo_source_titles.py | 2026-04-12 | One-shot patch script. Standards-reviewer pass. |
| build/scripts/patch_titlecase_source_titles.py | 2026-04-12 | One-shot bulk normalisation. Standards-reviewer pass. |
| build/scripts/patch_pacian_source_titles.py | 2026-04-12 | Nil patch (0 entries). Standards-reviewer pass. |
| build/scripts/patch_source_title_thietland_of_einsiedeln.py | 2026-04-12 | Standards-reviewer pass. |
| build/parsers/ia_schaff_herzog.py | 2026-04-15 | Standards-reviewer pass. is_running_header() fragment rewrite + PIPE-05 fix. Opus review pending. |
| build/parsers/ia_hastings_dictionary.py | 2026-04-30 | Opus + Codex review (T6-7 follow-up). Fixed 3 critical (re-run dedup losing within-run dups; Form 1 over-permissive on body labels like LXX:/RV:; Form 3 over-permissive on ALL-CAPS body sentences and OCR THE-variant page headers; front-matter line-400 skip globally rather than vol-keyed) and 4 important (Vol 5 homoglyph guard now raises HomoglyphSkip → process_volume returns skipped-by-guard, not error; _OCR_CORRECTIONS load logged via main(); clean_term fallback no longer returns full prose; non-ASCII guard scoped to known-bad vols). 6 regression fixtures added. Re-parsed: 2705 → 2502 entries (junk headings removed). |
| build/parsers/ccel_schaff_herzog.py | never | Needs Opus review — merge bug fixed (e549b1c), completeness flag, 13-vol support |
| build/parsers/ccel_expositors_bible.py | never | Needs Opus review — 48-vol registry, 4 parse patterns, cross-chapter range fix, dedup logic. 2026-04-14: _CCEL_OSISREF_CORRECTIONS table added (4 entries) |
| build/scripts/patch_gregory_nazianzus_source_titles.py | never | Needs Opus review |
| build/scripts/patch_gregory_nazianzus_col_jer.py | never | Needs Opus review |
| build/scripts/patch_jerome_source_titles.py | never | Needs Opus review |
| build/scripts/patch_chrysostom_source_titles.py | never | Needs Opus review |
| build/parsers/spurgeon_mtp_missing.py | never | Needs Opus review — two HTML parsers (AiG + archive.spurgeon.org), JSON patch + verify logic |
| build/parsers/church_fathers.py | never | Needs Opus review — NameError fix + REL-03 added since last review |
| build/parsers/helloao_commentary.py | never | Needs Opus review — intro entries added (2.2.0) |
| build/validate.py | never | Needs Opus review — intro-entries handling added |
| build/parsers/westminster_standard_parser.py | never | Needs Opus review — PY-06 changes 2026-04-12 |
| build/scripts/generate_disputed_verses.py | never | Needs Opus review — PY-06 changes 2026-04-12 |
| build/parsers/gutenberg_maclaren.py | 2026-04-23 | Opus reviewed 2026-04-23 (8 major findings). Fixes applied: urllib.error import, module-level constant, author_id, book ToC + volume-intro phantom filter (312456a, e2fdd08). Deferred: sermon_id stability, series label fragility, primary_reference_text convention. |
