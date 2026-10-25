"""Accepted-source guard for the 1645 Directory's web back-navigation omission."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release import publick_worship
from ocd_kernel.release.public_rows import public_rows_with_omissions, restore_private_source_locations
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / ("library/works/directory-for-publick-worship/forms/"
                     "directory-for-publick-worship-retained-text/editions/"
                     "directory-for-publick-worship-retained-electronic-witness/acceptance.json")


@pytest.fixture(scope="module")
def accepted_rows():
    assert hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() == publick_worship.ACCEPTANCE_SHA256
    with cached_edition_lookups():
        projection = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
        assert verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE,
                                     rows=projection["rows"], receipt=projection["receipt"]) == []
        rows = [dict(row, license=publick_worship.LICENSE) for row in projection["rows"]]
        rows, receipt = compose_work_metadata(ROOT, rows, projection["receipt"])
    assert hashlib.sha256(canonical_bytes(rows)).hexdigest() == publick_worship.PRIVATE_ROWS_SHA256
    return rows


@pytest.fixture(scope="module")
def transformed(accepted_rows):
    public, receipt = public_rows_with_omissions(
        accepted_rows, item_id=publick_worship.ITEM,
        acceptance_sha256=publick_worship.ACCEPTANCE_SHA256,
        master_sha256=publick_worship.MASTER_SHA256)
    return public, receipt


def test_historical_rows_omit_only_exact_site_back_navigation(accepted_rows, transformed):
    public, receipt = transformed
    assert len(public) == 5 and public[:4] == accepted_rows[:4]
    assert len(receipt["omitted_nodes"]) == len(receipt["omitted_references"]) == 16
    assert all(reference["raw"] == "Back to top." for reference in receipt["omitted_references"])
    assert public[4]["source_references"] == []
    assert "Back to top." not in public[4]["text"]
    assert public[4]["text"].startswith("THE PREFACE.")
    assert public[4]["text"].endswith("the places of publick assembling for worship among us should be continued and employed to that use.")
    assert hashlib.sha256(canonical_bytes(public)).hexdigest() == publick_worship.PUBLIC_ROWS_SHA256
    assert restore_private_source_locations(
        public, receipt, item_id=publick_worship.ITEM,
        acceptance_sha256=publick_worship.ACCEPTANCE_SHA256,
        master_sha256=publick_worship.MASTER_SHA256) == accepted_rows


@pytest.mark.parametrize("mutation", (
    "public-text", "public-structure", "node-content", "node-missing",
    "reference-target", "reference-missing", "position", "receipt-hash",
))
def test_inverse_rejects_tampering(transformed, mutation):
    public, receipt = deepcopy(transformed)
    if mutation == "public-text":
        public[4]["text"] += " altered"
    elif mutation == "public-structure":
        public[4]["structure"][0]["content"][1]["content"].pop()
    elif mutation == "node-content":
        receipt["omitted_nodes"][0]["content"][0]["content"][0]["content"][0]["text"] = "New note"
    elif mutation == "node-missing":
        receipt["omitted_nodes"].pop()
    elif mutation == "reference-target":
        receipt["omitted_references"][0]["target"] = "#wrong"
    elif mutation == "reference-missing":
        receipt["omitted_references"].pop()
    elif mutation == "position":
        receipt["omitted_indices"][0] += 1
    else:
        receipt["public_rows_sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="Publick Worship"):
        restore_private_source_locations(
            public, receipt, item_id=publick_worship.ITEM,
            acceptance_sha256=publick_worship.ACCEPTANCE_SHA256,
            master_sha256=publick_worship.MASTER_SHA256)


def test_wrong_accepted_authority_fails_closed(accepted_rows):
    with pytest.raises(PipelineError, match="accepted authority"):
        public_rows_with_omissions(accepted_rows, item_id=publick_worship.ITEM,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=publick_worship.MASTER_SHA256)
