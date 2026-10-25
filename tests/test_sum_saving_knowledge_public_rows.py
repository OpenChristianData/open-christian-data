"""Exact reversible U.S. historical scope for the accepted Sum."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.prose import project_accepted_prose
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (
    public_rows_with_omissions,
    restore_private_source_locations,
)
from ocd_kernel.release.sum_saving_knowledge import ITEM, LICENSE
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / (
    "library/works/sum-of-saving-knowledge/forms/sum-of-saving-knowledge-retained-electronic/"
    "editions/sum-of-saving-knowledge-retained-electronic-witness/acceptance.json"
)


@pytest.mark.requires_local_artifacts
def test_sum_keeps_six_historical_units_and_restores_contents_links():
    projected = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
    rows = [dict(row, license=LICENSE) for row in projected["rows"]]
    rows, receipt = compose_work_metadata(ROOT, rows, projected["receipt"])
    authority = {
        "acceptance_sha256": sha256(ACCEPTANCE.read_bytes()).hexdigest(),
        "master_sha256": receipt["master_sha256"],
    }
    public, artifact = public_rows_with_omissions(rows, item_id=ITEM, **authority)
    assert len(public) == 6
    assert [len(row["text"]) for row in public] == [1202, 1384, 9018, 18661, 23834, 15897]
    assert [row["text"] for row in public] == [row["text"] for row in rows]
    assert "Edinburgh, January 2, 1871" in public[1]["text"]
    assert all(row["source_references"] == [] for row in public)
    assert not _scan(public, "Sum historical public rows")
    assert restore_private_source_locations(
        json.loads(json.dumps(public)), json.loads(json.dumps(artifact)),
        item_id=ITEM, **authority,
    ) == rows

    changed = deepcopy(public)
    changed[5]["text"] += " forged"
    with pytest.raises(PipelineError):
        restore_private_source_locations(changed, artifact, item_id=ITEM, **authority)
    changed_receipt = deepcopy(artifact)
    changed_receipt["removed"][0]["wrapper"]["content"][0]["text"] += " forged"
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, changed_receipt, item_id=ITEM,
                                         **authority)
    with pytest.raises(PipelineError):
        public_rows_with_omissions(rows, item_id=ITEM,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=authority["master_sha256"])
