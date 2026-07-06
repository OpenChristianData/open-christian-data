"""Tests for bible_text_translations.py.

Parameterized parser that ingests public-domain Bible translations from the
scrollmapper bible_databases JSON (same shape as BSB.json) into the bible_text
schema, reusing the BSB book-name/OSIS maps. Integration tests are skipped when
the per-translation source JSON is absent (gitignored raw/).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.schema_enums import get_enum  # noqa: E402
from build.parsers import bible_text_translations as btt  # noqa: E402


EXPECTED_PD_TRANSLATIONS = {
    "asv": {
        "book_count": 66,
        "genesis_count": 1533,
        "source_label": "ASV: American Standard Version (1901)",
        "known_verses": {
            "Gen.1.1": "In the beginning God created the heavens and the earth.",
            "John.3.16": "For God so loved the world, that he gave his only begotten Son",
            "Ps.23.1": "Jehovah is my shepherd; I shall not want.",
        },
    },
    "ylt": {
        "book_count": 66,
        "genesis_count": 1533,
        "source_label": "YLT: Young's Literal Translation (1898)",
        "known_verses": {
            "Gen.1.1": "In the beginning of God's preparing the heavens and the earth",
            "John.3.16": "for God did so love the world",
            "Ps.23.1": "A Psalm of David. Jehovah is my shepherd, I do not lack",
        },
    },
    "darby": {
        "book_count": 66,
        "genesis_count": 1533,
        "source_label": "Darby: Darby Bible (1889)",
        "known_verses": {
            "Gen.1.1": "In the beginning God created the heavens and the earth.",
            "John.3.16": "For God so loved the world",
            "Ps.23.1": "Jehovah is my shepherd; I shall not want.",
        },
    },
    "webster": {
        "book_count": 66,
        "genesis_count": 1533,
        "source_label": "Webster: Webster Bible",
        "known_verses": {
            "Gen.1.1": "In the beginning God created the heaven and the earth.",
            "John.3.16": "For God so loved the world",
            "Ps.23.1": "A Psalm of David. The LORD [is] my shepherd; I shall not want.",
        },
    },
    "kjva": {
        "book_count": 80,
        "genesis_count": 1533,
        "source_label": "KJVA: King James Version (1769)",
        "known_verses": {
            "Gen.1.1": "In the beginning God created the heaven and the earth.",
            "John.3.16": "For God so loved the world",
            "Ps.23.1": "The Lord is my shepherd; I shall not want.",
        },
    },
    "jps": {
        "book_count": 39,
        "genesis_count": 1533,
        "source_label": "JPS: Jewish Publication Society Old Testament",
        "known_verses": {
            "Gen.1.1": "IN THE beginning G-d created the heaven and the earth.",
            "Ps.23.1": "A Psalm of David. HaShem is my shepherd; I shall not want.",
        },
    },
    "drc": {
        "book_count": 78,
        "genesis_count": 1530,
        "source_label": "DRC: Douay-Rheims Bible, Challoner Revision",
        "known_verses": {
            "Gen.1.1": "In the beginning God created heaven, and earth.",
            "John.3.16": "For God so loved the world",
            "Ps.23.1": "On the first day of the week, a psalm for David. The earth is the Lord's",
        },
    },
}


ALL_PD_TRANSLATIONS = ["kjv", *EXPECTED_PD_TRANSLATIONS]


def test_translation_configs_enum_valid():
    trad = get_enum("bible_text", "meta", "tradition")
    lic = get_enum("bible_text", "meta", "license")
    assert btt.TRANSLATIONS, "expected at least one translation configured"
    for tid, cfg in btt.TRANSLATIONS.items():
        assert set(cfg["tradition"]) <= trad, f"{tid}: bad tradition {cfg['tradition']}"
        assert cfg["license"] in lic, f"{tid}: bad license {cfg['license']}"
        assert cfg["license"] == "public-domain", f"{tid}: only PD translations belong here"


def _verse_lookup(tid: str) -> dict[str, str]:
    _require_source(tid)
    verses: dict[str, str] = {}
    books = btt.load_translation_books(tid)
    for book in books:
        osis = btt.NAME_TO_OSIS[book["name"]]
        for entry in btt.build_verse_entries(book, osis):
            verses[entry["osis"]] = entry["text"]
    return verses


def _require_source(tid: str) -> Path:
    src = btt.source_path(tid)
    if not src.exists():
        pytest.skip(f"{tid} source not present: {src.name}")
    return src


def test_all_target_pd_translations_are_registered():
    assert set(EXPECTED_PD_TRANSLATIONS) <= set(btt.TRANSLATIONS)
    for tid in EXPECTED_PD_TRANSLATIONS:
        cfg = btt.TRANSLATIONS[tid]
        assert cfg["license"] == "public-domain"
        assert cfg["original_publication_year"] < 1928


@pytest.mark.parametrize("tid", ALL_PD_TRANSLATIONS)
def test_source_present_and_book_names_map(tid):
    _require_source(tid)
    books = btt.load_translation_books(tid)
    expected = EXPECTED_PD_TRANSLATIONS.get(tid, {"book_count": 66})["book_count"]
    assert len(books) == expected, f"{tid}: expected {expected} books, got {len(books)}"
    unmapped = [b["name"] for b in books if b["name"] not in btt.NAME_TO_OSIS]
    assert not unmapped, f"{tid}: unmapped book names {unmapped}"


@pytest.mark.parametrize("tid, expected", EXPECTED_PD_TRANSLATIONS.items())
def test_source_metadata_confirms_translation_identity(tid, expected):
    _require_source(tid)
    source = btt.load_source_payload(tid)
    assert source["translation"].startswith(expected["source_label"])


def test_kjv_known_verses():
    if not btt.source_path("kjv").exists():
        pytest.skip("KJV source not present")
    books = {b["name"]: b for b in btt.load_translation_books("kjv")}
    gen = btt.build_verse_entries(books["Genesis"], "Gen")
    g11 = next(e for e in gen if e["osis"] == "Gen.1.1")
    assert g11["text"] == "In the beginning God created the heaven and the earth."
    john = btt.build_verse_entries(books["John"], "John")
    j316 = next(e for e in john if e["osis"] == "John.3.16")
    assert j316["text"].startswith("For God so loved the world")


@pytest.mark.parametrize("tid", ALL_PD_TRANSLATIONS)
def test_verse_entries_have_no_markup(tid):
    _require_source(tid)
    import re
    tag = re.compile(r"\{[HG]?\d+\}|<[^>]+>")
    books = btt.load_translation_books(tid)
    for b in books:
        for e in btt.build_verse_entries(b, btt.NAME_TO_OSIS[b["name"]]):
            assert not tag.search(e["text"]), f"{tid}: markup leaked: {e['osis']}"


@pytest.mark.parametrize("tid, expected", EXPECTED_PD_TRANSLATIONS.items())
def test_known_verses_match_expected_translation(tid, expected):
    verses = _verse_lookup(tid)
    for osis, text_start in expected["known_verses"].items():
        assert verses[osis].startswith(text_start), f"{tid} {osis}"


@pytest.mark.parametrize("tid", ALL_PD_TRANSLATIONS)
def test_output_verse_count(tid):
    book = REPO_ROOT / "data" / "bible-text" / tid / "genesis.json"
    assert book.exists(), f"{tid} genesis.json not generated"
    import json
    d = json.loads(book.read_text(encoding="utf-8"))
    expected = EXPECTED_PD_TRANSLATIONS.get(tid, {"genesis_count": 1533})["genesis_count"]
    assert len(d["data"]) == expected
