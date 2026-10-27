"""Tests for the scoped pre-commit pytest runner."""

from pathlib import Path
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import json

from build.tools import pre_commit_pytest


def test_additional_release_selection_preserves_coverage_and_unmapped_paths(tmp_path):
    _selection_fixture(tmp_path, {"tests/test_current.py": "", "tests/test_previous.py": ""})
    path = tmp_path / "previous.json"
    path.write_text(json.dumps({"tests": ["tests/test_previous.py", "tests/test_current.py::test_one"], "unmapped": []}))
    current = {"tests": ["tests/test_current.py"], "unmapped": ["build/unproved.py"]}
    assert pre_commit_pytest._include_additional_selection(current, path, tmp_path) == {
        "tests": ["tests/test_current.py", "tests/test_previous.py"], "unmapped": ["build/unproved.py"],
    }


@pytest.mark.parametrize("additional", [
    {"tests": ["../test_escape.py"], "unmapped": []},
    {"tests": ["tests/test_missing.py"], "unmapped": []},
    {"tests": [7], "unmapped": []},
    {"tests": [], "unmapped": ["unproved.py"]},
])
def test_additional_release_selection_rejects_invalid_evidence(tmp_path, additional):
    path = tmp_path / "previous.json"
    path.write_text(json.dumps(additional))
    with pytest.raises((ValueError, RuntimeError)):
        pre_commit_pytest._include_additional_selection({"tests": [], "unmapped": []}, path, tmp_path)


def test_additional_release_selection_is_not_inherited_by_test_subprocesses(monkeypatch):
    monkeypatch.setenv(pre_commit_pytest.ADDITIONAL_SELECTION_ENV, "release.json")
    assert pre_commit_pytest.ADDITIONAL_SELECTION_ENV not in pre_commit_pytest._pytest_environment()


@pytest.mark.parametrize("changed", (
    "tests/fixtures/reconstruction-runtime/retained-manifest-inventory.json",
    "tests/fixtures/reconstruction-runtime/authorities/frozen.py.txt",
    "tests/fixtures/reconstruction-runtime/npnf113-lib041.work-ticket-map.md",
))
def test_runtime_fixture_edits_require_all_preservation_and_closure_proofs(tmp_path, changed):
    targets = pre_commit_pytest.RUNTIME_FIXTURE_PROOFS
    files = {target.split("::")[0]: "" for target in targets}
    files["tests/test_unrelated.py"] = ""
    _selection_fixture(tmp_path, files)
    selection = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selection == {"tests": sorted(targets), "unmapped": []}


def test_runtime_candidate_helper_selects_package_and_catalog_proofs(tmp_path):
    source = "tests/runtime_candidate_baselines.py"
    targets = pre_commit_pytest.COMPONENT_TEST_POLICIES[source].add
    _selection_fixture(tmp_path, {source: "", **{target.split("::", 1)[0]: "" for target in targets}})
    assert pre_commit_pytest.select_tests([source], tmp_path) == {
        "tests": sorted(targets), "unmapped": [],
    }


def test_pytest_child_can_query_its_own_git_repository(tmp_path, monkeypatch):
    clean = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    repositories = [tmp_path / "hook-owner", tmp_path / "retained-source"]
    revisions = []
    for root in repositories:
        root.mkdir()
        subprocess.run(["git", "init", "--quiet", str(root)], env=clean, check=True)
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.name=Test", "-c",
             "user.email=test@example.invalid", "commit", "--quiet", "--allow-empty",
             "-m", root.name], env=clean, check=True,
        )
        revisions.append(subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], env=clean,
            check=True, capture_output=True, text=True,
        ).stdout.strip())
    assert revisions[0] != revisions[1]
    monkeypatch.setenv("GIT_DIR", str(repositories[0] / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(repositories[0] / ".git/index"))
    monkeypatch.setenv("OCD_PYTEST_ENV_PROBE", "preserved")
    monkeypatch.setattr(pre_commit_pytest, "_pytest_temp_parent", lambda: tmp_path)
    probe = (
        "import os, subprocess, sys; "
        "observed = subprocess.run(['git', '-C', sys.argv[1], 'rev-parse', 'HEAD'], "
        "check=True, capture_output=True, text=True).stdout.strip(); "
        "assert observed == sys.argv[2], (observed, sys.argv[2]); "
        "assert os.environ['OCD_PYTEST_ENV_PROBE'] == 'preserved'"
    )
    monkeypatch.setattr(pre_commit_pytest, "_pytest_command", lambda *args, **kwargs: [
        sys.executable, "-c", probe, str(repositories[1]), revisions[1],
    ])
    assert pre_commit_pytest._run_pytest(["nested-git-probe"]) == 0
    assert os.environ["GIT_DIR"] == str(repositories[0] / ".git")


def test_long_selection_preserves_exact_node_ids_with_parallel_workers(tmp_path, monkeypatch):
    pytest.importorskip("xdist")
    repository = tmp_path / "repository"
    repository.mkdir()
    temp_parent = tmp_path / "temporary"
    temp_parent.mkdir()
    targets = []
    labels = [f"case {value:03d} " + "x" * 160 for value in range(200)]
    for ordinal in range(2):
        name = f"test_selected cases_{ordinal}.py"
        (repository / name).write_text(
            "import pytest\n"
            f"@pytest.mark.parametrize('value', range(200), ids={labels!r})\n"
            "def test_selected(value):\n    assert value % 2 == 0\n",
            encoding="utf-8",
        )
        targets.extend(f"{name}::test_selected[{labels[value]}]" for value in range(0, 200, 2))
    monkeypatch.setattr(pre_commit_pytest, "REPO_ROOT", str(repository))
    monkeypatch.setattr(pre_commit_pytest, "_pytest_temp_parent", lambda: temp_parent)
    monkeypatch.setattr(pre_commit_pytest, "MIN_PARALLEL_TEST_FILES", 2)
    monkeypatch.setenv(pre_commit_pytest.WORKER_LIMIT_ENV, "2")
    command = pre_commit_pytest._pytest_command(targets, basetemp=str(temp_parent / "probe"))
    assert len(subprocess.list2cmdline(command)) > 32_767
    assert command[command.index("-n") + 1] == "2"
    # Keep the existing real 200-node child with spaces in parameter IDs,
    # but give its second file priority to prove the @file execution order.
    monkeypatch.setattr(pre_commit_pytest, "SLOW_TEST_FILE_PRIORITY", (
        "test_selected cases_1.py", "test_selected cases_0.py",
    ))
    expected = targets[100:] + targets[:100]
    prioritized = pre_commit_pytest._pytest_command(targets, basetemp=str(temp_parent / "probe"))
    assert prioritized[-len(targets):] == expected
    assert "--no-loadscope-reorder" in prioritized
    actual_run = pre_commit_pytest.subprocess.run
    observed = []

    def real_child(command, **kwargs):
        assert command[-1].startswith("@")
        arguments = Path(command[-1][1:])
        ordered = arguments.read_text(encoding="utf-8").splitlines()
        assert ordered == expected
        observed.extend(ordered)
        return actual_run(command, **kwargs)

    monkeypatch.setattr(pre_commit_pytest.subprocess, "run", real_child)
    assert pre_commit_pytest._run_pytest(targets) == 0
    assert observed == expected
    assert list(temp_parent.iterdir()) == []


def test_large_selections_report_test_names_and_durations():
    paths = [f"tests/test_case_{ordinal}.py" for ordinal in range(51)]
    command = pre_commit_pytest._pytest_command(
        paths, basetemp="temporary", xdist_available=False
    )
    assert "-v" in command and "-q" not in command
    assert "--durations=20" in command
    assert command[-len(paths):] == paths


def _selection_fixture(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_selection_covers_reconstruction_contract_and_direct_kernel_import(tmp_path):
    _selection_fixture(tmp_path, {
        "build/tei/daily_light_reconstruction.py": "",
        "ocd_kernel/lib/example.py": "",
        "tests/test_daily_light_reconstruction_contract.py": "def test_route(): pass",
        "tests/test_kernel_behavior.py": "from ocd_kernel.lib.example import load\n",
        "tests/test_unrelated.py": "def test_other(): pass",
    })
    result = pre_commit_pytest.select_tests([
        "build/tei/daily_light_reconstruction.py", "ocd_kernel/lib/example.py"
    ], tmp_path)
    assert result["unmapped"] == []
    assert result["tests"] == [
        "tests/test_daily_light_reconstruction_contract.py", "tests/test_kernel_behavior.py"
    ]


def test_selection_uses_component_node_ids_for_route_producer_changes(tmp_path, monkeypatch):
    source = "build/tei/example_oracle.py"
    test_file = "tests/test_routes.py"
    test_case = f"{test_file}::test_route_reconstructs[example]"
    _selection_fixture(tmp_path, {
        source: "",
        test_file: "from build.tei.example_oracle import oracle\n",
    })
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        source: pre_commit_pytest.ComponentTestPolicy(route=test_case),
    })

    assert pre_commit_pytest.select_tests([source], tmp_path) == {
        "tests": [test_case], "unmapped": []
    }


