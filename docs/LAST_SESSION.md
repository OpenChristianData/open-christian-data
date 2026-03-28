# Last Session

## 2026-03-28 -- Westminster Standards Implementation (Phase 1)

### Completed
- Task 1: Citation parser with book abbreviation lookup table (build/lib/citation_parser.py)
- Task 2: Reference parsing with OSIS conversion (parse_single_reference, parse_citation_string)
- Task 3: HTML scraper for thewestminsterstandard.org (6 pages cached)
- Task 4: Schema extended with "directory" and "covenant" kinds; manifest synced to 33 entries
- Task 5: WSC proof texts enriched -- 107/107 questions, 400 total references
- Task 6: 5 new Westminster Standards documents added (directory-for-family-worship, solemn-league-and-covenant, directory-for-publick-worship, form-of-church-government, sum-of-saving-knowledge); manifest synced to 38 entries

### Key decisions
- WSC bare continuation refs (e.g. "15:4") stored with raw source text, OSIS resolved via carry-forward context
- Three documents set to completeness: "partial" -- inline proof extraction deferred to Phase 2
- build/__init__.py added (needed for build.lib.citation_parser import path)
- license: "cc0-1.0" used (not "public-domain") -- matches rest of repo convention

### What's next (Phase 2)
- Inline citation extraction for Form of Church Government, Solemn League, Sum of Saving Knowledge
- Requires Roman numeral chapter support and free-text citation boundary detection
- Consider using pythonbible library (MIT, has built-in Roman numeral support)
