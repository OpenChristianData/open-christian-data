"""Source-bound checks for the remaining representable LIB062 catechisms."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.creeds_json_lib062_remaining import (
    ROOT,
    ROUTES,
    project_rows,
    shape,
    verify_rows,
)


CANDIDATES = Path("D:/Library/Open Christian Data/candidate-reviews/creeds-lib062-six-20260926")
SHORTER_CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/creeds-catechism-preflight-20260926")
STAGEABLE = ("keachs-catechism", "matthew-henrys-scripture-catechism", "puritan-catechism",
             "exposition-of-the-assemblies-catechism", "heidelberg-catechism")


def _case(work_id: str) -> tuple[dict[str, object], dict[str, object], bytes]:
    route = ROUTES[work_id]
    source_bytes = (ROOT / route["source_path"]).read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == route["source_sha256"]
    document = json.loads(source_bytes)
    candidate_root = SHORTER_CANDIDATE if work_id == "shorter-catechism-explained" else CANDIDATES
    tei = (candidate_root / work_id / "package/content.tei.xml").read_bytes()
    assert hashlib.sha256(tei).hexdigest() == route["candidate_content_sha256"]
    context = {
        "work_id": work_id,
        "identity": {"work_id": work_id, "textual_form_id": f"{work_id}-retained-electronic",
                     "edition_id": route["edition_id"]},
        "representation_revision": "lib062-test", "edition_title": "Retained Creeds.json electronic witness",
        "document": document,
    }
    return context, document, tei


@pytest.mark.parametrize("work_id", STAGEABLE)
def test_exact_source_rows_and_independent_checker(work_id: str) -> None:
    context, document, tei = _case(work_id)
    rows = project_rows(context, document, tei)
    route = ROUTES[work_id]
    assert len(rows) == route["row_count"]
    assert sum(len(row["proofs"]) for row in rows) == route["proof_count"]
    assert sum(len(row["sub_questions"] or []) for row in rows) == route["subquestion_count"]
    assert verify_rows(context, rows, tei) == []
    rows[0]["answer"] += " altered"
    assert verify_rows(context, rows, tei)


def test_nested_subquestion_mutation_is_rejected() -> None:
    context, document, tei = _case("matthew-henrys-scripture-catechism")
    rows = project_rows(context, document, tei)
    rows[0]["sub_questions"][0]["answer"] += " changed"
    assert verify_rows(context, rows, tei)
    altered = tei.replace(b' n="1a"', b' n="1z"', 1)
    assert altered != tei
    assert verify_rows(context, project_rows(context, document, tei), altered)


def test_heidelberg_preserves_proof_bearing_questions_and_rejects_mutations() -> None:
    context, document, tei = _case("heidelberg-catechism")
    assert document["Metadata"]["OriginalLanguage"] == "German"
    rows = project_rows(context, document, tei)
    assert [row["sequence"] for row in rows if "question_with_proofs" in row] == [25, 47]
    assert all(rows[number - 1]["question_with_proofs"] == document["Data"][number - 1]["QuestionWithProofs"]
               for number in (25, 47))
    assert sum(len(row["proofs"]) for row in rows) == 357
    assert sum(len(proof["references"]) for row in rows for proof in row["proofs"]) == 1011
    assert verify_rows(context, rows, tei) == []

    removed = deepcopy(rows)
    del removed[24]["question_with_proofs"]
    assert verify_rows(context, removed, tei)

    changed = deepcopy(rows)
    changed[46]["question_with_proofs"] += " changed"
    assert verify_rows(context, changed, tei)

    invented = deepcopy(rows)
    invented[0]["question_with_proofs"] = invented[0]["question"]
    assert verify_rows(context, invented, tei)

    altered_tei = tei.replace(b'ana="#question-with-proofs"', b'ana="#changed-question-with-proofs"', 1)
    assert altered_tei != tei
    assert verify_rows(context, rows, altered_tei)


def test_1695_empty_source_answer_is_explicit_contract_hold() -> None:
    _, document, _ = _case("1695-baptist-catechism")
    with pytest.raises(PipelineError, match="empty source Answer"):
        shape("1695-baptist-catechism", document)


def test_shorter_explained_preserves_every_nested_label_parent_and_order() -> None:
    context, document, tei = _case("shorter-catechism-explained")
    rows = project_rows(context, document, tei)
    assert len(rows) == 107
    assert sum(len(row["sub_questions"] or []) for row in rows) == 3831
    for position, (source, row) in enumerate(zip(document["Data"], rows, strict=True), 1):
        assert row["sort_key"] == position
        assert row["item_id"] == str(source["Number"])
        assert [(sub["item_id"], sub["question"], sub["answer"]) for sub in row["sub_questions"]] == [
            (sub["Number"], sub["Question"], sub["Answer"]) for sub in source["SubQuestions"]
        ]
    assert verify_rows(context, rows, tei) == []

    relabeled = deepcopy(rows)
    relabeled[0]["sub_questions"][0]["item_id"] = "999"
    assert verify_rows(context, relabeled, tei)

    moved = deepcopy(rows)
    moved[1]["sub_questions"].insert(0, moved[0]["sub_questions"].pop(0))
    assert verify_rows(context, moved, tei)

    reordered = deepcopy(rows)
    reordered[0]["sub_questions"][0], reordered[0]["sub_questions"][1] = (
        reordered[0]["sub_questions"][1], reordered[0]["sub_questions"][0]
    )
    assert verify_rows(context, reordered, tei)


def test_exposition_preserves_placeholder_labels_empty_lists_and_source_order() -> None:
    context, document, tei = _case("exposition-of-the-assemblies-catechism")
    rows = project_rows(context, document, tei)
    assert len(rows) == 125
    assert sum(len(row["sub_questions"] or []) for row in rows) == 1244
    assert sum(row["sub_questions"] == [] for row in rows) == 24
    placeholders = [row for row in rows if row["item_id"] == "?"]
    assert len(placeholders) == 23
    assert all(row["question"] == row["answer"] == "?" for row in placeholders)
    assert sum(sub["item_id"] == "2 " for row in rows for sub in row["sub_questions"] or []) == 1
    assert sum(sub["item_id"] == "4 " for row in rows for sub in row["sub_questions"] or []) == 1
    for position, (source, row) in enumerate(zip(document["Data"], rows, strict=True), 1):
        assert row["sort_key"] == position
        assert row["item_id"] == source["Number"]
        assert [(sub["item_id"], sub["question"], sub["answer"]) for sub in row["sub_questions"]] == [
            (sub["Number"], sub["Question"], sub["Answer"])
            for sub in source["SubQuestions"]
        ]
    assert verify_rows(context, rows, tei) == []

    trimmed = deepcopy(rows)
    target = next(sub for row in trimmed for sub in row["sub_questions"] or [] if sub["item_id"] == "2 ")
    target["item_id"] = target["item_id"].strip()
    assert verify_rows(context, trimmed, tei)

    relabeled_placeholder = deepcopy(rows)
    target = next(row for row in relabeled_placeholder if row["item_id"] == "?")
    target["item_id"] = "1"
    assert verify_rows(context, relabeled_placeholder, tei)

    altered = deepcopy(document)
    target = next(row for row in altered["Data"] if row["Number"] == "?")
    target["Number"] = "1"
    with pytest.raises(PipelineError, match="placeholder row"):
        shape("exposition-of-the-assemblies-catechism", altered)


def test_catechism_schema_accepts_source_exact_main_and_subquestion_labels() -> None:
    schema = json.loads((ROOT / "schemas/v2/categories/catechisms.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema["$defs"]["subquestion"])
    item = {"item_id": "1", "question": "Question", "answer": "Answer", "proofs": []}
    for label in ("1", "001", "1a", "2 "):
        assert validator.is_valid({**item, "item_id": label})
    for label in ("", " 2", "2  ", "?", "1-a"):
        assert not validator.is_valid({**item, "item_id": label})

    main = Draft202012Validator(schema["properties"]["item_id"])
    assert main.is_valid("?")
    assert main.is_valid("107")
    assert not main.is_valid("1 ")
