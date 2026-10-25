"""Faithfully reconstruct the nine LIB-044 Ambrose NPNF210 works."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import XML_ID, XML_LANG, stamp_header, tei_el


CONVERTER_ID = "ocd-npnf210-ambrose-assigned-works-to-tei"
CONVERTER_VERSION = "1"
SOURCE_PATH = "raw/ccel/npnf2/npnf210.xml"
SOURCE_SHA256 = "c6f1a9d66653852d8b743c84a613c72c521dfb1b05602f0a2eff400c17665ee8"
ASSIGNED = (
    ("iv.i", "ambrose-of-milan-on-duties-of-clergy"),
    ("iv.ii", "ambrose-of-milan-on-holy-spirit"),
    ("iv.iii", "ambrose-of-milan-on-satyrus"),
    ("iv.iv", "ambrose-of-milan-exposition-of-christian-faith"),
    ("iv.v", "ambrose-of-milan-on-mysteries"),
    ("iv.vi", "ambrose-of-milan-concerning-repentance"),
    ("iv.vii", "ambrose-of-milan-concerning-virgins"),
    ("iv.viii", "ambrose-of-milan-concerning-widows"),
    ("v", "ambrose-of-milan-letters"),
)
TOP_LEVEL_DIVISIONS = ("i", "ii", "iii", "iv", "v", "vi")
DIRECT_DIV2 = (
    "iii.i",
    "iii.ii",
    "iii.iii",
    "iii.iv",
    "iii.v",
    "iii.vi",
    *(scope for scope, _ in ASSIGNED if scope != "v"),
    "v.i",
    "v.ii",
    "v.iii",
    "v.iv",
    "v.v",
    "v.vi",
    "v.vii",
    "v.viii",
    "v.ix",
    "v.x",
    "v.xi",
    "v.xii",
    "v.xiii",
    "v.xiv",
    "v.xv",
    "vi.i",
    "vi.ii",
    "vi.iii",
)
TAG_MAP = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "h1": "ab",
    "h2": "ab",
    "h3": "ab",
    "h4": "ab",
    "hr": "milestone",
    "i": "hi",
    "note": "note",
    "p": "p",
    "pb": "pb",
    "scripRef": "ref",
    "span": "seg",
    "sup": "hi",
}
EXPECTED_COUNTS = {
    "div1": 1,
    "div2": 23,
    "div3": 51,
    "div4": 296,
    "h1": 2,
    "h2": 14,
    "h3": 69,
    "h4": 296,
    "hr": 18,
    "i": 902,
    "note": 3782,
    "p": 7251,
    "pb": 463,
    "scripRef": 3307,
    "span": 646,
    "sup": 1,
}
EXPECTED_CENSUS = {
    "elements": 17_122,
    "attributes": 44_159,
    "text_nodes": 12_757,
    "tail_nodes": 12_555,
    "characters": 2_206_439,
    "non_ascii_characters": 14_144,
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
        raise ValueError("retained NPNF210 source has no ThML.body")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    if tuple(node.get("id") for node in top) != TOP_LEVEL_DIVISIONS:
        raise ValueError("retained NPNF210 top-level division order drifted")
    direct = [
        node
        for wrapper in top
        for node in wrapper
        if isinstance(node.tag, str) and node.tag == "div2"
    ]
    if tuple(node.get("id") for node in direct) != DIRECT_DIV2:
        raise ValueError("retained NPNF210 direct div2 order drifted")
    by_id = {node.get("id"): node for node in direct}
    selected = [
        top[4] if scope == "v" else by_id[scope] for scope, _work_id in ASSIGNED
    ]
    if tuple(node.get("id") for node in selected) != tuple(
        scope for scope, _ in ASSIGNED
    ):
        raise ValueError("retained NPNF210 assigned work order drifted")
    return top, selected


def _text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained NPNF210 evidence {source_id!r} drifted")
    return "".join(nodes[0].itertext())


def _credit_evidence(tree: etree._ElementTree) -> dict[str, str]:
    ids = (
        "i-p7",
        "i-p9",
        "i-p12",
        "i-p14",
        "i-p15",
        "i-p16",
        "i-p17",
        "i-p19",
        "i-p20",
        "i-p22",
        "i-p23",
        "i-p25",
        "i-p26",
        "i-p27",
        "i-p28",
        "i-p29",
        "i-p31",
        "i-p32",
        "ii-p3",
    )
    result = {source_id: _text(tree, source_id) for source_id in ids}
    required = {
        "i-p7": "SECOND SERIES",
        "i-p9": "PHILIP SCHAFF",
        "i-p12": "HENRY WACE",
        "i-p14": "VOLUME X",
        "i-p15": "Ambrose: Select Works and",
        "i-p16": "T&T CLARK",
        "i-p19": "WM. B. EERDMANS PUBLISHING COMPANY",
        "i-p25": "H. De Romestin",
        "i-p28": "E. De Romestin",
        "i-p31": "H. T. F. Duckworth",
        "ii-p3": "availed myself of the assistance",
    }
    if any(phrase not in result[source_id] for source_id, phrase in required.items()):
        raise ValueError("retained NPNF210 title-page credit evidence drifted")
    return result


def _work_credit(scope: str) -> dict[str, object]:
    return {
        "status": "retained-volume-level-credit",
        "credited_to": [
            "H. De Romestin",
            "E. De Romestin",
            "H. T. F. Duckworth",
        ],
        "role": "principal translator with two assistants",
        "source_xml_ids": ["i-p23", "i-p25", "i-p27", "i-p28", "i-p31"],
        "work_specific_allocation": None,
        "scope": scope,
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
        "xml:id": "npnf-ambrose-"
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
        elif name == "style" and tag == "hr":
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
    elif tag == "hr":
        attrs["unit"] = "source-horizontal-rule"
    elif tag in {"h1", "h2", "h3", "h4"}:
        attrs["type"] = f"source-{tag}"
    return attrs, dispositions


def _append(
    source: etree._Element,
    parent: etree._Element,
    rows: list[dict[str, object]],
    parent_feature_id: str | None,
) -> None:
    number = len(rows) + 1
    feature_id = f"npnf-ambrose-feature-{number:05d}"
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
                "assigned NPNF210 scope unexpectedly contains comment or PI"
            )
        if child.tag not in TAG_MAP:
            raise ValueError(f"unsupported retained source element {child.tag!r}")
        _append(child, target, rows, feature_id)


def _division_accounting(top: list[etree._Element]) -> list[dict[str, object]]:
    rows = []
    reasons = {
        "i": "title page used as edition and attribution evidence; outside exact work roots",
        "ii": "translator preface used as volume-credit evidence; outside exact work roots",
        "iii": "prolegomena are contextual front matter outside the nine assigned work roots",
        "iv": "dogmatic and ethical wrapper excluded; its eight assigned direct work children are represented",
        "v": "complete assigned letters work root represented with all fifteen direct letter children",
        "vi": "scripture, Greek-phrase, and print-page indexes are outside the nine assigned work roots",
    }
    for ordinal, node in enumerate(top, start=1):
        rows.append(
            {
                "ordinal": ordinal,
                "div1_id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": (
                    "assigned-work-represented"
                    if node.get("id") == "v"
                    else "source-evidence-outside-work-projection"
                ),
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
                else "contained-in-assigned-letters-root"
                if node.getparent().get("id") == "v"
                else "front-or-index-outside-assigned-work-scope"
            ),
            "reason": (
                "complete retained work subtree projected in source order"
                if node.get("id") in mapping
                else "retained letter division represented inside complete assigned div1 v root"
                if node.getparent().get("id") == "v"
                else "retained front or index division is outside the nine assigned works"
            ),
            "work_id": (
                mapping.get(str(node.get("id")))
                or (
                    "ambrose-of-milan-letters"
                    if node.getparent().get("id") == "v"
                    else None
                )
            ),
        }
        for ordinal, node in enumerate(nodes, start=1)
    ]


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    source = source_manifest.authority_path("retained-thml")
    source_bytes = source.read_bytes()
    if len(source_bytes) != 3_837_030 or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF210 authority drifted")
    tree = _parse(source)
    top, selected = _structure(tree)
    credit_evidence = _credit_evidence(tree)

    root = tei_el("TEI", {"xml:id": "npnf-ambrose-lib044"})
    root.append(
        stamp_header(
            title="NPNF2-10. Ambrose: Selected Works and Letters — nine assigned works",
            author="Ambrose of Milan",
            contributors=[
                {"name": "Philip Schaff", "role": "series editor"},
                {"name": "Henry Wace", "role": "series editor"},
                {
                    "name": "H. De Romestin",
                    "role": "principal translator of the retained selected works and letters",
                },
                {
                    "name": "E. De Romestin",
                    "role": "translation assistant",
                },
                {
                    "name": "H. T. F. Duckworth",
                    "role": "translation assistant",
                },
            ],
            source_url="https://www.ccel.org/ccel/schaff/npnf210.html",
            source_sha256=SOURCE_SHA256,
            print_source="Retained title page: Second Series, Volume X, Ambrose: Select Works and Letters; T&T Clark (Edinburgh) and Wm. B. Eerdmans Publishing Company (Grand Rapids, Michigan); no retained date and no print collation",
            rights_statement="The retained CCEL header states Public Domain. CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Attribution is included in README.source.md. Human acceptance and publication remain absent.",
        )
    )
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "npnf-ambrose-assigned-body"})
    text.append(body)
    root.append(text)
    crosswalk: list[dict[str, object]] = []
    for source_div, (scope, work_id) in zip(selected, ASSIGNED, strict=True):
        if source_div.get("id") != scope:
            raise ValueError("assigned NPNF210 scope order drifted")
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
            f"assigned NPNF210 source census drifted: {counts} {node_census}"
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
        "contract": "ocd-npnf-ambrose-source-accountability-v1",
        "schema": "npnf-ambrose.source-accountability.schema.json",
        "profile_id": "npnf210-ambrose-nine-work-v1",
        "source_scope": "retained ThML.body div2 iv.i through iv.viii plus complete div1 v",
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
                "disposition": "sole retained member; eight exact div2 roots and complete letters div1 represented",
            }
        ],
        "source_census": {
            "complete_document": total_census,
            "assigned_scope": node_census,
            "excluded_shell_front_and_indexes": excluded_census,
        },
        "assigned_work_count": 9,
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
        "contract": "ocd-npnf-ambrose-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": SOURCE_PATH,
            "sha256": SOURCE_SHA256,
            "scope": "div2 iv.i through iv.viii plus complete div1 v",
        },
        "works": [
            {
                "ordinal": ordinal,
                "source_root_id": scope,
                "work_id": work_id,
                "source_title": selected[ordinal - 1].get("title", ""),
                "author": "Ambrose of Milan",
                "translation_credit": _work_credit(scope),
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
            }
            for ordinal, (scope, work_id) in enumerate(ASSIGNED, start=1)
        ],
        "edition": {
            "title": "Ambrose: Select Works and Letters",
            "series": "A Select Library of the Nicene and Post-Nicene Fathers of the Christian Church, Second Series, Volume X",
            "editors": ["Philip Schaff", "Henry Wace"],
            "title_page_publishers": [
                "T&T Clark, Edinburgh",
                "Wm. B. Eerdmans Publishing Company, Grand Rapids, Michigan",
            ],
            "title_page_date": None,
            "retained_print_source_info": None,
            "source_identifier": "https://www.ccel.org/ccel/schaff/npnf210.html",
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
            "id": "npnf-ambrose-work-specific-translator-allocation",
            "scope": "all-nine-assigned-works",
            "status": "unresolved",
            "question": "Which retained volume-level translation contributor is responsible for each assigned work?",
            "evidence": "The retained title page names H. De Romestin with assistance from E. De Romestin and H. T. F. Duckworth but does not allocate individual works; no allocation is inferred.",
        },
        {
            "id": "npnf-ambrose-edition-witness-and-print-collation",
            "scope": "edition",
            "status": "unresolved",
            "question": "What publication date and exact print witness correspond to the undated retained title page, and does the XML differ from it?",
            "evidence": "The retained title page names the series, Volume X, T&T Clark, and Wm. B. Eerdmans but no date; the candidate is bound to retained CCEL XML and no print collation was performed.",
        },
        {
            "id": "npnf-ambrose-rights-human-acceptance-and-publication",
            "scope": "all-nine-assigned-works",
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
