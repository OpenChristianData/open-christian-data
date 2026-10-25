"""Source-bound TEI candidate route for Project Gutenberg eBook 3296."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-augustines-confessions-pg3296-to-tei"
CONVERTER_VERSION = "2"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SOURCE_BYTES = 632167
_SOURCE_SHA256 = "5a036498dc7c546a98b9e7a31952e030ca74db7dd111b30029354efe12bcd691"
_BOOK = re.compile(r"^BOOK ([IVX]+)\s*$")
_CENTERED_TERMINAL_LAYOUT = {
    "source_line": 9367,
    "source_text": "GRATIAS TIBI DOMINE",
    "leading_spaces": 25,
    "tei_rend": "align-center",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _records(source: bytes, terminal_layout: Mapping[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    raw_lines = source.splitlines(keepends=True)
    if not raw_lines:
        raise ValueError("Confessions source is empty")
    texts: list[str] = []
    starts: list[int] = []
    offset = 0
    for raw in raw_lines:
        starts.append(offset)
        offset += len(raw)
        content = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1] if raw.endswith((b"\n", b"\r")) else raw
        texts.append(content.decode("utf-8", errors="strict"))
    start_markers = [i for i, line in enumerate(texts) if line.startswith("*** START OF THE PROJECT GUTENBERG EBOOK ")]
    end_markers = [i for i, line in enumerate(texts) if line.startswith("*** END OF THE PROJECT GUTENBERG EBOOK ")]
    if len(start_markers) != 1 or len(end_markers) != 1 or start_markers[0] >= end_markers[0]:
        raise ValueError("Confessions source wrapper markers are missing or ambiguous")
    first, last = start_markers[0], end_markers[0]
    sections: list[dict[str, object]] = []
    line_data: list[dict[str, object]] = []
    books: list[str] = []
    current_book: str | None = None
    paragraph_lines: list[int] = []
    paragraph_kind: str | None = None

    def flush() -> None:
        nonlocal paragraph_lines, paragraph_kind
        if not paragraph_lines:
            return
        if paragraph_kind == "provider-header":
            prefix = "provider"
        elif paragraph_kind == "title-page":
            prefix = "title"
        elif paragraph_kind == "license":
            prefix = "license"
        else:
            prefix = f"book-{current_book}"
        number = 1 + sum(item["kind"] == "paragraph" and item["section"] == prefix for item in sections)
        identifier = f"confessions-{prefix}-p-{number:04d}"
        text = " ".join(texts[i].strip() for i in paragraph_lines).strip()
        section = {"kind": "paragraph", "section": prefix, "book": current_book if prefix.startswith("book-") else None, "id": identifier, "text": text, "lines": paragraph_lines.copy()}
        if len(paragraph_lines) == 1 and paragraph_lines[0] + 1 == int(terminal_layout["source_line"]):
            source_line = texts[paragraph_lines[0]]
            expected_source_line = " " * int(terminal_layout["leading_spaces"]) + str(terminal_layout["source_text"])
            if current_book != "XIII" or source_line != expected_source_line:
                raise ValueError("Confessions centered terminal doxology source line drifted")
            section["rend"] = str(terminal_layout["tei_rend"])
        sections.append(section)
        for i in paragraph_lines:
            line_data[i]["tei_id"] = identifier
        paragraph_lines = []
        paragraph_kind = None

    def add_marker(index: int, kind: str, identifier: str) -> None:
        sections.append({"kind": kind, "section": kind, "book": current_book, "id": identifier, "text": texts[index], "lines": [index]})
        line_data[index]["tei_id"] = identifier

    for i, text in enumerate(texts):
        raw = raw_lines[i]
        body = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1] if raw.endswith((b"\n", b"\r")) else raw
        terminator = "CRLF" if raw.endswith(b"\r\n") else "LF" if raw.endswith(b"\n") else "CR" if raw.endswith(b"\r") else "none"
        if not text.strip():
            kind = "blank-layout"
        elif i < first:
            kind = "provider-header"
        elif i == first:
            kind = "start-marker"
        elif i == last:
            kind = "end-marker"
        elif i > last:
            kind = "license"
        else:
            match = _BOOK.fullmatch(text.strip())
            if match:
                kind = "book-heading"
                current_book = match.group(1)
                if current_book in books:
                    raise ValueError(f"duplicate Confessions book heading: {current_book}")
                books.append(current_book)
            elif current_book is None:
                kind = "title-page"
            else:
                kind = "book-text"
        line_data.append({"line": i + 1, "byte_start": starts[i], "byte_end": starts[i] + len(body), "terminator": terminator, "record_sha256": _sha(body), "kind": kind, "tei_id": None})

        if kind == "blank-layout":
            flush()
        elif kind == "book-heading":
            flush()
            add_marker(i, "book-heading", f"confessions-book-{current_book}-head")
        elif kind in {"start-marker", "end-marker"}:
            flush()
            add_marker(i, kind, f"confessions-{kind}")
        else:
            if paragraph_kind != kind:
                flush()
                paragraph_kind = kind
            paragraph_lines.append(i)
    flush()
    expected = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII"]
    if books != expected or len(raw_lines) != 9724 or offset != len(source):
        raise ValueError("Confessions line or 13-book source census drifted")
    centered = [item for item in sections if item.get("rend") == terminal_layout["tei_rend"]]
    if len(centered) != 1 or centered[0]["lines"] != [int(terminal_layout["source_line"]) - 1]:
        raise ValueError("Confessions centered terminal doxology was not mapped exactly once")
    centered_index = sections.index(centered[0])
    if centered_index + 1 >= len(sections) or sections[centered_index + 1]["kind"] != "end-marker":
        raise ValueError("Confessions centered terminal doxology is not the final Book XIII text")
    return line_data, sections, books


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    if source_manifest.record.get("source_id") != "augustine-confessions-project-gutenberg-pg3296" or source_manifest.record.get("work_id") != "augustines-confessions":
        raise ValueError("Confessions manifest identity mismatch")
    source = source_manifest.authority_path("retained-text").read_bytes()
    if len(source) != _SOURCE_BYTES or _sha(source) != _SOURCE_SHA256:
        raise ValueError("Confessions retained source bytes drifted")
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    mapping = profile.get("mapping")
    terminal_layout = mapping.get("centered_terminal_doxology") if isinstance(mapping, Mapping) else None
    if not isinstance(terminal_layout, Mapping) or {
        key: terminal_layout.get(key) for key in _CENTERED_TERMINAL_LAYOUT
    } != _CENTERED_TERMINAL_LAYOUT:
        raise ValueError("Confessions centered terminal layout profile drifted")
    line_data, sections, books = _records(source, terminal_layout)
    line_inventory = [{**item, "line": int(item["line"])} for item in line_data]
    accountability = {"contract": "ocd-augustines-confessions-source-accountability-v1", "work_id": "augustines-confessions", "source_id": source_manifest.record["source_id"], "source_bytes": len(source), "source_sha256": _sha(source), "physical_line_count": len(line_data), "line_inventory_sha256": _sha(_canonical(line_inventory)), "line_inventory": line_inventory, "book_order": books, "paragraph_count": sum(item["kind"] == "paragraph" for item in sections), "omitted_count": 0, "duplicate_count": 0}

    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, "augustines-confessions-pg3296-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = "The Confessions of St. Augustine"
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = "Saint of Hippo Augustine"
    resp = etree.SubElement(title_stmt, f"{{{_TEI}}}respStmt")
    etree.SubElement(resp, f"{{{_TEI}}}resp").text = "Translator named in retained source"
    etree.SubElement(resp, f"{{{_TEI}}}name").text = "E. B. Pusey"
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    etree.SubElement(etree.SubElement(publication, f"{{{_TEI}}}availability", status="unknown"), f"{{{_TEI}}}p").text = str(profile["source_observations"]["rights_status"])
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = "The Confessions of St. Augustine"
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="project-gutenberg-ebook").text = "3296"
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="sha256").text = _SOURCE_SHA256
    etree.SubElement(bibl, f"{{{_TEI}}}note").text = "Release and update dates are provider metadata; no print imprint or composition date is asserted by this reconstruction."
    etree.SubElement(header, f"{{{_TEI}}}encodingDesc").append(etree.Element(f"{{{_TEI}}}p"))
    header.find(f"{{{_TEI}}}encodingDesc/{{{_TEI}}}p").text = "Blank-line-delimited source paragraphs are preserved in order; the source-centered Book XIII terminal doxology is encoded as rend='align-center'. Remaining whitespace normalization and physical line records are documented in source-accountability.json."
    etree.SubElement(etree.SubElement(header, f"{{{_TEI}}}revisionDesc", status="candidate"), f"{{{_TEI}}}change", when="2026-09-17").text = "Generated as a nonaccepted source-bound technical candidate."
    text_node = etree.SubElement(root, f"{{{_TEI}}}text")
    front = etree.SubElement(text_node, f"{{{_TEI}}}front")
    provider = etree.SubElement(front, f"{{{_TEI}}}div", type="source-envelope", subtype="provider-header")
    start = etree.SubElement(front, f"{{{_TEI}}}div", type="source-boundary", subtype="start-marker")
    title_page = etree.SubElement(front, f"{{{_TEI}}}div", type="titlepage")
    body = etree.SubElement(text_node, f"{{{_TEI}}}body")
    book_nodes: dict[str, etree._Element] = {}
    end = etree.SubElement(etree.SubElement(text_node, f"{{{_TEI}}}back"), f"{{{_TEI}}}div", type="source-boundary", subtype="end-marker")
    license_div = etree.SubElement(text_node.find(f"{{{_TEI}}}back"), f"{{{_TEI}}}div", type="source-evidence", subtype="project-gutenberg-license")
    section_nodes = {"provider": provider, "title": title_page, "start-marker": start, "end-marker": end, "license": license_div}
    for roman in books:
        div = etree.SubElement(body, f"{{{_TEI}}}div", type="book", n=roman)
        div.set(_XML_ID, f"confessions-book-{roman}")
        book_nodes[roman] = div
    for item in sections:
        kind = str(item["kind"])
        identifier = str(item["id"])
        if kind == "book-heading":
            node = etree.SubElement(book_nodes[str(item["book"])], f"{{{_TEI}}}head")
            node.set(_XML_ID, identifier)
            node.text = str(item["text"]).strip()
        elif kind == "paragraph":
            section = str(item["section"])
            parent = book_nodes[str(item["book"])] if section.startswith("book-") else section_nodes[section]
            node = etree.SubElement(parent, f"{{{_TEI}}}p")
            node.set(_XML_ID, identifier)
            if item.get("rend"):
                node.set("rend", str(item["rend"]))
            node.text = str(item["text"])
        else:
            parent = section_nodes[kind]
            node = etree.SubElement(parent, f"{{{_TEI}}}p")
            node.set(_XML_ID, identifier)
            node.text = str(item["text"])

    unresolved = [
        {"id": "augustines-confessions-edition-history", "status": "unresolved", "kind": "identity", "detail": "The retained electronic source does not establish a print imprint, edition statement, composition date, or first-publication date."},
        {"id": "augustines-confessions-rights-review", "status": "unresolved", "kind": "rights", "detail": "Project Gutenberg's qualified notice and full license are transcribed as source evidence; human rights and distribution review remains outstanding."},
        {"id": "augustines-confessions-human-acceptance", "status": "unresolved", "kind": "acceptance", "detail": "This candidate has not received human textual acceptance, release selection, or publication authorization."}
    ]
    authorities = {str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")} for item in source_manifest.record["authorities"]}
    provenance = {"contract": "ocd-augustines-confessions-candidate-provenance-v1", "status": "nonaccepted", "work_id": "augustines-confessions", "ticket_id": "LIB-077", "source_id": source_manifest.record["source_id"], "source_manifest_sha256": source_manifest.sha256, "rights_observation": profile["source_observations"]["rights_status"], "authorities": authorities, "acceptance_status": "not-accepted", "release_status": "not-selected", "publication_status": "not-authorized", "canonical_data_or_ir_written": False}
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False), "source-accountability.json": _canonical(accountability), "provenance.json": _canonical(provenance), "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved), "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
