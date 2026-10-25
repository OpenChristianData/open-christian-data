"""Source-derived, opt-in native prose projection for Greenleaf PG34989."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import (
    GREENLEAF_MARKER_PROFILE,
    project_document,
    verify_document,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/clean-ready-acquisition-to-tei/master-4/28/greenleaf-testimony-four-evangelists-1847/34989-tei.tei"
CANDIDATE = ROOT / "reports/clean-ready-acquisition-to-tei/master-4/28/greenleaf-testimony-four-evangelists-1847/candidate/package/greenleaf-testimony-four-evangelists-1847.tei.xml"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONTEXT = {
    "identity": {
        "work_id": "greenleaf-testimony-four-evangelists-1847",
        "textual_form_id": "greenleaf-testimony-four-evangelists-1847-gutenberg-retained-en",
        "edition_id": "greenleaf-testimony-four-evangelists-1847-gutenberg-electronic",
    },
    "language": "en",
    "representation_revision": "greenleaf-source-native-probe",
    "edition_title": "Project Gutenberg electronic witness 34989",
    "category": "prose",
    "_allow_acceptance_metadata": True,
    "projection_profile": GREENLEAF_MARKER_PROFILE,
}


def _walk(content: dict) -> list[dict]:
    found = [content]
    for child in content.get("content", []):
        if isinstance(child, dict):
            found.extend(_walk(child))
    return found


@pytest.fixture(scope="module")
def projected() -> dict:
    return project_document(CANDIDATE, **CONTEXT)


def test_retained_p4_has_exact_page_triples_and_generator_scopes() -> None:
    source = etree.parse(str(SOURCE), etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    text = source.getroot().find("text")
    assert text is not None
    body = text.find("body")
    assert body is not None and len(body) == 30
    labels = []
    for index in range(0, 30, 3):
        page, anchor, division = list(body)[index:index + 3]
        assert [page.tag, anchor.tag, division.tag] == ["pb", "anchor", "div"]
        assert anchor.get("id") == "Pg" + page.get("n")
        assert not (page.tail or "").strip() and not (anchor.tail or "").strip()
        labels.append(page.get("n"))
    assert labels == ["iii", "vii", "ix", "xx", "001", "049", "498", "507", "523", "531"]
    front, back = text.find("front"), text.find("back")
    assert front is not None and back is not None
    assert [[node.get("type") for node in division.findall("divGen")] for division in front] == [
        ["pgheader"], ["encodingDesc"], [], ["toc"]
    ]
    assert [[node.get("type") for node in division.findall("divGen")] for division in back] == [
        ["footnotes"], ["pgfooter"]
    ]


def test_paired_rows_preserve_source_markers_glyphs_and_private_header(projected: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    rows, receipt = projected["rows"], projected["receipt"]
    assert len(rows) == 13
    assert Counter(row["locator"]["text_part"] for row in rows) == {"front": 2, "body": 10, "back": 1}
    body_rows = [row for row in rows if row["locator"]["text_part"] == "body"]
    assert [row["locator"]["unit"] for row in body_rows] == list(range(3, 31, 3))
    assert [tuple(node["kind"] for node in row["structure"]) for row in body_rows] == [
        ("page-break", "anchor", "division")
    ] * 10
    assert [row["structure"][0]["attributes"]["number"] for row in body_rows] == [
        "iii", "vii", "ix", "xx", "001", "049", "498", "507", "523", "531"
    ]
    assert [row["structure"][1]["attributes"]["source_anchor"] for row in body_rows] == [
        "Pgiii", "Pgvii", "Pgix", "Pgxx", "Pg001", "Pg049", "Pg498", "Pg507", "Pg523", "Pg531"
    ]
    assert all(row["text"] for row in rows)
    nodes = [node for row in rows for root in row["structure"] for node in _walk(root)]
    glyphs = [node for node in nodes if node.get("kind") == "glyph"]
    assert len(glyphs) == 155
    assert all(node["attributes"]["reference"] == "#U0x2014" for node in glyphs)
    assert all(node["content"] == [{"kind": "text", "text": "\u2014"}] for node in glyphs)
    assert sum(row["text"].count("\u2014") for row in rows) == 93
    assert len([node for node in nodes if node.get("kind") == "generator-placeholder"]) == 2
    assert [node["attributes"]["type"] for node in nodes if node.get("kind") == "generator-placeholder"] == [
        "toc", "footnotes"
    ]
    assert Counter(node["attributes"].get("index_name") for node in nodes if node.get("kind") == "index-marker") == {
        "toc": 21, "pdf": 21
    }
    assert len([item for item in receipt["exclusions"] if item["reason"] == "source-generator-only"]) == 6
    assert all("charDecl" not in str(row) for row in rows)
    from ocd_kernel.projection.categories import native_documents

    monkeypatch.setattr(native_documents, "_prose_references", lambda *_args: pytest.fail("producer called"))
    assert verify_document(CANDIDATE, rows, receipt, **CONTEXT) == []
    changed = deepcopy(rows)
    changed[4]["structure"][1]["attributes"]["source_anchor"] = "Pgwrong"
    assert verify_document(CANDIDATE, changed, receipt, **CONTEXT)


@pytest.mark.parametrize("mutation", ["marker-order", "char-mapping", "glyph-ref", "glyph-text", "index-name", "generator-type", "missing-text", "missing-back"])
def test_source_feature_mutations_fail_closed(tmp_path: Path, projected: dict, mutation: str) -> None:
    tree = etree.parse(str(CANDIDATE))
    root = tree.getroot()
    if mutation == "marker-order":
        body = root.find(f"{TEI}text/{TEI}body")
        assert body is not None
        body.insert(0, body[1])
    elif mutation == "char-mapping":
        mapping = root.find(f"{TEI}teiHeader/{TEI}encodingDesc/{TEI}charDecl/{TEI}char/{TEI}mapping")
        assert mapping is not None
        mapping.text = "??"
    elif mutation == "glyph-ref":
        glyph = next(root.iter(f"{TEI}g"))
        glyph.set("ref", "#U0x2003")
    elif mutation == "glyph-text":
        glyph = next(root.iter(f"{TEI}g"))
        glyph.text = "x"
    elif mutation == "index-name":
        marker = next(root.iter(f"{TEI}index"))
        marker.set("indexName", "invented")
    elif mutation == "missing-text":
        root.remove(root.find(f"{TEI}text"))
    elif mutation == "missing-back":
        text = root.find(f"{TEI}text")
        assert text is not None
        text.remove(text.find(f"{TEI}back"))
    else:
        generator = next(root.iter(f"{TEI}divGen"))
        generator.set("type", "invented")
    path = tmp_path / "mutated.tei.xml"
    tree.write(str(path), encoding="utf-8", xml_declaration=True)
    with pytest.raises(PipelineError):
        project_document(path, **CONTEXT)
    assert verify_document(path, projected["rows"], projected["receipt"], **CONTEXT)


def test_default_native_document_with_missing_text_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "missing-text.tei.xml"
    path.write_text('<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/></TEI>', encoding="utf-8")
    context = {key: value for key, value in CONTEXT.items() if key != "projection_profile"}
    with pytest.raises(PipelineError, match="header and text"):
        project_document(path, **context)
    assert verify_document(path, [], {}, **context)
