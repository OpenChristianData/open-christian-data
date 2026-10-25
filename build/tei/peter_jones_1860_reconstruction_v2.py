"""Exact retained Wikisource 1860 Peter Jones selection to readable TEI."""
from __future__ import annotations

from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EXPORT_NS = "http://www.mediawiki.org/xml/export-0.11/"
SOURCE = "raw/wikisource/peter-jones-life-and-journals-1860"
NONSOURCE = re.compile(r"<noinclude>.*?</noinclude>", re.I | re.S)
PAGE = re.compile(r"<pages\s+index=\"([^\"]+)\"\s+from=(\d+)\s+to=(\d+)\s*/>", re.I)
HEADER = re.compile(r"\|\s*section\s*=\s*(.+)")
SENTINEL = re.compile(r"\uFFF0([A-Z]+):?([^\uFFF1]*)\uFFF1")
NOTE = re.compile(r"<ref\b[^>]*>(.*?)</ref>", re.I | re.S)
LINK = re.compile(r"\[\[([^][]+)\]\]")
TAG = re.compile(r"</?(?:span|div|nowiki|poem)\b[^>]*>", re.I)


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _node(parent: etree._Element, name: str, **attrs: str) -> etree._Element:
    child = etree.SubElement(parent, f"{{{TEI}}}{name}")
    for key, value in attrs.items():
        child.set(key, value)
    return child


def _authority(manifest: SourceManifest, name: str) -> bytes:
    return manifest.authority_path(name).read_bytes()


