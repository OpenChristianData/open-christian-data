"""Check Calvin direct CCEL source binding and package boundary."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build.tools import library_calvin_direct_ccel_binding as calvin
from build.tools.library_calvin_direct_ccel_binding import bind_calvin_direct_ccel
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/calvin-direct-ccel-46-sidecar-batch-20260926.json"


def _row_and_work() -> tuple[dict, dict]:
    row = json.loads(PACKET.read_text(encoding="utf-8"))["entries"][0]
    work = json.loads((ROOT / row["work"]["path"]).read_text(encoding="utf-8"))
    return row, work


def test_all_46_direct_ccel_xml_files_are_bound_without_zip_source() -> None:
    row, work = _row_and_work()
    retained, source_fields, evidence, attribution = bind_calvin_direct_ccel(ROOT, row, work)
    assert len(retained) == 46
    assert {Path(item["path"]).name for item in retained} == {
        "commentaries.xml", *(f"calcom{number:02d}.xml" for number in range(1, 46))
    }
    assert all(item["path"].startswith("raw/ccel/calvin-commentaries/") for item in retained)
    assert all(not item["path"].lower().endswith(".zip") for item in retained)
    assert source_fields["source_kind"] == "retained-member-set"
    assert "raw/sword_modules/CalvinCommentaries.zip" in evidence
    assert attribution == [
        "sources/commentaries/calvin/calvin-commentaries.reconstruction-profile.json",
        "sources/commentaries/calvin/README.source.md",
    ]


def test_crosswire_package_url_cannot_replace_direct_ccel_provenance() -> None:
    row, work = _row_and_work()
    changed = copy.deepcopy(row)
    changed["url"] = "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/CalvinCommentaries.zip"
    with pytest.raises(PipelineError, match="direct CCEL identity"):
        bind_calvin_direct_ccel(ROOT, changed, work)


def test_changed_direct_member_url_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row, work = _row_and_work()
    receipt = json.loads((ROOT / row["direct_ccel_receipt"]["path"]).read_text(encoding="utf-8"))
    receipt["files"][0]["source_url"] = "https://ccel.org/ccel/c/calvin/other.xml"
    changed_receipt = tmp_path / "changed-calvin-receipt.json"
    changed_receipt.write_text(json.dumps(receipt), encoding="utf-8")
    original_bound = calvin._bound

    def bound_with_changed_receipt(root: Path, ref: dict, label: str) -> Path:
        if label == "Calvin CCEL receipt":
            return changed_receipt
        return original_bound(root, ref, label)

    monkeypatch.setattr(calvin, "_bound", bound_with_changed_receipt)
    with pytest.raises(PipelineError, match="direct CCEL URL differs"):
        bind_calvin_direct_ccel(ROOT, row, work)
