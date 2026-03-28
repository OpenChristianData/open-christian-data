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
