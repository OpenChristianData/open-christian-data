"""Exact historical-text boundary for the accepted Bounds electronic witness."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release import public_rows as boundary
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
SAVED = ROOT / "library/works/bounds-power-through-prayer/publication/actual-master-projection.json"
SAVED_SHA256 = "10ae6c05cff20e6987cd8fa182860b3b7acc4d9503d2678236132d45102d0364"
AUTHORITY = {"acceptance_sha256": boundary.BOUNDS_ACCEPTANCE_SHA256,
             "master_sha256": boundary.BOUNDS_MASTER_SHA256}


def _licensed_rows() -> list[dict]:
    assert sha256(SAVED.read_bytes()).hexdigest() == SAVED_SHA256
    projection = json.loads(SAVED.read_text(encoding="utf-8"))
    licensed = [dict(row, license=boundary.BOUNDS_LICENSE) for row in projection["rows"]]
    rows, _receipt = compose_work_metadata(ROOT, licensed, projection["receipt"])
    return rows


@pytest.mark.requires_local_artifacts
def test_only_two_promotional_paragraphs_are_reversibly_omitted() -> None:
    private = _licensed_rows()
    public, artifact = boundary.public_rows_with_omissions(
        private, item_id=boundary.BOUNDS_ITEM, **AUTHORITY,
    )
    assert len(private) == len(public) == 1
    assert artifact["contract"] == boundary.BOUNDS_CONTRACT
    assert [entry["index"] for entry in artifact["removed"]] == [12, 14]
    assert boundary.restore_private_source_locations(
        public, artifact, item_id=boundary.BOUNDS_ITEM, **AUTHORITY,
    ) == private
    assert not _scan(public, "Bounds public text")
    assert "Power through Prayerhas been called" not in public[0]["text"]
    assert "In twenty provocative and inspiring chapters" not in public[0]["text"]
    assert "Recreation to a minister" in public[0]["text"]
    assert "A Praying Pulpit Begets a Praying Pew" in public[0]["text"]
    assert sha256(canonical_bytes(private[0])).hexdigest() == boundary.BOUNDS_PRIVATE_ROW_SHA256


@pytest.mark.requires_local_artifacts
def test_bounds_scope_and_inverse_reject_mutations() -> None:
    private = _licensed_rows()
    public, artifact = boundary.public_rows_with_omissions(
        private, item_id=boundary.BOUNDS_ITEM, **AUTHORITY,
    )
    mutated_private = deepcopy(private)
    mutated_private[0]["structure"][0]["content"][0]["content"][12]["content"].append(
        {"kind": "text", "text": " changed"}
    )
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(
            mutated_private, item_id=boundary.BOUNDS_ITEM, **AUTHORITY,
        )
    wrong_license = deepcopy(private)
    wrong_license[0]["license"] = "CC0 1.0"
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(
            wrong_license, item_id=boundary.BOUNDS_ITEM, **AUTHORITY,
        )
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(
            private, item_id=boundary.BOUNDS_ITEM,
            acceptance_sha256=AUTHORITY["acceptance_sha256"], master_sha256="0" * 64,
        )
    changed_public = deepcopy(public)
    changed_public[0]["text"] += " changed"
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(
            changed_public, artifact, item_id=boundary.BOUNDS_ITEM, **AUTHORITY,
        )
    changed_receipt = deepcopy(artifact)
    changed_receipt["removed"][0]["node"]["content"].append(
        {"kind": "text", "text": " changed"}
    )
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(
            public, changed_receipt, item_id=boundary.BOUNDS_ITEM, **AUTHORITY,
        )
