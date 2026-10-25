"""Explicit source-native commentary rows for exact accepted electronic witnesses.

This route never infers a Bible target. Public native content keeps source order;
the independently regenerated private receipt binds slots, byte gaps, links,
and literal multi-target references omitted from the public row shape.
"""
from __future__ import annotations

import copy
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection import native_content
from ocd_kernel.projection.native_content_check import observe_content
from ocd_kernel.projection.envelope import row_text_hash

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
VERSION = "ocd-commentary-accepted-source-native-v1"
BARNES = ("barnes-nt-notes", "crosswire-sword-v1.1", "barnes-sword-v1.1")
ROBERTSON = ("robertson-word-pictures-vol1", "robertson-word-pictures-vol1-matthew-mark-ccel",
             "robertson-word-pictures-vol1-matthew-mark-source-set")
LIGHTFOOT = ("lightfoot-colossians-philemon", "pg50857", "pg50857-text")
JFB = ("jamieson-fausset-brown", "jamieson-fausset-brown-retained-electronic",
       "jamieson-fausset-brown-acquired-member-set")
GILL = ("john-gill", "john-gill-retained-electronic", "john-gill-acquired-member-set")
KEIL = ("keil-delitzsch", "keil-delitzsch-retained-electronic", "keil-delitzsch-acquired-member-set")
KEIL_FORM = "keil-delitzsch-retained-en"
KEIL_VERSION = "ocd-commentary-keil-retained-collection-native-v1"
HENRY = ("matthew-henry-complete", "matthew-henry-complete-retained-electronic",
         "matthew-henry-complete-acquired-member-set")
LIGHTFOOT_VERSION = "ocd-commentary-lightfoot-region-native-v1"
FINDLAY_VERSION = "ocd-commentary-findlay-complete-member-native-v1"
FINDLAY_WORK = "expositors-bible--g-g-findlay"
FINDLAY_EDITIONS = {
    "expositors-bible--g-g-findlay--findlay-expositoreph--ccel-electronic": (
        "expositors-bible--g-g-findlay--findlay-expositoreph--retained-en",
        "expositors-bible--g-g-findlay--findlay-expositoreph--acquired",
        "5a2dd38ba68aa0895525b82a37409c625dd3d169be3b9c2698ad00e9acf37ae5",
        "findlay-expositoreph", "https://www.ccel.org/ccel/findlay/expositoreph.html", 5793, 11437, 14),
    "expositors-bible--g-g-findlay--findlay-expositorgal--ccel-electronic": (
        "expositors-bible--g-g-findlay--findlay-expositorgal--retained-en",
        "expositors-bible--g-g-findlay--findlay-expositorgal--acquired",
        "87a0a5761e8f6df19c9d2f801f6886e3cfdc9f2fa120639b45a83af621784b2e",
        "findlay-expositorgal", "https://www.ccel.org/ccel/findlay/expositorgal.html", 4538, 8974, 22),
}
JOSHUA = ("calvin-commentary-on-joshua", "calvin-commentary-on-joshua-ccel-electronic", "calvin-joshua-direct-ccel-xml-source-set")
JOSHUA_FORM = "calvin-commentary-on-joshua-english"
JOSHUA_FAMILY = "calvin-joshua-source-native-v1"
LIGHTFOOT_REGIONS = (
    ("gutenberg-preamble", "lightfoot-region-preamble"),
    ("transcriber-note", "lightfoot-region-transcriber-note"),
    ("title-page", "lightfoot-region-title-page"),
    ("preface", "lightfoot-region-preface"),
    ("contents", "lightfoot-region-contents"),
    ("colossians-introduction", "lightfoot-region-colossians-introduction"),
    ("colossians-text-frontmatter", "lightfoot-region-colossians-frontmatter"),
    ("colossians-text-commentary", "lightfoot-region-colossians-commentary"),
    ("colossians-apparatus", "lightfoot-region-colossians-apparatus"),
    ("philemon-introduction", "lightfoot-region-philemon-introduction"),
    ("philemon-text-frontmatter", "lightfoot-region-philemon-frontmatter"),
    ("philemon-text-commentary", "lightfoot-region-philemon-commentary"),
    ("additions-and-corrections", "lightfoot-region-additions"),
    ("index", "lightfoot-region-index"),
    ("colophon-and-transcriber-note", "lightfoot-region-colophon-note"),
    ("gutenberg-end-envelope", "lightfoot-region-gutenberg-end"),
    ("gutenberg-license", "lightfoot-region-gutenberg-license"),
)


