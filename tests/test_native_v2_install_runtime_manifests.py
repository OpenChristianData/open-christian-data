"""Native-V2 runtime fixtures preserve the complete historical source and profile."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path

import pytest
from ocd_kernel.reconstruction import SourceManifest

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/native-v2-install-runtime-cases.json").read_bytes())
assert {case["name"] for case in CASES} == {"charnock_vol2_native_v2", "luther_galatians_native_v2"}


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_complete_original_source_and_profile_records_preserved(case):
    original_raw = (ROOT / case["original"]).read_bytes()
    assert sha256(original_raw).hexdigest() == case["original_sha256"]
    original = json.loads(original_raw)
    current_raw = (ROOT / case["manifest"]).read_bytes()
    assert sha256(current_raw).hexdigest() == case["manifest_sha256"]
    current = json.loads(current_raw)
    assert current["converter"]["version"] == current["validator"]["version"] == "2"
    restored = deepcopy(current)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    for name, original_authority in (("reconstruction-profile", case["original_profile"]),
                                     ("attribution-readme", case["original_readme"])):
        index = next(i for i, row in enumerate(restored["authorities"]) if row["name"] == name)
        assert next(row for row in original["authorities"] if row["name"] == name) == original_authority
        restored["authorities"][index] = deepcopy(original_authority)
    assert restored == original
    old_profile_raw = (Path(case["original_stage"]) / case["original_profile"]["path"]).read_bytes()
    assert sha256(old_profile_raw).hexdigest() == case["original_profile"]["sha256"]
    assert len(old_profile_raw) == case["original_profile"]["bytes"]
    old_profile = json.loads(old_profile_raw)
    profile_raw = (ROOT / case["profile"]).read_bytes()
    assert sha256(profile_raw).hexdigest() == case["profile_sha256"]
    profile = json.loads(profile_raw)
    reverse_profile = deepcopy(profile)
    reverse_profile["producer_import_closure_sha256"] = old_profile["producer_import_closure_sha256"]
    assert reverse_profile == old_profile
    module = importlib.import_module(current["converter"]["implementation_path"][:-3].replace("/", "."))
    closure = list(module._closure(ROOT, ROOT / current["converter"]["implementation_path"]))
    assert closure == case["producer_closure"]
    assert sha256(_canonical(closure)).hexdigest() == profile["producer_import_closure_sha256"] == case["producer_closure_sha256"]
    loaded = SourceManifest.load(ROOT / case["manifest"], repository_root=ROOT)
    assert loaded.sha256 == sha256(current_raw).hexdigest()
    assert (ROOT / case["original"]).read_bytes() == original_raw


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_native_provenance_inverse_rejects_other_changes(case):
    from ocd_kernel.reconstruction import CandidatePackage
    from tests.current_frozen_install_context import _assert_native_provenance
    installer = importlib.import_module("build.tools.install_" + case["name"] + "_acceptance")
    retained = CandidatePackage.load(Path(case["original_stage"]) / installer.EVIDENCE / "inputs/package")
    baseline = SourceManifest.load(ROOT / case["manifest"], repository_root=ROOT)
    raw = retained.member_bytes("provenance.json")
    original = json.loads(raw)
    current = deepcopy(original)
    from ocd_kernel.reconstruction.contract import _runtime_binding
    current.update(source_manifest_sha256=baseline.sha256,
                   runtime=_runtime_binding(),
                   producer_import_closure=case["producer_closure"],
                   producer_import_closure_sha256=case["producer_closure_sha256"])
    _assert_native_provenance(raw, _canonical(current), baseline, case["original_sha256"])
    for field in ("publication", "source_sha256", "work_id", "runtime"):
        changed = deepcopy(current)
        changed[field] = "unbound-mutation"
        with pytest.raises(AssertionError):
            _assert_native_provenance(raw, _canonical(changed), baseline, case["original_sha256"])
