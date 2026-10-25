"""Regression coverage for preserving Windows extended prefixes on deep paths."""

import os
from pathlib import Path

from ocd_kernel.lib import path_io


def test_resolve_preserves_prefix_for_deep_existing_path(tmp_path: Path) -> None:
    deep = tmp_path / ("retained-" * 12) / ("edition-" * 12) / ("evidence-" * 6)
    assert len(str(deep)) > 260

    physical = path_io.io_path(deep)
    physical.mkdir(parents=True)
    resolved = path_io.resolve_path(physical, strict=True, preserve_prefix=True)
    assert resolved.samefile(physical)

    if os.name == "nt":
        assert str(resolved).startswith("\\\\?\\")
    else:
        assert resolved == deep.resolve(strict=True)
