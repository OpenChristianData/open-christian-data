"""The Gregory NPNF2-05 stage binds the frozen fourteen-work candidate receipt."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from build.tools import preflight_npnf205_work_acceptance as guard
from tests.npnf_four_install_fixture import (
    four_work_install_fixture, current_npnf_generation_is_preserved, current_generation_receipt,
)
from build.tools import stage_npnf205_work_acceptance as stager

from build.tools.preflight_npnf205_work_acceptance import preflight
from build.tools.install_npnf205_work_acceptance import install
from build.tools.stage_npnf205_work_acceptance import prepare
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


WORK_ID = "gregory-of-nyssa-answer-to-eunomius-second-book"
ROOT = Path(__file__).resolve().parents[1]
FROZEN = Path(r"D:\Library\Open Christian Data\candidate-reviews\n205-10-20260927")


def test_gregory_stage_reproduces_and_preflights(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path_factory.mktemp("n205")
    acquired, _, current, batch_sha = four_work_install_fixture(ROOT, root / "context", WORK_ID)
    for module in (stager, guard):
        monkeypatch.setattr(module, "BATCH", Path(current["package_receipt"]))
        monkeypatch.setattr(module, "BATCH_SHA", batch_sha)
    monkeypatch.setattr(stager, "ROOT", acquired)
    stage, receipt = root / "s", root / "r.json"
    real_run = stager.subprocess.run
    expected_argv = [sys.executable, "-m", "build.tools.reconstruct_candidate",
        "--manifest", current["manifest_path"],
        "--destination", str(stage.parent / f"{stage.name}-candidate"),
        "--repository-root", str(stage)]
    calls = []

    def current_tool_run(argv, **kwargs):
        assert argv == expected_argv
        assert kwargs["cwd"] == acquired
        calls.append(tuple(argv))
        return real_run(argv, **dict(kwargs, cwd=ROOT))

    # The partial acquired mirror owns source and writes; the frozen repository
    # supplies the real current CLI and kernel imports.
    monkeypatch.setattr(stager, "subprocess", SimpleNamespace(run=current_tool_run))
    result = prepare(WORK_ID, stage, receipt)
    assert calls == [tuple(expected_argv)]
    assert result["package_receipt"] == stager.BATCH.as_posix()
    assert result["package_receipt_sha256"] == stager.BATCH_SHA
    assert result["before"] != result["after"]
    assert preflight(receipt) == {
        "status": "ready-for-review", "work_id": WORK_ID,
        "before_files": 3, "after_files": 28, "projection_rows": 1,
        "installation": "not-performed",
    }

    changed = json.loads(receipt.read_text(encoding="utf-8"))
    changed["package_receipt_sha256"] = "0" * 64
    receipt.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(PipelineError, match="candidate receipt changed"):
        preflight(receipt)


def test_installer_requires_exact_pin_and_rolls_back_fixture(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    frozen_receipt = FROZEN / "w01.json"
    with pytest.raises(PipelineError, match="exact reviewed stage receipt hash changed"):
        install(frozen_receipt, expected_receipt_sha256="0" * 64)

    fixture = tmp_path_factory.mktemp("n205install")
    root, receipt, record, batch_sha = four_work_install_fixture(ROOT, fixture, WORK_ID)
    monkeypatch.setattr(guard, "BATCH", Path(record["package_receipt"]))
    monkeypatch.setattr(guard, "BATCH_SHA", batch_sha)
    work = Path("library/works") / WORK_ID
    assert preflight(receipt)["status"] == "ready-for-review"
    before = _files(root / work)
    manifest, profile = root / record["manifest_path"], root / record["profile_path"]
    before_manifest = _io_path(manifest).read_bytes()
    before_profile = _io_path(profile).read_bytes()
    pin = sha256(receipt.read_bytes()).hexdigest()

    def fail_after_manifest(phase: str) -> None:
        if phase == "after-source-manifest.json-swap":
            raise RuntimeError("injected manifest-swap failure")

    with pytest.raises(RuntimeError, match="injected manifest-swap failure"):
        install(receipt, expected_receipt_sha256=pin, fail_at=fail_after_manifest,
                operation_prefix="npnf205-fixture")
    assert _files(root / work) == before
    assert _io_path(manifest).read_bytes() == before_manifest
    assert _io_path(profile).read_bytes() == before_profile
    journals = list((root / "library/.sidecar-operations").glob("npnf205-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"

    result = install(receipt, expected_receipt_sha256=pin,
                     operation_prefix="npnf205-fixture")
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(root / work) == record["after"]


@pytest.fixture(autouse=True)
def _preserve_current_repository_and_retained_stage():
    with current_npnf_generation_is_preserved(ROOT, WORK_ID):
        yield


def test_current_accepted_generation_is_not_the_original_before(tmp_path: Path) -> None:
    receipt = current_generation_receipt(ROOT, tmp_path / "current-generation.json", WORK_ID)
    with pytest.raises(PipelineError, match="work generation or source sidecar path changed"):
        guard.preflight(receipt)


def test_current_install_closure_preserves_both_historical_records_and_rejects_old_binding(tmp_path: Path) -> None:
    from copy import deepcopy
    from build.tei import npnf205_work_oracle as oracle
    from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
    from tests.npnf_four_install_fixture import _case
    from tests.npnf_install_runtime_fixture import _runtime_record

    case = _case(ROOT, WORK_ID)
    assert set(case["runtime_fields"]) == {"validator.import_closure_sha256"}
    original_receipt_raw = Path(case["original_receipt"]).read_bytes()
    assert sha256(original_receipt_raw).hexdigest() == case["original_receipt_sha256"]
    original_receipt = json.loads(original_receipt_raw)
    held = next(row for row in case["preserved_before"] if row["repository_path"] == case["manifest_path"])
    before_raw = (ROOT / held["fixture"]).read_bytes()
    assert sha256(before_raw).hexdigest() == held["sha256"] == original_receipt["source_manifest_before_sha256"]
    after_raw = (Path(original_receipt["stage_root"]) / case["manifest_path"]).read_bytes()
    assert sha256(after_raw).hexdigest() == original_receipt["source_manifest_after_sha256"]
    before = json.loads(before_raw)
    policy_row = next(row for row in before["authorities"] if row["name"] == "validation-policy")
    policy_raw = (ROOT / policy_row["path"]).read_bytes()
    assert sha256(policy_raw).hexdigest() == policy_row["sha256"] and len(policy_raw) == policy_row["bytes"]
    closure = oracle._sha(oracle._json([
        {"path": path, "sha256": oracle._sha((ROOT / path).read_bytes())}
        for path in json.loads(policy_raw)["closure_inputs"]
    ]))
    assert case["runtime_fields"] == {"validator.import_closure_sha256": closure}
    for payload in (before_raw, after_raw):
        original = json.loads(payload)
        assert original["validator"]["import_closure_sha256"] == "de9710635677757118c19b3e132e3099235d8cc4923c4bb3588b9f669ae39110"
        assert closure != original["validator"]["import_closure_sha256"]
        current = _runtime_record(original, case["runtime_fields"])
        expected = deepcopy(original)
        expected["validator"]["import_closure_sha256"] = closure
        assert current == expected
        restored = deepcopy(current)
        restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
        assert restored == original
        assert _runtime_record(original, {}) == original
    root, _, current, _ = four_work_install_fixture(ROOT, tmp_path, WORK_ID)
    manifest_path = root / current["manifest_path"]
    runtime_raw = manifest_path.read_bytes()
    batch_path = Path(original_receipt["package_receipt"])
    assert sha256(batch_path.read_bytes()).hexdigest() == original_receipt["package_receipt_sha256"]
    item = next(row for row in json.loads(batch_path.read_bytes())["works"] if row["work_id"] == WORK_ID)
    retained = CandidatePackage.load(Path(item["candidate_root"]) / "package")
    assert retained.sha256 == item["candidate_sha256"]
    try:
        manifest_path.write_bytes(before_raw)
        historical = SourceManifest.load(manifest_path, repository_root=root)
        assert json.loads(json.dumps(historical.record, default=dict)) == before
        assert historical.sha256 == sha256(before_raw).hexdigest()
        actual_oracle = guard._oracle(root, historical)
        assert actual_oracle(historical, retained)["import_closure_sha256"] == closure
        with pytest.raises(ValueError, match="oracle import-closure binding mismatch"):
            validate(historical, retained, actual_oracle)
    finally:
        manifest_path.write_bytes(runtime_raw)
    assert (ROOT / held["fixture"]).read_bytes() == before_raw
    assert (Path(original_receipt["stage_root"]) / case["manifest_path"]).read_bytes() == after_raw


@pytest.mark.parametrize("field", ["source_id", "converter.id", "validator.id", "authorities"])
def test_install_runtime_context_rejects_unlisted_record_changes(field: str) -> None:
    from tests.npnf_four_install_fixture import _case
    from tests.npnf_install_runtime_fixture import _runtime_record
    case = _case(ROOT, WORK_ID)
    held = next(row for row in case["preserved_before"] if row["repository_path"] == case["manifest_path"])
    raw = (ROOT / held["fixture"]).read_bytes()
    assert sha256(raw).hexdigest() == held["sha256"]
    with pytest.raises(AssertionError):
        _runtime_record(json.loads(raw), {field: "unreviewed"})
