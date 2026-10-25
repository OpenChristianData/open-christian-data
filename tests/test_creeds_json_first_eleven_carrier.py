"""Source-family and row mutations against pinned external Creeds stages."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from build.tools.install_creeds_json_first_eleven import STAGE_PARENT
from ocd_kernel.projection.categories import creeds_json_carrier as carrier
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.tei.install_accepted import _io_path


@pytest.mark.parametrize("work_id", ["consensus-tigurinus", "gregorys-declaration-of-faith", "tertullians-rule-of-faith"])
def test_family_oracle_and_mutated_row(work_id: str) -> None:
    stage = STAGE_PARENT / work_id
    if not _io_path(stage / "final-stage-receipt.json").is_file():
        pytest.skip("pinned durable Creeds stage is not mounted")
    acceptance = (stage / "library/works" / work_id / "forms" /
                  f"{work_id}-retained-electronic" / "editions" /
                  f"{work_id}-creeds-json" / "acceptance.json")
    output = project_accepted_doctrinal_documents(_io_path(stage), acceptance_path=_io_path(acceptance))
    assert verify_accepted_doctrinal_documents(
        _io_path(stage), acceptance_path=_io_path(acceptance),
        rows=output["rows"], receipt=output["receipt"],
    ) == []
    mutated = deepcopy(output["rows"])
    mutated[0]["content"] += " changed"
    assert verify_accepted_doctrinal_documents(
        _io_path(stage), acceptance_path=_io_path(acceptance),
        rows=mutated, receipt=output["receipt"],
    )


@pytest.mark.parametrize("work_id", ["gregorys-declaration-of-faith", "tertullians-rule-of-faith"])
def test_family_checker_rejects_wrong_carrier_namespace(work_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    stage = STAGE_PARENT / work_id
    if not _io_path(stage / "final-stage-receipt.json").is_file():
        pytest.skip("pinned durable Creeds stage is not mounted")
    acceptance = (stage / "library/works" / work_id / "forms" /
                  f"{work_id}-retained-electronic" / "editions" /
                  f"{work_id}-creeds-json" / "acceptance.json")
    context = carrier._context(_io_path(stage), _io_path(acceptance))
    carrier._oracle_tree(context)
    original_json = carrier._json

    def wrong_manifest(path: Path) -> dict[str, object]:
        value = original_json(path)
        if path.name == "manifest.json":
            value["source_manifest"]["path"] = value["source_manifest"]["path"].replace(
                "lib064-creeds-json", "lib063-creeds-json"
            ).replace("lib065-creeds-json", "lib063-creeds-json")
        return value

    monkeypatch.setattr(carrier, "_json", wrong_manifest)
    with pytest.raises(ValueError, match="TEI div element or attributes drifted"):
        carrier._oracle_tree(context)
