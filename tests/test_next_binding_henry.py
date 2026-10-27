"""Keep retained manifests intact while testing their current validator closures."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.reconstruction.closure_verification import (
    _call_producer_closure,
    _call_validator_closure,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (ROOT / "tests/fixtures/reconstruction-runtime/next-binding-henry.json").read_bytes()
)


@pytest.mark.parametrize("case", CASES, ids=[Path(row["manifest"]).name for row in CASES])
def test_runtime_copy_preserves_complete_historical_record(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    expected = json.loads(raw)
    for role in case.get("implementation_roles", []):
        assert role == "validator"
        binding = expected[role]
        binding["implementation_sha256"] = sha256((ROOT / binding["implementation_path"]).read_bytes()).hexdigest()
    for support in case.get("supports", []):
        assert support["kind"] == "historical"
        authority = next(row for row in expected["authorities"] if row["name"] == support["authority"])
        historical = (ROOT / support["fixture"]).read_bytes()
        assert len(historical) == authority["bytes"]
        assert sha256(historical).hexdigest() == authority["sha256"] == support["original_sha256"]
        authority["path"] = support["fixture"]
    live, _ = _call_validator_closure(
        ROOT, expected["validator"]["implementation_path"], expected,
        manifest_path=ROOT / case["original"],
    )
    expected["validator"]["import_closure_sha256"] = live
    if "runtime_profile" in case:
        authority = next(row for row in expected["authorities"] if row["name"] == "reconstruction-profile")
        raw_profile = (ROOT / authority["path"]).read_bytes()
        assert sha256(raw_profile).hexdigest() == case["original_profile_sha256"]
        profile = json.loads(raw_profile)
        producer, _ = _call_producer_closure(
            ROOT, expected["converter"]["implementation_path"],
            expected["validator"]["implementation_path"], expected,
        )
        profile["producer_import_closure_sha256"] = producer
        runtime_profile = ROOT / case["runtime_profile"]
        assert json.loads(runtime_profile.read_bytes()) == profile
        authority.update(
            path=case["runtime_profile"], bytes=runtime_profile.stat().st_size,
            sha256=sha256(runtime_profile.read_bytes()).hexdigest(),
        )
    assert json.loads((ROOT / case["manifest"]).read_bytes()) == expected
