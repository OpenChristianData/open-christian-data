"""Source-bound, nonaccepted PG #8381 constituent reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE = Path("raw/gutenberg/sermons/maclaren/pg8381.txt")
EXPECTED_SHA = "9666a51d24dfcfff7b23d2ddfb2e2fe143a1b742f8951143a9fbde2c67f26841"
HEADING_LINES = (
    156, 426, 743, 978, 1257, 1571, 1845, 2095, 2405, 2724, 3028,
    3327, 3623, 3961, 4226, 4497, 4766, 5035, 5339, 5590, 5889,
    6054, 6162, 6280, 6550, 6864, 7053, 7287, 7528, 7721, 7934,
    8027, 8276, 8528, 8837, 8952, 9201, 9470, 9752, 10079, 10322,
    10651, 11046, 11310, 11577,
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_lines(root: Path) -> list[str]:
    data = (root / SOURCE).read_bytes()
    if sha(data) != EXPECTED_SHA or len(data) != 731722:
        raise ValueError("PG #8381 extracted TXT differs from declared acquisition")
    if not data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("PG #8381 lost its UTF-8 BOM")
    if data.count(b"\r\n") != data.count(b"\r") or data.count(b"\r\n") != data.count(b"\n"):
        raise ValueError("PG #8381 physical lines are not exact CRLF")
    if not data.endswith(b"\r\n"):
        raise ValueError("PG #8381 final CRLF is missing")
    lines = data.decode("utf-8-sig").split("\r\n")[:-1]
    if len(lines) != 12244:
        raise ValueError("PG #8381 line count changed")
    return lines


def _node(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", attributes)


def _line_id(number: int) -> str:
    return f"pg8381-line-{number:05d}"


def _append_line(parent: etree._Element, number: int, value: str, *, heading: bool = False) -> None:
    identity = {f"{{{XML}}}id": _line_id(number), "n": str(number), f"{{{XML}}}space": "preserve"}
    if value == "":
        _node(parent, "milestone", unit="source-empty-line", n=str(number), **{f"{{{XML}}}id": _line_id(number)})
        return
    if heading:
        carrier = _node(parent, "head")
        _node(carrier, "seg", type="source-physical-line", **identity).text = value
        return
    if value.isspace() or value.startswith("*** ") or value == "END OF VOL. III.":
        _node(parent, "ab", type="source-physical-line", **identity).text = value
        return
    paragraph = parent[-1] if len(parent) and parent[-1].tag == f"{{{TEI}}}p" else None
    if paragraph is None:
        paragraph = _node(parent, "p")
    elif len(paragraph):
        _node(paragraph, "lb", n=str(number))
    _node(paragraph, "seg", type="source-physical-line", **identity).text = value


def render(root: Path) -> bytes:
    lines = source_lines(root)
    if len(HEADING_LINES) != 45 or lines[60] != "CONTENTS" or lines[11880] != "END OF VOL. III.":
        raise ValueError("PG #8381 constituent anchors changed")
    if not lines[26].startswith("*** START OF THE PROJECT GUTENBERG EBOOK "):
        raise ValueError("PG #8381 start wrapper changed")
    if not lines[11893].startswith("*** END OF THE PROJECT GUTENBERG EBOOK "):
        raise ValueError("PG #8381 end wrapper changed")
    for number in HEADING_LINES:
        value = lines[number - 1]
        if value.strip() != value.strip().upper() or not value.strip():
            raise ValueError(f"PG #8381 exposition heading changed at {number}")

    tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    tei.set(f"{{{XML}}}id", "maclaren-pg8381-constituent-v1")
    header = _node(tei, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(title_stmt, "title").text = lines[10].partition(": ")[2]
    _node(title_stmt, "author").text = lines[12].partition(": ")[2]
    _node(file_desc, "publicationStmt")
    _node(file_desc[-1], "p").text = "Nonaccepted source-bound candidate; no rights or publication decision."
    source_desc = _node(file_desc, "sourceDesc")
    bibl = _node(source_desc, "bibl")
    _node(bibl, "title").text = lines[10].partition(": ")[2]
    _node(bibl, "idno", type="project-gutenberg-ebook").text = "8381"
    _node(bibl, "idno", type="sha256").text = EXPECTED_SHA
    _node(bibl, "note", type="retained-source-path").text = SOURCE.as_posix()
    text = _node(tei, "text")
    front = _node(text, "front")
    front_div = _node(front, "div", type="electronic-front-and-contents", n="1-155")
    for number in range(1, 156):
        _append_line(front_div, number, lines[number - 1])
    body = _node(text, "body")
    for ordinal, start in enumerate(HEADING_LINES, 1):
        end = HEADING_LINES[ordinal] - 1 if ordinal < len(HEADING_LINES) else 11880
        division = _node(body, "div", type="exposition", n=str(ordinal), **{f"{{{XML}}}id": f"pg8381-exposition-{ordinal:02d}"})
        for number in range(start, end + 1):
            _append_line(division, number, lines[number - 1], heading=number == start)
    back = _node(text, "back")
    back_div = _node(back, "div", type="volume-end-and-gutenberg-license", n="11881-12244")
    for number in range(11881, len(lines) + 1):
        _append_line(back_div, number, lines[number - 1])
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    content = render(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(content)
    print(json.dumps({"candidate": str(args.output), "sha256": sha(content), "expositions": len(HEADING_LINES)}))


if __name__ == "__main__":
    main()
