from __future__ import annotations

from pathlib import Path

from lxml import etree

from ocd_kernel.tei.writer import TEI_NS, derive_address, serialize, stamp_header, tei_el

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def test_stamp_header_records_provenance() -> None:
    header = stamp_header(
        title="The City of God",
        author="Augustine of Hippo",
        contributors=["Marcus Dods (translator, 1871)", "Philip Schaff (series editor)"],
        source_url="https://www.ccel.org/ccel/schaff/npnf102.xml",
        source_sha256="abc123",
        print_source="New York: The Christian Literature Publishing Co., 1890",
    )

    assert header.findtext(f".//{{{TEI_NS}}}title") == "The City of God"
    assert header.findtext(f".//{{{TEI_NS}}}author") == "Augustine of Hippo"
    resp_stmts = header.findall(f".//{{{TEI_NS}}}respStmt")
    assert [n.findtext(f"{{{TEI_NS}}}resp") for n in resp_stmts] == ["Contributor", "Contributor"]
    assert [n.findtext(f"{{{TEI_NS}}}name") for n in resp_stmts] == [
        "Marcus Dods (translator, 1871)",
        "Philip Schaff (series editor)",
    ]
    publication_children = [etree.QName(child).localname for child in header.find(f".//{{{TEI_NS}}}publicationStmt")]
    assert publication_children == ["publisher", "availability"]
    assert header.findtext(f".//{{{TEI_NS}}}publisher") == "Open Christian Data"
    availability = header.find(f".//{{{TEI_NS}}}availability")
    assert availability.text is None
    assert "public domain" in availability.findtext(f"{{{TEI_NS}}}p").lower()
    ptr = header.find(f".//{{{TEI_NS}}}ptr")
    assert ptr.get("target") == "https://www.ccel.org/ccel/schaff/npnf102.xml"
    assert ptr.text is None
    source_desc = " ".join(header.find(f".//{{{TEI_NS}}}sourceDesc").itertext())
    assert "abc123" in source_desc
    assert "Christian Literature Publishing" in source_desc


def test_derive_address_uses_xml_id_when_present() -> None:
    node = tei_el("p", {"xml:id": "iv.ii.i-p1"})
    assert derive_address(node) == "iv.ii.i-p1"


def test_derive_address_for_unidentified_descendant_is_stable() -> None:
    div = tei_el("div", {"xml:id": "book-1"})
    p1 = tei_el("p")
    p2 = tei_el("p", {"xml:id": "p-with-id"})
    hi1 = tei_el("hi")
    hi2 = tei_el("hi")
    p1.append(hi1)
    p2.append(hi2)
    div.extend([p1, p2])

    assert derive_address(p1) == "book-1/p[1]"
    assert derive_address(hi1) == "book-1/hi[1]"
    assert derive_address(hi2) == "p-with-id/hi[1]"


def test_serialize_writes_default_tei_namespace(tmp_path: Path) -> None:
    root = tei_el("TEI")
    root.append(tei_el("text"))
    path = tmp_path / "out.xml"

    serialize(etree.ElementTree(root), path)

    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("<?xml version='1.0' encoding='UTF-8'?>")
    assert 'xmlns="http://www.tei-c.org/ns/1.0"' in raw
    assert etree.parse(str(path)).getroot().tag == f"{{{TEI_NS}}}TEI"
