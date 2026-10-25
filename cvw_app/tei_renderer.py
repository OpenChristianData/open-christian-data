"""Typed, code-native artifact renderers for the Corpus Review Viewer."""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Callable
from xml.etree import ElementTree


from cvw_app.renderer_nodes import (
    RendererError,
    MAX_TABLE_COLSPAN,
    MAX_TABLE_ROWSPAN,
    project_visible_text,
    is_route_valid_scalar_text,
    _StructureLocations,
    _node,
    _parse_table_span,
    _finalize_structure,
    _heading_contexts,
)
from cvw_app.renderer_nodes import (
    _local_name,
    _TEI_XML_ID,
    _ENTITY_DECLARATION,
    _INTERNAL_DTD_SUBSET,
    _TEI_SUPPRESSED,
    _TEI_TEXT_BLOCKS,
    _TEI_DICTIONARY_ENTRY_TYPES,
    _TEI_LEAF_HANDLED,
)

from cvw_app.tei_inline import inline_node, page_break_label, pointer_review_label


def _source_heading(element: ElementTree.Element) -> re.Match[str] | None:
    if _local_name(element.tag) not in {"p", "ab", "seg"}:
        return None
    return re.fullmatch(r"source-h([1-6])", element.get("rend", "")) or re.fullmatch(r"source-h([1-6])", element.get("type", ""))


def _contains_handled_descendant(element: ElementTree.Element) -> bool:
    return any(
        _local_name(item.tag) in _TEI_LEAF_HANDLED or _source_heading(item)
        for item in element.iter()
        if item is not element
    )


def _tei_readable_text(element: ElementTree.Element) -> str:
    """Project TEI text while honoring explicit line-break word boundaries."""
    if _local_name(element.tag) == "pb":
        return " " + page_break_label(element) + " "
    if element.attrib.get("type") == "json-null":
        return "null"
    parts = [pointer_review_label(element), element.text or ""]
    for child in element:
        if _local_name(child.tag) == "lb":
            if (child.attrib.get("break") or "").lower() != "no":
                parts.append("\n")
        else:
            parts.append(_tei_readable_text(child))
        parts.append(child.tail or "")
    text = "".join(parts)
    if _local_name(element.tag) != "gap" or project_visible_text(text).strip():
        return text

    # TCP GAP/@DISP is retained as TEI GAP/@rend by the producer.  Empty gaps
    # have no element text for the ordinary recursive projection to collect, so
    # expose that retained marker without adding a second copy when text exists.
    for attribute in ("rend", "display"):
        display = element.attrib.get(attribute)
        if display and project_visible_text(display).strip():
            return display

    # A gap without retained display text must remain visibly honest.  The
    # reason/extent describe what is absent; they never stand in for guessed
    # source words.
    reason = project_visible_text(
        element.attrib.get("reason") or element.attrib.get("desc") or ""
    )
    extent = project_visible_text(element.attrib.get("extent") or "")
    label = f"{reason} gap" if reason else "gap"
    if extent:
        label = f"{label}; extent {extent}"
    return f"[{label}]"


def _tei_preserves_space(element: ElementTree.Element, inherited: bool) -> bool:
    setting = element.attrib.get("{http://www.w3.org/XML/1998/namespace}space")
    return inherited if setting is None else setting == "preserve"


def _tei_readable_blocks(
    element: ElementTree.Element,
    *,
    preserve_whitespace: bool = False,
    xml_space_preserve: bool = False,
) -> list[tuple[str, str]]:
    """Preserve inline notes and distinguish XML formatting from verse breaks."""

    result: list[tuple[str, str]] = []
    buffered: list[tuple[str, str]] = []

    def append_text(value: str, space: bool) -> None:
        # Keep source horizontal indentation in meaningful text nodes. XML
        # newlines are soft separators unless xml:space preserves them; an lb
        # has its own token and cannot be confused with those formatting runs.
        if preserve_whitespace and not space:
            pieces = re.split(r"[ \t]*[\r\n]+[ \t\r\n]*", value)
            for index, piece in enumerate(pieces):
                if index:
                    buffered.append(("format", ""))
                if piece:
                    buffered.append(("text", piece))
        elif value:
            buffered.append(("text", value))

    def flush_paragraph() -> None:
        pieces: list[str] = []
        for index, (kind, value) in enumerate(buffered):
            if kind == "text":
                pieces.append(value)
            elif kind == "break":
                pieces.append("\n")
            elif kind == "format":
                before = next(
                    (
                        token
                        for token in reversed(buffered[:index])
                        if token[0] != "format"
                    ),
                    None,
                )
                after = next(
                    (token for token in buffered[index + 1 :] if token[0] != "format"),
                    None,
                )
                # Defer separator decisions until all inline wrappers have
                # been traversed, so wrapper edges cannot join source words.
                if (
                    before
                    and after
                    and before[0] == after[0] == "text"
                    and not before[1][-1].isspace()
                    and not after[1][0].isspace()
                    and (not pieces or not pieces[-1].endswith(" "))
                ):
                    pieces.append(" ")
        text = "".join(pieces)
        if not preserve_whitespace:
            text = project_visible_text(text)
        buffered.clear()
        if text.strip():
            result.append(
                ("preformatted" if preserve_whitespace else "paragraph", text)
            )

    def consume(parent: ElementTree.Element, inherited_space: bool) -> None:
        space = _tei_preserves_space(parent, inherited_space)
        append_text(pointer_review_label(parent), space)
        append_text(parent.text or "", space)
        for child in parent:
            child_name = _local_name(child.tag)
            if child_name == "note":
                flush_paragraph()
                note_text = project_visible_text(_tei_readable_text(child))
                if note_text.strip():
                    result.append(("blockquote", note_text))
            elif child_name == "lb":
                buffered.append(
                    (
                        "join"
                        if (child.attrib.get("break") or "").lower() == "no"
                        else "break",
                        "",
                    )
                )
            elif child_name == "pb":
                append_text(" " + page_break_label(child) + " ", space)
            elif child_name == "gap":
                append_text(
                    _tei_readable_text(child), _tei_preserves_space(child, space)
                )
            elif child_name in {"lg", "l"}:
                flush_paragraph()
                result.extend(_tei_verse_blocks(child, xml_space_preserve=space))
            elif child_name in {"p", "ab", "item"}:
                flush_paragraph()
                result.extend(
                    _tei_readable_blocks(
                        child,
                        preserve_whitespace=preserve_whitespace,
                        xml_space_preserve=space,
                    )
                )
            else:
                consume(child, space)
            append_text(child.tail or "", space)

    consume(element, xml_space_preserve)
    flush_paragraph()
    return result


