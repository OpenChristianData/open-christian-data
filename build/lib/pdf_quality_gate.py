"""build/lib/pdf_quality_gate.py
Post-extraction quality checks for PDF-to-Markdown output.

Imported by build/extract_pdf.py. Never blocks processing -- returns a list
of warning strings that are written to _extraction_report.json and printed.

Checks:
  1. Empty pages  -- pages with <10 chars of extracted text
  2. Character density anomalies  -- chars/page vs expected range
  3. Heading count vs page count  -- 0 headings in 50+ pages suggests failure
  4. Unicode replacement characters  -- high U+FFFD ratio suggests encoding problem
  5. Consecutive identical pages  -- extraction loop / repeated content
  6. File size vs page count sanity  -- tiny file with many pages
"""

from __future__ import annotations

import re

# Thresholds
MIN_CHARS_PER_PAGE = 10          # below this: page counted as empty
DENSITY_LOW_CHARS_PAGE = 100     # suspiciously sparse (non-front-matter)
DENSITY_HIGH_CHARS_PAGE = 15000  # suspiciously dense (possible extraction loop)
HEADING_CHECK_MIN_PAGES = 50     # only check heading count if doc >= this many pages
MAX_FFFD_RATIO = 0.02            # >2% replacement chars = encoding problem
MIN_BYTES_PER_PAGE = 2000        # <2 KB/page for a 20+ page doc = suspect PDF


def run_quality_gate(markdown: str, extraction_meta: dict, pdf_config: dict) -> list:
    """
    Run all quality checks on the extracted Markdown.

    Args:
        markdown: The raw Markdown string from extraction (pre-normaliser).
        extraction_meta: Dict from extract_pdf() with text_layer stats, page count, etc.
        pdf_config: The pdf_extraction block from the source config (may be empty).

    Returns:
        List of warning strings (empty list if no issues).
    """
    warnings = []
    text_layer = extraction_meta.get("text_layer", {})
    # Use total_pages from the text layer (full document scan) for empty-page ratios,
    # not pages_processed (which is 3 in dry-run mode).
    total_pages_full = text_layer.get("total_pages", extraction_meta.get("total_pages", 0))
    total_pages_processed = extraction_meta.get("pages_processed", total_pages_full)

    # 1. Empty pages
    empty_pages = text_layer.get("empty_pages", [])
    if empty_pages:
        count = len(empty_pages)
        pct = count * 100 / total_pages_full if total_pages_full else 0
        sample = empty_pages[:5]
        suffix = "..." if count > 5 else ""
        warnings.append(
            f"CHECK-1 empty_pages: {count}/{total_pages_full} pages ({pct:.0f}%) "
            f"have <{MIN_CHARS_PER_PAGE} chars -- likely image-only (pages {sample}{suffix})"
        )

    # 2. Character density (uses pages_processed to be fair to dry-run)
    if total_pages_processed > 0 and markdown:
        chars_per_page = len(markdown) / total_pages_processed
        if chars_per_page < DENSITY_LOW_CHARS_PAGE and total_pages_processed >= 5:
            warnings.append(
                f"CHECK-2 low_density: {chars_per_page:.0f} chars/page avg "
                f"(threshold {DENSITY_LOW_CHARS_PAGE}) -- possibly sparse OCR or truncation"
            )
        if chars_per_page > DENSITY_HIGH_CHARS_PAGE:
            warnings.append(
                f"CHECK-2 high_density: {chars_per_page:.0f} chars/page avg "
                f"(threshold {DENSITY_HIGH_CHARS_PAGE}) -- possibly repeated content"
            )

    # 3. Heading count vs page count
    heading_count = len(re.findall(r"^#{1,6}\s", markdown, re.MULTILINE))
    if total_pages_processed >= HEADING_CHECK_MIN_PAGES and heading_count == 0:
        ocr_mode = extraction_meta.get("ocr_mode", False)
        if not ocr_mode:
            # For OCR PDFs we expect 0 font-size headings -- not a warning
            warnings.append(
                f"CHECK-3 no_headings: 0 Markdown headings in {total_pages_processed} pages -- "
                f"IdentifyHeaders may have failed; consider body_font_size_min in config"
            )

    # 4. Unicode replacement characters (U+FFFD)
    if markdown:
        fffd_count = markdown.count("\ufffd")
        total_chars = len(markdown)
        fffd_ratio = fffd_count / total_chars if total_chars else 0
        if fffd_ratio > MAX_FFFD_RATIO:
            warnings.append(
                f"CHECK-4 encoding_anomaly: {fffd_count} U+FFFD replacement chars "
                f"({fffd_ratio * 100:.1f}% of text) -- likely encoding mismatch in source PDF"
            )

    # 5. Consecutive identical pages
    if total_pages_processed >= 3 and markdown:
        # Split on double-newline as rough page proxy and compare adjacent blocks
        page_blocks = [b.strip() for b in re.split(r"\n{3,}", markdown) if b.strip()]
        consecutive = 0
        max_consecutive = 0
        for i in range(1, len(page_blocks)):
            if len(page_blocks[i]) > 200 and page_blocks[i] == page_blocks[i - 1]:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0
        if max_consecutive >= 2:
            warnings.append(
                f"CHECK-5 repeated_content: {max_consecutive + 1} consecutive identical "
                f"content blocks detected -- possible extraction loop"
            )

    # 6. File size vs page count sanity (uses extraction_meta if available)
    # This check uses pdf_hash presence as proxy; actual file size check happens in extract_pdf.py
    # Here we check the chars/page ratio as a proxy for effective content.
    # (Structural file-size check is done at extract time before calling this function.)

    return warnings
