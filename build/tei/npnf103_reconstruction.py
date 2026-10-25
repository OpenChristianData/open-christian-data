"""Faithfully reconstruct the sixteen LIB-039 NPNF103 works."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import XML_ID, XML_LANG, stamp_header, tei_el


CONVERTER_ID = "ocd-npnf103-assigned-works-to-tei"
CONVERTER_VERSION = "1"
SOURCE_PATH = "raw/ccel/npnf1/npnf103.xml"
SOURCE_SHA256 = "410f240f8105bb6097316a54a867fa5a4ae02c0d3d03606aefc2df71f5bfc455"
ASSIGNED = (
    ("iv.i", "augustine-on-the-trinity"),
    ("iv.ii", "augustine-enchiridion"),
    ("iv.iii", "augustine-catechising-uninstructed"),
    ("iv.iv", "augustine-faith-and-creed"),
    ("iv.v", "augustine-faith-things-not-seen"),
    ("iv.vi", "augustine-profit-of-believing"),
    ("iv.vii", "augustine-on-the-creed"),
    ("v.i", "augustine-on-continence"),
    ("v.ii", "augustine-good-of-marriage"),
    ("v.iii", "augustine-holy-virginity"),
    ("v.iv", "augustine-good-of-widowhood"),
    ("v.v", "augustine-on-lying"),
    ("v.vi", "augustine-against-lying"),
    ("v.vii", "augustine-work-of-monks"),
    ("v.viii", "augustine-on-patience"),
    ("v.ix", "augustine-care-for-dead"),
)
TOP_LEVEL_DIVISIONS = ("i", "ii", "iii", "iv", "v", "vi", "vii")
DIRECT_DIV2 = (
    *(scope for scope, _ in ASSIGNED),
    "vi.i",
    "vi.ii",
    "vii.i",
    "vii.ii",
    "vii.iii",
)
TAG_MAP = {
    "br": "lb",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "i": "hi",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "scripRef": "ref",
    "span": "seg",
    "sup": "hi",
}
EXPECTED_COUNTS = {
    "br": 4,
    "div2": 16,
    "div3": 580,
    "div4": 226,
    "i": 1309,
    "note": 2775,
    "p": 4414,
    "pb": 504,
    "scripRef": 2297,
    "span": 705,
    "sup": 2,
}
EXPECTED_CENSUS = {
    "elements": 12_832,
    "attributes": 35_788,
    "text_nodes": 8_673,
    "tail_nodes": 7_053,
    "characters": 2_420_322,
    "non_ascii_characters": 10_130,
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


def _structure(
    tree: etree._ElementTree,
) -> tuple[list[etree._Element], list[etree._Element]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained NPNF103 source has no ThML.body")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    if tuple(node.get("id") for node in top) != TOP_LEVEL_DIVISIONS:
        raise ValueError("retained NPNF103 top-level division order drifted")
    direct = [
        node
        for wrapper in top
        for node in wrapper
        if isinstance(node.tag, str) and node.tag == "div2"
    ]
    if tuple(node.get("id") for node in direct) != DIRECT_DIV2:
        raise ValueError("retained NPNF103 direct div2 order drifted")
    selected = direct[: len(ASSIGNED)]
    if tuple(node.get("id") for node in selected) != tuple(
        scope for scope, _ in ASSIGNED
    ):
        raise ValueError("retained NPNF103 assigned work order drifted")
    return top, selected


def _text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained NPNF103 evidence {source_id!r} drifted")
    return "".join(nodes[0].itertext())


def _credit_evidence(tree: etree._ElementTree) -> dict[str, str]:
    ids = (
        "i-p15",
        "i-p16",
        "i-p24",
        "i-p25",
        "i-p26",
        "i-p27",
        "i-p32",
        "i-p33",
        "i-p35",
        "i-p36",
        "iii-p6",
        "iii-p8",
        "iii-p10",
        "iii-p12",
        "iii-p14",
        "iii-p16",
        "iii-p18",
        "iii-p21",
        "iii-p23",
        "iii-p25",
        "iii-p27",
        "iii-p29",
        "iii-p31",
        "iii-p33",
        "iii-p35",
        "iii-p37",
        "iv.i-p4",
        "iv.i-p5",
        "iv.i-p7",
        "iv.i-p9",
        "iv.ii-p4",
        "iv.iii-p4",
        "iv.iii-p5",
        "iv.iv-p4",
        "iv.iv-p5",
        "iv.vi-p3",
        "iv.vii-p4",
        "v.i-p3",
        "v.ii-p3",
        "v.iii-p3",
        "v.iv-p3",
        "v.v-p4",
        "v.v-p5",
        "v.vi-p4",
        "v.vii-p3",
        "v.viii-p3",
        "v.ix-p3",
    )
    result = {source_id: _text(tree, source_id) for source_id in ids}
    required = {
        "i-p15": "EDITED BY",
        "i-p16": "PHILIP SCHAFF",
        "iv.i-p5": "Arthur West Haddan",
        "iv.i-p9": "William G. T. Shedd",
        "iv.ii-p4": "J. F. Shaw",
        "iv.iii-p5": "S. D. F. Salmond",
        "iv.iv-p5": "S. D. F. Salmond",
        "iv.vi-p3": "C. L. Cornish",
        "iv.vii-p4": "C. L.\nCornish",
        "v.iii-p3": "C. I. Cornish",
        "v.v-p5": "H. Browne",
        "v.ix-p3": "H. Browne",
    }
    if any(phrase not in result[source_id] for source_id, phrase in required.items()):
        raise ValueError("retained NPNF103 title/work credit evidence drifted")
    return result


def _work_credit(scope: str) -> dict[str, object]:
    direct: dict[str, tuple[str, list[str]]] = {
        "iv.ii": ("J. F. Shaw", ["iv.ii-p4"]),
        "iv.iii": ("S. D. F. Salmond", ["iv.iii-p4", "iv.iii-p5"]),
        "iv.iv": ("S. D. F. Salmond", ["iv.iv-p4", "iv.iv-p5"]),
        "iv.vi": ("C. L. Cornish", ["iv.vi-p3"]),
        "v.i": ("C. L. Cornish", ["v.i-p3"]),
        "v.ii": ("C. L. Cornish", ["v.ii-p3"]),
        "v.iv": ("C. L. Cornish", ["v.iv-p3"]),
        "v.v": ("H. Browne", ["v.v-p4", "v.v-p5"]),
        "v.vi": ("H. Browne", ["v.vi-p4"]),
        "v.vii": ("H. Browne", ["v.vii-p3"]),
        "v.viii": ("H. Browne", ["v.viii-p3"]),
        "v.ix": ("H. Browne", ["v.ix-p3"]),
    }
    if scope == "iv.i":
        return {
            "status": "retained-explicit",
            "credited_to": "Arthur West Haddan",
            "role": "translator",
            "source_xml_ids": ["iv.i-p4", "iv.i-p5"],
            "additional_credit": {
                "credited_to": "William G. T. Shedd",
                "role": "reviser, annotator, and introductory essay author",
                "source_xml_ids": ["iv.i-p7", "iv.i-p9"],
            },
        }
    if scope == "iv.v":
        return {
            "status": "retained-contents-only",
            "credited_to": "C. L. Cornish",
            "role": "translator",
            "source_xml_ids": ["iii-p13", "iii-p14"],
        }
    if scope == "iv.vii":
        return {
            "status": "retained-work-heading-with-conflicting-contents",
            "credited_to": "C. L. Cornish",
            "role": "translator",
            "source_xml_ids": ["iv.vii-p4"],
            "conflicting_contents_credit": "H. Brown",
            "conflicting_source_xml_ids": ["iii-p17", "iii-p18"],
        }
    if scope == "v.iii":
        return {
            "status": "retained-conflicting-name-form",
            "credited_to": None,
            "role": "translator",
            "source_name_forms": ["C. I. Cornish", "C. L. Cornish"],
            "source_xml_ids": ["v.iii-p3", "iii-p24", "iii-p25"],
        }
    name, source_ids = direct[scope]
    return {
        "status": "retained-explicit",
        "credited_to": name,
        "role": "translator",
        "source_xml_ids": source_ids,
    }


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


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
    return TAG_MAP[str(source.tag)]


def _tei_attrs(
    source: etree._Element, number: int
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = source.get("id")
    attrs = {
        "xml:id": "npnf103-"
        + (_safe_id(source_id) if source_id else f"feature-{number:05d}")
    }
    dispositions: list[dict[str, str]] = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination, method = "@xml:id", "deterministic-prefix"
        elif name == "n" and tag in {"div3", "div4", "note", "pb"}:
            attrs["n"], destination = value, "@n"
        elif name == "type" and tag in {"div3", "div4"}:
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
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = "grc" if value == "EL" else value.lower()
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
    return attrs, dispositions


def _append(
    source: etree._Element,
    parent: etree._Element,
    rows: list[dict[str, object]],
    parent_feature_id: str | None,
) -> None:
    number = len(rows) + 1
    feature_id = f"npnf103-feature-{number:05d}"
    attrs, dispositions = _tei_attrs(source, number)
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
            "feature_id": feature_id,
            "source_selector": _selector(source),
            "source_tag": source.tag,
            "source_xml_id": source.get("id"),
            "attributes": dict(source.attrib),
            "direct_text": source.text or "",
            "tail_text": source.tail or "",
            "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
            "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
            "tei_tag": _target_tag(source),
            "tei_xml_id": target.get(XML_ID),
            "tei_parent_id": parent.get(XML_ID),
            "tei_child_ordinal": child_ordinal,
            "tei_attributes": {
                (
                    "xml:id"
                    if key == XML_ID
                    else "xml:lang"
                    if key == XML_LANG
                    else key
                ): value
                for key, value in target.attrib.items()
            },
            "attribute_dispositions": dispositions,
            "disposition": "represented",
            "tei_selector": f"#{target.get(XML_ID)}",
            "parent_feature_id": parent_feature_id,
            "source_title_head": title,
        }
    )
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError(
                "assigned NPNF103 scope unexpectedly contains comment or PI"
            )
        if child.tag not in TAG_MAP:
            raise ValueError(f"unsupported retained source element {child.tag!r}")
        _append(child, target, rows, feature_id)


def _division_accounting(top: list[etree._Element]) -> list[dict[str, object]]:
    rows = []
    reasons = {
        "i": "title page used as edition and attribution evidence; outside exact work roots",
        "ii": "edition preface used as contextual evidence; outside exact work roots",
        "iii": "contents used as title and credit evidence; outside exact work roots",
        "iv": "doctrinal-treatises wrapper; all seven direct work children represented, wrapper itself excluded",
        "v": "moral-treatises wrapper; all nine direct work children represented, wrapper itself excluded",
        "vi": "subject indexes are outside the sixteen assigned work roots",
        "vii": "scripture, Greek-phrase, and print-page indexes are outside the sixteen assigned work roots",
    }
    for ordinal, node in enumerate(top, start=1):
        rows.append(
            {
                "ordinal": ordinal,
                "div1_id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "source-evidence-outside-work-projection",
                "reason": reasons[str(node.get("id"))],
            }
        )
    return rows


def _direct_div2_accounting(tree: etree._ElementTree) -> list[dict[str, object]]:
    mapping = dict(ASSIGNED)
    nodes = tree.xpath("//ThML.body/div1/div2")
    return [
        {
            "ordinal": ordinal,
            "div2_id": node.get("id"),
            "parent_div1_id": node.getparent().get("id"),
            "title": node.get("title", ""),
            "disposition": (
                "assigned-work-represented"
                if node.get("id") in mapping
                else "index-outside-assigned-work-scope"
            ),
            "reason": (
                "complete retained work subtree projected in source order"
                if node.get("id") in mapping
                else "retained index division is not one of the sixteen assigned works"
            ),
            "work_id": mapping.get(str(node.get("id"))),
        }
        for ordinal, node in enumerate(nodes, start=1)
    ]


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    source = source_manifest.authority_path("retained-thml")
    source_bytes = source.read_bytes()
    if len(source_bytes) != 3_842_341 or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF103 authority drifted")
    tree = _parse(source)
    top, selected = _structure(tree)
    credit_evidence = _credit_evidence(tree)

    root = tei_el("TEI", {"xml:id": "npnf103-lib039"})
    root.append(
        stamp_header(
            title="NPNF1-03. On the Holy Trinity; Doctrinal Treatises; Moral Treatises — sixteen assigned works",
            author="Augustine of Hippo",
            contributors=[
                {"name": "Philip Schaff", "role": "editor"},
                {
                    "name": "Arthur West Haddan",
                    "role": "translator of On the Holy Trinity",
                },
                {
                    "name": "William G. T. Shedd",
                    "role": "reviser, annotator, and introductory essay author for On the Holy Trinity",
                },
                {"name": "J. F. Shaw", "role": "translator of The Enchiridion"},
                {
                    "name": "S. D. F. Salmond",
                    "role": "translator of two assigned doctrinal treatises",
                },
                {
                    "name": "C. L. Cornish",
                    "role": "retained translator credit for assigned doctrinal and moral treatises",
                },
                {
                    "name": "C. I. Cornish",
                    "role": "source-spelled translator credit for Of Holy Virginity",
                },
                {
                    "name": "H. Browne",
                    "role": "translator of five assigned moral treatises",
                },
            ],
            source_url="https://www.ccel.org/ccel/schaff/npnf103.html",
            source_sha256=SOURCE_SHA256,
            print_source="Retained title page: Volume III, T&T Clark (Edinburgh) and Wm. B. Eerdmans Publishing Company (Grand Rapids, Michigan), no date; retained CCEL printSourceInfo separately states New York: The Christian Literature Publishing Co., 1890; no print collation",
            rights_statement="The retained CCEL header states Public Domain. CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Attribution is included in README.source.md. Human acceptance and publication remain absent.",
        )
    )
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "npnf103-assigned-body"})
    text.append(body)
    root.append(text)
    crosswalk: list[dict[str, object]] = []
    for source_div, (scope, work_id) in zip(selected, ASSIGNED, strict=True):
        if source_div.get("id") != scope:
            raise ValueError("assigned NPNF103 scope order drifted")
        before = len(crosswalk)
        _append(source_div, body, crosswalk, None)
        crosswalk[before]["work_id"] = work_id

    counts: dict[str, int] = {}
    for row in crosswalk:
        tag = str(row["source_tag"])
        counts[tag] = counts.get(tag, 0) + 1
    # Node-presence counts distinguish absent text from present empty strings and are
    # checked directly from retained nodes before their strings enter the crosswalk.
    assigned_nodes = [node for division in selected for node in division.iter()]
    node_census = {
        "elements": len(assigned_nodes),
        "attributes": sum(len(node.attrib) for node in assigned_nodes),
        "text_nodes": sum(node.text is not None for node in assigned_nodes),
        "tail_nodes": sum(node.tail is not None for node in assigned_nodes),
        "characters": sum(
            len((node.text or "") + (node.tail or "")) for node in assigned_nodes
        ),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in assigned_nodes
        ),
    }
    if counts != EXPECTED_COUNTS or node_census != EXPECTED_CENSUS:
        raise ValueError(
            f"assigned NPNF103 source census drifted: {counts} {node_census}"
        )

    total_nodes = [node for node in tree.getroot().iter() if isinstance(node.tag, str)]
    total_census = {
        "elements": len(total_nodes),
        "attributes": sum(len(node.attrib) for node in total_nodes),
        "text_nodes": sum(node.text is not None for node in total_nodes),
        "tail_nodes": sum(node.tail is not None for node in total_nodes),
        "characters": sum(
            len((node.text or "") + (node.tail or "")) for node in total_nodes
        ),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in total_nodes
        ),
    }
    excluded_census = {
        key: total_census[key] - node_census[key] for key in total_census
    }
    accountability = {
        "contract": "ocd-npnf103-source-accountability-v1",
        "schema": "augustine-npnf103.source-accountability.schema.json",
        "profile_id": "npnf103-assigned-div2-iv-i-through-v-ix-v1",
        "source_scope": "retained ThML.body div1 iv/v direct div2 iv.i–iv.vii and v.i–v.ix",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(source_bytes),
            "sha256": SOURCE_SHA256,
            "disposition": "included as the sole retained source member",
        },
        "document_accounting": {
            "xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>',
            "standalone": False,
            "doctype": '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" "http://www.ccel.org/dtd/ThML10.dtd">',
            "pre_root_comments": [
                '\n<?xml-stylesheet type="text/xml"\n    href="http://www.ccel.org/ss/thml.html.xsl" ?>\n<?xml-stylesheet type="text/xsl"\n    href="http://www.ccel.org/ss/thml.html.xsl" ?>\n',
                " Copyright Christian Classics Ethereal Library ",
            ],
            "pre_root_processing_instructions": [],
            "post_root_nodes": [],
            "root_tag": "ThML",
            "root_attributes": {},
            "root_namespace_declarations": {},
            "assigned_comment_count": 0,
            "assigned_processing_instruction_count": 0,
        },
        "member_accounting": [
            {
                "path": SOURCE_PATH,
                "disposition": "sole retained member; sixteen exact work subtrees represented",
            }
        ],
        "source_census": {
            "complete_document": total_census,
            "assigned_scope": node_census,
            "excluded_shell_front_and_indexes": excluded_census,
        },
        "assigned_work_count": 16,
        "feature_count": len(crosswalk),
        "attribute_count": node_census["attributes"],
        "feature_counts": counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": {"tables": 0, "rows": 0, "cells": 0},
        "top_level_division_accounting": _division_accounting(top),
        "direct_div2_accounting": _direct_div2_accounting(tree),
        "crosswalk": crosswalk,
    }
    provenance = {
        "contract": "ocd-npnf103-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": SOURCE_PATH,
            "sha256": SOURCE_SHA256,
            "scope": "div2 iv.i through iv.vii and v.i through v.ix",
        },
        "works": [
            {
                "ordinal": ordinal,
                "div2_id": scope,
                "work_id": work_id,
                "source_title": selected[ordinal - 1].get("title", ""),
                "author": "Augustine of Hippo",
                "translation_credit": _work_credit(scope),
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
            }
            for ordinal, (scope, work_id) in enumerate(ASSIGNED, start=1)
        ],
        "edition": {
            "title": "NPNF1-03. On the Holy Trinity; Doctrinal Treatises; Moral Treatises",
            "series": "A Select Library of the Nicene and Post-Nicene Fathers of the Christian Church, First Series, Volume III",
            "editor": "Philip Schaff",
            "title_page_publishers": [
                "T&T Clark, Edinburgh",
                "Wm. B. Eerdmans Publishing Company, Grand Rapids, Michigan",
            ],
            "title_page_date": None,
            "retained_print_source_info": "New York: The Christian Literature Publishing Co., 1890",
            "retained_preface_dateline": "New York, March, 1887",
            "source_identifier": "https://www.ccel.org/ccel/schaff/npnf103.html",
            "print_collation": "not-performed",
        },
        "credit_evidence": credit_evidence,
        "rights": {
            "retained_statement": "Public Domain",
            "ccel_permission": "parsing permitted; do not sell CCEL files or derivatives of CCEL formatting",
            "attribution": "sourced via CCEL.org",
            "human_acceptance": "absent",
            "publication_state": "not_ready",
        },
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "npnf103-on-the-creed-credit-conflict",
            "scope": "augustine-on-the-creed",
            "status": "unresolved",
            "question": "Why does the retained contents credit H. Brown while the work heading credits C. L. Cornish?",
            "evidence": "Retained iii-p17/iii-p18 and iv.vii-p4 conflict; the candidate records the work-local heading without silently correcting the contents.",
        },
        {
            "id": "npnf103-holy-virginity-name-form-conflict",
            "scope": "augustine-holy-virginity",
            "status": "unresolved",
            "question": "Do the retained C. I. Cornish work-heading form and C. L. Cornish contents form identify the same translator?",
            "evidence": "Retained v.iii-p3 conflicts with iii-p24/iii-p25; no identity normalization is inferred.",
        },
        {
            "id": "npnf103-edition-witness-and-print-collation",
            "scope": "edition",
            "status": "unresolved",
            "question": "How does the undated retained title-page imprint relate to the CCEL printSourceInfo 1890 claim and the 1887 preface dateline, and does the XML differ from those print witnesses?",
            "evidence": "The candidate is bound to retained CCEL XML; no print collation or edition-identity decision was performed.",
        },
        {
            "id": "npnf103-rights-human-acceptance-and-publication",
            "scope": "all-16-assigned-works",
            "status": "unresolved",
            "question": "Will a maintainer accept these candidate texts and separately authorize publication after rights review?",
            "evidence": "Technical verification is not human textual acceptance, a rights decision, or publication authorization.",
        },
    ]
    readme = source_manifest.authority_path(
        "source-local-attribution-readme"
    ).read_bytes()
    return {
        "README.source.md": readme,
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