def _tei_citation_blocks(element, *, xml_space_preserve):
    """Normalize a bounded citation shape beside its parser-owned sources."""
    children = tuple(element)
    if not children:
        groups = ((element, (element,)),)
    else:
        inline_names = {"quote", "bibl", "hi", "ref"}
        names = {_local_name(child.tag) for child in children}
        if (
            project_visible_text(element.text or "")
            or any(project_visible_text(child.tail or "") or len(child)
                   for child in children)
            or any(child.tag not in {
                _local_name(child.tag),
                "{http://www.tei-c.org/ns/1.0}" + _local_name(child.tag),
            } for child in children)
            or not (names <= inline_names or names == {"p"})
            or (names == {"p"} and pointer_review_label(element))
        ):
            raise RendererError("Body provenance requires a plain bounded citation")
        if names == {"p"}:
            groups = tuple((child, (element, child)) for child in children)
        else:
            groups = ((element, (element, *children)),)
    blocks = []
    space = _tei_preserves_space(element, xml_space_preserve)
    for source, owners in groups:
        for node_type, text in _tei_readable_blocks(source, xml_space_preserve=space):
            blocks.append((node_type, text, owners))
    return blocks


def _tei_plain_verse_sources(
    element: ElementTree.Element,
) -> tuple[ElementTree.Element, ...]:
    """Capture one plain line/stanza's owners before string aggregation.

    Empty lines own stanza separators too; direct empty page markers own
    their existing labels. Direct childless highlights and plain segments
    retain their own identities; nested stanzas and other inline elements
    fail closed.
    This check runs only for the opt-in body provenance observer.
    """
    def plain_line(line: ElementTree.Element) -> bool:
        if line.tag not in {"l", "{http://www.tei-c.org/ns/1.0}l"}:
            return False
        for child in line:
            if child.tag in {"lb", "{http://www.tei-c.org/ns/1.0}lb"}:
                if len(child) or child.text:
                    return False
            elif child.tag in {"hi", "{http://www.tei-c.org/ns/1.0}hi"}:
                if len(child):
                    return False
            elif child.tag in {"seg", "{http://www.tei-c.org/ns/1.0}seg"}:
                if len(child) or "type" in child.attrib:
                    return False
            else:
                return False
        return True

    if plain_line(element):
        return (element, *element)

    def plain_page_marker(marker: ElementTree.Element) -> bool:
        # The existing stanza renderer inserts this explicit marker's label
        # into its line sequence. No numbered page or displayed text is inferred.
        return (
            marker.tag in {"pb", "{http://www.tei-c.org/ns/1.0}pb"}
            and not len(marker)
            and not (marker.text or "")
        )

    if (
        _local_name(element.tag) == "lg"
        and not project_visible_text(element.text or "")
        and all(
            (plain_line(child) or plain_page_marker(child))
            and not project_visible_text(child.tail or "")
            for child in element
        )
    ):
        return (element, *(owner for child in element for owner in (child, *child)))
    raise RendererError("verse provenance requires a plain line or flat plain stanza")


def _tei_plain_hymn_sources(
    element: ElementTree.Element,
) -> tuple[ElementTree.Element, ...]:
    """Bind direct hymn text and empty line markers before projection."""
    if (
        _local_name(element.tag) == "ab"
        and element.attrib.get("type") == "hymn-text"
        and all(
            child.tag in {"lb", "{http://www.tei-c.org/ns/1.0}lb"}
            and not len(child)
            and not (child.text or "")
            for child in element
        )
    ):
        return (element, *element)
    raise RendererError("hymn-text provenance requires plain text and empty line markers")


def _tei_verse_blocks(
    element: ElementTree.Element, *, xml_space_preserve: bool = False
) -> list[tuple[str, str]]:
    """Keep TEI verse lines and stanza boundaries, including inline note order."""
    space = _tei_preserves_space(element, xml_space_preserve)
    if _local_name(element.tag) == "l":
        return _tei_readable_blocks(
            element, preserve_whitespace=True, xml_space_preserve=space
        )
    result: list[tuple[str, str]] = []
    lines: list[str] = []

    def flush_stanza() -> None:
        if lines and any(line.strip() for line in lines):
            result.append(("preformatted", "\n".join(lines)))
        lines.clear()

    if project_visible_text(element.text or ""):
        result.append(("paragraph", project_visible_text(element.text or "")))
    for child in element:
        name = _local_name(child.tag)
        if name in _TEI_SUPPRESSED:
            continue
        if name == "l":
            blocks = _tei_readable_blocks(
                child, preserve_whitespace=True, xml_space_preserve=space
            )
            if not blocks:
                lines.append("")
            elif len(blocks) == 1 and blocks[0][0] == "preformatted":
                lines.append(blocks[0][1])
            else:
                flush_stanza()
                result.extend(blocks)
        elif name == "pb":
            lines.append(page_break_label(child))
        elif name in {"cb", "milestone"}:
            pass
        elif name in {"note", "gap"}:
            flush_stanza()
            text = project_visible_text(_tei_readable_text(child))
            if text.strip():
                result.append(("blockquote" if name == "note" else "paragraph", text))
        else:
            flush_stanza()
            result.extend(
                _tei_verse_blocks(child, xml_space_preserve=space)
                if name == "lg"
                else _tei_readable_blocks(child, xml_space_preserve=space)
            )
        tail = project_visible_text(child.tail or "")
        if tail:
            flush_stanza()
            result.append(("paragraph", tail))
    flush_stanza()
    return result


