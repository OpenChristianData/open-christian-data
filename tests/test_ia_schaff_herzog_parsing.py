"""test_ia_schaff_herzog_parsing.py
Unit tests for is_running_header() in build/parsers/ia_schaff_herzog.py.

Tests OCR-variant running-header cases encountered during
Schaff-Herzog IA vol 10 and vol 12 development, plus census variants
confirmed across all 9 IA volumes (2026-04-14).

Retro finding 2026-04-14: new parser shipped without automated tests.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.ia_schaff_herzog import is_running_header  # noqa: E402


# ---------------------------------------------------------------------------
# Should be detected as running headers (True)
# ---------------------------------------------------------------------------

def test_standard_running_header():
    """Standard form: left-side page header."""
    assert is_running_header("THE NEW SCHAFF-HERZOG") is True


def test_ocr_schaff_with_the_prefix():
    """OCR corruption with THE prefix preserved: caught by THE heuristic.
    Note: the full page header 'THE NEW SCHAFF-HERZOG' OCR-corrupts to
    'THE 8CHAFF-HERZ0G', not standalone '8CHAFF-HERZ0G'."""
    assert is_running_header("THE 8CHAFF-HERZ0G") is True


def test_schaff_standalone_no_the_prefix():
    """'8CHAFF-HERZ0G' alone (no 'THE ' prefix): caught by fragment matching.
    After stripping digits/punctuation: 'CHAFF HERZG' -> schaff_frag (CHAFF)
    and herz_frag (HERZ) both match -> True."""
    assert is_running_header("8CHAFF-HERZ0G") is True


def test_religious_encyclopedia_standard():
    """Standard form: right-side page header."""
    assert is_running_header("RELIGIOUS ENCYCLOPEDIA") is True


def test_religious_encyclopedia_ocr_reugious():
    """OCR corruption: 'L' dropped from 'RELIGIOUS' -> 'REUGIOUS'.
    len('REUGIOUS ENCYCLOPEDIA') = 21 < 30, so short-form threshold catches it."""
    assert is_running_header("REUGIOUS ENCYCLOPEDIA") is True


def test_encyclopedia_religiods_variant():
    """'ENCYCLOPEDIA OF RELIGIODS KNOWLEDGE': OCR corrupts 'RELIGIOUS'.
    ENCY fragment (encyclopedia) + RELIG fragment in 'RELIGIODS' -> True."""
    assert is_running_header("ENCYCLOPEDIA OF RELIGIODS KNOWLEDGE") is True


def test_encyclopedia_of_religious_knowledge():
    """Section header that precedes the first article."""
    assert is_running_header("ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE") is True


def test_the_prefix_heuristic_general():
    """Any line starting with 'THE ' is treated as a header variant."""
    assert is_running_header("THE something") is True


def test_religious_encyclopedu():
    """Most common OCR variant: 'A' dropped from end of ENCYCLOPEDIA.
    Appears in 6 of 9 volumes."""
    assert is_running_header("RELIGIOUS ENCYCLOPEDU") is True


def test_religious_knowledge_standalone():
    """Right-side running header (no 'ENCYCLOPEDIA'). Appears in 8 of 9 volumes."""
    assert is_running_header("RELIGIOUS KNOWLEDGE") is True


def test_ihb_new_schaff_double_corruption():
    """Double OCR corruption in vol 11: 'THE' -> 'IHB', digits sub for letters.
    Neither THE prefix nor TH[A-Z] matches 'IHB', but schaff_frag (CHAFF) and
    herz_frag (HERZ) both present -> True."""
    assert is_running_header("IHB NEW 8CHAFF-HERZ00") is True


def test_thb_new_schaff_herzoq():
    """'THE' OCR'd to 'THB' (vol 10). schaff_frag (SCHAFF) and herz_frag
    (HERZ in HERZOQ) both present -> True."""
    assert is_running_header("THB NEW SCHAFF-HERZOQ") is True


# ---------------------------------------------------------------------------
# Should NOT be detected as running headers (False)
# ---------------------------------------------------------------------------

def test_legitimate_article_simple():
    """Simple all-caps article heading -> not a running header."""
    assert is_running_header("AARON") is False


def test_legitimate_article_inverted_name():
    """Inverted-name article heading -> not a running header."""
    assert is_running_header("ZWINGLI, ULRICH") is False


def test_legitimate_article_inverted_name_2():
    assert is_running_header("CALVIN, JOHN") is False


def test_schaff_person_not_header():
    """'SCHAFF, PHILIP': schaff_frag matches but herz_frag absent -> False."""
    assert is_running_header("SCHAFF, PHILIP") is False


def test_comparative_religion():
    """Contains RELIG but no ENCY/NCYCL and no KNOWLEDGE -> False."""
    assert is_running_header("COMPARATIVE RELIGION") is False


def test_revivals_of_religion():
    """Contains RELIG but no ENCY/NCYCL and no KNOWLEDGE -> False."""
    assert is_running_header("REVIVALS OF RELIGION") is False


def test_empty_string():
    """Empty string -> False (not a header)."""
    assert is_running_header("") is False


def test_lowercase_content_line():
    """Lowercase body text -> False."""
    assert is_running_header("born in thrace around 285 ad") is False


# ---------------------------------------------------------------------------
# Run directly for quick feedback
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
