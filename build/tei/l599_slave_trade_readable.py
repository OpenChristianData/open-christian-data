"""Bounded readable repair of the already retained L599 electronic witness.

Draft for source review. The historical package is input evidence, never edited.
Only the root's declared transclusion is rendered; this is not a MediaWiki engine.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import quote

from lxml import etree

T = "{http://www.tei-c.org/ns/1.0}"
X = "{http://www.w3.org/XML/1998/namespace}"
MW = "{http://www.mediawiki.org/xml/export-0.11/}"
SOURCE_SHA = "54b15f460245becab46674cc364a05129d5b03ea4cb431df58704973c539b0a5"
ORIGINAL_TEI_SHA = "f100a1bcc5de3d5fa9563329360bfbdecedd992642e46287fbf89981678ff9de"
PAGE_PREFIX = "Page:The slave trade of east Africa.djvu/"
STYLES = {
    "center": "text-align:center; margin:0 auto;",
    "right": "text-align:right;",
    "sc": "font-variant:small-caps;",
    "smaller": "font-size:83%;",
    "smaller block": "font-size:83%; line-height:1.4;",
    "larger": "font-size:120%;",
    "xx-larger": "font-size:182%;",
    "xxxx-larger": "font-size:249%;",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def append_text(parent: etree._Element, text: str) -> None:
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def split_arguments(value: str) -> list[str]:
    """Split only this witness's balanced nested templates and links."""
    parts, start, templates, links, i = [], 0, 0, 0, 0
    while i < len(value):
        pair = value[i:i + 2]
        if pair == "{{":
            templates += 1
            i += 2
        elif pair == "}}":
            templates -= 1
            if templates < 0:
                raise ValueError("L599 unmatched template close")
            i += 2
        elif pair == "[[":
            links += 1
            i += 2
        elif pair == "]]":
            links -= 1
            if links < 0:
                raise ValueError("L599 unmatched link close")
            i += 2
        elif value[i] == "|" and not templates and not links:
            parts.append(value[start:i])
            start = i + 1
            i += 1
        else:
            i += 1
    if templates or links:
        raise ValueError("L599 unclosed nested source argument")
    return parts + [value[start:]]


def template_end(value: str, start: int) -> int:
    depth, i = 0, start
    while i < len(value) - 1:
        if value[i:i + 2] == "{{":
            depth += 1
            i += 2
        elif value[i:i + 2] == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    raise ValueError("L599 unterminated retained template")


def link_target(literal: str) -> str:
    # w: is the literal interwiki prefix; its declared disposition is explicit.
    base = "https://en.wikisource.org/wiki/"
    if literal.startswith("w:"):
        base, literal = "https://en.wikipedia.org/wiki/", literal[2:]
    title, mark, fragment = literal.partition("#")
    return base + quote(title.replace(" ", "_"), safe=":/") + (
        "#" + quote(fragment.replace(" ", "_"), safe="") if mark else ""
    )


