"""Independent source-derived structure and text check for the PG #7925 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from lxml import etree

SOURCE = Path("raw/gutenberg/sermons/maclaren/pg7925.txt")
SOURCE_SHA = "18d36d2629476615e2a4a7c7e26c46f431747f306f28947134ed7615c555144a"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NS = {"t": TEI}


def retained_lines(root: Path) -> list[str]:
    data = (root / SOURCE).read_bytes()
    if len(data) != 1377274 or hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError("PG #7925 retained TXT differs from its acquired source")
    if (not data.startswith(b"\xef\xbb\xbf") or not data.endswith(b"\r\n")
            or data.count(b"\r\n") != data.count(b"\r")
            or data.count(b"\r\n") != data.count(b"\n")):
        raise ValueError("PG #7925 physical line framing changed")
    lines = data.decode("utf-8-sig").split("\r\n")[:-1]
    if len(lines) != 22708:
        raise ValueError("PG #7925 physical line count changed")
    return lines


def source_structure(lines: list[str]) -> tuple[list[int], list[int]]:
    anchors = {56: "VOLUME I: PSALMS _I to XLIX_", 59: "CONTENTS",
               10988: "END OF VOL. I.", 10994: "VOLUME II: PSALMS _LI to CXLV_",
               10997: "CONTENTS", 22346: "END OF VOL. II."}
    if any(lines[number - 1] != text for number, text in anchors.items()):
        raise ValueError("source-printed volume or contents boundary changed")
    normalize = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())
    groups: list[list[int]] = []
    for toc_first, toc_last, body_first, body_last in (
        (62, 137, 142, 10987), (11000, 11084, 11089, 22345)
    ):
        contents = [(number, lines[number - 1].rsplit(" (Psalm", 1)[0])
                    for number in range(toc_first, toc_last + 1)
                    if " (Psalm" in lines[number - 1]]
        bodies = [(number, lines[number - 1].strip())
                  for number in range(body_first, body_last + 1)
                  if lines[number - 1].strip()
                  and lines[number - 1].strip() == lines[number - 1].strip().upper()
                  and any(letter.isalpha() for letter in lines[number - 1])]
        if len(contents) not in (38, 43):
            raise ValueError("source contents count changed")
        matched: list[int] = []
        for toc_line, title in contents:
            hits = [number for number, body_title in bodies
                    if normalize(body_title) == normalize(title)]
            if len(hits) != 1:
                raise ValueError(f"contents entry {toc_line} has {len(hits)} body headings")
            matched.append(hits[0])
        extra = [(number, title) for number, title in bodies if number not in matched]
        if extra:
            raise ValueError(f"body headings omitted from source contents: {extra}")
        if body_first == 142 and ("PSALM xlix. 14." not in lines[10707 - 1]
                                  or "REV. vii. 17." not in lines[10710 - 1]):
            raise ValueError("last first-volume exposition epigraph changed")
        if matched != sorted(set(matched)) or matched[0] != body_first:
            raise ValueError("source exposition order changed")
        groups.append(matched)
    if [len(group) for group in groups] != [38, 43]:
        raise ValueError("source exposition group counts changed")
    return groups[0], groups[1]


def _children(parent: etree._Element, names: list[str]) -> list[etree._Element]:
    children = list(parent)
    if [child.tag for child in children] != [f"{{{TEI}}}{name}" for name in names]:
        raise ValueError(f"candidate structure changed under {parent.tag}")
    if parent.text not in (None, ""):
        raise ValueError(f"unaccounted text under {parent.tag}")
    return children


def _source_carrier(element: etree._Element) -> tuple[int, str] | None:
    tag = element.tag
    if tag == f"{{{TEI}}}milestone" and element.get("unit") == "source-empty-line":
        return int(element.get("n")), ""
    if tag in (f"{{{TEI}}}seg", f"{{{TEI}}}ab") and element.get("type") == "source-physical-line":
        return int(element.get("n")), element.text or ""
    return None


def _check_region(region: etree._Element, lines: list[str], first: int, last: int,
                  *, heading: int | None = None) -> None:
    actual = [(element, pair) for element in region.iter()
              if (pair := _source_carrier(element)) is not None]
    if [pair[0] for _, pair in actual] != list(range(first, last + 1)):
        raise ValueError(f"source lines {first}-{last} missing, duplicated, reordered, or wrongly attached")
    for element, (number, text) in actual:
        if text != lines[number - 1] or element.get(XML_ID) != f"pg7925-line-{number:05d}":
            raise ValueError(f"source line {number} changed")
        if element.tag == f"{{{TEI}}}milestone":
            expected = {"unit": "source-empty-line", "n": str(number), XML_ID: f"pg7925-line-{number:05d}"}
        else:
            expected = {"type": "source-physical-line", "n": str(number),
                        XML_ID: f"pg7925-line-{number:05d}", XML_SPACE: "preserve"}
        if dict(element.attrib) != expected or list(element):
            raise ValueError(f"source carrier {number} has invented structure or attributes")
    expected_blocks: list[tuple[str, list[int]]] = []
    for number in range(first, last + 1):
        value = lines[number - 1]
        if number == heading:
            expected_blocks.append(("head", [number]))
        elif not value:
            expected_blocks.append(("milestone", [number]))
        elif value.isspace() or value.startswith("*** ") or value.startswith("END OF VOL."):
            expected_blocks.append(("ab", [number]))
        elif expected_blocks and expected_blocks[-1][0] == "p":
            expected_blocks[-1][1].append(number)
        else:
            expected_blocks.append(("p", [number]))
    if len(region) != len(expected_blocks):
        raise ValueError(f"source paragraph or heading groups changed at {first}-{last}")
    for block, (name, numbers) in zip(region, expected_blocks, strict=True):
        if block.tag != f"{{{TEI}}}{name}" or (name != "ab" and block.text not in (None, "")):
            raise ValueError(f"source block type or text changed at {first}-{last}")
        carriers = [pair[0] for element in block.iter()
                    if (pair := _source_carrier(element)) is not None]
        if carriers != numbers:
            raise ValueError(f"source paragraph grouping changed at {first}-{last}")
        if name == "head":
            _children(block, ["seg"])
        elif name == "p":
            children = list(block)
            if [child.tag for child in children] != [f"{{{TEI}}}{'seg' if i % 2 == 0 else 'lb'}"
                                                       for i in range(2 * len(numbers) - 1)]:
                raise ValueError("source paragraph line-break layout changed")
            for i, child in enumerate(children):
                if i % 2 and (dict(child.attrib) != {"n": str(numbers[(i + 1) // 2])}
                              or child.text not in (None, "") or list(child)):
                    raise ValueError("source paragraph line break changed")
        elif list(block):
            raise ValueError("standalone source block gained children")


def check_tree(tree: etree._ElementTree, lines: list[str]) -> dict[str, object]:
    first_heads, second_heads = source_structure(lines)
    root = tree.getroot()
    if root.tag != f"{{{TEI}}}TEI" or dict(root.attrib) != {
        XML_ID: "maclaren-pg7925-psalms-constituent-v1"
    }:
        raise ValueError("candidate document identity changed")
    for element in root.iter():
        if not isinstance(element.tag, str) or element.tail not in (None, ""):
            raise ValueError("candidate has unaccounted tail or node")
    header, text = _children(root, ["teiHeader", "text"])
    description, = _children(header, ["fileDesc"])
    title_stmt, publication, source_desc = _children(
        description, ["titleStmt", "publicationStmt", "sourceDesc"])
    title, author = _children(title_stmt, ["title", "author"])
    statement, = _children(publication, ["p"])
    bibliography, = _children(source_desc, ["bibl"])
    bibl_title, pg_id, source_hash, source_path = _children(
        bibliography, ["title", "idno", "idno", "note"])
    expected_header = (
        (title, lines[10].partition(": ")[2], {}),
        (author, lines[12].partition(": ")[2], {}),
        (statement, "Nonaccepted source-bound candidate; no rights or publication decision.", {}),
        (bibl_title, lines[10].partition(": ")[2], {}),
        (pg_id, "7925", {"type": "project-gutenberg-ebook"}),
        (source_hash, SOURCE_SHA, {"type": "sha256"}),
        (source_path, SOURCE.as_posix(), {"type": "retained-source-path"}),
    )
    for element, value, attributes in expected_header:
        if element.text != value or dict(element.attrib) != attributes or list(element):
            raise ValueError("candidate header source attribution or status changed")
    front, body, back = _children(text, ["front", "body", "back"])
    front_div, = _children(front, ["div"])
    volume_one, gap, volume_two = _children(body, ["div", "div", "div"])
    back_div, = _children(back, ["div"])
    for div, expected in ((front_div, {"type": "electronic-front", "n": "1-55"}),
                          (gap, {"type": "inter-volume-gap", "n": "10989-10993"}),
                          (back_div, {"type": "gutenberg-tail", "n": "22347-22708"})):
        if dict(div.attrib) != expected:
            raise ValueError("source envelope region identity changed")
    _check_region(front_div, lines, 1, 55)
    _check_region(gap, lines, 10989, 10993)
    _check_region(back_div, lines, 22347, len(lines))
    for ordinal, volume, starts, title, toc_end, ending in (
        (1, volume_one, first_heads, 56, 141, 10988),
        (2, volume_two, second_heads, 10994, 11088, 22346),
    ):
        if dict(volume.attrib) != {"type": "printed-volume", "n": str(ordinal),
                                   XML_ID: f"pg7925-volume-{ordinal}"}:
            raise ValueError("printed volume identity changed")
        head = volume[0]
        if head.tag != f"{{{TEI}}}head":
            raise ValueError("printed volume title lost its readable head")
        title_carrier, = _children(head, ["seg"])
        if _source_carrier(title_carrier) != (title, lines[title - 1]):
            raise ValueError("printed volume title changed")
        parts = list(volume)[1:]
        if len(parts) != len(starts) + 2 or any(part.tag != f"{{{TEI}}}div" for part in parts):
            raise ValueError("printed volume parts changed")
        contents, *expositions, volume_end = parts
        if dict(contents.attrib) != {"type": "volume-contents", "n": f"{title + 1}-{toc_end}"}:
            raise ValueError("volume contents identity changed")
        _check_region(contents, lines, title + 1, toc_end)
        for index, exposition in enumerate(expositions, 1):
            start = starts[index - 1]
            stop = starts[index] - 1 if index < len(starts) else ending - 1
            if dict(exposition.attrib) != {"type": "exposition", "n": str(index),
                                            XML_ID: f"pg7925-v{ordinal}-exposition-{index:02d}"}:
                raise ValueError(f"exposition {ordinal}:{index} identity changed")
            _check_region(exposition, lines, start, stop, heading=start)
        if dict(volume_end.attrib) != {"type": "volume-end", "n": str(ending)}:
            raise ValueError("printed volume end identity changed")
        _check_region(volume_end, lines, ending, ending)
    carriers = [_source_carrier(element) for element in text.iter()]
    numbers = [item[0] for item in carriers if item is not None]
    if numbers != list(range(1, len(lines) + 1)):
        raise ValueError("complete electronic source order or coverage changed")
    allowed = {"text", "front", "body", "back", "div", "head", "p", "seg", "lb", "ab", "milestone"}
    for element in text.iter():
        if element.tag not in {f"{{{TEI}}}{name}" for name in allowed}:
            raise ValueError("unexpected source text element")
        if element.tag not in (f"{{{TEI}}}seg", f"{{{TEI}}}ab") and element.text not in (None, ""):
            raise ValueError("unaccounted readable text outside source carriers")
        if element.tag not in {f"{{{TEI}}}{name}" for name in ("div", "seg", "ab", "milestone", "lb")}:
            if element.attrib:
                raise ValueError("invented semantic source attribute")
    return {"source_lines": len(lines), "printed_volumes": 2,
            "toc_entries": [38, 43], "expositions": [len(first_heads), len(second_heads)],
            "last_first_volume_exposition_heading_line": 10703,
            "heading_lines": [first_heads, second_heads]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    lines = retained_lines(args.root)
    candidate = args.candidate.read_bytes()
    tree = etree.ElementTree(etree.fromstring(candidate))
    result = check_tree(tree, lines)
    schema = etree.XMLSchema(etree.parse(str(args.root / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    if not schema.validate(tree):
        raise ValueError(f"TEI P5 XSD failed: {schema.error_log}")
    result.update({"contract": "maclaren-pg7925-psalms-constituent-oracle-v1",
                   "source_sha256": SOURCE_SHA,
                   "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                   "tei_p5_xsd": "valid", "status": "nonaccepted"})
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.receipt:
        args.receipt.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
