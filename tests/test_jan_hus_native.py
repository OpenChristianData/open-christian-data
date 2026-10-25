"""Source-bound Jan Hus division and serialized accepted-receipt regression."""

from copy import deepcopy
import json
from pathlib import Path

from ocd_kernel.projection.categories import jan_hus_native
from ocd_kernel.projection.categories.sermons import _accepted_context


import pytest

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / (
    "library/works/jan-hus-de-ecclesia-the-church/forms/"
    "jan-hus-de-ecclesia-the-church-wikisource-retained/editions/"
    "jan-hus-de-ecclesia-the-church-wikisource-electronic/acceptance.json"
)


@pytest.mark.requires_local_artifacts
def test_exact_accepted_source_divisions_and_receipt_mutations():
    context = _accepted_context(ROOT, ACCEPTANCE, expected_category="prose")
    assert jan_hus_native.route(context)
    result = jan_hus_native.project(context)
    rows, receipt = result["rows"], result["receipt"]
    assert len(rows) == len(receipt["source_division_binding"]["source_unit_ids"]) == 31
    assert receipt["master_sha256"] == jan_hus_native.MASTER_SHA256
    assert jan_hus_native.verify(context, rows, json.loads(json.dumps(receipt))) == []
    bad_receipt = deepcopy(receipt)
    bad_receipt["master_sha256"] = "0" * 64
    assert jan_hus_native.verify(context, rows, bad_receipt)
    bad_rows = deepcopy(rows)
    bad_rows[0]["text"] += "changed"
    assert jan_hus_native.verify(context, bad_rows, receipt)
