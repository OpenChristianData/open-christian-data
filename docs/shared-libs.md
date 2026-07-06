# Shared libraries — guide

## bible_ref_normalizer.py (canonical OSIS shared library)

`build/lib/bible_ref_normalizer.py` (684 lines) is the canonical shared library for OSIS book-name mapping in OCD. Import it instead of writing per-parser reference lookup.

Handles:
- 179+ book abbreviations including rare and archaic forms
- OCR typos (e.g. `Actsts`, `Hen` for `Heb`)
- HelloAO digit-after format (`Sa1`, `Kg2`)
- Maclaren Roman-numeral chapter format
- ThML `scripRef` tag parsing and plain-text extraction

Public API: `parse_thml_refs()`, `extract_refs_from_text()`, `parse_maclaren_ref()`.

Currently used by `sword_commentary.py` and `helloao_commentary.py`. New parsers handling Bible references should import it rather than reinventing.

The library is rung-2 (shared lib) but not yet used by every parser that handles references. It is manually maintained, not auto-generated or drift-checked against schemas.

## citation_parser.py is intentionally separate

`build/lib/citation_parser.py` (~226 book abbreviations, no OCR handling) is used by the Westminster Standard parser for WSC proof-text citations. It is **not a redundant duplicate** — WSC proof texts have a cleaner format that doesn't need OCR correction. The two libraries serve different source formats.

**Do not merge them. Do not flag `citation_parser.py` as redundant in a future audit.**

A prior Red Team pass flagged OSIS mapping as a drift-class candidate. The answer is: `bible_ref_normalizer.py` resolved it for commentary/CCEL sources; `citation_parser.py` is an intentional lighter-weight alternative for WSC.
