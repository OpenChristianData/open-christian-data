"""Exact Creeds.json Q&A mapping and independent mutation probes."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.creeds_json_two_catechisms import (
    ROUTES,
    project_rows,
    shape,
    verify_rows,
)
from ocd_kernel.projection.categories.creeds_json_two_catechisms_profile import _metadata_header


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = Path("D:/Library/Open Christian Data/candidate-reviews/creeds-catechism-preflight-20260926")


def _fixture(work_id: str) -> tuple[dict[str, object], dict[str, object], bytes]:
    route = ROUTES[work_id]
    source = json.loads((ROOT / route["source_path"]).read_bytes())
    context = {
        "work_id": work_id,
        "identity": {
            "work_id": work_id,
            "textual_form_id": f"{work_id}-retained-electronic",
            "edition_id": route["edition_id"],
        },
        "representation_revision": "source-test",
        "edition_title": source["Metadata"]["Title"],
        "document": source,
    }
    tei = (CANDIDATES / route["candidate"] / "package/content.tei.xml").read_bytes()
    return context, source, tei


@pytest.mark.parametrize("work_id", sorted(ROUTES))
def test_exact_catechism_units_project_and_check(work_id: str) -> None:
    context, source, tei = _fixture(work_id)
    rows = project_rows(context, source, tei)
    assert len(rows) == ROUTES[work_id]["row_count"]
    assert sum(len(row["proofs"]) for row in rows) == ROUTES[work_id]["proof_count"]
    assert sum(len(proof["references"]) for row in rows for proof in row["proofs"]) == ROUTES[work_id]["reference_count"]
    assert verify_rows(context, rows, tei) == []
    changed = deepcopy(rows)
    changed[-1]["answer"] = "invented answer"
    assert verify_rows(context, changed, tei)


def test_empty_source_proof_arrays_remain_empty_rows() -> None:
    context, source, tei = _fixture("westminster-larger-catechism")
    rows = project_rows(context, source, tei)
    assert [row["item_id"] for row in rows if not row["proofs"]] == ["100", "188"]
    assert rows[99]["answer_with_proofs"] == source["Data"][99]["AnswerWithProofs"]
    assert verify_rows(context, rows, tei) == []


def test_proof_mutation_fails_independent_checker() -> None:
    context, source, tei = _fixture("westminster-larger-catechism")
    rows = project_rows(context, source, tei)
    altered_tei = tei.replace(b"Rom.11.36", b"Rom.11.35", 1)
    assert altered_tei != tei
    assert verify_rows(context, rows, altered_tei)
    changed = deepcopy(rows)
    changed[0]["proofs"][0]["references"][0]["raw"] = "Rom.11.35"
    assert verify_rows(context, changed, tei)


def test_source_question_shape_fails_closed() -> None:
    _, source, _ = _fixture("catechism-for-young-children")
    changed = deepcopy(source)
    changed["Data"][0]["SubQuestions"] = []
    with pytest.raises(PipelineError, match="source question 1 differs"):
        shape("catechism-for-young-children", changed)


def test_null_metadata_carrier_keeps_source_type_and_path() -> None:
    _, source, tei = _fixture("catechism-for-young-children")
    assert source["Metadata"]["OriginStory"] is None
    _metadata_header(tei, source["Metadata"])
    altered = tei.replace(b'n="OriginStory">null', b'n="OriginStory">"null"', 1)
    assert altered != tei
    with pytest.raises(PipelineError, match="metadata value differs: OriginStory"):
        _metadata_header(altered, source["Metadata"])
