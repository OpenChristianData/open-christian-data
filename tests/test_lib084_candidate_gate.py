"""Synthetic subprocess regressions for the LIB-084 collection gate.

These tests copy the candidate ``tests/conftest.py`` into a temporary
synthetic project and invoke pytest synchronously. They never use the retained
corpus or the real LIB-084 candidate. Every child receives an explicit nested
basetemp under a parent pytest temp directory, which is outside this checkout.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_CONFTEST = REPO_ROOT / "tests" / "conftest.py"
BUILD_INIT = REPO_ROOT / "build" / "__init__.py"
BUILD_LIB_INIT = REPO_ROOT / "build" / "lib" / "__init__.py"
PYTEST_SKIPS = REPO_ROOT / "build" / "lib" / "pytest_skips.py"


def _literal(path: Path) -> str:
    return repr(str(path))


def _write_project(
    tmp_path: Path,
    module_source: str,
    *,
    name: str,
) -> tuple[Path, Path]:
    """Create one isolated project and return (project, child_basetemp)."""

    project = tmp_path / f"synthetic-{name}"
    tests = project / "tests"
    tests.mkdir(parents=True)
    shutil.copy2(LIVE_CONFTEST, tests / "conftest.py")
    build_lib = project / "build" / "lib"
    build_lib.mkdir(parents=True)
    shutil.copy2(BUILD_INIT, project / "build" / "__init__.py")
    shutil.copy2(BUILD_LIB_INIT, build_lib / "__init__.py")
    helper = build_lib / "pytest_skips.py"
    shutil.copy2(PYTEST_SKIPS, helper)
    (project / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        "testpaths = [\"tests\"]\n"
        "addopts = [\"--tb=short\"]\n"
        "markers = [\n"
        "    \"slow: synthetic slow test\",\n"
        "    \"lib084_oracle_e2e: synthetic LIB-084 E2E test\",\n"
        "]\n",
        encoding="utf-8",
    )
    (tests / "test_synthetic.py").write_text(module_source, encoding="utf-8")

    child_basetemp = tmp_path / f"child-basetemp-{name}" / "nested"
    resolved_root = REPO_ROOT.resolve()
    resolved_basetemp = child_basetemp.resolve()
    assert resolved_root not in (resolved_basetemp, *resolved_basetemp.parents)
    return project, child_basetemp


def _run_child(
    project: Path,
    child_basetemp: Path,
    *pytest_args: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("OCD_LIB084_CANDIDATE", None)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTHONPATH", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(child_basetemp),
        *pytest_args,
    ]
    return subprocess.run(
        command,
        cwd=project,
        env=env,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


@pytest.mark.lib084_candidate_local
@pytest.mark.slow
def test_selected_missing_candidate_fails_before_test_body(tmp_path: Path) -> None:
    candidate = tmp_path / "missing-candidate"
    sentinel = tmp_path / "body-ran.txt"
    source = f"""from pathlib import Path
import pytest

CANDIDATE = Path({_literal(candidate)})
SENTINEL = Path({_literal(sentinel)})

@pytest.mark.lib084_oracle_e2e
def test_selected_e2e_body():
    SENTINEL.write_text("body ran", encoding="utf-8")
"""
    project, child_basetemp = _write_project(tmp_path, source, name="missing")

    result = _run_child(project, child_basetemp, "-m", "lib084_oracle_e2e", "-q")
    output = _output(result)

    assert result.returncode != 0, output
    assert not sentinel.exists()
    assert "Selected LIB-084 E2E tests require an accessible candidate package" in output
    assert "reconstruct_candidate" in output
    assert "OCD_LIB084_CANDIDATE" in output


@pytest.mark.lib084_candidate_local
@pytest.mark.slow
def test_deselected_e2e_does_not_block_fast_selection(tmp_path: Path) -> None:
    candidate = tmp_path / "missing-candidate"
    slow_sentinel = tmp_path / "slow-body-ran.txt"
    fast_sentinel = tmp_path / "fast-body-ran.txt"
    source = f"""from pathlib import Path
import pytest

CANDIDATE = Path({_literal(candidate)})
SLOW_SENTINEL = Path({_literal(slow_sentinel)})
FAST_SENTINEL = Path({_literal(fast_sentinel)})

@pytest.mark.lib084_oracle_e2e
@pytest.mark.slow
def test_deselected_e2e_body():
    SLOW_SENTINEL.write_text("slow body ran", encoding="utf-8")

def test_fast_body():
    FAST_SENTINEL.write_text("fast body ran", encoding="utf-8")
"""
    project, child_basetemp = _write_project(tmp_path, source, name="deselected")

    result = _run_child(project, child_basetemp, "-m", "not slow", "-q")
    output = _output(result)

    assert result.returncode == 0, output
    assert fast_sentinel.exists()
    assert not slow_sentinel.exists()
    assert "Selected LIB-084 E2E tests require" not in output
    assert "1 passed" in output
    assert "1 deselected" in output


@pytest.mark.lib084_candidate_local
@pytest.mark.slow
def test_collect_only_does_not_require_candidate(tmp_path: Path) -> None:
    candidate = tmp_path / "missing-candidate"
    sentinel = tmp_path / "body-ran.txt"
    source = f"""from pathlib import Path
import pytest

CANDIDATE = Path({_literal(candidate)})
SENTINEL = Path({_literal(sentinel)})

@pytest.mark.lib084_oracle_e2e
def test_collect_only_e2e_body():
    SENTINEL.write_text("body ran", encoding="utf-8")
"""
    project, child_basetemp = _write_project(tmp_path, source, name="collect-only")

    result = _run_child(
        project,
        child_basetemp,
        "--collect-only",
        "-m",
        "lib084_oracle_e2e",
        "-q",
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert "test_synthetic.py::test_collect_only_e2e_body" in output
    assert not sentinel.exists()
    assert "OCD_LIB084_CANDIDATE" not in output


@pytest.mark.lib084_candidate_local
@pytest.mark.slow
def test_valid_candidate_allows_selected_e2e_execution(tmp_path: Path) -> None:
    candidate = tmp_path / "valid-candidate"
    (candidate / "package").mkdir(parents=True)
    sentinel = tmp_path / "body-ran.txt"
    source = f"""from pathlib import Path
import pytest

CANDIDATE = Path({_literal(candidate)})
SENTINEL = Path({_literal(sentinel)})

@pytest.mark.lib084_oracle_e2e
def test_valid_e2e_body():
    SENTINEL.write_text("body ran", encoding="utf-8")
"""
    project, child_basetemp = _write_project(tmp_path, source, name="valid")

    result = _run_child(project, child_basetemp, "-m", "lib084_oracle_e2e", "-q")
    output = _output(result)

    assert result.returncode == 0, output
    assert sentinel.exists()
    assert "1 passed" in output