CLARKE = ("adam-clarke", "adam-clarke-retained-electronic", "adam-clarke-acquired-member-set")


def _findlay_expected(acceptance: dict) -> tuple | None:
    expected = FINDLAY_EDITIONS.get(acceptance["identity"]["edition_id"])
    if acceptance.get("representation_revision", {}).get("id") == "findlay-expositorgal-source-text-corrections-20261008-v1":
        if expected is None or expected[3] != "findlay-expositorgal":
            raise PipelineError("Findlay corrected revision has a different edition")
        expected = (*expected[:2], "00247b413f879e24728d7ae7824ad25d12e46370f5134268235d4549f01140ff",
                    *expected[3:5], 4802, *expected[6:])
    return expected


def route(metadata: dict) -> str | None:
    identity = metadata["acceptance"]["identity"]
    if identity.get("work_id") == "church-fathers-quotations":
        from . import lib061_toml_native
        return lib061_toml_native.route(metadata)
    key = (identity["work_id"], identity["edition_id"], identity["acquisition_id"])
    source_kind = metadata["acceptance"]["source"].get("source_kind")
    if identity["work_id"] == FINDLAY_WORK:
        expected = _findlay_expected(metadata["acceptance"])
        if (expected is None or identity != {"work_id": FINDLAY_WORK, "textual_form_id": expected[0],
                                             "edition_id": identity["edition_id"], "acquisition_id": expected[1]}
                or source_kind is not None or metadata["language"] != "en"
                or _sha(Path(metadata["master_path"]).read_bytes()) != expected[2]):
            raise PipelineError("Findlay source-native route requires an exact accepted witness")
        return "findlay"
    if identity.get("work_id") == "calvin-commentaries":
        from . import calvin_collection_source_native
        return calvin_collection_source_native.route(metadata)
    if identity.get("work_id") == JOSHUA[0]:
        if key != JOSHUA:
            raise PipelineError("recognized Joshua work identity has an unexpected edition or acquisition")
        if source_kind != "retained-member-set":
            raise PipelineError("recognized Joshua identity requires retained-member-set source authority")
        if getattr(metadata.get("edition"), "textual_form_id", None) != JOSHUA_FORM:
            raise PipelineError("recognized Joshua identity has a different textual form")
        from . import calvin_joshua_source_native
        return calvin_joshua_source_native.route(metadata)
    if key[0] == CLARKE[0] or key[1] == CLARKE[1] or key[2] == CLARKE[2]:
        if (key != CLARKE or source_kind != "retained-member-set"
                or identity.get("textual_form_id") != "adam-clarke-retained-en"):
            raise PipelineError("Clarke retained route requires its exact identity and source kind")
        return "clarke"
    if key[0] == HENRY[0] or key[1] == HENRY[1] or key[2] == HENRY[2]:
        if (key != HENRY or source_kind != "retained-member-set"
                or identity.get("textual_form_id") != "matthew-henry-complete-retained-en"):
            raise PipelineError("Henry retained route requires its exact identity and source kind")
        return "henry"
    if key[0] == KEIL[0] or key[1] == KEIL[1] or key[2] == KEIL[2]:
        if (key != KEIL or source_kind != "retained-member-set"
                or identity.get("textual_form_id") != KEIL_FORM):
            raise PipelineError("Keil retained route requires its exact identity and source kind")
        return "keil"
    if key == LIGHTFOOT and source_kind is None:
        return "lightfoot"
    if source_kind != "retained-member-set":
        return None
    if key == GILL:
        return "gill"
    if key == JFB:
        return "jfb"
    if key == BARNES:
        return "barnes"
    if key == ROBERTSON:
        return "robertson"
    return None


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _logical_hash(value: object) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _name(node: object) -> str:
    return etree.QName(node).localname if hasattr(node, "nsmap") else str(node.tag).rsplit("}", 1)[-1]


def _attrs(node: object) -> dict[str, str]:
    return {
        ("xml:id" if key == XML_ID else key.rsplit("}", 1)[-1] if key.startswith("{") else key): value
        for key, value in sorted(node.attrib.items())
    }


def _children(node: object, name: str) -> list:
    return [child for child in node if _name(child) == name]


