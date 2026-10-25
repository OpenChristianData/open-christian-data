"""Exercise the City of God per-work swap failure path."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from build.tools import install_city_of_god_sidecars as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[1]
STAGE = Path("C:/Scratch/Open Christian Data/city-of-god-two-edition-sidecar-stage-20260926-v2")


def test_validation_failure_restores_exact_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = Path("library/works") / installer.WORK_ID
    target = tmp_path / prefix
    target.parent.mkdir(parents=True)
    target.mkdir()
    expected_before = {'state.json': 'f8d97679029611f99b09fae58046211bcb7f958e66378d7a99f34f43654df24a', 'work.json': '14f279d35efc05fed53392a9a4852a990ab85d741bbe040af42bcf2703de3d99'}
    retained = Path(__file__).parent / "fixtures/city-sidecar-before"
    for relative, expected in expected_before.items():
        raw = (retained / relative).read_bytes()
        assert __import__("hashlib").sha256(raw).hexdigest() == expected
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    assert installer._tree(target) == expected_before
    before = installer._tree(target)
    staged = tmp_path / "staged"
    shutil.copytree(_io_path(STAGE / prefix), _io_path(staged / prefix))
    receipt = json.loads((STAGE / "receipt.json").read_text(encoding="utf-8"))

    assert all(before.get(Path(item["path"]).relative_to(prefix).as_posix()) == item["before_sha256"] for item in receipt["files"])

    def fail_validation(*_args: object, **_kwargs: object) -> None:
        raise PipelineError("injected post-swap validation failure")

    monkeypatch.setattr(installer, "validate_acquisition", fail_validation)
    with pytest.raises(PipelineError, match="injected post-swap"):
        installer._install_one(tmp_path, staged, receipt["files"])

    assert installer._tree(target) == before
    operations = list((tmp_path / "library/.sidecar-operations").glob("city-sidecars-*/operation.json"))
    assert len(operations) == 1
    journal = json.loads(operations[0].read_text(encoding="utf-8"))
    assert journal["phase"] == "rolled-back"
    assert journal["before"] == before
