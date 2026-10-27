"""Focused guards for the frozen Didache technical-acceptance install route."""

from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import json
import shutil
from build.tools import preflight_didache_full_witness as identity_stage
from build.tools import stage_didache_full_witness_acceptance as acceptance_stage
from build.tools.reconstruct_candidate import _bound_callable
from ocd_kernel.reconstruction import SourceManifest
from tests.runtime_candidate_baselines import current_runtime_baseline
from tests.vendored_schema_mirrors import copy_vendored_schema_imports

import pytest

from build.tools import install_didache_full_witness_acceptance as installer
from ocd_kernel.library._common import PipelineError


def test_read_only_preflight_checks_frozen_work_without_installing() -> None:
    before = installer._files(installer.ROOT / installer.WORK_DIR)
    result = installer.preflight(installer.RECEIPT_SHA256)
    assert result == {
        "status": "ready-for-review", "installation": "not-performed",
        "work_id": "didache-prayers", "receipt_sha256": installer.RECEIPT_SHA256,
        "before_files": 3, "after_files": 21, "native_rows": 18,
        "human_verification": "not-recorded", "rights": "unresolved",
    }
    assert installer._files(installer.ROOT / installer.WORK_DIR) == before


def test_installer_rejects_any_other_receipt_pin() -> None:
    with pytest.raises(PipelineError, match="exact frozen v5 receipt pin"):
        installer.preflight("0" * 64)


def test_installer_rejects_an_extra_canonical_work_file(monkeypatch: pytest.MonkeyPatch) -> None:
    actual_files = installer._files
    canonical = (installer.ROOT / installer.WORK_DIR).resolve(strict=True)

    def changed_files(path: Path) -> dict[str, str]:
        files = actual_files(path)
        if path.resolve(strict=True) == canonical:
            return files | {"unreviewed.json": "0" * 64}
        return files

    monkeypatch.setattr(installer, "_files", changed_files)
    with pytest.raises(PipelineError, match="complete work preimage"):
        installer.preflight(installer.RECEIPT_SHA256)


SOURCE_ROOT = installer.ROOT
HISTORICAL_STAGE = installer.STAGE
HISTORICAL_SOURCE_STAGE = installer.SOURCE_STAGE
HISTORICAL_RECEIPT_SHA = installer.RECEIPT_SHA256
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/didache_prayers_oracle.source-manifest.json")
RUNTIME_SHA = "09b195546e7eb3780a59c7c56dd996cf5e1442c78bce4a4e4ec6137a96e99af3"
FROZEN_BEFORE = {'library/works/didache-prayers/forms/didache-prayers-retained-electronic/editions/didache-prayers-retained-electronic-witness/acquisitions/didache-prayers-retained-source.json': 'tests/fixtures/reconstruction-runtime/authorities/didache-full-before.acquisition.json', 'library/works/didache-prayers/state.json': 'tests/fixtures/reconstruction-runtime/authorities/didache-full-before.state.json', 'library/works/didache-prayers/work.json': 'tests/fixtures/reconstruction-runtime/authorities/didache-full-before.work.json'}


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture(scope="module")
def current_source_candidate(tmp_path_factory):
    original = json.loads((HISTORICAL_STAGE / acceptance_stage.RECEIPT).read_bytes())
    assert sha256((SOURCE_ROOT / RUNTIME_MANIFEST).read_bytes()).hexdigest() == RUNTIME_SHA
    return current_runtime_baseline(
        root=SOURCE_ROOT, original_manifest=installer.MANIFEST, runtime_manifest=RUNTIME_MANIFEST,
        retained_package=HISTORICAL_SOURCE_STAGE / "package",
        retained_sha256=original["source_candidate_sha256"],
        destination=tmp_path_factory.mktemp("didache-baseline") / "current")