def _profile(body: object, family: str) -> list:
    children = list(body)
    if family == "findlay":
        if (len(children) != 1 or _name(children[0]) != "div"
                or children[0].get("type") != "retained-source-member"
                or len(children[0]) != 2
                or [_name(child) for child in children[0]] != ["head", "div"]
                or children[0][1].get("type") != "source-xml-element"
                or children[0][1].get("{http://www.w3.org/XML/1998/namespace}space") != "preserve"):
            raise PipelineError("Findlay requires one complete retained source member and literal nested tree")
        return children
    if family in {"jfb", "gill", "henry", "clarke", "keil"}:
        codes = ('GEN', 'EXO', 'LEV', 'NUM', 'DEU', 'JOS', 'JDG', 'RUT', '1SA', '2SA', '1KI', '2KI', '1CH', '2CH', 'EZR', 'NEH', 'EST', 'JOB', 'PSA', 'PRO', 'ECC', 'SNG', 'ISA', 'JER', 'LAM', 'EZK', 'DAN', 'HOS', 'JOL', 'AMO', 'OBA', 'JON', 'MIC', 'NAM', 'HAB', 'ZEP', 'HAG', 'ZEC', 'MAL', 'MAT', 'MRK', 'LUK', 'JHN', 'ACT', 'ROM', '1CO', '2CO', 'GAL', 'EPH', 'PHP', 'COL', '1TH', '2TH', '1TI', '2TI', 'TIT', 'PHM', 'HEB', 'JAS', '1PE', '2PE', '1JN', '2JN', '3JN', 'JUD', 'REV')
        if family == "clarke":
            codes = tuple(code for code in codes if code not in {"DEU", "JDG", "PSA", "PRO", "ECC", "JER", "JOL", "MAL", "MAT"})
        if family == "henry":
            codes = tuple(code for code in codes if code != "SNG")
        if family == "keil":
            codes = codes[:39]
        if (len(children) != len(codes) or tuple(node.get("n") for node in children) != codes
                or any(_name(node) != "div" or node.get("type") != "book"
                       or node.get(XML_ID) != f"book-{node.get('n')}" for node in children)):
            raise PipelineError("JFB retained native route requires all66 source-ordered books")
        chapters = [node for book in children for node in _children(book, "div") if node.get("type") == "chapter"]
        occurrences = [node for chapter in chapters for node in _children(chapter, "div") if node.get("type") == "commentary-occurrence"]
        introductions = [node for chapter in chapters for node in _children(chapter, "div") if node.get("type") == "chapter-introduction"]
        if (len(chapters), len(occurrences), len(introductions)) != ({"jfb": (1187, 17056, 1178), "gill": (1189, 28300, 1186), "henry": (1167, 4124, 1156), "clarke": (854, 13318, 831), "keil": (909, 6516, 394)}[family]):
            raise PipelineError("JFB retained chapter, occurrence, or introduction inventory differs")
        for book in children:
            if len([node for node in _children(book, "div") if node.get("type") == "book-introduction"]) != 1:
                raise PipelineError("JFB retained book introduction inventory differs")
            numbers = [int(node.get("n")) for node in _children(book, "div") if node.get("type") == "chapter"]
            keil_gaps = {"EXO": {37, 38}, "NUM": {17}, "JOB": {25},
                         "PSA": {101, 117, 131, 133}, "EZK": {4, 5, 36}}
            excluded = (keil_gaps if family == "keil" else
                        {"MRK": {15}, "PSA": {146}} if family == "jfb" else
                        {"ISA": {67}} if family == "henry" else {}).get(book.get("n"), set())
            if (not numbers and (family != "keil" or book.get("n") != "SNG")) or (
                numbers and numbers != [number for number in range(1, max(numbers) + 1)
                                        if number not in excluded]
            ):
                raise PipelineError("JFB retained source order or known chapter gaps differ")
        for chapter in chapters:
            code = chapter.get(XML_ID).removeprefix("chapter-")
            entries = [node for node in _children(chapter, "div") if node.get("type") == "commentary-occurrence"]
            if any(node.get(XML_ID) != f"commentary-{code}-{ordinal:0{5 if family in {'gill', 'keil'} else 4}d}" for ordinal, node in enumerate(entries, 1)):
                raise PipelineError("JFB retained commentary occurrence order differs")
        if family == "clarke":
            intro_only = [node for node in chapters if not _children(node, "div") or not any(child.get("type") == "commentary-occurrence" for child in _children(node, "div"))]
            if len(intro_only) != 127 or any(not any(child.get("type") == "chapter-introduction" for child in _children(node, "div")) for node in intro_only):
                raise PipelineError("Clarke retained introduction-only chapter inventory differs")
        if family in {"gill", "keil"}:
            notes = [node for book in children for node in book.iter() if _name(node) == "note"]
            expected_notes = (66, 1189, 3567) if family == "gill" else (39, 909, 2727)
            if tuple(sum(node.get("type") == kind for node in notes) for kind in ("book-metadata", "number-of-verses", "chapter-link")) != expected_notes:
                raise PipelineError("retained private source metadata inventory differs")
        return children
    if family == "barnes":
        if len(children) != 1 or _name(children[0]) != "div" or children[0].get("type") != "sword-module" or children[0].get("subtype") != "new-testament":
            raise PipelineError("Barnes accepted native route requires one New Testament SWORD module")
        slots = list(children[0])
        if len(slots) != 8246:
            raise PipelineError(f"Barnes accepted native route requires 8246 ordered source slots, found {len(slots)}")
        for ordinal, slot in enumerate(slots):
            if (_name(slot) != "ab" or slot.get("type") != "sword-slot" or slot.get("n") != str(ordinal)
                    or slot.get(XML_ID) != f"barnes-slot-{ordinal:05d}"):
                raise PipelineError(f"Barnes source slot order or identity differs at {ordinal}")
        if sum(slot.get("ana") == "#empty-source-slot" for slot in slots) != 783:
            raise PipelineError("Barnes empty source-slot accounting differs")
        if sum(1 for slot in slots for node in slot.iter() if _name(node) == "gap") != 166:
            raise PipelineError("Barnes source-byte gap count differs")
        return slots
    if family == "lightfoot":
        if (len(children) != 1 or _name(children[0]) != "div"
                or _attrs(children[0]) != {"xml:id": "lightfoot-envelope", "type": "gutenberg-envelope"}):
            raise PipelineError("Lightfoot requires the exact retained Gutenberg envelope")
        regions = list(children[0])
        if len(regions) != len(LIGHTFOOT_REGIONS):
            raise PipelineError("Lightfoot source-region count differs")
        for ordinal, (region, (kind, source_id)) in enumerate(zip(regions, LIGHTFOOT_REGIONS), 1):
            if (_name(region) != "div" or _attrs(region) != {"xml:id": source_id, "type": kind}):
                raise PipelineError(f"Lightfoot source-region identity or order differs at {ordinal}")
        return regions
    if family == "robertson":
        if len(children) != 2 or [_name(child) for child in children] != ["div", "div"] or [child.get("type") for child in children] != ["retained-member", "retained-member"] or [child.get("n") for child in children] != ["matthew", "mark"]:
            raise PipelineError("Robertson accepted native route requires ordered Matthew and Mark members")
        divisions = [node for member in children for node in member.iter() if _name(node) == "div"]
        paragraphs = [node for member in children for node in member.iter() if _name(node) == "p"]
        linked = [node for node in divisions if node.get("prev") is not None or node.get("next") is not None]
        multiple = [node for member in children for node in member.iter() if _name(node) == "ref" and len((node.get("target") or "").split()) > 1]
        if (len(divisions), len(paragraphs), len(linked), len(multiple)) != (62, 1531, 54, 166):
            raise PipelineError("Robertson native divisions, paragraphs, links, or multiple targets differ")
        if any(not (node.get("prev", "").startswith("#") and node.get("next", "").startswith("#")) for node in linked):
            raise PipelineError("Robertson source division links differ")
        return children
    raise PipelineError(f"unknown accepted native commentary route: {family}")



