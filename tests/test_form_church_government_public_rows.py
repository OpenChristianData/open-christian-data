"""Exact reversible public boundary for the accepted Westminster Form."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.form_church_government import ITEM, LICENSE
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (
    public_rows_with_omissions,
    restore_private_source_locations,
)
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / (
    "library/works/form-of-church-government/forms/"
    "form-of-church-government-retained-text/editions/"
    "form-of-church-government-retained-electronic-witness/acceptance.json"
)
PROJECTION = ROOT / (
    "reports/_logs/form-of-church-government-private-release-20261002-v1/"
    "actual-master-projection-proof.json"
)


@pytest.mark.requires_local_artifacts
def test_form_historical_rows_restore_exact_accepted_private_rows():
    saved = json.loads(PROJECTION.read_text(encoding="utf-8"))
    rows = [dict(row, license=LICENSE) for row in saved["rows"]]
    rows, receipt = compose_work_metadata(ROOT, rows, saved["receipt"])
    authority = {
        "acceptance_sha256": sha256(ACCEPTANCE.read_bytes()).hexdigest(),
        "master_sha256": receipt["master_sha256"],
    }
    public, artifact = public_rows_with_omissions(rows, item_id=ITEM, **authority)
    assert len(public) == 2
    assert [len(row["text"]) for row in public] == [2848, 31060]
    assert "The Directory for the Ordination of Ministers." in public[1]["text"]
    assert not any("Back to top" in row["text"] for row in public)
    assert not _scan(public, "Form historical public rows")
    assert restore_private_source_locations(
        json.loads(json.dumps(public)), json.loads(json.dumps(artifact)),
        item_id=ITEM, **authority,
    ) == rows

    changed = deepcopy(public)
    changed[1]["text"] += " forged"
    with pytest.raises(PipelineError):
        restore_private_source_locations(changed, artifact, item_id=ITEM, **authority)
    changed_receipt = deepcopy(artifact)
    changed_receipt["navigation"][0]["content"][0]["content"][0]["content"][0]["text"] += " forged"
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, changed_receipt, item_id=ITEM,
                                         **authority)
    with pytest.raises(PipelineError):
        public_rows_with_omissions(rows, item_id=ITEM,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=authority["master_sha256"])
