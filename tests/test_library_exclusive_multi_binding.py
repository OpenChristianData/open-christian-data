"""Exact electronic-member-set declarations cannot silently lose source files."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tests.historical_bcp_packet_context import historical_bcp_packet_root

from build.tools.library_exclusive_multi_binding import bind_exclusive_multi_manifest
from build.tools.prepare_library_sidecar_batch import prepare
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/exclusive-multi-manifest-six-sidecar-batch-20260926.json"


def _packet() -> dict:
    return json.loads(PACKET.read_text(encoding="utf-8"))


def test_bcp_member_sets_bind_exact_retained_files_and_old_se_sets_fail_closed(tmp_path: Path) -> None:
    packet = _packet()
    historical_root = historical_bcp_packet_root(
        ROOT, [row for row in packet["entries"] if row["provider"] != "Standard Ebooks"], tmp_path / "bcp"
    )
    assert len(packet["entries"]) == 6
    for row in packet["entries"]:
        work = load_work(ROOT / row["work"]["path"])
        if row["provider"] == "Standard Ebooks":
            with pytest.raises(PipelineError, match="superseded"):
                bind_exclusive_multi_manifest(ROOT, row, work)
            continue
        retained, fields, evidence, _ = bind_exclusive_multi_manifest(historical_root, row, work)
        assert fields["source_kind"] == "retained-member-set"
        assert [item["path"] for item in retained] == [item["path"] for item in row["primary_sources"]]
        assert all(not item["path"].lower().endswith(".zip") for item in retained)
        assert row["source_manifest"]["path"] in evidence


@pytest.mark.parametrize("change", ["drop", "hash", "zip", "url", "scope", "rights"])
def test_changed_claim_fails_closed(change: str, tmp_path: Path) -> None:
    row = copy.deepcopy(_packet()["entries"][0])
    historical_root = historical_bcp_packet_root(ROOT, [row], tmp_path / "bcp")
    work = load_work(ROOT / row["work"]["path"])
    if change == "drop":
        row["primary_sources"].pop()
    elif change == "hash":
        row["primary_sources"][0]["sha256"] = "0" * 64
    elif change == "zip":
        row["primary_sources"][0]["path"] = "raw/archive/package.zip"
    elif change == "url":
        row["url"] = "https://example.invalid/wrong"
    elif change == "scope":
        row["source_scope"] = "complete print edition"
    else:
        row["warnings"] = []
    with pytest.raises(PipelineError):
        bind_exclusive_multi_manifest(historical_root, row, work)


def test_bcp_sidecars_are_prepared_or_installed() -> None:
    rows = [row for row in _packet()["entries"] if row["provider"] != "Standard Ebooks"]
    installed = all(load_work(ROOT / row["work"]["path"])["textual_forms"] for row in rows)
    if installed:
        for row in rows:
            acquisition = next((ROOT / "library/works" / row["work_id"]).rglob("acquisitions/*.json"))
            validate_acquisition(acquisition, root=ROOT)
    else:
        prepared = prepare(ROOT, {"contract": "ocd-library-sidecar-batch-v1", "entries": rows}, "2026-09-26T00:00:00Z")
        assert len(prepared) == 2
        assert all(len(item["output"]) == 4 for item in prepared)


def test_historical_catalog_context_retains_exact_hash_guard(tmp_path: Path) -> None:
    row = _packet()["entries"][0]
    root = historical_bcp_packet_root(ROOT, [row], tmp_path / "bcp")
    work = load_work(ROOT / row["work"]["path"])
    bind_exclusive_multi_manifest(root, row, work)
    catalog = root / row["metadata_evidence"]["path"]
    catalog.write_bytes(catalog.read_bytes() + b"\n")
    with pytest.raises(PipelineError, match="catalog.*changed"):
        bind_exclusive_multi_manifest(root, row, work)
