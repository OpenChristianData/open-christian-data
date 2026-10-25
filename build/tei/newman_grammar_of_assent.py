"""Convert retained Project Gutenberg 34022 HTML to a TEI P5 candidate.

This source-local route is bound to the authorized 1874 witness and its
observed HTML structure. Project Gutenberg's redistribution wrapper is not
part of the historical book and is excluded; the title matter, contents,
dedication, complete part/chapter/section hierarchy, terminal note, footnotes,
page milestones, quotations, language spans, and typography are retained.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Mapping
from zipfile import BadZipFile, ZipFile

if __package__ in {None, ""}:  # pragma: no cover - exercised by CLI tests
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree, html

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
NS = {"t": TEI_NS}

PACKAGE_LOGICAL_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-1/07/"
    "newman-grammar-of-assent/pg34022-h.zip"
)
SOURCE_LOGICAL_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-1/07/"
    "newman-grammar-of-assent/extracted/pg34022-h/pg34022-images.html"
)
SOURCE_ARCHIVE_SHA256 = (
    "27f6e1c54a0b5ac43b15b1ac26dabeff05a78aa27e2e2989f1633093200cedec"
)
SOURCE_HTML_MEMBER = "pg34022-images.html"
SOURCE_HTML_SHA256 = (
    "798d867ac82ef0df1f2496cceaf06aea6fef8160f1c947dc95e4f7b2ae6def08"
)
SOURCE_HTML_URL = "https://www.gutenberg.org/cache/epub/34022/pg34022-images.html"
SOURCE_COVER_MEMBER = "images/cover.jpg"
SOURCE_COVER_SHA256 = (
    "1e4c52a14131a78573156916ec5ba3954d52db27025f0acdaa23420ba05d8162"
)

EXPECTED_PAGE_COUNT = 491
EXPECTED_NOTE_REF_COUNT = 56
EXPECTED_NOTE_COUNT = 56
EXPECTED_PART_COUNT = 2
EXPECTED_CHAPTER_COUNT = 10
EXPECTED_SECTION_COUNT = 20
EXPECTED_CONTENTS_ITEM_COUNT = 35
EXPECTED_SOURCE_PARAGRAPH_COUNT = 794
EXPECTED_EMPHASIS_COUNT = 94
EXPECTED_STYLE_ITALIC_COUNT = 312
EXPECTED_SMALLCAPS_COUNT = 4
EXPECTED_SUPERSCRIPT_COUNT = 56
EXPECTED_FOREIGN_COUNT = 135
EXPECTED_LATIN_COUNT = 102
EXPECTED_GREEK_COUNT = 6
EXPECTED_UNMARKED_FOREIGN_COUNT = 27
EXPECTED_INLINE_QUOTE_COUNT = 829
EXPECTED_BLOCK_QUOTE_COUNT = 7
EXPECTED_LINE_GROUP_COUNT = 5
EXPECTED_LINE_COUNT = 13
EXPECTED_TYPOGRAPHIC_BREAK_COUNT = 13

TEI_RNG_PATH = (
    Path(__file__).resolve().parents[2]
    / "ocd_kernel"
    / "tei"
    / "vendor"
    / "relaxng"
    / "tei_all.rng"
)


class ConversionError(ValueError):
    """Raised when the retained source or candidate violates this route."""


@dataclass(frozen=True)
class ConversionResult:
    """Output path and deterministic accounting for one conversion."""

    output_path: Path
    accounting: dict[str, object]


@dataclass
class _Context:
    source_to_tei_ids: dict[str, str]
    seen_ids: set[str]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _qname(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _el(
    name: str,
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
    *,
    nsmap: Mapping[str | None, str] | None = None,
) -> etree._Element:
    node = etree.Element(_qname(name), nsmap=nsmap)
    for key, value in (attrs or {}).items():
        if key == "xml:id":
            node.set(XML_ID, value)
        elif key == "xml:lang":
            node.set(XML_LANG, value)
        else:
            node.set(key, value)
    node.text = text
    return node


def _has_class(node: etree._Element, value: str) -> bool:
    return value in (node.get("class", "") or "").split()


def _normalized_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "")


def _node_text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _append_text(parent: etree._Element, value: str | None) -> None:
    text = _normalized_text(value)
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _safe_id(prefix: str, source_id: str) -> str:
    return prefix + re.sub(r"[^A-Za-z0-9_.-]+", "-", source_id)


def _source_fragment(node: etree._Element) -> str | None:
    source_id = node.get("id")
    if source_id:
        return source_id
    anchors = node.xpath("./a[@id]")
    if anchors:
        return anchors[0].get("id")
    return None


def _div_type(heading: str) -> str:
    folded = heading.casefold()
    if folded.startswith("part "):
        return "part"
    if folded.startswith("chapter "):
        return "chapter"
    if heading.startswith(("§", "�")):
        return "section"
    if folded.startswith("dedication"):
        return "dedication"
    if folded == "note.":
        return "terminal-note"
    if folded == "footnotes":
        return "footnotes"
    return "section"


def _style_rend(node: etree._Element) -> str | None:
    style = node.get("style", "") or ""
    values: list[str] = []
    if "font-style: italic" in style or node.tag == "em":
        values.append("italic")
    if "font-variant: small-caps" in style:
        values.append("smallcaps")
    if "font-weight: bold" in style or node.tag == "strong":
        values.append("bold")
    if "vertical-align: super" in style:
        values.append("superscript")
    if "text-align: center" in style:
        values.append("center")
    font_size = re.search(r"font-size:\s*([0-9]+)%", style)
    if font_size:
        size = int(font_size.group(1))
        if size < 100:
            values.append("smaller")
        elif size > 100:
            values.append("larger")
    return " ".join(dict.fromkeys(values)) or None


def _register_source_ids(book_roots: list[etree._Element]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for root in book_roots:
        for node in root.xpath(".//*[@id]"):
            source_id = node.get("id")
            if not source_id:
                continue
            if source_id.startswith("page") and _has_class(node, "tei-pb"):
                target = _safe_id("pb-", source_id)
            elif source_id.startswith("Pg") and _has_class(node, "tei-anchor"):
                page_source_id = "page" + source_id[2:]
                target = _safe_id("pb-", page_source_id)
            elif source_id.startswith("noteref_"):
                target = _safe_id("ref-", source_id.removeprefix("noteref_"))
            elif source_id.startswith("note_"):
                target = _safe_id("note-", source_id.removeprefix("note_"))
            elif source_id.startswith(("toc", "pdf")):
                parent = node.getparent()
                while parent is not None and not _has_class(parent, "tei-div"):
                    parent = parent.getparent()
                fragment = _source_fragment(parent) if parent is not None else source_id
                target = _safe_id("div-", fragment or source_id)
            else:
                target = _safe_id("src-", source_id)
            mapping[source_id] = target
    return mapping


def _claim_id(context: _Context, candidate: str) -> str:
    if candidate in context.seen_ids:
        raise ConversionError(f"duplicate generated xml:id: {candidate}")
    context.seen_ids.add(candidate)
    return candidate


def _corresp(fragment: str | None) -> str | None:
    return f"{SOURCE_HTML_URL}#{fragment}" if fragment else None


def _render_children(source: etree._Element, parent: etree._Element, context: _Context) -> None:
    _append_text(parent, source.text)
    for child in source:
        rendered = _render_inline(child, context)
        if rendered is not None:
            parent.append(rendered)
        _append_text(parent, child.tail)


def _render_page(node: etree._Element, context: _Context) -> etree._Element:
    source_id = node.get("id") or "page-unknown"
    text = _node_text(node)
    match = re.fullmatch(r"\[pg\s+(.+?)\]", text, flags=re.IGNORECASE)
    if not match:
        raise ConversionError(f"unrecognized page milestone: {text!r}")
    attrs = {
        "xml:id": _claim_id(context, context.source_to_tei_ids[source_id]),
        "n": match.group(1),
        "corresp": _corresp(source_id) or SOURCE_HTML_URL,
    }
    return _el("pb", attrs)


def _render_ref(node: etree._Element, context: _Context) -> etree._Element:
    source_id = node.get("id")
    href = node.get("href", "")
    attrs: dict[str, str] = {}
    if source_id and source_id.startswith("noteref_"):
        number = source_id.removeprefix("noteref_")
        attrs.update(
            {
                "xml:id": _claim_id(context, context.source_to_tei_ids[source_id]),
                "type": "note",
                "n": number,
                "corresp": _corresp(source_id) or SOURCE_HTML_URL,
            }
        )
    if href.startswith("#"):
        source_target = href[1:]
        target = context.source_to_tei_ids.get(source_target)
        attrs["target"] = f"#{target}" if target else f"{SOURCE_HTML_URL}{href}"
    elif href:
        attrs["target"] = href
    ref = _el("ref", attrs)
    _render_children(node, ref, context)
    return ref


def _render_inline(node: etree._Element, context: _Context) -> etree._Element | None:
    if not isinstance(node.tag, str):
        return None
    if _has_class(node, "tei-pb"):
        return _render_page(node, context)
    if node.tag == "a":
        if node.get("href"):
            return _render_ref(node, context)
        return None
    if node.tag == "br":
        return _el("lb")
    if _has_class(node, "tei-foreign"):
        attrs: dict[str, str] = {}
        if node.get("lang"):
            attrs["xml:lang"] = node.get("lang", "")
        foreign = _el("foreign", attrs)
        _render_children(node, foreign, context)
        return foreign
    if _has_class(node, "tei-q"):
        quote = _el("q")
        _render_children(node, quote, context)
        return quote
    if node.tag in {"em", "strong"} or _has_class(node, "tei-hi") or node.get("style"):
        rend = _style_rend(node)
        if rend:
            hi = _el("hi", {"rend": rend})
            _render_children(node, hi, context)
            return hi
    if node.tag == "span":
        wrapper = _el("seg")
        _render_children(node, wrapper, context)
        return wrapper
    if node.tag in {"i", "b", "sup"}:
        rend = {"i": "italic", "b": "bold", "sup": "superscript"}[node.tag]
        hi = _el("hi", {"rend": rend})
        _render_children(node, hi, context)
        return hi
    wrapper = _el("seg")
    _render_children(node, wrapper, context)
    return wrapper


def _render_paragraph(node: etree._Element, context: _Context) -> etree._Element:
    attrs: dict[str, str] = {}
    rend = _style_rend(node)
    if rend:
        attrs["rend"] = rend
    paragraph = _el("p", attrs)
    _render_children(node, paragraph, context)
    return paragraph


def _render_heading(node: etree._Element, context: _Context) -> etree._Element:
    head = _el("head")
    _render_children(node, head, context)
    return head


def _render_list(node: etree._Element, context: _Context) -> etree._Element:
    attrs = {"type": "contents"} if _has_class(node, "tei-index-toc") else {}
    result = _el("list", attrs)
    for item_source in node.xpath("./li"):
        item = _el("item")
        _render_children(item_source, item, context)
        result.append(item)
    return result


def _render_quote(node: etree._Element, context: _Context) -> etree._Element:
    quote = _el("quote")
    _render_block_children(node, quote, context)
    return quote


def _render_line_group(node: etree._Element, context: _Context) -> etree._Element:
    group = _el("lg")
    _render_block_children(node, group, context)
    return group


def _render_line(node: etree._Element, context: _Context) -> etree._Element:
    line = _el("l")
    _render_children(node, line, context)
    return line


def _render_div(node: etree._Element, context: _Context) -> etree._Element:
    heading_node = next(
        (child for child in node if isinstance(child.tag, str) and re.fullmatch(r"h[1-6]", child.tag)),
        None,
    )
    heading = _node_text(heading_node) if heading_node is not None else ""
    fragment = _source_fragment(node)
    attrs = {"type": _div_type(heading)}
    if fragment:
        generated_id = context.source_to_tei_ids.get(fragment, _safe_id("div-", fragment))
        attrs["xml:id"] = _claim_id(context, generated_id)
        attrs["corresp"] = _corresp(fragment) or SOURCE_HTML_URL
    result = _el("div", attrs)
    _render_block_children(node, result, context)
    return result


def _render_note_list(node: etree._Element, context: _Context) -> list[etree._Element]:
    notes: list[etree._Element] = []
    children = list(node)
    index = 0
    while index < len(children):
        label_node = children[index]
        if label_node.tag != "dt" or index + 1 >= len(children) or children[index + 1].tag != "dd":
            raise ConversionError("footnote definition list is not paired dt/dd markup")
        body_node = children[index + 1]
        label_link = next(iter(label_node.xpath(".//a[@id]")), None)
        if label_link is None:
            raise ConversionError("footnote label has no source identifier")
        source_id = label_link.get("id", "")
        number = source_id.removeprefix("note_")
        note = _el(
            "note",
            {
                "xml:id": _claim_id(context, context.source_to_tei_ids[source_id]),
                "place": "end",
                "n": number,
                "corresp": _corresp(source_id) or SOURCE_HTML_URL,
            },
        )
        paragraphs = body_node.xpath("./p")
        if paragraphs:
            for paragraph_index, paragraph_source in enumerate(paragraphs):
                paragraph = _render_paragraph(paragraph_source, context)
                if paragraph_index == 0:
                    paragraph.text = f"{_node_text(label_node)} " + (paragraph.text or "")
                note.append(paragraph)
        else:
            paragraph = _el("p", text=f"{_node_text(label_node)} ")
            _render_children(body_node, paragraph, context)
            note.append(paragraph)
        notes.append(note)
        index += 2
    return notes


def _render_block(node: etree._Element, context: _Context) -> etree._Element | list[etree._Element] | None:
    if not isinstance(node.tag, str):
        return None
    if _has_class(node, "tei-pb"):
        return _render_page(node, context)
    if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return _render_heading(node, context)
    if node.tag == "p":
        return _render_paragraph(node, context)
    if node.tag == "ul":
        return _render_list(node, context)
    if node.tag == "dl" and _has_class(node, "tei-list-footnotes"):
        return _render_note_list(node, context)
    if _has_class(node, "tei-div"):
        return _render_div(node, context)
    if _has_class(node, "tei-quote") or node.tag == "blockquote":
        return _render_quote(node, context)
    if _has_class(node, "tei-lg"):
        return _render_line_group(node, context)
    if _has_class(node, "tei-l"):
        return _render_line(node, context)
    if _has_class(node, "tei-tb"):
        return _el("milestone", {"unit": "source-horizontal-rule"})
    if node.tag == "hr" or (node.tag == "a" and not node.get("href")):
        return None
    if not _node_text(node) and not any(isinstance(child.tag, str) for child in node):
        return None
    anonymous = _el("ab")
    _render_children(node, anonymous, context)
    return anonymous


def _render_block_children(source: etree._Element, parent: etree._Element, context: _Context) -> None:
    for child in source:
        rendered = _render_block(child, context)
        if isinstance(rendered, list):
            parent.extend(rendered)
        elif rendered is not None:
            parent.append(rendered)


def _book_roots(root: html.HtmlElement) -> list[etree._Element]:
    body = root.xpath("//body")
    if len(body) != 1:
        raise ConversionError("retained HTML must contain one body")
    top = list(body[0])
    title = next((node for node in top if node.xpath("./h1")), None)
    contents = next(
        (node for node in top if node.xpath("./h2[normalize-space()='Contents']")),
        None,
    )
    text_body = next((node for node in top if _has_class(node, "tei-body")), None)
    text_back = next((node for node in top if _has_class(node, "tei-back")), None)
    if any(node is None for node in (title, contents, text_body, text_back)):
        raise ConversionError("retained title, contents, body, or back matter is missing")
    return [title, contents, text_body, text_back]  # type: ignore[list-item]


def _source_census(book_roots: list[etree._Element]) -> dict[str, object]:
    def count(xpath: str) -> int:
        return sum(len(root.xpath(xpath)) for root in book_roots)

    all_nodes = [node for root in book_roots for node in root.xpath(".//*")]
    census: dict[str, object] = {
        "source_paragraph_count": count(".//p[contains(concat(' ', normalize-space(@class), ' '), ' tei-p ')]"),
        "printed_page_anchor_count": count(".//span[contains(concat(' ', normalize-space(@class), ' '), ' tei-pb ')]"),
        "note_reference_count": count(".//a[starts-with(@id, 'noteref_')]"),
        "note_body_count": count(".//dd[contains(concat(' ', normalize-space(@class), ' '), ' tei-notetext ')]"),
        "source_emphasis_count": count(".//em[contains(concat(' ', normalize-space(@class), ' '), ' tei-emph ')]"),
        "source_style_italic_count": sum(1 for node in all_nodes if "font-style: italic" in (node.get("style", "") or "")),
        "source_smallcaps_count": sum(1 for node in all_nodes if "font-variant: small-caps" in (node.get("style", "") or "")),
        "source_superscript_count": sum(1 for node in all_nodes if "vertical-align: super" in (node.get("style", "") or "")),
        "source_foreign_count": count(".//span[contains(concat(' ', normalize-space(@class), ' '), ' tei-foreign ')]"),
        "source_latin_count": count(".//span[contains(concat(' ', normalize-space(@class), ' '), ' tei-foreign ') and @lang='la']"),
        "source_greek_count": count(".//span[contains(concat(' ', normalize-space(@class), ' '), ' tei-foreign ') and @lang='el']"),
        "source_unmarked_foreign_count": count(".//span[contains(concat(' ', normalize-space(@class), ' '), ' tei-foreign ') and not(@lang)]"),
        "source_inline_quote_count": count(".//span[contains(concat(' ', normalize-space(@class), ' '), ' tei-q ')]"),
        "source_block_quote_count": count(".//div[contains(concat(' ', normalize-space(@class), ' '), ' tei-quote ')]"),
        "source_line_group_count": count(".//div[contains(concat(' ', normalize-space(@class), ' '), ' tei-lg ')]"),
        "source_line_count": count(".//div[contains(concat(' ', normalize-space(@class), ' '), ' tei-l ')]"),
        "source_typographic_break_count": count(".//div[contains(concat(' ', normalize-space(@class), ' '), ' tei-tb ')]"),
        "source_contents_item_count": count(".//ul[contains(concat(' ', normalize-space(@class), ' '), ' tei-index-toc ')]/li"),
    }
    expected = {
        "source_paragraph_count": EXPECTED_SOURCE_PARAGRAPH_COUNT,
        "printed_page_anchor_count": EXPECTED_PAGE_COUNT,
        "note_reference_count": EXPECTED_NOTE_REF_COUNT,
        "note_body_count": EXPECTED_NOTE_COUNT,
        "source_emphasis_count": EXPECTED_EMPHASIS_COUNT,
        "source_style_italic_count": EXPECTED_STYLE_ITALIC_COUNT,
        "source_smallcaps_count": EXPECTED_SMALLCAPS_COUNT,
        "source_superscript_count": EXPECTED_SUPERSCRIPT_COUNT,
        "source_foreign_count": EXPECTED_FOREIGN_COUNT,
        "source_latin_count": EXPECTED_LATIN_COUNT,
        "source_greek_count": EXPECTED_GREEK_COUNT,
        "source_unmarked_foreign_count": EXPECTED_UNMARKED_FOREIGN_COUNT,
        "source_inline_quote_count": EXPECTED_INLINE_QUOTE_COUNT,
        "source_block_quote_count": EXPECTED_BLOCK_QUOTE_COUNT,
        "source_line_group_count": EXPECTED_LINE_GROUP_COUNT,
        "source_line_count": EXPECTED_LINE_COUNT,
        "source_typographic_break_count": EXPECTED_TYPOGRAPHIC_BREAK_COUNT,
        "source_contents_item_count": EXPECTED_CONTENTS_ITEM_COUNT,
    }
    changed = {key: (expected[key], census[key]) for key in expected if census[key] != expected[key]}
    if changed:
        raise ConversionError(f"retained source census changed: {changed}")
    return census


def _header() -> etree._Element:
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", {"type": "main"}, "An Essay in Aid of a Grammar of Assent"))
    title_stmt.append(_el("author", text="John Henry Newman"))
    file_desc.append(title_stmt)
    publication_stmt = _el("publicationStmt")
    publication_stmt.append(_el("publisher", text="Open Christian Data"))
    publication_stmt.append(_el("date", {"when": "2026-08-31"}, "2026"))
    availability = _el("availability", {"status": "unknown"})
    licence = _el("licence", {"target": "https://www.gutenberg.org/ebooks/34022"})
    licence.append(
        _el(
            "p",
            text=(
                "Historical text retained from Project Gutenberg eBook 34022; "
                "see the source-local README for credit and terms."
            ),
        )
    )
    availability.append(licence)
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("title", text="An Essay in Aid of a Grammar of Assent"))
    bibl.append(_el("edition", text="London: Burns, Oates & Co., 1874"))
    bibl.append(_el("author", text="John Henry Newman"))
    bibl.append(_el("date", {"when": "1874"}, "1874"))
    bibl.append(_el("idno", {"type": "project-gutenberg"}, "34022"))
    bibl.append(_el("idno", {"type": "archive-sha256"}, SOURCE_ARCHIVE_SHA256))
    bibl.append(_el("idno", {"type": "html-sha256"}, SOURCE_HTML_SHA256))
    bibl.append(_el("idno", {"type": "source-path"}, SOURCE_LOGICAL_PATH))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    encoding_desc = _el("encodingDesc")
    project_desc = _el("projectDesc")
    project_desc.append(
        _el(
            "p",
            text=(
                "Source-specific deterministic HTML-to-TEI P5 conversion. Printed pages are "
                "pb milestones; Gutenberg redistribution boilerplate is excluded."
            ),
        )
    )
    encoding_desc.append(project_desc)
    header.append(encoding_desc)
    revision = _el("revisionDesc")
    revision.append(_el("change", {"when": "2026-08-31"}, "Initial retained-source candidate conversion."))
    header.append(revision)
    return header


def _canonical_source_text(book_roots: list[etree._Element]) -> str:
    pieces: list[str] = []
    for root in book_roots:
        for text in root.xpath(".//text()"):
            parent = text.getparent()
            if parent is not None and _has_class(parent, "tei-pb"):
                continue
            pieces.append(str(text))
    return " ".join(" ".join(pieces).split())


def _canonical_tei_text(tree: etree._ElementTree) -> str:
    nodes = tree.xpath("/t:TEI/t:text", namespaces=NS)
    if len(nodes) != 1:
        raise ConversionError("TEI must contain one text element")
    return " ".join(" ".join(nodes[0].itertext()).split())


def _tei_counts(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    if root.tag != _qname("TEI"):
        raise ConversionError("TEI root is not TEI P5")
    ids = root.xpath("//@xml:id", namespaces=NS)
    if len(ids) != len(set(ids)):
        raise ConversionError("TEI xml:id values are not unique")
    id_set = set(ids)
    for target in root.xpath("//t:ref[starts-with(@target, '#')]/@target", namespaces=NS):
        if target[1:] not in id_set:
            raise ConversionError(f"unresolved TEI link target: {target}")
    counts: dict[str, object] = {
        "printed_page_anchor_count": len(root.xpath("//t:pb", namespaces=NS)),
        "note_reference_count": len(root.xpath("//t:ref[@type='note']", namespaces=NS)),
        "note_body_count": len(root.xpath("//t:note[@place='end']", namespaces=NS)),
        "part_count": len(root.xpath("/t:TEI/t:text/t:body/t:div[@type='part']", namespaces=NS)),
        "chapter_count": len(root.xpath("/t:TEI/t:text/t:body//t:div[@type='chapter']", namespaces=NS)),
        "section_count": len(root.xpath("/t:TEI/t:text/t:body//t:div[@type='section']", namespaces=NS)),
        "contents_item_count": len(root.xpath("//t:list[@type='contents']/t:item", namespaces=NS)),
        "foreign_count": len(root.xpath("//t:foreign", namespaces=NS)),
        "latin_count": len(root.xpath("//t:foreign[@xml:lang='la']", namespaces=NS)),
        "greek_count": len(root.xpath("//t:foreign[@xml:lang='el']", namespaces=NS)),
        "unmarked_foreign_count": len(root.xpath("//t:foreign[not(@xml:lang)]", namespaces=NS)),
        "inline_quote_count": len(root.xpath("//t:q", namespaces=NS)),
        "block_quote_count": len(root.xpath("//t:quote", namespaces=NS)),
        "line_group_count": len(root.xpath("//t:lg", namespaces=NS)),
        "line_count": len(root.xpath("//t:l", namespaces=NS)),
        "typographic_break_count": len(root.xpath("//t:milestone[@unit='source-horizontal-rule']", namespaces=NS)),
        "italic_mark_count": len(root.xpath("//t:hi[contains(concat(' ', @rend, ' '), ' italic ')]", namespaces=NS)),
        "smallcaps_count": len(root.xpath("//t:hi[contains(concat(' ', @rend, ' '), ' smallcaps ')]", namespaces=NS)),
        "superscript_count": len(root.xpath("//t:hi[contains(concat(' ', @rend, ' '), ' superscript ')]", namespaces=NS)),
        "tei_visible_text_sha256": _sha256(_canonical_tei_text(tree).encode("utf-8")),
    }
    expected = {
        "printed_page_anchor_count": EXPECTED_PAGE_COUNT,
        "note_reference_count": EXPECTED_NOTE_REF_COUNT,
        "note_body_count": EXPECTED_NOTE_COUNT,
        "part_count": EXPECTED_PART_COUNT,
        "chapter_count": EXPECTED_CHAPTER_COUNT,
        "section_count": EXPECTED_SECTION_COUNT,
        "contents_item_count": EXPECTED_CONTENTS_ITEM_COUNT,
        "foreign_count": EXPECTED_FOREIGN_COUNT,
        "latin_count": EXPECTED_LATIN_COUNT,
        "greek_count": EXPECTED_GREEK_COUNT,
        "unmarked_foreign_count": EXPECTED_UNMARKED_FOREIGN_COUNT,
        "inline_quote_count": EXPECTED_INLINE_QUOTE_COUNT,
        "block_quote_count": EXPECTED_BLOCK_QUOTE_COUNT,
        "line_group_count": EXPECTED_LINE_GROUP_COUNT,
        "line_count": EXPECTED_LINE_COUNT,
        "typographic_break_count": EXPECTED_TYPOGRAPHIC_BREAK_COUNT,
        "smallcaps_count": EXPECTED_SMALLCAPS_COUNT,
        "superscript_count": EXPECTED_SUPERSCRIPT_COUNT,
    }
    changed = {key: (expected[key], counts[key]) for key in expected if counts[key] != expected[key]}
    if changed:
        raise ConversionError(f"generated TEI accounting changed: {changed}")
    return counts


@lru_cache(maxsize=1)
def _tei_relaxng() -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(TEI_RNG_PATH)))


def validate_tei(value: etree._ElementTree | etree._Element | bytes | Path) -> dict[str, object]:
    """Validate TEI P5 and all source-specific structural/link invariants."""

    if isinstance(value, Path):
        tree = etree.parse(str(value))
    elif isinstance(value, bytes):
        tree = etree.ElementTree(etree.fromstring(value))
    elif isinstance(value, etree._ElementTree):
        tree = value
    elif isinstance(value, etree._Element):
        tree = etree.ElementTree(value)
    else:  # pragma: no cover - defensive API boundary
        raise TypeError(f"unsupported TEI value: {type(value)!r}")
    counts = _tei_counts(tree)
    schema = _tei_relaxng()
    if not schema.validate(tree):
        errors = [str(error) for error in schema.error_log]
        excerpt = "\n".join(errors[:20])
        if len(errors) > 20:
            excerpt += f"\n... {len(errors) - 20} more TEI P5 validation errors"
        raise ConversionError(f"TEI P5 Relax NG validation failed:\n{excerpt}")
    return counts


def _load_retained_source(
    source_logical_path: str,
    repository_root: Path,
) -> tuple[bytes, list[etree._Element], dict[str, object]]:
    if source_logical_path != SOURCE_LOGICAL_PATH:
        raise ConversionError(
            f"this route accepts only {SOURCE_LOGICAL_PATH}, got {source_logical_path}"
        )
    try:
        source_path = resolve_repo_path(repository_root, source_logical_path)
        archive_path = resolve_repo_path(repository_root, PACKAGE_LOGICAL_PATH)
    except StorageTopologyError as exc:
        raise ConversionError(f"cannot resolve retained source: {exc}") from exc
    if not source_path.is_file() or not archive_path.is_file():
        raise ConversionError(f"retained source does not exist: {source_logical_path}")
    extracted_bytes = source_path.read_bytes()
    if _sha256(extracted_bytes) != SOURCE_HTML_SHA256:
        raise ConversionError("retained extracted HTML SHA-256 changed")
    archive_bytes = archive_path.read_bytes()
    if _sha256(archive_bytes) != SOURCE_ARCHIVE_SHA256:
        raise ConversionError("retained archive SHA-256 does not match the release")
    try:
        with ZipFile(archive_path) as archive:
            members = sorted(info.filename for info in archive.infolist() if not info.is_dir())
            if members != sorted([SOURCE_HTML_MEMBER, SOURCE_COVER_MEMBER]):
                raise ConversionError(f"retained archive members changed: {members}")
            html_bytes = archive.read(SOURCE_HTML_MEMBER)
            cover_bytes = archive.read(SOURCE_COVER_MEMBER)
    except BadZipFile as exc:
        raise ConversionError("retained source is not a valid ZIP") from exc
    if html_bytes != extracted_bytes:
        raise ConversionError("retained ZIP HTML member differs from extracted source")
    if _sha256(cover_bytes) != SOURCE_COVER_SHA256:
        raise ConversionError("retained cover member SHA-256 changed")
    root = html.fromstring(extracted_bytes.decode("utf-8"))
    book_roots = _book_roots(root)
    census = _source_census(book_roots)
    census["source_visible_text_sha256"] = _sha256(
        _canonical_source_text(book_roots).encode("utf-8")
    )
    return extracted_bytes, book_roots, census


def _build_document(
    book_roots: list[etree._Element],
    census: dict[str, object],
) -> tuple[etree._ElementTree, dict[str, object]]:
    title_source, contents_source, body_source, back_source = book_roots
    context = _Context(_register_source_ids(book_roots), set())
    root = _el("TEI", nsmap={None: TEI_NS})
    root.append(_header())
    text = _el("text", {"xml:lang": "en"})
    front = _el("front")
    body = _el("body")
    back = _el("back")
    text.extend([front, body, back])
    root.append(text)

    title_page = _el("div", {"type": "title-page"})
    _render_block_children(title_source, title_page, context)
    front.append(title_page)
    contents = _el("div", {"type": "contents"})
    _render_block_children(contents_source, contents, context)
    front.append(contents)

    pending: list[etree._Element] = []
    for source_child in body_source:
        if _has_class(source_child, "tei-div"):
            heading_node = next(
                (child for child in source_child if isinstance(child.tag, str) and re.fullmatch(r"h[1-6]", child.tag)),
                None,
            )
            heading = _node_text(heading_node) if heading_node is not None else ""
            destination = front if heading.casefold().startswith("dedication") else back if heading.casefold() == "note." else body
            for pending_node in pending:
                rendered_pending = _render_block(pending_node, context)
                if rendered_pending is not None and not isinstance(rendered_pending, list):
                    destination.append(rendered_pending)
            pending.clear()
            destination.append(_render_div(source_child, context))
        else:
            pending.append(source_child)
    if any(_has_class(node, "tei-pb") for node in pending):
        raise ConversionError("unassigned terminal page milestone in source body")

    footnote_id = context.source_to_tei_ids.get("toc68", "div-footnotes")
    footnotes = _el("div", {"type": "footnotes", "xml:id": footnote_id})
    _claim_id(context, footnote_id)
    _render_block_children(back_source, footnotes, context)
    back.append(footnotes)

    tree = etree.ElementTree(root)
    counts = validate_tei(tree)
    source_text = _canonical_source_text(book_roots)
    tei_text = _canonical_tei_text(tree)
    if source_text != tei_text:
        mismatch = next(
            (index for index, values in enumerate(zip(source_text, tei_text)) if values[0] != values[1]),
            min(len(source_text), len(tei_text)),
        )
        raise ConversionError(
            "visible source text does not match TEI text; "
            f"first mismatch at {mismatch}: source={source_text[mismatch:mismatch + 80]!r}, "
            f"tei={tei_text[mismatch:mismatch + 80]!r}"
        )
    accounting: dict[str, object] = {
        "source_logical_path": SOURCE_LOGICAL_PATH,
        "package_logical_path": PACKAGE_LOGICAL_PATH,
        "archive_sha256": SOURCE_ARCHIVE_SHA256,
        "html_member": SOURCE_HTML_MEMBER,
        "html_sha256": SOURCE_HTML_SHA256,
        "cover_member": SOURCE_COVER_MEMBER,
        "cover_sha256": SOURCE_COVER_SHA256,
        **census,
        **counts,
        "tei_p5_relaxng_valid": True,
        "tei_relaxng_path": TEI_RNG_PATH.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
        "tei_relaxng_sha256": _sha256(TEI_RNG_PATH.read_bytes()),
        "excluded_boilerplate": {
            "project_gutenberg_header": "excluded as redistribution boilerplate; identity and credit are retained in teiHeader and README",
            "project_gutenberg_footer": "excluded as redistribution boilerplate; terms and credit are documented in README",
        },
    }
    return tree, accounting


def convert_source(
    source_logical_path: str,
    output_path: Path,
    *,
    repository_root: Path | None = None,
) -> ConversionResult:
    """Convert the one authorized retained source to deterministic TEI P5."""

    root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    _, book_roots, census = _load_retained_source(source_logical_path, root)
    tree, accounting = _build_document(book_roots, census)
    document = etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(document)
    accounting = dict(accounting)
    accounting["document_sha256"] = _sha256(document)
    return ConversionResult(output, accounting)


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_logical_path")
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--accounting", action="store_true")
    parser.add_argument("--accounting-output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = convert_source(args.source_logical_path, args.output_path)
    except (ConversionError, OSError, BadZipFile) as exc:
        parser.exit(2, f"error: {exc}\n")
    if args.accounting:
        print(json.dumps(result.accounting, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if args.accounting_output is not None:
        args.accounting_output.parent.mkdir(parents=True, exist_ok=True)
        args.accounting_output.write_text(
            json.dumps(result.accounting, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI test
    raise SystemExit(_main())
