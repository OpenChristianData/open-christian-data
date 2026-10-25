"""Seven Chrysostom acquisitions bind distinct retained NPNF div1 children."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build.tools.library_chrysostom_seven_binding import bind_chrysostom_seven
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/chrysostom-npnf110-114-seven-sidecar-packet-20260926.json"


def _rows() -> list[dict]:
    return json.loads(PACKET.read_text(encoding="utf-8"))["entries"]


def _work(row: dict) -> dict:
    return json.loads((ROOT / row["work"]["path"]).read_text(encoding="utf-8"))


def test_all_seven_children_bind_unique_xml_locators():
    rows = _rows()
    assert len(rows) == 7
    locators = set()
    for row in rows:
        retained, fields, evidence, _ = bind_chrysostom_seven(ROOT, row, _work(row))
        assert fields["source_path"] == retained[0]["path"]
        assert fields["source_sha256"] == retained[0]["sha256"]
        assert fields["source_path"].endswith(".xml")
        assert evidence[0].endswith("npnf-chrysostom.source-manifest.json")
        locators.add(row["containing_source"]["locator"])
    assert len(locators) == 7


def test_swapped_volume_is_rejected():
    rows = _rows()
    row = copy.deepcopy(rows[0])
    row["primary_source"] = next(item["primary_source"] for item in rows
                                 if item["primary_source"]["path"] != row["primary_source"]["path"])
    with pytest.raises(PipelineError, match="source differs"):
        bind_chrysostom_seven(ROOT, row, _work(row))


def test_wrong_child_locator_is_rejected():
    row = copy.deepcopy(_rows()[0])
    row["containing_source"]["locator"] = row["primary_source"]["path"] + "#other"
    with pytest.raises(PipelineError, match="child scope"):
        bind_chrysostom_seven(ROOT, row, _work(row))


def test_missing_rights_warning_is_rejected():
    row = copy.deepcopy(_rows()[0])
    row["warnings"] = [warning for warning in row["warnings"] if "CCEL" not in warning]
    with pytest.raises(PipelineError, match="rights warnings"):
        bind_chrysostom_seven(ROOT, row, _work(row))


def test_changed_child_evidence_is_rejected():
    row = copy.deepcopy(_rows()[0])
    row["chrysostom_child_evidence"]["sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="bytes changed"):
        bind_chrysostom_seven(ROOT, row, _work(row))
