"""Retain original NPNF103 declarations while proving its current validator."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from ocd_kernel.reconstruction.closure_verification import _call_validator_closure
ROOT = Path(__file__).resolve().parents[1]
CASE = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf103.json").read_bytes())[0]


def test_complete_original_source_record_preserved():
    raw = (ROOT / CASE["original"]).read_bytes()
    assert sha256(raw).hexdigest() == CASE["original_sha256"]
    expected = deepcopy(json.loads(raw))
    live, _ = _call_validator_closure(ROOT, expected["validator"]["implementation_path"], expected, manifest_path=ROOT / CASE["original"])
    assert live != expected["validator"]["import_closure_sha256"]
    expected["validator"]["import_closure_sha256"] = live
    assert json.loads((ROOT / CASE["manifest"]).read_bytes()) == expected


def test_historical_validator_closure_is_not_current():
    record = json.loads((ROOT / CASE["original"]).read_bytes())
    assert sha256((ROOT / CASE["original"]).read_bytes()).hexdigest() == CASE["original_sha256"]
    live, _ = _call_validator_closure(ROOT, record["validator"]["implementation_path"], record, manifest_path=ROOT / CASE["original"])
    assert live != record["validator"]["import_closure_sha256"]
