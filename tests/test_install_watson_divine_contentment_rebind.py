"""Guarded Watson Divine Contentment install preflight and rollback on an isolated mirror."""

import json
import shutil
from pathlib import Path

import pytest

from build.tools import install_watson_divine_contentment_rebind as installer
from build.tools import prepare_watson_divine_contentment_rebind as route
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.watson_public_runtime_fixture import current_installed_acceptance


def _mirror(tmp_path_factory, monkeypatch):
    canonical = route.ROOT
    manifest = json.loads((canonical / installer.DEFAULT_MANIFEST).read_text(encoding="utf-8"))
    original_manifest = json.loads(json.dumps(manifest))
    original_stage = Path(manifest["stage_root"])
    original_stage_files = _files(original_stage)
    context = tmp_path_factory.mktemp("w")
    source_root = context / "c"
    # Reuse the real current producer/oracle proof without restoring old global scratch paths.
    current_installed_acceptance(route, source_root, monkeypatch)
    stage = context / "s"
    shutil.copytree(_io_path(original_stage), _io_path(stage))
    assert _files(stage) == original_stage_files
    additions = {}
    for relative, digest in _files(source_root).items():
        path = Path(relative)
        target = _io_path(stage / path)
        if relative in original_stage_files:
            assert installer._sha(target) == original_stage_files[relative]
            continue
        content = _io_path(source_root / path).read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        assert installer._sha(target) == digest
        additions[relative] = digest
    assert _files(stage) == original_stage_files | additions
    # The real current runtime proof binds the adopted creator scopes. Keep
    # that exact work generation in this private install context; retain the
    # complete historical stage and restore the original install-record pin.
    work_relative = (route.WORK / "work.json").as_posix()
    historical_work_raw = _io_path(original_stage / work_relative).read_bytes()
    assert installer._sha(original_stage / work_relative) == original_manifest["canonical_before"]["work_sha256"]
    current_work_raw = _io_path(source_root / work_relative).read_bytes()
    assert current_work_raw == _io_path(canonical / work_relative).read_bytes()
    runtime_manifest = source_root / "sources/structured-text" / route.WORK.name / "runtime-proof-20261025-main.source-manifest.json"
    work_authorities = [item for item in json.loads(runtime_manifest.read_bytes())["authorities"]
                        if item["name"] == "work"]
    assert len(work_authorities) == 1
    work_authority = work_authorities[0]
    assert work_authority["path"] == work_relative
    assert work_authority["bytes"] == len(current_work_raw)
    assert work_authority["sha256"] == installer._sha(source_root / work_relative)
    historical_work = json.loads(historical_work_raw)
    current_work = json.loads(current_work_raw)
    assert all("scope" not in creator for creator in historical_work["creators"])
    restored_work = json.loads(current_work_raw)
    for creator in restored_work["creators"]:
        assert creator.pop("scope") == {"kind": "work", "id": route.WORK.name}
    assert restored_work == historical_work
    _io_path(stage / work_relative).write_bytes(current_work_raw)
    manifest["canonical_before"]["work_sha256"] = work_authority["sha256"]
    assert _files(stage) == original_stage_files | additions | {work_relative: work_authority["sha256"]}
    assert installer._evidence_hashes(stage) == manifest["stage"]["evidence_files"]
    for name, relative in installer.CONTROL_PATHS.items():
        expected = (manifest["stage"]["acceptance_sha256"] if name == "acceptance_sha256"
                    else manifest["canonical_before"][name])
        assert installer._sha(stage / relative) == expected
    assert _files(original_stage) == original_stage_files
    manifest["stage_root"] = stage.resolve().as_posix()
    historical_path = route.EVIDENCE / "inputs/historical-acceptance.json"
    historical_acceptance = (stage / historical_path).read_bytes()
    historical_sha256 = installer._sha(stage / historical_path)
    assert historical_sha256 == manifest["stage"]["evidence_files"][historical_path.as_posix()]
    assert historical_sha256 == manifest["canonical_before"]["acceptance_sha256"]
    canonical_acceptance_sha256 = installer._sha(canonical / route.EDITION / "acceptance.json")
    mirror = tmp_path_factory.mktemp("w") / "r"
    shutil.copytree(stage, mirror)
    installer._remove_owned(
        mirror / route.EVIDENCE,
        parent=mirror / route.WORK / "integration",
        expected=manifest["stage"]["evidence_files"],
    )
    acceptance = mirror / route.EDITION / "acceptance.json"
    acceptance.write_bytes(historical_acceptance)
    manifest["canonical_root"] = mirror.resolve().as_posix()
    restored_manifest = json.loads(json.dumps(manifest))
    for key in ("canonical_root", "stage_root"):
        restored_manifest[key] = original_manifest[key]
    restored_manifest["canonical_before"]["work_sha256"] = original_manifest["canonical_before"]["work_sha256"]
    assert restored_manifest == original_manifest
    manifest_path = mirror.parent / "install-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(route, "ROOT", mirror)
    # Prove the genuine positive baseline before any caller injects a
    # post-swap validation failure, partial-copy failure, or stale acceptance.
    checked, checked_stage = installer.preflight(manifest_path)
    assert checked == manifest and checked_stage == stage
    return canonical, mirror, manifest_path, manifest, canonical_acceptance_sha256


