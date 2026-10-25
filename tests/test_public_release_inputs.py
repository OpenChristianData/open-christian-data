from pathlib import Path
from collections import deque
from types import SimpleNamespace
import ast
import json
import os
import subprocess
import sys

import pytest

from tests.public_release_inputs import local_input_cases, pytest_collection_modifyitems


ROOT = Path(__file__).resolve().parents[1]


def test_marks_only_declared_missing_inputs_and_never_skips_a_case(tmp_path):
    directory = tmp_path / "tests/fixtures"
    directory.mkdir(parents=True)
    inventory = {"contract": "ocd-public-test-inputs-v1", "modules": {
        "tests/test_example.py": {"required_path": "raw/source.txt",
                                  "source_manifest": "source.json", "tests": ["test_source"]},
    }}
    (directory / "public-local-input-cases.json").write_text(json.dumps(inventory))
    marked = []
    source = SimpleNamespace(nodeid="tests/test_example.py::test_source[one]", add_marker=marked.append)
    ordinary = SimpleNamespace(nodeid="tests/test_example.py::test_ordinary", add_marker=lambda _: pytest.fail("ordinary test marked"))
    pytest_collection_modifyitems(SimpleNamespace(rootpath=tmp_path), [source, ordinary])
    assert [mark.name for mark in marked] == ["requires_local_artifacts"]
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/source.txt").write_text("source")
    marked.clear()
    pytest_collection_modifyitems(SimpleNamespace(rootpath=tmp_path), [source, ordinary])
    assert not marked
    inventory["modules"]["tests/test_example.py"]["required_path"] = "../outside"
    (directory / "public-local-input-cases.json").write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match="invalid raw test input"):
        local_input_cases(tmp_path)


