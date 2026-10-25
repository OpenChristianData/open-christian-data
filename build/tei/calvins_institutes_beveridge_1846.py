"""Build the bounded OLL Beveridge *Institutes* TEI P5 candidate.

This source-local route preserves the exact retained OLL EPUB transcription and
keeps the facsimile-only General Index (printed pp. 691-704) in a separately
identified, page-bounded low-certainty searchable-text layer.  The latter is
not represented as an exact human transcription and is never mixed into the
EPUB visible-text digest.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Mapping
from zipfile import BadZipFile, ZipFile

if __package__ in {None, ""}:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree, html

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
NS = {"t": TEI_NS}

RAW_PREFIX = (
    "raw/clean-ready-acquisition-to-tei/master-1/08/"
    "calvins-institutes-beveridge-1846"
)
SOURCE_LOGICAL_PATH = f"{RAW_PREFIX}/calvin-the-institutes-of-the-christian-religion.epub"
SOURCE_SHA256 = "4a7bfc603c2e9f460c4b48a12389f3ec9b0ef00f8864416d0fcd87168813d0d1"
SOURCE_HTML_MEMBER = "Calvin_0038.html"
SOURCE_HTML_SHA256 = "43409edd7da6a1db1478f5c8b3740d3d747b01b5daea47ef1d143a217ada72cb"
EBOOK_PDF_LOGICAL_PATH = f"{RAW_PREFIX}/Calvin_0038_EBk_v6.0.pdf"
EBOOK_PDF_SHA256 = "8015510ce3c79ddf086ce3bd5f117c2cc0244410d98f7a87dbc05c9e725d6e75"
FACSIMILE_LOGICAL_PATH = f"{RAW_PREFIX}/0038_Bk.pdf"
FACSIMILE_SHA256 = "bfb1cde92d58eadabb068eb7b11ee0bfd13bcb4c5b0a6c8993f4ce5712c1cc4c"
INDEX_EXTRACTION_LOGICAL_PATH = (
    f"{RAW_PREFIX}/facsimile-general-index-p691-704.pypdf-6.10.0.json"
)
INDEX_EXTRACTION_SHA256 = "03099add1e81f17f7a834570d48651ed57d3e9c1a5a991581d6adeb934a35fe3"
OLL_TITLE_URL = "https://oll.libertyfund.org/titles/calvin-the-institutes-of-the-christian-religion"

EXPECTED_EPUB_MEMBERS = (
    "1-liberty_fund.html",
    "2-online_library_of_liberty.html",
    "3-copyright.html",
    "Amagi300.jpg",
    "Calvin_0038.html",
    "META-INF/container.xml",
    "OLL-Banner600.png",
    "content.opf",
    "copyright64.jpg",
    "cover.html",
    "epub.css",
    "mimetype",
    "toc.html",
    "toc.ncx",
)

EXPECTED_SOURCE_COUNTS = {
    "paragraph_count": 3970,
    "chapter_count": 80,
    "argument_count": 4,
    "section_div_count": 2822,
    "electronic_page_milestone_count": 1290,
    "processing_instruction_page_milestone_count": 13,
    "note_count": 660,
    "note_reference_count": 660,
    "section_cross_reference_count": 2545,
    "toc_page_reference_count": 16,
    "table_count": 67,
    "caption_count": 65,
    "list_item_count": 135,
    "italic_count": 767,
    "small_caps_count": 159,
    "gap_count": 1,
}

TEI_RNG_PATH = (
    Path(__file__).resolve().parents[2]
    / "ocd_kernel"
    / "tei"
    / "vendor"
    / "relaxng"
    / "tei_all.rng"
)


class ConversionError(ValueError):
    """Raised when retained bytes or the generated candidate violate the route."""


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    accounting: dict[str, object]


@dataclass
class _Context:
    electronic_page: int = 0


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _qname(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _el(
    name: str,
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
    *,
    nsmap: Mapping[str | None, str] | None = None,
) -> etree._Element:
    node = etree.Element(_qname(name), nsmap=nsmap)
    for key, value in (attrs or {}).items():
        attribute = XML_ID if key == "xml:id" else XML_LANG if key == "xml:lang" else key
        node.set(attribute, value)
    node.text = text
    return node


def _append_raw_text(parent: etree._Element, value: str | None) -> None:
    if value is None:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _classes(node: etree._Element) -> set[str]:
    return set((node.get("class") or "").split())


def _copy_common_attrs(source: etree._Element, attrs: dict[str, str]) -> None:
    if source.get("id"):
        attrs["xml:id"] = source.get("id", "")
    if source.get("title"):
        attrs["n"] = source.get("title", "")
    if source.get("class"):
        attrs["rend"] = source.get("class", "")


def _page_number(node: etree._Element) -> str:
    text = " ".join(node.text_content().split())
    match = re.search(r"\[([^]]+)\]", text)
    if not match:
        raise ConversionError(f"electronic page milestone has no bracketed number: {text!r}")
    return match.group(1)


def _render_children(source: etree._Element, parent: etree._Element, context: _Context) -> None:
    _append_raw_text(parent, source.text)
    for child in source:
        if isinstance(child, etree._ProcessingInstruction) and child.target == "pb":
            context.electronic_page += 1
            number = re.search(r'n="([^"]+)"', child.text or "")
            edition = re.search(r'ed="([^"]+)"', child.text or "")
            if number is None:
                raise ConversionError(f"page processing instruction lacks n: {child.text!r}")
            rendered = _el(
                "pb",
                {
                    "xml:id": f"epub-pb-{context.electronic_page:04d}",
                    "n": number.group(1),
                    "ed": edition.group(1) if edition else "OLL-electronic",
                },
            )
        else:
            rendered = _render_node(child, context)
        if rendered is not None:
            parent.append(rendered)
        _append_raw_text(parent, child.tail)


def _render_table(source: etree._Element, context: _Context) -> etree._Element:
    attrs: dict[str, str] = {}
    _copy_common_attrs(source, attrs)
    table = _el("table", attrs)
    captions = source.xpath("./caption")
    if captions:
        head = _el("head", {"type": "caption"})
        _render_children(captions[0], head, context)
        table.append(head)
    for row_source in source.xpath(".//tr"):
        row = _el("row")
        for cell_source in row_source.xpath("./th|./td"):
            cell_attrs = {"role": "label"} if cell_source.tag == "th" else {}
            cell = _el("cell", cell_attrs)
            _render_children(cell_source, cell, context)
            row.append(cell)
        table.append(row)
    return table


def _render_container_children(
    source: etree._Element,
    parent: etree._Element,
    context: _Context,
) -> None:
    """Render an HTML block container without placing inline content under div."""

    current_ab: etree._Element | None = None

    def inline_block() -> etree._Element:
        nonlocal current_ab
        if current_ab is None:
            current_ab = _el("ab", {"type": "source-inline"})
            parent.append(current_ab)
        return current_ab

    if source.text and source.text.strip():
        _append_raw_text(inline_block(), source.text)
    block_tags = {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul"}
    for child in source:
        is_page_milestone = (
            isinstance(child, etree._ProcessingInstruction) and child.target == "pb"
        ) or (
            isinstance(child.tag, str)
            and child.tag.lower() == "span"
            and "pb" in _classes(child)
        )
        if isinstance(child, etree._ProcessingInstruction) and child.target == "pb":
            context.electronic_page += 1
            number = re.search(r'n="([^"]+)"', child.text or "")
            edition = re.search(r'ed="([^"]+)"', child.text or "")
            if number is None:
                raise ConversionError(f"page processing instruction lacks n: {child.text!r}")
            rendered = _el(
                "pb",
                {
                    "xml:id": f"epub-pb-{context.electronic_page:04d}",
                    "n": number.group(1),
                    "ed": edition.group(1) if edition else "OLL-electronic",
                },
            )
        else:
            rendered = _render_node(child, context)
        is_block = is_page_milestone or (
            isinstance(child.tag, str) and child.tag.lower() in block_tags
        )
        if rendered is not None:
            if is_block:
                current_ab = None
                parent.append(rendered)
            else:
                inline_block().append(rendered)
        if child.tail and child.tail.strip():
            _append_raw_text(inline_block(), child.tail)


def _render_list(source: etree._Element, context: _Context) -> etree._Element:
    attrs: dict[str, str] = {}
    _copy_common_attrs(source, attrs)
    result = _el("list", attrs)
    for source_item in source.xpath("./li"):
        item_attrs: dict[str, str] = {}
        _copy_common_attrs(source_item, item_attrs)
        item = _el("item", item_attrs)
        _append_raw_text(item, source_item.text)
        for child in source_item:
            if isinstance(child.tag, str) and child.tag.lower() in {
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
            }:
                rendered = _el("label")
                _render_children(child, rendered, context)
            else:
                rendered = _render_node(child, context)
            if rendered is not None:
                item.append(rendered)
            _append_raw_text(item, child.tail)
        result.append(item)
    return result


def _render_flat_children(source: etree._Element, parent: etree._Element, context: _Context) -> None:
    """Preserve a presentational wrapper inline when TEI block ordering forbids it."""

    _append_raw_text(parent, source.text)
    for child in source:
        if not isinstance(child.tag, str):
            rendered = None
        elif child.tag.lower() in {"div", "p", "h1", "h2", "h3", "h4"}:
            attrs: dict[str, str] = {}
            _copy_common_attrs(child, attrs)
            rendered = _el("seg", attrs)
            _render_flat_children(child, rendered, context)
        else:
            rendered = _render_node(child, context)
        if rendered is not None:
            parent.append(rendered)
        _append_raw_text(parent, child.tail)


def _render_div(source: etree._Element, context: _Context) -> etree._Element:
    classes = _classes(source)
    if "PlaceName" in classes:
        name = "placeName"
    elif "dateline" in classes:
        name = "dateline"
    elif any(value.startswith("date") for value in classes):
        name = "date"
    elif "signed" in classes:
        name = "signed"
    elif "addrline" in classes:
        name = "addrLine"
    elif "byline" in classes:
        name = "byline"
    elif "opener" in classes and any("epigraph" in _classes(child) for child in source):
        name = "argument"
    elif "opener" in classes:
        name = "opener"
    elif "closer" in classes:
        name = "p"
    elif "cit" in classes:
        name = "quote"
    else:
        name = "div"
    attrs: dict[str, str] = {}
    _copy_common_attrs(source, attrs)
    if name != "div":
        pass
    elif "type-chapter" in classes:
        attrs["type"] = "chapter"
    elif "type-argument" in classes:
        attrs["type"] = "argument"
    elif "type-footnote" in classes:
        attrs["type"] = "endnote"
    elif "type-index" in classes:
        attrs["type"] = "index"
    elif "type-toc" in classes:
        attrs["type"] = "contents"
    elif "type-introduction" in classes:
        attrs["type"] = "introduction"
    elif "type-part" in classes:
        attrs["type"] = "part"
    elif "type-section" in classes:
        attrs["type"] = "section"
    elif "table-wrap" in classes or "type-table-wrap" in classes:
        attrs["type"] = "table-wrap"
    elif "front" in classes:
        attrs["type"] = "electronic-front"
    elif "titlepage" in classes:
        attrs["type"] = "title-page"
    elif classes:
        attrs["type"] = "-".join(sorted(classes))
    else:
        attrs["type"] = "source-div"
    result = _el(name, attrs)
    if name == "argument":
        _append_raw_text(result, source.text)
        for child in source:
            if isinstance(child.tag, str) and "epigraph" in _classes(child):
                _render_children(child, result, context)
            else:
                rendered = _render_node(child, context) if isinstance(child.tag, str) else None
                if rendered is not None:
                    result.append(rendered)
            _append_raw_text(result, child.tail)
    elif "closer" in classes:
        _render_flat_children(source, result, context)
    elif name == "div":
        _render_container_children(source, result, context)
    else:
        _render_children(source, result, context)
    return result


def _render_span(source: etree._Element, context: _Context) -> etree._Element:
    classes = _classes(source)
    if "pb" in classes:
        context.electronic_page += 1
        return _el(
            "pb",
            {
                "xml:id": f"epub-pb-{context.electronic_page:04d}",
                "n": _page_number(source),
                "ed": "OLL-electronic",
            },
        )
    attrs: dict[str, str] = {}
    _copy_common_attrs(source, attrs)
    if "ital" in classes:
        name, attrs["rend"] = "hi", "italic"
    elif "csc" in classes or "sc" in classes:
        name, attrs["rend"] = "hi", "small-caps"
    elif "subhead" in classes:
        name, attrs["rend"] = "label", "subhead"
    elif "title" in classes:
        name = "title"
    elif "gap" in classes:
        return _el("gap", {"reason": "source-gap", "extent": source.get("title", "unknown")})
    else:
        name = "seg"
    result = _el(name, attrs)
    _render_children(source, result, context)
    return result


def _render_anchor(source: etree._Element, context: _Context) -> etree._Element:
    classes = _classes(source)
    attrs: dict[str, str] = {}
    _copy_common_attrs(source, attrs)
    href = source.get("href")
    if href:
        attrs["target"] = href
    if "type-footnote" in classes:
        attrs["type"] = "note"
    elif "type-cross" in classes:
        attrs["type"] = "section"
    elif "type-tocpage" in classes:
        attrs["type"] = "printed-page"
    elif href:
        attrs["type"] = "source-link"
    result = _el("ref", attrs)
    _render_children(source, result, context)
    return result


def _render_node(source: etree._Element, context: _Context) -> etree._Element | None:
    if not isinstance(source.tag, str):
        return None
    tag = source.tag.lower()
    if tag == "div":
        return _render_div(source, context)
    if tag == "p":
        name = "p"
    elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        name = "head"
    elif tag == "span":
        return _render_span(source, context)
    elif tag == "a":
        return _render_anchor(source, context)
    elif tag == "table":
        return _render_table(source, context)
    elif tag == "ul":
        return _render_list(source, context)
    elif tag == "li":
        name = "item"
    elif tag == "br":
        return _el("lb")
    elif tag in {"i", "em"}:
        name = "hi"
    elif tag == "small":
        name = "hi"
    elif tag in {"col", "colgroup", "thead", "tbody", "tr", "th", "td", "caption"}:
        return None
    else:
        name = "seg"
    attrs: dict[str, str] = {}
    _copy_common_attrs(source, attrs)
    if tag in {"i", "em"}:
        attrs["rend"] = "italic"
    elif tag == "small":
        attrs["rend"] = "smaller"
    result = _el(name, attrs)
    _render_children(source, result, context)
    return result


def _source_text(node: etree._Element) -> str:
    pieces: list[str] = []

    def visit(current: etree._Element) -> None:
        if not isinstance(current.tag, str):
            return
        if current.tag == "span" and "pb" in _classes(current):
            return
        if current.text:
            pieces.append(current.text)
        for child in current:
            visit(child)
            if child.tail:
                pieces.append(child.tail)

    visit(node)
    return " ".join(" ".join(pieces).split())


def _tei_text(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _source_counts(root: etree._Element) -> dict[str, int]:
    anchors = list(root.iter("a"))
    counts = {
        "paragraph_count": len(list(root.iter("p"))),
        "chapter_count": sum(1 for n in root.iter("div") if n.get("class") == "type-chapter"),
        "argument_count": sum(1 for n in root.iter("div") if n.get("class") == "type-argument"),
        "section_div_count": sum(1 for n in root.iter("div") if n.get("class") == "type-section"),
        "electronic_page_milestone_count": sum(1 for n in root.iter("span") if "pb" in _classes(n)),
        "processing_instruction_page_milestone_count": sum(
            1 for n in root.iter() if isinstance(n, etree._ProcessingInstruction) and n.target == "pb"
        ),
        "note_count": sum(1 for n in root.iter("div") if n.get("class") == "type-footnote note"),
        "note_reference_count": sum(1 for n in anchors if n.get("class") == "footnote-link type-footnote"),
        "section_cross_reference_count": sum(1 for n in anchors if n.get("class") == "footnote-link type-cross"),
        "toc_page_reference_count": sum(1 for n in anchors if n.get("class") == "footnote-link type-tocpage"),
        "table_count": len(list(root.iter("table"))),
        "caption_count": len(list(root.iter("caption"))),
        "list_item_count": len(list(root.iter("li"))),
        "italic_count": sum(1 for n in root.iter("span") if "ital" in _classes(n)),
        "small_caps_count": sum(1 for n in root.iter("span") if _classes(n) & {"csc", "sc"}),
        "gap_count": sum(1 for n in root.iter("span") if "gap" in _classes(n)),
    }
    changed = {
        key: (EXPECTED_SOURCE_COUNTS[key], value)
        for key, value in counts.items()
        if EXPECTED_SOURCE_COUNTS[key] != value
    }
    if changed:
        raise ConversionError(f"retained EPUB source census changed: {changed}")
    ids = [n.get("id") for n in root.iter() if isinstance(n.tag, str) and n.get("id")]
    if len(ids) != 12027 or len(ids) != len(set(ids)):
        raise ConversionError("retained EPUB source ID census changed or contains duplicates")
    targets = [n.get("href", "")[1:] for n in anchors if n.get("href", "").startswith("#")]
    if len(targets) != 3865 or set(targets) - set(ids):
        raise ConversionError("retained EPUB internal-link accounting changed")
    return counts


def _header() -> etree._Element:
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", {"type": "main"}, "The Institutes of the Christian Religion"))
    title_stmt.append(_el("author", text="John Calvin"))
    resp = _el("respStmt")
    resp.append(_el("resp", text="translated by"))
    resp.append(_el("name", text="Henry Beveridge"))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = _el("publicationStmt")
    publication.append(_el("publisher", text="Open Christian Data"))
    publication.append(_el("date", {"when": "2026-08-31"}, "2026"))
    availability = _el("availability", {"status": "free"})
    licence = _el("licence", {"target": OLL_TITLE_URL})
    licence.append(_el("p", text="Online Library of Liberty states: The text is in the public domain."))
    availability.append(licence)
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("title", text="The Institutes of the Christian Religion"))
    bibl.append(_el("author", text="John Calvin"))
    bibl.append(_el("editor", text="Henry Beveridge, translator"))
    bibl.append(_el("edition", text="Edinburgh: Calvin Translation Society, 1846; two volumes in one; OLL electronic edition"))
    bibl.append(_el("ref", {"target": OLL_TITLE_URL}, OLL_TITLE_URL))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    encoding = _el("encodingDesc")
    project = _el("projectDesc")
    project.append(
        _el(
            "p",
            text=(
                "Source-specific deterministic projection of the retained OLL EPUB. "
                "The facsimile-only General Index is represented separately from an "
                "uncorrected searchable-text extraction with page-level facsimile pointers."
            ),
        )
    )
    encoding.append(project)
    header.append(encoding)
    revision = _el("revisionDesc")
    change = _el("change", {"when": "2026-08-31"})
    change.text = "Created nonaccepted source-bound candidate for technical review."
    revision.append(change)
    header.append(revision)
    return header


def _load_sources(repository_root: Path) -> tuple[etree._Element, dict[str, object]]:
    try:
        epub_path = resolve_repo_path(repository_root, SOURCE_LOGICAL_PATH)
        ebook_pdf_path = resolve_repo_path(repository_root, EBOOK_PDF_LOGICAL_PATH)
        facsimile_path = resolve_repo_path(repository_root, FACSIMILE_LOGICAL_PATH)
        extraction_path = resolve_repo_path(repository_root, INDEX_EXTRACTION_LOGICAL_PATH)
    except StorageTopologyError as exc:
        raise ConversionError(f"cannot resolve retained source: {exc}") from exc
    source_bytes = epub_path.read_bytes()
    if _sha256(source_bytes) != SOURCE_SHA256:
        raise ConversionError("retained EPUB SHA-256 changed")
    if _sha256(ebook_pdf_path.read_bytes()) != EBOOK_PDF_SHA256:
        raise ConversionError("retained text-based eBook PDF SHA-256 changed")
    if _sha256(facsimile_path.read_bytes()) != FACSIMILE_SHA256:
        raise ConversionError("retained facsimile PDF SHA-256 changed")
    extraction_bytes = extraction_path.read_bytes()
    if _sha256(extraction_bytes) != INDEX_EXTRACTION_SHA256:
        raise ConversionError("bounded facsimile index extraction SHA-256 changed")
    try:
        with ZipFile(epub_path) as archive:
            if archive.testzip() is not None:
                raise ConversionError("retained EPUB CRC check failed")
            members = tuple(sorted(info.filename for info in archive.infolist() if not info.is_dir()))
            if members != tuple(sorted(EXPECTED_EPUB_MEMBERS)):
                raise ConversionError(f"retained EPUB members changed: {members}")
            html_bytes = archive.read(SOURCE_HTML_MEMBER)
    except BadZipFile as exc:
        raise ConversionError("retained source is not a valid EPUB/ZIP") from exc
    if _sha256(html_bytes) != SOURCE_HTML_SHA256:
        raise ConversionError("retained EPUB HTML member SHA-256 changed")
    root = html.fromstring(html_bytes)
    bodies = root.xpath("//body")
    body_elements = [child for child in bodies[0] if isinstance(child.tag, str)] if bodies else []
    if len(bodies) != 1 or len(body_elements) != 1:
        raise ConversionError("retained EPUB must contain one body/document root")
    document = body_elements[0]
    counts = _source_counts(document)
    extraction = json.loads(extraction_bytes.decode("utf-8"))
    pages = extraction.get("pages")
    if (
        extraction.get("source_pdf_sha256") != FACSIMILE_SHA256
        or extraction.get("source_pdf_pages") != 1311
        or not isinstance(pages, list)
        or [page.get("printed_page") for page in pages] != list(range(691, 705))
        or [page.get("pdf_page_number") for page in pages] != list(range(1298, 1312))
    ):
        raise ConversionError("bounded facsimile General Index extraction metadata changed")
    for page in pages:
        if _sha256(page["text"].encode("utf-8")) != page["text_sha256"]:
            raise ConversionError(f"facsimile extraction page hash changed: {page['printed_page']}")
    return document, {"counts": counts, "index_extraction": extraction}


def _build_document(source: etree._Element, loaded: dict[str, object]) -> tuple[etree._ElementTree, dict[str, object]]:
    root = _el("TEI", {"xml:lang": "en"}, nsmap={None: TEI_NS})
    root.append(_header())
    facsimile = _el("facsimile", {"xml:id": "facsimile-general-index"})
    pages = loaded["index_extraction"]["pages"]
    for page in pages:
        surface = _el("surface", {"xml:id": f"facsimile-index-p{page['printed_page']}"})
        surface.append(
            _el(
                "graphic",
                {
                    "url": f"{FACSIMILE_LOGICAL_PATH}#page={page['pdf_page_number']}",
                    "mimeType": "application/pdf",
                },
            )
        )
        facsimile.append(surface)
    root.append(facsimile)
    text = _el("text")
    body = _el("body")
    transcription = _el("div", {"type": "epub-transcription", "xml:id": "epub-transcription"})
    context = _Context()
    _render_children(source, transcription, context)
    body.append(transcription)
    index = _el(
        "div",
        {
            "type": "index",
            "subtype": "facsimile-searchable-text-extraction",
            "xml:id": "facsimile-general-index-transcription",
        },
    )
    index.append(_el("head", text="GENERAL INDEX."))
    provenance = _el("note", {"type": "provenance"})
    provenance.text = (
        "Printed pages 691-704 are omitted from the EPUB and electronic PDF. "
        "The following page-bounded text is the uncorrected embedded searchable-text "
        "extraction from the retained facsimile, not an exact human transcription."
    )
    index.append(provenance)
    for page in pages:
        index.append(
            _el(
                "pb",
                {
                    "n": str(page["printed_page"]),
                    "facs": f"#facsimile-index-p{page['printed_page']}",
                    "ed": "facsimile-1846-reprint",
                },
            )
        )
        index.append(
            _el(
                "ab",
                {
                    "type": "searchable-text-extraction",
                    "cert": "low",
                    "n": str(page["printed_page"]),
                },
                page["text"],
            )
        )
    body.append(index)
    text.append(body)
    root.append(text)
    tree = etree.ElementTree(root)
    epub_source_text = _source_text(source)
    epub_tei_text = _tei_text(transcription)
    if epub_source_text != epub_tei_text:
        mismatch = next(
            (i for i, pair in enumerate(zip(epub_source_text, epub_tei_text)) if pair[0] != pair[1]),
            min(len(epub_source_text), len(epub_tei_text)),
        )
        raise ConversionError(
            f"EPUB/TEI visible text mismatch at {mismatch}: "
            f"{epub_source_text[mismatch:mismatch+80]!r} != {epub_tei_text[mismatch:mismatch+80]!r}"
        )
    extracted_text = "\n".join(page["text"] for page in pages)
    encoded_text = "\n".join(node.text or "" for node in index.xpath("./t:ab", namespaces=NS))
    if extracted_text != encoded_text:
        raise ConversionError("facsimile extraction/TEI text mismatch")
    counts = loaded["counts"]
    accounting: dict[str, object] = {
        "source_logical_path": SOURCE_LOGICAL_PATH,
        "source_sha256": SOURCE_SHA256,
        "source_html_member": SOURCE_HTML_MEMBER,
        "source_html_sha256": SOURCE_HTML_SHA256,
        "ebook_pdf_logical_path": EBOOK_PDF_LOGICAL_PATH,
        "ebook_pdf_sha256": EBOOK_PDF_SHA256,
        "facsimile_logical_path": FACSIMILE_LOGICAL_PATH,
        "facsimile_sha256": FACSIMILE_SHA256,
        "facsimile_page_count": 1311,
        "facsimile_index_extraction_logical_path": INDEX_EXTRACTION_LOGICAL_PATH,
        "facsimile_index_extraction_sha256": INDEX_EXTRACTION_SHA256,
        **counts,
        "epub_visible_text_sha256": _sha256(epub_source_text.encode("utf-8")),
        "tei_epub_visible_text_sha256": _sha256(epub_tei_text.encode("utf-8")),
        "facsimile_index_extracted_text_sha256": _sha256(extracted_text.encode("utf-8")),
        "tei_facsimile_index_text_sha256": _sha256(encoded_text.encode("utf-8")),
        "facsimile_index_printed_pages": list(range(691, 705)),
        "facsimile_index_pdf_pages": list(range(1298, 1312)),
        "facsimile_index_textual_status": "uncorrected embedded searchable-text extraction; low certainty",
        "facsimile_index_visual_terminal_boundary": ["ZEPHYRINUS", "ZIPPORAH"],
        "electronic_source_omission": "General Index, facsimile printed pp. 691-704",
        "electronic_source_additions": [
            "Wm. B. Eerdmans title/imprint matter",
            "Introduction by the Rev. John Murray",
            "OLL electronic page-marker labels and navigation metadata",
        ],
        "electronic_normalization": [
            "EPUB entity decoding to Unicode by lxml HTML parser",
            "source whitespace retained in TEI nodes; comparison digest collapses XML/HTML whitespace only",
            "no spelling, punctuation, capitalization, wording, or source page values modernized",
        ],
        "tei_p5_relaxng_valid": True,
        "tei_relaxng_path": TEI_RNG_PATH.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
        "tei_relaxng_sha256": _sha256(TEI_RNG_PATH.read_bytes()),
    }
    return tree, accounting


@lru_cache(maxsize=1)
def _tei_relaxng() -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(TEI_RNG_PATH)))


def validate_tei(value: etree._ElementTree | etree._Element | bytes | Path) -> dict[str, object]:
    if isinstance(value, Path):
        tree = etree.parse(str(value))
    elif isinstance(value, bytes):
        tree = etree.ElementTree(etree.fromstring(value))
    elif isinstance(value, etree._ElementTree):
        tree = value
    elif isinstance(value, etree._Element):
        tree = etree.ElementTree(value)
    else:  # pragma: no cover
        raise TypeError(f"unsupported TEI value: {type(value)!r}")
    schema = _tei_relaxng()
    if not schema.validate(tree):
        errors = [f"{error.path}: {error.message}" for error in schema.error_log]
        raise ConversionError("TEI P5 Relax NG validation failed:\n" + "\n".join(errors[:30]))
    ids = tree.xpath("//@xml:id", namespaces=NS)
    if len(ids) != len(set(ids)):
        raise ConversionError("generated TEI contains duplicate xml:id values")
    targets = tree.xpath("//t:ref[starts-with(@target, '#')]/@target", namespaces=NS)
    missing = sorted({target[1:] for target in targets} - set(ids))
    if missing:
        raise ConversionError(f"generated TEI has unresolved internal targets: {missing[:20]}")
    return {
        "xml_id_count": len(ids),
        "internal_target_count": len(targets),
        "facsimile_surface_count": len(tree.xpath("/t:TEI/t:facsimile/t:surface", namespaces=NS)),
    }


def convert_source(
    source_logical_path: str,
    output_path: Path,
    *,
    repository_root: Path | None = None,
) -> ConversionResult:
    if source_logical_path != SOURCE_LOGICAL_PATH:
        raise ConversionError(f"this route accepts only {SOURCE_LOGICAL_PATH}")
    repository = (repository_root or Path(__file__).resolve().parents[2]).resolve()
    source, loaded = _load_sources(repository)
    tree, accounting = _build_document(source, loaded)
    validation = validate_tei(tree)
    document = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(document)
    accounting = {**accounting, **validation, "document_sha256": _sha256(document)}
    return ConversionResult(output, accounting)


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_logical_path")
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--accounting", action="store_true")
    parser.add_argument("--accounting-output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = convert_source(args.source_logical_path, args.output_path)
    except (BadZipFile, ConversionError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    if args.accounting:
        print(json.dumps(result.accounting, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if args.accounting_output is not None:
        args.accounting_output.parent.mkdir(parents=True, exist_ok=True)
        args.accounting_output.write_text(
            json.dumps(result.accounting, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
