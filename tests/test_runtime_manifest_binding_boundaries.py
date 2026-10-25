"""Current-runtime test manifests preserve their frozen retained authorities."""

from copy import deepcopy
from functools import cache
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from ocd_kernel.reconstruction.contract import SourceManifest, _freeze


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (ROOT / "tests/fixtures/reconstruction-runtime/runtime-binding-cases.json").read_bytes()
)


def allow_runtime_manifest_selection(monkeypatch: pytest.MonkeyPatch, manifest: Path) -> None:
    """Select a test-only manifest while retaining actual bounded catalog verification."""

    from build.tools import count_dataset_records

    original = count_dataset_records._resolve_source_manifest_allowlist

    def resolve(sources_root: Path, selections):
        selections = tuple(selections)
        if selections == (manifest.relative_to(ROOT).as_posix(),):
            assert manifest.parent == ROOT / "tests/fixtures/reconstruction-runtime"
            return sources_root, (manifest,)
        return original(sources_root, selections)

    monkeypatch.setattr(count_dataset_records, "_resolve_source_manifest_allowlist", resolve)
    retained_paths = {case["fixture"]: case["original"] for case in CASES}
    retained_paths.update({case["manifest"]: case["original"] for case in json.loads(
        (ROOT / "tests/fixtures/reconstruction-runtime/next-binding-puritan.json").read_bytes()
    )})
    retained_path = ROOT / retained_paths[manifest.relative_to(ROOT).as_posix()]
    original_identity = count_dataset_records._runtime_policy_identity

    def identity(source, record, path, sources_root, **kwargs):
        # Category comes from the retained source directory; verified bytes use the fixture.
        return original_identity(
            source, record, retained_path if path == manifest else path, sources_root, **kwargs
        )

    monkeypatch.setattr(count_dataset_records, "_runtime_policy_identity", identity)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@cache
def _module(relative: str):
    path = ROOT / relative
    name = "runtime_binding_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _digest(case: dict, record: dict, binding: dict) -> str:
    mode = binding["arguments"]
    if mode == "closure-artifact":
        authority = next(a for a in record["authorities"] if a["name"] == binding["authority"])
        return _sha(ROOT / authority["path"])
    role = binding.get("module_role", "validator")
    module = _module(record[role]["implementation_path"])
    function = getattr(module, binding["function"])
    if mode == "none":
        value = function()
    elif mode == "root":
        value = function(ROOT)
    elif mode == "policy-root":
        authority = next(a for a in record["authorities"] if a["name"] == binding["policy"])
        value = function(json.loads((ROOT / authority["path"]).read_bytes()), ROOT)
    elif mode == "root-implementation":
        value = function(ROOT, ROOT / record[binding["implementation_role"]]["implementation_path"])
    elif mode == "manifest":
        path = ROOT / case["fixture"]
        source = SourceManifest(path, ROOT, _sha(path), _freeze(record))
        value = function(source)
    else:
        raise AssertionError(f"Unsupported runtime-binding calculation: {mode}")
    return value[0] if isinstance(value, tuple) else value


def _expected_support(case: dict, support: dict) -> dict:
    original = ROOT / support["original"]
    assert _sha(original) == support["original_sha256"]
    expected = json.loads(original.read_bytes())
    if support["kind"] == "producer-profile":
        expected["producer_import_closure_sha256"] = _digest(case, case["original_record"], support["calculation"])
    elif support["kind"] == "oracle-closure":
        for member in expected["first_party"]:
            assert member["path"].endswith(".py")
            member["sha256"] = _sha(ROOT / member["path"])
            if "bytes" in member:
                member["bytes"] = (ROOT / member["path"]).stat().st_size
        for path in support.get("added_code_paths", []):
            assert path.startswith("ocd_kernel/") and path.endswith(".py")
            assert all(member["path"] != path for member in expected["first_party"])
            expected["first_party"].append({"path": path, "sha256": _sha(ROOT / path)})
    else:
        raise AssertionError("Unsupported runtime support fixture")
    return expected


def expected_manifest(case: dict) -> dict:
    original = ROOT / case["original"]
    assert _sha(original) == case["original_sha256"]
    expected = json.loads(original.read_bytes())
    by_name = {a["name"]: a for a in expected["authorities"]}
    for name in case["code_authorities"]:
        authority = by_name[name]
        assert authority["role"] != "primary-source"
        assert authority["path"].endswith(".py") or authority["path"] == "schemas/v2/work.schema.json"
        path = ROOT / authority["path"]
        authority.update(bytes=path.stat().st_size, sha256=_sha(path))
    for role in case["implementation_roles"]:
        assert role in {"converter", "validator"}
        expected[role]["implementation_sha256"] = _sha(ROOT / expected[role]["implementation_path"])
    for support in case.get("historical_support", []):
        authority = by_name[support["authority"]]
        assert support["fixture"].startswith("tests/fixtures/reconstruction-runtime/")
        path = ROOT / support["fixture"]
        assert _sha(path) == authority["sha256"] == support["original_sha256"]
        assert path.stat().st_size == authority["bytes"]
        authority["path"] = support["fixture"]
    for support in case.get("support", []):
        assert support["fixture"].startswith("tests/fixtures/reconstruction-runtime/")
        support_case = {**case, "original_record": deepcopy(expected)}
        assert json.loads((ROOT / support["fixture"]).read_bytes()) == _expected_support(support_case, support)
        path = ROOT / support["fixture"]
        by_name[support["authority"]].update(path=support["fixture"], bytes=path.stat().st_size, sha256=_sha(path))
    if case.get("validator_closure"):
        expected["validator"]["import_closure_sha256"] = _digest(case, expected, case["validator_closure"])
    if case.get("producer_closure"):
        expected["producer_import_closure_sha256"] = _digest(case, expected, case["producer_closure"])
    return expected


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_runtime_manifest_preserves_frozen_source_scope_and_only_updates_declared_runtime(case: dict) -> None:
    assert json.loads((ROOT / case["fixture"]).read_bytes()) == expected_manifest(case)



@pytest.mark.parametrize("case", [case for case in CASES if any(
    support["authority"] == "work" for support in case.get("historical_support", [])
)], ids=lambda case: case["id"])
def test_historical_work_support_loads_with_current_runtime_dependencies(case: dict) -> None:
    manifest = SourceManifest.load(ROOT / case["fixture"], repository_root=ROOT)
    original = json.loads((ROOT / case["original"]).read_bytes())
    original_work = next(row for row in original["authorities"] if row["name"] == "work")
    assert _sha(manifest.authority_path("work")) == original_work["sha256"]
    assert manifest.authority_path("work") != ROOT / original_work["path"]