def _require_blank(value: str | None, region: str) -> None:
    if value and value.strip():
        raise PipelineError(f"accepted native commentary has unaccounted text in {region}")


def _envelope(root: object, body: object, units: list, family: str) -> None:
    """Reject visible content outside the exact selected native units."""
    root_children = list(root)
    if (len(root_children) != 2 or root_children[0].tag != f"{{{TEI}}}teiHeader"
            or root_children[1].tag != f"{{{TEI}}}text"):
        raise PipelineError("accepted native commentary requires only teiHeader and text")
    text = root_children[1]
    if list(text) != [body]:
        raise PipelineError("accepted native commentary cannot omit front, back, or other text children")
    _require_blank(root.text, "TEI root")
    _require_blank(root_children[0].tail, "teiHeader tail")
    _require_blank(text.tail, "text tail")
    _require_blank(text.text, "text wrapper")
    _require_blank(body.tail, "body tail")
    _require_blank(body.text, "body wrapper")
    for child in body:
        _require_blank(child.tail, "body child tail")
    if family == "barnes":
        module = body[0]
        _require_blank(module.text, "SWORD module wrapper")
        for slot in units:
            _require_blank(slot.tail, "SWORD slot tail")
    if family == "lightfoot":
        _require_blank(body[0].text, "Gutenberg envelope wrapper")
        for region in units:
            _require_blank(region.tail, "Gutenberg source-region tail")