def test_changed_test_file_runs_in_full_when_producer_is_staged(tmp_path, monkeypatch):
    source = "build/tei/example_oracle.py"
    test_file = "tests/test_routes.py"
    test_case = f"{test_file}::test_route_reconstructs[example]"
    _selection_fixture(tmp_path, {
        source: "",
        test_file: "from build.tei.example_oracle import oracle\n",
    })
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        source: pre_commit_pytest.ComponentTestPolicy(route=test_case),
    })

    assert pre_commit_pytest.select_tests([source, test_file], tmp_path) == {
        "tests": [test_file], "unmapped": []
    }


def test_selection_does_not_execute_test_imports(tmp_path):
    _selection_fixture(tmp_path, {
        "tests/test_boundary.py": "raise RuntimeError('must not execute')\nfrom ocd_kernel.lib.example import load\n",
    })
    assert pre_commit_pytest.select_tests(["ocd_kernel/lib/example.py"], tmp_path)["tests"] == ["tests/test_boundary.py"]


def test_selection_reports_unmapped_and_includes_changed_test(tmp_path):
    _selection_fixture(tmp_path, {"tests/test_changed.py": "def test_changed(): pass"})
    result = pre_commit_pytest.select_tests([
        "ocd_kernel/new_component.py", "tests/test_changed.py", "docs/readme.md"
    ], tmp_path)
    assert result["unmapped"] == ["ocd_kernel/new_component.py"]
    assert result["tests"] == ["tests/test_changed.py"]


def test_selection_uses_only_direct_imports_not_transitive_corpus(tmp_path):
    _selection_fixture(tmp_path, {
        "build/wrapper.py": "from ocd_kernel.lib.example import load\n",
        "tests/test_wrapper.py": "from build.wrapper import run\n",
        "tests/test_example.py": "from ocd_kernel.lib.example import load\n",
    })
    assert pre_commit_pytest.select_tests(["ocd_kernel/lib/example.py"], tmp_path)["tests"] == ["tests/test_example.py"]


def test_staged_discovery_is_nul_delimited_and_keeps_deletions(monkeypatch):
    def run(command, **kwargs):
        assert "-z" in command
        assert "--diff-filter=ACDMR" in command
        return SimpleNamespace(stdout="M\0ocd_kernel/cafÃ©.py\0D\0build/deleted.py\0M\0docs/a.md\0")
    monkeypatch.setattr(pre_commit_pytest.subprocess, "run", run)
    assert pre_commit_pytest._get_staged_changes() == {"changed": ["ocd_kernel/cafÃ©.py", "build/deleted.py"], "deleted": ["build/deleted.py"]}


def test_staged_discovery_failure_is_not_no_changes(monkeypatch):
    def fail(*args, **kwargs):
        raise FileNotFoundError("git unavailable")
    monkeypatch.setattr(pre_commit_pytest.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="staged"):
        pre_commit_pytest._get_staged_changes()


def test_gate_blocks_unmapped_or_large_selection_without_skipping_tests(monkeypatch):
    calls = []
    monkeypatch.setattr(pre_commit_pytest, "_run_pytest", lambda paths: calls.append(paths) or 0)
    assert pre_commit_pytest.run_selection({"tests": [], "unmapped": ["build/new.py"]}, {}) == 1
    paths = [f"tests/test_{n}.py" for n in range(51)]
    assert pre_commit_pytest.run_selection({"tests": paths, "unmapped": []}, {}) == 1
    assert calls == []
    assert pre_commit_pytest.run_selection({"tests": paths, "unmapped": []}, {"OCD_PRECOMMIT_RUN_LARGE_SELECTION": "1"}) == 0
    assert calls == [paths]


@pytest.mark.requires_local_artifacts
def test_explicit_component_policies_have_existing_sources_and_targets():
    root = Path(pre_commit_pytest.REPO_ROOT)
    for source, policy in pre_commit_pytest.COMPONENT_TEST_POLICIES.items():
        assert (root / source).is_file()
        targets = policy.add + (policy.replace or ())
        if policy.route is not None:
            targets += (policy.route,)
            test_file, _, nodeid = policy.route.partition("::")
            route_id = nodeid.rsplit("[", 1)[1].removesuffix("]")
            assert f'id="{route_id}"' in (root / test_file).read_text(encoding="utf-8")
        assert targets
        for target in targets:
            test_file, separator, nodeid = target.partition("::")
            assert not separator or nodeid
            assert (root / test_file).is_file()


def test_component_test_targets_replace_broader_direct_import_matches(tmp_path, monkeypatch):
    source = "build/example.py"
    target = "tests/test_focused.py::test_route[example]"
    _selection_fixture(tmp_path, {
        source: "",
        "tests/test_focused.py": "from build.example import run\n",
        "tests/test_slow_matrix.py": "from build.example import run\n",
    })
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        source: pre_commit_pytest.ComponentTestPolicy(replace=(target,)),
    })

    assert pre_commit_pytest.select_tests([source], tmp_path) == {
        "tests": [target], "unmapped": []
    }


def test_changed_test_file_runs_in_full_with_its_producer_mapping(tmp_path, monkeypatch):
    source = "build/example.py"
    test_file = "tests/test_focused.py"
    target = f"{test_file}::test_route[example]"
    _selection_fixture(tmp_path, {
        source: "",
        test_file: "def test_route(): pass\ndef test_unrelated_case(): pass\n",
    })
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        source: pre_commit_pytest.ComponentTestPolicy(replace=(target,)),
    })

    assert pre_commit_pytest.select_tests([source, test_file], tmp_path) == {
        "tests": [test_file], "unmapped": []
    }


def test_changed_component_test_file_runs_in_full(tmp_path, monkeypatch):
    test_file = "tests/test_focused.py"
    target = f"{test_file}::test_route[example]"
    _selection_fixture(tmp_path, {
        test_file: "def test_route(): pass\ndef test_unrelated_case(): pass\n"
    })
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        test_file: pre_commit_pytest.ComponentTestPolicy(replace=(target,)),
    })

    assert pre_commit_pytest.select_tests([test_file], tmp_path) == {
        "tests": [test_file], "unmapped": []
    }


