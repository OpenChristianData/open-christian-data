"""Edition page key assignment for paginated source manifests."""

from __future__ import annotations

from typing import Any

from build.lib.nsh_leaf_model import gap_by_sha, leaf_by_sha, leaves_view
from build.lib.schema_enums import get_enum

_KIND_VALUES = get_enum("source_manifest", "leaves", "kind")
_SECTION_RANK = {"front_matter": 0, "body": 1, "back_matter": 2}
_ROMAN_VALUES = {
    "i": 1,
    "v": 5,
    "x": 10,
    "l": 50,
    "c": 100,
    "d": 500,
    "m": 1000,
}


def edition_page_sort_key(key: dict[str, Any]) -> tuple[int, int, int, str]:
    """Return the explicit, deterministic sort key for an edition page key."""
    section = key["section"]
    return (
        _SECTION_RANK[section],
        int(key["anchor"]),
        int(key["ordinal"]),
        section,
    )


def resolve_edition_page_key_by_sha(manifest: dict, sha: str) -> dict[str, int | str] | None:
    """Resolve a page-image SHA to its simple body edition key, if known."""
    leaf_matches = leaf_by_sha(manifest).get(sha, [])
    body_matches = [
        leaf for leaf in leaf_matches if leaf.get("kind") == "body" and isinstance(leaf.get("page_num"), int)
    ]
    if len(body_matches) == 1:
        return _key("body", body_matches[0]["page_num"], 0)

    gap = gap_by_sha(manifest).get(sha)
    if gap is not None and isinstance(gap.get("page_num"), int):
        return _key("body", gap["page_num"], 0)

    return None


def body_edition_key(page_num: int) -> dict[str, int | str]:
    """Return the edition key for a numbered body page."""
    return _key("body", page_num, 0)


def edition_page_keys_by_sha(manifest: dict) -> dict[str, dict[str, int | str]]:
    """Index every assigned edition page key by its source-payload sha.

    Covers all sections (front_matter / body / back_matter / plate) and recovered
    gaps via :func:`assign_edition_page_keys`. Unlike
    :func:`resolve_edition_page_key_by_sha` (the body + gap fast path), an S1
    runner that OCRs front/back-matter (the page_order opt-in path) needs the
    full-section map so every emitted page carries a required ``edition_page_key``.
    Later duplicates of a sha are ignored (first assignment wins).
    """
    by_sha: dict[str, dict[str, int | str]] = {}
    for assignment in assign_edition_page_keys(manifest):
        sha = assignment.get("source_payload_sha256")
        key = assignment.get("edition_page_key")
        if isinstance(sha, str) and key is not None and sha not in by_sha:
            by_sha[sha] = key
    return by_sha


def assign_edition_page_keys(manifest: dict) -> list[dict[str, Any]]:
    """Assign edition page keys to all non-discarded leaves and recovered gaps."""
    leaves = leaves_view(manifest)
    body_leaf_nums = [
        leaf["leaf_num"]
        for leaf in leaves
        if leaf.get("kind") == "body" and isinstance(leaf.get("leaf_num"), int)
    ]
    first_body = min(body_leaf_nums) if body_leaf_nums else None
    last_body = max(body_leaf_nums) if body_leaf_nums else None

    pages = [
        _entry_from_leaf(leaf, first_body=first_body, last_body=last_body)
        for leaf in leaves
        if leaf.get("kind") != "discarded"
    ]
    pages.extend(_entry_from_gap(gap) for gap in manifest.get("gaps", []) if isinstance(gap, dict))
    pages.sort(key=_reading_order_key)

    group_counts: dict[tuple[str, int], int] = {}
    region_positions = {"front_matter": 0, "back_matter": 0}
    preceding_anchor = {"front_matter": 0, "body": 0, "back_matter": 0}

    assignments: list[dict[str, Any]] = []
    for page in pages:
        section = _section_for_page(page)
        if section is None:
            continue

        anchor = _anchor_for_page(page, section, region_positions, preceding_anchor)
        ordinal = group_counts.get((section, anchor), 0)
        group_counts[(section, anchor)] = ordinal + 1
        preceding_anchor[section] = anchor

        assignment = {
            "source": page["source"],
            "leaf_num": page.get("leaf_num"),
            "page_num": page.get("page_num"),
            "kind": page["kind"],
            "source_payload_sha256": page.get("sha256"),
            "edition_page_key": _key(section, anchor, ordinal),
        }
        if assignment["leaf_num"] is None:
            assignment.pop("leaf_num")
        assignments.append(assignment)

    return assignments


