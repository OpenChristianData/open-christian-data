"""Helpers for tests that depend on data files absent from a fresh clone.

Companion to the `raw_required` pytest marker registered in
`tests/conftest.py`. The marker covers statically-resolvable paths. This
helper covers the parametrized-path case, where the path depends on the
test's runtime parameters and cannot be evaluated at collection time:

    @pytest.mark.parametrize("slug", ALL_SLUGS)
    def test_foo(slug):
        out = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
        skip_if_missing_data(out)
        ...

Skip reason format matches the marker for grep-friendliness.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_SKIP_REASON_FMT = "raw data file not present: {path}"


def skip_if_missing_data(path) -> None:
    path = Path(path)
    if not path.exists():
        pytest.skip(_SKIP_REASON_FMT.format(path=path))
