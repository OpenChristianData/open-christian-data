from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema

from build.tools.reconcile_stale_gaps import remove_stale_gaps

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json"


def _manifest() -> dict:
    return {
        "ia_item_id": "test",
        "ia_derivative_type": "jp2",
        "volume": 99,
        "created_at": "2026-06-19T00:00:00+00:00",
        "page_count": 3,
        "leaves": [
            {"leaf_num": 0, "page_num": 1, "kind": "body", "image_state": "present"},
            {"leaf_num": 1, "page_num": 2, "kind": "body", "image_state": "present"},
            {"leaf_num": 2, "page_num": 3, "kind": "body", "image_state": "present"},
        ],
        "gaps": [
            {"page_num": 2, "status": "resolved", "investigation_note": "stale recovered gap"},
            {"page_num": 7, "status": "unresolved", "investigation_note": "real missing page"},
        ],
        "manifest_warnings": [],
    }


def test_target_entry_is_removed_and_count_decrements():
    manifest = _manifest()

    removed = remove_stale_gaps(manifest, {2})

    assert removed == [2]
    assert len(manifest["gaps"]) == 1
    assert [gap["page_num"] for gap in manifest["gaps"]] == [7]


def test_non_target_entry_is_preserved():
    manifest = _manifest()
    non_target = copy.deepcopy(manifest["gaps"][1])

    remove_stale_gaps(manifest, {2})

    assert manifest["gaps"] == [non_target]


def test_idempotency_second_call_leaves_manifest_identical():
    manifest = _manifest()
    assert remove_stale_gaps(manifest, {2}) == [2]
    after_first = copy.deepcopy(manifest)

    assert remove_stale_gaps(manifest, {2}) == []
    assert manifest == after_first


def test_after_removal_manifest_validates_against_source_manifest_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    manifest = _manifest()

    remove_stale_gaps(manifest, {2})

    jsonschema.validate(instance=manifest, schema=schema)
