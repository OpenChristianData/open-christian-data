"""The retained WEB byte contract stays immutable across checkout EOL policies."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import pytest
from ocd_kernel.reconstruction import SourceManifest
ROOT = Path(__file__).resolve().parents[1]
CASE = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-l596-web.json").read_bytes())[0]


def test_runtime_preserves_complete_historical_record():
    raw = (ROOT / CASE["original"]).read_bytes()
    assert sha256(raw).hexdigest() == CASE["original_sha256"]
    expected = deepcopy(json.loads(raw))
    for name in ("converter", "oracle"):
        authority = next(a for a in expected["authorities"] if a["name"] == name)
        payload = (ROOT / authority["path"]).read_bytes()
        assert b"\r" not in payload
        assert sha256(payload.replace(b"\n", b"\r\n")).hexdigest() == authority["sha256"]
        authority.update(sha256=sha256(payload).hexdigest(), bytes=len(payload))
        expected["converter" if name == "converter" else "validator"]["implementation_sha256"] = authority["sha256"]
    expected["validator"]["import_closure_sha256"] = expected["validator"]["implementation_sha256"]
    assert json.loads((ROOT / CASE["manifest"]).read_bytes()) == expected


def test_original_crlf_implementation_binding_rejects_current_lf():
    assert sha256((ROOT / CASE["original"]).read_bytes()).hexdigest() == CASE["original_sha256"]
    with pytest.raises(ValueError, match="converter authority bytes drifted"):
        SourceManifest.load(ROOT / CASE["original"], repository_root=ROOT)
