"""Two lookup CCEL works bind exact XML, edition, and rights evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build.tools.library_lookup_ccel_binding import bind_lookup_ccel
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]


def _packet() -> dict:
    path = ROOT / "plans/2026-09-22-source-preflight/two-lookup-ccel-sidecar-packet-20260926.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _work(row: dict) -> dict:
    return json.loads((ROOT / row["work"]["path"]).read_text(encoding="utf-8"))


def test_both_lookup_sources_bind_distinct_retained_xml():
    packet = _packet()
    assert {row["work_id"] for row in packet["entries"]} == {
        "edwards-select-sermons", "spurgeons-morning-evening"
    }
    sources = set()
    for row in packet["entries"]:
        retained, source_fields, evidence, _ = bind_lookup_ccel(ROOT, row, _work(row))
        assert retained[0]["path"] == source_fields["source_path"]
        assert retained[0]["path"].endswith(".xml")
        assert evidence[0].endswith("two-lookup-retained-source-preflight-20260925.json")
        sources.add(retained[0]["path"])
    assert len(sources) == 2


def test_swapped_xml_is_rejected():
    rows = {row["work_id"]: row for row in _packet()["entries"]}
    edwards = copy.deepcopy(rows["edwards-select-sermons"])
    edwards["primary_source"] = rows["spurgeons-morning-evening"]["primary_source"]
    with pytest.raises(PipelineError, match="preflight, packet"):
        bind_lookup_ccel(ROOT, edwards, _work(edwards))


def test_changed_preflight_hash_is_rejected():
    row = copy.deepcopy(_packet()["entries"][0])
    row["lookup_source_evidence"]["sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="retained authority changed"):
        bind_lookup_ccel(ROOT, row, _work(row))


def test_spurgeon_editorial_privacy_warning_is_required():
    row = next(row for row in _packet()["entries"]
               if row["work_id"] == "spurgeons-morning-evening")
    changed = copy.deepcopy(row)
    changed["warnings"] = [warning for warning in row["warnings"]
                           if "contact address" not in warning]
    with pytest.raises(PipelineError, match="edition or privacy warning"):
        bind_lookup_ccel(ROOT, changed, _work(changed))

