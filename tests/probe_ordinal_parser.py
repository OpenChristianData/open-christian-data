"""tests/probe_ordinal_parser.py
Exhaustive probe: generates the expected ordinal string for every psalm (1-150)
and checks ordinal_to_psalm_number() returns the correct number.

Run before writing tests, and after touching the parser or OCR corrections table:
    py -3 tests/probe_ordinal_parser.py

Exit 0 = all 150 pass. Exit 1 = failures reported.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.parsers.ccel_pdf_commentary import ordinal_to_psalm_number


# ---------------------------------------------------------------------------
# Ordinal generator: int -> string as used in Spurgeon running headers
# ---------------------------------------------------------------------------

_ONES = [
    "", "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH",
    "SEVENTH", "EIGHTH", "NINTH", "TENTH", "ELEVENTH", "TWELFTH",
    "THIRTEENTH", "FOURTEENTH", "FIFTEENTH", "SIXTEENTH", "SEVENTEENTH",
    "EIGHTEENTH", "NINETEENTH",
]

_TENS_ORDINAL = [
    "", "", "TWENTIETH", "THIRTIETH", "FORTIETH", "FIFTIETH",
    "SIXTIETH", "SEVENTIETH", "EIGHTIETH", "NINETIETH",
]

_TENS_STEM = [
    "", "", "TWENTY", "THIRTY", "FORTY", "FIFTY",
    "SIXTY", "SEVENTY", "EIGHTY", "NINETY",
]


def psalm_ordinal(n: int) -> str:
    """Return the English ordinal name for psalm number n (1-150).

    Examples:
        psalm_ordinal(1)   -> "FIRST"
        psalm_ordinal(20)  -> "TWENTIETH"
        psalm_ordinal(53)  -> "FIFTY-THIRD"
        psalm_ordinal(100) -> "HUNDREDTH"
        psalm_ordinal(119) -> "HUNDRED AND NINETEENTH"
    """
    if not 1 <= n <= 150:
        raise ValueError(f"Psalm number out of range: {n}")
    if n == 100:
        return "HUNDREDTH"
    if n > 100:
        return f"HUNDRED AND {psalm_ordinal(n - 100)}"
    if n < 20:
        return _ONES[n]
    if n % 10 == 0:
        return _TENS_ORDINAL[n // 10]
    return f"{_TENS_STEM[n // 10]}-{_ONES[n % 10]}"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def run_probe() -> int:
    """Check all 150 psalms. Returns number of failures."""
    failures = []
    for psalm in range(1, 151):
        expected_ordinal = psalm_ordinal(psalm)
        result = ordinal_to_psalm_number(expected_ordinal)
        if result != psalm:
            failures.append((psalm, expected_ordinal, result))

    if failures:
        print(f"FAIL  {len(failures)}/150 psalms parsed incorrectly:")
        for psalm, ordinal, got in failures:
            print(f"  Psalm {psalm:3d}  ordinal={ordinal!r:40s}  got={got}")
    else:
        print(f"PASS  all 150 psalms parsed correctly")

    return len(failures)


if __name__ == "__main__":
    sys.exit(1 if run_probe() else 0)
