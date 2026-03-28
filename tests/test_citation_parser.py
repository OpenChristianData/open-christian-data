# tests/test_citation_parser.py
"""Tests for build.lib.citation_parser."""
import sys
from pathlib import Path

# Allow imports from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.lib.citation_parser import lookup_book


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
