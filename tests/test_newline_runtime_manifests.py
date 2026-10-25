"""Historical CRLF pins remain frozen while tests bind repository LF bytes."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.reconstruction.closure_verification import _call_validator_closure

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/newline-binding-cases.json").read_bytes())


@pytest.mark.parametrize("name", CASES)
def test_runtime_fixture_changes_only_line_endings_and_current_validator_closure(name):
    case = CASES[name]
    original = ROOT / case["original"]
    raw = original.read_bytes()
    assert sha256(raw).hexdigest() == case["sha256"]
    expected = deepcopy(json.loads(raw))
    for role in case["roles"]:
        binding = expected[role]
        code = (ROOT / binding["implementation_path"]).read_bytes()
        assert b"\r\n" not in code
        assert binding["implementation_sha256"] == sha256(code.replace(b"\n", b"\r\n")).hexdigest()
        binding["implementation_sha256"] = sha256(code).hexdigest()
    expected["validator"]["import_closure_sha256"] = _call_validator_closure(
        ROOT, expected["validator"]["implementation_path"], expected, manifest_path=original,
    )[0]
    assert json.loads((ROOT / case["fixture"]).read_bytes()) == expected
