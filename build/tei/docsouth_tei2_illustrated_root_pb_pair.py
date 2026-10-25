"""Convert two illustrated DocSouth works with root page breaks and back matter."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from copy import deepcopy
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
CONTRACT = "ocd-docsouth-tei2-illustrated-root-pb-pair-p5-v1"
SELECTIONS = {
    "wharton-jackson-green-recollections-and-reflections",
    "william-h-robinson-from-log-cabin-to-pulpit",
}
TAGS = base.BODY_TAGS | base.FRONT_TAGS | {
    "back", "body", "byline", "closer", "dateline", "div2", "div3", "div4", "div5", "emph", "epigraph", "floatingText",
    "name", "note", "ref", "salute", "signed", "text", "figure", "foreign", "argument", "docEdition",
}
_FIGURE_URLS: dict[str, str] = {}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _header(source: etree._Element, work: dict) -> etree._Element:
    """Map the attested print bibl and mixed electronic title exactly."""
    copy = deepcopy(source)
    desc = base._one(copy, "teiHeader/fileDesc/sourceDesc")
    bibl = base._one(desc, "bibl")
    if [child.tag for child in bibl] != ["title", "author", "imprint"]:
        raise ValueError("DocSouth Lane/Arter print bibl shape differs")
    imprint = base._one(bibl, "imprint")
    if [child.tag for child in imprint] != ["pubPlace", "publisher", "date"]:
        raise ValueError("DocSouth Lane/Arter imprint shape differs")
    full = etree.Element("biblFull")
    title_stmt = etree.SubElement(full, "titleStmt")
    for child in list(bibl)[:2]:
        title_stmt.append(deepcopy(child))
    publication = etree.SubElement(full, "publicationStmt")
    for child in imprint:
        publication.append(deepcopy(child))
    desc.replace(bibl, full)
    result = base._header(copy, work)
    source_names = source.findall("teiHeader/fileDesc/titleStmt/respStmt/name")
    target_names = result.findall(TEI + "fileDesc/" + TEI + "titleStmt/" + TEI + "respStmt/" + TEI + "name")
    if len(source_names) != len(target_names):
        raise ValueError("DocSouth source responsibility count differs")
    for original, mapped in zip(source_names, target_names, strict=True):
        if set(original.attrib) not in (set(), {"id"}):
            raise ValueError("DocSouth source responsibility attributes differ")
        if original.get("id"):
            mapped.set("key", "source-id-" + original.get("id"))
    taxonomy = base._one(source, "teiHeader/encodingDesc/classDecl/taxonomy")
    classification = base._one(result, TEI + "fileDesc/" + TEI + "notesStmt/" + TEI + "note[@type='source-classification']")
    if taxonomy.attrib != {"id": "lcsh"}:
        raise ValueError("DocSouth source taxonomy identity differs")
    classification.set("n", taxonomy.get("id"))
    original_keywords = source.findall("teiHeader/profileDesc/textClass/keywords")
    mapped_keywords = result.findall(TEI + "profileDesc/" + TEI + "textClass/" + TEI + "keywords")
    if len(original_keywords) != len(mapped_keywords):
        raise ValueError("DocSouth source keyword classification differs")
    for original, mapped in zip(original_keywords, mapped_keywords, strict=True):
        if original.attrib not in ({}, {"scheme": "lcsh"}):
            raise ValueError("DocSouth source keyword scheme differs")
        if original.get("scheme"):
            mapped.set("scheme", original.get("scheme"))
    original_notes = source.findall("teiHeader/fileDesc/notesStmt/note")
    if len(original_notes) != 1 or original_notes[0].attrib != {"anchored": "yes"}:
        raise ValueError("DocSouth Lane/Arter electronic call-number note differs")
    target_notes = base._one(result, TEI + "fileDesc/" + TEI + "notesStmt")
    retained = etree.SubElement(target_notes, TEI + "note", type="source-call-number", rend="source-anchored-yes")
    retained.text = base._text(original_notes[0])
    source_title = base._one(source, "teiHeader/fileDesc/titleStmt/title")
    if any(child.tag != "emph" or len(child) or set(child.attrib) not in (set(), {"rend"})
           for child in source_title):
        raise ValueError("DocSouth electronic title emphasis shape differs")
    if len(source_title):
        markup = etree.SubElement(target_notes, TEI + "note", type="source-electronic-title-markup")
        markup.text = etree.tostring(source_title, encoding="unicode", with_tail=False)
    return result


def _convert_node(node: etree._Element) -> etree._Element:
    name = node.tag
    if name not in TAGS:
        raise ValueError(f"DocSouth illustrated source element differs: {name}")
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
        if set(node.attrib) != {"corr" if name == "sic" else "sic"}:
            raise ValueError("DocSouth correction shape differs")
        result = etree.Element(TEI + "seg", type="source-" + name)
        result.text, result.tail = node.text, node.tail
        for child in node:
            result.append(_convert_node(child))
        alternate = etree.SubElement(result, TEI + "note",
                                     type="source-correction" if name == "sic" else "source-sic-reading")
        alternate.text = node.get("corr" if name == "sic" else "sic")
        if not alternate.text:
            raise ValueError("DocSouth correction alternate empty")
        return result
    if name in {"sic", "corr"}:
        if node.attrib and (name != "sic" or set(node.attrib) != {"cert"}):
            raise ValueError("DocSouth unpaired correction attributes differ")
        result = etree.Element(TEI + "seg", type="source-" + name)
        if node.get("cert"):
            result.set("rend", "source-cert-" + quote(node.get("cert"), safe=""))
        result.text, result.tail = node.text, node.tail
        for child in node:
            result.append(_convert_node(child))
        return result
    mapping = {
        "div1": "div", "div2": "div", "div3": "div", "div4": "div", "div5": "div", "text": "floatingText",
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
    if name == "titlePart" and node.getparent().tag == "titlePage":
        target = "p"
    if name == "head" and node.getparent().tag in {"div1", "div2", "div3", "div4", "div5"} and any(
            earlier.tag not in {"pb", "head"} for earlier in node.itersiblings(preceding=True)):
        target = "p"
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
        elif name == "note" and key == "target":
            if not value:
                raise ValueError("DocSouth note target differs")
            key = "rend" if "type" in node.attrib else "type"
            value = "source-target-" + value
        elif name == "note" and key == "anchored" and value == "yes":
            value = "true"
        elif name == "titlePart" and key == "type":
            if target == "p":
                key, value = "rend", "source-title-part-" + value
            else:
                key = "subtype"
        elif name == "ref" and key == "lang":
            key, value = "rend", "source-lang-" + value
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
    elif name == "titlePart":
        if target != "p":
            result.set("type", "source-title-part")
    elif name == "byline":
        result.set("rend" if target in {"l", "p"} else "type", "source-byline")
    elif name == "head" and target == "p":
        result.set("rend", "source-late-head")
    elif name in {"div1", "div2", "div3", "div4", "div5"}:
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
    source_order = ({"wharton-jackson-green-recollections-and-reflections": ["front", "pb", "body", "pb", "back"],
                    "william-h-robinson-from-log-cabin-to-pulpit": ["front", "pb", "body", "back"]})[work_id]
    if (entry["accepted_master_present"] or not entry["element_counts"].get("figure", 0)
            or entry["element_counts"].get("table", 0) or entry["back_count"] != 1
            or entry["text_child_tags"] != source_order or entry["body_nested_text_count"] != 0):
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
    if [child.tag for child in text] != source_order:
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
    if len(figures) != entry["element_counts"]["figure"] or {f.get("entity") for f in figures} != set(declarations):
        raise ValueError("DocSouth source figure/DTD binding differs")
    receipt = json.loads(_io_path(ROOT / entry["acquisition_receipt_path"]).read_bytes())
    members = {m["entity"]: m for m in receipt["image_members"]}
    if set(members) != set(declarations) or receipt["member"]["sha256"] != entry["source_sha256"]:
        raise ValueError("DocSouth image receipt differs")
    global _FIGURE_URLS
    _FIGURE_URLS = {}
    for entity, system_path in declarations.items():
        member = members[entity]
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
    last_part: etree._Element | None = None
    for child in text:
        if child.tag == "pb":
            if last_part is None or last_part.tag not in (TEI + "front", TEI + "body"):
                raise ValueError("DocSouth root page-break position differs")
            boundary = _convert_node(child)
            boundary.set("rend", "source-text-boundary-after-" + etree.QName(last_part).localname)
            last_part.append(boundary)
        else:
            last_part = _convert_node(child)
            target_text.append(last_part)
    content = etree.tostring(result, encoding="UTF-8", xml_declaration=True)
    report = dict(contract=CONTRACT, work_id=work_id, source_path=entry["source_path"],
                  source_sha256=entry["source_sha256"], source_bytes=len(source_bytes),
                  source_doctype=entry["doctype"], source_nested_text_count=len(nested),
                  source_entity_declarations=len(declarations), source_rights_text_sha256=entry["rights_text_sha256"],
                  source_body_text_sha256=entry["body_text_sha256"],
                  source_back_text_sha256=_sha(base._text(base._one(text, "back")).encode("utf-8")),
                  source_root_page_breaks=source_order.count("pb"),
                  source_image_sha256={k: members[k]["sha256"] for k in sorted(members)},
                  candidate_sha256=_sha(content), candidate_bytes=len(content),
                  mapping="source-declared figures bind exact JPEGs by entity and official URL; text-level page breaks are source-marked at preceding part boundaries; all source readings retained")
    return content, report