def test_deleted_production_path_still_selects_surviving_test(tmp_path):
    _selection_fixture(tmp_path, {"tests/test_removed.py": "from build.removed import run\n"})
    assert pre_commit_pytest.select_tests(["build/removed.py"], tmp_path) == {
        "tests": ["tests/test_removed.py"], "unmapped": []
    }


def test_conftest_change_selects_its_directory_only(tmp_path):
    _selection_fixture(tmp_path, {
        "tests/slice/test_one.py": "", "tests/test_other.py": "",
    })
    assert pre_commit_pytest.select_tests(["tests/slice/conftest.py"], tmp_path)["tests"] == [
        "tests/slice/test_one.py"
    ]


def test_missing_component_test_fails_with_path(tmp_path, monkeypatch):
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        "build/one.py": pre_commit_pytest.ComponentTestPolicy(add=("tests/test_missing.py",))
    })
    with pytest.raises(RuntimeError, match="Stale component mapping.*test_missing"):
        pre_commit_pytest.select_tests(["build/one.py"], tmp_path)


def test_no_tests_collected_is_not_success(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest, "_run_pytest", lambda paths: 5)
    assert pre_commit_pytest.run_selection({
        "tests": ["tests/test_empty.py"], "unmapped": []
    }, {}) == 5


def test_document_only_change_does_not_inspect_unrelated_tests(tmp_path):
    _selection_fixture(tmp_path, {"tests/test_broken.py": "not valid python!"})
    assert pre_commit_pytest.select_tests(["docs/readme.md"], tmp_path) == {
        "tests": [], "unmapped": []
    }


def test_root_conftest_selects_all_tests(tmp_path):
    _selection_fixture(tmp_path, {"tests/test_one.py": "", "tests/slice/test_two.py": ""})
    assert pre_commit_pytest.select_tests(["conftest.py"], tmp_path) == {
        "tests": ["tests/slice/test_two.py", "tests/test_one.py"], "unmapped": []
    }


def test_run_pytest_uses_file_level_workers_for_large_test_sets(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 60_000)

    assert pre_commit_pytest._pytest_command(
        ["tests/test_example.py", "tests/test_other.py"],
        basetemp="C:/tmp/ocd-precommit-test",
        xdist_available=True,
    ) == [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        "-x",
        "--basetemp",
        "C:/tmp/ocd-precommit-test",
        "-n",
        "2",
        "--dist",
        "loadfile",
        "tests/test_example.py",
        "tests/test_other.py",
    ]


def test_run_pytest_keeps_small_test_sets_serial(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 10_000)

    assert pre_commit_pytest._pytest_command(
        ["tests/test_example.py", "tests/test_other.py"],
        basetemp="C:/tmp/ocd-precommit-test",
        xdist_available=True,
    ) == [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        "-x",
        "--basetemp",
        "C:/tmp/ocd-precommit-test",
        "tests/test_example.py",
        "tests/test_other.py",
    ]


def test_run_pytest_parallelizes_multi_file_sets_with_small_sources(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 10_000)
    monkeypatch.setattr(pre_commit_pytest.os, "cpu_count", lambda: 8)

    command = pre_commit_pytest._pytest_command(
        ["tests/test_one.py", "tests/test_two.py", "tests/test_three.py"],
        basetemp="C:/tmp/ocd-precommit-test",
        xdist_available=True,
    )

    assert command[-7:] == [
        "-n", "3", "--dist", "loadfile",
        "tests/test_one.py", "tests/test_two.py", "tests/test_three.py"
    ]


@pytest.mark.parametrize("override,expected", [(None, "4"), ("8", "8")])
def test_worker_default_limits_load_without_dropping_targets(monkeypatch, override, expected):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _path: 60_000)
    monkeypatch.setattr(pre_commit_pytest.os, "cpu_count", lambda: 16)
    if override is None:
        monkeypatch.delenv("OCD_PRECOMMIT_WORKERS", raising=False)
    else:
        monkeypatch.setenv("OCD_PRECOMMIT_WORKERS", override)
    targets = [f"tests/test_{index}.py" for index in range(8)]
    command = pre_commit_pytest._pytest_command(targets, basetemp="C:/tmp/worker-probe", xdist_available=True)
    assert command[command.index("-n") + 1] == expected
    assert command[-len(targets):] == targets


def test_run_pytest_respects_bounded_worker_override(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 60_000)
    monkeypatch.setenv("OCD_PRECOMMIT_WORKERS", "2")

    command = pre_commit_pytest._pytest_command(
        [f"tests/test_{index}.py" for index in range(8)],
        basetemp="C:/tmp/ocd-precommit-test",
        xdist_available=True,
    )

    assert command[command.index("-n") + 1] == "2"
    assert "--dist" in command


def test_run_pytest_falls_back_to_serial_when_xdist_is_missing(monkeypatch):
    assert pre_commit_pytest._pytest_command(
        ["tests/test_example.py"],
        basetemp="C:/tmp/ocd-precommit-test",
        xdist_available=False,
    ) == [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        "-x",
        "--basetemp",
        "C:/tmp/ocd-precommit-test",
        "tests/test_example.py",
    ]


def test_pytest_temp_parent_uses_valid_external_debug_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    external = tmp_path / "sandbox-temp"
    external.mkdir()
    monkeypatch.setattr(pre_commit_pytest, "REPO_ROOT", str(repository))

    assert pre_commit_pytest._pytest_temp_parent(
        {"PYTEST_DEBUG_TEMPROOT": str(external)}
    ) == external.resolve()


def test_pytest_temp_parent_rejects_repository_local_debug_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    local_temp = repository / ".tmp"
    local_temp.mkdir()
    monkeypatch.setattr(pre_commit_pytest, "REPO_ROOT", str(repository))

    with pytest.raises(RuntimeError, match=r"PYTEST_DEBUG_TEMPROOT.*\.tmp"):
        pre_commit_pytest._pytest_temp_parent(
            {"PYTEST_DEBUG_TEMPROOT": str(local_temp)}
        )


def test_pytest_temp_parent_uses_host_temp_when_debug_root_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(pre_commit_pytest, "REPO_ROOT", str(repository))

    assert pre_commit_pytest._pytest_temp_parent({}) is None


def test_pytest_temp_parent_rejects_unavailable_debug_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    missing = tmp_path / "missing-sandbox-temp"
    monkeypatch.setattr(pre_commit_pytest, "REPO_ROOT", str(repository))

    with pytest.raises(RuntimeError, match=r"PYTEST_DEBUG_TEMPROOT is unavailable"):
        pre_commit_pytest._pytest_temp_parent(
            {"PYTEST_DEBUG_TEMPROOT": str(missing)}
        )


