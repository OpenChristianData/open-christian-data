"""Exact partial BCP1662 historical public boundary and private inverse."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release import bcp1662_public as boundary
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (
    public_rows_with_omissions, restore_private_source_locations,
)
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/bcp-1662/forms/bcp-1662-retained-electronic/editions/bcp-1662-retained-electronic-witness/acceptance.json"
PROJECTION = ROOT / "reports/_logs/bcp1662-private-release-20261002-v1/actual-master-projection.json"
SCOPE = ROOT / "library/works/bcp-1662/publication/bcp1662-historical-private-us-20261012/rights-scope.json"


@pytest.fixture(scope="module")
def private_rows():
    assert sha256(ACCEPTANCE.read_bytes()).hexdigest() == boundary.ACCEPTANCE_SHA256
    assert sha256(ACCEPTANCE.with_name("master.tei.xml").read_bytes()).hexdigest() == boundary.MASTER_SHA256
    scope = SCOPE if SCOPE.is_file() else Path(__file__).resolve().parent / "scope-evidence.json"
    assert sha256(scope.read_bytes()).hexdigest() == boundary.SCOPE_SHA256
    assert sha256(PROJECTION.read_bytes()).hexdigest() == (
        "7fe846b89918dd7f9f0345ea2273539b34d2ec587093d317c0e4f2f2c8d5ab4e")
    saved = json.loads(PROJECTION.read_bytes())
    with cached_edition_lookups():
        rows, _ = compose_work_metadata(
            ROOT, [dict(row, license=boundary.LICENSE) for row in saved["rows"]],
            saved["receipt"])
    assert sha256(canonical_bytes(rows)).hexdigest() == boundary.PRIVATE_ROWS_SHA256
    return rows


@pytest.mark.requires_local_artifacts
def test_explicit_later_passages_and_layout_only_omitted(private_rows):
    authority = {"acceptance_sha256": boundary.ACCEPTANCE_SHA256,
                 "master_sha256": boundary.MASTER_SHA256}
    public, inverse = boundary.public_rows(private_rows, **authority)
    assert len(public) == 25
    assert len(inverse["removed"]) == 3 and len(inverse["styles"]) == 473
    assert [row["record_id"] for row in public] == [row["record_id"] for row in private_rows]
    assert [row.get("source_links") for row in public] == [
        row.get("source_links") for row in private_rows]
    assert [public[i]["text"] for i in range(25) if i not in (0, 1, 5)] == [
        private_rows[i]["text"] for i in range(25) if i not in (0, 1, 5)]
    assert all("If no priest be present" not in public[i]["text"] for i in (0, 1))
    assert "If a Minister be persuaded" not in public[5]["text"]
    assert json.dumps(public, ensure_ascii=False).count("source-role-token:#bcp-role-") == 255
    assert not _scan(public, boundary.ITEM)
    assert boundary.restore_private_rows(public, inverse, **authority) == private_rows

    dispatched, receipt = public_rows_with_omissions(
        private_rows, item_id=boundary.ITEM, **authority)
    assert dispatched == public and receipt == inverse
    assert restore_private_source_locations(
        dispatched, receipt, item_id=boundary.ITEM, **authority) == private_rows


@pytest.mark.requires_local_artifacts
def test_scope_and_inverse_mutations_fail(private_rows):
    authority = {"acceptance_sha256": boundary.ACCEPTANCE_SHA256,
                 "master_sha256": boundary.MASTER_SHA256}
    public, inverse = boundary.public_rows(private_rows, **authority)
    altered = deepcopy(public)
    altered[0]["text"] += " altered"
    with pytest.raises(PipelineError):
        boundary.restore_private_rows(altered, inverse, **authority)
    altered = deepcopy(inverse)
    altered["styles"].pop()
    with pytest.raises(PipelineError):
        boundary.restore_private_rows(public, altered, **authority)
    altered = deepcopy(inverse)
    altered["removed"][0]["node"]["content"].append({"kind": "text", "text": "altered"})
    with pytest.raises(PipelineError):
        boundary.restore_private_rows(public, altered, **authority)
    with pytest.raises(PipelineError):
        boundary.public_rows(private_rows, acceptance_sha256="0" * 64,
                             master_sha256=boundary.MASTER_SHA256)
