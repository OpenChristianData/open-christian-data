"""Tests for deterministic repository-local Python dependency closure."""

from pathlib import Path

import pytest

from cvw_phase1b.dependency_closure import (
    DependencyClosureError,
    collect_local_python_dependencies,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def test_collects_transitive_absolute_and_relative_local_imports(tmp_path: Path) -> None:
    _write(tmp_path / "build/parsers/entry.py", "from build.lib import helper\n")
    _write(tmp_path / "build/lib/helper.py", "from .nested import VALUE\n")
    _write(tmp_path / "build/lib/nested.py", "VALUE = 1\n")

    assert collect_local_python_dependencies(
        tmp_path, ["build/parsers/entry.py"]
    ) == (
        "build/lib/helper.py",
        "build/lib/nested.py",
        "build/parsers/entry.py",
    )


def test_closure_is_cycle_safe_and_rejects_missing_entry(tmp_path: Path) -> None:
    _write(tmp_path / "cvw_phase1b/a.py", "from . import b\n")
    _write(tmp_path / "cvw_phase1b/b.py", "from . import a\n")

    assert collect_local_python_dependencies(tmp_path, ["cvw_phase1b/a.py"]) == (
        "cvw_phase1b/a.py",
        "cvw_phase1b/b.py",
    )
    with pytest.raises(DependencyClosureError, match="missing"):
        collect_local_python_dependencies(tmp_path, ["cvw_phase1b/missing.py"])