def test_run_pytest_uses_and_cleans_the_selected_temp_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, Path] = {}

    monkeypatch.setattr(pre_commit_pytest, "_pytest_temp_parent", lambda: tmp_path)

    def command(_test_files, *, basetemp, xdist_available=None):
        del xdist_available
        observed["basetemp"] = Path(basetemp)
        assert observed["basetemp"].parent == tmp_path
        assert observed["basetemp"].is_dir()
        return ["pytest-probe"]

    monkeypatch.setattr(pre_commit_pytest, "_pytest_command", command)
    monkeypatch.setattr(
        pre_commit_pytest.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    assert pre_commit_pytest._run_pytest(["tests/test_example.py"]) == 0
    assert not observed["basetemp"].exists()
    assert list(tmp_path.iterdir()) == []


def test_deleted_unmapped_module_uses_regression_surface(tmp_path):
    _selection_fixture(tmp_path, {"tests/test_new_name.py": "", "cvw_app/tests/test_view.py": ""})
    assert pre_commit_pytest.select_tests(["build/old_name.py"], tmp_path, deleted_paths=["build/old_name.py"]) == {
        "tests": ["cvw_app/tests/test_view.py", "tests/test_new_name.py"], "unmapped": []
    }


def test_cvw_python_changes_select_cvw_tests(tmp_path):
    _selection_fixture(tmp_path, {"cvw_app/tests/test_service.py": "from cvw_app.review_service import run\n"})
    assert pre_commit_pytest.select_tests(["cvw_app/review_service.py"], tmp_path)["tests"] == ["cvw_app/tests/test_service.py"]


def test_conftest_without_tests_is_explicitly_unmapped(tmp_path):
    assert pre_commit_pytest.select_tests(["build/tei/conftest.py"], tmp_path) == {
        "tests": [], "unmapped": ["build/tei/conftest.py"]
    }


@pytest.mark.parametrize("deleted", [
    "tests/test_removed.py",
    "build/parsers/tests/test_removed.py",
    "cvw_app/tests/test_removed.py",
])
def test_deleted_tests_use_consistent_regression_coverage(tmp_path, deleted):
    _selection_fixture(tmp_path, {
        "build/removed.py": "def run(): pass",
        "tests/test_surviving.py": "", "cvw_app/tests/test_view.py": "",
    })
    assert pre_commit_pytest.select_tests([deleted], tmp_path, deleted_paths=[deleted]) == {
        "tests": ["cvw_app/tests/test_view.py", "tests/test_surviving.py"], "unmapped": []
    }


def test_deleting_only_test_cannot_be_an_empty_success(tmp_path):
    assert pre_commit_pytest.select_tests(["tests/test_removed.py"], tmp_path, deleted_paths=["tests/test_removed.py"]) == {
        "tests": [], "unmapped": ["tests/test_removed.py"]
    }


def test_large_selection_bounds_memory_workers_without_dropping_files(monkeypatch):
    monkeypatch.delenv(pre_commit_pytest.WORKER_LIMIT_ENV, raising=False)
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 60_000)
    monkeypatch.setattr(pre_commit_pytest.os, "cpu_count", lambda: 32)
    paths = [f"tests/test_work_{index}.py" for index in range(24)]
    command = pre_commit_pytest._pytest_command(
        paths, basetemp="C:/tmp/ocd-precommit-test", xdist_available=True
    )
    assert command[command.index("-n") + 1] == "4"
    assert command[command.index("--dist") + 1] == "loadfile"
    assert command[-len(paths):] == paths


def test_component_targets_allow_whole_unit_file_and_selected_consumer(tmp_path, monkeypatch):
    source = "build/tools/reconstruct_candidate.py"
    whole = "tests/test_reconstruct_candidate.py"
    route = "tests/test_corpus.py::test_cli_route"
    _selection_fixture(tmp_path, {
        source: "",
        whole: "def test_existing(): pass\ndef test_new_case(): pass\n",
        "tests/test_corpus.py": "from build.tools.reconstruct_candidate import run\ndef test_cli_route(): pass\ndef test_unrelated_catalog(): pass\n",
    })
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        source: pre_commit_pytest.ComponentTestPolicy(replace=(whole, route)),
    })
    assert pre_commit_pytest.select_tests([source, whole], tmp_path) == {
        "tests": [route, whole], "unmapped": []
    }


def test_component_targets_reject_empty_node_after_separator(tmp_path, monkeypatch):
    source = "build/example.py"
    _selection_fixture(tmp_path, {source: "", "tests/test_example.py": ""})
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        source: pre_commit_pytest.ComponentTestPolicy(replace=("tests/test_example.py::",)),
    })
    with pytest.raises(RuntimeError, match="Stale component target mapping"):
        pre_commit_pytest.select_tests([source], tmp_path)

@pytest.mark.parametrize("replacement", [None, ("tests/test_override.py::test_case",)])
def test_component_policy_precedence_preserves_unrelated_matches(tmp_path, monkeypatch, replacement):
    source = "build/example.py"
    direct = "tests/test_direct.py"
    route_file = "tests/test_routes.py"
    route_case = route_file + "::test_route[example]"
    added = "tests/test_added.py"
    _selection_fixture(tmp_path, {
        source: "",
        direct: "from build.example import run\n",
        route_file: "from build.example import run\n",
        added: "",
        "tests/test_override.py": "",
    })
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        source: pre_commit_pytest.ComponentTestPolicy(
            add=(added,), route=route_case, replace=replacement,
        ),
    })
    expected = list(replacement) if replacement is not None else sorted([direct, added, route_case])
    assert pre_commit_pytest.select_tests([source], tmp_path) == {
        "tests": expected, "unmapped": [],
    }


@pytest.mark.parametrize("policy, diagnostic", [
    (pre_commit_pytest.ComponentTestPolicy(
        add=("tests/test_missing.py",), route="tests/test_route_missing.py::test_route",
        replace=("tests/test_override.py",),
    ), "Stale component mapping"),
    (pre_commit_pytest.ComponentTestPolicy(
        route="tests/test_route_missing.py::test_route", replace=("tests/test_override.py",),
    ), "Stale route node mapping"),
])
def test_shadowed_policy_still_validates_in_order(tmp_path, monkeypatch, policy, diagnostic):
    source = "build/example.py"
    _selection_fixture(tmp_path, {source: "", "tests/test_override.py": ""})
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {source: policy})
    with pytest.raises(RuntimeError, match=diagnostic):
        pre_commit_pytest.select_tests([source], tmp_path)


def test_empty_replacement_suppresses_discovery_and_preserves_deletion_fallback(tmp_path, monkeypatch):
    source = "build/example.py"
    _selection_fixture(tmp_path, {"tests/test_direct.py": "from build.example import run\n"})
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        source: pre_commit_pytest.ComponentTestPolicy(replace=()),
    })
    assert pre_commit_pytest.select_tests([source], tmp_path) == {
        "tests": [], "unmapped": [source],
    }
    assert pre_commit_pytest.select_tests([source], tmp_path, deleted_paths=[source]) == {
        "tests": ["tests/test_direct.py"], "unmapped": [],
    }


def test_changed_test_policy_ignores_producer_rules_and_adds_consumer(tmp_path, monkeypatch):
    changed = "tests/test_changed.py"
    consumer = "tests/test_consumer.py::test_case"
    _selection_fixture(tmp_path, {changed: "", "tests/test_consumer.py": ""})
    monkeypatch.setattr(pre_commit_pytest, "COMPONENT_TEST_POLICIES", {
        changed: pre_commit_pytest.ComponentTestPolicy(
            add=("tests/test_missing.py",), route="tests/test_missing.py::test_route",
            replace=(changed + "::test_case", consumer),
        ),
    })
    assert pre_commit_pytest.select_tests([changed], tmp_path) == {
        "tests": [changed, consumer], "unmapped": [],
    }


@pytest.mark.parametrize("helper,expected", [('tests/npnf_install_runtime_fixture.py', ('tests/test_npnf104_work_acceptance_install.py', 'tests/test_npnf109_final_work_acceptance_install.py', 'tests/test_npnf109_next_work_acceptance_install.py', 'tests/test_npnf109_olympias_corpus_acceptance_install.py', 'tests/test_npnf109_rome_corpus_acceptance_install.py')), ('tests/runtime_candidate_baselines.py', ('tests/test_gregory_select_letters_npnf207_acceptance_stage.py', 'tests/test_lib028_remaining_histories_acceptance_stage.py', 'tests/test_lib028_socrates_sozomen_acceptance_stage.py', 'tests/test_npnf207_two_work_ccel_acceptance_stage.py', 'tests/test_schleitheim_confession_acceptance.py', 'tests/test_standard_ebooks_four_acceptance_stage.py', 'tests/test_sum_saving_knowledge_acceptance.py'))])
def test_single_runtime_helper_selects_transitive_fixture_consumers(tmp_path, helper, expected):
    targets = pre_commit_pytest.COMPONENT_TEST_POLICIES[helper].add
    files = {helper: "", **{target.split("::", 1)[0]: "" for target in targets}}
    module = helper.removesuffix(".py").replace("/", ".")
    files["tests/_current_adapter.py"] = f"from {module} import replay\n"
    for target in expected:
        files[target] = "from tests._current_adapter import replay\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([helper], tmp_path)
    assert selected["unmapped"] == []
    assert set(expected) <= {target.partition("::")[0] for target in selected["tests"]}


