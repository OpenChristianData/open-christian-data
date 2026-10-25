"""Pin Carey's current source-bound TEI and the exact native projection hold."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

from lxml import etree
import pytest

from build.tei.gutenberg_proofread_selected_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import (
    CAREY_GROUPED_TABLE_PROFILE, project_document, verify_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/gutenberg/pg11449.txt"
MANIFEST = ROOT / "sources/structured-text/lib071-gutenberg-evangelical/work-bindings/carey-enquiry/37c-094-tables-v4.source-manifest.json"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-094-carey-enquiry-20260915-tables-v5/package")
NS = {"t": "http://www.tei-c.org/ns/1.0"}
IDENTITY = {
    "work_id": "carey-enquiry",
    "textual_form_id": "carey-enquiry-retained-text",
    "edition_id": "carey-enquiry-pg11449-electronic-witness",
}


def test_current_one_member_candidate_passes_source_oracle_and_retains_table_roles() -> None:
    assert sha256(SOURCE.read_bytes()).hexdigest() == "6dc07e5606be5a0032d6583fa5b663a81ed0971a5d9d1f267cfc14959aa602c0"
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(PACKAGE)
    assert manifest.sha256 == "7ad116b357a606b411f9eabdcb76288ed772f2105c54897afd96a1c3d88c877e"
    assert package.sha256 == "5140dbd06577383369badc227fb7f07e9fa0a6325bbee557427444fdd6ae839e"
    assert validate(manifest, package, _oracle).status == "pass"
    root = etree.fromstring(package.member_bytes("content.tei.xml"))
    outer = root.xpath("./t:text", namespaces=NS)
    assert len(outer) == 1 and len(outer[0]) == 1 and len(outer[0][0]) == 1
    assert [etree.QName(node).localname for node in (outer[0][0], outer[0][0][0])] == ["group", "text"]
    assert len(root.xpath("./t:text/t:group/t:text/t:body/t:div[@type='retained-text-witness']", namespaces=NS)) == 1
    assert len(root.xpath(".//t:space[@type='source-blank-line']", namespaces=NS)) == 250
    assert len(root.xpath(".//t:head[@type='source-located-heading']", namespaces=NS)) == 13
    tables = root.xpath(".//t:table", namespaces=NS)
    assert [(int(table.get("rows")), int(table.get("cols")), len(table.xpath("./t:row", namespaces=NS))) for table in tables] == [
        (112, 5, 112), (100, 5, 100), (42, 5, 42), (98, 6, 98)
    ]
    assert len(root.xpath(".//t:row[@role]", namespaces=NS)) == 352
    assert len(root.xpath(".//t:cell[@n]", namespaces=NS)) == 1536
    assert Counter(node.get("role") for node in root.xpath(".//t:row", namespaces=NS))["data"] > 0


def test_generic_native_producer_and_independent_checker_reject_group_without_a_profile() -> None:
    content = PACKAGE / "content.tei.xml"
    with pytest.raises(PipelineError, match="native text parts are missing, duplicated, or out of order"):
        project_document(
            content, identity=IDENTITY, language="en", representation_revision="carey-v5",
            edition_title="Project Gutenberg PG 11449", category="prose",
            _allow_acceptance_metadata=True,
        )
    errors = verify_document(
        content, [], {}, identity=IDENTITY, language="en", representation_revision="carey-v5",
        edition_title="Project Gutenberg PG 11449", category="prose",
        _allow_acceptance_metadata=True,
    )
    assert any("native document part order differs" in error for error in errors)


def _native_context() -> dict:
    return {
        "identity": IDENTITY, "language": "en", "representation_revision": "carey-v5",
        "edition_title": "Project Gutenberg PG 11449", "category": "prose",
        "projection_profile": CAREY_GROUPED_TABLE_PROFILE, "_allow_acceptance_metadata": True,
    }


def _native_nodes(structure: dict):
    yield structure
    for child in structure.get("content", []):
        if child.get("kind") != "text":
            yield from _native_nodes(child)


def test_carey_profile_preserves_group_path_and_table_semantics() -> None:
    result = project_document(PACKAGE / "content.tei.xml", **_native_context())
    assert len(result["rows"]) == 1
    assert result["receipt"]["projection_profile"] == CAREY_GROUPED_TABLE_PROFILE
    assert result["receipt"]["anchors"][0]["unit_id"].startswith("/TEI/text/group/text/body/")
    nodes = list(_native_nodes(result["rows"][0]["structure"][0]))
    tables = [node for node in nodes if node["kind"] == "table"]
    assert [(node["attributes"]["source_row_count"], node["attributes"]["source_column_count"]) for node in tables] == [
        ("112", "5"), ("100", "5"), ("42", "5"), ("98", "6"),
    ]
    assert len([node for node in nodes if node["kind"] == "table-row" and "source_role" in node["attributes"]]) == 352
    assert len([node for node in nodes if node["kind"] == "table-cell" and "number" in node["attributes"]]) == 1536
    assert verify_document(PACKAGE / "content.tei.xml", result["rows"], result["receipt"], **_native_context()) == []


@pytest.mark.parametrize(
    ("xpath", "attribute", "value"),
    [
        ("./t:text/t:group/t:text", "{http://www.w3.org/XML/1998/namespace}id", "other-member"),
        (".//t:space[@type='source-blank-line']", "{http://www.w3.org/XML/1998/namespace}id", "other-blank-00010"),
        (".//t:head[@type='source-located-heading']", "subtype", "4"),
        (".//t:table", "rows", "111"),
        (".//t:row[@role]", "role", "unaccounted"),
        (".//t:cell[@n]", "n", "0"),
    ],
    ids=["member", "blank-line", "heading", "table-rows", "row-role", "cell-position"],
)
def test_carey_profile_rejects_changed_source_carriers(tmp_path: Path, xpath: str, attribute: str, value: str) -> None:
    root = etree.fromstring((PACKAGE / "content.tei.xml").read_bytes())
    target = root.xpath(xpath, namespaces=NS)[0]
    target.set(attribute, value)
    changed = tmp_path / "changed.tei.xml"
    changed.write_bytes(etree.tostring(root, encoding="utf-8", xml_declaration=True))
    with pytest.raises(PipelineError):
        project_document(changed, **_native_context())
    assert verify_document(changed, [], {}, **_native_context())
