"""Focused PIPE-014A tests with retained JSONL source oracles."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.reference_entries import (
    build_reference_entries_receipt,
    project_reference_entries,
    verify_reference_entries,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/library-pipeline/categories/reference-entries"
XSD = ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
BUILDER = ROOT / "plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-014A/04-rebuild-fixtures.py"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
CASES = {case["fixture_id"]: case for case in MANIFEST["fixtures"]}
_CROSS_REF = re.compile(r"See\s+\[\d+\]([A-Za-z][A-Za-z' -]*?)(?=[\.,;)]|$)", re.IGNORECASE)
pytestmark = pytest.mark.requires_local_artifacts


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _source_units(case: dict) -> list[dict]:
    source = ROOT / case["source_path"]
    units: list[dict] = []
    for order, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        definitions = [str(value) for value in record["definitions"]]
        units.append(
            {
                "id": f"line-{order:06d}",
                "source_order": order,
                "term": str(record["term"]),
                "definition_count": len(definitions),
                "definition_sha256": _sha_bytes(_canonical(definitions)),
                "definitions": definitions,
            }
        )
    return units


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _excerpt(case: dict) -> dict:
    return json.loads((FIXTURES / case["source_file"]).read_text(encoding="utf-8"))


def _context(case: dict) -> dict:
    excerpt = _excerpt(case)
    return {
        "identity": case["identity"],
        "language": "en",
        "representation_revision": "tei-v2",
        "edition_title": case["edition_title"],
        "entry_kind": case["entry_kind"],
        "source_url": case["source_url"],
        "source_sha256": case["source_sha256"],
        "retained_sha256": case["retained_sha256"],
        "source_path": ROOT / case["source_path"],
        "source_logical_path": case["source_path"],
        "source_selector": excerpt["selector"],
        "source_scope": excerpt["scope"],
        "source_unit_count": excerpt["native_unit_count"],
        "source_selected_units": excerpt["selected_unit_ids"],
        "source_census": excerpt["native_units"],
        "source_excerpt_sha256": excerpt["source_excerpt_sha256"],
    }


def _project(name: str, *, scope_id: str | None = None) -> tuple[dict, dict]:
    case = CASES[name]
    projection = project_reference_entries(FIXTURES / case["tei_file"], scope_id=scope_id, **_context(case))
    receipt = build_reference_entries_receipt(projection, identity=case["identity"])
    return projection, receipt


def _source_cross_references(definitions: list[str]) -> list[dict[str, str]]:
    return [{"raw": match.group(0), "target_term": match.group(1).strip()} for definition in definitions for match in _CROSS_REF.finditer(definition)]


def _assert_source_oracle(case: dict) -> None:
    source = ROOT / case["source_path"]
    excerpt = _excerpt(case)
    derived = _source_units(case)
    assert _sha(source) == case["retained_sha256"]
    assert excerpt["source_sha256"] == _sha(source)
    assert excerpt["native_unit_count"] == len(derived) == len(excerpt["native_units"])
    assert excerpt["native_units"] == [{key: unit[key] for key in ("id", "source_order", "term", "definition_count", "definition_sha256")} for unit in derived]
    selected_ids = [str(value) for value in excerpt["selected_unit_ids"]]
    selected = [unit for unit in derived if unit["id"] in set(selected_ids)]
    assert [unit["id"] for unit in selected] == selected_ids
    assert excerpt["selected_units"] == selected
    assert _sha_bytes(_canonical({"selected_units": excerpt["selected_units"], "selector": excerpt["selector"]})) == excerpt["source_excerpt_sha256"]


@pytest.mark.parametrize("name", CASES)
def test_source_native_reference_fixtures_and_complete_census(name: str) -> None:
    case = CASES[name]
    _assert_source_oracle(case)
    projection, receipt = _project(name)
    assert receipt["category"] == "reference_entries"
    assert receipt["master_sha256"] == _sha(FIXTURES / case["tei_file"])
    assert receipt["source_binding"]["source_path"] == case["source_path"]
    assert receipt["source_binding"]["retained_sha256"] == _sha(ROOT / case["source_path"])
    assert receipt["source_accounting"]["native_unit_count"] == case["source_unit_count"]
    assert receipt["source_accounting"]["selected_unit_ids"] == case["selected_source_units"]
    assert receipt["source_accounting"]["excluded_unit_count"] == case["source_unit_count"] - len(case["selected_source_units"])
    assert receipt["independent_check"] == {"status": "pending", "errors": []}
    assert verify_reference_entries(FIXTURES / case["tei_file"], projection["rows"], receipt, **_context(case)) == []


def test_source_accounting_rejects_reversed_native_selection() -> None:
    case = CASES["fixture-smiths-bible-dictionary"]
    context = _context(case)
    context["source_selected_units"] = list(reversed(context["source_selected_units"]))
    with pytest.raises(PipelineError, match="native census order"):
        project_reference_entries(FIXTURES / case["tei_file"], **context)
    projection, receipt = _project(case["fixture_id"])
    errors = verify_reference_entries(FIXTURES / case["tei_file"], projection["rows"], receipt, **context)
    assert any("native census order" in error for error in errors)


@pytest.mark.parametrize("name", CASES)
def test_checker_requires_receipt_even_when_rows_match(name: str) -> None:
    case = CASES[name]
    projection, receipt = _project(name)
    errors = verify_reference_entries(FIXTURES / case["tei_file"], projection["rows"], None, **_context(case))
    assert any("receipt is missing" in error for error in errors)
    errors = verify_reference_entries(FIXTURES / case["tei_file"], {"rows": projection["rows"]}, None, **_context(case))
    assert any("receipt is missing" in error for error in errors)
    assert verify_reference_entries(FIXTURES / case["tei_file"], {"rows": projection["rows"], "receipt": receipt}, None, **_context(case)) == []


def test_eastons_preserves_headword_definition_blocks_and_source_cross_reference() -> None:
    case = CASES["fixture-eastons-bible-dictionary"]
    projection, _ = _project(case["fixture_id"])
    source = {unit["term"]: unit for unit in _source_units(case)}
    for row in projection["rows"]:
        expected = source[row["headword"]]
        assert row["headword"] == expected["term"]
        assert row["definition_blocks"] == expected["definitions"]
        assert row["text"] == "\n\n".join(expected["definitions"])
        assert row["cross_references"] == _source_cross_references(expected["definitions"])
        assert "anchor" not in row["locator"]


def test_public_source_entry_id_is_source_order_and_rejects_private_xml_id_leakage() -> None:
    projection, receipt = _project("fixture-eastons-bible-dictionary")
    case = CASES["fixture-eastons-bible-dictionary"]
    assert [row["source_entry_id"] for row in projection["rows"]] == ["source-order-000001", "source-order-000002"]
    assert all(row["source_entry_id"] != anchor["xml_id"] for row, anchor in zip(projection["rows"], receipt["anchors"]))
    leaked = copy.deepcopy(projection["rows"])
    leaked[0]["source_entry_id"] = receipt["anchors"][0]["xml_id"]
    errors = verify_reference_entries(FIXTURES / case["tei_file"], leaked, receipt, **_context(case))
    assert any("rows do not match" in error or "invalid reference public row" in error for error in errors)


def test_smiths_keeps_multiple_source_cross_references_and_noncontiguous_source_order() -> None:
    case = CASES["fixture-smiths-bible-dictionary"]
    projection, _ = _project(case["fixture_id"])
    assert [row["headword"] for row in projection["rows"]] == ["A", "Aaron"]
    assert [row["source_order"] for row in projection["rows"]] == [1, 3]
    assert projection["rows"][0]["cross_references"] == [{"raw": "See [1]Alpha", "target_term": "Alpha"}]
    assert [ref["target_term"] for ref in projection["rows"][1]["cross_references"]] == ["Moses", "Hor", "Abiathar"]


def test_hitchcocks_preserves_single_definition_and_does_not_invent_alternate_terms() -> None:
    projection, _ = _project("fixture-hitchcocks-bible-names")
    assert [row["headword"] for row in projection["rows"]] == ["Aaron", "Abaddon"]
    assert all(len(row["definition_blocks"]) == 1 and row["alternate_terms"] is None for row in projection["rows"])
    assert all(row["cross_references"] == [] for row in projection["rows"])


def test_scope_accounts_for_tei_subset_while_source_census_stays_complete() -> None:
    projection, receipt = _project("fixture-smiths-bible-dictionary", scope_id="fixture-smiths-1863-line-000003")
    case = CASES["fixture-smiths-bible-dictionary"]
    assert len(projection["rows"]) == 1
    assert receipt["selection"] == {"available_units": 2, "selected_units": 1, "excluded_units": 1, "scope_id": "fixture-smiths-1863-line-000003"}
    assert receipt["source_accounting"]["native_unit_count"] == 4560
    assert receipt["source_accounting"]["selected_unit_ids"] == ["line-000001", "line-000003"]
    assert any(item["reason"] == "outside-scope" and item["headword"] == "A" for item in receipt["exclusions"])
    assert verify_reference_entries(FIXTURES / case["tei_file"], projection["rows"], receipt, scope_id="fixture-smiths-1863-line-000003", **_context(case)) == []


def test_checker_rejects_omission_duplication_reorder_text_and_definition_collapse() -> None:
    projection, receipt = _project("fixture-eastons-bible-dictionary")
    case = CASES["fixture-eastons-bible-dictionary"]
    for rows in (projection["rows"][:-1], projection["rows"] + [copy.deepcopy(projection["rows"][0])], list(reversed(projection["rows"]))):
        assert verify_reference_entries(FIXTURES / case["tei_file"], rows, receipt, **_context(case))
    drifted = copy.deepcopy(projection["rows"])
    drifted[0]["definition_blocks"][0] += " drift"
    assert any("rows do not match" in error for error in verify_reference_entries(FIXTURES / case["tei_file"], drifted, receipt, **_context(case)))
    collapsed = copy.deepcopy(projection["rows"])
    collapsed[1]["definition_blocks"] = [" ".join(collapsed[1]["definition_blocks"])]
    assert verify_reference_entries(FIXTURES / case["tei_file"], collapsed, receipt, **_context(case))
    ref_collapsed = copy.deepcopy(projection["rows"])
    ref_collapsed[1]["cross_references"] = []
    assert verify_reference_entries(FIXTURES / case["tei_file"], ref_collapsed, receipt, **_context(case))


def test_independent_checker_rejects_duplicate_source_order_with_forged_master(tmp_path: Path) -> None:
    case = CASES["fixture-eastons-bible-dictionary"]
    tree = etree.parse(str(FIXTURES / case["tei_file"]))
    second = tree.xpath("//t:div[@type='dictionary-entry'][2]", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    second.set("n", "1")
    path = tmp_path / "duplicate-source-order.tei.xml"
    path.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
    projection, receipt = _project(case["fixture_id"])
    forged_receipt = copy.deepcopy(receipt)
    forged_receipt["master_sha256"] = _sha(path)
    errors = verify_reference_entries(path, projection["rows"], forged_receipt, **_context(case))
    assert any("checker: duplicate reference source order" in error for error in errors)


def test_independent_checker_rejects_nested_inline_structure_with_forged_master(tmp_path: Path) -> None:
    case = CASES["fixture-eastons-bible-dictionary"]
    tree = etree.parse(str(FIXTURES / case["tei_file"]))
    definition = tree.xpath("//t:div[@type='dictionary-entry'][1]/t:p[1]", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    forged = etree.SubElement(definition, "{http://www.tei-c.org/ns/1.0}div", type="unaccounted")
    forged.text = "forged nested visible text"
    path = tmp_path / "nested-inline.tei.xml"
    path.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
    projection, receipt = _project(case["fixture_id"])
    forged_receipt = copy.deepcopy(receipt)
    forged_receipt["master_sha256"] = _sha(path)
    errors = verify_reference_entries(path, projection["rows"], forged_receipt, **_context(case))
    assert any("checker: reference inline div" in error for error in errors)


def test_checker_rejects_public_anchor_and_forged_receipt_fields() -> None:
    projection, receipt = _project("fixture-eastons-bible-dictionary")
    case = CASES["fixture-eastons-bible-dictionary"]
    private = copy.deepcopy(projection["rows"])
    private[0]["locator"]["anchor"] = "fixture-eastons-1897-line-000001"
    errors = verify_reference_entries(FIXTURES / case["tei_file"], private, receipt, **_context(case))
    assert any("invalid reference public row" in error or "rows do not match" in error for error in errors)
    forged = copy.deepcopy(receipt)
    forged["master_sha256"] = "0" * 64
    forged["source_accounting"]["census"] = []
    forged["independent_check"] = {"status": "passed", "errors": []}
    errors = verify_reference_entries(FIXTURES / case["tei_file"], projection["rows"], forged, **_context(case))
    assert any("master_sha256" in error for error in errors)
    assert any("source_accounting" in error for error in errors)
    assert any("independent_check" in error for error in errors)


def test_checker_rejects_retained_source_path_mutation(tmp_path: Path) -> None:
    case = CASES["fixture-eastons-bible-dictionary"]
    source = ROOT / case["source_path"]
    altered = tmp_path / source.name
    altered.write_bytes(source.read_bytes() + b"\nforged")
    context = _context(case)
    context["source_path"] = altered
    context["source_logical_path"] = case["source_path"]
    with pytest.raises(PipelineError, match="retained source hash"):
        project_reference_entries(FIXTURES / case["tei_file"], **context)
    projection, receipt = _project(case["fixture_id"])
    assert verify_reference_entries(FIXTURES / case["tei_file"], projection["rows"], receipt, **context)


@pytest.mark.parametrize("change", ["table", "attribute", "namespace", "doctype", "comment", "outside-pi"])
def test_unsupported_or_unbound_source_fails_both_routes(change: str, tmp_path: Path) -> None:
    case = CASES["fixture-eastons-bible-dictionary"]
    tree = etree.parse(str(FIXTURES / case["tei_file"]))
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
    else:
        raw = b"<?outside instruction?>\n" + etree.tostring(tree, encoding="utf-8")
    if change not in {"doctype", "comment", "outside-pi"}:
        raw = etree.tostring(tree, encoding="utf-8")
    path = tmp_path / "unsupported.tei.xml"
    path.write_bytes(raw)
    with pytest.raises(PipelineError, match="unsupported-visible"):
        project_reference_entries(path, **_context(case))
    projection, receipt = _project(case["fixture_id"])
    assert verify_reference_entries(path, projection["rows"], receipt, **_context(case))


@pytest.mark.parametrize("name", CASES)
def test_fixture_is_valid_full_tei_p5(name: str) -> None:
    document = etree.parse(str(FIXTURES / CASES[name]["tei_file"]))
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    assert schema.validate(document), schema.error_log.last_error


def test_source_to_fixture_builder_matches_actual_fixture_bytes_and_is_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    subprocess.run([sys.executable, str(BUILDER), "--output", str(first)], check=True)
    subprocess.run([sys.executable, str(BUILDER), "--output", str(second)], check=True)
    actual_files = sorted(path.relative_to(FIXTURES) for path in FIXTURES.rglob("*") if path.is_file())
    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert first_files == actual_files == second_files
    assert all((first / relative).read_bytes() == (FIXTURES / relative).read_bytes() == (second / relative).read_bytes() for relative in actual_files)
