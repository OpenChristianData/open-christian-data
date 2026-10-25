"""Focused PIPE-013B tests with retained-source oracles and independent checks."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import doctrinal_documents
from ocd_kernel.projection.categories.doctrinal_documents import (
    build_doctrinal_receipt,
    project_doctrinal_document,
    verify_doctrinal_document,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/library-pipeline/categories/doctrinal-documents"
XSD = ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
BUILDER = ROOT / "plans/2026-08-31-library-pipeline-redesign/artifacts/PIPE-013B/04-rebuild-fixtures.py"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
CASES = {case["fixture_id"]: case for case in MANIFEST["fixtures"]}
pytestmark = pytest.mark.requires_local_artifacts

HELVETIC_PROMOTED = Path(
    "D:/Library/Open Christian Data/candidate-reviews/completion-20261023/"
    "helvetic-publication-ready/helvetic-promoted-v3"
)
HELVETIC_ACCEPTANCE = Path(
    "library/works/helvetic-consensus/forms/helvetic-consensus-hodge-english/"
    "editions/helvetic-consensus-hodge-1879/acceptance.json"
)


def test_helvetic_promoted_member_set_preserves_all_scans_and_rejects_tampering(tmp_path: Path) -> None:
    if not (HELVETIC_PROMOTED / "official-promotion-receipt.json").is_file():
        pytest.skip("pinned Helvetic promoted stage is not mounted")
    accepted = HELVETIC_PROMOTED / HELVETIC_ACCEPTANCE
    projection = doctrinal_documents.project_accepted_doctrinal_documents(
        HELVETIC_PROMOTED, acceptance_path=accepted
    )
    assert [row["unit_type"] for row in projection["rows"]] == ["unit", *(["canon"] * 26)]
    assert [row["number"] for row in projection["rows"][1:]] == [str(n) for n in range(1, 27)]
    assert len(projection["authority"]["retained_members"]) == 10
    assert projection["source_binding"]["retained_sha256"] == _sha(
        HELVETIC_PROMOTED / HELVETIC_ACCEPTANCE.parent / "source-member-set.json"
    )
    assert doctrinal_documents.verify_accepted_doctrinal_documents(
        HELVETIC_PROMOTED, acceptance_path=accepted,
        rows=projection["rows"], receipt=projection["receipt"],
    ) == []

    wrong_label = tmp_path / "wrong-source-location.xml"
    tree = ET.parse(accepted.with_name("master.tei.xml"))
    source_location = next(
        node for node in tree.iter()
        if node.tag.endswith("note") and node.get("type") == "source-location"
    )
    source_location.text = "library/works/other/source-member-set.json"
    tree.write(wrong_label, encoding="utf-8")
    identity = json.loads(accepted.read_text(encoding="utf-8"))["identity"]
    context = {
        "identity": {key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
        "edition_title": "Hodge 1879 appendix",
        "document_kind": "confession",
        "source_url": projection["source_binding"]["source_url"],
        "source_sha256": projection["source_binding"]["source_sha256"],
        "retained_sha256": projection["source_binding"]["retained_sha256"],
        "source_logical_path": projection["source_binding"]["source_path"],
    }
    with pytest.raises(PipelineError, match="doctrinal TEI source path mismatch"):
        project_doctrinal_document(wrong_label, **context)
    assert any(
        "checker: source path mismatch" in error
        for error in verify_doctrinal_document(wrong_label, projection["rows"], projection["receipt"], **context)
    )

    forged = copy.deepcopy(projection["receipt"])
    forged["authority"]["retained_members"].pop()
    assert "accepted authority bindings differ" in doctrinal_documents.verify_accepted_doctrinal_documents(
        HELVETIC_PROMOTED, acceptance_path=accepted,
        rows=projection["rows"], receipt=forged,
    )

    copied = tmp_path / "helvetic"
    shutil.copytree(HELVETIC_PROMOTED, copied)
    scan = copied / "raw/internet-archive/helvetic-consensus-hodge-1879/appendix/scan-663-leaf-667.jpg"
    original = scan.read_bytes()
    scan.unlink()
    with pytest.raises(PipelineError, match="missing retained file"):
        doctrinal_documents.project_accepted_doctrinal_documents(
            copied, acceptance_path=copied / HELVETIC_ACCEPTANCE
        )
    scan.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(PipelineError, match="retained file sha256 mismatch"):
        doctrinal_documents.project_accepted_doctrinal_documents(
            copied, acceptance_path=copied / HELVETIC_ACCEPTANCE
        )


@pytest.mark.parametrize(
    ("scope_id", "expected_roots", "expected_members"),
    [
        (None, ["parent", "last"], [["first", "second"], ["last"]]),
        ("parent", ["parent"], [["first", "second"]]),
        ("nested", ["nested"], [["second"]]),
        ("first", ["first"], [["first"]]),
        ("second", ["second"], [["second"]]),
        ("excluded", [], []),
    ],
)
def test_doctrinal_hierarchy_selection_preserves_scoped_leaf_coverage(
    scope_id: str | None, expected_roots: list[str],
    expected_members: list[list[str]],
) -> None:
    body = ET.fromstring('''<body xmlns="http://www.tei-c.org/ns/1.0">
      <div type="chapter" xml:id="parent"><head>Chapter</head>
        <p>Before the first section.</p>
        <div type="section" xml:id="first"><p>First.</p></div>
        <div type="section" xml:id="nested"><p>Before the article.</p>
          <div type="article" xml:id="second"><p>Second.</p></div>
          <p>After the article.</p>
        </div>
        <p>After both sections.</p>
      </div>
      <div type="chapter"><head>Heading-only parent</head>
        <div type="section" xml:id="last"><p>Last.</p></div>
      </div>
      <div type="title-page" xml:id="excluded">
        <div type="section" xml:id="paratext"><p>Not normative.</p></div>
      </div>
    </body>''')
    parents = {child: parent for parent in body.iter() for child in parent}
    scope = doctrinal_documents._scope([body], scope_id)
    roots, members = doctrinal_documents._hierarchy_selection([body], scope, parents)
    assert [node.get(doctrinal_documents.XML_ID) for node in roots] == expected_roots
    assert [[node.get(doctrinal_documents.XML_ID) for node in members[root]]
            for root in roots] == expected_members
    # Selecting a child must not import its parent's surrounding prose.
    if scope_id in {"first", "second"}:
        assert "Before" not in "".join(roots[0].itertext())
        assert "After" not in "".join(roots[0].itertext())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _source_units(case: dict) -> list[dict]:
    source = ROOT / case["source_path"]
    document = json.loads(source.read_text(encoding="utf-8"))
    if case["shape"] in {"wcf", "dort"}:
        units: list[dict] = []
        for chapter in document["Data"]:
            for section in chapter["Sections"]:
                units.append(
                    {
                        "id": f"{chapter['Chapter']}.{section['Section']}",
                        "chapter": str(chapter["Chapter"]),
                        "chapter_title": chapter["Title"],
                        "section": str(section["Section"]),
                        "content": section["Content"],
                        "content_with_proofs": section.get("ContentWithProofs") if case["shape"] == "wcf" else None,
                        "proofs": [
                            {"id": int(proof["Id"]), "references": [str(reference) for reference in proof["References"]]}
                            for proof in section.get("Proofs", [])
                        ] if case["shape"] == "wcf" else [],
                    }
                )
        return units
    return [
        {
            "id": f"paragraph-{index:06d}",
            "source_ordinal": index,
            "number": None,
            "content": paragraph,
            "content_with_proofs": None,
            "proofs": [],
        }
        for index, paragraph in enumerate(document["Data"]["Content"].split("\n\n"), 1)
        if paragraph.strip()
    ]


def _excerpt(case: dict) -> dict:
    return json.loads((FIXTURES / case["source_file"]).read_text(encoding="utf-8"))


def _context(case: dict) -> dict:
    excerpt = _excerpt(case)
    return {
        "identity": case["identity"],
        "language": "en",
        "representation_revision": "tei-v2",
        "edition_title": case["edition_title"],
        "document_kind": case["document_kind"],
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
    projection = project_doctrinal_document(FIXTURES / case["tei_file"], scope_id=scope_id, **_context(case))
    receipt = build_doctrinal_receipt(projection, identity=case["identity"])
    return projection, receipt


def _assert_source_oracle(case: dict) -> None:
    source = ROOT / case["source_path"]
    excerpt = _excerpt(case)
    derived = _source_units(case)
    assert _sha(source) == case["retained_sha256"]
    assert excerpt["source_sha256"] == _sha(source)
    assert excerpt["native_unit_count"] == len(derived) == len(excerpt["native_units"])
    assert [unit["id"] for unit in derived] == [str(unit["id"]) for unit in excerpt["native_units"]]
    selected_ids = [str(value) for value in excerpt["selected_unit_ids"]]
    selected = [unit for unit in derived if unit["id"] in set(selected_ids)]
    assert [unit["id"] for unit in selected] == selected_ids
    for expected, recorded in zip(selected, excerpt["selected_units"]):
        assert expected == recorded
    payload = {"selected_units": excerpt["selected_units"], "selector": excerpt["selector"]}
    assert _sha_bytes(_canonical(payload)) == excerpt["source_excerpt_sha256"]


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.mark.parametrize("name", CASES)
def test_source_native_fixture_and_accounting(name: str) -> None:
    case = CASES[name]
    _assert_source_oracle(case)
    projection, receipt = _project(name)
    assert receipt["category"] == "doctrinal_documents"
    assert receipt["master_sha256"] == _sha(FIXTURES / case["tei_file"])
    assert receipt["source_binding"]["source_path"] == case["source_path"]
    assert receipt["source_binding"]["retained_sha256"] == _sha(ROOT / case["source_path"])
    assert receipt["source_accounting"]["native_unit_count"] == case["source_unit_count"]
    assert receipt["source_accounting"]["selected_unit_ids"] == case["selected_source_units"]
    assert receipt["source_accounting"]["excluded_unit_count"] == case["source_unit_count"] - len(case["selected_source_units"])
    assert receipt["independent_check"] == {"status": "pending", "errors": []}
    assert verify_doctrinal_document(FIXTURES / case["tei_file"], projection["rows"], receipt, **_context(case)) == []


def test_source_accounting_rejects_reversed_native_selection() -> None:
    case = CASES["fixture-westminster-confession"]
    context = _context(case)
    context["source_selected_units"] = list(reversed(context["source_selected_units"]))
    with pytest.raises(PipelineError, match="native census order"):
        project_doctrinal_document(FIXTURES / case["tei_file"], **context)
    projection, receipt = _project(case["fixture_id"])
    errors = verify_doctrinal_document(FIXTURES / case["tei_file"], projection["rows"], receipt, **context)
    assert any("native census order" in error for error in errors)


@pytest.mark.parametrize("name", CASES)
def test_checker_requires_receipt_even_when_rows_match(name: str) -> None:
    case = CASES[name]
    projection, receipt = _project(name)
    errors = verify_doctrinal_document(FIXTURES / case["tei_file"], projection["rows"], None, **_context(case))
    assert any("receipt is missing" in error for error in errors)
    errors = verify_doctrinal_document(FIXTURES / case["tei_file"], {"rows": projection["rows"]}, None, **_context(case))
    assert any("receipt is missing" in error for error in errors)
    assert verify_doctrinal_document(FIXTURES / case["tei_file"], {"rows": projection["rows"], "receipt": receipt}, None, **_context(case)) == []


def test_westminster_preserves_normative_content_proofs_and_readable_locator() -> None:
    projection, receipt = _project("fixture-westminster-confession")
    case = CASES["fixture-westminster-confession"]
    source = _source_units(case)
    document = etree.parse(str(FIXTURES / case["tei_file"]))
    carriers = document.xpath("//t:div[@type='section']/t:p/t:seg[@type='content-with-proofs']", namespaces={"t": "http://www.tei-c.org/ns/1.0"})
    assert len(carriers) == 2
    for row, expected, carrier in zip(projection["rows"], source[:2], carriers):
        assert row["number"] == expected["section"]
        assert row["content"] == expected["content"]
        assert row["content_blocks"] == [expected["content"]]
        assert row["content_with_proofs"] == expected["content_with_proofs"]
        assert row["content_with_proofs"] != row["content"]
        assert "[1]" in row["content_with_proofs"]
        assert " ".join("".join(carrier.itertext()).split()) == expected["content_with_proofs"]
        assert [seg.text for seg in carrier.xpath(".//t:seg[@type='source-proof-marker']", namespaces={"t": "http://www.tei-c.org/ns/1.0"})] == re.findall(r"\[\d+\]", expected["content_with_proofs"])
        assert [proof["id"] for proof in row["proofs"]] == [proof["id"] for proof in expected["proofs"]]
        assert [ref["osis"][0] for proof in row["proofs"] for ref in proof["references"]] == [ref for proof in expected["proofs"] for ref in proof["references"]]
        assert row["locator"]["divisions"][0]["type"] == "chapter"
        assert row["locator"]["divisions"][0]["titles"] == [expected["chapter_title"]]
        assert "anchor" not in row["locator"]
    assert receipt["anchors"][0]["xml_id"] == "fixture-wcf-1647-unit-1-1"


def test_canons_preserve_alpha_section_numbers_without_fabricated_proofs() -> None:
    projection, _ = _project("fixture-canons-of-dort")
    source = _source_units(CASES["fixture-canons-of-dort"])
    assert [row["number"] for row in projection["rows"]] == ["A1", "A2"]
    assert [row["content"] for row in projection["rows"]] == [unit["content"] for unit in source[:2]]
    assert all(row["proofs"] == [] for row in projection["rows"])
    assert all(row["locator"]["divisions"][0]["number"] == "1" for row in projection["rows"])


def test_nicene_preserves_source_paragraph_boundaries_and_text_part_locator() -> None:
    projection, _ = _project("fixture-nicene-creed")
    source = _source_units(CASES["fixture-nicene-creed"])
    assert [row["content"] for row in projection["rows"]] == [unit["content"] for unit in source[:2]]
    assert [row["number"] for row in projection["rows"]] == [None, None]
    assert [row["locator"]["source_order"] for row in projection["rows"]] == [1, 2]
    assert [row["locator"]["text_part"] for row in projection["rows"]] == ["body", "body"]
    assert [row["locator"]["part_titles"] for row in projection["rows"]] == [[], []]
    assert [row["locator"]["divisions"][0]["type"] for row in projection["rows"]] == ["text", "text"]
    assert [row["locator"]["divisions"][0]["number"] for row in projection["rows"]] == [None, None]
    assert [row["locator"]["divisions"][0]["titles"] for row in projection["rows"]] == [[], []]


def test_omitted_note_tail_is_emitted_once_for_source_derived_content(tmp_path: Path) -> None:
    case = CASES["fixture-westminster-confession"]
    source_content = _source_units(case)[0]["content"]
    prefix, suffix = source_content.rsplit(" ", 1)
    tree = etree.parse(str(FIXTURES / case["tei_file"]))
    paragraph = tree.xpath("//t:div[@type='section'][1]/t:p", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    paragraph.text = prefix
    note = etree.SubElement(paragraph, "{http://www.tei-c.org/ns/1.0}note")
    note.text = " source-derived regression note"
    note.tail = " " + suffix
    path = tmp_path / "note-tail.tei.xml"
    raw = etree.tostring(tree, encoding="utf-8", xml_declaration=True)
    path.write_bytes(raw)

    # The source oracle excludes the inserted note and proves the following
    # tail is retained exactly once by each independent text walker.
    producer_root = ET.fromstring(raw)
    producer_paragraph = producer_root.find(".//{http://www.tei-c.org/ns/1.0}div[@type='section']/{http://www.tei-c.org/ns/1.0}p")
    assert producer_paragraph is not None
    assert doctrinal_documents._render(producer_paragraph, omit_notes=True) == source_content
    assert doctrinal_documents._render(producer_paragraph, omit_notes=True).count(suffix) == 1

    checker_root = etree.fromstring(raw)
    checker_paragraph = checker_root.xpath("//t:div[@type='section'][1]/t:p", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    assert doctrinal_documents._checker_text(checker_paragraph, omit_notes=True) == source_content
    assert doctrinal_documents._checker_text(checker_paragraph, omit_notes=True).count(suffix) == 1

    projection = project_doctrinal_document(path, **_context(case))
    rendered = projection["rows"][0]["content"]
    assert rendered == f"{prefix} source-derived regression note {suffix}"
    assert rendered.count(suffix) == 1
    assert [warning["reason"] for warning in projection["warnings"]].count("note-extracted") == 1
    receipt = build_doctrinal_receipt(projection, identity=case["identity"])
    assert verify_doctrinal_document(path, projection["rows"], receipt, **_context(case)) == []


def test_scope_accounts_for_tei_subset_but_retains_complete_source_census() -> None:
    projection, receipt = _project("fixture-westminster-confession", scope_id="fixture-wcf-1647-unit-1-1")
    case = CASES["fixture-westminster-confession"]
    assert len(projection["rows"]) == 1
    assert receipt["selection"] == {"available_units": 2, "selected_units": 1, "excluded_units": 1, "scope_id": "fixture-wcf-1647-unit-1-1"}
    assert receipt["source_accounting"]["native_unit_count"] == 172
    assert receipt["source_accounting"]["selected_unit_ids"] == ["1.1", "1.2"]
    assert any(item["reason"] == "outside-scope" and item["number"] == "2" for item in receipt["exclusions"])
    assert verify_doctrinal_document(FIXTURES / case["tei_file"], projection["rows"], receipt, scope_id="fixture-wcf-1647-unit-1-1", **_context(case)) == []


def test_ordered_doctrinal_parent_content_and_child_scope(tmp_path: Path) -> None:
    # Synthetic mapping extension, not new evidence of retained-source fidelity.
    case = CASES["fixture-westminster-confession"]
    context = _context(case)
    context["source_tei_unit_bindings"] = [
        {"tei_xml_id": "fixture-wcf-1647-unit-1-1", "source_unit_ids": ["1.1"]},
        {"tei_xml_id": "fixture-wcf-1647-unit-1-2", "source_unit_ids": ["1.2"]},
    ]
    tree = ET.parse(FIXTURES / case["tei_file"])
    parent = tree.find(".//{*}div[@type='chapter']")
    assert parent is not None
    before = ET.Element(f"{{{doctrinal_documents.TEI_NS}}}p")
    before.text = "Synthetic parent introduction."
    parent.insert(1, before)
    after = ET.SubElement(parent, f"{{{doctrinal_documents.TEI_NS}}}p")
    after.text = "Synthetic parent conclusion."
    path = tmp_path / "hierarchy.tei.xml"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    projection = project_doctrinal_document(path, **context)
    receipt = build_doctrinal_receipt(projection, identity=case["identity"])
    assert verify_doctrinal_document(path, projection["rows"], receipt, **context) == []
    assert len(projection["rows"]) == 1
    row = projection["rows"][0]
    from ocd_kernel.release.features import configuration_features
    from ocd_kernel.release.typed_rows import encode_rows, check_rows
    features = configuration_features(projection["rows"])
    check_rows(encode_rows(projection["rows"], features), projection["rows"], features)
    assert row["text"].index(before.text) < row["text"].index(after.text)
    assert receipt["selection"]["selected_units"] == 2
    assert len(receipt["anchors"][0]["selected_leaf_paths"]) == 2
    assert receipt["anchors"][0]["source_unit_ids"] == ["1.1", "1.2"]
    children = [node for node in row["structure"]["content"] if node["kind"] != "text"]
    assert len(children) == 5  # heading, introduction, two sections, conclusion
    for mutation in ("drop-child", "swap-children", "drop-binding"):
        changed = copy.deepcopy(projection["rows"])
        changed_receipt = copy.deepcopy(receipt)
        content = changed[0]["structure"]["content"]
        positions = [i for i, node in enumerate(content) if node["kind"] == children[2]["kind"]]
        if mutation == "drop-child":
            del content[positions[0]]
        elif mutation == "swap-children":
            content[positions[0]], content[positions[1]] = content[positions[1]], content[positions[0]]
        else:
            changed_receipt["anchors"][0]["selected_leaf_paths"].pop()
        changed_receipt["output_sha256"] = hashlib.sha256(_canonical(changed)).hexdigest()
        assert verify_doctrinal_document(path, changed, changed_receipt, **context)
    scope_id = "fixture-wcf-1647-unit-1-1"
    scoped = project_doctrinal_document(path, scope_id=scope_id, **context)
    scoped_receipt = build_doctrinal_receipt(scoped, identity=case["identity"])
    assert verify_doctrinal_document(path, scoped["rows"], scoped_receipt, scope_id=scope_id, **context) == []
    assert scoped_receipt["anchors"][0]["source_unit_ids"] == ["1.1"]
    assert before.text not in scoped["rows"][0]["text"]
    assert after.text not in scoped["rows"][0]["text"]
    assert scoped["rows"][0]["record_id"] != row["record_id"]

    for mutation in ("absent", "drop", "swap", "duplicate", "unknown-tei"):
        invalid = copy.deepcopy(context)
        declarations = invalid["source_tei_unit_bindings"]
        if mutation == "absent":
            invalid.pop("source_tei_unit_bindings")
        elif mutation == "drop":
            declarations.pop()
        elif mutation == "swap":
            declarations.reverse()
        elif mutation == "duplicate":
            declarations[1]["source_unit_ids"] = ["1.1"]
        else:
            declarations[1]["tei_xml_id"] = "unknown"
        with pytest.raises(PipelineError):
            project_doctrinal_document(path, **invalid)
        assert verify_doctrinal_document(path, projection["rows"], receipt, **invalid)


def test_checker_rejects_rows_drift_and_flattened_content() -> None:
    projection, receipt = _project("fixture-westminster-confession")
    case = CASES["fixture-westminster-confession"]
    for rows in (projection["rows"][:-1], projection["rows"] + [copy.deepcopy(projection["rows"][0])], list(reversed(projection["rows"]))):
        assert verify_doctrinal_document(FIXTURES / case["tei_file"], rows, receipt, **_context(case))
    drifted = copy.deepcopy(projection["rows"])
    drifted[0]["content"] += " drift"
    errors = verify_doctrinal_document(FIXTURES / case["tei_file"], drifted, receipt, **_context(case))
    assert any("rows do not match" in error for error in errors)


def test_checker_rejects_private_public_locator_field_and_forged_receipt_context() -> None:
    projection, receipt = _project("fixture-westminster-confession")
    case = CASES["fixture-westminster-confession"]
    private = copy.deepcopy(projection["rows"])
    private[0]["locator"]["anchor"] = "fixture-wcf-1647-unit-1-1"
    errors = verify_doctrinal_document(FIXTURES / case["tei_file"], private, receipt, **_context(case))
    assert any("invalid doctrinal public row" in error or "rows do not match" in error for error in errors)
    forged = copy.deepcopy(receipt)
    forged["master_sha256"] = "0" * 64
    forged["source_accounting"]["census"] = []
    forged["independent_check"] = {"status": "passed", "errors": []}
    errors = verify_doctrinal_document(FIXTURES / case["tei_file"], projection["rows"], forged, **_context(case))
    assert any("master_sha256" in error for error in errors)
    assert any("source_accounting" in error for error in errors)
    assert any("independent_check" in error for error in errors)


def test_checker_rejects_retained_source_path_mutation_even_with_matching_tei_receipt(tmp_path: Path) -> None:
    case = CASES["fixture-westminster-confession"]
    source = ROOT / case["source_path"]
    altered = tmp_path / source.name
    altered.write_bytes(source.read_bytes() + b"\nforged")
    context = _context(case)
    context["source_path"] = altered
    context["source_logical_path"] = case["source_path"]
    with pytest.raises(PipelineError, match="retained source hash"):
        project_doctrinal_document(FIXTURES / case["tei_file"], **context)
    projection, receipt = _project("fixture-westminster-confession")
    assert verify_doctrinal_document(FIXTURES / case["tei_file"], projection["rows"], receipt, **context)


@pytest.mark.parametrize("change", ["table", "attribute", "namespace", "doctype", "comment", "outside-pi"])
def test_unsupported_or_unbound_source_fails_both_routes(change: str, tmp_path: Path) -> None:
    case = CASES["fixture-westminster-confession"]
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
        project_doctrinal_document(path, **_context(case))
    projection, receipt = _project("fixture-westminster-confession")
    assert verify_doctrinal_document(path, projection["rows"], receipt, **_context(case))


def test_independent_checker_rejects_nested_inline_structure_with_forged_master(tmp_path: Path) -> None:
    case = CASES["fixture-westminster-confession"]
    tree = etree.parse(str(FIXTURES / case["tei_file"]))
    paragraph = tree.xpath("//t:div[@type='section'][1]/t:p", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    forged = etree.SubElement(paragraph, "{http://www.tei-c.org/ns/1.0}div", type="unaccounted")
    forged.text = "forged nested visible text"
    path = tmp_path / "nested-inline.tei.xml"
    path.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
    projection, receipt = _project(case["fixture_id"])
    forged_receipt = copy.deepcopy(receipt)
    forged_receipt["master_sha256"] = _sha(path)
    errors = verify_doctrinal_document(path, projection["rows"], forged_receipt, **_context(case))
    assert any("checker: doctrinal inline div" in error for error in errors)


@pytest.mark.parametrize("name", CASES)
def test_fixture_is_valid_full_tei_p5(name: str) -> None:
    document = etree.parse(str(FIXTURES / CASES[name]["tei_file"]))
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    assert schema.validate(document), schema.error_log.last_error


def test_source_to_fixture_builder_is_byte_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    subprocess.run([sys.executable, str(BUILDER), "--output", str(first)], check=True)
    subprocess.run([sys.executable, str(BUILDER), "--output", str(second)], check=True)
    actual_files = sorted(path.relative_to(FIXTURES) for path in FIXTURES.rglob("*") if path.is_file())
    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert first_files == actual_files == second_files
    assert all((first / relative).read_bytes() == (FIXTURES / relative).read_bytes() == (second / relative).read_bytes() for relative in actual_files)


def test_source_revision_events_are_separate_from_processing_history(tmp_path, monkeypatch):
    import xml.etree.ElementTree as ET
    from ocd_kernel.projection.categories import doctrinal_documents as module
    case = CASES['fixture-westminster-confession']
    tree = ET.parse(FIXTURES / case['tei_file'])
    ns = '{http://www.tei-c.org/ns/1.0}'
    source = tree.find('.//'+ns+'sourceDesc')
    note = ET.SubElement(source, ns+'note', type='source-revision')
    ET.SubElement(note, ns+'date').text = '1788'
    ET.SubElement(note, ns+'seg', type='revising-body').text = 'Synthetic assembly'
    ET.SubElement(note, ns+'seg', type='description').text = 'Synthetic source revision statement.'
    path = tmp_path / 'history.xml'
    tree.write(path, encoding='utf-8')
    projection = project_doctrinal_document(path, **_context(case))
    receipt = build_doctrinal_receipt(projection, identity=case['identity'])
    assert projection['rows'][0]['revision_history'] == [{'year':1788,'body':'Synthetic assembly','description':'Synthetic source revision statement.'}]
    monkeypatch.setattr(module, '_source_revision_events', lambda *args: pytest.fail('producer called'))
    assert verify_doctrinal_document(path, projection['rows'], receipt, **_context(case)) == []
    projection['rows'][0]['revision_history'][0]['year'] = 1789
    assert verify_doctrinal_document(path, projection['rows'], receipt, **_context(case))


@pytest.mark.parametrize('fields', [
    '<date>1788</date>',
    '<date>circa 1788</date><seg type="description">Revision.</seg>',
    '<date>1788</date><date>1789</date><seg type="description">Revision.</seg>',
    '<date>1788</date><seg type="revising-body"> </seg><seg type="description">Revision.</seg>',
])
def test_source_revision_rejects_ambiguous_fields(fields):
    import xml.etree.ElementTree as ET
    from lxml import etree
    from ocd_kernel.projection.categories import doctrinal_documents as module
    source = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><sourceDesc><note type="source-revision">'+fields+'</note></sourceDesc></fileDesc></teiHeader></TEI>'
    with pytest.raises(module.UnsupportedStructure):
        module._source_revision_events(ET.fromstring(source))
    with pytest.raises(module.UnsupportedStructure):
        module._observed_source_revision_events(etree.fromstring(source.encode()))
