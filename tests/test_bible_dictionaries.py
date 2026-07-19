"""Tests for Bible dictionary field mappings.

The raw JSONL corpus is also checked when present so the source-field census
cannot silently drift back to a sample-only assertion.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from build.parsers import bible_dictionaries as parser


@pytest.mark.parametrize("source_name", ["eastons", "smiths", "hitchcocks", "torreys"])
def test_raw_source_field_census_is_term_and_definitions(source_name: str) -> None:
    source_path = parser.RAW_DIR / parser.DICTIONARIES[source_name]["source_file"]
    if not source_path.exists():
        pytest.skip(f"raw source unavailable: {source_path}")

    records = parser.load_jsonl(source_path)
    assert records
    assert all(set(record) == {"term", "definitions"} for record in records)
    assert all(isinstance(record["term"], str) for record in records)
    assert all(isinstance(record["definitions"], list) for record in records)


def test_extract_scripture_references_preserves_source_and_normalizes_osis() -> None:
    references = parser.extract_scripture_references([
        "Alpha is named in Rev. 1:8, 11; 21:6; 22:13, and Heb. 12:2."
    ])

    assert references == [
        {
            "raw": "Rev. 1:8, 11; 21:6; 22:13",
            "osis": ["Rev.1.8", "Rev.1.11", "Rev.21.6", "Rev.22.13"],
        },
        {"raw": "Heb. 12:2", "osis": ["Heb.12.2"]},
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(See [1]MOSES.)", ["MOSES"]),
        ("See [10]Shittah Tree, Shittim, [11]Shittim.", ["Shittah Tree, Shittim", "Shittim"]),
        ('See "Love to man".', ["Love to man"]),
        ("See chapters 10, 40-48 of Ezekiel.", []),
    ],
)
def test_extract_related_terms_only_maps_explicit_headword_links(
    text: str, expected: list[str]
) -> None:
    assert parser.extract_related_terms([text]) == expected


def test_parse_torrey_subtopics_normalizes_inline_references() -> None:
    subtopics = parser.parse_torrey_subtopics([
        "Is by Christ -- Joh 10:7, 9; 14:6; Ro 5:2.",
        "Exemplified",
    ])

    assert subtopics == [
        {
            "label": "Is by Christ",
            "references": [
                {
                    "raw": "Joh 10:7, 9; 14:6; Ro 5:2.",
                    "osis": ["John.10.7", "John.10.9", "John.14.6", "Rom.5.2"],
                }
            ],
        },
        {"label": "Exemplified", "references": []},
    ]


def _write_source(tmp_path: Path, filename: str, records: list[dict]) -> None:
    source_path = tmp_path / filename
    source_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_reference_parser_writes_enriched_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_source(tmp_path, "eastons.jsonl", [{
        "term": "Abba",
        "definitions": [
            "This word is found in Mark 14:36.",
            "(See [1]MOSES.)",
        ],
    }])
    config = deepcopy(parser.DICTIONARIES["eastons"])
    config["source_file"] = "eastons.jsonl"
    config["expected_count"] = 1
    monkeypatch.setattr(parser, "RAW_DIR", tmp_path)
    monkeypatch.setattr(parser, "OUTPUT_DIR", tmp_path / "data" / "reference")

    stats = parser.process_reference_dict("eastons", config)
    output = json.loads(
        (tmp_path / "data" / "reference" / "eastons-bible-dictionary.json").read_text(encoding="utf-8")
    )
    entry = output["data"][0]

    assert stats["scripture_populated"] == 1
    assert stats["related_populated"] == 1
    assert entry["alt_terms"] == []
    assert entry["scripture_references"] == [
        {"raw": "Mark 14:36", "osis": ["Mark.14.36"]}
    ]
    assert entry["related_terms"] == ["MOSES"]


def test_torrey_parser_writes_enriched_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_source(tmp_path, "torreys.jsonl", [{
        "term": "Access to God",
        "definitions": [
            "Is of God -- Ps 65:4.",
            "In Prayer -- See Prayer. De 4:7; Mt 6:6.",
        ],
    }])
    config = deepcopy(parser.DICTIONARIES["torreys"])
    config["source_file"] = "torreys.jsonl"
    config["expected_count"] = 1
    monkeypatch.setattr(parser, "RAW_DIR", tmp_path)
    monkeypatch.setattr(parser, "OUTPUT_DIR", tmp_path / "data" / "reference")

    stats = parser.process_torrey("torreys", config)
    output = json.loads(
        (tmp_path / "data" / "reference" / "torreys-topical-textbook.json").read_text(encoding="utf-8")
    )
    entry = output["data"][0]

    assert stats["reference_total"] == 3
    assert stats["related_total"] == 1
    assert entry["alt_topics"] == []
    assert entry["related_topics"] == ["Prayer"]
    assert entry["subtopics"][0]["references"][0]["osis"] == ["Ps.65.4"]
    assert entry["subtopics"][1]["references"][0]["osis"] == ["Deut.4.7", "Matt.6.6"]
