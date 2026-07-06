"""Pytest plugin: skip tests when their data file is absent on this checkout.

Two surfaces:

    @pytest.mark.raw_required(path)
        Decorator/marker for tests whose required file path is known at
        collection time (module-level constant or config lookup). The plugin
        resolves the path at collection time and inserts a skip marker if the
        file is missing.

    skip_if_missing_data(path)
        Runtime helper for tests where the path is computed from a parametrize
        value or otherwise unknown until the test runs. Lives in
        build/lib/pytest_skips.py so it imports cleanly from any test file
        (REPO_ROOT is on sys.path).

Skip reason format: "raw data file not present: <path>".

The marker name is "raw" in the OCD sense: any data file (raw archive, parsed
output JSON, fixture) that isn't checked in and may not exist on a fresh
clone. The shared reason makes filtered test runs and skip-report scanning
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


def pytest_collection_modifyitems(config, items):
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
