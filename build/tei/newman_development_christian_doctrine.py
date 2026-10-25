"""Convert the retained Gutenberg 35110 HTML edition of Newman's work to TEI P5.

This is intentionally a source-local route.  Project Gutenberg's HTML is a
useful carrier for this edition's page anchors, footnote links, typography,
and chapter hierarchy, but its surrounding redistribution boilerplate is not
part of the historical work.  The route therefore binds itself to the
retained archive and its observed census instead of trying to be a general
Gutenberg converter.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Mapping
from zipfile import BadZipFile, ZipFile

if __package__ in {None, ""}:  # pragma: no cover - exercised by the CLI test
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
    "newman-development-christian-doctrine/pg35110-h.zip"
)
SOURCE_ARCHIVE_SHA256 = (
    "8335ab4ef21bc0c17169eb8562d3271f49595ce851948476a32ce9ae8d7c22f6"
)
SOURCE_HTML_MEMBER = "pg35110-images.html"
SOURCE_HTML_SHA256 = "9713808e5dc56b6d0ffff66e4ea470b21760ee1aadca7ff8aad9da807e8822d4"
SOURCE_HTML_URL = "https://www.gutenberg.org/cache/epub/35110/pg35110-images.html"
SOURCE_COVER_MEMBER = "35110-cover.png"
EXPECTED_PAGE_COUNT = 458
EXPECTED_NOTE_REF_COUNT = 401
EXPECTED_NOTE_COUNT = 400
EXPECTED_GREEK_COUNT = 26
EXPECTED_PARAGRAPH_COUNT = 1566
EXPECTED_INCLUDED_PARAGRAPH_COUNT = 1560
EXPECTED_ITALIC_COUNT = 380
EXPECTED_SMALLCAPS_COUNT = 13
EXPECTED_PART_COUNT = 2
EXPECTED_CHAPTER_COUNT = 12
EXPECTED_SECTION_COUNT = 29
EXPECTED_SUBSECTION_COUNT = 21
EXPECTED_FOOTNOTE_GROUP_COUNT = 14
EXPECTED_DUPLICATE_NOTE_SOURCE_ID = "Footnote_315_3_296"
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
    """The requested output and source/TEI accounting for one conversion."""

    output_path: Path
    accounting: dict[str, object]


@dataclass
class _Context:
    page_ids: dict[str, str]
    anchor_ids: dict[str, str]
    note_ids: dict[str, str]
    paragraph_ids: dict[str, str]
    reference_number: int = 0
    greek_count: int = 0


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalized_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "")


def _norm_node(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _node_path(node: etree._Element) -> str:
    """Return a stable source-tree key (lxml proxy identity is not stable)."""

    return node.getroottree().getpath(node)


def _has_class(node: html.HtmlElement | etree._Element, name: str) -> bool:
    return name in (node.get("class", "") or "").split()


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


def _safe_id(prefix: str, source_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_id)
    return prefix + value


def _append_text(parent: etree._Element, text: str | None) -> None:
    value = _normalized_text(text)
    if not value:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _append_source_tail(source: etree._Element, parent: etree._Element) -> None:
    """Carry visible whitespace between source sibling blocks into TEI tails."""

    _append_text(parent, source.tail)


def _is_heading(node: html.HtmlElement | etree._Element) -> bool:
    return node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}


def _heading_text(node: html.HtmlElement | etree._Element) -> str:
    return _norm_node(node)


def _source_note_nodes(body: html.HtmlElement) -> list[html.HtmlElement]:
    return [
        node
        for node in body.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' footnote ')]"
        )
        if isinstance(node.tag, str)
    ]


def _source_census(root: html.HtmlElement) -> dict[str, object]:
    bodies = root.xpath("//body")
    if len(bodies) != 1:
        raise ConversionError("retained HTML must contain exactly one body")
    body = bodies[0]

    title_nodes = body.xpath(".//h1")
    if len(title_nodes) != 1 or _heading_text(title_nodes[0]) != (
        "AN ESSAY ON THE DEVELOPMENT OF CHRISTIAN DOCTRINE."
    ):
        raise ConversionError("retained HTML has an unexpected Gutenberg title")

    pages = body.xpath(
        ".//span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')]"
    )
    page_source_ids: list[str] = []
    for page in pages:
        anchors = page.xpath(".//a[@id]")
        if len(anchors) != 1:
            raise ConversionError("each printed page span must carry one source anchor")
        page_source_ids.append(anchors[0].get("id", ""))
    if len(pages) != EXPECTED_PAGE_COUNT:
        raise ConversionError(
            f"printed page anchor count changed: expected {EXPECTED_PAGE_COUNT}, got {len(pages)}"
        )
    if len(set(page_source_ids)) != EXPECTED_PAGE_COUNT:
        raise ConversionError("printed page source IDs are not unique")

    note_nodes = _source_note_nodes(body)
    if len(note_nodes) != EXPECTED_NOTE_COUNT:
        raise ConversionError(
            f"footnote body count changed: expected {EXPECTED_NOTE_COUNT}, got {len(note_nodes)}"
        )
    note_source_ids: list[str] = []
    for note in note_nodes:
        anchors = note.xpath(".//p[1]/a[@id]")
        if len(anchors) != 1:
            raise ConversionError("each footnote body must carry one source ID anchor")
        note_source_ids.append(anchors[0].get("id", ""))
    if len(set(note_source_ids)) != EXPECTED_NOTE_COUNT:
        raise ConversionError("footnote source IDs are not unique")

    fnanchors = body.xpath(
        ".//a[contains(concat(' ', normalize-space(@class), ' '), ' fnanchor ')]"
    )
    if len(fnanchors) != EXPECTED_NOTE_REF_COUNT:
        raise ConversionError(
            f"footnote reference count changed: expected {EXPECTED_NOTE_REF_COUNT}, got {len(fnanchors)}"
        )
    note_source_id_set = set(note_source_ids)
    targets: list[str] = []
    for ref in fnanchors:
        href = ref.get("href", "")
        if not href.startswith("#") or href[1:] not in note_source_id_set:
            raise ConversionError(f"unresolved retained footnote target: {href!r}")
        targets.append(href[1:])
    target_counts = Counter(targets)
    if target_counts.get(EXPECTED_DUPLICATE_NOTE_SOURCE_ID) != 2:
        raise ConversionError(
            "the retained extra-reference condition for Footnote_315_3_296 was not observed"
        )
    if sum(count > 1 for count in target_counts.values()) != 1:
        raise ConversionError("unexpected duplicate footnote targets in retained source")

    ins_nodes = body.xpath(".//ins")
    if len(ins_nodes) != EXPECTED_GREEK_COUNT or not all(
        _has_class(node, "greek") and bool(node.get("title")) for node in ins_nodes
    ):
        raise ConversionError(
            "retained <ins> census changed; all 26 source spans must be Greek with titles"
        )
    if body.xpath(".//del"):
        raise ConversionError("unexpected deletion markup in retained source")

    part_nodes = [
        node
        for node in body.xpath("./h2")
        if _heading_text(node) in {"PART I.", "PART II."}
    ]
    chapter_nodes = [
        node for node in body.xpath("./h2") if _heading_text(node).startswith("CHAPTER ")
    ]
    if len(part_nodes) != EXPECTED_PART_COUNT or len(chapter_nodes) != EXPECTED_CHAPTER_COUNT:
        raise ConversionError("retained part/chapter heading census changed")

    paragraphs = body.xpath(".//p")
    if len(paragraphs) != EXPECTED_PARAGRAPH_COUNT:
        raise ConversionError(
            f"source paragraph count changed: expected {EXPECTED_PARAGRAPH_COUNT}, got {len(paragraphs)}"
        )
    included_paragraphs = [
        paragraph
        for paragraph in paragraphs
        if not paragraph.xpath("ancestor::header[@id='pg-header'] | ancestor::footer[@id='pg-footer']")
    ]
    if len(included_paragraphs) != EXPECTED_INCLUDED_PARAGRAPH_COUNT:
        raise ConversionError("included source paragraph count changed")
    empty_layout_paragraphs = [
        paragraph for paragraph in included_paragraphs if not _norm_node(paragraph)
    ]
    page_only_paragraphs = [
        paragraph
        for paragraph in included_paragraphs
        if paragraph.xpath(
            ".//span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')]"
        )
        and not "".join(
            paragraph.xpath(
                ".//text()[not(ancestor::span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')])]"
            )
        ).strip()
    ]

    footnote_heading_count = sum(
        1
        for node in body.xpath("./h3")
        if _heading_text(node).upper() == "FOOTNOTES:"
    )
    if footnote_heading_count != EXPECTED_FOOTNOTE_GROUP_COUNT:
        raise ConversionError("source footnote-group heading census changed")

    return {
        "source_page_ids": tuple(page_source_ids),
        "source_note_ids": tuple(note_source_ids),
        "source_note_targets": tuple(targets),
        "source_paragraph_count": len(paragraphs),
        "included_source_paragraph_count": len(included_paragraphs),
        "source_empty_layout_paragraph_count": len(empty_layout_paragraphs),
        "source_page_only_paragraph_count": len(page_only_paragraphs),
        "source_ins_greek_count": len(ins_nodes),
        "source_italic_count": len(body.xpath(".//i")),
        "source_smallcaps_count": sum(
            1
            for node in body.xpath(".//span")
            if _has_class(node, "smcap") or _has_class(node, "allcapsc")
        ),
        "source_table_row_count": len(body.xpath(".//table//tr")),
        "source_block_quote_count": len(
            body.xpath(
                ".//div[contains(concat(' ', normalize-space(@class), ' '), ' blockquot ')]"
            )
        ),
        "source_list_count": len(body.xpath(".//ul | .//ol")),
        "source_visible_text": _source_visible_text(body),
    }


def _source_visible_text(node: html.HtmlElement | etree._Element) -> str:
    """Return visible source text, omitting only represented page labels."""

    parts: list[str] = []

    def visit(current: html.HtmlElement | etree._Element) -> None:
        if current.tag in {"header", "footer"} and _has_class(current, "pg-boilerplate"):
            return
        if current.tag == "span" and _has_class(current, "pagenum"):
            return
        if current.text:
            parts.append(current.text)
        for child in current:
            visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return " ".join("".join(parts).split())


def _prepare_context(body: html.HtmlElement, census: Mapping[str, object]) -> _Context:
    page_ids = {
        source_id: _safe_id("newman-page-", source_id)
        for source_id in census["source_page_ids"]  # type: ignore[index]
    }
    note_ids = {
        source_id: _safe_id("newman-note-", source_id)
        for source_id in census["source_note_ids"]  # type: ignore[index]
    }
    anchor_ids: dict[str, str] = {}
    for anchor in body.xpath(".//a[@id]"):
        source_id = anchor.get("id")
        if not source_id:
            continue
        if source_id in page_ids or source_id in note_ids:
            continue
        if source_id in anchor_ids:
            raise ConversionError(f"source anchor ID is not unique: {source_id}")
        anchor_ids[source_id] = _safe_id("newman-anchor-", source_id)

    paragraph_ids: dict[str, str] = {}
    number = 0
    for paragraph in body.xpath(".//p"):
        if paragraph.xpath("ancestor::header[@id='pg-header'] | ancestor::footer[@id='pg-footer']"):
            continue
        number += 1
        paragraph_ids[_node_path(paragraph)] = f"newman-p-{number:04d}"
    return _Context(page_ids, anchor_ids, note_ids, paragraph_ids)


def _append_children(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    if source.text:
        _append_text(parent, source.text)
    for child in source:
        _render_any(child, parent, context)
        if child.tail:
            _append_text(parent, child.tail)


def _render_page_span(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    anchors = source.xpath(".//a[@id]")
    if len(anchors) != 1:
        raise ConversionError("printed page span lost its source anchor")
    source_id = anchors[0].get("id")
    if not source_id or source_id not in context.page_ids:
        raise ConversionError("printed page span references an unknown source page ID")
    label = _norm_node(source)
    match = re.fullmatch(r"\[Pg\s+(.+)\]", label)
    if match is None:
        raise ConversionError(f"unexpected printed page label: {label!r}")
    parent.append(
        _el(
            "pb",
            {
                "xml:id": context.page_ids[source_id],
                "n": match.group(1),
                "corresp": f"{SOURCE_HTML_URL}#{source_id}",
            },
        )
    )


def _render_note_ref(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    href = source.get("href", "")
    source_target = href.removeprefix("#")
    target = context.note_ids.get(source_target)
    if target is None:
        raise ConversionError(f"footnote reference target is not represented: {href}")
    previous = source.getprevious()
    source_ref_id = previous.get("id") if previous is not None and previous.tag == "a" else None
    attrs = {
        "type": "note",
        "target": f"#{target}",
        "xml:id": f"newman-ref-{context.reference_number + 1:04d}",
        "corresp": (
            f"{SOURCE_HTML_URL}#{source_ref_id}"
            if source_ref_id
            else f"{SOURCE_HTML_URL}#{source_target}"
        ),
    }
    context.reference_number += 1
    ref = _el("ref", attrs)
    _append_children(source, ref, context)
    parent.append(ref)


def _render_anchor(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    source_id = source.get("id")
    if not source_id:
        _append_children(source, parent, context)
        return
    output_id = context.anchor_ids.get(source_id)
    if output_id is None:
        output_id = context.page_ids.get(source_id)
    if output_id is None:
        output_id = _safe_id("newman-anchor-", source_id)
        context.anchor_ids[source_id] = output_id
    parent.append(
        _el(
            "anchor",
            {"xml:id": output_id, "corresp": f"{SOURCE_HTML_URL}#{source_id}"},
        )
    )
    _append_children(source, parent, context)


def _render_link(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    href = source.get("href", "")
    if href.startswith("#"):
        source_target = href[1:]
        if source_target in context.page_ids:
            target = context.page_ids[source_target]
            ref_type = "page"
        elif source_target in context.anchor_ids:
            target = context.anchor_ids[source_target]
            ref_type = "internal"
        else:
            raise ConversionError(f"internal source link target is not represented: {href}")
        ref = _el(
            "ref",
            {
                "type": ref_type,
                "target": f"#{target}",
                "corresp": f"{SOURCE_HTML_URL}{href}",
            },
        )
    else:
        ref = _el("ref", {"type": "external", "target": href})
    _append_children(source, ref, context)
    parent.append(ref)


def _render_inline(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    tag = source.tag
    if tag == "span" and _has_class(source, "pagenum"):
        _render_page_span(source, parent, context)
        return
    if tag == "a" and _has_class(source, "fnanchor"):
        _render_note_ref(source, parent, context)
        return
    if tag == "a" and source.get("href"):
        _render_link(source, parent, context)
        return
    if tag == "a" and source.get("id"):
        _render_anchor(source, parent, context)
        return
    if tag == "br":
        parent.append(_el("lb"))
        return
    if tag == "ins" and _has_class(source, "greek"):
        title = source.get("title")
        if not title:
            raise ConversionError("Greek source span has no transliteration title")
        context.greek_count += 1
        foreign = _el(
            "foreign",
            {
                "xml:lang": "grc",
                "ana": "urn:ocd:greek-transliteration",
                "n": title,
            },
        )
        _append_children(source, foreign, context)
        parent.append(foreign)
        return
    if tag in {"i", "em"}:
        hi = _el("hi", {"rend": "italic"})
        _append_children(source, hi, context)
        parent.append(hi)
        return
    if tag in {"strong", "b"}:
        hi = _el("hi", {"rend": "bold"})
        _append_children(source, hi, context)
        parent.append(hi)
        return
    if tag == "span" and (_has_class(source, "smcap") or _has_class(source, "allcapsc")):
        hi = _el("hi", {"rend": "smallcaps"})
        _append_children(source, hi, context)
        parent.append(hi)
        return
    if tag == "span" and _has_class(source, "label"):
        label = _el("label")
        _append_children(source, label, context)
        parent.append(label)
        return
    if tag == "span":
        seg = _el("seg", {"rend": source.get("class", "")})
        _append_children(source, seg, context)
        parent.append(seg)
        return
    if tag == "ins":
        raise ConversionError("unexpected non-Greek <ins> source markup")
    if tag in {"u", "s", "del", "sup", "sub"}:
        rend = {"u": "underline", "s": "strikethrough", "del": "deleted"}.get(tag)
        attrs = {"rend": rend} if rend else {"rend": tag}
        hi = _el("hi", attrs)
        _append_children(source, hi, context)
        parent.append(hi)
        return
    _append_children(source, parent, context)


def _paragraph_attrs(source: html.HtmlElement | etree._Element, paragraph_id: str) -> dict[str, str]:
    attrs = {"xml:id": paragraph_id}
    classes = set((source.get("class", "") or "").split())
    layout: set[str] = set()
    if "sectctr" in classes:
        layout.add("section-number")
    if classes.intersection({"signatureline1", "signatureline2", "signatureline3"}):
        layout.add("signature")
    layout.update(
        classes.intersection(
            {
                "center",
                "centersc",
                "indentsc",
                "indent2",
                "p2",
                "p3",
                "p4",
                "gap",
                "smallgap",
                "biggap",
            }
        )
    )
    if layout:
        attrs["rend"] = " ".join(sorted(layout))
    return attrs


def _render_paragraph(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> etree._Element:
    paragraph_id = context.paragraph_ids.get(_node_path(source))
    if paragraph_id is None:
        raise ConversionError("source paragraph was not assigned a deterministic ID")
    paragraph = _el("p", _paragraph_attrs(source, paragraph_id))
    _append_children(source, paragraph, context)
    if not _norm_node(paragraph):
        children = list(paragraph)
        if children and all(child.tag == _qname("pb") for child in children):
            for child in children:
                paragraph.remove(child)
                parent.append(child)
            return paragraph
        if not children:
            return paragraph
    parent.append(paragraph)
    return paragraph


def _render_heading(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
    *,
    heading_type: str | None = None,
) -> etree._Element:
    if parent.tag == _qname("div") and any(
        child.tag != _qname("head") for child in parent
    ):
        rend = "heading" if heading_type is None else f"heading {heading_type}"
        paragraph = _el("p", {"rend": rend})
        _append_children(source, paragraph, context)
        parent.append(paragraph)
        return paragraph
    attrs = {"type": heading_type} if heading_type else None
    head = _el("head", attrs)
    _append_children(source, head, context)
    parent.append(head)
    return head


def _render_table(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> etree._Element:
    attrs = {"type": "contents"} if source.get("data-summary") == "Table of Contents" else {}
    table = _el("table", attrs)
    if source.get("data-summary"):
        table.set("n", source.get("data-summary"))
    _append_children(source, table, context)
    parent.append(table)
    return table


def _render_block(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    tag = source.tag
    if tag == "p":
        _render_paragraph(source, parent, context)
        return
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        _render_heading(source, parent, context)
        return
    if tag == "table":
        _render_table(source, parent, context)
        return
    if tag in {"tbody"}:
        _append_children(source, parent, context)
        return
    if tag == "tr":
        row = _el("row")
        _append_children(source, row, context)
        parent.append(row)
        return
    if tag in {"td", "th"}:
        attrs = {"role": "label"} if tag == "th" else {}
        if source.get("class"):
            attrs["rend"] = source.get("class")
        cell = _el("cell", attrs)
        _append_children(source, cell, context)
        parent.append(cell)
        return
    if tag in {"ul", "ol"}:
        list_node = _el("list", {"type": "ordered" if tag == "ol" else "unordered"})
        _append_children(source, list_node, context)
        parent.append(list_node)
        return
    if tag == "li":
        item = _el("item")
        _append_children(source, item, context)
        parent.append(item)
        return
    if tag == "hr":
        parent.append(_el("milestone", {"unit": "separator", "rend": "horizontal-rule"}))
        return
    if tag == "div" and _has_class(source, "blockquot"):
        quote = _el("quote", {"rend": "blockquot"})
        _append_children(source, quote, context)
        parent.append(quote)
        return
    if tag == "blockquote":
        quote = _el("quote", {"rend": "blockquote"})
        _append_children(source, quote, context)
        parent.append(quote)
        return
    if tag == "div":
        attrs = {"type": "source-div"}
        if source.get("class"):
            attrs["rend"] = source.get("class")
        div = _el("div", attrs)
        _append_children(source, div, context)
        parent.append(div)
        return
    if tag == "pre":
        if _norm_node(source):
            ab = _el("ab")
            _append_children(source, ab, context)
            parent.append(ab)
        return
    _render_inline(source, parent, context)


def _render_any(
    source: html.HtmlElement | etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    if source.tag in {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "tbody",
        "tr",
        "td",
        "th",
        "ul",
        "ol",
        "li",
        "hr",
        "blockquote",
        "pre",
    } or (source.tag == "div" and not _has_class(source, "footnote")):
        _render_block(source, parent, context)
    else:
        _render_inline(source, parent, context)


def _render_notebox(
    source: html.HtmlElement,
    parent: etree._Element,
    context: _Context,
    *,
    subtype: str,
) -> etree._Element:
    box = _el("div", {"type": "transcribers-notes", "subtype": subtype})
    _append_text(box, source.text)
    for child in source:
        if child.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            _render_heading(child, box, context)
        else:
            _render_any(child, box, context)
        _append_source_tail(child, box)
    parent.append(box)
    return box


def _is_footnote_heading(node: html.HtmlElement | etree._Element) -> bool:
    return node.tag == "h3" and _heading_text(node).upper() == "FOOTNOTES:"


def _collect_footnote_groups(
    children: list[html.HtmlElement],
) -> list[list[html.HtmlElement]]:
    groups: list[list[html.HtmlElement]] = []
    index = 0
    while index < len(children):
        if not _is_footnote_heading(children[index]):
            index += 1
            continue
        group: list[html.HtmlElement] = []
        index += 1
        while index < len(children) and _has_class(children[index], "footnote"):
            group.append(children[index])
            index += 1
        groups.append(group)
    return groups


def _footnote_group_map(
    children: list[html.HtmlElement],
    groups: list[list[html.HtmlElement]],
) -> dict[str, tuple[int, list[html.HtmlElement]]]:
    """Associate each retained FOOTNOTES heading with its source group."""

    mapping: dict[str, tuple[int, list[html.HtmlElement]]] = {}
    group_number = 0
    for node in children:
        if not _is_footnote_heading(node):
            continue
        if group_number >= len(groups):
            raise ConversionError("source footnote heading has no collected group")
        mapping[_node_path(node)] = (group_number + 1, groups[group_number])
        group_number += 1
    if group_number != len(groups):
        raise ConversionError("collected source footnote group has no heading")
    return mapping


def _render_footnote_group(
    source_heading: html.HtmlElement,
    source_notes: list[html.HtmlElement],
    parent: etree._Element,
    number: int,
    context: _Context,
) -> etree._Element:
    """Render one Gutenberg footnote group at its source position."""

    group_div = _el("div", {"type": "footnote-group", "n": str(number)})
    _render_heading(source_heading, group_div, context)
    _append_source_tail(source_heading, group_div)
    for source in source_notes:
        _render_note(source, group_div, context)
        _append_source_tail(source, group_div)
    parent.append(group_div)
    return group_div


def _render_note(
    source: html.HtmlElement,
    parent: etree._Element,
    context: _Context,
) -> None:
    source_paragraphs = source.xpath("./p")
    if len(source_paragraphs) != 1:
        raise ConversionError("footnote body must contain exactly one paragraph")
    paragraph = source_paragraphs[0]
    source_anchor_nodes = paragraph.xpath("./a[@id]")
    if len(source_anchor_nodes) != 1:
        raise ConversionError("footnote body lost its source ID anchor")
    source_id = source_anchor_nodes[0].get("id")
    if source_id not in context.note_ids:
        raise ConversionError("footnote body source ID is not in the retained census")
    return_links = paragraph.xpath("./a[starts-with(@href, '#FNanchor_')]")
    if len(return_links) != 1:
        raise ConversionError("footnote body must contain one return link")
    return_id = return_links[0].get("href", "")[1:]

    label_spans = return_links[0].xpath(".//span[contains(concat(' ', normalize-space(@class), ' '), ' label ')]")
    if len(label_spans) != 1:
        raise ConversionError("footnote return link must carry one visible label")
    note = _el(
        "note",
        {
            "xml:id": context.note_ids[source_id],
            "place": "end",
            "n": _norm_node(label_spans[0]),
            "corresp": (
                f"{SOURCE_HTML_URL}#{source_id} "
                f"{SOURCE_HTML_URL}#{return_id}"
            ),
        },
    )
    label = _el("label")
    _append_children(label_spans[0], label, context)
    note.append(label)

    paragraph_id = context.paragraph_ids.get(_node_path(paragraph))
    if paragraph_id is None:
        raise ConversionError("footnote paragraph was not assigned a deterministic ID")
    out_paragraph = _el("p", _paragraph_attrs(paragraph, paragraph_id))
    if paragraph.text:
        _append_text(out_paragraph, paragraph.text)
    for child in paragraph:
        if child is source_anchor_nodes[0] or child is return_links[0]:
            pass
        else:
            _render_any(child, out_paragraph, context)
        if child.tail:
            _append_text(out_paragraph, child.tail)
    note.append(out_paragraph)
    parent.append(note)


def _render_front(
    front: etree._Element,
    nodes: list[html.HtmlElement],
    context: _Context,
    footnote_groups: Mapping[str, tuple[int, list[html.HtmlElement]]],
) -> None:
    title_page: etree._Element | None = None
    dedication: etree._Element | None = None
    preface: etree._Element | None = None
    advertisement: etree._Element | None = None
    contents: etree._Element | None = None
    current: etree._Element | None = None

    def ensure_title_page() -> etree._Element:
        nonlocal title_page
        if title_page is None:
            title_page = _el("div", {"type": "title-page"})
            front.append(title_page)
        return title_page

    for node in nodes:
        if node.tag in {"header", "footer"} and _has_class(node, "pg-boilerplate"):
            continue
        if _is_footnote_heading(node):
            group_info = footnote_groups.get(_node_path(node))
            if group_info is None:
                raise ConversionError("front footnote heading is not in the retained group map")
            _render_footnote_group(node, group_info[1], front, group_info[0], context)
            continue
        if _has_class(node, "footnote"):
            continue
        if node.tag == "div" and _has_class(node, "notebox"):
            _render_notebox(node, front, context, subtype="front")
            _append_source_tail(node, front)
            current = None
            continue
        if node.tag == "h1":
            current = ensure_title_page()
            _render_heading(node, current, context, heading_type="title")
            _append_source_tail(node, current)
            continue
        if node.tag == "h2":
            heading = _heading_text(node)
            if heading.startswith("PREFACE TO THE EDITION"):
                preface = _el("div", {"type": "preface", "n": "1878"})
                front.append(preface)
                current = preface
            elif heading.startswith("ADVERTISEMENT TO THE FIRST EDITION"):
                advertisement = _el("div", {"type": "advertisement"})
                front.append(advertisement)
                current = advertisement
            elif heading == "CONTENTS.":
                contents = _el("div", {"type": "contents"})
                front.append(contents)
                current = contents
            else:
                current = ensure_title_page()
            _render_heading(node, current, context)
            _append_source_tail(node, current)
            continue
        if node.tag == "p" and _norm_node(node) == "TO THE":
            dedication = _el("div", {"type": "dedication"})
            front.append(dedication)
            current = dedication
            _render_block(node, current, context)
            _append_source_tail(node, current)
            continue
        if node.tag == "p" and _norm_node(node) == "POSTSCRIPT.":
            if advertisement is None:
                advertisement = _el("div", {"type": "advertisement"})
                front.append(advertisement)
            postscript = _el("div", {"type": "postscript"})
            advertisement.append(postscript)
            current = postscript
            _render_heading(node, current, context)
            _append_source_tail(node, current)
            continue
        if (
            node.tag in {"p", "pre"}
            and not _norm_node(node)
            and not node.xpath(
                ".//span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')]"
            )
        ):
            continue
        target = current if current is not None else ensure_title_page()
        if node.tag == "table" and contents is None:
            contents = _el("div", {"type": "contents"})
            front.append(contents)
            target = contents
        _render_block(node, target, context)
        _append_source_tail(node, target)


def _roman_heading_number(text: str) -> str | None:
    match = re.match(r"SECTION\s+([IVXLCDM]+)\.?$", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _subsection_number(text: str) -> str | None:
    match = re.match(r"§\s*(\d+)\.", text)
    return match.group(1) if match else None


def _render_body(
    body: etree._Element,
    nodes: list[html.HtmlElement],
    context: _Context,
    footnote_groups: Mapping[str, tuple[int, list[html.HtmlElement]]],
) -> None:
    current_part: etree._Element | None = None
    current_chapter: etree._Element | None = None
    current_introduction: etree._Element | None = None
    current_section: etree._Element | None = None
    current_subsection: etree._Element | None = None
    section_count_by_chapter: Counter[str] = Counter()

    for node in nodes:
        if _is_footnote_heading(node):
            group_info = footnote_groups.get(_node_path(node))
            if group_info is None:
                raise ConversionError("body footnote heading is not in the retained group map")
            if current_subsection is not None:
                target = current_subsection
            elif current_section is not None:
                target = current_section
            elif current_introduction is not None:
                target = current_introduction
            elif current_chapter is not None:
                target = current_chapter
            elif current_part is not None:
                target = current_part
            else:
                target = body
            _render_footnote_group(node, group_info[1], target, group_info[0], context)
            continue
        if _has_class(node, "footnote"):
            continue
        if node.tag == "h2":
            heading = _heading_text(node)
            if heading in {"PART I.", "PART II."}:
                current_part = _el("div", {"type": "part", "n": heading[5]})
                body.append(current_part)
                _render_heading(node, current_part, context)
                current_chapter = None
                current_introduction = None
                current_section = None
                current_subsection = None
                _append_source_tail(node, current_part)
                continue
            if heading == "INTRODUCTION.":
                if current_part is None:
                    raise ConversionError("introduction appears before Part I")
                current_introduction = _el("div", {"type": "introduction"})
                current_part.append(current_introduction)
                _render_heading(node, current_introduction, context)
                current_chapter = None
                current_section = None
                current_subsection = None
                _append_source_tail(node, current_introduction)
                continue
            if heading.startswith("CHAPTER "):
                if current_part is None:
                    raise ConversionError("chapter appears before a part")
                roman = heading.removeprefix("CHAPTER ").rstrip(".").strip()
                current_chapter = _el("div", {"type": "chapter", "n": roman})
                current_part.append(current_chapter)
                _render_heading(node, current_chapter, context)
                current_introduction = None
                current_section = None
                current_subsection = None
                section_count_by_chapter[roman] = 0
                _append_source_tail(node, current_chapter)
                continue
            raise ConversionError(f"unexpected body h2 heading: {heading}")
        if node.tag == "h3":
            target = current_chapter if current_chapter is not None else current_part
            if target is None:
                raise ConversionError("body subtitle appears before a part")
            _render_heading(node, target, context, heading_type="subtitle")
            _append_source_tail(node, target)
            continue
        if node.tag == "h4":
            heading = _heading_text(node)
            subsection_number = _subsection_number(heading)
            if subsection_number is not None:
                if current_section is not None:
                    target = current_section
                elif current_chapter is not None:
                    target = current_chapter
                else:
                    target = current_part
                if target is None:
                    raise ConversionError("subsection appears before a chapter")
                current_subsection = _el(
                    "div", {"type": "subsection", "n": subsection_number}
                )
                target.append(current_subsection)
                _render_heading(node, current_subsection, context)
            else:
                target = current_chapter if current_chapter is not None else current_part
                if target is None:
                    raise ConversionError("section appears before a chapter")
                chapter_key = current_chapter.get("n", "_") if current_chapter is not None else "_"
                section_count_by_chapter[chapter_key] += 1
                attrs = {"type": "section"}
                number = _roman_heading_number(heading)
                if number:
                    attrs["n"] = number
                current_section = _el("div", attrs)
                target.append(current_section)
                _render_heading(node, current_section, context)
                current_subsection = None
            _append_source_tail(
                node,
                current_subsection if current_subsection is not None else current_section,
            )
            continue
        if node.tag == "h5":
            if current_subsection is not None:
                target = current_subsection
            elif current_section is not None:
                target = current_section
            elif current_chapter is not None:
                target = current_chapter
            else:
                target = current_part
            if target is None:
                raise ConversionError("subheading appears before a chapter")
            _render_heading(node, target, context, heading_type="subtitle")
            _append_source_tail(node, target)
            continue
        if current_subsection is not None:
            target = current_subsection
        elif current_section is not None:
            target = current_section
        elif current_introduction is not None:
            target = current_introduction
        elif current_chapter is not None:
            target = current_chapter
        elif current_part is not None:
            target = current_part
        else:
            target = body
        _render_block(node, target, context)
        _append_source_tail(node, target)


def _render_back(
    back: etree._Element,
    final_notes: html.HtmlElement | None,
    context: _Context,
) -> None:
    if final_notes is not None:
        _render_notebox(final_notes, back, context, subtype="final")


def _header() -> etree._Element:
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", {"type": "main"}, "An Essay on the Development of Christian Doctrine"))
    title_stmt.append(_el("author", text="John Henry Newman"))
    file_desc.append(title_stmt)

    publication_stmt = _el("publicationStmt")
    publication_stmt.append(_el("publisher", text="Open Christian Data"))
    publication_stmt.append(_el("date", {"when": "2026-08-31"}, "2026"))
    availability = _el("availability", {"status": "unknown"})
    licence = _el(
        "licence",
        {"target": "https://www.gutenberg.org/ebooks/35110"},
    )
    licence.append(
        _el(
            "p",
            text=(
                "Historical text retained from Project Gutenberg eBook 35110; "
                "see the source-local README for the Project Gutenberg credit and terms."
            ),
        )
    )
    availability.append(licence)
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)

    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("title", text="An Essay on the Development of Christian Doctrine"))
    bibl.append(_el("edition", text="Sixth edition"))
    bibl.append(_el("author", text="John Henry Newman"))
    bibl.append(_el("date", {"when": "1878"}, "1878"))
    bibl.append(_el("idno", {"type": "project-gutenberg"}, "35110"))
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
                "represented by pb milestones; Gutenberg redistribution boilerplate is excluded."
            ),
        )
    )
    encoding_desc.append(project_desc)
    header.append(encoding_desc)
    revision = _el("revisionDesc")
    revision.append(
        _el(
            "change",
            {"when": "2026-08-31"},
            "Initial retained-source candidate conversion.",
        )
    )
    header.append(revision)
    return header


def _tei_visible_text(tree: etree._ElementTree) -> str:
    text_nodes = tree.xpath("/t:TEI/t:text", namespaces=NS)
    if len(text_nodes) != 1:
        raise ConversionError("TEI must contain exactly one text element")
    return " ".join("".join(text_nodes[0].itertext()).split())


def _tei_counts(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    if root.tag != _qname("TEI"):
        raise ConversionError("TEI root is not a TEI P5 document")
    if len(root.xpath("./t:teiHeader", namespaces=NS)) != 1:
        raise ConversionError("TEI header is missing")
    if len(root.xpath("./t:text", namespaces=NS)) != 1:
        raise ConversionError("TEI text is missing")

    ids = root.xpath("//@xml:id", namespaces=NS)
    if len(ids) != len(set(ids)):
        raise ConversionError("TEI xml:id values are not unique")
    id_set = set(ids)
    refs = root.xpath("//t:ref[@type='note']", namespaces=NS)
    if len(refs) != EXPECTED_NOTE_REF_COUNT:
        raise ConversionError(
            f"note reference count mismatch: expected {EXPECTED_NOTE_REF_COUNT}, got {len(refs)}"
        )
    notes = root.xpath("//t:note[@place='end']", namespaces=NS)
    if len(notes) != EXPECTED_NOTE_COUNT:
        raise ConversionError(
            f"note body count mismatch: expected {EXPECTED_NOTE_COUNT}, got {len(notes)}"
        )
    for ref in root.xpath("//t:ref[@target]", namespaces=NS):
        target = ref.get("target", "")
        if target.startswith("#") and target[1:] not in id_set:
            raise ConversionError(f"unresolved TEI link target: {target}")
    page_nodes = root.xpath("//t:pb", namespaces=NS)
    if len(page_nodes) != EXPECTED_PAGE_COUNT:
        raise ConversionError(
            f"printed page milestone count mismatch: expected {EXPECTED_PAGE_COUNT}, got {len(page_nodes)}"
        )
    greek = root.xpath(
        "//t:foreign[@xml:lang='grc' and @ana='urn:ocd:greek-transliteration']",
        namespaces=NS,
    )
    if len(greek) != EXPECTED_GREEK_COUNT or any(
        not node.get("n") for node in greek
    ):
        raise ConversionError("Greek/transliteration span accounting failed")
    if len(root.xpath("//t:hi[@rend='italic']", namespaces=NS)) != EXPECTED_ITALIC_COUNT:
        raise ConversionError("italic source-mark count changed")
    if len(root.xpath("//t:hi[@rend='smallcaps']", namespaces=NS)) != EXPECTED_SMALLCAPS_COUNT:
        raise ConversionError("small-caps source-mark count changed")
    counts: dict[str, object] = {
        "paragraph_count": len(root.xpath("//t:p", namespaces=NS)),
        "text_paragraph_count": len(
            root.xpath("/t:TEI/t:text//t:p", namespaces=NS)
        ),
        "printed_page_anchor_count": len(page_nodes),
        "note_reference_count": len(refs),
        "note_body_count": len(notes),
        "note_target_unique_count": len(
            {ref.get("target", "").removeprefix("#") for ref in refs}
        ),
        "greek_span_count": len(greek),
        "italic_count": len(root.xpath("//t:hi[@rend='italic']", namespaces=NS)),
        "smallcaps_count": len(root.xpath("//t:hi[@rend='smallcaps']", namespaces=NS)),
        "part_count": len(root.xpath("//t:body/t:div[@type='part']", namespaces=NS)),
        "chapter_count": len(root.xpath("//t:body//t:div[@type='chapter']", namespaces=NS)),
        "section_count": len(root.xpath("//t:body//t:div[@type='section']", namespaces=NS)),
        "subsection_count": len(root.xpath("//t:body//t:div[@type='subsection']", namespaces=NS)),
        "contents_table_count": len(root.xpath("//t:table[@type='contents']", namespaces=NS)),
        "contents_row_count": len(root.xpath("//t:table[@type='contents']/t:row", namespaces=NS)),
        "quote_count": len(root.xpath("//t:quote", namespaces=NS)),
        "list_count": len(root.xpath("//t:list", namespaces=NS)),
        "signature_count": len(
            root.xpath(
                "//t:p[contains(concat(' ', normalize-space(@rend), ' '), ' signature ')]",
                namespaces=NS,
            )
        ),
        "footnote_group_count": len(root.xpath("//t:div[@type='footnote-group']", namespaces=NS)),
        "tei_visible_text_sha256": _sha256(_tei_visible_text(tree).encode("utf-8")),
    }
    if counts["part_count"] != EXPECTED_PART_COUNT:
        raise ConversionError("TEI part count changed")
    if counts["chapter_count"] != EXPECTED_CHAPTER_COUNT:
        raise ConversionError("TEI chapter count changed")
    if counts["section_count"] != EXPECTED_SECTION_COUNT:
        raise ConversionError("TEI section count changed")
    if counts["subsection_count"] != EXPECTED_SUBSECTION_COUNT:
        raise ConversionError("TEI subsection count changed")
    if counts["contents_table_count"] != 1:
        raise ConversionError("contents table is missing")
    if counts["footnote_group_count"] != EXPECTED_FOOTNOTE_GROUP_COUNT:
        raise ConversionError("TEI footnote-group count changed")
    return counts


def validate_tei(value: etree._ElementTree | etree._Element | bytes | Path) -> dict[str, object]:
    """Validate TEI P5 plus source-specific/link invariants and return counts."""

    if isinstance(value, Path):
        tree = etree.parse(str(value))
    elif isinstance(value, bytes):
        tree = etree.ElementTree(etree.fromstring(value))
    elif isinstance(value, etree._ElementTree):
        tree = value
    elif isinstance(value, etree._Element):
        tree = etree.ElementTree(value)
    else:  # pragma: no cover - defensive API guard
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


@lru_cache(maxsize=1)
def _tei_relaxng() -> etree.RelaxNG:
    """Load the vendored TEI P5 grammar once for this source-local route."""

    return etree.RelaxNG(etree.parse(str(TEI_RNG_PATH)))


def _load_retained_source(
    source_logical_path: str,
    repository_root: Path,
) -> tuple[bytes, html.HtmlElement, dict[str, object], list[html.HtmlElement]]:
    if source_logical_path != SOURCE_LOGICAL_PATH:
        raise ConversionError(
            f"this source-local route accepts only {SOURCE_LOGICAL_PATH}, got {source_logical_path}"
        )
    try:
        archive_path = resolve_repo_path(repository_root, source_logical_path)
    except StorageTopologyError as exc:
        raise ConversionError(f"cannot resolve retained source logical path: {exc}") from exc
    if not archive_path.is_file():
        raise ConversionError(f"retained source archive does not exist: {source_logical_path}")
    archive_bytes = archive_path.read_bytes()
    if _sha256(archive_bytes) != SOURCE_ARCHIVE_SHA256:
        raise ConversionError("retained source archive SHA-256 does not match the authorized release")
    try:
        with ZipFile(archive_path) as archive:
            members = archive.namelist()
            if sorted(members) != sorted([SOURCE_HTML_MEMBER, SOURCE_COVER_MEMBER]):
                raise ConversionError("retained source archive members changed")
            html_bytes = archive.read(SOURCE_HTML_MEMBER)
    except BadZipFile as exc:
        raise ConversionError("retained source archive is not a valid ZIP") from exc
    if _sha256(html_bytes) != SOURCE_HTML_SHA256:
        raise ConversionError("retained Gutenberg HTML SHA-256 does not match the authorized release")
    root = html.fromstring(html_bytes, parser=html.HTMLParser(encoding="utf-8"))
    census = _source_census(root)
    body = root.xpath("//body")[0]
    return html_bytes, body, census, list(body.xpath("./*"))


def _build_document(
    body_source: html.HtmlElement,
    census: dict[str, object],
    children: list[html.HtmlElement],
) -> tuple[etree._ElementTree, dict[str, object]]:
    context = _prepare_context(body_source, census)
    part_i_index = next(
        (
            index
            for index, node in enumerate(children)
            if node.tag == "h2" and _heading_text(node) == "PART I."
        ),
        None,
    )
    if part_i_index is None or part_i_index == 0:
        raise ConversionError("retained source has no usable Part I boundary")
    if _norm_node(children[part_i_index - 1]) != "[Pg 1]":
        raise ConversionError("Part I boundary is not preceded by the retained printed page 1 anchor")
    final_notes_index = next(
        (
            index
            for index, node in enumerate(children)
            if node.tag == "div"
            and _has_class(node, "notebox")
            and bool(node.xpath(".//h2[.//a[@id='TN'] or contains(., \"TRANSCRIBER'S NOTES\")]"))
        ),
        None,
    )
    if final_notes_index is None:
        raise ConversionError("retained final Transcriber's Notes block is missing")
    groups = _collect_footnote_groups(children)
    if len(groups) != EXPECTED_FOOTNOTE_GROUP_COUNT:
        raise ConversionError("retained footnote groups cannot be reconstructed")
    footnote_groups = _footnote_group_map(children, groups)

    root = _el("TEI", {"xml:lang": "en"}, nsmap={None: TEI_NS})
    root.append(_header())
    text = _el("text")
    front = _el("front")
    body = _el("body")
    back = _el("back")
    text.extend([front, body, back])
    root.append(text)

    _render_front(front, children[: part_i_index - 1], context, footnote_groups)
    _render_body(
        body,
        children[part_i_index - 1 : final_notes_index],
        context,
        footnote_groups,
    )
    _render_back(back, children[final_notes_index], context)

    if context.reference_number != EXPECTED_NOTE_REF_COUNT:
        raise ConversionError("generated note reference count does not match source census")
    if context.greek_count != EXPECTED_GREEK_COUNT:
        raise ConversionError("generated Greek span count does not match source census")

    tree = etree.ElementTree(root)
    tei_counts = validate_tei(tree)
    source_visible = str(census["source_visible_text"])
    tei_visible = _tei_visible_text(tree)
    if source_visible != tei_visible:
        raise ConversionError(
            "visible source text does not match TEI text after structural representation"
        )
    accounting: dict[str, object] = {
        "source_logical_path": SOURCE_LOGICAL_PATH,
        "archive_sha256": SOURCE_ARCHIVE_SHA256,
        "html_member": SOURCE_HTML_MEMBER,
        "html_sha256": SOURCE_HTML_SHA256,
        "source_paragraph_count": census["source_paragraph_count"],
        "included_source_paragraph_count": census["included_source_paragraph_count"],
        "source_empty_layout_paragraph_count": census[
            "source_empty_layout_paragraph_count"
        ],
        "source_page_only_paragraph_count": census[
            "source_page_only_paragraph_count"
        ],
        "source_ins_greek_count": census["source_ins_greek_count"],
        "source_italic_count": census["source_italic_count"],
        "source_smallcaps_count": census["source_smallcaps_count"],
        "source_table_row_count": census["source_table_row_count"],
        "source_block_quote_count": census["source_block_quote_count"],
        "source_list_count": census["source_list_count"],
        "source_visible_text_sha256": _sha256(source_visible.encode("utf-8")),
        "tei_p5_relaxng_valid": True,
        "tei_relaxng_path": TEI_RNG_PATH.relative_to(
            Path(__file__).resolve().parents[2]
        ).as_posix(),
        "tei_relaxng_sha256": _sha256(TEI_RNG_PATH.read_bytes()),
        **tei_counts,
        "extra_reference_condition": {
            "source_target": EXPECTED_DUPLICATE_NOTE_SOURCE_ID,
            "reference_count": 2,
            "unique_note_body_count": 1,
        },
        "ins_semantics": "all 26 source <ins class=greek> spans are Greek text with title transliterations; typographical corrections remain in the final Transcriber's Notes",
        "excluded_boilerplate": {
            "project_gutenberg_header": "excluded as redistribution boilerplate; edition metadata and credit are retained in teiHeader and the source-local README",
            "project_gutenberg_footer": "excluded as redistribution boilerplate; license/credit obligation is documented in the source-local README",
            "project_gutenberg_footer_lists": 1,
            "empty_layout_pre_elements": 2,
            "empty_layout_source_paragraphs": census[
                "source_empty_layout_paragraph_count"
            ],
            "page_only_source_paragraphs_unwrapped_to_pb": census[
                "source_page_only_paragraph_count"
            ],
        },
    }
    return tree, accounting


def convert_source(
    source_logical_path: str,
    output_path: Path,
    *,
    repository_root: Path | None = None,
) -> ConversionResult:
    """Convert one authorized logical retained-source path to a TEI document."""

    root = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    _, body, census, children = _load_retained_source(source_logical_path, root)
    tree, accounting = _build_document(body, census, children)
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
    parser.add_argument("source_logical_path", help="normalized repository logical path to the retained ZIP")
    parser.add_argument("output_path", type=Path, help="path for the generated TEI P5 XML")
    parser.add_argument(
        "--accounting",
        action="store_true",
        help="print compact JSON accounting after writing the TEI",
    )
    parser.add_argument(
        "--accounting-output",
        type=Path,
        help="write deterministic, formatted JSON accounting to this path",
    )
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
            json.dumps(
                result.accounting,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI test
    raise SystemExit(_main())
