"""Build one nonaccepted LIB-031 TEI directly from its retained ThML witness."""

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


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source_binding(source_manifest: SourceManifest) -> tuple[dict[str, object], dict[str, object]]:
    sources = [dict(item) for item in source_manifest.record["authorities"] if item["role"] == "primary-source"]
    if len(sources) != 1:
        raise ValueError("work-local LIB-031 manifest must bind one retained ThML source")
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    work_id = source_manifest.record["source_id"].removeprefix("ccel-lib031-work-")
    matches = [item for item in profile["works"] if item["work_id"] == work_id]
    if len(matches) != 1 or not sources[0]["name"] == work_id + "-source":
        raise ValueError("work-local LIB-031 identity/profile mismatch")
    return sources[0], matches[0]


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    source_binding, metadata = _source_binding(source_manifest)
    work_id = str(metadata["work_id"])
    source_path = source_manifest.authority_path(str(source_binding["name"]))
    source_bytes = source_path.read_bytes()
    if _sha(source_bytes) != source_binding["sha256"]:
        raise ValueError("retained work source changed")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    head, source_body = source.find("ThML.head"), source.find("ThML.body")
    if source.tag != "ThML" or head is None or source_body is None:
        raise ValueError("complete retained ThML envelope is required")
    if (source_body.text or "").strip() or (source_body.tail or "").strip():
        raise ValueError("nonformatting body boundary text needs explicit mapping")

    tei = tei_el("TEI")
    header = tei_el("teiHeader")
    desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text=str(metadata["title"])))
    title_stmt.append(tei_el("author", text=str(metadata["author"])))
    desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(tei_el("publisher", text="Open Christian Data"))
    availability = tei_el("availability", {"status": "restricted"})
    availability.append(tei_el("p", text="Nonaccepted electronic-witness candidate; rights and publication remain unresolved."))
    publication.append(availability)
    desc.append(publication)
    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl", {"type": "retained-electronic-witness"})
    bibl.append(tei_el("title", text=str(metadata["title"])))
    bibl.append(tei_el("author", text=str(metadata["author"])))
    source_publisher = (head.findtext(".//DC.Publisher") or "").strip()
    if source_publisher:
        bibl.append(tei_el("publisher", text=source_publisher))
    bibl.append(tei_el("ref", {"target": str(metadata["source_url"])}, text=str(source_binding["path"])))
    bibl.append(tei_el("idno", {"type": "sha256"}, text=_sha(source_bytes)))
    source_desc.append(bibl)
    desc.append(source_desc)
    header.append(desc)
    tei.append(header)
    text = tei_el("text")
    body = tei_el("body")
    work_div = tei_el("div", {"xml:id": work_id, "type": "work"})
    body.append(work_div)
    text.append(body)
    tei.append(text)

    rows: list[dict[str, object]] = []
    counter = [0]
    for child in source_body:
        _append_node(child, work_div, body=source_body, work_id=work_id, rows=rows, counter=counter, parent_id=work_id)
        work_div[-1].tail = child.tail or ""
    nodes = list(source_body.iter())[1:]
    if len(rows) != len(nodes):
        raise ValueError("source body feature accounting incomplete")
    targets = {node.get(XML_ID): node for node in work_div.iter() if isinstance(node.tag, str) and node.get(XML_ID)}
    source_ids: dict[str, str] = {}
    for node, row in zip(nodes, rows, strict=True):
        source_id = node.get("id")
        if source_id:
            if source_id in source_ids:
                raise ValueError(f"duplicate source ID: {source_id}")
            source_ids[source_id] = str(row["tei_selector"])[1:]
    localized = 0
    semantic_heads = 0
    source_headings = 0
    for node, row in zip(nodes, rows, strict=True):
        target = targets[str(row["tei_selector"])[1:]]
        parent = node.getparent()
        if isinstance(node.tag, str) and node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            source_headings += 1
            leading_division_heading = (parent is not None and parent.tag in {"div1", "div2", "div3", "div4"}
                                        and all(isinstance(previous.tag, str) and previous.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} for previous in parent[:parent.index(node)]))
            if leading_division_heading:
                target.tag = f"{{{TEI_NS}}}head"
                row["tei_tag"] = "head"
                if parent.index(node) == 0:
                    semantic_heads += 1
            else:
                target.set("rend", "heading-level-" + node.tag[1:])
                row["tei_attributes"]["rend"] = target.get("rend")
        if node.tag == "a":
            href = node.get("href", "")
            fragment = href.partition("#")[2]
            if not fragment or fragment not in source_ids:
                raise ValueError(f"unresolved work-local source link: {href}")
            target.set("target", "#" + source_ids[fragment])
            row["tei_attributes"]["target"] = target.get("target")
            localized += 1
    header_rows = [
        {"tag": node.tag if isinstance(node.tag, str) else "#comment", "attributes": dict(node.attrib), "text": node.text or "", "tail": node.tail or ""}
        for node in head.iter()
    ]
    accounting = {
        "contract": "ocd-lib031-work-local-accounting-v1",
        "work_id": work_id,
        "source_path": source_binding["path"],
        "source_sha256": _sha(source_bytes),
        "source_header": header_rows,
        "source_body_boundary": {"text": source_body.text or "", "tail": source_body.tail or "", "disposition": "excluded formatting whitespace"},
        "body_crosswalk": rows,
        "first_child_division_heads": semantic_heads,
        "source_headings": source_headings,
        "localized_source_links": localized,
    }
    provenance = {
        "contract": "ocd-lib031-work-local-provenance-v1",
        "status": "nonaccepted",
        "work_id": work_id,
        "source_path": source_binding["path"],
        "source_sha256": _sha(source_bytes),
        "source_url": metadata["source_url"],
        "print_collation": "not-assessed",
        "rights_clearance": "not-assessed",
        "human_review": "not-recorded",
    }
    readme = (
        f"# {metadata['title']} — source-local electronic witness\n\n"
        f"This nonaccepted TEI was reconstructed directly from `{source_binding['path']}`. "
        "The complete retained ThML body and source-header inventory are bound in the accountability file. "
        "First-child division headings and local source links are represented as TEI headings and local targets. "
        "Print collation, human review, rights clearance, and publication are separate.\n"
    ).encode("utf-8")
    return {
        "README.source.md": readme,
        "content.tei.xml": etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n",
        "source-accountability.json": _canonical(accounting),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"",
    }


_convert.converter_id = "ocd-lib031-work-local-thml-to-tei"
_convert.converter_version = "1"
