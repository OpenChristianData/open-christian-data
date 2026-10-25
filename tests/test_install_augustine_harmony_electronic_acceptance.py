"""Exact Harmony stage, preserved handoff, and guarded rollback fixtures."""

import json
from hashlib import sha256
from pathlib import Path
import shutil

import pytest

from build.tools import install_augustine_harmony_electronic_acceptance as installer
from build.tools.install_augustine_harmony_electronic_acceptance import (
    FIXTURE_MARKER, RECEIPT, STAGE, WORK, install, preflight,
)
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.tei.install_accepted import _files


INPUT_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_RECEIPT_SHA256 = "97c36d88dcdb7a2f8953617b6fbf6d5ff77c6c3efe4b2aaf7779ac1220687d62"
ORIGINAL_NATIVE_PINS = {
    "CURRENT_NATIVE_DOCUMENTS_SHA256": "1b854764070c46257e16d0ced0e02392f69a9c6a9ed729e2c70d2043f3c4aa87",
    "CURRENT_NATIVE_CONTENT_SHA256": "97c44a3b873d9c52307953015ef1e9edf276e616caaf55e36b16a7b8f6e58e00",
}
CURRENT_RUNTIME_FILES = {'ocd_kernel/projection/categories/lib040_harmony.py': {'sha256': '8ef92e59591de649072014cb16468b7d1ce507c0d253bf91456cb758a161cd4e', 'bytes': 10748}, 'ocd_kernel/projection/categories/prose.py': {'sha256': 'e39117916a64f903bd2b5efc569096308c29c99f429f28386f0ada378aba49aa', 'bytes': 57580}, 'ocd_kernel/projection/categories/native_documents.py': {'sha256': '229f3f1e9be106c061c8f7a699820f263fc615798c61212ef8756a009261a59a', 'bytes': 174564}, 'ocd_kernel/projection/native_content.py': {'sha256': '0cf26976895508516f84bff8c6436acf35b5d0593632971cf5eb5a788165ff77', 'bytes': 52716}, 'build/tools/stage_augustine_harmony_electronic_acceptance.py': {'sha256': 'ca20326d2947d96d8b329d60672aaf5b04806da7bb8204560784e3dd403d86ce', 'bytes': 16542}}


