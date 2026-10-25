"""Recover only exact frozen three-file openMGH preimages in temporary test roots."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def historical_exact_work_root(root: Path, destination: Path, manifest_path: Path,
                               freeze_path: Path, expected_freeze_sha256: str) -> Path:
    freeze_raw = _io_path(freeze_path).read_bytes()
    assert sha256(freeze_raw).hexdigest() == expected_freeze_sha256
    frozen = json.loads(freeze_raw)
    manifest_raw = _io_path(manifest_path).read_bytes()
    assert manifest_path.relative_to(root).as_posix() == frozen["manifest"]["path"]
    assert sha256(manifest_raw).hexdigest() == frozen["manifest"]["sha256"]
    manifest = json.loads(manifest_raw)
    assert {e["work_id"] for e in manifest["works"]} == {e["work_id"] for e in frozen["works"]}
    for entry in manifest["works"]:
        work_id = entry["work_id"]
        pin = next(p for p in frozen["works"] if p["work_id"] == work_id)
        receipt_path = Path(frozen["stage_home"]) / pin["stage_receipt"]
        receipt_raw = _io_path(receipt_path).read_bytes()
        assert sha256(receipt_raw).hexdigest() == pin["stage_receipt_sha256"]
        receipt = json.loads(receipt_raw)
        assert receipt["work_id"] == work_id and receipt["status"] == "staged-only"
        work = Path(entry["work_path"]).parent
        assert receipt["before"]["work.json"] == entry["work_sha256"]
        acquisition = Path(entry["acquisition_path"]).relative_to(work).as_posix()
        assert receipt["before"][acquisition] == entry["acquisition_sha256"]
        stage = Path(receipt["stage_root"])
        for relative in receipt["before"]:
            assert sha256(_io_path(stage / work / relative).read_bytes()).hexdigest() == receipt["after"][relative]
        _recover_generation(stage, destination, work_id, receipt["before"],
                            category=entry["category"], language=entry["language"])
        assert _files(destination / work) == receipt["before"]
    return destination


def _recover_generation(root: Path, destination: Path, work_id: str, before: dict[str, str], *, category: str = "prose", language: str = "la") -> None:
    work = Path("library/works") / work_id
    assert len(before) == 3 and "work.json" in before and "state.json" in before
    for relative, expected in before.items():
        raw = _io_path(root / work / relative).read_bytes()
        if sha256(raw).hexdigest() != expected:
            value = json.loads(raw)
            if relative == "work.json":
                assert len(value["textual_forms"]) == len(value["textual_forms"][0]["editions"]) == 1
                edition = value["textual_forms"][0]["editions"][0]
                assert edition.pop("category") == category
                assert edition.pop("language") == language
            elif relative == "state.json":
                editions = [t for t in value["targets"] if t["target_type"] == "edition"]
                acquisitions = [t for t in value["targets"] if t["target_type"] == "acquisition"]
                assert len(editions) == len(acquisitions) == 1
                target = editions[0]
                assert target["stage"] == "accepted"
                target["stage"] = "acquired"
                target.pop("reason")
                target["updated_at"] = acquisitions[0]["updated_at"]
                assert target["evidence"][-2].endswith("/master.tei.xml")
                assert target["evidence"][-1].endswith("/acceptance.json")
                target["evidence"] = target["evidence"][:-2]
            else:
                raise AssertionError("Acquisition bytes must already match the historical receipt")
            raw = _json(value)
        assert sha256(raw).hexdigest() == expected
        target = _io_path(destination / work / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert _files(destination / work) == before


def historical_nested_installer_context(root: Path, destination: Path, freeze_path: Path,
                                        expected_freeze_sha256: str,
                                        source_bindings: tuple[tuple[Path, str], ...]) -> tuple[Path, Path, str]:
    raw = _io_path(freeze_path).read_bytes()
    assert sha256(raw).hexdigest() == expected_freeze_sha256
    frozen = json.loads(raw)
    for pin in frozen["works"]:
        work_id = pin["work_id"]
        stage = Path(pin["stage_root"]) if "stage_root" in pin else Path(frozen["stage_home"]) / work_id
        receipt_raw = _io_path(stage / "stage-receipt.json").read_bytes()
        assert sha256(receipt_raw).hexdigest() == pin["stage_receipt_sha256"]
        receipt = json.loads(receipt_raw)
        assert receipt["work_id"] == work_id and receipt["status"] == "staged-only"
        for relative in receipt["before"]:
            assert sha256(_io_path(stage / "library/works" / work_id / relative).read_bytes()).hexdigest() == receipt["after"][relative]
        _recover_generation(stage, destination, work_id, receipt["before"])
    # Only the exact source/package/receipt needed by this installer is copied.
    for logical, expected in source_bindings:
        payload = _io_path(root / logical).read_bytes()
        assert sha256(payload).hexdigest() == expected
        target = _io_path(destination / logical)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert sha256(target.read_bytes()).hexdigest() == expected
    current = dict(frozen, canonical_root=destination.as_posix())
    derived = _json(current)
    restored = json.loads(derived)
    restored["canonical_root"] = frozen["canonical_root"]
    assert restored == frozen
    path = destination / "historical-freeze-context.json"
    path.write_bytes(derived)
    return destination, path, sha256(derived).hexdigest()


def historical_receipt_context(root: Path, destination: Path, receipt_path: Path,
                               expected_receipt_sha256: str,
                               source_bindings: tuple[tuple[Path, str], ...]) -> tuple[Path, Path, str]:
    raw = _io_path(receipt_path).read_bytes()
    assert sha256(raw).hexdigest() == expected_receipt_sha256
    record = json.loads(raw)
    assert record["status"] == "staged-only"
    stage = Path(record["stage_root"])
    for relative in record["before"]:
        assert sha256(_io_path(stage / "library/works" / record["work_id"] / relative).read_bytes()).hexdigest() == record["after"][relative]
    _recover_generation(stage, destination, record["work_id"], record["before"], category=record["category"], language=record["language"])
    for logical, digest in source_bindings:
        payload = _io_path(root / logical).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(destination / logical)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert sha256(target.read_bytes()).hexdigest() == digest
    context = dict(record, canonical_root=destination.as_posix())
    derived = _json(context)
    restored = json.loads(derived)
    restored["canonical_root"] = record["canonical_root"]
    assert restored == record
    path = destination / "historical-receipt-context.json"
    path.write_bytes(derived)
    return destination, path, sha256(derived).hexdigest()


def historical_docsouth_context(root: Path, destination: Path, freeze_path: Path,
                                expected_freeze_sha256: str) -> tuple[Path, Path, str]:
    raw = _io_path(freeze_path).read_bytes()
    assert sha256(raw).hexdigest() == expected_freeze_sha256
    frozen = json.loads(raw)
    direct_raw = _io_path(Path(frozen["direct_receipt"])).read_bytes()
    assert sha256(direct_raw).hexdigest() == frozen["direct_receipt_sha256"]
    direct = json.loads(direct_raw)
    inputs = {frozen["inventory_path"]: frozen["inventory_sha256"]}
    for pin in frozen["works"]:
        work_id = pin["work_id"]
        stage = Path(frozen["stage_home"]) / work_id
        receipt_raw = _io_path(stage / "stage-receipt.json").read_bytes()
        assert sha256(receipt_raw).hexdigest() == pin["stage_receipt_sha256"]
        record = json.loads(receipt_raw)
        assert record["work_id"] == work_id and record["status"] == "staged-only"
        work = Path("library/works") / work_id
        # The retained after generation predates later current-state qualifications.
        for relative in record["before"]:
            payload = _io_path(stage / work / relative).read_bytes()
            assert sha256(payload).hexdigest() == record["after"][relative]
        _recover_generation(stage, destination, work_id, record["before"],
                            category=record["category"], language=record["language"])
        acquisition_relative = next(p for p in record["before"] if p not in ("work.json", "state.json"))
        acquisition = json.loads(_io_path(destination / work / acquisition_relative).read_bytes())
        for member in acquisition["retained_files"]:
            if member["path"] in inputs:
                assert inputs[member["path"]] == member["sha256"]
            inputs[member["path"]] = member["sha256"]
        entry = next(e for e in direct["selected_works"] if e["work_id"] == work_id)
        inputs[entry["acquisition_receipt_path"]] = pin["acquisition_receipt_sha256"]
    for logical, digest in inputs.items():
        payload = _io_path(root / logical).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(destination / logical)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert sha256(target.read_bytes()).hexdigest() == digest
    context = dict(frozen, canonical_root=destination.as_posix())
    derived = _json(context)
    restored = json.loads(derived)
    restored["canonical_root"] = frozen["canonical_root"]
    assert restored == frozen
    path = destination / "historical-freeze-context.json"
    path.write_bytes(derived)
    return destination, path, sha256(derived).hexdigest()


DOCSOUTH_RIGHTS_APPENDIX = "\n## Current rights preparation — October 9, 2026\n".encode("utf-8")


def historical_docsouth_source_note(raw: bytes, expected_sha256: str) -> bytes:
    """Recover only the complete note whose original bytes match its frozen index."""
    if sha256(raw).hexdigest() == expected_sha256:
        return raw
    if raw.count(DOCSOUTH_RIGHTS_APPENDIX) == 1:
        original, _appendix = raw.split(DOCSOUTH_RIGHTS_APPENDIX, 1)
        if sha256(original).hexdigest() == expected_sha256:
            return original
    raise ValueError("Source note does not preserve the frozen notice-index preimage")
