"""Producer-independent retained-source oracle for the LIB-045 NPNF204 cohort."""

from __future__ import annotations

import ast
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


ORACLE_ID = "ocd-npnf204-source-to-tei-oracle"
ORACLE_VERSION = "2"
SOURCE_SHA256 = "bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652"
SOURCE_PATH = "raw/ccel/npnf2/npnf204.xml"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ASSIGNED = (
    ("vi", "athanasius-against-the-heathen"),
    ("vii", "athanasius-on-the-incarnation"),
    ("viii", "athanasius-deposition-of-arius"),
    ("ix", "eusebius-letter-on-nicene-creed"),
    ("x", "athanasius-statement-of-faith"),
    ("xi", "athanasius-on-luke-10-22"),
    ("xii", "athanasius-encyclical-letter"),
    ("xiii", "athanasius-defence-against-the-arians"),
    ("xiv", "athanasius-defence-of-the-nicene-definition"),
    ("xv", "athanasius-defence-of-dionysius"),
    ("xvi", "athanasius-life-of-antony"),
    ("xvii", "athanasius-circular-to-bishops-of-egypt-and-libya"),
    ("xviii", "athanasius-apology-to-the-emperor"),
    ("xix", "athanasius-defence-of-his-flight"),
    ("xx", "athanasius-arian-history"),
    ("xxi", "athanasius-against-the-arians"),
    ("xxii", "athanasius-on-ariminum-and-seleucia"),
    ("xxiii", "athanasius-synodal-letter-to-antioch"),
    ("xxiv", "athanasius-synodal-letter-to-africa"),
    ("xxv", "athanasius-letters-and-chronicles"),
)
ALL_DIVISIONS = (
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    *(scope for scope, _ in ASSIGNED),
    "xxvi",
)
TAG_MAP = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "p": "p",
    "i": "hi",
    "note": "note",
    "span": "seg",
    "scripRef": "ref",
    "td": "cell",
    "tr": "row",
    "table": "table",
    "pb": "pb",
    "br": "lb",
    "sup": "hi",
}
EXPECTED_COUNTS = {
    "br": 25,
    "div1": 20,
    "div2": 44,
    "div3": 215,
    "div4": 142,
    "i": 6101,
    "note": 4707,
    "p": 8291,
    "pb": 581,
    "scripRef": 2676,
    "span": 2921,
    "sup": 15,
    "table": 6,
    "td": 966,
    "tr": 180,
}
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}


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


def _source_tree(source: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_comments=False,
        huge_tree=True,
    )
    return etree.parse(io.BytesIO(source), parser)


def _divisions(tree: etree._ElementTree) -> list[etree._Element]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source lacks ThML.body")
    divisions = [
        child for child in body if isinstance(child.tag, str) and child.tag == "div1"
    ]
    if tuple(item.get("id") for item in divisions) != ALL_DIVISIONS:
        raise ValueError("retained source division accounting drift")
    return divisions


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
    return TAG_MAP[str(source.tag)]


def _expected_tei_attributes(source: etree._Element, number: int) -> dict[str, str]:
    source_id = source.get("id")
    attrs = {
        "xml:id": "npnf204-"
        + (_safe_id(source_id) if source_id else f"feature-{number:05d}")
    }
    tag = str(source.tag)
    for name, value in source.attrib.items():
        if name == "n" and tag in {"div3", "div4", "note", "pb"}:
            attrs["n"] = value
        elif name == "type" and tag in {"div3", "div4"}:
            attrs["type"] = value
        elif name == "class":
            attrs["rend"] = value
        elif name == "place" and tag == "note":
            attrs["place"] = value
        elif name == "href" and tag == "pb":
            attrs["facs"] = value
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"] = value
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"] = value
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = "grc" if value == "EL" else value.lower()
        elif name == "colspan" and tag == "td":
            attrs["cols"] = value
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    return attrs


