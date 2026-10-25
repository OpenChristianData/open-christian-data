"""Independent retained-HTML comparison for Elmslie PG71811."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import re

from lxml import etree, html

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/gutenberg/71811/html/pg71811-images.html")
SOURCE_SHA256 = "c423067697dc9d0ce52d7066548db97910af541f2255699e2926fd71b4d3a722"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _display(node: etree._Element) -> str:
    if node.tag == TEI + "expan":
        return ""
    return (node.text or "") + "".join(_display(child) + (child.tail or "") for child in node)


def check(candidate: bytes) -> dict[str, object]:
    raw = _io_path(ROOT / SOURCE).read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG71811 source digest differs")
    raw.decode("utf-8", errors="strict")
    source = html.fromstring(raw, parser=html.HTMLParser(encoding="utf-8"))
    body = source.find(".//body")
    if body is None:
        raise ValueError("PG71811 source body absent")
    tei = etree.fromstring(candidate, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    selected = tei.xpath("./t:text/t:body/t:div[@type='complete-retained-html-body']", namespaces=NS)
    if len(selected) != 1:
        raise ValueError("PG71811 candidate body boundary differs")
    block = selected[0]
    displayed_source = _normalized("".join(body.itertext()))
    displayed_tei = _normalized(_display(block))
    if displayed_source != displayed_tei:
        mismatch = next((index for index, pair in enumerate(zip(displayed_source, displayed_tei)) if pair[0] != pair[1]), min(len(displayed_source), len(displayed_tei)))
        raise ValueError(f"PG71811 displayed source text differs at character {mismatch}")

    source_abbr = [node for node in body.iter("abbr")]
    choices = block.xpath(".//t:choice", namespaces=NS)
    if len(source_abbr) != 7255 or len(choices) != len(source_abbr):
        raise ValueError("PG71811 title-bearing abbreviation count differs")
    for index, (source_node, choice) in enumerate(zip(source_abbr, choices), 1):
        if (list(choice.attrib) or [child.tag for child in choice] != [TEI + "abbr", TEI + "expan"]
                or (choice.text or "").strip() or any((child.tail or "").strip() for child in choice)
                or "".join(source_node.itertext()) != "".join(choice[0].itertext())
                or source_node.get("title") != choice[1].text or len(choice[1]) or choice[1].attrib):
            raise ValueError(f"PG71811 abbreviation choice differs at {index}")

    source_links = [node.get("href") for node in body.iter("a") if node.get("href")]
    candidate_links = [node.get("target") if node.tag == TEI + "ref" else node.get("corresp")
                       for node in block.iter() if (node.tag == TEI + "ref" and node.get("target"))
                       or (node.tag == TEI + "graphic" and node.get("corresp"))]
    if len(source_links) != 2543 or candidate_links != source_links:
        raise ValueError("PG71811 ordered literal HTML hrefs differ")
    source_ids = [node.get("id") for node in body.iter() if isinstance(node.tag, str) and node.get("id")]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("PG71811 source duplicate IDs")
    tei_ids = {node.get(XML_ID) for node in block.iter() if node.get(XML_ID)}
    figure_wrapper_ids = {anchor.get("id") for figure in body.iter("figure") for anchor in figure.iter("a")}
    if set(source_ids) - tei_ids != figure_wrapper_ids or len(figure_wrapper_ids) != 5:
        raise ValueError("PG71811 source ID accounting differs")
    if any(link.startswith("#") and (link[1:] not in source_ids or link[1:] not in tei_ids) for link in source_links):
        raise ValueError("PG71811 local fragment target differs")

    source_figures = list(body.iter("figure"))
    figures = block.xpath(".//t:figure", namespaces=NS)
    if len(source_figures) != len(figures) or len(figures) != 6:
        raise ValueError("PG71811 six source figures differ")
    for index, (source_figure, figure) in enumerate(zip(source_figures, figures), 1):
        source_images = list(source_figure.iter("img"))
        graphics = figure.xpath(".//t:graphic", namespaces=NS)
        if (len(source_images) != 1 or len(graphics) != 1
                or figure.get(XML_ID) != source_figure.get("id")
                or graphics[0].get("url") != source_images[0].get("src")
                or (graphics[0].get("n") or "") != (source_images[0].get("alt") or "")):
            raise ValueError(f"PG71811 figure/image support differs at {index}")
        source_captions = list(source_figure.iter("figcaption"))
        caption_paragraphs = figure.xpath("./t:p[contains(@rend, 'source-figcaption')]", namespaces=NS)
        if (len(source_captions) > 1 or len(caption_paragraphs) != sum(len(caption) for caption in source_captions)
                or [_normalized("".join(paragraph.itertext())) for caption in source_captions for paragraph in caption]
                != [_normalized("".join(paragraph.itertext())) for paragraph in caption_paragraphs]):
            raise ValueError(f"PG71811 figure caption differs at {index}")

    source_tables = list(body.iter("table"))
    tables = block.xpath(".//t:table", namespaces=NS)
    if len(source_tables) != 3 or len(tables) != 3:
        raise ValueError("PG71811 table count differs")
    for table_number, (source_table, table) in enumerate(zip(source_tables, tables), 1):
        source_rows = list(source_table.iter("tr"))
        rows = table.xpath("./t:row", namespaces=NS)
        if len(source_rows) != len(rows):
            raise ValueError(f"PG71811 table row count differs at {table_number}")
        for row_number, (source_row, row) in enumerate(zip(source_rows, rows), 1):
            source_cells = list(source_row.iter("td"))
            cells = row.xpath("./t:cell", namespaces=NS)
            if (len(source_cells) != len(cells)
                    or [_normalized("".join(node.itertext())) for node in source_cells]
                    != [_normalized(_display(node)) for node in cells]
                    or [(node.get("colspan") or "1") for node in source_cells]
                    != [(node.get("cols") or "1") for node in cells]):
                raise ValueError(f"PG71811 table cells differ at {table_number}:{row_number}")

    definitions = list(body.iter("dl"))
    tei_lists = block.xpath(".//t:list[@type='definition']", namespaces=NS)
    if len(definitions) != 1 or len(tei_lists) != 1:
        raise ValueError("PG71811 definition list differs")
    source_entries = list(definitions[0])
    items = list(tei_lists[0])
    if len(source_entries) != 1288 or len(items) != len(source_entries):
        raise ValueError("PG71811 definition entry count differs")
    for index, (source_entry, item) in enumerate(zip(source_entries, items), 1):
        role = "source-term" if source_entry.tag == "dt" else "source-definition"
        source_class = source_entry.get("class")
        expected_rend = role + (" source-class:" + " ".join(source_class.split()) if source_class else "")
        if (source_entry.tag not in {"dt", "dd"} or item.tag != TEI + "item"
                or item.get("rend") != expected_rend
                or _normalized("".join(source_entry.itertext())) != _normalized(_display(item))):
            raise ValueError(f"PG71811 definition entry differs at {index}")

    source_comment = body.xpath(".//comment()")
    if (len(source_comment) != 1
            or source_comment[0].text != ' WIP line in red\r\n<hr id="WIP"> page +0 ― Note #: 467 '):
        raise ValueError("PG71811 source editorial comment differs")
    source_tags = Counter(node.tag for node in body.iter() if isinstance(node.tag, str))
    return {
        "contract": "ocd-elmslie-pg71811-independent-html-oracle-v1",
        "source_sha256": SOURCE_SHA256,
        "candidate_sha256": sha256(candidate).hexdigest(),
        "displayed_text_sha256": sha256(displayed_source.encode("utf-8")).hexdigest(),
        "source_tags": dict(sorted(source_tags.items())),
        "abbreviation_choices": len(choices), "hrefs": len(source_links),
        "figures": len(figures), "image_refs": sum(len(list(figure.iter("img"))) for figure in source_figures),
        "table_rows": [len(list(table.iter("tr"))) for table in source_tables],
        "table_cells": [len(list(table.iter("td"))) for table in source_tables],
        "definition_terms": sum(entry.tag == "dt" for entry in source_entries),
        "definition_descriptions": sum(entry.tag == "dd" for entry in source_entries),
        "source_id_count": len(source_ids), "private_figure_wrapper_ids": sorted(figure_wrapper_ids),
        "source_editorial_comment_sha256": sha256(source_comment[0].text.encode("utf-8")).hexdigest(),
        "source_head_disposition": "Retained real HTML remains the authority; HTML head metadata and CSS are support, not silently promoted into body text.",
    }