def test_vendored_schema_helper_selects_all_transitive_mirror_consumers(tmp_path):
    helper = "tests/vendored_schema_mirrors.py"
    expected = {
        "tests/test_vendored_schema_mirrors.py",
        "tests/test_historical_authority_mirrors.py",
        "tests/test_apostolic_tradition_reconstruction.py",
        "tests/test_gregory_select_letters_npnf207_acceptance_stage.py",
        "tests/test_moody_prevailing_prayer_61883_reconstruction.py",
        "tests/test_davis_l332_ia.py",
        "tests/test_methodius_first1kgreek.py",
        "tests/test_schleitheim_confession_acceptance.py",
        "tests/test_sum_saving_knowledge_acceptance.py",
        "tests/test_npnf207_two_work_ccel_acceptance_stage.py",
        "tests/test_augustines_pg3296_install.py",
        "tests/test_wikisource_l594_chrysostom_v2.py",
    }
    files = {
        helper: "",
        "tests/_schema_adapter.py": "from tests.vendored_schema_mirrors import copy_vendored_schema_imports\n",
        "tests/test_unrelated.py": "def test_other(): pass\n",
    }
    for target in expected:
        files[target] = "from tests._schema_adapter import replay\n"
    _selection_fixture(tmp_path, files)
    assert pre_commit_pytest.select_tests([helper], tmp_path) == {
        "tests": sorted(expected), "unmapped": [],
    }


def test_current_frozen_context_selects_exact_transitive_consumers(tmp_path):
    helper = "tests/current_frozen_install_context.py"
    expected = {
        'tests/test_old_elizabeth_pg17826_install.py',
        'tests/test_jarena_lee_pg66953_install.py',
        'tests/test_charnock_vol2_native_v2_install.py',
        'tests/test_luther_galatians_native_v2_install.py',
        'tests/test_before_most_holy_pg76888_install.py',
        'tests/test_eliza_southall_pg11959_install.py',
        'tests/test_evening_incense_pg50916_install.py',
        'tests/test_luther_pg1722_install.py',
        'tests/test_native_v2_install_runtime_manifests.py',
    }
    files = {
        helper: "",
        "tests/_frozen_context_adapter.py": "from tests.current_frozen_install_context import current_frozen_stage\n",
        "tests/test_unrelated.py": "def test_other(): pass\n",
    }
    for target in expected:
        files[target] = "from tests._frozen_context_adapter import replay\n"
    _selection_fixture(tmp_path, files)
    assert pre_commit_pytest.select_tests([helper], tmp_path) == {
        "tests": sorted(expected), "unmapped": [],
    }


