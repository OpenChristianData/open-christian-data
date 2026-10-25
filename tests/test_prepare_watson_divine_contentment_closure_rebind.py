"""The current Watson closure is a new proof over unchanged reviewed text."""

import hashlib
import json

import pytest

from build.tools import prepare_watson_divine_contentment_closure_rebind as rebind
from build.tools.reconstruct_candidate import run as reconstruct_candidate
from tests.watson_rebind_runtime_fixture import current_contentment_closure_context


def test_versioned_manifest_changes_only_reviewed_shared_dependencies(tmp_path, monkeypatch):
    current_contentment_closure_context(rebind, tmp_path / "r", monkeypatch)
    manifest = rebind.prepare_manifest(rebind.ROOT)
    historical = json.loads((rebind.ROOT / rebind.HISTORICAL_MANIFEST).read_text(encoding="utf-8"))
    current = json.loads((rebind.ROOT / rebind.CURRENT_MANIFEST).read_text(encoding="utf-8"))
    assert hashlib.sha256((rebind.ROOT / rebind.HISTORICAL_MANIFEST).read_bytes()).hexdigest() == rebind.HISTORICAL_MANIFEST_SHA
    assert manifest.sha256 == hashlib.sha256((rebind.ROOT / rebind.CURRENT_MANIFEST).read_bytes()).hexdigest()
    assert current["validator"]["import_closure_sha256"] == rebind.CURRENT_CLOSURE_SHA
    current["validator"]["import_closure_sha256"] = historical["validator"]["import_closure_sha256"]
    for old, new in zip(historical["authorities"], current["authorities"], strict=True):
        assert old["name"] == new["name"]
        if old["name"] in rebind.CHANGED_AUTHORITIES:
            assert (new["bytes"], new["sha256"]) == rebind.CHANGED_AUTHORITIES[old["name"]]
            new["bytes"], new["sha256"] = old["bytes"], old["sha256"]
    assert current == historical


def test_current_candidate_replays_oracle_and_reproduces_installed_master(tmp_path, monkeypatch):
    current_contentment_closure_context(rebind, tmp_path / "r", monkeypatch)
    rebind.prepare_manifest(rebind.ROOT)
    candidate = tmp_path / "watson-current-candidate"
    reconstruct_candidate(
        manifest=rebind.CURRENT_MANIFEST.as_posix(),
        destination=str(candidate),
        repository_root=str(rebind.ROOT),
    )
    from build.tools.reconstruct_candidate import _bound_callable
    from ocd_kernel.reconstruction import SourceManifest
    manifest = SourceManifest.load(rebind.ROOT / rebind.CURRENT_MANIFEST, repository_root=rebind.ROOT)
    oracle = _bound_callable(rebind.ROOT, manifest.record["validator"], role="validator")
    monkeypatch.setattr(rebind, "_oracle", oracle)
    receipt = rebind.audit_candidate(candidate, root=rebind.ROOT)
    assert receipt["status"] == "prepared-for-coordinated-acceptance"
    assert receipt["reviewed_tei_bytes_identical"] is True
    assert receipt["installed_master_reproduced_from_current_candidate"] is True
    assert receipt["installed_master_sha256"] == rebind.MASTER_SHA


def test_historical_recipe_rejects_changed_shared_closure():
    with pytest.raises(ValueError, match="Watson oracle import closure changed since review"):
        rebind.prepare_manifest(rebind.ROOT)


def test_private_historical_work_rejects_unrecognized_metadata_drift(tmp_path, monkeypatch):
    root = current_contentment_closure_context(rebind, tmp_path / "r", monkeypatch)
    # The production SourceManifest reader verifies the exact held work bytes.
    rebind.prepare_manifest(root)
    work = root / "library/works/watson-divine-contentment/work.json"
    original = work.read_bytes()
    try:
        work.write_bytes(original + b"\n")
        with pytest.raises(ValueError, match="work authority bytes drifted"):
            rebind.prepare_manifest(root)
    finally:
        work.write_bytes(original)
