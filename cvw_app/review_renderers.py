"""Typed, code-native artifact renderers for the Corpus Review Viewer."""

from __future__ import annotations

import hashlib
from html import escape as _html_escape
from html.parser import HTMLParser
import io
import json
import posixpath
import re
import struct
from typing import Any, Callable
from xml.etree import ElementTree
import zipfile
import zlib

from cvw_app.tei_inline import page_break_label

from cvw_app.renderer_nodes import (
    RendererError as RendererError,
    MAX_STRUCTURE_LOCATION_SCALARS as MAX_STRUCTURE_LOCATION_SCALARS,
    MAX_STRUCTURE_LABEL_SCALARS as MAX_STRUCTURE_LABEL_SCALARS,
    MAX_STRUCTURE_CONTEXT_SCALARS as MAX_STRUCTURE_CONTEXT_SCALARS,
    MAX_PAGE_SCALARS as MAX_PAGE_SCALARS,
    MAX_PAGE_SERIALIZED_BYTES as MAX_PAGE_SERIALIZED_BYTES,
    MAX_TABLE_COLSPAN as MAX_TABLE_COLSPAN,
    MAX_TABLE_ROWSPAN as MAX_TABLE_ROWSPAN,
    _TABLE_ASCII_WHITESPACE as _TABLE_ASCII_WHITESPACE,
    _TABLE_ASCII_DIGITS as _TABLE_ASCII_DIGITS,
    ECMASCRIPT_TRIM_CODEPOINTS as ECMASCRIPT_TRIM_CODEPOINTS,
    COLLAPSIBLE_WHITESPACE as COLLAPSIBLE_WHITESPACE,
    UNICODE_SURROGATES as UNICODE_SURROGATES,
    project_visible_text as project_visible_text,
    is_route_valid_scalar_text as is_route_valid_scalar_text,
    _StructureLocations as _StructureLocations,
    _node as _node,
    _parse_table_span as _parse_table_span,
    _html_table_span as _html_table_span,
    _serialized_json_bytes as _serialized_json_bytes,
    _node_text as _node_text,
    _nodes_text as _nodes_text,
    _is_unicode_scalar_text as _is_unicode_scalar_text,
    _bounded_visible_text as _bounded_visible_text,
    bounded_visible_text as bounded_visible_text,
    _DOCUMENT_NODE_TYPES as _DOCUMENT_NODE_TYPES,
    PRESENTATION_KINDS as PRESENTATION_KINDS,
    BINARY_PRESENTATION_KINDS as BINARY_PRESENTATION_KINDS,
    CONTEXT_PRESENTATION_KINDS as CONTEXT_PRESENTATION_KINDS,
    _DOCUMENT_NODE_FIELDS as _DOCUMENT_NODE_FIELDS,
    _ROOT_NODE_TYPES as _ROOT_NODE_TYPES,
    _CONTEXT_ROOT_NODE_TYPES as _CONTEXT_ROOT_NODE_TYPES,
    _CHILD_NODE_TYPES as _CHILD_NODE_TYPES,
    _validate_document_nodes as _validate_document_nodes,
    _validate_renderer_output as _validate_renderer_output,
    _finalize_structure as _finalize_structure,
    _node_contains_location as _node_contains_location,
    _SPLITTABLE_ROOT_TYPES as _SPLITTABLE_ROOT_TYPES,
    _SPLITTABLE_VISIBLE_LEAF_TYPES as _SPLITTABLE_VISIBLE_LEAF_TYPES,
    _split_visible_leaf_node as _split_visible_leaf_node,
    _segment_locations as _segment_locations,
    _build_segments_and_pages as _build_segments_and_pages,
    _wrapped_pages as _wrapped_pages,
    _heading_contexts as _heading_contexts,
)
from cvw_app.renderer_nodes import (
    _local_name as _local_name,
    _TEI_XML_ID as _TEI_XML_ID,
    _ENTITY_DECLARATION as _ENTITY_DECLARATION,
    _INTERNAL_DTD_SUBSET as _INTERNAL_DTD_SUBSET,
    _TEI_SUPPRESSED as _TEI_SUPPRESSED,
    _TEI_TEXT_BLOCKS as _TEI_TEXT_BLOCKS,
    _TEI_DICTIONARY_ENTRY_TYPES as _TEI_DICTIONARY_ENTRY_TYPES,
    _TEI_LEAF_HANDLED as _TEI_LEAF_HANDLED,
)
from cvw_app.tei_renderer import (
    render_tei as render_tei,
)

from cvw_app.tei_inline import normalize_runs
from cvw_app.json_books import render_json_book