def test_marker_filter_is_explicit_and_unfiltered_tests_still_run(tmp_path):
    directory = tmp_path / "tests/fixtures"
    directory.mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers = requires_local_artifacts: local inputs\n")
    (directory / "public-local-input-cases.json").write_text(json.dumps({
        "contract": "ocd-public-test-inputs-v1", "modules": {"tests/test_example.py": {
            "required_path": "raw/source.txt", "source_manifest": "source.json", "tests": ["test_source"],
        }},
    }))
    (tmp_path / "tests/test_example.py").write_text(
        "def test_source():\n    raise AssertionError('required source not supplied')\n"
        "def test_ordinary():\n    assert True\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "tests.public_release_inputs", "-q"]
    selected = subprocess.run([*command, "-m", "not requires_local_artifacts"], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert selected.returncode == 0, selected.stdout + selected.stderr
    assert "1 passed, 1 deselected" in selected.stdout
    complete = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert complete.returncode == 1
    assert "required source not supplied" in complete.stdout


def _declared_external_values(module, source):
    from build.tools.pre_commit_pytest import _direct_imports

    pending, visited = deque([module]), set()
    while pending:
        current = pending.popleft()
        if current in visited:
            continue
        visited.add(current)
        path = ROOT / current
        if current == source:
            return {node.value.replace("\\", "/").removeprefix("//?/").rstrip("/")
                    for node in ast.walk(ast.parse(path.read_bytes()))
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        pending.extend(name.replace(".", "/") + ".py" for name in _direct_imports(path)
                       if (ROOT / (name.replace(".", "/") + ".py")).is_file())
    raise AssertionError(f"External source is not imported by {module}: {source}")


@pytest.mark.requires_local_artifacts
def test_declared_cases_exist_and_inputs_are_real_retained_source_bindings():
    inventory = json.loads((ROOT / "tests/fixtures/public-local-input-cases.json").read_bytes())
    local_input_cases(ROOT)
    for module, record in [*inventory["modules"].items(), *inventory.get("external_modules", {}).items()]:
        functions = {node.name for node in ast.parse((ROOT / module).read_text(encoding="utf-8-sig")).body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert set(record["tests"]) <= functions, module
        if "external_path" in record:
            declared = _declared_external_values(module, record.get("declared_in", module))
            assert record["external_path"] in declared, module
            continue
        manifest = json.loads((ROOT / record["source_manifest"]).read_bytes())
        paths = {authority["path"] for authority in manifest["authorities"]}
        if "source_set" in record:
            assert record["source_set"] in paths
            source_set = json.loads((ROOT / record["source_set"]).read_bytes())
            assert source_set["contract"] == "ocd-retained-source-set-v1"
            paths |= {"raw/" + member["logical_path"] for member in source_set["members"]}
        assert record["required_path"] in paths, module


    from build.tools.publish_public_mirror import load_config, matches_any
    policy = load_config()
    tracked = set(subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                                 capture_output=True, check=True).stdout.decode().split("\0"))
    module_functions = {}
    input_visibility = {}
    for node, private in inventory.get("private_cases", {}).items():
        module, name = node.split("::", 1)
        if module not in module_functions:
            module_functions[module] = {n.name for n in ast.parse((ROOT / module).read_bytes()).body if isinstance(n, ast.FunctionDef)}
        functions = module_functions[module]
        assert name.split("[", 1)[0] in functions, node
        if private not in input_visibility:
            actual = ROOT / private
            assert actual.exists(), node
            paths = {private} if actual.is_file() else {p for p in tracked if p.startswith(private.rstrip("/") + "/")}
            input_visibility[private] = any(p in tracked and matches_any(p, policy["include"])
                                            and not matches_any(p, policy["exclude"]) for p in paths)
        assert not input_visibility[private], f"Public input must be supplied, not deselected: {node}"


@pytest.mark.parametrize("external", ["D:/Library/Open Christian Data/candidate-reviews/stage", "C:/Scratch/stage"])
def test_external_stage_is_local_even_when_available_on_the_test_host(tmp_path, monkeypatch, external):
    directory = tmp_path / "tests/fixtures"
    directory.mkdir(parents=True)
    inventory = {"contract": "ocd-public-test-inputs-v1", "modules": {}, "external_modules": {
        "tests/test_example.py": {"external_path": external,
                                  "tests": ["test_stage"]},
    }}
    path = directory / "public-local-input-cases.json"
    path.write_text(json.dumps(inventory))
    marked = []
    stage = SimpleNamespace(nodeid="tests/test_example.py::test_stage[one]", add_marker=marked.append)
    ordinary = SimpleNamespace(nodeid="tests/test_example.py::test_ordinary", add_marker=lambda _: pytest.fail("ordinary test marked"))
    monkeypatch.setattr(Path, "exists", lambda _: True)
    pytest_collection_modifyitems(SimpleNamespace(rootpath=tmp_path), [stage, ordinary])
    assert [mark.name for mark in marked] == ["requires_local_artifacts"]
    inventory["external_modules"]["tests/test_example.py"]["external_path"] = external + "/../outside"
    path.write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match="invalid external test input"):
        local_input_cases(tmp_path)


def test_private_input_marks_only_the_exact_parameter_case(tmp_path):
    directory = tmp_path / "tests/fixtures"
    directory.mkdir(parents=True)
    inventory = {"contract": "ocd-public-test-inputs-v1", "modules": {}, "private_cases": {
        "tests/test_example.py::test_stage[archive]": "plans/archive.json",
    }}
    path = directory / "public-local-input-cases.json"
    path.write_text(json.dumps(inventory))
    marked = []
    archived = SimpleNamespace(nodeid="tests/test_example.py::test_stage[archive]", add_marker=marked.append)
    portable = SimpleNamespace(nodeid="tests/test_example.py::test_stage[synthetic]", add_marker=lambda _: pytest.fail("portable parameter marked"))
    pytest_collection_modifyitems(SimpleNamespace(rootpath=tmp_path), [archived, portable])
    assert [mark.name for mark in marked] == ["requires_local_artifacts"]
    inventory["private_cases"][archived.nodeid] = "../outside"
    path.write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match="invalid private test input"):
        local_input_cases(tmp_path)


def test_input_inventory_does_not_deselect_its_own_portable_proofs():
    assert not any(node.startswith("tests/test_public_release_inputs.py::")
                   for node in local_input_cases(ROOT))


def test_imported_external_input_requires_its_actual_import_graph(tmp_path, monkeypatch):
    module = tmp_path / "tests/test_stage.py"
    source = tmp_path / "build/tools/stage.py"
    unrelated = source.with_name("unrelated.py")
    module.parent.mkdir()
    source.parent.mkdir(parents=True)
    module.write_text("from build.tools import stage\n", encoding="utf-8")
    source.write_text('ROOT = r"\\\\?\\D:\\Library\\Open Christian Data\\stage"\n', encoding="utf-8")
    unrelated.write_bytes(source.read_bytes())
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert "D:/Library/Open Christian Data/stage" in _declared_external_values(
        "tests/test_stage.py", "build/tools/stage.py")
    with pytest.raises(AssertionError, match="not imported"):
        _declared_external_values("tests/test_stage.py", "build/tools/unrelated.py")
