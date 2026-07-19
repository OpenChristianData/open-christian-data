from __future__ import annotations

from ocd_kernel.lib.warning_producers.structural_integrity import run


def _codes(record):
    return [warning["code"] for warning in run(record, {"resource_type": "commentary"}, {})["warnings"]]


def test_duplicate_entry_ids_emit_one_warning() -> None:
    record = {"data": [{"entry_id": "a"}, {"entry_id": "a"}]}

    assert _codes(record).count("duplicate_entry_id") == 1


def test_missing_entry_id_emits_one_warning() -> None:
    record = {"data": [{"commentary_text": "text"}]}

    assert _codes(record).count("missing_entry_id") == 1


def test_cross_references_not_list_emits_warning() -> None:
    record = {"data": [{"entry_id": "a", "cross_references": "bad"}]}

    assert "cross_references_shape" in _codes(record)


def test_cross_references_non_string_element_emits_warning() -> None:
    record = {"data": [{"entry_id": "a", "cross_references": ["Gen.1.1", 1]}]}

    assert "cross_references_shape" in _codes(record)


def test_related_terms_not_list_emits_warning() -> None:
    record = {"data": [{"entry_id": "a", "related_terms": "bad"}]}

    assert "related_terms_shape" in _codes(record)


def test_clean_record_emits_no_warnings() -> None:
    record = {"data": [{"entry_id": "a", "cross_references": [], "related_terms": []}]}

    assert run(record, {"resource_type": "commentary"}, {})["warnings"] == []
