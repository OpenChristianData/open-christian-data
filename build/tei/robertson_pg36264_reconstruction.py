"""Reconstruct the complete retained Harper PG36264 electronic witness."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote

from lxml import etree, html
from ocd_kernel.reconstruction.contract import reconstruct

CONVERTER_ID = "ocd-robertson-pg36264-html-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "105aac29a024f9771c1f8fe4917e668eabe5d2abe39c1afcbd67e91960a20418"
TAGS = {"pre": "ab", "table": "table", "tr": "row", "td": "cell",
        "img": "graphic", "br": "lb", "h1": "ab", "h2": "ab", "h3": "ab",
        "h4": "ab", "center": "ab", "div": "ab", "p": "p", "blockquote": "quote",
        "big": "hi", "i": "hi", "b": "hi", "small": "hi", "sup": "hi", "a": "ref"}


def _sha(value):
    return sha256(value).hexdigest()


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _convert(manifest):
    source = manifest.authority_path("retained-source").read_bytes()
    if _sha(source) != SOURCE_SHA:
        raise ValueError("PG36264 retained HTML differs")
    body = html.document_fromstring(source, parser=html.HTMLParser(encoding="iso-8859-1")).find("body")
    nodes = list(body.iterdescendants())
    if len(nodes) != 44176 or any(n.tag not in TAGS for n in nodes):
        raise ValueError("PG36264 source feature boundary differs")
    identifiers = {n: n.get("name") or f"src-{i:05d}" for i, n in enumerate(nodes, 1)}
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    titles = etree.SubElement(desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(titles, f"{{{TEI}}}title").text = "A Harmony of the Gospels for Students of the Life of Christ"
    etree.SubElement(titles, f"{{{TEI}}}author").text = "A. T. Robertson"
    publication = etree.SubElement(desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}p").text = "Source-bound electronic reconstruction candidate; publication disposition is separate."
    sources = etree.SubElement(desc, f"{{{TEI}}}sourceDesc")
    etree.SubElement(sources, f"{{{TEI}}}p").text = "Project Gutenberg 36264, retained ISO-8859-1 HTML; title page: Harper & Brothers, 1922. Produced by Ron Swanson."
    text = etree.SubElement(root, f"{{{TEI}}}text")
    text.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    envelope = etree.SubElement(etree.SubElement(text, f"{{{TEI}}}body"), f"{{{TEI}}}div", type="complete-html-body")
    envelope.text = body.text
    major = part = group = envelope
    boundaries = []

    def convert(node, parent):
        tag = "anchor" if node.tag == "a" and not node.get("href") else TAGS[node.tag]
        target = etree.SubElement(parent, f"{{{TEI}}}{tag}")
        target.set(XML_ID, identifiers[node])
        target.set("rend" if tag == "anchor" else "ana", "urn:ocd:pg36264:html:" + quote(_json({"tag": node.tag, "attributes": dict(node.attrib)}).decode().strip(), safe=""))
        if node.tag in {"h1", "h2", "h3", "h4"}:
            target.set("type", "source-" + node.tag)
        elif tag == "ab":
            target.set("type", "source-pre" if node.tag == "pre" else "source-block")
        if tag == "table":
            target.set("n", node.get("summary"))
        if tag == "cell":
            for old, new in (("colspan", "cols"), ("rowspan", "rows")):
                if node.get(old):
                    target.set(new, node.get(old))
        if tag == "ref":
            target.set("target", node.get("href"))
        if tag == "graphic":
            target.set("url", node.get("src"))
            target.set("n", "source-alt:" + node.get("alt"))
        if tag == "hi":
            target.set("rend", {"i": "italic", "b": "bold", "small": "small", "big": "large", "sup": "superscript"}[node.tag])
        if node.get("align") and tag != "row":
            target.set("rend", "source-align:" + node.get("align"))
        target.text = node.text
        for child in node:
            converted = convert(child, target)
            converted.tail = child.tail
        return target

    for node in body:
        name = node.get("name") if node.tag == "a" else None
        if name:
            if name.startswith("section"):
                group = etree.SubElement(part, f"{{{TEI}}}div", type="harmony-section", n=name)
            elif name.startswith("part"):
                part = group = etree.SubElement(major, f"{{{TEI}}}div", type="harmony-part", n=name)
            elif name.startswith("note") and name != "notes":
                group = etree.SubElement(major, f"{{{TEI}}}div", type="explanatory-note", n=name)
            else:
                major = part = group = etree.SubElement(envelope, f"{{{TEI}}}div", type="source-division", n=name)
            boundaries.append(name)
        parent = group
        if TAGS[node.tag] in {"lb", "ref", "hi", "graphic"} or node.tag == "a":
            parent = etree.SubElement(group, f"{{{TEI}}}ab", type="source-inline-container")
        converted = convert(node, parent)
        carrier = parent if parent is not group else converted
        if (node.tail or "").strip():
            etree.SubElement(group, f"{{{TEI}}}ab", type="source-block").text = node.tail
        else:
            carrier.tail = node.tail
    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    account = dict(contract="ocd-robertson-pg36264-accountability-v1", source_sha256=_sha(source),
                   source_bytes=len(source), body_elements=len(nodes), body_top_level_elements=len(body),
                   tags=dict(Counter(n.tag for n in nodes)), omitted_elements=0,
                   body_text_sha256=_sha("".join(body.itertext()).encode()),
                   source_boundaries=boundaries, source_attributes="Literal tag and all attributes in each node's ana URI (anchor rend URI)",
                   table_count=137, note_blockquotes=905, media_count=2,
                   source_head_disposition="Retained byte-exact in HTML; metadata and CSS support, not literary body")
    return {"content.tei.xml": content, "source-accountability.json": _json(account),
            "provenance.json": _json(dict(source_id=manifest.record["source_id"], source_sha256=_sha(source),
                                         authority="complete retained electronic HTML body and two referenced JPEGs",
                                         print_collation="not-claimed", doran_equivalence="not-claimed")),
            "unresolved.jsonl": _json(dict(status="bounded", stronger_unassessed_claims=["Harper print collation", "Doran equivalence", "human verification"])),
            "README.source.md": manifest.authority_path("source-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(manifest, destination: str | Path):
    return reconstruct(manifest, destination, _convert)