@pytest.fixture(autouse=True)
def exact_before_current_source_context(tmp_path, tmp_path_factory, monkeypatch, current_source_candidate):
    baseline, candidate = current_source_candidate
    original_receipt = (HISTORICAL_STAGE / acceptance_stage.RECEIPT).read_bytes()
    assert sha256(original_receipt).hexdigest() == HISTORICAL_RECEIPT_SHA
    original = json.loads(original_receipt)
    original_source_receipt = (HISTORICAL_SOURCE_STAGE / "didache-stage-receipt.json").read_bytes()
    assert sha256(original_source_receipt).hexdigest() == original["source_stage_receipt_sha256"]
    original_identity = json.loads(original_source_receipt)
    original_source_state = installer._files(SOURCE_ROOT / installer.WORK_DIR)
    original_stage_files = installer._files(HISTORICAL_STAGE)
    original_held_files = installer._files(HISTORICAL_SOURCE_STAGE)
    root = tmp_path / "before-root"
    root.mkdir()
    for relative, expected in original_stage_files.items():
        if relative == acceptance_stage.RECEIPT.as_posix() or relative.startswith(installer.WORK_DIR.as_posix() + "/"):
            continue
        raw = (HISTORICAL_STAGE / relative).read_bytes()
        assert sha256(raw).hexdigest() == expected
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for relative, fixture in FROZEN_BEFORE.items():
        raw = (SOURCE_ROOT / fixture).read_bytes()
        assert sha256(raw).hexdigest() == original["before"][relative]
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert {installer.WORK_DIR.as_posix() + "/" + p: v for p, v in installer._files(root / installer.WORK_DIR).items()} == original["before"]
    support = {row["path"] for row in baseline.record["authorities"]}
    support.update({baseline.record["converter"]["implementation_path"], baseline.record["validator"]["implementation_path"],
                    "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/__init__.py", RUNTIME_MANIFEST.as_posix()})
    for relative in support:
        raw = (SOURCE_ROOT / relative).read_bytes()
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    copy_vendored_schema_imports(SOURCE_ROOT, root)
    parent = tmp_path_factory.mktemp("didache-stages")
    held = parent / HISTORICAL_SOURCE_STAGE.name
    stage = parent / HISTORICAL_STAGE.name
    shutil.copytree(HISTORICAL_SOURCE_STAGE, held)
    shutil.copytree(HISTORICAL_STAGE, stage)
    for home in (held / "package", stage / acceptance_stage.EVIDENCE / "inputs/package"):
        for name in candidate.member_names:
            if name == "provenance.json":
                prior_provenance = json.loads((home / name).read_bytes())
                current_provenance = json.loads(candidate.member_bytes(name))
                assert prior_provenance["source_manifest_sha256"] == original_identity["source_manifest_sha256"]
                assert current_provenance["source_manifest_sha256"] == baseline.sha256
                restored_provenance = deepcopy(current_provenance)
                restored_provenance["source_manifest_sha256"] = prior_provenance["source_manifest_sha256"]
                assert restored_provenance == prior_provenance
            elif name != "manifest.json":
                assert (home / name).read_bytes() == candidate.member_bytes(name), name
            (home / name).write_bytes(candidate.member_bytes(name))
    validation_raw = (candidate.path.parent / "validation.json").read_bytes()
    (held / "validation.json").write_bytes(validation_raw)
    (stage / acceptance_stage.EVIDENCE / "inputs/validation.json").write_bytes(validation_raw)
    identity = deepcopy(original_identity)
    identity.update(candidate_sha256=candidate.sha256, source_manifest_sha256=baseline.sha256,
                    validation_sha256=sha256(validation_raw).hexdigest())
    restored = deepcopy(identity)
    for key in ("candidate_sha256", "source_manifest_sha256", "validation_sha256"):
        restored[key] = original_identity[key]
    assert restored == original_identity
    identity_raw = _canonical(identity)
    (held / "didache-stage-receipt.json").write_bytes(identity_raw)
    current = deepcopy(original)
    current.update(source_candidate_sha256=candidate.sha256, source_stage_receipt_sha256=sha256(identity_raw).hexdigest(),
                   after={installer.WORK_DIR.as_posix() + "/" + p: v for p, v in installer._files(stage / installer.WORK_DIR).items()})
    changed = {p for p in current["after"] if current["after"][p] != original["after"][p]}
    assert set(current["after"]) == set(original["after"])
    assert changed <= {(acceptance_stage.EVIDENCE / "inputs/package/manifest.json").as_posix(),
                       (acceptance_stage.EVIDENCE / "inputs/package/provenance.json").as_posix(),
                       (acceptance_stage.EVIDENCE / "inputs/validation.json").as_posix()}
    restored = deepcopy(current)
    for key in ("source_candidate_sha256", "source_stage_receipt_sha256", "after"):
        restored[key] = original[key]
    assert restored == original
    current_raw = _canonical(current)
    (stage / acceptance_stage.RECEIPT).write_bytes(current_raw)
    for module in (identity_stage, acceptance_stage, installer):
        monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(identity_stage, "MANIFEST", RUNTIME_MANIFEST)
    monkeypatch.setattr(identity_stage, "STAGE_PARENT", parent)
    monkeypatch.setattr(acceptance_stage, "PARENT", parent)
    monkeypatch.setattr(acceptance_stage, "SOURCE_STAGE", held)
    monkeypatch.setattr(acceptance_stage, "SOURCE_RECEIPT_SHA256", sha256(identity_raw).hexdigest())
    monkeypatch.setattr(installer, "STAGE", stage)
    monkeypatch.setattr(installer, "SOURCE_STAGE", held)
    monkeypatch.setattr(installer, "RECEIPT_SHA256", sha256(current_raw).hexdigest())
    monkeypatch.setattr(installer, "MANIFEST", RUNTIME_MANIFEST)
    private_manifest = SourceManifest.load(root / RUNTIME_MANIFEST, repository_root=root)
    monkeypatch.setattr(installer, "_oracle", _bound_callable(root, private_manifest.record["validator"], role="validator"))
    yield
    assert installer._files(SOURCE_ROOT / installer.WORK_DIR) == original_source_state
    assert installer._files(HISTORICAL_STAGE) == original_stage_files
    assert installer._files(HISTORICAL_SOURCE_STAGE) == original_held_files
    assert (HISTORICAL_STAGE / acceptance_stage.RECEIPT).read_bytes() == original_receipt
    assert (HISTORICAL_SOURCE_STAGE / "didache-stage-receipt.json").read_bytes() == original_source_receipt