class Reading:
    """One finite witness grammar; cross-page quotation state is source-owned."""

    def __init__(self) -> None:
        self.quote_number = 0
        self.active_quote: int | None = None
        self.events: list[dict[str, object]] = []
        self.note_number = 0

    def event(self, number: int, kind: str, literal: str, **fields: object) -> None:
        self.events.append({"scan": number, "kind": kind, "literal": literal, **fields})

    def content(self, parent: etree._Element, value: str, number: int,
                *, permit_quote: bool = False) -> None:
        current = parent
        quote_node = None
        if permit_quote and self.active_quote is not None:
            quote_node = etree.SubElement(parent, T + "quote", type="source-blockquote-continuation",
                                          n=str(self.active_quote))
            current = quote_node
        i = 0
        while i < len(value):
            if value.startswith("{{", i):
                end = template_end(value, i)
                literal = value[i:end]
                parts = split_arguments(literal[2:-2])
                name = parts[0].strip().lower().replace("_", " ")
                args = parts[1:]
                if name in STYLES:
                    if len(args) != 1:
                        raise ValueError("L599 styling template argument shape: " + name)
                    node = etree.SubElement(current, T + "seg", type="source-template", n=name,
                                            style=STYLES[name])
                    self.content(node, args[0], number)
                elif name in {"hws", "hyphenated word end"}:
                    if len(args) != 2 or any("{{" in a or "[[" in a for a in args):
                        raise ValueError("L599 hyphenation argument shape differs")
                    node = etree.SubElement(current, T + "seg", type="source-hyphenation", n=name)
                    # The retained template explicitly selects this outside Page:.
                    node.text = "" if name == "hws" else unescape(args[1])
                elif name == "rule":
                    if args != ["10em"]:
                        raise ValueError("L599 rule width differs")
                    etree.SubElement(current, T + "milestone", unit="rule", n="10em", style="width:10em;")
                elif name == "nop":
                    if args:
                        raise ValueError("L599 nop arguments differ")
                    etree.SubElement(current, T + "seg", type="source-template", n="nop")
                else:
                    raise ValueError("L599 unsupported transcluded template: " + name)
                self.event(number, "template", literal, name=name, arguments=args,
                           context="main-transclusion-outside-Page")
                i = end
            elif value.startswith("[[", i):
                end = value.find("]]", i + 2)
                if end < 0:
                    raise ValueError("L599 unclosed retained link")
                literal = value[i:end + 2]
                args = value[i + 2:end].split("|", 1)
                if len(args) == 2:
                    label = args[1]
                else:
                    label = args[0].split("#", 1)[0]
                node = etree.SubElement(current, T + "ref", type="source-link", target=link_target(args[0]))
                self.content(node, label, number)
                self.event(number, "link", literal, target=args[0], resolved_target=node.get("target"))
                i = end + 2
            elif value.startswith("'''", i):
                raise ValueError("L599 unexpected bold delimiter")
            elif value.startswith("''", i):
                end = value.find("''", i + 2)
                if end < 0 or value.startswith("'''", end):
                    raise ValueError("L599 unmatched italic delimiter")
                node = etree.SubElement(current, T + "hi", rend="italic")
                self.content(node, value[i + 2:end], number)
                self.event(number, "italic", value[i:end + 2])
                i = end + 2
            elif value.startswith("<ref>", i):
                end = value.find("</ref>", i + 5)
                if end < 0:
                    raise ValueError("L599 unclosed source footnote")
                self.note_number += 1
                node = etree.SubElement(current, T + "note", place="foot",
                                        attrib={X + "id": f"l599-note-{self.note_number}"})
                self.content(node, value[i + 5:end], number)
                self.event(number, "footnote", value[i:end + 6], note_id=node.get(X + "id"))
                i = end + 6
            elif value.startswith("<blockquote>", i):
                if not permit_quote or self.active_quote is not None:
                    raise ValueError("L599 unexpected nested quotation")
                self.quote_number += 1
                self.active_quote = self.quote_number
                quote_node = etree.SubElement(parent, T + "quote", type="source-blockquote",
                                              n=str(self.active_quote))
                current = quote_node
                self.event(number, "blockquote-open", "<blockquote>", quote=self.active_quote)
                i += 12
            elif value.startswith("</blockquote>", i):
                if not permit_quote or self.active_quote is None:
                    raise ValueError("L599 unmatched transcluded quotation close")
                self.event(number, "blockquote-close", "</blockquote>", quote=self.active_quote)
                self.active_quote, quote_node, current = None, None, parent
                i += 13
            elif value.startswith("<br", i):
                match = re.match(r"<br\s*/?>", value[i:])
                if match is None:
                    raise ValueError("L599 unsupported retained line-break attributes")
                etree.SubElement(current, T + "lb")
                self.event(number, "line-break", match.group(0))
                i += len(match.group(0))
            elif value[i] == "<" or value.startswith("}}", i) or value.startswith("]]", i):
                raise ValueError("L599 unsupported source markup at " + value[i:i + 60])
            else:
                end = i + 1
                while end < len(value) and value[end] != "<" and not any(
                    value.startswith(token, end) for token in ("{{", "}}", "[[", "]]", "''")
                ):
                    end += 1
                append_text(current, unescape(value[i:end]))
                i = end

    def page(self, block: etree._Element, raw: str, number: int) -> None:
        block.clear(keep_tail=True)
        block.set("type", "source-block")
        block.set(X + "space", "preserve")
        pieces, start = [], 0
        for match in re.finditer(r"<noinclude>.*?</noinclude>", raw, re.S):
            pieces.append(raw[start:match.start()])
            self.event(number, "source-administration", match.group(0), disposition="exact-wikitext-in-sourceDesc")
            start = match.end()
        pieces.append(raw[start:])
        rendered = "".join(pieces)
        if "noinclude" in rendered:
            raise ValueError("L599 unsupported noinclude shape")
        self.content(block, rendered, number, permit_quote=True)