def _entry_from_leaf(
    leaf: dict[str, Any],
    *,
    first_body: int | None,
    last_body: int | None,
) -> dict[str, Any]:
    kind = _validated_kind(leaf.get("kind"))
    entry = dict(leaf)
    entry["source"] = "leaf"
    entry["kind"] = kind
    entry["_first_body_leaf"] = first_body
    entry["_last_body_leaf"] = last_body
    return entry


def _entry_from_gap(gap: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "gap",
        "kind": "body",
        "page_num": gap.get("page_num"),
        "sha256": gap.get("sha256"),
    }


def _validated_kind(value: Any) -> str:
    if not isinstance(value, str) or value not in _KIND_VALUES:
        raise ValueError(f"unknown source-manifest leaf kind: {value!r}")
    return value


def _key(section: str, anchor: int, ordinal: int) -> dict[str, int | str]:
    return {"section": section, "anchor": int(anchor), "ordinal": int(ordinal)}


def _section_for_page(page: dict[str, Any]) -> str | None:
    kind = page["kind"]
    if kind == "discarded":
        return None
    if kind in _SECTION_RANK:
        return kind
    if kind != "plate":
        raise ValueError(f"cannot map leaf kind to edition section: {kind!r}")

    leaf_num = page.get("leaf_num")
    if not isinstance(leaf_num, int):
        return "body"
    first_body = page.get("_first_body_leaf")
    last_body = page.get("_last_body_leaf")
    if isinstance(first_body, int) and leaf_num < first_body:
        return "front_matter"
    if isinstance(last_body, int) and leaf_num > last_body:
        return "back_matter"
    return "body"


def _anchor_for_page(
    page: dict[str, Any],
    section: str,
    region_positions: dict[str, int],
    preceding_anchor: dict[str, int],
) -> int:
    page_num = page.get("page_num")
    if section == "body" and isinstance(page_num, int):
        return page_num

    printed_anchor = _printed_anchor(page)
    if printed_anchor is not None:
        return printed_anchor

    if page["kind"] == "plate" and preceding_anchor[section] > 0:
        return preceding_anchor[section]

    if section in region_positions:
        region_positions[section] += 1
        return region_positions[section]

    if preceding_anchor[section] > 0:
        return preceding_anchor[section]
    raise ValueError(f"cannot assign anchor for page: {page!r}")


def _printed_anchor(page: dict[str, Any]) -> int | None:
    for field in ("printed_page", "printed_page_num", "page_label", "printed_page_label"):
        value = page.get(field)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            parsed = _roman_to_int(value)
            if parsed is not None:
                return parsed
            if value.isdecimal():
                return int(value)
    return None


def _roman_to_int(value: str) -> int | None:
    text = value.strip().lower()
    if not text or any(char not in _ROMAN_VALUES for char in text):
        return None
    total = 0
    previous = 0
    for char in reversed(text):
        current = _ROMAN_VALUES[char]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total


def _reading_order_key(page: dict[str, Any]) -> tuple[int, int, int, int]:
    kind = page["kind"]
    leaf_num = page.get("leaf_num")
    page_num = page.get("page_num")
    leaf_order = leaf_num if isinstance(leaf_num, int) else 1_000_000
    if page["source"] == "leaf":
        if kind == "front_matter":
            return (0, leaf_order, 0, leaf_order)
        if kind in ("body", "plate"):
            return (1, leaf_order, 0, leaf_order)
        if kind == "back_matter":
            return (2, leaf_order, 0, leaf_order)
    if kind == "front_matter":
        return (0, _printed_anchor(page) or leaf_order, 0, leaf_order)
    if kind in ("body", "plate"):
        if isinstance(page_num, int):
            return (1, page_num, 0, leaf_order)
        return (1, leaf_order, 1, leaf_order)
    if kind == "back_matter":
        return (2, _printed_anchor(page) or leaf_order, 0, leaf_order)
    return (3, leaf_order, 0, leaf_order)
