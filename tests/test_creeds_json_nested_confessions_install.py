"""Isolated complete-generation checks for a pinned nested confession stage."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import shutil

import pytest

from build.tools import install_creeds_json_nested_confessions as installer
from build.tools.install_creeds_json_nested_confessions import (
    FIXTURE_CONTENT,
    FIXTURE_MARKER,
    ROOT,
    STAGE_PARENT,
    install,
    preflight,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


WORK_ID = "canons-of-dort"
WORK = Path("library/works") / WORK_ID
STAGE = STAGE_PARENT / WORK_ID

pytestmark = pytest.mark.skipif(
    not _io_path(STAGE / "final-stage-receipt.json").is_file(),
    reason="pinned durable Creeds.json stage is not mounted",
)


def _historical_call(operation, work_id: str, *, root_override: Path, monkeypatch: pytest.MonkeyPatch, **kwargs):
    assert work_id == WORK_ID
    raw = _io_path(STAGE / "final-stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == installer.STAGE_RECEIPTS[work_id]
    recorded_root = Path(json.loads(raw)["canonical_root"])
    assert root_override.resolve(strict=True) != recorded_root.resolve(strict=True)
    assert _io_path(root_override / FIXTURE_MARKER).read_text(encoding="utf-8") == FIXTURE_CONTENT
    # ROOT is consulted only for historical identity and the unused default;
    # every read and write below uses this explicit marked fixture root.
    with monkeypatch.context() as context:
        context.setattr(installer, "ROOT", recorded_root)
        return operation(work_id, root_override=root_override, **kwargs)


@pytest.fixture
def isolated_root(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    _io_path(root / FIXTURE_MARKER).write_text(FIXTURE_CONTENT, encoding="utf-8")
    receipt_raw = _io_path(STAGE / "final-stage-receipt.json").read_bytes()
    assert sha256(receipt_raw).hexdigest() == installer.STAGE_RECEIPTS[WORK_ID]
    receipt = json.loads(receipt_raw)
    assert _files(STAGE / WORK) == receipt["after"]
    for relative, expected in receipt["before"].items():
        payload = _io_path(STAGE / WORK / relative).read_bytes()
        assert sha256(payload).hexdigest() == receipt["after"][relative]
        if sha256(payload).hexdigest() != expected:
            value = json.loads(payload)
            if relative == "work.json":
                edition = value["textual_forms"][0]["editions"][0]
                assert edition.pop("category") == "doctrinal-documents"
                assert edition.pop("language") == "en"
            elif relative == "state.json":
                edition = next(t for t in value["targets"] if t["target_type"] == "edition")
                acquisition = next(t for t in value["targets"] if t["target_type"] == "acquisition")
                assert edition["stage"] == "accepted"
                edition["stage"] = "acquired"
                edition.pop("reason")
                edition["updated_at"] = acquisition["updated_at"]
                assert edition["evidence"][-2].endswith("/master.tei.xml")
                assert edition["evidence"][-1].endswith("/acceptance.json")
                edition["evidence"] = edition["evidence"][:-2]
            else:
                raise AssertionError("Unchanged acquisition bytes are required")
            payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        assert sha256(payload).hexdigest() == expected
        target = _io_path(root / WORK / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    assert _files(root / WORK) == receipt["before"]
    for relative in _files(STAGE):
        if relative in {"stage-receipt.json", "final-stage-receipt.json"} or relative.startswith(f"library/works/{WORK_ID}/"):
            continue
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(STAGE / relative), target)
    return root


def test_guarded_install_commits_exact_generation_in_isolation(isolated_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checked = _historical_call(preflight, WORK_ID, root_override=isolated_root, monkeypatch=monkeypatch)
    assert checked["status"] == "ready-stage-only"
    result = _historical_call(install, WORK_ID, root_override=isolated_root, monkeypatch=monkeypatch)
    assert result["status"] == "creeds-json-electronic-accepted"
    assert _files(isolated_root / WORK) == checked["after"]
    assert result["live_projection_rows"] == 93
    journal = json.loads(_io_path(Path(result["operation"]) / "operation.json").read_bytes())
    assert journal["phase"] == "complete"


def test_guarded_preflight_rejects_stale_preimage(isolated_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = _io_path(isolated_root / WORK / "work.json")
    work.write_bytes(work.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="canonical before"):
        _historical_call(preflight, WORK_ID, root_override=isolated_root, monkeypatch=monkeypatch)


def test_injected_post_install_failure_rolls_back(isolated_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _files(isolated_root / WORK)

    def fail_after_validation() -> None:
        raise RuntimeError("injected after-live check")

    with pytest.raises(RuntimeError, match="injected after-live check"):
        _historical_call(install, WORK_ID, root_override=isolated_root, monkeypatch=monkeypatch, after_live_check=fail_after_validation)
    assert _files(isolated_root / WORK) == before
    journals = list((isolated_root / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(_io_path(journals[0]).read_bytes())["phase"] == "rolled-back"


def test_original_stage_identity_rejects_wrong_root(isolated_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-historical-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="stage identity, source, or projection receipt differs"):
        preflight(WORK_ID, root_override=isolated_root)
