"""Preserve retained Puritan route records while exercising current dependencies."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.reconstruction.closure_verification import (
    _call_producer_closure,
    _call_validator_closure,
)


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tests/fixtures/reconstruction-runtime"
CASES = json.loads((RUNTIME / "next-binding-puritan.json").read_bytes())
STORAGE_DEPENDENCIES = (
    "ocd_kernel/lib/__init__.py",
    "ocd_kernel/lib/path_io.py",
    "ocd_kernel/lib/storage_topology.py",
)


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _frozen_json(relative, digest):
    raw = (ROOT / relative).read_bytes()
    assert sha256(raw).hexdigest() == digest
    return json.loads(raw)


def expected_manifest(case):
    expected = _frozen_json(case["original"], case["original_sha256"])
    supports = case.get("supports", [])
    for support in supports:
        if support["kind"] == "historical":
            authority = next(item for item in expected["authorities"] if item["name"] == support["authority"])
            raw = (ROOT / support["fixture"]).read_bytes()
            assert len(raw) == authority["bytes"]
            assert sha256(raw).hexdigest() == authority["sha256"] == support["original_sha256"]
            authority["path"] = support["fixture"]
            continue
        original = _frozen_json(support["original"], support["original_sha256"])
        if support["kind"] == "producer-runtime":
            members = original["producer_runtime"]["members"]
            assert not set(STORAGE_DEPENDENCIES) & {member["path"] for member in members}
            members.extend({"path": path} for path in STORAGE_DEPENDENCIES)
            members.sort(key=lambda member: member["path"])
            for member in members:
                raw = (ROOT / member["path"]).read_bytes()
                member.update(bytes=len(raw), sha256=sha256(raw).hexdigest())
            original["producer_runtime"]["sha256"] = sha256(_canonical(members)).hexdigest()
        else:
            assert support["kind"] == "producer-profile"
            original["producer_import_closure_sha256"] = _call_producer_closure(
                ROOT, expected["converter"]["implementation_path"],
                expected["validator"]["implementation_path"], expected,
            )[0]
        actual = (ROOT / support["fixture"]).read_bytes()
        assert json.loads(actual) == original
        authority = next(item for item in expected["authorities"] if item["name"] == support["authority"])
        authority.update(path=support["fixture"], bytes=len(actual), sha256=sha256(actual).hexdigest())
    if "producer_import_closure_sha256" in expected:
        expected["producer_import_closure_sha256"] = _call_producer_closure(
            ROOT, expected["converter"]["implementation_path"],
            expected["validator"]["implementation_path"], expected,
        )[0]
    expected["validator"]["import_closure_sha256"] = _call_validator_closure(
        ROOT, expected["validator"]["implementation_path"], expected,
        manifest_path=ROOT / case["manifest"],
    )[0]
    return expected


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["original"])
def test_runtime_copy_preserves_complete_retained_record_except_declared_closures(case):
    assert json.loads((ROOT / case["manifest"]).read_bytes()) == expected_manifest(case)
