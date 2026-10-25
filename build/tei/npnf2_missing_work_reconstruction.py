"""Readable, source-root-bound reconstruction for 37c-130/180/181.

The pure builder supplies TEI and source accounting for eventual maintained
candidate packaging. Packaging and independent verification are separate steps.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from lxml import etree

from build.tei.npnf2_missing_work_roots import WORK_ROOTS, load_work_root
from ocd_kernel.tei.writer import tei_el
from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-npnf2-missing-work-roots-to-tei"
CONVERTER_VERSION = "1"


TAGS = {
    "div1": "div", "div2": "div", "div3": "div", "div4": "div",
    "p": "p", "note": "note", "i": "hi", "span": "seg", "sup": "hi",
    "pb": "pb", "scripRef": "ref", "table": "table", "tr": "row",
    "td": "cell", "br": "lb",
}


def build_work(repository_root: Path, work_id: str) -> tuple[bytes, dict[str, Any]]:
    """Build a complete selected subtree; fail on any ungoverned source tag."""
    tree, selected = load_work_root(repository_root, work_id)
    binding = WORK_ROOTS[work_id]
    rows: list[dict[str, Any]] = []

    def append(source: etree._Element, parent: etree._Element) -> None:
        if source.tag not in TAGS:
            raise ValueError(f"unsupported source carrier at {tree.getpath(source)}: {source.tag}")
        ordinal = len(rows) + 1
        target_id = f"{work_id}-{ordinal}"
        attrs = {"xml:id": target_id}
        tag = TAGS[source.tag]
        if source.tag == "span" and source.get("lang"):
            tag = "foreign"
            language = source.get("lang")
            attrs["xml:lang"] = {"EL": "grc", "HE": "he", "LA": "la"}.get(language, language.lower())
        if source.tag.startswith("div"):
            attrs["type"] = source.get("type", "source-division")
        if source is selected:
            attrs.update(type="work", subtype=work_id)
        if source.tag in {"i", "sup"}:
            attrs["rend"] = "italic" if source.tag == "i" else "superscript"
        rendition = [source.get(name) for name in ("class", "style") if source.get(name)]
        if rendition:
            attrs["rend"] = " ".join(rendition)
        if source.tag in {"div1", "div2", "div3", "div4", "note", "pb"} and "n" in source.attrib:
            attrs["n"] = source.get("n")
        if source.tag == "note":
            for name in ("place",):
                if name in source.attrib:
                    attrs[name] = source.get(name)
            if "anchored" in source.attrib:
                try:
                    attrs["anchored"] = {"yes": "true", "no": "false", "true": "true", "false": "false"}[source.get("anchored")]
                except KeyError as exc:
                    raise ValueError(f"unknown anchored value at {tree.getpath(source)}") from exc
        if source.tag == "pb" and source.get("href"):
            attrs["facs"] = source.get("href")
        if source.tag == "scripRef":
            # Preserve the source's reference labeling without inferring that
            # every retained scripRef is correctly classified as Scripture.
            if source.get("passage"):
                attrs["cRef"] = source.get("passage")
            if source.get("osisRef"):
                attrs["target"] = source.get("osisRef")
        target = tei_el(tag, attrs)
        target.text, target.tail = source.text, source.tail
        title = source.get("title") if source.tag.startswith("div") else None
        if title is not None:
            target.append(tei_el("head", text=title))
        if etree.QName(parent).localname == "div" and tag in {"hi", "seg", "foreign", "ref"}:
            wrapper = tei_el("ab", {"type": "source-inline-container"})
            wrapper.append(target)
            parent.append(wrapper)
        else:
            parent.append(target)
        rows.append({
            "source_path": tree.getpath(source), "source_tag": source.tag,
            "source_attributes": dict(source.attrib), "source_text": source.text,
            "source_tail": source.tail, "tei_xml_id": target_id,
            "tei_tag": tag, "generated_title_head": title,
        })
        for child in source:
            append(child, target)

    document = tei_el("TEI", {"xml:id": work_id})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text=binding.root_title))
    file_desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(tei_el("publisher", text="Open Christian Data"))
    availability = tei_el("availability", {"status": "restricted"})
    availability.append(tei_el("p", text="Nonaccepted reconstruction candidate; publication is not authorized."))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl")
    bibl.append(tei_el("title", text=binding.root_title))
    bibl.append(tei_el("ptr", {"target": binding.source_path}))
    bibl.append(tei_el("idno", {"type": "sha256"}, binding.source_sha256))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    document.append(header)
    text = tei_el("text")
    body = tei_el("body")
    append(selected, body)
    text.append(body)
    document.append(text)
    selected_paths = {row["source_path"] for row in rows}
    # Every enclosing/sibling carrier receives an explicit source-local
    # disposition. Source metadata remains evidence, not inferred work credit.
    envelope = [{
        "source_path": tree.getpath(node),
        "source_tag": node.tag if isinstance(node.tag, str) else ("comment" if node.tag is etree.Comment else "processing-instruction"),
        "source_attributes": dict(node.attrib), "source_text": node.text,
        "source_tail": node.tail,
        "disposition": "represented" if tree.getpath(node) in selected_paths else "outside-selected-work",
    } for node in tree.iter()]
    content = etree.tostring(document, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    def external_nodes(start: etree._Element | None, direction: str) -> list[dict[str, Any]]:
        result = []
        while start is not None:
            result.append({"kind": "comment" if start.tag is etree.Comment else "processing-instruction",
                           "text": start.text, "tail": start.tail})
            start = start.getprevious() if direction == "before" else start.getnext()
        return list(reversed(result)) if direction == "before" else result
    return content, {
        "work_id": work_id, "source_path": binding.source_path,
        "source_sha256": binding.source_sha256, "root_path": list(binding.root_path),
        "tei_sha256": hashlib.sha256(content).hexdigest(),
        "represented_carriers": rows, "document_carriers": envelope,
        "scope": "complete selected subtree; enclosing and sibling material accounted outside projection",
        "verification_status": "independent fidelity verification and candidate packaging pending",
        "document_declaration": {
            "xml_version": tree.docinfo.xml_version, "encoding": tree.docinfo.encoding,
            "standalone": tree.docinfo.standalone, "doctype": tree.docinfo.doctype,
        },
        "pre_root_nodes": external_nodes(tree.getroot().getprevious(), "before"),
        "post_root_nodes": external_nodes(tree.getroot().getnext(), "after"),
    }


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    """Maintained five-member candidate adapter for one exact work manifest."""
    source_manifest.verify()
    work_id = source_manifest.record.get("work_id")
    if work_id not in WORK_ROOTS:
        raise ValueError("manifest does not identify a supported missing NPNF2 work")
    binding = WORK_ROOTS[work_id]
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("work_id") != work_id or profile.get("root_path") != list(binding.root_path):
        raise ValueError("manifest/profile work root mismatch")
    primary = next(item for item in source_manifest.record["authorities"] if item["name"] == "retained-source")
    if (primary["path"], primary["bytes"], primary["sha256"]) != (binding.source_path, binding.source_bytes, binding.source_sha256):
        raise ValueError("manifest retained source does not bind selected work")
    content, accounting = build_work(source_manifest.repository_root, work_id)
    provenance = {
        "contract": "ocd-npnf2-missing-work-provenance-v1", "work_id": work_id,
        "source_manifest_sha256": source_manifest.sha256,
        "source_sha256": binding.source_sha256, "root_path": list(binding.root_path),
        "profile_sha256": hashlib.sha256(source_manifest.authority_path("reconstruction-profile").read_bytes()).hexdigest(),
        "publication": False,
    }
    unresolved = {
        "id": "acceptance-and-metadata-review", "status": "unresolved",
        "detail": "Candidate technical checks do not establish human acceptance, rights clearance, work-level contributor allocation, or publication authorization.",
    }
    return {
        "content.tei.xml": content,
        "source-accountability.json": _canonical(accounting),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": _canonical(unresolved),
        "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
