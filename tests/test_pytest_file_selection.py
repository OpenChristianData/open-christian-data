"""Directory discovery retains exact files, ordering, errors, and cleanup."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from build.tools import pre_commit_pytest as runner
from build.tools import pytest_file_selection as selection


def _configuration(root, record):
    path = root / "selection.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return SimpleNamespace(rootpath=root, getoption=lambda _: str(path),
                           getini=lambda _: ["test_*.py"])


@pytest.mark.parametrize("case", ("duplicate", "escape", "missing", "wrong-root", "named-node", "non-test-file", "non-string"))
def test_selection_input_rejects_invalid_or_ambiguous_files(tmp_path, case):
    (tmp_path / "test_valid.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    record = {"root": str(tmp_path), "files": ["test_valid.py"]}
    if case == "duplicate": record["files"] *= 2
    elif case == "escape": record["files"] = ["../test_escape.py"]
    elif case == "missing": record["files"] = ["test_missing.py"]
    elif case == "wrong-root": record["root"] = str(tmp_path.parent)
    elif case == "named-node": record["files"] = ["test_valid.py::test_ok[unsupported]"]
    elif case == "non-string": record["files"] = [42]
    else:
        (tmp_path / "helper.py").write_text("", encoding="utf-8")
        record["files"] = ["helper.py"]
    with pytest.raises(pytest.UsageError, match="Invalid selected-file input"):
        selection.pytest_configure(_configuration(tmp_path, record))


def test_selection_rejects_missing_or_extra_collected_files(tmp_path):
    member = tmp_path / "test_one.py"
    config = SimpleNamespace(_ocd_file_selection=({member: [("test_one.py", 0)]}, {tmp_path}, set(), set()))
    with pytest.raises(pytest.UsageError, match="missing="):
        next(selection.pytest_collection_modifyitems(config, []))
    config._ocd_file_selection[2].add(member)
    with pytest.raises(pytest.UsageError, match="extra="):
        next(selection.pytest_collection_modifyitems(config, [SimpleNamespace(path=tmp_path / "test_extra.py")]))


def test_large_complete_file_selection_runs_every_case_in_original_priority_order(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    tests = root / "tests"
    tests.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\npython_files = ["test_*.py"]\n', encoding="utf-8")
    targets = []
    for index in range(60):
        logical = f"tests/test_{index:03d}.py"
        (root / logical).write_text("def test_first(): assert True\ndef test_second(): assert True\n", encoding="utf-8")
        targets.append(logical)
    (tests / "test_partial.py").write_text("def test_a(): assert True\ndef test_b(): assert True\ndef test_unselected(): assert False\n", encoding="utf-8")
    targets.extend(["tests/test_partial.py::test_b", "tests/test_partial.py::test_a"])
    (tests / "test_unselected.py").write_text('raise RuntimeError("unselected file was imported")\n', encoding="utf-8")
    ignored = tests / "unselected_directory"
    ignored.mkdir()
    (ignored / "test_unselected.py").write_text('raise RuntimeError("unselected directory was imported")\n', encoding="utf-8")
    (root / "conftest.py").write_text('import json\nfrom pathlib import Path\ndef pytest_collection_finish(session):\n    Path("collected.json").write_text(json.dumps([item.nodeid for item in session.items]), encoding="utf-8")\n', encoding="utf-8")
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(runner, "REPO_ROOT", str(root))
    monkeypatch.setattr(runner, "_pytest_temp_parent", lambda: temporary)
    monkeypatch.setattr(runner, "SLOW_TEST_FILE_PRIORITY", (targets[50],))
    monkeypatch.setattr(runner, "CATALOG_WAITING_TEST_FILES", (targets[1],))
    monkeypatch.setenv(runner.WORKER_LIMIT_ENV, "2")
    command = runner._pytest_command(targets, basetemp=str(temporary / "probe"))
    ordered = command[-len(targets):]
    assert runner._pytest_directory_roots(targets) == ["tests"]
    assert runner._run_pytest(targets) == 0
    collected = json.loads((root / "collected.json").read_bytes())
    expected = [node for path in ordered for node in ([path] if "::" in path else [path + "::test_first", path + "::test_second"])]
    assert collected == expected
    assert len(collected) == len(set(collected)) == 122
    assert list(temporary.iterdir()) == []
