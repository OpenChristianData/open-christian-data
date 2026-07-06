"""test_ccel_npnf1.py
Unit tests for ccel_npnf1.py pure functions.

Covers key correctness invariants for NPNF1 Augustine and Chrysostom volumes:
  - _EDITORIAL_TITLE_PATTERNS: NPNF1-specific editorial skip titles
  - is_editorial_div: type= and title= paths, including content-type guard
  - _DIV_TYPE_MAP: NPNF1 new div types (Tractate, Homily, Sermon, Division)
  - clean_text: whitespace normalization
  - Batch B (Chrysostom) homily-count assertions against actual XML
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
from build.parsers.ccel_npnf1 import (  # noqa: E402
    _CONTENT_DIV_TYPES,
    _EDITORIAL_TITLE_PATTERNS,
    _DIV_TYPE_MAP,
    VOLUME_CONFIG,
    BATCH_B_VOLS,
    clean_text,
    is_editorial_div,
)


# ---------------------------------------------------------------------------
# _EDITORIAL_TITLE_PATTERNS -- positive (should match = skip as editorial)
# ---------------------------------------------------------------------------

def test_pattern_title_page():
    assert _EDITORIAL_TITLE_PATTERNS.match("Title Page.") is not None


def test_pattern_preface():
    assert _EDITORIAL_TITLE_PATTERNS.match("Preface.") is not None


def test_pattern_abstract():
    """NPNF1-specific: 'Abstract.' div in xix is editorial front-matter."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Abstract.") is not None


def test_pattern_extract_from():
    """'Extract from Augustin's Retractations.' matches 'extract from'."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Extract from Augustin's Retractations.") is not None


def test_pattern_two_letters_written():
    """'Two Letters Written by...' matches 'two letters written'."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Two Letters Written by Augustin to Valentinus.") is not None


def test_pattern_editor_preface():
    """'Editor's Preface.' must match — added after npnf108 exposed the gap."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Editor's Preface.") is not None


def test_pattern_editor_note():
    """'Editor's Note' matches via 'editor\\b' — word boundary between r and '."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Editor's Note") is not None


def test_pattern_retractations():
    assert _EDITORIAL_TITLE_PATTERNS.match("Retractations.") is not None


def test_pattern_advertisement():
    assert _EDITORIAL_TITLE_PATTERNS.match("Advertisement.") is not None


def test_pattern_argument():
    assert _EDITORIAL_TITLE_PATTERNS.match("Argument.") is not None


def test_pattern_index_of():
    assert _EDITORIAL_TITLE_PATTERNS.match("Index of Scripture References") is not None


# ---------------------------------------------------------------------------
# _EDITORIAL_TITLE_PATTERNS -- negative (should NOT match = keep as content)
# ---------------------------------------------------------------------------

def test_pattern_book_not_editorial():
    assert _EDITORIAL_TITLE_PATTERNS.match("Book I") is None


def test_pattern_psalm_not_editorial():
    assert _EDITORIAL_TITLE_PATTERNS.match("Psalm I") is None


def test_pattern_chapter_not_editorial():
    assert _EDITORIAL_TITLE_PATTERNS.match("Chapter 1") is None


def test_pattern_introduction_not_editorial():
    """'Introduction' is kept — common chapter type in Augustine."""
    assert _EDITORIAL_TITLE_PATTERNS.match("Introduction.") is None


def test_pattern_occasion_not_editorial():
    """Section title from grace-and-free-will chapters must not be filtered."""
    assert _EDITORIAL_TITLE_PATTERNS.match("The Occasion and Argument of This Work.") is None


def test_pattern_tractate_not_editorial():
    assert _EDITORIAL_TITLE_PATTERNS.match("Tractate I.") is None


def test_pattern_editorial_only_matches_start():
    """'On the Preface...' must NOT match — 'preface' is not at the start."""
    assert _EDITORIAL_TITLE_PATTERNS.match("On the Preface to the Work") is None


# ---------------------------------------------------------------------------
# is_editorial_div -- element-based tests
# ---------------------------------------------------------------------------

def test_editorial_div_abstract_title():
    """div titled 'Abstract.' is editorial."""
    elem = ET.fromstring('<div2 title="Abstract." id="xix.iv"/>')
    assert is_editorial_div(elem) is True


def test_editorial_div_editor_preface_title():
    """div titled 'Editor\'s Preface.' is editorial."""
    elem = ET.fromstring('<div2 title="Editor\'s Preface." id="ii.i"/>')
    assert is_editorial_div(elem) is True