def repair(source_bytes: bytes, original_tei_bytes: bytes) -> tuple[bytes, dict[str, object]]:
    if sha(source_bytes) != SOURCE_SHA or sha(original_tei_bytes) != ORIGINAL_TEI_SHA:
        raise ValueError("L599 source or original technical TEI bytes differ")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    source = etree.fromstring(source_bytes, parser)
    pages = {p.findtext(MW + "title"): p.findtext(MW + "revision/" + MW + "text") or ""
             for p in source.findall(MW + "page")}
    original = etree.fromstring(original_tei_bytes, parser)
    root = copy.deepcopy(original)
    text = root.find(T + "text")
    back = text.find(T + "back")
    witness = back.find(T + "div")
    raw_blocks = witness.findall(T + "ab")
    if len(raw_blocks) != 25:
        raise ValueError("L599 historical exact-wikitext envelope differs")
    source_desc = root.find(T + "teiHeader/" + T + "fileDesc/" + T + "sourceDesc")
    bibl = etree.SubElement(source_desc, T + "bibl", type="retained-source-administration")
    note = etree.SubElement(bibl, T + "note", type="source-witness-and-disposition")
    etree.SubElement(note, T + "p").text = (
        "This retained Wikisource export supplies the main transcription at scan positions 5 through 27. "
        "Its title page says REPRINTED FROM THE CHRISTIAN OBSERVER and WITH AN APPENDIX; "
        "the Index attributes the edition to Church Missionary Society, London, 1869. "
        "The Appendix and cited Notes A through C are not retained. Index positions 1 through 4 and "
        "41 through 44 carry a dash; positions 28 through 40 have no retained Page records. "
        "No print scans, page collation, or complete print-witness claim is supplied. "
        "The source record graph and support definitions remain bound in source accounting."
    )
    etree.SubElement(note, T + "p").text = (
        "Historical edition text and Wikisource contributor transcription have separate rights layers. "
        "The retained acquisition notice states CC BY-SA 4.0 and GFDL for contributor transcription "
        "unless an exact page states a different license; retain attribution and ShareAlike obligations. "
        "This technical candidate does not clear rights or authorize publication. "
        "The retained export preserves contributor identities and revision records."
    )
    for old in raw_blocks:
        kind = old.get("type")
        title = ("The slave trade of east Africa" if kind == "root-page-wikitext" else
                 "Index:The slave trade of east Africa.djvu" if kind == "index-page-wikitext" else
                 PAGE_PREFIX + old.get("n", ""))
        if old.text != pages.get(title):
            raise ValueError("L599 original wikitext witness does not equal retained source")
        entry = etree.SubElement(bibl, T + "note", type=kind)
        etree.SubElement(entry, T + "p", n=title, attrib={X + "space": "preserve"}).text = old.text
    text.remove(back)
    reading = Reading()
    mapped = []
    for wrapper in text.iter(T + "div"):
        if wrapper.get("type") != "retained-page-transcription":
            continue
        number = int(wrapper.find(T + "pb").get("n"))
        block = wrapper.find(T + "ab")
        reading.page(block, pages[PAGE_PREFIX + str(number)], number)
        mapped.append(number)
    if mapped != list(range(5, 28)) or reading.active_quote is not None:
        raise ValueError("L599 transclusion sequence or final quotation context differs")
    gap = root.find(".//" + T + "gap")
    # A source absence is readable as a gap, with no fabricated Appendix extent.
    del gap.attrib["unit"]
    etree.SubElement(gap, T + "desc").text = "The linked Appendix and cited Notes A through C are not retained in this export."
    result = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    graph = []
    def visit(node: etree._Element, path: str, parent: str | None, ordinal: int) -> None:
        graph.append({"path": path, "parent": parent, "ordinal": ordinal, "tag": node.tag,
                      "attributes": list(node.attrib.items()), "direct_text": node.text,
                      "tail_text": node.tail, "child_count": len(node),
                      "disposition": "retained-export-administration-and-support-fields"})
        for position, child in enumerate(node):
            visit(child, path + "/" + str(position), path, position)
    visit(source, "0", None, 0)
    return result, {"source_sha256": SOURCE_SHA, "original_tei_sha256": ORIGINAL_TEI_SHA,
                    "reading_context": "root-main-transclusion-outside-Page", "scan_order": mapped,
                    "events": reading.events, "source_quote_groups": reading.quote_number,
                    "note_count": reading.note_number,
                    "retained_xml_field_graph": graph,
                    "representation_limit": "Current readable repair; original technical package and scan-page wikitext are conserved separately."}
