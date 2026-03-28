# tests/test_citation_parser.py
"""Tests for build.lib.citation_parser."""
import sys
from pathlib import Path

import pytest

# Allow imports from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.lib.citation_parser import lookup_book
from build.lib.citation_parser import parse_single_reference
from build.lib.citation_parser import parse_citation_string


def test_simple_book():
    assert lookup_book("Gen.") == "Gen"
    assert lookup_book("Gen") == "Gen"


def test_numbered_book():
    assert lookup_book("1 Cor.") == "1Cor"
    assert lookup_book("2 Tim.") == "2Tim"
    assert lookup_book("1 John") == "1John"


def test_abbreviated_book():
    assert lookup_book("Ps.") == "Ps"
    assert lookup_book("Matt.") == "Matt"
    assert lookup_book("Rev.") == "Rev"
    assert lookup_book("Jas.") == "Jas"
    assert lookup_book("Ecc.") == "Eccl"
    assert lookup_book("Ex.") == "Exod"
    assert lookup_book("Deut.") == "Deut"


def test_full_name():
    assert lookup_book("Romans") == "Rom"
    assert lookup_book("Hebrews") == "Heb"
    assert lookup_book("Psalms") == "Ps"


def test_unknown_returns_none():
    assert lookup_book("Notabook") is None


# --- parse_single_reference tests ---

def test_simple_reference():
    result = parse_single_reference("Rom. 11:36")
    assert result == {"raw": "Rom. 11:36", "osis": ["Rom.11.36"]}


def test_verse_range():
    result = parse_single_reference("Ps. 73:25-28")
    assert result == {"raw": "Ps. 73:25-28", "osis": ["Ps.73.25-Ps.73.28"]}


def test_comma_separated_verses():
    result = parse_single_reference("Eph. 1:4,11")
    assert result == {"raw": "Eph. 1:4,11", "osis": ["Eph.1.4", "Eph.1.11"]}


def test_chapter_only():
    result = parse_single_reference("Gen. 1")
    assert result == {"raw": "Gen. 1", "osis": ["Gen.1"]}


def test_numbered_book_reference():
    result = parse_single_reference("1 Cor. 10:31")
    assert result == {"raw": "1 Cor. 10:31", "osis": ["1Cor.10.31"]}


def test_verse_list_with_range():
    # "Ps. 51:1-2, 7, 9" -- range + individual verses in same chapter
    result = parse_single_reference("Ps. 51:1-2, 7, 9")
    assert result == {"raw": "Ps. 51:1-2, 7, 9", "osis": ["Ps.51.1-Ps.51.2", "Ps.51.7", "Ps.51.9"]}


def test_acts_with_comma_verses():
    result = parse_single_reference("Acts 2:42, 46-47")
    assert result == {"raw": "Acts 2:42, 46-47", "osis": ["Acts.2.42", "Acts.2.46-Acts.2.47"]}


# --- parse_citation_string tests ---

def test_semicolon_separated():
    result = parse_citation_string("1 Cor. 10:31; Rom. 11:36; Ps. 73:25-28.")
    assert len(result) == 3
    assert result[0] == {"raw": "1 Cor. 10:31", "osis": ["1Cor.10.31"]}
    assert result[2] == {"raw": "Ps. 73:25-28", "osis": ["Ps.73.25-Ps.73.28"]}


def test_with_conjunction():
    # "with" should split into two separate references
    result = parse_citation_string("Gen. 17:10 with Col. 2:11-12; 1 Cor. 7:14.")
    assert len(result) == 3
    assert result[0]["osis"] == ["Gen.17.10"]
    assert result[1]["osis"] == ["Col.2.11-Col.2.12"]


def test_trailing_period_stripped():
    result = parse_citation_string("Heb. 11:3.")
    assert len(result) == 1
    assert result[0]["osis"] == ["Heb.11.3"]


def test_chapter_only_ref():
    result = parse_citation_string("Gen. 1; Heb. 11:3.")
    assert len(result) == 2
    assert result[0]["osis"] == ["Gen.1"]


def test_book_only_raises():
    with pytest.raises(ValueError, match="No chapter/verse found"):
        parse_single_reference("Gen")
