"""Focused exact-source, preimage, and rollback checks for final LIB-051 works."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tools import install_lib051_owen_acceptance as installer
from build.tools import install_lib051_owen_batch as batch
from build.tools.install_lib051_owen_batch import _pins
from build.tools.install_lib051_owen_acceptance import FIXTURE_MARKER, install, preflight
from build.tools.stage_lib051_owen_acceptance import _work_row
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


WORK_ID = "john-owen-glory"
STAGE = Path(r"D:\Library\Open Christian Data\l51-gl2")
OTHER_STAGES = {
    "john-owen-justification": Path(r"D:\Library\Open Christian Data\l51-j2"),
    "john-owen-pneumatologia": Path(r"D:\Library\Open Christian Data\l51-pn2"),
}
PINS = Path("plans/2026-09-22-source-preflight/owen-lib051-final-three-readable-stage-pins-20260927.json")
STAGE_INVENTORY = json.loads(
    (Path(__file__).resolve().parent / "fixtures/reconstruction-runtime/lib051-owen-install-stage-inventory.json").read_bytes()
)["stages"]


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture(autouse=True)
def isolated_stage_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "LIBRARY", tmp_path)


def _runtime_stage(tmp_path: Path, work_id: str, original: Path) -> Path:
    # Same bounded temporary-successor pattern as the LIB-050 install tests.
    frozen = STAGE_INVENTORY[work_id]
    assert original.resolve(strict=True) == Path(frozen["stage_root"]).resolve(strict=True)
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


def _fixture_root(tmp_path: Path, work_id: str = WORK_ID,
                  stage: Path = STAGE) -> tuple[Path, Path, Path, str]:
    root = tmp_path / "fixture"
    root.mkdir()
    (root / FIXTURE_MARKER).write_text("isolated LIB-051 fixture\n", encoding="utf-8")
    stage = _runtime_stage(tmp_path, work_id, stage)
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
    target = _io_path(root / acquisition)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(stage / acquisition), target)
    work_record = json.loads(_io_path(stage / work / "work.json").read_bytes())
    work_record.pop("creators")
    work_record["textual_forms"][0]["editions"][0].pop("category")
    state = json.loads(_io_path(stage / work / "state.json").read_bytes())
    target = next(item for item in state["targets"] if item["target_id"] == row["edition_id"])
    target["stage"] = "acquired"
    target.pop("reason")
    target["evidence"] = target["evidence"][:-2]
    for name, record in (("work.json", work_record), ("state.json", state)):
        (root / work / name).write_bytes(_json(record))
    return root, stage, work, receipt_sha


@pytest.mark.parametrize("work_id,stage", [(WORK_ID, STAGE), *OTHER_STAGES.items()])
def test_guarded_install_checks_actual_master(tmp_path: Path, work_id: str, stage: Path) -> None:
    root, stage, work, receipt_sha = _fixture_root(tmp_path, work_id, stage)
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


def test_stale_preimage_source_and_receipt_fail_closed(tmp_path: Path) -> None:
    root, stage, work, receipt_sha = _fixture_root(tmp_path)
    with pytest.raises(PipelineError, match="receipt differs from caller pin"):
        preflight(WORK_ID, stage, "0" * 64, root_override=root)
    record_path = root / work / "work.json"
    record = json.loads(record_path.read_bytes())
    record["title"] = "changed after stage"
    record_path.write_bytes(_json(record))
    with pytest.raises(PipelineError, match="staged work metadata differs"):
        preflight(WORK_ID, stage, receipt_sha, root_override=root)
    record["title"] = json.loads((stage / work / "work.json").read_bytes())["title"]
    record_path.write_bytes(_json(record))
    source = root / _work_row(WORK_ID)["source"]["path"]
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="external dependency changed"):
        preflight(WORK_ID, stage, receipt_sha, root_override=root)
    assert not (root / "library/.sidecar-operations").exists()


def test_changed_projector_pin_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, stage, _, receipt_sha = _fixture_root(tmp_path)
    code_path = installer.ROOT / "ocd_kernel/projection/categories/prose.py"
    original_sha = installer._sha

    def changed_sha(path: Path) -> str:
        return "0" * 64 if Path(path) == code_path else original_sha(path)

    monkeypatch.setattr(installer, "_sha", changed_sha)
    with pytest.raises(PipelineError, match="code pins differ"):
        preflight(WORK_ID, stage, receipt_sha, root_override=root)
    assert not (root / "library/.sidecar-operations").exists()


def test_batch_pin_mutations_fail_before_install(tmp_path: Path) -> None:
    raw = PINS.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert len(_pins(PINS, digest)) == 3
    with pytest.raises(PipelineError, match="pins file differs"):
        _pins(PINS, "0" * 64)
    changed = json.loads(raw)
    changed["stages"][0], changed["stages"][1] = changed["stages"][1], changed["stages"][0]
    path = tmp_path / "wrong-order.json"
    altered = _json(changed)
    path.write_bytes(altered)
    with pytest.raises(PipelineError, match="work order"):
        _pins(path, hashlib.sha256(altered).hexdigest())


def test_batch_checks_all_stages_before_first_serial_install(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str]] = []
    digest = hashlib.sha256(PINS.read_bytes()).hexdigest()

    def check(work_id: str, stage: Path, receipt_sha: str, *, root_override=None) -> dict:
        events.append(("check", work_id))
        return {"work_id": work_id, "stage_receipt_sha256": receipt_sha, "projection_rows": 1}

    def apply(work_id: str, stage: Path, receipt_sha: str, *, root_override=None) -> dict:
        assert len([event for event in events if event[0] == "check"]) == 3
        events.append(("install", work_id))
        return {"work_id": work_id, "status": "installed-and-validated"}

    monkeypatch.setattr(batch, "preflight", check)
    monkeypatch.setattr(batch, "install", apply)
    result = batch.install_all(PINS, digest)
    assert result["status"] == "installed-serially"
    assert len(result["results"]) == 3
    assert [kind for kind, _ in events] == ["check"] * 3 + ["install"] * 3


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_failure_restores_prior_generation(tmp_path: Path, phase: str) -> None:
    root, stage, work, receipt_sha = _fixture_root(tmp_path)
    before = _files(root / work)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise RuntimeError("injected " + phase)

    with pytest.raises(RuntimeError, match="injected " + phase):
        install(WORK_ID, stage, receipt_sha, root_override=root, fail_at=fail_at)
    assert _files(root / work) == before
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    journal = json.loads((operations[0] / "operation.json").read_bytes())
    assert journal["phase"] == "rolled-back"
    assert preflight(WORK_ID, stage, receipt_sha, root_override=root)["status"] == "pass-read-only"


@pytest.mark.parametrize("work_id", STAGE_INVENTORY)
def test_runtime_stage_preserves_complete_frozen_receipt_and_files(tmp_path: Path, work_id: str) -> None:
    frozen = STAGE_INVENTORY[work_id]
    original = Path(frozen["stage_root"])
    root, stage, _, _ = _fixture_root(tmp_path, work_id, original)
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


@pytest.mark.parametrize("work_id", STAGE_INVENTORY)
def test_frozen_historical_stage_rejects_current_code(tmp_path: Path, work_id: str) -> None:
    frozen = STAGE_INVENTORY[work_id]
    original = Path(frozen["stage_root"])
    root, _, work, _ = _fixture_root(tmp_path, work_id, original)
    before = _files(root / work)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "LIBRARY", original.parent)
        with pytest.raises(PipelineError, match="stage code pins differ"):
            preflight(work_id, original, frozen["receipt_sha256"], root_override=root)
    assert _files(root / work) == before
    assert _files(original) == frozen["files"]
    assert not (root / "library/.sidecar-operations").exists()


def test_runtime_stage_parent_guard_remains_exact(tmp_path: Path) -> None:
    root, stage, work, receipt_sha = _fixture_root(tmp_path)
    before = _files(root / work)
    other = tmp_path / "unapproved-parent"
    other.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "LIBRARY", other)
        with pytest.raises(PipelineError, match="stage path or receipt pin is outside"):
            preflight(WORK_ID, stage, receipt_sha, root_override=root)
    assert _files(root / work) == before
    assert not (root / "library/.sidecar-operations").exists()