def _tei_plain_entry_sources(
    element: ElementTree.Element,
) -> tuple[ElementTree.Element, ...]:
    """Bind plain atomic entries before the renderer selects and joins fields.

    Support childless fields, including one form/orth or sense/def wrapper.
    Empty fields add no separator in the existing renderer. Wrapper identity
    accompanies its selected fields; mixed or deeper content remains rejected.
    """
    if not len(element):
        return (element,)
    def reject() -> None:
        raise RendererError(
            "entry provenance requires a plain entry or flat plain fields "
            "with at most one form/orth or sense/def wrapper"
        )

    if project_visible_text(element.text or ""):
        reject()
    owners = [element]
    for child in element:
        if project_visible_text(child.tail or ""):
            reject()
        name = _local_name(child.tag)
        if name in {"orth", "def"}:
            fields = [child]
        elif name in {"form", "sense"}:
            expected = "orth" if name == "form" else "def"
            if project_visible_text(child.text or "") or any(
                _local_name(field.tag) != expected
                or project_visible_text(field.tail or "") for field in child
            ):
                reject()
            fields = list(child)
        else:
            reject()
        if any(len(field) for field in fields):
            reject()
        selected = [field for field in fields
                    if project_visible_text(field.text or "").strip()]
        if selected:
            if name in {"form", "sense"}:
                owners.append(child)
            owners.extend(selected)
    return tuple(owners)


def _tei_plain_note_sources(
    element: ElementTree.Element,
) -> tuple[ElementTree.Element, ...]:
    """Bind a note's paragraph/citation owners before text projection.

    The renderer concatenates child text without inventing separators.
    Retain every child owner, including empty children; this is element
    provenance, not a claim that each owner contributes visible characters.
    """
    if not len(element):
        return (element,)
    def plain_citation_children(child: ElementTree.Element) -> bool:
        return (
            _local_name(child.tag) == "cit"
            and not project_visible_text(child.text or "")
            and all(
                grandchild.tag in {
                    name for local in ("quote", "bibl", "hi", "ref")
                    for name in (local, "{http://www.tei-c.org/ns/1.0}" + local)
                }
                and not len(grandchild)
                and not project_visible_text(grandchild.tail or "")
                for grandchild in child
            )
        )

    if project_visible_text(element.text or "") or any(
        child.tag not in {
            "p", "cit", "{http://www.tei-c.org/ns/1.0}p",
            "{http://www.tei-c.org/ns/1.0}cit",
        }
        or (len(child) and not plain_citation_children(child))
        or project_visible_text(child.tail or "")
        for child in element
    ):
        raise RendererError(
            "Body provenance requires a childless plain note or flat plain paragraphs/citations"
        )
    return (element, *(owner for child in element for owner in (child, *child)))


def _tei_entry_readable_text(element: ElementTree.Element) -> str:
    """Keep one dictionary entry atomic while separating its source fields."""
    fields = []
    for descendant in element.iter():
        if _local_name(descendant.tag) not in {"orth", "def"}:
            continue
        text = project_visible_text(_tei_readable_text(descendant))
        if text.strip():
            fields.append(text)
    if fields:
        return " ".join(fields)
    return project_visible_text(_tei_readable_text(element))


def render_tei(media_type: str, exact: str) -> dict[str, Any]:
    if _ENTITY_DECLARATION.search(exact) or _INTERNAL_DTD_SUBSET.search(exact):
        raise RendererError(
            "TEI artifact declares an XML entity or internal DTD subset; "
            "only a subset-free DOCTYPE is permitted"
        )
    try:
        root = ElementTree.fromstring(exact)
    except ElementTree.ParseError as error:
        raise RendererError(f"TEI artifact is malformed: {error}") from error
    from cvw_app.hymn_tei import hymn_tei_book
    from cvw_app.usfm_books import usfm_tei_book
    from cvw_app.toml_books import toml_tei_book
    book = (hymn_tei_book(root) or usfm_tei_book(root) or toml_tei_book(root)) if _local_name(root.tag) == 'TEI' else None
    if book is not None:
        return book
    rendered = _render_tei_root(root)
    from cvw_app.json_books import semantic_json_book, catechism_layout
    from cvw_app.xml_books import jats_tei_book
    from cvw_app.toml_books import toml_tei_book
    book = semantic_json_book(root) or catechism_layout(root, rendered) or jats_tei_book(root) or toml_tei_book(root)
    if book is not None:
        book["limitations"] = rendered.get("limitations", [])
        return book
    return rendered


