"""Only current validator closure changes; retained source and candidates stay exact."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
import pytest
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf103104.json").read_bytes())
def _closure(case):
    rows = [{"path": path, "sha256": sha256((ROOT / path).read_bytes()).hexdigest()} for path in case["closure_inputs"]]
    return sha256((json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
@pytest.mark.parametrize("case", CASES, ids=lambda row: row["work_id"])
def test_complete_original_record_is_preserved(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    expected = deepcopy(json.loads(raw))
    live = _closure(case)
    assert live == case["runtime_closure_sha256"]
    assert live != expected["validator"]["import_closure_sha256"]
    expected["validator"]["import_closure_sha256"] = live
    assert json.loads((ROOT / case["manifest"]).read_bytes()) == expected
    SourceManifest.load(ROOT / case["manifest"], repository_root=ROOT)
@pytest.mark.parametrize("case", CASES, ids=lambda row: row["work_id"])
def test_original_package_and_historical_closure_are_not_claimed_current(case):
    manifest = SourceManifest.load(ROOT / case["original"], repository_root=ROOT)
    retained = CandidatePackage.load(Path(case["retained_package"]))
    assert retained.sha256 == case["retained_sha256"]
    assert retained.manifest["source_manifest"]["sha256"] == case["retained_source_manifest_sha256"]
    oracle = importlib.import_module(f"build.tei.{case['family']}_work_oracle")._oracle
    result = oracle(manifest, retained)
    assert result["import_closure_sha256"] == _closure(case)
    assert result["import_closure_sha256"] != manifest.record["validator"]["import_closure_sha256"]
    with pytest.raises(ValueError, match="candidate source manifest binding mismatch"):
        validate(manifest, retained, oracle)
