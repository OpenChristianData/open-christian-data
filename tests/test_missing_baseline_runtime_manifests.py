"""Missing historical fixture aliases get isolated current-runtime bindings."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.reconstruction.closure_verification import _call_validator_closure


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/reconstruction-runtime"
CASES = json.loads((FIXTURES / "missing-baseline-bindings.json").read_bytes())
NOTICE_SHA = "f5f0ad69f414deb8067f6835a5a4b02668e4434800e7897badd50275788cf4e2"


@pytest.mark.parametrize("name", CASES)
def test_runtime_fixture_preserves_complete_frozen_record_except_declared_runtime_bindings(name):
    relative, frozen_sha = CASES[name]
    original = ROOT / relative
    raw = original.read_bytes()
    assert sha256(raw).hexdigest() == frozen_sha
    expected = deepcopy(json.loads(raw))
    for role in ("converter", "validator"):
        binding = expected[role]
        binding["implementation_sha256"] = sha256((ROOT / binding["implementation_path"]).read_bytes()).hexdigest()
    for authority in expected["authorities"]:
        if authority["path"].startswith(("build/", "ocd_kernel/")):
            content = (ROOT / authority["path"]).read_bytes()
            authority.update(bytes=len(content), sha256=sha256(content).hexdigest())
    if name == "hodge-systematic-theology-vol-2":
        authority = next(row for row in expected["authorities"] if row["name"] == "attribution-readme")
        assert authority["bytes"] == 1780 and authority["sha256"] == NOTICE_SHA
        authority["path"] = "tests/fixtures/reconstruction-runtime/hodge-vol2.README.source.md"
        assert sha256((ROOT / authority["path"]).read_bytes()).hexdigest() == NOTICE_SHA
    expected["validator"]["import_closure_sha256"] = _call_validator_closure(
        ROOT, expected["validator"]["implementation_path"], expected, manifest_path=original,
    )[0]
    actual = json.loads((FIXTURES / f"{name}.source-manifest.json").read_bytes())
    assert actual == expected
