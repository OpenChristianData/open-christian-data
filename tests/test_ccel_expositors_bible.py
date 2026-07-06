"""Tests for ccel_expositors_bible.py — covers:
  - section_title_to_osis() (Chadwick's Mark pattern)
  - book-keying bug fix for four multi-book volumes that were mis-keying
    second/third books to the first book's OSIS code
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.ccel_expositors_bible import (  # noqa: E402
    section_title_to_osis,
    parse_volume,
    _book_from_chapter_ranges,
)

RAW_MARK = REPO_ROOT / "raw" / "ccel" / "expositors-bible" / "chadwick_mark.xml"
RAW_GAL = REPO_ROOT / "raw" / "ccel" / "expositors-bible" / "findlay_expositorgal.xml"
RAW_EZNEHES = REPO_ROOT / "raw" / "ccel" / "expositors-bible" / "adeney_expositoreznehes.xml"
RAW_SONGLAMENT = REPO_ROOT / "raw" / "ccel" / "expositors-bible" / "adeney_expositorsonglament.xml"
RAW_PASTORAL = REPO_ROOT / "raw" / "ccel" / "expositors-bible" / "plummer_expositorpastoral.xml"
RAW_JAMESJUDE = REPO_ROOT / "raw" / "ccel" / "expositors-bible" / "plummer_expositorjamesjude.xml"


# (title, default_chapter, expected_verse_range_osis)
# default_chapter is the Bible chapter from the enclosing div1 ("Chapter I" -> 1).
_SECTION_CASES = [
    # simple in-chapter range (em-dash normalized to hyphen)
    ("At the Jordan. 7–11", 1, "Mark.1.7-Mark.1.11"),
    # "Vss." prefix + comma list -> bounding range
    ("The Temptation. Vss. 12,13", 1, "Mark.1.12-Mark.1.13"),
    ("Teaching with Authority. Vss. 21, 22.", 1, "Mark.1.21-Mark.1.22"),
    # single verse, "Vs." prefix, trailing period
    ("Miracles. Vs. 23.", 1, "Mark.1.23"),
    ("The Son of Man. Vs. 10", 2, "Mark.2.10"),
    # "Vss" no period
    ("The Sick of the Palsy. Vss 1–12.", 2, "Mark.2.1-Mark.2.12"),
    # bare range, no prefix
    ("The Call and Feast of Levi. 13–17.", 2, "Mark.2.13-Mark.2.17"),
    # bare single trailing verse
    ("The Apostle Judas. 19", 3, "Mark.3.19"),
    # explicit chapter:verse cross-chapter range overrides div1 chapter
    ("Unwashen Hands. 6:53–7:13", 6, "Mark.6.53-Mark.7.13"),
    ("The Rebuke of Peter. 8:32–9:1", 8, "Mark.8.32-Mark.9.1"),
    # multiple disjoint specs -> bounding span (first start .. last end) in chapter
    ("The Parables. 1,2 10–13", 4, "Mark.4.1-Mark.4.13"),
    ("The Sower. 3–9, 14–20", 4, "Mark.4.3-Mark.4.20"),
    # multiple explicit ch:verse points -> bounding span across chapters
    ("Four Miracles. 4:39 5:15 5:31 5:41", 4, "Mark.4.39-Mark.5.41"),
    # no verse spec -> None (caller inherits previous / skips)
    ("The Beginning of the Gospel.", 1, None),
    ("The Sower cont.", 4, None),
]


@pytest.mark.parametrize("title,chapter,expected", _SECTION_CASES)
def test_section_title_to_osis(title, chapter, expected):
    result = section_title_to_osis(title, chapter, "Mark")
    if expected is None:
        assert result is None, f"{title!r}: expected None, got {result}"
    else:
        assert result is not None, f"{title!r}: expected {expected}, got None"
        _, _, osis = result
        assert osis == expected, f"{title!r}: expected {expected}, got {osis}"


def test_section_title_chapter_from_explicit_ref():
    # When the title carries an explicit chapter:verse, that chapter wins over default.
    chapter, _, osis = section_title_to_osis("Unwashen Hands. 6:53–7:13", 6, "Mark")
    assert chapter == 6
    assert osis == "Mark.6.53-Mark.7.13"


@pytest.mark.skipif(not RAW_MARK.exists(), reason="raw Chadwick Mark XML not present")
def test_mark_volume_parses_many_entries():
    entries, _ = parse_volume("chadwick/mark")
    # Mark has 16 chapters of multi-section expository commentary; expect dozens
    # of verse-keyed entries, all in the book of Mark.
    assert len(entries) >= 60, f"expected >=60 Mark entries, got {len(entries)}"
    for e in entries:
        assert e["verse_range_osis"].startswith("Mark."), e["verse_range_osis"]


@pytest.mark.skipif(not RAW_GAL.exists(), reason="raw Findlay Galatians XML not present")
def test_galatians_div1_title_entries():
    # Findlay's Galatians organises the epistle into 5 major expository divisions,
    # each div1 stating its passage range in the title ("... Chapter i. 1-10.").
    entries, _ = parse_volume("findlay/expositorgal")
    assert len(entries) == 5, f"expected 5 Galatians divisions, got {len(entries)}"
    for e in entries:
        assert e["verse_range_osis"].startswith("Gal."), e["verse_range_osis"]
    assert entries[0]["verse_range_osis"] == "Gal.1.1-Gal.1.10"
    # cross-chapter division range preserved
    assert any(e["verse_range_osis"] == "Gal.1.11-Gal.2.21" for e in entries)


_EXPECTED_TOP_ENTRIES = {
    # Exact count locked after the first clean full run (parser-section-counts rule):
    # a delta means a section-extraction change added or dropped commentary entries.
    "mark": 85,
    "gal": 5,
    # Counts locked after book-keying bug fix (2026-06-17):
    "ezra": 14,
    "neh": 16,
    "esth": 5,
    "song": 2,
    "lam": 19,
    "1tim": 16,
    "2tim": 11,
    "titus": 9,
    "jas": 26,
    "jude": 8,
}


@pytest.mark.parametrize("slug,expected", sorted(_EXPECTED_TOP_ENTRIES.items()))
def test_output_entry_count(slug, expected):
    path = REPO_ROOT / "data" / "commentaries" / "expositors-bible" / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["data"]) == expected


# ---------------------------------------------------------------------------
# _book_from_chapter_ranges unit tests
# ---------------------------------------------------------------------------

def test_book_from_chapter_ranges_ezra():
    ranges = [("Ezra", 1, 14), ("Neh", 15, 30), ("Esth", 31, 35)]
    assert _book_from_chapter_ranges(1, ranges) == "Ezra"
    assert _book_from_chapter_ranges(7, ranges) == "Ezra"
    assert _book_from_chapter_ranges(14, ranges) == "Ezra"


def test_book_from_chapter_ranges_neh():
    ranges = [("Ezra", 1, 14), ("Neh", 15, 30), ("Esth", 31, 35)]
    assert _book_from_chapter_ranges(15, ranges) == "Neh"
    assert _book_from_chapter_ranges(22, ranges) == "Neh"
    assert _book_from_chapter_ranges(30, ranges) == "Neh"


def test_book_from_chapter_ranges_esth():
    ranges = [("Ezra", 1, 14), ("Neh", 15, 30), ("Esth", 31, 35)]
    assert _book_from_chapter_ranges(31, ranges) == "Esth"
    assert _book_from_chapter_ranges(35, ranges) == "Esth"


def test_book_from_chapter_ranges_out_of_bounds():
    ranges = [("Ezra", 1, 14), ("Neh", 15, 30), ("Esth", 31, 35)]
    assert _book_from_chapter_ranges(0, ranges) is None
    assert _book_from_chapter_ranges(36, ranges) is None


# ---------------------------------------------------------------------------
# adeney/expositoreznehes — all three books correctly keyed
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RAW_EZNEHES.exists(), reason="raw adeney_expositoreznehes.xml not present")
def test_expositoreznehes_produces_all_three_books():
    entries, _ = parse_volume("adeney/expositoreznehes")
    books = {e["book_osis"] for e in entries}
    assert "Ezra" in books, "expected Ezra entries"
    assert "Neh" in books, "expected Neh entries"
    assert "Esth" in books, "expected Esth entries"


@pytest.mark.skipif(not RAW_EZNEHES.exists(), reason="raw adeney_expositoreznehes.xml not present")
def test_expositoreznehes_ezra_entries_chapters_1_to_14():
    entries, _ = parse_volume("adeney/expositoreznehes")
    ezra = [e for e in entries if e["book_osis"] == "Ezra"]
    assert len(ezra) == 14
    assert all(1 <= e["chapter"] <= 14 for e in ezra)


@pytest.mark.skipif(not RAW_EZNEHES.exists(), reason="raw adeney_expositoreznehes.xml not present")
def test_expositoreznehes_neh_entries_chapters_15_to_30():
    entries, _ = parse_volume("adeney/expositoreznehes")
    neh = [e for e in entries if e["book_osis"] == "Neh"]
    assert len(neh) == 16
    assert all(15 <= e["chapter"] <= 30 for e in neh)


@pytest.mark.skipif(not RAW_EZNEHES.exists(), reason="raw adeney_expositoreznehes.xml not present")
def test_expositoreznehes_esth_entries_chapters_31_to_35():
    entries, _ = parse_volume("adeney/expositoreznehes")
    esth = [e for e in entries if e["book_osis"] == "Esth"]
    assert len(esth) == 5
    assert all(31 <= e["chapter"] <= 35 for e in esth)


# ---------------------------------------------------------------------------
# adeney/expositorsonglament — Song and Lamentations correctly split
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RAW_SONGLAMENT.exists(), reason="raw adeney_expositorsonglament.xml not present")
def test_expositorsonglament_produces_song_and_lam():
    entries, _ = parse_volume("adeney/expositorsonglament")
    books = {e["book_osis"] for e in entries}
    assert "Song" in books, "expected Song of Solomon entries"
    assert "Lam" in books, "expected Lamentations entries"


@pytest.mark.skipif(not RAW_SONGLAMENT.exists(), reason="raw adeney_expositorsonglament.xml not present")
def test_expositorsonglament_entry_counts():
    entries, _ = parse_volume("adeney/expositorsonglament")
    song = [e for e in entries if e["book_osis"] == "Song"]
    lam = [e for e in entries if e["book_osis"] == "Lam"]
    assert len(song) == 2
    assert len(lam) == 19


# ---------------------------------------------------------------------------
# plummer/expositorpastoral — 1Tim / Titus / 2Tim correctly split
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RAW_PASTORAL.exists(), reason="raw plummer_expositorpastoral.xml not present")
def test_expositorpastoral_produces_all_three_books():
    entries, _ = parse_volume("plummer/expositorpastoral")
    books = {e["book_osis"] for e in entries}
    assert "1Tim" in books, "expected 1 Timothy entries"
    assert "2Tim" in books, "expected 2 Timothy entries"
    assert "Titus" in books, "expected Titus entries"


@pytest.mark.skipif(not RAW_PASTORAL.exists(), reason="raw plummer_expositorpastoral.xml not present")
def test_expositorpastoral_entry_counts():
    entries, _ = parse_volume("plummer/expositorpastoral")
    assert len([e for e in entries if e["book_osis"] == "1Tim"]) == 16
    assert len([e for e in entries if e["book_osis"] == "2Tim"]) == 11
    assert len([e for e in entries if e["book_osis"] == "Titus"]) == 9


# ---------------------------------------------------------------------------
# plummer/expositorjamesjude — James and Jude correctly split
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not RAW_JAMESJUDE.exists(), reason="raw plummer_expositorjamesjude.xml not present")
def test_expositorjamesjude_produces_jas_and_jude():
    entries, _ = parse_volume("plummer/expositorjamesjude")
    books = {e["book_osis"] for e in entries}
    assert "Jas" in books, "expected James entries"
    assert "Jude" in books, "expected Jude entries"


@pytest.mark.skipif(not RAW_JAMESJUDE.exists(), reason="raw plummer_expositorjamesjude.xml not present")
def test_expositorjamesjude_entry_counts():
    entries, _ = parse_volume("plummer/expositorjamesjude")
    assert len([e for e in entries if e["book_osis"] == "Jas"]) == 26
    assert len([e for e in entries if e["book_osis"] == "Jude"]) == 8
