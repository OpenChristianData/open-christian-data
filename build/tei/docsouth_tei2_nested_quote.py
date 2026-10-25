"""Convert three source-bound DocSouth TEI.2 works with embedded quoted texts."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote

from lxml import etree

from build.tei import docsouth_tei2_simple as base
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = base.INVENTORY
INVENTORY_SHA = base.INVENTORY_SHA
TEI = base.TEI
XML = base.XML
CONTRACT = "ocd-docsouth-tei2-nested-quote-p5-v1"
SELECTIONS = {
    "elijah-p-marrs-life-and-history",
    "george-white-brief-account-life-experience-travels",
    "peter-randolph-from-slave-cabin-to-pulpit",
}
TAGS = base.BODY_TAGS | base.FRONT_TAGS | {
    "body", "byline", "closer", "dateline", "div2", "div3", "emph", "epigraph", "floatingText",
    "name", "note", "ref", "salute", "signed", "text",
}


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _convert_node(node: etree._Element) -> etree._Element:
    name = node.tag
    if name not in TAGS:
        raise ValueError(f"DocSouth nested-quote source element differs: {name}")
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
        "div1": "div", "div2": "div", "div3": "div", "text": "floatingText",
        "titlePage": "div", "docTitle": "head", "titlePart": "seg", "byline": "head",
        "docAuthor": "p", "docImprint": "div", "docDate": "p",
    }
    target = mapping.get(name, name)
    if name == "q" and node.get("type"):
        target = "quote"
    if name in {"publisher", "pubPlace"} and node.getparent().tag == "docImprint":
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
            if not value or "type" in node.attrib:
                raise ValueError("DocSouth note target differs")
            key, value = "type", "source-target-" + value
        elif name == "note" and key == "anchored" and value == "yes":
            value = "true"
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
        result.set("type", "source-imprint")
    elif name == "titlePart":
        result.set("type", "source-title-part")
    elif name == "byline":
        result.set("type", "source-byline")
    elif name in {"div1", "div2", "div3"}:
        result.set("subtype", "source-" + name)
    result.text, result.tail = node.text, node.tail
    for child in node:
        if not isinstance(child.tag, str):
            raise ValueError("DocSouth nested source contains nontext node")
        result.append(_convert_node(child))
    return result


def convert(work_id: str) -> tuple[bytes, dict]:
    if work_id not in SELECTIONS or _sha(_io_path(INVENTORY).read_bytes()) != INVENTORY_SHA:
        raise ValueError("DocSouth nested-quote selection or inventory differs")
    inventory = json.loads(_io_path(INVENTORY).read_bytes())
    entries = [item for item in inventory["works"] if item["work_id"] == work_id]
    if len(entries) != 1:
        raise ValueError("DocSouth nested-quote work absent or repeated")
    entry = entries[0]
    if (entry["accepted_master_present"] or not entry["body_nested_text_count"]
            or entry["element_counts"].get("figure", 0) or entry["element_counts"].get("table", 0)
            or entry["entity_declarations"] or entry["back_count"]
            or entry["text_child_tags"] != ["front", "body"]):
        raise ValueError("DocSouth nested-quote source shape differs")
    source_bytes = _io_path(ROOT / entry["source_path"]).read_bytes()
    work_bytes = _io_path(ROOT / entry["work_path"]).read_bytes()
    if (_sha(source_bytes) != entry["source_sha256"] or len(source_bytes) != entry["source_bytes"]
            or _sha(work_bytes) != entry["work_sha256"]):
        raise ValueError("DocSouth nested-quote retained source or current work differs")
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True,
                                                            remove_comments=False, huge_tree=True))
    if source.tag != "TEI.2" or source.xpath("//comment()|//processing-instruction()"):
        raise ValueError("DocSouth nested-quote source envelope differs")
    text = base._one(source, "text")
    if [child.tag for child in text] != ["front", "body"]:
        raise ValueError("DocSouth nested-quote text ownership differs")
    nested = text.findall(".//body//text")
    if len(nested) != entry["body_nested_text_count"] or any(
            n.getparent().tag != "q" or [c.tag for c in n] != ["body"] for n in nested):
        raise ValueError("DocSouth nested-quote ownership differs")
    result = etree.Element(TEI + "TEI", nsmap={None: TEI[1:-1]})
    result.set(XML + "id", f"ocd-{work_id}-docsouth-tei2-v1")
    result.append(base._header(source, json.loads(work_bytes)))
    target_text = base._element(result, "text", **{XML + "lang": "en"})
    for child in text:
        target_text.append(_convert_node(child))
    content = etree.tostring(result, encoding="UTF-8", xml_declaration=True)
    report = dict(contract=CONTRACT, work_id=work_id, source_path=entry["source_path"],
                  source_sha256=entry["source_sha256"], source_bytes=len(source_bytes),
                  source_doctype=entry["doctype"], source_nested_text_count=len(nested),
                  source_entity_declarations=0, source_rights_text_sha256=entry["rights_text_sha256"],
                  source_body_text_sha256=entry["body_text_sha256"],
                  candidate_sha256=_sha(content), candidate_bytes=len(content),
                  mapping="quoted nested text becomes floatingText; source readings, corrections, target order and note target retained in native-safe carriers")
    return content, report
