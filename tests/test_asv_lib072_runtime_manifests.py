"""Runtime-only ASV/LIB-072 copies preserve their historical source authority."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.reconstruction.closure_verification import (
    _call_validator_closure,
    check_validator_manifest_closure,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (ROOT / "tests/fixtures/reconstruction-runtime/next-binding-asv-lib072.json").read_bytes()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: Path(case["manifest"]).stem)
def test_runtime_fixture_preserves_complete_frozen_record(case):
    original = ROOT / case["original"]
    raw = original.read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    retained = json.loads(raw)
    expected = deepcopy(retained)
    fixture = ROOT / case["manifest"]
    live, _ = _call_validator_closure(
        ROOT, expected["validator"]["implementation_path"], expected,
        manifest_path=fixture,
    )
    assert live != retained["validator"]["import_closure_sha256"]
    expected["validator"]["import_closure_sha256"] = live
    assert json.loads(fixture.read_bytes()) == expected


@pytest.mark.parametrize("case", CASES, ids=lambda case: Path(case["manifest"]).stem)
def test_retained_originals_reject_current_validator_closure(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    checked = check_validator_manifest_closure(ROOT, case["original"])
    assert not checked.matches
    assert checked.declared_sha256 == json.loads(raw)["validator"]["import_closure_sha256"]
    assert checked.live_sha256 == json.loads((ROOT / case["manifest"]).read_bytes())["validator"]["import_closure_sha256"]