def _render_tei_root(
    root: ElementTree.Element,
    *,
    _on_outline_node: Callable[[ElementTree.Element, dict[str, Any]], None] | None = None,
    _on_fragment: Callable[[ElementTree.Element, ElementTree.Element], None] | None = None,
    _on_table_node: Callable[[ElementTree.Element, dict[str, Any]], None] | None = None,
    _on_body_node: Callable[..., None] | None = None,
    _on_context_replacement: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Render an already parsed tree using the unchanged global allocator.

    The WU-13 indexed parser can retain element identities through this seam.
    The optional outline callback receives the actual source element and node
    at construction time. The fragment callback binds synthetic roots and exact
    deepcopy identities to their contributing elements before visiting them.
    The table callback receives cells, rows, and tables at construction time,
    including intermediate rows in tables that produce no reader output.
    The body callback receives supported inline paragraphs/headings and list/
    blockquote wrappers after their fields are assigned. Explicit replacements
    mark list-item mutations; inline source handles survive normalization.
    Context replacement receives the selected live body nodes and the actual
    SHA-marked replacement before the finalizer discards those selected nodes.
    Unsupported specialized body branches have no callback. Consumers must
    check coverage and reject unbound final or split-page nodes.
    """
    if _local_name(root.tag) not in {"TEI", "teiCorpus"}:
        raise RendererError("TEI artifact root must be TEI or teiCorpus")
    nodes: list[dict[str, Any]] = []
    carrier_details: list[str] = []
    outline: list[dict[str, Any]] = []
    locations = _StructureLocations()
    corpus_work_breaks: set[int] = set()
    parents: dict[ElementTree.Element, ElementTree.Element] = {}
    parents_with_note_children: set[ElementTree.Element] = set()
    for parent in root.iter():
        for child in parent:
            parents[child] = parent
            if _local_name(child.tag) == "note":
                parents_with_note_children.add(parent)

    def body_emitted(element, node, sources=(), *, replacement=False):
        if _on_body_node is not None:
            _on_body_node(element, node, sources, replacement=replacement)

    def body_inline(node_type, element, **extra):
        sources = []
        node = inline_node(
            node_type, element,
            _on_contributions=(lambda node, owners: sources.extend(owners))
            if _on_body_node is not None else None, **extra)
        return node, tuple(sources)

    def fragment_for(source: ElementTree.Element, tag: str, attributes=None):
        fragment = ElementTree.Element(tag, attributes or {})
        if _on_fragment is not None:
            _on_fragment(source, fragment)
        return fragment

    def copy_fragment(source: ElementTree.Element) -> ElementTree.Element:
        if _on_fragment is None:
            return deepcopy(source)
        memo: dict[int, Any] = {}
        copied = deepcopy(source, memo)
        # deepcopy's identity memo binds each original to its actual copy.
        # Never infer this relationship from matching IDs, text, or positions.
        for original in source.iter():
            _on_fragment(original, memo[id(original)])
        return copied

    def enclosing_source_sha256(element: ElementTree.Element) -> str:
        container = element
        while _local_name(container.tag) != "TEI":
            parent = parents.get(container)
            if parent is None:
                raise RendererError(
                    "base64 application/JSON carrier is outside an enclosing TEI work"
                )
            container = parent
        headers = [
            child for child in container if _local_name(child.tag) == "teiHeader"
        ]
        if len(headers) != 1:
            raise RendererError(
                "base64 application/JSON carrier requires one enclosing TEI header"
            )
        digests = [
            project_visible_text(item.text or "")
            for item in headers[0].iter()
            if _local_name(item.tag) == "idno" and item.attrib.get("type") == "sha256"
        ]
        if len(set(digests)) != 1 or any(re.fullmatch(r"[0-9a-f]{64}", digest) is None for digest in digests):
            raise RendererError(
                "base64 application/JSON carrier requires one lowercase source SHA-256"
            )
        return digests[0]

    def visit(
        element: ElementTree.Element,
        depth: int,
        location: str | None,
        emit_own: bool = True,
        xml_space_preserve: bool = False,
    ) -> None:
        name = _local_name(element.tag)
        space = _tei_preserves_space(element, xml_space_preserve)
        if name in _TEI_SUPPRESSED:
            return
        next_location = (
            element.attrib.get(_TEI_XML_ID, location) if name == "div" else location
        )
        # Heading depth counts TEI <div> nesting only; non-structural wrappers
        # (TEI, text, body) do not deepen the published outline levels.
        next_depth = depth + 1 if name == "div" else depth
        unit_type = element.get("type")
        unit_label = None
        if name == "div" and unit_type == "day" and element.get("n"):
            unit_label = element.get("n")
        elif name == "ab" and unit_type == "sword-slot" and project_visible_text(_tei_readable_text(element)):
            unit_label = (element.get("subtype") or "").partition(":")[2] or element.get("n")
        if unit_label and element.get(_TEI_XML_ID):
            unit_location = locations.allocate(element.get(_TEI_XML_ID), len(outline) + 1)
            anchor = _node("heading", "", level=1, location=unit_location)
            nodes.append(anchor)
            outline.append({"location": unit_location, "label": unit_label, "level": 1})
            if _on_outline_node is not None:
                _on_outline_node(element, anchor)
            body_emitted(element, anchor)
        # These are reader labels for explicit TEI structure, not source prose.
        # Keep existing chapter headings and ordinary/nonempty blocks unchanged.
        if name == "div" and element.get("type") == "chapter" and not any(
            _local_name(child.tag) == "head" for child in element
        ):
            number = project_visible_text(element.get("n") or "").strip()
            chapter_node = _node(
                "paragraph", f"[Chapter: {number}]" if number else "[Chapter]"
            )
            nodes.append(chapter_node)
            body_emitted(element, chapter_node)
        if (
            name == "ab" and element.get("type") == "verse"
            and not len(element) and not element.text
        ):
            number = project_visible_text(element.get("n") or "").strip()
            label = f"Verse {number}" if number else "Verse"
            verse_node = _node("paragraph", f"[{label}: empty text]")
            nodes.append(verse_node)
            body_emitted(element, verse_node)
            return
        if name == "list" and element.get("type") == "source-metadata" and not any(_local_name(child.tag) == "head" for child in element.iter()):
            fragment = copy_fragment(element)
            fragment.attrib.pop("type")
            before = len(nodes)
            visit(fragment, depth, location, xml_space_preserve=space)
            children = nodes[before:]
            del nodes[before:]
            if children:
                nodes.append(_node("details", "Source details", children=children))
                body_emitted(element, nodes[-1])
            return
        if name == "quote" and element.get("type") == "block":
            before = len(nodes)
            block_children = _TEI_TEXT_BLOCKS - {"quote"} | {
                "div",
                "head",
                "lg",
                "list",
                "table",
            }
            if any(
                _local_name(child.tag) in block_children
                or (
                    _local_name(child.tag) == "quote"
                    and child.get("type") == "block"
                )
                for child in element
            ):
                # Visit existing TEI blocks directly so a paragraph isn't
                # nested inside a synthetic paragraph and its inline marks lost.
                fragment = fragment_for(element, "p")
                fragment.text = element.text
                for child in element:
                    child_name = _local_name(child.tag)
                    is_block = child_name in block_children or (
                        child_name == "quote" and child.get("type") == "block"
                    )
                    if is_block:
                        visit(fragment, depth, location, xml_space_preserve=space)
                        visit(child, depth, location, xml_space_preserve=space)
                        fragment = fragment_for(element, "p")
                        fragment.text = child.tail
                    else:
                        fragment.append(copy_fragment(child))
                visit(fragment, depth, location, xml_space_preserve=space)
            else:
                # Reuse paragraph rendering for directly inline quoted content.
                content = copy_fragment(element)
                content.tag = "p"
                visit(content, depth, location, xml_space_preserve=space)
            children = nodes[before:]
            del nodes[before:]
            if children:
                nodes.append(_node("blockquote", "", children=children))
                body_emitted(element, nodes[-1])
            return
        if name in {"p", "ab", "item", "quote"} and any(
            _local_name(child.tag) == "quote" and child.get("type") == "block"
            for child in element
        ):
            # Split inline runs at block quotes instead of flattening the paragraph.
            fragment = fragment_for(element, element.tag, element.attrib)
            fragment.text = element.text
            for child in element:
                if _local_name(child.tag) == "quote" and child.get("type") == "block":
                    visit(fragment, depth, location, xml_space_preserve=space)
                    visit(child, depth, location, xml_space_preserve=space)
                    fragment = fragment_for(element, element.tag, element.attrib)
                    fragment.text = child.tail
                else:
                    fragment.append(copy_fragment(child))
            visit(fragment, depth, location, xml_space_preserve=space)
            return
        if name == "l" or (
            name == "lg"
            and not any(_local_name(child.tag) == "head" for child in element.iter())
        ):
            # Bind exact source handles before the verse renderer joins lines.
            # A plain stanza has at most one output block; no text/position
            # lookup is used to recover ownership after aggregation.
            sources = _tei_plain_verse_sources(element) if _on_body_node else ()
            blocks = _tei_verse_blocks(element, xml_space_preserve=space)
            if _on_body_node and len(blocks) > 1:
                raise RendererError("plain verse provenance has ambiguous block ownership")
            for node_type, text in blocks:
                node = _node(node_type, text)
                nodes.append(node)
                body_emitted(element, node, sources)
            return
        if name == "list":
            items = []
            pending_labels = []

            def flush_items():
                if items:
                    nodes.append(
                        _node(
                            "list",
                            "",
                            ordered=element.attrib.get("type")
                            in {"ordered", "numbered"},
                            children=list(items),
                        )
                    )
                    body_emitted(element, nodes[-1])
                    items.clear()

            for child in element:
                child_name = _local_name(child.tag)
                if child_name not in {"item", "label"}:
                    flush_items()
                    nodes.extend(pending_labels)
                    pending_labels.clear()
                    visit(child, next_depth, next_location, xml_space_preserve=space)
                    continue
                before = len(nodes)
                visit(child, next_depth, next_location, xml_space_preserve=space)
                content = nodes[before:]
                del nodes[before:]
                if child_name == "label":
                    pending_labels.extend(content)
                    continue
                for block in content:
                    if block["type"] == "list-item" and "children" not in block:
                        block["type"] = "paragraph"
                        body_emitted(child, block, replacement=True)
                items.append(
                    _node("list-item", "", children=[*pending_labels, *content])
                )
                body_emitted(child, items[-1])
                pending_labels.clear()
            flush_items()
            nodes.extend(pending_labels)
            return
        if element.attrib.get("type") == "json-null":
            nodes.append(_node("paragraph", "null"))
            return
        if name == "table":
            table_rows: list[dict[str, Any]] = []
            table_has_explicit_cell = False
            for row in element.iter():
                if _local_name(row.tag) != "row":
                    continue
                cells = []
                for cell in row:
                    cell_name = _local_name(cell.tag)
                    if cell_name not in {"cell", "head"}:
                        continue
                    table_has_explicit_cell = True
                    text = project_visible_text(_tei_readable_text(cell))
                    extra: dict[str, object] = {}
                    colspan = _parse_table_span(
                        cell.attrib.get("cols"), "cols", MAX_TABLE_COLSPAN
                    )
                    rowspan = _parse_table_span(
                        cell.attrib.get("rows"), "rows", MAX_TABLE_ROWSPAN
                    )
                    if colspan is not None:
                        extra["colspan"] = colspan
                    if rowspan is not None:
                        extra["rowspan"] = rowspan
                    if (cell.attrib.get("role") or "").lower() == "label":
                        cells.append(
                            inline_node("table-header", cell, scope="row", **extra)
                        )
                    else:
                        cells.append(inline_node("table-cell", cell, **extra))
                    if _on_table_node is not None:
                        _on_table_node(cell, cells[-1])
                table_rows.append(_node("table-row", "", children=cells))
                if _on_table_node is not None:
                    _on_table_node(row, table_rows[-1])
            if table_rows and table_has_explicit_cell:
                nodes.append(_node("table", "", children=table_rows))
                if _on_table_node is not None:
                    _on_table_node(element, nodes[-1])
            return
        if name in _TEI_DICTIONARY_ENTRY_TYPES:
            sources = _tei_plain_entry_sources(element) if _on_body_node else ()
            text = _tei_entry_readable_text(element)
            if text.strip():
                node = _node("paragraph", text)
                if element.get(_TEI_XML_ID):
                    entry_location = locations.allocate(element.get(_TEI_XML_ID), len(outline) + 1)
                    label = next((project_visible_text(_tei_readable_text(child)) for child in element.iter() if _local_name(child.tag) == "orth"), element.get("n") or text)
                    node["location"] = entry_location
                    outline.append({"location": entry_location, "label": label, "level": 6})
                    if _on_outline_node is not None:
                        _on_outline_node(element, node)
                nodes.append(node)
                body_emitted(element, node, sources)
            return
        if (
            name == "div"
            and element.attrib.get("type") == "complete-xml-node-transcription"
        ):
            records = list(element)
            if not records:
                raise RendererError("complete XML node ledger is empty")
            for ordinal, record_element in enumerate(records, 1):
                if (
                    _local_name(record_element.tag) != "ab"
                    or record_element.attrib.get("type") != "source-xml-node"
                    or record_element.attrib.get("n") != str(ordinal)
                    or list(record_element)
                ):
                    raise RendererError("complete XML node ledger topology drifted")
                try:
                    record = json.loads(record_element.text or "")
                except json.JSONDecodeError as error:
                    raise RendererError(
                        "complete XML node ledger contains invalid JSON"
                    ) from error
                feature_id = record_element.attrib.get(_TEI_XML_ID)
                kind = record_element.attrib.get("subtype")
                if (
                    not isinstance(record, dict)
                    or record.get("feature_id") != feature_id
                    or record.get("ordinal") != ordinal
                    or record.get("kind") != kind
                    or not isinstance(record.get("payload_sha256"), str)
                ):
                    raise RendererError("complete XML node ledger identity drifted")
                expected_digest = record.pop("payload_sha256")
                payload = (
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
                if hashlib.sha256(payload).hexdigest() != expected_digest:
                    raise RendererError(
                        "complete XML node ledger payload digest drifted"
                    )
            nodes.append(
                _node(
                    "paragraph",
                    f"Complete XML node ledger: {len(records)} identity-bound records verified. "
                    "CVW keeps record JSON outside the readable projection; the exact TEI route preserves it.",
                )
            )
            return
        if (
            emit_own
            and name == "ab"
            and element.attrib.get("type") == "exact-retained-source-bytes"
        ):
            subtype = element.attrib.get("subtype")
            expected_sha256 = element.attrib.get("n", "")
            if (
                subtype != "base64"
                or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            ):
                raise RendererError(
                    "exact retained-source byte carrier must declare base64 and lowercase SHA-256"
                )
            encoded = "".join(_tei_readable_text(element).split())
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as error:
                raise RendererError(
                    "exact retained-source byte carrier is not valid base64"
                ) from error
            observed_sha256 = hashlib.sha256(decoded).hexdigest()
            if observed_sha256 != expected_sha256:
                raise RendererError(
                    "exact retained-source byte carrier does not match its declared SHA-256"
                )
            nodes.append(
                _node(
                    "paragraph",
                    "Exact retained source bytes: "
                    f"base64 carrier, {len(decoded)} decoded bytes, "
                    f"SHA-256 {expected_sha256}, {len(encoded)} encoded scalars. "
                    "The identity-bound exact TEI route preserves the complete carrier.",
                )
            )
            return
        if (
            emit_own
            and name == "ab"
            and element.attrib.get("type") == "base64-application-json"
        ):
            parent = parents.get(element)
            if (
                set(element.attrib) != {"type"}
                or list(element)
                or parent is None
                or _local_name(parent.tag) != "div"
                or parent.attrib.get("type") != "retained-byte-stream"
                or list(parent) != [element]
            ):
                raise RendererError("base64 application/JSON carrier topology drifted")
            encoded = element.text or ""
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as error:
                raise RendererError(
                    "base64 application/JSON carrier is not valid base64"
                ) from error
            if base64.b64encode(decoded).decode("ascii") != encoded:
                raise RendererError(
                    "base64 application/JSON carrier is not canonical base64"
                )
            try:
                source_text = decoded.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RendererError(
                    "base64 application/JSON carrier is not UTF-8"
                ) from error
            try:
                json.loads(
                    source_text,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"non-standard JSON constant {value}")
                    ),
                )
            except (json.JSONDecodeError, ValueError) as error:
                raise RendererError(
                    "base64 application/JSON carrier does not decode to valid JSON"
                ) from error
            expected_sha256 = enclosing_source_sha256(element)
            observed_sha256 = hashlib.sha256(decoded).hexdigest()
            if observed_sha256 != expected_sha256:
                raise RendererError(
                    "base64 application/JSON carrier does not match the enclosing source SHA-256"
                )
            carrier_details.append(
                    "Exact retained JSON source bytes: "
                    f"canonical base64 carrier, {len(decoded)} decoded bytes, "
                    f"SHA-256 {expected_sha256}, {len(encoded)} encoded scalars, "
                    "valid UTF-8 JSON. The identity-bound exact TEI route preserves "
                    "the complete carrier; CVW keeps the literal outside the readable projection.",
            )
            return
        source_heading = _source_heading(element)
        if emit_own and (
            source_heading
            or (name == "ab" and element.attrib.get("type") == "source-heading")
        ):
            text = project_visible_text(_tei_readable_text(element))
            if text.strip():
                subtype = (
                    "h" + source_heading.group(1)
                    if source_heading
                    else element.attrib.get("subtype", "")
                )
                level = (
                    int(subtype[1])
                    if re.fullmatch(r"h[1-6]", subtype)
                    else min(6, max(1, next_depth))
                )
                heading_location = locations.allocate(
                    element.attrib.get(_TEI_XML_ID, location)
                    if source_heading
                    else element.attrib.get("corresp", location),
                    len(outline) + 1,
                )
                heading_node, sources = body_inline(
                    "heading", element, level=level, location=heading_location
                )
                if _on_outline_node is not None:
                    _on_outline_node(element, heading_node)
                body_emitted(element, heading_node, sources)
                nodes.append(heading_node)
                outline.append(
                    {"location": heading_location, "label": text, "level": level}
                )
            return
        if emit_own and name == "quote":
            structural_children: list[ElementTree.Element] = []
            transparent = not project_visible_text(element.text or "").strip()
            for child in element:
                child_name = _local_name(child.tag)
                if project_visible_text(child.tail or "").strip():
                    transparent = False
                    break
                if child_name in _TEI_SUPPRESSED:
                    continue
                if child_name == "milestone":
                    if list(child) or project_visible_text(child.text or "").strip():
                        transparent = False
                        break
                    continue
                if child_name not in {"quote", "list"}:
                    transparent = False
                    break
                structural_children.append(child)
            if (
                transparent
                and structural_children
                and any(_local_name(item.tag) == "list" for item in element.iter())
            ):
                # Empty TEI quote wrappers (and their empty milestones) around a
                # block list should not flatten the list before item rendering.
                for child in structural_children:
                    visit(child, next_depth, next_location, xml_space_preserve=space)
                return
        if emit_own and name == "item" and any(
            _local_name(child.tag) == "label" for child in element
        ):
            # A field label is a block boundary, not part of the field value.
            # Reuse normal paragraph rendering to retain inline marks and tails.
            fragment = fragment_for(element, "p")
            fragment.text = element.text
            for child in element:
                if _local_name(child.tag) == "label":
                    visit(fragment, depth, location, xml_space_preserve=space)
                    visit(child, depth, location, xml_space_preserve=space)
                    fragment = fragment_for(element, "p")
                    fragment.text = child.tail
                else:
                    fragment.append(copy_fragment(child))
            visit(fragment, depth, location, xml_space_preserve=space)
            return
        if (
            emit_own
            and name
            in {"p", "ab", "item", "quote", "label", "figDesc", "speaker", "stage"}
            and not any(
                _local_name(child.tag)
                in {"note", "p", "ab", "lg", "l", "list", "item", "gap", "table"}
                or _source_heading(child)
                for child in element.iter()
                if child is not element
            )
            and not (name == "ab" and element.get("type") == "hymn-text")
        ):
            node, sources = body_inline("list-item" if name == "item" else "paragraph", element)
            if name == "p" and element.get("rend") == "align-center":
                node["align"] = "center"
            if node["text"]:
                # Preserve noncollapsible spaces as content, but do not turn
                # a blank paragraph into an unreadable navigation context.
                if (
                    name == "p"
                    and element.get(_TEI_XML_ID)
                    and is_route_valid_scalar_text(node["text"])
                ):
                    paragraph_location = locations.allocate(
                        element.get(_TEI_XML_ID), len(outline) + 1
                    )
                    node["location"] = paragraph_location
                    if _on_outline_node is not None:
                        _on_outline_node(element, node)
                    outline.append(
                        {
                            "location": paragraph_location,
                            "label": node["text"],
                            "level": 6,
                        }
                    )
                body_emitted(element, node, sources)
                nodes.append(node)
            return
        if (
            emit_own
            and name == "item"
            and any(_local_name(child.tag) == "list" for child in element)
        ):
            if project_visible_text(element.text or ""):
                nodes.append(
                    _node("paragraph", project_visible_text(element.text or ""))
                )
            for child in element:
                visit(child, next_depth, next_location, xml_space_preserve=space)
                if project_visible_text(child.tail or ""):
                    nodes.append(
                        _node("paragraph", project_visible_text(child.tail or ""))
                    )
            return
        if emit_own and name in {"head", *_TEI_TEXT_BLOCKS} and not any(_source_heading(child) for child in element.iter() if child is not element):
            if name == "head":
                text = project_visible_text(_tei_readable_text(element))
                if text.strip():
                    heading_location = locations.allocate(location, len(outline) + 1)
                    level = min(6, max(1, next_depth))
                    heading_node, sources = body_inline(
                        "heading", element, level=level, location=heading_location
                    )
                    if _on_outline_node is not None:
                        _on_outline_node(element, heading_node)
                    body_emitted(element, heading_node, sources)
                    nodes.append(heading_node)
                    outline.append(
                        {"location": heading_location, "label": text, "level": level}
                    )
            elif name == "note":
                sources = (
                    _tei_plain_note_sources(element)
                    if _on_body_node is not None else ()
                )
                text = project_visible_text(_tei_readable_text(element))
                if text.strip():
                    node = _node("blockquote", text)
                    body_emitted(element, node, sources)
                    nodes.append(node)
            else:
                if _on_body_node is not None and name == "cit":
                    for node_type, text, sources in _tei_citation_blocks(
                        element, xml_space_preserve=space
                    ):
                        node = _node(node_type, text)
                        body_emitted(element, node, sources)
                        nodes.append(node)
                    return
                readable_blocks = _tei_readable_blocks(
                    element,
                    preserve_whitespace=(
                        name == "ab" and element.attrib.get("type") == "hymn-text"
                    ),
                    xml_space_preserve=space,
                )
                hymn_sources = ()
                if _on_body_node is not None and (
                    name == "ab" and element.attrib.get("type") == "hymn-text"
                ):
                    hymn_sources = _tei_plain_hymn_sources(element)
                    if len(readable_blocks) > 1:
                        raise RendererError(
                            "hymn-text provenance has ambiguous block ownership"
                        )
                if (
                    name == "item"
                    and len(readable_blocks) == 1
                    and readable_blocks[0][0] == "paragraph"
                ):
                    nodes.append(_node("list-item", readable_blocks[0][1]))
                else:
                    for node_type, text in readable_blocks:
                        node = _node(node_type, text)
                        if name == "cit" and not len(element):
                            body_emitted(element, node)
                        elif hymn_sources:
                            body_emitted(element, node, hymn_sources)
                        nodes.append(node)
            return
        pending: list[str] = []
        pending_sources: list[ElementTree.Element] = []
        pending_seen: set[ElementTree.Element] = set()
        mixed_handled = False

        def append_pending(value: str, *owners: ElementTree.Element) -> None:
            """Keep source owners beside generic text until its node is emitted."""
            pending.append(value)
            if _on_body_node is None:
                return
            for owner in owners:
                if owner not in pending_seen:
                    pending_seen.add(owner)
                    pending_sources.append(owner)

        def flush_pending() -> None:
            text = project_visible_text("".join(pending))
            pending.clear()
            sources = tuple(pending_sources)
            pending_sources.clear()
            pending_seen.clear()
            if text.strip():
                if _on_body_node is not None and mixed_handled:
                    raise RendererError(
                        "generic mixed body provenance lacks construction identity"
                    )
                node = _node("paragraph", text)
                body_emitted(element, node, sources)
                nodes.append(node)

        def collect_unhandled(item: ElementTree.Element) -> None:
            """Emit generic text around handled children in source order."""
            nonlocal mixed_handled
            append_pending(pointer_review_label(item), item)
            append_pending(item.text or "", item)
            for child in item:
                child_name = _local_name(child.tag)
                if child_name in _TEI_SUPPRESSED:
                    continue
                if child_name in _TEI_LEAF_HANDLED or _source_heading(child) or _contains_handled_descendant(
                    child
                ):
                    mixed_handled = True
                    flush_pending()
                    visit(child, next_depth, next_location, xml_space_preserve=space)
                elif child_name == "lb":
                    if (child.attrib.get("break") or "").lower() != "no":
                        append_pending("\n", child)
                else:
                    append_pending(_tei_readable_text(child), *child.iter())
                append_pending(child.tail or "", *child.iter())

        collect_unhandled(element)
        flush_pending()
        return

    if _local_name(root.tag) == "teiCorpus":
        work_count = 0
        for child in root:
            if _local_name(child.tag) != "TEI":
                continue
            work_count += 1
            before = len(nodes)
            visit(child, 0, None, xml_space_preserve=_tei_preserves_space(root, False))
            if len(nodes) == before:
                raise RendererError("TEI corpus child has no readable content")
            if before:
                corpus_work_breaks.add(before)
        if work_count == 0:
            raise RendererError("TEI corpus has no child TEI works")
    else:
        visit(root, 0, None)
    if not nodes:
        raise RendererError("TEI artifact has no readable heading or paragraph content")
    rendered = _finalize_structure(
        "tei-reader",
        nodes,
        outline,
        _heading_contexts(nodes, outline, include_nested=True),
        hard_break_before=corpus_work_breaks,
        _on_context_replacement=_on_context_replacement,
    )
    limitations = list(carrier_details)
    for ordinal, element in enumerate(root.iter(), 1):
        name = _local_name(element.tag)
        locus = element.get(_TEI_XML_ID) or f"element-{ordinal}"
        reason = None
        if name in {"hi", "emph"}:
            from cvw_app.tei_inline import MARKS

            unknown = [
                token
                for token in (element.get("rend") or "").split()
                if token.lower() not in MARKS
            ]
            if unknown:
                reason = "Unknown emphasis rendition is shown as text: " + " ".join(
                    unknown
                )
            parent = parents.get(element)
            while parent is not None:
                if _local_name(parent.tag) in {"note", "l", "lg", "entry", "entryFree"}:
                    reason = "Inline typography in this specialized block is not fully projected"
                    break
                if parent in parents_with_note_children:
                    reason = (
                        "Inline typography around a note requires exact-TEI inspection"
                    )
                    break
                parent = parents.get(parent)
        elif name == "note":
            reason = "Note content is displayed separately; original inline paragraph continuity and backlinks require exact-TEI inspection"
        elif name == "ref" and element.get("target"):
            reason = (
                "Reference text is visible; its target relationship is not interactive"
            )
        if reason:
            limitations.append(f"{locus}: {reason}"[:1000])
    if limitations:
        rendered["limitations"] = limitations[:32] + (
            [
                f"{len(limitations) - 32} additional presentation limitations; inspect exact TEI."
            ]
            if len(limitations) > 32
            else []
        )
    if corpus_work_breaks:
        rendered["_hard_break_before"] = sorted(corpus_work_breaks)
    return rendered