def _protected_hashes(root):
    return {
        name: installer._sha(root / relative)
        for name, relative in installer.CONTROL_PATHS.items()
        if name != "acceptance_sha256"
    }


def test_guarded_install_preflight_and_mirror_apply(tmp_path_factory, monkeypatch):
    canonical, mirror, manifest_path, manifest, canonical_acceptance_sha256 = _mirror(tmp_path_factory, monkeypatch)
    before = _protected_hashes(mirror)
    checked, stage = installer.preflight(manifest_path)
    assert stage == Path(manifest["stage_root"])
    assert checked["canonical_before"]["acceptance_sha256"] == installer._sha(
        mirror / route.EDITION / "acceptance.json"
    )
    result = installer.install(manifest_path)
    assert result["status"] == "applied"
    assert installer._sha(mirror / route.EDITION / "acceptance.json") == (
        manifest["stage"]["acceptance_sha256"]
    )
    assert installer._evidence_hashes(mirror) == manifest["stage"]["evidence_files"]
    assert _protected_hashes(mirror) == before
    assert installer._sha(canonical / route.EDITION / "acceptance.json") == (
        canonical_acceptance_sha256
    )


def test_guarded_install_rolls_back_after_validation_failure(tmp_path_factory, monkeypatch):
    canonical, mirror, manifest_path, manifest, canonical_acceptance_sha256 = _mirror(tmp_path_factory, monkeypatch)
    before = _protected_hashes(mirror)
    old_acceptance = (mirror / route.EDITION / "acceptance.json").read_bytes()
    actual_validate = installer.validate_acceptance

    def fail_after_swap(path, *, root):
        if Path(root).resolve() == mirror.resolve():
            raise PipelineError("injected post-swap validation failure")
        return actual_validate(path, root=root)

    monkeypatch.setattr(installer, "validate_acceptance", fail_after_swap)
    with pytest.raises(PipelineError, match="injected post-swap validation failure"):
        installer.install(manifest_path)
    assert (mirror / route.EDITION / "acceptance.json").read_bytes() == old_acceptance
    assert not (mirror / route.EVIDENCE).exists()
    assert _protected_hashes(mirror) == before
    assert not list((mirror / route.EDITION).glob(".acceptance-watson-*.json"))
    assert installer._sha(canonical / route.EDITION / "acceptance.json") == (
        canonical_acceptance_sha256
    )


def test_guarded_install_cleans_verified_partial_copy(tmp_path_factory, monkeypatch):
    canonical, mirror, manifest_path, manifest, canonical_acceptance_sha256 = _mirror(tmp_path_factory, monkeypatch)
    before = _protected_hashes(mirror)
    old_acceptance = (mirror / route.EDITION / "acceptance.json").read_bytes()

    def partial_copy(source, destination):
        destination.mkdir()
        shutil.copy2(source / "validation.json", destination / "validation.json")
        raise OSError("injected mid-copy failure")

    monkeypatch.setattr(installer.shutil, "copytree", partial_copy)
    with pytest.raises(OSError, match="injected mid-copy failure"):
        installer.install(manifest_path)
    assert (mirror / route.EDITION / "acceptance.json").read_bytes() == old_acceptance
    assert not (mirror / route.EVIDENCE).exists()
    assert not list((mirror / route.WORK / "integration").glob(".ccel-thml-closure-rebind-v2-*"))
    assert _protected_hashes(mirror) == before
    assert installer._sha(canonical / route.EDITION / "acceptance.json") == (
        canonical_acceptance_sha256
    )


def test_original_manifest_rejects_current_acceptance_generation(tmp_path_factory, monkeypatch):
    canonical, mirror, manifest_path, manifest, canonical_acceptance_sha256 = _mirror(
        tmp_path_factory, monkeypatch
    )
    current_acceptance = (canonical / route.EDITION / "acceptance.json").read_bytes()
    assert canonical_acceptance_sha256 != manifest["canonical_before"]["acceptance_sha256"]
    acceptance = mirror / route.EDITION / "acceptance.json"
    acceptance.write_bytes(current_acceptance)
    before = _protected_hashes(mirror)
    with pytest.raises(PipelineError, match="Watson canonical before-hash differs: acceptance_sha256"):
        installer.preflight(manifest_path)
    assert acceptance.read_bytes() == current_acceptance
    assert _protected_hashes(mirror) == before
    assert not (mirror / route.EVIDENCE).exists()
    assert installer._sha(canonical / route.EDITION / "acceptance.json") == canonical_acceptance_sha256
