"""Evidence-bound checks for the eight large retained source cohorts."""

from pathlib import Path

import pytest

from build.tools.prepare_large_source_sets import SOURCES, binding
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SUPPORT = {"adam-clarke": 2, "catholic-encyclopedia-vol01": 378, "church-fathers-quotations": 335, "jamieson-fausset-brown": 2, "john-gill": 2, "keil-delitzsch": 2, "matthew-henry-complete": 2, "spurgeon-mtp": 0}
EXPECTED_COUNTS = {
    "adam-clarke": 856,
    "catholic-encyclopedia-vol01": 12058,
    "church-fathers-quotations": 58675,
    "jamieson-fausset-brown": 1189,
    "john-gill": 1191,
    "keil-delitzsch": 911,
    "matthew-henry-complete": 1169,
    "spurgeon-mtp": 3550,
}


def test_each_manifest_binds_all_explicit_nonpackage_primary_members():
    assert set(SOURCES) == set(EXPECTED_COUNTS)
    for work_id, count in EXPECTED_COUNTS.items():
        info, members = binding(ROOT, work_id, verify_files=False)
        assert info["manifest_primary_count"] == count
        assert info["source_member_count"] == len(members)
        assert info["support_member_count"] == len(info["support_members"]) == EXPECTED_SUPPORT[work_id]
        assert len(members) + len(info["support_members"]) == count
        assert len({member["path"] for member in members + info["support_members"]}) == count
        assert all(not member["path"].lower().endswith(".zip") for member in members + info["support_members"])
        assert info["member_order_sha256"]


def test_partial_and_collection_scope_is_explicit():
    for work_id, fragment in (
        ("catholic-encyclopedia-vol01", "Volume I boundary"),
        ("matthew-henry-complete", "Song of Solomon"),
        ("spurgeon-mtp", "13 numbered sermon slots"),
        ("church-fathers-quotations", "multiple historical authors"),
    ):
        info, _ = binding(ROOT, work_id, verify_files=False)
        assert any(fragment in warning for warning in info["scope_warnings"])


def test_manifest_primary_member_must_be_in_pinned_retained_root(tmp_path, monkeypatch):
    import json

    root = tmp_path / "repo"
    manifest_rel = "sources/commentaries/adam-clarke/adam-clarke.source-manifest.json"
    manifest_path = root / manifest_rel
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"source_id": "witness", "authorities": [
        {"path": "raw/helloao_local/api/c/other/book.json", "role": "primary-source", "bytes": 1, "sha256": "0" * 64}
    ]}), encoding="utf-8")
    config_rel = "sources/commentaries/adam-clarke/config.json"
    (root / config_rel).write_text('{"resource_id":"adam-clarke"}', encoding="utf-8")
    with pytest.raises(PipelineError, match="invalid/duplicate non-source member"):
        binding(root, "adam-clarke", verify_files=False)
