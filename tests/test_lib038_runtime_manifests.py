"""Preserve LIB-038 history while binding its declared current runtime closures."""

from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = [row for row in json.loads(
    (ROOT / "tests/fixtures/reconstruction-runtime/individual-runtime-bindings.json").read_bytes())
    if Path(row["manifest"]).name in {"npnf104-lib038.source-manifest.json", "npnf108-lib038.source-manifest.json"}]


@pytest.mark.parametrize("case", CASES, ids=[Path(row["manifest"]).stem for row in CASES])
def test_runtime_fixture_preserves_original_authorities_and_only_updates_live_closures(case):
    raw = (ROOT / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    expected = json.loads(raw)
    actual = json.loads((ROOT / case["manifest"]).read_bytes())
    for role in ("converter", "validator"):
        module = import_module(expected[role]["implementation_path"][:-3].replace("/", "."))
        name = role + "-first-party-import-closure"
        authority = next(item for item in expected["authorities"] if item["name"] == name)
        original = (ROOT / authority["path"]).read_bytes()
        assert sha256(original).hexdigest() == authority["sha256"]
        original_record = json.loads(original)
        records = module._closure_records()
        assert [item["path"] for item in records] == [item["path"] for item in original_record["files"]]
        copied = next(item for item in actual["authorities"] if item["name"] == name)
        path = ROOT / "tests/fixtures/reconstruction-runtime" / (Path(case["manifest"]).name.removesuffix(".source-manifest.json") + f".{role}.import-closure.json")
        content = path.read_bytes()
        assert content == module._canonical({"contract": original_record["contract"], "files": records})
        authority.update(path=path.relative_to(ROOT).as_posix(), bytes=len(content), sha256=sha256(content).hexdigest())
        assert copied == authority
        if role == "validator":
            expected[role]["import_closure_sha256"] = module._closure_digest(records)
    assert actual == expected
