"""Focused LIB-062 work/source identity checks against retained packet evidence."""
from copy import deepcopy
from pathlib import Path

import pytest
from tests.historical_sidecar_packet_fixture import historical_packet_context, current_work_context

from build.tools.prepare_library_sidecar_batch import prepare
from ocd_kernel.library._common import PipelineError, load_json

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/lib062-six-source-packet-sidecar-batch-20260926.json"
RETAINED = ROOT / "raw/Creeds.json/creeds/1695_baptist_catechism.json"


@pytest.mark.skipif(not RETAINED.is_file(), reason="durable Creeds.json source is not mounted")
def test_six_packets_bind_distinct_retained_json_members(tmp_path):
    root = historical_packet_context(ROOT, tmp_path / "repo", "creeds-six")
    rows = prepare(root, load_json(PACKET), "2026-09-26T00:00:00Z")
    assert len(rows) == 6
    paths = [result["output"][2][1]["source_path"] for result in rows]
    assert len(set(paths)) == 6
    assert all(path.startswith("raw/Creeds.json/creeds/") and path.endswith(".json") for path in paths)


@pytest.mark.skipif(not RETAINED.is_file(), reason="durable Creeds.json source is not mounted")
def test_source_packet_from_another_catechism_fails_closed(tmp_path):
    root = historical_packet_context(ROOT, tmp_path / "repo", "creeds-six")
    packet = deepcopy(load_json(PACKET))
    packet["entries"][0]["source_packet"] = packet["entries"][1]["source_packet"]
    with pytest.raises(PipelineError, match="packet identity differs from preflight"):
        prepare(root, packet, "2026-09-26T00:00:00Z")


@pytest.mark.skipif(not RETAINED.is_file(), reason="durable Creeds.json source is not mounted")
def test_source_scope_must_name_exact_json_member(tmp_path):
    root = historical_packet_context(ROOT, tmp_path / "repo", "creeds-six")
    packet = deepcopy(load_json(PACKET))
    packet["entries"][0]["source_scope"] = "Unspecified catechism member."
    with pytest.raises(PipelineError, match="source scope does not identify exact JSON member"):
        prepare(root, packet, "2026-09-26T00:00:00Z")


def test_current_creeds_identity_still_rejects_duplicate_staging(tmp_path):
    root = historical_packet_context(ROOT, tmp_path / "repo", "creeds-six")
    packet = load_json(PACKET)
    row = packet["entries"][0]
    current = ROOT / row["work"]["path"]
    assert any(form["textual_form_id"] == row["textual_form_id"] for form in load_json(current)["textual_forms"])
    current_work_context(ROOT, root, row["work"]["path"])
    with pytest.raises(PipelineError, match="duplicate global forms ID"):
        prepare(root, packet, "2026-09-26T00:00:00Z")