def _source(manifest: SourceManifest) -> dict[str, object]:
    profile = json.loads(_authority(manifest, "profile"))
    root_bytes = _authority(manifest, "root-export")
    root_receipt = json.loads(_authority(manifest, "root-receipt"))
    linked = json.loads(_authority(manifest, "linked-receipt"))
    leaves = json.loads(_authority(manifest, "leaf-receipt"))
    query = json.loads(_authority(manifest, "revision-query"))
    outer = json.loads(_authority(manifest, "outer-disposition"))
    if root_receipt["member"]["sha256"] != _sha(root_bytes) or root_receipt["verification"]["export_page_count"] != 68:
        raise ValueError("root export identity or envelope drift")
    if root_receipt["verification"]["member_inventory_sha256"] != _sha(_authority(manifest, "root-inventory")):
        raise ValueError("root inventory drift")
    if linked["inventory"]["sha256"] != _sha(_authority(manifest, "linked-inventory")) or linked["query"]["sha256"] != _sha(_authority(manifest, "revision-query")):
        raise ValueError("linked member inventory or revision query drift")
    if leaves["page_inventory"]["sha256"] != _sha(_authority(manifest, "leaf-inventory")) or leaves["outer_disposition"]["sha256"] != _sha(_authority(manifest, "outer-disposition")):
        raise ValueError("leaf inventory or outer disposition drift")
    if outer["index"]["parent_export_sha256"] != _sha(root_bytes):
        raise ValueError("outer disposition bound to another root export")
    if leaves["quality_gate"]["total_pages"] != 425 or leaves["quality_gate"]["validated"] != 424 or not leaves["quality_gate"]["page20_blank_is_index_declared"]:
        raise ValueError("retained leaf quality scope differs")
    xml = etree.fromstring(root_bytes, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    pages = xml.findall(f"{{{EXPORT_NS}}}page")
    if len(pages) != 68:
        raise ValueError("root export page count differs")
    indexed: dict[str, tuple[str, str]] = {}
    for page in pages:
        title = page.findtext(f"{{{EXPORT_NS}}}title")
        revision = page.find(f"{{{EXPORT_NS}}}revision")
        if title is None or revision is None or title in indexed:
            raise ValueError("duplicate or incomplete exported page")
        text = revision.findtext(f"{{{EXPORT_NS}}}text") or ""
        indexed[title] = (revision.findtext(f"{{{EXPORT_NS}}}id") or "", text)
    root_title = profile["root_title"]
    index_title = profile["index_title"]
    if indexed[root_title][0] != str(profile["root_revision"]) or indexed[index_title][0] != str(profile["index_revision"]):
        raise ValueError("root or Index revision differs")
    if not re.search(r"<pages\s+index=\"[^\"]+\"\s+from=8\s+to=19\s*/>", indexed[root_title][1]):
        raise ValueError("root paratext selector differs")
    index_text = indexed[index_title][1]
    for needle in ("|Publisher=Anson Green", "|Address=Toronto", "|Year=1860", "|Transclusion=yes", "20=-", "21=1", "445to450=-"):
        if needle not in index_text:
            raise ValueError(f"Index edition/scope claim differs: {needle}")
    front = []
    for number in range(8, 20):
        title = f"Page:Life and journals of Kah-ke-wa-quo-na-by.djvu/{number}"
        revision, text = indexed[title]
        front.append({"number": number, "revision": revision, "text": text, "title": title, "sha256": _sha(text.encode("utf-8"))})
    api_pages = {page["title"]: page for page in query["query"]["pages"].values()}
    children = []
    next_page = 20
    for expected_ordinal, item in enumerate(linked["pages"], 1):
        if item["ordinal"] != expected_ordinal:
            raise ValueError("linked child order differs")
        path = resolve_repo_path(manifest.repository_root, f"{SOURCE}/linked-work-pages-20260925/{item['path']}")
        content = path.read_bytes()
        if _sha(content) != item["sha256"] or len(content) != item["bytes"]:
            raise ValueError(f"linked child bytes differ: {item['path']}")
        page = api_pages[item["title"]]
        revision = page["revisions"][0]
        if revision["revid"] != item["revision_id"] or revision["slots"]["main"]["*"].encode("utf-8") != content:
            raise ValueError("linked child fixed revision differs")
        text = content.decode("utf-8", "strict")
        selectors = PAGE.search(text)
        if selectors is None or selectors.group(1) != profile["scan_index_name"]:
            raise ValueError(f"linked child transclusion missing: {item['path']}")
        start, end = int(selectors.group(2)), int(selectors.group(3))
        if start != next_page or end != item["transclusion"]["to_page"] or start != item["transclusion"]["from_page"]:
            raise ValueError("linked child range gap or receipt mismatch")
        heading = HEADER.search(text)
        if heading is None:
            raise ValueError("linked child heading missing")
        children.append({"ordinal": expected_ordinal, "title": item["title"], "revision": item["revision_id"], "path": item["path"], "sha256": item["sha256"], "start": start, "end": end, "heading": heading.group(1).strip()})
        next_page = end + 1
    if next_page != 445 or len(children) != 15 or children != profile["children"]:
        raise ValueError("linked child scope/profile differs")
    if len(leaves["members"]) != 425 or [item["page_number"] for item in leaves["members"]] != list(range(20, 445)):
        raise ValueError("leaf sequence is incomplete")
    leaf_text = {}
    for item in leaves["members"]:
        number = item["page_number"]
        path = resolve_repo_path(manifest.repository_root, f"{SOURCE}/page-leaves-20260925/{item['path']}")
        content = path.read_bytes()
        if _sha(content) != item["sha256"] or len(content) != item["bytes"]:
            raise ValueError(f"retained Page leaf bytes differ: {number}")
        if item["quality_status"] != ("Without text" if number == 20 else "Validated"):
            raise ValueError(f"unexpected Page quality status: {number}")
        leaf_text[number] = content.decode("utf-8", "strict")
    if leaf_text[20].replace(" ", "").find("pagequality") < 0 or NONSOURCE.sub("", leaf_text[20]).strip():
        raise ValueError("Index-declared blank leaf changed")
    return {"profile": profile, "front": front, "children": children, "leaves": leaves["members"], "leaf_text": leaf_text, "outer": outer, "root_export_sha256": _sha(root_bytes)}


def _split_pipe(text: str) -> list[str]:
    parts, start, depth, index = [], 0, 0, 0
    while index < len(text):
        if text.startswith("{{", index):
            depth += 1
            index += 2
        elif text.startswith("}}", index):
            depth -= 1
            index += 2
        elif text[index] == "|" and depth == 0:
            parts.append(text[start:index])
            start = index + 1
            index += 1
        else:
            index += 1
    parts.append(text[start:])
    return parts


def _expand_templates(text: str) -> str:
    output, index = [], 0
    while True:
        start = text.find("{{", index)
        if start < 0:
            output.append(text[index:])
            return "".join(output)
        output.append(text[index:start])
        pos, depth = start + 2, 1
        while depth and pos < len(text):
            if text.startswith("{{", pos):
                depth += 1
                pos += 2
            elif text.startswith("}}", pos):
                depth -= 1
                pos += 2
            else:
                pos += 1
        if depth:
            raise ValueError("unclosed source template")
        pieces = _split_pipe(text[start + 2:pos - 2])
        name = pieces[0].strip().casefold()
        args = pieces[1:]
        if name in {"hyphenated word start", "hyphenated word end", "dropinitial"}:
            value = args[0] if args else ""
        elif name in {"font-size", "fsx-block"}:
            value = args[-1] if args else ""
        elif name in {"small-caps", "center", "c", "cquote", "smaller", "smaller block", "xx-larger", "block center", "right", "left", "float right"}:
            value = next((item for item in reversed(args) if "=" not in item.split("\n", 1)[0]), "")
        elif name in {"rule", "upe"}:
            value = "\uFFF0RULE\uFFF1" if name == "rule" else "\uFFF0TEMPLATE:upe\uFFF1"
        elif name in {"gap", "rh", "smallrefs", "-"}:
            value = " " if name == "gap" else ""
        else:
            raise ValueError(f"unmapped retained template: {name}")
        output.append(_expand_templates(value))
        index = pos


def _render_inline(text: str) -> tuple[str, list[str], list[str], list[tuple[str, str]]]:
    notes: list[str] = []
    media: list[str] = []
    links: list[tuple[str, str]] = []
    def note(match: re.Match[str]) -> str:
        number = len(notes)
        notes.append(match.group(1))
        return f"\uFFF0NOTE:{number}\uFFF1"
    text = NOTE.sub(note, text)
    text = _expand_templates(text)
    def link(match: re.Match[str]) -> str:
        parts = match.group(1).split("|")
        if parts[0].casefold().startswith(("image:", "file:")):
            number = len(media)
            media.append(parts[0].split(":", 1)[1])
            return f"\uFFF0MEDIA:{number}\uFFF1"
        label = parts[-1] if len(parts) > 1 else parts[0]
        number = len(links)
        links.append((parts[0], label))
        return f"\uFFF0LINK:{number}\uFFF1"
    text = LINK.sub(link, text)
    text = re.sub(r"<br\b[^>]*>", "\uFFF0LB\uFFF1", text, flags=re.I)
    text = TAG.sub("", text)
    text = re.sub(r"'{2,5}", "", text)
    text = unescape(text)
    if "<" in text or "{{" in text or "[[" in text:
        raise ValueError("unmapped retained inline markup: " + repr(text))
    return text, notes, media, links


def _append(parent: etree._Element, content: str, notes: list[str], media: list[str], links: list[tuple[str, str]], targets: dict[str, str]) -> None:
    cursor = 0
    for match in SENTINEL.finditer(content):
        _add_text(parent, content[cursor:match.start()])
        kind, arg = match.groups()
        if kind == "NOTE":
            node = _node(parent, "note", place="foot")
            note_content, inner_notes, inner_media, inner_links = _render_inline(notes[int(arg)])
            if inner_notes:
                raise ValueError("nested source footnotes unsupported")
            _append(node, note_content, [], inner_media, inner_links, targets)
        elif kind == "MEDIA":
            _node(parent, "milestone", unit="unretained-media-reference", n=media[int(arg)])
        elif kind == "LINK":
            source_target, label = links[int(arg)]
            if source_target not in targets:
                raise ValueError(f"unresolved retained Wikisource link: {source_target}")
            _node(parent, "ref", target="#" + targets[source_target], n=source_target).text = label
        elif kind == "LB":
            _node(parent, "lb")
        elif kind == "RULE":
            _node(parent, "milestone", unit="source-rule")
        elif kind == "TEMPLATE":
            _node(parent, "milestone", unit="unexpanded-source-template", n=arg)
        else:
            raise ValueError(f"unknown render marker: {kind}")
        cursor = match.end()
    _add_text(parent, content[cursor:])


def _add_text(parent: etree._Element, text: str) -> None:
    if not text:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _page_body(source: str) -> str:
    body = NONSOURCE.sub("", source)
    if "<noinclude" in body.casefold() or "</noinclude" in body.casefold():
        raise ValueError("unbalanced Page noinclude wrapper")
    return body


def _map_pages(parent: etree._Element, pages: list[tuple[int, str]], targets: dict[str, str]) -> dict[str, object]:
    current: etree._Element | None = None
    table: etree._Element | None = None
    row: etree._Element | None = None
    cell: etree._Element | None = None
    page_text: dict[str, str] = {}
    source_tables = source_rows = source_cells = source_notes = source_media = source_links = 0
    for number, raw in pages:
        original_body = _page_body(raw)
        body, notes, media, links = _render_inline(_expand_templates(original_body))
        page_text[str(number)] = original_body
        source_notes += len(notes)
        source_media += len(media)
        source_links += len(links)
        target = cell if table is not None and cell is not None else current if current is not None else parent
        _node(target, "pb", n=str(number))
        if number == 20:
            _node(parent, "gap", reason="blank", unit="page", extent="1")
            continue
        for line in body.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("{|"):
                if table is not None:
                    raise ValueError(f"nested source table on page {number}")
                current = None
                table = _node(parent, "table", n=str(source_tables + 1))
                row = cell = None
                source_tables += 1
                continue
            if stripped.startswith("|}"):
                if table is None:
                    raise ValueError(f"unmatched source table end on page {number}")
                table = row = cell = None
                current = None
                continue
            if table is not None and stripped.startswith("|-"):
                row = _node(table, "row")
                cell = None
                source_rows += 1
                continue
            if table is not None and stripped.startswith("|"):
                if row is None:
                    row = _node(table, "row")
                    source_rows += 1
                content = stripped[1:]
                cells = re.split(r"\|\|", content)
                for part in cells:
                    if "|" in part:
                        attrs, value = part.split("|", 1)
                    else:
                        attrs, value = "", part
                    cell = _node(row, "cell")
                    if "colspan" in attrs:
                        span = re.search(r"colspan\s*=\s*[\"']?(\d+)", attrs)
                        if span:
                            cell.set("cols", span.group(1))
                    source_cells += 1
                    _append(cell, value, notes, media, links, targets)
                continue
            if not stripped:
                if table is None:
                    current = None
                elif cell is not None:
                    _add_text(cell, " ")
                continue
            if table is not None:
                if row is None:
                    row = _node(table, "row")
                    source_rows += 1
                if cell is None:
                    cell = _node(row, "cell")
                    source_cells += 1
                target = cell
            else:
                if current is None:
                    current = _node(parent, "p")
                target = current
            rendered = line.rstrip("\r\n")
            if target.text or len(target):
                _add_text(target, " ")
            _append(target, rendered, notes, media, links, targets)
    if table is not None:
        raise ValueError("unclosed source table at component boundary")
    return {"source_tables": source_tables, "source_rows": source_rows, "source_cells": source_cells, "notes": source_notes, "media_references": source_media, "links": source_links, "page_body_sha256": {n: _sha(t.encode("utf-8")) for n,t in page_text.items()}}


def _header(root: etree._Element, source_sha: str) -> None:
    header = _node(root, "teiHeader")
    desc = _node(header, "fileDesc")
    titles = _node(desc, "titleStmt")
    _node(titles, "title").text = "Life and Journals of Kah-ke-wa-quo-nā-by"
    _node(titles, "author").text = "Peter Jones"
    publication = _node(desc, "publicationStmt")
    _node(publication, "p").text = "Nonaccepted Wikisource transcription candidate. Human acceptance, print collation, rights clearance, and publication remain pending."
    source = _node(desc, "sourceDesc")
    _node(source, "p").text = "Toronto: Anson Green, 1860, edited selection as represented by the exact retained Wikisource electronic text. Root XML SHA-256 " + source_sha + ". Page scans were not acquired or visually collated."


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    source = _source(manifest)
    profile = source["profile"]
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "peter-jones-1860-wikisource-edited-selection")
    _header(root, source["root_export_sha256"])
    text = _node(root, "text")
    front = _node(text, "front")
    front_div = _node(front, "div", type="source-paratext")
    front_div.set(XML_ID, "root-paratext-pages-8-19")
    _node(front_div, "head").text = "Title matter, preface, and contents"
    targets = {child["title"]: "peter-jones-1860-component-" + str(child["ordinal"]) for child in source["children"]}
    accounting = {"front": _map_pages(front_div, [(item["number"], item["text"]) for item in source["front"]], targets), "children": []}
    body = _node(text, "body")
    for child in source["children"]:
        div = _node(body, "div", type="source-component", n=str(child["ordinal"]))
        div.set(XML_ID, "peter-jones-1860-component-" + str(child["ordinal"]))
        div.set("corresp", child["title"])
        _node(div, "head").text = child["heading"]
        range_pages = [(n, source["leaf_text"][n]) for n in range(child["start"], child["end"] + 1)]
        result = _map_pages(div, range_pages, targets)
        accounting["children"].append({"ordinal": child["ordinal"], "revision_id": child["revision"], "path": child["path"], "sha256": child["sha256"], "start": child["start"], "end": child["end"], **result})
    xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    account = {"contract": "ocd-peter-jones-1860-source-accounting-v2", "root_export_sha256": source["root_export_sha256"], "root_paratext_pages": 12, "linked_child_count": 15, "page_leaf_count": 425, "blank_page": 20, "outer_disposition_sha256": _sha(_authority(manifest, "outer-disposition")), "tei_sha256": _sha(xml), **accounting}
    policy = json.loads(_authority(manifest, "policy"))
    return {"content.tei.xml": xml, "source-accountability.json": _json(account), "README.source.md": _authority(manifest, "readme"), "provenance.json": _json(policy["provenance"]), "unresolved.jsonl": b"".join(_json(item) for item in policy["unresolved"])}


_convert.converter_id = "ocd-peter-jones-1860-wikisource-to-tei-v2"
_convert.converter_version = "2"
_convert.implementation_path = Path(__file__).resolve()





