"""Faithful direct TEI candidate for the original, unrevised Douay-Rheims."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.validate import compiled_schema


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SOURCE_PREFIX = "source-json:original-douay-rheims-v1.0/"
CONFIG_RELATIVE = "sources/structured-text/original-douay-rheims/config.json"
OUTPUT_PREFIX = "reports/clean-ready-acquisition-to-tei/master-3/21/original-douay-rheims/"
DEFAULT_OUTPUT = OUTPUT_PREFIX + "candidate"

CANONICAL_OT = (
    "genesis", "exodus", "leviticus", "numbers", "deuteronomy", "josue",
    "judges", "ruth", "1-kings", "2-kings", "3-kings", "4-kings",
    "1-paralipomenon", "2-paralipomenon", "1-esdras", "2-esdras", "tobias",
    "judith", "esther", "job", "psalms", "proverbs", "ecclesiastes",
    "canticle-of-canticles", "wisdom", "ecclesiasticus", "isaie", "jeremie",
    "lamentations", "baruch", "ezechiel", "daniel", "osee", "joel", "amos",
    "abdias", "jonas", "micheas", "nahum", "habacuc", "sophonias", "aggeus",
    "zacharias", "malachie", "1-machabees", "2-machabees",
)
CANONICAL_NT = (
    "matthew", "mark", "luke", "john", "acts", "romans", "1-corinthians",
    "2-corinthians", "galatians", "ephesians", "philippians", "colossians",
    "1-thessalonians", "2-thessalonians", "1-timothy", "2-timothy", "titus",
    "philemon", "hebrews", "james", "1-peter", "2-peter", "1-john", "2-john",
    "3-john", "jude", "apocalypse",
)
APPENDIX_BOOKS = ("3-esdras", "4-esdras", "prayer-of-manasses")
DUPLICATE_BOOK = "prayer-of-manasseh"

_INLINE = re.compile(
    r"<br>|</?(?:i|sc|na|mn|cr|alt|col-left|col-right)>|"
    r"<span class=\"ref-title-sub\">|</span>"
)
_OPEN = {
    "i": ("hi", {"rend": "italic"}),
    "sc": ("hi", {"rend": "small-caps"}),
    "na": ("seg", {"type": "note-anchor"}),
    "mn": ("seg", {"type": "marginal-note-marker"}),
    "cr": ("ref", {"type": "cross-reference-marker"}),
    "alt": ("seg", {"type": "alternate-reading"}),
    "col-left": ("seg", {"type": "column-left"}),
    "col-right": ("seg", {"type": "column-right"}),
    "span": ("hi", {"rend": "ref-title-sub"}),
}


def _q(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source_text(value: Any) -> str:
    """Preserve JSON scalar values without Python display spellings."""
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    raise ValueError(f"unsupported non-scalar value in text-bearing source field: {type(value).__name__}")


def _member(path: Path, root: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(content),
        "sha256": _sha(content),
    }


def _members(root: Path, paths: Iterable[Path]) -> list[dict[str, object]]:
    return [_member(path, root) for path in sorted(paths)]


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"source JSON is not an object: {path}")
    return value


def _pointer(relative: str, *parts: object) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return SOURCE_PREFIX + relative.replace("\\", "/") + "#/" + "/".join(escaped)


def _append_text(parent: etree._Element, value: str) -> None:
    if len(parent):
        child = parent[-1]
        child.tail = (child.tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _append_markup(parent: etree._Element, value: str) -> None:
    stack: list[tuple[str, etree._Element]] = [("root", parent)]
    position = 0
    for match in _INLINE.finditer(value):
        _append_text(stack[-1][1], value[position : match.start()])
        token = match.group(0)
        if token == "<br>":
            etree.SubElement(stack[-1][1], _q("lb"), type="source-br")
        elif token.startswith("</"):
            name = token[2:-1]
            if name == "span":
                name = "span"
            if len(stack) == 1 or stack[-1][0] != name:
                _append_text(stack[-1][1], token)
            else:
                stack.pop()
        else:
            if token.startswith("<span"):
                name = "span"
            else:
                name = token[1:-1]
            tag, attributes = _OPEN[name]
            child = etree.SubElement(stack[-1][1], _q(tag), **attributes)
            stack.append((name, child))
        position = match.end()
    _append_text(stack[-1][1], value[position:])
    for _, node in stack[1:]:
        node.set("ana", "#source-unclosed-markup")


def _source_markup(parent: etree._Element) -> str:
    output = [parent.text or ""]
    for child in parent:
        local = etree.QName(child).localname
        if local == "lb" and child.get("type") == "source-br":
            output.append("<br>")
        else:
            key: str
            if local == "hi" and child.get("rend") == "italic":
                key = "i"
            elif local == "hi" and child.get("rend") == "small-caps":
                key = "sc"
            elif local == "hi" and child.get("rend") == "ref-title-sub":
                key = "span"
            elif local == "seg" and child.get("type") == "note-anchor":
                key = "na"
            elif local == "seg" and child.get("type") == "marginal-note-marker":
                key = "mn"
            elif local == "ref" and child.get("type") == "cross-reference-marker":
                key = "cr"
            elif local == "seg" and child.get("type") == "alternate-reading":
                key = "alt"
            elif local == "seg" and child.get("type") == "column-left":
                key = "col-left"
            elif local == "seg" and child.get("type") == "column-right":
                key = "col-right"
            else:
                raise ValueError(f"unsupported TEI inline projection: {etree.tostring(child)!r}")
            opening = '<span class="ref-title-sub">' if key == "span" else f"<{key}>"
            closing = "</span>" if key == "span" else f"</{key}>"
            output.extend((opening, _source_markup(child)))
            if child.get("ana") != "#source-unclosed-markup":
                output.append(closing)
        output.append(child.tail or "")
    return "".join(output)


def _add_source_text(
    parent: etree._Element,
    tag: str,
    value: str,
    corresp: str,
    events: list[dict[str, str]],
    **attributes: str,
) -> etree._Element:
    node = etree.SubElement(parent, _q(tag), corresp=corresp, **attributes)
    _append_markup(node, value)
    events.append({"corresp": corresp, "value": value})
    return node


def _render_notes(
    parent: etree._Element,
    notes: list[dict[str, Any]],
    relative: str,
    pointer_parts: tuple[object, ...],
    events: list[dict[str, str]],
    note_type: str,
) -> None:
    for index, note in enumerate(notes):
        if set(note) not in ({"label", "text"}, {"marker", "text"}):
            raise ValueError(f"unsupported {note_type} note shape in {relative}: {sorted(note)}")
        marker_key = "label" if "label" in note else "marker"
        _add_source_text(
            parent,
            "note",
            _source_text(note["text"]),
            _pointer(relative, *pointer_parts, index, "text"),
            events,
            type=note_type,
            n=str(note[marker_key]),
        )


def _render_article(
    parent: etree._Element,
    article: dict[str, Any],
    relative: str,
    pointer_parts: tuple[object, ...],
    events: list[dict[str, str]],
    article_type: str,
    index: int,
) -> None:
    allowed = {"title", "text", "notes", "part", "default"}
    if not set(article) <= allowed:
        raise ValueError(f"unsupported {article_type} keys in {relative}: {sorted(set(article) - allowed)}")
    div = etree.SubElement(parent, _q("div"), type=article_type, n=str(index + 1))
    if "title" in article:
        _add_source_text(div, "head", _source_text(article["title"]), _pointer(relative, *pointer_parts, "title"), events)
    if "text" in article:
        _add_source_text(div, "ab", _source_text(article["text"]), _pointer(relative, *pointer_parts, "text"), events, type=f"{article_type}-text")
    if "part" in article:
        _add_source_text(div, "ab", _source_text(article["part"]), _pointer(relative, *pointer_parts, "part"), events, type="annotation-part")
    if article.get("default") is True:
        div.set("ana", "#default-introduction")
    if "notes" in article:
        _render_notes(div, article["notes"], relative, (*pointer_parts, "notes"), events, f"{article_type}-note")


def _render_reference_value(
    parent: etree._Element,
    key: str,
    value: Any,
    relative: str,
    pointer_parts: tuple[object, ...],
    events: list[dict[str, str]],
) -> None:
    subtype = key.replace("_", "-")
    if isinstance(value, str):
        field = etree.SubElement(parent, _q("div"), type="reference-field", subtype=subtype)
        _add_source_text(field, "ab", value, _pointer(relative, *pointer_parts), events, type="reference-value")
    elif value is None or isinstance(value, (bool, int, float)):
        rendered = json.dumps(value, ensure_ascii=False)
        field = etree.SubElement(parent, _q("div"), type="reference-scalar", subtype=subtype)
        _add_source_text(field, "ab", rendered, _pointer(relative, *pointer_parts), events, type="reference-value")
    elif isinstance(value, list):
        listing = etree.SubElement(parent, _q("div"), type="reference-list", subtype=subtype)
        for index, item in enumerate(value):
            item_pointer = (*pointer_parts, index)
            if isinstance(item, dict):
                item_div = etree.SubElement(listing, _q("div"), type="reference-item", n=str(index + 1))
                for child_key, child_value in item.items():
                    _render_reference_value(item_div, str(child_key), child_value, relative, (*item_pointer, child_key), events)
            else:
                _render_reference_value(listing, "item", item, relative, item_pointer, events)
    elif isinstance(value, dict):
        div = etree.SubElement(parent, _q("div"), type="reference-object", subtype=subtype)
        for child_key, child_value in value.items():
            _render_reference_value(div, str(child_key), child_value, relative, (*pointer_parts, child_key), events)
    else:
        raise ValueError(f"unsupported reference value {type(value).__name__} at {relative}:{pointer_parts}")


def _render_reference_document(
    parent: etree._Element,
    path: Path,
    source_root: Path,
    testament: str,
    events: list[dict[str, str]],
) -> None:
    relative = path.relative_to(source_root).as_posix()
    document = _load(path)
    if "title" not in document:
        raise ValueError(f"reference document has no title: {relative}")
    div = etree.SubElement(parent, _q("div"), type="reference-document", subtype=testament, n=path.stem, source=relative)
    _add_source_text(div, "head", _source_text(document["title"]), _pointer(relative, "title"), events)
    if "subtitle" in document:
        _add_source_text(div, "head", _source_text(document["subtitle"]), _pointer(relative, "subtitle"), events, type="subtitle")
    for key, value in document.items():
        if key in {"title", "subtitle"}:
            continue
        _render_reference_value(div, str(key), value, relative, (key,), events)


def _render_book(
    parent: etree._Element,
    path: Path,
    source_root: Path,
    annotations_root: Path,
    events: list[dict[str, str]],
    *,
    appendix: bool,
) -> dict[str, int]:
    relative = path.relative_to(source_root).as_posix()
    data = _load(path)
    allowed_top = {
        "book", "book_title", "short_title", "hebrew_title", "intros", "chapters",
        "endMatters", "date", "version_abbr",
    }
    if not set(data) <= allowed_top or not {"book", "chapters"} <= set(data):
        raise ValueError(f"unsupported book shape in {relative}: {sorted(data)}")
    slug = path.stem
    div = etree.SubElement(parent, _q("div"), type="appendix-book" if appendix else "book", n=slug, source=relative)
    div.set(XML_ID, f"odr-book-{slug}")
    if "book_title" in data:
        _add_source_text(div, "head", _source_text(data["book_title"]), _pointer(relative, "book_title"), events, type="book-title")
    else:
        _add_source_text(div, "head", _source_text(data["book"]), _pointer(relative, "book"), events, type="book-title")
    if "short_title" in data:
        _add_source_text(div, "ab", _source_text(data["short_title"]), _pointer(relative, "short_title"), events, type="short-title")
    if "hebrew_title" in data:
        _add_source_text(div, "ab", _source_text(data["hebrew_title"]), _pointer(relative, "hebrew_title"), events, type="source-language-title")
    if "book_title" in data:
        _add_source_text(div, "ab", _source_text(data["book"]), _pointer(relative, "book"), events, type="source-book-identifier")
    if "date" in data:
        _add_source_text(div, "ab", _source_text(data["date"]), _pointer(relative, "date"), events, type="source-date")
    if "version_abbr" in data:
        _add_source_text(div, "ab", _source_text(data["version_abbr"]), _pointer(relative, "version_abbr"), events, type="source-version-abbreviation")
    intros = data.get("intros", [])
    if not isinstance(intros, list):
        raise ValueError(f"intros are not a list: {relative}")
    for index, intro in enumerate(intros):
        _render_article(div, intro, relative, ("intros", index), events, "book-introduction", index)

    annotation_files = {int(path.name[:-5]): path for path in sorted((annotations_root / slug).glob("*.json"))} if (annotations_root / slug).exists() else {}
    chapters = data["chapters"]
    if not isinstance(chapters, list):
        raise ValueError(f"chapters are not a list: {relative}")
    verse_count = inline_note_count = cross_reference_count = annotation_count = annotation_note_count = 0
    duplicate_verse_addresses = 0
    for chapter_index, chapter in enumerate(chapters):
        allowed_chapter = {"chapter", "summary", "summary_notes", "verses", "articles"}
        if not isinstance(chapter, dict) or not set(chapter) <= allowed_chapter or not {"chapter", "verses"} <= set(chapter):
            raise ValueError(f"unsupported chapter shape in {relative}: {chapter!r}")
        number = int(chapter["chapter"])
        chapter_div = etree.SubElement(div, _q("div"), type="chapter", n=str(number), source=f"{relative}#/chapters/{chapter_index}")
        chapter_div.set(XML_ID, f"odr-{slug}-{number}")
        if "summary" in chapter:
            _add_source_text(chapter_div, "head", _source_text(chapter["summary"]), _pointer(relative, "chapters", chapter_index, "summary"), events, type="chapter-summary")
        if "summary_notes" in chapter:
            _render_notes(chapter_div, chapter["summary_notes"], relative, ("chapters", chapter_index, "summary_notes"), events, "chapter-summary-note")
        verse_occurrences: Counter[int] = Counter()
        for verse_index, verse in enumerate(chapter["verses"]):
            allowed_verse = {"verse", "text", "notes", "cross_refs", "has_annotation"}
            if not isinstance(verse, dict) or not set(verse) <= allowed_verse or not {"verse", "text"} <= set(verse):
                raise ValueError(f"unsupported verse shape in {relative}: {verse!r}")
            verse_number = int(verse["verse"])
            verse_occurrences[verse_number] += 1
            occurrence = verse_occurrences[verse_number]
            verse_div = etree.SubElement(chapter_div, _q("div"), type="verse", n=str(verse_number))
            verse_id = f"odr-{slug}-{number}-{verse_number}"
            if occurrence > 1:
                verse_id += f"-occurrence-{occurrence}"
                verse_div.set("ana", "#duplicate-source-address")
                duplicate_verse_addresses += 1
            verse_div.set(XML_ID, verse_id)
            if verse.get("has_annotation") is True:
                verse_div.set("ana", "#has-annotation")
            _add_source_text(
                verse_div,
                "ab",
                _source_text(verse["text"]),
                _pointer(relative, "chapters", chapter_index, "verses", verse_index, "text"),
                events,
                type="verse-text",
            )
            verse_count += 1
            notes = verse.get("notes", [])
            _render_notes(verse_div, notes, relative, ("chapters", chapter_index, "verses", verse_index, "notes"), events, "inline-note")
            inline_note_count += len(notes)
            for cross_index, cross_ref in enumerate(verse.get("cross_refs", [])):
                if set(cross_ref) not in ({"text"}, {"label", "text"}):
                    raise ValueError(f"unsupported cross-reference shape in {relative}: {cross_ref!r}")
                attributes = {"type": "cross-reference"}
                if "label" in cross_ref:
                    attributes["n"] = str(cross_ref["label"])
                _add_source_text(
                    verse_div,
                    "note",
                    _source_text(cross_ref["text"]),
                    _pointer(relative, "chapters", chapter_index, "verses", verse_index, "cross_refs", cross_index, "text"),
                    events,
                    **attributes,
                )
                cross_reference_count += 1

        annotation_path = annotation_files.pop(number, None)
        if annotation_path is not None:
            annotation_relative = annotation_path.relative_to(source_root).as_posix()
            annotation_document = _load(annotation_path)
            if set(annotation_document) != {"chapter", "annotations"}:
                raise ValueError(f"unsupported annotation document shape: {annotation_relative}")
            if int(annotation_document["chapter"]) != number:
                raise ValueError(f"annotation chapter mismatch: {annotation_relative}")
            annotation_div = etree.SubElement(chapter_div, _q("div"), type="chapter-annotations", source=annotation_relative)
            for annotation_index, annotation in enumerate(annotation_document["annotations"]):
                verse_number = int(annotation["verse"])
                ann = etree.SubElement(annotation_div, _q("div"), type="annotation", n=str(verse_number), corresp=f"#odr-{slug}-{number}-{verse_number}")
                allowed_annotation = {"verse", "title", "text", "notes", "part"}
                if not set(annotation) <= allowed_annotation:
                    raise ValueError(f"unsupported annotation keys: {annotation_relative}:{sorted(annotation)}")
                if "title" in annotation:
                    _add_source_text(ann, "head", _source_text(annotation["title"]), _pointer(annotation_relative, "annotations", annotation_index, "title"), events)
                if "text" in annotation:
                    _add_source_text(ann, "ab", _source_text(annotation["text"]), _pointer(annotation_relative, "annotations", annotation_index, "text"), events, type="annotation-text")
                if "part" in annotation:
                    _add_source_text(ann, "ab", _source_text(annotation["part"]), _pointer(annotation_relative, "annotations", annotation_index, "part"), events, type="annotation-part")
                notes = annotation.get("notes", [])
                _render_notes(ann, notes, annotation_relative, ("annotations", annotation_index, "notes"), events, "annotation-subnote")
                annotation_count += 1
                annotation_note_count += len(notes)
    if annotation_files:
        raise ValueError(f"orphan annotation files for {slug}: {sorted(annotation_files)}")
    for index, end_matter in enumerate(data.get("endMatters", [])):
        _render_article(div, end_matter, relative, ("endMatters", index), events, "book-end-matter", index)
    return {
        "chapters": len(chapters),
        "verses": verse_count,
        "inline_notes": inline_note_count,
        "cross_references": cross_reference_count,
        "annotations": annotation_count,
        "annotation_subnotes": annotation_note_count,
        "duplicate_verse_addresses": duplicate_verse_addresses,
    }


def _make_header(root: etree._Element, config: dict[str, Any]) -> None:
    header = etree.SubElement(root, _q("teiHeader"))
    file_desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(file_desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = str(config["title"])
    resp_stmt = etree.SubElement(title_stmt, _q("respStmt"))
    etree.SubElement(resp_stmt, _q("resp")).text = "Translation, revision, and original annotation corpus"
    for contributor in config["contributors"]:
        etree.SubElement(resp_stmt, _q("name")).text = str(contributor)
    publication = etree.SubElement(file_desc, _q("publicationStmt"))
    etree.SubElement(publication, _q("p")).text = (
        "CC0 1.0 Universal. Nonaccepted faithful TEI candidate for technical review; "
        "not a canonical master or publication."
    )
    source_desc = etree.SubElement(file_desc, _q("sourceDesc"))
    etree.SubElement(source_desc, _q("p")).text = (
        "Pinned structured release v1.0 at Git revision " + str(config["source_revision"]) + ". "
        "Rheims New Testament (1582) and Douai Old Testament (1609-1610), original unrevised text and apparatus."
    )
    encoding = etree.SubElement(header, _q("encodingDesc"))
    etree.SubElement(encoding, _q("p")).text = (
        "Source-specific transcription of tagged JSON, annotation sidecars, and reference documents. "
        "Historical spelling, punctuation, capitalization, inline markup, notes, and source structure are preserved."
    )
    revision = etree.SubElement(header, _q("revisionDesc"))
    etree.SubElement(revision, _q("change"), when="2026-08-31").text = "Generated as a nonaccepted ticket-21 pilot candidate."


def _tei(source_root: Path, config: dict[str, Any]) -> tuple[bytes, dict[str, int], list[dict[str, str]]]:
    tagged_root = source_root / "bible" / "tagged"
    annotations_root = source_root / "annotations"
    actual = {path.stem for path in tagged_root.glob("*.json")}
    expected = set(CANONICAL_OT) | set(CANONICAL_NT) | set(APPENDIX_BOOKS) | {DUPLICATE_BOOK}
    if actual != expected or len(actual) != 77:
        raise ValueError(f"tagged book inventory drift: missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    duplicate = tagged_root / f"{DUPLICATE_BOOK}.json"
    authority = tagged_root / "prayer-of-manasses.json"
    if duplicate.read_bytes() != authority.read_bytes():
        raise ValueError("the two Prayer of Manasses source members are no longer exact duplicates")

    root = etree.Element(_q("TEI"), nsmap={None: TEI_NS})
    root.set(XML_LANG, "en")
    _make_header(root, config)
    events: list[dict[str, str]] = []
    text = etree.SubElement(root, _q("text"))
    group = etree.SubElement(text, _q("group"))
    counts = Counter()

    ot_text = etree.SubElement(group, _q("text"), type="testament", n="OT")
    ot_front = etree.SubElement(ot_text, _q("front"))
    for path in sorted((source_root / "reference" / "ot").glob("*.json")):
        _render_reference_document(ot_front, path, source_root, "old-testament", events)
        counts["reference_documents"] += 1
    ot_body = etree.SubElement(ot_text, _q("body"))
    for slug in CANONICAL_OT:
        counts.update(_render_book(ot_body, tagged_root / f"{slug}.json", source_root, annotations_root, events, appendix=False))
        counts["canonical_books"] += 1
    appendix = etree.SubElement(ot_body, _q("div"), type="source-appendix", n="apocryphal-appendix")
    for slug in APPENDIX_BOOKS:
        counts.update(_render_book(appendix, tagged_root / f"{slug}.json", source_root, annotations_root, events, appendix=True))
        counts["appendix_books"] += 1

    nt_text = etree.SubElement(group, _q("text"), type="testament", n="NT")
    nt_front = etree.SubElement(nt_text, _q("front"))
    for path in sorted((source_root / "reference" / "nt").glob("*.json")):
        _render_reference_document(nt_front, path, source_root, "new-testament", events)
        counts["reference_documents"] += 1
    nt_body = etree.SubElement(nt_text, _q("body"))
    for slug in CANONICAL_NT:
        counts.update(_render_book(nt_body, tagged_root / f"{slug}.json", source_root, annotations_root, events, appendix=False))
        counts["canonical_books"] += 1

    etree.SubElement(
        appendix,
        _q("note"),
        type="source-disposition",
    ).text = (
        "The pinned release contains both prayer-of-manasseh.json and prayer-of-manasses.json with identical bytes. "
        "The latter is rendered once; the former remains retained and hash-accounted as an exact duplicate."
    )
    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    return content, dict(counts), events


def _verify_text_events(tei_bytes: bytes, events: list[dict[str, str]]) -> dict[str, object]:
    root = etree.fromstring(tei_bytes)
    nodes = {
        node.get("corresp"): node
        for node in root.xpath("//*[@corresp]")
        if str(node.get("corresp", "")).startswith(SOURCE_PREFIX)
    }
    if len(nodes) != len(events):
        raise ValueError(f"TEI source-text pointer count mismatch: {len(nodes)} != {len(events)}")
    for event in events:
        node = nodes.get(event["corresp"])
        if node is None:
            raise ValueError(f"TEI lacks source text pointer {event['corresp']}")
        observed = _source_markup(node)
        if observed != event["value"]:
            raise ValueError(f"TEI text event drift at {event['corresp']}")
    return {
        "text_events": len(events),
        "text_event_inventory_sha256": _sha(_canonical(events)),
        "exact_source_markup_roundtrip": True,
    }


def _tag_census(paths: Iterable[Path]) -> dict[str, int]:
    result: Counter[str] = Counter()
    tag = re.compile(r"<(/?)([A-Za-z0-9_-]+)(?:\s[^>]*)?>")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            for match in tag.finditer(value):
                result[("/" if match.group(1) else "") + match.group(2)] += 1

    for path in paths:
        walk(_load(path))
    return dict(sorted(result.items()))


def _build_candidate(repository_root: Path) -> dict[str, bytes]:
    config_path = repository_root / CONFIG_RELATIVE
    config = _load(config_path)
    source_root = resolve_repo_path(repository_root, str(config["source_root"]))
    archive_path = resolve_repo_path(repository_root, str(config["source_file"]))
    headers_path = resolve_repo_path(repository_root, str(config["http_headers_file"]))
    if not source_root.is_dir() or not archive_path.is_file() or not headers_path.is_file():
        raise FileNotFoundError("retained original Douay-Rheims acquisition is incomplete")
    archive_bytes = archive_path.read_bytes()
    headers_bytes = headers_path.read_bytes()
    all_files = sorted(path for path in source_root.rglob("*") if path.is_file())
    tagged = sorted((source_root / "bible" / "tagged").glob("*.json"))
    raw = sorted((source_root / "bible" / "raw").glob("*.json"))
    usfm = sorted((source_root / "usfm").glob("*.usfm"))
    annotations = sorted((source_root / "annotations").rglob("*.json"))
    references = sorted((source_root / "reference").rglob("*.json"))
    if (len(tagged), len(raw), len(usfm), len(annotations), len(references)) != (77, 77, 77, 394, 26):
        raise ValueError("retained v1.0 member census drifted")
    if {p.name for p in tagged} != {p.name for p in raw} or {p.stem for p in tagged} != {p.stem for p in usfm}:
        raise ValueError("tagged/raw/USFM member inventories disagree")

    tei_bytes, tei_counts, events = _tei(source_root, config)
    schema = compiled_schema()
    tei_tree = etree.fromstring(tei_bytes)
    schema_valid = schema.validate(tei_tree)
    if not schema_valid:
        raise ValueError(f"TEI P5 validation failure: {schema.error_log.last_error}")
    event_evidence = _verify_text_events(tei_bytes, events)

    used_paths = tagged + annotations + references + [source_root / "README.md", source_root / "SCHEMA.md", source_root / "LICENSE"]
    receipt = {
        "contract": "ocd-original-douay-rheims-source-receipt-v1",
        "ticket": 21,
        "gate_identity": "provisional net-new candidate - no canonical WorkCatalog write",
        "source_title": config["title"],
        "contributors": config["contributors"],
        "edition": config["source_edition"],
        "explicit_omissions": [
            "The moving main branch is not used; this acquisition is pinned to tag v1.0.",
            "The text-only raw JSON and USFM derivatives are retained and hashed but are not transformation authorities.",
            "The exact duplicate prayer-of-manasseh.json is not rendered a second time.",
            "The separately downloadable PDFs are not members of the released GitHub v1.0 source archive and are not candidate authority.",
        ],
        "landing_url": config["source_url"],
        "download_url": config["source_download_url"],
        "retrieved_at_utc": config["retrieved_at_utc"],
        "source_tag": config["source_tag"],
        "source_revision": config["source_revision"],
        "http_etag": config["http_etag"],
        "archive": {"path": config["source_file"], "bytes": len(archive_bytes), "sha256": _sha(archive_bytes)},
        "http_headers": {"path": config["http_headers_file"], "bytes": len(headers_bytes), "sha256": _sha(headers_bytes)},
        "extracted_members": _members(source_root, all_files),
        "transformation_authority_members": _members(source_root, used_paths),
        "rights": {
            "license": "CC0 1.0 Universal",
            "license_member": _member(source_root / "LICENSE", source_root),
            "attribution_required": False,
            "basis": "The retained README and LICENSE state that the release is CC0 and public domain.",
        },
        "completeness_observation": {
            "opening_title": "reference/ot/title-page.json and reference/nt/title-page.json are retained and rendered.",
            "middle_structure": "The canonical book/chapter/verse sequence, book introductions, chapter summaries, articles, and chapter annotation transitions are rendered.",
            "ending": "Apocalypse 22:21 is retained and rendered as the final canonical verse.",
            "unusual_features": [
                "Inline i, sc, na, mn, cr, alt, br, span, col-left, and col-right markup is retained in TEI equivalents.",
                "All 394 annotation sidecars, 1,659 annotations, and 3,544 annotation subnotes are rendered.",
                "All 26 reference files, including historical tables, glossaries, doctrinal tables, and title material, are rendered.",
                "The source declares 73 books but contains 77 tagged members; 3 Esdras, 4 Esdras, and Prayer of Manasses are rendered as source appendix components and the second Prayer filename is an exact retained duplicate.",
            ],
        },
        "acquisition_behavior": {
            "redirect": "GitHub returned HTTP 302 to codeload.github.com, followed to HTTP 200.",
            "container": "The exact tag archive is retained and extracted without source-byte normalization.",
            "decoding": "JSON members are decoded as UTF-8; source strings are emitted without spelling, punctuation, capitalization, or wording modernization.",
            "text_value_mapping": "Source strings are preserved exactly; non-string scalar values in text-bearing fields use their JSON lexical form (for example, null is rendered as null and booleans remain lowercase JSON literals). Unsupported compound values fail closed.",
            "ocr": "No OCR was performed by this acquisition or converter.",
        },
        "unresolved_questions": [
            "The release README says 73 books although the pinned tag contains 77 tagged members and 76 unique textual components.",
            "The release tree does not encode a reading order; the candidate uses the historical Catholic order stated explicitly in the source-specific converter and places the three extra textual components in a source appendix.",
            "The source's claim of faithful rendering from the original printed volumes is retained as a source claim, not elevated to human textual acceptance.",
        ],
    }
    accountability = {
        "contract": "ocd-original-douay-rheims-source-accountability-v1",
        "source_revision": config["source_revision"],
        "member_counts": {
            "archive_containers": 1,
            "extracted_files": len(all_files),
            "tagged_book_members": len(tagged),
            "canonical_books_rendered": len(CANONICAL_OT) + len(CANONICAL_NT),
            "appendix_books_rendered": len(APPENDIX_BOOKS),
            "exact_duplicate_tagged_members": 1,
            "annotation_files": len(annotations),
            "reference_files": len(references),
            "raw_derivative_book_files_retained": len(raw),
            "usfm_derivative_book_files_retained": len(usfm),
        },
        "text_counts": tei_counts,
        "source_markup_counts": _tag_census(tagged + annotations + references),
        "member_inventory_sha256": _sha(_canonical(_members(source_root, all_files))),
        **event_evidence,
        "tei_sha256": _sha(tei_bytes),
        "tei_p5_valid": True,
        "omitted_transformation_authority_members": 0,
        "candidate_status": "nonaccepted",
        "human_review_required": True,
        "canonical_data_or_ir_changed": False,
        "work_catalog_changed": False,
        "publication_ready": False,
    }
    unresolved = {
        "contract": "ocd-original-douay-rheims-unresolved-v1",
        "items": receipt["unresolved_questions"],
        "source_member_disposition": {
            "canonical": list(CANONICAL_OT + CANONICAL_NT),
            "source_appendix": list(APPENDIX_BOOKS),
            "exact_duplicate_not_rendered_twice": DUPLICATE_BOOK,
        },
    }
    validation = {
        "contract": "ocd-original-douay-rheims-validation-v1",
        "status": "pass",
        "tei_p5_schema": "vendored tei_all.xsd",
        "tei_p5_valid": schema_valid,
        "source_text_events_exact": event_evidence["exact_source_markup_roundtrip"],
        "source_member_binding": "pass",
        "accountability_status": "pass",
        "candidate_status": "nonaccepted",
    }
    readme = (
        "# Original Douay-Rheims ticket-21 pilot\n\n"
        "This directory is a deterministic, nonaccepted faithful TEI candidate for the pinned v1.0 structured release.\n\n"
        "It is not the Challoner revision, a canonical WorkCatalog entry, human textual acceptance, or publication. "
        "See `source-receipt.json`, `source-accountability.json`, `validation.json`, and `unresolved.json` for the exact evidence boundary.\n"
    ).encode("utf-8")
    outputs = {
        "README.md": readme,
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "source-receipt.json": _canonical(receipt),
        "unresolved.json": _canonical(unresolved),
        "validation.json": _canonical(validation),
    }
    manifest = {
        "contract": "ocd-original-douay-rheims-candidate-manifest-v1",
        "candidate_id": "original-douay-rheims-v1.0-ticket-21",
        "status": "nonaccepted",
        "source_revision": config["source_revision"],
        "members": [
            {"name": name, "bytes": len(content), "sha256": _sha(content)}
            for name, content in sorted(outputs.items())
        ],
        "human_review_required": True,
        "publication_ready": False,
    }
    outputs["manifest.json"] = _canonical(manifest)
    return outputs


def write_candidate(repository_root: Path, destination: Path) -> dict[str, object]:
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"candidate destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    outputs = _build_candidate(repository_root)
    for name, content in sorted(outputs.items()):
        (destination / name).write_bytes(content)
    return {
        "destination": str(destination),
        "members": [
            {"name": name, "bytes": len(content), "sha256": _sha(content)}
            for name, content in sorted(outputs.items())
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-relative", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    relative = str(args.output_relative).replace("\\", "/")
    if not relative.startswith(OUTPUT_PREFIX) or ".." in Path(relative).parts:
        raise SystemExit(f"output must stay below {OUTPUT_PREFIX}")
    destination = resolve_repo_path(repository_root, relative)
    print(json.dumps(write_candidate(repository_root, destination), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
