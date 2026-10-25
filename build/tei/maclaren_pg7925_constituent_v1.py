"""Source-bound, nonaccepted two-volume PG #7925 Psalms reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE = Path("raw/gutenberg/sermons/maclaren/pg7925.txt")
SOURCE_SHA = "18d36d2629476615e2a4a7c7e26c46f431747f306f28947134ed7615c555144a"
VOLUME_HEADS = (56, 10994)
EXPOSITION_HEADS = (
    (142, 565, 795, 1004, 1388, 1642, 2102, 2344, 2622, 2883, 3184,
     3380, 3682, 3927, 4225, 4440, 4677, 4915, 5103, 5353, 5535,
     5810, 6121, 6324, 6514, 6713, 7090, 7443, 7796, 8218, 8489,
     8803, 8986, 9287, 9592, 10013, 10285, 10703),
    (11089, 11496, 11931, 12192, 12408, 12628, 12941, 13163, 13437,
     13730, 13943, 14184, 14367, 14601, 14809, 15077, 15341, 15663,
     15957, 16161, 16374, 16621, 16855, 17104, 17323, 17586, 17767,
     17952, 18405, 18691, 18914, 19145, 19464, 19684, 19874, 20524,
     20693, 20904, 21086, 21404, 21660, 21871, 22130),
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_lines(root: Path) -> list[str]:
    data = (root / SOURCE).read_bytes()
    if len(data) != 1377274 or sha(data) != SOURCE_SHA:
        raise ValueError("PG #7925 retained TXT differs from the bound acquisition")
    if (not data.startswith(b"\xef\xbb\xbf") or not data.endswith(b"\r\n")
            or data.count(b"\r\n") != data.count(b"\r")
            or data.count(b"\r\n") != data.count(b"\n")):
        raise ValueError("PG #7925 source line framing changed")
    lines = data.decode("utf-8-sig").split("\r\n")[:-1]
    if len(lines) != 22708:
        raise ValueError("PG #7925 physical line count changed")
    return lines


def node(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", attributes)


def add_line(parent: etree._Element, number: int, value: str, *, heading: bool = False) -> None:
    identity = {f"{{{XML}}}id": f"pg7925-line-{number:05d}", "n": str(number),
                f"{{{XML}}}space": "preserve"}
    if not value:
        node(parent, "milestone", unit="source-empty-line", n=str(number),
             **{f"{{{XML}}}id": f"pg7925-line-{number:05d}"})
    elif heading:
        head = node(parent, "head")
        node(head, "seg", type="source-physical-line", **identity).text = value
    elif value.isspace() or value.startswith("*** ") or value.startswith("END OF VOL."):
        node(parent, "ab", type="source-physical-line", **identity).text = value
    else:
        paragraph = parent[-1] if len(parent) and parent[-1].tag == f"{{{TEI}}}p" else None
        if paragraph is None:
            paragraph = node(parent, "p")
        elif len(paragraph):
            node(paragraph, "lb", n=str(number))
        node(paragraph, "seg", type="source-physical-line", **identity).text = value


def add_span(parent: etree._Element, lines: list[str], first: int, last: int,
             *, heading: int | None = None) -> None:
    for number in range(first, last + 1):
        add_line(parent, number, lines[number - 1], heading=number == heading)


def render(root: Path) -> bytes:
    lines = source_lines(root)
    anchors = {
        56: "VOLUME I: PSALMS _I to XLIX_", 59: "CONTENTS",
        10988: "END OF VOL. I.", 10994: "VOLUME II: PSALMS _LI to CXLV_",
        10997: "CONTENTS", 22346: "END OF VOL. II.",
    }
    if any(lines[number - 1] != value for number, value in anchors.items()):
        raise ValueError("PG #7925 volume or contents anchors changed")
    if lines[10702] != "TWO SHEPHERDS AND TWO FLOCKS":
        raise ValueError("PG #7925 unlisted exposition heading changed")
    if (not lines[26].startswith("*** START OF THE PROJECT GUTENBERG EBOOK ")
            or not lines[22357].startswith("*** END OF THE PROJECT GUTENBERG EBOOK ")):
        raise ValueError("PG #7925 electronic wrapper changed")
    for group in EXPOSITION_HEADS:
        for number in group:
            title = lines[number - 1].strip()
            if not title or title != title.upper():
                raise ValueError(f"PG #7925 exposition heading changed at {number}")

    tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    tei.set(f"{{{XML}}}id", "maclaren-pg7925-psalms-constituent-v1")
    header = node(tei, "teiHeader")
    description = node(header, "fileDesc")
    titles = node(description, "titleStmt")
    node(titles, "title").text = lines[10].partition(": ")[2]
    node(titles, "author").text = lines[12].partition(": ")[2]
    publication = node(description, "publicationStmt")
    node(publication, "p").text = "Nonaccepted source-bound candidate; no rights or publication decision."
    bibliography = node(node(description, "sourceDesc"), "bibl")
    node(bibliography, "title").text = lines[10].partition(": ")[2]
    node(bibliography, "idno", type="project-gutenberg-ebook").text = "7925"
    node(bibliography, "idno", type="sha256").text = SOURCE_SHA
    node(bibliography, "note", type="retained-source-path").text = SOURCE.as_posix()
    text = node(tei, "text")
    front = node(text, "front")
    add_span(node(front, "div", type="electronic-front", n="1-55"), lines, 1, 55)
    body = node(text, "body")
    for ordinal, (first, last, title, toc_end, ending) in enumerate((
        (56, 10988, 56, 141, 10988),
        (10994, 22346, 10994, 11088, 22346),
    ), 1):
        volume = node(body, "div", type="printed-volume", n=str(ordinal),
                      **{f"{{{XML}}}id": f"pg7925-volume-{ordinal}"})
        add_line(volume, title, lines[title - 1], heading=True)
        contents = node(volume, "div", type="volume-contents", n=f"{title + 1}-{toc_end}")
        add_span(contents, lines, title + 1, toc_end)
        starts = EXPOSITION_HEADS[ordinal - 1]
        for index, start in enumerate(starts, 1):
            stop = starts[index] - 1 if index < len(starts) else ending - 1
            exposition = node(volume, "div", type="exposition", n=str(index),
                              **{f"{{{XML}}}id": f"pg7925-v{ordinal}-exposition-{index:02d}"})
            add_span(exposition, lines, start, stop, heading=start)
        add_span(node(volume, "div", type="volume-end", n=str(ending)), lines,
                 ending, ending)
    gap = node(body, "div", type="inter-volume-gap", n="10989-10993")
    add_span(gap, lines, 10989, 10993)
    # The source order is volume I, five blank separator lines, volume II.
    body.remove(gap)
    body.insert(1, gap)
    back = node(text, "back")
    add_span(node(back, "div", type="gutenberg-tail", n="22347-22708"),
             lines, 22347, len(lines))
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    content = render(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(content)
    print(json.dumps({"candidate": str(args.output), "sha256": sha(content),
                      "printed_volumes": 2, "expositions": 81}))


if __name__ == "__main__":
    main()
