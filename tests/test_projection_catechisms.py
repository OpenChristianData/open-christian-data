"""Focused PIPE-013A tests for source-native catechism projection.

The TEI fixtures are checked against the retained source files at test time.
The expected questions and answers therefore do not come from duplicated
constants in this test module or from the producer's own output.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree, html

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.catechisms import (
    build_catechism_receipt,
    project_catechism_document,
    verify_catechism,
)
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/library-pipeline/categories/catechisms"
XSD = ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
BUILDER = ROOT / "plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-013A/04-rebuild-fixtures.py"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
CASES = {case["fixture_id"]: case for case in MANIFEST["fixtures"]}
pytestmark = pytest.mark.requires_local_artifacts


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _text(node: object) -> str:
    return " ".join("".join(node.itertext()).split())  # type: ignore[union-attr]


def _westminster_source(path: Path) -> list[dict]:
    document = html.fromstring(path.read_bytes().decode("utf-8"))
    containers = document.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' entry-content ')]")
    assert len(containers) == 1
    result: list[dict] = []
    for node in containers[0].xpath(".//p"):
        value = _text(node)
        match = re.match(r"^Q\.\s*([0-9]+)\.\s*(.*?)\s+A\.\s*(.*)$", value)
        if not match:
            continue
        proof_node = node.getnext()
        proof_text = _text(proof_node) if proof_node is not None and proof_node.tag == "p" else ""
        proofs = [part.strip() for part in proof_text.split(";") if part.strip() and not part.startswith("Q.")]
        result.append({"id": match.group(1), "question": match.group(2), "answer": match.group(3), "proofs": proofs})
    return result


def _matthew_source(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    result: list[dict] = []
    for index, item in enumerate(document["Data"]):
        result.append(
            {
                "id": str(item["Number"]),
                "question": item["Question"],
                "answer": item["Answer"],
                "subquestions": [
                    {"id": str(sub["Number"]), "question": sub["Question"], "answer": sub["Answer"]}
                    for sub in item.get("SubQuestions") or []
                ],
                "selector": f"Data[{index}]",
            }
        )
    return result


def _luther_source(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    result: list[dict] = []
    for order, index in enumerate((i for i, line in enumerate(lines) if line.strip() == "What does this mean?"), 1):
        cursor = index + 1
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        answer: list[str] = []
        while cursor < len(lines) and lines[cursor].strip():
            answer.append(lines[cursor].strip())
            cursor += 1
        result.append({"id": str(order), "question": "What does this mean?", "answer": " ".join(answer), "line": index + 1})
    return result


def _source_units(case: dict) -> list[dict]:
    path = ROOT / case["source_path"]
    if case["fixture_id"] == "westminster-shorter":
        return _westminster_source(path)
    if case["fixture_id"] == "matthew-henry":
        return _matthew_source(path)
    return _luther_source(path)


def _source_excerpt(case: dict) -> dict:
    return json.loads((FIXTURES / case["source_file"]).read_text(encoding="utf-8"))


def _context(case: dict) -> dict:
    excerpt = _source_excerpt(case)
    return {
        "identity": case["identity"],
        "language": "en",
        "representation_revision": "tei-v2",
        "edition_title": case["edition_title"],
        "source_url": case["source_url"],
        "source_sha256": case["source_sha256"],
        "retained_sha256": case["retained_sha256"],
        "source_path": ROOT / case["source_path"],
        "source_selector": excerpt["selector"],
        "source_scope": excerpt["scope"],
        "source_unit_count": excerpt["native_unit_count"],
        "source_selected_units": excerpt["selected_unit_ids"],
        "source_selected_subunits": excerpt.get("selected_subunit_ids"),
        "source_census": excerpt["native_units"],
        "source_excerpt_sha256": excerpt["source_excerpt_sha256"],
    }


def _project(name: str, *, scope_id: str | None = None) -> tuple[dict, dict]:
    case = CASES[name]
    projection = project_catechism_document(FIXTURES / case["tei_file"], scope_id=scope_id, **_context(case))
    receipt = build_catechism_receipt(projection, identity=case["identity"])
    return projection, receipt


def _assert_source_binding_and_oracle(case: dict) -> None:
    source_path = ROOT / case["source_path"]
    excerpt = _source_excerpt(case)
    derived = _source_units(case)
    assert _sha(source_path) == case["retained_sha256"]
    assert excerpt["source_sha256"] == _sha(source_path)
    assert excerpt["native_unit_count"] == len(derived) == len(excerpt["native_units"])
    assert [item["id"] for item in derived] == [item["id"] for item in excerpt["native_units"]]
    selected_ids = {str(value) for value in excerpt["selected_unit_ids"]}
    selected = [item for item in derived if item["id"] in selected_ids]
    assert selected
    assert [item["id"] for item in selected] == [str(value) for value in excerpt["selected_unit_ids"]]
    for expected, recorded in zip(selected, excerpt["selected_units"]):
        assert expected["id"] == str(recorded["id"])
        assert expected["question"] == recorded["question"]
        assert expected["answer"] == recorded["answer"]
        if case["fixture_id"] == "westminster-shorter":
            assert expected["proofs"] == recorded["proofs"]
        if case["fixture_id"] == "matthew-henry":
            selected_sub_ids = {str(value) for value in excerpt["selected_subunit_ids"]}
            assert [sub["id"] for sub in recorded["subquestions"]] == list(excerpt["selected_subunit_ids"])
            assert [sub["id"] for sub in expected["subquestions"] if sub["id"] in selected_sub_ids] == list(excerpt["selected_subunit_ids"])
    selected_payload = {"selected_units": excerpt["selected_units"], "selector": excerpt["selector"]}
    assert hashlib.sha256(_canonical(selected_payload)).hexdigest() == excerpt["source_excerpt_sha256"]


@pytest.mark.parametrize("name", CASES)
def test_real_source_native_fixtures_use_retained_source_oracle_and_full_census(name: str) -> None:
    case = CASES[name]
    _assert_source_binding_and_oracle(case)
    projection, receipt = _project(name)
    assert len(projection["rows"]) == case["rows"]
    assert receipt["category"] == "catechisms"
    assert receipt["master_sha256"] == _sha(FIXTURES / case["tei_file"])
    assert receipt["source_binding"]["source_path"] == case["source_path"]
    assert receipt["source_binding"]["retained_sha256"] == _sha(ROOT / case["source_path"])
    assert receipt["source_accounting"]["native_unit_count"] == case["source_unit_count"]
    assert receipt["source_accounting"]["selected_unit_ids"] == case["selected_source_units"]
    assert receipt["source_accounting"]["excluded_unit_count"] == case["source_unit_count"] - len(case["selected_source_units"])
    assert receipt["selection"] == {"available_units": case["rows"], "selected_units": case["rows"], "excluded_units": 0, "scope_id": None}
    assert receipt["independent_check"] == {"status": "pending", "errors": []}
    assert verify_catechism(FIXTURES / case["tei_file"], projection["rows"], receipt, **_context(case)) == []


def test_source_accounting_rejects_reversed_native_selection_and_subunits() -> None:
    case = CASES["westminster-shorter"]
    context = _context(case)
    context["source_selected_units"] = list(reversed(context["source_selected_units"]))
    with pytest.raises(PipelineError, match="native census order"):
        project_catechism_document(FIXTURES / case["tei_file"], **context)
    projection, receipt = _project(case["fixture_id"])
    errors = verify_catechism(FIXTURES / case["tei_file"], projection["rows"], receipt, **context)
    assert any("native census order" in error for error in errors)

    case = CASES["matthew-henry"]
    context = _context(case)
    context["source_selected_subunits"] = list(reversed(context["source_selected_subunits"]))
    with pytest.raises(PipelineError, match="native order"):
        project_catechism_document(FIXTURES / case["tei_file"], **context)
    projection, receipt = _project(case["fixture_id"])
    errors = verify_catechism(FIXTURES / case["tei_file"], projection["rows"], receipt, **context)
    assert any("subquestion selection does not follow native order" in error for error in errors)


@pytest.mark.parametrize("name", CASES)
def test_checker_requires_receipt_even_when_rows_match(name: str) -> None:
    case = CASES[name]
    projection, receipt = _project(name)
    errors = verify_catechism(FIXTURES / case["tei_file"], projection["rows"], None, **_context(case))
    assert any("receipt is missing" in error for error in errors)
    errors = verify_catechism(FIXTURES / case["tei_file"], {"rows": projection["rows"]}, None, **_context(case))
    assert any("receipt is missing" in error for error in errors)
    assert verify_catechism(FIXTURES / case["tei_file"], {"rows": projection["rows"], "receipt": receipt}, None, **_context(case)) == []


def test_projected_text_and_proofs_are_derived_from_westminster_source() -> None:
    case = CASES["westminster-shorter"]
    projection, _ = _project("westminster-shorter")
    source = _source_units(case)
    for row, expected in zip(projection["rows"], source[:2]):
        assert row["item_id"] == expected["id"]
        assert row["question"] == expected["question"]
        assert row["answer"] == expected["answer"]
        assert [ref["raw"] for proof in row["proofs"] for ref in proof["references"]] == expected["proofs"]
    assert projection["rows"][0]["locator"]["divisions"] == []
    assert projection["rows"][0]["group"] is None


def test_omitted_note_tail_is_emitted_once_for_source_derived_answer(tmp_path: Path) -> None:
    case = CASES["westminster-shorter"]
    source_answer = _source_units(case)[0]["answer"]
    prefix, suffix = source_answer.rsplit(" ", 1)
    tree = etree.parse(str(FIXTURES / case["tei_file"]))
    answer = tree.xpath("//t:ab[@type='answer']", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    answer.text = prefix
    note = etree.SubElement(answer, "{http://www.tei-c.org/ns/1.0}note")
    note.text = "source-derived regression note"
    note.tail = " " + suffix
    path = tmp_path / "note-tail.tei.xml"
    path.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))

    projection = project_catechism_document(path, **_context(case))
    row = projection["rows"][0]
    assert row["answer"] == source_answer
    assert row["answer"].count(suffix) == 1
    assert [warning["reason"] for warning in projection["warnings"]].count("note-extracted") == 1
    receipt = build_catechism_receipt(projection, identity=case["identity"])
    assert verify_catechism(path, projection["rows"], receipt, **_context(case)) == []


def test_matthew_henry_preserves_source_nested_subquestions_without_fabricated_proofs() -> None:
    case = CASES["matthew-henry"]
    projection, _ = _project("matthew-henry")
    source = _source_units(case)[0]
    row = projection["rows"][0]
    assert row["question"] == source["question"]
    assert row["answer"] == source["answer"]
    assert [item["item_id"] for item in row["sub_questions"]] == case["selected_source_subunits"]
    for got, expected in zip(row["sub_questions"], source["subquestions"], strict=True):
        assert got["question"] == expected["question"]
        assert got["answer"] == expected["answer"]
        assert got["proofs"] == []
    assert row["proofs"] == []
    assert len(row["sub_questions"]) == 30
    assert projection["warnings"] == []


def test_luther_preserves_source_text_and_real_group_locators() -> None:
    case = CASES["luther-small"]
    projection, _ = _project("luther-small")
    source = _source_units(case)[:2]
    for row, expected in zip(projection["rows"], source):
        assert row["question"] == expected["question"]
        assert row["answer"] == expected["answer"]
        assert row["item_id"] is None
        assert row["locator"]["question"] is None
        assert row["locator"]["divisions"][-1]["number"] is None
    row = projection["rows"][1]
    assert row["group"] == "The Second Commandment"
    assert [item["type"] for item in row["locator"]["divisions"]] == ["part", "chapter"]
    assert row["locator"]["source_order"] == 2
    assert "anchor" not in row["locator"]


def test_scope_selection_accounts_for_tei_subset_while_retained_source_accounting_stays_complete() -> None:
    projection, receipt = _project("westminster-shorter", scope_id="wsc-q-1")
    assert len(projection["rows"]) == 1
    assert receipt["selection"] == {"available_units": 2, "selected_units": 1, "excluded_units": 1, "scope_id": "wsc-q-1"}
    assert receipt["source_accounting"]["native_unit_count"] == 107
    assert receipt["source_accounting"]["selected_unit_ids"] == ["1", "2"]
    assert any(item["reason"] == "outside-scope" and item["item_id"] == "2" for item in receipt["exclusions"])
    case = CASES["westminster-shorter"]
    assert verify_catechism(FIXTURES / case["tei_file"], projection["rows"], receipt, scope_id="wsc-q-1", **_context(case)) == []


def test_checker_rejects_omission_duplication_reorder_text_and_nested_flattening() -> None:
    projection, receipt = _project("westminster-shorter")
    case = CASES["westminster-shorter"]
    mutations = [projection["rows"][:-1], projection["rows"] + [copy.deepcopy(projection["rows"][0])], list(reversed(projection["rows"]))]
    for rows in mutations:
        assert verify_catechism(FIXTURES / case["tei_file"], rows, receipt, **_context(case))
    drifted = copy.deepcopy(projection["rows"])
    drifted[0]["answer"] += " drift"
    errors = verify_catechism(FIXTURES / case["tei_file"], drifted, receipt, **_context(case))
    assert any("rows do not match" in error for error in errors)
    nested_projection, nested_receipt = _project("matthew-henry")
    flattened = copy.deepcopy(nested_projection["rows"])
    flattened[0]["sub_questions"] = None
    assert verify_catechism(FIXTURES / CASES["matthew-henry"]["tei_file"], flattened, nested_receipt, **_context(CASES["matthew-henry"]))


def test_checker_rejects_bad_locator_extra_row_field_and_forged_receipt_fields() -> None:
    projection, receipt = _project("westminster-shorter")
    case = CASES["westminster-shorter"]
    bad_locator = copy.deepcopy(projection["rows"])
    bad_locator[0]["locator"]["source_order"] = 99
    assert verify_catechism(FIXTURES / case["tei_file"], bad_locator, receipt, **_context(case))
    private = copy.deepcopy(projection["rows"])
    private[0]["unexpected"] = "not in closed schema"
    assert verify_catechism(FIXTURES / case["tei_file"], private, receipt, **_context(case))
    forged = copy.deepcopy(receipt)
    forged["master_sha256"] = "0" * 64
    forged["source_accounting"]["census"] = []
    forged["independent_check"] = {"status": "passed", "errors": []}
    errors = verify_catechism(FIXTURES / case["tei_file"], projection["rows"], forged, **_context(case))
    assert any("master_sha256" in error for error in errors)
    assert any("source_accounting" in error for error in errors)
    assert any("independent_check" in error for error in errors)
    assert receipt["anchors"][0]["xml_id"] == "wsc-q-1"
    assert "anchor" not in projection["rows"][0]["locator"]


def test_checker_rejects_source_path_mutation_even_when_tei_receipt_is_consistent(tmp_path: Path) -> None:
    case = CASES["westminster-shorter"]
    source = ROOT / case["source_path"]
    altered = tmp_path / source.name
    altered.write_bytes(source.read_bytes() + b"\nforged")
    context = _context(case)
    context["source_path"] = altered
    context["source_logical_path"] = case["source_path"]
    with pytest.raises(PipelineError, match="retained source hash"):
        project_catechism_document(FIXTURES / case["tei_file"], **context)
    projection, receipt = _project("westminster-shorter")
    assert verify_catechism(FIXTURES / case["tei_file"], projection["rows"], receipt, **context)


@pytest.mark.parametrize("change", ["table", "attribute", "namespace", "doctype", "comment", "outside-pi"])
def test_unsupported_or_unbound_source_fails_both_routes(change: str, tmp_path: Path) -> None:
    case = CASES["westminster-shorter"]
    source_path = FIXTURES / case["tei_file"]
    tree = etree.parse(str(source_path))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    body = tree.xpath("/t:TEI/t:text/t:body", namespaces=ns)[0]
    if change == "table":
        etree.SubElement(body, "{http://www.tei-c.org/ns/1.0}table")
    elif change == "attribute":
        body.set("ana", "invented")
    elif change == "namespace":
        body.tag = "{urn:wrong}body"
    elif change == "doctype":
        raw = b'<!DOCTYPE TEI [<!ENTITY x "danger">]>' + etree.tostring(tree, encoding="utf-8")
    elif change == "comment":
        raw = etree.tostring(tree, encoding="utf-8").replace(b"<text", b"<!-- forged --><text", 1)
    elif change == "outside-pi":
        raw = b"<?outside instruction?>\n" + etree.tostring(tree, encoding="utf-8")
    if change not in {"doctype", "comment", "outside-pi"}:
        raw = etree.tostring(tree, encoding="utf-8")
    path = tmp_path / "unsupported.tei.xml"
    path.write_bytes(raw)
    with pytest.raises(PipelineError, match="unsupported-visible"):
        project_catechism_document(path, **_context(case))
    projection, receipt = _project("westminster-shorter")
    assert verify_catechism(path, projection["rows"], receipt, **_context(case))


@pytest.mark.parametrize("name", CASES)
def test_fixture_is_valid_tei_p5(name: str) -> None:
    document = etree.parse(str(FIXTURES / CASES[name]["tei_file"]))
    schema = compiled_tei_schema(XSD)
    assert schema.validate(document), schema.error_log.last_error


def test_source_to_fixture_builder_is_byte_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    subprocess.run([sys.executable, str(BUILDER), "--output", str(first)], check=True)
    subprocess.run([sys.executable, str(BUILDER), "--output", str(second)], check=True)
    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert first_files == second_files
    assert all((first / relative).read_bytes() == (second / relative).read_bytes() for relative in first_files)

    assert first_files == sorted(path.relative_to(FIXTURES) for path in FIXTURES.rglob("*") if path.is_file())
    assert all((first / relative).read_bytes() == (FIXTURES / relative).read_bytes() for relative in first_files)