@pytest.mark.parametrize("changed", (
    "tests/fixtures/reconstruction-runtime/native-v2-install-runtime-cases.json",
    "tests/fixtures/reconstruction-runtime/next-binding-checkpoint-install-contexts.json",
))
def test_installer_metadata_selects_new_record_and_live_runtime_proofs(tmp_path, changed):
    expected = {
        'tests/test_old_elizabeth_pg17826_install.py::test_runtime_manifest_preserves_complete_original_record',
        'tests/test_jarena_lee_pg66953_install.py::test_runtime_manifest_preserves_complete_original_record',
        'tests/test_native_v2_install_runtime_manifests.py',
        'tests/test_charnock_vol2_native_v2_install.py::test_exact_receipt_pin_and_read_only_preflight',
        'tests/test_luther_galatians_native_v2_install.py::test_exact_receipt_pin_and_read_only_preflight',
        'tests/test_before_most_holy_pg76888_install.py::test_runtime_source_preserves_complete_historical_record',
        'tests/test_eliza_southall_pg11959_install.py::test_runtime_source_preserves_complete_historical_record',
        'tests/test_evening_incense_pg50916_install.py::test_runtime_source_preserves_complete_historical_record',
        'tests/test_luther_pg1722_install.py::test_runtime_source_preserves_complete_historical_record',
    }
    files = {target.split("::", 1)[0]: "" for target in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected["unmapped"] == []
    assert expected <= set(selected["tests"])
    assert "tests/test_unrelated.py" not in selected["tests"]


def test_npnf104_work_producer_selects_real_conversion_and_resealed_mutation(tmp_path):
    source = "build/tei/npnf104_work_reconstruction.py"
    target = "tests/test_npnf104_work_candidates.py"
    _selection_fixture(tmp_path, {
        source: "",
        target: "from tests.npnf_work_runtime_baselines import current_work_baseline\n",
        "tests/test_npnf103_work_candidates.py": "def test_other_volume(): pass\n",
        "tests/test_unrelated.py": "def test_other(): pass\n",
    })
    assert pre_commit_pytest.select_tests([source], tmp_path) == {
        "tests": [target], "unmapped": [],
    }


@pytest.mark.parametrize("work_id", (
    "augustine-soliloquies", "augustine-sermon-on-the-mount",
    "augustine-tractates-on-john", "augustine-letters-part-1",
    "augustine-sermons-selected-lessons", "augustine-homilies-on-first-john",
))
@pytest.mark.parametrize("name", ("state.json", "work.json"))
def test_lib040_exact_before_fixture_selects_real_install_projection_and_rollback(tmp_path, work_id, name):
    changed = "tests/fixtures/reconstruction-runtime/authorities/lib040-child-install-preimage-" + work_id + "." + name
    target = "tests/test_install_lib040_augustine_child.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("work_id", ("ambrose-of-milan-on-holy-spirit", "ambrose-of-milan-concerning-virgins"))
@pytest.mark.parametrize("name", ("state.json", "work.json", "acquisition.json"))
def test_npnf210_frozen_before_fixture_selects_real_install_and_rollback(tmp_path, work_id, name):
    changed = "tests/fixtures/reconstruction-runtime/authorities/npnf210-two-before-" + work_id + "." + name
    target = "tests/test_npnf210_two_acceptances.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("changed", ('tests/fixtures/reconstruction-runtime/authorities/gangulf-before.acquisition.json', 'tests/fixtures/reconstruction-runtime/authorities/gangulf-before.boundary-readme.md', 'tests/fixtures/reconstruction-runtime/authorities/gangulf-before.manifest-before.json', 'tests/fixtures/reconstruction-runtime/authorities/gangulf-before.profile-before.json', 'tests/fixtures/reconstruction-runtime/authorities/gangulf-before.source-boundary.json', 'tests/fixtures/reconstruction-runtime/authorities/gangulf-before.state.json', 'tests/fixtures/reconstruction-runtime/authorities/gangulf-before.work.json'))
def test_gangulf_frozen_authority_selects_real_hymn_install_and_rollback(tmp_path, changed):
    target = "tests/test_gangulf_hymn.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("changed", ('tests/fixtures/reconstruction-runtime/ajops-v1-a11.source-manifest.json', 'tests/fixtures/reconstruction-runtime/ajops-v1-a2.source-manifest.json', 'tests/fixtures/reconstruction-runtime/ajops-v1-a18.source-manifest.json', 'tests/fixtures/reconstruction-runtime/ajops-v1-a22.source-manifest.json'))
def test_ajops_runtime_manifest_selects_real_reproduction_and_readable_link_negatives(tmp_path, changed):
    target = "tests/test_ajops_jats_link_repair.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]



def test_l594_runtime_manifest_selects_complete_export_reproduction_and_strict_mutants(tmp_path):
    changed = "tests/fixtures/reconstruction-runtime/wikisource-l594-chrysostom-v3.source-manifest.json"
    target = "tests/test_wikisource_l594_chrysostom_v2.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("changed", ('tests/fixtures/reconstruction-runtime/authorities/37c136-generic-source-manifest.json', 'tests/fixtures/reconstruction-runtime/authorities/37c136-generic-ticket.md', 'tests/fixtures/reconstruction-runtime/authorities/37c136-generic-policy.json'))
def test_37c136_generic_authorities_select_real_reproduction_and_semantic_mutants(tmp_path, changed):
    target = "tests/test_gutenberg_proofread_selected_sources.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


def test_37c136_specialized_policy_selects_current_hundred_note_positive_and_mutants(tmp_path):
    changed = "tests/fixtures/reconstruction-runtime/authorities/37c136-specialized-note-policy.json"
    target = "tests/test_gutenberg_proofread_selected_sources.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


def test_npnf205_install_metadata_selects_real_install_rollback_and_complete_record_proofs(tmp_path):
    changed = "tests/fixtures/reconstruction-runtime/npnf-four-install-before.json"
    target = "tests/test_npnf205_work_acceptance_stage.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("changed", ('tests/fixtures/reconstruction-runtime/authorities/four-source-before-drc.state.json', 'tests/fixtures/reconstruction-runtime/authorities/four-source-before-drc.work.json', 'tests/fixtures/reconstruction-runtime/authorities/four-source-before-maclaren-expositions.state.json', 'tests/fixtures/reconstruction-runtime/authorities/four-source-before-maclaren-expositions.work.json', 'tests/fixtures/reconstruction-runtime/authorities/four-source-before-robertson-word-pictures-vol1.state.json', 'tests/fixtures/reconstruction-runtime/authorities/four-source-before-robertson-word-pictures-vol1.work.json', 'tests/fixtures/reconstruction-runtime/authorities/four-source-before-westminster-shorter-catechism.state.json', 'tests/fixtures/reconstruction-runtime/authorities/four-source-before-westminster-shorter-catechism.work.json', 'tests/fixtures/reconstruction-runtime/authorities/four-source-before-robertson.README.source.md'))
def test_four_source_historical_authority_selects_real_boundary_and_rollback_owner(tmp_path, changed):
    target = "tests/test_four_source_accounting_sidecars.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


def test_bede_original_work_fixture_selects_real_complete_reconstruction_and_semantic_mutants(tmp_path):
    changed = "tests/fixtures/reconstruction-runtime/authorities/bede-original-work.json"
    target = "tests/test_bede_gutenberg_reconstruction.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("changed,target", (('tests/fixtures/reconstruction-runtime/authorities/boethius-complete-before.acquisition.json', 'tests/test_install_boethius_complete_envelope_acceptance.py'), ('tests/fixtures/reconstruction-runtime/authorities/boethius-complete-before.state.json', 'tests/test_install_boethius_complete_envelope_acceptance.py'), ('tests/fixtures/reconstruction-runtime/authorities/boethius-complete-before.work.json', 'tests/test_install_boethius_complete_envelope_acceptance.py'), ('tests/fixtures/reconstruction-runtime/authorities/didache-full-before.acquisition.json', 'tests/test_install_didache_full_witness_acceptance.py'), ('tests/fixtures/reconstruction-runtime/authorities/didache-full-before.state.json', 'tests/test_install_didache_full_witness_acceptance.py'), ('tests/fixtures/reconstruction-runtime/authorities/didache-full-before.work.json', 'tests/test_install_didache_full_witness_acceptance.py'), ('tests/fixtures/reconstruction-runtime/newman-pg34022-current-installer.source-manifest.json', 'tests/test_newman_grammar_pg34022_handoff.py')))
def test_late_install_metadata_selects_real_original_preimage_and_rollback_guards(tmp_path, changed, target):
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("changed", ('tests/fixtures/reconstruction-runtime/authorities/vincent-pg6733-before.acquisition.json', 'tests/fixtures/reconstruction-runtime/authorities/vincent-pg6733-before.state.json', 'tests/fixtures/reconstruction-runtime/authorities/vincent-pg6733-before.work.json', 'tests/fixtures/reconstruction-runtime/vincent-pg6733-current-installer.source-manifest.json'))
def test_vincent_install_metadata_selects_original_preimage_current_closure_and_real_rollback(tmp_path, changed):
    target = "tests/test_vincent_pg6733_install.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize(("changed", "target"), (('tests/fixtures/reconstruction-runtime/eliza-southall-pg11959-current-installer.source-manifest.json', 'tests/test_eliza_southall_pg11959_oracle.py'), ('tests/fixtures/reconstruction-runtime/evening-incense-pg50916-current-installer.source-manifest.json', 'tests/test_evening_incense_pg50916_oracle.py'), ('tests/fixtures/reconstruction-runtime/jarena-lee-pg66953-current-installer.source-manifest.json', 'tests/test_jarena_lee_pg66953_oracle.py'), ('tests/fixtures/reconstruction-runtime/arnulf-bsb830-current-cvw.source-manifest.json', 'tests/test_arnulf_bsb830_cvw.py'), ('tests/fixtures/reconstruction-runtime/authorities/npnf113-galatians-original-bound-work.json', 'tests/test_npnf113_work_candidates.py'), ('tests/fixtures/reconstruction-runtime/openmgh-exclusive-anulus-et-baculus.current.source-manifest.json', 'tests/test_openmgh_exclusive_reconstruction.py'), ('tests/fixtures/reconstruction-runtime/authorities/practical-mysticism-original-before.state.json', 'tests/test_practical_mysticism_spine_sidecars.py'), ('tests/fixtures/reconstruction-runtime/authorities/practical-mysticism-original-before.work.json', 'tests/test_practical_mysticism_spine_sidecars.py')))
def test_current_oracle_and_exact_before_metadata_selects_actual_mutation_and_reproduction_owners(tmp_path, changed, target):
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("changed", (
    "tests/fixtures/reconstruction-runtime/authorities/wikisource-l594-current-catalog-work.json",
    "tests/fixtures/reconstruction-runtime/authorities/wikisource-l594-current-catalog-state.json",
    "tests/fixtures/reconstruction-runtime/authorities/wikisource-l594-current-catalog-acquisition.json",
))
def test_l594_current_catalog_fixture_selects_real_reproduction_and_catalog_drift_guard(tmp_path, changed):
    target = "tests/test_wikisource_l594_chrysostom_v2.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files[target] = ""
    files["tests/test_unrelated.py"] = "def test_other(): pass\n"
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


@pytest.mark.parametrize("changed", ('tests/fixtures/reconstruction-runtime/authorities/augustine-on-christian-doctrine-original-bound-work.json', 'tests/fixtures/reconstruction-runtime/authorities/augustine-spirit-and-letter-original-bound-work.json', 'tests/fixtures/reconstruction-runtime/authorities/john-owen-conscience-original-bound-work.json', 'tests/fixtures/reconstruction-runtime/authorities/watson-beatitudes-original-bound-work.json', 'tests/fixtures/reconstruction-runtime/authorities/watson-body-of-divinity-original-bound-work.json', 'tests/fixtures/reconstruction-runtime/authorities/watson-divine-contentment-original-bound-work.json', 'tests/fixtures/reconstruction-runtime/authorities/watson-lords-prayer-original-bound-work.json', 'tests/fixtures/reconstruction-runtime/authorities/watson-ten-commandments-original-bound-work.json', 'tests/fixtures/reconstruction-runtime/authorities/bcp-1549-original-catalog-evidence.json', 'tests/fixtures/reconstruction-runtime/authorities/bcp-1559-original-catalog-evidence.json', 'tests/fixtures/reconstruction-runtime/authorities/bcp-1662-original-catalog-evidence.json', 'tests/fixtures/reconstruction-runtime/authorities/bcp-1662-collects-original-catalog-evidence.json', 'tests/fixtures/reconstruction-runtime/authorities/standard-ebooks-three-metadata-successor.json'))
def test_metadata_adoption_historical_support_selects_actual_boundaries(tmp_path, changed):
    targets = pre_commit_pytest.RUNTIME_FIXTURE_PROOFS
    files = {target.split("::", 1)[0]: "" for target in targets}
    files["tests/test_unrelated.py"] = ""
    _selection_fixture(tmp_path, files)
    selection = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selection == {"tests": sorted(targets), "unmapped": []}
    for target in ('tests/test_library_exclusive_multi_binding.py', 'tests/test_library_mixed_manifest_binding.py', 'tests/test_accepted_standard_ebooks_spine_rebind.py', 'tests/test_37c_317_watson_lords_prayer.py::test_bound_work_and_complete_source_envelope', 'tests/test_37c_318_watson_ten_commandments.py::test_bound_work_and_complete_source_envelope'):
        assert target in selection["tests"]
    assert "tests/test_unrelated.py" not in selection["tests"]


def test_bcp_historical_catalog_helper_selects_both_real_packet_consumers(tmp_path):
    changed = "tests/historical_bcp_packet_context.py"
    targets = ('tests/test_library_exclusive_multi_binding.py', 'tests/test_library_mixed_manifest_binding.py')
    _selection_fixture(tmp_path, {changed: "", **{target: "" for target in targets}})
    assert pre_commit_pytest.select_tests([changed], tmp_path) == {"tests": sorted(targets), "unmapped": []}



def test_watson_public_runtime_helper_selects_both_real_acceptance_mutation_owners(tmp_path):
    changed = "tests/watson_public_runtime_fixture.py"
    targets = ("tests/test_tei_acceptance_beatitudes.py", "tests/test_tei_acceptance_divine_contentment.py")
    _selection_fixture(tmp_path, {changed: "", **{target: "" for target in targets}})
    assert pre_commit_pytest.select_tests([changed], tmp_path) == {"tests": sorted(targets), "unmapped": []}



def test_pytest_child_uses_the_interpreter_that_checked_its_dependencies(monkeypatch):
    active = "F:/fixture-python314/python.exe"
    monkeypatch.setattr(pre_commit_pytest.sys, "executable", active)
    command = pre_commit_pytest._pytest_command(
        ["tests/test_example.py"], basetemp="F:/fixture-temp", xdist_available=False
    )
    assert command[:3] == [active, "-m", "pytest"]


@pytest.mark.parametrize(("changed", "target"), (('tests/fixtures/reconstruction-runtime/authorities/config-free-bcp-1928-collects-original-catalog.json', 'tests/test_library_config_free_multi_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/config-free-naves-topical-bible-original-catalog.json', 'tests/test_library_config_free_multi_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/exclusive-darby-original-catalog.json', 'tests/test_library_exclusive_manifest_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/exclusive-didache-prayers-original-catalog.json', 'tests/test_library_exclusive_manifest_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/exclusive-eastons-bible-dictionary-original-catalog.json', 'tests/test_library_exclusive_manifest_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/exclusive-hitchcocks-bible-names-dictionary-original-catalog.json', 'tests/test_library_exclusive_manifest_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/exclusive-schleitheim-confession-1527-original-catalog.json', 'tests/test_library_exclusive_manifest_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/exclusive-smiths-bible-dictionary-original-catalog.json', 'tests/test_library_exclusive_manifest_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/exclusive-sum-of-saving-knowledge-original-catalog.json', 'tests/test_library_exclusive_manifest_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/exclusive-torreys-topical-textbook-original-catalog.json', 'tests/test_library_exclusive_manifest_binding.py'), ('tests/fixtures/reconstruction-runtime/authorities/four-source-drc-original-catalog.json', 'tests/test_four_source_accounting_sidecars.py'), ('tests/fixtures/reconstruction-runtime/authorities/four-source-maclaren-expositions-original-catalog.json', 'tests/test_four_source_accounting_sidecars.py'), ('tests/fixtures/reconstruction-runtime/authorities/four-source-robertson-word-pictures-vol1-original-catalog.json', 'tests/test_four_source_accounting_sidecars.py'), ('tests/fixtures/reconstruction-runtime/authorities/wesley-exception-john-wesley-sermons-original-catalog.json', 'tests/test_library_manifest_exception_binding.py')))
def test_exact_historical_catalog_fixtures_select_their_real_packet_owners(tmp_path, changed, target):
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files["tests/test_unrelated.py"] = ""
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


def test_prayer_held_work_selects_real_acceptance_and_handoff_guards(tmp_path):
    changed = "tests/fixtures/reconstruction-runtime/authorities/watson-lords-prayer-original-bound-work.json"
    target = "tests/test_prepare_watson_lords_prayer_acceptance.py"
    files = {node.split("::", 1)[0]: "" for node in pre_commit_pytest.RUNTIME_FIXTURE_PROOFS}
    files["tests/test_unrelated.py"] = ""
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(pre_commit_pytest.RUNTIME_FIXTURE_PROOFS)), "unmapped": []}
    assert target in selected["tests"]
    assert "tests/test_unrelated.py" not in selected["tests"]


