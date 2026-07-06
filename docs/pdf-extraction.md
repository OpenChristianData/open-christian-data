# PDF extraction

PDF sources use pymupdf4llm → quality gate → normalizer → clean Markdown, which content-type parsers then consume.

## Tool choice — pymupdf4llm

Selected 2026-03-28 after deep tool comparison. Plan at `.claude/plans/jolly-knitting-wind.md`.

- Speed: 0.14s/page vs Docling's 3s+
- Better heading hierarchy on clean PDFs (font-size heuristics from text layer)
- No ML models or GPU

Docling reserved as manual fallback for scanned/image-only PDFs only.

## Pipeline

`build/extract_pdf.py` and `build/parsers/ccel_pdf_commentary.py` are implemented and code-reviewed. Both use:

- `_TeeWriter` logging
- `try/except` wrap on multi-item loops
- Path constants at top of file

`build/lib/pdf_quality_gate.py` and `build/lib/pdf_normalizer.py` are also reviewed.

Tests at `tests/test_ordinal_parser.py` cover all 150 psalms via full-range probe.

## Known limitations

- **Hebrew RTL broken in ALL open-source PDF tools** — word order reverses within Hebrew runs. Mitigation: python-bidi post-processing or manual review.
- **Footnotes are positional** (page-bottom detection), not semantically linked to reference marks in body text.
- **pymupdf4llm is rules-based** — no column detection ML. Complex multi-column layouts may need Docling.

## When to add a new PDF source

Use `build/extract_pdf.py`. Don't revisit tool choice unless a source is scanned/image-only or has complex multi-column layout.
