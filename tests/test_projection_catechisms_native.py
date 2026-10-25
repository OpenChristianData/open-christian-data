"""Accepted Gutenberg catechisms retain complete source-line scope in native rows."""

from __future__ import annotations

import copy
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.catechisms import (
    _native_question_answers_et,
    _validate_rows,
    UnsupportedStructure,
    project_accepted_catechisms,
    verify_accepted_catechisms,
)


ROOT = Path(__file__).resolve().parents[1]
TEI = "http://www.tei-c.org/ns/1.0"


@pytest.mark.parametrize(
    ("slug", "line_count", "question_count", "role", "first_number"),
    [
        ("baltimore-catechism-no-1", 2620, 206, "hymns", "1."),
        ("luthers-small-catechism", 1035, 44, "home-chart", None),
    ],
)
def test_accepted_native_catechism_preserves_complete_tree_and_exact_qa_lines(
    slug: str, line_count: int, question_count: int, role: str, first_number: str | None,
) -> None:
    acceptance = next((ROOT / "library/works" / slug).rglob("acceptance.json"))
    master = acceptance.with_name("master.tei.xml")
    source = etree.parse(str(master))
    native = project_accepted_catechisms(ROOT, acceptance_path=acceptance)
    row = native["rows"][0]
    receipt = native["receipt"]

    assert verify_accepted_catechisms(
        ROOT, acceptance_path=acceptance, rows=native["rows"], receipt=receipt
    ) == []
    assert len(native["rows"]) == 1
    assert row["source_line_count"] == line_count
    assert len(row["question_answers"]) == question_count
    assert len(receipt["inventory"]) == sum(1 for _ in source.iter())
    assert receipt["exclusions"] and all(
        entry["reason"] == "bibliographic-header" for entry in receipt["exclusions"]
    )
    assert row["question_answers"][0]["source_number"] == first_number
    assert "tei_id" not in row["question_answers"][0]
    assert len(receipt["question_anchors"]) == question_count
    assert row["question_answers"][0]["question_lines"][0]["text"] == source.xpath(
        "(//t:div[@type='question-answer']/t:div/t:ab[@type='question'])[1]/text()",
        namespaces={"t": TEI},
    )[0]
    question_text = row["question_answers"][0]["question_lines"][0]["text"]
    source_repetitions = sum(leaf.text == question_text for leaf in source.xpath("//t:ab[@type='question']", namespaces={"t": TEI}))
    assert row["text"].count(question_text) == source_repetitions
    assert "Project Gutenberg License" in row["text"]
    assert role in [
        node["attributes"].get("type")
        for node in _walk(row["structure"][0])
        if node["kind"] == "division"
    ]
    assert [entry["number"] for entry in row["question_answers"][0]["answer_lines"]] == [
        leaf.get("n")
        for leaf in source.xpath(
            "(//t:div[@type='question-answer'])[1]/t:div/t:ab[@type='answer']",
            namespaces={"t": TEI},
        )
    ]
    if slug == "baltimore-catechism-no-1":
        assert [item["source_number"] for item in row["question_answers"][:4]] == [
            "1.", "2.", "3.", "6."
        ]
    else:
        assert all(item["source_number"] is None for item in row["question_answers"])


def _walk(node: dict):
    yield node
    for child in node.get("content", []):
        if child.get("kind") != "text":
            yield from _walk(child)


def test_native_checker_rejects_qa_and_inventory_mutation() -> None:
    acceptance = next((ROOT / "library/works/baltimore-catechism-no-1").rglob("acceptance.json"))
    native = project_accepted_catechisms(ROOT, acceptance_path=acceptance)
    rows = copy.deepcopy(native["rows"])
    rows[0]["question_answers"][0]["answer_lines"][0]["text"] += " invented"
    errors = verify_accepted_catechisms(
        ROOT, acceptance_path=acceptance, rows=rows, receipt=native["receipt"]
    )
    assert any("rows differ" in error for error in errors)

    receipt = copy.deepcopy(native["receipt"])
    receipt["inventory"].pop()
    errors = verify_accepted_catechisms(
        ROOT, acceptance_path=acceptance, rows=native["rows"], receipt=receipt
    )
    assert any("receipt differs" in error for error in errors)

    missing = copy.deepcopy(native["rows"])
    del missing[0]["source_line_count"]
    with pytest.raises(PipelineError, match="invalid catechism public row"):
        _validate_rows(missing)

def test_duplicate_qa_tei_ids_are_rejected_before_public_projection() -> None:
    acceptance = next((ROOT / "library/works/baltimore-catechism-no-1").rglob("acceptance.json"))
    document = ET.parse(acceptance.with_name("master.tei.xml"))
    groups = document.findall(f".//{{{TEI}}}div[@type='question-answer']")
    groups[1].set("{http://www.w3.org/XML/1998/namespace}id", groups[0].get("{http://www.w3.org/XML/1998/namespace}id"))
    with pytest.raises(UnsupportedStructure, match="unique line grouping"):
        _native_question_answers_et(groups)
