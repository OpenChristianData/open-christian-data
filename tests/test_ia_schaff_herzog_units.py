"""test_ia_schaff_herzog_units.py
Unit tests for ia_schaff_herzog pure functions:
  is_article_heading, is_page_marker, clean_term, _BODY_MARKER_RE pattern.

is_running_header is covered separately in test_ia_schaff_herzog_parsing.py.

Added 2026-04-15 as part of T5-3c closeout.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.ia_schaff_herzog import (  # noqa: E402
    is_article_heading,
    is_page_marker,
    clean_term,
)


# ---------------------------------------------------------------------------
# is_article_heading -- positive cases (should return True)
# ---------------------------------------------------------------------------

def test_article_heading_form1_inline():
    """Form 1: TERM: body text on same line."""
    assert is_article_heading("AARON: Older brother of Moses") is True


def test_article_heading_form2_standalone_colon():
    """Form 2: TERM: with trailing colon only, no body on this line."""
    assert is_article_heading("ZWINGLI, ULRICH:") is True


def test_article_heading_form3_trailing_period():
    """Form 3: standalone ALL CAPS with trailing period."""
    assert is_article_heading("LUTHERANS.") is True


def test_article_heading_form3_inverted_name():
    """Form 3: standalone ALL CAPS inverted name (comma, no colon).
    is_running_header returns False for SCHAFF, PHILIP (herz_frag absent),
    so is_article_heading sees it as a valid all-caps line."""
    assert is_article_heading("SCHAFF, PHILIP") is True


# ---------------------------------------------------------------------------
# is_article_heading -- negative cases (should return False)
# ---------------------------------------------------------------------------

def test_article_heading_not_roman_numeral_section():
    """Roman-numeral section header 'I. History:' fails the ^[A-Z]{2} guard
    (only one uppercase letter before the period) -> False."""
    assert is_article_heading("I. History:") is False


def test_article_heading_not_running_header():
    """Running page header -> is_running_header catches it -> False.
    is_article_heading calls is_running_header internally."""
    assert is_article_heading("THE NEW SCHAFF-HERZOG") is False


def test_article_heading_not_page_number():
    """Standalone page number: no leading uppercase letters -> False."""
    assert is_article_heading("244") is False


def test_article_heading_empty_string():
    """Empty string: ^[A-Z]{2} guard fails immediately -> False."""
    assert is_article_heading("") is False


# ---------------------------------------------------------------------------
# is_page_marker -- positive cases (should return True)
# ---------------------------------------------------------------------------

def test_page_marker_volume_chapter_1():
    """Volume-chapter marker: Roman numeral + separator + digit."""
    assert is_page_marker("III.- 1") is True


def test_page_marker_volume_chapter_2():
    """Volume-chapter marker with higher Roman numerals."""
    assert is_page_marker("VIII.- 32") is True


def test_page_marker_standalone_page_number():
    """Standalone page number."""
    assert is_page_marker("244") is True


def test_page_marker_standalone_year():
    """Standalone year matched by the digit-only pattern."""
    assert is_page_marker("1909") is True


def test_page_marker_short_ocr_garbage():
    """Short non-alpha, non-digit string (OCR garbage): len<=3, no alpha -> True.
    Note: 'ab' would NOT match because it contains alpha characters.
    '--' has len=2 and no alpha -> matches the garbage guard."""
    assert is_page_marker("--") is True


# ---------------------------------------------------------------------------
# is_page_marker -- negative cases (should return False)
# ---------------------------------------------------------------------------

def test_page_marker_not_article_heading():
    """Legitimate all-caps article heading -> False."""
    assert is_page_marker("AARON") is False


def test_page_marker_not_inline_article():
    """Inline article heading with body -> False."""
    assert is_page_marker("AARON: body text here") is False


# ---------------------------------------------------------------------------
# clean_term -- OCR correction table
# Pre-flight: verified corrections table keys and clean_term logic.
# ---------------------------------------------------------------------------

def test_clean_term_ocr_space_insertion():
    """Space-insertion OCR corruption: 'THE ATINES' -> 'THEATINES'."""
    assert clean_term("THE ATINES") == "THEATINES"


def test_clean_term_ocr_digit_sub_variant1():
    """Digit substitution (0->O, 8->S): 'THE0T0K08' -> 'THEOTOKOS'."""
    assert clean_term("THE0T0K08") == "THEOTOKOS"


def test_clean_term_ocr_digit_sub_variant2():
    """Digit substitution (0->O, 0->O, 0->O): 'THE0T0K0S' -> 'THEOTOKOS'."""
    assert clean_term("THE0T0K0S") == "THEOTOKOS"


def test_clean_term_pronunciation_guide_stripped():
    """Pronunciation guide (all-lowercase comma segment) is stripped.
    Input 'CHAMIER, ahd/mye, DANIEL': 'ahd/mye' has upper_ratio=0 (<0.70)
    -> dropped. 'CHAMIER' and 'DANIEL' both ratio=1.0 -> kept.
    Example is from clean_term() docstring."""
    assert clean_term("CHAMIER, ahd/mye, DANIEL") == "CHAMIER, DANIEL"


def test_clean_term_no_change_schaff():
    """No OCR corruption, no pronunciation guide -> returned unchanged."""
    assert clean_term("SCHAFF") == "SCHAFF"


def test_clean_term_no_change_aaron():
    """No OCR corruption, no pronunciation guide -> returned unchanged."""
    assert clean_term("AARON") == "AARON"


# ---------------------------------------------------------------------------
# _BODY_MARKER_RE
#
# _BODY_MARKER_RE is a local variable inside parse_volume_text(), so it cannot
# be imported directly.  We compile the same pattern here and verify it matches
# the three known OCR forms and rejects two known non-forms.
#
# The live code also enforces len(norm) < 50 to exclude false positives;
# that length guard is not tested here (pure regex behaviour only).
# ---------------------------------------------------------------------------

_BODY_MARKER_PATTERN = re.compile(
    r"ENCYCLOPEDIA\s+OF\s+RELI\w+\s+KNOWLEDGE", re.IGNORECASE
)


def test_body_marker_standard_form():
    """Standard section header that opens the A-Z article body."""
    assert _BODY_MARKER_PATTERN.search("ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE") is not None


def test_body_marker_religiods_ocr_variant():
    """vol 10 OCR variant: 'RELIGIODS' instead of 'RELIGIOUS'.
    RELI\\w+ matches RELIGIODS."""
    assert _BODY_MARKER_PATTERN.search("ENCYCLOPEDIA OF RELIGIODS KNOWLEDGE") is not None


def test_body_marker_trailing_artifact():
    """vol 12 OCR variant: trailing '^' artifact after KNOWLEDGE."""
    assert _BODY_MARKER_PATTERN.search("ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE^") is not None


def test_body_marker_not_religious_encyclopedia():
    """Right-side running header 'RELIGIOUS ENCYCLOPEDIA' must NOT match
    (no 'OF' and no 'KNOWLEDGE')."""
    assert _BODY_MARKER_PATTERN.search("RELIGIOUS ENCYCLOPEDIA") is None


def test_body_marker_not_article():
    """Ordinary article heading must NOT match."""
    assert _BODY_MARKER_PATTERN.search("AARON: body text") is None


# ---------------------------------------------------------------------------
# Corrections table migration tests (B5 / Task 7)
# ---------------------------------------------------------------------------

def test_clean_term_ocr_correction_the0t0k0s():
    """THE0T0K0S is corrected to THEOTOKOS via corrections table."""
    result = clean_term("THE0T0K0S")
    assert result == "THEOTOKOS", f"Expected THEOTOKOS, got {result}"


def test_clean_term_ocr_correction_the0t0k08():
    """THE0T0K08 is corrected to THEOTOKOS via corrections table."""
    result = clean_term("THE0T0K08")
    assert result == "THEOTOKOS", f"Expected THEOTOKOS, got {result}"


def test_clean_term_ocr_correction_space_insertion():
    """THE ATINES (OCR space-insertion) is corrected to THEATINES via corrections table."""
    result = clean_term("THE ATINES")
    assert result == "THEATINES", f"Expected THEATINES, got {result}"


def test_corrections_table_file_exists():
    """schaff-herzog corrections table file exists at expected path."""
    corrections_path = (
        Path(__file__).resolve().parents[1]
        / "build" / "tools" / "ocr_scanner" / "corrections" / "schaff-herzog.json"
    )
    assert corrections_path.exists(), f"Corrections table not found at {corrections_path}"


# ---------------------------------------------------------------------------
# Run directly for quick feedback (mirrors test_ia_schaff_herzog_parsing.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