@pytest.fixture
def harmony_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    original_raw = io_path(RECEIPT).read_bytes()
    assert sha256(original_raw).hexdigest() == ORIGINAL_RECEIPT_SHA256
    original = json.loads(original_raw)
    for logical, pin in CURRENT_RUNTIME_FILES.items():
        payload = io_path(INPUT_ROOT / logical).read_bytes()
        assert sha256(payload).hexdigest() == pin["sha256"] and len(payload) == pin["bytes"]
    current = json.loads(original_raw)
    for logical in current["projection_code_sha256"]:
        current["projection_code_sha256"][logical] = CURRENT_RUNTIME_FILES[logical]["sha256"]
    current["stage_tool_sha256"] = CURRENT_RUNTIME_FILES[current["stage_tool"]]["sha256"]
    restored = json.loads(json.dumps(current))
    restored["projection_code_sha256"] = original["projection_code_sha256"]
    restored["stage_tool_sha256"] = original["stage_tool_sha256"]
    assert restored == original
    for constant, old in ORIGINAL_NATIVE_PINS.items():
        assert getattr(installer, constant) == old
        logical = ("ocd_kernel/projection/categories/native_documents.py" if constant == "CURRENT_NATIVE_DOCUMENTS_SHA256"
                   else "ocd_kernel/projection/native_content.py")
        monkeypatch.setattr(installer, constant, CURRENT_RUNTIME_FILES[logical]["sha256"])
    assert installer.CURRENT_PROJECTION_RECEIPT_SHA256 == "307ef32a88e1d88426e09b4b73fc08233740078845dbadd2fba18e638533abaa"
    monkeypatch.setattr(installer, "CURRENT_PROJECTION_RECEIPT_SHA256",
                        "d412e1e523d73cd1d1feaa70cb80bff2fc3f6ce891a4bd7347490a65d65ca648")
    path = tmp_path / "harmony-current-runtime-receipt.json"
    payload = (json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(payload)
    monkeypatch.setattr(installer, "RECEIPT", path)
    monkeypatch.setattr(installer, "RECEIPT_SHA256", sha256(payload).hexdigest())
    return current


@pytest.fixture
def harmony_root(tmp_path: Path, harmony_runtime: dict) -> Path:
    root = tmp_path / "harmony-fixture"
    root.mkdir()
    (root / FIXTURE_MARKER).write_text("isolated test fixture\n", encoding="utf-8")
    receipt = json.loads(RECEIPT.read_bytes())
    prefix = WORK.as_posix() + "/"
    for relative in receipt["after"]:
        if relative.startswith(prefix):
            continue
        destination = io_path(root / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(io_path(STAGE / relative), destination)
    prefix = WORK.as_posix() + "/"
    before = {path[len(prefix):]: digest for path, digest in receipt["before"].items() if digest is not None}
    for relative, expected in before.items():
        payload = io_path(STAGE / WORK / relative).read_bytes()
        assert sha256(payload).hexdigest() == receipt["after"][prefix + relative]
        if sha256(payload).hexdigest() != expected:
            value = json.loads(payload)
            if relative == "work.json":
                assert value["textual_forms"][0]["editions"][0].pop("category") == "prose"
            elif relative == "state.json":
                target = next(t for t in value["targets"] if t["target_type"] == "edition")
                acquisition = next(t for t in value["targets"] if t["target_type"] == "acquisition")
                assert target["stage"] == "accepted"
                target["stage"] = "acquired"
                target.pop("reason")
                target["updated_at"] = acquisition["updated_at"]
                assert target["evidence"][-2].endswith("/master.tei.xml")
                assert target["evidence"][-1].endswith("/acceptance.json")
                target["evidence"] = target["evidence"][:-2]
            else:
                raise AssertionError("Unchanged acquired source is required")
            payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        assert sha256(payload).hexdigest() == expected
        destination = io_path(root / WORK / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    handoff = receipt["work_local_handoff"]
    payload = io_path(INPUT_ROOT / handoff).read_bytes()
    assert sha256(payload).hexdigest() == receipt["work_local_handoff_sha256"]
    destination = io_path(root / handoff)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    before[handoff[len(prefix):]] = receipt["work_local_handoff_sha256"]
    assert _files(root / WORK) == before
    assert preflight(root_override=root)["status"] == "pass-read-only"
    return root


def _operation(root: Path) -> tuple[Path, dict]:
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    operation = operations[0]
    return operation, json.loads((operation / "operation.json").read_text(encoding="utf-8"))


def test_clean_fixture_install_preserves_handoff_and_checks_seven_rows(harmony_root: Path) -> None:
    checked = preflight(root_override=harmony_root)
    result = install(root_override=harmony_root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 7
    assert _files(harmony_root / WORK) == checked["after"]
    operation, journal = _operation(harmony_root)
    assert journal["phase"] == "complete"
    assert _files(operation / "previous") == checked["before"]
    handoff = checked["preserved_handoff"]
    assert io_path(harmony_root / handoff).read_bytes() == io_path(operation / "previous" / Path(handoff).relative_to(WORK)).read_bytes()


@pytest.mark.parametrize("phase", ["after-copy", "after-old-rename", "after-new-rename", "after-postcheck"])
def test_injected_failure_restores_exact_harmony_generation(harmony_root: Path, phase: str) -> None:
    before = _files(harmony_root / WORK)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise RuntimeError("injected " + phase)

    with pytest.raises(RuntimeError, match="injected " + phase):
        install(root_override=harmony_root, fail_at=fail_at)
    assert _files(harmony_root / WORK) == before
    operation, journal = _operation(harmony_root)
    assert journal["phase"] == ("failed-before-swap" if phase == "after-copy" else "rolled-back")
    if phase in {"after-new-rename", "after-postcheck"}:
        assert _files(operation / "failed-new") == journal["after"]
    assert preflight(root_override=harmony_root)["status"] == "pass-read-only"


def test_drifted_canonical_handoff_is_rejected(harmony_root: Path) -> None:
    handoff = Path(preflight(root_override=harmony_root)["preserved_handoff"])
    io_path(harmony_root / handoff).write_bytes(b"changed handoff")
    with pytest.raises(PipelineError, match="handoff differs"):
        preflight(root_override=harmony_root)


def test_original_receipt_strictly_rejects_current_projector_code(harmony_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "RECEIPT", RECEIPT)
    monkeypatch.setattr(installer, "RECEIPT_SHA256", ORIGINAL_RECEIPT_SHA256)
    for constant, old in ORIGINAL_NATIVE_PINS.items():
        monkeypatch.setattr(installer, constant, old)
    with pytest.raises(PipelineError, match="projection code differs from stage receipt"):
        preflight(root_override=harmony_root)


def test_current_native_runtime_pin_still_fails_closed(harmony_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "CURRENT_NATIVE_CONTENT_SHA256", "0" * 64)
    with pytest.raises(PipelineError, match="current native projector or content checker differs"):
        preflight(root_override=harmony_root)


def test_current_actual_master_projector_preserves_all_seven_rows(harmony_root: Path) -> None:
    checked = preflight(root_override=harmony_root)
    record = json.loads(io_path(installer.RECEIPT).read_bytes())
    projected = installer._bound_projection(STAGE, record)
    assert len(projected["rows"]) == checked["projection_rows"] == 7
    assert checked["current_projection_receipt_sha256"] == installer.CURRENT_PROJECTION_RECEIPT_SHA256
