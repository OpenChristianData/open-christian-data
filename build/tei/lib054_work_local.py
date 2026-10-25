"""Readable, independently addressable LIB-054 ThML work candidates."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

from lxml import etree

from build.tei.lib031_reconstruction import _append_node
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.writer import tei_el

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI_NS = "http://www.tei-c.org/ns/1.0"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    work_id = str(manifest.record["work_id"])
    profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    matches = [item for item in profile["works"] if item["work_id"] == work_id]
    sources = [item for item in manifest.record["authorities"] if item["role"] == "primary-source"]
    if len(matches) != 1 or len(sources) != 1:
        raise ValueError("LIB-054 work/profile/source identity is not unique")
    work, binding = matches[0], sources[0]
    if binding["path"] != work["source_path"] or binding["sha256"] != work["sha256"]:
        raise ValueError("LIB-054 work source does not match family profile")
    source_bytes = manifest.authority_path(str(binding["name"])).read_bytes()
    if _sha(source_bytes) != binding["sha256"]:
        raise ValueError("LIB-054 retained source changed")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    if source.tag != "ThML":
        raise ValueError("LIB-054 retained source is not ThML")
    heads, bodies = source.findall("ThML.head"), source.findall("ThML.body")
    if len(bodies) != 1 or len(heads) > 1 or len(source) != len(heads) + 1:
        raise ValueError("LIB-054 retained envelope is ambiguous")
    head, body = heads[0] if heads else None, bodies[0]
    if (body.text or "").strip() or (body.tail or "").strip():
        raise ValueError("LIB-054 body boundary has unassigned text")

    tei = tei_el("TEI")
    header = tei_el("teiHeader")
    desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text=str(work["title"])))
    title_stmt.append(tei_el("author", text=str(work["author"])))
    desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(tei_el("publisher", text="Open Christian Data"))
    availability = tei_el("availability", {"status": "restricted"})
    availability.append(tei_el("p", text="Nonaccepted electronic-witness candidate; rights and publication remain unresolved."))
    publication.append(availability)
    desc.append(publication)
    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl", {"type": "retained-electronic-witness"})
    bibl.append(tei_el("title", text=str(work["title"])))
    bibl.append(tei_el("author", text=str(work["author"])))
    publisher = (head.findtext(".//DC.Publisher") or "").strip() if head is not None else ""
    if publisher:
        bibl.append(tei_el("publisher", text=publisher))
    bibl.append(tei_el("ref", {"target": str(work["source_url"])}, text=str(binding["path"])))
    bibl.append(tei_el("idno", {"type": "sha256"}, text=_sha(source_bytes)))
    if head is None:
        bibl.append(tei_el("note", {"type": "extracted-fragment"}, text="Retained local extract has no ThML.head; extraction provenance from the enclosing volume remains unresolved."))
    source_desc.append(bibl)
    desc.append(source_desc)
    header.append(desc)
    tei.append(header)
    text = tei_el("text")
    tei_body = tei_el("body")
    work_div = tei_el("div", {"xml:id": work_id, "type": "work"})
    tei_body.append(work_div)
    text.append(tei_body)
    tei.append(text)

    rows: list[dict[str, object]] = []
    count = [0]
    for child in body:
        _append_node(child, work_div, body=body, work_id=work_id, rows=rows, counter=count, parent_id=work_id)
        work_div[-1].tail = child.tail or ""
    nodes = list(body.iter())[1:]
    if len(rows) != len(nodes):
        raise ValueError("LIB-054 body node accounting incomplete")
    targets = {node.get(XML_ID): node for node in work_div.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
    source_ids: dict[str, str] = {}
    for node, row in zip(nodes, rows, strict=True):
        source_id = node.get("id") if isinstance(node.tag, str) else None
        if source_id:
            if source_id in source_ids:
                raise ValueError(f"duplicate source ID: {source_id}")
            source_ids[source_id] = str(row["tei_selector"])[1:]
    local_links = 0
    for node, row in zip(nodes, rows, strict=True):
        if isinstance(node.tag, str) and node.tag == "blockquote":
            quote = targets[str(row["tei_selector"])[1:]]
            quote.tag = f"{{{TEI_NS}}}quote"
            row["tei_tag"] = "quote"
        if isinstance(node.tag, str) and node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            parent = node.getparent()
            leading = (parent is not None and parent.tag in {"div1", "div2", "div3", "div4"}
                       and all(isinstance(previous.tag, str) and previous.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} for previous in parent[:parent.index(node)]))
            heading = targets[str(row["tei_selector"])[1:]]
            if leading:
                heading.tag = f"{{{TEI_NS}}}head"
                row["tei_tag"] = "head"
            else:
                heading.set("rend", "heading-level-" + node.tag[1:])
                row["tei_attributes"]["rend"] = heading.get("rend")
        if not isinstance(node.tag, str) or node.tag != "a":
            continue
        href = node.get("href", "")
        if not href.startswith("#"):
            continue
        fragment = href[1:]
        if fragment not in source_ids:
            raise ValueError(f"unresolved work-local link: {href}")
        target = targets[str(row["tei_selector"])[1:]]
        target.set("target", "#" + source_ids[fragment])
        row["tei_attributes"]["target"] = target.get("target")
        local_links += 1
    header_rows = (
        [{"tag": node.tag if isinstance(node.tag, str) else "#comment", "attributes": dict(node.attrib), "text": node.text or "", "tail": node.tail or ""} for node in head.iter()]
        if head is not None else []
    )
    accounting = {
        "contract": "ocd-lib054-work-local-accounting-v1",
        "work_id": work_id,
        "source_path": binding["path"],
        "source_sha256": _sha(source_bytes),
        "source_header": header_rows,
        "source_body_boundary": {"text": body.text or "", "tail": body.tail or ""},
        "body_crosswalk": rows,
        "localized_source_links": local_links,
        "shared_matter": "Source title, preface, index, and notes stay in their original divisions within this one retained work; no sibling XML is imported.",
    }
    provenance = {
        "contract": "ocd-lib054-work-local-provenance-v1",
        "status": "nonaccepted",
        "work_id": work_id,
        "source_path": binding["path"],
        "source_sha256": _sha(source_bytes),
        "source_url": work["source_url"],
        "extraction_provenance": "unresolved" if head is None else "not-applicable",
        "print_collation": "not-assessed",
        "rights_clearance": "not-assessed",
        "human_review": "not-recorded",
    }
    readme = (
        f"# {work['title']} — retained CCEL electronic witness\n\n"
        f"This nonaccepted work-local TEI is reconstructed from `{binding['path']}`. "
        "Its source body is readable as nested divisions, headings, paragraphs, notes, and inline text. "
        "The source header and every body node are inventoried in `source-accountability.json`. "
        "Print collation, human review, rights clearance, and publication remain separate.\n"
    ).encode("utf-8")
    return {
        "README.source.md": readme,
        "content.tei.xml": etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n",
        "source-accountability.json": _json(accounting),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"",
    }


_convert.converter_id = "ocd-lib054-work-local-thml-to-tei"
_convert.converter_version = "1"
