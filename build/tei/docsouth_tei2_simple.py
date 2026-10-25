"""Convert two source-bound, single-text DocSouth TEI.2 witnesses to P5."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "plans/2026-09-22-source-preflight/docsouth-tei2-exact-source-shapes-20260927.json"
INVENTORY_SHA = "90f085ef14460c3a3d0351781c077502bf845e93dd2934a6afa344655d48341b"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
CONTRACT = "ocd-docsouth-tei2-simple-p5-v1"
SELECTIONS = {
    "john-jea-life-history-unparalleled-sufferings",
    "major-james-wilkerson-history-travels-labors",
}
BODY_TAGS = {
    "abbr", "body", "closer", "corr", "div1", "head", "hi", "item", "l", "lb", "lg",
    "list", "p", "pb", "q", "sic", "signed", "trailer",
}
FRONT_TAGS = {
    "date", "div1", "docAuthor", "docDate", "docImprint", "docTitle", "epigraph",
    "front", "head", "hi", "l", "lb", "lg", "opener", "p", "pb", "pubPlace",
    "publisher", "salute", "titlePage", "titlePart",
}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _one(parent: etree._Element, path: str) -> etree._Element:
    found = parent.findall(path)
    if len(found) != 1:
        raise ValueError(f"DocSouth single source header field required: {path}")
    return found[0]


def _text(node: etree._Element) -> str:
    return "".join(node.itertext())


def _element(parent: etree._Element, name: str, text: str | None = None, **attributes: str) -> etree._Element:
    node = etree.SubElement(parent, TEI + name, **attributes)
    node.text = text
    return node


def _convert_body(node: etree._Element) -> etree._Element:
    """Preserve source body order, text, tails, and all source readings."""
    name = node.tag
    if name not in BODY_TAGS | FRONT_TAGS:
        raise ValueError(f"DocSouth simple cohort has unsupported source element: {name}")
    if name in {"sic", "corr"} and ("corr" if name == "sic" else "sic") in node.attrib:
        if len(node) or set(node.attrib) != {"corr" if name == "sic" else "sic"}:
            raise ValueError("DocSouth source correction shape changed")
        result = etree.Element(TEI + "seg", type="source-" + name)
        result.text = node.text
        alternate = _element(result, "note", node.get("corr" if name == "sic" else "sic"),
                             type="source-correction" if name == "sic" else "source-sic-reading")
        if not alternate.text:
            raise ValueError("DocSouth source correction is empty")
        result.tail = node.tail
        return result
    mapping = {
        "div1": "div", "titlePage": "div", "docTitle": "head", "titlePart": "seg",
        "docAuthor": "p", "docImprint": "div", "docDate": "p",
    }
    target = mapping.get(name, name)
    if name == "q" and node.get("type") == "verse":
        target = "quote"
    if name in {"publisher", "pubPlace"} and node.getparent().tag == "docImprint":
        target = "p"
    result = etree.Element(TEI + target)
    for key, value in node.attrib.items():
        if name == "q" and key == "direct":
            if value != "unspecified":
                raise ValueError("DocSouth source quote directness is no longer unspecified")
            continue
        if name == "titlePart" and key == "type":
            key = "subtype"
        elif key == "id":
            key = XML + "id"
        elif key == "lang":
            key = XML + "lang"
        elif name == "note" and key == "anchored" and value == "yes":
            value = "true"
        result.set(key, value)
    if name == "titlePage":
        result.set("type", "source-title-page")
    elif name == "docImprint":
        result.set("type", "source-imprint")
    elif name == "titlePart":
        result.set("type", "source-title-part")
    elif name == "div1":
        result.set("subtype", "source-div1")
    result.text = node.text
    result.tail = node.tail
    for child in node:
        if not isinstance(child.tag, str):
            raise ValueError("DocSouth simple source contains unsupported comment or instruction")
        result.append(_convert_body(child))
    return result


def _header(source: etree._Element, work: dict) -> etree._Element:
    original = _one(source, "teiHeader")
    original_file = _one(original, "fileDesc")
    header = etree.Element(TEI + "teiHeader")
    file_desc = _element(header, "fileDesc")
    title_stmt = _element(file_desc, "titleStmt")
    source_title = _one(original_file, "titleStmt/title")
    _element(title_stmt, "title", _text(source_title))
    author = original_file.find("titleStmt/author")
    if author is not None:
        _element(title_stmt, "author", _text(author))
    for source_resp in original_file.findall("titleStmt/respStmt"):
        resp = _element(title_stmt, "respStmt")
        for child in source_resp:
            if child.tag not in {"resp", "name"}:
                raise ValueError("DocSouth source credit role changed")
            _element(resp, child.tag, _text(child))
    edition_stmt = original_file.find("editionStmt")
    if edition_stmt is not None:
        edition = _one(edition_stmt, "edition")
        target = _element(_element(file_desc, "editionStmt"), "edition", edition.text)
        for child in edition:
            if child.tag != "date":
                raise ValueError("DocSouth source edition content changed")
            target.append(_element(etree.Element(TEI + "tmp"), "date", _text(child)))
            target[-1].tail = child.tail
    extent = original_file.find("extent")
    if extent is not None:
        _element(file_desc, "extent", _text(extent))
    publication = _element(file_desc, "publicationStmt")
    original_publication = _one(original_file, "publicationStmt")
    for name in ("publisher", "pubPlace", "date"):
        item = original_publication.find(name)
        if item is not None:
            _element(publication, name, _text(item))
    availability = _one(original_publication, "availability")
    target_availability = _element(publication, "availability", status=availability.get("status", "unknown"))
    for paragraph in availability.findall("p"):
        target_paragraph = _element(target_availability, "p", paragraph.text)
        for child in paragraph:
            if child.tag != "a" or not child.get("href"):
                raise ValueError("DocSouth electronic availability link changed")
            link = _element(target_paragraph, "ref", _text(child), target=child.get("href"))
            link.tail = child.tail
    notes = _element(file_desc, "notesStmt")
    funder = original_file.find("titleStmt/funder")
    if funder is not None:
        _element(notes, "note", _text(funder), type="source-funder")
    classification = original.find("encodingDesc/classDecl")
    if classification is not None:
        _element(notes, "note", _text(classification), type="source-classification")
    header_type = original.get("type", "")
    header_status = original.get("status", "")
    _element(notes, "note", f"Source TEI.2 header type: {header_type}; status: {header_status}.",
             type="source-header-attributes")
    source_desc = _element(file_desc, "sourceDesc")
    original_bibl = _one(original_file, "sourceDesc/biblFull")
    bibl = _element(source_desc, "biblFull")
    bibl_title = _element(bibl, "titleStmt")
    for name in ("title", "author"):
        item = original_bibl.find("titleStmt/" + name)
        if item is not None:
            attrs = {"type": "title-page"} if name == "title" and item.get("type") == "title page" else {}
            _element(bibl_title, name, _text(item), **attrs)
    print_extent = original_bibl.find("extent")
    if print_extent is not None:
        _element(bibl, "extent", _text(print_extent))
    print_publication = _one(original_bibl, "publicationStmt")
    target_publication = _element(bibl, "publicationStmt")
    for name in ("publisher", "pubPlace", "date"):
        item = print_publication.find(name)
        if item is not None:
            _element(target_publication, name, _text(item))
    print_note = original_bibl.find("notesStmt/note")
    if print_note is not None:
        _element(_element(bibl, "notesStmt"), "note", _text(print_note))
    original_encoding = original.find("encodingDesc")
    if original_encoding is not None:
        encoding = _element(header, "encodingDesc")
        for name in ("projectDesc", "editorialDecl"):
            item = original_encoding.find(name)
            if item is not None:
                target = _element(encoding, name)
                for paragraph in item.findall("p"):
                    _element(target, "p", _text(paragraph))
    original_profile = original.find("profileDesc")
    if original_profile is not None:
        profile = _element(header, "profileDesc")
        languages = original_profile.findall("langUsage/language")
        if languages:
            usage = _element(profile, "langUsage")
            for language in languages:
                if not language.get("id"):
                    raise ValueError("DocSouth source language identifier missing")
                _element(usage, "language", _text(language), ident=language.get("id"))
        keyword_items = original_profile.findall("textClass/keywords/list/item")
        if keyword_items:
            keywords = _element(_element(profile, "textClass"), "keywords")
            for item in keyword_items:
                _element(keywords, "term", _text(item))
    revision = original.find("revisionDesc")
    if revision is not None:
        target = _element(header, "revisionDesc")
        for change in revision.findall("change"):
            _element(target, "change", _text(change))
    return header


def convert(work_id: str) -> tuple[bytes, dict]:
    if work_id not in SELECTIONS or _sha(_io_path(INVENTORY).read_bytes()) != INVENTORY_SHA:
        raise ValueError("DocSouth simple selection or shape inventory changed")
    inventory = _json(INVENTORY)
    matches = [item for item in inventory["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise ValueError("DocSouth simple work absent or repeated in exact inventory")
    entry = matches[0]
    if (entry["accepted_master_present"] or entry["body_nested_text_count"]
            or entry["element_counts"].get("figure", 0) or entry["element_counts"].get("table", 0)
            or entry["entity_declarations"] or entry["back_count"]):
        raise ValueError("DocSouth simple source shape now requires a different mapping")
    source_bytes = _io_path(ROOT / entry["source_path"]).read_bytes()
    if _sha(source_bytes) != entry["source_sha256"] or len(source_bytes) != entry["source_bytes"]:
        raise ValueError("DocSouth retained TEI.2 source changed")
    work_bytes = _io_path(ROOT / entry["work_path"]).read_bytes()
    if _sha(work_bytes) != entry["work_sha256"]:
        raise ValueError("DocSouth current work sidecar changed")
    work = json.loads(work_bytes)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    if source.tag != "TEI.2" or source.xpath("//comment()|//processing-instruction()"):
        raise ValueError("DocSouth simple source root or nontext nodes changed")
    text = _one(source, "text")
    if [child.tag for child in text] != ["front", "body"]:
        raise ValueError("DocSouth simple source text envelope changed")
    front, body = text
    if ({node.tag for node in front.iter() if isinstance(node.tag, str)} - FRONT_TAGS
            or {node.tag for node in body.iter() if isinstance(node.tag, str)} - BODY_TAGS):
        raise ValueError("DocSouth simple source vocabulary changed")
    result = etree.Element(TEI + "TEI", nsmap={None: TEI[1:-1]})
    result.set(XML + "id", f"ocd-{work_id}-docsouth-tei2-v1")
    result.append(_header(source, work))
    target_text = _element(result, "text", **{XML + "lang": "en"})
    target_text.append(_convert_body(front))
    target_text.append(_convert_body(body))
    content = etree.tostring(result, encoding="UTF-8", xml_declaration=True)
    report = dict(contract=CONTRACT, work_id=work_id, source_path=entry["source_path"],
                  source_sha256=entry["source_sha256"], source_bytes=len(source_bytes),
                  source_doctype=entry["doctype"], candidate_sha256=_sha(content),
                  candidate_bytes=len(content), source_rights_text_sha256=entry["rights_text_sha256"],
                  source_body_text_sha256=entry["body_text_sha256"],
                  mapping="source body/front structure and original reading preserved; legacy alternatives become typed notes; print/electronic header wording retained in P5-compatible fields")
    return content, report
