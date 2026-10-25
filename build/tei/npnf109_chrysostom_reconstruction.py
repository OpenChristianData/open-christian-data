"""Source-first faithful TEI producer for LIB-042 NPNF First Series cohort 5.

One retained member: npnf109.xml (ThML, CCEL, SHA-256 6d0887393...).
Sixteen assigned works: div1 ids iv through xix in source order.
Authority: retained npnf109.xml only. No current JSON, legacy TEI, or
plausible metadata as reconstruction authority.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from lxml import etree
from ocd_kernel.reconstruction import SourceManifest, reconstruct

# TEI namespace
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"


# ---- Static constants derived from retained source census ----

SOURCE_MEMBER = {
    "name": "npnf109",
    "path": "raw/ccel/npnf1/npnf109.xml",
    "bytes": 3_017_592,
    "sha256": "6d0887393b4d197d7784cbea989aeb422d7e38f55711b4c4d4af85e3de680175",
}

DOCTYPE = (
    '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" '
    '"http://www.ccel.org/dtd/ThML10.dtd">'
)

# Source div1 id -> work ID (source order)
ASSIGNED_DIV1_TO_WORK = [
    ("iv", "chrysostom-on-the-priesthood"),
    ("v", "chrysostom-exhortation-to-theodore"),
    ("vi", "chrysostom-letter-to-young-widow"),
    ("vii", "chrysostom-homilies-ignatius-and-babylas"),
    ("viii", "chrysostom-homily-on-lowliness-of-mind"),
    ("ix", "chrysostom-instructions-to-catechumens"),
    ("x", "chrysostom-three-homilies-on-power-of-demons"),
    ("xi", "chrysostom-homily-on-father-if-it-be-possible"),
    ("xii", "chrysostom-homily-on-the-paralytic"),
    ("xiii", "chrysostom-homily-to-those-not-attended-assembly"),
    ("xiv", "chrysostom-homily-against-publishing-errors"),
    ("xv", "chrysostom-two-homilies-on-eutropius"),
    ("xvi", "chrysostom-no-one-can-be-harmed"),
    ("xvii", "chrysostom-letters-to-olympias"),
    ("xviii", "chrysostom-correspondence-with-rome"),
    ("xix", "chrysostom-homilies-on-the-statues"),
]

ASSIGNED_IDS = [d for d, _ in ASSIGNED_DIV1_TO_WORK]
ASSIGNED = tuple(ASSIGNED_DIV1_TO_WORK)

WORK_TITLES = {
    "chrysostom-on-the-priesthood": "Treatise Concerning the Christian Priesthood",
    "chrysostom-exhortation-to-theodore": "An Exhortation to Theodore After His Fall",
    "chrysostom-letter-to-young-widow": "Letter to a Young Widow",
    "chrysostom-homilies-ignatius-and-babylas": "Homilies on S. Ignatius and S. Babylas",
    "chrysostom-homily-on-lowliness-of-mind": "Homily Concerning Lowliness of Mind",
    "chrysostom-instructions-to-catechumens": "Instructions to Catechumens",
    "chrysostom-three-homilies-on-power-of-demons": "Three Homilies Concerning the Power of Demons",
    "chrysostom-homily-on-father-if-it-be-possible": "Homily on the Passage 'Father, If It Be Possible...'",
    "chrysostom-homily-on-the-paralytic": "Homily on the Paralytic Let Down Through the Roof",
    "chrysostom-homily-to-those-not-attended-assembly": "Homily to Those Who Had Not Attended the Assembly",
    "chrysostom-homily-against-publishing-errors": "Homily Against Publishing the Errors of the Brethren",
    "chrysostom-two-homilies-on-eutropius": "Two Homilies on Eutropius",
    "chrysostom-no-one-can-be-harmed": "Treatise to Prove That No One Can Harm the Man Who Does Not Injure Himself",
    "chrysostom-letters-to-olympias": "Letters of St. Chrysostom to Olympias",
    "chrysostom-correspondence-with-rome": "Correspondence of St. Chrysostom with the Bishop of Rome",
    "chrysostom-homilies-on-the-statues": "The Homilies on the Statues to the People of Antioch",
}

# Source element tag -> TEI target tag
TAG_MAP = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "p": "p",
    "note": "note",
    "scripRef": "ref",
    "scripCom": "ref",
    "i": "hi",
    "br": "lb",
    "pb": "pb",
    "span": "seg",
    "sup": "hi",
}

# Source language codes in span elements -> xml:lang values
LANGUAGE_MAP = {"DE": "de", "EL": "grc", "HE": "he", "FR": "fr"}


# ---- Producer identity ----

PRODUCER_ID = "ocd-npnf109-16-work-to-tei"
PRODUCER_VERSION = "20"
PROFILE_ID = "npnf109-16-work-v1"


# ---- Helpers ----

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


def _tei_el(local_name: str, attrs: dict | None = None) -> etree._Element:
    el = etree.Element(f"{{{TEI_NS}}}{local_name}", nsmap={None: TEI_NS})
    for name, value in (attrs or {}).items():
        if name == "xml:id":
            el.set(f"{{{XML_NS}}}id", value)
        elif name == "xml:lang":
            el.set(f"{{{XML_NS}}}lang", value)
        else:
            el.set(name, value)
    return el


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
        return "p" if parent is not None and str(parent.tag).startswith("div") else "seg"
    return TAG_MAP[str(source.tag)]


def _tei_attrs(
    source: etree._Element,
    member: str,
    number: int,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = source.get("id")
    attrs: dict[str, str] = {
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
        dispositions.append({
            "source_attribute": name,
            "source_value": value,
            "destination": destination,
            "method": method,
        })
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    elif tag == "scripCom":
        parent = source.getparent()
        attrs["rend" if _target_tag(source) == "p" else "type"] = "scripture-commentary"
    return attrs, dispositions


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        ("xml:id" if key == f"{{{XML_NS}}}id" else "xml:lang" if key == f"{{{XML_NS}}}lang" else key): value
        for key, value in node.attrib.items()
    }


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


def _source_divisions(
    tree: etree._ElementTree,
) -> tuple[list[etree._Element], list[etree._Element]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained npnf109 source has no ThML.body")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    selected_by_id = {node.get("id"): node for node in top}
    if len(selected_by_id) != len(top):
        raise ValueError("retained npnf109 div1 identity drifted")
    if any(scope not in selected_by_id for scope in ASSIGNED_IDS):
        raise ValueError("retained npnf109 assigned div1 scope drifted")
    selected = [selected_by_id[scope] for scope in ASSIGNED_IDS]
    if [node.get("id") for node in selected] != ASSIGNED_IDS:
        raise ValueError("retained npnf109 assigned div1 order drifted")
    return top, selected


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
    feature_id = f"npnf109-feature-{number:05d}"
    attrs, dispositions = _tei_attrs(source, member, number)
    if parent_feature_id is None:
        attrs["corresp"] = f"#{member}:{source.get('id')}:{work_id}"
    target = _tei_el(_target_tag(source), attrs)
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        target.append(_tei_el("head", {}))
        target[0].text = title
    target.text = source.text or ""
    target.tail = source.tail or ""
    child_ordinal = 1 + sum(
        1 for child in parent if isinstance(child.tag, str)
    )
    parent.append(target)
    rows.append({
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
        "tei_xml_id": target.get(f"{{{XML_NS}}}id"),
        "tei_parent_id": parent.get(f"{{{XML_NS}}}id"),
        "tei_child_ordinal": child_ordinal,
        "tei_attributes": _normalized_attrs(target),
        "attribute_dispositions": dispositions,
        "tei_selector": f"#{target.get(f'{{{XML_NS}}}id')}",
        "parent_feature_id": parent_feature_id,
        "source_title_head": title,
        "disposition": "represented",
    })
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError(
                "assigned npnf109 source scope unexpectedly contains comment or PI"
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


# ---- Contributor metadata from retained source div2 apparatus ----

CONTRIBUTOR_SPECS = {
    "chrysostom-on-the-priesthood": [
        ("Schaff", "series editor", "iv", "iv.ii", "schaff"),
    ],
}


def _node_text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained credit evidence {source_id!r} drifted")
    return " ".join("".join(nodes[0].itertext()).split())


# ---- Main conversion ----

def convert(source_root: Path) -> dict[str, bytes]:
    """Convert retained npnf109 to TEI. Returns member-name -> bytes map."""
    source_path = source_root / "raw/ccel/npnf1/npnf109.xml"
    content = source_path.read_bytes()

    # Verify retained authority
    if len(content) != SOURCE_MEMBER["bytes"]:
        raise ValueError(f"retained npnf109 byte size changed: {len(content)}")
    if _sha(content) != SOURCE_MEMBER["sha256"]:
        raise ValueError("retained npnf109 SHA-256 authority drifted")

    tree = _parse(source_path)
    if tree.docinfo.doctype != DOCTYPE:
        raise ValueError("retained npnf109 doctype drifted")

    top, selected = _source_divisions(tree)

    # Census
    source_census: dict[str, dict[str, int]] = {}
    for division in selected:
        for node in division.iter():
            if isinstance(node.tag, str):
                pass  # counted below

    assigned_nodes = []
    for division in selected:
        for node in division.iter():
            if isinstance(node.tag, str):
                assigned_nodes.append(node)

    complete_nodes = [
        node for node in tree.getroot().iter() if isinstance(node.tag, str)
    ]
    excluded_nodes = [
        node for node in complete_nodes if node not in set(assigned_nodes)
    ]
    source_census["complete_document"] = _census(complete_nodes)
    source_census["assigned_scope"] = _census(assigned_nodes)
    source_census["excluded_shell_front_and_indexes"] = _census(excluded_nodes)

    # Comments
    prolog_comments = tree.xpath("/comment()")
    if len(prolog_comments) != 2:
        raise ValueError("retained npnf109 pre-root comment count drifted")

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
        if division is not None and division.get("id") in set(ASSIGNED_IDS):
            assigned_comments.append(comment)
        else:
            excluded_comments.append(comment)
    if assigned_comments:
        raise ValueError("retained npnf109 assigned comments drifted")

    # Document accounting
    document_accounting = {
        "member": "npnf109",
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

    # Division accounting
    division_accounting: list[dict[str, object]] = []
    work_map = dict(ASSIGNED)
    for ordinal, division in enumerate(top, start=1):
        scope = str(division.get("id"))
        assigned = scope in set(ASSIGNED_IDS)
        div2_entries: list[dict[str, object]] = []
        if assigned:
            div2s = [
                child for child in division
                if isinstance(child.tag, str) and child.tag == "div2"
            ]
            for child_ordinal, div2 in enumerate(div2s, start=1):
                div2_id = str(div2.get("id"))
                div2_entries.append({
                    "level": "div2",
                    "ordinal": child_ordinal,
                    "source_xml_id": div2_id,
                    "parent_div1_id": scope,
                    "title": div2.get("title", ""),
                    "disposition": "assigned-work-content-represented",
                    "work_id": work_map[scope],
                })
        division_accounting.append({
            "member": "npnf109",
            "level": "div1",
            "ordinal": ordinal,
            "source_xml_id": scope,
            "title": division.get("title", ""),
            "disposition": (
                "assigned-work-represented"
                if assigned
                else "front-or-index-outside-assigned-work-scope"
            ),
            "work_id": work_map.get(scope),
            "child_div2_count": len(div2_entries),
        })
        division_accounting.extend(div2_entries)

    # Source members
    source_members = [{
        "name": "npnf109",
        "path": SOURCE_MEMBER["path"],
        "bytes": SOURCE_MEMBER["bytes"],
        "sha256": SOURCE_MEMBER["sha256"],
        "disposition": (
            "included retained member with exact assigned work subtrees"
        ),
    }]

    # Build TEI
    root = _tei_el("TEI", {"xml:id": "npnf109-lib042"})

    # TEI Header
    tei_header = _tei_el("teiHeader")
    file_desc = _tei_el("fileDesc")
    title_stmt = _tei_el("titleStmt")

    main_title = _tei_el("title")
    main_title.text = (
        "NPNF1-09. St. Chrysostom: On the Priesthood; Ascetic Treatises; "
        "Select Homilies and Letters; Homilies on the Statutes"
    )
    title_stmt.append(main_title)

    author = _tei_el("author")
    author.text = "St. Chrysostom"
    title_stmt.append(author)

    for name, role in [
        ("Philip Schaff", "series editor"),
    ]:
        resp_stmt = _tei_el("respStmt")
        resp = _tei_el("resp")
        resp.text = role
        contributor = _tei_el("name")
        contributor.text = name
        resp_stmt.extend([resp, contributor])
        title_stmt.append(resp_stmt)

    publication_stmt = _tei_el("publicationStmt")
    publisher = _tei_el("publisher")
    publisher.text = "Grand Rapids, MI: Christian Classics Ethereal Library"
    availability = _tei_el("availability")
    rights_p = _tei_el("p")
    rights_p.text = "Retained electronic-edition rights statement: Public Domain."
    availability.append(rights_p)
    publication_stmt.extend([publisher, availability])

    source_desc = _tei_el("sourceDesc")
    bibl = _tei_el("bibl")
    ptr = _tei_el("ptr", {"target": "https://www.ccel.org/ccel/schaff/npnf109"})
    bibl.append(ptr)
    source_desc.append(bibl)

    file_desc.extend([title_stmt, publication_stmt, source_desc])
    tei_header.append(file_desc)
    root.append(tei_header)

    # Text body
    text_el = _tei_el("text")
    body = _tei_el("body", {"xml:id": "npnf109-assigned-body"})
    text_el.append(body)
    root.append(text_el)

    # Crosswalk and work sections
    crosswalk: list[dict[str, object]] = []
    for division, (scope, work_id) in zip(selected, ASSIGNED, strict=True):
        if division.get("id") != scope:
            raise ValueError("retained npnf109 work order drifted")
        _append(
            division,
            body,
            crosswalk,
            member="npnf109",
            work_id=work_id,
            parent_feature_id=None,
        )

    # Verify census
    tag_counts = dict(
        sorted(Counter(str(row["source_tag"]) for row in crosswalk).items())
    )
    census_assigned = source_census["assigned_scope"]
    expected_census = {
        "elements": 7723,
        "attributes": 19877,
        "text_nodes": 5200,
        "tail_nodes": 5528,
        "characters": 2_021_867,
        "non_ascii_characters": 12334,
    }
    expected_tag_counts = {
        "br": 3,
        "div1": 16,
        "div2": 82,
        "i": 491,
        "note": 1832,
        "p": 3022,
        "pb": 427,
        "scripCom": 1,
        "scripRef": 1281,
        "span": 568,
    }

    if tag_counts != expected_tag_counts or census_assigned != expected_census:
        raise ValueError(
            f"assigned npnf109 source census drifted: "
            f"tags={tag_counts} census={census_assigned}"
        )

    # Source has 2 excluded embedded comments (both in div1 xx — the index div)
    expected_excluded = 2
    if len(excluded_comments) != expected_excluded:
        raise ValueError(
            f"retained npnf109 excluded index comment count unexpected: "
            f"{len(excluded_comments)} (expected {expected_excluded})"
        )

    # Source accountability
    accountability = {
        "contract": "ocd-npnf109-source-accountability-v1",
        "schema": "npnf109.source-accountability.schema.json",
        "profile_id": PROFILE_ID,
        "source_scope": (
            "one retained NPNF ThML member (npnf109); "
            "16 exact assigned div1 work roots (iv through xix)"
        ),
        "source_members": source_members,
        "document_accounting": [document_accounting],
        "member_accounting": [{
            "member": "npnf109",
            "assigned_div1": ASSIGNED_IDS,
            "assigned_work_ids": [wid for _, wid in ASSIGNED],
            "excluded_div1": [
                str(node.get("id"))
                for node in top
                if node.get("id") not in set(ASSIGNED_IDS)
            ],
            "disposition": (
                "member completely accounted; "
                "exact work roots represented and remaining front/index divisions excluded"
            ),
        }],
        "source_census": source_census,
        "assigned_work_count": 16,
        "feature_count": len(crosswalk),
        "attribute_count": census_assigned["attributes"],
        "feature_counts": tag_counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": {"tables": 0, "rows": 0, "cells": 0},
        "excluded_index_comment_count": len(excluded_comments),
        "division_accounting": division_accounting,
        "crosswalk": crosswalk,
    }

    # Works list for provenance
    works = [
        {
            "ordinal": ordinal,
            "source_member": "npnf109",
            "div1_id": scope,
            "work_id": wid,
            "title": WORK_TITLES[wid],
            "retained_division_title": division.get("title", ""),
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        }
        for ordinal, (division, (scope, wid)) in enumerate(
            zip(selected, ASSIGNED), start=1
        )
    ]

    retained_head = tree.getroot().find("ThML.head")
    if retained_head is None:
        raise ValueError("retained npnf109 source has no ThML.head")
    dc_entries = tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/*")
    print_source_entries = tree.xpath("/ThML/ThML.head/printSourceInfo/*")
    retained_metadata_evidence = {
        "head_c14n_sha256": _sha(
            etree.tostring(retained_head, method="c14n", with_comments=True)
        ),
        "dc_entries": [
            {
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text or "",
                "tail": node.tail or "",
            }
            for node in dc_entries
        ],
        "print_source_entries": [
            {
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text or "",
                "tail": node.tail or "",
            }
            for node in print_source_entries
        ],
        "normalization_policy": (
            "Retained ThML head and assigned work title/credit apparatus are preserved "
            "as evidence; source config metadata is diagnostic only and is not used to "
            "supply or reconcile candidate readings."
        ),
    }

    provenance = {
        "contract": "ocd-npnf109-provenance-v1",
        "status": "nonaccepted",
        "source_id": "LIB-042",
        "sources": source_members,
        "edition": {
            "series": "Nicene and Post-Nicene Fathers, First Series",
            "volume": "IX",
            "author": "St. Chrysostom",
            "series_editor": "Philip Schaff",
            "print_source": "New York: Christian Literature Publishing Co., 1886",
            "electronic_publisher": (
                "Grand Rapids, MI: Christian Classics Ethereal Library"
            ),
        },
        "works": works,
        "retained_metadata_evidence": retained_metadata_evidence,
        "localized_config_conflicts": [
            {
                "scope": "all sixteen LIB-042 source configs",
                "fields": ["contributors", "source_edition", "translator"],
                "retained_authority": (
                    "npnf109 ThML head plus each assigned work's preserved title/credit apparatus"
                ),
                "disposition": (
                    "configs remain diagnostic aids; no config-only contributor, year, or edition claim is asserted"
                ),
            }
        ],
        "rights": {
            "retained_statement": "Public Domain",
            "ccel_formatting_condition": (
                "Do not sell CCEL files or derivatives of CCEL formatting."
            ),
            "attribution_readme": "README.source.md",
            "publication_state": "not_ready",
        },
        "canonical_data_written": False,
    }

    unresolved = [
        {
            "id": "npnf109-print-collation-not-performed",
            "scope": "one retained electronic witness",
            "status": "unresolved",
            "question": (
                "Do the retained CCEL witness and stated print edition differ "
                "substantively?"
            ),
            "evidence": (
                "Candidate is byte-bound to retained npnf109.xml authority; "
                "no print collation was performed."
            ),
        },
        {
            "id": "npnf109-human-textual-acceptance",
            "scope": "16 assigned works",
            "status": "unresolved",
            "question": (
                "Will the project maintainer accept this candidate after "
                "optional risk-focused human review?"
            ),
            "evidence": (
                "Technical validation is not human textual acceptance; "
                "every work remains human_review required and "
                "accepted_ir not_accepted."
            ),
        },
        {
            "id": "npnf109-publication-authorization",
            "scope": "candidate package",
            "status": "unresolved",
            "question": "Has publication been separately authorized?",
            "evidence": (
                "No publication decision is present; "
                "publication remains not_ready."
            ),
        },
    ]

    tei_bytes = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )

    return {
        "README.source.md": (
            "# Source attribution for LIB-042\n\n"
            "This nonaccepted reconstruction candidate was generated from the retained "
            "CCEL ThML member `raw/ccel/npnf1/npnf109.xml`. The retained metadata "
            "identifies Christian Classics Ethereal Library as the electronic publisher, "
            "states `Public Domain`, and identifies the print source as `New York: "
            "Christian Literature Publishing Co., 1886`.\n\n"
            "The project permission evidence states that CCEL permits parsing its ThML/XML "
            "and asks that CCEL files or derivatives of CCEL formatting not be sold. "
            "This package preserves that attribution and condition; it does not establish "
            "human textual acceptance or publication authorization.\n"
        ).encode("utf-8"),
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    """Kernel reconstruction seam bound to the inspected retained member."""

    source_manifest.verify()
    authority = source_manifest.authority_path("npnf109-retained-xml")
    expected = (source_manifest.repository_root / SOURCE_MEMBER["path"]).resolve(
        strict=True
    )
    if not authority.samefile(expected):
        raise ValueError("npnf109 retained authority path drifted")
    return convert(source_manifest.repository_root)


_convert.converter_id = PRODUCER_ID
_convert.converter_version = PRODUCER_VERSION


if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    source = SourceManifest.load(
        Path(args.source_manifest), repository_root=Path(args.repository_root)
    )
    package = reconstruct(source, Path(args.output_dir), _convert)
    print(f"Producer wrote {len(package.member_names)} members to {package.path}")
    sys.exit(0)
