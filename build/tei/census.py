"""Raw-source feature census for TEI conversion gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from lxml import etree

from build.lib.ccel_thml import preprocess_thml
from build.tei.bcp_source import feature_payload, load_bcp_edition
from build.tei.ccel_work_config import (
    ccel_division_rule,
    ccel_scope_label,
    load_ccel_work_config,
    select_ccel_scope,
)
from build.tei.gutenberg_to_tei import (
    INLINE_RE,
    _footnotes,
    _footnote_ranges,
    _is_vol1_source,
    _load_source,
    _paragraphs,
    _paired_parenthetical_anchor_count,
    _source_groups,
)

CENSUS_SCHEMA_ID = "tei-census-v1"

_XHTML_NS = {"x": "http://www.w3.org/1999/xhtml"}
_EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
_DIV_TAG_RE = re.compile(r"^div\d+$")
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "title"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _feature(nodes: list[Any]) -> dict[str, Any]:
    ids = [node.get("id") for node in nodes if node.get("id")]
    return {"count": len(nodes), "ids": ids}


def _has_ancestor_named(node: etree._Element, tag: str) -> bool:
    parent = node.getparent()
    while parent is not None:
        if etree.QName(parent).localname == tag:
            return True
        parent = parent.getparent()
    return False


def _parse_thml(xml_path: Path) -> etree._Element:
    # Matches the CCEL NPNF1 parser pattern: strip DOCTYPE and replace ThML
    # named entities before strict XML parsing.
    prepared = preprocess_thml(xml_path.read_bytes()).encode("utf-8")
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False)
    try:
        return etree.fromstring(prepared, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Could not parse ThML XML at {_display_path(xml_path)}: {exc}") from exc


def census_thml_div1(xml_path: str | Path, div1_id: str) -> dict[str, Any]:
    path = Path(xml_path)
    root = _parse_thml(path)
    matches = root.xpath(".//div1[@id=$div1_id]", div1_id=div1_id)
    if not matches:
        raise ValueError(f"No div1 with id {div1_id!r} found in {_display_path(path)}")
    div1 = matches[0]

    paragraphs = [node for node in div1.xpath(".//p") if not _has_ancestor_named(node, "note")]
    div2 = list(div1.xpath("./div2"))
    div3 = list(div1.xpath(".//div3"))
    notes = list(div1.xpath(".//note"))
    page_breaks = list(div1.xpath(".//pb"))
    scripture_refs = list(div1.xpath(".//scripRef"))
    italics = list(div1.xpath(".//i"))
    lang_spans = [node for node in div1.xpath(".//*[@lang]")]

    structure_titles = {
        node.get("id"): node.get("title", "")
        for node in [*div2, *div3]
        if node.get("id") and node.get("title") is not None
    }

    return {
        "census_schema": CENSUS_SCHEMA_ID,
        "source": {
            "type": "ccel_thml",
            "path": _display_path(path),
            "sha256": _sha256(path),
            "scope": f"div1[@id='{div1_id}']",
        },
        "features": {
            "divisions_level2": _feature(div2),
            "divisions_level3": _feature(div3),
            "paragraphs": _feature(paragraphs),
            "notes": _feature(notes),
            "page_breaks": _feature(page_breaks),
            "scripture_refs": _feature(scripture_refs),
            "italics": _feature(italics),
            "lang_spans": _feature(lang_spans),
        },
        "structure_titles": structure_titles,
    }


def _is_configured_div(node: etree._Element) -> bool:
    return bool(_DIV_TAG_RE.match(etree.QName(node).localname))


def _is_skipped_by_config(node: etree._Element, rules: list[dict[str, Any]]) -> bool:
    current: etree._Element | None = node
    while current is not None:
        if _is_configured_div(current) and ccel_division_rule(current, rules).get("skip"):
            return True
        current = current.getparent()
    return False


def census_ccel_work(
    config_path: str | Path,
    work_id: str,
    *,
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    config = load_ccel_work_config(config_path, work_id, repo_root)
    root = _parse_thml(config.raw_path)
    scope = select_ccel_scope(root, config)
    rules = config.division_rules

    divisions = [
        node
        for node in scope.iter()
        if node is not scope and _is_configured_div(node) and not _is_skipped_by_config(node, rules)
    ]
    paragraphs = [
        node
        for node in scope.xpath(".//p")
        if not _has_ancestor_named(node, "note") and not _is_skipped_by_config(node, rules)
    ]
    notes = [node for node in scope.xpath(".//note") if not _is_skipped_by_config(node, rules)]
    page_breaks = [node for node in scope.xpath(".//pb") if not _is_skipped_by_config(node, rules)]
    scripture_refs = [node for node in scope.xpath(".//scripRef") if not _is_skipped_by_config(node, rules)]
    italics = [node for node in scope.xpath(".//i") if not _is_skipped_by_config(node, rules)]
    lang_spans = [node for node in scope.xpath(".//*[@lang]") if not _is_skipped_by_config(node, rules)]
    display_spans = [
        node
        for node in scope.xpath(".//span[not(@lang)]")
        if not _is_skipped_by_config(node, rules)
    ]
    arguments = [node for node in scope.xpath(".//argument") if not _is_skipped_by_config(node, rules)]
    headings = [
        node
        for node in scope.iter()
        if etree.QName(node).localname in _HEADING_TAGS and not _is_skipped_by_config(node, rules)
    ]
    names = [node for node in scope.xpath(".//name") if not _is_skipped_by_config(node, rules)]
    citations = [node for node in scope.xpath(".//cite") if not _is_skipped_by_config(node, rules)]
    tables = [node for node in scope.xpath(".//table") if not _is_skipped_by_config(node, rules)]
    table_rows = [node for node in scope.xpath(".//tr") if not _is_skipped_by_config(node, rules)]
    table_cells = [
        node
        for node in scope.xpath(".//td | .//th")
        if not _is_skipped_by_config(node, rules)
    ]

    structure_titles = {
        node.get("id"): node.get("title", "")
        for node in divisions
        if node.get("id") and node.get("title") is not None
    }

    return {
        "census_schema": CENSUS_SCHEMA_ID,
        "source": {
            "type": "ccel_thml",
            "work_id": config.work_id,
            "rendering_id": config.rendering_id,
            "path": _display_path(config.raw_path),
            "sha256": _sha256(config.raw_path),
            "scope": ccel_scope_label(config),
        },
        "features": {
            "divisions": _feature(divisions),
            "paragraphs": _feature(paragraphs),
            "notes": _feature(notes),
            "page_breaks": _feature(page_breaks),
            "scripture_refs": _feature(scripture_refs),
            "italics": _feature(italics),
            "lang_spans": _feature(lang_spans),
            "display_spans": _feature(display_spans),
            "arguments": _feature(arguments),
            "headings": _feature(headings),
            "names": _feature(names),
            "citations": _feature(citations),
            "tables": _feature(tables),
            "table_rows": _feature(table_rows),
            "table_cells": _feature(table_cells),
        },
        "structure_titles": structure_titles,
    }


def _parse_xhtml(path: Path) -> etree._Element:
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False)
    try:
        return etree.parse(str(path), parser=parser).getroot()
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Could not parse XHTML at {_display_path(path)}: {exc}") from exc


def _epub_type_tokens(node: etree._Element) -> set[str]:
    return set((node.get(_EPUB_TYPE) or "").split())


def _section_depth(section: etree._Element) -> int:
    depth = 1
    parent = section.getparent()
    while parent is not None:
        if etree.QName(parent).localname == "section":
            depth += 1
        parent = parent.getparent()
    return depth


def _git_head_or_none(work_dir: Path) -> str | None:
    if not (work_dir / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(work_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def census_se_work(work_dir: str | Path) -> dict[str, Any]:
    root_dir = Path(work_dir)
    text_dir = root_dir / "src" / "epub" / "text"
    xhtml_files = sorted(text_dir.glob("*.xhtml"))
    content_files = [path for path in xhtml_files if path.name != "endnotes.xhtml"]
    endnotes_path = text_dir / "endnotes.xhtml"

    sections: list[etree._Element] = []
    noterefs: list[etree._Element] = []
    bridgeheads: list[etree._Element] = []
    emphasis: list[etree._Element] = []
    typographic_emphasis: list[etree._Element] = []
    bold: list[etree._Element] = []
    lists: list[etree._Element] = []
    list_items: list[etree._Element] = []
    verse_blocks: list[etree._Element] = []
    front_sections: list[etree._Element] = []
    back_sections: list[etree._Element] = []
    section_depths: dict[str, int] = {}

    for path in content_files:
        root = _parse_xhtml(path)
        file_sections = list(root.xpath(".//x:section", namespaces=_XHTML_NS))
        sections.extend(file_sections)
        for section in file_sections:
            section_id = section.get("id")
            if section_id:
                section_depths[section_id] = _section_depth(section)
        body = root.find("{http://www.w3.org/1999/xhtml}body")
        body_tokens = _epub_type_tokens(body) if body is not None else set()
        if "frontmatter" in body_tokens:
            front_sections.extend(file_sections)
        if "backmatter" in body_tokens:
            back_sections.extend(file_sections)
        noterefs.extend(
            node
            for node in root.xpath(".//x:a", namespaces=_XHTML_NS)
            if "noteref" in _epub_type_tokens(node)
        )
        bridgeheads.extend(
            node
            for node in root.xpath(".//x:p", namespaces=_XHTML_NS)
            if _epub_type_tokens(node) & {"se:bridgehead", "bridgehead"}
        )
        emphasis.extend(root.xpath(".//x:em", namespaces=_XHTML_NS))
        typographic_emphasis.extend(root.xpath(".//x:i", namespaces=_XHTML_NS))
        bold.extend(root.xpath(".//x:b | .//x:strong", namespaces=_XHTML_NS))
        lists.extend(root.xpath(".//x:ol | .//x:ul", namespaces=_XHTML_NS))
        list_items.extend(root.xpath(".//x:li", namespaces=_XHTML_NS))
        verse_blocks.extend(
            node
            for node in root.xpath(".//x:blockquote", namespaces=_XHTML_NS)
            if _epub_type_tokens(node) & {"z3998:verse", "z3998:song", "z3998:poem"}
        )

    endnotes: list[etree._Element] = []
    if endnotes_path.exists():
        endnotes_root = _parse_xhtml(endnotes_path)
        endnotes = list(endnotes_root.xpath(".//x:li[@id]", namespaces=_XHTML_NS))
    endnote_ids = {node.get("id") for node in endnotes if node.get("id")}

    unresolved_noterefs = []
    for noteref in noterefs:
        href = noteref.get("href", "")
        target = href.rsplit("#", 1)[-1] if "#" in href else ""
        if target not in endnote_ids and noteref.get("id"):
            unresolved_noterefs.append(noteref.get("id"))

    censused_files = [*content_files]
    if endnotes_path.exists():
        censused_files.append(endnotes_path)

    return {
        "census_schema": CENSUS_SCHEMA_ID,
        "source": {
            "type": "standard_ebooks",
            "path": _display_path(root_dir),
            "git_head": _git_head_or_none(root_dir),
            "files": [
                {"path": _display_path(path), "sha256": _sha256(path)}
                for path in sorted(censused_files)
            ],
        },
        "features": {
            "sections": _feature(sections),
            "noterefs": _feature(noterefs),
            "endnotes": _feature(endnotes),
            "bridgeheads": _feature(bridgeheads),
            "emphasis": _feature(emphasis),
            "typographic_emphasis": _feature(typographic_emphasis),
            "bold": _feature(bold),
            "lists": _feature(lists),
            "list_items": _feature(list_items),
            "verse_blocks": _feature(verse_blocks),
            "front_sections": _feature(front_sections),
            "back_sections": _feature(back_sections),
        },
        "section_depths": section_depths,
        "unresolved_noterefs": unresolved_noterefs,
    }


def census_gutenberg_calvin(vol1_path: str | Path, vol2_path: str | Path) -> dict[str, Any]:
    """Census the selected Calvin Gutenberg rendering before TEI conversion."""
    sources = (_load_source(Path(vol1_path), 1), _load_source(Path(vol2_path), 2))
    book_ids_by_roman: dict[str, str] = {}
    chapters: list[str] = []
    body_paragraphs: list[tuple[str, int]] = []
    body_markup_texts: dict[str, list[str]] = {source.slug: [] for source in sources}
    markup_texts: list[str] = []
    anchor_markup_texts: dict[str, list[str]] = {source.slug: [] for source in sources}
    for source in sources:
        front = _paragraphs(source.lines, 0, source.first_book)
        front_texts = [text for _line, text in front]
        markup_texts.extend(front_texts)
        anchor_markup_texts[source.slug].extend(front_texts)
        for book, chapter_events in _source_groups(source):
            book_id = f"{source.slug}-book-{book.roman}"
            book_ids_by_roman.setdefault(book.roman, book_id)
            for position, chapter in enumerate(chapter_events):
                chapters.append(f"{source.slug}-chapter-{book.roman}-{chapter.roman}")
                stop = chapter_events[position + 1].line if position + 1 < len(chapter_events) else next(
                    (
                        event.line
                        for event in source.events
                        if event.kind == "book" and event.line > book.line
                    ),
                    source.main_stop,
                )
                paragraphs = _paragraphs(
                    source.lines,
                    chapter.content_start,
                    stop,
                    skip_ranges=_footnote_ranges(source),
                )
                body_paragraphs.extend((source.slug, line) for line, _text in paragraphs)
                body_texts = [text for _line, text in paragraphs]
                body_markup_texts[source.slug].extend(body_texts)
                anchor_markup_texts[source.slug].extend(body_texts)
                markup_texts.extend(body_texts)
        note_texts = [text for _line, _number, text in _footnotes(source)]
        markup_texts.extend(note_texts)

    emphasis_count = sum(1 for text in markup_texts for match in INLINE_RE.finditer(text) if match.group(1))
    anchor_counts_by_source = {
        source.slug: (
            _paired_parenthetical_anchor_count(
                anchor_markup_texts[source.slug],
                frozenset(number for _line, number, _text in _footnotes(source)),
            )
            if _is_vol1_source(source)
            else sum(
                1
                for text in body_markup_texts[source.slug]
                for match in INLINE_RE.finditer(text)
                if match.group(2)
            )
        )
        for source in sources
    }
    anchor_count = sum(anchor_counts_by_source.values())
    note_bodies = [
        f"{source.slug}-note-{number}"
        for source in sources
        for _line, number, _text in _footnotes(source)
    ]
    source_files = [
        {"path": _display_path(source.path), "sha256": _sha256(source.path)} for source in sources
    ]
    return {
        "census_schema": CENSUS_SCHEMA_ID,
        "source": {
            "type": "gutenberg_plain_text",
            "work_id": "calvins-institutes",
            "rendering_id": "gutenberg",
            "files": source_files,
            "apparatus_shape": [
                {
                    "volume": ("I", "II")[index],
                    "source": source.slug,
                    "anchor_count": anchor_counts_by_source[source.slug],
                    "note_body_count": len(_footnotes(source)),
                    "resolution": (
                        "unanchored back-matter"
                        if anchor_counts_by_source[source.slug] == 0
                        else "all refs resolve"
                        if _is_vol1_source(source)
                        else "all refs resolve; one note body is unreferenced"
                    ),
                }
                for index, source in enumerate(sources)
            ],
            "scopes": [
                "each volume after the first all-caps BOOK heading through the selected work boundary",
                "Vol. I FOOTNOTES and Vol. II Footnote N: blocks are preserved as per-volume note bodies and removed from body prose",
            ],
            "excluded": [
                "Project Gutenberg license wrapper lines",
                "Vol. II material after END OF THE INSTITUTES. (index and scripture index)",
            ],
        },
        "features": {
            "books": {
                "count": len(book_ids_by_roman),
                "ids": [book_ids_by_roman[roman] for roman in ("I", "II", "III", "IV") if roman in book_ids_by_roman],
            },
            "chapters": {"count": len(chapters), "ids": chapters},
            "paragraphs": {"count": len(body_paragraphs), "ids": []},
            "front_matter": {"count": len(sources), "ids": [f"{source.slug}-front" for source in sources]},
            "emphasis": {"count": emphasis_count, "ids": []},
            "note_anchors": {"count": anchor_count, "ids": []},
            "note_bodies": {"count": len(note_bodies), "ids": note_bodies},
        },
    }


def census_bcp_liturgy(edition_slug: str, raw_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(raw_root) if raw_root is not None else Path.cwd() / "raw"
    edition = load_bcp_edition(edition_slug, root)
    features = {
        "services": feature_payload(edition.events, "services"),
        "collects": feature_payload(edition.events, "collects"),
        "speaker_units": feature_payload(edition.events, "speaker_units"),
        "rubrics": feature_payload(edition.events, "rubrics"),
        "labels": feature_payload(edition.events, "labels"),
    }
    files: dict[str, dict[str, str]] = {}
    for event in edition.events:
        if not event.source_path.startswith("raw/"):
            continue
        path = root / event.source_path.removeprefix("raw/")
        files[event.source_path] = {"path": event.source_path, "sha256": _sha256(path)}
    return {
        "census_schema": CENSUS_SCHEMA_ID,
        "source": {
            "type": "bcp_liturgy",
            "edition": edition.slug,
            "path": "raw",
            "source_kind": edition.source_kind,
            "files": list(files.values()),
        },
        "features": features,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build raw-source census JSON for TEI conversion gates.")
    subparsers = parser.add_subparsers(dest="source_type", required=True)

    thml = subparsers.add_parser("thml", help="Census one div1 in a CCEL ThML file.")
    thml.add_argument("xml_path", type=Path)
    thml.add_argument("div1_id")
    thml.add_argument("output_path", type=Path)

    se = subparsers.add_parser("se", help="Census a Standard Ebooks work directory.")
    se.add_argument("work_dir", type=Path)
    se.add_argument("output_path", type=Path)

    gutenberg = subparsers.add_parser("gutenberg-calvin", help="Census the selected Calvin Gutenberg rendering.")
    gutenberg.add_argument("vol1_path", type=Path)
    gutenberg.add_argument("vol2_path", type=Path)
    gutenberg.add_argument("output_path", type=Path)

    bcp = subparsers.add_parser("bcp", help="Census one BCP liturgy edition.")
    bcp.add_argument("edition_slug")
    bcp.add_argument("output_path", type=Path)
    bcp.add_argument("--raw-root", type=Path)

    args = parser.parse_args()
    if args.source_type == "thml":
        census = census_thml_div1(args.xml_path, args.div1_id)
    elif args.source_type == "se":
        census = census_se_work(args.work_dir)
    elif args.source_type == "gutenberg-calvin":
        census = census_gutenberg_calvin(args.vol1_path, args.vol2_path)
    else:
        census = census_bcp_liturgy(args.edition_slug, args.raw_root)
    _write_json(args.output_path, census)


if __name__ == "__main__":
    main()
