"""Reconstruct the complete current Wikisource electronic witness of The Church."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.etree import ElementTree as ET

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest

T = "{http://www.tei-c.org/ns/1.0}"
X = "{http://www.w3.org/XML/1998/namespace}"
MW = "{http://www.mediawiki.org/xml/export-0.11/}"
CONVERTER_ID = "ocd-jan-hus-complete-wikisource-transcription"
CONVERTER_VERSION = "1"

_IGNORED_CLASSES = {
    "__nop", "mw-cite-backlink", "mw-empty-elt", "ws-noexport", "wst-dhr",
    "wst-header-back-arrow", "wst-header-forward-arrow",
}
_BLOCKS = {T + x for x in ("ab", "div", "head", "list", "p", "table")}


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _classes(node) -> set[str]:
    return set((node.get("class") or "").split())


def _title_id(record: dict[str, object]) -> tuple[str, str, str | None]:
    title = str(record["title"])
    if title == "De Ecclesia. The Church/Front matter":
        return "jan-hus-front-matter", "front-matter", None
    if title == "De Ecclesia. The Church/Introduction":
        return "jan-hus-introduction", "introduction", None
    if title == "De Ecclesia. The Church":
        return "jan-hus-table-of-contents", "table-of-contents", None
    match = re.fullmatch(r"De Ecclesia\. The Church/Chapter ([1-9][0-9]*)", title)
    if match:
        return f"jan-hus-chapter-{match.group(1)}", "chapter", match.group(1)
    match = re.fullmatch(r"Page:The Church, by John Huss\.pdf/([0-9]+)", title)
    if match and match.group(1) == "51":
        return "jan-hus-title-page", "title-page", None
    if match and int(match.group(1)) in {353, 354, 355, 356}:
        return f"jan-hus-index-page-{match.group(1)}", "printed-index-page", match.group(1)
    raise ValueError(f"unexpected source record title: {title}")


def _wiki_title_url(title: str) -> str:
    return "https://en.wikisource.org/wiki/" + quote(title.replace(" ", "_"), safe="/:().")


def _record_pages(record: dict[str, object], document) -> list[int]:
    if record["kind"] == "page":
        page_number = int(str(record["title"]).rsplit("/", 1)[1])
        return [page_number]
    wrappers = document.xpath(
        './/div[contains(concat(" ",normalize-space(@class)," ")," prp-pages-output ")]'
    )
    main = [wrapper for wrapper in wrappers if not wrapper.xpath(
        './/ol[contains(concat(" ",normalize-space(@class)," ")," mw-references ")]'
    )]
    return [
        int(node.get("data-page-index"))
        for wrapper in main
        for node in wrapper.iter()
        if node.get("data-page-index")
    ]


def _note_key(section_id: str, note_id: str) -> str:
    suffix = note_id.removeprefix("cite_note-")
    suffix = re.sub(r"[^A-Za-z0-9.-]+", "-", suffix).strip("-")
    if not suffix:
        raise ValueError("empty Wikisource footnote identifier")
    return f"{section_id}-note-{suffix}"


def _notes(document, section_id: str) -> tuple[dict[str, str], list[tuple[object, str, str]]]:
    targets: dict[str, str] = {}
    rows = []
    for note in document.xpath('.//li[starts-with(@id,"cite_note-")]'):
        source_id = note.get("id") or ""
        target_id = _note_key(section_id, source_id)
        if source_id in targets or target_id in {row[1] for row in rows}:
            raise ValueError("duplicate section-scoped footnote identity")
        targets[source_id] = target_id
        match = re.search(r"-([0-9]+)$", source_id)
        rows.append((note, target_id, match.group(1) if match else ""))
    return targets, rows


def _append_text(parent, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _copy_node(source, parent, *, section_id: str, note_targets: dict[str, str], section_ids: dict[str, str], profile: dict[str, object]) -> None:
    if not isinstance(source.tag, str):
        _append_text(parent, source.tail)
        return
    classes = _classes(source)
    if source.tag in {"style", "link", "meta", "script"} or classes & _IGNORED_CLASSES:
        _append_text(parent, source.tail)
        return
    if "mw-references" in classes or "mw-references-wrap" in classes:
        _append_text(parent, source.tail)
        return
    if source.get("data-page-index") is not None:
        page = etree.SubElement(parent, T + "pb", n=source.get("data-page-index"))
        page_title = source.get("data-page-name")
        if page_title:
            page.set("facs", _wiki_title_url(page_title.replace("_", " ")))
        page.tail = source.tail
        return

    tag = source.tag
    if tag in {"div", "section"}:
        _append_text(parent, source.text)
        for child in source:
            _copy_node(child, parent, section_id=section_id, note_targets=note_targets, section_ids=section_ids, profile=profile)
        _append_text(parent, source.tail)
        return
    if tag == "p" and parent.tag in {T + "p", T + "seg", T + "hi", T + "ref"}:
        node = etree.SubElement(parent, T + "seg", type="nested-source-paragraph")
        node.text = source.text
        for child in source:
            _copy_node(child, node, section_id=section_id, note_targets=note_targets, section_ids=section_ids, profile=profile)
        node.tail = source.tail
        return

    if tag == "a" and source.get("href", "").startswith("#cite_note-"):
        href = source.get("href", "")[1:]
        if href not in note_targets:
            raise ValueError(f"footnote reference has no retained note: {href}")
        ref = etree.SubElement(parent, T + "ref", target="#" + note_targets[href], type="footnote-marker")
        ref.text = "".join(source.itertext())
        ref.tail = source.tail
        return
    if tag == "sup" and "mw-ref" in classes:
        anchors = source.xpath('.//a[starts-with(@href,"#cite_note-")]')
        if len(anchors) != 1:
            raise ValueError("footnote marker must bind exactly one source note")
        href = anchors[0].get("href", "")[1:]
        if href not in note_targets:
            raise ValueError(f"footnote marker has no retained note: {href}")
        ref = etree.SubElement(parent, T + "ref", target="#" + note_targets[href], type="footnote-marker")
        ref.text = "".join(source.itertext())
        ref.tail = source.tail
        return
    if tag in {"tbody", "thead", "tfoot"}:
        _append_text(parent, source.text)
        for child in source:
            _copy_node(child, parent, section_id=section_id, note_targets=note_targets, section_ids=section_ids, profile=profile)
        _append_text(parent, source.tail)
        return

    mapping = {
        "a": "ref", "b": "hi", "blockquote": "quote", "br": "lb",
        "em": "hi", "figcaption": "figDesc", "figure": "figure", "h1": "head",
        "h2": "head", "h3": "head", "h4": "head", "h5": "head", "h6": "head",
        "hr": "milestone", "i": "hi", "img": "graphic", "li": "item", "ol": "list",
        "p": "p", "small": "hi", "span": "seg", "strong": "hi", "sub": "hi",
        "sup": "hi", "table": "table", "td": "cell", "th": "cell", "tr": "row",
        "ul": "list",
    }
    if tag not in mapping:
        raise ValueError(f"unmapped Wikisource HTML element: {tag}")
    if tag == "a" and any(child.tag == "img" for child in source):
        _append_text(parent, source.text)
        for child in source:
            _copy_node(child, parent, section_id=section_id, note_targets=note_targets, section_ids=section_ids, profile=profile)
        _append_text(parent, source.tail)
        return

    output_tag = mapping[tag]
    if tag == "img":
        src = source.get("src", "")
        graphics = profile["graphics"]
        match = next((entry for filename, entry in graphics.items() if filename in unquote(src)), None)
        if match is None:
            raise ValueError("unrecognized source image")
        node = etree.SubElement(parent, T + "graphic", url=match["url"])
        if source.get("alt"):
            node.set("n", source.get("alt"))
        node.tail = source.tail
        return

    node = etree.SubElement(parent, T + output_tag)
    if output_tag == "div":
        node.set("type", "source-layout")
    elif output_tag == "list":
        node.set("type", "ordered" if tag == "ol" else "unordered")
    elif output_tag == "item" and source.get("value"):
        node.set("n", source.get("value"))
    elif output_tag == "cell":
        if tag == "th":
            node.set("role", "label")
        for src_name, dst_name in (("colspan", "cols"), ("rowspan", "rows")):
            if source.get(src_name):
                node.set(dst_name, source.get(src_name))
    elif output_tag == "hi":
        rendition = "italic" if tag in {"i", "em"} else "bold" if tag in {"b", "strong"} else "source-style"
        details = sorted(classes)
        if details:
            rendition += " " + " ".join(details)
        node.set("rend", rendition)
    elif output_tag == "seg" and classes:
        node.set("rend", "source-class " + " ".join(sorted(classes)))
    elif output_tag == "ref":
        href = source.get("href")
        if not href:
            raise ValueError("source link has no href")
        absolute = urljoin(_wiki_title_url(str(profile["render_base_title"])), href)
        parsed = urlsplit(absolute)
        path = unquote(parsed.path.removeprefix("/wiki/")).replace("_", " ")
        if path in section_ids and not parsed.fragment:
            node.set("target", "#" + section_ids[path])
        elif parsed.scheme in {"http", "https"}:
            node.set("target", absolute)
        else:
            raise ValueError("source reference target is not an absolute Wikisource or HTTP URI")
    elif output_tag == "milestone":
        node.set("unit", "source-rule")
    if source.get("lang"):
        node.set(X + "lang", source.get("lang"))
    node.text = source.text
    for child in source:
        _copy_node(child, node, section_id=section_id, note_targets=note_targets, section_ids=section_ids, profile=profile)
    node.tail = source.tail


def _blockify(parent) -> None:
    """Wrap inline runs directly under divs so the output remains P5-valid."""
    for node in list(parent.iter(T + "div")):
        if node.getparent() is None:
            continue
        children = list(node)
        leading = node.text
        if not (leading and leading.strip()) and all(child.tag in _BLOCKS for child in children):
            continue
        node.text = None
        for child in children:
            node.remove(child)
        run = None

        def append_inline_text(value: str | None) -> None:
            nonlocal run
            if value is None:
                return
            if run is None:
                run = etree.SubElement(node, T + "ab")
            _append_text(run, value)

        append_inline_text(leading)
        for child in children:
            tail = child.tail
            child.tail = None
            if child.tag in _BLOCKS:
                node.append(child)
                run = None
            else:
                if run is None:
                    run = etree.SubElement(node, T + "ab")
                run.append(child)
            append_inline_text(tail)


def _page_quality(manifest: SourceManifest) -> tuple[dict[str, dict[str, object]], dict[int, int]]:
    root = ET.fromstring(manifest.authority_path("page-records-export").read_bytes())
    rows: dict[str, dict[str, object]] = {}
    counts: dict[int, int] = {}
    for page in root.findall(MW + "page"):
        title = page.findtext(MW + "title") or ""
        revision = page.find(MW + "revision")
        if revision is None:
            raise ValueError(f"page record has no revision: {title}")
        revision_id = revision.findtext(MW + "id") or ""
        wikitext = revision.findtext(MW + "text") or ""
        match = re.search(r"pagequality\s+level=[\"']([0-4])[\"']", wikitext, re.IGNORECASE)
        if not match:
            match = re.search(r"\{\{\s*pagequality\s*\|\s*([0-4])", wikitext, re.IGNORECASE)
        if not match:
            raise ValueError(f"page quality is missing: {title}")
        quality = int(match.group(1))
        if title in rows:
            raise ValueError(f"duplicate page title: {title}")
        rows[title] = {
            "revision": revision_id,
            "quality": quality,
            "wikitext_sha256": _sha(wikitext.encode("utf-8")),
        }
        counts[quality] = counts.get(quality, 0) + 1
    return rows, counts


def _verify_authorities(manifest: SourceManifest, profile: dict[str, object], capture: dict[str, object]) -> dict[str, object]:
    scope_root = ET.fromstring(manifest.authority_path("scope-export").read_bytes())
    scope_rows = {}
    for page in scope_root.findall(MW + "page"):
        title = page.findtext(MW + "title") or ""
        revision = page.find(MW + "revision")
        if revision is None:
            raise ValueError(f"scope record has no revision: {title}")
        scope_rows[title] = revision.findtext(MW + "id") or ""
    if len(scope_rows) != profile["expected_scope_export_record_count"]:
        raise ValueError("complete Wikisource export record count differs")
    page_rows, quality_counts = _page_quality(manifest)
    if len(page_rows) != profile["expected_page_count"]:
        raise ValueError("complete scan-page revision ledger differs")
    ledger = {row["title"]: row for row in capture["page_record_ledger"]}
    if len(ledger) != len(capture["page_record_ledger"]) or set(ledger) != set(page_rows):
        raise ValueError("render capture and complete page ledger membership differs")
    for title, row in page_rows.items():
        captured = ledger[title]
        if captured["revision"] != row["revision"] or int(captured["quality"]) != row["quality"]:
            raise ValueError(f"page revision/quality differs from retained XML: {title}")
        if captured["wikitext_sha256"] != row["wikitext_sha256"]:
            raise ValueError(f"page wikitext digest differs from retained XML: {title}")
    quality_summary = {str(key): value for key, value in quality_counts.items()}
    if quality_summary != profile["expected_page_quality_counts"]:
        raise ValueError("scan page-quality counts differ")
    untranscribed = sorted(
        int(title.rsplit("/", 1)[1])
        for title, row in page_rows.items()
        if row["quality"] == 0
    )
    if untranscribed != profile["untranscribed_scan_positions"]:
        raise ValueError("untranscribed scan-position set differs")
    classification = profile["untranscribed_page_classification"]
    expected_page_revisions = {
        str(number): page_rows[f"Page:The Church, by John Huss.pdf/{number}"]["revision"]
        for number in untranscribed
    }
    if (
        classification["status"] != "without-text"
        or classification["page_revision_ids"] != expected_page_revisions
    ):
        raise ValueError("no-text page classification does not bind exact source revisions")
    render_rows = capture["records"]
    if len(render_rows) != profile["expected_render_record_count"]:
        raise ValueError("rendered source-record count differs")
    by_title = {row["title"]: row for row in render_rows}
    expected_order = profile["record_order"]
    if len(by_title) != len(render_rows) or list(expected_order) != list(dict.fromkeys(expected_order)) or set(by_title) != set(expected_order):
        raise ValueError("rendered source-record identities differ")
    for record in render_rows:
        if record["http_status"] != 200:
            raise ValueError(f"source render did not return 200: {record['title']}")
        raw_html = record["render_html"].encode("utf-8")
        if len(raw_html) != record["render_bytes"] or _sha(raw_html) != record["render_sha256"]:
            raise ValueError(f"source render digest/size differs: {record['title']}")
        if record["kind"] == "section":
            if scope_rows.get(record["title"]) != record["revision"]:
                raise ValueError(f"work-page revision differs from complete XML: {record['title']}")
        else:
            page_title = record["title"]
            if page_title not in page_rows or page_rows[page_title]["revision"] != record["revision"]:
                raise ValueError(f"direct page-render revision differs from page ledger: {page_title}")
        oldid = "oldid=" + str(record["revision"])
        if oldid not in record["final_url"]:
            raise ValueError(f"render URL is not pinned to its captured revision: {record['title']}")
    return {"page_rows": page_rows, "quality_counts": quality_counts, "render_rows": by_title, "scope_rows": scope_rows}


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    capture = json.loads(manifest.authority_path("rendered-text").read_bytes())
    authorities = _verify_authorities(manifest, profile, capture)
    section_ids = {
        title: _title_id(authorities["render_rows"][title])[0]
        for title in profile["record_order"]
    }
    root = etree.Element(T + "TEI", nsmap={None: T[1:-1]})
    root.set(X + "lang", "en")
    root.set(X + "id", "jan-hus-de-ecclesia-the-church")
    header = etree.SubElement(root, T + "teiHeader")
    file_desc = etree.SubElement(header, T + "fileDesc")
    title_stmt = etree.SubElement(file_desc, T + "titleStmt")
    etree.SubElement(title_stmt, T + "title").text = profile["title"]
    etree.SubElement(title_stmt, T + "author").text = profile["author"]
    resp = etree.SubElement(title_stmt, T + "respStmt")
    etree.SubElement(resp, T + "resp").text = "translator"
    etree.SubElement(resp, T + "name").text = profile["translator"]
    pub_stmt = etree.SubElement(file_desc, T + "publicationStmt")
    etree.SubElement(pub_stmt, T + "p").text = "Nonaccepted source-bound reconstruction candidate; publication is not authorized. See README.source.md."
    source_desc = etree.SubElement(file_desc, T + "sourceDesc")
    etree.SubElement(source_desc, T + "p").text = (
        "1915 New York edition of the English translation by David Schley Schaff, "
        "represented by the complete current electronic Wikisource transcription. "
        "See the retained source ledger and README.source.md."
    )
    body = etree.SubElement(etree.SubElement(root, T + "text"), T + "body")
    work = etree.SubElement(body, T + "div", type="complete-electronic-transcription")
    all_page_numbers: list[int] = []
    note_count = 0
    footnote_marker_count = 0

    for title in profile["record_order"]:
        record = authorities["render_rows"][title]
        document = html.fromstring(record["render_html"])
        section_id, section_type, number = _title_id(record)
        section = etree.SubElement(work, T + "div", type=section_type)
        section.set(X + "id", section_id)
        if number:
            section.set("n", number)
        note_targets, note_rows = _notes(document, section_id)
        if record["kind"] == "section":
            wrappers = document.xpath(
                './/div[contains(concat(" ",normalize-space(@class)," ")," prp-pages-output ")]'
            )
            main = [wrapper for wrapper in wrappers if not wrapper.xpath(
                './/ol[contains(concat(" ",normalize-space(@class)," ")," mw-references ")]'
            )]
            if not main:
                raise ValueError(f"section has no main page-transclusion content: {title}")
            for wrapper in main:
                for node in wrapper:
                    _copy_node(node, section, section_id=section_id, note_targets=note_targets, section_ids=section_ids, profile=profile)
            page_numbers = _record_pages(record, document)
        else:
            wrappers = document.xpath(
                './/div[contains(concat(" ",normalize-space(@class)," ")," pagetext ")]'
            )
            if len(wrappers) != 1:
                raise ValueError(f"direct page render must have one pagetext body: {title}")
            page_number = int(title.rsplit("/", 1)[1])
            page_title = title.replace(" ", "_")
            pb = etree.SubElement(section, T + "pb", n=str(page_number), facs=_wiki_title_url(title))
            for node in wrappers[0]:
                _copy_node(node, section, section_id=section_id, note_targets=note_targets, section_ids=section_ids, profile=profile)
            page_numbers = [page_number]
        if page_numbers != record["expected_page_numbers"]:
            raise ValueError(f"rendered page-position sequence differs: {title}")
        all_page_numbers.extend(page_numbers)
        for source_note, target_id, note_number in note_rows:
            note = etree.SubElement(section, T + "note", place="foot")
            note.set(X + "id", target_id)
            if note_number:
                note.set("n", note_number)
            note_text = source_note.xpath(
                './/span[contains(concat(" ",normalize-space(@class)," ")," mw-reference-text ")]'
            )
            if len(note_text) != 1:
                raise ValueError(f"Wikisource note must have one reference-text carrier: {source_note.get('id')}")
            _append_text(note, note_text[0].text)
            for child in note_text[0]:
                _copy_node(child, note, section_id=section_id, note_targets=note_targets, section_ids=section_ids, profile=profile)
        note_count += len(note_rows)
        footnote_marker_count += len(document.xpath('.//sup[contains(concat(" ",normalize-space(@class)," ")," mw-ref ")]'))

    if len(all_page_numbers) != profile["expected_transcribed_page_count"] or len(set(all_page_numbers)) != len(all_page_numbers):
        raise ValueError("transcribed page coverage is incomplete or duplicated")
    expected_transcribed = sorted(
        int(title.rsplit("/", 1)[1])
        for title, row in authorities["page_rows"].items()
        if row["quality"] in {3, 4}
    )
    if sorted(all_page_numbers) != expected_transcribed:
        raise ValueError("transcribed page positions do not equal quality-3/4 source pages")
    _blockify(body)
    raw_tei = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    unresolved = {
        "kind": "untranscribed-scan-positions",
        "pages": profile["untranscribed_scan_positions"],
        "reason": "The exact retained Wikisource page revisions classify these quality-0 positions as Without text; scan-image contents were not independently collated.",
        "effect": "No missing electronic text is demonstrated at these positions. The TEI represents the complete current Wikisource text, not a blind collation of all 360 scan images.",
    }
    account = {
        "contract": "ocd-wikisource-source-accountability-v1",
        "work_id": manifest.record["work_id"],
        "edition_id": manifest.record["edition_id"],
        "source_manifest_sha256": manifest.sha256,
        "profile_sha256": _sha(manifest.authority_path("profile").read_bytes()),
        "rendered_source_sha256": _sha(manifest.authority_path("rendered-text").read_bytes()),
        "source_record_count": len(authorities["render_rows"]),
        "source_page_count": len(authorities["page_rows"]),
        "page_quality_counts": {str(k): v for k, v in sorted(authorities["quality_counts"].items())},
        "transcribed_pages": sorted(all_page_numbers),
        "untranscribed_pages": profile["untranscribed_scan_positions"],
        "untranscribed_page_classification": profile["untranscribed_page_classification"],
        "section_order": profile["record_order"],
        "footnote_count": note_count,
        "footnote_marker_count": footnote_marker_count,
        "render_records": [
            {
                "kind": authorities["render_rows"][title]["kind"],
                "title": title,
                "revision": authorities["render_rows"][title]["revision"],
                "username": authorities["render_rows"][title]["username"],
                "render_sha256": authorities["render_rows"][title]["render_sha256"],
                "expected_page_numbers": authorities["render_rows"][title]["expected_page_numbers"],
            }
            for title in profile["record_order"]
        ],
        "candidate_sha256": _sha(raw_tei),
        "candidate_bytes": len(raw_tei),
        "limitations": [unresolved["effect"]],
    }
    return {
        "content.tei.xml": raw_tei,
        "source-accountability.json": _json(account),
        "README.source.md": manifest.authority_path("readme").read_bytes(),
        "provenance.json": manifest.authority_path("provenance").read_bytes(),
        "unresolved.jsonl": _json(unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
