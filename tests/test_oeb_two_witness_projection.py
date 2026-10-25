"""Focused accepted OEB US/Cth witness projection and inverse checks."""

from collections import Counter
import copy
from pathlib import Path

import pytest

from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories import bible, oeb_native_bible
from ocd_kernel.projection.categories.oeb_native_bible_check import check_document
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.public_allowlist import _scan


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/open-english-bible/forms/oeb-english/editions/oeb-2025-6-us-cth/acceptance.json"


@pytest.fixture(scope="module")
def accepted_projection():
    with cached_edition_lookups():
        metadata = oeb_native_bible._context(ROOT, ACCEPTANCE)
        projection = bible.project_accepted_bible(ROOT, acceptance_path=ACCEPTANCE)
    return metadata, projection


def test_distinct_complete_witness_rows_and_independent_receipt(accepted_projection):
    metadata, projection = accepted_projection
    rows = projection["rows"]
    assert len(rows) == 27828
    assert Counter(row["locator"]["witness"] for row in rows) == {"US": 13914, "Cth": 13914}
    assert len({row["record_id"] for row in rows}) == len(rows)
    assert len({row["edition_id"] for row in rows}) == 1
    assert projection["inventory"]["textual_members"] == 90
    assert projection["inventory"]["blank_footnote_verses"] == 38
    assert check_document(metadata["master_path"], rows, projection["receipt"], metadata=metadata) == []
    assert _scan(rows, "OEB public rows") == []
    us = {(row["locator"]["book_osis"], row["locator"]["chapter"],
           row["locator"]["verse"]): row["text"]
          for row in rows if row["locator"]["witness"] == "US"}
    cth = {(row["locator"]["book_osis"], row["locator"]["chapter"],
            row["locator"]["verse"]): row["text"]
           for row in rows if row["locator"]["witness"] == "Cth"}
    assert us.keys() == cth.keys()
    assert sum(us[key] != cth[key] for key in us) == 4229


@pytest.mark.parametrize("mutation", ["witness", "text", "missing-row", "receipt"])
def test_independent_observer_rejects_mutations(accepted_projection, mutation):
    metadata, projection = accepted_projection
    rows = copy.deepcopy(projection["rows"])
    receipt = copy.deepcopy(projection["receipt"])
    if mutation == "witness":
        rows[0]["locator"]["witness"] = "Cth"
    elif mutation == "text":
        rows[0]["text"] = "Altered verse wording"
    elif mutation == "missing-row":
        rows.pop(0)
    else:
        receipt["output_sha256"] = "0" * 64
    assert check_document(metadata["master_path"], rows, receipt, metadata=metadata)


def test_oeb_row_schema_requires_named_witness(accepted_projection):
    _, projection = accepted_projection
    row = copy.deepcopy(projection["rows"][0])
    row["locator"].pop("witness")
    with pytest.raises(PipelineError):
        bible._validate_rows([row])
