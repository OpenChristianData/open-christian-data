"""Pytest plugin for optional data and explicit LIB-084 E2E inputs.

Three surfaces:

    @pytest.mark.raw_required(path)
        Decorator/marker for tests whose required file path is known at
        collection time (module-level constant or config lookup). The plugin
        resolves the path at collection time and inserts a skip marker if the
        file is missing.

    @pytest.mark.lib084_oracle_e2e
        Selected complete-corpus LIB-084 oracle tests must expose an
        accessible ``testmodule.CANDIDATE / "package"``. The check runs at
        collection time after marker deselection. ``--collect-only`` remains
        discovery-only and does not require the external candidate.

    skip_if_missing_data(path)
        Runtime helper for tests where the path is computed from a parametrize
        value or otherwise unknown until the test runs. Lives in
        build/lib/pytest_skips.py so it imports cleanly from any test file
        (REPO_ROOT is on sys.path).

Skip reason format: "raw data file not present: <path>".

The marker name is "raw" in the OCD sense: any data file (raw archive, parsed
output JSON, fixture) that isn't checked in and may not exist on a fresh clone.
The shared reason makes filtered test runs and skip-report scanning
straightforward.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from build.lib.pytest_skips import _SKIP_REASON_FMT  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "raw_required(path): skip when the named file is not on disk.",
    )


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """Apply raw skips and fail selected LIB-084 E2E items before execution."""

    for item in items:
        marker = item.get_closest_marker("raw_required")
        if marker is None:
            continue
        if not marker.args:
            raise pytest.UsageError(
                f"{item.nodeid}: @pytest.mark.raw_required requires a path argument"
            )
        path = Path(marker.args[0])
        if not path.exists():
            item.add_marker(pytest.mark.skip(reason=_SKIP_REASON_FMT.format(path=path)))

    # Collection is intentionally allowed to describe the complete E2E set
    # without requiring the external candidate. The selected test list has
    # already been filtered by pytest's -m expression at trylast time.
    if config.getoption("collectonly"):
        return

    missing: list[str] = []
    for item in items:
        if item.get_closest_marker("lib084_oracle_e2e") is None:
            continue
        candidate_value = getattr(item.module, "CANDIDATE", None)
        if candidate_value is None:
            missing.append(f"{item.nodeid}: test module does not define CANDIDATE")
            continue
        candidate = Path(candidate_value)
        package = candidate / "package"
        try:
            accessible = package.resolve(strict=True).is_dir()
        except (OSError, RuntimeError):
            accessible = False
        if not accessible:
            missing.append(f"{item.nodeid}: {package}")

    if missing:
        raise pytest.UsageError(
            "Selected LIB-084 E2E tests require an accessible candidate package. "
            "Build it with the maintained CLI:\n"
            "  py -3 -m build.tools.reconstruct_candidate --manifest "
            "tests/fixtures/reconstruction-runtime/spurgeon-mtp.source-manifest.json "
            "--destination <external-candidate-root> --repository-root .\n"
            "Then set OCD_LIB084_CANDIDATE=<external-candidate-root>.\n"
            "Missing selected candidate inputs:\n"
            + "\n".join(f"  - {entry}" for entry in missing)
        )
