from __future__ import annotations

from build.lib.coverage_strategies import dispatch


PROVENANCE = {"source": "config", "path": "tests"}


def _commentary_record(*, intent: str = "exhaustive", data: list[dict] | None = None) -> dict:
    return {
        "meta": {
            "id": "sample-commentary",
            "schema_type": "commentary",
            "coverage": {
                "strategy": "scriptural_canon",
                "intent": intent,
                "parameters": {"books": {"value": ["2John"], "provenance": PROVENANCE}},
            },
        },
        "data": data if data is not None else [],
    }


def _entry(book: str, chapter: int, verse_range: str) -> dict:
    return {
        "entry_id": f"sample.{book}.{chapter}.{verse_range}",
        "book_osis": book,
        "chapter": chapter,
        "verse_range": verse_range,
    }


def _entry_inventory_parameters(expected_letters: str = "AB") -> dict:
    return {
        "expected_entry_count_range": {"value": [1, 3], "provenance": PROVENANCE},
        "alphabetical_completeness": {
            "expected_letters": expected_letters,
            "provenance": PROVENANCE,
        },
    }


def test_scriptural_canon_emits_missing_chapter() -> None:
    warnings = dispatch(
        "commentary",
        "scriptural_canon",
        {"books": {"value": ["2John"], "provenance": PROVENANCE}},
        _commentary_record(data=[]),
    )

    assert [warning["code"] for warning in warnings] == ["missing_chapter"]


def test_scriptural_canon_emits_missing_verse_range_for_exhaustive_intent() -> None:
    warnings = dispatch(
        "commentary",
        "scriptural_canon",
        {"books": {"value": ["2John"], "provenance": PROVENANCE}},
        _commentary_record(data=[_entry("2John", 1, "1"), _entry("2John", 1, "3-4")]),
    )

    assert "missing_verse_range" in {warning["code"] for warning in warnings}
    assert any(warning["evidence"]["verse_range"] == "2" for warning in warnings)


def test_scriptural_canon_suppresses_verse_gaps_for_selective_intent() -> None:
    warnings = dispatch(
        "commentary",
        "scriptural_canon",
        {"books": {"value": ["2John"], "provenance": PROVENANCE}},
        _commentary_record(intent="selective", data=[_entry("2John", 1, "1")]),
    )

    assert "missing_verse_range" not in {warning["code"] for warning in warnings}


def test_entry_inventory_emits_alphabetical_gap() -> None:
    record = {
        "meta": {"id": "sample-encyclopedia", "schema_type": "reference_entry"},
        "data": [{"entry_id": "e1", "term": "Alpha"}],
    }

    warnings = dispatch("encyclopedia", "entry_inventory", _entry_inventory_parameters("AB"), record)

    assert any(warning["code"] == "alphabetical_gap" and warning["evidence"]["letter"] == "B" for warning in warnings)


def test_entry_inventory_emits_count_and_duplicate_warnings() -> None:
    record = {
        "meta": {"id": "sample-encyclopedia", "schema_type": "reference_entry"},
        "data": [
            {"entry_id": "e1", "term": "Alpha"},
            {"entry_id": "e2", "term": " alpha "},
            {"entry_id": "e3", "term": "Beta"},
            {"entry_id": "e4", "term": "Gamma"},
        ],
    }

    warnings = dispatch("encyclopedia", "entry_inventory", _entry_inventory_parameters("ABG"), record)
    codes = {warning["code"] for warning in warnings}

    assert "entry_count_out_of_range" in codes
    assert "duplicate_headword" in codes


def test_none_strategy_emits_no_warnings() -> None:
    assert dispatch("commentary", "none", {}, _commentary_record()) == []
