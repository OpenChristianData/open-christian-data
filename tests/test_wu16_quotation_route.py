"""Maintained quotation route controls; acceptance is simulated only in tmp_path.

Reuse the existing acceptance fixture and schema owners, without authoring a
second route declaration or lifecycle ledger. These tests do not prove CVW review.
"""

import copy
import json

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.quotations import (
    project_accepted_quotations,
    verify_accepted_quotations,
)
from ocd_kernel.tei.acceptance import promote_accepted_master
from tests.test_projection_quotations import accepted_fixture


@pytest.fixture
def tmp_path(tmp_path_factory):
    """Keep nested accepted-edition paths below the Windows path limit."""
    return tmp_path_factory.mktemp("qr")


def _onboard(tmp_path):
    root, acceptance = accepted_fixture(tmp_path, "quotations")
    promoted = promote_accepted_master(
        root, acceptance_path=acceptance, destination=tmp_path / "offline"
    )
    return tmp_path / "offline", promoted.acceptance_path


def test_valid_route_preserves_occurrences_and_unknown_original_work(tmp_path):
    root, acceptance = _onboard(tmp_path)
    result = project_accepted_quotations(root, acceptance_path=acceptance)
    assert verify_accepted_quotations(root, acceptance_path=acceptance, **result) == []
    rows = result["rows"]
    assert len(rows) == 5
    assert rows[0]["text"] == rows[3]["text"]
    assert rows[0]["record_id"] != rows[3]["record_id"]
    assert rows[0]["locator"]["heading"] != rows[3]["locator"]["heading"]
    assert [row["sequence"] for row in rows] == list(range(1, 6))
    # A source citation is not an asserted original-work identity.
    assert rows[0]["citation"]["work"] is None
    assert all("original_work_id" not in row for row in rows)
    record = json.loads(acceptance.read_text(encoding="utf-8"))
    assert record["decision"]["human_decision"]["status"] == "not-recorded"


@pytest.mark.parametrize("mutation", ["context", "order", "selection", "parent", "revision", "deduplicate"])
def test_invalid_route_output_names_affected_occurrence(tmp_path, mutation):
    root, acceptance = _onboard(tmp_path)
    result = project_accepted_quotations(root, acceptance_path=acceptance)
    altered = copy.deepcopy(result)
    rows = altered["rows"]
    if mutation == "context":
        rows[0]["locator"]["heading"] = None
    elif mutation == "order":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "selection":
        rows.pop(0)
    elif mutation == "parent":
        rows[0]["work_id"] = "unrelated-parent"
    elif mutation == "revision":
        rows[0]["representation_revision"] = "unrelated-revision"
    else:
        rows.pop(3)
    errors = verify_accepted_quotations(root, acceptance_path=acceptance, **altered)
    affected = "d0929am" if mutation == "deduplicate" else "d0226pm"
    assert any(f"occurrence {affected}" in error for error in errors)


def test_stale_route_input_is_rejected_before_output(tmp_path):
    root, acceptance = _onboard(tmp_path)
    result = project_accepted_quotations(root, acceptance_path=acceptance)
    binding = result["receipt"]["authority"]["master"]
    master = root / binding["path"]
    master.write_bytes(master.read_bytes() + b"\n")
    with pytest.raises(PipelineError):
        project_accepted_quotations(root, acceptance_path=acceptance)
    assert verify_accepted_quotations(root, acceptance_path=acceptance, **result)
