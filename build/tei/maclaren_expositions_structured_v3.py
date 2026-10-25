"""One nonaccepted, source-structured TEI for the exact 15-member PG cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
MAP = Path("sources/sermons/maclaren-expositions/full-cohort-v3/source-structure-map.json")
MAP_SHA = "a7e40fe8f1eae31d5ceac9bbc9f14db3ad6f8d76df24bb8e20ff174cda4bd5bc"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def node(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", attributes)


def source_lines(root: Path, member: dict[str, object]) -> list[str]:
    data = (root / str(member["path"])).read_bytes()
    if len(data) != member["bytes"] or sha(data) != member["sha256"]:
        raise ValueError(f"PG #{member['pg_id']} differs from frozen cohort map")
    if (not data.startswith(b"\xef\xbb\xbf") or not data.endswith(b"\r\n")
            or data.count(b"\r\n") != data.count(b"\n")
            or data.count(b"\r\n") != data.count(b"\r")):
        raise ValueError(f"PG #{member['pg_id']} source physical line framing changed")
    lines = data.decode("utf-8-sig").split("\r\n")[:-1]
    if len(lines) != member["physical_line_count"]:
        raise ValueError(f"PG #{member['pg_id']} source line count changed")
    return lines


def add_line(parent: etree._Element, pg: str, number: int, value: str,
             *, role: str | None = None) -> None:
    line_id = f"pg{pg}-line-{number:06d}"
    identity = {f"{{{XML}}}id": line_id, "n": str(number), f"{{{XML}}}space": "preserve"}
    if role in ("book-section", "exposition", "contents"):
        head = node(parent, "head")
        node(head, "seg", type="source-physical-line", **identity).text = value
    elif not value:
        node(parent, "milestone", unit="source-empty-line", n=str(number),
             **{f"{{{XML}}}id": line_id})
    elif value.isspace() or value.startswith("*** ") or value.strip() == value.strip().upper():
        kind = role if role in ("internal-subsection", "verse-column-label") else "source-uppercase-line"
        node(parent, "ab", type=kind, **identity).text = value
    else:
        paragraph = parent[-1] if len(parent) and parent[-1].tag == f"{{{TEI}}}p" else None
        if paragraph is None:
            paragraph = node(parent, "p")
        elif len(paragraph):
            node(paragraph, "lb", n=str(number))
        node(paragraph, "seg", type="source-physical-line", **identity).text = value


def add_span(parent: etree._Element, pg: str, lines: list[str], first: int, last: int,
             *, first_head: bool = False) -> None:
    for number in range(first, last + 1):
        add_line(parent, pg, number, lines[number - 1],
                 role="contents" if first_head and number == first else None)


def render(root: Path) -> bytes:
    mapping_data = (root / MAP).read_bytes()
    if sha(mapping_data) != MAP_SHA:
        raise ValueError("Maclaren frozen full-cohort structure map changed")
    mapping = json.loads(mapping_data)
    if (mapping["contract"] != "maclaren-expositions-structured-cohort-map-v3"
            or mapping["source_member_count"] != 15
            or mapping["source_line_count"] != 339526):
        raise ValueError("Maclaren full-cohort structure map scope changed")
    tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    tei.set(f"{{{XML}}}id", "maclaren-expositions-full-cohort-v3")
    header = node(tei, "teiHeader")
    description = node(header, "fileDesc")
    titles = node(description, "titleStmt")
    node(titles, "title").text = "Expositions of Holy Scripture"
    node(titles, "author").text = "Alexander Maclaren"
    publication = node(description, "publicationStmt")
    node(publication, "p").text = "Nonaccepted source-bound candidate; rights and publication decisions remain open."
    source_desc = node(description, "sourceDesc")
    bibls = node(source_desc, "listBibl")
    for member in mapping["members"]:
        bibl = node(bibls, "bibl", **{f"{{{XML}}}id": f"bibl-pg{member['pg_id']}"})
        node(bibl, "title").text = "Project Gutenberg electronic member of Expositions of Holy Scripture"
        node(bibl, "idno", type="project-gutenberg-ebook").text = str(member["pg_id"])
        node(bibl, "idno", type="sha256").text = str(member["sha256"])
        node(bibl, "note", type="retained-path").text = str(member["path"])
    body = node(node(tei, "text"), "body")
    for order, member in enumerate(mapping["members"], 1):
        pg = str(member["pg_id"])
        lines = source_lines(root, member)
        source_member = node(body, "div", type="source-member", n=str(order),
                             **{f"{{{XML}}}id": f"member-pg{pg}"})
        for part in member["parts"]:
            index = int(part["index"])
            if part["kind"] == "printed-volumes-I-II-undivided":
                kind = "printed-volume-group"
            elif str(part["kind"]).startswith("printed-volume-"):
                kind = "printed-volume"
            else:
                kind = "source-part"
            part_div = node(source_member, "div", type=kind, n=str(index),
                            **{f"{{{XML}}}id": f"pg{pg}-part-{index}"})
            title_div = node(part_div, "div", type="source-title-and-wrapper",
                             n=f"{part['line_start']}-{int(part['contents_line']) - 1}")
            add_span(title_div, pg, lines, int(part["line_start"]), int(part["contents_line"]) - 1)
            contents_div = node(part_div, "div", type="contents",
                                n=f"{part['contents_line']}-{int(part['body_start']) - 1}")
            add_span(contents_div, pg, lines, int(part["contents_line"]),
                     int(part["body_start"]) - 1, first_head=True)
            heading_by_line = {int(row["line"]): row for row in part["headings"]}
            book: etree._Element | None = None
            exposition: etree._Element | None = None
            book_index = 0
            exposition_index = 0
            for number in range(int(part["body_start"]), int(part["body_end"]) + 1):
                row = heading_by_line.get(number)
                role = str(row["role"]) if row else None
                if row and row["text"] != lines[number - 1]:
                    raise ValueError(f"PG #{pg} frozen heading line {number} changed")
                if role == "book-section":
                    book_index += 1
                    book = node(part_div, "div", type="book-section", n=str(book_index),
                                **{f"{{{XML}}}id": f"pg{pg}-p{index}-book-{book_index}"})
                    exposition = None
                    add_line(book, pg, number, lines[number - 1], role=role)
                elif role == "exposition":
                    exposition_index += 1
                    exposition = node(book if book is not None else part_div, "div",
                                      type="exposition", n=str(exposition_index),
                                      **{f"{{{XML}}}id": f"pg{pg}-p{index}-exposition-{exposition_index}"})
                    add_line(exposition, pg, number, lines[number - 1], role=role)
                else:
                    target = exposition if exposition is not None else book
                    if target is None:
                        raise ValueError(f"PG #{pg} line {number} precedes its first body division")
                    add_line(target, pg, number, lines[number - 1], role=role)
            if part["tail_start"] is not None:
                tail = node(part_div, "div", type="part-end-and-separator",
                            n=f"{part['tail_start']}-{part['tail_end']}")
                add_span(tail, pg, lines, int(part["tail_start"]), int(part["tail_end"]))
        back = node(source_member, "div", type="gutenberg-license-tail",
                    n=f"{member['end_marker_line']}-{member['physical_line_count']}")
        add_span(back, pg, lines, int(member["end_marker_line"]), len(lines))
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
                      "bytes": len(content), "source_members": 15}))


if __name__ == "__main__":
    main()
