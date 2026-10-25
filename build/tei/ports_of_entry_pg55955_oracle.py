"""Independent complete HTML-body and retained-image oracle for PG55955."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from lxml import etree, html

from build.tei.ports_of_entry_pg55955_native import (
    IMAGE_NAMES, NS, SOURCE_SHA256, SOURCE_URL, XML_ID, image_bindings, source_path,
)


CONTRACT = "ocd-ports-of-entry-pg55955-independent-html-oracle-v1"
SECTIONS = (
    "Ports of Entry", "Ellis Island", "Boston Port of Entry",
    "Philadelphia Port of Entry", "The Philadelphia Immigration Station",
)
END_MARKER = "*** END OF THE PROJECT GUTENBERG EBOOK PORTS OF ENTRY: MISSIONARY HERALD ***"


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _visible(node: etree._Element) -> str:
    parts: list[str] = []

    def visit(element: etree._Element) -> None:
        if element.text:
            parts.append(element.text)
        for child in element:
            if isinstance(child.tag, str):
                classes = (child.get("class") or "").split()
                if child.tag == "br":
                    parts.append(" ")
                elif child.tag == "img" or (child.tag == "span" and "pagenum" in classes):
                    pass
                else:
                    visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return _normalized("".join(parts))


def _figure_label(node: etree._Element, document: etree._Element) -> str:
    reference = node.get("aria-labelledby")
    if reference:
        matches = document.xpath("//*[@id=$label]", label=reference)
        if len(matches) == 1 and _visible(matches[0]):
            return _visible(matches[0])
    for caption in node.xpath(".//*[contains(concat(' ',normalize-space(@class),' '),' caption ')]"):
        if _visible(caption):
            return _visible(caption)
    return " ".join(_normalized(alt) for alt in node.xpath(".//img/@alt")
                    if _normalized(alt) not in ("", "Image"))


def _carriers(node: etree._Element, document: etree._Element) -> list[str]:
    if node.xpath(".//img"):
        label = _figure_label(node, document)
        return [label] if label else []
    if node.tag in {"h1", "h2", "h3", "h4", "p", "li", "td", "th"}:
        value = _visible(node)
        result = [value] if value else []
        if node.tag == "li":
            for nested in node.xpath("./ul|./ol"):
                result.extend(_carriers(nested, document))
        return result
    if node.tag in {"ul", "ol"}:
        return [value for item in node.xpath("./li") for value in _carriers(item, document)]
    if node.tag == "table":
        return [value for cell in node.xpath(".//th|.//td") for value in _carriers(cell, document)]
    if node.tag in {"blockquote", "div"}:
        return [value for child in node if isinstance(child.tag, str)
                for value in _carriers(child, document)]
    return []


def check(candidate: bytes, *, source: Path | None = None) -> dict:
    raw = (source or source_path()).read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG55955 retained HTML hash differs")
    document = html.fromstring(raw)
    bodies = document.xpath("//body")
    if len(bodies) != 1:
        raise ValueError("PG55955 HTML body count differs")
    direct = [node for node in bodies[0] if isinstance(node.tag, str)]
    starts = [i for i, node in enumerate(direct) if node.get("id") == "pg-header"]
    ends = [i for i, node in enumerate(direct) if node.get("id") == "pg-footer"]
    if len(starts) != 1 or len(ends) != 1 or starts[0] != 0 or ends[0] != 234:
        raise ValueError("PG55955 header/footer boundary differs")
    selected = direct[starts[0] + 1:ends[0]]
    if (len(selected) != 233 or sum(node.tag == "hr" for node in selected) != 15
            or sum(node.tag == "div" and not _normalized("".join(node.itertext()))
                   and not node.xpath(".//img") for node in selected) != 2):
        raise ValueError("PG55955 complete selected body or spacer census differs")
    expected = [value for node in selected for value in _carriers(node, document)]
    root = etree.fromstring(candidate)
    actual_nodes = [node for node in root.iter()
                    if (node.get(XML_ID) or "").startswith("poe-src-B")]
    actual = [_normalized("".join(node.itertext())) for node in actual_nodes]
    ids = [node.get(XML_ID) for node in actual_nodes]
    if len(expected) != 868 or ids != [f"poe-src-B{i:04d}" for i in range(1, 869)]:
        raise ValueError("PG55955 carrier cardinality or source IDs differ")
    if expected != actual:
        for index, (left, right) in enumerate(zip(expected, actual), 1):
            if left != right:
                raise ValueError(f"PG55955 source carrier {index} differs: {left!r} != {right!r}")
        raise ValueError("PG55955 source carrier stream differs")
    source_sections = [_visible(node.xpath(".//h2")[0]) for node in selected
                       if node.tag == "div" and "chapter" in (node.get("class") or "").split()]
    if source_sections != [*SECTIONS, "Transcriber's Note"]:
        raise ValueError("PG55955 six source sections differ")
    tei_sections = root.xpath("/tei:TEI/tei:text/tei:body/tei:div[@type='section']/tei:head", namespaces=NS)
    if [_normalized("".join(head.itertext())) for head in tei_sections] != list(SECTIONS):
        raise ValueError("PG55955 five intellectual work sections differ")
    images = [src for node in selected for src in node.xpath(".//img/@src")]
    image_names = [Path(src).name for src in images]
    if len(images) != 12 or sorted(set(image_names)) != sorted(IMAGE_NAMES):
        raise ValueError("PG55955 complete source image references differ")
    graphics = root.xpath("//tei:figure/tei:graphic/@url", namespaces=NS)
    if graphics != [SOURCE_URL.rsplit("/", 1)[0] + "/" + src for src in images]:
        raise ValueError("PG55955 TEI image occurrence order differs")
    source_pages = [int(value.removeprefix("Page_")) for value in document.xpath(
        "//span[contains(concat(' ',normalize-space(@class),' '),' pagenum ')]/a[starts-with(@id,'Page_')]/@id")]
    tei_pages = [int(value) for value in root.xpath("//tei:pb/@n", namespaces=NS)]
    if source_pages != list(range(1, 31)) or tei_pages != source_pages:
        raise ValueError("PG55955 page-marker sequence differs")
    if len(document.xpath("//body//table")) != 7 or len(root.xpath("//tei:table", namespaces=NS)) != 7:
        raise ValueError("PG55955 seven source tables differ")
    if END_MARKER not in _normalized("".join(direct[ends[0]].itertext())):
        raise ValueError("PG55955 Gutenberg end marker is missing")
    back = root.xpath("/tei:TEI/tei:text/tei:back/tei:div[@type='source-wrapper']", namespaces=NS)
    if len(back) != 1 or END_MARKER not in _normalized("".join(back[0].itertext())):
        raise ValueError("PG55955 provider footer is not accounted in TEI back")
    titles = root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)
    if len(titles) != 1 or _normalized("".join(titles[0].itertext())) != "Ports of Entry: Missionary Herald":
        raise ValueError("PG55955 electronic title differs")
    support = image_bindings()
    return dict(contract=CONTRACT, source_sha256=SOURCE_SHA256,
                candidate_sha256=sha256(candidate).hexdigest(), body_direct_children=len(direct),
                selected_children=len(selected), excluded_empty_spacers=2,
                horizontal_rules=15, source_carriers=len(expected),
                source_carrier_sha256=sha256("\n".join(expected).encode()).hexdigest(),
                sections=len(SECTIONS), page_markers=len(source_pages), tables=7,
                image_occurrences=len(images), image_members=len(support),
                image_support_sha256={Path(item["path"]).name: item["sha256"] for item in support},
                gutenberg_end_marker_in_back=True)
