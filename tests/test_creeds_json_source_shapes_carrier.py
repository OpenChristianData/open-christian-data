"""Integrated carrier mutation checks for new Canon and nested source shapes."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from build.tools.install_creeds_json_canon_variants import STAGE_PARENT as CANON_STAGES
from build.tools.install_creeds_json_nested_confessions import STAGE_PARENT as NESTED_STAGES
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.tei.install_accepted import _io_path


@pytest.mark.parametrize(
    ("stage_parent", "work_id"),
    [
        (CANON_STAGES, "council-of-orange"),
        (CANON_STAGES, "helvetic-consensus"),
        (NESTED_STAGES, "canons-of-dort"),
        (NESTED_STAGES, "savoy-declaration"),
    ],
)
def test_exact_source_shape_and_mutation(stage_parent: Path, work_id: str) -> None:
    stage = stage_parent / work_id
    if not _io_path(stage / "final-stage-receipt.json").is_file():
        pytest.skip("pinned source-shape stage is not mounted")
    acceptance = (stage / "library/works" / work_id / "forms" /
                  f"{work_id}-retained-electronic" / "editions" /
                  f"{work_id}-creeds-json" / "acceptance.json")
    output = project_accepted_doctrinal_documents(_io_path(stage), acceptance_path=_io_path(acceptance))
    assert verify_accepted_doctrinal_documents(
        _io_path(stage), acceptance_path=_io_path(acceptance),
        rows=output["rows"], receipt=output["receipt"],
    ) == []
    changed = deepcopy(output["rows"])
    changed[-1]["locator"]["unit_path"][-1] = "invented"
    assert verify_accepted_doctrinal_documents(
        _io_path(stage), acceptance_path=_io_path(acceptance),
        rows=changed, receipt=output["receipt"],
    )
