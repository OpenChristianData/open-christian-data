"""Source-local TEI reconstruction of the retained PG71811 UTF-8 HTML."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

from lxml import etree, html

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/gutenberg/71811/html/pg71811-images.html")
SOURCE_SHA256 = "c423067697dc9d0ce52d7066548db97910af541f2255699e2926fd71b4d3a722"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


def _node(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{tag}", **attrs)


def _append_text(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def source_body() -> tuple[etree._Element, bytes]:
    raw = _io_path(ROOT / SOURCE).read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG71811 retained HTML digest differs")
    raw.decode("utf-8", errors="strict")
    document = html.fromstring(raw, parser=html.HTMLParser(encoding="utf-8"))
    body = document.find(".//body")
    if body is None or len(body) != 94 or len(body.xpath('.//comment()')) != 1:
        raise ValueError("PG71811 body envelope differs")
    return body, raw


def _append(source: etree._Element, parent: etree._Element, tally: Counter[str]) -> etree._Element | None:
    if parent.tag == f"{{{TEI}}}div":
        carrier = _node(parent, "div", type="source-html-child")
        mapped = _map(source, carrier, tally)
        if mapped is None:
            raise ValueError("PG71811 div child has no TEI carrier")
        carrier.tail = mapped.tail
        mapped.tail = None
        return carrier
    return _map(source, parent, tally)


def _map(source: etree._Element, parent: etree._Element, tally: Counter[str]) -> etree._Element | None:
    if not isinstance(source.tag, str):
        raise ValueError("PG71811 unexpected source comment in body")
    tag = source.tag.lower()
    tally[tag] += 1
    if tag == "tbody":
        if source.attrib or (source.text or "").strip():
            raise ValueError("PG71811 table-body carrier differs")
        # HTML's implicit table-body wrapper has no TEI peer. Its whitespace
        # remains source-accounted; rows retain their own text and tail order.
        for child in source:
            _append(child, parent, tally)
        return None
    if tag == "figcaption":
        if source.attrib or (source.text or "").strip() or any(child.tag != "p" for child in source):
            raise ValueError("PG71811 figure caption differs")
        if source.text:
            _append_text(parent, source.text)
        last = None
        for paragraph in source:
            last = _map(paragraph, parent, tally)
            if last is None:
                raise ValueError("PG71811 caption paragraph absent")
            last.set("rend", " ".join(filter(None, (last.get("rend"), "source-figcaption"))))
        if last is not None:
            last.tail = (last.tail or "") + (source.tail or "")
        return last
    if tag == "a" and parent.tag == f"{{{TEI}}}figure":
        if (set(source.attrib) != {"href", "id"} or len(source) != 1
                or source[0].tag != "img" or (source.text or "").strip()
                or (source[0].tail or "").strip()):
            raise ValueError("PG71811 linked figure differs")
        graphic = _map(source[0], parent, tally)
        if graphic is None or source.get("href") != graphic.get("url"):
            raise ValueError("PG71811 linked figure target differs")
        graphic.set("corresp", source.get("href"))
        graphic.tail = source.tail
        return graphic
    mapping = {
        "div": "div", "header": "div", "footer": "div", "h1": "ab", "h2": "ab",
        "h3": "ab", "h4": "ab", "p": "p", "blockquote": "quote", "ul": "list",
        "li": "item", "dl": "list", "dt": "item", "dd": "item", "table": "table",
        "tr": "row", "td": "cell", "figure": "figure", "img": "graphic",
        "a": "ref", "b": "hi", "strong": "hi", "i": "hi", "small": "hi",
        "span": "seg", "br": "lb", "hr": "milestone",
    }
    if tag == "abbr":
        if set(source.attrib) != {"title"} or not source.get("title", "").strip():
            raise ValueError("PG71811 abbreviation/title differs")
        target = _node(parent, "choice")
        abbreviated = _node(target, "abbr")
        abbreviated.text = source.text
        for child in source:
            _append(child, abbreviated, tally)
        _node(target, "expan").text = source.get("title")
        target.tail = source.tail
        return target
    if tag not in mapping:
        raise ValueError(f"PG71811 unmapped source element: {tag}")
    target = _node(parent, mapping[tag])
    inline = {"a", "span", "br", "abbr", "b", "i", "small", "strong"}
    if tag == "div" and all(child.tag in inline for child in source):
        target.tag = f"{{{TEI}}}ab"
    if target.tag == f"{{{TEI}}}div" and ((source.text or "").strip() or any((c.tail or "").strip() for c in source)):
        raise ValueError("PG71811 block div has direct visible text")
    identifier = source.get("id")
    if identifier:
        target.set(f"{{{XML}}}id", identifier)
    if tag in {"header", "footer"}:
        target.set("type", f"gutenberg-{tag}")
    elif tag == "div":
        target.set("type", "source-block" if target.tag == f"{{{TEI}}}ab" else "source-html-div")
    elif tag in {"h1", "h2", "h3", "h4"}:
        target.set("type", f"source-{tag}")
    elif tag == "dl":
        target.set("type", "definition")
    elif tag in {"dt", "dd"}:
        target.set("rend", "source-term" if tag == "dt" else "source-definition")
    elif tag == "ul":
        target.set("type", "unordered")
    elif tag in {"b", "strong", "i", "small"}:
        target.set("rend", {"b": "bold", "strong": "strong", "i": "italic", "small": "small"}[tag])
    elif tag == "hr":
        target.set("unit", "source-horizontal-rule")
    elif tag == "a":
        if not source.get("href"):
            if identifier and not len(source) and not (source.text or "").strip():
                target.tag = f"{{{TEI}}}anchor"
            elif identifier:
                target.tag = f"{{{TEI}}}seg"
            else:
                raise ValueError("PG71811 unaddressed anchor differs")
        else:
            target.set("target", source.get("href"))
    elif tag == "img":
        if not source.get("src") or len(source) or (source.text or "").strip():
            raise ValueError("PG71811 image reference differs")
        target.set("url", source.get("src"))
        if source.get("alt"):
            target.set("n", source.get("alt"))
    elif tag == "td" and source.get("colspan"):
        target.set("cols", source.get("colspan"))
    source_lang = source.get("lang")
    if source_lang:
        target.set(f"{{{XML}}}lang", source_lang)
    source_style = source.get("style")
    if source_style:
        if tag not in {"div", "p", "span"}:
            raise ValueError("PG71811 unsupported styled source element")
        if target.tag == f"{{{TEI}}}ab":
            target.set("rend", " ".join(filter(None, (target.get("rend"), "source-style:" + source_style))))
        else:
            target.set("style", source_style)
    source_direction = source.get("dir")
    if source_direction:
        if tag != "span" or source_direction != "rtl" or source_style:
            raise ValueError("PG71811 unsupported source direction")
        target.set("style", "direction:rtl")
    if tag not in {"figure", "img", "tr"}:
        classes = source.get("class")
        if classes:
            target.set("rend", " ".join(filter(None, (target.get("rend"), "source-class:" + " ".join(classes.split())))))
    target.text = source.text
    for child in source:
        _append(child, target, tally)
    target.tail = source.tail
    return target


def reconstruct() -> tuple[bytes, dict[str, int]]:
    body, _ = source_body()
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(f"{{{XML}}}id", "gutenberg-elmslie-books-of-chronicles")
    header = _node(root, "teiHeader")
    description = _node(header, "fileDesc")
    titles = _node(description, "titleStmt")
    _node(titles, "title").text = "The Books of Chronicles"
    _node(titles, "author").text = "W. A. L. Elmslie"
    publication = _node(description, "publicationStmt")
    _node(publication, "p").text = "Nonaccepted retained-source reconstruction; publication rights remain under review."
    source_desc = _node(description, "sourceDesc")
    _node(source_desc, "bibl").text = "Project Gutenberg eBook 71811, the complete 1916 second-edition Cambridge Bible electronic witness, retained extracted UTF-8 HTML."
    text = _node(root, "text")
    text.set(f"{{{XML}}}lang", "en")
    tei_body = _node(text, "body")
    wrapper = _node(tei_body, "div", type="complete-retained-html-body")
    wrapper.text = body.text
    tally: Counter[str] = Counter()
    for child in body:
        if isinstance(child, etree._Comment):
            if (child.text != ' WIP line in red\r\n<hr id="WIP"> page +0 ― Note #: 467 '
                    or not len(wrapper) or (child.tail or '').strip()):
                raise ValueError("PG71811 source editorial comment differs")
            tally['#comment'] += 1
            wrapper[-1].tail = (wrapper[-1].tail or '') + (child.tail or '')
            continue
        _append(child, wrapper, tally)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True), dict(tally)
