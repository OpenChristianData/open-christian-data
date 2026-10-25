"""Work-specific source-bound TEI route for LIB-089 entry 37c-300."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest

_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_REPRESENTED_COLUMNS = (1, 2, 3, 6, 9, 12)
_DISPOSITIONS = {
    1: "represented-contents",
    2: "represented-preface",
    3: "represented-introductory-text",
    4: "excluded-back-navigation",
    5: "excluded-empty-spacer",
    6: "represented-practical-use",
    7: "excluded-back-navigation",
    8: "excluded-empty-spacer",
    9: "represented-warrants",
    10: "excluded-back-navigation",
    11: "excluded-empty-spacer",
    12: "represented-evidences",
    13: "excluded-back-navigation",
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _producer_closure(root: Path) -> str:
    """Bind this producer and its repository-local reconstruction imports."""
    root = root.resolve()
    members = (
        root / "build/tei/sum_saving_knowledge_reconstruction.py",
        root / "ocd_kernel/reconstruction/contract.py",
        root / "ocd_kernel/reconstruction/__init__.py",
    )
    rows = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(members, key=lambda path: path.as_posix())
    ]
    return _sha(_canonical(rows))


def _text(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _mapping(node: etree._Element) -> tuple[str, dict[str, str]]:
    tag = str(node.tag).lower()
    if tag == "div":
        return "div", {"type": "html-div"}
    if tag in {"h1", "h2", "h3"}:
        return "div", {"type": "source-heading"}
    if tag == "p":
        return "p", {}
    if tag in {"strong", "b", "em"}:
        return "hi", {"rend": "italic" if tag == "em" else "bold", "ana": f"html-{tag}"}
    if tag == "br":
        return "lb", {}
    if tag == "a":
        attrs = {"type": "html-a"}
        if node.get("href") is not None:
            attrs["target"] = str(node.get("href"))
            return "ref", attrs
    if tag == "ol":
        return "list", {"type": "ordered"}
    if tag == "li":
        return "item", {}
    raise ValueError(f"unsupported source element in selected Sum text: {tag}")


def _project(parent: etree._Element, node: etree._Element, events: list[dict[str, object]], tree: etree._ElementTree, slug: str) -> None:
    name, attrs = _mapping(node)
    target = etree.SubElement(parent, f"{{{_TEI}}}{name}", attrs)
    ordinal = len(events) + 1
    target.set(_XML_ID, f"{slug}-node-{ordinal:05d}")
    events.append({
        "ordinal": ordinal,
        "source_xpath": tree.getpath(node),
        "source_tag": str(node.tag).lower(),
        "source_attributes": dict(sorted((str(k), str(v)) for k, v in node.attrib.items())),
        "direct_text_sha256": _sha((node.text or "").encode("utf-8")),
        "tail_sha256": _sha((node.tail or "").encode("utf-8")),
        "tei_xml_id": target.get(_XML_ID),
        "tei_tag": name,
        "tei_attributes": {etree.QName(k).localname: v for k, v in sorted(target.attrib.items()) if k != _XML_ID},
        "disposition": "represented",
    })
    if str(node.tag).lower() == "div" and any(str(child.tag).lower() in {"h1", "h2", "h3"} for child in node):
        target.text = node.text
        for child in node:
            if not isinstance(child.tag, str):
                raise ValueError("comments inside represented text are unsupported")
            flow = etree.SubElement(target, f"{{{_TEI}}}div", {"type": "source-flow"})
            _project(flow, child, events, tree, slug)
            flow.tail = child.tail
        return
    if str(node.tag).lower() in {"h1", "h2", "h3"}:
        heading = etree.SubElement(target, f"{{{_TEI}}}head")
        heading.text = node.text
        for child in node:
            if not isinstance(child.tag, str):
                raise ValueError("comments inside represented text are unsupported")
            _project(heading, child, events, tree, slug)
            heading[-1].tail = child.tail
        return
    target.text = node.text
    for child in node:
        if not isinstance(child.tag, str):
            raise ValueError("comments inside represented text are unsupported")
        _project(target, child, events, tree, slug)
        target[-1].tail = child.tail


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_text(encoding="utf-8"))
    raw = source_manifest.authority_path("retained-html").read_bytes()
    if profile.get("work_id") != "sum-of-saving-knowledge" or _sha(raw) != profile.get("source_sha256"):
        raise ValueError("37c-300 source/profile identity mismatch")
    doc = html.document_fromstring(raw).getroottree()
    columns = doc.xpath("/html/body/div[4]/div[2]/div//div[contains(concat(' ',normalize-space(@class),' '),' wpb_text_column ')]")
    if len(columns) != len(_DISPOSITIONS):
        raise ValueError("37c-300 text-column census changed")
    rows = []
    for index, node in enumerate(columns, 1):
        disposition = _DISPOSITIONS[index]
        rows.append({"index": index, "source_xpath": doc.getpath(node), "disposition": disposition,
                     "subtree_sha256": _sha(etree.tostring(node, encoding="utf-8", with_tail=False)),
                     "normalized_text_sha256": _sha(_text(node).encode("utf-8")),
                     "element_count": sum(isinstance(item.tag, str) for item in node.iter()),
                     "word_count": len(_text(node).split())})
        if disposition == "excluded-empty-spacer" and _text(node):
            raise ValueError("37c-300 declared empty spacer contains text")
        if disposition == "excluded-back-navigation" and _text(node) != "Back to the Top.":
            raise ValueError("37c-300 back-navigation text changed")
    if [i for i, row in enumerate(rows, 1) if row["disposition"].startswith("represented-")] != list(_REPRESENTED_COLUMNS):
        raise ValueError("37c-300 represented-column census changed")

    slug = "sum-of-saving-knowledge"
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, f"{slug}-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    fd = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    ts = etree.SubElement(fd, f"{{{_TEI}}}titleStmt")
    etree.SubElement(ts, f"{{{_TEI}}}title").text = "The Sum of Saving Knowledge"
    ps = etree.SubElement(fd, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(ps, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    av = etree.SubElement(ps, f"{{{_TEI}}}availability", status="restricted")
    etree.SubElement(av, f"{{{_TEI}}}p").text = "Nonaccepted technical candidate; publication is not authorized."
    sd = etree.SubElement(fd, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(sd, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = "The Sum of Saving Knowledge – The Westminster Standard"
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="sha256").text = _sha(raw)
    enc = etree.SubElement(header, f"{{{_TEI}}}encodingDesc")
    etree.SubElement(enc, f"{{{_TEI}}}p").text = profile["scope_note"]
    body = etree.SubElement(etree.SubElement(root, f"{{{_TEI}}}text"), f"{{{_TEI}}}body")
    events: list[dict[str, object]] = []
    for idx in _REPRESENTED_COLUMNS:
        source_col = columns[idx - 1]
        wrapper = etree.SubElement(body, f"{{{_TEI}}}div", type="source-column", n=str(idx))
        wrapper.set(_XML_ID, f"{slug}-column-{idx:02d}")
        if source_col.text:
            wrapper.text = source_col.text
        for child in source_col:
            if not isinstance(child.tag, str):
                raise ValueError("comment in represented source column")
            _project(wrapper, child, events, doc, slug)
            wrapper[-1].tail = child.tail
    represented = [row for row in rows if row["disposition"].startswith("represented-")]
    accounting = {"contract": "ocd-37c-300-html-accounting-v1", "ticket_id": "37c-300", "work_id": slug,
                  "source": {"path": source_manifest.record["retained_source_path"], "bytes": len(raw), "sha256": _sha(raw)},
                  "document_element_count": sum(isinstance(n.tag, str) for n in doc.iter()),
                  "document_comment_count": sum(not isinstance(n, etree._Element) or not isinstance(n.tag, str) for n in doc.iter()),
                  "document_element_census": dict(sorted(Counter(str(n.tag).lower() for n in doc.iter() if isinstance(n.tag, str)).items())),
                  "document_envelope": {"doctype": doc.docinfo.doctype, "root": str(doc.getroot().tag).lower(),
                                        "head_count": len(doc.xpath("/html/head")), "body_count": len(doc.xpath("/html/body")),
                                        "script_count": len(doc.xpath("//script")), "style_count": len(doc.xpath("//style")),
                                        "work_content_xpath": "/html/body/div[4]/div[2]/div",
                                        "outside_work_text": "retained and hash-bound; site shell/support material is not represented as work text"},
                  "text_columns": rows, "represented_column_count": len(represented),
                  "excluded_column_count": len(rows)-len(represented), "source_events": events,
                  "legacy_json_used_as_authority": False,
                  "identity_status": "work, textual form, edition, parts, and witness authority unresolved"}
    provenance = {"contract": "ocd-37c-300-candidate-provenance-v1", "ticket_id": "37c-300", "work_id": slug,
                  "status": "nonaccepted", "publication": False, "source_manifest_sha256": source_manifest.sha256,
                  "identity": "observed page title only; authorship and edition are not adopted", "rights": "unresolved",
                  "canonical_data_or_ir_written": False}
    unresolved = [
        {"id": slug+"-identity", "kind": "identity", "status": "unresolved", "detail": "Work, textual form, edition, parts, and witness authority are not settled by this route."},
        {"id": slug+"-rights", "kind": "rights", "status": "unresolved", "detail": "No rights or attribution decision is made."},
        {"id": slug+"-acceptance", "kind": "acceptance", "status": "unresolved", "detail": "Human textual acceptance has not occurred."},
    ]
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False),
            "source-accountability.json": _canonical(accounting), "provenance.json": _canonical(provenance),
            "unresolved.jsonl": b"".join(_canonical(row) for row in unresolved),
            "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes()}


_convert.converter_id = "ocd-37c-300-sum-saving-knowledge-html-to-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
