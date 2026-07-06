"""tests/test_gutenberg_commentary.py
Tests for build/parsers/gutenberg_commentary.py.

Covers:
- Unit tests for heading regex and parsing utilities
- Integration tests against the real PG #50857 source file
"""

import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.gutenberg_commentary import (  # noqa: E402
    LIGHTFOOT_COL_PHILEMON_SECTIONS,
    build_verse_range_osis,
    normalize_verse_range,
    parse_col_heading,
    parse_pg_verse_commentary,
    parse_phm_heading,
    roman_to_int,
)

RAW_FILE = (
    REPO_ROOT
    / "raw"
    / "gutenberg"
    / "commentary"
    / "lightfoot-colossians-philemon"
    / "pg50857.txt"
)

# ---------------------------------------------------------------------------
# Unit: roman_to_int
# ---------------------------------------------------------------------------


def test_roman_to_int_I():
    assert roman_to_int("I") == 1


def test_roman_to_int_II():
    assert roman_to_int("II") == 2


def test_roman_to_int_III():
    assert roman_to_int("III") == 3


def test_roman_to_int_IV():
    assert roman_to_int("IV") == 4


# ---------------------------------------------------------------------------
# Unit: normalize_verse_range
# ---------------------------------------------------------------------------


def test_normalize_single_verse():
    assert normalize_verse_range("6") == "6"


def test_normalize_comma_range():
    # "1, 2" -> "1-2"
    assert normalize_verse_range("1, 2") == "1-2"


def test_normalize_en_dash_range():
    # "19–22" (en-dash) -> "19-22"
    assert normalize_verse_range("19–22") == "19-22"


def test_normalize_hyphen_range():
    assert normalize_verse_range("1-3") == "1-3"


def test_normalize_comma_multi():
    # "1, 2, 3" -> "1-3" (first to last)
    assert normalize_verse_range("1, 2, 3") == "1-3"


# ---------------------------------------------------------------------------
# Unit: build_verse_range_osis
# ---------------------------------------------------------------------------


def test_osis_single_verse():
    assert build_verse_range_osis("Col", 1, "6") == "Col.1.6"


def test_osis_range_col():
    assert build_verse_range_osis("Col", 1, "1-2") == "Col.1.1-Col.1.2"


def test_osis_range_phm():
    assert build_verse_range_osis("Phlm", 1, "1-3") == "Phlm.1.1-Phlm.1.3"


def test_osis_chapter_3():
    assert build_verse_range_osis("Col", 3, "19-22") == "Col.3.19-Col.3.22"


# ---------------------------------------------------------------------------
# Unit: parse_col_heading
# ---------------------------------------------------------------------------

COL_HEAD_RE = re.compile(r"^([IVX]+)\. ([\d, –—\-]+)\]$")
PHM_HEAD_RE = re.compile(r"^([\d, –—\-]+)\]$")


def test_col_heading_re_single():
    assert COL_HEAD_RE.match("I. 3]") is not None


def test_col_heading_re_comma():
    assert COL_HEAD_RE.match("I. 1, 2]") is not None


def test_col_heading_re_dash():
    assert COL_HEAD_RE.match("III. 19–22]") is not None


def test_col_heading_re_chapter4():
    assert COL_HEAD_RE.match("IV. 18]") is not None


def test_phm_heading_re_single():
    assert PHM_HEAD_RE.match("6]") is not None


def test_phm_heading_re_dash():
    assert PHM_HEAD_RE.match("1–3]") is not None


def test_phm_heading_re_comma():
    assert PHM_HEAD_RE.match("4, 5]") is not None


def test_parse_col_heading_single():
    chapter, verse_range, osis = parse_col_heading("I. 3]", "Col")
    assert chapter == 1
    assert verse_range == "3"
    assert osis == "Col.1.3"


def test_parse_col_heading_comma_range():
    chapter, verse_range, osis = parse_col_heading("I. 1, 2]", "Col")
    assert chapter == 1
    assert verse_range == "1-2"
    assert osis == "Col.1.1-Col.1.2"


def test_parse_col_heading_dash_range():
    chapter, verse_range, osis = parse_col_heading("III. 19–22]", "Col")
    assert chapter == 3
    assert verse_range == "19-22"
    assert osis == "Col.3.19-Col.3.22"


def test_parse_col_heading_ch4():
    chapter, verse_range, osis = parse_col_heading("IV. 18]", "Col")
    assert chapter == 4
    assert verse_range == "18"
    assert osis == "Col.4.18"


# ---------------------------------------------------------------------------
# Unit: parse_phm_heading
# ---------------------------------------------------------------------------


def test_parse_phm_heading_single():
    chapter, verse_range, osis = parse_phm_heading("6]", "Phlm")
    assert chapter == 1
    assert verse_range == "6"
    assert osis == "Phlm.1.6"


def test_parse_phm_heading_dash_range():
    chapter, verse_range, osis = parse_phm_heading("1–3]", "Phlm")
    assert chapter == 1
    assert verse_range == "1-3"
    assert osis == "Phlm.1.1-Phlm.1.3"