def test_editorial_div_title_page_exact():
    elem = ET.fromstring('<div2 title="Title Page." id="vi.i"/>')
    assert is_editorial_div(elem) is True


def test_editorial_div_preface_type():
    elem = ET.fromstring('<div2 type="Preface" title="Preface"/>')
    assert is_editorial_div(elem) is True


def test_editorial_div_book_not_editorial():
    elem = ET.fromstring('<div2 type="Book" title="Book I" n="I"/>')
    assert is_editorial_div(elem) is False


def test_editorial_div_psalm_not_editorial():
    elem = ET.fromstring('<div2 title="Psalm I" id="ii.ii"/>')
    assert is_editorial_div(elem) is False


def test_editorial_div_tractate_chapter_not_editorial():
    elem = ET.fromstring('<div2 type="Tractate" title="Chapter I. 1-5." n="1"/>')
    assert is_editorial_div(elem) is False


# ---------------------------------------------------------------------------
# _DIV_TYPE_MAP -- NPNF1-specific types
# ---------------------------------------------------------------------------

def test_div_type_tractate_maps_to_chapter():
    assert _DIV_TYPE_MAP.get("Tractate") == "chapter"


def test_div_type_homily_maps_to_chapter():
    assert _DIV_TYPE_MAP.get("Homily") == "chapter"


def test_div_type_sermon_maps_to_chapter():
    assert _DIV_TYPE_MAP.get("Sermon") == "chapter"


def test_div_type_division_maps_to_book():
    assert _DIV_TYPE_MAP.get("Division") == "book"


def test_div_type_note_maps_to_none():
    assert _DIV_TYPE_MAP.get("Note") is None


def test_div_type_table_maps_to_none():
    assert _DIV_TYPE_MAP.get("Table") is None


def test_div_type_book_maps_to_book():
    assert _DIV_TYPE_MAP.get("Book") == "book"


def test_div_type_chapter_maps_to_chapter():
    assert _DIV_TYPE_MAP.get("Chapter") == "chapter"


def test_div_type_letter_maps_to_letter():
    assert _DIV_TYPE_MAP.get("Letter") == "letter"


# ---------------------------------------------------------------------------
# clean_text -- whitespace normalization
# ---------------------------------------------------------------------------

def test_clean_text_strips_whitespace():
    assert clean_text("  hello   world  ") == "hello world"


def test_clean_text_collapses_newlines():
    assert clean_text("line1\n\nline2") == "line1 line2"


def test_clean_text_empty():
    assert clean_text("") == ""


def test_clean_text_tabs_collapsed():
    assert clean_text("line1\t\tline2") == "line1 line2"


# ---------------------------------------------------------------------------
# Batch B (Chrysostom) — content-type guard and homily-count assertions
# ---------------------------------------------------------------------------

def test_content_div_types_includes_homily():
    """Homily-typed divs are protected from title-based editorial filtering."""
    assert "Homily" in _CONTENT_DIV_TYPES
    assert "Sermon" in _CONTENT_DIV_TYPES
    assert "Tractate" in _CONTENT_DIV_TYPES


def test_homily_titled_preface_is_kept():
    """NPNF1-14 Homily I on John is titled 'Preface.' -- must NOT be filtered.

    Pre-1.1.0, the editorial title regex would swallow this homily entirely.
    The _CONTENT_DIV_TYPES guard fixes that.
    """
    elem = ET.fromstring('<div2 type="Homily" title="Preface." n="I"/>')
    assert is_editorial_div(elem) is False


def test_untyped_the_argument_is_editorial():
    """NPNF1-11 Romans has an untyped div2 titled 'The Argument'."""
    elem = ET.fromstring('<div2 title="The Argument"/>')
    assert is_editorial_div(elem) is True


def test_untyped_argument_is_editorial():
    """NPNF1-12 1 Cor has an untyped div2 titled 'Argument.'."""
    elem = ET.fromstring('<div2 title="Argument."/>')
    assert is_editorial_div(elem) is True


def test_untyped_introductory_discourse_is_editorial():
    """NPNF1-13 Philippians div3 titled 'Introductory Discourse.'."""
    elem = ET.fromstring('<div3 title="Introductory Discourse."/>')
    assert is_editorial_div(elem) is True


def test_chrysostom_works_present_in_batch_b():
    """Every Batch B volume id is present in VOLUME_CONFIG with works."""
    for vol in BATCH_B_VOLS:
        assert vol in VOLUME_CONFIG, f"{vol} missing from VOLUME_CONFIG"
        assert VOLUME_CONFIG[vol]["works"], f"{vol} has no works"


