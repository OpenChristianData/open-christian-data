"""Readable TEI reconstruction for the two acquired Gutenberg editions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping
from zipfile import ZipFile

from lxml import etree, html
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
BOOKS = {
    "pg49917-john-damascene-allies": {
        "ebook": "49917",
        "title": "St John Damascene on Holy Images. Followed by Three Sermons on the Assumption",
        "translator": "Mary H. Allies",
    },
    "pg77576-apostolic-fathers-ancl-i": {
        "ebook": "77576",
        "title": "The Writings of the Apostolic Fathers",
        "translator": "Alexander Roberts, James Donaldson, and Frederick Crombie",
    },
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def node(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{tag}", **attrs)


def _zip_members(archive: ZipFile) -> list[dict[str, object]]:
    return [
        {"path": item.filename, "bytes": item.file_size, "crc32": f"{item.CRC:08x}", "sha256": sha(archive.read(item))}
        for item in archive.infolist()
        if not item.is_dir()
    ]


def source_html(manifest: SourceManifest) -> tuple[bytes, dict[str, object]]:
    book = BOOKS[manifest.record["work_id"]]
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    archive_path = manifest.authority_path("retained-archive")
    archive_bytes = archive_path.read_bytes()
    if sha(archive_bytes) != profile["archive_sha256"]:
        raise ValueError("retained Gutenberg archive digest differs from profile")
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("retained Gutenberg archive failed CRC validation")
        observed = _zip_members(archive)
        if observed != profile["archive_members"]:
            raise ValueError("Gutenberg member order, length, CRC, or hash differs from profile")
        raw = archive.read(profile["html_member"])
    raw.decode("utf-8", errors="strict")
    return raw, profile


def _mapped_tag(tag: str) -> tuple[str, dict[str, str]]:
    direct = {
        "div": ("div", {"type": "source-html-div"}),
        "p": ("p", {}),
        "h1": ("head", {"type": "h1"}), "h2": ("head", {"type": "h2"}),
        "h3": ("head", {"type": "h3"}), "h4": ("head", {"type": "h4"}),
        "h5": ("head", {"type": "h5"}), "h6": ("head", {"type": "h6"}),
        "header": ("div", {"type": "provider-header"}),
        "footer": ("div", {"type": "provider-footer"}),
        "blockquote": ("quote", {}), "ul": ("list", {"type": "unordered"}),
        "ol": ("list", {"type": "ordered"}), "li": ("item", {}),
        "a": ("ref", {}), "img": ("graphic", {}), "br": ("lb", {}),
        "hr": ("milestone", {"unit": "source-rule"}), "table": ("table", {}),
        "tr": ("row", {}), "td": ("cell", {}), "th": ("cell", {"role": "label"}),
        "abbr": ("abbr", {}), "b": ("hi", {"rend": "bold"}),
        "strong": ("hi", {"rend": "strong"}), "i": ("hi", {"rend": "italic"}),
        "em": ("hi", {"rend": "emphasis"}), "sup": ("hi", {"rend": "superscript"}),
        "sub": ("hi", {"rend": "subscript"}), "span": ("seg", {}),
        "small": ("hi", {"rend": "small"}), "code": ("code", {}),
        "u": ("hi", {"rend": "underline"}),
    }
    if tag in {"tbody", "thead", "tfoot", "colgroup", "col"}:
        return "milestone", {"unit": f"source-html-{tag}"}
    if tag not in direct:
        raise ValueError(f"unmapped source HTML element: {tag}")
    mapped, attrs = direct[tag]
    return mapped, dict(attrs)


def _copy_element(source: etree._Element, parent: etree._Element, ordinal: int) -> etree._Element:
    if not isinstance(source.tag, str):
        comment = node(parent, "milestone", unit="source-html-comment", n=str(ordinal))
        comment.set("rend", "comment-digest:" + sha((source.text or "").encode("utf-8")))
        comment.tail = source.tail
        return comment
    mapped_tag, attrs = _mapped_tag(source.tag.lower())
    target = node(parent, mapped_tag, **attrs)
    target.set("n", str(ordinal))
    target.set(XML_ID, source.get("id") or f"source-node-{ordinal}")
    css = " ".join((source.get("class") or "").split())
    if css:
        target.set("rend", " ".join(filter(None, (target.get("rend"), "source-class:" + css))))
    if source.tag.lower() == "a" and source.get("href"):
        target.set("target", source.get("href"))
    if source.tag.lower() == "img":
        if not source.get("src"):
            raise ValueError("source image has no src")
        target.set("url", source.get("src"))
        if source.get("alt"):
            target.set("n", source.get("alt"))
    if source.tag.lower() in {"td", "th"} and source.get("colspan"):
        target.set("cols", source.get("colspan"))
    target.text = source.text
    for child_index, child in enumerate(source, 1):
        child_ordinal = int(child.get("data-ocd-ordinal", "0"))
        if not child_ordinal:
            child_ordinal = ordinal * 100000 + child_index
        _copy_element(child, target, child_ordinal)
    target.tail = source.tail
    return target


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    work_id = str(manifest.record["work_id"])
    book = BOOKS[work_id]
    raw, profile = source_html(manifest)
    source = html.fromstring(raw)
    source_body = source.find(".//body")
    if source_body is None:
        raise ValueError("source HTML has no body")
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    header = node(root, "teiHeader")
    file_desc = node(header, "fileDesc")
    title_stmt = node(file_desc, "titleStmt")
    node(title_stmt, "title").text = book["title"]
    node(title_stmt, "author").text = "John of Damascus" if book["ebook"] == "49917" else "Clement, Polycarp, Ignatius, Hermas, Papias, and other early Christian writers"
    node(title_stmt, "editor").text = "Alexander Roberts and James Donaldson" if book["ebook"] == "77576" else ""
    node(title_stmt, "editor").text = "" if book["ebook"] == "49917" else node(title_stmt, "editor").text
    node(title_stmt, "respStmt").text = "Translated by " + book["translator"]
    publication = node(file_desc, "publicationStmt")
    node(publication, "p").text = "Nonaccepted source reconstruction candidate. Project Gutenberg states public domain in the USA; no worldwide rights conclusion is recorded."
    source_desc = node(file_desc, "sourceDesc")
    node(source_desc, "p").text = f"Project Gutenberg eBook {book['ebook']}; source edition as identified in the electronic title page; retained archive SHA-256 {profile['archive_sha256']}."
    text = node(root, "text")
    body = node(text, "body", type="complete-gutenberg-html-body")
    body.text = source_body.text
    ordinal = 0
    for child in source_body:
        ordinal += 1
        child.set("data-ocd-ordinal", str(ordinal))
        _copy_element(child, body, ordinal)
    xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    account = {
        "contract": "ocd-gutenberg-complete-body-accountability-v1",
        "ebook_id": book["ebook"],
        "source_archive_sha256": profile["archive_sha256"],
        "source_html_sha256": profile["html_sha256"],
        "candidate_sha256": sha(xml),
        "candidate_bytes": len(xml),
        "archive_members": profile["archive_members"],
        "body_element_count": profile["body_element_count"],
        "body_direct_child_count": profile["body_direct_child_count"],
        "body_text_sha256": profile["body_text_sha256"],
        "mapping": "Every source body element appears in document order as a TEI element or an explicitly typed structural milestone. Headings, classes, links, anchor IDs, image path, list/table structures, punctuation, and mixed-inline order remain represented; the independent source profile retains all original attributes and carrier relationships.",
        "archive_support": "The complete ZIP member set, including unreferenced cover art, remains retained and hash-accounted. No archive member is silently dropped.",
        "html_head_policy": "HTML head stylesheet and provider metadata are retained in the source archive and feature profile; source body content is fully reconstructed.",
    }
    policy = json.loads(manifest.authority_path("policy").read_bytes())
    return {
        "README.source.md": manifest.authority_path("readme").read_bytes(),
        "content.tei.xml": xml,
        "source-accountability.json": encoded(account),
        "provenance.json": encoded(policy["provenance"]),
        "unresolved.jsonl": b"".join(encoded(item) for item in policy["unresolved"]),
    }


_convert.converter_id = "ocd-pg-49917-77576-complete-html-to-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