def test_parse_phm_heading_comma_range():
    chapter, verse_range, osis = parse_phm_heading("4, 5]", "Phlm")
    assert chapter == 1
    assert verse_range == "4-5"
    assert osis == "Phlm.1.4-Phlm.1.5"


# ---------------------------------------------------------------------------
# Integration: full parse against real source file
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def all_entries():
    if not RAW_FILE.exists():
        pytest.skip("Raw source file not downloaded")
    return parse_pg_verse_commentary(RAW_FILE, LIGHTFOOT_COL_PHILEMON_SECTIONS)


def test_extracts_colossians_records(all_entries):
    col = [e for e in all_entries if e["book_osis"] == "Col" and e["chapter"] > 0]
    assert len(col) >= 5, f"Expected at least 5 Colossians records, got {len(col)}"


def test_extracts_philemon_records(all_entries):
    phm = [e for e in all_entries if e["book_osis"] == "Phlm" and e["chapter"] > 0]
    assert len(phm) >= 5, f"Expected at least 5 Philemon records, got {len(phm)}"


def test_col_intro_not_dropped(all_entries):
    intros = [e for e in all_entries if e["book_osis"] == "Col" and e["chapter"] == 0]
    assert len(intros) >= 1, "Colossians introduction should be captured"
    assert intros[0]["verse_range"] == "intro"
    assert len(intros[0]["commentary_text"]) > 100


def test_phm_intro_not_dropped(all_entries):
    intros = [e for e in all_entries if e["book_osis"] == "Phlm" and e["chapter"] == 0]
    assert len(intros) >= 1, "Philemon introduction should be captured"
    assert intros[0]["verse_range"] == "intro"
    assert intros[0]["verse_range_osis"] is None


def test_greek_text_preserved(all_entries):
    greek_entries = [
        e
        for e in all_entries
        if any(0x0370 <= ord(c) <= 0x03FF for c in e["commentary_text"])
    ]
    assert len(greek_entries) > 0, "Expected entries with Greek text in commentary body"


def test_footnote_markers_preserved(all_entries):
    # PG transcription uses ^{N} for superscripts and [NNN] for footnote refs
    marked = [
        e
        for e in all_entries
        if "^{" in e["commentary_text"] or "[" in e["commentary_text"]
    ]
    assert len(marked) > 0, "Expected entries with footnote/superscript markers"


def test_entry_ids_unique(all_entries):
    ids = [e["entry_id"] for e in all_entries]
    assert len(ids) == len(set(ids)), "Duplicate entry IDs found"


def test_col_osis_references_present(all_entries):
    col_verse = [e for e in all_entries if e["book_osis"] == "Col" and e["chapter"] > 0]
    for e in col_verse[:5]:
        assert e["verse_range_osis"] is not None
        assert e["verse_range_osis"].startswith("Col.")


def test_phm_osis_references_present(all_entries):
    phm_verse = [e for e in all_entries if e["book_osis"] == "Phlm" and e["chapter"] > 0]
    for e in phm_verse[:5]:
        assert e["verse_range_osis"] is not None
        assert e["verse_range_osis"].startswith("Phlm.")


def test_required_fields_present(all_entries):
    required = [
        "entry_id", "book", "book_osis", "book_number", "chapter",
        "verse_range", "verse_range_osis", "verse_text", "commentary_text",
        "summary", "summary_review_status", "cross_references", "word_count",
    ]
    for e in all_entries[:10]:
        for field in required:
            assert field in e, f"Missing field '{field}' in {e.get('entry_id')}"


def test_verse_range_schema_pattern(all_entries):
    # verse_range must match schema pattern: ^\d+(-\d+)?|intro)$
    pattern = re.compile(r"^(\d+(-\d+)?|intro)$")
    for e in all_entries:
        assert pattern.match(e["verse_range"]), (
            f"verse_range {e['verse_range']!r} fails schema pattern "
            f"in {e['entry_id']}"
        )


def test_word_counts_positive(all_entries):
    verse_entries = [e for e in all_entries if e["chapter"] > 0]
    for e in verse_entries[:10]:
        assert e["word_count"] > 0, f"Zero word_count in {e['entry_id']}"


def test_col_chapter_coverage(all_entries):
    col_verse = [e for e in all_entries if e["book_osis"] == "Col" and e["chapter"] > 0]
    chapters = {e["chapter"] for e in col_verse}
    assert chapters == {1, 2, 3, 4}, f"Expected chapters 1-4, got {sorted(chapters)}"


def test_col_first_verse(all_entries):
    # Col 1:1 should be the first verse entry
    first = next(
        (e for e in all_entries if e["book_osis"] == "Col" and e["chapter"] == 1
         and e["verse_range"].startswith("1")),
        None,
    )
    assert first is not None, "Col 1:1 entry not found"
    assert "Col.1.1" in first["verse_range_osis"]


def test_phm_last_verse(all_entries):
    # Philemon last entry should cover verse 25 (23-25 block)
    phm = [e for e in all_entries if e["book_osis"] == "Phlm" and e["chapter"] > 0]
    ranges = [e["verse_range"] for e in phm]
    assert any(r.endswith("25") for r in ranges), (
        f"No Philemon entry ending at verse 25; ranges: {ranges}"
    )
