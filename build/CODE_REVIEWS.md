# Code Reviews — Open Christian Data

| Script | Last Reviewed | Notes |
|---|---|---|
| build/parsers/matthew_henry_helloao.py | 2026-03-28 | Opus review: no critical issues. H3 grand summary added, M1 whitespace fix applied. H2 retry deferred (API mode secondary). M2 mutation, M3 return ambiguity noted but not blocking. |
| build/parsers/creeds_json_confession.py | 2026-03-28 | Opus review: M1 VALID_TRADITIONS missing particular-baptist -- fixed. L1/L2 map_proofs+log duplication noted (defer to shared module when parser count grows). |
| build/parsers/creeds_json_catechism.py | 2026-03-28 | Opus review: H1 author null (fixed in schema). M2 _parse_sort_key now warns on non-numeric Number (fixed). M3 --all wrapped in try/finally (fixed). L1-L3 duplication noted (defer). |
| build/validate.py | 2026-03-28 | Opus review (2nd pass): no new issues. Partial completeness logic correct. Previous M4/M7 still accepted. |
| schemas/v1/commentary.schema.json | never | Phase 1a |
| schemas/v1/catechism_qa.schema.json | 2026-03-28 | Opus review: H1 author type changed from string to ["string", "null"] to match doctrinal_document pattern and handle empty Authors in source. |
| schemas/v1/doctrinal_document.schema.json | never | Task 3 |
