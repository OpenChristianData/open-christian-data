"""Source-defined prose projection for the complete Evangelical Churches work."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

from lxml import etree
import pytest

from build.tei.john_owen_evangelical_churches_audit import compare
from ocd_kernel.projection.categories.lib050_owen import _synthetic, _verify_evangelical_row_map
from ocd_kernel.projection.categories.native_documents import project_document, verify_document


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "raw/ccel/owen/evangelicalchurches.xml"
CANDIDATE = Path(os.environ.get("OCD_OWEN_EVANGELICAL_CANDIDATE", ""))
WORK_ID = "john-owen-evangelical-churches"
IDENTITY = {
    "work_id": WORK_ID,
    "textual_form_id": "john-owen-evangelical-churches-english",
    "edition_id": "john-owen-evangelical-churches-ccel-thml-electronic",
}
REVISION = "john-owen-evangelical-churches-ccel-electronic-v1"
TITLE = "CCEL ThML electronic witness"
NS = "{http://www.tei-c.org/ns/1.0}"


def _walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _source_id(node: dict[str, object]) -> str | None:
    attributes = node.get("attributes")
    if not isinstance(attributes, dict):
        return None
    annotations = attributes.get("source_annotations", "")
    if not isinstance(annotations, str):
        return None
    prefix = "urn:ocd:thml-attribute:id:"
    for token in annotations.split():
        if token.startswith(prefix):
            return unquote(token[len(prefix):])
    return None


def test_complete_source_divisions_and_paragraph_order_project_to_prose() -> None:
    if not os.environ.get("OCD_OWEN_EVANGELICAL_CANDIDATE"):
        pytest.skip("set OCD_OWEN_EVANGELICAL_CANDIDATE to the exact work-local candidate")
    source_bytes = SOURCE.read_bytes()
    candidate_bytes = CANDIDATE.read_bytes()
    assert compare(source_bytes, candidate_bytes)["status"] == "pass"
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    tei = etree.fromstring(candidate_bytes, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    division = tei.find(NS + "text/" + NS + "body/" + NS + "div")
    assert division is not None
    synthetic = _synthetic(tei, division, split_evangelical=True)
    with TemporaryDirectory() as folder:
        path = Path(folder) / "readable.tei.xml"
        path.write_bytes(synthetic)
        result = project_document(
            path, identity=IDENTITY, language="en", representation_revision=REVISION,
            edition_title=TITLE, _allow_acceptance_metadata=True, category="prose",
        )
        assert verify_document(
            path, result["rows"], result["receipt"], identity=IDENTITY,
            language="en", representation_revision=REVISION, edition_title=TITLE,
            _allow_acceptance_metadata=True, category="prose",
        ) == []
    assert len(result["rows"]) == 4
    assert result["receipt"]["unsupported"] == []
    assert _verify_evangelical_row_map(source_bytes, result["rows"]) == []
    assert [row["locator"]["unit"] for row in result["rows"]] == [1, 2, 3, 4]
    assert all(row["category"] == "prose" and row["language"] == "en" and row["work_id"] == WORK_ID for row in result["rows"])
    assert result["receipt"]["master_sha256"] == sha256(synthetic).hexdigest()
    source_divisions = source.find("ThML.body").findall("div1")
    assert [_source_id(row["structure"][0]["content"][0]) for row in result["rows"]] == ["i", "ii", "iii", "iv"]
    for source_division, row in zip(source_divisions, result["rows"], strict=True):
        expected_paragraphs = [node.get("id") for node in source_division.iter() if node.tag in {"p", "argument"}]
        actual_paragraphs = [_source_id(node) for node in _walk(row["structure"]) if node.get("kind") == "paragraph"]
        assert expected_paragraphs == actual_paragraphs
    altered_rows = list(result["rows"])
    altered_rows[1], altered_rows[2] = altered_rows[2], altered_rows[1]
    assert _verify_evangelical_row_map(source_bytes, altered_rows)
