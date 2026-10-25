"""Exact original nine-work identities survive later accepted metadata."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import pytest
from build.tei.npnf_ambrose_work_local_oracle import _closure
from ocd_kernel.reconstruction.closure_verification import check_validator_manifest_closure
ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf210-work.json").read_bytes())


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["work_id"])
def test_complete_original_record_and_authority_bytes_preserved(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    expected = deepcopy(json.loads(raw))
    for support in case["supports"]:
        authority = next(a for a in expected["authorities"] if a["name"] == support["authority"])
        retained = (ROOT / support["fixture"]).read_bytes()
        assert sha256(retained).hexdigest() == authority["sha256"] == support["sha256"]
        assert len(retained) == authority["bytes"] == support["bytes"]
        assert authority["path"] == support["original_path"]
        authority["path"] = support["fixture"]
    expected["validator"]["import_closure_sha256"] = _closure(ROOT)
    assert json.loads((ROOT / case["manifest"]).read_bytes()) == expected


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["work_id"])
def test_original_validator_closure_is_not_current(case):
    assert sha256((ROOT / case["original"]).read_bytes()).hexdigest() == case["original_sha256"]
    assert not check_validator_manifest_closure(ROOT, case["original"]).matches
