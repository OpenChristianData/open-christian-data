"""Shared TEI writer helpers."""
from __future__ import annotations

from pathlib import Path

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"


def qn(localname: str) -> str:
    return f"{{{TEI_NS}}}{localname}"


def tei_el(localname: str, attrs: dict[str, str] | None = None, text: str | None = None) -> etree._Element:
    normalized: dict[str, str] = {}
    for key, value in (attrs or {}).items():
        if value is None:
            continue
        if key == "xml:id":
            normalized[XML_ID] = value
        elif key == "xml:lang":
            normalized[XML_LANG] = value
        else:
            normalized[key] = value
    nsmap = {None: TEI_NS} if localname == "TEI" else None
    node = etree.Element(qn(localname), normalized, nsmap=nsmap)
    if text is not None:
        node.text = text
    return node


def stamp_header(
    *,
    title: str,
    author: str,
    contributors: list[str],
    source_url: str,
    source_sha256: str,
    print_source: str,
) -> etree._Element:
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    header.append(file_desc)

    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text=title))
    title_stmt.append(tei_el("author", text=author))
    for contributor in contributors:
        resp_stmt = tei_el("respStmt")
        resp_stmt.append(tei_el("resp", text="Contributor"))
        resp_stmt.append(tei_el("name", text=contributor))
        title_stmt.append(resp_stmt)
    file_desc.append(title_stmt)

    publication_stmt = tei_el("publicationStmt")
    publication_stmt.append(tei_el("publisher", text="Open Christian Data"))
    availability = tei_el("availability", {"status": "free"})
    availability.append(tei_el("p", text="Public domain source text prepared for Open Christian Data."))
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)

    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl")
    bibl.append(tei_el("ptr", {"target": source_url}))
    bibl.append(tei_el("idno", {"type": "sha256"}, text=source_sha256.removeprefix("sha256:")))
    bibl.append(tei_el("note", {"type": "print-source"}, text=print_source))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    return header


def derive_address(node: etree._Element) -> str:
    node_id = node.get(XML_ID)
    if node_id:
        return node_id

    ancestor = node.getparent()
    while ancestor is not None and ancestor.get(XML_ID) is None:
        ancestor = ancestor.getparent()
    if ancestor is None:
        localname = etree.QName(node).localname
        return f"{localname}[1]"

    ancestor_id = ancestor.get(XML_ID)
    localname = etree.QName(node).localname
    peers = [
        desc
        for desc in ancestor.iterdescendants()
        if etree.QName(desc).localname == localname and desc.get(XML_ID) is None
    ]
    ordinal = peers.index(node) + 1
    return f"{ancestor_id}/{localname}[{ordinal}]"


def serialize(tree: etree._ElementTree, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(output),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
