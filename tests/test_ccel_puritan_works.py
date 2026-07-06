"""test_ccel_puritan_works.py
Unit tests for ccel_puritan_works.py pure functions.

Covers correctness invariants from the T5-4 implementation, including
the bugs discovered during post-parse spot-checking:
  - extract_heading: Law pattern (decorative h2s before real h3)
  - extract_heading: label-only h3 (CHAPTER I) + title= desc lookup
  - extract_heading: Watson numbered headings ('1. Man's Chief End')
  - extract_heading: Ryle roman-numeral headings ('I. Sin' via title=)
  - extract_heading: title= fallback when no h* present
  - is_editorial_div: Title Page, Brief Memoir, To The Reader patterns
  - is_editorial_div: content divs correctly pass through
  - get_scriptrefs: 'Bible:' and 'Bible.kjv:' osis prefix variants
  - build_meta: work-level completeness overrides author-level

Added 2026-04-23 as T5-4 closeout (TDD retro).
"""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.pytest_skips import skip_if_missing_data  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402
from build.parsers.ccel_puritan_works import (  # noqa: E402
    AUTHOR_CONFIG,
    WORK_CONFIG,
    extract_heading,
    is_editorial_div,
    get_scriptrefs,
    build_meta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_div(xml: str):
    return ET.fromstring(xml)


# ---------------------------------------------------------------------------
# extract_heading -- Law pattern (decorative h2s before real h3)
# ---------------------------------------------------------------------------

def test_extract_heading_law_ch1_decorative_h2s():
    """Law ch.1: two decorative book-title h2s before the actual chapter h3.
    Parser must skip unmatched h2s and find the HEADING_RE match in h3."""
    div = make_div(
        '<div1 title="Chapter I. Concerning the nature and extent of Christian devotion">'
        '<h2>A SERIOUS CALL TO</h2>'
        '<h2>A DEVOUT AND HOLY LIFE</h2>'
        '<h3>CHAPTER I</h3>'
        '<p>Content.</p>'
        '</div1>'
    )
    label, title = extract_heading(div)
    assert label == "CHAPTER I"
    assert "Concerning the nature" in title


def test_extract_heading_law_ch2_no_decorative():
    """Law ch.2 onwards: only h3 present, no decorative headers."""
    div = make_div(
        '<div1 title="Chapter II. An inquiry into the reason">'
        '<h3>CHAPTER II</h3>'
        '<p>Content.</p>'
        '</div1>'
    )
    label, title = extract_heading(div)
    assert label == "CHAPTER II"
    assert "inquiry" in title


def test_extract_heading_label_only_h3_uses_title_attr():
    """When h3 matches HEADING_RE but produces empty title, title= supplies the description."""
    div = make_div(
        '<div1 title="Part III. Showing that these affections">'
        '<h3>Part III.</h3>'
        '<p>Content.</p>'
        '</div1>'
    )
    label, title = extract_heading(div)
    assert "Part III" in label
    assert "Showing that these affections" in title


# ---------------------------------------------------------------------------
# extract_heading -- Watson numbered headings (no HEADING_RE match)
# ---------------------------------------------------------------------------

def test_extract_heading_watson_numbered_uses_title_attr():
    """Watson '1. Man\'s Chief End': no HEADING_RE match; title= attr used."""
    div = make_div(
        "<div2 title=\"1. Man's Chief End\">"
        "<h3>1. Man's Chief End</h3>"
        "<p>Content.</p>"
        "</div2>"
    )
    label, title = extract_heading(div)
    assert label == ""
    assert "Man's Chief End" in title


def test_extract_heading_no_title_attr_uses_h_text():
    """When no title= and h* doesn't match HEADING_RE, return raw h* text."""
    div = make_div(
        "<div2>"
        "<h3>A Brief Discourse</h3>"
        "<p>Content.</p>"
        "</div2>"
    )
    label, title = extract_heading(div)
    assert label == ""
    assert title == "A Brief Discourse"


# ---------------------------------------------------------------------------
# extract_heading -- Ryle roman numeral via title=
# ---------------------------------------------------------------------------

def test_extract_heading_ryle_roman_numeral_prefers_title_attr():
    """Ryle: h2 is 'I SIN' (br-collapsed), title= is 'I. Sin'; title= wins."""
    div = make_div(
        '<div2 title="I. Sin">'
        '<h2>I SIN</h2>'
        '<p>Content.</p>'
        '</div2>'
    )
    label, title = extract_heading(div)
    assert label == ""
    assert title == "I. Sin"


# ---------------------------------------------------------------------------
# extract_heading -- no h* present, title= fallback
# ---------------------------------------------------------------------------

def test_extract_heading_title_attr_heading_re_match():
    """No h* child; title= matches HEADING_RE."""
    div = make_div(
        '<div1 title="Chapter IV. Of the great danger">'
        '<p>Content.</p>'
        '</div1>'
    )
    label, title = extract_heading(div)
    assert "Chapter IV" in label
    assert "great danger" in title


def test_extract_heading_title_attr_no_match():
    """No h* child; title= present but no HEADING_RE match."""
    div = make_div(
        '<div1 title="A Note to the Reader">'
        '<p>Content.</p>'
        '</div1>'
    )
    label, title = extract_heading(div)
    assert label == ""
    assert title == "A Note to the Reader"


def test_extract_heading_empty_div():
    """No h*, no title= -- returns ('', '')."""
    div = make_div("<div1><p>Content.</p></div1>")
    label, title = extract_heading(div)
    assert label == ""
    assert title == ""


# ---------------------------------------------------------------------------
# is_editorial_div -- editorial patterns must return True
# ---------------------------------------------------------------------------

def test_editorial_title_page_attr():
    div = make_div('<div1 title="Title Page"><p>London, 1729.</p></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_brief_memoir_heading():
    div = make_div('<div1><h2>Brief Memoir Of Thomas Watson</h2><p>He was born...</p></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_to_the_reader_heading():
    div = make_div('<div1><h2>To The Reader</h2><p>Content.</p></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_advertisement_to_the_reader():
    div = make_div('<div1><h2>An Advertisement To The Reader</h2><p>Content.</p></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_flavel_method_epistle_front_matter():
    div = make_div('<div1><h1>The Epistle To The Reader</h1><p>Content.</p></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_flavel_method_dedicatory_front_matter():
    div = make_div('<div1><h1>The Epistle Dedicatory</h1><p>Content.</p></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_type_titlepage():
    div = make_div('<div1 type="Titlepage"><p>Title info.</p></div1>')
    assert is_editorial_div(div, is_top_level=True)


def test_editorial_type_back():
    div = make_div('<div1 type="Back"><p>Back matter.</p></div1>')
    assert is_editorial_div(div, is_top_level=False)


# ---------------------------------------------------------------------------
# is_editorial_div -- content divs must return False
# ---------------------------------------------------------------------------

def test_not_editorial_chapter_heading():
    div = make_div('<div1><h3>CHAPTER I</h3><p>Devotion signifies a life given to God.</p></div1>')
    assert not is_editorial_div(div, is_top_level=False)


def test_not_editorial_sermon_type():
    div = make_div('<div1 type="Sermon"><h2>Sermon I</h2><p>Content.</p></div1>')
    assert not is_editorial_div(div, is_top_level=False)


def test_not_editorial_part_heading():
    div = make_div(
        '<div1 title="Part I. Concerning the nature of the affections"><p>Text.</p></div1>'
    )
    assert not is_editorial_div(div, is_top_level=False)


# ---------------------------------------------------------------------------
# get_scriptrefs -- osis prefix variants
# ---------------------------------------------------------------------------

def test_scriptrefs_bible_prefix():
    div = make_div(
        '<div1><p>'
        '<scripRef osisRef="Bible:Rom.8.28">Romans 8:28</scripRef>'
        '</p></div1>'
    )
    refs = get_scriptrefs(div)
    assert len(refs) == 1
    assert refs[0]["raw"] == "Romans 8:28"
    assert "Rom.8.28" in refs[0]["osis"]


def test_scriptrefs_bible_kjv_prefix():
    div = make_div(
        '<div1><p>'
        '<scripRef osisRef="Bible.kjv:John.3.16">John 3:16</scripRef>'
        '</p></div1>'
    )
    refs = get_scriptrefs(div)
    assert len(refs) == 1
    assert "John.3.16" in refs[0]["osis"]


def test_scriptrefs_none_present():
    div = make_div('<div1><p>No scripture here.</p></div1>')
    assert get_scriptrefs(div) == []


# ---------------------------------------------------------------------------
# build_meta -- work-level completeness overrides author-level
# ---------------------------------------------------------------------------

def test_build_meta_completeness_work_override():
    """baxter-saints-rest has completeness='abridged' at work level;
    build_meta() must use that instead of author_cfg's 'full'."""
    saints_rest = next(w for w in WORK_CONFIG if w["slug"] == "baxter-saints-rest")
    assert saints_rest.get("completeness") == "abridged"
    fake_result = {
        "_source_hash": "sha256:abc123",
        "_download_date": "2026-04-23",
        "_warnings": [],
    }
    meta = build_meta(saints_rest, fake_result)
    assert meta["completeness"] == "abridged"


def test_build_meta_completeness_default_from_author():
    """Other Baxter works inherit completeness from AUTHOR_CONFIG."""
    pastor = next(w for w in WORK_CONFIG if w["slug"] == "baxter-reformed-pastor")
    assert pastor.get("completeness") is None
    fake_result = {
        "_source_hash": "sha256:abc123",
        "_download_date": "2026-04-23",
        "_warnings": [],
    }
    meta = build_meta(pastor, fake_result)
    assert meta["completeness"] == AUTHOR_CONFIG["baxter"]["completeness"]


# ---------------------------------------------------------------------------
# edwards-history-of-redemption -- output file invariants
# ---------------------------------------------------------------------------

_HIST_SLUG = "edwards-history-of-redemption"
_HIST_PATH = REPO_ROOT / "data" / "structured-text" / f"{_HIST_SLUG}.json"

_EXPECTED_TOP_SECTIONS = {
    _HIST_SLUG: 1,                       # div1 id='xii' extracted as single container
    "edwards-distinguishing-marks": 1,   # div1 id='vii' extracted as single container
    "flavel-method-of-grace": 35,        # 35 sermon div1s after front/back matter filtering
    "rutherford-letters": 1,             # "Letters" container div with 71 letter children
    "boston-crook-in-the-lot": 3,        # Part 1, Part 2, Part 3 (flat paragraphs, no div2)
    "murray-absolute-surrender": 9,      # 9 address chapters after editorial filtering
    "edwards-life-of-brainerd": 1,       # div1 id='ix' extracted as single container, 21 children
    "butler-analogy-of-religion": 3,     # Prefatory Material + Introduction + Analogy (main)
}


@pytest.mark.parametrize("slug,expected", sorted(_EXPECTED_TOP_SECTIONS.items()))
def test_top_section_counts(slug, expected):
    out_path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["data"]["sections"]) == expected, (
        f"{slug}: expected {expected} top sections, got {len(data['data']['sections'])}"
    )


def _sum_word_count(sections: list) -> int:
    total = 0
    for s in sections:
        total += s.get("word_count", 0)
        total += _sum_word_count(s.get("children", []))
    return total


def _collect_titles(sections: list) -> list:
    titles = []
    for s in sections:
        titles.append(s.get("title", ""))
        titles.extend(_collect_titles(s.get("children", [])))
    return titles


@pytest.mark.raw_required(_HIST_PATH)
def test_history_of_redemption_output_exists():
    pass


@pytest.mark.raw_required(_HIST_PATH)
def test_history_of_redemption_section_count():
    """Work extracts as single div1 container; must have >= 5 children inside."""
    with open(_HIST_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    container = data["data"]["sections"][0]
    assert len(container.get("children", [])) >= 5, (
        f"Expected >= 5 children in container, got {len(container.get('children', []))}"
    )


@pytest.mark.raw_required(_HIST_PATH)
def test_history_of_redemption_tradition_valid():
    valid_traditions = get_enum("structured_text", "meta", "tradition")
    with open(_HIST_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for t in data["meta"]["tradition"]:
        assert t in valid_traditions, f"Invalid tradition: {t!r}"


@pytest.mark.raw_required(_HIST_PATH)
def test_history_of_redemption_word_count():
    with open(_HIST_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert _sum_word_count(data["data"]["sections"]) > 0


@pytest.mark.raw_required(_HIST_PATH)
def test_history_of_redemption_redemptive_history_headings():
    """Three-period redemptive-historical structure should appear in section titles."""
    keywords = {"Fall", "Incarnation", "Resurrection", "Redemption", "Christ"}
    with open(_HIST_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    all_titles = _collect_titles(data["data"]["sections"])
    assert any(
        any(kw in title for kw in keywords) for title in all_titles
    ), f"No redemptive-history keyword found in titles: {all_titles[:10]}"


# ---------------------------------------------------------------------------
# edwards-distinguishing-marks -- output file invariants
# ---------------------------------------------------------------------------

_DM_SLUG = "edwards-distinguishing-marks"
_DM_PATH = REPO_ROOT / "data" / "structured-text" / f"{_DM_SLUG}.json"


@pytest.mark.raw_required(_DM_PATH)
def test_distinguishing_marks_output_exists():
    pass


@pytest.mark.raw_required(_DM_PATH)
def test_distinguishing_marks_section_count():
    """Extracted div1 container must have >= 2 children (Cooper's preface + main text)."""
    with open(_DM_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    container = data["data"]["sections"][0]
    assert len(container.get("children", [])) >= 2, (
        f"Expected >= 2 children in container, got {len(container.get('children', []))}"
    )


@pytest.mark.raw_required(_DM_PATH)
def test_distinguishing_marks_tradition_valid():
    valid_traditions = get_enum("structured_text", "meta", "tradition")
    with open(_DM_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for t in data["meta"]["tradition"]:
        assert t in valid_traditions, f"Invalid tradition: {t!r}"


@pytest.mark.raw_required(_DM_PATH)
def test_distinguishing_marks_word_count():
    with open(_DM_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert _sum_word_count(data["data"]["sections"]) > 0