def _expected_dispositions(source: etree._Element) -> list[dict[str, str]]:
    result = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
        if name == "id":
            destination, method = "@xml:id", "deterministic-prefix"
        elif name == "n" and tag in {"div3", "div4", "note", "pb"}:
            destination = "@n"
        elif name == "type" and tag in {"div3", "div4"}:
            destination = "@type"
        elif name == "class":
            destination = "@rend"
        elif name == "place" and tag == "note":
            destination = "@place"
        elif name == "href" and tag == "pb":
            destination = "@facs"
        elif name == "passage" and tag == "scripRef":
            destination = "@cRef"
        elif name == "osisRef" and tag == "scripRef":
            destination = "@target"
        elif name == "lang" and tag == "span":
            destination, method = "@xml:lang", "declared-language-code-map"
        elif name == "colspan" and tag == "td":
            destination = "@cols"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        result.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    return result


def _expected_rows(divisions: list[etree._Element]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def visit(
        node: etree._Element,
        parent_feature_id: str | None,
        parent_tei_id: str,
        child_ordinal: int,
    ) -> None:
        number = len(rows) + 1
        feature_id = f"npnf204-feature-{number:05d}"
        tei_attrs = _expected_tei_attributes(node, number)
        row: dict[str, object] = {
            "feature_id": feature_id,
            "source_selector": _selector(node),
            "source_tag": node.tag,
            "source_xml_id": node.get("id"),
            "attributes": dict(node.attrib),
            "direct_text": node.text or "",
            "tail_text": node.tail or "",
            "direct_text_sha256": _sha((node.text or "").encode("utf-8")),
            "tail_text_sha256": _sha((node.tail or "").encode("utf-8")),
            "tei_tag": _target_tag(node),
            "tei_xml_id": tei_attrs["xml:id"],
            "tei_parent_id": parent_tei_id,
            "tei_child_ordinal": child_ordinal,
            "tei_attributes": tei_attrs,
            "attribute_dispositions": _expected_dispositions(node),
            "disposition": "represented",
            "tei_selector": f"#{tei_attrs['xml:id']}",
            "parent_feature_id": parent_feature_id,
            "source_title_head": (
                node.get("title") if str(node.tag).startswith("div") else None
            ),
        }
        rows.append(row)
        title_offset = (
            1
            if node.get("title") is not None and str(node.tag).startswith("div")
            else 0
        )
        source_child_ordinal = 0
        for child in node:
            if not isinstance(child.tag, str):
                raise ValueError("assigned source unexpectedly contains comment or PI")
            source_child_ordinal += 1
            visit(
                child,
                feature_id,
                str(tei_attrs["xml:id"]),
                title_offset + source_child_ordinal,
            )

    for division_ordinal, division in enumerate(divisions[5:25], start=1):
        before = len(rows)
        visit(division, None, "npnf204-assigned-body", division_ordinal)
        rows[before]["work_id"] = dict(ASSIGNED)[str(division.get("id"))]
    return rows


def _normalize_tei_attributes(element: etree._Element) -> dict[str, str]:
    return {
        "xml:id"
        if key == f"{{{XML_NS}}}id"
        else "xml:lang"
        if key == f"{{{XML_NS}}}lang"
        else key: value
        for key, value in element.attrib.items()
    }


def _verify_tei_node(
    source: etree._Element,
    target: etree._Element,
    number: list[int],
) -> None:
    number[0] += 1
    expected_tag = f"{{{TEI_NS}}}{_target_tag(source)}"
    if target.tag != expected_tag:
        raise ValueError("NPNF204 TEI source-kind drift")
    if _normalize_tei_attributes(target) != _expected_tei_attributes(source, number[0]):
        raise ValueError("NPNF204 TEI semantic attribute drift")
    source_title = source.get("title") if str(source.tag).startswith("div") else None
    children = [child for child in target if isinstance(child.tag, str)]
    offset = 0
    if source_title is not None:
        if (
            not children
            or children[0].tag != f"{{{TEI_NS}}}head"
            or children[0].text != source_title
        ):
            raise ValueError("NPNF204 TEI division title drift")
        if children[0].tail not in {None, ""}:
            raise ValueError("NPNF204 TEI invented title tail")
        offset = 1
    if (target.text or "") != (source.text or "") or (target.tail or "") != (
        source.tail or ""
    ):
        raise ValueError("NPNF204 TEI direct text or tail drift")
    source_children = [child for child in source if isinstance(child.tag, str)]
    if len(children) - offset != len(source_children):
        raise ValueError("NPNF204 TEI omission duplication or invention")
    for source_child, target_child in zip(
        source_children, children[offset:], strict=True
    ):
        _verify_tei_node(source_child, target_child, number)


def _verify_document_shell(content: bytes, tree: etree._ElementTree) -> None:
    declaration = b"<?xml version='1.0' encoding='UTF-8'?>\n"
    if not content.startswith(declaration):
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
            namespace = etree.QName(name).namespace
            if namespace not in {None, XML_NS}:
                raise ValueError("TEI attribute namespace drift")


def _verify_tei(source_tree: etree._ElementTree, content: bytes) -> None:
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
        raise ValueError("NPNF204 TEI is not well-formed XML") from exc
    _verify_document_shell(content, tree)
    root = tree.getroot()
    if (
        root.tag != f"{{{TEI_NS}}}TEI"
        or _normalize_tei_attributes(root) != {"xml:id": "npnf204-lib045"}
        or (root.text or "") != ""
        or (root.tail or "") != ""
    ):
        raise ValueError("NPNF204 TEI root drift")
    root_children = [child for child in root if isinstance(child.tag, str)]
    if [child.tag for child in root_children] != [
        f"{{{TEI_NS}}}teiHeader",
        f"{{{TEI_NS}}}text",
    ]:
        raise ValueError("NPNF204 TEI root topology drift")
    headers = root.xpath("/tei:TEI/tei:teiHeader", namespaces={"tei": TEI_NS})
    expected_header = (
        '<teiHeader xmlns="http://www.tei-c.org/ns/1.0"><fileDesc><titleStmt>'
        "<title>NPNF2-04. Athanasius: Select Works and Letters — assigned works vi–xxv</title>"
        "<author>Athanasius of Alexandria and Eusebius of Caesarea</author>"
        "<respStmt><resp>editorial supervisor</resp><name>Philip Schaff</name></respStmt>"
        "<respStmt><resp>editorial supervisor</resp><name>Henry Wace</name></respStmt>"
        "<respStmt><resp>special editor; prolegomena, indices, and tables</resp><name>Archibald Robertson</name></respStmt>"
        "<respStmt><resp>translation reader</resp><name>J. H. Lupton</name></respStmt>"
        "<respStmt><resp>translator of Life of Antony</resp><name>H. Ellershaw</name></respStmt>"
        "<respStmt><resp>translator whose earlier translations were revised where retained evidence specifies</resp><name>John Henry Newman</name></respStmt>"
        "<respStmt><resp>reviser of the Oxford translation of the bulk of the Festal Letters</resp><name>Miss Payne Smith</name></respStmt>"
        "</titleStmt><publicationStmt><publisher>Open Christian Data</publisher>"
        '<availability status="restricted"><p>The local source configs label the underlying texts public domain. CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Attribution is included in README.source.md. Human acceptance and publication remain absent.</p></availability>'
        '</publicationStmt><sourceDesc><bibl><ptr target="https://www.ccel.org/ccel/schaff/npnf204.xml"/>'
        '<idno type="sha256">bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652</idno>'
        '<note type="print-source">NPNF Second Series, Volume IV: Athanasius: Select Works and Letters (retained title pages; no print collation)</note>'
        "</bibl></sourceDesc></fileDesc></teiHeader>"
    )
    if (
        len(headers) != 1
        or etree.tostring(headers[0], encoding="unicode") != expected_header
    ):
        raise ValueError("NPNF204 complete TEI header drift")
    text = root_children[1]
    text_children = [child for child in text if isinstance(child.tag, str)]
    if (
        _normalize_tei_attributes(text) != {}
        or (text.text or "") != ""
        or (text.tail or "") != ""
        or [child.tag for child in text_children] != [f"{{{TEI_NS}}}body"]
    ):
        raise ValueError("NPNF204 TEI text topology drift")
    body = text_children[0]
    if (
        _normalize_tei_attributes(body) != {"xml:id": "npnf204-assigned-body"}
        or (body.text or "") != ""
        or (body.tail or "") != ""
    ):
        raise ValueError("NPNF204 TEI body drift")
    source_divisions = _divisions(source_tree)[5:25]
    target_divisions = [child for child in body if isinstance(child.tag, str)]
    if len(target_divisions) != 20:
        raise ValueError("NPNF204 assigned work count drift")
    number = [0]
    for source_division, target_division in zip(
        source_divisions, target_divisions, strict=True
    ):
        _verify_tei_node(source_division, target_division, number)
    if number[0] != 26890:
        raise ValueError("NPNF204 TEI feature count drift")
    table = root.xpath("//*[@xml:id='npnf204-vii.i-p19.1']", namespaces={"xml": XML_NS})
    if (
        len(table) != 1
        or len(table[0].xpath(".//tei:row", namespaces={"tei": TEI_NS})) != 55
        or len(table[0].xpath(".//tei:cell", namespaces={"tei": TEI_NS})) != 165
    ):
        raise ValueError("preserved Athanasius table route drift")
    try:
        compiled_schema().assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("NPNF204 candidate fails TEI P5 validation") from exc


def _expected_work_credit(scope: str) -> dict[str, object]:
    if scope == "xvi":
        return {
            "status": "retained-explicit",
            "credited_to": "H. Ellershaw",
            "role": "translator",
            "source_xml_ids": ["iv-p11", "xvi.ii.i-p50"],
        }
    if scope == "xxii":
        return {
            "status": "retained-explicit",
            "credited_to": "John Henry Newman",
            "role": "translator; translation more closely revised for this edition",
            "source_xml_ids": ["ii-p4", "iv-p4", "xxii.i-p13"],
        }
    if scope in {"xxiii", "xxiv"}:
        return {
            "status": "retained-explicit-anonymous",
            "credited_to": None,
            "role": "translation independently made and collated with Bright",
            "source_xml_ids": ["xxiii.i-p9"],
        }
    if scope == "xxv":
        return {
            "status": "retained-component-level",
            "credited_to": "Miss Payne Smith",
            "role": "reviser of the Oxford translation of the bulk of the Festal Letters",
            "source_xml_ids": ["iv-p11", "xxv.iii.i-p20"],
        }
    return {
        "status": "unresolved",
        "credited_to": None,
        "role": None,
        "source_xml_ids": [],
    }


def _text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained credit evidence {source_id} drift")
    return "".join(nodes[0].itertext())


def _verify_evidence_members(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    source_tree: etree._ElementTree,
    rows: list[dict[str, object]],
) -> None:
    divisions = _divisions(source_tree)
    mapping = dict(ASSIGNED)
    expected_divisions = [
        {
            "ordinal": index,
            "div1_id": str(div.get("id")),
            "title": div.get("title", ""),
            "disposition": "assigned-work-represented"
            if div.get("id") in mapping
            else "outside-assigned-work-scope",
            "work_id": mapping.get(str(div.get("id"))),
        }
        for index, div in enumerate(divisions, start=1)
    ]
    expected_accountability = {
        "contract": "ocd-npnf204-source-accountability-v1",
        "schema": "athanasius-table.source-accountability.schema.json",
        "profile_id": "npnf204-assigned-div1-vi-through-xxv-v1",
        "source_scope": "retained ThML.body div1 vi through xxv",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": 5809854,
            "sha256": SOURCE_SHA256,
            "disposition": "included as the sole retained member",
        },
        "document_accounting": {
            "xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>',
            "doctype": '<!DOCTYPE ThML PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
            "pre_root_comment": " Copyright Christian Classics Ethereal Library ",
            "pre_root_comment_disposition": "retained witness evidence outside assigned work scope",
            "assigned_comment_count": 0,
            "assigned_processing_instruction_count": 0,
        },
        "assigned_work_count": 20,
        "feature_count": 26890,
        "attribute_count": 57398,
        "feature_counts": EXPECTED_COUNTS,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": {"tables": 6, "rows": 180, "cells": 966},
        "preserved_table_route": {
            "div1_id": "vii",
            "feature_count": 1241,
            "table_id": "vii.i-p19.1",
            "tables": 1,
            "rows": 55,
            "cells": 165,
        },
        "division_accounting": expected_divisions,
        "crosswalk": rows,
    }
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "source accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"NPNF204 accountability schema failure: {errors[0].message}")
    if accountability != expected_accountability:
        raise ValueError("NPNF204 crosswalk accountability drift")

    credit_ids = (
        "i-p8",
        "i-p10",
        "i-p11",
        "i-p14",
        "ii-p3",
        "ii-p4",
        "ii-p5",
        "iii-p4",
        "iii-p6",
        "iv-p4",
        "iv-p11",
        "xvi.ii.i-p50",
        "xxii.i-p13",
        "xxiii.i-p9",
        "xxv.iii.i-p20",
    )
    expected_provenance = {
        "contract": "ocd-npnf204-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source": {
            "path": SOURCE_PATH,
            "sha256": SOURCE_SHA256,
            "scope": "div1 vi through xxv",
        },
        "works": [
            {
                "ordinal": index,
                "div1_id": scope,
                "work_id": work_id,
                "source_title": divisions[index + 4].get("title", ""),
                "author": "Eusebius of Caesarea"
                if scope == "ix"
                else "Athanasius of Alexandria",
                "translation_credit": _expected_work_credit(scope),
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
            }
            for index, (scope, work_id) in enumerate(ASSIGNED, start=1)
        ],
        "edition": {
            "title": "Athanasius: Select Works and Letters",
            "series": "A Select Library of the Nicene and Post-Nicene Fathers of the Christian Church, Second Series, Volume IV",
            "editorial_supervision": ["Philip Schaff", "Henry Wace"],
            "special_editor": "Archibald Robertson",
            "special_editor_roles": ["editor", "prolegomena", "indices", "tables"],
            "source_identifier": "https://www.ccel.org/ccel/schaff/npnf204.xml",
            "print_collation": "not-performed",
        },
        "credit_evidence": {
            source_id: _text(source_tree, source_id) for source_id in credit_ids
        },
        "rights": {
            "local_config_claim": "public-domain",
            "ccel_permission": "parsing permitted; do not sell CCEL files or derivatives of CCEL formatting",
            "attribution": "sourced via CCEL.org",
            "human_acceptance": "absent",
            "publication_state": "not_ready",
        },
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    provenance = _strict_json(candidate.member_bytes("provenance.json"), "provenance")
    if provenance != expected_provenance:
        raise ValueError("NPNF204 provenance semantic drift")

    expected_unresolved = [
        {
            "id": "npnf204-work-specific-translation-allocation",
            "scope": "assigned works except exact retained allocations",
            "status": "unresolved",
            "question": "Which translator or reviser applies to each assigned work or component not explicitly allocated by retained evidence?",
            "evidence": "The retained preface describes mixed new and revised translations but only safely names exact allocations for Life of Antony, de Synodis, the anonymous Antioch/Africa group, and Festal Letter components.",
        },
        {
            "id": "npnf204-print-collation-not-performed",
            "scope": "edition",
            "status": "unresolved",
            "question": "Does the retained CCEL witness differ substantively from the print edition identified by its retained title pages?",
            "evidence": "The candidate is bound to retained CCEL XML; no print collation was performed.",
        },
        {
            "id": "npnf204-rights-human-acceptance-and-publication",
            "scope": "all-20-assigned-works",
            "status": "unresolved",
            "question": "Will a maintainer accept these candidates and separately authorize publication after rights review?",
            "evidence": "Technical verification is not human textual acceptance, a rights decision, or publication authorization.",
        },
    ]
    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    if unresolved_bytes != b"".join(_canonical(item) for item in expected_unresolved):
        raise ValueError("NPNF204 unresolved evidence drift")

    expected_readme = """# NPNF2-04 assigned-work reconstruction source

This nonaccepted TEI candidate is reconstructed deterministically from the retained `raw/ccel/npnf2/npnf204.xml` member. It represents exactly the twenty assigned `div1` scopes vi through xxv. The retained title page, editorial front matter, prolegomena, and index divisions i through v and xxvi are outside assigned work scope and are explicitly accounted as exclusions; their primary metadata and contributor evidence is recorded in the review packet.

The retained title page places the series under the editorial supervision of Philip Schaff and Henry Wace. It identifies Archibald Robertson as editor with prolegomena, indices, and tables. The retained editorial preface credits J. H. Lupton with reading the translations throughout. Work-level credit is not inferred: H. Ellershaw is explicitly credited for the Life of Antony; Newman's de Synodis translation is explicitly said to have been more closely revised; the Antioch/Africa group is described as independently translated and collated with Bright without naming its translator; and Miss Payne Smith revised the Oxford translation of the bulk of the Festal Letters.

The retained electronic edition is sourced via [CCEL.org](https://www.ccel.org/ccel/schaff/npnf204.xml). CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Local source configs label the underlying texts public domain. These statements remain evidence rather than a human rights or publication decision.

All twenty works remain `accepted_ir:not_accepted`, `human_review:required`, and `publication:not_ready`. Human textual acceptance and publication authorization are separate and absent.
""".encode("utf-8")
    if candidate.member_bytes("README.source.md") != expected_readme:
        raise ValueError("NPNF204 README attribution drift")
    permission = source_manifest.authority_path("ccel-permission").read_bytes()
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
    pending = ["build.tei.athanasius_table_oracle"]
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

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import_name(
                    module,
                    path,
                    node.module,
                    node.level,
                )
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
    records = []
    for path in _closure_paths(root, policy):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha(path.read_bytes()),
            }
        )
    return _sha(_canonical(records))


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    if (
        set(candidate.member_names) != MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("NPNF204 candidate member or status drift")
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
        raise ValueError("NPNF204 candidate authority binding drift")
    source = source_manifest.authority_path("retained-thml").read_bytes()
    if len(source) != 5809854 or _sha(source) != SOURCE_SHA256:
        raise ValueError("NPNF204 source member drift")
    source_tree = _source_tree(source)
    rows = _expected_rows(_divisions(source_tree))
    if len(rows) != 26890 or sum(len(row["attributes"]) for row in rows) != 57398:
        raise ValueError("NPNF204 independent source census drift")
    tei = candidate.member_bytes("content.tei.xml")
    _verify_tei(source_tree, tei)
    _verify_evidence_members(source_manifest, candidate, source_tree, rows)

    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy = _strict_json(policy_bytes, "validation policy")
    profile = _strict_json(profile_bytes, "reconstruction profile")
    if (
        policy.get("candidate_status") != "nonaccepted"
        or policy.get("publication_state") != "not_ready"
        or profile.get("assigned_feature_count") != 26890
    ):
        raise ValueError("NPNF204 profile or policy drift")
    implementation = Path(__file__).resolve()
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(implementation.read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": SOURCE_SHA256,
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
