from __future__ import annotations

import pytest

from build.lib.coverage_strategies import CoverageStrategyError, register_record_strategy
from build.lib.warning_producers import coverage


PROVENANCE = {"source": "config", "path": "tests"}


def _scriptural_parameters() -> dict:
    return {"books": {"value": ["2John"], "provenance": PROVENANCE}}


def _inventory_parameters() -> dict:
    return {
        "expected_entry_count_range": {"value": [1, 2], "provenance": PROVENANCE},
        "alphabetical_completeness": {"expected_letters": "A", "provenance": PROVENANCE},
    }


def test_encyclopedia_scriptural_canon_fails_registration() -> None:
    with pytest.raises(CoverageStrategyError):
        register_record_strategy("encyclopedia", "scriptural_canon", _scriptural_parameters())


def test_encyclopedia_entry_inventory_passes_registration() -> None:
    assert register_record_strategy("encyclopedia", "entry_inventory", _inventory_parameters()).__name__.endswith(
        "entry_inventory"
    )


def test_commentary_entry_inventory_fails_registration() -> None:
    with pytest.raises(CoverageStrategyError):
        register_record_strategy("commentary", "entry_inventory", _inventory_parameters())


def test_none_passes_for_declared_resource_types() -> None:
    for resource_type in [
        "commentary",
        "encyclopedia",
        "sermon_collection",
        "anthology",
        "hymnary",
        "creed_corpus",
    ]:
        assert register_record_strategy(resource_type, "none", {}).__name__.endswith("none")


def test_invalid_pair_emits_coverage_pair_invalid_warning() -> None:
    record = {
        "meta": {
            "id": "bad-encyclopedia",
            "coverage": {
                "strategy": "scriptural_canon",
                "parameters": _scriptural_parameters(),
            },
        },
        "data": [],
    }

    output = coverage.run(record, {"resource_id": "bad-encyclopedia", "resource_type": "encyclopedia"}, {})

    assert [warning["code"] for warning in output["warnings"]] == ["coverage_pair_invalid"]
    assert output["warnings"][0]["evidence"]["resource_type"] == "encyclopedia"
    assert output["warnings"][0]["evidence"]["strategy"] == "scriptural_canon"
