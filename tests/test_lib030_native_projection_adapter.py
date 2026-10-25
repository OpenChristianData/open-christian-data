from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from lxml import etree
import pytest

from build.tei.lib030_native_projection_adapter import adapt_lib030_for_native_projection
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XID = f"{{{XML}}}id"


def _miniature_candidate() -> bytes:
    return f'''<TEI xmlns="{TEI}" xml:id="lib030-candidate">
      <teiHeader><fileDesc>
        <titleStmt><title>Morning and Evening: Daily Readings</title></titleStmt>
        <publicationStmt><p>Private candidate</p></publicationStmt>
        <notesStmt><note type="source-description">CCEL electronic witness</note></notesStmt>
        <sourceDesc><bibl><ptr target="https://www.ccel.org/ccel/spurgeon/morneve.xml"/>
          <idno type="sha256">43dad0c9216508815611a1d91c17f73cf05eec0050b6d7ecac450c39705f725a</idno>
        </bibl></sourceDesc>
      </fileDesc></teiHeader>
      <text><front xml:id="lib030-front">
        <div xml:id="lib030-document-shell" type="source-document-shell">
          <head>Retained CCEL XML document shell</head>
          <ab xml:id="lib030-source-xml-declaration" type="xml-declaration">&lt;?xml version="1.0" encoding="UTF-8"?&gt;</ab>
          <ab xml:id="lib030-source-doctype" type="doctype">&lt;!DOCTYPE ThML PUBLIC &quot;legacy&quot;&gt;</ab>
        </div>
        <div xml:id="lib030-source-head" type="source-metadata">
          <head>Retained ThML metadata, editorial history, rights, and styles</head>
          <ab xml:id="lib030-source-head-transcription" type="exact-parsed-thml-head-xml">&lt;ThML.head&gt;Source credit and editorial text&lt;/ThML.head&gt;</ab>
        </div>
      </front><body><div xml:id="lib030-work" type="work">
        <p xml:id="lib030-day-paragraph"><milestone xml:id="lib030-day" unit="DayOfYear" n="01-01"/>Morning, January 1</p>
        <milestone xml:id="lib030-scripture-comment" type="scripture-comment" unit="scripture-comment" subtype="Meditation" n="Jos 5:12" corresp="Bible:Josh.5.12"/>
        <index xml:id="lib030-scripture-index" indexName="scripRef"/>
        <p>January 1 meditation text.</p>
      </div></body></text>
    </TEI>'''.encode("utf-8")


