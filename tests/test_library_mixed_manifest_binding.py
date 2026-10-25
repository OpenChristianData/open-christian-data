"""BCP source cohorts remain valid; superseded mixed-source packets fail closed."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.historical_bcp_packet_context import historical_bcp_packet_root

from build.tools.library_exclusive_multi_binding import bind_exclusive_multi_manifest
from build.tools.library_mixed_manifest_binding import bind_mixed_manifest
from build.tools.prepare_library_sidecar_batch import prepare
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work


ROOT = Path(__file__).resolve().parents[1]
MIXED = ROOT / "plans/2026-09-22-source-preflight/bcp-1662-two-sidecar-batch-20260926.json"
OLD_MIXED = ROOT / "plans/2026-09-22-source-preflight/bcp-whitefield-mixed-three-sidecar-batch-20260926.json"
PRACTICAL = ROOT / "plans/2026-09-22-source-preflight/practical-mysticism-member-set-sidecar-batch-20260926.json"


def _packet(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_two_bcp_scopes_use_only_selected_real_files(tmp_path: Path) -> None:
    packet = _packet(MIXED)
    historical_root = historical_bcp_packet_root(ROOT, packet["entries"], tmp_path / "bcp")
    assert len(packet["entries"]) == 2
    for row in packet["entries"]:
        retained, fields, _, _ = bind_mixed_manifest(
            historical_root, row, load_work(ROOT / row["work"]["path"])
        )
        assert fields["source_kind"] == "retained-member-set"
        assert [item["path"] for item in retained] == [item["path"] for item in row["primary_sources"]]
        assert all(not item["path"].lower().endswith(".zip") for item in retained)
        if row["work_id"] == "bcp-1662-collects":
            assert len(retained) == 5
            assert all(item["path"].startswith("raw/bcp1662/") for item in retained)


def test_superseded_whitefield_combined_witness_fails_closed() -> None:
    row = _packet(OLD_MIXED)["entries"][2]
    with pytest.raises(PipelineError, match="superseded"):
        bind_mixed_manifest(ROOT, row, load_work(ROOT / row["work"]["path"]))


def test_superseded_practical_all_file_source_fails_closed() -> None:
    row = _packet(PRACTICAL)["entries"][0]
    with pytest.raises(PipelineError, match="superseded"):
        bind_exclusive_multi_manifest(ROOT, row, load_work(ROOT / row["work"]["path"]))


def test_guarded_bcp_route_is_staged_or_installed() -> None:
    packet = _packet(MIXED)
    installed = all(load_work(ROOT / row["work"]["path"])["textual_forms"] for row in packet["entries"])
    if installed:
        for row in packet["entries"]:
            work_root = ROOT / "library/works" / row["work_id"]
            acquisition = next(work_root.rglob("acquisitions/*.json"))
            validate_acquisition(acquisition, root=ROOT)
    else:
        result = prepare(ROOT, packet, "2026-09-26T00:00:00Z")
        assert len(result) == 2
        assert all(len(item["output"]) == 4 for item in result)


def test_historical_catalog_context_retains_exact_hash_guard(tmp_path: Path) -> None:
    row = _packet(MIXED)["entries"][0]
    root = historical_bcp_packet_root(ROOT, [row], tmp_path / "bcp")
    work = load_work(ROOT / row["work"]["path"])
    bind_mixed_manifest(root, row, work)
    catalog = root / row["metadata_evidence"]["path"]
    catalog.write_bytes(catalog.read_bytes() + b"\n")
    with pytest.raises(PipelineError, match="catalog.*changed"):
        bind_mixed_manifest(root, row, work)
