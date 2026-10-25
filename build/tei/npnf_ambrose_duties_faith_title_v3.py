"""Build Duties or Faith with source-visible chapter titles displayed once."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

from lxml import etree

from build.tei.npnf_ambrose_reconstruction import _append
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import tei_el


SOURCE_SHA256 = "c6f1a9d66653852d8b743c84a613c72c521dfb1b05602f0a2eff400c17665ee8"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORKS = {"ambrose-of-milan-on-duties-of-clergy", "ambrose-of-milan-exposition-of-christian-faith"}


def _visible_text(node: etree._Element) -> str:
    pieces: list[str] = []

    def walk(current: etree._Element) -> None:
        pieces.append(current.text or "")
        for child in current:
            if child.tag != "note":
                walk(child)
            pieces.append(child.tail or "")

    walk(node)
    return "".join(pieces)


def _source_typography(text: str) -> str:
    return " ".join(text.split()).replace("\u2019", "'").replace("\u2014", "--")


def _redundant_title(source: etree._Element) -> bool:
    title = source.get("title")
    if not title or not str(source.tag).startswith("div"):
        return False
    normalized = _source_typography(title)
    children = [child for child in source if isinstance(child.tag, str)]
    for index, child in enumerate(children):
        if child.tag not in {"h1", "h2", "h3", "h4"}:
            continue
        heading = _source_typography(_visible_text(child))
        if normalized == heading:
            return True
        following = next((node for node in children[index + 1:] if node.tag not in {"pb", "hr"}), None)
        if following is not None and following.tag == "p":
            summary = _source_typography(_visible_text(following))
            if normalized == f"{heading} {summary}":
                return True
    return False


def _repair_display(source: etree._Element, target: etree._Element, rows: list[dict[str, object]]) -> None:
    by_id = {str(row["tei_xml_id"]): row for row in rows}

    def visit(source_node: etree._Element, tei_node: etree._Element) -> None:
        row = by_id[str(tei_node.get(XML_ID))]
        if source_node.tag in {"h1", "h2", "h3", "h4"}:
            level = source_node.tag[1]
            tei_node.set("type", "source-heading")
            tei_node.set("n", level)
            row["tei_attributes"] = {"xml:id": tei_node.get(XML_ID), "type": "source-heading", "n": level}
        if source_node.tag == "hr":
            tei_node.set("unit", "horizontal-rule")
            row["tei_attributes"]["unit"] = "horizontal-rule"
        if _redundant_title(source_node):
            synthetic = tei_node[0]
            if etree.QName(synthetic).localname != "head" or synthetic.text != source_node.get("title"):
                raise ValueError("redundant source title did not bind its synthetic TEI head")
            tei_node.remove(synthetic)
            row["source_title_head"] = None
            for disposition in row["attribute_dispositions"]:
                if disposition["source_attribute"] == "title":
                    disposition["destination"] = "source-accountability"
                    disposition["method"] = "redundant-explicit-content"
        source_children = [child for child in source_node if isinstance(child.tag, str)]
        tei_children = [child for child in tei_node if isinstance(child.tag, str) and etree.QName(child).localname != "head"]
        if len(source_children) != len(tei_children):
            raise ValueError("work-local display repair changed source feature count")
        for ordinal, (source_child, tei_child) in enumerate(zip(source_children, tei_children, strict=True), 1):
            by_id[str(tei_child.get(XML_ID))]["tei_child_ordinal"] = ordinal + int(tei_node[0] is not tei_child and etree.QName(tei_node[0]).localname == "head")
            visit(source_child, tei_child)

    visit(source, target)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    work_id = str(source_manifest.record["work_id"])
    if work_id not in WORKS:
        raise ValueError("source-typography v3 converter is Duties/Faith-only")
    source_bytes = source_manifest.authority_path("retained-thml").read_bytes()
    if len(source_bytes) != 3_837_030 or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF210 source identity drifted")
    work = json.loads(source_manifest.authority_path("work-identity").read_bytes())
    if work["work_id"] != work_id:
        raise ValueError("work identity does not match the source manifest")
    edition = work["textual_forms"][0]["editions"][0]
    acquisition_id = edition["acquisition_ids"][0]
    acquisition = json.loads(source_manifest.authority_path("acquisition").read_bytes())
    if (acquisition["acquisition_id"] != acquisition_id or acquisition["source_sha256"] != SOURCE_SHA256):
        raise ValueError("work acquisition does not match retained source")
    locator = edition["containing_source"]["locator"]
    scope = locator.rpartition("#")[2]
    if locator != f"raw/ccel/npnf2/npnf210.xml#{scope}" or not scope:
        raise ValueError("work source locator is not an exact NPNF210 child")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, huge_tree=True)
    source_tree = etree.fromstring(source_bytes, parser)
    matches = source_tree.xpath("//ThML.body//*[@id=$scope]", scope=scope)
    if len(matches) != 1:
        raise ValueError("assigned work root missing or ambiguous")
    source_div = matches[0]
    if (scope == "v" and source_div.tag != "div1") or (scope != "v" and source_div.tag != "div2"):
        raise ValueError("assigned work root depth changed")
    if scope != "v" and source_div.getparent().get("id") != "iv":
        raise ValueError("assigned Ambrose work left its volume wrapper")

    tei = tei_el("TEI", {"xml:id": work_id})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text=work["title"]))
    title_stmt.append(tei_el("author", text="Ambrose of Milan"))
    file_desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(tei_el("publisher", text="Open Christian Data"))
    availability = tei_el("availability", {"status": "restricted"})
    availability.append(tei_el("p", text="Nonaccepted retained CCEL electronic-witness candidate; rights and publication remain unresolved."))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl", {"type": "retained-electronic-witness"})
    bibl.append(tei_el("title", text="Ambrose: Select Works and Letters, NPNF Second Series Volume X"))
    bibl.append(tei_el("publisher", text="Christian Classics Ethereal Library"))
    bibl.append(tei_el("ref", {"target": acquisition["url"]}, text=locator))
    bibl.append(tei_el("idno", {"type": "sha256"}, text=SOURCE_SHA256))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)
    text = tei_el("text")
    body = tei_el("body", {"xml:id": f"{work_id}-body"})
    rows: list[dict[str, object]] = []
    _append(source_div, body, rows, None)
    _repair_display(source_div, body[0], rows)
    rows[0]["work_id"] = work_id
    text.append(body)
    tei.append(text)

    nodes = [node for node in source_div.iter() if isinstance(node.tag, str)]
    if len(nodes) != len(rows):
        raise ValueError("source feature inventory is incomplete")
    accounting = {
        "contract": "ocd-npnf210-work-local-accounting-v1",
        "work_id": work_id,
        "edition_id": edition["edition_id"],
        "acquisition_id": acquisition_id,
        "source_path": acquisition["source_path"],
        "source_sha256": SOURCE_SHA256,
        "source_locator": locator,
        "source_root_tag": source_div.tag,
        "source_root_id": scope,
        "source_feature_count": len(nodes),
        "source_attribute_count": sum(len(node.attrib) for node in nodes),
        "source_text_node_count": sum(node.text is not None for node in nodes),
        "source_tail_node_count": sum(node.tail is not None for node in nodes),
        "source_character_count": sum(len((node.text or "") + (node.tail or "")) for node in nodes),
        "crosswalk": rows,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
    }
    provenance = {
        "contract": "ocd-npnf210-work-local-provenance-v1",
        "status": "nonaccepted",
        "work_id": work_id,
        "edition_id": edition["edition_id"],
        "acquisition_id": acquisition_id,
        "source_path": acquisition["source_path"],
        "source_sha256": SOURCE_SHA256,
        "source_locator": locator,
        "translation_credit": "Volume credits H. De Romestin with assistance from E. De Romestin and H. T. F. Duckworth; individual allocation unresolved.",
        "human_review": "not-recorded",
        "rights_clearance": "not-assessed",
        "publication": "not-ready",
    }
    readme = (
        f"# {work['title']} — retained CCEL electronic witness\n\n"
        f"This nonaccepted TEI is reconstructed directly from `{locator}` in the retained XML volume. "
        "CCEL.org is the electronic source. The volume credits H. De Romestin with assistance from "
        "E. De Romestin and H. T. F. Duckworth; it does not allocate individual works. "
        "The retained header states Public Domain, while CCEL's separate restrictions on its files and formatting "
        "still require publication review. No print collation or human acceptance is claimed.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n",
        "source-accountability.json": _json(accounting),
        "provenance.json": _json(provenance),
        "README.source.md": readme,
        "unresolved.jsonl": b"",
    }


_convert.converter_id = "ocd-npnf210-duties-faith-title-v3-to-tei"
_convert.converter_version = "3"
