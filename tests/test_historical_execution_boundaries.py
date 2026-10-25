"""Frozen standalone recipes reject missing inputs without changing retained records."""

from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_cli_input_guards import _invoke


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module", [
    "build.tools.probe_blaikie_joshua_title_execution",
    "build.tools.probe_farrar_retained_execution",
    "build.tools.probe_smith_isaiah_execution",
    "build.tools.probe_watson_retained_execution",
])
def test_retained_execution_probe_rejects_missing_stage_before_operations(tmp_path, module):
    missing = tmp_path / "missing-stage"
    result = _invoke(module, str(missing))
    assert result.returncode != 0
    assert "FileNotFoundError" in result.stderr
    assert "missing-stage" in result.stderr
    assert "attempted an operation" not in result.stderr
    assert "attempted operations" not in result.stderr
    assert not missing.exists()


def test_blaikie_first_samuel_derivative_requires_retained_source_before_writing_files(tmp_path):
    script = ROOT / "build/tools/prepare_blaikie_first_samuel_route.py"
    result = subprocess.run(
        [sys.executable, "-B", str(script)], cwd=tmp_path,
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "FileNotFoundError" in result.stderr
    assert "blaikie_expositor8.xml" in result.stderr
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize(("module", "destination", "reason"), [
    ("build.tools.prepare_maclaren_code", "build/tei/maclaren_retained_native_emitter.py", "Preserve Maclaren derivative"),
    ("build.tools.prepare_maclaren_stage_code", "build/tools/stage_maclaren_retained_acceptance.py", "Preserve existing Maclaren standalone guard"),
])
def test_frozen_maclaren_recipe_preserves_existing_derivative(module, destination, reason):
    path = ROOT / destination
    before = path.read_bytes()
    result = _invoke(module, "ignored-by-retained-recipe")
    assert result.returncode != 0
    assert "FileExistsError" in result.stderr
    assert reason in result.stderr
    assert "attempted an operation" not in result.stderr
    assert "attempted operations" not in result.stderr
    assert path.read_bytes() == before
