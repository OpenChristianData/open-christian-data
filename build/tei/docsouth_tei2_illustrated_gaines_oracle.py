"""Independently compare Gaines's complete TEI.2 table/JPEG witness with P5."""

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
CONTRACT = "ocd-docsouth-tei2-illustrated-gaines-source-image-oracle-v1"


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
    if tag == "table" and (source.attrib or [child.tag for child in source[:1]] != ["head"]
                           or len(source.findall("row")) != 49):
        raise ValueError("DocSouth Gaines source table shape differs")
    if tag == "row" and (source.attrib not in ({"role": "label"}, {"role": "data"})
                         or len(source.findall("cell")) != 9):
        raise ValueError("DocSouth Gaines row role or cell count differs")
    if tag == "cell" and (source.attrib not in ({"role": "label", "rows": "1", "cols": "1"},
                                            {"role": "data", "rows": "1", "cols": "1"})
                          or [child.tag for child in source] not in ([], ["ref", "note"])):
        raise ValueError("DocSouth Gaines cell role or span differs")
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
        "div1": "div", "div2": "div", "div3": "div", "div4": "div", "text": "floatingText",
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
    if tag == "epigraph" and source.getparent().tag == "lg":
        expected_tag = "lg"
    if tag == "p" and source.getparent().tag == "epigraph" and source.getparent().getparent().tag == "lg":
        expected_tag = "l"
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
        elif tag == "ref" and key == "targOrder":
            if value != "U":
                raise ValueError("DocSouth source target ordering differs")
            key, value = "subtype", "source-targOrder-U"
        elif tag == "ref" and key == "lang":
            if "rend" in source.attrib:
                raise ValueError("DocSouth source ref language/rendition collision")
            key, value = "rend", "source-lang-" + value
        elif key == "lang":
            key = XML + "lang"
        elif tag == "pb" and key == "rend" and value == " ":
            value = "source-single-space"
        elif tag == "note" and key == "target":
            key, value = "type", "source-target-" + value
        elif tag == "note" and key == "anchored" and value == "yes":
            value = "true"
        elif tag in {"row", "cell"} and key == "role":
            key, value = "ana", "source-role-" + value
        elif tag == "cell" and key == "rows":
            key, value = "rend", "source-rows-" + value
        elif tag == "titlePart" and key == "type":
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
        attributes["type"] = "source-title-part"
    elif tag == "byline":
        attributes["rend" if expected_tag == "l" else "type"] = "source-byline"
    elif tag in {"div1", "div2", "div3", "div4"}:
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
        ("teiHeader/fileDesc/publicationStmt/availability", TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "publicationStmt/" + TEI + "availability"),
    )
    for original, migrated in fields:
        _compare_wording(source, target, original, migrated)
    source_titles = source.findall("teiHeader/fileDesc/sourceDesc/biblFull/titleStmt/title")
    target_titles = target.findall(TEI + "teiHeader/" + TEI + "fileDesc/" + TEI + "sourceDesc/" + TEI + "biblFull/" + TEI + "titleStmt/" + TEI + "title")
    if ([re.sub(r"\s+", " ", _text(item)).strip() for item in source_titles]
            != [re.sub(r"\s+", " ", _text(item)).strip() for item in target_titles]):
        raise ValueError("DocSouth source print title sequence differs")
    if [item.attrib for item in target_titles] != [
            {"type": "source-" + quote(item.get("type"), safe="")} for item in source_titles]:
        raise ValueError("DocSouth source print title attributes differ")
    file_source = _one(source, "teiHeader/fileDesc")
    file_target = _one(target, TEI + "teiHeader/" + TEI + "fileDesc")
    electronic_title = _one(file_source, "titleStmt/title")
    title_markup = file_target.findall(TEI + "notesStmt/" + TEI + "note[@type='source-electronic-title-markup']")
    if (len(electronic_title) != 1 or electronic_title[0].tag != "emph"
            or electronic_title[0].attrib or len(electronic_title[0])
            or len(title_markup) != 1 or title_markup[0].attrib != {"type": "source-electronic-title-markup"}
            or title_markup[0].text != etree.tostring(electronic_title, encoding="unicode", with_tail=False)):
        raise ValueError("DocSouth electronic title markup differs")
    for source_path, target_path in (
            ("titleStmt/author", TEI + "titleStmt/" + TEI + "author"),
            ("sourceDesc/biblFull/titleStmt/author",
             TEI + "sourceDesc/" + TEI + "biblFull/" + TEI + "titleStmt/" + TEI + "author")):
        originals = file_source.findall(source_path)
        migrated = file_target.findall(target_path)
        if (not originals or [re.sub(r"\s+", " ", _text(item)).strip() for item in originals]
                != [re.sub(r"\s+", " ", _text(item)).strip() for item in migrated]
                or any(item.attrib for item in originals + migrated)):
            raise ValueError(f"DocSouth electronic or print author sequence differs: {source_path}")
    original_notes = file_source.findall("notesStmt/note")
    mapped_notes = file_target.findall(TEI + "notesStmt/" + TEI + "note[@type='source-call-number']")
    if len(original_notes) > 1 or len(original_notes) != len(mapped_notes) or any(
            original.attrib != {"anchored": "yes"}
            or mapped.attrib != {"type": "source-call-number", "rend": "source-anchored-yes"}
            or _text(original) != _text(mapped)
            for original, mapped in zip(original_notes, mapped_notes, strict=True)):
        raise ValueError("DocSouth electronic call-number note differs")
    authority = _one(file_source, "sourceDesc/biblFull/publicationStmt/authority")
    if authority.attrib or len(authority) or _text(authority).strip():
        raise ValueError("DocSouth empty print authority field differs")
    for path in ("editionStmt/edition", "extent", "publicationStmt/publisher",
                 "publicationStmt/pubPlace", "publicationStmt/date",
                 "sourceDesc/biblFull/extent", "sourceDesc/biblFull/publicationStmt/publisher"):
        original = file_source.find(path)
        migrated = file_target.find("/".join(TEI + part for part in path.split("/")))
        if (original is None) != (migrated is None) or (original is not None and _text(original) != _text(migrated)):
            raise ValueError(f"DocSouth source bibliographic field differs: {path}")
    source_responsibilities = [(_text(item.find("resp")), _text(item.find("name")))
                               for item in file_source.findall("titleStmt/respStmt")]
    target_responsibilities = [(_text(item.find(TEI + "resp")), _text(item.find(TEI + "name")))
                               for item in file_target.findall(TEI + "titleStmt/" + TEI + "respStmt")]
    if source_responsibilities != target_responsibilities:
        raise ValueError("DocSouth source transcription/encoding credit differs")
    funder = file_source.find("titleStmt/funder")
    funder_note = file_target.find(TEI + "notesStmt/" + TEI + "note[@type='source-funder']")
    if funder is None or funder_note is None or _text(funder) != _text(funder_note):
        raise ValueError("DocSouth source funding credit differs")
    for name in ("projectDesc", "editorialDecl"):
        source_paragraphs = file_source.getparent().findall("encodingDesc/" + name + "/p")
        target_paragraphs = file_target.getparent().findall(TEI + "encodingDesc/" + TEI + name + "/" + TEI + "p")
        if [_text(item) for item in source_paragraphs] != [_text(item) for item in target_paragraphs]:
            raise ValueError(f"DocSouth electronic encoding description differs: {name}")
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
    return dict(contract=CONTRACT, source_sha256=source_sha256, candidate_sha256=_sha(candidate),
                body_text_sha256=_sha(_text(_one(source_text, "body")).encode("utf-8")),
                source_table_count=tally["table"], source_row_count=tally["row"],
                source_cell_count=tally["cell"],
                empty_print_authority=True,
                source_unit_count=tally["source_nodes"], source_page_count=tally["pb"],
                source_verse_line_count=tally["l"], source_correction_count=tally["source_corrections"],
                source_nested_text_count=len(source_nested),
                source_figure_count=tally["figure"], source_images=images,
                unspecified_quote_attribute_count=tally["unspecified_quote_attributes"],
                electronic_rights_text_sha256=_sha(_text(original_availability).encode("utf-8")),
                header_wording="pass", source_body_structure="pass")
