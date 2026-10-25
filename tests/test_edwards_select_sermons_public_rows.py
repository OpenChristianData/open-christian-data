"""Exact accepted Edwards Select Sermons public scope and private inverse."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release import public_rows as boundary
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.work_metadata import compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/edwards-select-sermons/forms/edwards-select-sermons-english/editions/edwards-select-sermons-ccel-thml-electronic/acceptance.json"
SAVED = ROOT / "reports/_logs/edwards-select-sermons-offline-release-20261001-v1/edwards-select-sermons-ccel-thml-electronic/actual-master-projection.json"
SCOPE = ROOT / "library/works/edwards-select-sermons/publication/edwards-select-private-us-20261012/rights-scope.json"
AUTHORITY = {"acceptance_sha256": "9e5aa76554b253bdf7d09b2825d2c8f0827f35e2da2fd6c17a1c6bbae5ee9b26",
             "master_sha256": "10c21eab6f603b07b0116e5666d5d38f6383912b3806d5ab16ee433a7847bc92"}
SAVED_SHA256 = "084006a4b904cc394b861f9fca4a1f8030b9c887aa0d417cfb7a11ce5288af79"


@pytest.fixture(scope="module")
def private_rows():
    assert sha256(ACCEPTANCE.read_bytes()).hexdigest() == AUTHORITY["acceptance_sha256"]
    scope = SCOPE if SCOPE.is_file() else Path(__file__).resolve().parent / "scope-evidence.json"
    assert sha256(scope.read_bytes()).hexdigest() == boundary.EDWARDS_SELECT_SCOPE_SHA256
    assert sha256(SAVED.read_bytes()).hexdigest() == SAVED_SHA256
    projection = json.loads(SAVED.read_bytes())
    with cached_edition_lookups():
        rows, _ = compose_work_metadata(
            ROOT, [dict(row, license=boundary.EDWARDS_SELECT_LICENSE)
                   for row in projection["rows"]], projection["receipt"])
    assert sha256(canonical_bytes(rows)).hexdigest() == boundary.EDWARDS_SELECT_PRIVATE_ROWS_SHA256
    return rows


@pytest.mark.requires_local_artifacts
def test_accepted_sermon_and_indexes_survive_exact_boundary(private_rows):
    public, inverse = boundary.public_rows_with_omissions(
        private_rows, item_id=boundary.EDWARDS_SELECT_ITEM, **AUTHORITY)
    assert len(public) == len(private_rows) == 21 and inverse is not None
    assert [row["record_id"] for row in public] == [row["record_id"] for row in private_rows]
    assert [public[i]["text"] for i in range(21) if i != 4] == [
        private_rows[i]["text"] for i in range(21) if i != 4]
    assert "An outline of the sermon has been prepared" not in public[4]["text"]
    assert "click on a Roman Numeral" not in public[4]["text"]
    assert "Sermon IV of Seventeen Occasional Sermons" in public[4]["text"]
    assert "Worcester reprint" in public[7]["text"]
    assert "Horman Gardiner" in public[19]["text"]
    assert "Index of Scripture References" in public[20]["text"]
    assert "upper-roman" in json.dumps(public, ensure_ascii=False)
    assert not _scan(public, boundary.EDWARDS_SELECT_ITEM)
    assert boundary.restore_private_source_locations(
        public, inverse, item_id=boundary.EDWARDS_SELECT_ITEM, **AUTHORITY) == private_rows
    fields = [field for entry in inverse["inner"]["omissions"] for field in entry["fields"]]
    assert len([field for field in fields if field["path"][-1] == "style"]) == 25


@pytest.mark.requires_local_artifacts
def test_scope_and_inverse_mutations_fail(private_rows):
    public, inverse = boundary.public_rows_with_omissions(
        private_rows, item_id=boundary.EDWARDS_SELECT_ITEM, **AUTHORITY)
    assert inverse is not None
    altered = deepcopy(public)
    altered[4]["text"] += " altered"
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(
            altered, inverse, item_id=boundary.EDWARDS_SELECT_ITEM, **AUTHORITY)
    altered = deepcopy(inverse)
    altered["inner"]["omissions"][0]["fields"].pop()
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(
            public, altered, item_id=boundary.EDWARDS_SELECT_ITEM, **AUTHORITY)
    altered = deepcopy(inverse)
    altered["removed_outline"]["content"].append({"kind": "text", "text": "unapproved"})
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(
            public, altered, item_id=boundary.EDWARDS_SELECT_ITEM, **AUTHORITY)
    with pytest.raises(PipelineError):
        boundary.public_rows_with_omissions(
            private_rows, item_id=boundary.EDWARDS_SELECT_ITEM,
            acceptance_sha256="0" * 64, master_sha256=AUTHORITY["master_sha256"])
