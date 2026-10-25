"""Faithfully reconstruct the seven LIB-043 Chrysostom NPNF works."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import XML_ID, XML_LANG, stamp_header, tei_el


CONVERTER_ID = "ocd-npnf-chrysostom-seven-work-to-tei"
CONVERTER_VERSION = "1"
PROFILE_ID = "npnf-chrysostom-110-111-112-114-seven-work-v1"
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


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parse(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _source_divisions(
    tree: etree._ElementTree, spec: Mapping[str, object]
) -> tuple[list[etree._Element], list[etree._Element]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError(f"retained {spec['name']} source has no ThML.body")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    selected_by_id = {node.get("id"): node for node in top}
    assigned = tuple(str(value) for value in spec["assigned_div1"])
    if len(selected_by_id) != len(top) or any(
        scope not in selected_by_id for scope in assigned
    ):
        raise ValueError(f"retained {spec['name']} div1 identity drifted")
    selected = [selected_by_id[scope] for scope in assigned]
    if [node.get("id") for node in selected] != list(assigned):
        raise ValueError(f"retained {spec['name']} assigned order drifted")
    return top, selected


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        if not isinstance(current.tag, str):
            break
        parent = current.getparent()
        if parent is None:
            break
        siblings = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.tag == current.tag
        ]
        parts.append(f"{current.tag}[{siblings.index(current) + 1}]")
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


def _tei_attrs(
    source: etree._Element,
    member: str,
    number: int,
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
    return attrs, dispositions


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        ("xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key): value
        for key, value in node.attrib.items()
    }


def _append(
    source: etree._Element,
    parent: etree._Element,
    rows: list[dict[str, object]],
    *,
    member: str,
    work_id: str,
    parent_feature_id: str | None,
) -> None:
    number = len(rows) + 1
    feature_id = f"npnf-chrysostom-feature-{number:05d}"
    attrs, dispositions = _tei_attrs(source, member, number)
    if parent_feature_id is None:
        attrs["corresp"] = f"#{member}:{source.get('id')}:{work_id}"
    target = tei_el(_target_tag(source), attrs)
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        target.append(tei_el("head", text=title))
    target.text = source.text or ""
    target.tail = source.tail or ""
    child_ordinal = 1 + sum(1 for child in parent if isinstance(child.tag, str))
    parent.append(target)
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
            "tei_xml_id": target.get(XML_ID),
            "tei_parent_id": parent.get(XML_ID),
            "tei_child_ordinal": child_ordinal,
            "tei_attributes": _normalized_attrs(target),
            "attribute_dispositions": dispositions,
            "tei_selector": f"#{target.get(XML_ID)}",
            "parent_feature_id": parent_feature_id,
            "source_title_head": title,
            "disposition": "represented",
        }
    )
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError(
                "assigned Chrysostom source scope unexpectedly contains comment or PI"
            )
        if child.tag not in TAG_MAP:
            raise ValueError(f"unsupported retained source element {child.tag!r}")
        _append(
            child,
            target,
            rows,
            member=member,
            work_id=work_id,
            parent_feature_id=feature_id,
        )


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
        raise ValueError(f"retained credit evidence {source_id!r} drifted")
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
                raise ValueError(f"retained contributor evidence for {name} drifted")
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


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    trees: dict[str, etree._ElementTree] = {}
    tops: dict[str, list[etree._Element]] = {}
    selections: dict[str, list[etree._Element]] = {}
    source_members: list[dict[str, object]] = []
    document_accounting: list[dict[str, object]] = []
    division_accounting: list[dict[str, object]] = []
    source_census: dict[str, dict[str, dict[str, int]]] = {}
    excluded_index_comment_count = 0

    for spec in SOURCE_SPECS:
        member = str(spec["name"])
        path = source_manifest.authority_path(f"{member}-retained-xml")
        content = path.read_bytes()
        if len(content) != spec["bytes"] or _sha(content) != spec["sha256"]:
            raise ValueError(f"retained {member} authority drifted")
        tree = _parse(path)
        if tree.docinfo.doctype != DOCTYPE:
            raise ValueError(f"retained {member} doctype drifted")
        top, selected = _source_divisions(tree, spec)
        trees[member], tops[member], selections[member] = tree, top, selected
        assigned_ids = {str(value) for value in spec["assigned_div1"]}
        assigned_nodes = [
            node
            for division in selected
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
        if len(prolog_comments) != 2:
            raise ValueError(f"retained {member} pre-root comment inventory drifted")
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
            raise ValueError(f"retained {member} assigned comments drifted")
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
        for ordinal, division in enumerate(top, start=1):
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

    credits = _credits(trees)
    root = tei_el("TEI", {"xml:id": "npnf-chrysostom-lib043"})
    root.append(
        stamp_header(
            title="NPNF First Series Chrysostom volumes X, XI, XII, and XIV — seven assigned works",
            author="John Chrysostom",
            contributors=[
                {"name": "Philip Schaff", "role": "series editor"},
                {"name": "George Prevost", "role": "Matthew translator"},
                {"name": "M. B. Riddle", "role": "Matthew reviser and essay author"},
                {
                    "name": "J. Walker; J. Sheppard; H. Browne",
                    "role": "Acts translators",
                },
                {"name": "J. B. Morris", "role": "Romans translator and annotator"},
                {"name": "W. H. Simcox", "role": "Romans translation reviser"},
                {"name": "George B. Stevens", "role": "Acts and Romans reviser"},
                {
                    "name": "Talbot W. Chambers",
                    "role": "Corinthians translation reviser and annotator",
                },
                {"name": "G. T. Stupart", "role": "John translator"},
                {"name": "J. G. Hickley", "role": "John press preparation"},
                {"name": "T. Keble", "role": "Hebrews translator"},
                {
                    "name": "T. Keble's brother, the Vicar of Hursley",
                    "role": "Hebrews translation reviser",
                },
                {
                    "name": "Frederic Gardiner",
                    "role": "Hebrews reviser, introduction author, and annotator",
                },
            ],
            source_url="https://www.ccel.org/ccel/schaff/",
            source_sha256=_sha(_canonical(source_members)),
            print_source=PRINT_SOURCE,
            rights_statement=RIGHTS_STATEMENT,
        )
    )
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "npnf-chrysostom-assigned-body"})
    text.append(body)
    root.append(text)
    crosswalk: list[dict[str, object]] = []
    for spec in SOURCE_SPECS:
        member = str(spec["name"])
        for division, (scope, work_id) in zip(
            selections[member], spec["works"], strict=True
        ):
            if division.get("id") != scope:
                raise ValueError(f"retained {member} work order drifted")
            _append(
                division,
                body,
                crosswalk,
                member=member,
                work_id=work_id,
                parent_feature_id=None,
            )

    tag_counts = dict(
        sorted(Counter(str(row["source_tag"]) for row in crosswalk).items())
    )
    assigned_census = {
        key: sum(
            source_census[member]["assigned_scope"][key] for member in source_census
        )
        for key in EXPECTED_CENSUS
    }
    if tag_counts != EXPECTED_TAG_COUNTS or assigned_census != EXPECTED_CENSUS:
        raise ValueError(
            f"assigned Chrysostom source census drifted: {tag_counts} {assigned_census}"
        )
    if excluded_index_comment_count != 110:
        raise ValueError("excluded Chrysostom index comment inventory drifted")

    accountability = {
        "contract": "ocd-npnf-chrysostom-source-accountability-v1",
        "schema": "npnf-chrysostom.source-accountability.schema.json",
        "profile_id": PROFILE_ID,
        "source_scope": "four retained NPNF ThML members; seven exact assigned div1 work roots",
        "source_members": source_members,
        "document_accounting": document_accounting,
        "member_accounting": [
            {
                "member": str(spec["name"]),
                "assigned_div1": list(spec["assigned_div1"]),
                "assigned_work_ids": [work_id for _, work_id in spec["works"]],
                "excluded_div1": [
                    str(node.get("id"))
                    for node in tops[str(spec["name"])]
                    if node.get("id") not in set(spec["assigned_div1"])
                ],
                "disposition": "member completely accounted; exact work roots represented and remaining front/index divisions excluded",
            }
            for spec in SOURCE_SPECS
        ],
        "source_census": source_census,
        "assigned_work_count": 7,
        "feature_count": len(crosswalk),
        "attribute_count": assigned_census["attributes"],
        "feature_counts": tag_counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": {"tables": 0, "rows": 0, "cells": 0},
        "excluded_index_comment_count": excluded_index_comment_count,
        "apparatus_division_ids": {
            member: list(ids) for member, ids in APPARATUS.items()
        },
        "division_accounting": division_accounting,
        "crosswalk": crosswalk,
    }
    schema_path = source_manifest.authority_path("source-accountability-schema")
    schema = json.loads(schema_path.read_bytes())
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"source-accountability schema failure: {errors[0].message}")

    works = []
    selected_by_key = {
        (str(spec["name"]), str(scope)): division
        for spec in SOURCE_SPECS
        for division, (scope, _) in zip(
            selections[str(spec["name"])], spec["works"], strict=True
        )
    }
    for ordinal, (member, scope, work_id) in enumerate(ASSIGNED, start=1):
        works.append(
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
        )
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
    readme = source_manifest.authority_path(
        "source-local-attribution-readme"
    ).read_bytes()
    return {
        "content.tei.xml": etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=False,
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
