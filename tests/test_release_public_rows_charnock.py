"""Bound Charnock Volume I public rows to accepted text and private inverse."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.release import public_rows as boundary
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / (
    "library/works/charnock-existence-attributes-vol-1/forms/"
    "charnock-existence-attributes-vol-1-english/editions/"
    "charnock-existence-attributes-vol-1-retained-electronic-witness/acceptance.json"
)


def digest(value):
    return sha256(canonical_bytes(value)).hexdigest()


@pytest.fixture(scope="module")
def selected_rows():
    projected = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    licensed = [dict(row, license=boundary.CHARNOCK_LICENSE)
                for row in projected["rows"]]
    private, receipt = compose_work_metadata(ROOT, licensed, projected["receipt"])
    acceptance_sha = sha256(ACCEPTANCE.read_bytes()).hexdigest()
    assert receipt["master_sha256"] == boundary.CHARNOCK_MASTER_SHA256
    assert acceptance_sha == boundary.CHARNOCK_ACCEPTANCE_SHA256
    assert digest(private) == boundary.CHARNOCK_PRIVATE_ROWS_SHA256
    public, omission = boundary.public_rows_with_omissions(
        private, item_id=boundary.CHARNOCK_ITEM,
        acceptance_sha256=acceptance_sha, master_sha256=receipt["master_sha256"])
    return private, public, omission


def restore(rows, artifact):
    return boundary.restore_private_source_locations(
        rows, artifact, item_id=boundary.CHARNOCK_ITEM,
        acceptance_sha256=boundary.CHARNOCK_ACCEPTANCE_SHA256,
        master_sha256=boundary.CHARNOCK_MASTER_SHA256)


def test_selected_license_metadata_public_scope_and_exact_inverse(selected_rows):
    private, public, omission = selected_rows
    assert len(public) == 2
    assert digest(public) == boundary.CHARNOCK_PUBLIC_ROWS_SHA256
    assert restore(public, omission) == private
    assert not _scan(public, "Charnock Volume I public")
    assert [len(row["source_references"]) for row in public] == [809, 0]
    assert len(omission["removed_volume_ledger"]["content"]) == 30275
    assert len(omission["removed_shared_ledger"]["content"]) == 6013
    assert "WITH HIS LIFE AND CHARACTER" in public[0]["text"]
    assert "BY WILLIAM SYMINGTON" in public[0]["text"]
    assert "Reprinted 1996 by Baker Books" in public[0]["text"]
    assert "Third printing, January 2000" in public[0]["text"]
    assert "For information about academic books" not in public[0]["text"]
    assert public[1]["text"] == private[1]["text"]
    assert "TRANSCRIBER’S NOTES" in public[1]["text"]


def test_historical_text_and_public_receipt_mutations_fail(selected_rows):
    private, public, omission = selected_rows
    altered_public = deepcopy(public)
    altered_public[0]["text"] += "changed"
    with pytest.raises(PipelineError):
        restore(altered_public, omission)
    altered_receipt = deepcopy(omission)
    altered_receipt["removed_volume_ledger"]["content"][0]["content"][0]["text"] = "changed"
    with pytest.raises(PipelineError):
        restore(public, altered_receipt)
    altered_promotion = deepcopy(omission)
    altered_promotion["removed_promotion"][0]["content"][0]["text"] = "changed"
    with pytest.raises(PipelineError):
        restore(public, altered_promotion)
    altered_private = deepcopy(private)
    altered_private[0]["text"] += "changed"
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(
            altered_private, item_id=boundary.CHARNOCK_ITEM,
            acceptance_sha256=boundary.CHARNOCK_ACCEPTANCE_SHA256,
            master_sha256=boundary.CHARNOCK_MASTER_SHA256)


def test_wrong_authority_and_legacy_receipt_cannot_bypass_boundary(selected_rows):
    private, public, _ = selected_rows
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(
            private, item_id=boundary.CHARNOCK_ITEM,
            acceptance_sha256="0" * 64,
            master_sha256=boundary.CHARNOCK_MASTER_SHA256)
    with pytest.raises(PipelineError):
        restore(public, {"contract": boundary.CONTRACT,
                         "item_id": boundary.CHARNOCK_ITEM,
                         "row_count": 2, "omissions": []})
    assert boundary.CHARNOCK_ITEM in boundary.HASH_BOUND_ITEMS
