"""Producer-independent retained-source oracle for LIB-039 NPNF103."""

from __future__ import annotations

import ast
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import (
    MechanicalFacts,
    verify_mechanical_facts,
)
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-npnf103-source-to-tei-oracle"
ORACLE_VERSION = "1"
SOURCE_PATH = "raw/ccel/npnf1/npnf103.xml"
SOURCE_SHA256 = "410f240f8105bb6097316a54a867fa5a4ae02c0d3d03606aefc2df71f5bfc455"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
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
MEMBERS = {
    "manifest.json",
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
CREDIT_IDS = (
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


def _structure(
    tree: etree._ElementTree,
) -> tuple[list[etree._Element], list[etree._Element]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source lacks ThML.body")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    if tuple(node.get("id") for node in top) != TOP_LEVEL_DIVISIONS:
        raise ValueError("retained source top-level division accounting drift")
    direct = [
        node
        for wrapper in top
        for node in wrapper
        if isinstance(node.tag, str) and node.tag == "div2"
    ]
    if tuple(node.get("id") for node in direct) != DIRECT_DIV2:
        raise ValueError("retained source direct div2 accounting drift")
    return top, direct[: len(ASSIGNED)]


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
        "xml:id": "npnf103-"
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
    if tag == "i":
        attrs["rend"] = "italic"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    return attrs


def _expected_dispositions(source: etree._Element) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
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


def _expected_rows(selected: list[etree._Element]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def visit(
        node: etree._Element,
        parent_feature_id: str | None,
        parent_tei_id: str,
        child_ordinal: int,
    ) -> None:
        number = len(rows) + 1
        feature_id = f"npnf103-feature-{number:05d}"
        attrs = _expected_tei_attributes(node, number)
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
            "tei_xml_id": attrs["xml:id"],
            "tei_parent_id": parent_tei_id,
            "tei_child_ordinal": child_ordinal,
            "tei_attributes": attrs,
            "attribute_dispositions": _expected_dispositions(node),
            "disposition": "represented",
            "tei_selector": f"#{attrs['xml:id']}",
            "parent_feature_id": parent_feature_id,
            "source_title_head": (
                node.get("title") if str(node.tag).startswith("div") else None
            ),
        }
        rows.append(row)
        title_offset = int(
            node.get("title") is not None and str(node.tag).startswith("div")
        )
        source_ordinal = 0
        for child in node:
            if not isinstance(child.tag, str):
                raise ValueError("assigned source unexpectedly contains comment or PI")
            source_ordinal += 1
            visit(
                child, feature_id, str(attrs["xml:id"]), title_offset + source_ordinal
            )

    for ordinal, (division, (_, work_id)) in enumerate(
        zip(selected, ASSIGNED, strict=True), start=1
    ):
        before = len(rows)
        visit(division, None, "npnf103-assigned-body", ordinal)
        rows[before]["work_id"] = work_id
    return rows


def _normalize_attributes(element: etree._Element) -> dict[str, str]:
    return {
        "xml:id"
        if key == f"{{{XML_NS}}}id"
        else "xml:lang"
        if key == f"{{{XML_NS}}}lang"
        else key: value
        for key, value in element.attrib.items()
    }


def _verify_node(
    source: etree._Element, target: etree._Element, number: list[int]
) -> None:
    number[0] += 1
    if target.tag != f"{{{TEI_NS}}}{_target_tag(source)}":
        raise ValueError("NPNF103 TEI source-kind drift")
    if _normalize_attributes(target) != _expected_tei_attributes(source, number[0]):
        raise ValueError("NPNF103 TEI semantic attribute drift")
    title = source.get("title") if str(source.tag).startswith("div") else None
    children = [child for child in target if isinstance(child.tag, str)]
    offset = 0
    if title is not None:
        if (
            not children
            or children[0].tag != f"{{{TEI_NS}}}head"
            or children[0].text != title
            or (children[0].tail or "") != ""
            or _normalize_attributes(children[0])
        ):
            raise ValueError("NPNF103 TEI division title drift")
        offset = 1
    if (target.text or "") != (source.text or "") or (target.tail or "") != (
        source.tail or ""
    ):
        raise ValueError("NPNF103 TEI direct text or tail drift")
    source_children = [child for child in source if isinstance(child.tag, str)]
    if len(children) - offset != len(source_children):
        raise ValueError("NPNF103 TEI omission duplication or invention")
    for source_child, target_child in zip(
        source_children, children[offset:], strict=True
    ):
        _verify_node(source_child, target_child, number)


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
            if etree.QName(name).namespace not in {None, XML_NS}:
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
        raise ValueError("NPNF103 TEI is not well-formed XML") from exc
    _verify_document_shell(content, tree)
    root = tree.getroot()
    if (
        root.tag != f"{{{TEI_NS}}}TEI"
        or _normalize_attributes(root) != {"xml:id": "npnf103-lib039"}
        or (root.text or "") != ""
        or (root.tail or "") != ""
    ):
        raise ValueError("NPNF103 TEI root drift")
    children = [child for child in root if isinstance(child.tag, str)]
    if [child.tag for child in children] != [
        f"{{{TEI_NS}}}teiHeader",
        f"{{{TEI_NS}}}text",
    ]:
        raise ValueError("NPNF103 TEI root topology drift")
    expected_header = (
        '<teiHeader xmlns="http://www.tei-c.org/ns/1.0"><fileDesc><titleStmt>'
        "<title>NPNF1-03. On the Holy Trinity; Doctrinal Treatises; Moral Treatises — sixteen assigned works</title>"
        "<author>Augustine of Hippo</author>"
        "<respStmt><resp>editor</resp><name>Philip Schaff</name></respStmt>"
        "<respStmt><resp>translator of On the Holy Trinity</resp><name>Arthur West Haddan</name></respStmt>"
        "<respStmt><resp>reviser, annotator, and introductory essay author for On the Holy Trinity</resp><name>William G. T. Shedd</name></respStmt>"
        "<respStmt><resp>translator of The Enchiridion</resp><name>J. F. Shaw</name></respStmt>"
        "<respStmt><resp>translator of two assigned doctrinal treatises</resp><name>S. D. F. Salmond</name></respStmt>"
        "<respStmt><resp>retained translator credit for assigned doctrinal and moral treatises</resp><name>C. L. Cornish</name></respStmt>"
        "<respStmt><resp>source-spelled translator credit for Of Holy Virginity</resp><name>C. I. Cornish</name></respStmt>"
        "<respStmt><resp>translator of five assigned moral treatises</resp><name>H. Browne</name></respStmt>"
        "</titleStmt><publicationStmt><publisher>Open Christian Data</publisher>"
        '<availability status="restricted"><p>The retained CCEL header states Public Domain. CCEL permits parsing its ThML; do not sell CCEL files or derivatives of CCEL formatting. Attribution is included in README.source.md. Human acceptance and publication remain absent.</p></availability>'
        '</publicationStmt><sourceDesc><bibl><ptr target="https://www.ccel.org/ccel/schaff/npnf103.html"/>'
        '<idno type="sha256">410f240f8105bb6097316a54a867fa5a4ae02c0d3d03606aefc2df71f5bfc455</idno>'
        '<note type="print-source">Retained title page: Volume III, T&amp;T Clark (Edinburgh) and Wm. B. Eerdmans Publishing Company (Grand Rapids, Michigan), no date; retained CCEL printSourceInfo separately states New York: The Christian Literature Publishing Co., 1890; no print collation</note>'
        "</bibl></sourceDesc></fileDesc></teiHeader>"
    )
    if etree.tostring(children[0], encoding="unicode") != expected_header:
        raise ValueError("NPNF103 complete TEI header drift")
    text = children[1]
    text_children = [child for child in text if isinstance(child.tag, str)]
    if (
        _normalize_attributes(text)
        or (text.text or "") != ""
        or (text.tail or "") != ""
        or [child.tag for child in text_children] != [f"{{{TEI_NS}}}body"]
    ):
        raise ValueError("NPNF103 TEI text topology drift")
    body = text_children[0]
    if (
        _normalize_attributes(body) != {"xml:id": "npnf103-assigned-body"}
        or (body.text or "") != ""
        or (body.tail or "") != ""
    ):
        raise ValueError("NPNF103 TEI body drift")
    selected = _structure(source_tree)[1]
    target_divisions = [child for child in body if isinstance(child.tag, str)]
    if len(target_divisions) != 16:
        raise ValueError("NPNF103 assigned work count drift")
    number = [0]
    for source_division, target_division in zip(
        selected, target_divisions, strict=True
    ):
        _verify_node(source_division, target_division, number)
    if number[0] != 12_832:
        raise ValueError("NPNF103 TEI feature count drift")
    try:
        compiled_schema().assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("NPNF103 candidate fails TEI P5 validation") from exc


def _text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath(f"//*[@id='{source_id}']")
    if len(nodes) != 1:
        raise ValueError(f"retained credit evidence {source_id} drift")
    return "".join(nodes[0].itertext())


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


def _division_accounting(top: list[etree._Element]) -> list[dict[str, object]]:
    reasons = {
        "i": "title page used as edition and attribution evidence; outside exact work roots",
        "ii": "edition preface used as contextual evidence; outside exact work roots",
        "iii": "contents used as title and credit evidence; outside exact work roots",
        "iv": "doctrinal-treatises wrapper; all seven direct work children represented, wrapper itself excluded",
        "v": "moral-treatises wrapper; all nine direct work children represented, wrapper itself excluded",
        "vi": "subject indexes are outside the sixteen assigned work roots",
        "vii": "scripture, Greek-phrase, and print-page indexes are outside the sixteen assigned work roots",
    }
    return [
        {
            "ordinal": ordinal,
            "div1_id": node.get("id"),
            "title": node.get("title", ""),
            "disposition": "source-evidence-outside-work-projection",
            "reason": reasons[str(node.get("id"))],
        }
        for ordinal, node in enumerate(top, start=1)
    ]


def _direct_accounting(tree: etree._ElementTree) -> list[dict[str, object]]:
    mapping = dict(ASSIGNED)
    return [
        {
            "ordinal": ordinal,
            "div2_id": node.get("id"),
            "parent_div1_id": node.getparent().get("id"),
            "title": node.get("title", ""),
            "disposition": "assigned-work-represented"
            if node.get("id") in mapping
            else "index-outside-assigned-work-scope",
            "reason": "complete retained work subtree projected in source order"
            if node.get("id") in mapping
            else "retained index division is not one of the sixteen assigned works",
            "work_id": mapping.get(str(node.get("id"))),
        }
        for ordinal, node in enumerate(tree.xpath("//ThML.body/div1/div2"), start=1)
    ]


def _verify_evidence(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    source_tree: etree._ElementTree,
    rows: list[dict[str, object]],
) -> None:
    top, selected = _structure(source_tree)
    total_nodes = [
        node for node in source_tree.getroot().iter() if isinstance(node.tag, str)
    ]
    selected_nodes = [node for division in selected for node in division.iter()]
    complete = _census(total_nodes)
    assigned = _census(selected_nodes)
    excluded = {key: complete[key] - assigned[key] for key in complete}
    counts: dict[str, int] = {}
    for row in rows:
        tag = str(row["source_tag"])
        counts[tag] = counts.get(tag, 0) + 1
    expected_accountability = {
        "contract": "ocd-npnf103-source-accountability-v1",
        "schema": "augustine-npnf103.source-accountability.schema.json",
        "profile_id": "npnf103-assigned-div2-iv-i-through-v-ix-v1",
        "source_scope": "retained ThML.body div1 iv/v direct div2 iv.i–iv.vii and v.i–v.ix",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": 3_842_341,
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
            "complete_document": complete,
            "assigned_scope": assigned,
            "excluded_shell_front_and_indexes": excluded,
        },
        "assigned_work_count": 16,
        "feature_count": 12_832,
        "attribute_count": 35_788,
        "feature_counts": counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": {"tables": 0, "rows": 0, "cells": 0},
        "top_level_division_accounting": _division_accounting(top),
        "direct_div2_accounting": _direct_accounting(source_tree),
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
        raise ValueError(f"NPNF103 accountability schema failure: {errors[0].message}")
    if accountability != expected_accountability:
        raise ValueError("NPNF103 crosswalk accountability drift")

    expected_provenance = {
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
        "credit_evidence": {
            source_id: _text(source_tree, source_id) for source_id in CREDIT_IDS
        },
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
    if (
        _strict_json(candidate.member_bytes("provenance.json"), "provenance")
        != expected_provenance
    ):
        raise ValueError("NPNF103 provenance semantic drift")

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
    if candidate.member_bytes("unresolved.jsonl") != b"".join(
        _canonical(item) for item in unresolved
    ):
        raise ValueError("NPNF103 unresolved evidence drift")
    source_readme = source_manifest.authority_path(
        "source-local-attribution-readme"
    ).read_bytes()
    if candidate.member_bytes("README.source.md") != source_readme:
        raise ValueError("NPNF103 README attribution drift")
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
    module: str, module_path: Path, imported: str | None, level: int
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
    pending = ["build.tei.npnf103_oracle"]
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
        raise ValueError("NPNF103 candidate member or status drift")
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
        raise ValueError("NPNF103 candidate authority binding drift")
    source = source_manifest.authority_path("retained-thml").read_bytes()
    if len(source) != 3_842_341 or _sha(source) != SOURCE_SHA256:
        raise ValueError("NPNF103 source member drift")
    source_tree = _source_tree(source)
    selected = _structure(source_tree)[1]
    rows = _expected_rows(selected)
    if (
        len(rows) != 12_832
        or sum(len(row["attributes"]) for row in rows) != 35_788
        or {
            tag: sum(row["source_tag"] == tag for row in rows)
            for tag in EXPECTED_COUNTS
        }
        != EXPECTED_COUNTS
    ):
        raise ValueError("NPNF103 independent source census drift")
    _verify_tei(source_tree, candidate.member_bytes("content.tei.xml"))
    _verify_evidence(source_manifest, candidate, source_tree, rows)

    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy = _strict_json(policy_bytes, "validation policy")
    profile = _strict_json(profile_bytes, "reconstruction profile")
    if (
        policy.get("candidate_status") != "nonaccepted"
        or policy.get("publication_state") != "not_ready"
        or profile.get("assigned_feature_count") != 12_832
        or profile.get("assigned_attribute_count") != 35_788
    ):
        raise ValueError("NPNF103 profile or policy drift")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).resolve().read_bytes()),
        validator_import_closure_sha256=_closure_digest(root, policy),
        source_sha256=SOURCE_SHA256,
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
