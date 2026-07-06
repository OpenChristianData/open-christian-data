from __future__ import annotations

from pathlib import Path

from build.lib.paths import REPO_ROOT


def test_repo_root_points_to_project_root() -> None:
    pyproject_path = Path(REPO_ROOT) / "pyproject.toml"

    assert pyproject_path.is_file()
