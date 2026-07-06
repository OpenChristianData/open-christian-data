from __future__ import annotations

from build.lib.warning_producers.text_suspicion import run


def _commentary(text: str):
    return {
        "meta": {"schema_type": "commentary", "id": "sample"},
        "data": [{"entry_id": "e1", "commentary_text": text}],
    }


def _reference(text: str):
    return {
        "meta": {"schema_type": "reference_entry", "id": "sample"},
        "data": [{"entry_id": "r1", "term": "Term", "alt_terms": [], "definition_blocks": [text]}],
    }


def _reference_with_term(term: str):
    return {
        "meta": {"schema_type": "reference_entry", "id": "sample"},
        "data": [{"entry_id": "r1", "term": term, "alt_terms": ["A"], "definition_blocks": ["Definition text."]}],
    }


def _codes(record):
    return [warning["code"] for warning in run(record, {"resource_type": "commentary"}, {})["warnings"]]


def test_replacement_character_in_commentary_text() -> None:
    assert "replacement_character" in _codes(_commentary("Bad \ufffd text."))


def test_possible_broken_hyphenation() -> None:
    assert "possible_broken_hyphenation" in _codes(_commentary("The word- word broke."))


def test_odd_double_quotes() -> None:
    assert "odd_double_quotes" in _codes(_commentary('The "quote is odd.'))


def test_repeated_paragraph_emits_once() -> None:
    record = {
        "meta": {"schema_type": "commentary", "id": "sample"},
        "data": [
            {"entry_id": "e1", "commentary_text": "Repeated paragraph."},
            {"entry_id": "e2", "commentary_text": "Repeated paragraph."},
        ],
    }

    assert _codes(record).count("repeated_paragraph") == 1


def test_likely_ocr_junk_sequence() -> None:
    assert "likely_ocr_junk_sequence" in _codes(_commentary("Readable text ||| junk."))


def test_suspiciously_short() -> None:
    assert "suspiciously_short" in _codes(_commentary("One"))


def test_suspiciously_long() -> None:
    assert "suspiciously_long" in _codes(_commentary("word " * 1600))


def test_reference_entry_definition_blocks_are_scanned() -> None:
    warnings = run(_reference("Broken word- word here."), {"resource_type": "encyclopedia"}, {})["warnings"]

    assert any(warning["code"] == "possible_broken_hyphenation" for warning in warnings)
    assert any(warning["field_path"] == "definition_blocks.0" for warning in warnings)


def test_short_reference_term_does_not_emit_suspiciously_short() -> None:
    warnings = run(_reference_with_term("A"), {"resource_type": "encyclopedia"}, {})["warnings"]

    assert not any(
        warning["code"] == "suspiciously_short" and warning["field_path"] in {"term", "alt_terms.0"}
        for warning in warnings
    )


def test_short_commentary_text_still_emits_suspiciously_short() -> None:
    warnings = run(_commentary("A"), {"resource_type": "commentary"}, {})["warnings"]

    assert any(warning["code"] == "suspiciously_short" and warning["field_path"] == "commentary_text" for warning in warnings)