def test_retained_handoff_helper_selects_all_real_current_and_original_rejection_consumers(tmp_path):
    changed = "tests/retained_handoff_runtime_fixture.py"
    targets = ('tests/test_prepare_law_serious_call_acceptance.py', 'tests/test_prepare_owen_conscience_acceptance.py', 'tests/test_prepare_augustine_christian_doctrine_acceptance.py')
    _selection_fixture(tmp_path, {changed: "", **{target: "" for target in targets}})
    assert pre_commit_pytest.select_tests([changed], tmp_path) == {"tests": sorted(targets), "unmapped": []}


@pytest.mark.parametrize("changed", ('tests/fixtures/reconstruction-runtime/john-owen-conscience.source-manifest.json', 'tests/fixtures/reconstruction-runtime/augustine-on-christian-doctrine.source-manifest.json'))
def test_retained_handoff_runtime_records_select_actual_acceptance_consumers(tmp_path, changed):
    targets = pre_commit_pytest.RUNTIME_FIXTURE_PROOFS
    files = {node.split("::", 1)[0]: "" for node in targets}
    _selection_fixture(tmp_path, files)
    selected = pre_commit_pytest.select_tests([changed], tmp_path)
    assert selected == {"tests": sorted(set(targets)), "unmapped": []}
    assert "tests/test_prepare_owen_conscience_acceptance.py" in selected["tests"]
    assert "tests/test_prepare_augustine_christian_doctrine_acceptance.py" in selected["tests"]


def test_contentment_closure_helper_selects_real_versioning_reproduction_and_drift_owner(tmp_path):
    changed = "tests/watson_rebind_runtime_fixture.py"
    target = 'tests/test_prepare_watson_divine_contentment_closure_rebind.py'
    _selection_fixture(tmp_path, {changed: "", target: ""})
    assert pre_commit_pytest.select_tests([changed], tmp_path) == {"tests": [target], "unmapped": []}