def _paths(root: object) -> dict[object, str]:
    result = {root: "/TEI[1]"}
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in parent:
            name = _name(child)
            counts[name] = counts.get(name, 0) + 1
            result[child] = f"{result[parent]}/{name}[{counts[name]}]"
    return result


def _unit_inventory(unit: object, structure: dict, path: str) -> dict:
    return {
        "tei_path": path, "disposition": "source-native-unit",
        "attributes": _attrs(unit), "structure_sha256": _logical_hash(structure),
        "descendant_count": sum(1 for _ in unit.iter()),
    }


def _evidence(units: list, paths: dict, family: str) -> tuple[list[dict], list[dict], list[dict]]:
    inventory: list[dict] = []
    references: list[dict] = []
    warnings: list[dict] = []
    for unit in units:
        for node in unit.iter():
            kind = _name(node)
            if family == "barnes" and kind == "gap":
                inventory.append({"tei_path": paths[node], "disposition": "source-byte-gap", "attributes": _attrs(node)})
                warnings.append({"tei_path": paths[node], "reason": "unrepresentable-source-bytes"})
            if family == "robertson" and kind == "div":
                role = "source-division-link" if node.get("prev") is not None or node.get("next") is not None else "source-division"
                inventory.append({"tei_path": paths[node], "disposition": role, "attributes": _attrs(node)})
            if kind == "ref" and len((node.get("target") or "").split()) > 1:
                references.append({"tei_path": paths[node], "original_target": node.get("target"),
                                   "normalization_status": "unsupported-explicit-target"})
    if family == "barnes":
        inventory.append({"disposition": "source-native-profile", "family": family,
                          "slots": len(units),
                          "empty_slots": sum(unit.get("ana") == "#empty-source-slot" for unit in units),
                          "byte_gaps": len(warnings)})
    else:
        inventory.append({"disposition": "source-native-profile", "family": family,
                          "member_containers": len(units),
                          "divisions": sum(_name(node) == "div" for unit in units for node in unit.iter()),
                          "paragraphs": sum(_name(node) == "p" for unit in units for node in unit.iter()),
                          "linked_divisions": sum(item["disposition"] == "source-division-link" for item in inventory),
                          "multiple_targets": len(references)})
    return inventory, references, warnings


