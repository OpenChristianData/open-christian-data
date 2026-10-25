"""Source-defined rows from the three held LIB-040 Augustine staged masters."""

from copy import deepcopy
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import lib040_augustine_selected as selected
from ocd_kernel.projection.categories.lib040_augustine_selected import project, verify
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.projection.categories.sermons import project_accepted_sermons, verify_accepted_sermons


@pytest.mark.parametrize("work_id,stage,category,count,non_rows", [
    ("augustine-letters-part-1", "l040u1", "prose", 169, ["vii.i", "vii.1"]),
    ("augustine-sermons-selected-lessons", "ss040u1", "sermons", 97, ["vii.i", "vii.ii"]),
    ("augustine-homilies-on-first-john", "hj040u1", "sermons", 10,
     [f"iv.{part}" for part in ("i", "ii", "iii", "xiv", "xv", "xvi", "xvii", "xviii", "xix")]),
])
def test_source_selected_actual_master_and_tamper_rejection(work_id, stage, category, count, non_rows):
    root = Path("C:/Scratch") / stage
    acceptance = next((root / "library/works" / work_id).rglob("acceptance.json"))
    projected = project(root, acceptance_path=acceptance, category=category)
    rows, receipt = projected["rows"], projected["receipt"]
    assert len(rows) == count
    assert receipt["source_division_binding"]["non_row_direct_source_ids"] == non_rows
    assert verify(root, acceptance_path=acceptance, category=category, rows=rows, receipt=receipt) == []
    public_project, public_verify = ((project_accepted_prose, verify_accepted_prose)
                                      if category == "prose" else (project_accepted_sermons, verify_accepted_sermons))
    routed = public_project(root, acceptance_path=acceptance)
    assert routed == projected
    assert public_verify(root, acceptance_path=acceptance, rows=routed["rows"], receipt=routed["receipt"]) == []
    if work_id == "augustine-letters-part-1":
        grouped = [item for item in receipt["source_division_binding"]["source_units"] if item["type"] == "Letters"]
        assert [(item["source_id"], item["n"]) for item in grouped] == [("LVI", "LVI")]
    changed = deepcopy(rows)
    changed[0]["text"] += " altered"
    assert verify(root, acceptance_path=acceptance, category=category, rows=changed, receipt=receipt)
    changed_receipt = deepcopy(receipt)
    changed_receipt["source_division_binding"]["source_units"][0]["source_id"] = "forged"
    assert verify(root, acceptance_path=acceptance, category=category, rows=rows, receipt=changed_receipt)


def test_retained_source_byte_drift_rejected(tmp_path, monkeypatch):
    root = Path("C:/Scratch/l040u1")
    acceptance = next((root / "library/works/augustine-letters-part-1").rglob("acceptance.json"))
    source = root / "raw/ccel/npnf1/npnf101.xml"
    altered = tmp_path / "altered-source.xml"
    altered.write_bytes(source.read_bytes() + b" ")
    original_io_path = selected.io_path

    def redirect(path):
        return altered if Path(path) == source else original_io_path(path)

    monkeypatch.setattr(selected, "io_path", redirect)
    with pytest.raises(PipelineError, match="retained source differs"):
        project(root, acceptance_path=acceptance, category="prose")
