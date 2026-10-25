"""Isolated clean, stale-preimage, and rollback checks for two pinned stages."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil

import pytest

from build.tools import install_creeds_json_two_catechisms as installer
from build.tools.install_creeds_json_two_catechisms import (
    FIXTURE_CONTENT,
    FIXTURE_MARKER,
    ROOT,
    ROUTES,
    STAGE_PARENT,
    STAGE_RECEIPTS,
    install,
    preflight,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


def _historical_call(operation, work_id: str, *, root_override: Path, monkeypatch: pytest.MonkeyPatch, **kwargs):
    assert work_id in ROUTES
    raw = _io_path(STAGE_PARENT / work_id / "final-stage-receipt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == STAGE_RECEIPTS[work_id]
    recorded_root = Path(json.loads(raw)["canonical_root"])
    assert root_override.resolve(strict=True) != recorded_root.resolve(strict=True)
    assert _io_path(root_override / FIXTURE_MARKER).read_text(encoding="utf-8") == FIXTURE_CONTENT
    # ROOT supplies only the frozen identity and unused default; all I/O uses root_override.
    with monkeypatch.context() as context:
        context.setattr(installer, "ROOT", recorded_root)
        return operation(work_id, root_override=root_override, **kwargs)


@pytest.fixture(params=sorted(ROUTES))
def isolated_root(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Path, str]:
    work_id = request.param
    work = Path("library/works") / work_id
    stage = STAGE_PARENT / work_id
    root = tmp_path / "r"
    root.mkdir()
    _io_path(root / FIXTURE_MARKER).write_text(FIXTURE_CONTENT, encoding="utf-8")
    receipt_bytes = _io_path(stage / "final-stage-receipt.json").read_bytes()
    assert hashlib.sha256(receipt_bytes).hexdigest() == STAGE_RECEIPTS[work_id]
    before = json.loads(receipt_bytes)["before"]
    for relative, expected_sha256 in before.items():
        source = (
            ROOT / "tests/fixtures/reconstruction-runtime/authorities" / f"creeds-install-{work_id}.{relative}"
            if relative in {"work.json", "state.json"}
            else stage / work / relative
        )
        payload = _io_path(source).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected_sha256
        target = _io_path(root / work / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    assert _files(root / work) == before
    for relative in _files(stage):
        if relative == "final-stage-receipt.json" or relative.startswith(f"library/works/{work_id}/"):
            continue
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(stage / relative), target)
    return root, work_id


def test_guarded_install_commits_exact_generation_in_isolation(isolated_root: tuple[Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    root, work_id = isolated_root
    checked = _historical_call(preflight, work_id, root_override=root, monkeypatch=monkeypatch)
    assert checked["status"] == "ready-stage-only"
    result = _historical_call(install, work_id, root_override=root, monkeypatch=monkeypatch)
    assert result["status"] == "creeds-json-electronic-accepted"
    assert _files(root / "library/works" / work_id) == checked["after"]
    assert result["live_projection_rows"] == ROUTES[work_id]["row_count"]
    journal = json.loads(_io_path(Path(result["operation"]) / "operation.json").read_bytes())
    assert journal["phase"] == "complete"


def test_guarded_preflight_rejects_stale_preimage(isolated_root: tuple[Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    root, work_id = isolated_root
    work = _io_path(root / "library/works" / work_id / "work.json")
    work.write_bytes(work.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="canonical before"):
        _historical_call(preflight, work_id, root_override=root, monkeypatch=monkeypatch)


def test_injected_post_install_failure_rolls_back(isolated_root: tuple[Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    root, work_id = isolated_root
    before = _files(root / "library/works" / work_id)

    def fail_after_validation() -> None:
        raise RuntimeError("injected after-live check")

    with pytest.raises(RuntimeError, match="injected after-live check"):
        _historical_call(install, work_id, root_override=root, monkeypatch=monkeypatch, after_live_check=fail_after_validation)
    assert _files(root / "library/works" / work_id) == before
    journals = list((root / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(_io_path(journals[0]).read_bytes())["phase"] == "rolled-back"


def test_original_stage_identity_rejects_wrong_root(isolated_root: tuple[Path, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, work_id = isolated_root
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="stage identity, source, or native catechism projection differs"):
        preflight(work_id, root_override=root)
