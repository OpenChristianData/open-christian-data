"""Four retained Standard Ebooks routes get test-only current dependency bindings."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from build.tei.se_candidate_oracle import _closure
from ocd_kernel.reconstruction import SourceManifest


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (ROOT / "tests/fixtures/reconstruction-runtime/next-binding-se-four.json").read_bytes()
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: Path(case["manifest"]).stem)
def test_runtime_copy_preserves_complete_frozen_source_record(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    retained = json.loads(raw)
    expected = deepcopy(retained)
    dependency = next(row for row in expected["authorities"] if row["name"] == "producer-dependency-006")
    assert dependency["path"] == "ocd_kernel/reconstruction/contract.py"
    assert dependency["role"] == "implementation-dependency"
    content = (ROOT / dependency["path"]).read_bytes()
    dependency.update(sha256=sha256(content).hexdigest(), bytes=len(content))
    expected["producer_import_closure_sha256"] = _closure(
        ROOT, ROOT / expected["converter"]["implementation_path"]
    )[0]
    expected["validator"]["import_closure_sha256"] = _closure(ROOT)[0]
    assert expected["producer_import_closure_sha256"] != retained["producer_import_closure_sha256"]
    assert expected["validator"]["import_closure_sha256"] != retained["validator"]["import_closure_sha256"]
    assert json.loads((ROOT / case["manifest"]).read_bytes()) == expected


@pytest.mark.parametrize("case", CASES, ids=lambda case: Path(case["manifest"]).stem)
def test_original_retained_dependency_binding_still_fails_closed(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    with pytest.raises(ValueError, match="producer-dependency-006 authority bytes drifted"):
        SourceManifest.load(ROOT / case["original"], repository_root=ROOT)


@pytest.mark.parametrize("case", CASES, ids=lambda case: Path(case["manifest"]).stem)
def test_current_runtime_dependency_rejects_changed_contract_bytes(case, monkeypatch):
    dependency = ROOT / "ocd_kernel/reconstruction/contract.py"
    read_bytes = Path.read_bytes

    def changed_dependency(path):
        raw = read_bytes(path)
        return raw + b"\n# test-only dependency mutation\n" if path.samefile(dependency) else raw

    # Simulate changed input bytes without editing shared source files on disk.
    monkeypatch.setattr(Path, "read_bytes", changed_dependency)
    with pytest.raises(ValueError, match="producer-dependency-006 authority bytes drifted"):
        SourceManifest.load(ROOT / case["manifest"], repository_root=ROOT)
