"""test_text_utils.py
Unit tests for build.lib.text_utils.smart_title.

Cases derived from real OCR/ALL-CAPS inputs in the OCD parser corpus.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.text_utils import smart_title  # noqa: E402


# ---------------------------------------------------------------------------
# Core apostrophe behaviour
# ---------------------------------------------------------------------------

def test_apostrophe_not_capitalised_after():
    """str.title() bug: 'GOD'S' -> 'God'S'; smart_title must not do this."""
    assert smart_title("GOD'S SOVEREIGNTY DEFINED") == "God's Sovereignty Defined"


def test_curly_apostrophe_not_capitalised_after():
    """Unicode right-single-quote (’) must not be treated as a word boundary."""
    assert smart_title("GOD’S SOVEREIGNTY") == "God’s Sovereignty"


def test_apostrophe_mid_word():
    """Mid-word apostrophe: 'NOBLEMAN'S' -> 'Nobleman's'."""
    assert smart_title("NOBLEMAN'S SON") == "Nobleman's Son"


# ---------------------------------------------------------------------------
# Whitespace normalisation
# ---------------------------------------------------------------------------

def test_double_spaces_collapsed():
    """DjVu OCR often emits multiple spaces; they must be collapsed to one."""
    assert smart_title("THE   VISION   OF   CREATION") == "The Vision Of Creation"


def test_leading_trailing_spaces_stripped():
    assert smart_title("  THE VISION  ") == "The Vision"


# ---------------------------------------------------------------------------
# ALL-CAPS inputs (dominant parser use-case)
# ---------------------------------------------------------------------------

def test_all_caps_plain():
    assert smart_title("THE SOVEREIGNTY OF GOD IN CREATION") == "The Sovereignty Of God In Creation"


def test_single_word_caps():
    """Ordinal like 'FIRST' -> 'First'."""
    assert smart_title("FIRST") == "First"


def test_all_caps_with_number():
    """Numbers should not prevent correct capitalisation of following words."""
    assert smart_title("52 LUTHER'S SERMONS") == "52 Luther's Sermons"


# ---------------------------------------------------------------------------
# Already-normalised input (must not mangle)
# ---------------------------------------------------------------------------

def test_mixed_case_passthrough():
    """Already-title-cased input should come out unchanged."""
    assert smart_title("The Vision of Creation") == "The Vision Of Creation"


def test_single_char():
    assert smart_title("A") == "A"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_string():
    assert smart_title("") == ""


def test_whitespace_only():
    assert smart_title("   ") == ""
