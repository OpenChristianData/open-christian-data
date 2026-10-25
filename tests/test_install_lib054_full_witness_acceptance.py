"""Isolated exact-install and rollback checks for the eight LIB-054 stages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tools.install_lib054_full_witness_acceptance import (
    FIXTURE_MARKER, install, preflight,
)
from build.tools.stage_lib054_full_witness_acceptance import _work_row
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path

LIBRARY = Path(r"D:\Library\Open Christian Data")
STAGES = {
    "baxter-call-to-unconverted": "l54-baxter-call-v2",
    "baxter-reformed-pastor": "l54-baxter-pastor-v2",
    "baxter-saints-rest": "l54-baxter-saints-v2",
    "boston-crook-in-the-lot": "l54-boston-crook-v2",
    "bunyan-grace-abounding": "l54-bunyan-grace-v2",
    "bunyan-holy-war": "l54-bunyan-war-v2",
    "butler-analogy-of-religion": "l54-butler-analogy-v2",
    "edwards-freedom-of-the-will": "l54-edwards-will-v2",
}


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fixture_root(tmp_path: Path, work_id: str) -> tuple[Path, Path, Path, str]:
    root = tmp_path / "fixture"
    root.mkdir()
    (root / FIXTURE_MARKER).write_text("isolated LIB-054 fixture\n", encoding="utf-8")
    stage = LIBRARY / STAGES[work_id]
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
    work_id = "baxter-call-to-unconverted"
    root, stage, work, receipt_sha = _fixture_root(tmp_path, work_id)
    path = root / work / "work.json"
    record = json.loads(path.read_bytes())
    record["title"] = "Changed after stage"
    path.write_bytes(_json(record))
    with pytest.raises(PipelineError, match="staged work metadata differs"):
        preflight(work_id, stage, receipt_sha, root_override=root)
    assert not (root / "library/.sidecar-operations").exists()


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_failure_restores_exact_prior_generation(tmp_path: Path, phase: str) -> None:
    work_id = "butler-analogy-of-religion"
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
