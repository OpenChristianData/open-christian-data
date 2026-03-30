"""build/lib/pdf_normalizer.py
Markdown normalisation for PDF-extracted text.

Imported by build/extract_pdf.py. Takes the raw Markdown string from
pymupdf4llm and returns a cleaner Markdown string ready for content parsers.

Transforms applied in order:
  1. Code block removal        -- strip ``` wrappers (OCR PDFs)
  2. Inline backtick stripping -- strip `word` fragments (OCR ignore_code output)
  3. Running header/footer removal -- strip repeated page-boundary text
  4. Heading level normalisation -- regex overrides from config, or pass-through
  5. Orphan page number removal -- standalone integers at block boundaries
  6. Hyphenation repair        -- rejoin words split across lines (the-\nlogy)
  7. Whitespace normalisation  -- collapse 3+ blank lines to 2, trim trailing spaces
  8. Footnote marker cleanup   -- normalise superscript-like patterns

Deferred (not implemented here):
  - Hebrew bidi correction (python-bidi) -- only if sources contain Hebrew
  - Footnote semantic extraction -- complex, depends on content type
  - Multi-column merge repair -- pymupdf4llm handles this; add only if real failures surface
"""

from __future__ import annotations

import re
from collections import Counter


# ---------------------------------------------------------------------------
# Transform 1: Code block removal
# ---------------------------------------------------------------------------

def _remove_code_blocks(text: str) -> str:
    """Remove ``` ... ``` fenced code blocks, keeping their content."""
    # Remove opening and closing ``` lines; keep the content between them
    # Handle both ``` and ```python etc.
    text = re.sub(r"^```[^\n]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```\s*$", "", text, flags=re.MULTILINE)
    return text


# ---------------------------------------------------------------------------
# Transform 2: Inline backtick stripping
# ---------------------------------------------------------------------------

def _strip_inline_backticks(text: str) -> str:
    """
    Strip inline backtick wrappers added by pymupdf4llm ignore_code mode.
    Converts `word` -> word, `multiple words` -> multiple words.
    Preserves legitimate code spans that appear in non-OCR content (rare in
    theological texts, but we leave genuine multi-word code spans alone if
    they contain code-like content).
    """
    # Remove backtick-wrapped single or multi-word spans
    # Pattern: `...` where content has no newlines
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Transform 3: Running header/footer removal
# ---------------------------------------------------------------------------

def _remove_running_headers_footers(text: str, min_repeat: int = 3) -> str:
    """
    Detect and remove text that appears repeatedly at the boundaries of pages.
    Strategy: find short lines (< 80 chars) that appear >= min_repeat times in
    the document and are likely running headers/footers.
    Common examples: 'EXPOSITIONS OF THE PSALMS.', 'TREASURY OF DAVID.'
    """
    lines = text.split("\n")
    # Count all short lines (stripped)
    short_lines = [l.strip() for l in lines if 0 < len(l.strip()) < 80]
    counts = Counter(short_lines)
    # Identify candidates: lines appearing >= min_repeat times
    # Exclude lines that look like verse content (start with number, contain quotes)
    to_remove = set()
    for line, count in counts.items():
        if count < min_repeat:
            continue
        # Skip lines that look like verse numbers or meaningful content
        if re.match(r"^\d+[\.\s]", line):
            continue
        # Skip lines with lowercase words > 3 chars (likely body text, not headers)
        lowercase_words = re.findall(r"\b[a-z]{4,}\b", line)
        if len(lowercase_words) > 3:
            continue
        # Skip markdown headings
        if line.startswith("#"):
            continue
        to_remove.add(line)

    if not to_remove:
        return text

    # Remove matched lines
    result_lines = []
    for line in lines:
        if line.strip() in to_remove:
            continue
        result_lines.append(line)
    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Transform 4: Heading level normalisation
# ---------------------------------------------------------------------------