def test_adapter_preserves_machine_evidence_and_projects_bound_candidate() -> None:
    original = _miniature_candidate()
    altered_marker = original.replace(b'unit="DayOfYear"', b'unit="unknown"', 1)
    with pytest.raises(ValueError, match="source marker fixture must include each adapted marker kind"):
        adapt_lib030_for_native_projection(
            altered_marker, expected_sha256=sha256(altered_marker).hexdigest(),
            require_complete_profile=False,
        )
    adapted, adapter_receipt = adapt_lib030_for_native_projection(
        original, expected_sha256=sha256(original).hexdigest(),
        require_complete_profile=False,
    )
    assert adapter_receipt["complete_tree_inverse_check"] == "pass"
    assert adapter_receipt["identifier_inventory_preserved"] is True
    assert adapter_receipt["ordered_text_and_tail_by_xml_id_preserved"] is True
    assert [row["xml_id"] for row in adapter_receipt["envelope_carriers"]] == [
        "lib030-source-xml-declaration",
        "lib030-source-doctype",
        "lib030-source-head-transcription",
    ]
    assert [row["source_text"] for row in adapter_receipt["generated_context_headings"]] == [
        "Retained CCEL XML document shell",
        "Retained ThML metadata, editorial history, rights, and styles",
    ]
    assert all(
        row["disposition"] == "preserved-as-typed-header-context-and-excluded-from-public-prose"
        for row in adapter_receipt["generated_context_headings"]
    )

    binding_identity = {
        "work_id": "spurgeons-morning-evening",
        "textual_form_id": "spurgeons-morning-evening-english",
        "edition_id": "spurgeons-morning-evening-ccel-thml-electronic",
        "acquisition_id": "spurgeons-morning-evening-ccel-retained-xml",
    }
    source = {
        "source_path": "raw/ccel/spurgeon/morneve.xml",
        "source_sha256": "3512797ae879d4fdbdcde90e5ebc04299e501658fd8fb6c09977c2e2648ad0a4",
        "source_bytes": 2136777,
    }
    revision = {
        "id": "spurgeons-morning-evening-ccel-binding-test-v1",
        "date": "2026-10-03",
        "note": "Bind the adapted review candidate to the retained CCEL electronic witness.",
    }
    bound = bind_reviewed_header(
        adapted, expected_sha256=sha256(adapted).hexdigest(),
        identity=binding_identity, source=source,
        source_url="https://www.ccel.org/ccel/spurgeon/morneve.xml",
        declared_scope="Complete retained CCEL electronic witness for this work.",
        revision=revision,
        historical_source_description={
            "pointers": ["https://www.ccel.org/ccel/spurgeon/morneve.xml"],
            "sha256": ["43dad0c9216508815611a1d91c17f73cf05eec0050b6d7ecac450c39705f725a"],
        },
    )
    identity = {key: binding_identity[key] for key in ("work_id", "textual_form_id", "edition_id")}
    kwargs = {
        "identity": identity,
        "language": "en",
        "representation_revision": revision["id"],
        "edition_title": "Morning and Evening: Daily Readings",
        "_allow_acceptance_metadata": True,
        "category": "prose",
    }
    with TemporaryDirectory(prefix="ocd-lib030-adapter-test-") as temp:
        candidate = Path(temp) / "bound-candidate.tei.xml"
        candidate.write_bytes(bound)
        assert validate_file(candidate) == []
        projected = project_document(candidate, **kwargs)
        assert len(projected["rows"]) == 1
        public_text = "\n".join(row["text"] for row in projected["rows"])
        assert "xml version=\"1.0\"" not in public_text
        assert "Source credit and editorial text" not in public_text
        assert "Retained CCEL XML document shell" not in public_text
        assert "Retained ThML metadata, editorial history, rights, and styles" not in public_text
        assert verify_document(candidate, projected["rows"], projected["receipt"], **kwargs) == []

    tree = etree.fromstring(bound)
    ns = {"t": TEI}
    for identifier, parent in (
        ("lib030-source-xml-declaration", "lib030-document-shell"),
        ("lib030-source-doctype", "lib030-document-shell"),
        ("lib030-source-head-transcription", "lib030-source-head"),
    ):
        note = tree.xpath("//*[@xml:id=$id]", namespaces={"xml": XML}, id=identifier)[0]
        assert etree.QName(note).localname == "note"
        assert note.get("corresp") == f"#{parent}"
        assert note.getparent().tag == f"{{{TEI}}}notesStmt"
    for subtype, parent in (
        ("source-document-shell", "lib030-document-shell"),
        ("source-metadata", "lib030-source-head"),
    ):
        note = tree.xpath(
            "//t:note[@type='generated-context' and @subtype=$subtype]",
            namespaces=ns,
            subtype=subtype,
        )[0]
        assert note.get("corresp") == f"#{parent}"
        assert note.getparent().tag == f"{{{TEI}}}notesStmt"
    assert tree.xpath("count(//t:milestone[@unit='source-text-break' and @ana='urn:ocd:lib030:source-unit:DayOfYear' and @n='01-01'])", namespaces=ns) == 1
    assert tree.xpath("count(//t:milestone[@unit='scripCom' and @type='scripture-comment' and @n='Jos 5:12' and @corresp='Bible:Josh.5.12'])", namespaces=ns) == 1
    assert tree.xpath("count(//t:anchor[@type='source-index-scripRef'])", namespaces=ns) == 1
