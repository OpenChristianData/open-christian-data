"""Basil sidecar accounting resolves three distinct source child scopes."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build.tools.library_basil_three_binding import bind_basil_three
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/basil-npnf208-three-sidecar-packet-20260926.json"


def _rows() -> list[dict]:
    return json.loads(PACKET.read_text(encoding="utf-8"))["entries"]


def _work(row: dict) -> dict:
    return json.loads((ROOT / row["work"]["path"]).read_text(encoding="utf-8"))


def test_three_basil_works_bind_distinct_retained_div1_children():
    rows = _rows()
    assert len(rows) == 3
    assert {row["containing_source"]["locator"].rsplit("#", 1)[1] for row in rows} == {
        "vii", "viii", "ix"}
    for row in rows:
        retained, fields, evidence_paths, _ = bind_basil_three(ROOT, row, _work(row))
        assert fields["source_path"] == "raw/ccel/npnf2/npnf208.xml"
        assert fields["source_sha256"] == retained[0]["sha256"]
        assert evidence_paths[0].endswith("npnf2-lib046.source-manifest.json")


def test_wrong_basil_child_locator_rejected():
    row = copy.deepcopy(_rows()[0])
    row["containing_source"]["locator"] = "raw/ccel/npnf2/npnf208.xml#viii"
    with pytest.raises(PipelineError, match="child scope"):
        bind_basil_three(ROOT, row, _work(row))


def test_changed_source_binding_rejected():
    row = copy.deepcopy(_rows()[0])
    row["primary_source"]["sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="retained XML differs"):
        bind_basil_three(ROOT, row, _work(row))


def test_missing_rights_warning_rejected():
    row = copy.deepcopy(_rows()[0])
    row["warnings"] = [warning for warning in row["warnings"] if "CCEL" not in warning]
    with pytest.raises(PipelineError, match="warnings"):
        bind_basil_three(ROOT, row, _work(row))
