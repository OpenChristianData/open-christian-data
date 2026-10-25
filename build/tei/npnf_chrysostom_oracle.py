"""Producer-independent retained-source oracle for LIB-043 Chrysostom."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-npnf-chrysostom-source-to-tei-oracle"
ORACLE_VERSION = "1"
PROFILE_ID = "npnf-chrysostom-110-111-112-114-seven-work-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
DOCTYPE = (
    '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" '
    '"http://www.ccel.org/dtd/ThML10.dtd">'
)
SOURCE_SPECS = (
    {
        "name": "npnf110",
        "path": "raw/ccel/npnf1/npnf110.xml",
        "bytes": 3_956_654,
        "sha256": "e110c98b1f444147bf7baf79e46e56ae6c6a1f0b2983e6fc52f2356fac7f858f",
        "assigned_div1": ("iii",),
        "works": (("iii", "chrysostom-homilies-on-matthew"),),
    },
    {
        "name": "npnf111",
        "path": "raw/ccel/npnf1/npnf111.xml",
        "bytes": 5_349_065,
        "sha256": "46072a7fefb80b4b7ea68544b46c13fc1785bd29d99834fd2f867f8aa5e14f08",
        "assigned_div1": ("vi", "vii"),
        "works": (
            ("vi", "chrysostom-homilies-on-acts"),
            ("vii", "chrysostom-homilies-on-romans"),
        ),
    },
    {
        "name": "npnf112",
        "path": "raw/ccel/npnf1/npnf112.xml",
        "bytes": 3_253_154,
        "sha256": "b8b345e060625cdf495e888322d88e922f66e686863e818a978204c5f564a4dd",
        "assigned_div1": ("iv", "v"),
        "works": (
            ("iv", "chrysostom-homilies-on-1-corinthians"),
            ("v", "chrysostom-homilies-on-2-corinthians"),
        ),
    },
    {
        "name": "npnf114",
        "path": "raw/ccel/npnf1/npnf114.xml",
        "bytes": 4_728_349,
        "sha256": "b130406978fbceb7bcd0774b0e8b09905f35a020a2300c1baf02f314a2d5a70a",
        "assigned_div1": ("iv", "v"),
        "works": (
            ("iv", "chrysostom-homilies-on-john"),
            ("v", "chrysostom-homilies-on-hebrews"),
        ),
    },
)
ASSIGNED = tuple(
    (str(spec["name"]), scope, work_id)
    for spec in SOURCE_SPECS
    for scope, work_id in spec["works"]
)
EXPECTED_CENSUS = {
    "elements": 58_867,
    "attributes": 155_252,
    "text_nodes": 43_635,
    "tail_nodes": 49_691,
    "characters": 10_468_284,
    "non_ascii_characters": 192_872,
}
EXPECTED_TAG_COUNTS = {
    "br": 20,
    "div1": 7,
    "div2": 381,
    "div3": 3,
    "i": 2_299,
    "note": 9_477,
    "p": 22_428,
    "pb": 2_027,
    "scripCom": 367,
    "scripRef": 11_490,
    "span": 10_364,
    "sup": 4,
}
APPARATUS = {
    "npnf110": ("iii.i", "iii.ii", "iii.iii"),
    "npnf111": ("vii.i", "vii.ii"),
    "npnf112": ("iv.i",),
    "npnf114": ("iv.i", "iv.ii", "v.i", "v.ii", "v.iii", "v.iv"),
}
WORK_TITLES = {
    "chrysostom-homilies-on-1-corinthians": "Homilies on the First Epistle of Paul to the Corinthians",
    "chrysostom-homilies-on-2-corinthians": "Homilies on the Second Epistle of Paul to the Corinthians",
    "chrysostom-homilies-on-acts": "Homilies on the Acts of the Apostles",
    "chrysostom-homilies-on-hebrews": "Homilies on the Epistle to the Hebrews",
    "chrysostom-homilies-on-john": "Homilies on the Gospel of St. John",
    "chrysostom-homilies-on-matthew": "Homilies on the Gospel of Matthew",
    "chrysostom-homilies-on-romans": "Homilies on the Epistle of Paul to the Romans",
}
TAG_MAP = {
    "br": "lb",
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "i": "hi",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "scripCom": "ref",
    "scripRef": "ref",
    "span": "seg",
    "sup": "hi",
}
LANGUAGE_MAP = {"DE": "de", "EL": "grc", "HE": "he"}
RIGHTS_STATEMENT = (
    "The retained CCEL headers state Public Domain. CCEL permits parsing its "
    "ThML; do not sell CCEL files or derivatives of CCEL formatting. "
    "Attribution is included in README.source.md. Human acceptance and "
    "publication remain absent."
)
PRINT_SOURCE = (
    "Retained NPNF First Series title matter for volumes X, XI, XII, and XIV; "
    "T&T Clark and Wm. B. Eerdmans title statements with CCEL print-source "
    "metadata; no print collation performed"
)
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
CREDIT_SPECS = {
    "chrysostom-homilies-on-matthew": (
        ("George Prevost", "translator", "npnf110", "iii.i-p8", "george prevost"),
        (
            "M. B. Riddle",
            "reviser, annotator, and introductory essay author",
            "npnf110",
            "iii.i-p11",
            "m. b. riddle",
        ),
    ),
    "chrysostom-homilies-on-acts": (
        ("J. Walker", "translator", "npnf111", "iii-p8", "j. walker"),
        ("J. Sheppard", "translator", "npnf111", "iii-p10", "j. sheppard"),
        ("H. Browne", "translator", "npnf111", "iii-p12", "h. browne"),
        (
            "George B. Stevens",
            "reviser and annotator",
            "npnf111",
            "iii-p15",
            "george b. stevens",
        ),
    ),
    "chrysostom-homilies-on-romans": (
        (
            "J. B. Morris",
            "translator and annotator",
            "npnf111",
            "vii.i-p12",
            "j.b. morris",
        ),
        ("W. H. Simcox", "translation reviser", "npnf111", "vii.i-p14", "w. h. simcox"),
        (
            "George B. Stevens",
            "reviser and annotator",
            "npnf111",
            "vii-p13",
            "george b. stevens",
        ),
    ),
    "chrysostom-homilies-on-1-corinthians": (
        (
            "Talbot W. Chambers",
            "Oxford translation reviser and additional annotator",
            "npnf112",
            "ii-p8",
            "talbot w. chambers",
        ),
    ),
    "chrysostom-homilies-on-2-corinthians": (
        (
            "Talbot W. Chambers",
            "Oxford translation reviser and additional annotator",
            "npnf112",
            "ii-p8",
            "talbot w. chambers",
        ),
    ),
    "chrysostom-homilies-on-john": (
        ("G. T. Stupart", "translator", "npnf114", "iv.ii-p11", "g. t. stupart"),
        (
            "J. G. Hickley",
            "carried the translation through the press",
            "npnf114",
            "iv.ii-p11",
            "j. g. hickley",
        ),
        (
            "Philip Schaff",
            "editor with additional notes",
            "npnf114",
            "iv.i-p6",
            "philip schaff",
        ),
    ),
    "chrysostom-homilies-on-hebrews": (
        ("T. Keble", "translator", "npnf114", "v.ii-p3", "t. keble"),
        (
            "T. Keble's brother, the Vicar of Hursley",
            "translation reviser",
            "npnf114",
            "v.ii-p3",
            "his brother, the vicar of hursley",
        ),
        (
            "Frederic Gardiner",
            "reviser, introduction author, and annotator",
            "npnf114",
            "v.i-p6",
            "frederic gardiner",
        ),
    ),
}
HEADER_CONTRIBUTORS = (
    ("Philip Schaff", "series editor"),
    ("George Prevost", "Matthew translator"),
    ("M. B. Riddle", "Matthew reviser and essay author"),
    ("J. Walker; J. Sheppard; H. Browne", "Acts translators"),
    ("J. B. Morris", "Romans translator and annotator"),
    ("W. H. Simcox", "Romans translation reviser"),
    ("George B. Stevens", "Acts and Romans reviser"),
    ("Talbot W. Chambers", "Corinthians translation reviser and annotator"),
    ("G. T. Stupart", "John translator"),
    ("J. G. Hickley", "John press preparation"),
    ("T. Keble", "Hebrews translator"),
    ("T. Keble's brother, the Vicar of Hursley", "Hebrews translation reviser"),
    ("Frederic Gardiner", "Hebrews reviser, introduction author, and annotator"),
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        record: dict[str, object] = {}
        for key, value in pairs:
            if key in record:
                raise ValueError(f"{label} has duplicate key {key!r}")
            record[key] = value
        return record

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _source_tree(content: bytes) -> etree._ElementTree:
    return etree.parse(
        io.BytesIO(content),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _structure(
    tree: etree._ElementTree, spec: Mapping[str, object]
) -> tuple[list[etree._Element], list[etree._Element]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError(f"retained {spec['name']} source lacks ThML.body")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    by_id = {node.get("id"): node for node in top}
    assigned = tuple(str(value) for value in spec["assigned_div1"])
    if len(by_id) != len(top) or any(scope not in by_id for scope in assigned):
        raise ValueError(f"retained {spec['name']} division identity drift")
    return top, [by_id[scope] for scope in assigned]


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        if not isinstance(current.tag, str):
            break
        parent = current.getparent()
        if parent is None:
            break
        peers = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.tag == current.tag
        ]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _target_tag(source: etree._Element) -> str:
    if source.tag == "span" and source.get("lang"):
        return "foreign"
    if source.tag == "scripCom":
        parent = source.getparent()
        return (
            "p" if parent is not None and str(parent.tag).startswith("div") else "seg"
        )
    return TAG_MAP[str(source.tag)]


def _expected_attributes(
    source: etree._Element,
    member: str,
    number: int,
    work_id: str,
    *,
    is_work_root: bool,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = source.get("id")
    attrs = {
        "xml:id": f"{member}-"
        + (_safe_id(source_id) if source_id else f"feature-{number:05d}")
    }
    dispositions: list[dict[str, str]] = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination, method = "@xml:id", "deterministic-member-prefix"
        elif name == "n" and tag in {"div1", "div2", "div3", "note", "pb"}:
            attrs["n"], destination = value, "@n"
        elif name == "type" and tag in {"div1", "div2", "div3"}:
            attrs["type"], destination = value, "@type"
        elif name == "class":
            attrs["rend"], destination = value, "@rend"
        elif name == "place" and tag == "note":
            attrs["place"], destination = value, "@place"
        elif name == "href" and tag == "pb":
            attrs["facs"], destination = value, "@facs"
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"], destination = value, "@cRef"
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"], destination = value, "@target"
        elif name == "passage" and tag == "scripCom":
            attrs["n"], destination = value, "@n"
        elif name == "osisRef" and tag == "scripCom":
            attrs["corresp"], destination = value, "@corresp"
        elif name == "lang" and tag == "span":
            if value not in LANGUAGE_MAP:
                raise ValueError(f"unsupported retained language code {value!r}")
            attrs["xml:lang"] = LANGUAGE_MAP[value]
            destination, method = "@xml:lang", "declared-language-code-map"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        dispositions.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    elif tag == "scripCom":
        attrs["rend" if _target_tag(source) == "p" else "type"] = "scripture-commentary"
    if is_work_root:
        attrs["corresp"] = f"#{member}:{source.get('id')}:{work_id}"
    return attrs, dispositions


def _normalize_attributes(node: etree._Element) -> dict[str, str]:
    return {
        (
            "xml:id"
            if key == f"{{{XML_NS}}}id"
            else "xml:lang"
            if key == f"{{{XML_NS}}}lang"
            else key
        ): value
        for key, value in node.attrib.items()
    }


def _expected_rows(
    selected: Mapping[str, list[etree._Element]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    feature_by_node: dict[int, str] = {}
    target_by_node: dict[int, str] = {}
    work_ordinal = 0

    def visit(
        source: etree._Element,
        *,
        member: str,
        work_id: str,
        is_work_root: bool,
    ) -> None:
        nonlocal work_ordinal
        number = len(rows) + 1
        feature_id = f"npnf-chrysostom-feature-{number:05d}"
        attrs, dispositions = _expected_attributes(
            source,
            member,
            number,
            work_id,
            is_work_root=is_work_root,
        )
        source_parent = source.getparent()
        if is_work_root:
            work_ordinal += 1
            parent_target_id = "npnf-chrysostom-assigned-body"
            child_ordinal = work_ordinal
            parent_feature_id = None
        else:
            if source_parent is None or id(source_parent) not in target_by_node:
                raise ValueError("retained source hierarchy drift")
            parent_target_id = target_by_node[id(source_parent)]
            parent_feature_id = feature_by_node[id(source_parent)]
            siblings = [child for child in source_parent if isinstance(child.tag, str)]
            child_ordinal = (
                siblings.index(source)
                + 1
                + (1 if source_parent.get("title") is not None else 0)
            )
        target_id = attrs["xml:id"]
        feature_by_node[id(source)] = feature_id
        target_by_node[id(source)] = target_id
        rows.append(
            {
                "ordinal": number,
                "feature_id": feature_id,
                "member": member,
                "work_id": work_id,
                "source_selector": _selector(source),
                "source_tag": source.tag,
                "source_xml_id": source.get("id"),
                "source_attributes": dict(source.attrib),
                "text_present": source.text is not None,
                "text_sha256": _sha((source.text or "").encode("utf-8")),
                "tail_present": source.tail is not None,
                "tail_sha256": _sha((source.tail or "").encode("utf-8")),
                "tei_tag": _target_tag(source),
                "tei_xml_id": target_id,
                "tei_parent_id": parent_target_id,
                "tei_child_ordinal": child_ordinal,
                "tei_attributes": attrs,
                "attribute_dispositions": dispositions,
                "tei_selector": f"#{target_id}",
                "parent_feature_id": parent_feature_id,
                "source_title_head": source.get("title")
                if str(source.tag).startswith("div")
                else None,
                "disposition": "represented",
            }
        )
        for child in source:
            if not isinstance(child.tag, str):
                raise ValueError("assigned source comment or PI drift")
            if child.tag not in TAG_MAP:
                raise ValueError(f"unsupported retained source element {child.tag!r}")
            visit(
                child,
                member=member,
                work_id=work_id,
                is_work_root=False,
            )

    for spec in SOURCE_SPECS:
        member = str(spec["name"])
        for division, (scope, work_id) in zip(
            selected[member], spec["works"], strict=True
        ):
            if division.get("id") != scope:
                raise ValueError(f"retained {member} assigned order drift")
            visit(
                division,
                member=member,
                work_id=work_id,
                is_work_root=True,
            )
    return rows


def _verify_node(
    source: etree._Element,
    target: etree._Element,
    *,
    member: str,
    work_id: str,
    number: list[int],
    is_work_root: bool,
) -> None:
    number[0] += 1
    expected_attrs, _ = _expected_attributes(
        source,
        member,
        number[0],
        work_id,
        is_work_root=is_work_root,
    )
    if (
        etree.QName(target).namespace != TEI_NS
        or etree.QName(target).localname != _target_tag(source)
        or _normalize_attributes(target) != expected_attrs
    ):
        raise ValueError("Chrysostom TEI tag or attribute drift")
    children = [child for child in target if isinstance(child.tag, str)]
    offset = 0
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        if (
            not children
            or children[0].tag != f"{{{TEI_NS}}}head"
            or children[0].text != title
            or (children[0].tail or "") != ""
            or _normalize_attributes(children[0])
            or list(children[0])
        ):
            raise ValueError("Chrysostom TEI division title drift")
        offset = 1
    if (target.text or "") != (source.text or "") or (target.tail or "") != (
        source.tail or ""
    ):
        raise ValueError("Chrysostom TEI direct text or tail drift")
    source_children = [child for child in source if isinstance(child.tag, str)]
    if len(children) - offset != len(source_children):
        raise ValueError("Chrysostom TEI omission duplication or invention")
    for source_child, target_child in zip(
        source_children, children[offset:], strict=True
    ):
        _verify_node(
            source_child,
            target_child,
            member=member,
            work_id=work_id,
            number=number,
            is_work_root=False,
        )


def _tei_element(
    local_name: str, attrs: Mapping[str, str] | None = None
) -> etree._Element:
    element = etree.Element(f"{{{TEI_NS}}}{local_name}", nsmap={None: TEI_NS})
    for name, value in (attrs or {}).items():
        if name == "xml:id":
            element.set(f"{{{XML_NS}}}id", value)
        else:
            element.set(name, value)
    return element


def _expected_header(source_members: list[dict[str, object]]) -> etree._Element:
    header = _tei_element("teiHeader")
    file_desc = _tei_element("fileDesc")
    title_stmt = _tei_element("titleStmt")
    title = _tei_element("title")
    title.text = "NPNF First Series Chrysostom volumes X, XI, XII, and XIV — seven assigned works"
    title_stmt.append(title)
    author = _tei_element("author")
    author.text = "John Chrysostom"
    title_stmt.append(author)
    for name, role in HEADER_CONTRIBUTORS:
        resp_stmt = _tei_element("respStmt")
        resp = _tei_element("resp")
        resp.text = role
        contributor = _tei_element("name")
        contributor.text = name
        resp_stmt.extend((resp, contributor))
        title_stmt.append(resp_stmt)
    publication = _tei_element("publicationStmt")
    publisher = _tei_element("publisher")
    publisher.text = "Open Christian Data"
    availability = _tei_element("availability", {"status": "restricted"})
    rights = _tei_element("p")
    rights.text = RIGHTS_STATEMENT
    availability.append(rights)
    publication.extend((publisher, availability))
    source_desc = _tei_element("sourceDesc")
    bibl = _tei_element("bibl")
    pointer = _tei_element("ptr", {"target": "https://www.ccel.org/ccel/schaff/"})
    identifier = _tei_element("idno", {"type": "sha256"})
    identifier.text = _sha(_canonical(source_members))
    note = _tei_element("note", {"type": "print-source"})
    note.text = PRINT_SOURCE
    bibl.extend((pointer, identifier, note))
    source_desc.append(bibl)
    file_desc.extend((title_stmt, publication, source_desc))
    header.append(file_desc)
    return header


def _verify_document_shell(content: bytes, tree: etree._ElementTree) -> None:
    if not content.startswith(b"<?xml version='1.0' encoding='UTF-8'?>\n"):
        raise ValueError("TEI document prolog drift")
    if b"<!DOCTYPE" in content[:512] or tree.docinfo.doctype:
        raise ValueError("TEI document prolog drift")
    root = tree.getroot()
    if root.getprevious() is not None or root.getnext() is not None:
        raise ValueError("TEI document sibling drift")
    for node in root.iter():
        if not isinstance(node.tag, str):
            raise ValueError("TEI comment or processing-instruction invention")
        if etree.QName(node).namespace != TEI_NS:
            raise ValueError("TEI element namespace drift")
        if set(node.nsmap) != {None} or node.nsmap.get(None) != TEI_NS:
            raise ValueError("TEI namespace declaration drift")
        for name in node.attrib:
            if etree.QName(name).namespace not in {None, XML_NS}:
                raise ValueError("TEI attribute namespace drift")


def _verify_tei(
    sources: Mapping[str, etree._ElementTree],
    selected: Mapping[str, list[etree._Element]],
    source_members: list[dict[str, object]],
    content: bytes,
) -> None:
    try:
        tree = etree.parse(
            io.BytesIO(content),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("Chrysostom TEI is not well-formed XML") from exc
    _verify_document_shell(content, tree)
    root = tree.getroot()
    if (
        root.tag != f"{{{TEI_NS}}}TEI"
        or _normalize_attributes(root) != {"xml:id": "npnf-chrysostom-lib043"}
        or (root.text or "") != ""
        or (root.tail or "") != ""
    ):
        raise ValueError("Chrysostom TEI root drift")
    children = [child for child in root if isinstance(child.tag, str)]
    if [etree.QName(child).localname for child in children] != ["teiHeader", "text"]:
        raise ValueError("Chrysostom TEI root topology drift")
    if etree.tostring(children[0]) != etree.tostring(_expected_header(source_members)):
        raise ValueError("Chrysostom complete TEI header drift")
    text = children[1]
    text_children = [child for child in text if isinstance(child.tag, str)]
    if (
        _normalize_attributes(text)
        or (text.text or "") != ""
        or (text.tail or "") != ""
        or [etree.QName(child).localname for child in text_children] != ["body"]
    ):
        raise ValueError("Chrysostom TEI text topology drift")
    body = text_children[0]
    if (
        _normalize_attributes(body) != {"xml:id": "npnf-chrysostom-assigned-body"}
        or (body.text or "") != ""
        or (body.tail or "") != ""
    ):
        raise ValueError("Chrysostom TEI body drift")
    target_divisions = [child for child in body if isinstance(child.tag, str)]
    if len(target_divisions) != 7:
        raise ValueError("Chrysostom assigned work count drift")
    number = [0]
    target_index = 0
    for spec in SOURCE_SPECS:
        member = str(spec["name"])
        for source_division, (_, work_id) in zip(
            selected[member], spec["works"], strict=True
        ):
            _verify_node(
                source_division,
                target_divisions[target_index],
                member=member,
                work_id=work_id,
                number=number,
                is_work_root=True,
            )
            target_index += 1
    if number[0] != 58_867:
        raise ValueError("Chrysostom TEI feature count drift")
    try:
        compiled_schema().assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("Chrysostom candidate fails TEI P5 validation") from exc


def _census(nodes: list[etree._Element]) -> dict[str, int]:
    return {
        "elements": len(nodes),
        "attributes": sum(len(node.attrib) for node in nodes),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len((node.text or "") + (node.tail or "")) for node in nodes),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in nodes
        ),
    }


def _comment_record(comment: etree._Comment, ordinal: int) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "text": comment.text or "",
        "text_sha256": _sha((comment.text or "").encode("utf-8")),
        "tail": comment.tail or "",
        "tail_sha256": _sha((comment.tail or "").encode("utf-8")),
    }


def _node_text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained credit evidence {source_id!r} drift")
    return " ".join("".join(nodes[0].itertext()).split())


def _credits(
    trees: Mapping[str, etree._ElementTree],
) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for work_id, claims in CREDIT_SPECS.items():
        result[work_id] = []
        for name, role, member, source_id, required in claims:
            evidence = _node_text(trees[member], source_id)
            if required.casefold() not in evidence.casefold():
                raise ValueError(f"retained contributor evidence for {name} drift")
            result[work_id].append(
                {
                    "name": name,
                    "role": role,
                    "source_member": member,
                    "source_xml_id": source_id,
                    "evidence_text": evidence,
                }
            )
    return result


def _expected_evidence(
    trees: Mapping[str, etree._ElementTree],
    tops: Mapping[str, list[etree._Element]],
    selected: Mapping[str, list[etree._Element]],
    rows: list[dict[str, object]],
    source_manifest: SourceManifest,
) -> tuple[dict[str, object], dict[str, object], bytes]:
    source_members: list[dict[str, object]] = []
    document_accounting: list[dict[str, object]] = []
    member_accounting: list[dict[str, object]] = []
    division_accounting: list[dict[str, object]] = []
    source_census: dict[str, dict[str, dict[str, int]]] = {}
    excluded_index_comment_count = 0
    for spec in SOURCE_SPECS:
        member = str(spec["name"])
        tree = trees[member]
        assigned_ids = {str(value) for value in spec["assigned_div1"]}
        assigned_nodes = [
            node
            for division in selected[member]
            for node in division.iter()
            if isinstance(node.tag, str)
        ]
        assigned_identity = {id(node) for node in assigned_nodes}
        complete_nodes = [
            node for node in tree.getroot().iter() if isinstance(node.tag, str)
        ]
        excluded_nodes = [
            node for node in complete_nodes if id(node) not in assigned_identity
        ]
        source_census[member] = {
            "complete_document": _census(complete_nodes),
            "assigned_scope": _census(assigned_nodes),
            "excluded_shell_front_and_indexes": _census(excluded_nodes),
        }
        prolog_comments = tree.xpath("/comment()")
        if tree.docinfo.doctype != DOCTYPE or len(prolog_comments) != 2:
            raise ValueError(f"retained {member} document shell drift")
        embedded_comments = [
            comment
            for comment in tree.xpath("//comment()")
            if comment.getparent() is not None
        ]
        assigned_comments = []
        excluded_comments = []
        for comment in embedded_comments:
            division = next(
                (
                    ancestor
                    for ancestor in comment.iterancestors()
                    if ancestor.tag == "div1"
                ),
                None,
            )
            if division is not None and division.get("id") in assigned_ids:
                assigned_comments.append(comment)
            else:
                excluded_comments.append(comment)
        if assigned_comments:
            raise ValueError(f"retained {member} assigned comment drift")
        excluded_index_comment_count += len(excluded_comments)
        document_accounting.append(
            {
                "member": member,
                "xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>',
                "standalone": False,
                "doctype": DOCTYPE,
                "pre_root_comment_count": 2,
                "pre_root_comments": [
                    _comment_record(comment, ordinal)
                    for ordinal, comment in enumerate(prolog_comments, start=1)
                ],
                "pre_root_processing_instructions": [],
                "post_root_nodes": [],
                "root_tag": tree.getroot().tag,
                "root_attributes": dict(tree.getroot().attrib),
                "root_namespace_declarations": dict(tree.getroot().nsmap),
                "assigned_comment_count": 0,
                "assigned_processing_instruction_count": 0,
                "excluded_index_comment_count": len(excluded_comments),
            }
        )
        source_members.append(
            {
                "name": member,
                "path": str(spec["path"]),
                "bytes": spec["bytes"],
                "sha256": spec["sha256"],
                "disposition": "included retained member with exact assigned work subtrees",
            }
        )
        work_map = dict(spec["works"])
        for ordinal, division in enumerate(tops[member], start=1):
            scope = str(division.get("id"))
            assigned = scope in assigned_ids
            division_accounting.append(
                {
                    "member": member,
                    "level": "div1",
                    "ordinal": ordinal,
                    "source_xml_id": scope,
                    "title": division.get("title", ""),
                    "disposition": "assigned-work-represented"
                    if assigned
                    else "front-or-index-outside-assigned-work-scope",
                    "work_id": work_map.get(scope),
                }
            )
            if assigned:
                direct_divisions = [
                    child
                    for child in division
                    if isinstance(child.tag, str) and child.tag == "div2"
                ]
                for child_ordinal, child in enumerate(direct_divisions, start=1):
                    child_id = str(child.get("id"))
                    division_accounting.append(
                        {
                            "member": member,
                            "level": "div2",
                            "ordinal": child_ordinal,
                            "source_xml_id": child_id,
                            "parent_div1_id": scope,
                            "title": child.get("title", ""),
                            "disposition": "source-apparatus-represented"
                            if child_id in APPARATUS[member]
                            else "assigned-work-content-represented",
                            "work_id": work_map[scope],
                        }
                    )
        member_accounting.append(
            {
                "member": member,
                "assigned_div1": list(spec["assigned_div1"]),
                "assigned_work_ids": [work_id for _, work_id in spec["works"]],
                "excluded_div1": [
                    str(node.get("id"))
                    for node in tops[member]
                    if node.get("id") not in set(spec["assigned_div1"])
                ],
                "disposition": "member completely accounted; exact work roots represented and remaining front/index divisions excluded",
            }
        )
    if excluded_index_comment_count != 110:
        raise ValueError("retained excluded index comment drift")
    accountability = {
        "contract": "ocd-npnf-chrysostom-source-accountability-v1",
        "schema": "npnf-chrysostom.source-accountability.schema.json",
        "profile_id": PROFILE_ID,
        "source_scope": "four retained NPNF ThML members; seven exact assigned div1 work roots",
        "source_members": source_members,
        "document_accounting": document_accounting,
        "member_accounting": member_accounting,
        "source_census": source_census,
        "assigned_work_count": 7,
        "feature_count": 58_867,
        "attribute_count": 155_252,
        "feature_counts": EXPECTED_TAG_COUNTS,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": {"tables": 0, "rows": 0, "cells": 0},
        "excluded_index_comment_count": 110,
        "apparatus_division_ids": {
            member: list(ids) for member, ids in APPARATUS.items()
        },
        "division_accounting": division_accounting,
        "crosswalk": rows,
    }
    credits = _credits(trees)
    selected_by_key = {
        (str(spec["name"]), str(scope)): division
        for spec in SOURCE_SPECS
        for division, (scope, _) in zip(
            selected[str(spec["name"])], spec["works"], strict=True
        )
    }
    works = [
        {
            "ordinal": ordinal,
            "source_member": member,
            "div1_id": scope,
            "work_id": work_id,
            "title": WORK_TITLES[work_id],
            "retained_division_title": selected_by_key[(member, scope)].get(
                "title", ""
            ),
            "contributors": credits[work_id],
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        }
        for ordinal, (member, scope, work_id) in enumerate(ASSIGNED, start=1)
    ]
    provenance = {
        "contract": "ocd-npnf-chrysostom-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "sources": source_members,
        "edition": {
            "series": "Nicene and Post-Nicene Fathers, First Series",
            "volumes": ["X", "XI", "XII", "XIV"],
            "author": "John Chrysostom",
            "series_editor": "Philip Schaff",
            "print_source": PRINT_SOURCE,
        },
        "works": works,
        "localized_config_conflicts": [
            {
                "work_id": "chrysostom-homilies-on-romans",
                "disposition": "legacy scalar translator claim rejected; retained Morris/Simcox/Stevens evidence governs candidate metadata",
            },
            {
                "work_id": "chrysostom-homilies-on-john",
                "disposition": "legacy scalar translator claim rejected; retained Stupart/Hickley/Schaff evidence governs candidate metadata",
            },
            {
                "work_id": "chrysostom-homilies-on-hebrews",
                "disposition": "legacy Gardiner-translator claim rejected; retained Keble translation and brother revision history is preserved with Gardiner's reviser/introduction/notes role",
            },
        ],
        "rights": {
            "retained_statement": "Public Domain",
            "ccel_formatting_condition": "Do not sell CCEL files or derivatives of CCEL formatting.",
            "attribution_readme": "README.source.md",
            "publication_state": "not_ready",
        },
        "canonical_data_written": False,
    }
    unresolved = [
        {
            "id": "npnf-chrysostom-print-collation-not-performed",
            "scope": "four retained electronic witnesses",
            "status": "unresolved",
            "question": "Do the retained CCEL witnesses differ substantively from the stated print editions?",
            "evidence": "The candidate is byte-bound to the four retained CCEL XML authorities; no print collation was performed.",
        },
        {
            "id": "npnf-chrysostom-human-textual-acceptance",
            "scope": "seven assigned works",
            "status": "unresolved",
            "question": "Will the project maintainer accept this candidate after optional risk-focused human review?",
            "evidence": "Technical validation is not human textual acceptance; every work remains human_review required and accepted_ir not_accepted.",
        },
        {
            "id": "npnf-chrysostom-publication-authorization",
            "scope": "candidate package",
            "status": "unresolved",
            "question": "Has publication been separately authorized?",
            "evidence": "No publication decision is present; publication remains not_ready.",
        },
    ]
    return accountability, provenance, b"".join(_canonical(item) for item in unresolved)


def _verify_evidence(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    expected_accountability: dict[str, object],
    expected_provenance: dict[str, object],
    expected_unresolved: bytes,
) -> None:
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"),
        "source accountability",
    )
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "source accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(
            f"Chrysostom accountability schema failure: {errors[0].message}"
        )
    if accountability != expected_accountability:
        raise ValueError("Chrysostom crosswalk or source accountability drift")
    if (
        _strict_json(candidate.member_bytes("provenance.json"), "provenance")
        != expected_provenance
    ):
        raise ValueError("Chrysostom provenance or metadata drift")
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("Chrysostom unresolved evidence drift")
    readme = source_manifest.authority_path(
        "source-local-attribution-readme"
    ).read_bytes()
    if candidate.member_bytes("README.source.md") != readme:
        raise ValueError("Chrysostom README attribution drift")
    permission = source_manifest.authority_path("ccel-permission-evidence").read_bytes()
    if b"parsing ThML/XML files for text is explicitly permitted" not in permission:
        raise ValueError("CCEL permission evidence drift")


def _first_party_module_path(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    module_path = base.with_suffix(".py")
    if module_path.is_file():
        return module_path.resolve()
    package_path = base / "__init__.py"
    if package_path.is_file():
        return package_path.resolve()
    return None


def _resolved_import_name(
    module: str,
    module_path: Path,
    imported: str | None,
    level: int,
) -> str:
    if level == 0:
        return imported or ""
    package = module if module_path.name == "__init__.py" else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return ""
    base = parts[: len(parts) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _closure_paths(root: Path, policy: Mapping[str, object]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.npnf_chrysostom_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _first_party_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        parts = module.split(".")
        package_parts = parts if path.name == "__init__.py" else parts[:-1]
        for index in range(1, len(package_parts) + 1):
            package = ".".join(package_parts[:index])
            if package not in modules:
                pending.append(package)
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import_name(module, path, node.module, node.level)
                if base:
                    names.append(base)
                    names.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif isinstance(node, ast.Call) and (
                (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"__import__", "eval", "exec", "import_module"}
                )
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            ):
                raise ValueError("oracle closure contains dynamic import or execution")
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(f"oracle closure contains forbidden import {name}")
                if _first_party_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in _closure_paths(root, policy)
    ]
    return _sha(_canonical(records))


def _source_member_set_digest(source_manifest: SourceManifest) -> str:
    authorities = source_manifest.record["authorities"]
    records = sorted(
        (
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in authorities
            if item["role"] == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if len(records) != 4:
        raise ValueError("Chrysostom primary source member count drift")
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": records})
    )


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    if (
        set(candidate.member_names) != MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != source_manifest.record["source_id"]
    ):
        raise ValueError("Chrysostom candidate member, source, or status drift")
    expected_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        candidate.manifest.get("source_manifest") != expected_manifest
        or candidate.manifest.get("converter") != source_manifest.record["converter"]
        or candidate.manifest.get("package_schema")
        != source_manifest.record["package_schema"]
    ):
        raise ValueError("Chrysostom candidate authority or closure binding drift")

    trees: dict[str, etree._ElementTree] = {}
    tops: dict[str, list[etree._Element]] = {}
    selected: dict[str, list[etree._Element]] = {}
    source_members: list[dict[str, object]] = []
    for spec in SOURCE_SPECS:
        member = str(spec["name"])
        content = source_manifest.authority_path(f"{member}-retained-xml").read_bytes()
        if len(content) != spec["bytes"] or _sha(content) != spec["sha256"]:
            raise ValueError(f"retained {member} source member drift")
        tree = _source_tree(content)
        top, chosen = _structure(tree, spec)
        trees[member], tops[member], selected[member] = tree, top, chosen
        source_members.append(
            {
                "name": member,
                "path": str(spec["path"]),
                "bytes": spec["bytes"],
                "sha256": spec["sha256"],
                "disposition": "included retained member with exact assigned work subtrees",
            }
        )
    rows = _expected_rows(selected)
    tag_counts = dict(sorted(Counter(str(row["source_tag"]) for row in rows).items()))
    census = {
        key: sum(
            _census(
                [
                    node
                    for division in selected[str(spec["name"])]
                    for node in division.iter()
                    if isinstance(node.tag, str)
                ]
            )[key]
            for spec in SOURCE_SPECS
        )
        for key in EXPECTED_CENSUS
    }
    if (
        len(rows) != 58_867
        or tag_counts != EXPECTED_TAG_COUNTS
        or census != EXPECTED_CENSUS
    ):
        raise ValueError("Chrysostom independent retained-source census drift")
    _verify_tei(
        trees,
        selected,
        source_members,
        candidate.member_bytes("content.tei.xml"),
    )
    expected_accountability, expected_provenance, expected_unresolved = (
        _expected_evidence(trees, tops, selected, rows, source_manifest)
    )
    _verify_evidence(
        source_manifest,
        candidate,
        expected_accountability,
        expected_provenance,
        expected_unresolved,
    )

    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy = _strict_json(policy_bytes, "validation policy")
    profile = _strict_json(profile_bytes, "reconstruction profile")
    if (
        policy.get("candidate_status") != "nonaccepted"
        or policy.get("publication_state") != "not_ready"
        or profile.get("assigned_feature_count") != 58_867
        or profile.get("assigned_attribute_count") != 155_252
        or profile.get("excluded_index_comment_count") != 110
    ):
        raise ValueError("Chrysostom profile or policy drift")
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _source_member_set_digest(source_manifest),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
