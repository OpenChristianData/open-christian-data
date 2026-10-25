"""Explicit maintained-runtime receipts for historical installer rollback fixtures."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
BINDINGS = ROOT / "tests/fixtures/reconstruction-runtime/authorities/frozen-install-runtime-bindings.json"


def runtime_promoted_stage(original: Path, destination: Path, test_path: str) -> tuple[Path, str]:
    binding = json.loads(BINDINGS.read_bytes())[test_path]
    original_raw = (original / "stage-receipt.json").read_bytes()
    assert sha256(original_raw).hexdigest() == binding["original_receipt_sha256"]
    original_record = json.loads(original_raw)
    pins = binding["runtime_schema_pins"]
    assert set(pins) == set(original_record["schema_pins"])
    assert any(pins[key] != original_record["schema_pins"][key] for key in pins)
    assert {relative: sha256((ROOT / relative).read_bytes()).hexdigest() for relative in pins} == pins
    shutil.copytree(original, destination)
    maintained = deepcopy(original_record)
    maintained["schema_pins"] = pins
    assert {key: value for key, value in maintained.items() if key != "schema_pins"} == {
        key: value for key, value in original_record.items() if key != "schema_pins"
    }
    raw = (json.dumps(maintained, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (destination / "stage-receipt.json").write_bytes(raw)
    assert (original / "stage-receipt.json").read_bytes() == original_raw
    return destination, sha256(raw).hexdigest()
