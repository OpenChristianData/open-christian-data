"""Owen acquisition records must bind exact retained XML and rights evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tools.library_owen_cohort_binding import bind_owen_cohort_member
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]


def _packet() -> dict:
    path = ROOT / "plans/2026-09-22-source-preflight/owen-lib050-052-29-sidecar-packet-20260926.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs(work_id: str = "john-owen-apostasy"):
    packet = _packet()
    row = next(item for item in packet["entries"] if item["work_id"] == work_id)
    manifest = json.loads((ROOT / row["source_manifest"]["path"]).read_text(encoding="utf-8"))
    work = json.loads((ROOT / row["work"]["path"]).read_text(encoding="utf-8"))
    config = json.loads((ROOT / row["config"]["path"]).read_text(encoding="utf-8"))
    return row, work, config, manifest


def test_packet_covers_only_29_owen_works():
    packet = _packet()
    assert len(packet["entries"]) == 29
    assert "john-owen-conscience" not in {item["work_id"] for item in packet["entries"]}
    paths = [item["primary_source"]["path"] for item in packet["entries"]]
    assert len(set(paths)) == 29
    assert all(path.startswith("raw/ccel/owen/") and path.endswith(".xml") for path in paths)


@pytest.mark.parametrize("work_id", ["john-owen-apostasy", "john-owen-glory", "john-owen-trinity"])
def test_each_cohort_has_bound_source_and_attribution(work_id: str):
    row, work, config, manifest = _inputs(work_id)
    paths = bind_owen_cohort_member(ROOT, row, work, config, manifest, row["primary_source"])
    assert len(paths) == 2
    assert paths[0].endswith(".reconstruction-profile.json")
    assert paths[1].endswith("README.md")


def test_swapped_owen_xml_is_rejected():
    row, work, config, manifest = _inputs()
    other = next(item for item in manifest["authorities"]
                 if item.get("name") == "communion-source")
    with pytest.raises(PipelineError, match="source differ"):
        bind_owen_cohort_member(ROOT, row, work, config, manifest, other)


def test_unsupported_source_url_is_rejected():
    row, work, config, manifest = _inputs()
    changed = dict(row, url="https://www.ccel.org/ccel/owen/other.html")
    with pytest.raises(PipelineError, match="URL differs"):
        bind_owen_cohort_member(ROOT, changed, work, config, manifest, row["primary_source"])


def test_ages_rights_warning_cannot_be_dropped():
    row, work, config, manifest = _inputs()
    changed = copy.deepcopy(row)
    changed["warnings"] = [warning for warning in row["warnings"] if "AGES" not in warning]
    with pytest.raises(PipelineError, match="AGES source warning"):
        bind_owen_cohort_member(ROOT, changed, work, config, manifest, row["primary_source"])


def test_proofreading_warning_follows_each_xml_status():
    counts = {"not_proofread": 0, "unknown": 0, "proofread": 0}
    for row in _packet()["entries"]:
        xml = etree.parse(str(ROOT / row["primary_source"]["path"]),
                          etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
        node = xml.getroot().find("./ThML.head/electronicEdInfo/status")
        status = " ".join("".join(node.itertext()).split()) if node is not None else ""
        warnings = " ".join(row["warnings"])
        if "not been proof-read" in status:
            counts["not_proofread"] += 1
            assert "marked as not proofread" in warnings
        elif not status:
            counts["unknown"] += 1
            assert "does not state a proofreading status" in warnings
        else:
            counts["proofread"] += 1
            assert "marked as not proofread" not in warnings
    assert counts == {"not_proofread": 12, "unknown": 3, "proofread": 14}
