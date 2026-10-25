"""Convert retained Project Gutenberg 8120 HTML to a TEI P5 candidate.

The route is bound to the current retained 1904 third enlarged edition. It
preserves the electronic source's title and editorial matter, complete Life,
Relations, Index, linked notes, internal references, language markup, and
typography. The source contains no print-page milestones; that limitation and
its disclosed electronic interventions are recorded rather than repaired.
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

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree, html

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
NS = {"t": TEI_NS}

SOURCE_LOGICAL_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-1/07/"
    "teresa-life-of-st-teresa-of-jesus/pg8120-h.zip"
)
SOURCE_ARCHIVE_SHA256 = (
    "92b3442c0b2c04c206152c41b698bd464899ac078c2660afa83c2c751b17d274"
)
SOURCE_HTML_MEMBER = "pg8120-images.html"
SOURCE_HTML_SHA256 = (
    "9aeeb297ddcd83e801b9782fd7c376af845491e3fd2a941a85530b0214ad3e74"
)
SOURCE_COVER_MEMBER = "8120-cover.png"
SOURCE_COVER_SHA256 = (
    "bf20cc07794aa2d1f6b350758dd7d7c7135a4759754f7058276d10be88ae04b6"
)
SOURCE_HTML_URL = "https://www.gutenberg.org/cache/epub/8120/pg8120-images.html"

EXPECTED_PARAGRAPH_COUNT = 2403
EXPECTED_HR_COUNT = 112
EXPECTED_NOTE_COUNT = 730
EXPECTED_NOTE_REF_COUNT = 730
EXPECTED_INTERNAL_LINK_COUNT = 2166
EXPECTED_LIFE_CHAPTER_COUNT = 40
EXPECTED_RELATION_COUNT = 11
EXPECTED_ABBR_COUNT = 529
EXPECTED_CITATION_COUNT = 337
EXPECTED_SMALL_COUNT = 772
EXPECTED_ITALIC_COUNT = 50
EXPECTED_BIG_COUNT = 59
EXPECTED_LANGUAGE_MARK_COUNT = 300
EXPECTED_SPANISH_COUNT = 95
EXPECTED_LATIN_COUNT = 191
EXPECTED_FRENCH_COUNT = 13
EXPECTED_HEBREW_COUNT = 1
EXPECTED_BLOCK_QUOTE_COUNT = 3
EXPECTED_TABLE_COUNT = 1
EXPECTED_DESCRIPTION_LIST_COUNT = 1
EXPECTED_DESCRIPTION_ITEM_COUNT = 20
EXPECTED_LINE_BREAK_COUNT = 24
EXPECTED_PAGE_COUNT = 0

TEI_RNG_PATH = (
    Path(__file__).resolve().parents[2]
    / "ocd_kernel"
    / "tei"
    / "vendor"
    / "relaxng"
    / "tei_all.rng"
)


class ConversionError(ValueError):
    """Raised when the retained source or generated TEI violates this route."""


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    accounting: dict[str, object]


@dataclass
class _Context:
    id_map: dict[str, str]
    claimed: set[str]


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


def _normalized(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "")


def _append_text(parent: etree._Element, value: str | None) -> None:
    text = _normalized(value)
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _node_text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _safe_id(prefix: str, source_id: str) -> str:
    return prefix + re.sub(r"[^A-Za-z0-9_.-]+", "-", source_id)


def _corresp(source_id: str | None) -> str | None:
    return f"{SOURCE_HTML_URL}#{source_id}" if source_id else None


def _note_anchor(node: etree._Element) -> etree._Element | None:
    anchors = node.xpath(".//a[@id and contains(@id, 'note')]")
    return anchors[0] if anchors else None


def _container_source_id(node: etree._Element) -> str | None:
    anchors = node.xpath(".//a[@id]")
    return anchors[0].get("id") if anchors else None


def _register_ids(book_roots: list[etree._Element]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for root in book_roots:
        candidates = [root] + list(root.xpath(".//*[@id]"))
        for node in candidates:
            source_id = node.get("id")
            if not source_id or source_id in mapping:
                continue
            if "note" in source_id and node.getparent() is not None and node.getparent().tag == "small":
                prefix = "note-"
            elif node.getparent() is not None and node.getparent().tag in {"h1", "h2", "h3", "h4"}:
                prefix = "div-"
            elif node.getparent() is not None and node.getparent().tag == "p":
                prefix = "p-"
            else:
                prefix = "anchor-"
            mapping[source_id] = _safe_id(prefix, source_id)
    return mapping


def _claim(context: _Context, value: str) -> str:
    if value in context.claimed:
        raise ConversionError(f"duplicate generated xml:id: {value}")
    context.claimed.add(value)
    return value


def _lang_attrs(node: etree._Element) -> dict[str, str]:
    return {"xml:lang": node.get("lang", "")} if node.get("lang") else {}


def _render_children(source: etree._Element, parent: etree._Element, context: _Context) -> None:
    _append_text(parent, source.text)
    for child in source:
        rendered = _render_inline(child, context)
        if rendered is not None:
            parent.append(rendered)
        _append_text(parent, child.tail)


def _render_anchor(node: etree._Element, context: _Context) -> etree._Element:
    source_id = node.get("id")
    href = node.get("href")
    if href:
        attrs: dict[str, str] = {}
        target_source = href[1:] if href.startswith("#") else None
        if target_source:
            target = context.id_map.get(target_source)
            attrs["target"] = f"#{target}" if target else f"{SOURCE_HTML_URL}{href}"
            if (
                "note" in target_source
                and _node_text(node).isdigit()
                and target_source in context.id_map
            ):
                attrs["type"] = "note"
                attrs["n"] = _node_text(node)
                ref_id = _safe_id("ref-", target_source)
                attrs["xml:id"] = _claim(context, ref_id)
        else:
            attrs["target"] = href
        ref = _el("ref", attrs)
        _render_children(node, ref, context)
        return ref
    attrs = {}
    if source_id:
        mapped = context.id_map[source_id]
        if mapped not in context.claimed:
            attrs["xml:id"] = _claim(context, mapped)
            attrs["corresp"] = _corresp(source_id) or SOURCE_HTML_URL
    segment = _el("seg", attrs)
    _render_children(node, segment, context)
    return segment


def _render_inline(node: etree._Element, context: _Context) -> etree._Element | None:
    if not isinstance(node.tag, str):
        return None
    if node.tag == "a":
        return _render_anchor(node, context)
    if node.tag == "br":
        return _el("lb")
    if node.tag == "abbr":
        attrs = _lang_attrs(node)
        if node.get("title"):
            attrs["n"] = node.get("title", "")
        result = _el("abbr", attrs)
        _render_children(node, result, context)
        return result
    if node.tag == "cite":
        attrs = {"rend": "citation", **_lang_attrs(node)}
        result = _el("title", attrs)
        _render_children(node, result, context)
        return result
    if node.get("lang") and node.tag in {"span", "i"}:
        attrs = _lang_attrs(node)
        if node.tag == "i":
            attrs["rend"] = "italic"
        result = _el("foreign", attrs)
        _render_children(node, result, context)
        return result
    if node.tag in {"i", "em", "strong", "small"} or "xhtml_big" in (node.get("class", "") or "").split():
        rend = {
            "i": "italic",
            "em": "italic emphasis",
            "strong": "bold",
            "small": "smaller",
        }.get(node.tag, "larger")
        result = _el("hi", {"rend": rend, **_lang_attrs(node)})
        _render_children(node, result, context)
        return result
    if node.tag == "span":
        result = _el("seg", _lang_attrs(node))
        _render_children(node, result, context)
        return result
    result = _el("seg", _lang_attrs(node))
    _render_children(node, result, context)
    return result


def _paragraph_id(node: etree._Element, context: _Context) -> tuple[str | None, str | None]:
    anchors = node.xpath(".//a[@id]")
    if not anchors:
        return None, None
    source_id = anchors[0].get("id")
    if not source_id or "note" in source_id:
        return None, None
    mapped = context.id_map[source_id]
    return _claim(context, mapped), source_id


def _render_paragraph(node: etree._Element, context: _Context) -> etree._Element:
    attrs = _lang_attrs(node)
    paragraph_id, source_id = _paragraph_id(node, context)
    if paragraph_id:
        attrs["xml:id"] = paragraph_id
        attrs["corresp"] = _corresp(source_id) or SOURCE_HTML_URL
    if node.get("align"):
        attrs["rend"] = node.get("align", "")
    paragraph = _el("p", attrs)
    _render_children(node, paragraph, context)
    return paragraph


def _render_note(node: etree._Element, context: _Context) -> etree._Element:
    anchor = _note_anchor(node)
    if anchor is None:
        raise ConversionError("note paragraph has no note anchor")
    source_id = anchor.get("id", "")
    number = _node_text(anchor)
    note = _el(
        "note",
        {
            "xml:id": _claim(context, context.id_map[source_id]),
            "place": "end",
            "n": number,
            "corresp": _corresp(source_id) or SOURCE_HTML_URL,
        },
    )
    note.append(_render_paragraph(node, context))
    return note


def _render_table(node: etree._Element, context: _Context) -> etree._Element:
    table = _el("table")
    for row_source in node.xpath(".//tr"):
        row = _el("row")
        for cell_source in row_source.xpath("./th|./td"):
            cell = _el("cell")
            if cell_source.xpath("./p"):
                for paragraph_source in cell_source.xpath("./p"):
                    cell.append(_render_paragraph(paragraph_source, context))
            else:
                _render_children(cell_source, cell, context)
            row.append(cell)
        table.append(row)
    return table


def _render_description_list(node: etree._Element, context: _Context) -> etree._Element:
    result = _el("list", {"type": "description"})
    for child in node:
        if child.tag == "dt":
            rendered = _el("label")
        elif child.tag == "dd":
            rendered = _el("item")
        else:
            continue
        if child.xpath("./p"):
            for paragraph_source in child.xpath("./p"):
                rendered.append(_render_paragraph(paragraph_source, context))
        else:
            _render_children(child, rendered, context)
        result.append(rendered)
    return result


def _render_quote(node: etree._Element, context: _Context) -> etree._Element:
    quote = _el("quote")
    paragraphs = node.xpath(".//p")
    if paragraphs:
        for paragraph_source in paragraphs:
            quote.append(_render_paragraph(paragraph_source, context))
    else:
        _render_children(node, quote, context)
    return quote


def _render_block(node: etree._Element, context: _Context) -> etree._Element | None:
    if node.tag == "p":
        return _render_note(node, context) if _note_anchor(node) is not None else _render_paragraph(node, context)
    if node.tag == "table":
        return _render_table(node, context)
    if node.tag == "blockquote":
        return _render_quote(node, context)
    if node.tag == "dl":
        return _render_description_list(node, context)
    if node.tag == "hr":
        return _el("milestone", {"unit": "typographic-break"})
    if node.tag == "pre":
        if not _node_text(node):
            return None
        paragraph = _el("p", {"rend": "preformatted"})
        _render_children(node, paragraph, context)
        return paragraph
    result = _el("ab")
    _render_children(node, result, context)
    return result


def _heading_type(text: str, level: int) -> str:
    folded = text.casefold()
    if level == 2:
        if folded.startswith("contents"):
            return "contents"
        if folded.startswith("introduction"):
            return "introduction"
        if "arguments of the chapters" in folded:
            return "chapter-arguments"
        if folded.startswith("preface"):
            return "translator-preface"
        if folded.startswith("annals"):
            return "chronology"
        if folded.startswith("the life of"):
            return "life"
        if folded.startswith("the relations"):
            return "relations"
        if folded.startswith("index"):
            return "index"
    if level == 3:
        if folded.startswith("chapter"):
            return "chapter"
        if folded.startswith("relation"):
            return "relation"
        if folded.startswith("prologue"):
            return "prologue"
    return "subsection"


def _new_div(node: etree._Element, level: int, context: _Context) -> etree._Element:
    text = _node_text(node)
    attrs = {"type": _heading_type(text, level)}
    source_id = _container_source_id(node)
    if source_id:
        attrs["xml:id"] = _claim(context, context.id_map[source_id])
        attrs["corresp"] = _corresp(source_id) or SOURCE_HTML_URL
    result = _el("div", attrs)
    head = _el("head")
    _render_children(node, head, context)
    result.append(head)
    return result


def _book_roots(root: html.HtmlElement) -> list[etree._Element]:
    bodies = root.xpath("//body")
    if len(bodies) != 1:
        raise ConversionError("retained source must contain one body")
    return [
        node
        for node in bodies[0]
        if isinstance(node.tag, str) and node.tag not in {"header", "footer"}
    ]


def _source_census(book_roots: list[etree._Element]) -> dict[str, object]:
    nodes = [node for root in book_roots for node in [root, *root.xpath(".//*")]]
    note_ids = [
        node for node in nodes
        if node.tag == "a" and node.get("id") and "note" in node.get("id", "")
        and node.getparent() is not None and node.getparent().tag == "small"
    ]
    note_refs = [
        node for node in nodes
        if node.tag == "a" and node.get("href", "").startswith("#")
        and "note" in node.get("href", "") and _node_text(node).isdigit()
    ]
    language_counts = {
        language: sum(1 for node in nodes if node.get("lang") == language)
        for language in ("es", "la", "fr", "he")
    }
    census: dict[str, object] = {
        "source_paragraph_count": sum(1 for node in nodes if node.tag == "p"),
        "source_typographic_break_count": sum(1 for node in nodes if node.tag == "hr"),
        "note_body_count": len(note_ids),
        "note_reference_count": len(note_refs),
        "note_target_unique_count": len({node.get("href", "")[1:] for node in note_refs}),
        "source_internal_link_count": sum(1 for node in nodes if node.tag == "a" and node.get("href", "").startswith("#")),
        "source_abbreviation_count": sum(1 for node in nodes if node.tag == "abbr"),
        "source_citation_count": sum(1 for node in nodes if node.tag == "cite"),
        "source_small_count": sum(1 for node in nodes if node.tag == "small"),
        "source_italic_count": sum(1 for node in nodes if node.tag in {"i", "em"}),
        "source_big_count": sum(1 for node in nodes if "xhtml_big" in (node.get("class", "") or "").split()),
        "source_language_mark_count": sum(1 for node in nodes if node.get("lang") in {"es", "la", "fr", "he"}),
        "source_spanish_count": language_counts["es"],
        "source_latin_count": language_counts["la"],
        "source_french_count": language_counts["fr"],
        "source_hebrew_count": language_counts["he"],
        "source_block_quote_count": sum(1 for node in nodes if node.tag == "blockquote"),
        "source_table_count": sum(1 for node in nodes if node.tag == "table"),
        "source_description_list_count": sum(1 for node in nodes if node.tag == "dl"),
        "source_description_item_count": sum(1 for node in nodes if node.tag == "dd"),
        "source_line_break_count": sum(1 for node in nodes if node.tag == "br"),
        "source_print_page_milestone_count": 0,
        "source_empty_pre_count": sum(1 for node in book_roots if node.tag == "pre" and not _node_text(node)),
    }
    expected = {
        "source_paragraph_count": EXPECTED_PARAGRAPH_COUNT,
        "source_typographic_break_count": EXPECTED_HR_COUNT,
        "note_body_count": EXPECTED_NOTE_COUNT,
        "note_reference_count": EXPECTED_NOTE_REF_COUNT,
        "note_target_unique_count": EXPECTED_NOTE_COUNT,
        "source_internal_link_count": EXPECTED_INTERNAL_LINK_COUNT,
        "source_abbreviation_count": EXPECTED_ABBR_COUNT,
        "source_citation_count": EXPECTED_CITATION_COUNT,
        "source_small_count": EXPECTED_SMALL_COUNT,
        "source_italic_count": EXPECTED_ITALIC_COUNT,
        "source_big_count": EXPECTED_BIG_COUNT,
        "source_language_mark_count": EXPECTED_LANGUAGE_MARK_COUNT,
        "source_spanish_count": EXPECTED_SPANISH_COUNT,
        "source_latin_count": EXPECTED_LATIN_COUNT,
        "source_french_count": EXPECTED_FRENCH_COUNT,
        "source_hebrew_count": EXPECTED_HEBREW_COUNT,
        "source_block_quote_count": EXPECTED_BLOCK_QUOTE_COUNT,
        "source_table_count": EXPECTED_TABLE_COUNT,
        "source_description_list_count": EXPECTED_DESCRIPTION_LIST_COUNT,
        "source_description_item_count": EXPECTED_DESCRIPTION_ITEM_COUNT,
        "source_line_break_count": EXPECTED_LINE_BREAK_COUNT,
        "source_print_page_milestone_count": EXPECTED_PAGE_COUNT,
        "source_empty_pre_count": 2,
    }
    changed = {key: (expected[key], census[key]) for key in expected if expected[key] != census[key]}
    if changed:
        raise ConversionError(f"retained source census changed: {changed}")
    return census


def _header() -> etree._Element:
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", {"type": "main"}, "The Life of St. Teresa of Jesus, of the Order of Our Lady of Carmel"))
    title_stmt.append(_el("author", text="Teresa of Avila"))
    title_stmt.append(_el("respStmt"))
    title_stmt[-1].append(_el("resp", text="translated by"))
    title_stmt[-1].append(_el("name", text="David Lewis"))
    file_desc.append(title_stmt)
    publication = _el("publicationStmt")
    publication.append(_el("publisher", text="Open Christian Data"))
    publication.append(_el("date", {"when": "2026-08-31"}, "2026"))
    availability = _el("availability", {"status": "unknown"})
    licence = _el("licence", {"target": "https://www.gutenberg.org/ebooks/8120"})
    licence.append(_el("p", text="Historical text retained from Project Gutenberg eBook 8120; see the source-local README for credit and terms."))
    availability.append(licence)
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("title", text="The Life of St. Teresa of Jesus, of the Order of Our Lady of Carmel"))
    bibl.append(_el("edition", text="Third Edition Enlarged, London and New York, 1904"))
    bibl.append(_el("author", text="Teresa of Avila"))
    bibl.append(_el("respStmt"))
    bibl[-1].append(_el("resp", text="translated by"))
    bibl[-1].append(_el("name", text="David Lewis"))
    bibl.append(_el("date", {"when": "1904"}, "1904"))
    bibl.append(_el("idno", {"type": "project-gutenberg"}, "8120"))
    bibl.append(_el("idno", {"type": "archive-sha256"}, SOURCE_ARCHIVE_SHA256))
    bibl.append(_el("idno", {"type": "html-sha256"}, SOURCE_HTML_SHA256))
    bibl.append(_el("idno", {"type": "source-path"}, SOURCE_LOGICAL_PATH))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    encoding = _el("encodingDesc")
    project = _el("projectDesc")
    project.append(_el("p", text="Source-specific deterministic HTML-to-TEI P5 conversion. The electronic source has no print-page milestones; disclosed Corrigenda, section-number, quotation, and footnote-placement interventions are retained and accounted."))
    encoding.append(project)
    header.append(encoding)
    revision = _el("revisionDesc")
    revision.append(_el("change", {"when": "2026-08-31"}, "Initial retained-source candidate conversion."))
    header.append(revision)
    return header


def _canonical_source(book_roots: list[etree._Element]) -> str:
    pieces: list[str] = []
    for root in book_roots:
        pieces.extend(str(value) for value in root.xpath(".//text()") if _normalized(str(value)))
    return " ".join(" ".join(pieces).split())


def _canonical_tei(tree: etree._ElementTree) -> str:
    text = tree.xpath("/t:TEI/t:text", namespaces=NS)
    if len(text) != 1:
        raise ConversionError("TEI must contain one text element")
    return " ".join(" ".join(text[0].itertext()).split())


def _tei_counts(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    ids = root.xpath("//@xml:id", namespaces=NS)
    if len(ids) != len(set(ids)):
        raise ConversionError("TEI xml:id values are not unique")
    id_set = set(ids)
    local_targets = root.xpath("//t:ref[starts-with(@target, '#')]/@target", namespaces=NS)
    missing = [target for target in local_targets if target[1:] not in id_set]
    if missing:
        raise ConversionError(f"unresolved TEI link targets: {missing[:10]}")
    counts: dict[str, object] = {
        "paragraph_count": len(root.xpath("/t:TEI/t:text//t:p", namespaces=NS)),
        "typographic_break_count": len(root.xpath("//t:milestone[@unit='typographic-break']", namespaces=NS)),
        "note_body_count": len(root.xpath("//t:note[@place='end']", namespaces=NS)),
        "note_reference_count": len(root.xpath("//t:ref[@type='note']", namespaces=NS)),
        "internal_link_count": len(root.xpath("//t:ref[starts-with(@target, '#')]", namespaces=NS)),
        "life_chapter_count": len(root.xpath("/t:TEI/t:text/t:body//t:div[@type='chapter']", namespaces=NS)),
        "relation_count": len(root.xpath("/t:TEI/t:text/t:back//t:div[@type='relation']", namespaces=NS)),
        "abbreviation_count": len(root.xpath("//t:abbr", namespaces=NS)),
        "citation_count": len(root.xpath("//t:title[@rend='citation']", namespaces=NS)),
        "small_count": len(root.xpath("//t:hi[contains(concat(' ', @rend, ' '), ' smaller ')]", namespaces=NS)),
        "italic_count": len(root.xpath("//*[@rend and contains(concat(' ', @rend, ' '), ' italic ')]", namespaces=NS)),
        "big_count": len(root.xpath("//t:hi[contains(concat(' ', @rend, ' '), ' larger ')]", namespaces=NS)),
        "language_mark_count": len(root.xpath("/t:TEI/t:text//*[@xml:lang and @xml:lang!='en']", namespaces=NS)),
        "spanish_count": len(root.xpath("/t:TEI/t:text//*[@xml:lang='es']", namespaces=NS)),
        "latin_count": len(root.xpath("/t:TEI/t:text//*[@xml:lang='la']", namespaces=NS)),
        "french_count": len(root.xpath("/t:TEI/t:text//*[@xml:lang='fr']", namespaces=NS)),
        "hebrew_count": len(root.xpath("/t:TEI/t:text//*[@xml:lang='he']", namespaces=NS)),
        "block_quote_count": len(root.xpath("//t:quote", namespaces=NS)),
        "table_count": len(root.xpath("/t:TEI/t:text//t:table", namespaces=NS)),
        "description_list_count": len(root.xpath("//t:list[@type='description']", namespaces=NS)),
        "description_item_count": len(root.xpath("//t:list[@type='description']/t:item", namespaces=NS)),
        "line_break_count": len(root.xpath("//t:lb", namespaces=NS)),
        "printed_page_milestone_count": len(root.xpath("//t:pb", namespaces=NS)),
        "tei_visible_text_sha256": _sha256(_canonical_tei(tree).encode("utf-8")),
    }
    expected = {
        "paragraph_count": EXPECTED_PARAGRAPH_COUNT,
        "typographic_break_count": EXPECTED_HR_COUNT,
        "note_body_count": EXPECTED_NOTE_COUNT,
        "note_reference_count": EXPECTED_NOTE_REF_COUNT,
        "internal_link_count": EXPECTED_INTERNAL_LINK_COUNT,
        "life_chapter_count": EXPECTED_LIFE_CHAPTER_COUNT,
        "relation_count": EXPECTED_RELATION_COUNT,
        "abbreviation_count": EXPECTED_ABBR_COUNT,
        "citation_count": EXPECTED_CITATION_COUNT,
        "small_count": EXPECTED_SMALL_COUNT,
        "italic_count": EXPECTED_ITALIC_COUNT,
        "big_count": EXPECTED_BIG_COUNT,
        "language_mark_count": EXPECTED_LANGUAGE_MARK_COUNT,
        "spanish_count": EXPECTED_SPANISH_COUNT,
        "latin_count": EXPECTED_LATIN_COUNT,
        "french_count": EXPECTED_FRENCH_COUNT,
        "hebrew_count": EXPECTED_HEBREW_COUNT,
        "block_quote_count": EXPECTED_BLOCK_QUOTE_COUNT,
        "table_count": EXPECTED_TABLE_COUNT,
        "description_list_count": EXPECTED_DESCRIPTION_LIST_COUNT,
        "description_item_count": EXPECTED_DESCRIPTION_ITEM_COUNT,
        "line_break_count": EXPECTED_LINE_BREAK_COUNT,
        "printed_page_milestone_count": EXPECTED_PAGE_COUNT,
    }
    changed = {key: (expected[key], counts[key]) for key in expected if expected[key] != counts[key]}
    if changed:
        raise ConversionError(f"generated TEI accounting changed: {changed}")
    return counts


@lru_cache(maxsize=1)
def _tei_relaxng() -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(TEI_RNG_PATH)))


def validate_tei(value: etree._ElementTree | etree._Element | bytes | Path) -> dict[str, object]:
    if isinstance(value, Path):
        tree = etree.parse(str(value))
    elif isinstance(value, bytes):
        tree = etree.ElementTree(etree.fromstring(value))
    elif isinstance(value, etree._ElementTree):
        tree = value
    elif isinstance(value, etree._Element):
        tree = etree.ElementTree(value)
    else:  # pragma: no cover
        raise TypeError(f"unsupported TEI value: {type(value)!r}")
    counts = _tei_counts(tree)
    schema = _tei_relaxng()
    if not schema.validate(tree):
        errors = [str(error) for error in schema.error_log]
        raise ConversionError("TEI P5 Relax NG validation failed:\n" + "\n".join(errors[:20]))
    return counts


def _load_retained_source(source_logical_path: str, repository_root: Path) -> tuple[list[etree._Element], dict[str, object]]:
    if source_logical_path != SOURCE_LOGICAL_PATH:
        raise ConversionError(f"this route accepts only {SOURCE_LOGICAL_PATH}")
    try:
        archive_path = resolve_repo_path(repository_root, source_logical_path)
    except StorageTopologyError as exc:
        raise ConversionError(f"cannot resolve retained source: {exc}") from exc
    archive_bytes = archive_path.read_bytes()
    if _sha256(archive_bytes) != SOURCE_ARCHIVE_SHA256:
        raise ConversionError("retained archive SHA-256 changed")
    try:
        with ZipFile(archive_path) as archive:
            members = sorted(info.filename for info in archive.infolist() if not info.is_dir())
            if members != sorted([SOURCE_HTML_MEMBER, SOURCE_COVER_MEMBER]):
                raise ConversionError(f"retained archive members changed: {members}")
            html_bytes = archive.read(SOURCE_HTML_MEMBER)
            cover_bytes = archive.read(SOURCE_COVER_MEMBER)
    except BadZipFile as exc:
        raise ConversionError("retained source is not a valid ZIP") from exc
    if _sha256(html_bytes) != SOURCE_HTML_SHA256 or _sha256(cover_bytes) != SOURCE_COVER_SHA256:
        raise ConversionError("retained member SHA-256 changed")
    root = html.fromstring(html_bytes.decode("utf-8"))
    book_roots = _book_roots(root)
    census = _source_census(book_roots)
    census["source_visible_text_sha256"] = _sha256(_canonical_source(book_roots).encode("utf-8"))
    return book_roots, census


def _build_document(book_roots: list[etree._Element], census: dict[str, object]) -> tuple[etree._ElementTree, dict[str, object]]:
    context = _Context(_register_ids(book_roots), set())
    root = _el("TEI", {"xml:lang": "en"}, nsmap={None: TEI_NS})
    root.append(_header())
    text = _el("text")
    front = _el("front")
    body = _el("body")
    back = _el("back")
    text.extend([front, body, back])
    root.append(text)

    title_page = _el("div", {"type": "title-page"})
    front.append(title_page)
    phase = "front"
    major: etree._Element = title_page
    section: etree._Element | None = None
    subsection: etree._Element | None = None

    for source in book_roots:
        if source.tag == "h1":
            section = _el("div", {"type": "title"})
            head = _el("head")
            _render_children(source, head, context)
            section.append(head)
            major.append(section)
            subsection = None
            continue
        if source.tag == "h2":
            heading_type = _heading_type(_node_text(source), 2)
            if heading_type == "life":
                phase = "body"
            elif heading_type in {"relations", "index"}:
                phase = "back"
            destination = {"front": front, "body": body, "back": back}[phase]
            major = _new_div(source, 2, context)
            destination.append(major)
            section = None
            subsection = None
            continue
        if source.tag == "h3":
            section = _new_div(source, 3, context)
            major.append(section)
            subsection = None
            continue
        if source.tag == "h4":
            subsection = _new_div(source, 4, context)
            target = section if section is not None else major
            target.append(subsection)
            continue
        rendered = _render_block(source, context)
        if rendered is not None:
            target = subsection if subsection is not None else section if section is not None else major
            target.append(rendered)

    tree = etree.ElementTree(root)
    counts = validate_tei(tree)
    source_text = _canonical_source(book_roots)
    tei_text = _canonical_tei(tree)
    if source_text != tei_text:
        mismatch = next((i for i, pair in enumerate(zip(source_text, tei_text)) if pair[0] != pair[1]), min(len(source_text), len(tei_text)))
        raise ConversionError(f"visible source/TEI text mismatch at {mismatch}: {source_text[mismatch:mismatch+80]!r} != {tei_text[mismatch:mismatch+80]!r}")
    accounting: dict[str, object] = {
        "source_logical_path": SOURCE_LOGICAL_PATH,
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
        "electronic_source_limitations": {
            "print_page_milestones": "none encoded in the retained HTML; no page numbers invented",
            "edition": "1904 Third Edition Enlarged with additional notes and an introduction by Benedict Zimmerman",
            "transcriber_interventions": [
                "Corrigenda corrections applied",
                "section number added for L 3.9",
                "two Scriptural quotation typographical errors corrected",
                "footnotes gathered at chapter ends"
            ],
            "facsimile": "the package contains a cover image but no page-image facsimile"
        },
        "excluded_boilerplate": {
            "project_gutenberg_header": "excluded; identity and credit retained in teiHeader and README",
            "project_gutenberg_footer": "excluded; terms and credit retained in README"
        }
    }
    return tree, accounting


def convert_source(source_logical_path: str, output_path: Path, *, repository_root: Path | None = None) -> ConversionResult:
    root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    book_roots, census = _load_retained_source(source_logical_path, root)
    tree, accounting = _build_document(book_roots, census)
    document = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=True)
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
        args.accounting_output.write_text(json.dumps(result.accounting, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
