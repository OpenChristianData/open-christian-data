"""Apply reviewed source spans while retaining their original readings in TEI.

The four CCEL editions already use source element ordinals as feature IDs.
This changes only text fields; their accepted hierarchy and attachment remain.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import xml.etree.ElementTree as ET

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _groups(rows):
    groups = defaultdict(list)
    for row in rows:
        if row["passage_review"] != "pass" or row["source_field"] not in {"text", "tail"}:
            raise ValueError("Unreviewed or unsupported correction")
        groups[(row["member_id"], row["source_selector"], row["source_field"])].append(row)
    return groups


def reconstruct(master: bytes, sources: dict[str, bytes], rows: list[dict]) -> bytes:
    tree = etree.fromstring(master, etree.XMLParser(resolve_entities=False, no_network=True))
    if tree.findall(".//" + TEI + "choice"):
        raise ValueError("This bounded repair requires a preimage without reading choices")
    targets = {n.get(XML_ID): n for n in tree.iter() if n.get(XML_ID)}
    parsed = {member: etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
              for member, raw in sources.items()}
    for (member, selector, field), corrections in _groups(rows).items():
        source, = parsed[member].xpath(selector)
        value = getattr(source, field) or ""
        if member in {"dods-expositorjohn1", "watson-ra-expositorjob", "bennett-expositorjer2"}:
            ordinal = list(parsed[member].find("ThML.body").iter()).index(source)
            identity = member + "-" + source.get("id") if source.get("id") else member + f"-feature-{ordinal:06d}"
        else:
            ordinal = [n for n in parsed[member].iter() if isinstance(n.tag, str)].index(source) + 1
            identity = member + f"-feature-{ordinal:05d}"
        target = targets[identity]
        if (getattr(target, field) or "") != value:
            raise ValueError(f"Accepted field differs from retained source: {selector}/{field}")
        corrections.sort(key=lambda row: row["start"])
        cursor, choices = 0, []
        for index, row in enumerate(corrections):
            start, end = row["start"], row["end"]
            if not (row["source_value_sha256"] == _hash(value) and cursor <= start < end <= len(value)
                    and value[start:end] == row["sic"] and row["sic"] != row["corr"] and row["corr"]):
                raise ValueError(f"Invalid source-bound correction span: {selector}/{field}")
            choice = etree.Element(TEI + "choice")
            etree.SubElement(choice, TEI + "sic").text = row["sic"]
            etree.SubElement(choice, TEI + "corr").text = row["corr"]
            next_start = corrections[index + 1]["start"] if index + 1 < len(corrections) else len(value)
            choice.tail = value[end:next_start] or None
            choices.append(choice)
            cursor = end
        setattr(target, field, value[:corrections[0]["start"]] or None)
        parent, offset = (target, 0) if field == "text" else (target.getparent(), target.getparent().index(target) + 1)
        for index, choice in enumerate(choices):
            parent.insert(offset + index, choice)
    revised = etree.tostring(tree, encoding="utf-8", xml_declaration=True)
    verify(master, revised, sources, rows)
    return revised


def verify(master: bytes, revised: bytes, sources: dict[str, bytes], rows: list[dict]) -> dict:
    """Use stdlib source traversal, then invert only actual sic/corr changes."""
    original = etree.fromstring(master)
    actual = etree.fromstring(revised)
    restored = deepcopy(actual)
    by_id = {n.get(XML_ID): n for n in actual.iter() if n.get(XML_ID)}
    count = 0
    for (member, selector, field), corrections in _groups(rows).items():
        source = ET.fromstring(sources[member], parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
        relative = selector.removeprefix("/ThML[1]")
        if not relative.startswith("/"):
            raise ValueError("Unexpected retained source selector")
        selected = source.findall("." + relative)
        if len(selected) != 1:
            raise ValueError("Source selector is missing or ambiguous")
        node = selected[0]
        value = getattr(node, field) or ""
        if member.startswith(("dods-", "watson-ra-", "bennett-")):
            position = tuple(source.find("ThML.body").iter()).index(node)
            key = f"{member}-{node.attrib['id']}" if "id" in node.attrib else f"{member}-feature-{position:06d}"
        else:
            position = tuple(n for n in source.iter() if isinstance(n.tag, str)).index(node) + 1
            key = f"{member}-feature-{position:05d}"
        target = by_id[key]
        corrections = sorted(corrections, key=lambda row: row["start"])
        if (getattr(target, field) or "") != value[:corrections[0]["start"]]:
            raise ValueError("Corrected field prefix differs")
        actual_choices = list(target)[:len(corrections)] if field == "text" else list(target.getparent())[target.getparent().index(target) + 1:target.getparent().index(target) + 1 + len(corrections)]
        for index, (row, choice) in enumerate(zip(corrections, actual_choices, strict=True)):
            start, end = row["start"], row["end"]
            next_start = corrections[index + 1]["start"] if index + 1 < len(corrections) else len(value)
            previous_end = corrections[index - 1]["end"] if index else 0
            if (not previous_end <= start < end <= next_start <= len(value)
                    or not row["corr"] or row["corr"] == row["sic"]
                    or row["source_value_sha256"] != _hash(value) or value[start:end] != row["sic"]
                    or choice.tag != TEI + "choice" or choice.attrib or choice.text
                    or len(choice) != 2 or [n.tag for n in choice] != [TEI + "sic", TEI + "corr"]
                    or choice[0].text != row["sic"] or choice[1].text != row["corr"]
                    or any(n.attrib or len(n) or n.tail for n in choice)
                    or (choice.tail or "") != value[end:next_start]):
                raise ValueError("Corrected reading, source span, or attachment differs")
            count += 1
    choices = list(restored.iter(TEI + "choice"))
    if len(choices) != count or count != len(rows):
        raise ValueError("Unexpected, missing, or duplicated reading choice")
    for choice in choices:
        parent = choice.getparent()
        previous = choice.getprevious()
        text = (choice[0].text or "") + (choice.tail or "")
        if previous is None:
            parent.text = (parent.text or "") + text
        else:
            previous.tail = (previous.tail or "") + text
        parent.remove(choice)
    if etree.tostring(restored, method="c14n") != etree.tostring(original, method="c14n"):
        raise ValueError("Repair changes content or structure beyond reviewed source spans")
    return {"status": "pass", "corrections": count,
            "preserved_replacement_characters": sum(row["sic"].count("\ufffd") for row in rows),
            "inverse": "Entire original master recovered by selecting sic; attributes, order and attachment conserved"}
