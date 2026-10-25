"""Current test routes conserve complete historical NPNF manifest records."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import pytest
from ocd_kernel.reconstruction import SourceManifest
ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf-work-late.json").read_bytes())
def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
@pytest.mark.parametrize("case", CASES, ids=lambda row: row["work_id"])
def test_complete_original_record_is_preserved(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    expected = deepcopy(json.loads(raw))
    if case["family"] == "npnf113":
        authority = next(a for a in expected["authorities"] if a["name"] == "aggregate-source-manifest")
        assert authority == case["aggregate_original_authority"]
        payload = (ROOT / case["runtime_aggregate"]).read_bytes()
        assert sha256(payload).hexdigest() == case["runtime_aggregate_sha256"]
        authority.update(path=case["runtime_aggregate"], sha256=sha256(payload).hexdigest(), bytes=len(payload))
        # Match the preparer's real ordered serializer, not the oracle's declaration echo.
        from build.tools import prepare_npnf113_work_candidates as preparer
        paths = (preparer.ORACLE, preparer.SOURCE_RULES, Path("ocd_kernel/reconstruction/contract.py"))
        assert [path.as_posix() for path in paths] == case["closure_inputs"]
        records = [{"path": path.as_posix(), "sha256": sha256((ROOT / path).read_bytes()).hexdigest()}
                   for path in paths]
        closure = preparer._sha(preparer._json(records))
        assert closure == case["runtime_closure_sha256"]
        expected["validator"]["import_closure_sha256"] = closure
    else:
        closure = sha256(_canonical([{ "path": path, "sha256": sha256((ROOT / path).read_bytes()).hexdigest() } for path in case["closure_inputs"]])).hexdigest()
        assert closure == case["runtime_closure_sha256"]
        for proof in case["implementation_EOL_proofs"]:
            actual = (ROOT / proof["path"]).read_bytes()
            assert sha256(actual).hexdigest() == proof["runtime_sha256"]
            assert b"\r\n" not in actual
            # The retained implementation differed only in its terminal newline.
            assert actual.endswith(b"\n")
            retained_serialization = actual[:-1] + b"\r\n"
            assert len(retained_serialization) == proof["original_bytes"]
            assert sha256(retained_serialization).hexdigest() == proof["original_sha256"]
        for key, value in case["runtime_changes"].items():
            if key.startswith("authorities."):
                owner, position, field = key.split(".")
                assert case["family"] == "npnf105" and position.isdigit() and field == "sha256"
                authority = expected[owner][int(position)]
                assert authority["name"] == "aggregate-oracle"
                assert authority["path"] == "build/tei/npnf105_oracle.py"
                current_code = (ROOT / authority["path"]).read_bytes()
                assert len(current_code) == authority["bytes"] and sha256(current_code).hexdigest() == value
                authority[field] = value
                continue
            owner, field = key.split(".")
            expected[owner][field] = value
    current = json.loads((ROOT / case["manifest"]).read_bytes())
    assert current == expected
    if case["family"] == "npnf113":
        restored = deepcopy(current)
        restored["validator"]["import_closure_sha256"] = json.loads(raw)["validator"]["import_closure_sha256"]
        authority = next(a for a in restored["authorities"] if a["name"] == "aggregate-source-manifest")
        authority.clear()
        authority.update(case["aggregate_original_authority"])
        assert restored == json.loads(raw)
    SourceManifest.load(ROOT / case["manifest"], repository_root=ROOT)
@pytest.mark.parametrize("case", CASES, ids=lambda row: row["work_id"])
def test_original_historical_binding_is_not_claimed_current(case):
    original = json.loads((ROOT / case["original"]).read_bytes())
    if case["family"] == "npnf113":
        with pytest.raises(ValueError, match="work-ticket-map authority bytes drifted"):
            SourceManifest.load(ROOT / case["aggregate_original_authority"]["path"], repository_root=ROOT)
    elif case["implementation_EOL_proofs"]:
        with pytest.raises(ValueError, match="implementation authority drifted"):
            SourceManifest.load(ROOT / case["original"], repository_root=ROOT)
    else:
        actual = sha256(_canonical([{ "path": path, "sha256": sha256((ROOT / path).read_bytes()).hexdigest() } for path in case["closure_inputs"]])).hexdigest()
        assert actual != original["validator"]["import_closure_sha256"]

@pytest.mark.parametrize("case", [row for row in CASES if row["family"] == "npnf105"], ids=lambda row: row["work_id"])
def test_retained_historical_candidate_does_not_claim_current_manifest_identity(case):
    from build.tei.npnf105_work_oracle import _oracle
    from ocd_kernel.reconstruction import CandidatePackage, validate
    original = json.loads((ROOT / case["original"]).read_bytes())
    current = SourceManifest.load(ROOT / case["manifest"], repository_root=ROOT)
    retained = CandidatePackage.load(Path(case["retained_package"]))
    assert retained.sha256 == case["retained_sha256"]
    assert retained.manifest["source_manifest"]["sha256"] == case["retained_source_manifest_sha256"]
    evidence = _oracle(current, retained)
    assert evidence["import_closure_sha256"] == case["runtime_closure_sha256"]
    assert evidence["import_closure_sha256"] != original["validator"]["import_closure_sha256"]
    with pytest.raises(ValueError, match="candidate source manifest binding mismatch"):
        validate(current, retained, _oracle)
