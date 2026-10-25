"""Focused full-source and native checks for the complete PG16739 witness."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from lxml import etree
import pytest

from build.tei.drummond_pg16739_native import adapt, direct_candidate
from build.tei.drummond_pg16739_native_oracle import check
from build.tools import install_drummond_pg16739 as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.validate import compiled_schema


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@pytest.fixture(scope="module")
def witness() -> bytes:
    adapted, counts = adapt(direct_candidate())
    assert counts == {"space": 665, "located-head": 18, "attached-title": 3, "c": 362}
    return adapted


def test_complete_source_oracle_p5_and_native_producer_checker(witness: bytes, tmp_path: Path) -> None:
    report = check(witness)
    assert report["source_oracle_status"] == "pass"
    assert report["adapted_tei_sha256"] == sha256(witness).hexdigest()
    assert compiled_schema().validate(etree.fromstring(witness))
    path = tmp_path / "drummond.tei.xml"
    path.write_bytes(witness)
    arguments = dict(
        identity={"work_id": "drummond-greatest-thing",
                  "textual_form_id": "drummond-greatest-thing-retained-text",
                  "edition_id": "drummond-greatest-thing-pg16739-electronic-witness"},
        language="en", representation_revision="1",
        edition_title="The Greatest Thing in the World and Other Addresses",
        category="prose", _allow_acceptance_metadata=True,
    )
    projected = project_document(path, **arguments)
    assert len(projected["rows"]) == 1
    assert verify_document(path, projected["rows"], projected["receipt"], **arguments) == []


@pytest.mark.parametrize("mutation", ["blank", "delimiter", "heading"])
def test_independent_oracle_rejects_source_carrier_mutation(witness: bytes, mutation: str) -> None:
    root = etree.fromstring(witness)
    if mutation == "blank":
        root.xpath(".//tei:div[@type='source-blank-line']", namespaces=NS)[0].set("n", "99999")
    elif mutation == "delimiter":
        root.xpath(".//tei:seg[@type='emphasis-delimiter']", namespaces=NS)[0].text = "x"
    else:
        root.xpath(".//tei:ab[@type='source-h1']", namespaces=NS)[0].set("type", "source-h3")
    with pytest.raises(ValueError, match="adapted native source node differs"):
        check(etree.tostring(root, encoding="UTF-8", xml_declaration=True))


def test_source_pin_and_receipt_pin_fail_closed(witness: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="direct candidate digest differs"):
        adapt(direct_candidate() + b" ")
    monkeypatch.setattr(installer, "RECEIPT_SHA256", "0" * 64)
    with pytest.raises(PipelineError, match="frozen stage path or receipt differs"):
        installer.preflight()
