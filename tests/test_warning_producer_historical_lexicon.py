from __future__ import annotations

from build.lib.warning_producers.historical_lexicon import run


def _commentary(text: str):
    return {
        "meta": {"schema_type": "commentary", "id": "sample"},
        "data": [{"entry_id": "e1", "commentary_text": text}],
    }


def _reference(term: str):
    return {
        "meta": {"schema_type": "reference_entry", "id": "sample"},
        "data": [{"entry_id": "r1", "term": term, "alt_terms": [], "definition_blocks": []}],
    }


def test_shew_emits_archaic_variant() -> None:
    warnings = run(_commentary("They shew the way."), {"resource_type": "commentary"}, {})["warnings"]

    assert len(warnings) == 1
    assert warnings[0]["code"] == "archaic_variant"
    assert warnings[0]["evidence"]["surface"] == "shew"
    assert warnings[0]["evidence"]["normalised"] == "show"


def test_clean_text_emits_no_warnings() -> None:
    assert run(_commentary("They show the way."), {"resource_type": "commentary"}, {})["warnings"] == []


def test_reference_entry_term_field_is_scanned() -> None:
    warnings = run(_reference("shew"), {"resource_type": "encyclopedia"}, {})["warnings"]

    assert warnings[0]["field_path"] == "term"
    assert warnings[0]["code"] == "archaic_variant"
