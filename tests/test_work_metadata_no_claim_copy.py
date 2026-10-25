"""No-claim metadata verification preserves source rows without copying them."""
from copy import deepcopy
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release import work_metadata


@pytest.fixture
def no_claims(monkeypatch):
    monkeypatch.setattr(work_metadata, "_authority", lambda _root, _rows: None)
    return Path("."), [{"provenance": {"source": "historical"}}], {"source": "accepted"}


def test_no_claims_return_original_inputs_without_mutation(no_claims):
    root, rows, receipt = no_claims
    original_rows, original_receipt = deepcopy(rows), deepcopy(receipt)
    checked_rows, checked_receipt = work_metadata.check_work_metadata(root, rows, receipt)
    assert checked_rows is rows
    assert checked_receipt is receipt
    assert rows == original_rows
    assert receipt == original_receipt


@pytest.mark.parametrize("field", ["original_language", "work_kind"])
def test_no_claims_reject_unadopted_row_fields_without_mutation(no_claims, field):
    root, rows, receipt = no_claims
    rows[0]["provenance"][field] = "unadopted"
    original_rows, original_receipt = deepcopy(rows), deepcopy(receipt)
    with pytest.raises(PipelineError, match="unadopted original language"):
        work_metadata.check_work_metadata(root, rows, receipt)
    assert rows == original_rows
    assert receipt == original_receipt


def test_no_claims_reject_unadopted_receipt_without_mutation(no_claims):
    root, rows, receipt = no_claims
    receipt["work_metadata"] = {"unadopted": True}
    original_rows, original_receipt = deepcopy(rows), deepcopy(receipt)
    with pytest.raises(PipelineError, match="unadopted original language"):
        work_metadata.check_work_metadata(root, rows, receipt)
    assert rows == original_rows
    assert receipt == original_receipt
