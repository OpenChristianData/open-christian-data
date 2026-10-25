"""Reconstruct the complete retained PG76888 HTML body as readable TEI."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct


CONVERTER_ID = "ocd-before-most-holy-pg76888-extracted-html-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE = "raw/gutenberg/76888/html/pg76888-images.html"
SOURCE_SHA = "b3f452ee4a68ee4aae8613cb5b78f65f1f00e2d639ccc9a08e8b2e6b754ae626"
TAGS = {
    "header": "div", "footer": "div", "div": "div", "blockquote": "div",
    "ul": "list", "li": "item", "table": "table", "tbody": None,
    "tr": "row", "td": "cell", "th": "cell", "h1": "head", "h2": "head",
    "p": "p", "i": "hi", "strong": "hi", "span": "seg", "a": "ref",
    "br": "lb", "hr": "milestone",
}
INLINE = {"hi", "seg", "ref", "anchor", "lb"}


def _q(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _target_tag(node: etree._Element) -> str | None:
    if node.tag == "div":
        classes = (node.get("class") or "").split()
        if "verse" in classes:
            return "l"
        if "footnote" in classes:
            return "note"
    if node.tag == "a" and not node.get("href"):
        return "anchor" if not "".join(node.itertext()).strip() else "seg"
    return TAGS[node.tag]


def _source(manifest: SourceManifest) -> tuple[bytes, etree._Element]:
    members = manifest.record["source_members"]
    if len(members) != 1 or members[0]["path"] != SOURCE:
        raise ValueError("PG76888 extracted HTML source boundary differs")
    content = manifest.authority_path("retained-source").read_bytes()
    if len(content) != 245986 or _sha(content) != SOURCE_SHA:
        raise ValueError("PG76888 extracted HTML bytes differ")
    document = html.document_fromstring(content)
    body = document.find("body")
    if body is None or len(body) != 505 or len(list(body.iterdescendants())) != 2325:
        raise ValueError("PG76888 complete HTML body census differs")
    if any(node.tag not in TAGS for node in body.iterdescendants()):
        raise ValueError("PG76888 has an unmodeled body element")
    return content, body


def _header(root: etree._Element) -> None:
    header = etree.SubElement(root, _q("teiHeader"))
    desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = "Before the Most Holy = (Coram Sanctissimo)"
    etree.SubElement(title_stmt, _q("author")).text = "Mother Mary Loyola"
    editor = etree.SubElement(title_stmt, _q("respStmt"))
    etree.SubElement(editor, _q("resp")).text = "editor named on retained title page"
    etree.SubElement(editor, _q("name")).text = "Father Herbert Thurston, S.J."
    publication = etree.SubElement(desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("publisher")).text = "Open Christian Data (candidate package)"
    availability = etree.SubElement(publication, _q("availability"), status="restricted")
    etree.SubElement(availability, _q("p")).text = "Technical reconstruction only; rights and publication remain unresolved."
    source_desc = etree.SubElement(desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = "Before the Most Holy = (Coram Sanctissimo)"
    etree.SubElement(bibl, _q("idno"), type="project-gutenberg-ebook").text = "76888"
    revision = etree.SubElement(header, _q("revisionDesc"), status="candidate")
    etree.SubElement(revision, _q("change"), when="2026-09-27").text = "Exact retained HTML body reconstruction."


def _tei(body: etree._Element) -> bytes:
    root = etree.Element(_q("TEI"), nsmap={None: TEI})
    root.set(f"{{{XML}}}id", "before-most-holy-pg76888-candidate")
    _header(root)
    text = etree.SubElement(root, _q("text"))
    text.set(f"{{{XML}}}lang", "en")
    envelope = etree.SubElement(etree.SubElement(text, _q("body")), _q("div"), type="complete-html-body")
    envelope.text = body.text
    ordinal = 0

    def convert(source: etree._Element, parent: etree._Element) -> etree._Element | None:
        nonlocal ordinal
        ordinal += 1
        tag = _target_tag(source)
        if tag is None:
            parent.text = (parent.text or "") + (source.text or "")
            for child in source:
                mapped = convert(child, parent)
                if mapped is not None:
                    mapped.tail = child.tail
            return None
        target = etree.SubElement(parent, _q(tag))
        target.set(f"{{{XML}}}id", source.get("id") or f"src-{ordinal:05d}")
        classes = (source.get("class") or "").split()
        if tag == "div":
            target.set("type", "provider-" + source.tag if source.tag in {"header", "footer"} else
                       "source-blockquote" if source.tag == "blockquote" else "source-div")
            if classes:
                target.set("subtype", classes[0])
        elif tag == "note":
            target.set("type", "source-footnote")
        elif tag == "milestone":
            target.set("unit", "source-horizontal-rule")
        elif tag == "ref":
            target.set("target", source.get("href"))
        elif tag == "cell" and source.tag == "th":
            target.set("role", "label")
        rendition = ["italic" if source.tag == "i" else "bold"] if tag == "hi" else []
        rendition.extend(value for value in (source.get("class"), source.get("style")) if value)
        if rendition:
            target.set("rend", "; ".join(rendition))
        if source.get("lang") and tag not in {"milestone", "lb"}:
            target.set(f"{{{XML}}}lang", source.get("lang"))
        if tag == "div":
            if (source.text or "").strip():
                etree.SubElement(target, _q("ab"), type="source-block").text = source.text
            else:
                target.text = source.text
            for child in source:
                wrapper = etree.SubElement(target, _q("div"), type="source-child")
                child_tag = _target_tag(child)
                if child_tag in INLINE:
                    mapped = convert(child, etree.SubElement(wrapper, _q("ab"), type="source-block"))
                else:
                    mapped = convert(child, wrapper)
                if (child.tail or "").strip():
                    etree.SubElement(wrapper, _q("ab"), type="source-block").text = child.tail
                else:
                    wrapper.tail = child.tail
            return target
        target.text = source.text
        for child in source:
            mapped = convert(child, target)
            if mapped is not None:
                mapped.tail = child.tail
            elif child.tail:
                if len(target):
                    target[-1].tail = (target[-1].tail or "") + child.tail
                else:
                    target.text = (target.text or "") + child.tail
        return target

    for child in body:
        wrapper = etree.SubElement(envelope, _q("div"), type="html-body-carrier")
        if _target_tag(child) in INLINE:
            convert(child, etree.SubElement(wrapper, _q("ab"), type="source-block"))
        else:
            convert(child, wrapper)
        wrapper.tail = child.tail
    if ordinal != 2325:
        raise ValueError("PG76888 mapped source element count differs")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    content, body = _source(manifest)
    records: list[dict] = []
    identifiers: dict[etree._Element, str] = {}
    for ordinal, node in enumerate(body.iterdescendants(), 1):
        identifier = node.get("id") or f"src-{ordinal:05d}"
        identifiers[node] = identifier
        records.append(dict(
            tei_id=(None if node.tag == "tbody" else identifier), source_tag=node.tag,
            parent=identifiers.get(node.getparent(), "body"),
            attributes=dict(sorted(node.attrib.items())),
            text_sha256=_sha((node.text or "").encode("utf-8")),
            tail_sha256=_sha((node.tail or "").encode("utf-8")),
            subtree_text_sha256=_sha("".join(node.itertext()).encode("utf-8")),
            disposition="flattened-table-wrapper" if node.tag == "tbody" else "represented",
        ))
    account = dict(contract="ocd-before-most-holy-pg76888-accountability-v1",
                   work_id="before-the-most-holy", source_path=SOURCE,
                   source_sha256=_sha(content), source_bytes=len(content),
                   top_level_elements=len(body), body_elements=len(records),
                   represented_elements=len(records) - 1, flattened_wrappers=1,
                   omitted_elements=0, body_text_sha256=_sha("".join(body.itertext()).encode("utf-8")),
                   crosswalk=records)
    provenance = dict(contract="ocd-before-most-holy-pg76888-provenance-v1",
                      work_id="before-the-most-holy", extracted_html_sha256=_sha(content),
                      source_authority="extracted-html", zip_role="retained-package",
                      cover_role="unreferenced-support", candidate_status="nonaccepted",
                      human_review="not-recorded", rights="not-assessed-for-publication")
    unresolved = dict(id="before-most-holy-pg76888-unresolved", status="unresolved",
                      items=["Print collation and whole-work visual review are unrecorded.",
                             "Jurisdictional rights and publication remain separate."])
    return {"content.tei.xml": _tei(body),
            "source-accountability.json": _canonical(account),
            "provenance.json": _canonical(provenance),
            "unresolved.jsonl": _canonical(unresolved),
            "README.source.md": manifest.authority_path("source-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(manifest: SourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(manifest, destination, _convert)
