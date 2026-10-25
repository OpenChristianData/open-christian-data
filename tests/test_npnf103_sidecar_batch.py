"""Check exact NPNF103 shared-volume sidecar source accounting."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from tests.historical_sidecar_packet_fixture import historical_packet_context, current_work_context

from build.tei.npnf103_reconstruction import ASSIGNED
from build.tools.prepare_library_sidecar_batch import prepare
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/augustine-npnf103-sixteen-sidecar-batch-20260926.json"
SOURCE = "raw/ccel/npnf1/npnf103.xml"


def _packet() -> dict:
    return json.loads(PACKET.read_text(encoding="utf-8"))


def test_sixteen_unique_child_acquisitions_bind_the_shared_xml(tmp_path: Path) -> None:
    root = historical_packet_context(ROOT, tmp_path / "repo", "npnf103-sixteen")
    packet = _packet()
    profile = json.loads((ROOT / "sources/structured-text/augustine-npnf103/augustine-npnf103.reconstruction-profile.json").read_text(encoding="utf-8"))
    assert profile["assigned_div2"] == [locator for locator, _ in ASSIGNED]
    assert len(ASSIGNED) == len({wid for _, wid in ASSIGNED}) == 16
    results = prepare(root, packet, "2026-09-26T00:00:00Z")
    assert len(results) == 16
    for result in results:
        acquisition = result["output"][2][1]
        work = result["output"][0][1]
        assert acquisition["source_path"] == SOURCE
        assert [item["path"] for item in acquisition["retained_files"]] == [SOURCE]
        assert all(not item["path"].endswith(".zip") for item in acquisition["retained_files"])
        edition = work["textual_forms"][0]["editions"][0]
        expected_locator = next(locator for locator, wid in ASSIGNED if wid == result["work_id"])
        assert edition["containing_source"]["locator"] == f"{SOURCE}#{expected_locator}"


def test_wrong_child_locator_is_rejected(tmp_path: Path) -> None:
    root = historical_packet_context(ROOT, tmp_path / "repo", "npnf103-sixteen")
    packet = copy.deepcopy(_packet())
    row = packet["entries"][1]
    row["containing_source"]["locator"] = f"{SOURCE}#iv.i"
    with pytest.raises(PipelineError, match="containing-source title, locator, or evidence mismatch"):
        prepare(root, packet, "2026-09-26T00:00:00Z")


def test_current_npnf103_form_still_rejects_duplicate_staging(tmp_path: Path) -> None:
    root = historical_packet_context(ROOT, tmp_path / "repo", "npnf103-sixteen")
    packet = _packet()
    row = packet["entries"][0]
    current = ROOT / row["work"]["path"]
    actual = json.loads(current.read_bytes())
    assert any(form["textual_form_id"] == row["textual_form_id"] for form in actual["textual_forms"])
    current_work_context(ROOT, root, row["work"]["path"])
    with pytest.raises(PipelineError, match="duplicate global forms ID"):
        prepare(root, packet, "2026-09-26T00:00:00Z")
