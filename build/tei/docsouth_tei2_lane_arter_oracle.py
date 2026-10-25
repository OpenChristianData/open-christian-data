"""Independently compare illustrated DocSouth TEI.2 XML and JPEGs with P5."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import quote
from urllib.parse import urljoin
import json

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
TEI = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
CONTRACT = "ocd-docsouth-tei2-lane-arter-source-image-oracle-v1"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _text(node: etree._Element) -> str:
    return "".join(node.itertext())


def _one(node: etree._Element, path: str) -> etree._Element:
    results = node.findall(path)
    if len(results) != 1:
        raise ValueError(f"DocSouth oracle expected one source or candidate field: {path}")
    return results[0]


def _compare_wording(source: etree._Element, candidate: etree._Element, source_path: str, target_path: str) -> None:
    source_words = re.sub(r"\s+", " ", _text(_one(source, source_path))).strip()
    candidate_words = re.sub(r"\s+", " ", _text(_one(candidate, target_path))).strip()
    if source_words != candidate_words:
        raise ValueError(f"DocSouth source header wording differs: {source_path}")


def _compare_body(source: etree._Element, candidate: etree._Element, tally: Counter,
                  images: dict[str, dict]) -> None:
    tag = source.tag
    if tag == "milestone":
        if (source.attrib != {"n": "* * *", "unit": "typography"}
                or source.text or len(source) or candidate.tag != TEI + "seg"
                or candidate.attrib != {"type": "source-milestone", "subtype": "typography", "n": source.get("n")}
                or candidate.text or len(candidate) or candidate.tail != source.tail):
            raise ValueError("DocSouth typography milestone attributes or order differ")
        tally["source_nodes"] += 1
        tally["typography_milestones"] += 1
        return
    if tag == "figure":
        entity = source.get("entity")
        image = images.get(entity)
        if (image is None or candidate.tag != TEI + "figure"
                or candidate.attrib != {XML + "id": source.get("id")}
                or candidate.text != source.text or candidate.tail != source.tail
                or len(candidate) != len(source) + 1 or candidate[0].tag != TEI + "graphic"
                or candidate[0].attrib != {"n": entity, "url": image["url"]}
                or candidate[0].text or candidate[0].tail):
            raise ValueError("DocSouth figure, entity, or graphic binding differs")
        tally["source_nodes"] += 1
        tally["figure"] += 1
        for original, migrated in zip(source, list(candidate)[1:], strict=True):
            _compare_body(original, migrated, tally, images)
        return
    if tag in {"sic", "corr"} and ("corr" if tag == "sic" else "sic") in source.attrib:
        alternate_attr = "corr" if tag == "sic" else "sic"
        if alternate_attr not in source.attrib or len(source):
            raise ValueError("DocSouth source correction differs from selected shape")
        wanted_note = "source-correction" if tag == "sic" else "source-sic-reading"
        if (candidate.tag != TEI + "seg" or candidate.attrib != {"type": "source-" + tag}
                or candidate.text != source.text or candidate.tail != source.tail
                or len(candidate) != 1 or candidate[0].tag != TEI + "note"
                or candidate[0].attrib != {"type": wanted_note}
                or candidate[0].text != source.get(alternate_attr)
                or candidate[0].tail not in (None, "")):
            raise ValueError("DocSouth source correction reading or alternate differs")
        tally["source_corrections"] += 1
        tally["source_nodes"] += 1
        return
    if tag in {"sic", "corr"}:
        if source.attrib or candidate.tag != TEI + "seg" or candidate.attrib != {"type": "source-" + tag}:
            raise ValueError("DocSouth unpaired correction carrier differs")
        if candidate.text != source.text or candidate.tail != source.tail or len(candidate) != len(source):
            raise ValueError("DocSouth unpaired correction text differs")
        tally["source_nodes"] += 1
        for a, b in zip(source, candidate, strict=True):
            _compare_body(a, b, tally, images)
        return
    tags = {
        "div1": "div", "div2": "div", "div3": "div", "text": "floatingText",
        "titlePage": "div", "docTitle": "head", "titlePart": "seg", "byline": "head",
        "docAuthor": "p", "docImprint": "p", "docDate": "p", "docEdition": "p", "epigraph": "quote",
    }
    expected_tag = tags.get(tag, tag)
    if tag == "emph" and source.get("rend"):
        expected_tag = "hi"
    if tag == "q" and source.get("type"):
        expected_tag = "quote"
    if tag in {"publisher", "pubPlace"} and source.getparent().tag == "docImprint":
        expected_tag = "seg"
    if tag == "docDate" and source.getparent().tag == "docImprint":
        expected_tag = "seg"
    if tag == "byline" and source.getparent().tag == "lg":
        expected_tag = "l"
    if tag == "titlePart" and source.getparent().tag == "titlePage":
        expected_tag = "p"
    if tag == "head" and source.getparent().tag in {"div1", "div2", "div3"} and any(
            earlier.tag not in {"pb", "head"} for earlier in source.itersiblings(preceding=True)):
        expected_tag = "p"
    if (candidate.tag != TEI + expected_tag or candidate.text != source.text
            or candidate.tail != source.tail or len(candidate) != len(source)):
        raise ValueError(f"DocSouth source unit structure/text differs: {tag}")
    attributes = {}
    for key, value in source.attrib.items():
        if tag == "q" and key == "direct":
            if value != "unspecified":
                raise ValueError("DocSouth source quote directness differs")
            tally["unspecified_quote_attributes"] += 1
            continue
        if key == "id":
            key = XML + "id"
        elif key == "lang":
            if tag == "ref":
                key, value = "rend", "source-lang-" + value
            else:
                key = XML + "lang"
        elif tag == "ref" and key == "targOrder":
            if value != "U":
                raise ValueError("DocSouth source target ordering differs")
            key, value = "subtype", "source-targOrder-U"
        elif tag == "note" and key == "target":
            key = "rend" if "type" in source.attrib else "type"
            value = "source-target-" + value
        elif tag == "note" and key == "anchored" and value == "yes":
            value = "true"
        elif tag == "titlePart" and key == "type":
            if expected_tag == "p":
                key, value = "rend", "source-title-part-" + value
            else:
                key = "subtype"
        elif key == "type" and any(character.isspace() for character in value):
            value = quote(value, safe="")
        attributes[key] = value
    if tag == "titlePage":
        attributes["type"] = "source-title-page"
    elif tag == "docImprint":
        attributes["rend"] = "source-imprint"
    elif tag == "epigraph":
        attributes["rend"] = "source-epigraph"
    elif tag == "docEdition":
        attributes["rend"] = "source-edition"
    elif tag == "titlePart":
        if expected_tag != "p":
            attributes["type"] = "source-title-part"
    elif tag == "byline":
        attributes["rend" if expected_tag == "l" else "type"] = "source-byline"
    elif tag == "head" and expected_tag == "p":
        attributes["rend"] = "source-late-head"
    elif tag in {"div1", "div2", "div3"}:
        attributes["subtype"] = "source-" + tag
    if candidate.attrib != attributes:
        raise ValueError(f"DocSouth source unit attributes differ: {tag}")
    tally["source_nodes"] += 1
    tally[tag] += 1
    for a, b in zip(source, candidate, strict=True):
        _compare_body(a, b, tally, images)


def check(source_path: Path, source_sha256: str, candidate: bytes,
          acquisition_receipt_path: Path) -> dict:
    source_bytes = _io_path(source_path).read_bytes()
    if _sha(source_bytes) != source_sha256:
        raise ValueError("DocSouth oracle retained TEI.2 source changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    target = etree.fromstring(candidate, parser)
    receipt = json.loads(_io_path(acquisition_receipt_path).read_bytes())
    declarations = {}
    for name, system_path in re.findall(
            rb'<!ENTITY\s+([A-Za-z][\w.-]*)\s+SYSTEM\s+["\']([^"\']+)["\']\s+NDATA\s+jpeg\s*>',
            source_bytes, re.I):
        declarations[name.decode("ascii")] = system_path.decode("ascii")
    members = {item["entity"]: item for item in receipt["image_members"]}
    figures = source.findall(".//figure")
    if (not figures or set(declarations) != set(members)
            or {item.get("entity") for item in figures} != set(declarations)
            or receipt["member"]["sha256"] != source_sha256):
        raise ValueError("DocSouth independent figure/DTD/receipt set differs")
    images = {}
    for entity, system_path in declarations.items():
        member = members[entity]
        data = _io_path(ROOT / member["path"]).read_bytes()
        expected_url = urljoin(receipt["source_url"], system_path)
        if (member["source_url"] != expected_url or member["sha256"] != _sha(data)
                or member["bytes"] != len(data) or data[:3] != b"\xff\xd8\xff"
                or data[-2:] != b"\xff\xd9"):
            raise ValueError("DocSouth independent JPEG provenance differs")
        images[entity] = dict(path=member["path"], sha256=member["sha256"], url=expected_url)
    if (source.tag != "TEI.2" or target.tag != TEI + "TEI" or target.getroottree().docinfo.doctype
            or source.xpath("//comment()|//processing-instruction()")
            or target.xpath("//comment()|//processing-instruction()")):
        raise ValueError("DocSouth oracle source or candidate envelope differs")
    source_text = _one(source, "text")
    target_text = _one(target, TEI + "text")
    if [item.tag for item in source_text] != ["front", "body"] or [item.tag for item in target_text] != [TEI + "front", TEI + "body"]:
        raise ValueError("DocSouth source text part ownership differs")
    source_nested = source_text.findall(".//body//text")
    target_nested = target_text.findall(".//" + TEI + "body//" + TEI + "floatingText")
    if (len(source_nested) != len(target_nested)
            or any(node.getparent().tag != "q" or [child.tag for child in node] != ["body"]
                   for node in source_nested)):
        raise ValueError("DocSouth quoted nested-text ownership differs")
    tally: Counter = Counter()
    for original, migrated in zip(source_text, target_text, strict=True):
        _compare_body(original, migrated, tally, images)
    # Header checks use original and candidate fields, not producer intermediate objects.
    fields = (
        ("teiHeader/fileDesc/titleStmt/title", TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "titleStmt/" + TEI + "title"),
        ("teiHeader/fileDesc/titleStmt/author", TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "titleStmt/" + TEI + "author"),
        ("teiHeader/fileDesc/publicationStmt/availability", TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "publicationStmt/" + TEI + "availability"),
        ("teiHeader/fileDesc/sourceDesc/bibl/author", TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "sourceDesc/" + TEI + "biblFull/" + TEI + "titleStmt/" + TEI + "author"),
    )
    for original, migrated in fields:
        _compare_wording(source, target, original, migrated)
    source_titles = source.findall("teiHeader/fileDesc/sourceDesc/bibl/title")
    target_titles = target.findall(TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "sourceDesc/" + TEI + "biblFull/" + TEI + "titleStmt/" + TEI + "title")
    if ([re.sub(r"\s+", " ", _text(item)).strip() for item in source_titles]
            != [re.sub(r"\s+", " ", _text(item)).strip() for item in target_titles]):
        raise ValueError("DocSouth source print title sequence differs")
    file_source = _one(source, "teiHeader/fileDesc")
    file_target = _one(target, TEI + "teiHeader/" + TEI + "fileDesc")
    for path in ("editionStmt/edition", "extent", "publicationStmt/publisher",
                 "publicationStmt/pubPlace", "publicationStmt/date",
                 "sourceDesc/bibl/imprint/publisher"):
        original = file_source.find(path)
        target_path = path.replace("sourceDesc/bibl/imprint", "sourceDesc/biblFull/publicationStmt")
        migrated = file_target.find("/".join(TEI + part for part in target_path.split("/")))
        if (original is None) != (migrated is None) or (original is not None and _text(original) != _text(migrated)):
            raise ValueError(f"DocSouth source bibliographic field differs: {path}")
    source_responsibilities = [(_text(item.find("resp")), _text(item.find("name")))
                               for item in file_source.findall("titleStmt/respStmt")]
    target_responsibilities = [(_text(item.find(TEI + "resp")), _text(item.find(TEI + "name")))
                               for item in file_target.findall(TEI + "titleStmt/" + TEI + "respStmt")]
    if source_responsibilities != target_responsibilities:
        raise ValueError("DocSouth source transcription/encoding credit differs")
    original_names = file_source.findall("titleStmt/respStmt/name")
    mapped_names = file_target.findall(TEI + "titleStmt/" + TEI + "respStmt/" + TEI + "name")
    if len(original_names) != len(mapped_names) or any(
            original.attrib != ({"id": mapped.get("key")[len("source-id-"):]} if mapped.get("key", "").startswith("source-id-") else {})
            for original, mapped in zip(original_names, mapped_names, strict=True)):
        raise ValueError("DocSouth source responsibility identifiers differ")
    funder = file_source.find("titleStmt/funder")
    funder_note = file_target.find(TEI + "notesStmt/" + TEI + "note[@type='source-funder']")
    if funder is None or funder_note is None or _text(funder) != _text(funder_note):
        raise ValueError("DocSouth source funding credit differs")
    original_note = _one(file_source, "notesStmt/note")
    mapped_note = _one(file_target, TEI + "notesStmt/" + TEI + "note[@type='source-call-number']")
    if (original_note.attrib != {"anchored": "yes"} or mapped_note.attrib != {"type": "source-call-number", "rend": "source-anchored-yes"}
            or _text(original_note) != _text(mapped_note)):
        raise ValueError("DocSouth electronic call-number note differs")
    source_bibl = _one(file_source, "sourceDesc/bibl")
    target_bibl = _one(file_target, TEI + "sourceDesc/" + TEI + "biblFull")
    if ([child.tag for child in source_bibl] != ["title", "author", "imprint"]
            or [child.tag for child in _one(source_bibl, "imprint")] != ["pubPlace", "publisher", "date"]
            or [child.tag for child in target_bibl] != [TEI + "titleStmt", TEI + "publicationStmt"]):
        raise ValueError("DocSouth print bibl topology differs")
    for name in ("pubPlace", "publisher", "date"):
        if _text(_one(source_bibl, "imprint/" + name)) != _text(_one(target_bibl, TEI + "publicationStmt/" + TEI + name)):
            raise ValueError(f"DocSouth print imprint wording differs: {name}")
    source_electronic_title = _one(file_source, "titleStmt/title")
    target_electronic_title = _one(file_target, TEI + "titleStmt/" + TEI + "title")
    source_emph = source_electronic_title.findall("emph")
    target_emph = file_target.findall(TEI + "notesStmt/" + TEI + "note[@type='source-electronic-title-emphasis']")
    if len(source_emph) != len(target_emph) or len(source_emph) > 1 or len(target_electronic_title):
        raise ValueError("DocSouth electronic title emphasis differs")
    if source_emph and (source_emph[0].attrib or target_emph[0].attrib != {"type": "source-electronic-title-emphasis"}
                        or _text(source_emph[0]) != _text(target_emph[0])):
        raise ValueError("DocSouth electronic title emphasis reading differs")
    for name in ("projectDesc", "editorialDecl"):
        source_paragraphs = file_source.getparent().findall("encodingDesc/" + name + "/p")
        target_paragraphs = file_target.getparent().findall(TEI + "encodingDesc/" + TEI + name + "/" + TEI + "p")
        if [_text(item) for item in source_paragraphs] != [_text(item) for item in target_paragraphs]:
            raise ValueError(f"DocSouth electronic encoding description differs: {name}")
    taxonomy = _one(source, "teiHeader/encodingDesc/classDecl/taxonomy")
    classification = _one(file_target, TEI + "notesStmt/" + TEI + "note[@type='source-classification']")
    if taxonomy.attrib != {"id": "lcsh"} or classification.get("n") != taxonomy.get("id"):
        raise ValueError("DocSouth source taxonomy identifier differs")
    original_availability = _one(source, "teiHeader/fileDesc/publicationStmt/availability")
    target_availability = _one(target, TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "publicationStmt/" + TEI + "availability")
    if original_availability.get("status") != target_availability.get("status"):
        raise ValueError("DocSouth electronic rights status differs")
    original_links = [(item.get("href"), _text(item)) for item in original_availability.findall(".//a")]
    target_links = [(item.get("target"), _text(item)) for item in target_availability.findall(".//" + TEI + "ref")]
    if original_links != target_links:
        raise ValueError("DocSouth electronic rights link differs")
    original_changes = source.findall("teiHeader/revisionDesc/change")
    target_changes = target.findall(TEI + "teiHeader/" + TEI + "revisionDesc/" + TEI + "change")
    if [_text(item) for item in original_changes] != [_text(item) for item in target_changes]:
        raise ValueError("DocSouth source revision wording differs")
    original_languages = source.findall("teiHeader/profileDesc/langUsage/language")
    target_languages = target.findall(TEI + "teiHeader/" + TEI + "profileDesc/" + TEI + "langUsage/" + TEI + "language")
    if [(item.get("id"), _text(item)) for item in original_languages] != [(item.get("ident"), _text(item)) for item in target_languages]:
        raise ValueError("DocSouth source language labels differ")
    source_keywords = source.findall("teiHeader/profileDesc/textClass/keywords/list/item")
    target_keywords = target.findall(TEI + "teiHeader/" + TEI + "profileDesc/" + TEI + "textClass/" + TEI + "keywords/" + TEI + "term")
    if [_text(item) for item in source_keywords] != [_text(item) for item in target_keywords]:
        raise ValueError("DocSouth source subject terms differ")
    original_keywords = source.findall("teiHeader/profileDesc/textClass/keywords")
    mapped_keywords = target.findall(TEI + "teiHeader/" + TEI + "profileDesc/" + TEI + "textClass/" + TEI + "keywords")
    if len(original_keywords) != len(mapped_keywords) or any(
            original.attrib != mapped.attrib for original, mapped in zip(original_keywords, mapped_keywords, strict=True)):
        raise ValueError("DocSouth source keyword scheme differs")
    return dict(contract=CONTRACT, source_sha256=source_sha256, candidate_sha256=_sha(candidate),
                body_text_sha256=_sha(_text(_one(source_text, "body")).encode("utf-8")),
                source_unit_count=tally["source_nodes"], source_page_count=tally["pb"],
                source_verse_line_count=tally["l"], source_correction_count=tally["source_corrections"],
                source_nested_text_count=len(source_nested),
                source_figure_count=tally["figure"], source_images=images,
                typography_milestone_count=tally["typography_milestones"],
                unspecified_quote_attribute_count=tally["unspecified_quote_attributes"],
                electronic_rights_text_sha256=_sha(_text(original_availability).encode("utf-8")),
                header_wording="pass", source_body_structure="pass")
