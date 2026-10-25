"""Exact public scope and inverse for the accepted Edwards electronic witness."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.release import public_rows as boundary
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/edwards-religious-affections/forms/edwards-religious-affections-english/editions/ccel-thml-electronic-witness/acceptance.json"
SAVED = ROOT / "reports/_logs/edwards-religious-affections-offline-release-20261001-v1/actual-master-projection.json"
AUTHORITY = {"acceptance_sha256": "84ba0cc0fca7bcc6d803522a9f69116f7d87aa752959d53f7039bcf808c190d0",
             "master_sha256": "2375aa5844ba313ed31bb849fce381884585676b24e13bcd3adc2f6dbb0908c8"}
SAVED_SHA256 = "08b7783600876f44dfac140ff4a6eeefd3b6226d967aae37777fb1d3740e38cf"


def _private_rows() -> list[dict]:
    if SAVED.is_file():
        assert sha256(SAVED.read_bytes()).hexdigest() == SAVED_SHA256
        projection = json.loads(SAVED.read_text(encoding="utf-8"))
    elif ACCEPTANCE.is_file():
        projection = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    else:
        pytest.skip("accepted Edwards witness is not installed")
    licensed = [dict(row, license=boundary.EDWARDS_LICENSE) for row in projection["rows"]]
    rows, _receipt = compose_work_metadata(ROOT, licensed, projection["receipt"])
    return rows


def test_edwards_styles_keep_semantics_and_reject_unreviewed_css() -> None:
    assert boundary._edwards_style("font-family:Gentium", "emphasis") is None
    assert boundary._edwards_style("font-variant:small-caps", "emphasis") == "small-caps"
    assert boundary._edwards_style("title ; text-align:left", "paragraph") == "title"
    assert boundary._edwards_style("italic", "emphasis") == "italic"
    with pytest.raises(PipelineError, match="presentation differs"):
        boundary._edwards_style("font-family:Unknown", "emphasis")


@pytest.mark.requires_local_artifacts
def test_edwards_exact_modern_row_omission_inverse_and_mutations() -> None:
    original = _private_rows()
    assert len(original) == 8
    public, receipt = boundary.public_rows_with_omissions(
        original, item_id=boundary.EDWARDS_ITEM, **AUTHORITY)
    assert len(public) == 7 and receipt["removed_row_index"] == 6
    assert boundary._digest(receipt["removed_row"]) == boundary.EDWARDS_ACK_ROW_SHA256
    assert [row["record_id"] for row in public] == [row["record_id"] for i, row in enumerate(original) if i != 6]
    assert [row["text"] for row in public] == [row["text"] for i, row in enumerate(original) if i != 6]
    assert "Acknowledgements" not in json.dumps(public, ensure_ascii=False)
    assert "Indexes\n\nIndex of Scripture References" in public[-1]["text"]
    assert not _scan(public, "Edwards public rows")
    assert boundary.restore_private_source_locations(
        public, receipt, item_id=boundary.EDWARDS_ITEM, **AUTHORITY) == original

    altered = deepcopy(receipt)
    altered["removed_row"]["text"] += " altered"
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(public, altered, item_id=boundary.EDWARDS_ITEM,
                                                  **AUTHORITY)
    altered = deepcopy(public)
    altered[0]["text"] += " altered"
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(altered, receipt, item_id=boundary.EDWARDS_ITEM,
                                                  **AUTHORITY)
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(original, item_id=boundary.EDWARDS_ITEM,
                                            acceptance_sha256="0" * 64,
                                            master_sha256=AUTHORITY["master_sha256"])