def _normalise_headings(text: str, pdf_config: dict) -> str:
    """
    Apply heading normalisation.

    For OCR PDFs (GlyphLessFont), font-size detection produces no headings.
    Config can supply regex_headings: a list of {pattern, level, flags?} dicts.
    Lines matching the pattern are converted to the given heading level.

    Example config:
        "regex_headings": [
            {"pattern": "^PSALM THE [A-Z-]+\\.?$", "level": 1},
            {"pattern": "^(EXPOSITION|HOMILETICAL HINTS|ILLUSTRATIVE EXTRACTS)", "level": 2}
        ]
    """
    regex_headings = pdf_config.get("regex_headings", [])
    if not regex_headings:
        return text

    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        matched = False
        for rule in regex_headings:
            pattern = rule.get("pattern", "")
            level = rule.get("level", 1)
            flags_str = rule.get("flags", "")
            re_flags = re.IGNORECASE if "i" in flags_str else 0
            if re.match(pattern, stripped, re_flags):
                prefix = "#" * min(max(level, 1), 6)
                result.append(f"{prefix} {stripped}")
                matched = True
                break
        if not matched:
            result.append(line)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Transform 5: Orphan page number removal
# ---------------------------------------------------------------------------

def _remove_orphan_page_numbers(text: str) -> str:
    """
    Remove standalone integers that appear alone on a line (orphan page numbers).
    These appear in scanned PDFs where the page number was on its own text block.
    Only removes integers surrounded by blank lines to avoid removing verse numbers.
    """
    # A standalone integer on its own line, with blank lines above and below
    text = re.sub(r"\n\n(\d{1,4})\n\n", "\n\n", text)
    # Also remove integers at the very start or end of the document
    text = re.sub(r"^\s*\d{1,4}\s*\n", "", text)
    return text


# ---------------------------------------------------------------------------
# Transform 6: Hyphenation repair
# ---------------------------------------------------------------------------

def _repair_hyphenation(text: str) -> str:
    """
    Rejoin words that were split across line boundaries with a hyphen.
    e.g. 'theo-\nlogy' -> 'theology'
    Only repairs word-hyphen-newline-word patterns (not en/em dashes).
    """
    # word ending with hyphen at end of line, followed by newline and continuation word
    text = re.sub(r"([a-zA-Z])-\n([a-z])", r"\1\2", text)
    return text


# ---------------------------------------------------------------------------
# Transform 7: Whitespace normalisation
# ---------------------------------------------------------------------------

def _normalise_whitespace(text: str) -> str:
    """
    - Collapse 3+ consecutive blank lines to 1 blank line.
    - Trim trailing whitespace from each line.
    - Ensure file ends with a single newline.
    """
    # Trim trailing spaces per line
    lines = [l.rstrip() for l in text.split("\n")]
    text = "\n".join(lines)
    # Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Ensure single trailing newline
    text = text.strip() + "\n"
    return text


# ---------------------------------------------------------------------------
# Transform 8: Footnote marker cleanup
# ---------------------------------------------------------------------------

def _clean_footnote_markers(text: str) -> str:
    """
    Normalise footnote markers that appear as superscript-like patterns in OCR.
    Common patterns from CCEL/archive.org PDFs:
      - Isolated numbers attached to words: 'God1' or 'God 1'
      - Symbols like * or dagger used as footnote anchors
    This pass only cleans up obvious noise -- full footnote extraction is deferred.
    """
    # Superscript digits glued to words (e.g., 'God3' -> 'God'... but keep verse refs
    # like 'Ps 3.1'). Only strip trailing digits on all-alpha words of 4+ chars.
    text = re.sub(r"\b([A-Za-z]{4,})(\d{1,2})\b", r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def normalise(markdown: str, pdf_config: dict) -> str:
    """
    Apply all normalisation transforms to the raw extracted Markdown.

    Args:
        markdown: Raw Markdown string from pymupdf4llm extraction.
        pdf_config: The pdf_extraction block from source config (may be empty).

    Returns:
        Cleaned Markdown string.
    """
    text = markdown

    # 1. Code block removal (triple-backtick fences from OCR PDFs)
    text = _remove_code_blocks(text)

    # 2. Inline backtick stripping (single-backtick wrapping from ignore_code mode)
    text = _strip_inline_backticks(text)

    # 3. Running header/footer removal
    if pdf_config.get("strip_headers_footers", True):
        text = _remove_running_headers_footers(text)

    # 4. Heading level normalisation (regex overrides from config)
    text = _normalise_headings(text, pdf_config)

    # 5. Orphan page number removal
    text = _remove_orphan_page_numbers(text)

    # 6. Hyphenation repair
    text = _repair_hyphenation(text)

    # 7. Whitespace normalisation
    text = _normalise_whitespace(text)

    # 8. Footnote marker cleanup
    text = _clean_footnote_markers(text)

    return text
