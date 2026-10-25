"""Fixture-only transaction checks for the pinned 20-work Athanasius installer."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from build.tools import install_athanasius_npnf204_acceptances as installer
from ocd_kernel.library._common import PipelineError
from tests.npnf_acquired_historical_fixture import historical_npnf_root
from ocd_kernel.tei.install_accepted import _files, _io_path


CURRENT_ROOT = installer.ROOT


@pytest.fixture(scope="module", autouse=True)
def historical_acquired_context(tmp_path_factory):
    """Exercise the real installer against exact retained acquired bytes."""
    root = historical_npnf_root(installer.STAGE, tmp_path_factory.mktemp("npnf-historical"))
    receipt = json.loads(_io_path(installer.STAGE / "stage-receipt.json").read_bytes())
    before = {row["work_id"]: _files(CURRENT_ROOT / "library/works" / row["work_id"]) for row in receipt["works"]}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "ROOT", root)
        yield root
    assert all(_files(CURRENT_ROOT / "library/works" / work_id) == saved for work_id, saved in before.items())


def test_current_generation_is_not_the_retained_acquired_preimage():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "ROOT", CURRENT_ROOT)
        with pytest.raises(PipelineError, match="preimage|generation"):
            installer.preflight()


WORKS = [work_id for _, work_id in installer.ASSIGNED]
WORKS_PATH = Path("library/works")


@pytest.fixture
def isolated_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    """Copy the pinned evidence, then restore all exact acquired preimages."""
    root = tmp_path / "r"
    stage = installer.STAGE
    receipt = json.loads(_io_path(stage / "stage-receipt.json").read_bytes())
    shutil.copytree(_io_path(stage), _io_path(root))
    for row in receipt["works"]:
        relative = WORKS_PATH / row["work_id"]
        destination = root / relative
        shutil.rmtree(_io_path(destination))
        shutil.copytree(_io_path(installer.ROOT / relative), _io_path(destination))
        assert _files(destination) == row["before"]
    unrelated = root / "unrelated-preserved.txt"
    unrelated.write_bytes(b"unrelated work remains unchanged\n")
    monkeypatch.setattr(installer, "ROOT", root)
    return root, receipt


def _work(root: Path, work_id: str) -> Path:
    return root / WORKS_PATH / work_id


def _journal(result: dict) -> dict:
    return json.loads(_io_path(Path(result["operation"]) / "operation.json").read_bytes())


def _only_journal(root: Path) -> dict:
    journals = list((root / ".tmp_audit").glob("*/operation.json"))
    assert len(journals) == 1
    return json.loads(_io_path(journals[0]).read_bytes())


def test_preflight_checks_all_twenty_without_writing(isolated_install: tuple[Path, dict]) -> None:
    root, receipt = isolated_install
    before = {work_id: _files(_work(root, work_id)) for work_id in WORKS}
    sentinel = (root / "unrelated-preserved.txt").read_bytes()
    checked = installer.preflight()
    assert checked["status"] == "pass-read-only"
    assert checked["canonical_action"] == "none"
    assert checked["receipt_sha256"] == installer.RECEIPT_SHA256
    assert [row["work_id"] for row in checked["works"]] == WORKS
    assert all(row["projection_rows"] == 1 for row in checked["works"])
    assert all(_files(_work(root, work_id)) == receipt["works"][i]["before"] == before[work_id]
               for i, work_id in enumerate(WORKS))
    assert (root / "unrelated-preserved.txt").read_bytes() == sentinel
    assert not (root / ".tmp_audit").exists()


def test_changed_preimage_is_rejected_before_any_swap(isolated_install: tuple[Path, dict]) -> None:
    root, receipt = isolated_install
    work_id = WORKS[0]
    drifted = _work(root, work_id) / "work.json"
    drifted.write_bytes(drifted.read_bytes() + b"\n")
    unrelated_before = _files(_work(root, WORKS[1]))
    with pytest.raises(PipelineError, match="preimage or staged generation differs"):
        installer.install_one(work_id)
    assert _files(_work(root, work_id)) != receipt["works"][0]["before"]
    assert _files(_work(root, WORKS[1])) == unrelated_before
    assert not (root / ".tmp_audit").exists()


def test_failure_after_new_live_restores_exact_previous_work(isolated_install: tuple[Path, dict]) -> None:
    root, receipt = isolated_install
    work_id = WORKS[0]
    unrelated = _work(root, WORKS[1])
    unrelated_before = _files(unrelated)

    def interrupt(checkpoint: str) -> None:
        if checkpoint == "after-new-live":
            raise RuntimeError("injected new-live failure")

    with pytest.raises(RuntimeError, match="injected new-live failure"):
        installer.install_one(work_id, fail_at=interrupt)
    assert _files(_work(root, work_id)) == receipt["works"][0]["before"]
    assert _files(unrelated) == unrelated_before
    assert _only_journal(root)["phase"] == "rolled-back"
    assert installer.preflight(work_id)["status"] == "pass-read-only"


def test_later_work_failure_preserves_earlier_install_and_unrelated_work(
    isolated_install: tuple[Path, dict],
) -> None:
    root, receipt = isolated_install
    first, second, third = WORKS[:3]
    third_before = _files(_work(root, third))
    sentinel = root / "unrelated-preserved.txt"
    sentinel_before = sentinel.read_bytes()
    result = installer.install_one(first)
    assert result["status"] == "installed-and-validated"
    assert _journal(result)["phase"] == "complete"
    assert _files(_work(root, first)) == receipt["works"][0]["after"]

    def interrupt(checkpoint: str) -> None:
        if checkpoint == "after-new-live":
            raise RuntimeError("injected later-work failure")

    with pytest.raises(RuntimeError, match="injected later-work failure"):
        installer.install_one(second, fail_at=interrupt)
    assert _files(_work(root, first)) == receipt["works"][0]["after"]
    assert _files(_work(root, second)) == receipt["works"][1]["before"]
    assert _files(_work(root, third)) == third_before
    assert sentinel.read_bytes() == sentinel_before
    journals = [json.loads(_io_path(path).read_bytes())
                for path in (root / ".tmp_audit").glob("*/operation.json")]
    assert len(journals) == 2
    assert {(journal["work_id"], journal["phase"]) for journal in journals} == {
        (first, "complete"), (second, "rolled-back")
    }
