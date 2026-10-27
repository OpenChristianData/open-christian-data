"""Bounded mixed-sender TEI corpus fixture for the held NPNF109 letters."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from lxml import etree

from build.tei.npnf109_chrysostom_reconstruction import _convert as convert_volume
from build.tei.npnf109_work_oracle import _check_node
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.acceptance import _tei_facts
from build.lib.tei_xsd import compiled_tei_schema


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources/structured-text/chrysostom-npnf109-16/npnf109-chrysostom.source-manifest.json"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
LETTERS = (
    (
        "xviii.iv", "To Innocent, Bishop of Rome, Greeting in the Lord.",
        "John Chrysostom", "The retained introduction identifies this as Chrysostom's second letter.",
        "dd574bc5277445e375821091949a05da67b2fa386e013870496c8f0fa2c60819",
    ),
    (
        "xviii.v", "To the Beloved Brother John, Innocent.",
        "Innocent, Bishop of Rome", "The retained introduction identifies Innocent as this letter's sender.",
        "66f039c2429c16b6c61992e5864486dde8bfdf5678ead82ee5e7153bcbb9e61f",
    ),
)


def _header(title: str, author: str | None = None) -> etree._Element:
    header = etree.Element(f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = title
    if author is not None:
        etree.SubElement(title_stmt, f"{{{TEI}}}author").text = author
    etree.SubElement(etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt"), f"{{{TEI}}}p").text = "Private diagnostic fixture."
    etree.SubElement(etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc"), f"{{{TEI}}}p").text = "Retained NPNF109 XML."
    return header


def test_two_letter_tei_corpus_is_independently_checkable_and_keeps_senders(tmp_path: Path) -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    manifest.verify()
    source_bytes = manifest.authority_path("npnf109-retained-xml").read_bytes()
    assert sha256(source_bytes).hexdigest() == "6d0887393b4d197d7784cbea989aeb422d7e38f55711b4c4d4af85e3de680175"
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    source_body = source.find("ThML.body")
    assert source_body is not None
    intro = source.xpath("//*[@id='xviii.ii']")
    assert len(intro) == 1
    intro_text = " ".join(" ".join(intro[0].itertext()).split())
    assert "The first letter of St. Chrysostom" in intro_text
    assert "The second was written" in intro_text
    assert "To Chrysostom Innocent writes" in intro_text
    selected_features = [node for root in list(source_body)[3:-2] for node in root.iter() if isinstance(node.tag, str)]

    aggregate_bytes = convert_volume(manifest)["content.tei.xml"]
    assert sha256(aggregate_bytes).hexdigest() == "38ace0cb485e8d88f8e6e4ab3ba108f21746db1d401416d7b722d0eab32f626a"
    aggregate = etree.fromstring(aggregate_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    corpus = etree.Element(f"{{{TEI}}}teiCorpus", nsmap={None: TEI})
    corpus.set(XML_ID, "npnf109-rome-two-letter-fixture")
    collection_header = _header("Correspondence of St. Chrysostom with the Bishop of Rome")
    revision = etree.SubElement(collection_header, f"{{{TEI}}}revisionDesc")
    change = etree.SubElement(revision, f"{{{TEI}}}change", when="2026-09-27")
    change.set(XML_ID, "npnf109-rome-two-letter-fixture-revision")
    change.text = "Test the nonaccepted two-letter collection shape."
    corpus.append(collection_header)
    for locator, title, author, attribution, source_hash in LETTERS:
        source_matches = source.xpath("//*[@id=$locator]", locator=locator)
        mapped_matches = aggregate.xpath("//*[@xml:id=$identifier]", namespaces={"xml": XML}, identifier=f"npnf109-{locator}")
        assert len(source_matches) == len(mapped_matches) == 1
        source_letter, mapped = source_matches[0], mapped_matches[0]
        assert source_letter.getparent().get("id") == "xviii"
        assert source_letter.get("title") == title
        assert sha256(etree.tostring(source_letter, method="c14n")).hexdigest() == source_hash
        ordinal = next(index for index, feature in enumerate(selected_features, 1) if feature is source_letter)
        assert _check_node(source_letter, mapped, ordinal, root=False, work_id="") == ordinal + sum(
            1 for feature in source_letter.iter() if isinstance(feature.tag, str)
        ) - 1

        member = etree.SubElement(corpus, f"{{{TEI}}}TEI")
        member.set(XML_ID, f"npnf109-{locator}-letter")
        member.append(_header(title, author))
        text = etree.SubElement(member, f"{{{TEI}}}text")
        text.set(f"{{{XML}}}lang", "en")
        body = etree.SubElement(text, f"{{{TEI}}}body")
        letter = deepcopy(mapped)
        letter.tail = None
        note = etree.SubElement(letter, f"{{{TEI}}}note", type="source-attribution")
        etree.SubElement(note, f"{{{TEI}}}seg", type="attribution-note").text = attribution
        body.append(letter)

    path = tmp_path / "two-letter-diagnostic.tei.xml"
    path.write_bytes(etree.tostring(corpus, encoding="UTF-8", xml_declaration=True))
    xsd = compiled_tei_schema(manifest.authority_path("tei-p5-xsd"))
    assert xsd.validate(etree.parse(str(path))), str(xsd.error_log.last_error)
    for member in list(corpus)[1:]:
        assert xsd.validate(etree.ElementTree(deepcopy(member))), str(xsd.error_log.last_error)
    tree, _facts = _tei_facts(path)
    assert [etree.QName(node).localname for node in tree.getroot()[1:]] == ["TEI", "TEI"]

    context = {
        "identity": {
            "work_id": "chrysostom-correspondence-with-rome",
            "textual_form_id": "chrysostom-correspondence-with-rome-retained-text",
            "edition_id": "chrysostom-correspondence-with-rome-npnf109-electronic-witness",
        },
        "language": "en", "representation_revision": "diagnostic-only",
        "edition_title": "Correspondence of St. Chrysostom with the Bishop of Rome",
        "category": "prose", "_allow_acceptance_metadata": True,
    }
    projection = project_document(path, **context)
    rows = projection["rows"]
    assert [row["locator"]["document"] for row in rows] == [1, 2]
    assert [row["provenance"]["attribution_note"] for row in rows] == [item[3] for item in LETTERS]
    assert all(row["provenance"]["attribution_note"] not in row["text"] for row in rows)
    assert len({row["record_id"] for row in rows}) == 2
    assert verify_document(path, rows, projection["receipt"], **context) == []
    reversed_rows = list(reversed(rows))
    assert verify_document(path, reversed_rows, projection["receipt"], **context)
    missing_row = rows[:1]
    assert verify_document(path, missing_row, projection["receipt"], **context)
