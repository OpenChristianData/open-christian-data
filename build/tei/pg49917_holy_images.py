"""Work-local reconstruction of the three Holy Images parts and their notes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import SourceManifest


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
PART_IDS = (
    "part-i-nl-apologia-of-st-john-damascene-against-those-who-decry-holy-images",
    "part-ii",
    "part-iii-20",
)
SKIP_LAYOUT = {"colgroup", "col", "tbody"}
MAP = {
    "div": "div", "p": "p", "h2": "head", "h3": "head", "h4": "head",
    "span": "seg", "em": "hi", "a": "ref", "sup": "hi", "br": "lb",
    "table": "table", "tr": "row", "td": "cell", "blockquote": "quote",
    "ol": "list", "li": "item",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _node(parent: etree._Element, name: str, **attributes: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", **attributes)


def _append_text(parent: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(parent):
        child = parent[-1]
        child.tail = (child.tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _copy(source: etree._Element, parent: etree._Element) -> None:
    if not isinstance(source.tag, str):
        marker = _node(parent, "milestone", unit="source-html-comment")
        marker.set("n", _sha((source.text or "").encode("utf-8")))
        marker.tail = source.tail
        return
    tag = source.tag.lower()
    if tag not in MAP and tag not in SKIP_LAYOUT:
        raise ValueError(f"unmapped Holy Images source element: {tag}")
    if tag in {"colgroup", "col"}:
        if source.text and source.text.strip():
            raise ValueError(f"layout element {tag} contains source text")
        if tag == "colgroup":
            for child in source:
                if child.tag != "col" or (child.text and child.text.strip()) or (child.tail and child.tail.strip()):
                    raise ValueError("nonempty source colgroup")
        _append_text(parent, source.tail)
        return
    if tag == "tbody":
        _append_text(parent, source.text)
        for child in source:
            _copy(child, parent)
        _append_text(parent, source.tail)
        return
    if tag == "blockquote":
        lines = source.xpath(".//div[contains(concat(' ', normalize-space(@class), ' '), ' line ')]")
        if len(lines) != 4 or any(line.get("id") for line in lines):
            raise ValueError("unsupported Holy Images note quotation structure")
        quote = _node(parent, "quote")
        group = _node(quote, "lg")
        for source_line in lines:
            line = _node(group, "l")
            line.text = source_line.text
            for child in source_line:
                _copy(child, line)
            line.tail = source_line.tail
        quote.tail = source.tail
        return
    target = _node(parent, MAP[tag])
    if source.get("id"):
        target.set(XML_ID, source.get("id"))
    if source.get("class"):
        target.set("rend", "source-class:" + " ".join(source.get("class").split()))
    if source.get("style"):
        target.set("rend", " ".join(filter(None, (target.get("rend"), "source-style:" + source.get("style")))))
    if source.get("title"):
        target.set("n", source.get("title"))
    if tag == "a":
        if not source.get("href"):
            raise ValueError("source anchor lacks href")
        target.set("target", source.get("href"))
    if tag == "div":
        target.set("type", "source-html-div")
    if tag.startswith("h") and tag[1:].isdigit():
        target.set("type", tag)
    if tag == "sup":
        target.set("rend", "superscript")
    if tag == "em":
        target.set("rend", "emphasis")
    if tag == "ol":
        target.set("type", "ordered")
    if tag == "td" and "label" in (source.get("class") or "").split():
        target.set("role", "label")
    target.text = source.text
    after_nested_div = False
    flow: etree._Element | None = None
    for child in source:
        if tag == "div" and isinstance(child.tag, str) and child.tag.lower() == "div":
            after_nested_div = True
            flow = None
            _copy(child, target)
        elif tag == "div" and after_nested_div:
            if flow is None:
                flow = _node(target, "div", type="source-flow")
            _copy(child, flow)
        else:
            _copy(child, target)
    target.tail = source.tail


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    if manifest.record.get("work_id") != "pg49917-holy-images":
        raise ValueError("wrong Holy Images work identity")
    source_path = resolve_repo_path(manifest.repository_root, "raw/gutenberg/49917/html/pg49917-images.html")
    if not source_path.samefile(manifest.authority_path("retained-html")):
        raise ValueError("Holy Images logical source route differs from manifest authority")
    source = source_path.read_bytes()
    profile = json.loads(manifest.authority_path("work-profile").read_bytes())
    if len(source) != 361466 or _sha(source) != "a517174360b8c13609b74c005965f1386e6a0cc0f97fd795d248ccb496944204":
        raise ValueError("retained Holy Images source changed")
    doc = html.fromstring(source)
    container = doc.get_element_by_id("st-john-damascene-on-holy-images")
    parts = list(container)[19:22]
    if tuple(item.get("id") for item in parts) != PART_IDS or len(container) != 26 or container[25].get("id") != "index":
        raise ValueError("Holy Images source boundary changed")
    note_ids = tuple(f"id{number}" for number in range(52, 81))
    notes = [doc.get_element_by_id(note_id) for note_id in note_ids]
    if any(item.tag != "table" or container[25] not in item.iterancestors() for item in notes):
        raise ValueError("Holy Images note source placement changed")
    refs = [item.get("href", "")[1:] for part in parts for item in part.xpath(".//a[starts-with(@href, '#')]")]
    if tuple(refs) != note_ids or profile.get("part_ids") != list(PART_IDS) or profile.get("note_ids") != list(note_ids):
        raise ValueError("Holy Images profile or note attachment changed")

    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set(XML_ID, "pg49917-holy-images-tei")
    root.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    header = _node(root, "teiHeader")
    description = _node(header, "fileDesc")
    titles = _node(description, "titleStmt")
    _node(titles, "title").text = "St John Damascene on Holy Images"
    _node(titles, "author").text = "John of Damascus"
    responsibility = _node(titles, "respStmt")
    _node(responsibility, "resp").text = "Translator"
    _node(responsibility, "name").text = "Mary H. Allies"
    _node(_node(description, "publicationStmt"), "p").text = "Nonaccepted source reconstruction candidate; rights and publication are unassessed."
    _node(_node(description, "sourceDesc"), "p").text = (
        "Project Gutenberg eBook 49917, extracted HTML SHA-256 " + _sha(source)
        + "; source edition: London, Thomas Baker, 1898."
    )
    text = _node(root, "text")
    body = _node(text, "body")
    work = _node(body, "div", type="work")
    work.set(XML_ID, "st-john-damascene-on-holy-images")
    for part in parts:
        _copy(part, work)
    back = _node(text, "back")
    note_div = _node(back, "div", type="source-footnotes")
    note_div.set(XML_ID, "pg49917-holy-images-source-footnotes")
    for note in notes:
        _copy(note, note_div)
    tei = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    accounting = {
        "contract": "ocd-pg49917-holy-images-source-accountability-v1",
        "work_id": "pg49917-holy-images",
        "source_sha256": _sha(source),
        "source_scope": {"container_id": container.get("id"), "text_child_start": 19, "text_child_end_exclusive": 22, "part_ids": list(PART_IDS)},
        "notes": {"source_parent_id": "index", "source_parent_child": 25, "ids": list(note_ids), "count": len(note_ids), "forward_reference_count": len(refs), "return_reference_count": sum(len(note.xpath(".//a[starts-with(@href, '#')]") ) for note in notes)},
        "source_feature_profile_sha256": _sha(manifest.authority_path("work-profile").read_bytes()),
        "intentional_dispositions": ["HTML head and out-of-work body remain retained in the complete source HTML", "note colgroup/col and tbody layout wrappers are omitted while note rows and cells remain", "one quoted four-line verse uses TEI quote/lg/l instead of presentation-only HTML div nesting", "source paragraphs after nested divisions use typed source-flow div wrappers for P5 placement", "source HTML comments are represented by typed digest milestones"],
        "candidate_tei_sha256": _sha(tei),
    }
    provenance = {
        "contract": "ocd-pg49917-holy-images-provenance-v1",
        "status": "nonaccepted",
        "work_id": "pg49917-holy-images",
        "edition_id": "pg49917-holy-images-pg49917-edition",
        "acquisition_id": "pg49917-holy-images-pg49917-acquisition",
        "source_sha256": _sha(source),
        "source_manifest_sha256": manifest.sha256,
        "rights": "Project Gutenberg states Public domain in the USA; OCD rights review is open.",
    }
    unresolved = [
        {"id": "visual-review", "status": "open"},
        {"id": "rights-review", "status": "open"},
        {"id": "acceptance-install", "status": "open"},
        {"id": "public-projection", "status": "open"},
    ]
    return {
        "content.tei.xml": tei,
        "source-accountability.json": _json(accounting),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(row) for row in unresolved),
        "README.source.md": manifest.authority_path("source-credit").read_bytes(),
    }


_convert.converter_id = "ocd-pg49917-holy-images-three-parts-and-index-notes"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
