from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from build.tools.reclassify_out_of_range_gaps import (
    OUT_OF_RANGE,
    coverage_pages_parsed,
    reclassify_gaps,
    run,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json"


def _manifest() -> dict:
    return {
        "page_count": 500,
        "gaps": [
            {"page_num": 96, "status": "resolved", "investigation_note": "recovered"},
            {"page_num": 209, "status": "permanently_missing", "investigation_note": "image absent, text exists"},
            {"page_num": 480, "status": "unresolved", "investigation_note": "in-range real hole"},
            {"page_num": 501, "status": "unresolved", "investigation_note": "no leaf mapping or fetched page image found for requested page"},
            {"page_num": 531, "status": "unresolved", "investigation_note": "no leaf mapping or fetched page image found for requested page"},
        ],
    }


def test_only_out_of_range_unresolved_reclassified():
    m = _manifest()
    changed = reclassify_gaps(m, true_page_count=500)
    assert changed == [501, 531]
    by_page = {g["page_num"]: g for g in m["gaps"]}
    assert by_page[501]["status"] == OUT_OF_RANGE
    assert by_page[531]["status"] == OUT_OF_RANGE
    # Real records are never touched.
    assert by_page[96]["status"] == "resolved"
    assert by_page[209]["status"] == "permanently_missing"
    assert by_page[480]["status"] == "unresolved"  # in-range unresolved = a real hole, kept


def test_note_preserves_original_audit_trail():
    m = _manifest()
    reclassify_gaps(m, true_page_count=500)
    note = {g["page_num"]: g["investigation_note"] for g in m["gaps"]}[501]
    assert "out_of_range" in note
    assert "no leaf mapping" in note  # original preserved


def test_idempotent_second_run():
    m = _manifest()
    assert reclassify_gaps(m, 500) == [501, 531]
    assert reclassify_gaps(m, 500) == []  # nothing left to reclassify


def test_page_count_preserved():
    m = _manifest()
    before = m["page_count"]
    reclassify_gaps(m, 500)
    assert m["page_count"] == before


def test_reclassified_manifest_is_schema_valid():
    # A minimal v4 manifest carrying a reclassified gap must validate.
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        schema = json.load(fh)
    manifest = {
        "ia_item_id": "test", "ia_derivative_type": "jp2", "volume": 1,
        "created_at": "2026-06-19T00:00:00+00:00", "page_count": 2,
        "leaves": [
            {"leaf_num": 0, "page_num": 1, "kind": "body", "image_state": "present"},
            {"leaf_num": 1, "page_num": 2, "kind": "body", "image_state": "present"},
        ],
        "gaps": [{"page_num": 3, "status": "unresolved", "investigation_note": "no leaf mapping"}],
        "manifest_warnings": [],
    }
    reclassify_gaps(manifest, true_page_count=2)
    assert manifest["gaps"][0]["status"] == OUT_OF_RANGE
    jsonschema.validate(instance=manifest, schema=schema)  # out_of_range must be an allowed enum value


@pytest.mark.skipif(
    not (REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_03.manifest.json").exists(),
    reason="raw/ NSH manifests not present",
)
def test_applied_corpus_is_idempotent_with_196_out_of_range():
    # The one-time apply has run: the corpus carries 196 out_of_range gaps and a
    # dry run reclassifies nothing more (idempotent -- TEST-05). Asserting the
    # post-apply count, not the pre-apply delta, keeps this stable across re-runs.
    report = run(REPO_ROOT, apply=False)
    assert report["apply"] is False
    assert report["total_reclassified"] == 0
    assert coverage_pages_parsed(REPO_ROOT, 3) == 500
    nsh = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
    total_oor = 0
    for volume in range(1, 14):
        path = nsh / f"vol_{volume:02d}.manifest.json"
        if path.exists():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            total_oor += sum(1 for g in manifest.get("gaps", []) if g.get("status") == OUT_OF_RANGE)
    assert total_oor == 196
