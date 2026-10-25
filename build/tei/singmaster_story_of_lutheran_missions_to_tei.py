"""Reconstruct Project Gutenberg 55819 as a faithful, nonaccepted TEI candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from lxml import etree, html

from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import XML_NS, serialize, stamp_header, tei_el

LANDING_URL = "https://www.gutenberg.org/ebooks/55819"
HTML_URL = "https://www.gutenberg.org/cache/epub/55819/pg55819-images.html"
TEXT_URL = "https://www.gutenberg.org/cache/epub/55819/pg55819.txt"
RDF_URL = "https://www.gutenberg.org/ebooks/55819.rdf"
ARCHIVE_URL = "https://www.gutenberg.org/cache/epub/55819/pg55819-h.zip"
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS, "xml": XML_NS}

EXPECTED_HTML_SHA256 = "11d6827013ade4b36ed68c3f9f9d4f5d96086405013deb202651361d5a41871a"
EXPECTED_TEXT_SHA256 = "935ca7b5fb6ed9dd1a01a8e40e6627caf1617d26b8616d03e305d81f2d669add"
EXPECTED_ARCHIVE_SHA256 = "ec7e7196279f4a24c8e584d87dc8e985d47e7136bd49ba3f7245f9b2e4b36f3e"
EXPECTED_CHAPTERS = (
    "CHAPTER I. The Beginnings",
    "CHAPTER II. Pioneers and Methods",
    "CHAPTER III. The Lutheran Church in India",
    "CHAPTER IV. The Lutheran Church in Africa",
    "CHAPTER V. The Lutheran Church in China, Japan and Elsewhere",
    "CHAPTER VI. Lutheran Foreign Missions on Western Continent",
)
EXPECTED_IMAGES = (
    "images/cover.jpg",
    "images/frontis.jpg",
    "images/preface2.jpg",
    "images/preface1.jpg",
    "images/p008.jpg",
    "images/p008b.jpg",
    "images/p024.jpg",
    "images/p024b.jpg",
    "images/p032.jpg",
    "images/p032b.jpg",
    "images/p040.jpg",
    "images/p055.jpg",
    "images/p064.jpg",
    "images/p072.jpg",
    "images/p072b.jpg",
    "images/p088.jpg",
    "images/p096.jpg",
    "images/p096b.jpg",
    "images/p104.jpg",
    "images/p120.jpg",
    "images/p120b.jpg",
    "images/p128.jpg",
    "images/p128b.jpg",
    "images/p136.jpg",
    "images/p136b.jpg",
    "images/p152.jpg",
    "images/p152b.jpg",
    "images/p160.jpg",
    "images/p160b.jpg",
    "images/p192.jpg",
    "images/p192b.jpg",
    "images/p192c.jpg",
    "images/p200.jpg",
    "images/p200b.jpg",
    "images/p216.jpg",
    "images/p216b.jpg",
)
TRANSCRIBER_STATEMENTS = (
    "Missing or obscured punctuation was corrected.",
    "Typographical errors were silently corrected.",
    "Inconsistent spelling and hyphenation were made consistent when a predominant form was found in this book; otherwise it was not changed.",
)
AUTHORIAL_SCOPE_PREFIX = "This account of Lutheran missions cannot be exhaustive."
END_MARKER = "*** END OF THE PROJECT GUTENBERG EBOOK THE STORY OF LUTHERAN MISSIONS ***"


class ConversionError(ValueError):
    """Raised when the retained source does not match the released work."""


@dataclass(frozen=True)
class ParsedSource:
    path: Path
    nodes: tuple[etree._Element, ...]
    carrier_texts: tuple[str, ...]
    chapter_titles: tuple[str, ...]
    image_sources: tuple[str, ...]
    page_break_count: int
    footnote_ids: tuple[str, ...]
    end_marker: str


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    receipt_path: Path
    accounting_path: Path
    validation_path: Path
    carrier_count: int
    chapter_count: int
    figure_count: int
    page_count: int
    table_count: int
    note_count: int


@dataclass
class BuildState:
    carrier_ordinal: int = 0
    page_ordinal: int = 0
    source_texts: list[str] = field(default_factory=list)

    def register(self, element: etree._Element, source_text: str) -> None:
        normalized = _normalized_visible(source_text)
        if not normalized:
            raise ConversionError("Attempted to register an empty source carrier")
        self.carrier_ordinal += 1
        element.set(f"{{{XML_NS}}}id", f"slm-src-B{self.carrier_ordinal:04d}")
        element.set("n", str(self.carrier_ordinal))
        self.source_texts.append(normalized)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _normalized_visible(value: str) -> str:
    return " ".join(value.split())


def _classes(node: etree._Element) -> set[str]:
    return set((node.get("class") or "").split())


def _append_literal(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _target(value: str) -> str:
    return f"#slm-{value.removeprefix('#')}" if value.startswith("#") else value


def _rend(node: etree._Element) -> str | None:
    values: list[str] = []
    tag = node.tag.lower() if isinstance(node.tag, str) else ""
    if tag in {"i", "em"}:
        values.append("italic")
    if tag in {"b", "strong"}:
        values.append("bold")
    if tag == "sup":
        values.append("superscript")
    if tag == "sub":
        values.append("subscript")
    classes = _classes(node)
    for class_name, rendition in (
        ("sc", "small-caps"),
        ("small", "small"),
        ("large", "large"),
        ("xlarge", "x-large"),
    ):
        if class_name in classes:
            values.append(rendition)
    return " ".join(dict.fromkeys(values)) or None


def _append_inline(parent: etree._Element, source: etree._Element, *, skip_lists: bool = False) -> None:
    _append_literal(parent, source.text)
    for child in source:
        if not isinstance(child.tag, str):
            _append_literal(parent, child.tail)
            continue
        tag = child.tag.lower()
        classes = _classes(child)
        if skip_lists and tag in {"ul", "ol"}:
            _append_literal(parent, child.tail)
            continue
        if "hidev" in classes:
            _append_literal(parent, child.tail)
            continue
        if tag == "br":
            parent.append(tei_el("lb"))
        elif tag == "img":
            pass
        elif tag == "a" and child.get("id") and not _normalized_visible("".join(child.itertext())):
            parent.append(tei_el("anchor", {"xml:id": f"slm-{child.get('id')}"}))
        else:
            attributes: dict[str, str] = {}
            if tag == "a" and child.get("href"):
                out_tag = "ref"
                attributes["target"] = _target(child.get("href") or "")
                if re.fullmatch(r"#f\d+", child.get("href") or ""):
                    attributes["type"] = "note"
            elif "sni" in classes:
                out_tag = "seg"
                attributes["type"] = "side-heading"
            elif _rend(child):
                out_tag = "hi"
                attributes["rend"] = _rend(child) or ""
            else:
                out_tag = "seg"
            rendered = tei_el(out_tag, attributes)
            _append_inline(rendered, child, skip_lists=skip_lists)
            parent.append(rendered)
        _append_literal(parent, child.tail)


def _source_text(node: etree._Element, *, skip_lists: bool = False) -> str:
    scratch = tei_el("ab")
    _append_inline(scratch, node, skip_lists=skip_lists)
    return _normalized_visible("".join(scratch.itertext()))


def _figure_caption(node: etree._Element) -> etree._Element | None:
    captions = node.xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), ' ic002 ')]//p"
    )
    if captions:
        return captions[0]
    return None


def _is_figure(node: etree._Element) -> bool:
    return bool(node.xpath(".//img"))


def _is_page_break(node: etree._Element) -> bool:
    return node.tag.lower() == "div" and "pbb" in _classes(node)


def _is_footnote(node: etree._Element) -> bool:
    return node.tag.lower() == "div" and "footnote" in _classes(node)


def _chapter_heading(node: etree._Element) -> etree._Element | None:
    if node.tag.lower() != "div" or "chapter" not in _classes(node):
        return None
    headings = node.xpath("./h2")
    if len(headings) != 1:
        raise ConversionError("Expected each source chapter wrapper to contain one h2")
    return headings[0]


def _is_inline_leaf_div(node: etree._Element) -> bool:
    if node.tag.lower() != "div":
        return False
    return not bool(
        node.xpath(
            "./div|./p|./ul|./ol|./table|./blockquote|./h1|./h2|./h3|./h4|./hr"
        )
    )


def _carrier_texts_for_node(node: etree._Element) -> Iterator[str]:
    tag = node.tag.lower() if isinstance(node.tag, str) else ""
    if _is_page_break(node):
        return
    if _is_figure(node):
        caption = _figure_caption(node)
        if caption is not None and (value := _source_text(caption)):
            yield value
        return
    if _is_footnote(node):
        for child in node:
            if isinstance(child.tag, str):
                yield from _carrier_texts_for_node(child)
        return
    if tag in {"h1", "h2", "h3", "h4", "p", "td", "th"}:
        if value := _source_text(node):
            yield value
        return
    if tag == "li":
        if value := _source_text(node, skip_lists=True):
            yield value
        for nested in node.xpath("./ul|./ol"):
            yield from _carrier_texts_for_node(nested)
        return
    if tag in {"ul", "ol"}:
        for item in node.xpath("./li"):
            yield from _carrier_texts_for_node(item)
        return
    if tag == "table":
        for cell in node.xpath(".//th|.//td"):
            yield from _carrier_texts_for_node(cell)
        return
    if tag == "div" and "line" in _classes(node):
        if value := _source_text(node):
            yield value
        return
    if _is_inline_leaf_div(node):
        if value := _source_text(node):
            yield value
        return
    if tag in {"blockquote", "div"}:
        children = [child for child in node if isinstance(child.tag, str)]
        if not children:
            if value := _source_text(node):
                yield value
            return
        for child in children:
            yield from _carrier_texts_for_node(child)


def _verify_archive(raw_dir: Path, html_bytes: bytes) -> list[dict[str, object]]:
    archive_path = raw_dir / "pg55819-h.zip"
    if _sha256(archive_path) != EXPECTED_ARCHIVE_SHA256:
        raise ConversionError("Retained Project Gutenberg HTML archive hash changed")
    members: list[dict[str, object]] = []
    with zipfile.ZipFile(archive_path) as archive:
        names = tuple(info.filename for info in archive.infolist())
        expected_names = ("pg55819-images.html",) + EXPECTED_IMAGES
        if names != expected_names:
            raise ConversionError(f"Unexpected Project Gutenberg archive members: {names!r}")
        if archive.read("pg55819-images.html") != html_bytes:
            raise ConversionError("Downloaded HTML differs from the retained archive member")
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename.startswith("images/"):
                extracted = raw_dir / info.filename
                if not extracted.is_file() or extracted.read_bytes() != data:
                    raise ConversionError(f"Extracted illustration differs: {info.filename}")
            members.append(
                {
                    "bytes": len(data),
                    "name": info.filename,
                    "sha256": _sha256_bytes(data),
                }
            )
    return members


def parse_source(path: Path) -> ParsedSource:
    raw = path.read_bytes()
    if _sha256_bytes(raw) != EXPECTED_HTML_SHA256:
        raise ConversionError("Retained Project Gutenberg HTML authority hash changed")
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ConversionError("Project Gutenberg HTML authority is not UTF-8") from error
    if "\ufffd" in decoded:
        raise ConversionError("Project Gutenberg HTML authority contains replacement characters")
    document = html.fromstring(decoded)
    bodies = document.xpath("//body")
    if len(bodies) != 1:
        raise ConversionError("Expected exactly one HTML body")
    direct = [child for child in bodies[0] if isinstance(child.tag, str)]
    header_indexes = [i for i, node in enumerate(direct) if node.get("id") == "pg-header"]
    footer_indexes = [i for i, node in enumerate(direct) if node.get("id") == "pg-footer"]
    if len(header_indexes) != 1 or len(footer_indexes) != 1:
        raise ConversionError("Expected one Project Gutenberg header and footer")
    nodes = tuple(direct[header_indexes[0] + 1 : footer_indexes[0]])
    image_sources = tuple(
        source for node in nodes for source in node.xpath(".//img/@src")
    )
    if image_sources != EXPECTED_IMAGES:
        raise ConversionError(f"Unexpected illustration sequence: {image_sources!r}")
    chapter_titles = tuple(
        _source_text(heading)
        for node in nodes
        if (heading := _chapter_heading(node)) is not None
        and (heading.get("id") or "").startswith("ch")
    )
    if chapter_titles != EXPECTED_CHAPTERS:
        raise ConversionError(f"Unexpected chapter hierarchy: {chapter_titles!r}")
    page_break_count = sum(_is_page_break(node) for node in nodes)
    if page_break_count != 21:
        raise ConversionError(f"Expected 21 source page breaks, found {page_break_count}")
    footnote_ids = tuple(node.get("id") or "" for node in nodes if _is_footnote(node))
    if footnote_ids != tuple(f"f{number}" for number in range(1, 12)):
        raise ConversionError(f"Unexpected footnote sequence: {footnote_ids!r}")
    if sum(len(node.xpath(".//table")) + (1 if node.tag.lower() == "table" else 0) for node in nodes) != 2:
        raise ConversionError("Expected exactly two source tables")
    side_headings = sum(
        len(node.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' sni ')]"))
        for node in nodes
    )
    if side_headings != 251:
        raise ConversionError(f"Expected 251 source side headings, found {side_headings}")
    source_text = (path.parent / "pg55819.txt")
    if _sha256(source_text) != EXPECTED_TEXT_SHA256:
        raise ConversionError("Retained Project Gutenberg plain-text cross-check hash changed")
    crosscheck = source_text.read_text(encoding="utf-8-sig")
    required_crosscheck = ("THE STORY OF LUTHERAN MISSIONS", AUTHORIAL_SCOPE_PREFIX) + TRANSCRIBER_STATEMENTS
    for required in required_crosscheck:
        if _normalized_visible(required) not in _normalized_visible(crosscheck):
            raise ConversionError(f"Plain-text cross-check lacks required text: {required!r}")
    footer_text = _normalized_visible(" ".join(direct[footer_indexes[0]].itertext()))
    if END_MARKER not in footer_text:
        raise ConversionError("Expected Project Gutenberg end marker is missing")
    _verify_archive(path.parent, raw)
    carrier_texts = tuple(text for node in nodes for text in _carrier_texts_for_node(node))
    for statement in TRANSCRIBER_STATEMENTS:
        if _normalized_visible(statement) not in carrier_texts:
            raise ConversionError(f"Transcriber statement is absent: {statement!r}")
    if not any(text.startswith(AUTHORIAL_SCOPE_PREFIX) for text in carrier_texts):
        raise ConversionError("The author's non-exhaustive-scope statement is absent")
    return ParsedSource(
        path=path,
        nodes=nodes,
        carrier_texts=carrier_texts,
        chapter_titles=chapter_titles,
        image_sources=image_sources,
        page_break_count=page_break_count,
        footnote_ids=footnote_ids,
        end_marker=END_MARKER,
    )


def _new_carrier(
    tag: str,
    source: etree._Element,
    state: BuildState,
    attributes: dict[str, str] | None = None,
    *,
    skip_lists: bool = False,
) -> etree._Element:
    source_text = _source_text(source, skip_lists=skip_lists)
    element = tei_el(tag, attributes or {})
    state.register(element, source_text)
    _append_inline(element, source, skip_lists=skip_lists)
    return element


def _convert_figure(node: etree._Element, parent: etree._Element, state: BuildState) -> None:
    images = node.xpath(".//img")
    if len(images) != 1:
        raise ConversionError("Expected each source figure to contain one image")
    source = images[0].get("src") or ""
    if source not in EXPECTED_IMAGES:
        raise ConversionError(f"Unexpected illustration source: {source!r}")
    attributes = {"source": HTML_URL}
    if node.get("id"):
        attributes["xml:id"] = f"slm-{node.get('id')}"
    figure = tei_el("figure", attributes)
    figure.append(
        tei_el(
            "graphic",
            {"url": f"https://www.gutenberg.org/cache/epub/55819/{source}"},
        )
    )
    if (caption := _figure_caption(node)) is not None:
        description = _source_text(caption)
        fig_desc = tei_el("figDesc")
        state.register(fig_desc, description)
        fig_desc.text = description
        figure.append(fig_desc)
    parent.append(figure)


def _convert_list(node: etree._Element, parent: etree._Element, state: BuildState) -> None:
    result = tei_el("list", {"type": "ordered" if node.tag.lower() == "ol" else "simple"})
    for source_item in node.xpath("./li"):
        value = _source_text(source_item, skip_lists=True)
        if value:
            item = _new_carrier("item", source_item, state, skip_lists=True)
        else:
            item = tei_el("item")
        for nested in source_item.xpath("./ul|./ol"):
            _convert_list(nested, item, state)
        result.append(item)
    parent.append(result)


def _convert_table(node: etree._Element, parent: etree._Element, state: BuildState) -> None:
    table = tei_el("table", {"rend": node.get("class") or "project-gutenberg-html-table"})
    for source_row in node.xpath(".//tr"):
        row = tei_el("row")
        for source_cell in source_row.xpath("./th|./td"):
            attributes: dict[str, str] = {}
            if source_cell.tag.lower() == "th":
                attributes["role"] = "label"
            if source_cell.get("rowspan"):
                attributes["rows"] = source_cell.get("rowspan") or "1"
            if source_cell.get("colspan"):
                attributes["cols"] = source_cell.get("colspan") or "1"
            if _source_text(source_cell):
                row.append(_new_carrier("cell", source_cell, state, attributes))
            else:
                row.append(tei_el("cell", attributes))
        table.append(row)
    parent.append(table)


def _convert_footnote(node: etree._Element, parent: etree._Element, state: BuildState) -> None:
    footnote_id = node.get("id") or ""
    note = tei_el("note", {"place": "foot", "xml:id": f"slm-{footnote_id}"})
    for child in node:
        if isinstance(child.tag, str):
            _convert_block(child, note, state)
    parent.append(note)


def _convert_block(node: etree._Element, parent: etree._Element, state: BuildState) -> None:
    tag = node.tag.lower()
    classes = _classes(node)
    if _is_page_break(node):
        state.page_ordinal += 1
        parent.append(
            tei_el(
                "pb",
                {
                    "n": str(state.page_ordinal),
                    "type": "source-electronic-break",
                    "facs": HTML_URL,
                },
            )
        )
        return
    if _is_figure(node):
        _convert_figure(node, parent, state)
        return
    if _is_footnote(node):
        _convert_footnote(node, parent, state)
        return
    if tag in {"h1", "h2", "h3", "h4"}:
        output_tag = "ab" if parent.xpath("./tei:head", namespaces=NS) else "head"
        parent.append(_new_carrier(output_tag, node, state, {"type": "source-heading", "rend": tag}))
        return
    if tag == "p":
        if not _source_text(node):
            return
        attributes = {"rend": " ".join(sorted(classes))} if classes else {}
        if _source_text(node).startswith(AUTHORIAL_SCOPE_PREFIX):
            attributes["rend"] = " ".join(
                value for value in (attributes.get("rend"), "authorial-scope") if value
            )
        parent.append(_new_carrier("p", node, state, attributes))
        return
    if tag in {"ul", "ol"}:
        _convert_list(node, parent, state)
        return
    if tag == "table":
        _convert_table(node, parent, state)
        return
    if tag == "blockquote":
        quote = tei_el("quote")
        for child in node:
            if isinstance(child.tag, str):
                _convert_block(child, quote, state)
        parent.append(quote)
        return
    if tag == "hr":
        parent.append(tei_el("milestone", {"unit": "typographic-rule", "rend": node.get("class") or ""}))
        return
    if tag == "div" and "line" in classes:
        if _source_text(node):
            parent.append(_new_carrier("l", node, state, {"rend": " ".join(sorted(classes))}))
        return
    if _is_inline_leaf_div(node):
        if _source_text(node):
            attributes = {"rend": " ".join(sorted(classes))} if classes else None
            parent.append(_new_carrier("ab", node, state, attributes))
        return
    if tag == "div" and ("linegroup" in classes or "group" in classes):
        group = tei_el("lg", {"type": "linegroup" if "linegroup" in classes else "group"})
        for child in node:
            if isinstance(child.tag, str):
                _convert_block(child, group, state)
        parent.append(group)
        return
    if tag == "div":
        children = [child for child in node if isinstance(child.tag, str)]
        if not children:
            if _source_text(node):
                attributes = {"rend": " ".join(sorted(classes))} if classes else None
                parent.append(_new_carrier("ab", node, state, attributes))
            return
        for child in children:
            _convert_block(child, parent, state)
        return
    raise ConversionError(f"Unsupported retained HTML block: <{tag}>")


def _header(source_sha256: str) -> etree._Element:
    header = stamp_header(
        title="The Story of Lutheran Missions",
        author="Elsie Singmaster",
        contributors=[
            {
                "name": "Co-operative Literature Committee, Woman's Missionary Societies of the Lutheran Church",
                "role": "publisher and issuing body",
            },
            {
                "name": "David Edwards, Barry Abrahamsen, and the Online Distributed Proofreading Team",
                "role": "Project Gutenberg production and proofreading",
            },
        ],
        source_url=HTML_URL,
        source_sha256=source_sha256,
        print_source=(
            "Columbia, South Carolina: Co-operative Literature Committee, Woman's "
            "Missionary Societies of the Lutheran Church / Survey Publishing Co., 1917."
        ),
        rights_statement=(
            "Project Gutenberg states that this work is public domain in the USA. "
            "Rights outside the USA and Project Gutenberg trademark or redistribution "
            "conditions require separate review. This nonaccepted candidate is not "
            "publication clearance."
        ),
    )
    encoding = tei_el("encodingDesc")
    project = tei_el("projectDesc")
    project.append(
        tei_el(
            "p",
            text=(
                "The retained proofread Project Gutenberg HTML is the text and structure "
                "authority. Title and responsibility matter, contents, six chapters and "
                "their outlines, side headings, linked notes, unnumbered electronic page "
                "breaks, illustrations and captions, lists, tables, typography, and final "
                "matter are represented without modernizing wording. The author's statement "
                "that the survey cannot be exhaustive is encoded as authorial scope, not as "
                "evidence of missing source text."
            ),
        )
    )
    encoding.append(project)
    header.append(encoding)
    profile = tei_el("profileDesc")
    language_usage = tei_el("langUsage")
    language_usage.append(tei_el("language", {"ident": "en"}, "English"))
    profile.append(language_usage)
    header.append(profile)
    return header


def _new_div(parent: etree._Element, div_type: str, source_id: str) -> etree._Element:
    result = tei_el("div", {"type": div_type, "xml:id": f"slm-{source_id}"})
    parent.append(result)
    return result


def build_tree(parsed: ParsedSource) -> tuple[etree._ElementTree, dict[str, object]]:
    root = tei_el("TEI", {"xml:lang": "en"})
    root.append(_header(_sha256(parsed.path)))
    text = tei_el("text")
    front = tei_el("front")
    body = tei_el("body")
    back = tei_el("back")
    text.extend((front, body, back))
    root.append(text)
    state = BuildState()
    current = _new_div(front, "title-matter", "title-matter")
    chapter_count = 0
    transcriber_seen = False

    for node in parsed.nodes:
        list_label = _source_text(node, skip_lists=True)
        if node.tag.lower() == "ul" and list_label.startswith("Transcriber") and "Notes" in list_label:
            current = _new_div(back, "transcribers-note", "transcribers-note")
            _convert_block(node, current, state)
            transcriber_seen = True
            continue
        heading = _chapter_heading(node)
        if heading is not None:
            heading_text = _source_text(heading)
            source_id = heading.get("id")
            if source_id == "foreword":
                current = _new_div(front, "foreword", source_id)
            elif heading_text == "CONTENTS":
                current = _new_div(front, "contents", "contents")
            elif source_id == "illus":
                current = _new_div(front, "illustrations", source_id)
            elif heading_text == "PREFACE":
                current = _new_div(front, "preface", "preface")
            elif source_id and source_id.startswith("ch"):
                current = _new_div(body, "chapter", source_id)
                chapter_count += 1
            _convert_block(node, current, state)
            continue
        if transcriber_seen and not _normalized_visible("".join(node.itertext())):
            continue
        _convert_block(node, current, state)

    if not transcriber_seen:
        raise ConversionError("The Project Gutenberg transcriber notes were not divided into back matter")
    wrapper = _new_div(back, "source-wrapper", "pg-end-wrapper")
    wrapper.append(tei_el("p", {"rend": "project-gutenberg-end-marker"}, parsed.end_marker))
    if tuple(state.source_texts) != parsed.carrier_texts:
        raise ConversionError("Source carrier traversal drifted from the parsed source model")
    tree = etree.ElementTree(root)
    stats: dict[str, object] = {
        "carrier_count": state.carrier_ordinal,
        "chapter_count": chapter_count,
        "figure_count": len(tree.xpath("//tei:figure", namespaces=NS)),
        "page_count": len(tree.xpath("//tei:pb", namespaces=NS)),
        "table_count": len(tree.xpath("//tei:table", namespaces=NS)),
        "note_count": len(tree.xpath("//tei:note[@place='foot']", namespaces=NS)),
    }
    return tree, stats


def _candidate_carriers(tree: etree._ElementTree) -> list[tuple[int, str]]:
    carriers = tree.xpath(
        "//*[@xml:id and starts-with(@xml:id, 'slm-src-B')]",
        namespaces=NS,
    )
    def carrier_text(carrier: etree._Element) -> str:
        values: list[str] = []

        def walk(node: etree._Element) -> None:
            if node.text:
                values.append(node.text)
            for child in node:
                if not (
                    carrier.tag == f"{{{TEI_NS}}}item"
                    and child.tag == f"{{{TEI_NS}}}list"
                ):
                    walk(child)
                if child.tail:
                    values.append(child.tail)

        walk(carrier)
        return _normalized_visible("".join(values))

    return sorted((int(carrier.get("n")), carrier_text(carrier)) for carrier in carriers)


def accounting_errors(parsed: ParsedSource, tree: etree._ElementTree) -> list[str]:
    expected = list(enumerate(parsed.carrier_texts, start=1))
    actual = _candidate_carriers(tree)
    if expected == actual:
        return []
    errors: list[str] = []
    if len(expected) != len(actual):
        errors.append(f"source carrier count: expected {len(expected)}, found {len(actual)}")
    for index, (left, right) in enumerate(zip(expected, actual), start=1):
        if left != right:
            errors.append(
                f"first source carrier mismatch at ordinal {index}: expected {left!r}, found {right!r}"
            )
            break
    return errors


def _source_members(raw_dir: Path) -> list[dict[str, object]]:
    roles = {
        "gutenberg-55819-landing.html": ("project-gutenberg-landing", LANDING_URL),
        "pg55819-images.html": ("html-text-and-structure-authority", HTML_URL),
        "pg55819.txt": ("plain-text-crosscheck", TEXT_URL),
        "pg55819.rdf": ("project-gutenberg-metadata", RDF_URL),
        "pg55819-h.zip": ("project-gutenberg-html-and-illustration-archive", ARCHIVE_URL),
    }
    members: list[dict[str, object]] = []
    for path in sorted(
        (item for item in raw_dir.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(raw_dir).as_posix(),
    ):
        relative = path.relative_to(raw_dir).as_posix()
        if relative.startswith("images/"):
            role = "project-gutenberg-illustration-member"
            url = f"https://www.gutenberg.org/cache/epub/55819/{relative}"
        else:
            role, url = roles.get(
                relative,
                ("http-evidence" if "headers" in relative else "acquisition-evidence", None),
            )
        members.append(
            {
                "bytes": path.stat().st_size,
                "name": relative,
                "role": role,
                "sha256": _sha256(path),
                "url": url,
            }
        )
    return members


def _receipt(parsed: ParsedSource) -> dict[str, object]:
    raw_dir = parsed.path.parent
    return {
        "archive_members": _verify_archive(raw_dir, parsed.path.read_bytes()),
        "completeness_checks": {
            "opening": "Cover, frontispiece, title, author, publisher, copyright, imprint, and foreword responsibility matter are represented.",
            "front": "Printed contents, complete illustration list, preface, and both preface plates are represented.",
            "middle": "All six chapters, source outlines, 251 side headings, 11 linked footnotes, 36 illustrations, 35 captions, lists, verse line groups, and two tables are represented.",
            "ending": "Chapter VI conclusion, the three transcriber statements, and the exact Project Gutenberg end marker are represented.",
            "unusual_features": "Small caps, italic, bold, superscript, display sizes, nested outlines, internal references, and source-encoded unnumbered page breaks are explicit.",
        },
        "credits": "Produced by David Edwards, Barry Abrahamsen, and the Online Distributed Proofreading Team from Internet Archive images.",
        "download_urls": [LANDING_URL, HTML_URL, TEXT_URL, RDF_URL, ARCHIVE_URL],
        "edition": "Columbia, South Carolina: Co-operative Literature Committee, Woman's Missionary Societies of the Lutheran Church / Survey Publishing Co., 1917",
        "electronic_source_limitations": {
            "page_breaks": "The retained HTML exposes 21 unnumbered electronic page-break rules. They are preserved in order with reconstruction ordinals, not asserted as printed page numbers.",
            "print_images": "Project Gutenberg credits Internet Archive page images, but the proofread HTML/text is the released text authority; no vendor scan is redistributed by this packet.",
        },
        "identity": "provisional net-new candidate; no canonical WorkCatalog write",
        "landing_metadata": {
            "ebook_number": 55819,
            "release_date": "2017-10-26",
            "most_recent_update": "2024-10-23",
            "title": "The Story of Lutheran Missions",
        },
        "landing_url": LANDING_URL,
        "omissions_from_tei": [
            "Project Gutenberg header/footer license boilerplate remains in retained raw evidence; only the exact end marker is represented as source-wrapper evidence."
        ],
        "retrieved_at_utc": (raw_dir / "retrieved_at_utc.txt").read_text(encoding="utf-8").strip(),
        "rights_and_attribution": {
            "attribution": "Retain Project Gutenberg 55819, its production credits, and the 1917 publisher/imprint responsibility.",
            "status": "Project Gutenberg states public domain in the USA.",
            "unresolved": "Rights outside the USA and Project Gutenberg trademark or redistribution terms require separate review before publication.",
        },
        "scope_statement": {
            "classification": "authorial historical scope, not textual incompleteness",
            "source_text": "This account of Lutheran missions cannot be exhaustive.",
        },
        "source_members": _source_members(raw_dir),
        "source_responsibility": {
            "author": "Elsie Singmaster (Mrs. Elsie Singmaster Lewars)",
            "publisher": "Co-operative Literature Committee, Woman's Missionary Societies of the Lutheran Church",
            "printer": "Survey Publishing Co., Columbia, S. C.",
        },
        "source_title": "The Story of Lutheran Missions",
        "transcriber_repairs": {
            "statements": list(TRANSCRIBER_STATEMENTS),
            "policy": "Retain the surfaced Project Gutenberg readings and all three statements; introduce no further silent correction.",
        },
        "transformations": [
            "Parsed the retained UTF-8 Project Gutenberg HTML between its boilerplate header and footer.",
            "Mapped source divisions, paragraphs, side headings, outlines, line groups, notes and links, tables, figures, captions, typography, and page-break rules to TEI without modernizing wording.",
            "Encoded the author's non-exhaustive-history statement as authorial scope rather than a source-completeness defect.",
            "Verified the downloaded HTML and all 36 extracted illustrations byte-for-byte against the retained Gutenberg archive.",
        ],
        "unresolved_questions": [
            "Project Gutenberg's individual silent typographical corrections are not enumerated.",
            "Human identity, edition, rights, textual, and editorial acceptance remain outside this candidate packet.",
        ],
    }


def _digest(values: Iterable[str]) -> str:
    return _sha256_bytes("\n".join(values).encode("utf-8"))


def convert(source_path: Path, output_path: Path, report_dir: Path) -> ConversionResult:
    parsed = parse_source(source_path)
    tree, stats = build_tree(parsed)
    errors = accounting_errors(parsed, tree)
    if errors:
        raise ConversionError("; ".join(errors))
    serialize(tree, output_path)
    xsd_errors = validate_file(output_path)
    if xsd_errors:
        raise ConversionError("TEI P5 XSD validation failed: " + "; ".join(xsd_errors[:5]))
    carriers = _candidate_carriers(tree)
    source_ids = [f"slm-src-B{ordinal:04d}" for ordinal in range(1, len(parsed.carrier_texts) + 1)]
    candidate_ids = tree.xpath(
        "//*[@xml:id and starts-with(@xml:id, 'slm-src-B')]/@xml:id",
        namespaces=NS,
    )
    table_rows = len(tree.xpath("//tei:table/tei:row", namespaces=NS))
    table_cells = len(tree.xpath("//tei:table/tei:row/tei:cell", namespaces=NS))
    reference_targets = tree.xpath("//tei:ref[starts-with(@target, '#')]/@target", namespaces=NS)
    available_ids = set(tree.xpath("//@xml:id", namespaces=NS))
    dangling = [target for target in reference_targets if target.removeprefix("#") not in available_ids]
    footnote_targets = {f"#slm-f{number}" for number in range(1, 12)}
    emphasis_counts = {
        token: len(
            tree.xpath(
                "//tei:hi[contains(concat(' ', normalize-space(@rend), ' '), $needle)]",
                namespaces=NS,
                needle=f" {token} ",
            )
        )
        for token in ("bold", "italic", "small-caps", "superscript", "subscript", "small", "large", "x-large")
    }
    accounting = {
        "authorial_scope_count": len(
            tree.xpath(
                "//tei:p[contains(concat(' ', normalize-space(@rend), ' '), ' authorial-scope ')]",
                namespaces=NS,
            )
        ),
        "candidate_carrier_count": len(carriers),
        "candidate_carrier_stream_sha256": _digest(text for _ordinal, text in carriers),
        "chapter_count": stats["chapter_count"],
        "chapter_titles": list(parsed.chapter_titles),
        "dangling_internal_references": dangling,
        "duplicated_source_carrier_ids": sorted({value for value in candidate_ids if candidate_ids.count(value) > 1}),
        "emphasis_counts": emphasis_counts,
        "figure_caption_count": len(tree.xpath("//tei:figure/tei:figDesc", namespaces=NS)),
        "figure_count": stats["figure_count"],
        "footnote_count": stats["note_count"],
        "footnote_reference_count": sum(target in footnote_targets for target in reference_targets),
        "front_division_count": len(tree.xpath("/tei:TEI/tei:text/tei:front/tei:div", namespaces=NS)),
        "illustration_members": list(parsed.image_sources),
        "list_item_count": len(tree.xpath("//tei:list/tei:item", namespaces=NS)),
        "line_count": len(tree.xpath("//tei:l", namespaces=NS)),
        "omitted_source_carrier_ids": sorted(set(source_ids) - set(candidate_ids)),
        "page_break_count": stats["page_count"],
        "page_break_interpretation": "source-encoded unnumbered electronic breaks; n is reconstruction ordinal, not printed page number",
        "page_break_sequence": tree.xpath("//tei:pb/@n", namespaces=NS),
        "side_heading_count": len(tree.xpath("//tei:seg[@type='side-heading']", namespaces=NS)),
        "source_carrier_count": len(parsed.carrier_texts),
        "source_carrier_stream_sha256": _digest(parsed.carrier_texts),
        "source_sha256": _sha256(source_path),
        "table_cell_count": table_cells,
        "table_count": stats["table_count"],
        "table_row_count": table_rows,
        "transcriber_statement_count": sum(
            1
            for statement in TRANSCRIBER_STATEMENTS
            if _normalized_visible(statement) in [text for _ordinal, text in carriers]
        ),
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = report_dir / "receipt.json"
    accounting_path = report_dir / "accounting.json"
    validation_path = report_dir / "validation.json"
    _write_json(receipt_path, _receipt(parsed))
    _write_json(accounting_path, accounting)
    _write_json(
        validation_path,
        {
            "accounting_errors": errors,
            "candidate_sha256": _sha256(output_path),
            "status": "technically_valid_nonaccepted_candidate",
            "tei_p5_xsd_errors": xsd_errors,
            "tei_p5_xsd_valid": not xsd_errors,
        },
    )
    return ConversionResult(
        output_path=output_path,
        receipt_path=receipt_path,
        accounting_path=accounting_path,
        validation_path=validation_path,
        carrier_count=int(stats["carrier_count"]),
        chapter_count=int(stats["chapter_count"]),
        figure_count=int(stats["figure_count"]),
        page_count=int(stats["page_count"]),
        table_count=int(stats["table_count"]),
        note_count=int(stats["note_count"]),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = convert(args.source, args.output, args.report_dir)
    print(
        f"Wrote {result.output_path} with {result.carrier_count} carriers, "
        f"{result.chapter_count} chapters, {result.figure_count} figures, "
        f"{result.note_count} notes, and {result.page_count} source page breaks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
