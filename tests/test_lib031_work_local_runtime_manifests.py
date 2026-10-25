"""Current ten-work LIB-031 successors preserve every historical source binding."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from build.tei.lib031_work_local_oracle import _import_closure_sha256
from build.tools.generate_lib031_work_manifests import manifest_bytes
from ocd_kernel.reconstruction.closure_verification import check_validator_manifest_closure


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-lib031-work-local.json").read_bytes())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["work_id"])
def test_runtime_copy_preserves_complete_original_record(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    expected = deepcopy(json.loads(raw))
    live = _import_closure_sha256(ROOT)
    assert live != expected["validator"]["import_closure_sha256"]
    expected["validator"]["import_closure_sha256"] = live
    fixture = (ROOT / case["manifest"]).read_bytes()
    assert json.loads(fixture) == expected
    assert fixture == manifest_bytes(ROOT, case["work_id"])


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["work_id"])
def test_historical_work_local_closure_is_not_current(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    checked = check_validator_manifest_closure(ROOT, case["original"])
    assert not checked.matches
    assert checked.live_sha256 == _import_closure_sha256(ROOT)
