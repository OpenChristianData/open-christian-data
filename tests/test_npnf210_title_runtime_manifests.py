"""Exact original work authorities remain immutable while current metadata advances."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import pytest
from build.tei.npnf_ambrose_duties_faith_title_v3_oracle import _closure
from ocd_kernel.reconstruction import SourceManifest
ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf210-title.json").read_bytes())


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["work_id"])
def test_complete_record_preserved_with_exact_historical_work_authority(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    expected = deepcopy(json.loads(raw))
    authority = next(a for a in expected["authorities"] if a["name"] == "work-identity")
    retained = (ROOT / case["historical_work_fixture"]).read_bytes()
    assert sha256(retained).hexdigest() == authority["sha256"] and len(retained) == authority["bytes"]
    authority["path"] = case["historical_work_fixture"]
    expected["validator"]["import_closure_sha256"] = _closure(ROOT)
    assert json.loads((ROOT / case["manifest"]).read_bytes()) == expected


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["work_id"])
def test_original_acquired_work_binding_rejects_later_current_metadata(case):
    assert sha256((ROOT / case["original"]).read_bytes()).hexdigest() == case["original_sha256"]
    with pytest.raises(ValueError, match="work-identity authority bytes drifted"):
        SourceManifest.load(ROOT / case["original"], repository_root=ROOT)
