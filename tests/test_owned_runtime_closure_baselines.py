"""Pin historical source records while testing explicitly updated runtime closures."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.reconstruction.closure_verification import _call_validator_closure, _call_producer_closure

ROOT = Path(__file__).resolve().parents[1]
BASELINES = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/closure-baselines.json").read_bytes())


@pytest.mark.parametrize("baseline", BASELINES, ids=[item["original"] for item in BASELINES])
def test_runtime_copy_preserves_the_complete_historical_record(baseline):
    raw = (ROOT / baseline["original"]).read_bytes()
    assert sha256(raw).hexdigest() == baseline["sha256"]
    expected = json.loads(raw)
    for keys, value in baseline["updates"]:
        holder = expected
        for key in keys[:-1]:
            holder = holder[key]
        holder[keys[-1]] = value
    actual = json.loads((ROOT / baseline["fixture"]).read_bytes())
    assert actual == expected
    for original, copied, length, digest in baseline["supports"]:
        content = (ROOT / copied).read_bytes()
        assert len(content) == length
        assert sha256(content).hexdigest() == digest
    validator = actual["validator"]
    live, _ = _call_validator_closure(ROOT, validator["implementation_path"], actual,
                                     manifest_path=ROOT / baseline["fixture"])
    assert live == validator["import_closure_sha256"]
    if "producer_import_closure_sha256" in actual:
        live, _ = _call_producer_closure(ROOT, actual["converter"]["implementation_path"],
                                        validator["implementation_path"], actual)
        assert live == actual["producer_import_closure_sha256"]