def test_npnf113_split_into_per_epistle_files():
    """npnf113 must produce 10 separate Pauline-epistle output files."""
    works = VOLUME_CONFIG["npnf113"]["works"]
    slugs = [w["slug"] for w in works]
    assert len(slugs) == 10, f"Expected 10 npnf113 works, got {len(slugs)}"
    expected = {
        "chrysostom-commentary-on-galatians",
        "chrysostom-homilies-on-ephesians",
        "chrysostom-homilies-on-philippians",
        "chrysostom-homilies-on-colossians",
        "chrysostom-homilies-on-1-thessalonians",
        "chrysostom-homilies-on-2-thessalonians",
        "chrysostom-homilies-on-1-timothy",
        "chrysostom-homilies-on-2-timothy",
        "chrysostom-homilies-on-titus",
        "chrysostom-homilies-on-philemon",
    }
    assert set(slugs) == expected


# Expected top-section counts after editorial filtering. NPNF1-10 publishes
# 86 Homilies on Matthew (Greek MS tradition); the prompt's 90 figure is from
# PG numbering and does not match this edition. Counts derived from
# 2026-04-28 census, updated 2026-04-29 after strip_lead_intro filter applied
# to 10 npnf109 works; used as parser-regression guards.
_EXPECTED_TOP_SECTIONS = {
    # npnf109 (one file per content div1; translator 'Introduction.' sections
    # are filtered via strip_lead_intro flag on each affected work config)
    "chrysostom-on-the-priesthood": 6,             # Books I-VI (Intro filtered)
    "chrysostom-exhortation-to-theodore": 2,       # 2 letters (Intro filtered)
    "chrysostom-letter-to-young-widow": 1,         # Intro filtered
    "chrysostom-homilies-ignatius-and-babylas": 2, # Intro filtered
    "chrysostom-homily-on-lowliness-of-mind": 1,   # Intro filtered
    "chrysostom-instructions-to-catechumens": 2,   # no translator intro
    "chrysostom-three-homilies-on-power-of-demons": 3,  # Intro filtered
    "chrysostom-homily-on-father-if-it-be-possible": 1,
    "chrysostom-homily-on-the-paralytic": 1,
    "chrysostom-homily-to-those-not-attended-assembly": 1,
    "chrysostom-homily-against-publishing-errors": 1,
    "chrysostom-two-homilies-on-eutropius": 2,     # Intro filtered
    "chrysostom-no-one-can-be-harmed": 1,          # Intro filtered
    "chrysostom-letters-to-olympias": 6,           # Intro filtered
    "chrysostom-correspondence-with-rome": 4,      # Intro filtered
    "chrysostom-homilies-on-the-statues": 21,
    # npnf110 / npnf111 / npnf112 / npnf114 — homily-series; counts reflect
    # NPNF1 actual publication, not other catalogues
    "chrysostom-homilies-on-matthew": 86,
    "chrysostom-homilies-on-acts": 55,
    "chrysostom-homilies-on-romans": 32,
    "chrysostom-homilies-on-1-corinthians": 44,
    "chrysostom-homilies-on-2-corinthians": 30,
    "chrysostom-homilies-on-john": 88,
    "chrysostom-homilies-on-hebrews": 35,           # 34 homilies + 1 'Introduction.'
    # npnf113 per-epistle splits
    "chrysostom-commentary-on-galatians": 6,
    "chrysostom-homilies-on-ephesians": 24,
    "chrysostom-homilies-on-philippians": 15,
    "chrysostom-homilies-on-colossians": 12,
    "chrysostom-homilies-on-1-thessalonians": 11,
    "chrysostom-homilies-on-2-thessalonians": 5,
    "chrysostom-homilies-on-1-timothy": 18,
    "chrysostom-homilies-on-2-timothy": 10,
    "chrysostom-homilies-on-titus": 6,
    "chrysostom-homilies-on-philemon": 3,
}


@pytest.mark.parametrize("slug,expected", sorted(_EXPECTED_TOP_SECTIONS.items()))
def test_chrysostom_top_section_counts(slug, expected):
    """Each Chrysostom work must yield the expected number of top-level sections.

    Reads the committed JSON output. Mismatches indicate either a div boundary
    detection bug or an editorial-filter regression — investigate before
    accepting any new count.
    """
    out_path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    sections = data["data"]["sections"]
    assert len(sections) == expected, (
        f"{slug}: expected {expected} top sections, got {len(sections)}"
    )
