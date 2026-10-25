"""Retained-source fidelity tests for the maintained Didache prayer parser."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import pytest

from build.parsers.didache import (
    API_URL,
    COLLECTION_ID,
    CONFIG_PATH,
    RAW_FILE,
    TARGET_CHAPTERS,
    extract_prayers,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "didache" / "chapters_viii_x.wikitext"
WITNESSES = REPO_ROOT / "sources" / "didache-prayers" / "witnesses.json"
RAW_SHA256 = "9ba0420fc2f1ef3d960335c100e31f8edbe7343b7fc5eab66dcce075744db764"
CONFIG_SHA256 = "bc23edc1f9056a7d42620828c6581c5cd500f61cd50ac14708a3c3c77a84f43e"
WITNESSES_SHA256 = "5de73e23f561f46df113c23f54212e12a456c5a0e1dfdbdc1945ff80eb486986"
WINDOW_SHA256 = "5028d4f329d26dceb1d148e92c74287e6766bfdc8d8120aedf2fe74faf9d75f2"

SELECTION = {
    "8-lords-prayer": ("8.2",),
    "9-cup": ("9.2",),
    "9-bread": ("9.3", "9.4"),
    "10-thanksgiving": ("10.2", "10.3", "10.4", "10.5", "10.6"),
}
RUBRIC_ADDRESSES = {"8.3", "9.1", "10.1"}
EXCLUDED_VERSE_ADDRESSES = {"8.1", "9.5", "10.7"}
PRAYER_CONTENT_SHA256 = {
    "8-lords-prayer": "915705888deaa63b348dd871e6d02564e5b1d9a7e160ecde9bccc21385609994",
    "9-cup": "3aee489cff1f755a73c35d3d6d6fc3fbc9c49fb08bba5b319903c7b5a4e7e046",
    "9-bread": "964934ad4a3a2783e54ec8a2c2eb266261ee4ce43a90379699b09206aef02b9d",
    "10-thanksgiving": "84d07f54e8e91f617640f6030749194862934867cd92c7846b5212b078295ff1",
}
LOCATIONS = {
    "8-lords-prayer": "Chapter VIII.2",
    "9-cup": "Chapter IX.2",
    "9-bread": "Chapter IX.3-4",
    "10-thanksgiving": "Chapter X.2-6",
}


def _feature_census(wikitext: str) -> Counter[str]:
    patterns = {
        "chapter": r"(?m)^==Chapter (?:VIII|IX|X)==$",
        "chapter-template": r"\{\{chapter\|(?:8|9|10)\}\}",
        "footnote": r"<ref[^>]*>.*?</ref>",
        "label": r"\|<small>.*?</small>",
        "table-close": r"(?m)^\|\}$",
        "table-open": r"(?m)^\{\|$",
        "table-row": r'(?m)^\|-valign="top"$',
        "table-width-cell": r'(?m)^\|width="\d+%"\|$',
        "verse-segment": r"\{\{verse\|chapter=(?:8|9|10)\|verse=\d+\}\}",
    }
    return Counter(
        {
            kind: len(re.findall(pattern, wikitext, flags=re.DOTALL))
            for kind, pattern in patterns.items()
        }
    )


def _feature_ids(wikitext: str) -> set[str]:
    addresses = re.findall(
        r"\{\{verse\|chapter=(8|9|10)\|verse=(\d+)\}\}", wikitext
    )
    ids = {
        *(f"chapter-{chapter}" for chapter in (8, 9, 10)),
        *(f"chapter-template-{chapter}" for chapter in (8, 9, 10)),
        *(f"table-open-{chapter}" for chapter in (8, 9, 10)),
        *(f"table-close-{chapter}" for chapter in (8, 9, 10)),
        *(f"verse-{chapter}-{verse}" for chapter, verse in addresses),
        "row-8-1",
        "row-8-2",
        "row-9-1",
        "row-9-2",
        "row-9-3",
        "row-10-1",
        "label-8-1",
        "label-8-2",
        "label-9-1",
        "label-9-2",
        "label-9-3",
        "label-10-1",
        "footnote-8-2",
        "footnote-9-1",
        "footnote-10-6",
    }
    ids.update(
        f"table-width-cell-{chapter}-{ordinal}"
        for chapter in (8, 9, 10)
        for ordinal in (1, 2)
    )
    return ids


def test_didache_viii_x_fixture_preserves_selection_and_feature_accounting() -> None:
    content = FIXTURE.read_bytes()
    assert len(content) == 3_976
    assert hashlib.sha256(content).hexdigest() == WINDOW_SHA256

    wikitext = content.decode("utf-8")
    assert len(wikitext.splitlines()) == 41
    assert wikitext.startswith("==Chapter VIII==\n")
    assert "==Chapter XI==" not in wikitext
    assert TARGET_CHAPTERS == [("VIII", 8), ("IX", 9), ("X", 10)]

    chapter_starts = {
        chapter: wikitext.index(f"==Chapter {chapter}==")
        for chapter in ("VIII", "IX", "X")
    }
    chapter_ranges = {
        "8": (chapter_starts["VIII"], chapter_starts["IX"]),
        "9": (chapter_starts["IX"], chapter_starts["X"]),
        "10": (chapter_starts["X"], len(wikitext)),
    }
    expected_chapters = {
        "8": (1_040, "57619d3488497b5097dea1438a9bee6533f2f777bc3a98e2e57608c58ed9b670"),
        "9": (1_431, "5e9ef78a0cc546b4fc0ae7a86d6371b32246ee77256ca2e7cb74e9e7a91dc7f4"),
        "10": (1_505, "5c7a755613d574bc474448822e9daad8ef03ccc1404d4d289f5182e8a6f34a66"),
    }
    for chapter, (start, end) in chapter_ranges.items():
        chapter_bytes = wikitext[start:end].encode("utf-8")
        assert (len(chapter_bytes), hashlib.sha256(chapter_bytes).hexdigest()) == (
            expected_chapters[chapter]
        )

    prayers = extract_prayers(wikitext)
    assert [prayer["prayer_id"] for prayer in prayers] == list(SELECTION)
    assert len(prayers) == 4
    assert sum(len(addresses) for addresses in SELECTION.values()) == 9
    selected_addresses = {
        address for addresses in SELECTION.values() for address in addresses
    }
    assert selected_addresses | RUBRIC_ADDRESSES | EXCLUDED_VERSE_ADDRESSES == {
        *(f"8.{verse}" for verse in range(1, 4)),
        *(f"9.{verse}" for verse in range(1, 6)),
        *(f"10.{verse}" for verse in range(1, 8)),
    }
    assert not (
        selected_addresses & RUBRIC_ADDRESSES
        or selected_addresses & EXCLUDED_VERSE_ADDRESSES
        or RUBRIC_ADDRESSES & EXCLUDED_VERSE_ADDRESSES
    )
    assert {prayer["prayer_id"]: prayer["location"] for prayer in prayers} == LOCATIONS
    assert {
        prayer["prayer_id"]: hashlib.sha256(prayer["content"].encode("utf-8")).hexdigest()
        for prayer in prayers
    } == PRAYER_CONTENT_SHA256

    assert _feature_census(wikitext) == Counter(
        {
            "chapter": 3,
            "chapter-template": 3,
            "footnote": 3,
            "label": 6,
            "table-close": 3,
            "table-open": 3,
            "table-row": 6,
            "table-width-cell": 6,
            "verse-segment": 15,
        }
    )
    feature_ids = _feature_ids(wikitext)
    assert len(feature_ids) == 48
    explained_exclusions = {
        *(f"table-open-{chapter}" for chapter in (8, 9, 10)),
        *(f"table-close-{chapter}" for chapter in (8, 9, 10)),
        *(
            f"table-width-cell-{chapter}-{ordinal}"
            for chapter in (8, 9, 10)
            for ordinal in (1, 2)
        ),
        "verse-8-1",
        "verse-9-5",
        "verse-10-7",
    }
    preserved_evidence = {"row-8-1", "label-8-1"}
    represented = feature_ids - explained_exclusions - preserved_evidence
    assert (len(explained_exclusions), len(preserved_evidence), len(represented)) == (
        15,
        2,
        31,
    )
    assert feature_ids == explained_exclusions | preserved_evidence | represented

    labels = re.findall(r"\|<small>(.*?)</small>", wikitext, flags=re.DOTALL)
    assert labels == [
        "Fasting",
        "Prayers",
        "The Eucharist",
        "The Cup",
        "The Bread",
        "The final prayer in the Eucharist",
    ]
    footnotes = re.findall(r"<ref[^>]*>(.*?)</ref>", wikitext, flags=re.DOTALL)
    assert len(footnotes) == 3
    assert "by no means certain" in footnotes[0]
    assert "translation fails to preserve the play" in footnotes[1]
    assert "Our Lord! Come!" in footnotes[2]

    config_bytes = CONFIG_PATH.read_bytes()
    witnesses_bytes = WITNESSES.read_bytes()
    assert hashlib.sha256(config_bytes).hexdigest() == CONFIG_SHA256
    assert hashlib.sha256(witnesses_bytes).hexdigest() == WITNESSES_SHA256
    config = json.loads(config_bytes)
    witnesses = json.loads(witnesses_bytes)
    assert COLLECTION_ID == config["collection_id"] == config["resource_id"]
    assert RAW_FILE.relative_to(REPO_ROOT).as_posix() == "raw/wikisource/didache.json"
    assert CONFIG_PATH.relative_to(REPO_ROOT).as_posix() == (
        "sources/prayers/didache/config.json"
    )
    assert WITNESSES.relative_to(REPO_ROOT).as_posix() == (
        "sources/didache-prayers/witnesses.json"
    )
    assert config["contributors"] == ["Kirsopp Lake (translator)"]
    assert config["source_edition"] == (
        "Kirsopp Lake translation, 1912; digitized by Wikisource contributors"
    )
    assert config["source_url"] == "https://en.wikisource.org/wiki/Didache_(Lake_translation)"
    assert config["expected_count"] == 4
    assert API_URL.endswith(
        "?action=parse&page=Didache_(Lake_translation)&prop=wikitext&format=json"
    )

    # These remain explicit gaps: attribution is not an exact Greek-exemplar
    # binding, and the public-domain claim has no acceptance-ready rights record.
    assert witnesses["witnesses"] == []
    assert witnesses["cross_source_readings"] == []
    assert "exact_greek_exemplar" not in config
    assert "rights_evidence" not in config


def test_didache_fixture_matches_retained_mediawiki_source_when_available() -> None:
    if not RAW_FILE.is_file():
        pytest.skip("ignored retained source is unavailable: raw/wikisource/didache.json")

    raw_bytes = RAW_FILE.read_bytes()
    assert len(raw_bytes) == 23_668
    assert hashlib.sha256(raw_bytes).hexdigest() == RAW_SHA256
    payload = json.loads(raw_bytes)
    assert payload["parse"]["title"] == "Didache (Lake translation)"
    assert payload["parse"]["pageid"] == 191_639

    wikitext = payload["parse"]["wikitext"]["*"]
    start = wikitext.index("==Chapter VIII==")
    end = wikitext.index("==Chapter XI==")
    assert (start, end) == (10_909, 14_875)
    assert (
        len(wikitext[:start].encode("utf-8")),
        len(wikitext[:end].encode("utf-8")),
    ) == (10_913, 14_889)
    assert (
        wikitext.count("\n", 0, start) + 1,
        wikitext.count("\n", 0, end - 1) + 1,
    ) == (104, 144)
    assert wikitext[start:end].encode("utf-8") == FIXTURE.read_bytes()
