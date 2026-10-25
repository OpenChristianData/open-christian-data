"""Exact historical single- and dual-edition MGH freeze contexts for tests."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def mgh_before_bytes(stage: Path, record: dict, work_id: str) -> dict[str, bytes]:
    work = Path("library/works") / work_id
    assert record["work_id"] == work_id and record["status"] == "staged-only"
    assert _files(stage / work) == record["after"]
    assert 3 <= len(record["before"]) <= 4
    revised_work = json.loads(_io_path(stage / work / "work.json").read_bytes())
    forms = revised_work["textual_forms"]
    assert len(forms) == 1 and 1 <= len(forms[0]["editions"]) <= 2
    edition_acquisitions = {e["edition_id"]: e["acquisition_ids"][0] for e in forms[0]["editions"]}
    result = {}
    for relative, expected in record["before"].items():
        raw = _io_path(stage / work / relative).read_bytes()
        assert sha256(raw).hexdigest() == record["after"][relative]
        if sha256(raw).hexdigest() != expected:
            value = json.loads(raw)
            if relative == "work.json":
                for edition in value["textual_forms"][0]["editions"]:
                    assert edition.pop("category") in {"prose", "poetry"}
                    assert edition.pop("language") == "la"
            elif relative == "state.json":
                acquisitions = {t["target_id"]: t for t in value["targets"] if t["target_type"] == "acquisition"}
                for target in value["targets"]:
                    if target["target_type"] != "edition":
                        continue
                    assert target["stage"] == "accepted"
                    target["stage"] = "acquired"
                    target.pop("reason")
                    target["updated_at"] = acquisitions[edition_acquisitions[target["target_id"]]]["updated_at"]
                    assert target["evidence"][-2].endswith("/master.tei.xml")
                    assert target["evidence"][-1].endswith("/acceptance.json")
                    target["evidence"] = target["evidence"][:-2]
            else:
                raise AssertionError("An acquisition or credit must already equal the complete before hash")
            raw = _json(value)
        assert sha256(raw).hexdigest() == expected
        result[relative] = raw
    assert set(result) == set(record["before"])
    return result


def historical_mgh_freeze_context(root: Path, destination: Path, freeze_path: Path,
                                  expected_sha256: str,
                                  source_bindings: tuple[tuple[Path, str], ...]) -> tuple[Path, Path, str]:
    raw = _io_path(freeze_path).read_bytes()
    assert sha256(raw).hexdigest() == expected_sha256
    frozen = json.loads(raw)
    direct_raw = _io_path(Path(frozen["direct_receipt"])).read_bytes()
    assert sha256(direct_raw).hexdigest() == frozen["direct_receipt_sha256"]
    if "works" in frozen:
        selections = frozen["works"]
    else:
        selections = [{"work_id": frozen["work_id"], "stage_root": frozen["stage_root"],
                       "stage_receipt_sha256": frozen["stage_receipt_sha256"]}]
    assert selections
    for pin in selections:
        work_id = pin["work_id"]
        stage = Path(pin["stage_root"]) if "stage_root" in pin else Path(frozen["stage_home"]) / work_id
        receipt_raw = _io_path(stage / "stage-receipt.json").read_bytes()
        assert sha256(receipt_raw).hexdigest() == pin["stage_receipt_sha256"]
        record = json.loads(receipt_raw)
        for relative, payload in mgh_before_bytes(stage, record, work_id).items():
            target = _io_path(destination / "library/works" / work_id / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        assert _files(destination / "library/works" / work_id) == record["before"]
    for logical, digest in source_bindings:
        payload = _io_path(root / logical).read_bytes()
        assert sha256(payload).hexdigest() == digest
        target = _io_path(destination / logical)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert sha256(target.read_bytes()).hexdigest() == digest
    context = dict(frozen, canonical_root=destination.as_posix())
    assert dict(context, canonical_root=frozen["canonical_root"]) == frozen
    path = destination / "historical-mgh-freeze-context.json"
    payload = _json(context)
    path.write_bytes(payload)
    return destination, path, sha256(payload).hexdigest()
