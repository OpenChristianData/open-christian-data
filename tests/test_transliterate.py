from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import json

from jsonschema import Draft202012Validator


GREEK_SEGMENT = "  ἀγάπη\tλόγος  "
HEBREW_SEGMENT = "  אֲדֹנָי\tיהוה  "
GREEK_TRANSLITERATION = "agapē logos"
HEBREW_TRANSLITERATION = "Adonai Yahweh"


def _transliterate(record: dict) -> dict:
    from build.lib.modernisation.engine import transliterate_record

    return transliterate_record(deepcopy(record))


def _base_record(blocks: list[dict]) -> dict:
    return {
        "meta": {
            "id": "test-work",
            "title": "Test Work",
            "author_slug": "test-author",
            "author_display_name": "Test Author",
            "author_birth_year": None,
            "author_death_year": None,
            "original_publication_year": 1890,
            "language": "en",
            "tradition": ["reformed"],
            "license": "public-domain",
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "edition": "test",
            "pd_anchor": "test-rendering",
            "modernisation_ruleset_version": None,
            "attestation_summary": {
                "block_count": len(blocks),
                "fully_attested_blocks": len(blocks),
                "blocks_with_disagreements": 0,
                "blocks_with_structural_disagreements": 0,
            },
        },
        "blocks": blocks,
        "match_explanations": [],
    }


def _block(text: str, *, language: str = "en", language_segments: list[dict] | None = None) -> dict:
    return {
        "block_id": "test-block",
        "block_id_history": [],
        "block_type": "paragraph",
        "language": language,
        "language_confidence": 0.95,
        "language_alternates": [],
        "language_segments": language_segments or [],
        "original_text": text,
        "modern_text": "",
        "annotations": {},
        "source_pages": [{"rendering_id": "test-rendering", "page_number": 1}],
        "attested_by": ["test-rendering"],
        "disagreements": [],
        "structural_disagreements": [],
        "modernisations": [],
    }


def _language_segment_validator() -> Draft202012Validator:
    schema_path = Path("schemas/v1/reconciled_record.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema["$defs"]["language_segment"])


def _assert_schema_valid_segment(segment: dict) -> None:
    assert isinstance(segment.get("original_script"), str)
    _language_segment_validator().validate(segment)


def _segments_for_language(record: dict, language: str) -> list[dict]:
    return [
        segment
        for block in record["blocks"]
        for segment in block["language_segments"]
        if segment.get("language") == language
    ]


def test_round_trip_per_language() -> None:
    cases = [
        ("grc", GREEK_SEGMENT, GREEK_TRANSLITERATION),
        ("hbo", HEBREW_SEGMENT, HEBREW_TRANSLITERATION),
    ]

    for language, source_script, expected_transliteration in cases:
        result = _transliterate(_base_record([_block(source_script, language=language)]))
        segments = _segments_for_language(result, language)

        assert len(segments) == 1
        segment = segments[0]
        _assert_schema_valid_segment(segment)
        assert segment["original_script"].encode("utf-8") == source_script.encode("utf-8")
        assert segment["transliteration"] == expected_transliteration
        assert segment["language"] == language


def test_original_script_byte_preservation() -> None:
    source_script = " \tἀγάπη\nλόγος  "

    result = _transliterate(_base_record([_block(source_script, language="grc")]))
    segments = _segments_for_language(result, "grc")

    assert len(segments) == 1
    original_script = segments[0]["original_script"]
    assert original_script.encode("utf-8") == source_script.encode("utf-8")
    assert original_script == source_script
    assert original_script != source_script.strip()


def test_transliterated_from_for_latin_source_segments() -> None:
    text = "The apostle's agapē is treated as Christian charity in the note."

    result = _transliterate(_base_record([_block(text)]))
    segments = result["blocks"][0]["language_segments"]

    assert len(segments) == 1
    segment = segments[0]
    assert segment["transliterated_from"] == "grc"
    assert segment["original_script"] is None
    assert segment["transliteration"] == "agapē"
    assert segment["language"] == "grc"


def test_no_op_for_latin_only_blocks() -> None:
    text = "This ordinary English paragraph contains no source-script text."

    result = _transliterate(_base_record([_block(text)]))

    assert result["blocks"][0]["language_segments"] == []
    assert result["blocks"][0]["original_text"].encode("utf-8") == text.encode("utf-8")
    assert result["blocks"][0]["original_text"] == text


def test_mixed_script_disagreement_carries_original_script() -> None:
    text = "The phrase ἀγάπη λόγος appears in the printed discussion."

    result = _transliterate(_base_record([_block(text)]))
    segments = result["blocks"][0]["language_segments"]
    greek_segments = [segment for segment in segments if segment.get("language") == "grc"]
    latin_segments = [segment for segment in segments if segment.get("language") == "en"]

    assert len(greek_segments) == 1
    _assert_schema_valid_segment(greek_segments[0])
    assert greek_segments[0]["original_script"] == "ἀγάπη λόγος"
    assert greek_segments[0]["transliteration"] == GREEK_TRANSLITERATION
    assert all(segment.get("original_script") is None for segment in latin_segments)


def test_re_transliterate_preserves_editorial_overrides() -> None:
    existing_segment = {
        "span": {"start_token": 1, "end_token": 3},
        "language": "grc",
        "original_script": "ἀγάπη λόγος",
        "transliteration": "editorial agape logos",
        "editorial_override": True,
    }
    text = "The phrase ἀγάπη λόγος appears in the printed discussion."

    result = _transliterate(_base_record([_block(text, language_segments=[existing_segment])]))
    segments = result["blocks"][0]["language_segments"]
    overridden = [segment for segment in segments if segment.get("editorial_override") is True]

    assert overridden == [existing_segment]
    assert overridden[0]["transliteration"] == "editorial agape logos"
    assert overridden[0]["original_script"] == "ἀγάπη λόγος"
