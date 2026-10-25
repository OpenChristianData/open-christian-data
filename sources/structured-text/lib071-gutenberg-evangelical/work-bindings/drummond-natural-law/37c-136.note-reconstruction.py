"""Work-local note enrichment of the bound complete PG23334 reconstruction."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree


CONVERTER_ID = "ocd-drummond-pg23334-notes-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_ID = "drummond-natural-law"
ENCODING_POLICY = (
    "The complete retained PG23334 member is preserved in source order as numbered "
    "line carriers and blank delimiters. Source-located headings preserve the "
    "declared section structure. All 100 numbered footnote calls link to their "
    "source definitions; continuation blocks point to the definition, and each "
    "definition points to the section containing its call. Source spelling and "
    "line endings are unchanged. Unmapped hierarchy remains source-block text."
)


def _one(root: etree._Element, query: str) -> etree._Element:
    nodes = root.xpath(query, namespaces={"tei": TEI_NS})
    if len(nodes) != 1:
        raise ValueError(f"PG23334 expected one node for {query!r}, found {len(nodes)}")
    return nodes[0]


def _bound_base(source_manifest: Any):
    path = source_manifest.authority_path("converter-implementation")
    spec = importlib.util.spec_from_file_location("_ocd_drummond_bound_base", path)
    if spec is None or spec.loader is None:
        raise ValueError("bound LIB-071 base converter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _convert(source_manifest: Any) -> Mapping[str, bytes]:
    if source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("PG23334 converter accepts only drummond-natural-law")
    source_manifest.verify()
    note_map = json.loads(source_manifest.authority_path("note-map").read_text(encoding="utf-8"))
    if note_map.get("contract") != "ocd-drummond-pg23334-note-map-v1":
        raise ValueError("PG23334 note map contract differs")
    notes = note_map.get("notes")
    if not isinstance(notes, list) or [item.get("number") for item in notes] != list(range(1, 101)):
        raise ValueError("PG23334 note map must cover numbers 1 through 100 once")

    produced = dict(_bound_base(source_manifest)._convert(source_manifest))
    source_tei = produced["content.tei.xml"]
    root = etree.fromstring(source_tei)
    project = _one(root, "//tei:teiHeader/tei:encodingDesc/tei:projectDesc/tei:p")
    project.text = ENCODING_POLICY

    calls_by_line: dict[int, list[int]] = {}
    for item in notes:
        calls_by_line.setdefault(item["call_line"], []).append(item["number"])
    for call_line, numbers in calls_by_line.items():
        call = _one(root, f"//tei:seg[@type='source-line' and @n='{call_line}']")
        if len(call) or not isinstance(call.text, str):
            raise ValueError(f"PG23334 note call carrier is invalid at line {call_line}")
        source_line = call.text
        matches = list(re.finditer(r"\[(\d{1,3})\]", source_line))
        if [int(match.group(1)) for match in matches] != numbers:
            raise ValueError(f"PG23334 note calls differ from map at line {call_line}")
        call.text = source_line[:matches[0].start()]
        for index, match in enumerate(matches):
            number = int(match.group(1))
            reference = etree.SubElement(
                call,
                f"{{{TEI_NS}}}ref",
                type="source-footnote-call",
                n=str(number),
                target=f"#{WORK_ID}-note-{number:03d}",
            )
            reference.set(XML_ID, f"{WORK_ID}-note-call-{number:03d}")
            reference.text = match.group(0)
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(source_line)
            reference.tail = source_line[match.end():next_start]

    for item in notes:
        number = item["number"]
        marker = f"[{number}]"
        call_line = item["call_line"]
        definition_line = item["definition_line"]
        owner_line = item["owner_heading_line"]
        group_line = item["definition_group_line"]
        if not all(isinstance(value, int) and value > 0 for value in (
            number, call_line, definition_line, owner_line, group_line
        )):
            raise ValueError(f"PG23334 note {number} has invalid source locators")
        call_id = f"{WORK_ID}-note-call-{number:03d}"
        note_id = f"{WORK_ID}-note-{number:03d}"
        definition = _one(root, f"//tei:seg[@type='source-line' and @n='{definition_line}']")
        if not (definition.text or "").startswith(marker):
            raise ValueError(f"PG23334 note {number} definition differs from source map")
        note = definition.getparent()
        if note.tag != f"{{{TEI_NS}}}p":
            raise ValueError(f"PG23334 note {number} definition has no source block paragraph")
        note.tag = f"{{{TEI_NS}}}note"
        note.attrib.clear()
        note.set("type", "source-footnote")
        note.set("n", str(number))
        note.set("target", f"#{call_id}")
        note.set("corresp", f"#{WORK_ID}-heading-{owner_line:05d}")
        note.set(XML_ID, note_id)
        group = _one(root, f"//tei:head[@type='source-located-heading' and @n='{group_line}']")
        if group.getparent() not in tuple(note.iterancestors()):
            raise ValueError(f"PG23334 note {number} is outside its source note group")
        for continuation_line in item["continuation_start_lines"]:
            continuation = _one(
                root, f"//tei:seg[@type='source-line' and @n='{continuation_line}']"
            )
            block = next(
                (ancestor for ancestor in continuation.iterancestors()
                 if ancestor.tag == f"{{{TEI_NS}}}div" and ancestor.get("type") == "source-block"),
                None,
            )
            if block is None or block.get("corresp") is not None:
                raise ValueError(f"PG23334 note {number} continuation block is invalid")
            block.set("corresp", f"#{note_id}")

    produced["content.tei.xml"] = etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    return produced


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
