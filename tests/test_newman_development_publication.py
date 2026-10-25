"""Accepted Newman text and exact reversible Greek source-marker release."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.public_rows import public_rows_with_omissions, restore_private_source_locations
from ocd_kernel.release.work_metadata import check_work_metadata, compose_work_metadata


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "library/works/newman-development-christian-doctrine/forms/newman-development-christian-doctrine-gutenberg-retained-en/editions/newman-development-christian-doctrine-gutenberg-electronic/acceptance.json"
MASTER_SHA = "03bf082f6f366163bdf14ea917108cbe393c5257313d739b2585cf0178d2938a"
ITEM = "newman-development-christian-doctrine--newman-development-christian-doctrine-gutenberg-electronic"
PRIVATE = "urn:ocd:greek-transliteration"
PUBLIC = "source-annotation:greek-transliteration"


@pytest.fixture(scope="module")
def accepted_rows():
    with cached_edition_lookups():
        projection = project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
        rows, receipt = compose_work_metadata(ROOT, projection["rows"], projection["receipt"])
    acceptance_sha = hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest()
    assert acceptance_sha == "3d4e48d90c1d03d1d64520c30515fa42c4fcd811ff9160d764c3259696837612"
    assert receipt["master_sha256"] == MASTER_SHA
    return rows, receipt, acceptance_sha


def test_all_source_units_and_greek_labels_survive_public_alias(accepted_rows) -> None:
    rows, receipt, acceptance_sha = accepted_rows
    public, inverse = public_rows_with_omissions(
        rows, item_id=ITEM, acceptance_sha256=acceptance_sha, master_sha256=MASTER_SHA)
    assert len(rows) == len(public) == 11 and inverse is not None
    assert rows[0]["text"].startswith("Transcriber's Notes:")
    assert rows[-1]["text"].startswith("TRANSCRIBER'S NOTES:")
    assert "UNIVERSITY OF NOTRE DAME PRESS" in rows[1]["text"]
    assert "Ian Ker" not in " ".join(row["text"] for row in rows)
    assert [row["text"] for row in public] == [row["text"] for row in rows]
    assert _scan(public, ITEM) == []
    fields = [field for entry in inverse["omissions"] for field in entry["fields"]]
    assert len(fields) == 26
    assert {field["private"] for field in fields} == {PRIVATE}
    assert {field["public"] for field in fields} == {PUBLIC}
    restored = restore_private_source_locations(
        public, inverse, item_id=ITEM,
        acceptance_sha256=acceptance_sha, master_sha256=MASTER_SHA)
    assert restored == rows
    with cached_edition_lookups():
        checked_rows, checked_receipt = check_work_metadata(ROOT, restored, receipt)
        assert verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE,
                                     rows=checked_rows, receipt=checked_receipt) == []


def test_public_alias_and_inverse_reject_tampering(accepted_rows) -> None:
    rows, _, acceptance_sha = accepted_rows
    public, inverse = public_rows_with_omissions(
        rows, item_id=ITEM, acceptance_sha256=acceptance_sha, master_sha256=MASTER_SHA)
    assert inverse is not None
    altered = deepcopy(public)
    field = inverse["omissions"][0]["fields"][0]
    node = altered[inverse["omissions"][0]["row_index"]]
    for segment in field["path"][:-1]:
        node = node[segment]
    node[field["path"][-1]] = "source-annotation:changed"
    with pytest.raises(PipelineError):
        restore_private_source_locations(
            altered, inverse, item_id=ITEM,
            acceptance_sha256=acceptance_sha, master_sha256=MASTER_SHA)
    incomplete = deepcopy(inverse)
    incomplete["omissions"][0]["fields"].pop()
    with pytest.raises(PipelineError):
        restore_private_source_locations(
            public, incomplete, item_id=ITEM,
            acceptance_sha256=acceptance_sha, master_sha256=MASTER_SHA)
    with pytest.raises(PipelineError):
        public_rows_with_omissions(
            rows[:-1], item_id=ITEM,
            acceptance_sha256=acceptance_sha, master_sha256=MASTER_SHA)
