"""Tests for build.lib.resource_ids (the canonical meta.id resolver)."""

from __future__ import annotations

import pytest

from build.lib import resource_ids as ri


def test_resource_id_of_returns_meta_id():
    assert ri.resource_id_of({"meta": {"id": "adam-clarke"}}) == "adam-clarke"


def test_resource_id_of_missing_meta_raises():
    with pytest.raises(KeyError):
        ri.resource_id_of({})


def test_resource_id_of_missing_id_raises():
    with pytest.raises(KeyError):
        ri.resource_id_of({"meta": {}})


def test_resource_id_of_empty_string_raises():
    with pytest.raises(ValueError):
        ri.resource_id_of({"meta": {"id": ""}})


def test_resource_id_of_non_string_raises():
    with pytest.raises(ValueError):
        ri.resource_id_of({"meta": {"id": 42}})


@pytest.mark.parametrize(
    "value",
    [
        "schaff-herzog-encyclopedia",
        "adam-clarke",
        "a",
        "a-b-c-d-1-2",
    ],
)
def test_is_valid_resource_id_accepts_kebab(value):
    assert ri.is_valid_resource_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Schaff_Herzog",
        "schaff_herzog",
        "Schaff-Herzog",
        "schaff--herzog",
        "-schaff",
        "schaff-",
        "schaff herzog",
    ],
)
def test_is_valid_resource_id_rejects_other(value):
    assert not ri.is_valid_resource_id(value)


def test_entry_id_prefix_returns_first_segment():
    assert ri.entry_id_prefix("schaff-herzog.theotokos") == "schaff-herzog"
    assert ri.entry_id_prefix("clarke.2John.1.1") == "clarke"


def test_entry_id_prefix_no_dots_returns_self():
    assert ri.entry_id_prefix("standalone") == "standalone"


def test_entry_id_prefix_empty_raises():
    with pytest.raises(ValueError):
        ri.entry_id_prefix("")
