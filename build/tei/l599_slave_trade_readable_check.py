"""Independent raw-first draft checker for the L599 readable repair.

It never imports the producer. Its grammar reduces innermost expressions first,
then reads source HTML events; the producer walks nested expressions directly.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import quote

T = "{http://www.tei-c.org/ns/1.0}"
X = "{http://www.w3.org/XML/1998/namespace}"
M = "{http://www.mediawiki.org/xml/export-0.11/}"
SOURCE_PIN = "54b15f460245becab46674cc364a05129d5b03ea4cb431df58704973c539b0a5"
OLD_PIN = "f100a1bcc5de3d5fa9563329360bfbdecedd992642e46287fbf89981678ff9de"
PAGE_PREFIX = "Page:The slave trade of east Africa.djvu/"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fields(node: ET.Element) -> object:
    return [node.tag, dict(node.attrib), node.text, node.tail, [fields(c) for c in node]]


def add(parent: ET.Element, text: str) -> None:
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


class Expected:
    def __init__(self) -> None:
        self.fragments: list[tuple[str, dict[str, str], str]] = []
        self.group = 0
        self.active: int | None = None
        self.notes = 0
        self.ends: list[tuple[int, str, str]] = []
        self.starts: list[tuple[int, str, str]] = []
        self.links: list[tuple[int, str, str]] = []
        self.administration: list[tuple[int, str]] = []

    def token(self, tag: str, attrs: dict[str, str], value: str) -> str:
        self.fragments.append((tag, attrs, value))
        return "\ue000" + str(len(self.fragments) - 1) + "\ue001"

    def reduce(self, value: str, number: int) -> str:
        if "\ue000" in value or "\ue001" in value:
            raise ValueError("L599 unexpected source placeholder character")
        def template(match: re.Match[str]) -> str:
            parts = match.group(1).split("|")
            name = parts[0].strip().lower().replace("_", " ")
            args = parts[1:]
            # Values are literal retained helper definitions, not a current web stylesheet.
            styles = {"center": "text-align:center; margin:0 auto;", "right": "text-align:right;",
                      "sc": "font-variant:small-caps;", "smaller": "font-size:83%;",
                      "smaller block": "font-size:83%; line-height:1.4;", "larger": "font-size:120%;",
                      "xx-larger": "font-size:182%;", "xxxx-larger": "font-size:249%;"}
            if name in styles and len(args) == 1:
                return self.token("seg", {"type": "source-template", "n": name, "style": styles[name]}, args[0])
            if name in {"hws", "hyphenated word end"} and len(args) == 2:
                (self.starts if name == "hws" else self.ends).append((number, args[0], args[1]))
                return self.token("seg", {"type": "source-hyphenation", "n": name}, "" if name == "hws" else args[1])
            if name == "rule" and args == ["10em"]:
                return self.token("milestone", {"unit": "rule", "n": "10em", "style": "width:10em;"}, "")
            if name == "nop" and not args:
                return self.token("seg", {"type": "source-template", "n": "nop"}, "")
            raise ValueError("L599 independent unsupported template or argument shape: " + name)
        def link(match: re.Match[str]) -> str:
            target, bar, label = match.group(1).partition("|")
            display = label if bar else target.split("#", 1)[0]
            site = "https://en.wikisource.org/wiki/"
            suffix = target
            if target.startswith("w:"):
                site, suffix = "https://en.wikipedia.org/wiki/", target[2:]
            title, mark, anchor = suffix.partition("#")
            address = site + quote(title.replace(" ", "_"), safe=":/")
            if mark:
                address += "#" + quote(anchor.replace(" ", "_"), safe="")
            self.links.append((number, target, address))
            return self.token("ref", {"type": "source-link", "target": address}, display)
        value = re.sub(r"\[\[([^\]]+)\]\]", link, value)
        if "[[" in value or "]]" in value or "'''" in value:
            raise ValueError("L599 independent unsupported link or bold shape")
        value = re.sub(r"''(.*?)''", lambda m: self.token("hi", {"rend": "italic"}, m.group(1)), value, flags=re.S)
        if "''" in value:
            raise ValueError("L599 independent unbalanced italic marker")
        while "{{" in value:
            updated = re.sub(r"\{\{([^{}]*)\}\}", template, value)
            if updated == value:
                raise ValueError("L599 independent unbalanced retained template")
            value = updated
        if "}}" in value:
            raise ValueError("L599 independent extra template close")
        return value

    def fill(self, parent: ET.Element, value: str, number: int,
             *, allow_quote: bool = False, reduced: bool = False) -> None:
        if not reduced:
            value = self.reduce(value, number)
        current = parent
        if allow_quote and self.active is not None:
            current = ET.SubElement(parent, T + "quote", {"type": "source-blockquote-continuation", "n": str(self.active)})
        parts = re.split(r"(\ue000[0-9]+\ue001|<[^>]*>)", value)
        note_stack: list[ET.Element] = []
        for part in parts:
            if not part:
                continue
            if part.startswith("\ue000"):
                tag, attrs, child_text = self.fragments[int(part[1:-1])]
                child = ET.SubElement(current, T + tag, attrs)
                self.fill(child, child_text, number, reduced=True)
            elif part == "<blockquote>":
                if not allow_quote or self.active is not None or note_stack:
                    raise ValueError("L599 independent unexpected quotation open")
                self.group += 1
                self.active = self.group
                current = ET.SubElement(parent, T + "quote", {"type": "source-blockquote", "n": str(self.group)})
            elif part == "</blockquote>":
                if not allow_quote or self.active is None or note_stack:
                    raise ValueError("L599 independent unexpected quotation close")
                self.active, current = None, parent
            elif part == "<ref>":
                if note_stack:
                    raise ValueError("L599 independent nested source footnote")
                self.notes += 1
                note_stack.append(current)
                current = ET.SubElement(current, T + "note", {"place": "foot", X + "id": "l599-note-" + str(self.notes)})
            elif part == "</ref>":
                if not note_stack:
                    raise ValueError("L599 independent unmatched source footnote")
                current = note_stack.pop()
            elif re.fullmatch(r"<br\s*/?>", part):
                ET.SubElement(current, T + "lb")
            elif part.startswith("<"):
                raise ValueError("L599 independent unsupported source HTML: " + part)
            else:
                add(current, unescape(part))
        if note_stack:
            raise ValueError("L599 independent source note crosses scan boundary")

    def page(self, raw: str, number: int) -> ET.Element:
        def administration(match: re.Match[str]) -> str:
            self.administration.append((number, match.group(0)))
            return ""
        value = re.sub(r"<noinclude>.*?</noinclude>", administration, raw, flags=re.S)
        if "noinclude" in value:
            raise ValueError("L599 independent unsupported noinclude")
        block = ET.Element(T + "ab", {"type": "source-block", X + "space": "preserve"})
        self.fill(block, value, number, allow_quote=True)
        return block


def check(source_bytes: bytes, original_bytes: bytes, actual_bytes: bytes) -> dict[str, object]:
    if digest(source_bytes) != SOURCE_PIN or digest(original_bytes) != OLD_PIN:
        raise ValueError("L599 independent source/original bytes differ")
    source = ET.fromstring(source_bytes)
    pages = {p.findtext(M + "title"): p.findtext(M + "revision/" + M + "text") or ""
             for p in source.findall(M + "page")}
    title_page = pages[PAGE_PREFIX + "5"]
    index = pages["Index:The slave trade of east Africa.djvu"]
    root_wiki = pages["The slave trade of east Africa"]
    if ("REPRINTED FROM THE \"CHRISTIAN OBSERVER.\"" not in title_page
            or "WITH AN APPENDIX." not in title_page or "1869." not in title_page
            or "CHURCH MISSIONARY SOCIETY," not in title_page
            or "|Author=Church Missionary Society" not in index
            or '<pagelist 1to4="\u2013" 5=1 41to44="\u2013" />' not in index
            or not all('to="' + str(n) + '"' in root_wiki for n in (6, 27))
            or any(PAGE_PREFIX + str(n) in pages for n in range(28, 41))
            or any("Appendix" in title for title in pages)):
        raise ValueError("L599 primary title/root/index/source-gap boundary differs")
    old = ET.fromstring(original_bytes)
    actual = ET.fromstring(actual_bytes)
    if actual.tag != T + "TEI" or actual.attrib != old.attrib or [c.tag for c in actual] != [T + "teiHeader", T + "text"]:
        raise ValueError("L599 exact actual root/header/text envelope differs")
    if actual.text != old.text or actual.tail != old.tail or actual[0].tail != old[0].tail or actual[1].tail != old[1].tail:
        raise ValueError("L599 actual outer direct/tail fields differ")
    expected = ET.fromstring(original_bytes)
    exp_text = expected.find(T + "text")
    old_back = exp_text.find(T + "back")
    witnesses = old_back.findall(T + "div/" + T + "ab")
    exp_text.remove(old_back)
    # Administration is checked directly from primary wikitext, never policy assertions.
    observed_source_desc = actual.find(T + "teiHeader/" + T + "fileDesc/" + T + "sourceDesc")
    bibliographies = list(observed_source_desc)
    if len(bibliographies) != 2 or bibliographies[1].tag != T + "bibl" or bibliographies[1].attrib != {"type": "retained-source-administration"}:
        raise ValueError("L599 administration bibliographic ownership differs")
    admin = bibliographies[1]
    if len(admin) != 26 or admin.text is not None or any(n.tail is not None for n in admin):
        raise ValueError("L599 administration note cardinality/direct fields differ")
    first = admin[0]
    if first.tag != T + "note" or first.attrib != {"type": "source-witness-and-disposition"} or len(first) != 2:
        raise ValueError("L599 human-visible administration shape differs")
    expected_notice = [
        "This retained Wikisource export supplies the main transcription at scan positions 5 through 27. Its title page says REPRINTED FROM THE CHRISTIAN OBSERVER and WITH AN APPENDIX; the Index attributes the edition to Church Missionary Society, London, 1869. The Appendix and cited Notes A through C are not retained. Index positions 1 through 4 and 41 through 44 carry a dash; positions 28 through 40 have no retained Page records. No print scans, page collation, or complete print-witness claim is supplied. The source record graph and support definitions remain bound in source accounting.",
        "Historical edition text and Wikisource contributor transcription have separate rights layers. The retained acquisition notice states CC BY-SA 4.0 and GFDL for contributor transcription unless an exact page states a different license; retain attribution and ShareAlike obligations. This technical candidate does not clear rights or authorize publication. The retained export preserves contributor identities and revision records.",
    ]
    if first.text is not None or first.tail is not None or any(p.tag != T + "p" or p.attrib or len(p) or p.tail is not None or p.text != text for p, text in zip(first, expected_notice)):
        raise ValueError("L599 actual human-visible title/creator/rights/gap assertions differ")
    for native, original in zip(admin[1:], witnesses):
        kind = original.get("type")
        title = "The slave trade of east Africa" if kind == "root-page-wikitext" else "Index:The slave trade of east Africa.djvu" if kind == "index-page-wikitext" else PAGE_PREFIX + original.get("n", "")
        if native.tag != T + "note" or native.attrib != {"type": kind} or native.text is not None or len(native) != 1:
            raise ValueError("L599 actual raw-witness note envelope differs")
        p = native[0]
        if p.tag != T + "p" or p.attrib != {"n": title, X + "space": "preserve"} or len(p) or p.tail is not None or p.text != pages[title] or original.text != pages[title]:
            raise ValueError("L599 actual-object wikitext inverse differs")
    # Remove only the newly declared administration branch to recover original header.
    observed_source_desc.remove(admin)
    if fields(actual[0]) != fields(expected[0]):
        raise ValueError("L599 conserved complete original header fields differ")
    observed_source_desc.append(admin)
    reader = Expected()
    numbers = []
    for div in exp_text.iter(T + "div"):
        if div.get("type") == "retained-page-transcription":
            n = int(div.find(T + "pb").get("n"))
            block = reader.page(pages[PAGE_PREFIX + str(n)], n)
            original_block = div.find(T + "ab")
            block.tail = original_block.tail
            div.remove(original_block)
            div.append(block)
            numbers.append(n)
    gap = expected.find(".//" + T + "gap")
    del gap.attrib["unit"]
    ET.SubElement(gap, T + "desc").text = "The linked Appendix and cited Notes A through C are not retained in this export."
    if numbers != list(range(5, 28)) or reader.active is not None or fields(actual[1]) != fields(expected[1]):
        raise ValueError("L599 entire actual readable envelope/roles/text/tails/attributes/attachment/order differs")
    if reader.ends != [(13, "portation", "importation"), (15, "dition", "expedition"), (20, "chases", "purchases"), (25, "rial", "memorial")] or reader.starts != [(19, "pur", "purchases"), (24, "memo", "memorial")]:
        raise ValueError("L599 source-defined root rendering six-event scope differs")
    return {"status": "pass", "source_sha256": SOURCE_PIN, "original_tei_sha256": OLD_PIN,
            "actual_tei_sha256": digest(actual_bytes), "source_record_count": len(pages),
            "actual_object_inverse_witness_count": len(witnesses), "source_quote_groups": reader.group,
            "notes": reader.notes, "links": reader.links, "word_ends": reader.ends,
            "word_starts": reader.starts, "noinclude_spans": len(reader.administration),
            "qualification": "Draft semantic/source comparison only; no supported package, P5, runtime closure, acceptance or installation claim."}
