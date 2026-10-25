"""Independent literal and structural check of the readable Douay companion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

from lxml import etree, html


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1/renewed-native-v1/content.tei.xml"
DEFAULT_COMPANION = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1/readable-companion-v2"
T = "{http://www.tei-c.org/ns/1.0}"
X = "{http://www.w3.org/XML/1998/namespace}id"
PRE = re.compile(r'<pre style="white-space: pre-wrap">(.*?)</pre>', re.DOTALL)
NULL_MESSAGE = "Source language title absent (JSON null; not authored text)"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def member_of(unit: etree._Element) -> str:
    encoded = unit.get("corresp", "")
    if not encoded.startswith("source-attributes:"):
        raise ValueError("Unit has no retained member binding")
    return json.loads(unquote(encoded.split(":", 1)[1]))["source"]


def source_styles(node: etree._Element) -> list[tuple[str, str]]:
    result = []
    for child in node.iter(T + "hi"):
        result.append((child.get("rend", ""), "".join(child.itertext())))
    return result


def shown_styles(pre: etree._Element) -> list[tuple[str, str]]:
    result = []
    for child in pre.iter():
        if child is pre:
            continue
        if child.tag == "em":
            result.append(("italic", child.text_content()))
        elif child.tag == "span":
            rendition = {"source-small-caps": "small-caps", "source-reference-title-sub": "ref-title-sub"}.get(child.get("class"))
            if rendition is None:
                raise ValueError("Unknown rendered source style")
            result.append((rendition, child.text_content()))
    return result


def expected_headings(unit: etree._Element) -> list[str]:
    headings = []

    def visit(node: etree._Element, depth: int) -> None:
        if node.tag != T + "div" or node.get("type") == "source-verse-group":
            return
        kind = node.get("type", "source division").replace("-", " ").title()
        label = kind + (" " + node.get("n") if node.get("n") else "")
        if node.get("type") not in {"reference-field", "reference-list"}:
            headings.append("#" * min(depth, 6) + " " + label)
        for child in node:
            if child.tag == T + "div":
                visit(child, depth + 1)

    for child in unit:
        if child.tag == T + "div":
            visit(child, 2)
    return headings


def expected_verse_contexts(unit: etree._Element) -> list[str]:
    contexts = []
    for group in unit.iter(T + "div"):
        if group.get("type") != "source-verse-group":
            continue
        verse = next((child for child in group if child.get("type") == "verse"), None)
        if verse is None:
            raise ValueError("Source verse group has no verse")
        has_notes = any(child.tag == T + "note" and (child.get(X) or "").startswith("odr-source-field-") for child in group)
        has_cues = any(
            child.tag in {T + "hi", T + "lb"}
            or (child.tag == T + "seg" and child.get("type") in {"note-anchor", "cross-reference-marker", "marginal-note-marker", "alternate-reading", "column-left", "column-right"})
            for child in verse.iter() if child is not verse
        )
        chapter = group.getparent()
        if has_notes or has_cues or (chapter is not None and chapter.get("type") == "chapter" and chapter.get("n") == "0"):
            contexts.append(group.get("n", ""))
    return contexts


def check(companion: Path) -> dict:
    manifest = json.loads((companion / "manifest.json").read_text(encoding="utf-8"))
    crosswalk = json.loads((companion / "private-crosswalk.json").read_text(encoding="utf-8"))
    source_bytes = SOURCE.read_bytes()
    if digest(source_bytes) != manifest["source_sha256"]:
        raise ValueError("Companion source differs from manifest")
    text = etree.fromstring(source_bytes).find(T + "text")
    if text is None:
        raise ValueError("TEI text missing")
    expected_by_member: dict[str, list[str]] = {}
    units_by_member: dict[str, etree._Element] = {}
    nodes: dict[str, etree._Element] = {}
    for unit in text.iter(T + "div"):
        if unit.get("type") not in {"book", "reference-document"}:
            continue
        member = member_of(unit)
        if member in expected_by_member:
            raise ValueError("Member appears in more than one source unit")
        expected_by_member[member] = []
        units_by_member[member] = unit
        for node in unit.iter():
            identity = node.get(X, "")
            if identity.startswith("odr-source-field-") and node.get("type") != "verse":
                if identity in nodes:
                    raise ValueError("Repeated source field identity")
                expected_by_member[member].append(identity)
                nodes[identity] = node
    if len(expected_by_member) != 102 or len(nodes) != 25145:
        raise ValueError("Exact source unit or field census differs")
    actual_by_member: dict[str, list[str]] = defaultdict(list)
    headings_by_member: dict[str, list[str]] = defaultdict(list)
    verse_contexts_by_member: dict[str, list[str]] = defaultdict(list)
    field_by_part: dict[str, list[str]] = defaultdict(list)
    seen_pointers = set()
    for item in crosswalk:
        identity = item["field_id"]
        if identity not in nodes:
            raise ValueError("Crosswalk includes a foreign field")
        pointer = item["pointer"]
        if "odr-source-field-" + digest(pointer.encode("utf-8")) != identity or pointer in seen_pointers:
            raise ValueError("Crosswalk source pointer is invalid or duplicated")
        seen_pointers.add(pointer)
        field_by_part[item["part"]].append(identity)
    source_literal_bytes = sum(len("".join(node.itertext()).encode("utf-8")) for node in nodes.values())
    if source_literal_bytes != 3781633:
        raise ValueError("Source field literal byte count differs")
    checked_text = 0
    checked_styles = 0
    checked_breaks = 0
    null_count = 0
    for part in manifest["parts"]:
        relative = part["path"]
        data = (companion / relative).read_bytes()
        if digest(data) != part["sha256"] or len(data) != part["bytes"] or len(data) > 65536:
            raise ValueError(f"Notice part binding differs: {relative}")
        if relative == "collection-context.md":
            continue
        member = part["member"]
        identities = field_by_part[relative]
        if len(identities) != part["fields"]:
            raise ValueError(f"Part field count differs: {relative}")
        actual_by_member[member].extend(identities)
        rendered = data.decode("utf-8")
        headings_by_member[member].extend(re.findall(r"^#{2,6} .+$", rendered, re.MULTILINE))
        verse_contexts_by_member[member].extend(re.findall(r"^\*\*Verse (.+?) context\*\*", rendered, re.MULTILINE))
        pre_values = iter(PRE.findall(rendered))
        part_nulls = 0
        for identity in identities:
            node = nodes[identity]
            if node.get("type") == "source-null-absence:source-language-title":
                if node.text != "null" or len(node):
                    raise ValueError("Invalid typed null in frozen TEI")
                part_nulls += 1
                null_count += 1
                continue
            try:
                pre = html.fragment_fromstring("<pre>" + next(pre_values) + "</pre>")
            except StopIteration as exc:
                raise ValueError(f"Missing visible source field in {relative}") from exc
            literal = "".join(node.itertext())
            if pre.text_content() != literal:
                raise ValueError(f"Literal text/tail differs for {identity} in {relative}")
            if shown_styles(pre) != source_styles(node):
                raise ValueError(f"Inline style differs for {identity} in {relative}")
            source_breaks = sum(1 for x in node.iter(T + "lb"))
            shown_breaks = sum(1 for x in pre.iter("br"))
            if source_breaks != shown_breaks:
                raise ValueError(f"Source line breaks differ for {identity} in {relative}")
            checked_text += 1
            checked_styles += len(source_styles(node))
            checked_breaks += source_breaks
        if next(pre_values, None) is not None or rendered.count(NULL_MESSAGE) != part_nulls:
            raise ValueError(f"Unexpected visible field or typed-null message in {relative}")
    if actual_by_member != expected_by_member:
        raise ValueError("Book/document source field ordering or attachment differs")
    if any(headings_by_member[member] != expected_headings(unit) for member, unit in units_by_member.items()):
        raise ValueError("Readable source hierarchy differs")
    if any(verse_contexts_by_member[member] != expected_verse_contexts(unit) for member, unit in units_by_member.items()):
        raise ValueError("Verse-local apparatus or chapter-zero context differs")
    if len(crosswalk) != 25145 or null_count != 73:
        raise ValueError("Complete source-field or typed-null coverage differs")
    disposition = [node for node in text.iter(T + "note") if node.get("type") == "source-disposition"]
    if len(disposition) != 1 or not disposition[0].text:
        raise ValueError("Collection disposition missing")
    collection = (companion / "collection-context.md").read_text(encoding="utf-8")
    value = PRE.findall(collection)
    if len(value) != 1 or html.fragment_fromstring("<pre>" + value[0] + "</pre>").text_content() != disposition[0].text:
        raise ValueError("Collection disposition wording differs")
    if source_literal_bytes + len(disposition[0].text.encode("utf-8")) != 3781838:
        raise ValueError("Complete nonverse literal byte count differs")
    report = {
        "status": "pass",
        "source_sha256": manifest["source_sha256"],
        "source_units": len(expected_by_member),
        "notice_parts": len(manifest["parts"]),
        "source_fields": len(crosswalk),
        "visible_text_fields": checked_text,
        "typed_json_nulls": null_count,
        "inline_styles": checked_styles,
        "source_line_breaks": checked_breaks,
        "literal_nonverse_bytes": 3781838,
        "readable_hierarchy": "exact source order and labels",
        "verse_context_attachments": sum(len(x) for x in verse_contexts_by_member.values()),
        "manifest_sha256": digest((companion / "manifest.json").read_bytes()),
        "crosswalk_sha256": digest((companion / "private-crosswalk.json").read_bytes()),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--companion", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = check(args.companion)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
