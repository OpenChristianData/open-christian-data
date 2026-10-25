"""Faithfully convert Project Gutenberg 56487 HTML into deterministic TEI P5.

The retained witness is the 1765 Baskerville eighth English edition of Robert
Barclay's *An Apology for the True Christian Divinity*.  This converter is
deliberately source-specific: it validates the exact retained byte stream and
its structural census before translating Gutenberg's HTML semantics into TEI.
It preserves the source-defined front matter, all fifteen propositions,
conclusion, two indexes, errata, transcriber's note, footnotes, margin notes,
page milestones, typographic distinctions, and explicit sic/corr evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
from collections import Counter
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.writer import TEI_NS, XML_ID, serialize, stamp_header, tei_el


NS = {"tei": TEI_NS}
SLUG = "barclay-apology-true-christian-divinity"
EXPECTED_SOURCE_SHA256 = "0e28cb9ff0b8e9063337c06337d702048df463fd4f50ed11a7517bd7940b4874"
SOURCE_RELATIVE_PATH = (
    "raw/clean-ready-acquisition-to-tei/master-4/28/"
    f"{SLUG}/56487-h.htm"
)
SOURCE_URL = "https://www.gutenberg.org/files/56487/56487-h/56487-h.htm"
LANDING_URL = "https://www.gutenberg.org/ebooks/56487"

EXPECTED_SOURCE_COUNTS = {
    "top_level_work_sections": 24,
    "top_level_chapters": 23,
    "transcriber_notes": 1,
    "page_milestones": 516,
    "footnote_anchors": 171,
    "footnote_bodies": 171,
    "margin_notes": 1361,
    "corrections": 139,
    "tables": 3,
    "images": 0,
}

BLOCK_TAGS = {"div", "h1", "h2", "h3", "h4", "hr", "p", "table", "ul"}
INLINE_SPAN_RENDS = {
    "center": "center",
    "chapter-head": "chapter-head",
    "gesperrt": "letter-spaced",
    "in4": "indent-4",
    "large": "large",
    "larger": "larger",
    "medium": "medium",
    "mobile-only": "mobile-only",
    "right": "right",
    "smaller": "smaller",
    "smcap": "small-caps",
}

CORRECTION_READING_PREFIXES = (
    "In the original book: ",
    "Erratum: originally: ",
)


class SourceMismatchError(ValueError):
    """The retained source or generated candidate violates the released contract."""


@dataclass
class _ConversionState:
    consumed_source_ids: set[str] = field(default_factory=set)
    section_counts: Counter[str] = field(default_factory=Counter)


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of one file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source_path(repository_root: Path) -> Path:
    """Resolve the released retained source through local storage topology."""
    return resolve_repo_path(repository_root, SOURCE_RELATIVE_PATH)


def _parse_html(source: Path) -> etree._ElementTree:
    # Gutenberg's legacy XHTML emits both name="X" and id="X" on the same
    # anchor. libxml2 reports that single element as a duplicate HTML ID when
    # recovery is disabled. The exact source SHA and complete structural census
    # below remain the fail-closed authority for this known syntax quirk.
    parser = html.HTMLParser(encoding="utf-8", recover=True)
    return html.parse(str(source), parser=parser)


def _classes(element: etree._Element) -> set[str]:
    return set((element.get("class") or "").split())


def _source_work_sections(document: etree._ElementTree) -> list[etree._Element]:
    body = document.getroot().find("body")
    if body is None:
        raise SourceMismatchError("retained HTML has no body")
    children = list(body)
    if len(children) != 26 or children[0].tag != "pre" or children[-1].tag != "pre":
        raise SourceMismatchError("unexpected Gutenberg wrapper or work-section boundary")
    return children[1:-1]


def _normalized_space(value: str) -> str:
    return " ".join(value.split())


def _source_visible_text(element: etree._Element) -> str:
    """Project logical work text, excluding page labels represented as TEI pb."""
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        if node.tag == "span" and "pagenum" in _classes(node):
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(element)
    return _normalized_space(" ".join(parts))


def _source_logical_text(sections: Iterable[etree._Element]) -> str:
    return _normalized_space(" ".join(_source_visible_text(section) for section in sections))


def _candidate_visible_text(element: etree._Element) -> str:
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        local = etree.QName(node).localname
        if local in {"pb", "sic"}:
            return
        if local == "choice":
            corr = node.find(f"{{{TEI_NS}}}corr")
            if corr is None:
                raise SourceMismatchError("choice has no corr reading")
            walk(corr)
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(element)
    return _normalized_space(" ".join(parts))


def _candidate_logical_text(tree: etree._ElementTree) -> str:
    text = tree.find(f"{{{TEI_NS}}}text")
    if text is None:
        raise SourceMismatchError("candidate has no TEI text")
    return _candidate_visible_text(text)


def _main_proposition_labels(sections: list[etree._Element]) -> list[str]:
    labels: list[str] = []
    for section in sections:
        for heading in section.xpath("./h2"):
            value = _normalized_space(heading.text_content()).rstrip(".")
            if value.startswith("PROPOSITION"):
                labels.append(value)
    return labels


def audit_source(source: Path) -> dict[str, Any]:
    """Verify the exact Gutenberg witness and return its source census."""
    source_hash = sha256_file(source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SourceMismatchError(
            f"source SHA-256 {source_hash} does not match {EXPECTED_SOURCE_SHA256}"
        )
    document = _parse_html(source)
    root = document.getroot()
    sections = _source_work_sections(document)
    body_text = _normalized_space(root.find("body").text_content())
    required_phrases = (
        "The Eighth Edition in ENGLISH.",
        "Printed by JOHN BASKERVILLE",
        "M DCC LXV.",
        "An Apology for the True Christian Divinity",
    )
    missing_phrases = [phrase for phrase in required_phrases if phrase not in body_text]
    if missing_phrases:
        raise SourceMismatchError(f"source identity phrases missing: {missing_phrases}")

    counts = {
        "top_level_work_sections": len(sections),
        "top_level_chapters": len(
            [
                section
                for section in sections
                if "chapter" in _classes(section) and "transnote" not in _classes(section)
            ]
        ),
        "transcriber_notes": len(
            [section for section in sections if "transnote" in _classes(section)]
        ),
        "page_milestones": len(root.xpath("//span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')]")),
        "footnote_anchors": len(root.xpath("//a[contains(concat(' ', normalize-space(@class), ' '), ' fnanchor ')]")),
        "footnote_bodies": len(root.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' footnote ')]")),
        "margin_notes": len(root.xpath("//span[contains(concat(' ', normalize-space(@class), ' '), ' sidenote ')]")),
        "corrections": len(root.xpath("//span[contains(concat(' ', normalize-space(@class), ' '), ' correction ')]")),
        "tables": len(root.xpath("//table")),
        "images": len(root.xpath("//img")),
    }
    if counts != EXPECTED_SOURCE_COUNTS:
        raise SourceMismatchError(
            f"source census differs from released witness: {counts} != {EXPECTED_SOURCE_COUNTS}"
        )

    anchor_targets = {
        anchor.get("href", "").removeprefix("#")
        for anchor in root.xpath("//a[contains(concat(' ', normalize-space(@class), ' '), ' fnanchor ')]")
    }
    footnote_ids = {
        anchor.get("id")
        for anchor in root.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' footnote ')]//a[@id]")
        if (anchor.get("id") or "").startswith("Footnote_")
    }
    if anchor_targets != footnote_ids:
        raise SourceMismatchError("footnote anchors and bodies do not form a closed set")

    page_ids = [
        anchor.get("id")
        for anchor in root.xpath("//span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')]/a[@id]")
    ]
    if len(page_ids) != len(set(page_ids)) or any(not value for value in page_ids):
        raise SourceMismatchError("page milestone IDs are missing or duplicated")

    correction_titles = [
        correction.get("title", "")
        for correction in root.xpath("//span[contains(concat(' ', normalize-space(@class), ' '), ' correction ')]")
    ]
    if any(not title for title in correction_titles):
        raise SourceMismatchError("one or more corrections lack source intervention evidence")

    all_tags = {element.tag for section in sections for element in section.iter()}
    expected_tags = {
        "a", "b", "br", "col", "colgroup", "div", "h1", "h2", "h3", "h4",
        "hr", "i", "li", "p", "span", "table", "td", "tr", "ul",
    }
    if all_tags - expected_tags:
        raise SourceMismatchError(f"unhandled source tags: {sorted(all_tags - expected_tags)}")

    proposition_labels = _main_proposition_labels(sections)
    expected_labels = [
        "PROPOSITION I", "PROPOSITION II", "PROPOSITION III", "PROPOSITION IV",
        "PROPOSITIONS V. & VI", "PROPOSITION VII", "PROPOSITION VIII",
        "PROPOSITION IX", "PROPOSITION X", "PROPOSITION XI", "PROPOSITION XII",
        "PROPOSITION XIII", "PROPOSITION XIV", "PROPOSITION XV",
    ]
    if proposition_labels != expected_labels:
        raise SourceMismatchError(f"unexpected proposition sequence: {proposition_labels}")

    logical_text = _source_logical_text(sections)
    return {
        "source_sha256": source_hash,
        "source_bytes": source.stat().st_size,
        "source_counts": counts,
        "proposition_labels": proposition_labels,
        "logical_text_sha256": hashlib.sha256(logical_text.encode("utf-8")).hexdigest(),
        "logical_text_characters": len(logical_text),
        "gutenberg_wrapper_excluded_from_candidate_text": True,
    }


def _append_text(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    normalized = re.sub(r"\s+", " ", value)
    if not normalized:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + normalized
    else:
        parent.text = (parent.text or "") + normalized


def _valid_xml_id(value: str | None) -> str | None:
    if not value:
        return None
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9._-]*", value) else None


def _first_structural_id(source_div: etree._Element) -> str | None:
    for value in source_div.xpath(".//a/@id"):
        if not value.startswith(("Page_", "FNanchor_", "Footnote_")):
            return _valid_xml_id(value)
    return None


def _page_break(source_span: etree._Element) -> etree._Element:
    anchors = source_span.xpath("./a[@id]")
    if len(anchors) != 1:
        raise SourceMismatchError("page milestone does not contain exactly one source ID")
    page_id = _valid_xml_id(anchors[0].get("id"))
    label = _normalized_space(source_span.text_content())
    match = re.fullmatch(r"\[Pg\s+(.+)]", label) if label else None
    if page_id is None or (label and match is None):
        raise SourceMismatchError(f"invalid page milestone {page_id!r}: {label!r}")
    page_number = match.group(1) if match is not None else page_id.removeprefix("Page_")
    return tei_el("pb", {"xml:id": page_id, "n": page_number})


def _copy_inline(
    source: etree._Element,
    target: etree._Element,
    state: _ConversionState,
) -> None:
    _append_text(target, source.text)
    for child in source:
        _convert_inline_child(child, target, state)
        _append_text(target, child.tail)


def _convert_inline_child(
    source: etree._Element,
    target: etree._Element,
    state: _ConversionState,
) -> None:
    tag = source.tag
    classes = _classes(source)
    if tag == "br":
        target.append(tei_el("lb"))
        return
    if tag == "span" and "pagenum" in classes:
        target.append(_page_break(source))
        return
    if tag == "span" and "sidenote" in classes:
        note = tei_el("note", {"place": "margin"})
        _copy_inline(source, note, state)
        target.append(note)
        return
    if tag == "span" and "correction" in classes:
        title = source.get("title", "")
        if not title:
            raise SourceMismatchError("correction lacks source intervention evidence")
        original = next(
            (
                title.removeprefix(prefix)
                for prefix in CORRECTION_READING_PREFIXES
                if title.startswith(prefix)
            ),
            title,
        )
        choice = tei_el("choice")
        choice.append(tei_el("sic", text=original))
        corr = tei_el("corr")
        _copy_inline(source, corr, state)
        choice.append(corr)
        target.append(choice)
        return
    if tag == "span" and "label" in classes:
        node = tei_el("label")
        _copy_inline(source, node, state)
        target.append(node)
        return
    if tag in {"i", "b"} or tag == "span":
        if tag == "i":
            rend = "italic"
        elif tag == "b":
            rend = "bold"
        else:
            known = [INLINE_SPAN_RENDS[name] for name in sorted(classes) if name in INLINE_SPAN_RENDS]
            unknown = classes - INLINE_SPAN_RENDS.keys()
            if unknown:
                raise SourceMismatchError(f"unhandled inline span classes: {sorted(unknown)}")
            rend = " ".join(known) if known else "span"
        node = tei_el("hi", {"rend": rend})
        _copy_inline(source, node, state)
        target.append(node)
        return
    if tag == "a":
        anchor_id = _valid_xml_id(source.get("id"))
        href = source.get("href")
        if href:
            attrs = {"target": href}
            if anchor_id and anchor_id not in state.consumed_source_ids:
                attrs["xml:id"] = anchor_id
            if "fnanchor" in classes:
                attrs["type"] = "note"
            node = tei_el("ref", attrs)
            _copy_inline(source, node, state)
            target.append(node)
        elif anchor_id and anchor_id not in state.consumed_source_ids:
            target.append(tei_el("anchor", {"xml:id": anchor_id}))
        else:
            _copy_inline(source, target, state)
        return
    raise SourceMismatchError(f"unhandled inline tag: {tag}")


def _rend_for(source: etree._Element) -> str | None:
    classes = _classes(source)
    known = [INLINE_SPAN_RENDS[name] for name in sorted(classes) if name in INLINE_SPAN_RENDS]
    unknown = classes - INLINE_SPAN_RENDS.keys() - {
        "hang", "index", "indx", "isub1", "padtop", "p2", "tdr", "col-wid",
    }
    known.extend(sorted(classes & {"hang", "index", "indx", "isub1", "padtop", "p2", "tdr", "col-wid"}))
    if unknown:
        raise SourceMismatchError(f"unhandled block classes: {sorted(unknown)}")
    return " ".join(known) or None


def _paragraph(source: etree._Element, state: _ConversionState) -> etree._Element:
    attrs: dict[str, str] = {}
    rend = _rend_for(source)
    if rend:
        attrs["rend"] = rend
    paragraph = tei_el("p", attrs)
    _copy_inline(source, paragraph, state)
    return paragraph


def _heading(source: etree._Element, state: _ConversionState) -> etree._Element | None:
    head = tei_el("head")
    _copy_inline(source, head, state)
    visible = _normalized_space("".join(head.itertext()))
    has_anchor = bool(head.xpath(".//tei:anchor", namespaces=NS))
    if not visible and not has_anchor:
        return None
    return head


def _footnote(source: etree._Element, state: _ConversionState) -> etree._Element:
    ids = [
        _valid_xml_id(value)
        for value in source.xpath(".//a/@id")
        if value.startswith("Footnote_")
    ]
    ids = [value for value in ids if value]
    if len(ids) != 1:
        raise SourceMismatchError(f"footnote does not have one usable ID: {ids}")
    note = tei_el("note", {"place": "foot", "xml:id": ids[0]})
    state.consumed_source_ids.add(ids[0])
    paragraphs = source.xpath("./p")
    if not paragraphs:
        raise SourceMismatchError(f"footnote {ids[0]} has no paragraph")
    for source_paragraph in paragraphs:
        note.append(_paragraph(source_paragraph, state))
    return note


def _table(source: etree._Element, state: _ConversionState) -> etree._Element:
    attrs: dict[str, str] = {}
    if source.get("summary"):
        attrs["rend"] = f"summary: {source.get('summary')}"
    if source.get("id"):
        table_id = _valid_xml_id(source.get("id"))
        if table_id:
            attrs["xml:id"] = table_id
            state.consumed_source_ids.add(table_id)
    table = tei_el("table", attrs)
    for row_source in source.xpath("./tr|./tbody/tr"):
        row = tei_el("row")
        for cell_source in row_source.xpath("./td"):
            cell_attrs: dict[str, str] = {}
            if cell_source.get("colspan"):
                cell_attrs["cols"] = cell_source.get("colspan")
            rend = _rend_for(cell_source)
            if rend:
                cell_attrs["rend"] = rend
            cell = tei_el("cell", cell_attrs)
            _copy_inline(cell_source, cell, state)
            row.append(cell)
        table.append(row)
    return table


def _list(source: etree._Element, state: _ConversionState) -> etree._Element:
    attrs: dict[str, str] = {}
    rend = _rend_for(source)
    if rend:
        attrs["rend"] = rend
    result = tei_el("list", attrs)
    for item_source in source.xpath("./li"):
        item_attrs: dict[str, str] = {}
        item_rend = _rend_for(item_source)
        if item_rend:
            item_attrs["rend"] = item_rend
        item = tei_el("item", item_attrs)
        _copy_inline(item_source, item, state)
        for nested in item_source.xpath("./ul"):
            item.append(_list(nested, state))
        result.append(item)
    return result


def _section_div(
    source: etree._Element,
    state: _ConversionState,
    parent_key: str,
) -> etree._Element:
    headings = source.xpath("./h3[contains(concat(' ', normalize-space(@class), ' '), ' h3inline ')]")
    if len(headings) != 1:
        raise SourceMismatchError("section-start div does not have one inline heading")
    state.section_counts[parent_key] += 1
    result = tei_el(
        "div",
        {
            "type": "section",
            "n": str(state.section_counts[parent_key]),
            "xml:id": f"{parent_key}-section-{state.section_counts[parent_key]}",
        },
    )
    head = _heading(headings[0], state)
    if head is not None:
        result.append(head)
    paragraph = tei_el("p")
    _append_text(paragraph, headings[0].tail)
    seen_heading = False
    for child in source:
        if child is headings[0]:
            seen_heading = True
            continue
        if not seen_heading:
            continue
        _convert_inline_child(child, paragraph, state)
        _append_text(paragraph, child.tail)
    if _normalized_space("".join(paragraph.itertext())) or len(paragraph):
        result.append(paragraph)
    return result


def _block(
    source: etree._Element,
    state: _ConversionState,
    parent_key: str,
) -> etree._Element | None:
    tag = source.tag
    classes = _classes(source)
    if tag == "p":
        return _paragraph(source, state)
    if tag in {"h1", "h2", "h3", "h4"}:
        return _heading(source, state)
    if tag == "hr":
        return tei_el("milestone", {"unit": "separator"})
    if tag == "table":
        return _table(source, state)
    if tag == "ul":
        return _list(source, state)
    if tag == "div" and "footnote" in classes:
        return _footnote(source, state)
    if tag == "div" and "section-start" in classes:
        return _section_div(source, state, parent_key)
    raise SourceMismatchError(f"unhandled block tag/classes: {tag} {sorted(classes)}")


def _append_blocks(
    target: etree._Element,
    sources: Iterable[etree._Element],
    state: _ConversionState,
    parent_key: str,
) -> None:
    for source in sources:
        node = _block(source, state, parent_key)
        if node is not None:
            target.append(node)


def _move_leading_page_milestones_into_head(target: etree._Element) -> None:
    """Satisfy TEI head ordering while retaining a source pre-heading page break."""
    children = list(target)
    if len(children) < 2:
        return
    leading = children[0]
    following = children[1]
    if etree.QName(leading).localname != "p" or etree.QName(following).localname != "head":
        return
    if _normalized_space("".join(leading.itertext())):
        return
    page_breaks = list(leading)
    if not page_breaks or any(etree.QName(child).localname != "pb" for child in page_breaks):
        return
    target.remove(leading)
    for page_break in reversed(page_breaks):
        following.insert(0, page_break)


def _group_numbered_sections(target: etree._Element) -> None:
    """Make a TEI div contain only heads plus sequential child divisions."""
    children = list(target)
    if not any(
        etree.QName(child).localname == "div" and child.get("type") == "section"
        for child in children
    ):
        return
    heads: list[etree._Element] = []
    remainder = children
    while remainder and etree.QName(remainder[0]).localname == "head":
        heads.append(remainder[0])
        remainder = remainder[1:]
    target[:] = heads
    current: etree._Element | None = None
    parent_id = target.get(XML_ID, "division")
    for child in remainder:
        if etree.QName(child).localname == "div" and child.get("type") == "section":
            current = child
            target.append(current)
            continue
        if current is None:
            current = tei_el(
                "div",
                {
                    "type": "section",
                    "n": "0",
                    "xml:id": f"{parent_id}-section-0",
                },
            )
            target.append(current)
        current.append(child)


def _ordinary_div(
    source: etree._Element,
    state: _ConversionState,
    *,
    div_type: str,
    fallback_id: str,
    n: str | None = None,
) -> etree._Element:
    source_id = _first_structural_id(source) or fallback_id
    attrs = {"type": div_type, "xml:id": source_id}
    if n:
        attrs["n"] = n
    state.consumed_source_ids.add(source_id)
    result = tei_el("div", attrs)
    _append_blocks(result, list(source), state, source_id)
    _move_leading_page_milestones_into_head(result)
    if div_type == "proposition":
        _group_numbered_sections(result)
    return result


def _theses_div(source: etree._Element, state: _ConversionState) -> etree._Element:
    result = _ordinary_div(
        source,
        state,
        div_type="theological_theses",
        fallback_id="theological-theses",
    )
    original_children = list(result)
    first_thesis = next(
        (index for index, child in enumerate(original_children) if etree.QName(child).localname == "head" and _normalized_space("".join(child.itertext())).startswith("The First Proposition")),
        None,
    )
    if first_thesis is None:
        raise SourceMismatchError("theological theses have no first proposition heading")
    prefix = original_children[:first_thesis]
    thesis_nodes = original_children[first_thesis:]
    if not prefix or etree.QName(prefix[0]).localname != "head":
        raise SourceMismatchError("theological theses do not begin with a TEI head")
    result[:] = [prefix[0]]
    if len(prefix) > 1:
        preamble = tei_el(
            "div",
            {
                "type": "theses_preamble",
                "xml:id": "theological-theses-preamble",
            },
        )
        preamble.extend(prefix[1:])
        result.append(preamble)
    current: etree._Element | None = None
    thesis_number = 0
    for node in thesis_nodes:
        if etree.QName(node).localname == "head":
            thesis_number += 1
            current = tei_el(
                "div",
                {
                    "type": "thesis",
                    "n": str(thesis_number),
                    "xml:id": f"theological-thesis-{thesis_number}",
                },
            )
            current.append(node)
            result.append(current)
        elif current is None:
            raise SourceMismatchError("thesis content precedes its heading")
        else:
            current.append(node)
    return result


def _combined_fifth_sixth(
    source: etree._Element,
    state: _ConversionState,
) -> etree._Element:
    source_id = _first_structural_id(source)
    if source_id != "PROPOSITIONS_V_VI":
        raise SourceMismatchError(f"unexpected combined proposition source ID: {source_id}")
    state.consumed_source_ids.add(source_id)
    result = tei_el(
        "div",
        {"type": "proposition_group", "n": "V-VI", "xml:id": source_id},
    )
    children = list(source)
    fifth = next(
        i for i, child in enumerate(children)
        if child.tag == "p" and _normalized_space(child.text_content()) == "PROPOSITION V."
    )
    sixth = next(
        i for i, child in enumerate(children)
        if child.tag == "p" and _normalized_space(child.text_content()) == "PROPOSITION VI."
    )
    _append_blocks(result, children[:fifth], state, source_id)
    for roman, start, stop in (("V", fifth, sixth), ("VI", sixth, len(children))):
        proposition = tei_el(
            "div",
            {"type": "proposition", "n": roman, "xml:id": f"proposition-{roman}"},
        )
        marker = tei_el("head")
        _copy_inline(children[start], marker, state)
        proposition.append(marker)
        _append_blocks(proposition, children[start + 1 : stop], state, f"proposition-{roman}")
        _group_numbered_sections(proposition)
        result.append(proposition)
    _move_leading_page_milestones_into_head(result)
    group_children = list(result)
    if not group_children or etree.QName(group_children[0]).localname != "head":
        raise SourceMismatchError("combined proposition group lacks a head")
    group_head = group_children[0]
    for child in group_children[1:]:
        if etree.QName(child).localname == "div":
            continue
        segment = tei_el("seg", {"type": "topic", "rend": child.get("rend") or "source-block"})
        segment.text = child.text
        for grandchild in list(child):
            segment.append(grandchild)
        _append_text(group_head, " ")
        group_head.append(segment)
        result.remove(child)
    return result


def _first_proposition_with_body_title(
    source: etree._Element,
    state: _ConversionState,
) -> tuple[etree._Element, etree._Element]:
    children = list(source)
    heading_index = next(
        (
            index
            for index, child in enumerate(children)
            if child.tag == "h2"
            and _normalized_space(child.text_content()) == "PROPOSITION I."
        ),
        None,
    )
    if heading_index is None or heading_index < 2:
        raise SourceMismatchError("Proposition I body-title boundary is missing")
    prefix = children[:heading_index]
    page_marker = prefix[-1]
    if page_marker.tag != "p" or not page_marker.xpath(
        ".//span[contains(concat(' ', normalize-space(@class), ' '), ' pagenum ')]"
    ):
        raise SourceMismatchError("Proposition I lacks its pre-heading Page_1 milestone")

    body_title = tei_el("div", {"type": "body_title", "xml:id": "body-title"})
    _append_blocks(body_title, prefix[:-1], state, "body-title")

    source_id = _first_structural_id(source)
    if source_id != "PROPOSITION_I":
        raise SourceMismatchError(f"unexpected Proposition I source ID: {source_id}")
    state.consumed_source_ids.add(source_id)
    proposition = tei_el(
        "div", {"type": "proposition", "xml:id": source_id, "n": "I"}
    )
    _append_blocks(
        proposition,
        [page_marker, *children[heading_index:]],
        state,
        source_id,
    )
    _move_leading_page_milestones_into_head(proposition)
    _group_numbered_sections(proposition)
    return body_title, proposition


def _index_div(
    source: etree._Element,
    state: _ConversionState,
    *,
    div_type: str,
) -> etree._Element:
    source_id = _first_structural_id(source)
    if source_id is None:
        raise SourceMismatchError("index lacks source structural ID")
    state.consumed_source_ids.add(source_id)
    result = tei_el("div", {"type": div_type, "xml:id": source_id})
    current: etree._Element | None = None
    source_children: list[etree._Element] = []
    for source_child in source:
        if (
            source_child.tag == "div"
            and not _classes(source_child)
            and all(child.tag in {"h4", "ul"} for child in source_child)
        ):
            source_children.extend(list(source_child))
        else:
            source_children.append(source_child)
    for source_child in source_children:
        if source_child.tag == "h4":
            letter = _normalized_space(source_child.text_content())
            current = tei_el(
                "div",
                {
                    "type": "index_letter",
                    "n": letter,
                    "xml:id": f"{source_id}-letter-{letter}",
                },
            )
            head = _heading(source_child, state)
            if head is not None:
                current.append(head)
            result.append(current)
            continue
        node = _block(source_child, state, source_id)
        if node is None:
            continue
        if current is None or source_child.tag in {"h2", "h3"}:
            result.append(node)
        else:
            current.append(node)
    return result


def _build_tei(source: Path) -> etree._ElementTree:
    document = _parse_html(source)
    sections = _source_work_sections(document)
    state = _ConversionState()

    header = stamp_header(
        title="An Apology for the True Christian Divinity",
        author="Robert Barclay",
        contributors=[
            {"name": "Emmanuel Ackerman", "role": "producer"},
            {"name": "Online Distributed Proofreading Team", "role": "transcriber"},
        ],
        source_url=SOURCE_URL,
        source_sha256=f"sha256:{EXPECTED_SOURCE_SHA256}",
        print_source=(
            "Eighth English edition, Birmingham: John Baskerville, 1765; "
            "Project Gutenberg eBook 56487"
        ),
        rights_statement=(
            "The 1765 witness and Project Gutenberg transcription are public domain "
            "in the United States. The retained eBook remains subject to the Project "
            "Gutenberg License and jurisdiction-specific rights checks."
        ),
    )

    tei = tei_el("TEI")
    tei.append(header)
    text = tei_el("text", {"xml:lang": "en"})
    front = tei_el("front")
    body = tei_el("body")
    back = tei_el("back")

    front_specs = [
        ("title_page", "title-page"),
        ("table_of_contents", "table-of-contents"),
        ("royal_dedication", "introduction"),
        ("reader_preface", "friendly-reader"),
    ]
    for section, (div_type, fallback_id) in zip(sections[:4], front_specs, strict=True):
        front.append(
            _ordinary_div(
                section,
                state,
                div_type=div_type,
                fallback_id=fallback_id,
            )
        )
    front.append(_theses_div(sections[4], state))

    main_numbers = ["I", "II", "III", "IV", None, "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV"]
    for section, number in zip(sections[5:19], main_numbers, strict=True):
        if number == "I":
            body_title, proposition = _first_proposition_with_body_title(section, state)
            body.extend((body_title, proposition))
        elif number is None:
            body.append(_combined_fifth_sixth(section, state))
        else:
            body.append(
                _ordinary_div(
                    section,
                    state,
                    div_type="proposition",
                    fallback_id=f"proposition-{number}",
                    n=number,
                )
            )
    body.append(
        _ordinary_div(
            sections[19],
            state,
            div_type="conclusion",
            fallback_id="CONCLUSION",
        )
    )

    back.append(_index_div(sections[20], state, div_type="author_index"))
    back.append(_index_div(sections[21], state, div_type="subject_index"))
    back.append(
        _ordinary_div(
            sections[22], state, div_type="errata", fallback_id="ERRATA"
        )
    )
    back.append(
        _ordinary_div(
            sections[23],
            state,
            div_type="transcribers_note",
            fallback_id="TN",
        )
    )

    text.extend((front, body, back))
    tei.append(text)
    return etree.ElementTree(tei)


@lru_cache(maxsize=1)
def _compiled_relaxng(schema_path: Path) -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(schema_path)))


def _validate_candidate(tree: etree._ElementTree, repository_root: Path) -> None:
    schema_path = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    schema = _compiled_relaxng(schema_path)
    if not schema.validate(tree):
        raise SourceMismatchError(f"TEI P5 Relax NG validation failed: {schema.error_log.last_error}")


def _candidate_census(tree: etree._ElementTree) -> dict[str, Any]:
    ids = tree.xpath("//@xml:id", namespaces=NS)
    if len(ids) != len(set(ids)):
        duplicates = sorted(value for value, count in Counter(ids).items() if count > 1)
        raise SourceMismatchError(f"duplicate candidate xml:id values: {duplicates}")
    targets = {
        target.removeprefix("#")
        for target in tree.xpath("//tei:ref[starts-with(@target, '#')]/@target", namespaces=NS)
    }
    unresolved = sorted(targets - set(ids))
    return {
        "propositions": len(tree.xpath("//tei:div[@type='proposition']", namespaces=NS)),
        "proposition_groups": len(tree.xpath("//tei:div[@type='proposition_group']", namespaces=NS)),
        "footnotes": len(tree.xpath("//tei:note[@place='foot']", namespaces=NS)),
        "margin_notes": len(tree.xpath("//tei:note[@place='margin']", namespaces=NS)),
        "page_milestones": len(tree.xpath("//tei:pb", namespaces=NS)),
        "correction_choices": len(tree.xpath("//tei:choice[tei:sic and tei:corr]", namespaces=NS)),
        "tables": len(tree.xpath("//tei:table", namespaces=NS)),
        "author_indexes": len(tree.xpath("//tei:div[@type='author_index']", namespaces=NS)),
        "subject_indexes": len(tree.xpath("//tei:div[@type='subject_index']", namespaces=NS)),
        "errata_sections": len(tree.xpath("//tei:div[@type='errata']", namespaces=NS)),
        "transcribers_notes": len(tree.xpath("//tei:div[@type='transcribers_note']", namespaces=NS)),
        "xml_ids": len(ids),
        "internal_ref_targets": len(targets),
        "unresolved_internal_ref_targets": unresolved,
    }


def build_candidate(
    source: Path,
    candidate: Path,
    report: Path,
    *,
    repository_root: Path,
    replace: bool = False,
) -> dict[str, Any]:
    """Build one atomic TEI candidate and deterministic validation report."""
    audit = audit_source(source)
    if not replace and (candidate.exists() or report.exists()):
        raise FileExistsError("candidate or validation report already exists")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    candidate_stage = candidate.with_name(f"{candidate.name}.tmp")
    report_stage = report.with_name(f"{report.name}.tmp")
    if candidate_stage.exists() or report_stage.exists():
        raise FileExistsError("staged candidate or validation path already exists")

    tree = _build_tei(source)
    serialize(tree, candidate_stage)
    parsed = etree.parse(str(candidate_stage))
    _validate_candidate(parsed, repository_root)
    census = _candidate_census(parsed)
    expected_candidate_counts = {
        "propositions": 15,
        "proposition_groups": 1,
        "footnotes": EXPECTED_SOURCE_COUNTS["footnote_bodies"],
        "margin_notes": EXPECTED_SOURCE_COUNTS["margin_notes"],
        "page_milestones": EXPECTED_SOURCE_COUNTS["page_milestones"],
        "correction_choices": EXPECTED_SOURCE_COUNTS["corrections"],
        "tables": EXPECTED_SOURCE_COUNTS["tables"],
        "author_indexes": 1,
        "subject_indexes": 1,
        "errata_sections": 1,
        "transcribers_notes": 1,
    }
    mismatches = {
        key: (census[key], value)
        for key, value in expected_candidate_counts.items()
        if census[key] != value
    }
    if mismatches:
        candidate_stage.unlink(missing_ok=True)
        raise SourceMismatchError(f"candidate structural accounting differs: {mismatches}")
    if census["unresolved_internal_ref_targets"]:
        candidate_stage.unlink(missing_ok=True)
        raise SourceMismatchError(
            f"candidate has unresolved internal refs: {census['unresolved_internal_ref_targets']}"
        )

    logical_text = _candidate_logical_text(parsed)
    logical_hash = hashlib.sha256(logical_text.encode("utf-8")).hexdigest()
    if logical_hash != audit["logical_text_sha256"]:
        candidate_stage.unlink(missing_ok=True)
        raise SourceMismatchError(
            "candidate logical text differs from the retained source after the declared "
            f"page-label/sic projection: {logical_hash} != {audit['logical_text_sha256']}"
        )

    result = {
        "source_sha256": audit["source_sha256"],
        "candidate_sha256": sha256_file(candidate_stage),
        "source_logical_text_sha256": audit["logical_text_sha256"],
        "candidate_logical_text_sha256": logical_hash,
        "logical_text_parity": True,
        "logical_text_characters": len(logical_text),
        "tei_p5_relaxng_valid": True,
        "source_counts": audit["source_counts"],
        "candidate_counts": census,
        "normalization": (
            "HTML formatting whitespace collapsed; source page labels represented as pb; "
            "source correction readings retained as sic with visible readings retained as corr"
        ),
        "gutenberg_wrapper_excluded_from_candidate_text": True,
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    report_stage.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    candidate_stage.replace(candidate)
    report_stage.replace(report)
    return result


def write_determinism_report(
    run_a_candidate: Path,
    run_a_validation: Path,
    run_b_candidate: Path,
    run_b_validation: Path,
    output: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Compare two fresh-run products created from different working directories."""
    candidate_bytes_equal = run_a_candidate.read_bytes() == run_b_candidate.read_bytes()
    validation_bytes_equal = run_a_validation.read_bytes() == run_b_validation.read_bytes()
    different_working_directory = Path.cwd().resolve() != repository_root.resolve()
    if not candidate_bytes_equal or not validation_bytes_equal:
        raise SourceMismatchError("fresh-run candidate or validation bytes differ")
    if not different_working_directory:
        raise SourceMismatchError("determinism comparison must run from a different working directory")
    result = {
        "candidate_bytes_equal": True,
        "candidate_sha256": sha256_file(run_a_candidate),
        "validation_bytes_equal": True,
        "validation_sha256": sha256_file(run_a_validation),
        "different_working_directory": True,
        "run_a_working_directory": str(repository_root.resolve()),
        "run_b_working_directory": str(Path.cwd().resolve()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(f"{path.name}.tmp")
    if stage.exists():
        raise FileExistsError(f"staged evidence path already exists: {stage}")
    stage.write_text(
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    stage.replace(path)


def _header_date(headers: Path) -> str:
    dates = [
        line.split(":", 1)[1].strip()
        for line in headers.read_text(encoding="utf-8").splitlines()
        if line.lower().startswith("date:")
    ]
    if not dates:
        raise SourceMismatchError(f"download headers contain no Date field: {headers}")
    return parsedate_to_datetime(dates[-1]).isoformat().replace("+00:00", "Z")


def write_evidence_packet(
    source: Path,
    candidate: Path,
    validation: Path,
    determinism: Path,
    evidence_root: Path,
    *,
    repository_root: Path,
) -> dict[str, Path]:
    """Write the ticket-06 receipt, accounting, and unresolved handoff."""
    audit = audit_source(source)
    raw_root = source.parent
    config = repository_root / "sources" / "structured-text" / SLUG / "config.json"
    attribution = config.with_name("README.md")
    schema = repository_root / "ocd_kernel" / "tei" / "vendor" / "relaxng" / "tei_all.rng"
    converter = Path(__file__).resolve()
    retained_members = []
    urls = {
        "56487-h.htm": SOURCE_URL,
        "ebook-56487.html": LANDING_URL,
        "56487-h.htm.headers.txt": SOURCE_URL,
        "ebook-56487.html.headers.txt": LANDING_URL,
    }
    for name in sorted(urls):
        path = raw_root / name
        retained_members.append(
            {
                "name": name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "url": urls[name],
            }
        )
    receipt = {
        "ticket": 28,
        "slug": SLUG,
        "identity": {
            "author": "Robert Barclay (1648–1690)",
            "title": "An Apology for the True Christian Divinity",
            "edition": "Eighth English edition, Birmingham: John Baskerville, 1765",
            "gutenberg_id": 56487,
            "cross_report_identity": "acquired once for apologetics row 3 and systematics row 2",
            "workcatalog": "provisional net-new candidate — no canonical WorkCatalog write",
        },
        "landing_url": LANDING_URL,
        "source_url": SOURCE_URL,
        "retrieved_at_utc": _header_date(raw_root / "56487-h.htm.headers.txt"),
        "retained_members": retained_members,
        "rights": {
            "work_and_witness": "Public domain in the United States",
            "digital_text": "Project Gutenberg eBook subject to the Project Gutenberg License",
            "rights_url": "https://www.gutenberg.org/policy/license.html",
            "jurisdiction_note": "Users outside the United States must check local law",
            "attribution": "Project Gutenberg credits retained in README and TEI header",
        },
        "completeness_observation": {
            "opening": "title matter, table of contents, royal dedication, reader preface, and theological theses",
            "middle": "all fifteen propositions, including the source-defined combined V/VI chapter",
            "ending": "conclusion, author index, subject index, errata, and transcriber's note",
            "unusual_features": audit["source_counts"],
        },
        "acquisition_behavior": {
            "method": "curl -fL from stable Project Gutenberg files/ and landing URLs",
            "normalization": "none; exact response bodies retained",
            "archive": "none; the self-contained HTML contains no images",
        },
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    validation_record = json.loads(validation.read_text(encoding="utf-8"))
    accountability = {
        "source_sha256": audit["source_sha256"],
        "candidate_sha256": sha256_file(candidate),
        "validation_sha256": sha256_file(validation),
        "determinism_sha256": sha256_file(determinism),
        "source_candidate_logical_text_parity": validation_record["logical_text_parity"],
        "logical_text_sha256": audit["logical_text_sha256"],
        "logical_text_characters": audit["logical_text_characters"],
        "source_counts": audit["source_counts"],
        "candidate_counts": validation_record["candidate_counts"],
        "schema": {
            "path": schema.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(schema),
        },
        "converter": {
            "path": converter.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(converter),
        },
        "source_config": {
            "path": config.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(config),
        },
        "attribution_readme": {
            "path": attribution.relative_to(repository_root).as_posix(),
            "sha256": sha256_file(attribution),
        },
        "tei_p5_relaxng_valid": True,
        "canonical_write": False,
    }
    unresolved = {
        "print_witness_collation": "not performed; Gutenberg/PGDP states the source images came from HathiTrust, Google, and the University of Michigan Library",
        "gutenberg_wrapper": "license/start/end wrapper retained in the exact HTML source and represented in provenance, but excluded from the work's TEI text",
        "page_labels": "516 visible Gutenberg page labels represented as TEI pb milestones, not duplicated as running text",
        "transcriber_interventions": (
            "All 139 Gutenberg correction/intervention spans retain either the literal "
            "original/erratum reading or the source title description as sic, with the "
            "source-visible reading as corr; the complete transcriber's note and errata "
            "table are retained"
        ),
        "correction_title_categories": {
            "original_book_readings": 82,
            "erratum_readings": 53,
            "descriptive_interventions": 4,
        },
        "viewer_table_and_list_layout": (
            "The existing CETEIcean stylesheet flows TEI table cells and list items inline. "
            "The candidate retains explicit table/row/cell and list/item structures; paired "
            "screenshots and logical-text hashes are retained as fidelity evidence."
        ),
        "textual_acceptance": "pending human review",
        "identity_and_edition_acceptance": "pending human review",
        "rights_acceptance": "pending human review; Gutenberg rights and license evidence retained",
        "editorial_acceptance": "pending human review",
        "canonical_integration": "not authorized",
        "publication": "not authorized",
    }
    paths = {
        "receipt": evidence_root / "source_receipt.json",
        "accountability": evidence_root / "accountability.json",
        "unresolved": evidence_root / "unresolved_items.json",
    }
    _write_json(paths["receipt"], receipt)
    _write_json(paths["accountability"], accountability)
    _write_json(paths["unresolved"], unresolved)
    return paths


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def render_visual_spot_check(
    source: Path,
    candidate: Path,
    output_dir: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Capture paired HTML/TEI evidence through the browser and existing viewer."""
    from build.tools.tei_viewer_screenshot import _chromium_path, _serve, _sync_playwright

    source_document = _parse_html(source)
    source_sections = _source_work_sections(source_document)
    candidate_document = etree.parse(str(candidate))
    sample_specs = [
        (
            "opening-title",
            source_sections[0],
            candidate_document.xpath("//tei:div[@type='title_page']", namespaces=NS)[0],
            "body > div:nth-of-type(1)",
            "tei-div[type='title_page']",
        ),
        (
            "propositions-v-vi-transition",
            source_sections[9],
            candidate_document.xpath("//tei:div[@xml:id='PROPOSITIONS_V_VI']", namespaces=NS)[0],
            "body > div:nth-of-type(10)",
            "tei-div#PROPOSITIONS_V_VI",
        ),
        (
            "conclusion-ending",
            source_sections[19],
            candidate_document.xpath("//tei:div[@type='conclusion']", namespaces=NS)[0],
            "body > div:nth-of-type(20)",
            "tei-div[type='conclusion']",
        ),
        (
            "author-index",
            source_sections[20],
            candidate_document.xpath("//tei:div[@type='author_index']", namespaces=NS)[0],
            "body > div:nth-of-type(21)",
            "tei-div[type='author_index']",
        ),
        (
            "subject-index",
            source_sections[21],
            candidate_document.xpath("//tei:div[@type='subject_index']", namespaces=NS)[0],
            "body > div:nth-of-type(22)",
            "tei-div[type='subject_index']",
        ),
        (
            "errata",
            source_sections[22],
            candidate_document.xpath("//tei:div[@type='errata']", namespaces=NS)[0],
            "body > div:nth-of-type(23)",
            "tei-div[type='errata']",
        ),
        (
            "transcribers-note",
            source_sections[23],
            candidate_document.xpath("//tei:div[@type='transcribers_note']", namespaces=NS)[0],
            "body > div:nth-of-type(24)",
            "tei-div[type='transcribers_note']",
        ),
    ]
    source_root = source_document.getroot()
    detail_specs = [
        (
            "footnote",
            source_root.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' footnote ')][.//a[@id='Footnote_86_86']]")[0],
            candidate_document.xpath("//tei:note[@xml:id='Footnote_86_86']", namespaces=NS)[0],
            "div.footnote:has(#Footnote_86_86)",
            "tei-note#Footnote_86_86",
        ),
        (
            "margin-note",
            source_root.xpath("//span[contains(concat(' ', normalize-space(@class), ' '), ' sidenote ')][1]")[0],
            candidate_document.xpath("//tei:note[@place='margin'][1]", namespaces=NS)[0],
            "span.sidenote",
            "tei-note[place='margin']",
        ),
        (
            "correction",
            source_root.xpath("//span[contains(concat(' ', normalize-space(@class), ' '), ' correction ')][1]")[0],
            candidate_document.xpath("//tei:choice[1]", namespaces=NS)[0],
            "span.correction",
            "tei-choice",
        ),
        (
            "page-milestone",
            source_root.xpath("//p[.//a[@id='Page_250']]")[0],
            candidate_document.xpath("//tei:p[.//tei:pb[@xml:id='Page_250']]", namespaces=NS)[0],
            "span.pagenum:has(#Page_250)",
            "tei-pb#Page_250",
        ),
    ]
    sample_specs.extend(detail_specs)

    checks: dict[str, Any] = {}
    for label, source_node, candidate_node, source_selector, candidate_selector in sample_specs:
        source_text = _source_visible_text(source_node)
        candidate_text = _candidate_visible_text(candidate_node)
        if source_text != candidate_text:
            raise SourceMismatchError(f"visual sample logical text differs at {label}")
        checks[label] = {
            "logical_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            "logical_text_characters": len(source_text),
            "source_candidate_logical_text_match": True,
            "source_selector": source_selector,
            "candidate_selector": candidate_selector,
            "source_screenshot": f"visual/source-{label}.png",
            "candidate_screenshot": f"visual/candidate-{label}.png",
            "result": "pass",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    screenshots: list[str] = []
    sync_playwright = _sync_playwright()
    port = _free_loopback_port()
    with _serve(repository_root, port) as base:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=_chromium_path(), headless=True
            )
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            try:
                page.goto(source.resolve().as_uri(), wait_until="load")
                source_stats = page.evaluate(
                    """() => ({
                        sections: document.querySelectorAll('body > div').length,
                        footnotes: document.querySelectorAll('div.footnote').length,
                        margin_notes: document.querySelectorAll('span.sidenote').length,
                        page_milestones: document.querySelectorAll('span.pagenum').length,
                        corrections: document.querySelectorAll('span.correction').length,
                        tables: document.querySelectorAll('table').length
                    })"""
                )
                for label, _snode, _cnode, source_selector, _candidate_selector in sample_specs:
                    item = page.locator(source_selector).first
                    item.wait_for(state="attached", timeout=60_000)
                    item.evaluate(
                        """element => {
                            element.style.outline = '4px solid #1d4ed8';
                            element.style.backgroundColor = '#eff6ff';
                            element.scrollIntoView({block: 'center'});
                        }"""
                    )
                    page.wait_for_timeout(150)
                    screenshot = output_dir / f"source-{label}.png"
                    page.screenshot(path=str(screenshot), full_page=False)
                    screenshots.append(screenshot.name)

                page.goto(f"{base}/viewer/index.html", wait_until="networkidle")
                page.set_input_files("#viewer-file-input", str(candidate.resolve()))
                page.wait_for_function(
                    "document.querySelector('#viewer-status').textContent.startsWith('Loaded')",
                    timeout=60_000,
                )
                page.wait_for_selector("tei-div", state="attached", timeout=60_000)
                page.add_style_tag(
                    content=(
                        "tei-choice tei-sic { display: none !important; } "
                        "tei-choice tei-corr { display: inline !important; }"
                    )
                )
                candidate_stats = page.evaluate(
                    """() => ({
                        propositions: document.querySelectorAll("tei-div[type='proposition']").length,
                        footnotes: document.querySelectorAll("tei-note[place='foot']").length,
                        margin_notes: document.querySelectorAll("tei-note[place='margin']").length,
                        page_milestones: document.querySelectorAll('tei-pb').length,
                        corrections: document.querySelectorAll('tei-choice').length,
                        tables: document.querySelectorAll('tei-table').length,
                        upgraded: !!customElements.get('tei-div')
                    })"""
                )
                for label, _snode, _cnode, _source_selector, candidate_selector in sample_specs:
                    item = page.locator(candidate_selector).first
                    item.wait_for(state="attached", timeout=60_000)
                    item.evaluate(
                        """element => {
                            let target = element;
                            while (target && target.getClientRects().length === 0) {
                                target = target.parentElement;
                            }
                            if (!target) { throw new Error('sample has no visible ancestor'); }
                            target.style.outline = '4px solid #b45309';
                            target.style.backgroundColor = '#fff7ed';
                            target.scrollIntoView({block: 'center'});
                        }"""
                    )
                    marker = item.locator(".viewer-note-marker")
                    if marker.count():
                        marker.first.click()
                    page.wait_for_timeout(150)
                    screenshot = output_dir / f"candidate-{label}.png"
                    page.screenshot(path=str(screenshot), full_page=False)
                    screenshots.append(screenshot.name)
            finally:
                browser.close()

    result = {
        "source_view": "retained Project Gutenberg HTML opened directly",
        "candidate_view": "existing viewer/index.html CETEIcean file-input path",
        "candidate_visual_projection": "sic hidden and corr shown for TEI choice display",
        "viewer_limitations": (
            "The existing CETEIcean stylesheet flows TEI table cells and list items inline. "
            "The candidate retains explicit table/row/cell and list/item structures; this "
            "display limitation is not textual or structural loss in the TEI."
        ),
        "source_dom_stats": source_stats,
        "candidate_dom_stats": candidate_stats,
        "checks": checks,
        "screenshots": screenshots,
        "acceptance_scope": "fidelity evidence only; no textual, identity, rights, editorial, canonical, or publication acceptance",
    }
    _write_json(output_dir / "visual_spot_check.json", result)
    lines = [
        "# Barclay visual spot check",
        "",
        "The retained Gutenberg HTML and faithful TEI candidate were rendered in a browser.",
        "The TEI used the existing CETEIcean viewer; its `sic` readings were hidden so the",
        "source-visible `corr` reading could be compared. Every selected pair has matching",
        "logical text under the same page-label and correction projection used by validation.",
        "The existing viewer flows TEI table cells and list items inline even though the XML",
        "retains explicit table/row/cell and list/item structures.",
        "",
        "| Check | Logical text SHA-256 | Source | Candidate | Result |",
        "|---|---|---|---|---|",
    ]
    for label, details in checks.items():
        lines.append(
            f"| {label} | `{details['logical_text_sha256']}` | "
            f"`{details['source_screenshot']}` | `{details['candidate_screenshot']}` | PASS |"
        )
    lines.extend(
        [
            "",
            "This is lightweight fidelity evidence only. It does not constitute human textual,",
            "identity, edition, rights, editorial, canonical, or publication acceptance.",
            "",
        ]
    )
    (output_dir / "visual_spot_check.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    return result


def write_path_hash_manifest(
    raw_root: Path,
    report_root: Path,
    output: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Hash all retained/evidence files and the four released worktree files."""
    entries: list[dict[str, Any]] = []
    for label, root in (("raw", raw_root), ("report", report_root)):
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.resolve() == output.resolve():
                continue
            entries.append(
                {
                    "scope": label,
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    worktree_paths = [
        repository_root / "sources" / "structured-text" / SLUG / "config.json",
        repository_root / "sources" / "structured-text" / SLUG / "README.md",
        repository_root / "build" / "tei" / "barclay_apology_true_christian_divinity.py",
        repository_root / "tests" / "test_barclay_apology_true_christian_divinity.py",
    ]
    for path in worktree_paths:
        entries.append(
            {
                "scope": "worktree",
                "path": path.relative_to(repository_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    result = {
        "ticket": 28,
        "slug": SLUG,
        "files": entries,
        "file_count_excluding_manifest": len(entries),
        "canonical_write": False,
        "acceptance_status": "nonaccepted",
        "publication_status": "not-authorized",
    }
    _write_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--compare-candidate", type=Path)
    parser.add_argument("--compare-report", type=Path)
    parser.add_argument("--determinism-report", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args(argv)
    repository_root = args.repository_root.resolve()
    source = (args.source or resolve_source_path(repository_root)).resolve()
    result = build_candidate(
        source,
        args.candidate.resolve(),
        args.report.resolve(),
        repository_root=repository_root,
        replace=args.replace,
    )
    print(json.dumps(result, sort_keys=True))
    comparison_args = (
        args.compare_candidate,
        args.compare_report,
        args.determinism_report,
    )
    if any(comparison_args):
        if not all(comparison_args):
            parser.error(
                "--compare-candidate, --compare-report, and --determinism-report must be supplied together"
            )
        determinism = write_determinism_report(
            args.compare_candidate.resolve(),
            args.compare_report.resolve(),
            args.candidate.resolve(),
            args.report.resolve(),
            args.determinism_report.resolve(),
            repository_root=repository_root,
        )
        print(json.dumps(determinism, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
