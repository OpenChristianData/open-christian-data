"""Exact accepted Schaff VI public presentation boundary."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (
    SCHAFF6_ITEM, SCHAFF6_LICENSE, SCHAFF6_PRIVATE_ROWS_SHA256,
    SCHAFF6_PUBLIC_ROWS_SHA256, _digest,
    public_rows_with_omissions, restore_private_source_locations,
)
from ocd_kernel.release.work_metadata import compose_work_metadata, check_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/schaff-history-vol-6/forms/schaff-history-vol-6-retained-electronic/editions/schaff-history-vol-6-retained-electronic-witness/acceptance.json"
ACCEPTANCE_SHA256 = "3175c5bf2f6e579fd0429adda0bf4a605ab6374bf6ddac6fd74fce58873fae3f"
MASTER_SHA256 = "63c144dc5b51c9855c030d6e0f1e35dbdf890364aa2fb5643f24559be99c2555"


@pytest.fixture(scope="module")
def boundary():
    assert sha256(ACCEPTANCE.read_bytes()).hexdigest() == ACCEPTANCE_SHA256
    with cached_edition_lookups():
        projected = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
        private, receipt = compose_work_metadata(
            ROOT, [dict(row, license=SCHAFF6_LICENSE) for row in projected["rows"]],
            projected["receipt"])
    assert receipt["master_sha256"] == MASTER_SHA256
    assert _digest(private) == SCHAFF6_PRIVATE_ROWS_SHA256
    public, artifact = public_rows_with_omissions(
        private, item_id=SCHAFF6_ITEM, acceptance_sha256=ACCEPTANCE_SHA256,
        master_sha256=MASTER_SHA256)
    return private, public, artifact, receipt


def test_exact_scope_inverse_and_independent_source(boundary):
    private, public, artifact, receipt = boundary
    assert len(public) == 4 and _digest(public) == SCHAFF6_PUBLIC_ROWS_SHA256
    assert not _scan(public, "Schaff VI public")
    assert [row["text"] for row in public] == [row["text"] for row in private]
    assert sum(len(part["fields"]) for part in artifact["omissions"]) == 14
    restored = restore_private_source_locations(
        public, artifact, item_id=SCHAFF6_ITEM,
        acceptance_sha256=ACCEPTANCE_SHA256, master_sha256=MASTER_SHA256)
    assert restored == private
    with cached_edition_lookups():
        native_rows, native_receipt = check_work_metadata(
            ROOT, [{key: value for key, value in row.items() if key != "license"}
                   for row in restored], receipt)
        assert verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE,
                                     rows=native_rows, receipt=native_receipt) == []


def test_mutations_and_incomplete_private_receipt_fail(boundary):
    private, public, artifact, _ = boundary
    tampered = deepcopy(public)
    tampered[0]["text"] += " altered"
    with pytest.raises(PipelineError):
        restore_private_source_locations(tampered, artifact, item_id=SCHAFF6_ITEM,
                                         acceptance_sha256=ACCEPTANCE_SHA256,
                                         master_sha256=MASTER_SHA256)
    incomplete = deepcopy(artifact)
    incomplete["omissions"].pop()
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, incomplete, item_id=SCHAFF6_ITEM,
                                         acceptance_sha256=ACCEPTANCE_SHA256,
                                         master_sha256=MASTER_SHA256)
    changed = deepcopy(private)
    changed[0]["text"] += " altered"
    with pytest.raises(PipelineError):
        public_rows_with_omissions(changed, item_id=SCHAFF6_ITEM,
                                   acceptance_sha256=ACCEPTANCE_SHA256,
                                   master_sha256=MASTER_SHA256)
