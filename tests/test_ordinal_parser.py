"""tests/test_ordinal_parser.py
Unit tests for the ordinal-to-psalm-number converter in ccel_pdf_commentary.py.

Run with: py -3 -m pytest tests/test_ordinal_parser.py -v
Or:        py -3 tests/test_ordinal_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.parsers.ccel_pdf_commentary import ordinal_to_psalm_number


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check(name: str, expected: int) -> None:
    result = ordinal_to_psalm_number(name)
    assert result == expected, (
        f"ordinal_to_psalm_number({name!r}) returned {result}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_low_ordinals():
    """Psalms 1-20: standalone ordinals used in earlier volumes."""
    check("FIRST", 1)
    check("SECOND", 2)
    check("FIFTH", 5)
    check("TENTH", 10)
    check("NINETEENTH", 19)
    check("TWENTIETH", 20)


def test_simple_compound_ordinals():
    check("FIFTY-THIRD", 53)
    check("FIFTY-FOURTH", 54)
    check("FIFTY-FIFTH", 55)
    check("FIFTY-SIXTH", 56)
    check("FIFTY-SEVENTH", 57)
    check("FIFTY-EIGHTH", 58)
    check("FIFTY-NINTH", 59)


def test_standalone_tens():
    """Standalone -IETH forms for every decade 30-100."""
    check("THIRTIETH", 30)
    check("FORTIETH", 40)
    check("FIFTIETH", 50)   # regression: was returning 0 before FIFTIETH added to TENS
    check("SIXTIETH", 60)
    check("SEVENTIETH", 70)
    check("EIGHTIETH", 80)
    check("NINETIETH", 90)
    check("HUNDREDTH", 100)


def test_compound_sixties():
    check("SIXTY-FIRST", 61)
    check("SIXTY-SECOND", 62)
    check("SIXTY-THIRD", 63)
    check("SIXTY-FOURTH", 64)
    check("SIXTY-FIFTH", 65)
    check("SIXTY-SIXTH", 66)
    check("SIXTY-SEVENTH", 67)
    check("SIXTY-EIGHTH", 68)
    check("SIXTY-NINTH", 69)


def test_compound_seventies():
    """These were the bug class: SEVENTY-FIRST through SEVENTY-EIGHTH all returned 70."""
    check("SEVENTY-FIRST", 71)
    check("SEVENTY-SECOND", 72)
    check("SEVENTY-THIRD", 73)
    check("SEVENTY-FOURTH", 74)
    check("SEVENTY-FIFTH", 75)
    check("SEVENTY-SIXTH", 76)
    check("SEVENTY-SEVENTH", 77)
    check("SEVENTY-EIGHTH", 78)


def test_compound_eighties():
    check("EIGHTY-FIRST", 81)
    check("EIGHTY-FIFTH", 85)
    check("EIGHTY-NINTH", 89)


def test_compound_nineties():
    check("NINETY-FIRST", 91)
    check("NINETY-FIFTH", 95)
    check("NINETY-NINTH", 99)


def test_compound_hundreds():
    """Psalms 101-150 use 'HUNDRED AND X' form."""
    check("HUNDRED AND FIRST", 101)
    check("HUNDRED AND TENTH", 110)
    check("HUNDRED AND NINETEENTH", 119)
    check("HUNDRED AND FIFTIETH", 150)


def test_roman_numerals():
    check("LIII", 53)
    check("LIX", 59)
    check("LX", 60)
    check("LXIV", 64)
    check("LXX", 70)
    check("LXXVIII", 78)


def test_ocr_corrections():
    check("TPIFTY-FOURTH", 54)    # TPIFTY -> FIFTY
    check("FIFTY-FIFTII", 55)     # FIFTII -> FIFTH (FIFTY-FIFTH)
    check("FIFTY-EIGUTH", 58)     # EIGUTH -> EIGHTH
    check("NIGHTIETH", 90)        # NIGHTIETH -> NINETIETH (OCR confusion n/ni)


def test_space_separated():
    """OCR sometimes produces spaces instead of hyphens."""
    check("SEVENTY EIGHTH", 78)
    check("SIXTY SECOND", 62)


def test_trailing_page_artifacts():
    """ordinal_to_psalm_number strips trailing whitespace+word-chars (page numbers)."""
    check("FIFTY-THIRD 42", 53)
    check("SIXTY-FIRST 7", 61)
    check("SEVENTY-EIGHTH 123", 78)


def test_invalid_returns_zero():
    assert ordinal_to_psalm_number("") == 0
    assert ordinal_to_psalm_number("BWEL") == 0
    assert ordinal_to_psalm_number("TECX VV LL") == 0


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_low_ordinals,
        test_simple_compound_ordinals,
        test_standalone_tens,
        test_compound_sixties,
        test_compound_seventies,
        test_compound_eighties,
        test_compound_nineties,
        test_compound_hundreds,
        test_roman_numerals,
        test_ocr_corrections,
        test_space_separated,
        test_trailing_page_artifacts,
        test_invalid_returns_zero,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
