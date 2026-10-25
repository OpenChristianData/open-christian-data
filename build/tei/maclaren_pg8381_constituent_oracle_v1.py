"""Independent source-to-readable-TEI check for the PG #8381 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from lxml import etree

SOURCE = Path("raw/gutenberg/sermons/maclaren/pg8381.txt")
SOURCE_SHA = "9666a51d24dfcfff7b23d2ddfb2e2fe143a1b742f8951143a9fbde2c67f26841"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"t": TEI}


def _source(root: Path) -> list[str]:
    data = (root / SOURCE).read_bytes()
    if len(data) != 731722 or hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError("retained extracted TXT bytes differ from acquired PG #8381")
    if not data.startswith(b"\xef\xbb\xbf") or data.count(b"\r\n") != data.count(b"\n") or data.count(b"\r\n") != data.count(b"\r") or not data.endswith(b"\r\n"):
        raise ValueError("retained extracted TXT line framing changed")
    lines = data.decode("utf-8-sig").split("\r\n")[:-1]
    if len(lines) != 12244:
        raise ValueError("retained extracted TXT line count changed")
    return lines


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    if lines[60] != "CONTENTS" or lines[153:155] != ["", ""]:
        raise ValueError("source contents boundary changed")
    contents = [(i + 1, lines[i].rsplit(" (John", 1)[0]) for i in range(63, 152, 2)]
    if len(contents) != 45 or any(" (John" not in lines[i - 1] for i, _ in contents):
        raise ValueError("source contents entries changed")
    def normalize(value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", value.upper())

    candidates = [
        (i + 1, line.strip())
        for i, line in enumerate(lines[155:11880], start=155)
        if line.strip() and line.strip() == line.strip().upper()
        and any(character.isalpha() for character in line)
    ]
    result: list[tuple[int, int, str]] = []
    for toc_line, title in contents:
        # The contents prints OP; the body prints OF. Both literal forms survive.
        expected = title.replace("THE JOYS OP 'THAT DAY'", "THE JOYS OF 'THAT DAY'")
        matches = [(number, text) for number, text in candidates if normalize(text) == normalize(expected)]
        if len(matches) != 1:
            raise ValueError(f"contents entry {toc_line} has {len(matches)} body headings")
        result.append((toc_line, matches[0][0], matches[0][1]))
    positions = [number for _, number, _ in result]
    if positions != sorted(set(positions)) or positions[0] != 156 or positions[-1] != 11577:
        raise ValueError("body heading order or scope changed")
    # All title-like lines outside those 45 remain readable body text, especially
    # the uppercase quotation on line 7930 and an indented heading on line 9470.
    return result


def _carrier(node: etree._Element) -> tuple[int, str] | None:
    if node.tag == f"{{{TEI}}}milestone" and node.get("unit") == "source-empty-line":
        return int(node.get("n")), ""
    if node.tag == f"{{{TEI}}}ab" and node.get("type") == "source-physical-line":
        return int(node.get("n")), node.text or ""
    if node.tag == f"{{{TEI}}}seg" and node.get("type") == "source-physical-line":
        return int(node.get("n")), node.text or ""
    return None



def _children(node: etree._Element, expected: list[str]) -> list[etree._Element]:
    children = list(node)
    if [child.tag for child in children] != [f"{{{TEI}}}{name}" for name in expected]:
        raise ValueError(f"unexpected candidate structure under {node.tag}")
    if node.text not in (None, ""):
        raise ValueError(f"unaccounted candidate text under {node.tag}")
    return children


def _check_complete_text_tree(root: etree._Element, lines: list[str]) -> None:
    # Every literal in the header is either source metadata or this declared
    # candidate status. Every text-region literal belongs to a source carrier.
    for node in root.iter():
        if not isinstance(node.tag, str) or node.tail not in (None, ""):
            raise ValueError("unaccounted candidate tail or non-TEI node")
    header, text = _children(root, ["teiHeader", "text"])
    file_desc, = _children(header, ["fileDesc"])
    title_stmt, publication, source_desc = _children(
        file_desc, ["titleStmt", "publicationStmt", "sourceDesc"]
    )
    title, author = _children(title_stmt, ["title", "author"])
    publication_note, = list(publication)
    if publication_note.tag != f"{{{TEI}}}p":
        raise ValueError("candidate publication statement changed")
    bibliography, = _children(source_desc, ["bibl"])
    bibl_title, pg_number, source_hash, source_path = _children(
        bibliography, ["title", "idno", "idno", "note"]
    )
    expected_header = (
        (title, lines[10].partition(": ")[2], {}),
        (author, lines[12].partition(": ")[2], {}),
        (publication_note, "Nonaccepted source-bound candidate; no rights or publication decision.", {}),
        (bibl_title, lines[10].partition(": ")[2], {}),
        (pg_number, "8381", {"type": "project-gutenberg-ebook"}),
        (source_hash, SOURCE_SHA, {"type": "sha256"}),
        (source_path, SOURCE.as_posix(), {"type": "retained-source-path"}),
    )
    for node, expected_text, expected_attributes in expected_header:
        if list(node) or node.text != expected_text or dict(node.attrib) != expected_attributes:
            raise ValueError(f"candidate header literal or metadata changed: {node.tag}")
    if publication.text not in (None, ""):
        raise ValueError("unaccounted publication text")
    front, body, back = _children(text, ["front", "body", "back"])
    front_div, = _children(front, ["div"])
    back_div, = _children(back, ["div"])
    body_divs = list(body)
    if body.text not in (None, "") or any(div.tag != f"{{{TEI}}}div" for div in body_divs):
        raise ValueError("unexpected body structure or text")
    if dict(front_div.attrib) != {"type": "electronic-front-and-contents", "n": "1-155"}:
        raise ValueError("front region identity changed")
    if dict(back_div.attrib) != {"type": "volume-end-and-gutenberg-license", "n": "11881-12244"}:
        raise ValueError("back region identity changed")
    for index, division in enumerate(body_divs, 1):
        if dict(division.attrib) != {
            "type": "exposition", "n": str(index), XML_ID: f"pg8381-exposition-{index:02d}"
        }:
            raise ValueError("exposition identity changed")

    for region in [front_div, *body_divs, back_div]:
        if region.text not in (None, ""):
            raise ValueError("unaccounted region text")
        children = list(region)
        if region in body_divs:
            if not children or children[0].tag != f"{{{TEI}}}head":
                raise ValueError("exposition head missing or misplaced")
            head = children.pop(0)
            segment, = _children(head, ["seg"])
            if list(segment) or segment.get("type") != "source-physical-line":
                raise ValueError("exposition head has unaccounted content")
        for block in children:
            if block.tag == f"{{{TEI}}}p":
                blocks = list(block)
                if block.text not in (None, "") or not blocks or len(blocks) % 2 != 1:
                    raise ValueError("unaccounted paragraph text or incomplete source line sequence")
                for position, item in enumerate(blocks):
                    if position % 2 == 0:
                        if item.tag != f"{{{TEI}}}seg" or item.get("type") != "source-physical-line" or list(item):
                            raise ValueError("unexpected paragraph source carrier")
                    else:
                        if item.tag != f"{{{TEI}}}lb" or item.text not in (None, "") or list(item):
                            raise ValueError("unexpected paragraph line break")
                        if item.get("n") != blocks[position + 1].get("n"):
                            raise ValueError("paragraph line break loses its source line")
            elif block.tag == f"{{{TEI}}}ab":
                if block.get("type") != "source-physical-line" or list(block):
                    raise ValueError("unexpected standalone source carrier")
            elif block.tag == f"{{{TEI}}}milestone":
                if block.get("unit") != "source-empty-line" or block.text not in (None, "") or list(block):
                    raise ValueError("unexpected source blank-line marker")
            else:
                raise ValueError(f"unaccounted candidate block {block.tag}")
    # Source blank lines and wrappers determine paragraph grouping. A line
    # moved to a neighboring paragraph must fail even when its ordinal stays.
    heading_positions = [number for _, number, _ in _headings(lines)]
    region_spans = [(front_div, 1, 155, False)]
    region_spans.extend(
        (
            division,
            start,
            heading_positions[index] - 1 if index < len(heading_positions) else 11880,
            True,
        )
        for index, (division, start) in enumerate(
            zip(body_divs, heading_positions, strict=True), 1
        )
    )
    region_spans.append((back_div, 11881, len(lines), False))
    for region, first, last, has_head in region_spans:
        expected_blocks: list[tuple[str, list[int]]] = []
        for number in range(first, last + 1):
            value = lines[number - 1]
            if has_head and number == first:
                expected_blocks.append(("head", [number]))
            elif value == "":
                expected_blocks.append(("milestone", [number]))
            elif value.isspace() or value.startswith("*** ") or value == "END OF VOL. III.":
                expected_blocks.append(("ab", [number]))
            elif expected_blocks and expected_blocks[-1][0] == "p":
                expected_blocks[-1][1].append(number)
            else:
                expected_blocks.append(("p", [number]))
        if len(region) != len(expected_blocks):
            raise ValueError("source paragraph or carrier ownership changed")
        for block, (name, expected_numbers) in zip(region, expected_blocks, strict=True):
            numbers = [
                carrier[0] for node in block.iter()
                if (carrier := _carrier(node)) is not None
            ]
            if block.tag != f"{{{TEI}}}{name}" or numbers != expected_numbers:
                raise ValueError("source paragraph or carrier ownership changed")

    permitted_attributes = {
        f"{{{TEI}}}idno": {"type"},
        f"{{{TEI}}}note": {"type"},
        f"{{{TEI}}}div": {"type", "n", XML_ID},
        f"{{{TEI}}}seg": {"type", "n", XML_ID, "{http://www.w3.org/XML/1998/namespace}space"},
        f"{{{TEI}}}ab": {"type", "n", XML_ID, "{http://www.w3.org/XML/1998/namespace}space"},
        f"{{{TEI}}}milestone": {"unit", "n", XML_ID},
        f"{{{TEI}}}lb": {"n"},
    }
    for node in root.iter():
        if node is root:
            if dict(node.attrib) != {XML_ID: "maclaren-pg8381-constituent-v1"}:
                raise ValueError("candidate root attributes changed")
            continue
        if set(node.attrib) - permitted_attributes.get(node.tag, set()):
            raise ValueError(f"unaccounted candidate attribute on {node.tag}")
        if node.tag in (f"{{{TEI}}}seg", f"{{{TEI}}}ab"):
            number = node.get("n")
            if not number or not number.isdecimal() or dict(node.attrib) != {
                "type": "source-physical-line",
                "n": number,
                XML_ID: f"pg8381-line-{int(number):05d}",
                "{http://www.w3.org/XML/1998/namespace}space": "preserve",
            }:
                raise ValueError("source carrier attributes changed")
        elif node.tag == f"{{{TEI}}}milestone":
            number = node.get("n")
            if not number or not number.isdecimal() or dict(node.attrib) != {
                "unit": "source-empty-line",
                "n": number,
                XML_ID: f"pg8381-line-{int(number):05d}",
            }:
                raise ValueError("source blank-line attributes changed")
    # No source-bearing text can hide outside the front/body/back tree.
    for node in text.iter():
        if node.tag not in {f"{{{TEI}}}{name}" for name in (
            "text", "front", "body", "back", "div", "head", "p", "seg", "lb", "ab", "milestone"
        )}:
            raise ValueError(f"unaccounted candidate element {node.tag}")

def check_tree(tree: etree._ElementTree, lines: list[str]) -> dict[str, object]:
    root = tree.getroot()
    if root.tag != f"{{{TEI}}}TEI" or root.get(XML_ID) != "maclaren-pg8381-constituent-v1":
        raise ValueError("candidate document identity differs")
    _check_complete_text_tree(root, lines)
    front = root.xpath("./t:text/t:front/t:div", namespaces=NS)
    body = root.xpath("./t:text/t:body/t:div", namespaces=NS)
    back = root.xpath("./t:text/t:back/t:div", namespaces=NS)
    headings = _headings(lines)
    if len(front) != 1 or front[0].get("type") != "electronic-front-and-contents":
        raise ValueError("front matter is missing or misplaced")
    if len(body) != len(headings):
        raise ValueError("exposition count differs from source contents")
    if len(back) != 1 or back[0].get("type") != "volume-end-and-gutenberg-license":
        raise ValueError("volume ending or Gutenberg license is misplaced")
    for index, (division, (_, heading_line, source_heading)) in enumerate(zip(body, headings, strict=True), 1):
        heads = division.xpath("./t:head/t:seg[@type='source-physical-line']", namespaces=NS)
        if division.get("type") != "exposition" or division.get("n") != str(index) or len(heads) != 1:
            raise ValueError(f"exposition {index} lacks one named division and head")
        if heads[0].get("n") != str(heading_line) or heads[0].text != lines[heading_line - 1]:
            raise ValueError(f"exposition {index} heading differs from source line {heading_line}")
        if heads[0].text.strip() != source_heading:
            raise ValueError(f"exposition {index} title differs from source")
    expected_regions = [(front[0], 1, 155)]
    expected_regions += [
        (division, position, headings[index][1] - 1 if index < len(headings) else 11880)
        for index, (division, (_, position, _)) in enumerate(zip(body, headings, strict=True), 1)
    ]
    expected_regions.append((back[0], 11881, len(lines)))
    seen: list[int] = []
    for region, first, last in expected_regions:
        carriers = [(node, carrier) for node in region.iter() if (carrier := _carrier(node)) is not None]
        if [number for _, (number, _) in carriers] != list(range(first, last + 1)):
            raise ValueError(f"region {first}-{last} omits, duplicates, or reorders source lines")
        for node, (number, text) in carriers:
            if text != lines[number - 1]:
                raise ValueError(f"source line {number} text changed")
            if node.get(XML_ID) != f"pg8381-line-{number:05d}":
                raise ValueError(f"source line {number} identity changed")
            seen.append(number)
    if seen != list(range(1, len(lines) + 1)):
        raise ValueError("complete source line coverage differs")
    if lines[11880] != "END OF VOL. III." or not lines[11893].startswith("*** END OF THE PROJECT GUTENBERG EBOOK ") or lines[11921] != "START: FULL LICENSE":
        raise ValueError("volume ending or license source anchors changed")
    return {"source_lines": len(lines), "expositions": len(headings), "front_lines": 155, "body_lines": 11725, "back_lines": len(lines) - 11880, "heading_lines": [position for _, position, _ in headings]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    lines = _source(args.root)
    candidate = args.candidate.read_bytes()
    tree = etree.ElementTree(etree.fromstring(candidate))
    result = check_tree(tree, lines)
    schema = etree.XMLSchema(etree.parse(str(args.root / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    if not schema.validate(tree):
        raise ValueError(f"TEI P5 XSD failed: {schema.error_log}")
    result.update({"contract": "maclaren-pg8381-constituent-oracle-v1", "source_sha256": SOURCE_SHA, "candidate_sha256": hashlib.sha256(candidate).hexdigest(), "tei_p5_xsd": "valid", "status": "nonaccepted"})
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.receipt:
        args.receipt.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
