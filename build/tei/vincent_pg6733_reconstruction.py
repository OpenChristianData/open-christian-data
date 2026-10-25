"""Reconstruct the complete retained PG6733 HTML body as source-bound TEI."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct


CONVERTER_ID = "ocd-vincent-pg6733-extracted-html-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
TAGS = {
    "header": ("div", "source-header"), "footer": ("div", "source-footer"),
    "div": ("div", "source-div"), "blockquote": ("div", "source-blockquote"),
    "ul": ("div", "source-list"), "p": ("p", None), "li": ("p", "source-item"),
    "h2": ("head", None), "h4": ("head", None), "h5": ("head", None),
    "i": ("hi", "italic"), "strong": ("hi", "bold"), "span": ("seg", None),
    "a": ("ref", None), "br": ("lb", None),
}


def _q(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _source(manifest: SourceManifest) -> tuple[bytes, etree._Element]:
    members = manifest.record["source_members"]
    if len(members) != 1 or members[0]["path"] != "raw/gutenberg/6733/html/pg6733-images.html":
        raise ValueError("Vincent extracted HTML source boundary differs")
    content = (manifest.repository_root / members[0]["path"]).read_bytes()
    if len(content) != members[0]["bytes"] or _sha(content) != members[0]["sha256"]:
        raise ValueError("Vincent extracted HTML source bytes differ")
    body = html.document_fromstring(content).find("body")
    if body is None or len(body) != 98 or len(list(body.iterdescendants())) != 202:
        raise ValueError("Vincent complete HTML body boundary differs")
    return content, body


def _header(root: etree._Element) -> None:
    header = etree.SubElement(root, _q("teiHeader"))
    desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = "Memoir of Father Vincent de Paul; religious of La Trappe"
    etree.SubElement(title_stmt, _q("author")).text = "Father Vincent de Paul"
    etree.SubElement(title_stmt, _q("editor")).text = "A. M. Pope, translator from the original French"
    preface = etree.SubElement(title_stmt, _q("respStmt"))
    etree.SubElement(preface, _q("resp")).text = "author of preface"
    etree.SubElement(preface, _q("name")).text = "John Cameron, Bishop of Arichat"
    publication = etree.SubElement(desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("publisher")).text = "Open Christian Data (candidate package)"
    availability = etree.SubElement(publication, _q("availability"), status="restricted")
    etree.SubElement(availability, _q("p")).text = "Technical reconstruction only; rights and publication remain unresolved."
    source_desc = etree.SubElement(desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = "Memoir of Father Vincent de Paul; religious of La Trappe"
    etree.SubElement(bibl, _q("idno"), type="project-gutenberg-ebook").text = "6733"
    revision = etree.SubElement(header, _q("revisionDesc"), status="candidate")
    etree.SubElement(revision, _q("change"), when="2026-09-27").text = "Exact retained HTML body reconstruction."


def _tei(body: etree._Element) -> bytes:
    root = etree.Element(_q("TEI"), nsmap={None: TEI})
    root.set(f"{{{XML}}}id", "vincent-pg6733-current-candidate")
    _header(root)
    text = etree.SubElement(root, _q("text"))
    envelope = etree.SubElement(etree.SubElement(text, _q("body")), _q("div"), type="complete-html-body")
    ordinal = 0

    def convert(source: etree._Element, parent: etree._Element) -> etree._Element:
        nonlocal ordinal
        ordinal += 1
        tag, kind = TAGS[source.tag]
        target = etree.SubElement(parent, _q(tag))
        target.set(f"{{{XML}}}id", f"src-{ordinal:05d}")
        if kind is not None:
            target.set("type" if tag == "div" else "rend", kind)
        if source.get("id"):
            target.set("n", source.get("id"))
        if source.get("lang"):
            target.set(f"{{{XML}}}lang", source.get("lang"))
        if tag == "ref":
            target.set("target", source.get("href"))
        is_div = tag == "div"
        if is_div and (source.text or "").strip():
            etree.SubElement(target, _q("ab"), type="source-block", subtype="direct-text").text = source.text
        else:
            target.text = source.text
        for child in source:
            if is_div:
                wrapper = etree.SubElement(target, _q("div"), type="source-child")
                child_parent = wrapper
                if TAGS[child.tag][0] in {"hi", "seg", "ref", "lb"}:
                    child_parent = etree.SubElement(wrapper, _q("ab"), type="source-block", subtype="inline")
            else:
                wrapper = target
                child_parent = target
            converted = convert(child, child_parent)
            if is_div and (child.tail or "").strip():
                tail_wrapper = etree.SubElement(target, _q("div"), type="source-child-tail")
                etree.SubElement(tail_wrapper, _q("ab"), type="source-block", subtype="child-tail").text = child.tail
            else:
                (wrapper if is_div else converted).tail = child.tail
        return target

    for child in body:
        wrapper = etree.SubElement(envelope, _q("div"), type="html-body-carrier")
        child_parent = wrapper
        if TAGS[child.tag][0] in {"hi", "seg", "ref", "lb"}:
            child_parent = etree.SubElement(wrapper, _q("ab"), type="source-block", subtype="inline")
        convert(child, child_parent)
        wrapper.tail = child.tail
    if ordinal != 202:
        raise ValueError("Vincent HTML carrier count differs")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    content, body = _source(manifest)
    records = []
    identifiers: dict[etree._Element, str] = {}
    for ordinal, node in enumerate(body.iterdescendants(), 1):
        identifier = f"src-{ordinal:05d}"
        identifiers[node] = identifier
        records.append({
            "id": identifier, "tag": node.tag, "parent": identifiers.get(node.getparent(), "body"),
            "attributes": dict(sorted(node.attrib.items())),
            "text_sha256": _sha((node.text or "").encode("utf-8")),
            "tail_sha256": _sha((node.tail or "").encode("utf-8")),
            "subtree_text_sha256": _sha("".join(node.itertext()).encode("utf-8")),
        })
    account = {
        "contract": "ocd-vincent-pg6733-current-accountability-v1", "work_id": "memoir-of-father-vincent-de-paul",
        "source_path": "raw/gutenberg/6733/html/pg6733-images.html", "source_sha256": _sha(content),
        "source_bytes": len(content), "top_level_elements": len(body), "represented_elements": len(records),
        "omitted_elements": 0, "body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
        "crosswalk": records,
    }
    provenance = {
        "contract": "ocd-vincent-pg6733-current-provenance-v1", "work_id": "memoir-of-father-vincent-de-paul",
        "extracted_html_sha256": _sha(content), "source_authority": "extracted-html",
        "zip_role": "retained-package-and-unreferenced-cover-support", "candidate_status": "nonaccepted",
        "human_review": "not-recorded", "rights": "not-assessed-for-publication",
    }
    unresolved = {
        "id": "vincent-pg6733-current-boundaries", "status": "unresolved", "items": [
            "Print publisher is not identified in the retained title page.",
            "Jurisdictional rights and publication are not cleared.",
            "Human visual review and textual acceptance are not recorded.",
        ],
    }
    return {
        "content.tei.xml": _tei(body), "source-accountability.json": _canonical(account),
        "provenance.json": _canonical(provenance), "unresolved.jsonl": _canonical(unresolved),
        "README.source.md": manifest.authority_path("source-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(manifest: SourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(manifest, destination, _convert)
