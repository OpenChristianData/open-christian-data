"""Versioned Watson runtime refresh preserves accepted text and prior evidence."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei import acceptance

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.requires_local_artifacts
CASES = [
    ("watson-beatitudes", "BEATITUDES_ACCEPTANCE", "6dd270d4ffe937d7943f65c6b6960fb0080724f55d0449cf1d7b62e8e587989c", "31dbf2a9594059c86dd9fb3bec56b23e13192f98905c43bcc1687cca6d40e919"),
    ("watson-divine-contentment", "DIVINE_CONTENTMENT", "f3722a961f60ef11012744386d8dbcf924016181c112b6b09592d774b9e0d42a", "2bf652d2cec38d17da378409afcf50abe5d537afa092e7bad245c683bc66da80"),
]


@pytest.mark.parametrize("work,prefix,original_sha,supplement_sha", CASES)
def test_current_runtime_preserves_complete_historical_record_and_substantive_members(work, prefix, original_sha, supplement_sha):
    original_path = ROOT / f"sources/structured-text/{work}/runtime-proof-20261021.source-manifest.json"
    original_raw = original_path.read_bytes()
    assert sha256(original_raw).hexdigest() == original_sha
    original = json.loads(original_raw)
    current_path = ROOT / getattr(acceptance, prefix + "_MANIFEST")
    current = SourceManifest.load(current_path, repository_root=ROOT)
    assert current.sha256 == getattr(acceptance, prefix + "_MANIFEST_SHA")
    restored = deepcopy(json.loads(current_path.read_bytes()))
    changed = set()
    for before, after in zip(original["authorities"], restored["authorities"], strict=True):
        if before != after:
            assert after["role"] == "implementation-dependency"
            changed.add(after["name"])
            after["bytes"], after["sha256"] = before["bytes"], before["sha256"]
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
    assert changed == ({"closure-identities", "closure-acquisitions", "closure-storage-topology", "closure-reconstruction-contract"} if work == "watson-beatitudes" else {"closure-identities", "closure-storage-topology", "closure-contract"})
    previous_path = ROOT / f"sources/structured-text/{work}/runtime-supplement-20261021.json"
    assert sha256(previous_path.read_bytes()).hexdigest() == supplement_sha
    previous = json.loads(previous_path.read_bytes())
    for binding in [previous["acceptance"], *previous["bindings"]]:
        raw = (ROOT / binding["path"]).read_bytes()
        assert len(raw) == binding["bytes"] and sha256(raw).hexdigest() == binding["sha256"]
    retained = CandidatePackage.load(ROOT / f"library/works/{work}/integration/runtime-proof-20261021/current-candidate/package")
    package = CandidatePackage.load(ROOT / getattr(acceptance, prefix + "_EVIDENCE"))
    assert package.sha256 == getattr(acceptance, prefix + "_PACKAGE_SHA")
    assert package.member_names == retained.member_names
    for name in package.member_names:
        if name != "manifest.json":
            assert package.member_bytes(name) == retained.member_bytes(name)
    accepted = acceptance.validate_acceptance(ROOT / previous["acceptance"]["path"], root=ROOT)
    assert accepted["promotion"]["status"] == "promoted"
    assert original_path.read_bytes() == original_raw
