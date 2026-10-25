"""Work-local producer for Watson's retained The Lord's Prayer ThML envelope.

The shared selected-ThML converter remains unchanged. This adapter binds its
callable to this ticket's exact source selection and unresolved-identity
profile so the route can be tested without creating a shared LIB-056 producer.
"""

from __future__ import annotations

import json

from build.tei import selected_thml as _selected_thml


WORK_ID = "watson-lords-prayer"
SOURCE_MEMBER = {
    "path": "raw/ccel/watson/prayer.xml",
    "bytes": 1376060,
    "sha256": "9f14813ac77f4a44ce08b63ec6343ec8f59f006df7f80f11fcf87926730468ca",
}
EXPECTED_NATIVE_IDS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x")
EXPECTED_FEATURE_COUNT = 6723


def _read_json(path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _verify_route_profile(manifest) -> dict:
    if manifest.record.get("work_id") != WORK_ID:
        raise ValueError("Watson The Lord's Prayer producer received another work")
    profile = _read_json(manifest.authority_path("profile"), "route profile")
    if profile.get("source_member") != SOURCE_MEMBER:
        raise ValueError("Watson The Lord's Prayer source member differs from profile")
    if profile.get("work_id") != WORK_ID:
        raise ValueError("Watson The Lord's Prayer profile work differs")
    selection = _read_json(manifest.authority_path("acquisition"), "acquisition")
    units = selection.get("source_selection", {}).get("units")
    if not isinstance(units, list) or tuple(row.get("native_id") for row in units) != EXPECTED_NATIVE_IDS:
        raise ValueError("Watson The Lord's Prayer source selection differs")
    if profile.get("feature_census", {}).get("selected_element_count") != EXPECTED_FEATURE_COUNT:
        raise ValueError("Watson The Lord's Prayer feature census differs")
    return profile


def _convert(manifest):
    """Produce the five non-manifest source-bound candidate members in memory."""

    manifest.verify()
    _verify_route_profile(manifest)
    produced = _selected_thml._convert(manifest)
    if set(produced) != {
        "content.tei.xml",
        "source-accountability.json",
        "provenance.json",
        "unresolved.jsonl",
        "README.source.md",
    }:
        raise ValueError("Watson The Lord's Prayer producer returned unexpected members")
    return produced


_convert.converter_id = "ocd-watson-lords-prayer-selected-thml-route"
_convert.converter_version = "1"
