"""Reconstruct the complete retained PG20005 HTML body as readable TEI."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct


CONVERTER_ID = "ocd-manifest-pg-l640-noah-davis-html-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE = "raw/gutenberg/20005/html/pg20005-images.html"
SOURCE_SHA = "b9f2a2c13098e7576f20180a2c81f001a836823c29a02e380f4123dfbade407f"
TAGS = {
    "header": "div", "footer": "div", "div": "div", "blockquote": "div", "pre": "ab",
    "ul": "list", "li": "item", "table": "table", "tbody": None,
    "tr": "row", "td": "cell", "th": "cell", "h1": "head", "h2": "head", "h3": "head",
    "h4": "head", "h5": "head", "h6": "head",
    "p": "p", "i": "hi", "strong": "hi", "b": "hi", "sup": "hi",
    "small": "hi", "span": "seg", "a": "ref", "img": "figure",
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
        if "pagenum" in classes:
            return "div"
    if node.tag == "a" and not node.get("href"):
        return "anchor" if not "".join(node.itertext()).strip() else "seg"
    return TAGS[node.tag]


def _source(manifest: SourceManifest) -> tuple[bytes, etree._Element]:
    members = manifest.record["source_members"]
    if len(members) != 1 or members[0]["path"] != SOURCE:
        raise ValueError("PG20005 extracted HTML source boundary differs")
    content = manifest.authority_path("retained-source").read_bytes()
    if len(content) != 142389 or _sha(content) != SOURCE_SHA:
        raise ValueError("PG20005 extracted HTML bytes differ")
    document = html.document_fromstring(content)
    body = document.find("body")
    if body is None or len(body) != 359 or len(list(body.iterdescendants())) != 899:
        raise ValueError("PG20005 complete HTML body census differs")
    if any(node.tag not in TAGS for node in body.iterdescendants()):
        raise ValueError("PG20005 has an unmodeled body element")
    return content, body


def _header(root: etree._Element) -> None:
    header = etree.SubElement(root, _q("teiHeader"))
    desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = "A Narrative of the Life of Rev. Noah Davis, A Colored Man"
    etree.SubElement(title_stmt, _q("author")).text = "Rev. Noah Davis"
    publication = etree.SubElement(desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("publisher")).text = "Open Christian Data (candidate package)"
    availability = etree.SubElement(publication, _q("availability"), status="restricted")
    etree.SubElement(availability, _q("p")).text = "Technical reconstruction only; rights and publication remain unresolved."
    source_desc = etree.SubElement(desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = "A Narrative of the Life of Rev. Noah Davis, A Colored Man"
    etree.SubElement(bibl, _q("idno"), type="project-gutenberg-ebook").text = "20005"
    revision = etree.SubElement(header, _q("revisionDesc"), status="candidate")
    etree.SubElement(revision, _q("change"), when="2026-09-30").text = "Exact retained HTML body reconstruction."


def _tei(body: etree._Element) -> bytes:
    root = etree.Element(_q("TEI"), nsmap={None: TEI})
    root.set(f"{{{XML}}}id", "noah-davis-pg20005-candidate")
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
        # TEI table cells contain phrase-level content. Gutenberg's title page
        # uses nested divs inside a cell; retain their identity as segments.
        if source.tag == "div" and any(ancestor.tag in {"td", "th"} for ancestor in source.iterancestors()):
            tag = "seg"
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
                       "source-blockquote" if source.tag == "blockquote" else
                       "source-figure" if source.get("role") == "figure" else "source-div")
            if classes:
                target.set("subtype", classes[0])
            if source.get("aria-labelledby"):
                target.set("corresp", "#" + source.get("aria-labelledby"))
        elif tag == "note":
            target.set("type", "source-footnote")
        elif tag == "milestone":
            target.set("unit", "source-horizontal-rule")
        elif tag == "ref":
            target.set("target", source.get("href"))
        elif tag == "figure":
            graphic = etree.SubElement(
                target,
                _q("graphic"),
                url="raw/gutenberg/20005/html/" + source.get("src"),
            )
            for name in ("width", "height", "alt"):
                if source.get(name):
                    graphic.set("n" if name == "alt" else name,
                                source.get(name) if name == "alt" else source.get(name) + "px")
        elif tag == "cell" and source.tag == "th":
            target.set("role", "label")
        if source.get("title"):
            target.set("n", source.get("title"))
        if source.get("data-summary"):
            target.set("n", source.get("data-summary"))
        rendition = (["italic"] if source.tag == "i" else ["bold"] if source.tag in {"strong", "b"}
                     else ["superscript"] if source.tag == "sup"
                     else ["small"] if source.tag == "small" else []) if tag == "hi" else []
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
    if ordinal != 899:
        raise ValueError("PG20005 mapped source element count differs")
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
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    archive_members = profile["source"]["members"]
    account = dict(
        contract="ocd-manifest-pg-l640-noah-davis-accountability-v1",
        work_id="noah-davis-narrative-life-1859",
        edition_id="noah-davis-narrative-life-1859-pg20005",
        acquisition_id="pg20005-retained-zip",
        source_path=SOURCE,
        source_sha256=_sha(content),
        source_bytes=len(content),
        archive_sha256=profile["source"]["archive_sha256"],
        archive_members=archive_members,
        top_level_elements=len(body),
        body_elements=len(records),
        represented_elements=len(records),
        flattened_wrappers=sum(node.tag == "tbody" for node in body.iterdescendants()),
        omitted_elements=0,
        body_text_sha256=_sha("".join(body.itertext()).encode("utf-8")),
        body_image_references=[node.get("src") for node in body.xpath(".//img")],
        crosswalk=records,
    )
    provenance = dict(
        contract="ocd-manifest-pg-l640-noah-davis-provenance-v1",
        work_id="noah-davis-narrative-life-1859",
        edition_id="noah-davis-narrative-life-1859-pg20005",
        acquisition_id="pg20005-retained-zip",
        extracted_html_sha256=_sha(content),
        source_authority="extracted-html",
        zip_role="retained-package",
        linked_church_image_role="referenced-body-image",
        cover_role="unreferenced-support",
        candidate_status="nonaccepted",
        human_review="not-recorded",
        rights="not-assessed-for-publication",
        publication="not-authorized",
    )
    unresolved = dict(
        id="pg20005-l640-unresolved",
        status="unresolved",
        items=[
            {"id": "print-collation", "status": "unresolved",
             "detail": "No print exemplar collation has been performed."},
            {"id": "visual-review", "status": "unresolved",
             "detail": "No whole-work visual source-to-TEI review is recorded."},
            {"id": "human-acceptance", "status": "unresolved",
             "detail": "Candidate is nonaccepted."},
            {"id": "rights", "status": "unresolved",
             "detail": "Item-level and jurisdictional rights review remains pending."},
            {"id": "publication", "status": "not-authorized",
             "detail": "No publication authorization is recorded."},
            {"id": "html-head", "status": "dispositioned-support",
             "detail": "The complete HTML member hash binds the head; head markup is metadata/support and is outside the body reconstruction."},
        ],
    )
    return {"content.tei.xml": _tei(body),
            "source-accountability.json": _canonical(account),
            "provenance.json": _canonical(provenance),
            "unresolved.jsonl": _canonical(unresolved),
            "README.source.md": manifest.authority_path("source-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(manifest: SourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(manifest, destination, _convert)