class _SafeHtmlNodes(HTMLParser):
    block_tags = {
        "h1": "heading",
        "h2": "heading",
        "h3": "heading",
        "h4": "heading",
        "h5": "heading",
        "h6": "heading",
        "p": "paragraph",
        "li": "list-item",
        "blockquote": "blockquote",
        "pre": "preformatted",
        # Retained sources include legacy HTML that uses these containers as
        # visible blocks instead of wrapping their text in a modern p element.
        "address": "paragraph",
        "article": "paragraph",
        "center": "paragraph",
        "dd": "paragraph",
        "div": "paragraph",
        "dt": "paragraph",
        "figcaption": "paragraph",
        "section": "paragraph",
        # ThML uses these source-native blocks around readable prose.
        "l": "paragraph",
        "note": "blockquote",
        "scripcom": "blockquote",
    }
    suppressed_tags = {
        "head",
        "title",
        "script",
        "style",
        "template",
        "iframe",
        "object",
        "embed",
        "form",
        "svg",
        "math",
        "audio",
        "video",
        "source",
    }

    def __init__(self, *, native_divisions: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.native_divisions = native_divisions
        self.nodes: list[dict[str, Any]] = []
        self.outline: list[dict[str, Any]] = []
        self._locations = _StructureLocations()
        self._suppressed = 0
        self._site_nav_lists = 0
        self._marks = []
        self._runs = {}
        self._lists = []
        self._active: (
            tuple[str, int | None, str | None, list[str], str | None] | None
        ) = None
        self._loose: list[str] = []
        self._table_rows: list[dict[str, Any]] | None = None
        self._table_row: list[dict[str, Any]] | None = None
        self._table_cell: (
            tuple[str, str | None, int | None, int | None, list[str]] | None
        ) = None
        self._table_has_explicit_cell = False

    def _decorate(self, node, parts):
        runs = normalize_runs(self._runs.pop(id(parts), []))
        if (
            any(run["marks"] for run in runs)
            and "".join(run["text"] for run in runs) == node["text"]
        ):
            node["inline"] = runs

    def _finish_item(self):
        self._finish_active()
        self._finish_loose()
        if self.nodes:
            for node in self.nodes:
                if node["type"] == "list-item":
                    node["type"] = "paragraph"
            self._lists[-1]["group"]["children"].append(
                _node("list-item", "", children=self.nodes)
            )
            self.nodes = []

    def _finish_active(self) -> None:
        if self._active is None:
            return
        node_type, level, location, parts, native_label = self._active
        raw = "".join(parts)
        # A pre element keeps its exact bytes, minus the single leading newline the
        # HTML parsing rules drop, because the browser also renders them exactly.
        text = (
            raw.removeprefix("\n")
            if node_type == "preformatted"
            else project_visible_text(raw)
        )
        if text.strip() or native_label is not None:
            if node_type == "heading":
                if native_label is not None:
                    native_label = project_visible_text(native_label)
                    if not native_label:
                        raise RendererError(
                            "ThML native division title must contain readable text"
                        )
                location = self._locations.allocate(location, len(self.outline) + 1)
                self.nodes.append(
                    _node(
                        "heading",
                        "" if native_label is not None else text,
                        level=level,
                        location=location,
                    )
                )
                self.outline.append(
                    {
                        "location": location,
                        "label": native_label if native_label is not None else text,
                        "level": level,
                    }
                )
            else:
                self.nodes.append(_node(node_type, text))
        if self.nodes and node_type != "preformatted":
            self._decorate(self.nodes[-1], parts)
        self._active = None

    def _finish_loose(self) -> None:
        text = project_visible_text("".join(self._loose))
        if text.strip():
            self.nodes.append(_node("paragraph", text))
            self._decorate(self.nodes[-1], self._loose)
        self._loose = []

    def _append_visible_text(self, text: str) -> None:
        parts = (
            self._table_cell[4]
            if self._table_cell is not None
            else self._active[3]
            if self._active is not None
            else self._loose
        )
        marks = sorted(set(mark for _, mark in self._marks))
        self._runs.setdefault(id(parts), []).append((text, marks))
        if self._table_cell is not None:
            self._table_cell[4].append(text)
        elif self._active is not None:
            self._active[3].append(text)
        else:
            self._loose.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._site_nav_lists:
            if tag == 'ul':
                self._site_nav_lists += 1
            return
        classes = next((value or '' for name,value in attrs if name.lower()=='class'),'').split()
        if tag == 'ul' and 'tnav' in classes and not self._suppressed:
            self._finish_active()
            self._finish_loose()
            self._site_nav_lists = 1
            return
        if tag in self.suppressed_tags:
            self._suppressed += 1
            return
        inline = {
            "em": "italic",
            "i": "italic",
            "strong": "bold",
            "b": "bold",
            "sup": "superscript",
            "sub": "subscript",
            "u": "underline",
        }
        if not self._suppressed and tag in inline:
            self._marks.append((tag, inline[tag]))
            return
        if not self._suppressed and self._table_rows is None and tag in {"ul", "ol"}:
            self._finish_active()
            self._finish_loose()
            group = _node("list", "", ordered=tag == "ol", children=[])
            start = next((value for name, value in attrs if name == "start"), None)
            if tag == "ol" and start is not None:
                if not re.fullmatch(r"-?[0-9]{1,6}", start):
                    raise RendererError("invalid ordered list start")
                group["start"] = int(start)
            parent = self.nodes
            parent.append(group)
            self._lists.append({"parent": parent, "group": group})
            self.nodes = []
            return
        if not self._suppressed and tag == "li" and self._lists:
            self._finish_item()
        if not self._suppressed and tag == "table" and self._table_rows is None:
            self._finish_active()
            self._finish_loose()
            self._table_rows = []
            self._table_has_explicit_cell = False
            return
        if not self._suppressed and self._table_rows is not None:
            if tag == "tr":
                self._table_row = []
            elif tag in {"th", "td"} and self._table_row is not None:
                self._table_has_explicit_cell = True
                scope = next(
                    (
                        value.lower()
                        for name, value in attrs
                        if name.lower() == "scope"
                        and value
                        and value.lower() in {"row", "col"}
                    ),
                    None,
                )
                colspan = _html_table_span(attrs, "colspan", MAX_TABLE_COLSPAN)
                rowspan = _html_table_span(attrs, "rowspan", MAX_TABLE_ROWSPAN)
                self._table_cell = (
                    "table-header" if tag == "th" else "table-cell",
                    scope,
                    colspan,
                    rowspan,
                    [],
                )
            return
        if self._suppressed:
            return
        if tag == "br":
            self._append_visible_text("\n")
            return
        if tag == "img":
            alternative = next(
                (value for name, value in attrs if name.lower() == "alt" and value),
                None,
            )
            if alternative:
                self._append_visible_text(alternative)
            return
        if tag not in self.block_tags:
            return
        # HTML permits omitted p end tags and historical sources commonly use a
        # new <P> token as the paragraph separator. Starting any visible block
        # therefore commits the previous block before opening the next one.
        self._finish_active()
        self._finish_loose()
        level = int(tag[1]) if tag.startswith("h") else None
        native_label = None
        if self.native_divisions:
            native_label = next(
                (
                    value
                    for name, value in attrs
                    if name.lower() == "data-cvw-native-label" and value is not None
                ),
                None,
            )
        location = next(
            (
                value
                for name, value in attrs
                if name.lower()
                == ("data-cvw-native-location" if native_label is not None else "id")
                and value
            ),
            None,
        )
        self._active = (self.block_tags[tag], level, location, [], native_label)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._site_nav_lists:
            if tag == 'ul':
                self._site_nav_lists -= 1
            return
        if tag in self.suppressed_tags:
            if self._suppressed:
                self._suppressed -= 1
            return
        if not self._suppressed and tag in {
            "em",
            "i",
            "strong",
            "b",
            "sup",
            "sub",
            "u",
        }:
            for index in range(len(self._marks) - 1, -1, -1):
                if self._marks[index][0] == tag:
                    del self._marks[index:]
                    break
            return
        if (
            not self._suppressed
            and tag in {"ul", "ol"}
            and self._lists
            and self._table_rows is None
        ):
            self._finish_item()
            self.nodes = self._lists.pop()["parent"]
            return
        if (
            not self._suppressed
            and tag == "li"
            and self._lists
            and self._table_rows is None
        ):
            self._finish_item()
            return
        if not self._suppressed and self._table_rows is not None:
            if (
                tag in {"th", "td"}
                and self._table_cell is not None
                and self._table_row is not None
            ):
                node_type, scope, colspan, rowspan, parts = self._table_cell
                text = project_visible_text("".join(parts))
                extra: dict[str, object] = {}
                if scope:
                    extra["scope"] = scope
                if colspan is not None:
                    extra["colspan"] = colspan
                if rowspan is not None:
                    extra["rowspan"] = rowspan
                self._table_row.append(_node(node_type, text, **extra))
                self._decorate(self._table_row[-1], parts)
                self._table_cell = None
            elif tag == "tr" and self._table_row is not None:
                all_headers = all(
                    cell["type"] == "table-header" for cell in self._table_row
                )
                for index, cell in enumerate(self._table_row):
                    if cell["type"] == "table-header" and "scope" not in cell:
                        cell["scope"] = "col" if all_headers or index > 0 else "row"
                self._table_rows.append(
                    _node("table-row", "", children=self._table_row)
                )
                self._table_row = None
            elif tag == "table":
                if self._table_rows and self._table_has_explicit_cell:
                    self.nodes.append(_node("table", "", children=self._table_rows))
                self._table_rows = None
                self._table_row = None
                self._table_cell = None
                self._table_has_explicit_cell = False
            return
        if (
            self._suppressed
            or not self._active
            or self.block_tags.get(tag) != self._active[0]
        ):
            return
        self._finish_active()

    def handle_data(self, data: str) -> None:
        if not self._suppressed and not self._site_nav_lists:
            self._append_visible_text(data)

    def close(self) -> None:
        super().close()
        while self._lists:
            self._finish_item()
            self.nodes = self._lists.pop()["parent"]
        self._finish_active()
        self._finish_loose()


def render_sanitized_html(media_type: str, exact: str) -> dict[str, Any]:
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise RendererError("sanitized-html requires HTML or XHTML media type")
    parser = _SafeHtmlNodes()
    try:
        parser.feed(exact)
        parser.close()
    except (AssertionError, ValueError) as error:
        raise RendererError(f"HTML artifact is malformed: {error}") from error
    if not parser.nodes:
        raise RendererError("HTML artifact has no readable allow-listed content")
    return _finalize_structure(
        "sanitized-html",
        parser.nodes,
        parser.outline,
        _heading_contexts(parser.nodes, parser.outline),
    )


_THML_DIVISION = re.compile(r"^div([1-9][0-9]*)$", re.IGNORECASE)


def _thml_has_readable_content(element: ElementTree.Element) -> bool:
    """Match the sanitizer's visible-content boundary for native markers."""
    tag = _local_name(element.tag).lower() if isinstance(element.tag, str) else ""
    if tag in _SafeHtmlNodes.suppressed_tags:
        return False
    if project_visible_text(element.text or ""):
        return True
    if tag == "img" and project_visible_text(element.attrib.get("alt", "")):
        return True
    for child in element:
        if _thml_has_readable_content(child):
            return True
        if project_visible_text(child.tail or ""):
            return True
    return False


def _thml_body_markup(element: ElementTree.Element) -> str:
    """Project ThML body markup while retaining native division metadata.

    The regular HTML sanitizer intentionally discards unknown XML element
    attributes. ThML's numbered divisions are the source-native work
    boundaries needed for navigation, so insert inert, empty heading markers
    for those divisions and leave every original readable child in source
    order. The marker carries only the native ``id`` and ``title`` metadata;
    it never supplies body text.
    """

    def serialize(node: ElementTree.Element) -> str:
        if not isinstance(node.tag, str):
            return ""
        division = _THML_DIVISION.fullmatch(_local_name(node.tag))
        if division:
            title = node.attrib.get("title")
            normalized_title = None if title is None else project_visible_text(title)
            inner = _html_escape(node.text or "")
            inner += "".join(
                serialize(child) + _html_escape(child.tail or "") for child in node
            )
            # A title is optional source metadata.  Keep an untitled division's
            # readable descendants in their original order and omit only its
            # navigation marker; no fallback label is invented.
            if (
                normalized_title is None
                or not is_route_valid_scalar_text(
                    normalized_title, MAX_STRUCTURE_LABEL_SCALARS
                )
                or not _thml_has_readable_content(node)
            ):
                return inner
            level = min(6, max(1, int(division.group(1))))
            marker_attributes = (
                f' data-cvw-native-location="{_html_escape(node.attrib.get("id", ""), quote=True)}"'
                f' data-cvw-native-label="{_html_escape(title, quote=True)}"'
            )
            marker = f"<h{level}{marker_attributes}></h{level}>"
            return marker + inner

        tag = _local_name(node.tag)
        if tag == "pb":
            return " " + _html_escape(page_break_label(node)) + " "
        reserved = {"data-cvw-native-label", "data-cvw-native-location"}
        attributes = "".join(
            f' {_local_name(name)}="{_html_escape(value or "", quote=True)}"'
            for name, value in node.attrib.items()
            if _local_name(name).lower() not in reserved
        )
        inner = _html_escape(node.text or "")
        inner += "".join(
            serialize(child) + _html_escape(child.tail or "") for child in node
        )
        if not inner and not list(node):
            return f"<{tag}{attributes}/>"
        return f"<{tag}{attributes}>{inner}</{tag}>"

    return _html_escape(element.text or "") + "".join(
        serialize(child) + _html_escape(child.tail or "") for child in element
    )


def render_xml_reader(media_type: str, exact: str) -> dict[str, Any]:
    """Render the readable body of retained ThML; preserve other XML as exact text.

    CVW must never turn an arbitrary XML vocabulary into an invented document.
    ThML has an explicit ``ThML.body`` with HTML-like reading structure, so that
    body can be projected through the same inert allow-list used for retained
    HTML. Malformed, entity-bearing, or other XML remains visibly exact text.
    """
    if media_type != "application/xml":
        raise RendererError("xml-reader requires application/xml media type")
    from cvw_app.xml_books import legacy_tei_book
    legacy = legacy_tei_book(exact)
    if legacy is not None:
        return legacy
    if _ENTITY_DECLARATION.search(exact) or _INTERNAL_DTD_SUBSET.search(exact):
        return render_exact_text(media_type, exact)
    try:
        root = ElementTree.fromstring(exact)
    except ElementTree.ParseError:
        return render_exact_text(media_type, exact)
    if _local_name(root.tag) == "TEI":
        return render_tei("application/tei+xml", exact)
    from cvw_app.xml_books import render_xml_book
    book = render_xml_book(root)
    if book is not None:
        return book
    if _local_name(root.tag).lower() != "thml":
        return render_exact_text(media_type, exact)
    body = next(
        (
            element
            for element in root.iter()
            if _local_name(element.tag).lower() == "thml.body"
        ),
        None,
    )
    if body is None:
        return render_exact_text(media_type, exact)
    body_markup = _thml_body_markup(body)
    if not any(text.strip() for text in body.itertext()):
        return render_exact_text(media_type, exact)
    # The inert markup now owns the body; release XML before allocating HTML nodes.
    del body, root
    parser = _SafeHtmlNodes(native_divisions=True)
    try:
        parser.feed(body_markup)
        parser.close()
    except (AssertionError, ValueError) as error:
        raise RendererError(f"ThML body is malformed: {error}") from error
    if not parser.nodes:
        return render_exact_text(media_type, exact)
    nodes, outline = parser.nodes, parser.outline
    del parser, body_markup
    rendered = _finalize_structure(
        "sanitized-html",
        nodes,
        outline,
        _heading_contexts(nodes, outline),
    )
    return {**rendered, "kind": "xml-reader"}


def render_json(media_type: str, exact: str) -> dict[str, Any]:
    try:
        value = json.loads(exact)
    except json.JSONDecodeError as error:
        raise RendererError(f"JSON artifact is malformed: {error}") from error
    book = render_json_book(value)
    if book is not None:
        return book
    if len(exact) > MAX_PAGE_SCALARS:
        # Building one recursive browser tree for a multi-megabyte authority makes
        # its top-level collection an atomic segment. That both stalls first open
        # and forces truncation. Keep the interactive tree for ordinary JSON, but
        # make every scalar of large valid JSON reviewable as bounded exact text.
        return render_exact_text("text/plain", exact)
    outline: list[dict[str, Any]] = []
    contexts: dict[str, dict[str, Any]] = {}
    locations = _StructureLocations()

    def pointer(parent: str, part: str) -> str:
        escaped = part.replace("~", "~0").replace("/", "~1")
        return f"{parent}/{escaped}" if parent else f"/{escaped}"

    def tree(item: object, path: str = "", level: int = 0) -> dict[str, Any]:
        if isinstance(item, dict):
            children = []
            for key, child in item.items():
                child_path = pointer(path, key)
                location = locations.allocate(child_path, len(outline) + 1)
                label = project_visible_text(key)
                outline.append(
                    {"location": location, "label": label, "level": level + 1}
                )
                child_node = tree(child, child_path, level + 1)
                property_node = _node(
                    "json-property",
                    label,
                    key=label,
                    location=location,
                    children=[child_node],
                )
                children.append(property_node)
                context_root = _node("json-object", "", children=[property_node])
                contexts[location] = {
                    "location": location,
                    "label": label,
                    "nodes": [context_root],
                    "text": _nodes_text([context_root]),
                }
            return _node(
                "json-object",
                f"Object with {len(item)} field{'s' if len(item) != 1 else ''}",
                children=children,
            )
        if isinstance(item, list):
            children = []
            for index, child in enumerate(item):
                child_path = pointer(path, str(index))
                location = locations.allocate(child_path, len(outline) + 1)
                outline.append(
                    {
                        "location": location,
                        "label": f"Item {index + 1}",
                        "level": level + 1,
                    }
                )
                child_node = tree(child, child_path, level + 1)
                property_node = _node(
                    "json-property",
                    str(index),
                    key=str(index),
                    location=location,
                    children=[child_node],
                )
                children.append(property_node)
                context_root = _node("json-array", "", children=[property_node])
                contexts[location] = {
                    "location": location,
                    "label": f"Item {index + 1}",
                    "nodes": [context_root],
                    "text": _nodes_text([context_root]),
                }
            return _node(
                "json-array",
                f"Array with {len(item)} item{'s' if len(item) != 1 else ''}",
                children=children,
            )
        if item is None:
            return _node("json-value", "null", value_kind="null")
        if isinstance(item, bool):
            return _node(
                "json-value", "true" if item else "false", value_kind="boolean"
            )
        if isinstance(item, (int, float)):
            return _node("json-value", str(item), value_kind="number")
        return _node("json-value", project_visible_text(item), value_kind="string")

    root_node = tree(value)
    contexts["start"] = {
        "location": "start",
        "label": "Start",
        "nodes": [root_node],
        "text": _nodes_text([root_node]),
    }
    return _finalize_structure("json-tree", [root_node], outline, contexts)


def _split_exact_text_chunks(exact: str, limit: int = MAX_PAGE_SCALARS) -> list[str]:
    """Split long plain text at line boundaries into bounded atomic chunks.

    Line boundaries are preferred, but a single long line is also sliced at the
    exact scalar bound so no retained text becomes an unreviewable truncated
    segment. The exact-artifact route remains the byte-for-byte fallback.
    """
    if len(exact) <= limit:
        return [exact]
    chunks: list[str] = []
    current = ""
    for original_line in exact.splitlines(keepends=True):
        line = original_line
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if current and len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def render_exact_text(media_type: str, exact: str) -> dict[str, Any]:
    """Preserve exact text; plain-text passages use source offsets, never inferred headings."""
    from cvw_app.structured_text import render_structured_text

    structured = render_structured_text(media_type, exact)
    if structured is not None:
        return structured
    nodes = []
    outline = []
    contexts = {}
    offset = 0
    line = 1
    plain = media_type.split(";", 1)[0] == "text/plain"
    passages = (
        [match.group() for match in re.finditer(r".+?(?:\r?\n[ \t]*\r?\n|\Z)", exact, re.S)]
        if plain else [exact]
    )
    for passage in passages or [exact]:
        for chunk in _split_exact_text_chunks(passage, MAX_STRUCTURE_CONTEXT_SCALARS if plain else MAX_PAGE_SCALARS):
            node = _node("preformatted", chunk)
            if plain and chunk.strip():
                location = f"text-{offset}"
                label = f"Line {line}: {project_visible_text(chunk)[:120]}"
                node["location"] = location
                outline.append({"location": location, "label": label, "level": 1})
                contexts[location] = {"location": location, "label": label, "nodes": [node], "text": chunk}
            nodes.append(node)
            offset += len(chunk)
            line += chunk.count("\n")
    start_context = {
        "location": "start",
        "label": "Start",
        "nodes": nodes,
        "text": _nodes_text(nodes),
    }
    contexts["start"] = start_context
    return _finalize_structure("exact-text", nodes, outline, contexts)


_SWORD_ZLD_MEDIA_TYPE = "application/vnd.crosswire.sword-zld"
_SWORD_ZLD_MEMBER_NAMES = ("dict-zdt", "dict-zdx", "dict-dat", "dict-idx")
_SWORD_ZLD_ARCHIVE_NAMES = {
    "dict-zdt": "modules/lexdict/zld/nave/dict.zdt",
    "dict-zdx": "modules/lexdict/zld/nave/dict.zdx",
    "dict-dat": "modules/lexdict/zld/nave/dict.dat",
    "dict-idx": "modules/lexdict/zld/nave/dict.idx",
    "nave-conf": "mods.d/nave.conf",
}
_SWORD_ZLD_ARCHIVE_ORDER = (
    "modules/lexdict/zld/nave/dict.zdx",
    "modules/lexdict/zld/nave/dict.zdt",
    "modules/lexdict/zld/nave/dict.dat",
    "modules/lexdict/zld/nave/dict.idx",
    "mods.d/nave.conf",
)


def _sword_zld_fragment(payload: bytes, ordinal: int, *, include_targets: bool = True) -> tuple[str, str]:
    if not payload.endswith(b"\x00") or b"\x00" in payload[:-1]:
        raise RendererError(
            f"SWORD zLD payload {ordinal} does not have exactly one terminal NUL"
        )
    body = payload[:-1]
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise RendererError("SWORD zLD payload declares a DTD or entity")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise RendererError(
            f"SWORD zLD payload {ordinal} is malformed XML: {error}"
        ) from error

    def local_name(tag: object) -> str:
        if not isinstance(tag, str):
            raise RendererError("SWORD zLD payload contains a non-element node")
        return tag.rsplit("}", 1)[-1]

    allowed = {"entryFree", "def", "lb", "ref", "list", "item"}
    for element in root.iter():
        name = local_name(element.tag)
        if name not in allowed:
            raise RendererError(f"SWORD zLD payload {ordinal} has unsupported <{name}>")
        attributes = set(element.attrib)
        if name == "entryFree":
            if attributes != {"n"} or not element.attrib.get("n"):
                raise RendererError(
                    f"SWORD zLD payload {ordinal} has invalid entryFree/@n"
                )
        elif name == "ref":
            if attributes not in ({"osisRef"}, {"target"}):
                raise RendererError(
                    f"SWORD zLD payload {ordinal} has invalid reference attributes"
                )
        elif attributes:
            raise RendererError(
                f"SWORD zLD payload {ordinal} has unsupported attributes"
            )
    children = list(root)
    if (
        local_name(root.tag) != "entryFree"
        or len(children) != 1
        or local_name(children[0].tag) != "def"
    ):
        raise RendererError(f"SWORD zLD payload {ordinal} has invalid entry structure")

    def readable(element: ElementTree.Element) -> str:
        pieces = [element.text or ""]
        for child in element:
            child_name = local_name(child.tag)
            if child_name == "lb":
                pieces.append("\n")
            elif child_name == "item":
                pieces.extend(("\n• ", readable(child)))
            elif child_name == "ref":
                reference_text = readable(child)
                attribute, target = next(iter(child.attrib.items()))
                pieces.append(reference_text)
                if include_targets:
                    pieces.append(f" ⟦{attribute}:{target}⟧")
            else:
                pieces.append(readable(child))
            pieces.append(child.tail or "")
        return "".join(pieces)

    return str(root.attrib["n"]), project_visible_text(readable(children[0]))


def render_sword_zld(media_type: str, context: dict[str, bytes]) -> dict[str, Any]:
    """Render one exact selected Nave carrier through its complete bound zLD set.

    The selected carrier remains the public artifact.  This in-memory context is
    only a review projection: all four source members, the retained acquisition
    ZIP, and module config are reverified before any readable text is emitted.
    """

    if media_type != _SWORD_ZLD_MEDIA_TYPE:
        raise RendererError("SWORD zLD presentation has an invalid media type")
    expected_keys = {
        *_SWORD_ZLD_MEMBER_NAMES,
        "nave-conf",
        "nave-archive",
        "__selected_name__",
        "__source_set_sha256__",
    }
    if set(context) != expected_keys or any(
        not isinstance(value, bytes) for value in context.values()
    ):
        raise RendererError("SWORD zLD presentation context is incomplete")
    try:
        selected_name = context["__selected_name__"].decode("ascii")
        source_set_sha256 = context["__source_set_sha256__"].decode("ascii")
    except UnicodeDecodeError as error:
        raise RendererError("SWORD zLD presentation identity is not ASCII") from error
    if selected_name not in _SWORD_ZLD_MEMBER_NAMES:
        raise RendererError("SWORD zLD selected carrier is invalid")
    if re.fullmatch(r"[0-9a-f]{64}", source_set_sha256) is None:
        raise RendererError("SWORD zLD source-set identity is invalid")

    archive_payload = context["nave-archive"]
    try:
        with zipfile.ZipFile(io.BytesIO(archive_payload)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if names != list(_SWORD_ZLD_ARCHIVE_ORDER) or len(names) != len(set(names)):
                raise RendererError("retained Nave ZIP member order or scope drifted")
            for member_name, archive_name in _SWORD_ZLD_ARCHIVE_NAMES.items():
                if archive.read(archive_name) != context[member_name]:
                    raise RendererError(
                        f"retained Nave ZIP differs from extracted {member_name}"
                    )
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise RendererError(f"retained Nave ZIP is unreadable: {error}") from error

    return _render_sword_zld_members(context, selected_name, source_set_sha256)


def _render_sword_zld_members(context, selected_name, source_set_sha256, *, include_targets=True):
    idx = context["dict-idx"]
    dat = context["dict-dat"]
    zdx = context["dict-zdx"]
    zdt = context["dict-zdt"]
    if not idx or len(idx) % 8 or not zdx or len(zdx) % 8:
        raise RendererError("SWORD zLD index is empty, truncated, or misaligned")

    physical_payloads: dict[tuple[int, int], bytes] = {}
    zdt_cursor = 0
    block_count = 0
    for block_number, position in enumerate(range(0, len(zdx), 8)):
        offset, compressed_size = struct.unpack_from("<II", zdx, position)
        if (
            offset != zdt_cursor
            or compressed_size == 0
            or offset + compressed_size + 2 > len(zdt)
            or zdt[offset + compressed_size : offset + compressed_size + 2] != b"\r\n"
        ):
            raise RendererError(f"SWORD zLD block {block_number} span drifted")
        inflater = zlib.decompressobj()
        try:
            plain = inflater.decompress(zdt[offset : offset + compressed_size], 16 * 1024 * 1024)
            if inflater.unconsumed_tail:
                raise RendererError("SWORD zLD block exceeds the decompressed reader limit")
            plain += inflater.flush()
        except zlib.error as error:
            raise RendererError(
                f"SWORD zLD block {block_number} cannot be decompressed"
            ) from error
        if (
            not inflater.eof
            or inflater.unconsumed_tail
            or len(inflater.unused_data) != 1_024
            or any(inflater.unused_data)
            or len(plain) < 12
        ):
            raise RendererError(f"SWORD zLD block {block_number} allocation drifted")
        entry_count = struct.unpack_from("<I", plain, 0)[0]
        data_start = 4 + entry_count * 8
        if entry_count == 0 or data_start > len(plain):
            raise RendererError(f"SWORD zLD block {block_number} table drifted")
        payload_cursor = data_start
        for entry_number in range(entry_count):
            payload_offset, payload_size = struct.unpack_from(
                "<II", plain, 4 + entry_number * 8
            )
            if (
                payload_offset != payload_cursor
                or payload_size == 0
                or payload_offset + payload_size > len(plain)
            ):
                raise RendererError(
                    f"SWORD zLD block {block_number} entry table drifted"
                )
            payload = plain[payload_offset : payload_offset + payload_size]
            _sword_zld_fragment(payload, len(physical_payloads) + 1)
            physical_payloads[(block_number, entry_number)] = payload
            payload_cursor += payload_size
        if payload_cursor != len(plain):
            raise RendererError(f"SWORD zLD block {block_number} has unaccounted bytes")
        zdt_cursor = offset + compressed_size + 2
        block_count += 1
    if zdt_cursor != len(zdt):
        raise RendererError("SWORD zLD payload has unindexed trailing bytes")

    rows: list[str] = []
    seen_pointers: set[tuple[int, int]] = set()
    dat_spans: list[tuple[int, int]] = []
    for ordinal, position in enumerate(range(0, len(idx), 8), 1):
        offset, record_size = struct.unpack_from("<II", idx, position)
        if record_size < 11 or offset + record_size + 2 > len(dat):
            raise RendererError(f"SWORD zLD dictionary record {ordinal} span drifted")
        raw_record = dat[offset : offset + record_size]
        if (
            dat[offset + record_size : offset + record_size + 2] != b"\r\n"
            or raw_record.count(b"\r\n") != 1
        ):
            raise RendererError(
                f"SWORD zLD dictionary record {ordinal} delimiter drifted"
            )
        key_bytes, pointer_bytes = raw_record.split(b"\r\n", 1)
        if not key_bytes or len(pointer_bytes) != 8:
            raise RendererError(f"SWORD zLD dictionary record {ordinal} shape drifted")
        try:
            key = key_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RendererError(
                f"SWORD zLD dictionary key {ordinal} is not UTF-8"
            ) from error
        pointer = struct.unpack("<II", pointer_bytes)
        if pointer not in physical_payloads or pointer in seen_pointers:
            raise RendererError(
                f"SWORD zLD dictionary record {ordinal} pointer drifted"
            )
        seen_pointers.add(pointer)
        payload_n, readable = _sword_zld_fragment(physical_payloads[pointer], ordinal, include_targets=include_targets)
        rows.append(f"{ordinal}. {key} ⟦entryFree/@n:{payload_n}⟧ — {readable}")
        dat_spans.append((offset, record_size))
    cursor = 0
    for offset, record_size in sorted(dat_spans):
        if offset != cursor:
            raise RendererError("SWORD zLD dictionary data has a gap or overlap")
        cursor = offset + record_size + 2
    if cursor != len(dat) or seen_pointers != set(physical_payloads):
        raise RendererError("SWORD zLD dictionary coverage is incomplete")

    selected = context[selected_name]
    summary = (
        f"Selected exact carrier: {selected_name}; {len(selected)} bytes; SHA-256 "
        f"{hashlib.sha256(selected).hexdigest()}. Derived review presentation: "
        f"{len(rows)} dictionary records in dict.idx order across {block_count} zLD "
        f"blocks; transformation source-set SHA-256 {source_set_sha256}. The four "
        "extracted members were byte-matched to the retained Nave ZIP; nave.conf "
        "is support metadata, not body text."
    )
    nodes = [_node("paragraph", summary), *(_node("paragraph", row) for row in rows)]
    contexts = {
        "start": {
            "location": "start",
            "label": "Start",
            "nodes": nodes,
            "text": _nodes_text(nodes),
        }
    }
    return _finalize_structure("sword-zld-reader", nodes, [], contexts)


_BARNES_ZCOM_MEDIA_TYPE = "application/vnd.crosswire.sword-zcom"
_BARNES_ZCOM_ARCHIVE_SHA256 = (
    "9e8edc0333875c214124371b3862df118ad3a76ade7753cb2faeed3484615baf"
)
_BARNES_ZCOM_MEMBERS = {
    "nt.czv": (
        82460,
        "edd2d46416db52595af44811a49940527bba208bd6b73b7c30f480c21d63edae",
        "modules/comments/zcom/barnes/nt.czv",
    ),
    "nt.czz": (
        6018995,
        "d26ada7eba82d4c0c24c18ad8d8a520c1dfd5761e2bdc8161c6888bc665ea40a",
        "modules/comments/zcom/barnes/nt.czz",
    ),
    "nt.czs": (
        3120,
        "a39f80ec47d108a43fda634c1234fc03827f32eac1636d614c01b424dfcf6302",
        "modules/comments/zcom/barnes/nt.czs",
    ),
}
_BARNES_ZCOM_CONF = (
    437,
    "6895f7186042c5624117973892bc22dc27fa31a21e9f4fbb217793e8b5df9a5f",
    "mods.d/barnes.conf",
)
_BARNES_ZCOM_ARCHIVE_NAMES = (
    "modules/comments/zcom/barnes/nt.czv",
    "modules/comments/zcom/barnes/nt.czz",
    "modules/comments/zcom/barnes/nt.czs",
)


def _barnes_zcom_slots(context: dict[str, bytes]) -> list[tuple[int, bytes]]:
    expected_keys = {
        "retained-archive",
        "nt.czv",
        "nt.czz",
        "nt.czs",
        "barnes-conf",
        "__selected_name__",
        "__source_set_sha256__",
    }
    if set(context) != expected_keys or any(
        not isinstance(value, bytes) for value in context.values()
    ):
        raise RendererError("Barnes zCom presentation context is incomplete")
    try:
        selected_name = context["__selected_name__"].decode("ascii")
        source_set_sha256 = context["__source_set_sha256__"].decode("ascii")
    except UnicodeDecodeError as error:
        raise RendererError("Barnes zCom presentation identity is not ASCII") from error
    if (
        selected_name != "retained-archive"
        or re.fullmatch(r"[0-9a-f]{64}", source_set_sha256) is None
    ):
        raise RendererError("Barnes zCom presentation identity is invalid")
    archive_payload = context[selected_name]
    if hashlib.sha256(archive_payload).hexdigest() != _BARNES_ZCOM_ARCHIVE_SHA256:
        raise RendererError("Barnes zCom retained archive digest drifted")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_payload)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            expected_names = [*_BARNES_ZCOM_ARCHIVE_NAMES, _BARNES_ZCOM_CONF[2]]
            if names != expected_names or len(names) != len(set(names)):
                raise RendererError("Barnes zCom archive member order or scope drifted")
            if any(info.compress_type != zipfile.ZIP_DEFLATED for info in infos):
                raise RendererError("Barnes zCom archive compression method drifted")
            archive_members = {
                name: archive.read(name)
                for name in (*_BARNES_ZCOM_ARCHIVE_NAMES, _BARNES_ZCOM_CONF[2])
            }
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise RendererError(
            f"Barnes zCom retained archive is unreadable: {error}"
        ) from error
    for name, (size, digest, _archive_name) in _BARNES_ZCOM_MEMBERS.items():
        payload = context[name]
        if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
            raise RendererError(f"Barnes zCom declared member identity drifted: {name}")
        if archive_members[_archive_name] != payload:
            raise RendererError(
                f"Barnes zCom archive differs from extracted member: {name}"
            )
    conf_size, conf_digest, conf_archive_name = _BARNES_ZCOM_CONF
    if (
        len(context["barnes-conf"]) != conf_size
        or hashlib.sha256(context["barnes-conf"]).hexdigest() != conf_digest
        or archive_members[conf_archive_name] != context["barnes-conf"]
    ):
        raise RendererError("Barnes zCom archive differs from declared module config")

    return _decode_barnes_members(context)


def _decode_barnes_members(context):
    index, packed, block_index = context["nt.czv"], context["nt.czz"], context["nt.czs"]
    if len(index) % 10 or len(block_index) % 12:
        raise RendererError("Barnes zCom indexes are truncated or misaligned")
    blocks: dict[int, bytes] = {}
    rows: list[tuple[int, bytes]] = []
    for slot, position in enumerate(range(0, len(index), 10)):
        block, start, length = struct.unpack_from("<IIH", index, position)
        if length == 0:
            rows.append((slot, b""))
            continue
        if block not in blocks:
            record = block * 12
            if record + 12 > len(block_index):
                raise RendererError(
                    f"Barnes zCom slot {slot} references a missing block"
                )
            offset, compressed_length, expected_length = struct.unpack_from(
                "<III", block_index, record
            )
            end = offset + compressed_length
            if not compressed_length or end > len(packed):
                raise RendererError(f"Barnes zCom block {block} range is invalid")
            try:
                decoder = zlib.decompressobj()
                raw = decoder.decompress(packed[offset:end]) + decoder.flush()
            except zlib.error as error:
                raise RendererError(f"Barnes zCom block {block} cannot be decompressed") from error
            if (
                not decoder.eof
                or len(decoder.unused_data) != 1_024
                or any(decoder.unused_data)
                or decoder.unconsumed_tail
                or len(raw) != expected_length
            ):
                raise RendererError(f"Barnes zCom block {block} decompression length or framing drifted")
            blocks[block] = raw
        raw = blocks[block]
        if start + length > len(raw):
            raise RendererError(f"Barnes zCom slot {slot} exceeds its indexed block")
        rows.append((slot, raw[start : start + length]))
    return rows


def render_barnes_zcom(media_type: str, context: dict[str, bytes]) -> dict[str, Any]:
    """Show source-bound Barnes zCom carriers by numeric slot, without inferred references."""
    if media_type != _BARNES_ZCOM_MEDIA_TYPE:
        raise RendererError("Barnes zCom presentation has an invalid media type")
    rows = _barnes_zcom_slots(context)
    nodes = [_node("preformatted", f"Source slot {slot:05d}: " + _barnes_zcom_carrier_text(payload)) for slot, payload in rows]
    summary = _node("paragraph", f"Exact Barnes zCom alternative presentation; {len(rows)} numeric source slots in retained index order. These slot numbers are not book, chapter, or verse references. Invalid UTF-8 is shown as exact-byte hex; XML-incompatible characters are escaped and flagged.")
    nodes.insert(0, summary)
    contexts = {
        "start": {
            "location": "start",
            "label": "Start",
            "nodes": nodes,
            "text": _nodes_text(nodes),
        }
    }
    return _finalize_structure("barnes-zcom-reader", nodes, [], contexts)


def _barnes_zcom_carrier_text(payload: bytes) -> str:
    if not payload:
        return "[empty source carrier]"
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return f"[WARNING: invalid UTF-8; exact bytes hex: {payload.hex()}]"
    output: list[str] = []
    unsafe = False
    for char in text:
        codepoint = ord(char)
        if (
            codepoint in (0x9, 0xA, 0xD)
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ):
            output.append(char)
        else:
            output.append(f"\\u{codepoint:04X}")
            unsafe = True
    visible = "".join(output)
    return (
        f"[WARNING: XML-incompatible character escaped] {visible}"
        if unsafe
        else visible
    )


TextRenderer = Callable[[str, str], dict[str, Any]]
BinaryRenderer = Callable[[str, bytes], dict[str, Any]]
ContextRenderer = Callable[[str, dict[str, bytes]], dict[str, Any]]
Renderer = TextRenderer | BinaryRenderer | ContextRenderer


# --- Ticket 06b binary renderers -------------------------------------------


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI = b"\xff\xd8\xff"
_TIFF_MAGIC = (b"II*\x00", b"MM\x00*")
MAX_EPUB_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_EPUB_SPINE_DOCUMENTS = 512
EPUB_MIMETYPE = b"application/epub+zip"
_HTML_SPINE_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def verify_binary_content_signature(media_type: str, payload: bytes) -> None:
    """Verify declared type against the artifact's content signature (plan C6/r2).

    JPEG requires only the SOI marker; any legal segment may follow it. PDF
    accepts ``%PDF-`` anywhere within the first 1 KiB. TIFF magic is checked for
    byte verification only because display honestly falls back. EPUB zip rules
    are enforced inside ``render_epub``.
    """
    if media_type == "image/png":
        if not payload.startswith(_PNG_SIGNATURE):
            raise RendererError(
                "declared image/png bytes do not start with the PNG signature"
            )
    elif media_type == "image/jpeg":
        if not payload.startswith(_JPEG_SOI):
            raise RendererError(
                "declared image/jpeg bytes do not start with the JPEG SOI marker"
            )
    elif media_type == "image/webp":
        if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
            raise RendererError(
                "declared image/webp bytes do not carry the RIFF/WEBP fourcc"
            )
    elif media_type == "image/tiff":
        if not payload.startswith(_TIFF_MAGIC):
            raise RendererError(
                "declared image/tiff bytes do not carry a TIFF byte-order mark"
            )
    elif media_type == "application/pdf":
        if b"%PDF-" not in payload[:1024]:
            raise RendererError(
                "declared application/pdf bytes lack a %PDF- header within the first 1 KiB"
            )
    elif media_type == "application/zip":
        if not payload.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            raise RendererError("declared application/zip bytes lack a ZIP signature")
    elif media_type == "application/gzip":
        if not payload.startswith(b"\x1f\x8b"):
            raise RendererError("declared application/gzip bytes lack a GZIP signature")
    elif media_type not in {"application/epub+zip", "application/octet-stream"}:
        raise RendererError(
            f"no content signature is governed for declared media type {media_type}"
        )


def _single_node_output(kind: str, node: dict[str, Any]) -> dict[str, Any]:
    nodes = [node]
    start_context = {
        "location": "start",
        "label": "Start",
        "nodes": nodes,
        "text": _nodes_text(nodes),
    }
    return _finalize_structure(kind, nodes, [], {"start": start_context})


def render_image_facsimile(media_type: str, payload: bytes) -> dict[str, Any]:
    """One image node with an alt label only; the frontend composes its own URL (A1/B1)."""
    del payload  # The bytes were already signature-verified at ingest.
    label = project_visible_text(f"Facsimile image ({media_type})")
    return _single_node_output("image-facsimile", {"type": "image", "text": label})


def _render_tiff_honest_fallback() -> dict[str, Any]:
    """Honest unsupported-with-bytes presentation for TIFF (B6)."""
    return _single_node_output(
        "image-facsimile",
        _node(
            "paragraph",
            "The browser cannot display TIFF images natively; exact byte access remains available.",
        ),
    )


def render_pdf_native(media_type: str, payload: bytes) -> dict[str, Any]:
    """One scan page per section, using the existing passage and paging controls."""
    from cvw_app.pdf_pages import pdf_page_count

    try:
        count = pdf_page_count(payload)
    except RendererError:
        return _single_node_output("pdf-native", _node("paragraph", "Page previews are unavailable. Download the original PDF to read it."))
    nodes = [_node("paragraph", f"Page {page}", location=f"pdf-page-{page}") for page in range(1, count + 1)]
    outline = [{"location": node["location"], "label": node["text"], "level": 1} for node in nodes]
    rendered = _finalize_structure("pdf-native", nodes, outline, _heading_contexts(nodes, outline), hard_break_before=set(range(1, count)))
    rendered["_hard_break_before"] = list(range(1, count))
    return rendered


def render_unsupported_binary(media_type: str, payload: bytes) -> dict[str, Any]:
    """Identify non-renderable retained bytes without decoding or executing them."""
    del payload
    return _single_node_output(
        "exact-text",
        _node(
            "paragraph",
            "Download this file to open it in another application.",
        ),
    )


def _decode_utf8(payload: bytes) -> str:
    return payload.decode("utf-8")


def _parse_governed_epub_xml(text: str) -> ElementTree.Element:
    """Reuse the TEI parser's DTD/entity-forbidding guards (B5)."""
    if _ENTITY_DECLARATION.search(text) or _INTERNAL_DTD_SUBSET.search(text):
        raise RendererError(
            "EPUB metadata XML declares an XML entity or internal DTD subset; "
            "only a subset-free DOCTYPE is permitted"
        )
    return ElementTree.fromstring(text)


def _read_bounded_zip_entry(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, budget: list[int]
) -> bytes:
    """Read one entry while enforcing the cumulative uncompressed cap incrementally (B4)."""
    chunks: list[bytes] = []
    with archive.open(info) as stream:
        while True:
            chunk = stream.read(262_144)
            if not chunk:
                break
            budget[0] -= len(chunk)
            if budget[0] < 0:
                raise RendererError(
                    "EPUB uncompressed content exceeds the governed 64 MiB bound"
                )
            chunks.append(chunk)
    return b"".join(chunks)


def _compose_epub(payload: bytes) -> dict[str, Any]:
    """Single composition pass over the OPF spine (B3)."""
    archive = zipfile.ZipFile(io.BytesIO(payload))
    try:
        infos = archive.infolist()
        if not infos or infos[0].filename != "mimetype":
            raise RendererError("EPUB first zip entry must be named mimetype")
        budget = [MAX_EPUB_UNCOMPRESSED_BYTES]
        mimetype = _read_bounded_zip_entry(archive, infos[0], budget)
        if infos[0].compress_type != zipfile.ZIP_STORED or mimetype != EPUB_MIMETYPE:
            raise RendererError(
                "EPUB mimetype entry must be stored uncompressed with content application/epub+zip"
            )
        container = _parse_governed_epub_xml(
            _decode_utf8(
                _read_bounded_zip_entry(
                    archive, archive.getinfo("META-INF/container.xml"), budget
                )
            ),
        )
        rootfile_path = next(
            (
                element.get("full-path")
                for element in container.iter()
                if _local_name(element.tag) == "rootfile"
            ),
            None,
        )
        if not rootfile_path:
            raise RendererError("EPUB container.xml declares no rootfile")
        opf = _parse_governed_epub_xml(
            _decode_utf8(
                _read_bounded_zip_entry(archive, archive.getinfo(rootfile_path), budget)
            )
        )
        manifest_items: dict[str, tuple[str, str]] = {}
        for element in opf.iter():
            if (
                _local_name(element.tag) == "item"
                and element.get("id")
                and element.get("href")
            ):
                manifest_items[element.get("id")] = (
                    element.get("href"),
                    element.get("media-type") or "",
                )
        spine_refs = [
            element.get("idref")
            for element in opf.iter()
            if _local_name(element.tag) == "itemref" and element.get("idref")
        ]
        locations = _StructureLocations()
        nodes: list[dict[str, Any]] = []
        outline: list[dict[str, Any]] = []
        base_dir = posixpath.dirname(rootfile_path)
        for spine_index, idref in enumerate(spine_refs, start=1):
            href, item_media_type = manifest_items.get(idref, ("", ""))
            entry_path = (
                posixpath.normpath(posixpath.join(base_dir, href)) if href else ""
            )
            entry_info = archive.getinfo(entry_path) if entry_path else None
            if (
                spine_index <= MAX_EPUB_SPINE_DOCUMENTS
                and item_media_type in _HTML_SPINE_MEDIA_TYPES
                and entry_info is not None
            ):
                doc_text = _decode_utf8(
                    _read_bounded_zip_entry(archive, entry_info, budget)
                )
                parser = _SafeHtmlNodes()
                parser.feed(doc_text)
                parser.close()
                if not parser.outline:
                    location = locations.allocate(f"spine-{spine_index}-start", len(outline) + 1)
                    label = f"Part {spine_index}: {posixpath.basename(href)}"
                    nodes.append(_node("heading", "" if parser.nodes else f"{label} contains no readable text.", level=1, location=location))
                    outline.append({"location": location, "label": label, "level": 1})
                remap: dict[str, str] = {}
                for node in parser.nodes:
                    old_location = node.get("location")
                    if isinstance(old_location, str):
                        new_location = locations.allocate(
                            f"spine-{spine_index}-{old_location}", len(outline) + 1
                        )
                        remap[old_location] = new_location
                        node["location"] = new_location
                nodes.extend(parser.nodes)
                for item in parser.outline:
                    outline.append(
                        {
                            "location": remap[item["location"]],
                            "label": item["label"],
                            "level": item["level"],
                        }
                    )
            else:
                # Named but unrendered spine documents stay in the outline; nothing is silently dropped.
                label = f"Spine document {spine_index} is named but not rendered"
                location = locations.allocate(
                    f"spine-{spine_index}-unrendered", len(outline) + 1
                )
                nodes.append(_node("heading", label, level=1, location=location))
                outline.append({"location": location, "label": label, "level": 1})
        if not nodes:
            raise RendererError("EPUB artifact has no readable spine content")
        contexts = _heading_contexts(nodes, outline)
        return _finalize_structure("epub-reader", nodes, outline, contexts)
    finally:
        archive.close()


def render_epub(media_type: str, payload: bytes) -> dict[str, Any]:
    """Governed EPUB composition; every failure mode converts to RendererError (B4/r2)."""
    if media_type != "application/epub+zip":
        raise RendererError("epub-reader requires the application/epub+zip media type")
    try:
        return _compose_epub(payload)
    except Exception as error:
        raise RendererError(f"EPUB artifact could not be opened: {error}") from error


class RendererRegistry:
    def __init__(self, renderers: dict[str, Renderer]) -> None:
        self._renderers = dict(renderers)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._renderers))

    def render(
        self, kind: str, media_type: str, exact: str | bytes | dict[str, bytes]
    ) -> tuple[dict[str, Any], bool]:
        try:
            renderer = self._renderers.get(kind)
            if renderer is None:
                if isinstance(exact, (bytes, bytearray)):
                    raise RendererError(
                        "unregistered kinds fall back to exact text, which requires decoded text"
                    )
                rendered = _validate_renderer_output(
                    render_exact_text(media_type, exact)
                )
                return (
                    {
                        **rendered,
                        "outline": [],
                        "contexts": {"start": rendered["contexts"]["start"]},
                    }
                ), False
            if kind in CONTEXT_PRESENTATION_KINDS:
                if not isinstance(exact, dict) or any(
                    not isinstance(key, str) or not isinstance(value, bytes)
                    for key, value in exact.items()
                ):
                    raise RendererError(
                        "context presentation kinds require verified named member bytes"
                    )
                output = renderer(media_type, exact)  # type: ignore[arg-type]
                if not output["nodes"]:
                    raise RendererError(
                        "context renderers must emit at least one document node"
                    )
                return (_validate_renderer_output(output)), True
            if kind in BINARY_PRESENTATION_KINDS:
                if not isinstance(exact, (bytes, bytearray)):
                    raise RendererError(
                        "binary presentation kinds require verified artifact bytes"
                    )
                if kind == "image-facsimile" and media_type == "image/tiff":
                    # B6: honest unsupported-with-bytes; no fake thumbnail, no conversion.
                    return (
                        _validate_renderer_output(_render_tiff_honest_fallback())
                    ), False
                output = renderer(media_type, bytes(exact))
                if not output["nodes"]:
                    raise RendererError(
                        "binary renderers must emit at least one document node"
                    )
                return (
                    _validate_renderer_output(output)
                ), kind != "unsupported-binary"
            if not isinstance(exact, str):
                raise RendererError("text presentation kinds require decoded text")
            return (
                _validate_renderer_output(renderer(media_type, exact))
            ), True
        except RecursionError as error:
            raise RendererError(
                "renderer nesting exceeds the governed recursion depth"
            ) from error


from cvw_app.sword_members import render_sword_members


DEFAULT_RENDERER_REGISTRY = RendererRegistry(
    {
        "sanitized-html": render_sanitized_html,
        "xml-reader": render_xml_reader,
        "tei-reader": render_tei,
        "json-tree": render_json,
        "exact-text": render_exact_text,
        "image-facsimile": render_image_facsimile,
        "pdf-native": render_pdf_native,
        "epub-reader": render_epub,
        "sword-zld-reader": render_sword_zld,
        "barnes-zcom-reader": render_barnes_zcom,
        "sword-members-reader": render_sword_members,
        "unsupported-binary": render_unsupported_binary,
    }
)