def _lightfoot_source_digest(unit: object, paths: dict) -> tuple[str, int, int]:
    """Bind every source node, attribute, text span and tail, including private IDs."""
    digest = hashlib.sha256()
    node_count = attribute_count = 0
    for node in unit.iter():
        attributes = _attrs(node)
        record = {"tei_path": paths[node], "element": _name(node), "attributes": attributes,
                  "text": node.text or "", "tail": node.tail or ""}
        digest.update(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        node_count += 1
        attribute_count += len(attributes)
    return digest.hexdigest(), node_count, attribute_count


def _lightfoot_evidence(units: list, paths: dict, family: str = "lightfoot") -> tuple[list[dict], list[dict], list[dict]]:
    inventory: list[dict] = []
    references: list[dict] = []
    for unit in units:
        source_digest, nodes, attributes = _lightfoot_source_digest(unit, paths)
        inventory.append({"tei_path": paths[unit], "disposition": "complete-source-region",
                          "source_type": unit.get("type"), "source_id": unit.get(XML_ID),
                          "source_tree_sha256": source_digest, "source_nodes": nodes,
                          "source_attributes": attributes})
        for node in unit.iter():
            if node.get("corresp") is not None:
                references.append({"tei_path": paths[node], "original_target": node.get("corresp"),
                                   "normalization_status": "source-literal-private"})
    inventory.append({"disposition": "source-native-profile", "family": family,
                      "region_count": len(units),
                      "total_nodes": sum(item["source_nodes"] for item in inventory),
                      "total_attributes": sum(item["source_attributes"] for item in inventory),
                      "private_correspondences": len(references)})
    return inventory, references, []


def _findlay_private_evidence(units: list, paths: dict, expected: tuple) -> tuple[list[dict], list[dict], list[dict]]:
    """Account for every original source node and every withheld source attribute."""
    unit = units[0]
    tree_hash, node_count, attr_count = _lightfoot_source_digest(unit, paths)
    carriers = []
    comment_count = omitted_count = 0
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
    xml_space = "{http://www.w3.org/XML/1998/namespace}space"
    for node in unit.iter():
        attrs = {}
        for key, value in node.attrib.items():
            if key in ("ana", "corresp", xml_space) or _name(node) == "index" and key == xml_lang:
                attrs[("xml:" + key.rsplit("}", 1)[-1]) if key.startswith("{") else key] = value
                omitted_count += 1
        if not attrs:
            continue
        if "corresp" in attrs and not attrs["corresp"].startswith("urn:source-xpath:"):
            raise PipelineError("Findlay private source-location annotation differs")
        if "xml:space" in attrs and (_name(node) != "div" or attrs["xml:space"] != "preserve"):
            raise PipelineError("Findlay source whitespace declaration differs")
        annotation = attrs.get("ana", "")
        if "source-comment-sha256" in annotation:
            if (_name(node) != "anchor" or not re.fullmatch(r"urn:source-comment-sha256:[0-9a-f]{64}", annotation)):
                raise PipelineError("Findlay source comment carrier differs")
            comment_count += 1
        carriers.append({"tei_path": paths[node], "element": _name(node),
                         "disposition": "source-annotation-retained-privately", "attributes": attrs})
    if (node_count, omitted_count, comment_count) != (expected[5], expected[6], expected[7]):
        raise PipelineError(f"Findlay complete source-tree or private-carrier counts differ: "
                            f"{(node_count, omitted_count, comment_count)} != "
                            f"{(expected[5], expected[6], expected[7])}")
    inventory = [{"tei_path": paths[unit], "disposition": "complete-retained-source-member",
                  "source_tree_sha256": tree_hash, "source_nodes": node_count,
                  "source_attributes": attr_count, "withheld_attribute_count": omitted_count,
                  "source_comment_carriers": comment_count}, *carriers]
    return inventory, [], [{"reason": "source-annotations-and-whitespace-retained-privately",
                            "carrier_count": len(carriers), "source_comment_carriers": comment_count}]


def _findlay_public_et(unit: ET.Element) -> ET.Element:
    copy = deepcopy(unit)
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
    xml_space = "{http://www.w3.org/XML/1998/namespace}space"
    for node in copy.iter():
        for key in ("ana", "corresp", xml_space):
            node.attrib.pop(key, None)
        if node.tag == f"{{{TEI}}}index":
            node.attrib.pop(xml_lang, None)
    return copy


def _findlay_public_lxml(unit: etree._Element) -> etree._Element:
    clone = deepcopy(unit)
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
    xml_space = "{http://www.w3.org/XML/1998/namespace}space"
    for node in clone.iter():
        if node.get("ana") is not None:
            del node.attrib["ana"]
        if node.get("corresp") is not None:
            del node.attrib["corresp"]
        if node.get(xml_space) is not None:
            del node.attrib[xml_space]
        if etree.QName(node).localname == "index" and node.get(xml_lang) is not None:
            del node.attrib[xml_lang]
    return clone


def _source_binding(header: dict) -> dict[str, str]:
    result = {"source_url": header["source_url"], "retained_sha256": header["retained_sha256"]}
    if header.get("source_sha256"):
        result["source_sha256"] = header["source_sha256"]
    return result


def _row(metadata: dict, structure: dict, text: str, ordinal: int) -> dict:
    identity = metadata["acceptance"]["identity"]
    return {
        "work_id": identity["work_id"], "textual_form_id": identity["textual_form_id"],
        "edition_id": identity["edition_id"],
        "record_id": f"{identity['edition_id']}:native-commentary-{ordinal:06d}",
        "sequence": ordinal, "category": "commentary", "language": metadata["language"],
        "text": text, "representation_revision": metadata["acceptance"]["representation_revision"]["id"],
        "provenance": {"edition_title": metadata["edition"].title},
        "content_format": "ocd-native-content-v1", "structure": [structure],
        "locator": {"kind": "native-unit", "text_part": "body", "unit": ordinal},
    }


def _jfb_binding_header(root: object, *, independent: bool, family: str = "jfb") -> dict:
    """Read only the added acceptance binding; retain the historical header whole."""
    from ocd_kernel.projection.categories import commentary as core
    from xml.etree import ElementTree as ET
    header = copy.deepcopy(root.find(f"{{{TEI}}}teiHeader"))
    description = header.find(f"{{{TEI}}}fileDesc/{{{TEI}}}sourceDesc")
    bindings = [node for node in description if node.get("type") == "ocd-acceptance-binding"]
    historical = [node for node in description if node.get("type") != "ocd-acceptance-binding"]
    if len(bindings) != 1 or len(historical) != 1:
        raise PipelineError("JFB requires exact historical and acceptance source descriptions")
    original = historical[0]
    expected = {"jfb": (("/api/c/jamieson-fausset-brown/books.json",), "5d934812f90505a095968bda4e17729f4d9edf51a72d452ad4754c49ec71303f"),
                "gill": (("/api/c/john-gill/books.json", "/api/c/john-gill/profiles.json"), "b874cf092641aa83722204ef765750cda69c1841cf355a57fc3d5d2134129549"),
                "henry": (("/api/c/matthew-henry/books.json",), "2114c8c37edd7f4c0e5a26cb3923ac49bd9e15f169e4f3023d470d42e545d0dc"),
                "clarke": (("/api/c/adam-clarke/books.json",), "27a8fdaf08938acd530d7c39ca207b3942183ab01664a5fad3ea9dd4c98cde55"),
                "keil": (("/api/c/keil-delitzsch/books.json", "/api/c/keil-delitzsch/profiles.json"),
                         "c1162721788883e57518966d52ad770fe20ed19bd354ed02dc71cb102d80a789")}[family]
    if (_name(original) != "bibl" or tuple(node.get("target") for node in _children(original, "ptr")) != expected[0]
            or len(_children(original, "idno")) != 1
            or _children(original, "idno")[0].get("type") != "sha256"
            or _children(original, "idno")[0].text != expected[1]):
        raise PipelineError("JFB historical source description differs")
    description.remove(original)
    view = etree.Element(f"{{{TEI}}}TEI") if independent else ET.Element(f"{{{TEI}}}TEI")
    view.append(header)
    return core._checker_header(view, _paths(view)) if independent else core._header(view)


_GILL_PRIVATE_METADATA = {"book-metadata", "number-of-verses", "chapter-link"}


def _gill_public_unit(unit: object) -> object:
    """Keep source metadata in the complete master and private receipt."""
    public = copy.deepcopy(unit)
    for parent in list(public.iter()):
        for child in list(parent):
            if _name(child) == "note" and child.get("type") in _GILL_PRIVATE_METADATA:
                _require_blank(child.tail, "Gill private source metadata tail")
                parent.remove(child)
    return public


def _projection(metadata: dict, family: str, *, independent: bool) -> dict:
    from ocd_kernel.projection.categories import commentary as core

    path = metadata["master_path"]
    raw = Path(path).read_bytes()
    if independent:
        root, _raw, paths, _parents = core._checker_parse(path)
        matches = root.xpath("./tei:text/tei:body", namespaces={"tei": TEI})
        if len(matches) != 1:
            raise PipelineError("accepted native commentary requires one body")
        body = matches[0]
        units = _profile(body, family)
        header = _jfb_binding_header(root, independent=True, family=family) if family in {"jfb", "gill", "henry", "clarke", "keil"} and any(node.get("type") == "ocd-acceptance-binding" for node in root.iter()) else core._checker_header(root, paths)
    else:
        root, _raw = core._read_root(path)
        paths = _paths(root)
        body = root.find(f"{{{TEI}}}text/{{{TEI}}}body")
        if body is None:
            raise PipelineError("accepted native commentary requires one body")
        units = _profile(body, family)
        header = _jfb_binding_header(root, independent=False, family=family) if family in {"jfb", "gill", "henry", "clarke", "keil"} and any(node.get("type") == "ocd-acceptance-binding" for node in root.iter()) else core._header(root)
    _envelope(root, body, units, family)
    core._validate_accepted_header(header, metadata)
    findlay_expected = None
    if family == "findlay":
        findlay_expected = _findlay_expected(metadata["acceptance"])
        if units[0].get(XML_ID) != findlay_expected[3] or header["source_url"] != findlay_expected[4]:
            raise PipelineError("Findlay member identity or accepted source URL differs")

    rows = []
    anchors = []
    inventory = []
    for ordinal, unit in enumerate(units, 1):
        public_unit = _gill_public_unit(unit) if family in {"gill", "keil"} else unit
        if independent:
            if family == "findlay":
                fragment = etree.tostring(_findlay_public_lxml(public_unit), encoding="utf-8", with_tail=False)
                structure, text = observe_content(fragment, source_base=header["source_url"])
            else:
                fragment = etree.tostring(public_unit, encoding="utf-8", with_tail=False)
                structure, text = observe_content(fragment)
        else:
            if family == "findlay":
                structure = native_content.project_content(_findlay_public_et(public_unit),
                                                           source_base=header["source_url"])
            else:
                structure = native_content.project_content(public_unit)
            text = native_content.readable_content(structure)
        row = _row(metadata, structure, text, ordinal)
        rows.append(row)
        anchor = {"record_id": row["record_id"], "tei_path": paths[unit], "text_sha256": row_text_hash(text),
                  "source_order": ordinal, "locator": row["locator"]}
        anchors.append(anchor)
        inventory.append(_unit_inventory(unit, structure, paths[unit]))
    if family == "findlay":
        special_inventory, references, warnings = _findlay_private_evidence(units, paths, findlay_expected)
    elif family in {"lightfoot", "jfb", "gill", "henry", "clarke", "keil"}:
        special_inventory, references, warnings = _lightfoot_evidence(units, paths, family)
    else:
        special_inventory, references, warnings = _evidence(units, paths, family)
    if family in {"gill", "keil"}:
        special_inventory.extend({"tei_path": paths[node], "disposition": "source-metadata-private", "attributes": _attrs(node), "source_text_sha256": _sha((node.text or "").encode("utf-8"))}
                                 for unit in units for node in unit.iter()
                                 if _name(node) == "note" and node.get("type") in _GILL_PRIVATE_METADATA)
    inventory.extend(special_inventory)
    result = {
        "rows": rows, "anchors": anchors, "inventory": inventory,
        "references": references, "warnings": warnings, "exclusions": [], "unsupported": [],
        "master_sha256": _sha(raw), "scope_id": None,
        "mapping_version": FINDLAY_VERSION if family == "findlay" else LIGHTFOOT_VERSION if family == "lightfoot" else KEIL_VERSION if family == "keil" else VERSION,
        "assembler_version": core.ASSEMBLER_VERSION, "source_binding": _source_binding(header),
        "authority": metadata["authority"],
    }
    public_identity = {key: metadata["acceptance"]["identity"][key] for key in core._IDENTITY_KEYS}
    if independent:
        # The checker constructs every row and receipt field from an lxml walk.
        result["receipt"] = core.build_commentary_receipt(result, identity=public_identity)
    else:
        core._validate_rows(rows)
        result["receipt"] = core.build_commentary_receipt(result, identity=public_identity)
    return result


def project(metadata: dict, family: str) -> dict:
    from . import calvin_collection_source_native
    if family == calvin_collection_source_native.FAMILY:
        return calvin_collection_source_native.project(metadata, family)
    if family == "ocd-commentary-lib061-retained-toml-members-v1":
        from . import lib061_toml_native
        return lib061_toml_native.project(metadata)
    if family == JOSHUA_FAMILY:
        from . import calvin_joshua_source_native
        return calvin_joshua_source_native.project(metadata, family)
    return _projection(metadata, family, independent=False)


def _compare(expected: dict, rows: object, receipt: object) -> list[str]:
    from ocd_kernel.projection.categories import commentary as core

    if isinstance(rows, dict):
        if receipt is None:
            receipt = rows.get("receipt")
        rows = rows.get("rows")
    if not isinstance(rows, list):
        return ["native commentary rows must be a list"]
    errors = []
    if len(rows) != len(expected["rows"]):
        errors.append(f"native commentary row count differs: {len(rows)} != {len(expected['rows'])}")
    for ordinal, (actual, wanted) in enumerate(zip(rows, expected["rows"]), 1):
        if actual != wanted:
            errors.append(f"native commentary row {ordinal} differs")
            if len(errors) > 30:
                break
    if receipt != expected["receipt"]:
        errors.append("native commentary private receipt differs")
    if errors:
        return errors
    try:
        core._validate_rows(rows)
    except (PipelineError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors



def verify(metadata: dict, family: str, rows: object, receipt: object) -> list[str]:
    from . import calvin_collection_source_native
    if family == calvin_collection_source_native.FAMILY:
        return calvin_collection_source_native.verify(metadata, family, rows, receipt)
    if family == "ocd-commentary-lib061-retained-toml-members-v1":
        from . import lib061_toml_native
        return lib061_toml_native.verify(metadata, rows, receipt)
    if family == JOSHUA_FAMILY:
        from . import calvin_joshua_source_native
        return calvin_joshua_source_native.verify(metadata, family, rows, receipt)
    try:
        expected = _projection(metadata, family, independent=True)
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]
    return _compare(expected, rows, receipt)
