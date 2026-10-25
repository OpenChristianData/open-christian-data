"""Convert Moore's illustrated DocSouth TEI.2 witness to source-bound P5."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urljoin
from urllib.parse import quote

from lxml import etree

from build.tei import docsouth_tei2_simple as base
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = base.INVENTORY
INVENTORY_SHA = base.INVENTORY_SHA
TEI = base.TEI
XML = base.XML
CONTRACT = "ocd-docsouth-tei2-illustrated-moore-p5-v1"
SELECTIONS = {
    "joanna-p-moore-in-christs-stead",
}
TAGS = base.BODY_TAGS | base.FRONT_TAGS | {
    "bibl", "body", "byline", "closer", "dateline", "div", "div2", "div3", "emph", "epigraph", "floatingText",
    "name", "note", "ref", "salute", "signed", "text", "figure", "foreign", "argument", "docEdition", "milestone",
}
_FIGURE_URLS: dict[str, str] = {}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _header(source: etree._Element, work: dict) -> etree._Element:
    """Keep all attested electronic authors, print titles/authors, and notes."""
    copy = deepcopy(source)
    source_languages = source.findall("teiHeader/profileDesc/langUsage/language")
    copied_languages = copy.findall("teiHeader/profileDesc/langUsage/language")
    if (len(source_languages) != 2 or len(copied_languages) != 2
            or source_languages[1].attrib or len(source_languages[1])
            or (source_languages[1].text or "").strip()):
        raise ValueError("DocSouth Moore empty language element differs")
    copied_languages[1].getparent().remove(copied_languages[1])
    result = base._header(copy, work)
    source_notes = base._one(result, TEI + "fileDesc/" + TEI + "notesStmt")
    empty_language = etree.SubElement(source_notes, TEI + "note", type="source-empty-language-element")
    empty_language.text = etree.tostring(source_languages[1], encoding="unicode", with_tail=False)
    original_electronic_authors = source.findall("teiHeader/fileDesc/titleStmt/author")
    target_title_stmt = base._one(result, TEI + "fileDesc/" + TEI + "titleStmt")
    target_electronic_authors = target_title_stmt.findall(TEI + "author")
    if len(target_electronic_authors) != 1 or not original_electronic_authors:
        raise ValueError("DocSouth electronic author cardinality differs")
    for index, extra in enumerate(original_electronic_authors[1:], 1):
        if extra.attrib:
            raise ValueError("DocSouth electronic author attributes differ")
        author = etree.Element(TEI + "author")
        author.text = base._text(extra)
        target_title_stmt.insert(target_title_stmt.index(target_electronic_authors[0]) + index, author)
    source_titles = source.findall("teiHeader/fileDesc/sourceDesc/biblFull/titleStmt/title")
    target_titles = result.findall(TEI + "fileDesc/" + TEI + "sourceDesc/" + TEI + "biblFull/" + TEI + "titleStmt/" + TEI + "title")
    if len(target_titles) != 1 or not source_titles:
        raise ValueError("DocSouth print title structure differs")
    parent = target_titles[0].getparent()
    if set(source_titles[0].attrib) != {"type"}:
        raise ValueError("DocSouth print title attributes differ")
    target_titles[0].set("type", "source-" + quote(source_titles[0].get("type"), safe=""))
    for index, extra in enumerate(source_titles[1:], 1):
        if set(extra.attrib) != {"type"}:
            raise ValueError("DocSouth extra print title attributes differ")
        added = etree.Element(TEI + "title", type="source-" + quote(extra.get("type"), safe=""))
        added.text = base._text(extra)
        parent.insert(index, added)
    original_print_authors = source.findall("teiHeader/fileDesc/sourceDesc/biblFull/titleStmt/author")
    target_print_authors = parent.findall(TEI + "author")
    if len(target_print_authors) != 1 or not original_print_authors:
        raise ValueError("DocSouth print author cardinality differs")
    for index, extra in enumerate(original_print_authors[1:], 1):
        if extra.attrib:
            raise ValueError("DocSouth print author attributes differ")
        author = etree.Element(TEI + "author")
        author.text = base._text(extra)
        parent.insert(parent.index(target_print_authors[0]) + index, author)
    source_notes = source.findall("teiHeader/fileDesc/notesStmt/note")
    if len(source_notes) > 1:
        raise ValueError("DocSouth electronic source note cardinality differs")
    if source_notes:
        if source_notes[0].attrib != {"anchored": "yes"}:
            raise ValueError("DocSouth electronic source note attributes differ")
        notes = base._one(result, TEI + "fileDesc/" + TEI + "notesStmt")
        retained = etree.SubElement(notes, TEI + "note", type="source-call-number", rend="source-anchored-yes")
        retained.text = base._text(source_notes[0])
    authority = base._one(source, "teiHeader/fileDesc/sourceDesc/biblFull/publicationStmt/authority")
    if authority.attrib or len(authority) or base._text(authority).strip():
        raise ValueError("DocSouth empty print authority field differs")
    electronic_title = base._one(source, "teiHeader/fileDesc/titleStmt/title")
    if (len(electronic_title) != 1 or electronic_title[0].tag != "emph"
            or electronic_title[0].attrib or len(electronic_title[0])):
        raise ValueError("DocSouth electronic title emphasis differs")
    notes = base._one(result, TEI + "fileDesc/" + TEI + "notesStmt")
    markup = etree.SubElement(notes, TEI + "note", type="source-electronic-title-markup")
    markup.text = etree.tostring(electronic_title, encoding="unicode", with_tail=False)
    return result


def _convert_node(node: etree._Element) -> etree._Element:
    name = node.tag
    if name not in TAGS:
        raise ValueError(f"DocSouth illustrated source element differs: {name}")
    if name == "milestone":
        if node.attrib != {"n": "N=*****", "unit": "typography"} or node.text or len(node):
            raise ValueError("DocSouth Moore typography milestone differs")
        result = etree.Element(TEI + "milestone", unit="separator", n=node.get("n"),
                               ana="source-unit-typography")
        result.tail = node.tail
        return result
    if name == "figure":
        entity = node.get("entity")
        if not entity or entity not in _FIGURE_URLS or set(node.attrib) != {"id", "entity"}:
            raise ValueError("DocSouth figure entity or attributes differ")
        result = etree.Element(TEI + "figure", attrib={XML + "id": node.get("id")})
        result.text, result.tail = node.text, node.tail
        etree.SubElement(result, TEI + "graphic", n=entity, url=_FIGURE_URLS[entity])
        for child in node:
            result.append(_convert_node(child))
        return result
    if name in {"sic", "corr"} and ("corr" if name == "sic" else "sic") in node.attrib:
        if len(node) or set(node.attrib) != {"corr" if name == "sic" else "sic"}:
            raise ValueError("DocSouth nested-quote correction shape differs")
        result = etree.Element(TEI + "seg", type="source-" + name)
        result.text = node.text
        alternate = etree.SubElement(result, TEI + "note",
                                     type="source-correction" if name == "sic" else "source-sic-reading")
        alternate.text = node.get("corr" if name == "sic" else "sic")
        if not alternate.text:
            raise ValueError("DocSouth nested-quote correction alternate empty")
        result.tail = node.tail
        return result
    if name in {"sic", "corr"}:
        if node.attrib:
            raise ValueError("DocSouth unpaired correction attributes differ")
        result = etree.Element(TEI + "seg", type="source-" + name)
        result.text, result.tail = node.text, node.tail
        for child in node:
            result.append(_convert_node(child))
        return result
    mapping = {
        "div1": "div", "div2": "div", "div3": "div", "div4": "div", "text": "floatingText",
        "titlePage": "div", "docTitle": "head", "titlePart": "seg", "byline": "head",
        "docAuthor": "p", "docImprint": "p", "docDate": "p", "docEdition": "p", "epigraph": "quote",
    }
    target = mapping.get(name, name)
    if name == "emph" and node.get("rend"):
        target = "hi"
    if name == "q" and node.get("type"):
        target = "quote"
    if name in {"publisher", "pubPlace"} and node.getparent().tag == "docImprint":
        target = "seg"
    if name == "docDate" and node.getparent().tag == "docImprint":
        target = "seg"
    if name == "byline" and node.getparent().tag == "lg":
        target = "l"
    if name == "byline" and node.getparent().tag == "titlePage":
        target = "p"
    if name == "docAuthor" and node.getparent().tag == "byline":
        target = "seg"
    if name == "epigraph" and node.getparent().tag == "lg":
        target = "lg"
    if name == "p" and node.getparent().tag == "epigraph" and node.getparent().getparent().tag == "lg":
        target = "l"
    result = etree.Element(TEI + target)
    for key, value in node.attrib.items():
        if name == "q" and key == "direct":
            if value != "unspecified":
                raise ValueError("DocSouth nested quote directness differs")
            continue
        if name == "ref" and key == "targOrder":
            if value != "U" or "subtype" in node.attrib:
                raise ValueError("DocSouth target ordering differs")
            key, value = "subtype", "source-targOrder-U"
        elif name == "ref" and key == "lang":
            if "rend" in node.attrib:
                raise ValueError("DocSouth source ref language/rendition collision")
            key, value = "rend", "source-lang-" + value
        elif name == "pb" and key == "rend" and value == " ":
            key, value = "rend", "source-single-space"
        elif name == "note" and key == "target":
            if not value or "type" in node.attrib:
                raise ValueError("DocSouth note target differs")
            key, value = "type", "source-target-" + value
        elif name == "note" and key == "anchored" and value == "yes":
            value = "true"
        elif name == "pb" and key == "ed":
            if "rend" in node.attrib:
                raise ValueError("DocSouth Moore page-break edition/rendition collision")
            key, value = "rend", "source-ed-" + value
        elif name == "titlePart" and key == "type":
            key = "subtype"
        elif key == "type" and any(character.isspace() for character in value):
            value = quote(value, safe="")
        elif key == "id":
            key = XML + "id"
        elif key == "lang":
            key = XML + "lang"
        result.set(key, value)
    if name == "titlePage":
        result.set("type", "source-title-page")
    elif name == "docImprint":
        result.set("rend", "source-imprint")
    elif name == "epigraph":
        result.set("rend", "source-epigraph")
    elif name == "docEdition":
        result.set("rend", "source-edition")
    elif name == "docAuthor" and target == "seg":
        result.set("rend", "source-doc-author")
    elif name == "titlePart":
        result.set("type", "source-title-part")
    elif name == "byline":
        result.set("rend" if target in {"l", "p"} else "type", "source-byline")
    elif name in {"div", "div1", "div2", "div3", "div4"}:
        result.set("subtype", "source-" + name)
    result.text, result.tail = node.text, node.tail
    for child in node:
        if not isinstance(child.tag, str):
            raise ValueError("DocSouth nested source contains nontext node")
        result.append(_convert_node(child))
    return result


def convert(work_id: str, *, selections: set[str] | None = None) -> tuple[bytes, dict]:
    selected = SELECTIONS if selections is None else selections
    if work_id not in selected or _sha(_io_path(INVENTORY).read_bytes()) != INVENTORY_SHA:
        raise ValueError("DocSouth illustrated selection or inventory differs")
    inventory = json.loads(_io_path(INVENTORY).read_bytes())
    entries = [item for item in inventory["works"] if item["work_id"] == work_id]
    if len(entries) != 1:
        raise ValueError("DocSouth illustrated work absent or repeated")
    entry = entries[0]
    if (entry["accepted_master_present"] or entry["element_counts"].get("figure", 0) != 34
            or entry["element_counts"].get("table", 0) or entry["back_count"]
            or entry["element_counts"].get("milestone", 0) != 1
            or entry["text_child_tags"] != ["front", "body"]):
        raise ValueError("DocSouth illustrated source shape differs")
    source_bytes = _io_path(ROOT / entry["source_path"]).read_bytes()
    work_bytes = _io_path(ROOT / entry["work_path"]).read_bytes()
    if (_sha(source_bytes) != entry["source_sha256"] or len(source_bytes) != entry["source_bytes"]
            or _sha(work_bytes) != entry["work_sha256"]):
        raise ValueError("DocSouth illustrated retained source or current work differs")
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True,
                                                            remove_comments=False, huge_tree=True))
    if source.tag != "TEI.2" or source.xpath("//comment()|//processing-instruction()"):
        raise ValueError("DocSouth illustrated source envelope differs")
    text = base._one(source, "text")
    if [child.tag for child in text] != ["front", "body"]:
        raise ValueError("DocSouth illustrated text ownership differs")
    nested = text.findall(".//body//text")
    if len(nested) != entry["body_nested_text_count"] or any(
            n.getparent().tag != "q" or [c.tag for c in n] != ["body"] for n in nested):
        raise ValueError("DocSouth illustrated nested ownership differs")
    # The system identifiers are part of the retained source DTD, never guessed
    # from the figure id or image filename.
    declarations = {name: path for name, path in re.findall(
        rb'<!ENTITY\s+([A-Za-z][\w.-]*)\s+SYSTEM\s+["\']([^"\']+)["\']\s+NDATA\s+jpeg\s*>',
        source_bytes, re.I) for name, path in [(name.decode("ascii"), path.decode("ascii"))]}
    figures = source.findall(".//figure")
    if (len(figures) != entry["element_counts"]["figure"]
            or set(declarations) - {f.get("entity") for f in figures} != {"moorebk"}
            or {f.get("entity") for f in figures} - set(declarations)):
        raise ValueError("DocSouth source figure/DTD binding differs")
    receipt = json.loads(_io_path(ROOT / entry["acquisition_receipt_path"]).read_bytes())
    members = {m["entity"]: m for m in receipt["image_members"]}
    if set(members) != {f.get("entity") for f in figures} or receipt["member"]["sha256"] != entry["source_sha256"]:
        raise ValueError("DocSouth image receipt differs")
    global _FIGURE_URLS
    _FIGURE_URLS = {}
    for entity, member in members.items():
        system_path = declarations[entity]
        expected_url = urljoin(receipt["source_url"], system_path)
        raw = _io_path(ROOT / member["path"]).read_bytes()
        if (member["source_url"] != expected_url or member["sha256"] != _sha(raw)
                or member["bytes"] != len(raw) or not raw.startswith(b"\xff\xd8\xff") or not raw.endswith(b"\xff\xd9")):
            raise ValueError("DocSouth source-declared JPEG binding differs")
        _FIGURE_URLS[entity] = expected_url
    result = etree.Element(TEI + "TEI", nsmap={None: TEI[1:-1]})
    result.set(XML + "id", f"ocd-{work_id}-docsouth-tei2-v1")
    result.append(_header(source, json.loads(work_bytes)))
    target_text = base._element(result, "text", **{XML + "lang": "en"})
    for child in text:
        target_text.append(_convert_node(child))
    content = etree.tostring(result, encoding="UTF-8", xml_declaration=True)
    report = dict(contract=CONTRACT, work_id=work_id, source_path=entry["source_path"],
                  source_sha256=entry["source_sha256"], source_bytes=len(source_bytes),
                  source_doctype=entry["doctype"], source_nested_text_count=len(nested),
                  source_entity_declarations=len(declarations), source_rights_text_sha256=entry["rights_text_sha256"],
                  source_image_member_count=len(members),
                  source_body_text_sha256=entry["body_text_sha256"],
                  source_typography_milestone_count=1,
                  source_empty_print_authority=(source.find("teiHeader/fileDesc/sourceDesc/biblFull/publicationStmt/authority") is not None
                                                and not base._text(base._one(source, "teiHeader/fileDesc/sourceDesc/biblFull/publicationStmt/authority")).strip()),
                  source_image_sha256={k: members[k]["sha256"] for k in sorted(members)},
                  source_unreferenced_declared_image="moorebk",
                  candidate_sha256=_sha(content), candidate_bytes=len(content),
                  mapping="source-declared figures bind exact JPEGs by entity and official URL; quoted nested text becomes floatingText; all source readings retained")
    return content, report
