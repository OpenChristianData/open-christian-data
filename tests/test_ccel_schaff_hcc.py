"""test_ccel_schaff_hcc.py
Unit tests for ccel_schaff_hcc.py pure functions.

Covers:
  - _SEC_HEADING_P_RE: section-heading paragraph skip (§ N. Title pattern)
  - get_scriptrefs: OSIS prefix stripping (Bible: and Bible.kjv:)
  - parse_section: basic chapter/section parsing from minimal XML
  - parse_chapter: skip logic for Preface/ToC div2 types

Added 2026-04-22 as T5-4b closeout (TDD retro).
"""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.ccel_schaff_hcc import (  # noqa: E402
    _SEC_HEADING_P_RE,
    _SKIP_DIV2_TYPES,
    get_scriptrefs,
    parse_section,
    parse_chapter,
)


# ---------------------------------------------------------------------------
# _SEC_HEADING_P_RE -- positive (should match = skip as duplicate heading)
# ---------------------------------------------------------------------------

def test_heading_re_section_sign_arabic():
    """'§ 1. Title' is a duplicate section heading."""
    assert _SEC_HEADING_P_RE.match("\u00a7 1. Nature of Church History") is not None


def test_heading_re_section_sign_roman():
    """'§ i. Literature' is a duplicate section heading."""
    assert _SEC_HEADING_P_RE.match("\u00a7 i. Literature") is not None


def test_heading_re_digit_dot_space():
    """'1. Title' without § sign should also match."""
    assert _SEC_HEADING_P_RE.match("1. Opening paragraph") is not None


def test_heading_re_roman_dot_space():
    """'III. Title' without § sign should match."""
    assert _SEC_HEADING_P_RE.match("III. Nicene Creed") is not None


# ---------------------------------------------------------------------------
# _SEC_HEADING_P_RE -- negative (should NOT match = keep as content)
# ---------------------------------------------------------------------------

def test_heading_re_prose_not_skipped():
    """Normal prose content must not match."""
    assert _SEC_HEADING_P_RE.match("The church was founded in Jerusalem.") is None


def test_heading_re_bare_title_not_skipped():
    """A bare title word without numeral prefix must not be skipped."""
    assert _SEC_HEADING_P_RE.match("Literature") is None


def test_heading_re_authors_name_not_skipped():
    """Bibliographic entries starting with a name must not match."""
    assert _SEC_HEADING_P_RE.match("Philip Schaff, What is Church History?") is None


# ---------------------------------------------------------------------------
# _SKIP_DIV2_TYPES -- editorial type set
# ---------------------------------------------------------------------------

def test_skip_preface_type():
    assert "Preface" in _SKIP_DIV2_TYPES


def test_skip_toc_type():
    assert "Table of Contents" in _SKIP_DIV2_TYPES


def test_chapter_type_not_skipped():
    assert "Chapter" not in _SKIP_DIV2_TYPES


# ---------------------------------------------------------------------------
# get_scriptrefs -- OSIS prefix stripping (key T5-4b fix)
# ---------------------------------------------------------------------------

def test_scriptrefs_bible_prefix():
    """'Bible:Acts.13' strips to 'Acts.13' — most common HCC pattern."""
    xml = '<p><scripRef osisRef="Bible:Acts.13">Acts 13</scripRef></p>'
    refs = get_scriptrefs(ET.fromstring(xml))
    assert refs[0]["osis"] == ["Acts.13"]


def test_scriptrefs_bible_kjv_prefix():
    """'Bible.kjv:Matt.5.3' uses canonical re.sub pattern (not .replace)."""
    xml = '<p><scripRef osisRef="Bible.kjv:Matt.5.3">Matt 5:3</scripRef></p>'
    refs = get_scriptrefs(ET.fromstring(xml))
    assert refs[0]["osis"] == ["Matt.5.3"]


def test_scriptrefs_multiple_refs():
    """Multiple space-separated refs in one osisRef attribute."""
    xml = '<p><scripRef osisRef="Bible:Col.1.16 Bible:Col.1.18">Col 1:16,18</scripRef></p>'
    refs = get_scriptrefs(ET.fromstring(xml))
    assert refs[0]["osis"] == ["Col.1.16", "Col.1.18"]


def test_scriptrefs_none_when_empty():
    xml = '<p>No refs.</p>'
    refs = get_scriptrefs(ET.fromstring(xml))
    assert refs == []


# ---------------------------------------------------------------------------
# parse_section -- minimal XML
# ---------------------------------------------------------------------------

_SECTION_XML = """<div3 type="Section" n="1" title="Nature of Church History" id="i.v.1">
  <p>\u00a7 1. Nature of Church History.</p>
  <p>History has two sides, a divine and a human.</p>
  <p>The church is the body of Christ.</p>
</div3>"""


def test_parse_section_returns_dict():
    div3 = ET.fromstring(_SECTION_XML)
    result = parse_section(div3)
    assert result is not None
    assert result["section_type"] == "section"


def test_parse_section_label():
    div3 = ET.fromstring(_SECTION_XML)
    result = parse_section(div3)
    assert result["label"] == "\u00a7 1"


def test_parse_section_title():
    div3 = ET.fromstring(_SECTION_XML)
    result = parse_section(div3)
    assert result["title"] == "Nature of Church History"


def test_parse_section_skips_heading_paragraph():
    """First '§ 1. ...' paragraph must be skipped as duplicate heading."""
    div3 = ET.fromstring(_SECTION_XML)
    result = parse_section(div3)
    assert result is not None
    for block in result["content_blocks"]:
        assert not block.startswith("\u00a7 1.")


def test_parse_section_has_content():
    div3 = ET.fromstring(_SECTION_XML)
    result = parse_section(div3)
    assert len(result["content_blocks"]) >= 1
    assert result["word_count"] > 0


def test_parse_section_none_when_empty():
    """div3 with no content_blocks returns None."""
    empty = ET.fromstring('<div3 type="Section" n="1" title="Empty"/>')
    result = parse_section(empty)
    assert result is None


# ---------------------------------------------------------------------------
# parse_chapter -- skip logic
# ---------------------------------------------------------------------------

_PREFACE_XML = '<div2 type="Preface" n="i" title="Preface to the Third Edition"/>'
_CHAPTER_XML = """<div2 type="Chapter" n="I" title="Chapter I">
  <p>This is the introductory paragraph.</p>
  <div3 type="Section" n="1" title="Opening">
    <p>First section content.</p>
  </div3>
</div2>"""


def test_parse_chapter_skips_preface():
    """div2 with type='Preface' must return None."""
    div2 = ET.fromstring(_PREFACE_XML)
    result = parse_chapter(div2)
    assert result is None


def test_parse_chapter_returns_dict():
    div2 = ET.fromstring(_CHAPTER_XML)
    result = parse_chapter(div2)
    assert result is not None
    assert result["section_type"] == "chapter"


def test_parse_chapter_has_children():
    div2 = ET.fromstring(_CHAPTER_XML)
    result = parse_chapter(div2)
    assert len(result["children"]) >= 1
