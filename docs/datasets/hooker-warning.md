# WARNING — hooker-ecclesiastical-polity.json contains synthetic chapter boundaries

**Do not trust the committed `data/structured-text/hooker-ecclesiastical-polity.json` chapter-level data until it has been regenerated against source locators.**

## What's wrong

Books I–VII have fabricated chapter boundaries. Only Book VIII (9 chapters) has source-derived boundaries.

The OCR detection (`_hooker_chapter_events`) found far fewer chapter markers than expected (e.g. Book V: 5 detected vs 81 expected). The arithmetic-fallback at `build/parsers/gutenberg_systematics.py:1390–1396` distributed boundaries evenly by count.

The IA DjVuTXT OCR for the Keble edition renders chapter headings inconsistently — inline Roman numerals, running headers, and editorial notes all contain Roman numerals, making reliable detection hard.

## What this means in practice

- Schema validation passes
- Chapter counts are correct
- But the boundaries themselves are arithmetic, not source-derived
- Any downstream use of chapter-level data inherits the fabrication

## Remediation plan

Run the boundary hardening plan from `research/t7-4-hooker-10-10-claude-review-report.md`:

1. Build a per-chapter locator table from IA page/HOCR data
2. Make the parser refuse to emit chapters without a source locator (see `.claude/rules/parsers.md`)
3. Regenerate and revalidate

Also fix `tests/test_hooker_gutenberg_systematics.py::test_parse_hooker_ignores_selected_editorial_apparatus` — the test fixture starts with Book III, which triggers the book-anchor guard. Prepend "THE FIRST BOOK." to the fixture lines.

## Status

Treat the Hooker JSON as an acquisition scaffold, not a trustworthy final dataset.
