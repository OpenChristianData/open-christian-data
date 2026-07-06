"""TDD coverage for edition-page key assignment."""

from __future__ import annotations

from build.lib.edition_page_key import (
    assign_edition_page_keys,
    body_edition_key,
    edition_page_keys_by_sha,
    edition_page_sort_key,
    resolve_edition_page_key_by_sha,
)


def _leaf(leaf_num: int, page_num: int | None, kind: str, sha: str | None = None, **extra):
    record = {
        "leaf_num": leaf_num,
        "page_num": page_num,
        "kind": kind,
        "image_state": "present",
    }
    if sha is not None:
        record["sha256"] = sha
    record.update(extra)
    return record


def _by_leaf(assignments: list[dict]) -> dict[int, dict]:
    return {assignment["leaf_num"]: assignment["edition_page_key"] for assignment in assignments}


def test_numbered_body_leaf_gets_body_page_key() -> None:
    manifest = {"leaves": [_leaf(12, 7, "body", "sha256:body")], "gaps": []}

    assert assign_edition_page_keys(manifest) == [
        {
            "source": "leaf",
            "leaf_num": 12,
            "page_num": 7,
            "kind": "body",
            "source_payload_sha256": "sha256:body",
            "edition_page_key": {"section": "body", "anchor": 7, "ordinal": 0},
        }
    ]


def test_body_edition_key_returns_body_page_key() -> None:
    assert body_edition_key(7) == {"section": "body", "anchor": 7, "ordinal": 0}


def test_recovered_gap_sha_resolves_to_body_key_and_unknown_sha_returns_none() -> None:
    manifest = {
        "leaves": [_leaf(10, 1, "body", "sha256:leaf")],
        "gaps": [{"page_num": 96, "sha256": "sha256:gap"}],
    }

    assert resolve_edition_page_key_by_sha(manifest, "sha256:gap") == {
        "section": "body",
        "anchor": 96,
        "ordinal": 0,
    }
    assert resolve_edition_page_key_by_sha(manifest, "sha256:missing") is None


def test_edition_page_keys_by_sha_covers_all_sections_and_gaps() -> None:
    manifest = {
        "leaves": [
            _leaf(1, None, "front_matter", "sha256:front", printed_page="i"),
            _leaf(20, 5, "body", "sha256:body"),
            _leaf(40, None, "back_matter", "sha256:back"),
        ],
        "gaps": [{"page_num": 96, "sha256": "sha256:gap"}],
    }

    by_sha = edition_page_keys_by_sha(manifest)

    assert by_sha["sha256:body"] == {"section": "body", "anchor": 5, "ordinal": 0}
    assert by_sha["sha256:front"]["section"] == "front_matter"
    assert by_sha["sha256:back"]["section"] == "back_matter"
    assert by_sha["sha256:gap"] == {"section": "body", "anchor": 96, "ordinal": 0}
    assert "sha256:missing" not in by_sha


def test_plate_between_body_pages_anchors_to_preceding_numbered_page() -> None:
    manifest = {
        "leaves": [
            _leaf(274, 274, "body", "sha256:274"),
            _leaf(275, None, "plate", "sha256:plate"),
            _leaf(276, 275, "body", "sha256:275"),
        ],
        "gaps": [],
    }

    assert _by_leaf(assign_edition_page_keys(manifest))[275] == {
        "section": "body",
        "anchor": 274,
        "ordinal": 1,
    }


def test_front_matter_roman_anchor_is_namespaced_from_body_anchor() -> None:
    manifest = {
        "leaves": [
            _leaf(1, None, "front_matter", "sha256:front-i", printed_page="i"),
            _leaf(2, None, "front_matter", "sha256:front-ii", printed_page="ii"),
            _leaf(20, 2, "body", "sha256:body-2"),
        ],
        "gaps": [],
    }

    keys = _by_leaf(assign_edition_page_keys(manifest))

    assert keys[2] == {"section": "front_matter", "anchor": 2, "ordinal": 0}
    assert keys[20] == {"section": "body", "anchor": 2, "ordinal": 0}
    assert keys[2] != keys[20]


def test_distinct_pages_sharing_section_anchor_get_sequential_ordinals() -> None:
    manifest = {
        "leaves": [
            _leaf(10, 96, "body", "sha256:body-96a"),
            _leaf(11, 96, "body", "sha256:body-96b"),
        ],
        "gaps": [],
    }

    keys = _by_leaf(assign_edition_page_keys(manifest))

    assert keys[10] == {"section": "body", "anchor": 96, "ordinal": 0}
    assert keys[11] == {"section": "body", "anchor": 96, "ordinal": 1}


def test_documented_transposition_keeps_printed_anchors_and_sort_restores_order() -> None:
    manifest = {
        "leaves": [
            _leaf(378, 358, "body", "sha256:358"),
            _leaf(379, 357, "body", "sha256:357"),
        ],
        "gaps": [],
    }

    keys = _by_leaf(assign_edition_page_keys(manifest))

    assert keys[378] == {"section": "body", "anchor": 358, "ordinal": 0}
    assert keys[379] == {"section": "body", "anchor": 357, "ordinal": 0}
    assert sorted([keys[378], keys[379]], key=edition_page_sort_key) == [
        {"section": "body", "anchor": 357, "ordinal": 0},
        {"section": "body", "anchor": 358, "ordinal": 0},
    ]


def test_sort_comparator_uses_section_rank_not_lexical_order() -> None:
    keys = [
        {"section": "body", "anchor": 1, "ordinal": 0},
        {"section": "back_matter", "anchor": 1, "ordinal": 0},
        {"section": "front_matter", "anchor": 1, "ordinal": 0},
    ]

    assert sorted(keys, key=edition_page_sort_key) == [
        {"section": "front_matter", "anchor": 1, "ordinal": 0},
        {"section": "body", "anchor": 1, "ordinal": 0},
        {"section": "back_matter", "anchor": 1, "ordinal": 0},
    ]
    assert sorted(keys, key=edition_page_sort_key) != sorted(keys, key=lambda key: key["section"])