def test_authority_checks_precede_book_reconstructions_without_dropping_targets(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 60_000)
    monkeypatch.setattr(pre_commit_pytest.os, "cpu_count", lambda: 8)
    targets = [
        "tests/test_other.py::test_first[space and :: punctuation]",
        "tests/test_maclaren_native.py::test_lines",
        "tests/test_four_source_accounting_sidecars.py::test_second",
        "tests/test_whitefield_two_witness_sidecars.py",
        "tests/test_four_source_accounting_sidecars.py::test_first",
        "tests/test_other.py::test_last",
    ]
    command = pre_commit_pytest._pytest_command(targets, basetemp="temporary", xdist_available=True)
    assert command[-len(targets):] == [targets[i] for i in (2, 4, 3, 1, 0, 5)]
    assert "--maxfail=1" not in command
    assert "--no-loadscope-reorder" in command


def test_parallel_native_priority_preserves_exact_nodes_and_serial_order(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 60_000)
    monkeypatch.setattr(pre_commit_pytest.os, "cpu_count", lambda: 8)
    monkeypatch.setenv(pre_commit_pytest.WORKER_LIMIT_ENV, "2")
    targets = [
        "tests/test_other.py::test_first[space and :: punctuation]",
        "tests/test_augustine_psalms_native.py::test_psalms",
        "tests/test_maclaren_native.py::test_lines[second selected member]",
        "tests/test_other.py::test_last",
        "tests/test_maclaren_native.py::test_lines[first selected member]",
    ]
    original = list(targets)
    command = pre_commit_pytest._pytest_command(targets, basetemp="temporary", xdist_available=True)
    assert command[-len(targets):] == [targets[2], targets[4], targets[1], targets[0], targets[3]]
    assert command[command.index("--dist") + 1] == "loadfile"
    assert command[command.index("-n") + 1] == "2"
    assert "--no-loadscope-reorder" in command
    assert targets == original
    serial = pre_commit_pytest._pytest_command(targets, basetemp="temporary", xdist_available=False)
    assert serial[-len(targets):] == targets
    assert "--no-loadscope-reorder" not in serial and "--dist" not in serial
    unrelated = [targets[0], targets[3], "tests/test_third.py::test_other"]
    ordinary = pre_commit_pytest._pytest_command(unrelated, basetemp="temporary", xdist_available=True)
    assert ordinary[-len(unrelated):] == unrelated
    assert "--dist" in ordinary and "--no-loadscope-reorder" not in ordinary


def test_successful_corpus_temp_is_removed_before_the_next_test(tmp_path):
    sentinel = tmp_path / "previous-copy.txt"
    case = tmp_path / "test_retention.py"
    case.write_text(
        "from pathlib import Path\n"
        "def test_create_copy(tmp_path):\n"
        "    (tmp_path / 'payload').write_bytes(b'corpus copy')\n"
        f"    Path({str(sentinel)!r}).write_text(str(tmp_path))\n"
        "def test_previous_copy_is_gone():\n"
        f"    assert not Path(Path({str(sentinel)!r}).read_text()).exists()\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "-c", str(Path(pre_commit_pytest.REPO_ROOT) / "pyproject.toml"),
         "--basetemp", str(tmp_path / "child-base"), str(case)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


def test_long_corpus_files_start_early_without_changing_coverage(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 60_000)
    monkeypatch.setattr(pre_commit_pytest.os, "cpu_count", lambda: 8)
    targets = [
        "tests/test_other.py::test_first",
        "tests/test_john_owen_lib050_reconstruction_contract.py::test_routes",
        "tests/test_spurgeon_mtp_reconstruction_contract.py::test_source",
        "tests/test_reconstruction_closure_corpus.py::test_bindings",
        "tests/test_spurgeon_mtp_reconstruction_contract.py::test_mutation",
    ]
    command = pre_commit_pytest._pytest_command(targets, basetemp="temporary", xdist_available=True)
    assert command[-len(targets):] == [targets[i] for i in (3, 2, 4, 1, 0)]
    assert "--no-loadscope-reorder" in command
    assert "-m" not in command[3:]


def test_shared_catalog_waiters_do_not_block_workers_with_other_work_available(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 60_000)
    monkeypatch.setattr(pre_commit_pytest.os, "cpu_count", lambda: 8)
    targets = [
        "tests/test_count_dataset_records.py",
        "tests/test_other.py::test_first",
        "tests/test_john_owen_lib050_reconstruction_contract.py",
        "tests/test_douay_rheims_reconstruction_contract.py::test_route",
        "tests/test_calvins_institutes_pg64392_member_contract.py",
        "tests/test_another.py",
    ]
    command = pre_commit_pytest._pytest_command(targets, basetemp="temporary", xdist_available=True)
    assert command[-len(targets):] == [targets[i] for i in (2, 1, 5, 0, 3, 4)]
    assert sorted(command[-len(targets):]) == sorted(targets)
    assert "-m" not in command[3:]


@pytest.mark.parametrize("platform,expected", [("win32", 0x4000), ("linux", 0)])
def test_pytest_child_yields_windows_cpu_to_interactive_work(tmp_path, monkeypatch, platform, expected):
    calls = []
    monkeypatch.setattr(pre_commit_pytest.sys, "platform", platform)
    monkeypatch.setattr(pre_commit_pytest.subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000, raising=False)
    monkeypatch.setattr(pre_commit_pytest, "_pytest_temp_parent", lambda: tmp_path)
    monkeypatch.setattr(pre_commit_pytest, "_pytest_command", lambda *args, **kwargs: ["pytest-probe"])

    def run(command, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pre_commit_pytest.subprocess, "run", run)
    assert pre_commit_pytest._run_pytest(["tests/test_example.py"]) == 0
    assert len(calls) == 1 and calls[0]["creationflags"] == expected
    assert calls[0]["check"] is True


def test_public_input_inventory_changes_require_its_declaration_proofs(tmp_path):
    _selection_fixture(tmp_path, {"tests/test_public_release_inputs.py": ""})
    assert pre_commit_pytest.select_tests(["tests/fixtures/public-local-input-cases.json"], tmp_path) == {
        "tests": ["tests/test_public_release_inputs.py"], "unmapped": [],
    }


def test_failed_gate_stops_early_and_passing_gate_runs_every_case(tmp_path):
    case = tmp_path / "test_failfast_probe.py"
    sentinel = tmp_path / "second-ran"

    def write_case(first_passes):
        case.write_text(
            "from pathlib import Path\n"
            "def test_first():\n"
            f"    assert {first_passes!r}\n"
            "def test_second():\n"
            f"    Path({str(sentinel)!r}).write_text('checked')\n",
            encoding="utf-8",
        )

    write_case(False)
    command = pre_commit_pytest._pytest_command(
        [str(case)], basetemp=str(tmp_path / "failed-base"), xdist_available=False,
    )
    failed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert not sentinel.exists()
    write_case(True)
    command = pre_commit_pytest._pytest_command(
        [str(case)], basetemp=str(tmp_path / "passed-base"), xdist_available=False,
    )
    passed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert "2 passed" in passed.stdout
    assert sentinel.read_text() == "checked"


def test_runtime_byte_guards_precede_full_book_reconstruction(monkeypatch):
    monkeypatch.setattr(pre_commit_pytest.os.path, "getsize", lambda _: 60_000)
    monkeypatch.setattr(pre_commit_pytest.os, "cpu_count", lambda: 8)
    targets = ["tests/test_spurgeon_mtp_reconstruction_contract.py",
               "tests/test_executable_checkout_bytes.py",
               "tests/test_runtime_manifest_binding_boundaries.py"]
    command = pre_commit_pytest._pytest_command(targets, basetemp="temporary", xdist_available=True)
    assert command[-3:] == [targets[2], targets[1], targets[0]]
