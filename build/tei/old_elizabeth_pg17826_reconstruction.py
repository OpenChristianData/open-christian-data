"""Reconstruct the complete retained PG17826 HTML body as source-bound TEI."""

from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct


CONVERTER_ID = "ocd-old-elizabeth-pg17826-extracted-html-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
TAGS = {
    "header": ("div", "source-header"), "footer": ("div", "source-footer"),
    "div": ("div", "source-div"), "blockquote": ("div", "source-blockquote"),
    "ul": ("div", "source-list"), "p": ("p", None), "li": ("p", "source-item"),
    "h1": ("head", None), "h2": ("head", None), "h3": ("head", None),
    "h4": ("head", None),
    "i": ("hi", "italic"), "strong": ("hi", "bold"), "span": ("seg", None),
    "a": ("ref", None), "br": ("lb", None), "pre": ("ab", "preformatted"),
    "hr": ("milestone", None), "img": ("graphic", None),
}


def _q(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _source(manifest: SourceManifest) -> tuple[bytes, etree._Element, bytes]:
    members = manifest.record["source_members"]
    if len(members) != 1 or members[0]["path"] != "raw/gutenberg/17826/html/pg17826-images.html":
        raise ValueError("Old Elizabeth extracted HTML source boundary differs")
    content = (manifest.repository_root / members[0]["path"]).read_bytes()
    if len(content) != members[0]["bytes"] or _sha(content) != members[0]["sha256"]:
        raise ValueError("Old Elizabeth extracted HTML source bytes differ")
    body = html.document_fromstring(content).find("body")
    if body is None or len(body) != 56 or len(list(body.iterdescendants())) != 186:
        raise ValueError("Old Elizabeth complete HTML body boundary differs")
    images = [node for node in body.iterdescendants() if node.tag == "img"]
    if len(images) != 1 or images[0].get("src") != "images/image_01.jpg":
        raise ValueError("Old Elizabeth referenced image boundary differs")
    image = manifest.authority_path("referenced-image").read_bytes()
    if len(image) != 27606 or _sha(image) != "338defe78365ba25b3cc15f4af5bd540fd2061f57ad81fe26254a68d4f601133":
        raise ValueError("Old Elizabeth referenced image bytes differ")
    return content, body, image


def _header(root: etree._Element) -> None:
    header = etree.SubElement(root, _q("teiHeader"))
    desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = "Memoir of Old Elizabeth, A Coloured Woman"
    etree.SubElement(title_stmt, _q("author")).text = "Old Elizabeth"
    publication = etree.SubElement(desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("publisher")).text = "Open Christian Data (candidate package)"
    availability = etree.SubElement(publication, _q("availability"), status="restricted")
    etree.SubElement(availability, _q("p")).text = "Technical reconstruction only; rights and publication remain unresolved."
    source_desc = etree.SubElement(desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = "Memoir of Old Elizabeth, A Coloured Woman"
    etree.SubElement(bibl, _q("note"), type="source-imprint").text = "Philadelphia: Collins, printer, 705 Jayne Street, 1863."
    etree.SubElement(bibl, _q("idno"), type="project-gutenberg-ebook").text = "17826"
    revision = etree.SubElement(header, _q("revisionDesc"), status="candidate")
    etree.SubElement(revision, _q("change"), when="2026-09-27").text = "Exact retained HTML body reconstruction."


def _tei(body: etree._Element, image: bytes) -> bytes:
    root = etree.Element(_q("TEI"), nsmap={None: TEI})
    root.set(f"{{{XML}}}id", "old-elizabeth-pg17826-current-candidate")
    _header(root)
    text = etree.SubElement(root, _q("text"))
    envelope = etree.SubElement(etree.SubElement(text, _q("body")), _q("div"), type="complete-html-body")
    ordinal = 0

    def convert(source: etree._Element, parent: etree._Element) -> etree._Element:
        nonlocal ordinal
        ordinal += 1
        tag, kind = TAGS[source.tag]
        if source.tag == "a" and source.get("href") is None:
            tag, kind = "seg", "page-anchor"
        target = etree.SubElement(parent, _q(tag))
        target.set(f"{{{XML}}}id", f"src-{ordinal:05d}")
        if kind is not None:
            target.set("type" if tag in {"div", "ab", "seg"} else "rend", kind if tag != "ab" else "source-block")
            if tag == "ab":
                target.set("subtype", "preformatted")
        if source.get("id"):
            target.set("n", source.get("id"))
        if source.get("lang"):
            target.set(f"{{{XML}}}lang", source.get("lang"))
        if tag == "ref":
            target.set("target", source.get("href"))
        if tag == "graphic":
            target.set("url", "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"))
            target.set("corresp", source.get("src"))
        if tag == "milestone":
            target.set("unit", "source-horizontal-rule")
        is_div = tag == "div"
        if is_div and (source.text or "").strip():
            etree.SubElement(target, _q("ab"), type="source-block", subtype="direct-text").text = source.text
        else:
            target.text = source.text
        for child in source:
            if is_div:
                wrapper = etree.SubElement(target, _q("div"), type="source-child")
                child_parent = wrapper
                if TAGS[child.tag][0] in {"hi", "seg", "ref", "lb", "graphic", "milestone"}:
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
        if TAGS[child.tag][0] in {"hi", "seg", "ref", "lb", "graphic", "milestone"}:
            child_parent = etree.SubElement(wrapper, _q("ab"), type="source-block", subtype="inline")
        convert(child, child_parent)
        wrapper.tail = child.tail
    if ordinal != 186:
        raise ValueError("Old Elizabeth HTML carrier count differs")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    content, body, image = _source(manifest)
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
        "contract": "ocd-old-elizabeth-pg17826-current-accountability-v1", "work_id": "old-elizabeth-memoir",
        "source_path": "raw/gutenberg/17826/html/pg17826-images.html", "source_sha256": _sha(content),
        "source_bytes": len(content), "top_level_elements": len(body), "represented_elements": len(records),
        "omitted_elements": 0, "body_text_sha256": _sha("".join(body.itertext()).encode("utf-8")),
        "referenced_image_path": "raw/gutenberg/17826/html/images/image_01.jpg",
        "referenced_image_sha256": _sha(image), "referenced_image_bytes": len(image),
        "crosswalk": records,
    }
    provenance = {
        "contract": "ocd-old-elizabeth-pg17826-current-provenance-v1", "work_id": "old-elizabeth-memoir",
        "extracted_html_sha256": _sha(content), "source_authority": "extracted-html",
        "zip_role": "retained-package", "cover_role": "unreferenced-support",
        "referenced_image_sha256": _sha(image), "candidate_status": "nonaccepted",
        "human_review": "not-recorded", "rights": "not-assessed-for-publication",
    }
    unresolved = {
        "id": "old-elizabeth-pg17826-current-boundaries", "status": "unresolved", "items": [
            "The title page names Collins as printer; a distinct publisher has not been established.",
            "Jurisdictional rights and publication are not cleared.",
            "Human visual review and textual acceptance are not recorded.",
        ],
    }
    return {
        "content.tei.xml": _tei(body, image), "source-accountability.json": _canonical(account),
        "provenance.json": _canonical(provenance), "unresolved.jsonl": _canonical(unresolved),
        "README.source.md": manifest.authority_path("source-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(manifest: SourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(manifest, destination, _convert)
