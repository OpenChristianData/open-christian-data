"""Exact Baltimore Gutenberg source pins, mutation, rollback, and live row."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from build.tools import install_pg_baltimore_no2 as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[1]


def _bytes(path: Path) -> bytes:
    return _io_path(path).read_bytes()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def _sha(path: Path) -> str:
    return sha256(_bytes(path)).hexdigest()


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, dict, dict]:
    pins = json.loads(_bytes(installer.PINS))
    record = json.loads(_bytes(Path(pins["receipt"])))
    stage = Path(record["stage_root"])
    fixture = tmp_path / "root"
    assert _sha(installer.PINS) == installer.PINS_SHA
    assert _sha(Path(pins["receipt"])) == pins["receipt_sha256"]
    assert _files(stage / installer.WORK) == record["after"]
    for relative, expected in record["before"].items():
        payload = _bytes(stage / installer.WORK / relative)
        assert sha256(payload).hexdigest() == record["after"][relative]
        if sha256(payload).hexdigest() != expected:
            value = json.loads(payload)
            if relative == "work.json":
                assert value["textual_forms"][0]["editions"][0].pop("category") == "catechisms"
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
                raise AssertionError("Acquisition must retain its complete original bytes")
            payload = _json(value)
        assert sha256(payload).hexdigest() == expected
        destination = _io_path(fixture / installer.WORK / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    assert _files(fixture / installer.WORK) == record["before"]
    for path in stage.rglob("*"):
        if not _io_path(path).is_file():
            continue
        relative = path.relative_to(stage)
        if relative.is_relative_to(installer.WORK):
            continue
        destination = fixture / relative
        _io_path(destination.parent).mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(path), _io_path(destination))
    original_record = json.loads(_bytes(Path(pins["receipt"])))
    record["canonical_root"] = fixture.as_posix()
    assert dict(record, canonical_root=original_record["canonical_root"]) == original_record
    receipt = tmp_path / "r.json"
    receipt.write_bytes(_json(record))
    pins["receipt"] = receipt.as_posix()
    pins["receipt_sha256"] = _sha(receipt)
    fixture_pins = tmp_path / "pins.json"
    fixture_pins.write_bytes(_json(pins))
    monkeypatch.setattr(installer, "PINS", fixture_pins)
    monkeypatch.setattr(installer, "PINS_SHA", _sha(fixture_pins))
    return fixture, receipt, record, pins


def test_exact_frozen_receipt_and_pin_mutation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pins = json.loads(_bytes(installer.PINS))
    receipt = Path(pins["receipt"])
    assert _sha(installer.PINS) == installer.PINS_SHA
    assert _sha(receipt) == pins["receipt_sha256"]
    _root, historical_receipt, _record, _pins = _fixture(tmp_path, monkeypatch)
    assert installer.preflight(historical_receipt)["status"] == "ready-for-review"
    monkeypatch.setattr(installer, "PINS_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="pin index changed"):
        installer.preflight(receipt)


def test_source_byte_mutation_rejected(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, receipt, _record, _pins = _fixture(tmp_path, monkeypatch)
    source = fixture / installer.SOURCE
    original = _bytes(source)
    assert b"A" in original
    _io_path(source).write_bytes(original.replace(b"A", b"B", 1))
    with pytest.raises(PipelineError, match="retained Baltimore TXT"):
        installer.preflight(receipt)


def test_isolated_rollback_and_actual_master(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, receipt, record, pins = _fixture(tmp_path, monkeypatch)
    target = fixture / installer.WORK
    before = _files(target)
    assert installer.preflight(receipt)["status"] == "ready-for-review"

    def fail_after_swap(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected Baltimore work swap failure")

    with pytest.raises(RuntimeError, match="injected Baltimore work swap failure"):
        installer.install(receipt, expected_receipt_sha256=pins["receipt_sha256"],
                          fail_at=fail_after_swap)
    assert _files(target) == before
    journals = list((fixture / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(_bytes(journals[0]))["phase"] == "rolled-back"

    result = installer.install(receipt, expected_receipt_sha256=pins["receipt_sha256"])
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(target) == record["after"]


def test_original_preflight_rejects_current_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, receipt, record, _pins = _fixture(tmp_path, monkeypatch)
    target = fixture / installer.WORK
    resolved = target.resolve(strict=True)
    assert resolved.is_relative_to(fixture.resolve(strict=True)) and not target.is_symlink() and not target.is_junction()
    shutil.rmtree(_io_path(target))
    shutil.copytree(_io_path(ROOT / installer.WORK), _io_path(target))
    assert _files(target) != record["before"]
    with pytest.raises(PipelineError, match="live preimage or staged generation changed"):
        installer.preflight(receipt)
