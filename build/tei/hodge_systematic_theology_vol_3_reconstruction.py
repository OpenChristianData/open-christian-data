"""Ticket-local, fail-closed TEI projection for Hodge Volume III."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from lxml import etree
from ocd_kernel.tei.writer import tei_el


WORK_ID = "hodge-systematic-theology-vol-3"
SOURCE_KEY = "retained-hodge-vol-3"  # gitleaks:allow
SOURCE_PATH = "raw/ccel/hodge/theology3.xml"
SOURCE_BYTES = 3_102_428
SOURCE_SHA256 = "aeb92566e8ce5019f6f43c56585538c67bafcea177d9d6f1df286006f24dda54"
TAGS = {
    "div": "quote", "div1": "div", "div2": "div", "div3": "div",
    "h1": "p", "h2": "p", "h3": "p", "h4": "p",
    "p": "p", "i": "hi", "span": "seg", "note": "note", "pb": "pb",
    "scripRef": "ref", "verse": "lg", "l": "l", "table": "table",
    "tr": "row", "td": "cell", "th": "cell", "colgroup": "row",
    "col": "cell", "ul": "list", "li": "item", "a": "ref",
    "br": "lb", "insertIndex": "milestone",
}


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _parse(raw: bytes) -> etree._ElementTree:
    return etree.parse(io.BytesIO(raw), etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, remove_pis=False, huge_tree=True))


def _convert(manifest):
    manifest.verify()
    authority = next(a for a in manifest.record["authorities"] if a["name"] == SOURCE_KEY)
    raw = manifest.authority_path(SOURCE_KEY).read_bytes()
    if len(raw) != SOURCE_BYTES or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("37c-205 retained source identity drift")
    tree = _parse(raw)
    source_root = tree.getroot()
    body = source_root.find("ThML.body")
    roots = list(body) if body is not None else []
    if [(n.get("id"), n.get("title")) for n in roots] != [("i", "Title"), ("ii", "Prefatory"), ("iii", "Part III. Continued."), ("iv", "Part IV. Eschatology."), ("v", "Indexes")]:
        raise ValueError("37c-205 complete five-root source envelope drift")
    tei = tei_el("TEI", {"xml:id": WORK_ID})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text="Systematic Theology, Vol. 3"))
    title_stmt.append(tei_el("author", text="Charles Hodge"))
    file_desc.append(title_stmt)
    pub = tei_el("publicationStmt")
    pub.append(tei_el("publisher", text="Christian Classics Ethereal Library"))
    availability = tei_el("availability", {"status": "unknown"})
    availability.append(tei_el("p", text="Rights status not assessed; this record is not a rights decision."))
    pub.append(availability)
    file_desc.append(pub)
    bibl = tei_el("bibl")
    bibl.append(tei_el("title", text="Systematic Theology - Volume III"))
    bibl.append(tei_el("note", {"type": "edition-claim-unresolved"}, text="The retained source identifies the CCEL electronic witness; the configured 1872-1873 print-edition claim is not established here and is not adopted."))
    source_desc = tei_el("sourceDesc")
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)
    text = tei_el("text", {"xml:lang": "en"})
    target_body = tei_el("body", {"xml:id": WORK_ID + "-body"})
    text.append(target_body)
    tei.append(text)
    rows = []

    def emit(node, parent):
        if not isinstance(node.tag, str):
            if node.tag is etree.Comment:
                child = etree.Comment(node.text or ""); child.tail = node.tail; parent.append(child); return
            raise ValueError("37c-205 source contains unsupported non-element node")
        if node.tag not in TAGS:
            raise ValueError(f"37c-205 unsupported retained source tag: {node.tag}")
        attrs = {"xml:id": f"{WORK_ID}-feature-{len(rows)+1:06d}"}
        for source, dest in (("n", "n"), ("class", "rend"), ("osisRef", "target"), ("passage", "cRef"), ("href", "target"), ("style", "rend")):
            if node.get(source): attrs[dest] = node.get(source)
        if node.tag == "i": attrs["rend"] = "italic"
        if node.tag in ("h1", "h2", "h3", "h4"): attrs["rend"] = "source-" + node.tag
        if node.tag == "verse": attrs["type"] = "source-verse"
        if node.tag == "insertIndex": attrs["unit"] = "insertIndex"
        out = tei_el(TAGS[node.tag], attrs)
        out.text, out.tail = node.text, node.tail
        parent.append(out)
        rows.append({"ordinal": len(rows)+1, "source_tag": node.tag, "source_id": node.get("id"), "source_attributes": dict(node.attrib), "source_text": node.text or "", "source_tail": node.tail or "", "tei_id": attrs["xml:id"], "tei_tag": TAGS[node.tag]})
        for child in node: emit(child, out)

    for root in roots: emit(root, target_body)
    accountability = {"contract": "37c-205-accountability-v1", "source": {"path": SOURCE_PATH, "bytes": len(raw), "sha256": SOURCE_SHA256}, "root_ids_in_order": [n.get("id") for n in roots], "root_titles_in_order": [n.get("title") for n in roots], "features": rows, "feature_count": len(rows)}
    provenance = {"work_id": WORK_ID, "source_id": manifest.record["source_id"], "scope": "complete retained ThML document; all five ordered body roots represented", "accepted_ir": False, "human_review": "required", "rights": "unresolved", "publication": "not_ready"}
    return {"content.tei.xml": etree.tostring(tei, encoding="utf-8", xml_declaration=True), "source-accountability.json": _json(accountability), "provenance.json": _json(provenance), "unresolved.jsonl": (json.dumps({"id": WORK_ID+"-edition-rights-review", "status": "unresolved", "detail": "Print-edition identity and rights require separate evidence and decisions."}, sort_keys=True)+"\n").encode(), "README.source.md": b"# Systematic Theology, Vol. 3\n\nNonaccepted reconstruction from the retained CCEL ThML witness (sourced via CCEL.org). All five source body roots are represented in source order. Edition identity beyond the CCEL electronic witness, rights, human acceptance, and publication remain unresolved.\n"}


_convert.converter_id = "ocd-37c205-hodge-vol-3"
_convert.converter_version = "1"
