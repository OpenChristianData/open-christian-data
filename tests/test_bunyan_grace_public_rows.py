"""Exact, reversible public scope for the accepted Bunyan electronic witness."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (
    BUNYAN_ITEM, BUNYAN_LICENSE, public_rows_with_omissions,
    restore_private_source_locations,
)
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / (
    "library/works/bunyan-grace-abounding/forms/bunyan-grace-abounding-english/"
    "editions/bunyan-grace-abounding-ccel-thml-electronic/acceptance.json"
)
PROJECTION = ROOT / (
    "reports/_logs/bunyan-grace-abounding-offline-release-20261001-v1/"
    "bunyan-grace-abounding-ccel-thml-electronic/actual-master-projection.json"
)


@pytest.mark.requires_local_artifacts
def test_bunyan_foreword_omission_restores_exact_selected_private_row():
    saved = json.loads(PROJECTION.read_text(encoding="utf-8"))
    rows = [dict(row, license=BUNYAN_LICENSE) for row in saved["rows"]]
    rows, receipt = compose_work_metadata(ROOT, rows, saved["receipt"])
    authority = {
        "acceptance_sha256": sha256(ACCEPTANCE.read_bytes()).hexdigest(),
        "master_sha256": receipt["master_sha256"],
    }
    public, artifact = public_rows_with_omissions(rows, item_id=BUNYAN_ITEM, **authority)
    assert len(public) == 1
    assert len(public[0]["structure"][0]["content"]) == 14
    assert len(rows[0]["text"]) - len(public[0]["text"]) == 4411
    assert not _scan(public, "Bunyan public row")
    assert restore_private_source_locations(
        json.loads(json.dumps(public)), json.loads(json.dumps(artifact)),
        item_id=BUNYAN_ITEM, **authority,
    ) == rows

    changed = deepcopy(public)
    changed[0]["text"] += " forged"
    with pytest.raises(PipelineError):
        restore_private_source_locations(changed, artifact, item_id=BUNYAN_ITEM, **authority)
    changed_receipt = deepcopy(artifact)
    changed_receipt["removed"][0]["content"].append({"kind": "text", "text": " forged"})
    with pytest.raises(PipelineError):
        restore_private_source_locations(public, changed_receipt, item_id=BUNYAN_ITEM,
                                         **authority)
    with pytest.raises(PipelineError):
        public_rows_with_omissions(rows, item_id=BUNYAN_ITEM,
                                   acceptance_sha256="0" * 64,
                                   master_sha256=authority["master_sha256"])
