"""Focused proof for Fell's exact source, native stage, and rollback guard."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from build.tei.fell_a41072_oracle import _oracle
from build.tools import install_fell_a41072_acceptance as installer
from build.tools.install_fell_a41072_acceptance import (
    FIXTURE_MARKER, ROOT, WORK, install, preflight,
)
from build.tools.stage_fell_a41072_acceptance import CANDIDATE, MANIFEST
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def test_frozen_stage_read_only_preflight() -> None:
    frozen = json.loads(_io_path(installer.RECEIPT).read_bytes())
    before = _files(ROOT / WORK)
    after = _files(installer.STAGE / WORK)
    if Path(frozen["canonical_root"]).resolve(strict=True) != ROOT.resolve(strict=True):
        with pytest.raises(PipelineError, match="Fell stage receipt contract or pins differ"):
            preflight()
        assert _files(ROOT / WORK) == before
        assert _files(installer.STAGE / WORK) == after
        return
    if before != frozen["before"] or after != frozen["after"]:
        with pytest.raises(PipelineError, match="complete-generation receipt is stale"):
            preflight()
        assert _files(ROOT / WORK) == before
        assert _files(installer.STAGE / WORK) == after
        return
    record, root, stage, fixture = preflight()
    assert root == ROOT.resolve()
    assert not fixture
    assert record["projection_rows"] == 3
    assert record["source_sha256"] == "6050d2fee9b03d63ec4cf52d137ea025a2404e09ff736f550d6b8d97d4316379"
    assert len(_files(stage / WORK)) == 21
    assert _files(ROOT / WORK) == record["before"]


@pytest.fixture
def historical_install_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    receipt_bytes = _io_path(installer.RECEIPT).read_bytes()
    assert sha256(receipt_bytes).hexdigest() == "baa76a84f1c7ae7c43ad7f2f3f04f01a9ab2be0c82a002f0e3df01b70cd05a93"
    record = json.loads(receipt_bytes)
    historical_stage = installer.STAGE
    assert _files(historical_stage / WORK) == record["after"]
    root, stage = tmp_path / "repo", tmp_path / "stage"
    root.mkdir()
    stage.mkdir()
    (root / FIXTURE_MARKER).write_text("test fixture\n", encoding="utf-8")
    for relative, expected_sha256 in _files(historical_stage).items():
        if relative == installer.RECEIPT.name:
            continue
        payload = _io_path(historical_stage / relative).read_bytes()
        assert sha256(payload).hexdigest() == expected_sha256
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        if not relative.startswith(WORK.as_posix() + "/"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    for relative, expected_sha256 in record["before"].items():
        source = (
            ROOT / "tests/fixtures/reconstruction-runtime/authorities" / ("fell-a41072." + relative)
            if relative in {"work.json", "state.json"}
            else historical_stage / WORK / relative
        )
        payload = _io_path(source).read_bytes()
        assert sha256(payload).hexdigest() == expected_sha256
        target = root / WORK / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    assert _files(root / WORK) == record["before"]
    assert _files(stage / WORK) == record["after"]
    record.update(canonical_root=str(root), stage_root=str(stage))
    receipt = stage / installer.RECEIPT.name
    receipt.write_bytes(_canonical(record))
    # Rebind only this test's complete historical mirror; production pins stay frozen.
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "STAGE", stage)
    monkeypatch.setattr(installer, "RECEIPT", receipt)
    monkeypatch.setattr(installer, "RECEIPT_SHA", sha256(receipt.read_bytes()).hexdigest())
    try:
        yield record, root, stage
    finally:
        for directory in (root, stage):
            if directory.exists():
                shutil.rmtree(directory)


def test_isolated_historical_preflight_checks_exact_complete_generation(historical_install_fixture) -> None:
    expected, root, stage = historical_install_fixture
    record, checked_root, checked_stage, fixture = preflight()
    assert record == expected
    assert checked_root == root and checked_stage == stage and not fixture
    assert _files(root / WORK) == record["before"]
    assert _files(stage / WORK) == record["after"]


def test_source_byte_mutation_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, historical_install_fixture) -> None:
    _, historical_root, _ = historical_install_fixture
    manifest = SourceManifest.load(historical_root / MANIFEST, repository_root=historical_root)
    package = CandidatePackage.load(_io_path(CANDIDATE))
    original_authority = SourceManifest.authority_path
    source = bytearray(original_authority(manifest, "retained-tei-p5").read_bytes())
    position = source.index(b"Womens")
    source[position] = ord("X")
    mutant = tmp_path / "mutant.xml"
    mutant.write_bytes(source)

    def changed_authority(self: SourceManifest, name: str) -> Path:
        return mutant if name == "retained-tei-p5" else original_authority(self, name)

    monkeypatch.setattr(SourceManifest, "authority_path", changed_authority)
    findings = _oracle(manifest, package)["findings"]
    assert any("source byte binding failed" in finding for finding in findings)
    assert any("not byte-identical" in finding for finding in findings)


def test_resealed_candidate_text_mutation_is_rejected(tmp_path: Path, historical_install_fixture) -> None:
    _, historical_root, _ = historical_install_fixture
    manifest = SourceManifest.load(historical_root / MANIFEST, repository_root=historical_root)
    package = CandidatePackage.load(_io_path(CANDIDATE))
    clone = tmp_path / "package"
    clone.mkdir()
    for name in package.member_names:
        (clone / name).write_bytes(package.member_bytes(name))
    content = package.member_bytes("content.tei.xml").replace(b"Womens", b"Xomens", 1)
    (clone / "content.tei.xml").write_bytes(content)
    manifest_json = json.loads((CANDIDATE / "manifest.json").read_bytes())
    member = next(item for item in manifest_json["members"] if item["name"] == "content.tei.xml")
    member.update(bytes=len(content), sha256=sha256(content).hexdigest())
    (clone / "manifest.json").write_bytes(_canonical(manifest_json))
    mutant = CandidatePackage.load(clone)
    assert any("not byte-identical" in finding for finding in _oracle(manifest, mutant)["findings"])


@pytest.mark.parametrize("failpoint", ["after-copy", "after-old-rename", "after-new-rename", "after-validation"])
def test_guarded_install_rolls_back_marked_fixture(historical_install_fixture, failpoint: str) -> None:
    _, fixture_root, _ = historical_install_fixture
    target = fixture_root / WORK
    before = _files(target)

    def fail(phase: str) -> None:
        if phase == failpoint:
            raise RuntimeError(f"injected {phase}")

    with pytest.raises(RuntimeError, match="injected"):
        install(fail_at=fail)
    assert _files(target) == before
