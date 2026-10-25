"""Exact accepted Ryle scope and reversible public formatting regression."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import (
    RYLE_ITEM, RYLE_LICENSE, RYLE_SCOPE_SHA256,
    public_rows_with_omissions, restore_private_source_locations,
)
from ocd_kernel.release.work_metadata import compose_work_metadata, check_work_metadata

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/ryle-holiness/forms/ryle-holiness-english/editions/ryle-holiness-retained-electronic-witness/acceptance.json"
SCOPE = ROOT / "library/works/ryle-holiness/publication/ryle-us-historical-20261012/rights-scope.json"
ACCEPTANCE_SHA = "da5b3a57ab87242a19987b39c019d3a92ac3f154922423100d99285b52889a91"
MASTER_SHA = "fc84a9b758d566bbee7011e9cab517229973b50041d39d9a427a4b1f67294850"


@pytest.fixture(scope="module")
def real_rows():
    assert sha256(ACCEPTANCE.read_bytes()).hexdigest() == ACCEPTANCE_SHA
    assert sha256(SCOPE.read_bytes()).hexdigest() == RYLE_SCOPE_SHA256
    with cached_edition_lookups():
        projected = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
        rows, receipt = compose_work_metadata(
            ROOT, [dict(row, license=RYLE_LICENSE) for row in projected["rows"]],
            projected["receipt"])
    return rows, receipt


def transform(rows):
    return public_rows_with_omissions(
        rows, item_id=RYLE_ITEM, acceptance_sha256=ACCEPTANCE_SHA,
        master_sha256=MASTER_SHA)


def restore(rows, inverse):
    return restore_private_source_locations(
        rows, inverse, item_id=RYLE_ITEM, acceptance_sha256=ACCEPTANCE_SHA,
        master_sha256=MASTER_SHA)


def test_ryle_four_source_units_words_and_indexes_remain(real_rows):
    rows, receipt = real_rows
    public, inverse = transform(rows)
    assert inverse is not None and len(public) == len(rows) == 4
    assert [row["text"] for row in public] == [row["text"] for row in rows]
    assert [row["record_id"] for row in public] == [row["record_id"] for row in rows]
    assert "THIS EDITION 1952" in public[0]["text"]
    assert "Index of Scripture References" in public[3]["text"]
    assert "I   SIN" in public[2]["text"]
    assert not _scan(public, RYLE_ITEM)
    fields = [field for entry in inverse["omissions"] for field in entry["fields"]]
    assert len(fields) == 7
    assert all(field["path"][-1] == "style" and field["public"] is None for field in fields)
    assert restore(public, inverse) == rows
    source_rows = [{key: value for key, value in row.items() if key != "license"}
                   for row in rows]
    with cached_edition_lookups():
        checked_rows, checked_receipt = check_work_metadata(ROOT, source_rows, receipt)
        assert verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE,
                                     rows=checked_rows, receipt=checked_receipt) == []


def test_ryle_scope_and_inverse_mutations_fail(real_rows):
    rows, _ = real_rows
    public, inverse = transform(rows)
    assert inverse is not None
    altered = deepcopy(public)
    altered[0]["text"] += "unapproved"
    with pytest.raises(PipelineError):
        restore(altered, inverse)
    incomplete = deepcopy(inverse)
    incomplete["omissions"][0]["fields"].pop()
    with pytest.raises(PipelineError):
        restore(public, incomplete)
    changed = deepcopy(rows)
    changed[0]["license"] = "unqualified"
    with pytest.raises(PipelineError):
        transform(changed)
    with pytest.raises(PipelineError):
        transform(rows[:-1])
    with pytest.raises(PipelineError):
        restore_private_source_locations(
            public, inverse, item_id=RYLE_ITEM, acceptance_sha256="0" * 64,
            master_sha256=MASTER_SHA)
    assert sha256(canonical_bytes(public)).hexdigest() == (
        "126427544212591cd4854b2e49d440182e57cffed2f24077065543aa2f9a4a7a")
