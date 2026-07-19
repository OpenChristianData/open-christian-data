"""Convert Standard Ebooks XHTML into the TEI intermediate representation."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.writer import TEI_NS, serialize, stamp_header, tei_el

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_LANG = f"{{{XML_NS}}}lang"
EPUB_TYPE = f"{{{EPUB_NS}}}type"

NS = {"x": XHTML_NS, "opf": "http://www.idpf.org/2007/opf"}

SECTION_TYPE_MAP = {
    "appendix": "appendix",
    "chapter": "chapter",
    "colophon": "colophon",
    "copyright-page": "copyright-page",
    "dedication": "dedication",
    "division": "book",
    "epigraph": "epigraph",
    "foreword": "foreword",
    "halftitlepage": "halftitlepage",
    "introduction": "introduction",
    "imprint": "imprint",
    "part": "part",
    "preamble": "preamble",
    "preface": "preface",
    "z3998:subchapter": "subchapter",
    "titlepage": "titlepage",
}

BODY_MATTER_TYPES = {"bodymatter", "frontmatter", "backmatter", "z3998:fiction", "z3998:non-fiction"}
HEADING_TYPES = {"title", "fulltitle", "z3998:ordinal", "z3998:roman"}
TYPOGRAPHIC_TYPES = {
    "se:era",
    "se:image.color-depth.black-on-transparent",
    "se:label",
    "se:name.publication",
    "se:name.publication.book",
    "se:name.publication.essay",
    "se:name.publication.play",
    "se:name.publication.poem",
    "se:name.visual-art.painting",
    "se:name.visual-art.typeface",
    "z3998:author",
    "z3998:given-name",
    "z3998:grapheme",
    "z3998:initialism",
    "z3998:name-title",
    "z3998:ordinal",
    "z3998:personal-name",
    "z3998:place",
    "z3998:publisher-logo",
    "z3998:roman",
    "z3998:signature",
    "z3998:surname",
    "z3998:translator",
    "title",
    "label",
    "ordinal",
    "z3998:subchapter",
}


class ConversionError(ValueError):
    """Raised when Standard Ebooks XHTML contains content with no TEI ruling."""


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    typographic_mappings: tuple[str, ...]


@dataclass
class _State:
    endnotes: dict[str, etree._Element]
    book_n: int = 0
    chapter_n_by_book: dict[str, int] = field(default_factory=dict)
    typographic_mappings: set[str] = field(default_factory=set)


def _parse_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False, remove_blank_text=False)
    try:
        return etree.parse(str(path), parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ConversionError(f"Could not parse XML at {path.as_posix()}: {exc}") from exc


def _tokens(node: etree._Element) -> set[str]:
    return set((node.get(EPUB_TYPE) or "").split())


def _source_location(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        local = etree.QName(current).localname
        node_id = current.get("id")
        parts.append(f"{local}#{node_id}" if node_id else local)
        current = current.getparent()
    return " > ".join(reversed(parts))


def _normalise_text(text: str | None) -> str:
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text)
    return "" if collapsed.strip() == "" else collapsed


def _append_text(parent: etree._Element, text: str | None) -> None:
    cleaned = _normalise_text(text)
    if not cleaned:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + cleaned
    else:
        parent.text = (parent.text or "") + cleaned


def _text_content(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _xml_attrs(node: etree._Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    node_id = node.get("id")
    if node_id:
        attrs["xml:id"] = node_id
    lang = node.get(XML_LANG) or node.get("lang")
    if lang:
        attrs["xml:lang"] = lang
    return attrs


def _ana(tokens: set[str]) -> dict[str, str]:
    return {"ana": " ".join(sorted(tokens))} if tokens else {}


def _is_bridgehead(node: etree._Element) -> bool:
    return bool(_tokens(node) & {"se:bridgehead", "bridgehead"})


def _assert_known_types(node: etree._Element, allowed: set[str]) -> None:
    unknown = _tokens(node) - allowed
    if unknown:
        raise ConversionError(
            f"No TEI mapping for epub:type {', '.join(sorted(unknown))!r} at {_source_location(node)}"
        )


def _copy_children(source: etree._Element, target: etree._Element, state: _State) -> None:
    _append_text(target, source.text)
    for child in source:
        tag = etree.QName(child).localname
        if tag == "br":
            target.append(tei_el("lb", _xml_attrs(child)))
        elif tag == "img":
            _assert_known_types(child, TYPOGRAPHIC_TYPES)
        else:
            converted = _convert_inline(child, state)
            if converted is not None:
                target.append(converted)
        _append_text(target, child.tail)


def _convert_inline(node: etree._Element, state: _State) -> etree._Element | None:
    tag = etree.QName(node).localname
    tokens = _tokens(node)

    if tag == "a":
        if "backlink" in tokens:
            return None
        if "noteref" in tokens:
            return _convert_noteref(node, state)
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        out = tei_el("ref", {**_xml_attrs(node), **_ana(tokens)})
        href = node.get("href")
        if href:
            out.set("target", href)
    elif tag == "abbr":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        state.typographic_mappings.add("abbr -> abbr @ana")
        out = tei_el("abbr", {**_xml_attrs(node), **_ana(tokens)})
    elif tag in {"b", "strong"}:
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        state.typographic_mappings.add(f"{tag} -> hi rend='bold' @ana")
        out = tei_el("hi", {**_xml_attrs(node), "rend": "bold", **_ana(tokens)})
    elif tag == "cite":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        state.typographic_mappings.add("cite -> title @ana")
        out = tei_el("title", {**_xml_attrs(node), **_ana(tokens)})
    elif tag == "em":
        if tokens:
            _assert_known_types(node, TYPOGRAPHIC_TYPES)
        out = tei_el("emph", {**_xml_attrs(node), **_ana(tokens)})
    elif tag == "i":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        if tokens:
            state.typographic_mappings.add("semantic i -> hi rend='italic' @ana")
        out = tei_el("hi", {**_xml_attrs(node), "rend": "italic", **_ana(tokens)})
    elif tag == "small":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        state.typographic_mappings.add("small -> hi rend='small' @ana")
        out = tei_el("hi", {**_xml_attrs(node), "rend": "small", **_ana(tokens)})
    elif tag == "span":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        if tokens:
            state.typographic_mappings.add("semantic span -> seg @ana")
        out = tei_el("seg", {**_xml_attrs(node), **_ana(tokens)})
    elif tag == "sub":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        state.typographic_mappings.add("sub -> hi rend='subscript' @ana")
        out = tei_el("hi", {**_xml_attrs(node), "rend": "subscript", **_ana(tokens)})
    elif tag == "sup":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        state.typographic_mappings.add("sup -> hi rend='superscript' @ana")
        out = tei_el("hi", {**_xml_attrs(node), "rend": "superscript", **_ana(tokens)})
    elif tag == "time":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        out = tei_el("date", _xml_attrs(node))
        datetime_value = node.get("datetime")
        if datetime_value:
            out.set("when", datetime_value)
    elif tag == "q":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        out = tei_el("q", {**_xml_attrs(node), **_ana(tokens)})
    else:
        raise ConversionError(f"No TEI mapping for XHTML tag <{tag}> at {_source_location(node)}")

    _copy_children(node, out, state)
    return out


def _convert_noteref(node: etree._Element, state: _State) -> etree._Element:
    href = node.get("href", "")
    note_id = href.rsplit("#", 1)[-1] if "#" in href else ""
    source_note = state.endnotes.get(note_id)
    if source_note is None:
        raise ConversionError(f"Noteref {node.get('id')!r} points to missing endnote {note_id!r}")
    noteref_id = node.get("id")
    attrs = {
        "place": "end",
        "n": _text_content(node),
        "xml:id": note_id,
    }
    if noteref_id:
        attrs["corresp"] = f"#{noteref_id}"
    out = tei_el("note", attrs)
    _copy_note_children(source_note, out, state)
    return out


def _copy_note_children(source: etree._Element, target: etree._Element, state: _State) -> None:
    _append_text(target, source.text)
    for child in source:
        tag = etree.QName(child).localname
        if tag == "p":
            paragraph = tei_el("p", _xml_attrs(child))
            _copy_children(child, paragraph, state)
            target.append(paragraph)
        elif tag == "blockquote":
            target.append(_convert_blockquote(child, state))
        elif tag == "cite":
            title = tei_el("title", _xml_attrs(child))
            _copy_children(child, title, state)
            target.append(title)
        else:
            converted = _convert_inline(child, state)
            if converted is not None:
                target.append(converted)
        _append_text(target, child.tail)


def _convert_heading(node: etree._Element, state: _State) -> etree._Element:
    _assert_known_types(node, HEADING_TYPES | TYPOGRAPHIC_TYPES)
    head = tei_el("head", _xml_attrs(node))
    _copy_children(node, head, state)
    return head


def _convert_p(node: etree._Element, state: _State) -> etree._Element:
    tokens = _tokens(node)
    _assert_known_types(node, {"se:bridgehead", "bridgehead", "z3998:signature", "title"})
    p = tei_el("p", {**_xml_attrs(node), **_ana(tokens - {"se:bridgehead", "bridgehead"})})
    _copy_children(node, p, state)
    return p


def _convert_verse_p(node: etree._Element, state: _State) -> list[etree._Element]:
    lines = [tei_el("l")]

    def current_line() -> etree._Element:
        return lines[-1]

    _append_text(current_line(), node.text)
    for child in node:
        if etree.QName(child).localname == "br":
            lines.append(tei_el("l"))
        else:
            converted = _convert_inline(child, state)
            if converted is not None:
                current_line().append(converted)
        _append_text(current_line(), child.tail)
    return [line for line in lines if "".join(line.itertext()).strip() or len(line)]


def _convert_blockquote(node: etree._Element, state: _State) -> etree._Element:
    tokens = _tokens(node)
    _assert_known_types(node, {"z3998:verse", "z3998:song", "z3998:poem", "epigraph"})
    quote = tei_el("quote", _xml_attrs(node))
    if tokens & {"z3998:verse", "z3998:song", "z3998:poem"}:
        lg = tei_el("lg")
        trailing: list[etree._Element] = []
        for child in node:
            child_tag = etree.QName(child).localname
            if child_tag == "p":
                for line in _convert_verse_p(child, state):
                    lg.append(line)
            elif child_tag == "cite":
                bibl = tei_el("bibl", _xml_attrs(child))
                _copy_children(child, bibl, state)
                trailing.append(bibl)
            else:
                raise ConversionError(f"No TEI verse mapping for <{child_tag}> at {_source_location(child)}")
        quote.append(lg)
        for child in trailing:
            quote.append(child)
        return quote

    _copy_block_children(node, quote, state)
    return quote


def _convert_list(node: etree._Element, state: _State) -> etree._Element:
    list_type = "ordered" if etree.QName(node).localname == "ol" else "bulleted"
    out = tei_el("list", {**_xml_attrs(node), "type": list_type})
    for child in node:
        if etree.QName(child).localname != "li":
            raise ConversionError(
                f"No TEI list mapping for <{etree.QName(child).localname}> at {_source_location(child)}"
            )
        item = tei_el("item", _xml_attrs(child))
        _append_text(item, child.text)
        for item_child in child:
            item_tag = etree.QName(item_child).localname
            if item_tag == "p":
                item.append(_convert_p(item_child, state))
            elif item_tag in {"ol", "ul"}:
                item.append(_convert_list(item_child, state))
            else:
                converted = _convert_inline(item_child, state)
                if converted is not None:
                    item.append(converted)
            _append_text(item, item_child.tail)
        out.append(item)
        _append_text(out, child.tail)
    return out


def _convert_hgroup(node: etree._Element, state: _State) -> etree._Element:
    head = tei_el("head", _xml_attrs(node))
    for child in node:
        tag = etree.QName(child).localname
        if tag in {"h1", "h2", "h3", "h4"} or (tag == "p" and "title" in _tokens(child)):
            _copy_children(child, head, state)
        else:
            raise ConversionError(f"No TEI hgroup mapping for <{tag}> at {_source_location(child)}")
        _append_text(head, child.tail)
    return head


def _convert_header_p(node: etree._Element, state: _State) -> etree._Element:
    head = tei_el("head", _xml_attrs(node))
    _copy_children(node, head, state)
    return head


def _copy_block_children(source: etree._Element, target: etree._Element, state: _State) -> None:
    _append_text(target, source.text)
    for child in source:
        converted = _convert_block(child, state)
        if converted is not None:
            target.append(converted)
        _append_text(target, child.tail)


def _convert_block(node: etree._Element, state: _State) -> etree._Element | None:
    tag = etree.QName(node).localname
    if tag in {"h1", "h2", "h3", "h4"}:
        return _convert_heading(node, state)
    if tag == "p":
        if _is_bridgehead(node):
            argument = tei_el("argument")
            argument.append(_convert_p(node, state))
            return argument
        return _convert_p(node, state)
    if tag == "blockquote":
        return _convert_blockquote(node, state)
    if tag in {"ol", "ul"}:
        return _convert_list(node, state)
    if tag == "hgroup":
        return _convert_hgroup(node, state)
    if tag == "cite":
        bibl = tei_el("bibl", _xml_attrs(node))
        _copy_children(node, bibl, state)
        return bibl
    if tag == "header":
        container = tei_el("ab")
        for child in node:
            converted = _convert_block(child, state)
            if converted is not None:
                container.append(converted)
        return container
    if tag == "footer":
        trailer = tei_el("trailer")
        _append_text(trailer, node.text)
        for child in node:
            if etree.QName(child).localname == "p":
                _copy_children(child, trailer, state)
            else:
                converted = _convert_inline(child, state)
                if converted is not None:
                    trailer.append(converted)
            _append_text(trailer, child.tail)
        return trailer
    if tag == "img":
        _assert_known_types(node, TYPOGRAPHIC_TYPES)
        return None
    raise ConversionError(f"No TEI mapping for XHTML tag <{tag}> at {_source_location(node)}")


def _append_header_children(section: etree._Element, div: etree._Element, state: _State) -> set[etree._Element]:
    consumed: set[etree._Element] = set()
    for child in section:
        tag = etree.QName(child).localname
        if tag in {"h1", "h2", "h3", "h4"}:
            div.append(_convert_heading(child, state))
            consumed.add(child)
        elif tag == "header":
            consumed.add(child)
            for header_child in child:
                header_tag = etree.QName(header_child).localname
                if header_tag in {"h1", "h2", "h3", "h4"}:
                    div.append(_convert_heading(header_child, state))
                elif header_tag == "p" and _is_bridgehead(header_child):
                    argument = tei_el("argument")
                    argument.append(_convert_p(header_child, state))
                    div.append(argument)
                elif header_tag == "p":
                    div.append(_convert_header_p(header_child, state))
                elif header_tag == "hgroup":
                    div.append(_convert_hgroup(header_child, state))
                elif header_tag == "blockquote":
                    div.append(_convert_blockquote(header_child, state))
                elif header_tag == "img":
                    _assert_known_types(header_child, TYPOGRAPHIC_TYPES)
                else:
                    raise ConversionError(
                        f"No TEI header mapping for <{header_tag}> at {_source_location(header_child)}"
                    )
        elif tag == "hgroup":
            consumed.add(child)
            div.append(_convert_hgroup(child, state))
    return consumed


def _section_n(section: etree._Element, div_type: str, state: _State, parent_book_id: str | None) -> str:
    section_id = section.get("id", "")
    if div_type == "book":
        state.book_n += 1
        state.chapter_n_by_book[section_id] = 0
        return str(state.book_n)
    if div_type == "chapter":
        if parent_book_id:
            state.chapter_n_by_book[parent_book_id] = state.chapter_n_by_book.get(parent_book_id, 0) + 1
            return str(state.chapter_n_by_book[parent_book_id])
        match = re.search(r"chapter-\d+-(\d+)$", section_id)
        if match:
            return match.group(1)
    match = re.search(r"(\d+)(?:-\d+)?$", section_id)
    return match.group(1) if match else ""


def _convert_section(section: etree._Element, state: _State, parent_book_id: str | None = None) -> etree._Element:
    tokens = _tokens(section)
    if len(tokens) != 1:
        raise ConversionError(f"Section must have one epub:type at {_source_location(section)}")
    source_type = next(iter(tokens))
    try:
        div_type = SECTION_TYPE_MAP[source_type]
    except KeyError as exc:
        raise ConversionError(f"No TEI mapping for section epub:type {source_type!r} at {_source_location(section)}") from exc

    attrs = {**_xml_attrs(section), "type": div_type}
    n = _section_n(section, div_type, state, parent_book_id)
    if n:
        attrs["n"] = n
    div = tei_el("div", attrs)
    consumed = _append_header_children(section, div, state)
    next_parent_book_id = section.get("id") if div_type == "book" else parent_book_id

    for child in section:
        if child in consumed:
            continue
        tag = etree.QName(child).localname
        if tag == "section":
            div.append(_convert_section(child, state, next_parent_book_id))
        else:
            converted = _convert_block(child, state)
            if converted is not None:
                div.append(converted)
    return div


def _spine_paths(work_dir: Path) -> list[Path]:
    opf_path = work_dir / "src" / "epub" / "content.opf"
    if not opf_path.exists():
        raise ConversionError(f"Missing EPUB package file at {opf_path.as_posix()}")
    opf = _parse_xml(opf_path)
    manifest = {
        item.get("id"): item.get("href")
        for item in opf.xpath("//opf:manifest/opf:item[@media-type='application/xhtml+xml']", namespaces=NS)
    }
    paths: list[Path] = []
    for itemref in opf.xpath("//opf:spine/opf:itemref", namespaces=NS):
        href = manifest.get(itemref.get("idref"))
        if href:
            paths.append(opf_path.parent / href)
    return paths


def _endnotes(work_dir: Path) -> dict[str, etree._Element]:
    path = work_dir / "src" / "epub" / "text" / "endnotes.xhtml"
    if not path.exists():
        return {}
    root = _parse_xml(path).getroot()
    return {
        li.get("id"): li
        for li in root.xpath(".//x:li[@id]", namespaces=NS)
        if li.get("id")
    }


def _git_head_or_empty(work_dir: Path) -> str:
    if not (work_dir / ".git").exists():
        return ""
    result = subprocess.run(
        ["git", "-C", str(work_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _section_bucket(path: Path, body_tokens: set[str]) -> str | None:
    if path.name in {"endnotes.xhtml", "toc.xhtml"}:
        return None
    if "frontmatter" in body_tokens:
        return "front"
    if "backmatter" in body_tokens:
        return "back"
    return "body"


def convert_se_to_tei(work_dir: str | Path, config_path: str | Path, output_path: str | Path) -> ConversionResult:
    root_dir = Path(work_dir)
    config_file = Path(config_path)
    output = Path(output_path)
    config = json.loads(config_file.read_text(encoding="utf-8"))
    state = _State(endnotes=_endnotes(root_dir))

    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    tei.append(
        stamp_header(
            title=str(config.get("title") or ""),
            author=str(config.get("author") or ""),
            contributors=[str(item) for item in config.get("contributors", [])],
            source_url=str(config.get("source_url") or ""),
            source_sha256=str(config.get("source_hash") or _git_head_or_empty(root_dir)),
            print_source=str(config.get("source_edition") or ""),
        )
    )

    text = tei_el("text")
    front = tei_el("front")
    body = tei_el("body")
    back = tei_el("back")

    for path in _spine_paths(root_dir):
        root = _parse_xml(path).getroot()
        body_node = root.find(f"{{{XHTML_NS}}}body")
        if body_node is None:
            raise ConversionError(f"Missing XHTML body in {path.as_posix()}")
        body_tokens = _tokens(body_node)
        _assert_known_types(body_node, BODY_MATTER_TYPES)
        bucket = _section_bucket(path, body_tokens)
        if bucket is None:
            continue
        target = {"front": front, "body": body, "back": back}[bucket]
        for section in body_node.xpath("./x:section", namespaces=NS):
            target.append(_convert_section(section, state))

    if len(front):
        text.append(front)
    text.append(body)
    if len(back):
        text.append(back)
    tei.append(text)
    serialize(etree.ElementTree(tei), output)
    return ConversionResult(output_path=output, typographic_mappings=tuple(sorted(state.typographic_mappings)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Standard Ebooks XHTML to TEI.")
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("config_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()
    result = convert_se_to_tei(args.work_dir, args.config_path, args.output_path)
    print(f"Wrote {result.output_path.as_posix()}")
    if result.typographic_mappings:
        print("Typographic mappings:")
        for mapping in result.typographic_mappings:
            print(f"- {mapping}")


if __name__ == "__main__":
    main()
