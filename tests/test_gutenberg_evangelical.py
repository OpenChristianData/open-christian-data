"""tests/test_gutenberg_evangelical.py
Unit tests for gutenberg_evangelical.py parser.

Coverage:
  - strip_ia_header: Google Books prefix stripping
  - _normalize_ws: multi-space normalization
  - _is_chapter_heading: generic CHAPTER/CHAP. pattern
  - _is_roman_numeral_alone: Murray Humility pattern
  - _is_allcaps_heading: Drummond Natural Law pattern
  - _is_sect_heading: Carey Enquiry SECT. pattern
  - _is_wilberforce_chapter: Wilberforce CHAPTER/SECTION pattern
  - _is_spurgeon_grace_chapter: Spurgeon All of Grace ALL-CAPS detection
  - gather_paragraphs: blank-line paragraph assembly
  - word_count_blocks: word counting
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build.parsers.gutenberg_evangelical as ev  # noqa: E402


# ---------------------------------------------------------------------------
# strip_ia_header
# ---------------------------------------------------------------------------

def test_strip_ia_header_removes_google_prefix():
    lines = [
        "Digitized by Google",
        "This book was digitized by Google.",
        "Keep it legal.",
        "INTRODUCTION",
        "The book begins here.",
    ]
    result = ev.strip_ia_header(lines)
    assert result[0].strip() == "INTRODUCTION"


def test_strip_ia_header_no_prefix_unchanged():
    lines = ["CHAPTER I", "Some text here."]
    result = ev.strip_ia_header(lines)
    assert result[0].strip() == "CHAPTER I"


def test_strip_ia_header_internet_archive_prefix():
    lines = [
        "Internet Archive",
        "Public domain in the USA.",
        "CHAPTER II",
        "Body text.",
    ]
    result = ev.strip_ia_header(lines)
    assert result[0].strip() == "CHAPTER II"


# ---------------------------------------------------------------------------
# _normalize_ws
# ---------------------------------------------------------------------------

def test_normalize_ws_collapses_multiple_spaces():
    assert ev._normalize_ws("CHAPTER   I") == "CHAPTER I"


def test_normalize_ws_single_space_unchanged():
    assert ev._normalize_ws("CHAPTER I") == "CHAPTER I"


def test_normalize_ws_mixed_whitespace():
    result = ev._normalize_ws("THE   IMPORTANCE   OF   PRAYER")
    assert result == "THE IMPORTANCE OF PRAYER"


# ---------------------------------------------------------------------------
# _is_chapter_heading: CHAPTER I / CHAPTER II etc.
# ---------------------------------------------------------------------------

def test_is_chapter_heading_uppercase_roman():
    assert ev._is_chapter_heading("CHAPTER I") is True


def test_is_chapter_heading_with_period():
    assert ev._is_chapter_heading("CHAPTER I.") is True


def test_is_chapter_heading_title_case():
    assert ev._is_chapter_heading("Chapter III") is True


def test_is_chapter_heading_digit():
    assert ev._is_chapter_heading("CHAPTER 1") is True


def test_is_chapter_heading_chap_abbrev():
    assert ev._is_chapter_heading("CHAP. IV.") is True


def test_is_chapter_heading_not_a_heading():
    assert ev._is_chapter_heading("This is a regular sentence.") is False


def test_is_chapter_heading_not_empty():
    assert ev._is_chapter_heading("") is False


# ---------------------------------------------------------------------------
# _is_roman_numeral_alone: Murray Humility pattern (I., II., etc.)
# ---------------------------------------------------------------------------

def test_roman_numeral_alone_single():
    assert ev._is_roman_numeral_alone("I.") is True


def test_roman_numeral_alone_multi():
    assert ev._is_roman_numeral_alone("XII.") is True


def test_roman_numeral_alone_with_spaces():
    assert ev._is_roman_numeral_alone("   IV.   ") is True


def test_roman_numeral_alone_not_heading():
    # Sentence starting with I. is not a standalone roman numeral heading
    assert ev._is_roman_numeral_alone("I. First of all, because there is a devil.") is False


def test_roman_numeral_alone_without_period():
    # Must end with period to be unambiguous
    assert ev._is_roman_numeral_alone("III") is False


# ---------------------------------------------------------------------------
# _is_allcaps_heading: Drummond Natural Law pattern
# ---------------------------------------------------------------------------

def test_allcaps_heading_biogenesis():
    assert ev._is_allcaps_heading("BIOGENESIS") is True


def test_allcaps_heading_death():
    assert ev._is_allcaps_heading("DEATH.") is True


def test_allcaps_heading_mixed_case():
    assert ev._is_allcaps_heading("Biogenesis") is False


def test_allcaps_heading_too_long():
    # Very long ALL CAPS lines are running headers, not chapter headings
    long = "NATURAL LAW IN THE SPIRITUAL WORLD AND MANY OTHER TOPICS DISCUSSED AT LENGTH"
    assert ev._is_allcaps_heading(long) is False


def test_allcaps_heading_with_page_number():
    # Running headers like "GOD JUSTIFIETH THE UNGODLY. 13" must be excluded
    assert ev._is_allcaps_heading("GOD JUSTIFIETH THE UNGODLY. 13") is False


# ---------------------------------------------------------------------------
# _is_sect_heading: Carey Enquiry SECT. pattern
# ---------------------------------------------------------------------------

def test_sect_heading_roman():
    assert ev._is_sect_heading("SECT. I.") is True


def test_sect_heading_with_spaces():
    assert ev._is_sect_heading("SECT.  V.") is True


def test_sect_heading_not_a_heading():
    assert ev._is_sect_heading("Section heading about prayer.") is False


# ---------------------------------------------------------------------------
# _is_wilberforce_chapter: CHAPTER I. pattern
# ---------------------------------------------------------------------------

def test_wilberforce_chapter():
    assert ev._is_wilberforce_chapter("CHAPTER I.") is True


def test_wilberforce_chapter_vii():
    assert ev._is_wilberforce_chapter("CHAPTER VII.") is True


def test_wilberforce_section():
    assert ev._is_wilberforce_chapter("SECTION II.") is True


def test_wilberforce_chapter_not_heading():
    assert ev._is_wilberforce_chapter("This chapter discusses prayer.") is False


# ---------------------------------------------------------------------------
# _is_spurgeon_grace_chapter: ALL CAPS chapter (no trailing page number)
# ---------------------------------------------------------------------------

def test_spurgeon_grace_chapter_real():
    assert ev._is_spurgeon_grace_chapter("WHAT ARE WE AT?") is True


def test_spurgeon_grace_chapter_god_justifieth():
    assert ev._is_spurgeon_grace_chapter("GOD JUSTIFIETH THE UNGODLY.") is True


def test_spurgeon_grace_chapter_running_header_excluded():
    # Running headers have page numbers like "13" at the end
    assert ev._is_spurgeon_grace_chapter("GOD FUSTIFIETH THE UNGODLY. 13") is False


def test_spurgeon_grace_chapter_mixed_case_excluded():
    assert ev._is_spurgeon_grace_chapter("How May Faith Be Illustrated?") is False


# ---------------------------------------------------------------------------
# gather_paragraphs
# ---------------------------------------------------------------------------

def test_gather_paragraphs_basic():
    lines = ["First paragraph first line.",
             "First paragraph second line.",
             "",
             "Second paragraph."]
    result = ev.gather_paragraphs(lines, 0, len(lines))
    assert len(result) == 2
    assert "First paragraph first line." in result[0]
    assert result[1] == "Second paragraph."


def test_gather_paragraphs_empty_blocks_skipped():
    lines = ["", "", "Text.", "", ""]
    result = ev.gather_paragraphs(lines, 0, len(lines))
    assert result == ["Text."]


def test_gather_paragraphs_respects_bounds():
    lines = ["Line 0.", "Line 1.", "", "Line 3."]
    result = ev.gather_paragraphs(lines, 0, 2)
    assert len(result) == 1
    assert "Line 0." in result[0]


# ---------------------------------------------------------------------------
# word_count_blocks
# ---------------------------------------------------------------------------

def test_word_count_blocks_basic():
    blocks = ["The quick brown fox.", "Jumped over the lazy dog."]
    assert ev.word_count_blocks(blocks) == 9


def test_word_count_blocks_empty():
    assert ev.word_count_blocks([]) == 0


def test_word_count_blocks_single():
    assert ev.word_count_blocks(["Hello world"]) == 2
