"""Reconstruct Project Gutenberg 55955 as a faithful, nonaccepted TEI candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from lxml import etree, html

from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import XML_NS, serialize, stamp_header, tei_el

LANDING_URL = "https://www.gutenberg.org/ebooks/55955"
HTML_URL = "https://www.gutenberg.org/cache/epub/55955/pg55955-images.html"
TEXT_URL = "https://www.gutenberg.org/cache/epub/55955/pg55955.txt"
RDF_URL = "https://www.gutenberg.org/ebooks/55955.rdf"
OPEN_LIBRARY_URL = "https://openlibrary.org/books/OL25721931M"
OPEN_LIBRARY_JSON_URL = "https://openlibrary.org/books/OL25721931M.json"
WITNESS_URL = "https://archive.org/details/ldpd_11375193_000"
WITNESS_PDF_URL = (
    "https://archive.org/download/ldpd_11375193_000/ldpd_11375193_000.pdf"
)
TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS, "xml": XML_NS}
EXPECTED_SECTIONS = (
    "Ports of Entry",
    "Ellis Island",
    "Boston Port of Entry",
    "Philadelphia Port of Entry",
    "The Philadelphia Immigration Station",
)
EXPECTED_IMAGES = {
    "images/cover.jpg",
    "images/i_004.jpg",
    "images/i_009.jpg",
    "images/i_016.jpg",
    "images/i_021.jpg",
    "images/i_022.jpg",
    "images/i_back.jpg",
    "images/i_cover.jpg",
    "images/i_decor.jpg",
    "images/i_decor2.jpg",
    "images/i_title.jpg",
}
EXPECTED_IMAGE_OCCURRENCES = (
    "images/cover.jpg",
    "images/i_title.jpg",
    "images/i_cover.jpg",
    "images/i_decor.jpg",
    "images/i_decor.jpg",
    "images/i_004.jpg",
    "images/i_009.jpg",
    "images/i_016.jpg",
    "images/i_decor2.jpg",
    "images/i_021.jpg",
    "images/i_022.jpg",
    "images/i_back.jpg",
)
SECTION_IDS = {
    "Ports of Entry": "poe-ports-of-entry",
    "Ellis Island": "poe-ellis-island",
    "Boston Port of Entry": "poe-boston-port-of-entry",
    "Philadelphia Port of Entry": "poe-philadelphia-port-of-entry",
    "The Philadelphia Immigration Station": "poe-philadelphia-immigration-station",
}


class ConversionError(ValueError):
    """Raised when the retained source does not match the released work."""


@dataclass(frozen=True)
class InlineEvent:
    kind: str
    value: str
    rend: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedSource:
    path: Path
    nodes: tuple[etree._Element, ...]
    carrier_texts: tuple[str, ...]
    page_numbers: tuple[int, ...]
    figure_sources: tuple[str, ...]
    section_titles: tuple[str, ...]
    toc_entries: tuple[tuple[str, str], ...]
    end_marker: str


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    receipt_path: Path
    accounting_path: Path
    validation_path: Path
    carrier_count: int
    figure_count: int
    page_count: int
    section_count: int
    table_count: int


@dataclass
class CarrierState:
    ordinal: int = 0
    source_texts: list[str] = field(default_factory=list)

    def register(self, element: etree._Element, source_text: str) -> None:
        normalized = _normalized_visible(source_text)
        if not normalized:
            raise ConversionError("Attempted to register an empty source-text carrier")
        self.ordinal += 1
        element.set(f"{{{XML_NS}}}id", f"poe-src-B{self.ordinal:04d}")
        element.set("n", str(self.ordinal))
        self.source_texts.append(normalized)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _normalized_visible(value: str) -> str:
    return " ".join(value.split())


def _classes(node: etree._Element) -> set[str]:
    return set((node.get("class") or "").split())


def _is_pagenum(node: etree._Element) -> bool:
    return node.tag.lower() == "span" and "pagenum" in _classes(node)


def _rend_for(node: etree._Element, inherited: tuple[str, ...]) -> tuple[str, ...]:
    result = list(inherited)
    tag = node.tag.lower()
    additions: list[str] = []
    if tag in {"i", "em"}:
        additions.append("italic")
    if tag in {"b", "strong"}:
        additions.append("bold")
    if tag == "sup":
        additions.append("superscript")
    if tag == "sub":
        additions.append("subscript")
    if "smcap" in _classes(node):
        additions.append("small-caps")
    for value in additions:
        if value not in result:
            result.append(value)
    return tuple(result)


def _raw_inline_events(node: etree._Element) -> list[InlineEvent]:
    events: list[InlineEvent] = []

    def append_text(value: str | None, rend: tuple[str, ...]) -> None:
        if value:
            events.append(InlineEvent("text", value, rend))

    def walk(current: etree._Element, inherited: tuple[str, ...]) -> None:
        current_rend = _rend_for(current, inherited)
        append_text(current.text, current_rend)
        for child in current:
            tag = child.tag.lower() if isinstance(child.tag, str) else ""
            if _is_pagenum(child):
                anchor = child.xpath(".//a[starts-with(@id, 'Page_')]/@id")
                if len(anchor) != 1:
                    raise ConversionError("Malformed Project Gutenberg page-number span")
                events.append(InlineEvent("page", anchor[0].removeprefix("Page_")))
            elif tag == "br":
                events.append(InlineEvent("break", ""))
            elif tag == "img":
                pass
            else:
                walk(child, current_rend)
            append_text(child.tail, current_rend)

    walk(node, ())
    return events


def _inline_events(node: etree._Element) -> tuple[InlineEvent, ...]:
    normalized: list[InlineEvent] = []
    pending_space = False
    visible = False

    def emit_text(value: str, rend: tuple[str, ...]) -> None:
        if not value:
            return
        if normalized and normalized[-1].kind == "text" and normalized[-1].rend == rend:
            prior = normalized[-1]
            normalized[-1] = InlineEvent("text", prior.value + value, rend)
        else:
            normalized.append(InlineEvent("text", value, rend))

    for event in _raw_inline_events(node):
        if event.kind == "text":
            for piece in re.findall(r"\s+|\S+", event.value):
                if piece.isspace():
                    pending_space = True
                    continue
                prefix = " " if pending_space and visible else ""
                emit_text(prefix + piece, event.rend)
                pending_space = False
                visible = True
        elif event.kind == "break":
            normalized.append(event)
            pending_space = False
        else:
            normalized.append(event)
    return tuple(normalized)


def _events_text(events: Iterable[InlineEvent]) -> str:
    return "".join(
        " " if event.kind == "break" else event.value if event.kind == "text" else ""
        for event in events
    )


def _semantic_text(node: etree._Element) -> str:
    return _normalized_visible(_events_text(_inline_events(node)))


def _figure_description(node: etree._Element) -> str:
    labelled_by = node.get("aria-labelledby")
    if labelled_by:
        matches = node.getroottree().xpath(f"//*[@id='{labelled_by}']")
        if len(matches) == 1:
            value = _semantic_text(matches[0])
            if value:
                return value
    captions = node.xpath(
        ".//*[contains(concat(' ', normalize-space(@class), ' '), ' caption ')]"
    )
    for caption in captions:
        value = _semantic_text(caption)
        if value:
            return value
    alternatives = [
        _normalized_visible(value)
        for value in node.xpath(".//img/@alt")
        if _normalized_visible(value) not in {"", "Image"}
    ]
    return " ".join(alternatives)


def _is_figure(node: etree._Element) -> bool:
    return bool(node.xpath(".//img"))


def _carrier_texts_for_node(node: etree._Element) -> Iterator[str]:
    tag = node.tag.lower() if isinstance(node.tag, str) else ""
    if _is_figure(node):
        description = _figure_description(node)
        if description:
            yield description
        return
    if tag in {"h1", "h2", "h3", "h4", "p", "li", "td", "th"}:
        value = _semantic_text(node)
        if value:
            yield value
        if tag == "li":
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
    if tag in {"blockquote", "div"}:
        for child in node:
            if isinstance(child.tag, str):
                yield from _carrier_texts_for_node(child)


def _chapter_title(node: etree._Element) -> str | None:
    if node.tag.lower() != "div" or "chapter" not in _classes(node):
        return None
    headings = node.xpath(".//h2")
    if len(headings) != 1:
        raise ConversionError("Expected each chapter div to contain exactly one h2")
    return _semantic_text(headings[0])


def parse_source(path: Path) -> ParsedSource:
    raw = path.read_bytes()
    try:
        raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ConversionError("Project Gutenberg HTML authority is not UTF-8") from error
    document = html.fromstring(raw)
    bodies = document.xpath("//body")
    if len(bodies) != 1:
        raise ConversionError("Expected exactly one HTML body")
    body = bodies[0]
    direct = [child for child in body if isinstance(child.tag, str)]
    header_indexes = [index for index, node in enumerate(direct) if node.get("id") == "pg-header"]
    footer_indexes = [index for index, node in enumerate(direct) if node.get("id") == "pg-footer"]
    if len(header_indexes) != 1 or len(footer_indexes) != 1:
        raise ConversionError("Expected one Project Gutenberg header and footer")
    start = header_indexes[0] + 1
    stop = footer_indexes[0]
    if stop <= start:
        raise ConversionError("Project Gutenberg footer precedes edition content")
    nodes = tuple(
        node
        for node in direct[start:stop]
        if node.tag.lower() != "div" or _is_figure(node) or _chapter_title(node) or _semantic_text(node)
    )
    headings = tuple(
        title for node in nodes if (title := _chapter_title(node)) is not None
    )
    expected_headings = EXPECTED_SECTIONS + ("Transcriber's Note",)
    if headings != expected_headings:
        raise ConversionError(f"Unexpected source divisions: {headings!r}")
    page_ids = document.xpath(
        "//span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')]"
        "/a[starts-with(@id, 'Page_')]/@id"
    )
    page_numbers = tuple(int(value.removeprefix("Page_")) for value in page_ids)
    if page_numbers != tuple(range(1, 31)):
        raise ConversionError(f"Unexpected page milestone sequence: {page_numbers!r}")
    figure_sources = tuple(document.xpath("//body/*[not(@id='pg-header') and not(@id='pg-footer')]//img/@src"))
    if figure_sources != EXPECTED_IMAGE_OCCURRENCES:
        raise ConversionError(f"Unexpected image members: {figure_sources!r}")
    if len(document.xpath("//body//table")) != 7:
        raise ConversionError("Expected seven source tables")
    toc_path = path.parent / "openlibrary-OL25721931M.json"
    toc_data = json.loads(toc_path.read_text(encoding="utf-8"))
    toc_entries = tuple(
        (str(entry["title"]), str(entry["pagenum"]))
        for entry in toc_data.get("table_of_contents", [])
    )
    if toc_entries != (
        ("Ports of Entry", "7"),
        ("Ellis Island", "11"),
        ("Boston Port of Entry", "22"),
        ("Philadelphia Port of Entry", "25"),
    ):
        raise ConversionError(f"Unexpected Open Library contents metadata: {toc_entries!r}")
    footer_text = _normalized_visible(" ".join(direct[footer_indexes[0]].itertext()))
    marker = "*** END OF THE PROJECT GUTENBERG EBOOK PORTS OF ENTRY: MISSIONARY HERALD ***"
    if marker not in footer_text:
        raise ConversionError("Expected Project Gutenberg end marker is missing")
    carrier_texts = tuple(
        text for node in nodes for text in _carrier_texts_for_node(node)
    )
    if not carrier_texts or "Obvious punctuation and spelling errors have been repaired." not in carrier_texts:
        raise ConversionError("The retained transcriber repair note is missing")
    return ParsedSource(
        path,
        nodes,
        carrier_texts,
        page_numbers,
        figure_sources,
        headings[:-1],
        toc_entries,
        marker,
    )


def _append_literal(parent: etree._Element, value: str) -> None:
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _append_inline(parent: etree._Element, events: Sequence[InlineEvent]) -> None:
    for event in events:
        if event.kind == "page":
            parent.append(
                tei_el(
                    "pb",
                    {"n": event.value, "facs": f"{HTML_URL}#Page_{event.value}"},
                )
            )
        elif event.kind == "break":
            parent.append(tei_el("lb"))
            parent[-1].tail = " "
        elif event.rend:
            parent.append(tei_el("hi", {"rend": " ".join(event.rend)}, event.value))
        else:
            _append_literal(parent, event.value)


def _new_carrier(
    tag: str,
    source: etree._Element,
    state: CarrierState,
    attributes: dict[str, str] | None = None,
) -> etree._Element:
    events = _inline_events(source)
    source_text = _events_text(events)
    element = tei_el(tag, attributes or {})
    state.register(element, source_text)
    _append_inline(element, events)
    return element


def _append_page_only(parent: etree._Element, node: etree._Element) -> bool:
    events = _inline_events(node)
    if any(event.kind == "text" and event.value.strip() for event in events):
        return False
    if not any(event.kind == "page" for event in events):
        return False
    _append_inline(parent, events)
    return True


def _convert_figure(node: etree._Element, parent: etree._Element, state: CarrierState) -> None:
    images = node.xpath(".//img")
    if len(images) != 1:
        raise ConversionError("Expected each source figure to contain exactly one image")
    source = images[0].get("src")
    if source not in EXPECTED_IMAGES:
        raise ConversionError(f"Unexpected figure source: {source!r}")
    figure = tei_el("figure", {"source": HTML_URL})
    figure.append(
        tei_el(
            "graphic",
            {"url": f"https://www.gutenberg.org/cache/epub/55955/{source}"},
        )
    )
    description = _figure_description(node)
    if description:
        fig_desc = tei_el("figDesc")
        state.register(fig_desc, description)
        fig_desc.text = description
        figure.append(fig_desc)
    parent.append(figure)


def _convert_list(node: etree._Element, parent: etree._Element, state: CarrierState) -> None:
    result = tei_el("list", {"type": "ordered" if node.tag.lower() == "ol" else "simple"})
    for source_item in node.xpath("./li"):
        item = _new_carrier("item", source_item, state)
        for nested in source_item.xpath("./ul|./ol"):
            _convert_list(nested, item, state)
        result.append(item)
    parent.append(result)


def _convert_table(node: etree._Element, parent: etree._Element, state: CarrierState) -> None:
    result = tei_el("table", {"rend": "project-gutenberg-html-table"})
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
            if _semantic_text(source_cell):
                row.append(_new_carrier("cell", source_cell, state, attributes))
            else:
                empty_cell = tei_el("cell", attributes)
                _append_inline(empty_cell, _inline_events(source_cell))
                row.append(empty_cell)
        if len(row):
            result.append(row)
    parent.append(result)


def _convert_quote(node: etree._Element, parent: etree._Element, state: CarrierState) -> None:
    quote = tei_el("quote")
    children = [child for child in node if isinstance(child.tag, str)]
    if children:
        for child in children:
            _convert_block(child, quote, state)
    else:
        quote.append(_new_carrier("p", node, state))
    parent.append(quote)


def _convert_block(node: etree._Element, parent: etree._Element, state: CarrierState) -> None:
    tag = node.tag.lower()
    if _is_figure(node):
        _convert_figure(node, parent, state)
        return
    if tag == "hr":
        attributes = {"unit": "typographic-rule"}
        if node.get("class"):
            attributes["rend"] = node.get("class") or ""
        parent.append(tei_el("milestone", attributes))
        return
    if tag in {"h1", "h2", "h3", "h4"}:
        parent.append(
            _new_carrier(
                "ab",
                node,
                state,
                {"type": "source-heading", "rend": tag},
            )
        )
        return
    if tag == "p":
        if _append_page_only(parent, node):
            return
        text = _semantic_text(node)
        if not text:
            return
        classes = _classes(node)
        if "sigright" in classes or "sigright2" in classes:
            result_tag = "p"
            classes.add("signature")
        elif "center" in classes and "bold" in classes:
            result_tag = "ab"
            classes.add("source-subheading")
        else:
            result_tag = "p"
        attributes = {"rend": " ".join(sorted(classes))} if classes else None
        parent.append(_new_carrier(result_tag, node, state, attributes))
        return
    if tag in {"ul", "ol"}:
        _convert_list(node, parent, state)
        return
    if tag == "blockquote":
        _convert_quote(node, parent, state)
        return
    if tag == "table":
        _convert_table(node, parent, state)
        return
    if tag == "div":
        if _chapter_title(node) is not None:
            for child in node:
                if isinstance(child.tag, str):
                    _convert_block(child, parent, state)
            return
        for child in node:
            if isinstance(child.tag, str):
                _convert_block(child, parent, state)
        return
    if tag == "img":
        _convert_figure(node, parent, state)
        return
    raise ConversionError(f"Unsupported retained HTML block: <{tag}>")


def _convert_chapter_heading(
    node: etree._Element,
    parent: etree._Element,
    state: CarrierState,
) -> etree._Element:
    headings = node.xpath(".//h2")
    if len(headings) != 1:
        raise ConversionError("Expected one source division heading")
    parent.append(_new_carrier("head", headings[0], state, {"type": "source-h2"}))
    return headings[0]


def _header(source_sha256: str) -> etree._Element:
    header = stamp_header(
        title="Ports of Entry: Missionary Herald",
        author="Home Missions Council of the United States and Council of Women for Home Missions",
        contributors=[
            {"name": "Joint Committee of Six", "role": "issuing body"},
            {
                "name": "ellinora, Larry B. Harrison, and the Online Distributed Proofreading Team",
                "role": "Project Gutenberg production and proofreading",
            },
        ],
        source_url=HTML_URL,
        source_sha256=source_sha256,
        print_source=(
            "New York: Joint Committee of Six, 1915. Open Library OL25721931M and "
            "Internet Archive ldpd_11375193_000 are retained only as bounded identity "
            "and text witnesses."
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
                "The retained Project Gutenberg HTML is the textual and structural authority. "
                "Its source-defined divisions, paragraphs, lists, tables, emphasis, figures, "
                "and page anchors are represented without modernizing the wording. The plain "
                "text is a cross-check. The Open Library contents metadata is marked as an "
                "electronic navigation aid, not silently attributed to the 1915 print."
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


def _append_electronic_contents(front: etree._Element, parsed: ParsedSource) -> None:
    contents = tei_el(
        "div",
        {
            "type": "contents",
            "subtype": "open-library-electronic-navigation",
            "source": OPEN_LIBRARY_JSON_URL,
            "xml:id": "poe-electronic-contents",
        },
    )
    contents.append(tei_el("head", text="Contents (Open Library navigation metadata)"))
    listing = tei_el("list")
    for title, page in parsed.toc_entries:
        item = tei_el("item")
        target = SECTION_IDS.get(title)
        if target:
            item.append(tei_el("ref", {"target": f"#{target}"}, title))
        else:
            item.text = title
        item.append(tei_el("label", text=f"Open Library page {page}"))
        listing.append(item)
    contents.append(listing)
    front.append(contents)


def build_tree(parsed: ParsedSource) -> tuple[etree._ElementTree, dict[str, object]]:
    chapter_indexes = [
        index for index, node in enumerate(parsed.nodes) if _chapter_title(node) is not None
    ]
    if len(chapter_indexes) != 6:
        raise ConversionError("Expected five source sections plus the transcriber note")
    first_body = chapter_indexes[0]
    transcriber_index = chapter_indexes[-1]
    last_table_index = max(
        index for index, node in enumerate(parsed.nodes) if node.tag.lower() == "table"
    )
    if not (first_body < last_table_index < transcriber_index):
        raise ConversionError("Unexpected final-matter ordering")

    root = tei_el("TEI", {"xml:lang": "en"})
    root.append(_header(_sha256(parsed.path)))
    text = tei_el("text")
    front = tei_el("front")
    body = tei_el("body")
    back = tei_el("back")
    text.extend((front, body, back))
    root.append(text)
    state = CarrierState()

    preliminaries = tei_el("div", {"type": "preliminaries", "xml:id": "poe-preliminaries"})
    for node in parsed.nodes[:first_body]:
        _convert_block(node, preliminaries, state)
    front.append(preliminaries)
    _append_electronic_contents(front, parsed)

    current: etree._Element | None = None
    section_count = 0
    for node in parsed.nodes[first_body : last_table_index + 1]:
        title = _chapter_title(node)
        if title is not None:
            if title not in SECTION_IDS:
                raise ConversionError(f"Unexpected body section title: {title!r}")
            current = tei_el(
                "div",
                {"type": "section", "xml:id": SECTION_IDS[title]},
            )
            body.append(current)
            _convert_chapter_heading(node, current, state)
            section_count += 1
        elif current is None:
            raise ConversionError("Body content appeared before its source-defined division")
        else:
            _convert_block(node, current, state)

    final_matter = tei_el("div", {"type": "final-matter", "xml:id": "poe-final-matter"})
    for node in parsed.nodes[last_table_index + 1 : transcriber_index]:
        _convert_block(node, final_matter, state)
    back.append(final_matter)

    transcriber = tei_el(
        "div",
        {"type": "transcribers-note", "xml:id": "poe-transcribers-note"},
    )
    transcriber_heading = _convert_chapter_heading(
        parsed.nodes[transcriber_index], transcriber, state
    )
    for node in transcriber_heading.itersiblings():
        if isinstance(node.tag, str):
            _convert_block(node, transcriber, state)
    back.append(transcriber)
    wrapper = tei_el("div", {"type": "source-wrapper", "xml:id": "poe-pg-end-wrapper"})
    wrapper.append(
        tei_el(
            "p",
            {"rend": "project-gutenberg-end-marker"},
            parsed.end_marker,
        )
    )
    back.append(wrapper)

    if tuple(state.source_texts) != parsed.carrier_texts:
        raise ConversionError("Source carrier traversal drifted from the parsed source model")
    tree = etree.ElementTree(root)
    stats: dict[str, object] = {
        "carrier_count": state.ordinal,
        "figure_count": len(tree.xpath("//tei:figure", namespaces=NS)),
        "page_count": len(tree.xpath("//tei:pb", namespaces=NS)),
        "section_count": section_count,
        "table_count": len(tree.xpath("//tei:table", namespaces=NS)),
    }
    return tree, stats


def _candidate_carriers(tree: etree._ElementTree) -> list[tuple[int, str]]:
    carriers = tree.xpath(
        "//*[@xml:id and starts-with(@xml:id, 'poe-src-B')]",
        namespaces=NS,
    )
    return sorted(
        (
            int(carrier.get("n")),
            _normalized_visible("".join(carrier.itertext())),
        )
        for carrier in carriers
    )


def accounting_errors(parsed: ParsedSource, tree: etree._ElementTree) -> list[str]:
    expected = list(enumerate(parsed.carrier_texts, start=1))
    actual = _candidate_carriers(tree)
    if expected == actual:
        return []
    errors: list[str] = []
    if len(expected) != len(actual):
        errors.append(f"source carrier count: expected {len(expected)}, found {len(actual)}")
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            errors.append(
                f"first source carrier mismatch at ordinal {index}: expected {left!r}, found {right!r}"
            )
            break
    return errors


def _source_members(raw_dir: Path) -> list[dict[str, object]]:
    direct_roles = {
        "pg55955-images.html": ("html-text-and-structure-authority", HTML_URL),
        "pg55955.txt": ("plain-text-crosscheck", TEXT_URL),
        "pg55955.rdf": ("project-gutenberg-metadata", RDF_URL),
        "gutenberg-55955-landing.html": ("project-gutenberg-landing", LANDING_URL),
        "openlibrary-OL25721931M.json": ("open-library-identity-and-contents", OPEN_LIBRARY_JSON_URL),
        "internet-archive-metadata.json": ("print-witness-metadata", "https://archive.org/metadata/ldpd_11375193_000"),
        "ldpd_11375193_000.pdf": ("bounded-print-witness", WITNESS_PDF_URL),
        "ldpd_11375193_000_djvu.xml": ("bounded-print-witness-ocr", "https://archive.org/download/ldpd_11375193_000/ldpd_11375193_000_djvu.xml"),
        "ldpd_11375193_000_djvu.txt": ("bounded-print-witness-ocr-text", "https://archive.org/download/ldpd_11375193_000/ldpd_11375193_000_djvu.txt"),
        "ldpd_11375193_000_scandata.xml": ("bounded-print-witness-scandata", "https://archive.org/download/ldpd_11375193_000/ldpd_11375193_000_scandata.xml"),
    }
    members: list[dict[str, object]] = []
    for path in sorted((item for item in raw_dir.rglob("*") if item.is_file()), key=lambda item: item.relative_to(raw_dir).as_posix()):
        relative = path.relative_to(raw_dir).as_posix()
        if relative.startswith("images/") and not relative.endswith(".headers.txt"):
            role = "project-gutenberg-image-member"
            url = f"https://www.gutenberg.org/cache/epub/55955/{relative}"
        else:
            role, url = direct_roles.get(
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
    retrieved = (raw_dir / "retrieved_at_utc.txt").read_text(encoding="utf-8").strip()
    return {
        "archive_members": [],
        "completeness_checks": {
            "ending": "Page 30 Departed 1914-1915 table, back matter images, the general transcriber repair note, and the Gutenberg end marker are retained.",
            "middle": "Five source-defined main divisions, pages 1-30, seven tables, lists, block quotations, twelve figure occurrences, and all eleven distinct referenced image members are represented.",
            "opening": "Cover/title text, issuing responsibility, both councils, the Joint Committee of Six, and organizational preliminaries are represented.",
            "unusual_features": "Page anchors, italic/bold/small-cap typography, statistical tables, signatures, figures/captions, and the non-enumerated repair statement are explicit.",
        },
        "credits": "Produced by ellinora, Larry B. Harrison, and the Online Distributed Proofreading Team.",
        "download_urls": [HTML_URL, TEXT_URL, RDF_URL, OPEN_LIBRARY_JSON_URL, WITNESS_PDF_URL],
        "edition": "New York: Joint Committee of Six, 1915",
        "identity": "provisional net-new candidate; no canonical WorkCatalog write",
        "landing_url": LANDING_URL,
        "omissions_from_tei": [
            "Project Gutenberg header/footer license boilerplate remains in retained raw evidence; only the exact end marker is represented as source-wrapper evidence.",
            "Internet Archive OCR is not used as text authority because it contains ordinary OCR errors; the scan is a bounded identity/text witness only.",
        ],
        "open_library_contents": {
            "entries": [{"page": page, "title": title} for title, page in parsed.toc_entries],
            "representation": "Explicit electronic navigation metadata, not asserted as printed contents matter.",
        },
        "repairs": {
            "source_statement": "Obvious punctuation and spelling errors have been repaired.",
            "granularity": "Project Gutenberg does not enumerate individual repairs; the surfaced Project Gutenberg readings and this limitation are retained without further silent correction.",
        },
        "retrieved_at_utc": retrieved,
        "rights_and_attribution": {
            "attribution": "Retain Project Gutenberg 55955, its production credits, and the Open Library/Internet Archive witness identifiers.",
            "status": "Project Gutenberg states public domain in the USA.",
            "unresolved": "Rights outside the USA and Project Gutenberg trademark or redistribution terms require separate review before publication.",
        },
        "source_members": _source_members(raw_dir),
        "source_responsibility": {
            "issued_by": "Joint Committee of Six",
            "represented_organizations": [
                "Home Missions Council of the United States",
                "Council of Women for Home Missions",
            ],
        },
        "source_title": "Ports of Entry: Missionary Herald",
        "transformations": [
            "Parsed the retained UTF-8 Project Gutenberg HTML between its boilerplate header and footer.",
            "Mapped source-defined divisions, paragraphs, lists, quotations, tables, figures, and typographic emphasis to TEI without modernizing wording.",
            "Mapped all thirty Project Gutenberg Page_N anchors to TEI pb milestones in document order.",
            "Represented the four Open Library contents entries separately as electronic navigation metadata.",
            "Preserved the general transcriber repair statement; no additional corrections were introduced.",
        ],
        "unresolved_questions": [
            "The exact punctuation and spelling repairs performed by Project Gutenberg are not individually enumerated.",
            "Human identity, edition, rights, textual, and editorial acceptance remain outside this candidate packet.",
        ],
        "witness": {
            "internet_archive_identifier": "ldpd_11375193_000",
            "open_library_edition": "OL25721931M",
            "pdf_md5_matches_archive_metadata": True,
            "purpose": "bounded identity and text witness only",
            "url": WITNESS_URL,
        },
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
    page_numbers = tuple(int(value) for value in tree.xpath("//tei:pb/@n", namespaces=NS))
    if page_numbers != parsed.page_numbers:
        raise ConversionError("Candidate page milestones differ from the retained HTML")
    source_ids = [f"poe-src-B{ordinal:04d}" for ordinal in range(1, len(parsed.carrier_texts) + 1)]
    candidate_ids = tree.xpath(
        "//*[@xml:id and starts-with(@xml:id, 'poe-src-B')]/@xml:id",
        namespaces=NS,
    )
    accounting = {
        "candidate_carrier_count": len(carriers),
        "candidate_carrier_stream_sha256": _digest(value for _ordinal, value in carriers),
        "duplicated_source_carrier_ids": sorted({value for value in candidate_ids if candidate_ids.count(value) > 1}),
        "electronic_contents_entry_count": len(parsed.toc_entries),
        "emphasis_counts": {
            value: len(tree.xpath(f"//tei:hi[contains(concat(' ', @rend, ' '), ' {value} ')]", namespaces=NS))
            for value in ("bold", "italic", "small-caps", "subscript", "superscript")
        },
        "figure_count": stats["figure_count"],
        "distinct_figure_member_count": len(set(parsed.figure_sources)),
        "figure_sources": list(parsed.figure_sources),
        "list_item_count": len(tree.xpath("//tei:list/tei:item", namespaces=NS)),
        "main_section_count": stats["section_count"],
        "main_section_titles": list(parsed.section_titles),
        "omitted_source_carrier_ids": sorted(set(source_ids) - set(candidate_ids)),
        "page_milestone_count": stats["page_count"],
        "page_milestone_sequence": list(page_numbers),
        "source_carrier_count": len(parsed.carrier_texts),
        "source_carrier_stream_sha256": _digest(parsed.carrier_texts),
        "source_sha256": _sha256(source_path),
        "table_cell_count": len(tree.xpath("//tei:table/tei:row/tei:cell", namespaces=NS)),
        "table_count": stats["table_count"],
        "table_row_count": len(tree.xpath("//tei:table/tei:row", namespaces=NS)),
        "transcriber_repair_note_count": len(
            tree.xpath("//tei:div[@type='transcribers-note']", namespaces=NS)
        ),
    }
    if accounting["source_carrier_stream_sha256"] != accounting["candidate_carrier_stream_sha256"]:
        raise ConversionError("Normalized source and TEI carrier digests differ")
    if accounting["omitted_source_carrier_ids"] or accounting["duplicated_source_carrier_ids"]:
        raise ConversionError("Source carrier identity accounting failed")

    receipt_path = report_dir / "receipt.json"
    accounting_path = report_dir / "accounting.json"
    validation_path = report_dir / "validation.json"
    _write_json(receipt_path, _receipt(parsed))
    _write_json(accounting_path, accounting)
    _write_json(
        validation_path,
        {
            "accounting_errors": [],
            "candidate_sha256": _sha256(output_path),
            "status": "technically_valid_nonaccepted_candidate",
            "tei_p5_xsd_errors": [],
            "tei_p5_xsd_valid": True,
        },
    )
    return ConversionResult(
        output_path,
        receipt_path,
        accounting_path,
        validation_path,
        len(carriers),
        int(stats["figure_count"]),
        int(stats["page_count"]),
        int(stats["section_count"]),
        int(stats["table_count"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    result = convert(args.source, args.output, args.report_dir)
    print(
        json.dumps(
            {
                "accounting": str(result.accounting_path),
                "carriers": result.carrier_count,
                "figures": result.figure_count,
                "output": str(result.output_path),
                "pages": result.page_count,
                "receipt": str(result.receipt_path),
                "sections": result.section_count,
                "tables": result.table_count,
                "validation": str(result.validation_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
