"""test_ccel_church_history.py
Unit tests for ccel_church_history.py pure functions.

Covers the key correctness invariants that were bugs during T5-4b development:
  - translator$ regex anchor: 'Translator's Preface.' must match is_editorial_div()
  - _EDITORIAL_TITLE_PATTERNS: title-based editorial skip logic
  - OSIS prefix stripping: 'Bible:' and 'Bible.kjv:' variants
  - get_div_label_title: label/title extraction from div attributes

Added 2026-04-22 as T5-4b closeout (TDD retro).
"""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.ccel_church_history import (  # noqa: E402
    _EDITORIAL_TITLE_PATTERNS,
    is_editorial_div,
    get_div_label_title,
    get_scriptrefs,
)


# ---------------------------------------------------------------------------
# _EDITORIAL_TITLE_PATTERNS -- positive (should match = editorial)
# ---------------------------------------------------------------------------

def test_pattern_title_page():
    assert _EDITORIAL_TITLE_PATTERNS.match("Title Page.") is not None


def test_pattern_preface():
    assert _EDITORIAL_TITLE_PATTERNS.match("Preface.") is not None


def test_pattern_preface_case_insensitive():
    assert _EDITORIAL_TITLE_PATTERNS.match("preface") is not None


def test_pattern_translator_exact():
    """'Translator' alone must match (was bug: translator$ required end-of-string)."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Translator") is not None


def test_pattern_translator_apostrophe():
    """'Translator's Preface.' must match — key T5-4b regression fix."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Translator's Preface.") is not None


def test_pattern_translator_s_notes():
    """'Translator's Notes' variant must match."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Translator's Notes") is not None


def test_pattern_indexes():
    assert _EDITORIAL_TITLE_PATTERNS.match("General Indexes.") is not None


def test_pattern_index_of():
    assert _EDITORIAL_TITLE_PATTERNS.match("Index of Scripture References") is not None


def test_pattern_subject_index():
    assert _EDITORIAL_TITLE_PATTERNS.match("Subject Index") is not None


# ---------------------------------------------------------------------------
# _EDITORIAL_TITLE_PATTERNS -- negative (should NOT match = keep content)
# ---------------------------------------------------------------------------

def test_pattern_introduction_not_editorial():
    """'Introduction' is kept as content — common chapter type."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Introduction") is None


def test_pattern_book_not_editorial():
    assert _EDITORIAL_TITLE_PATTERNS.match("Book I") is None


def test_pattern_prolegomena_not_editorial():
    assert _EDITORIAL_TITLE_PATTERNS.match("Prolegomena.") is None


# ---------------------------------------------------------------------------
# is_editorial_div -- type= attribute path
# ---------------------------------------------------------------------------

def test_editorial_div_preface_type():
    """div with type='Preface' is editorial."""
    elem = ET.fromstring('<div2 type="Preface" title="Preface"/>')
    assert is_editorial_div(elem) is True


def test_editorial_div_toc_type():
    """div with type='Table of Contents' is editorial."""
    elem = ET.fromstring('<div2 type="Table of Contents" title="Contents"/>')
    assert is_editorial_div(elem) is True


def test_editorial_div_translators_preface_title():
    """T5-4b regression: div with title='Translator' must be editorial."""
    elem = ET.fromstring('<div2 title="Translator" id="iv.ii"/>')
    assert is_editorial_div(elem) is True


def test_editorial_div_intro_not_editorial():
    """div with title='Introduction.' is content, not editorial."""
    elem = ET.fromstring('<div2 type="Book" title="Introduction." n="I"/>')
    assert is_editorial_div(elem) is False


def test_editorial_div_book_not_editorial():
    """div with type='Book' and title='Book I' is content."""
    elem = ET.fromstring('<div2 type="Book" title="Book I" n="I"/>')
    assert is_editorial_div(elem) is False


# ---------------------------------------------------------------------------
# get_div_label_title -- label/title extraction
# ---------------------------------------------------------------------------

def test_label_from_type_and_n():
    elem = ET.fromstring('<div2 type="Book" n="I" title="Book I"/>')
    label, title = get_div_label_title(elem)
    assert label == "Book I"


def test_title_strips_label_prefix():
    """Title 'Book I: The Church' should strip 'Book I' prefix."""
    elem = ET.fromstring('<div2 type="Book" n="I" title="Book I: The Church"/>')
    label, title = get_div_label_title(elem)
    assert "Book I" not in title
    assert "Church" in title


def test_label_none_when_no_n():
    elem = ET.fromstring('<div2 title="Prolegomena."/>')
    label, title = get_div_label_title(elem)
    assert label is None or label == ""
    assert title == "Prolegomena."


# ---------------------------------------------------------------------------
# get_scriptrefs -- OSIS prefix stripping
# ---------------------------------------------------------------------------

def test_scriptrefs_strips_bible_prefix():
    """'Bible:Acts.13' should produce 'Acts.13' in osis list."""
    xml = '<p><scripRef osisRef="Bible:Acts.13">Acts 13</scripRef></p>'
    elem = ET.fromstring(xml)
    refs = get_scriptrefs(elem)
    assert refs[0]["osis"] == ["Acts.13"]


def test_scriptrefs_strips_bible_kjv_prefix():
    """'Bible.kjv:Matt.5.3' should produce 'Matt.5.3' — canonical regex pattern."""
    xml = '<p><scripRef osisRef="Bible.kjv:Matt.5.3">Matt 5:3</scripRef></p>'
    elem = ET.fromstring(xml)
    refs = get_scriptrefs(elem)
    assert refs[0]["osis"] == ["Matt.5.3"]


def test_scriptrefs_raw_text_preserved():
    xml = '<p><scripRef osisRef="Bible:John.3.16">John 3:16</scripRef></p>'
    elem = ET.fromstring(xml)
    refs = get_scriptrefs(elem)
    assert refs[0]["raw"] == "John 3:16"


def test_scriptrefs_empty_when_no_refs():
    xml = '<p>No scripture references here.</p>'
    elem = ET.fromstring(xml)
    refs = get_scriptrefs(elem)
    assert refs == []
