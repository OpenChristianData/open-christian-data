"""The four newly extracted Gutenberg sources bind to text, packages, and rights."""
from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from build.tools.gutenberg_record_only_binding import bind_record_only
from build.tools.prepare_library_sidecar_batch import prepare
from ocd_kernel.library._common import PipelineError, load_json
from ocd_kernel.lib.storage_topology import resolve_repo_path
from tests.historical_sidecar_packet_fixture import current_work_context

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/gutenberg-record-only-four-sidecar-batch-20260926.json"


def _preacquisition_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(resolve_repo_path(ROOT, "raw").parent)}),
        encoding="utf-8", newline="\n",
    )
    for entry in load_json(PACKET)["entries"]:
        for name in ("work", "state"):
            source = ROOT / "tests/fixtures/gutenberg-record-only-four-preimages" / entry["work_id"] / (name + ".json")
            raw = source.read_bytes()
            assert sha256(raw).hexdigest() == entry[name]["sha256"]
            target = root / entry[name]["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return root


@pytest.mark.parametrize("ebook_id", ["61614", "38326", "30362", "4272"])
def test_extracted_html_is_source_and_zip_is_package(ebook_id: str) -> None:
    row = next(item for item in load_json(PACKET)["entries"] if item["url"].endswith("/" + ebook_id))
    work = load_json(ROOT / row["work"]["path"])
    receipt = load_json(ROOT / row["acquisition_receipt"]["path"])
    retained, original, evidence, _ = bind_record_only(
        ROOT, row, work, receipt, row["acquisition_receipt"]["path"]
    )
    assert original["source_path"] == f"raw/gutenberg/{ebook_id}/html/pg{ebook_id}-images.html"
    assert retained[0]["path"] == f"raw/gutenberg/{ebook_id}/pg{ebook_id}-h.zip"
    assert retained[0]["media_type"] == "application/zip"
    assert len(retained) == len(receipt["members"]) + 1
    assert original["source_path"] in evidence


def test_bede_second_rights_claim_is_bound() -> None:
    row = next(item for item in load_json(PACKET)["entries"] if item["url"].endswith("/38326"))
    work = load_json(ROOT / row["work"]["path"])
    receipt = load_json(ROOT / row["acquisition_receipt"]["path"])
    changed = copy.deepcopy(receipt)
    changed["rights_claim"]["text"].pop(0)
    with pytest.raises(PipelineError, match="rights"):
        bind_record_only(ROOT, row, work, changed, row["acquisition_receipt"]["path"])


def test_package_evidence_cannot_be_omitted() -> None:
    row = next(item for item in load_json(PACKET)["entries"] if item["url"].endswith("/61614"))
    work = load_json(ROOT / row["work"]["path"])
    receipt = load_json(ROOT / row["acquisition_receipt"]["path"])
    work["evidence"].remove(receipt["package"]["path"])
    with pytest.raises(PipelineError, match="package evidence"):
        bind_record_only(ROOT, row, work, receipt, row["acquisition_receipt"]["path"])


def test_proposed_work_binds_extracted_html_and_receipt(tmp_path: Path) -> None:
    root = _preacquisition_root(tmp_path)
    results = prepare(root, load_json(PACKET), "2026-09-26T00:00:00Z")
    assert len(results) == 4
    for result in results:
        work = next(value for path, value in result["output"] if path.endswith("/work.json"))
        receipt = load_json(ROOT / result["acquisition_receipt"])
        assert receipt["html"]["path"] in work["evidence"]
        assert result["acquisition_receipt"] in work["evidence"]


def test_already_present_batch_identity_is_still_rejected(tmp_path: Path) -> None:
    root = _preacquisition_root(tmp_path)
    packet = load_json(PACKET)
    entry = packet["entries"][0]
    current = ROOT / entry["work"]["path"]
    actual = load_json(current)
    assert any(form["textual_form_id"] == entry["textual_form_id"] for form in actual["textual_forms"])
    current_work_context(ROOT, root, entry["work"]["path"])
    with pytest.raises(PipelineError, match="duplicate global forms ID"):
        prepare(root, packet, "2026-09-26T00:00:00Z")
