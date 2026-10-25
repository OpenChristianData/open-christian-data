"""Isolated exact-install and rollback checks for the eight LIB-050 stages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tools import install_lib050_owen_acceptance as installer
from build.tools.install_lib050_owen_acceptance import (
    FIXTURE_MARKER, install, preflight,
)
from build.tools.stage_lib050_owen_acceptance import _work_row
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path

LIBRARY = Path(r"D:\Library\Open Christian Data")
STAGE_INVENTORY = json.loads(
    (Path(__file__).resolve().parent / "fixtures/reconstruction-runtime/lib050-owen-install-stage-inventory.json").read_bytes()
)["stages"]
STAGES = {
    "john-owen-apostasy": "l50-a2",
    "john-owen-church-love": "l50-c2",
    "john-owen-death-of-death": "l50-dd2",
    "john-owen-display-arminianism": "l50-d2",
    "john-owen-divine-justice": "l50-j2",
    "john-owen-eshcol": "l50-e2",
    "john-owen-faith-elect": "l50-f2",
}


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


@pytest.fixture(autouse=True)
def isolated_stage_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The unchanged installer still requires exactly this parent for each test stage.
    monkeypatch.setattr(installer, "LIBRARY", tmp_path)


def _runtime_stage(tmp_path: Path, work_id: str) -> Path:
    original = LIBRARY / STAGES[work_id]
    frozen = STAGE_INVENTORY[work_id]
    assert frozen["stage"] == original.name
    assert _files(original) == frozen["files"]
    original_raw = (original / "stage-receipt.json").read_bytes()
    assert hashlib.sha256(original_raw).hexdigest() == frozen["receipt_sha256"]
    stage = tmp_path / original.name
    shutil.copytree(original, stage)
    assert _files(stage) == frozen["files"]
    record = json.loads(original_raw)
    record["stage_root"] = stage.as_posix()
    record["code_sha256"] = {path: installer._sha(installer.ROOT / path) for path in installer.CODE_PATHS}
    (stage / "stage-receipt.json").write_bytes(_json(record))
    assert {path: digest for path, digest in _files(stage).items() if path != "stage-receipt.json"} == {
        path: digest for path, digest in frozen["files"].items() if path != "stage-receipt.json"
    }
    assert _files(original) == frozen["files"]
    return stage


def _fixture_root(tmp_path: Path, work_id: str) -> tuple[Path, Path, Path, str]:
    root = tmp_path / "fixture"
    root.mkdir()
    (root / FIXTURE_MARKER).write_text("isolated LIB-050 fixture\n", encoding="utf-8")
    stage = _runtime_stage(tmp_path, work_id)
    receipt_sha = hashlib.sha256((stage / "stage-receipt.json").read_bytes()).hexdigest()
    work = Path("library/works") / work_id
    prefix = work.as_posix() + "/"
    for relative in _files(stage):
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        destination = _io_path(root / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(stage / relative), destination)
    row = _work_row(work_id)
    edition = work / "forms" / row["form_id"] / "editions" / row["edition_id"]
    acquisition = edition / "acquisitions" / (row["acquisition_id"] + ".json")
    destination = _io_path(root / acquisition)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(stage / acquisition), destination)
    work_record = json.loads((stage / work / "work.json").read_bytes())
    work_record.pop("creators")
    work_record["textual_forms"][0]["editions"][0].pop("category")
    state = json.loads((stage / work / "state.json").read_bytes())
    target = next(item for item in state["targets"] if item["target_id"] == row["edition_id"])
    target["stage"] = "acquired"
    target.pop("reason")
    target["evidence"] = target["evidence"][:-2]
    for name, record in (("work.json", work_record), ("state.json", state)):
        (root / work / name).write_bytes(_json(record))
    return root, stage, work, receipt_sha


@pytest.mark.parametrize("work_id", STAGES)
def test_each_guarded_child_installs_and_checks_actual_master(tmp_path: Path, work_id: str) -> None:
    root, stage, work, receipt_sha = _fixture_root(tmp_path, work_id)
    before = _files(root / work)
    result = install(work_id, stage, receipt_sha, root_override=root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(root / work) == _files(stage / work)
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    journal = json.loads((operations[0] / "operation.json").read_bytes())
    assert journal["phase"] == "complete"
    assert _files(operations[0] / "previous") == before


def test_stale_live_preimage_is_rejected(tmp_path: Path) -> None:
    work_id = "john-owen-apostasy"
    root, stage, work, receipt_sha = _fixture_root(tmp_path, work_id)
    path = root / work / "work.json"
    record = json.loads(path.read_bytes())
    record["title"] = "Changed after stage"
    path.write_bytes(_json(record))
    with pytest.raises(PipelineError, match="staged work metadata differs"):
        preflight(work_id, stage, receipt_sha, root_override=root)
    assert not (root / "library/.sidecar-operations").exists()


def test_wrong_stage_receipt_pin_and_tampered_source_are_rejected(tmp_path: Path) -> None:
    work_id = "john-owen-faith-elect"
    root, stage, work, receipt_sha = _fixture_root(tmp_path, work_id)
    with pytest.raises(PipelineError, match="receipt differs from caller pin"):
        preflight(work_id, stage, "0" * 64, root_override=root)
    row = _work_row(work_id)
    source = root / row["source"]["path"]
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="external dependency changed"):
        preflight(work_id, stage, receipt_sha, root_override=root)
    assert not (root / "library/.sidecar-operations").exists()


def test_stale_projector_code_pin_is_rejected(tmp_path: Path, monkeypatch) -> None:
    work_id = "john-owen-faith-elect"
    root, stage, _, receipt_sha = _fixture_root(tmp_path, work_id)
    code_path = installer.ROOT / "ocd_kernel/projection/categories/lib050_owen.py"
    original_sha = installer._sha

    def changed_sha(path: Path) -> str:
        return "0" * 64 if Path(path) == code_path else original_sha(path)

    monkeypatch.setattr(installer, "_sha", changed_sha)
    with pytest.raises(PipelineError, match="code pins differ"):
        preflight(work_id, stage, receipt_sha, root_override=root)
    assert not (root / "library/.sidecar-operations").exists()


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_failure_restores_exact_prior_generation(tmp_path: Path, phase: str) -> None:
    work_id = "john-owen-eshcol"
    root, stage, work, receipt_sha = _fixture_root(tmp_path, work_id)
    before = _files(root / work)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise RuntimeError("injected " + phase)

    with pytest.raises(RuntimeError, match="injected " + phase):
        install(work_id, stage, receipt_sha, root_override=root, fail_at=fail_at)
    assert _files(root / work) == before
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    journal = json.loads((operations[0] / "operation.json").read_bytes())
    assert journal["phase"] == "rolled-back"
    assert journal["before"] == before
    assert preflight(work_id, stage, receipt_sha, root_override=root)["status"] == "pass-read-only"


@pytest.mark.parametrize("work_id", STAGES)
def test_runtime_stage_preserves_complete_frozen_receipt_and_files(tmp_path: Path, work_id: str) -> None:
    root, stage, _, _ = _fixture_root(tmp_path, work_id)
    original = LIBRARY / STAGES[work_id]
    frozen = STAGE_INVENTORY[work_id]
    raw = (original / "stage-receipt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == frozen["receipt_sha256"]
    expected = json.loads(raw)
    expected["stage_root"] = stage.as_posix()
    expected["code_sha256"] = {path: installer._sha(installer.ROOT / path) for path in installer.CODE_PATHS}
    assert (stage / "stage-receipt.json").read_bytes() == _json(expected)
    assert _files(original) == frozen["files"]
    current_files = _files(stage)
    assert set(current_files) == set(frozen["files"])
    assert all(current_files[path] == digest for path, digest in frozen["files"].items()
               if path != "stage-receipt.json")
    assert not (root / "library/.sidecar-operations").exists()


@pytest.mark.parametrize("work_id", STAGES)
def test_frozen_historical_stage_rejects_current_code(tmp_path: Path, work_id: str) -> None:
    root, _, work, _ = _fixture_root(tmp_path, work_id)
    before = _files(root / work)
    original = LIBRARY / STAGES[work_id]
    frozen = STAGE_INVENTORY[work_id]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "LIBRARY", LIBRARY)
        with pytest.raises(PipelineError, match="stage code pins differ"):
            preflight(work_id, original, frozen["receipt_sha256"], root_override=root)
    assert _files(root / work) == before
    assert _files(original) == frozen["files"]
    assert not (root / "library/.sidecar-operations").exists()


def test_runtime_stage_parent_guard_remains_exact(tmp_path: Path) -> None:
    work_id = "john-owen-apostasy"
    root, stage, work, receipt_sha = _fixture_root(tmp_path, work_id)
    before = _files(root / work)
    other = tmp_path / "unapproved-parent"
    other.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "LIBRARY", other)
        with pytest.raises(PipelineError, match="stage path or receipt pin is outside"):
            preflight(work_id, stage, receipt_sha, root_override=root)
    assert _files(root / work) == before
    assert not (root / "library/.sidecar-operations").exists()
