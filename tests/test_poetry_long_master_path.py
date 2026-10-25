"""Windows edition routing must read retained masters past MAX_PATH."""
from __future__ import annotations

import os

import pytest

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories.poetry import _uses_native_edition


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
@pytest.mark.parametrize("division_type,expected", [("work", True), ("poem", False)])
def test_long_master_keeps_source_defined_poetry_route(tmp_path, division_type, expected):
    master = tmp_path / ("retained-edition-" * 7) / ("work-identity-" * 7) / "master.tei.xml"
    assert len(str(master)) > 260
    io_path(master.parent).mkdir(parents=True)
    io_path(master).write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        f'<div type="{division_type}"><ab>Source verse.</ab></div>'
        '</body></text></TEI>', encoding="utf-8",
    )
    assert _uses_native_edition(master) is expected


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
def test_invalid_long_master_still_fails_closed(tmp_path):
    master = tmp_path / ("retained-edition-" * 7) / ("work-identity-" * 7) / "master.tei.xml"
    io_path(master.parent).mkdir(parents=True)
    io_path(master).write_text('<TEI><text>', encoding="utf-8")
    with pytest.raises(PipelineError, match="invalid poetry XML"):
        _uses_native_edition(master)
