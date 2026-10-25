"""Behavioral contracts for the shared metadata evidence operations."""
from __future__ import annotations

import copy
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from build.lib import source_metadata_contract as contract
from build.lib import source_metadata_evidence as evidence
from build.lib import source_metadata_review as review
from tests.test_source_metadata_review import _comparison_fixture, _receipt


def _write_carrier(path: Path, carrier: str, value: str) -> None:
    payload = contract.canonical_bytes({"title": value})
    if carrier == "plain":
        path.write_bytes(payload)
    elif carrier == "zip":
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("source.json", payload)
    else:
        with tarfile.open(path, "w") as archive:
            info = tarfile.TarInfo("source.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


@pytest.mark.parametrize("carrier", ["plain", "zip", "tar"])
def test_inspection_reports_changed_bytes_while_verification_rejects_them(
    tmp_path: Path, carrier: str,
) -> None:
    path = tmp_path / f"source.{carrier}"
    _write_carrier(path, carrier, "Old")
    request = {"id": "title", "path": path.name, "kind": "json_pointer",
               "value": "/title", "role": "primary"}
    if carrier != "plain":
        request["member"] = "source.json"
    binding = evidence.extract_bindings(tmp_path, [request])["bindings"]["title"]
    assert binding["locator"]["expected"] == "Old"
    evidence.BindingVerifier(tmp_path).verify(binding)
    assert evidence.inspect_binding(tmp_path, binding, "title")["status"] == "unchanged"

    _write_carrier(path, carrier, "New")
    observed = evidence.inspect_binding(tmp_path, binding, "title")
    assert observed["status"] == "changed"
    assert observed["current"]["selector_value"] == "New"
    assert observed["selector_status"] == "changed"
    assert {"file_hash", "selector_value"} <= set(observed["changes"])
    with pytest.raises(contract.EvidenceError, match="hash mismatch"):
        evidence.BindingVerifier(tmp_path).verify(binding)
    assert binding["locator"]["expected"] == "Old"
    assert evidence.extract_bindings(tmp_path, [request])["bindings"]["title"]["locator"]["expected"] == "New"


def test_extraction_rechecks_fresh_bytes_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "source.txt"
    path.write_bytes(b"old\n")
    read = Path.read_bytes
    changed = False

    def read_then_change(current: Path) -> bytes:
        nonlocal changed
        data = read(current)
        if current == path and not changed:
            changed = True
            path.write_bytes(b"new\n")
        return data

    monkeypatch.setattr(Path, "read_bytes", read_then_change)
    request = {"id": "text", "path": path.name, "kind": "text",
               "encoding": "utf-8", "start_line": 1, "end_line": 1, "role": "primary"}
    with pytest.raises(contract.EvidenceError, match="hash mismatch"):
        evidence.extract_bindings(tmp_path, [request])


def _current_receipt(tmp_path: Path) -> dict:
    root, work, decisions, selection, _, _, _ = _comparison_fixture(tmp_path)
    receipt, _, _ = review.preflight(
        root, worklist_path=work, decisions_path=decisions, selection_path=selection,
    )
    return receipt


@pytest.mark.parametrize("name,module", [
    ("evidence_engine", evidence), ("metadata_contract", contract),
])
def test_current_receipt_binds_moved_implementation_and_detects_drift(
    tmp_path: Path, name: str, module,
) -> None:
    receipt = _current_receipt(tmp_path)
    assert receipt["format"] == "source-metadata-review-receipt-v3"
    assert receipt["artifacts"][name] == review.file_identity(Path(module.__file__))
    assert review.verify_receipt(receipt) == []
    snapshot = tmp_path / f"{name}.py"
    snapshot.write_bytes(Path(module.__file__).read_bytes())
    receipt["artifacts"][name] = review.file_identity(snapshot)
    assert review.verify_receipt(receipt) == []
    snapshot.write_bytes(snapshot.read_bytes() + b"\n# changed implementation\n")
    issues = review.verify_receipt(receipt)
    assert any(issue["artifact"] == name for issue in issues)


@pytest.mark.parametrize("name", ["evidence_engine", "metadata_contract"])
def test_current_receipt_rejects_missing_implementation_identity(tmp_path: Path, name: str) -> None:
    receipt = _current_receipt(tmp_path)
    del receipt["artifacts"][name]
    with pytest.raises(contract.MetadataError, match="missing a required"):
        review.verify_receipt(receipt)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_historical_receipts_keep_their_original_requirements(tmp_path: Path, version: str) -> None:
    receipt, artifact = _receipt(tmp_path)
    receipt["format"] = f"source-metadata-review-receipt-{version}"
    if version == "v2":
        receipt["artifacts"]["semantic_alert_engine"] = review.file_identity(artifact)
    assert review.verify_receipt(receipt) == []
    stale = copy.deepcopy(receipt)
    artifact.write_bytes(b"changed")
    assert review.verify_receipt(stale)

@pytest.mark.parametrize("kind", ["json_pointer", "xml_id"])
def test_changed_structured_locator_inspection_preserves_historical_encoding_behavior(
    tmp_path: Path, kind: str,
) -> None:
    path = tmp_path / "source"
    before = b'{"title":"Old"}' if kind == "json_pointer" else b'<p id="title">Old</p>'
    after = before.replace(b"Old", b"New")
    path.write_bytes(before)
    request = {"id": "title", "path": path.name, "kind": kind,
               "value": "/title" if kind == "json_pointer" else "title", "role": "primary"}
    binding = evidence.extract_bindings(tmp_path, [request])["bindings"]["title"]
    # Historical impact reports observe JSON as UTF-8 and XML by its declaration.
    # The misleading encoding remains invalid for strict verification.
    binding["encoding"] = "latin-1"
    path.write_bytes(after)
    observed = evidence.inspect_binding(tmp_path, binding, "title")
    assert observed["status"] == "changed"
    assert observed["current"]["selector_value"] == "New"
    rebound = {**binding, "sha256": contract.sha256_bytes(after), "bytes": len(after)}
    with pytest.raises(contract.EvidenceError, match="does not use a declared"):
        evidence.BindingVerifier(tmp_path).verify(rebound)

