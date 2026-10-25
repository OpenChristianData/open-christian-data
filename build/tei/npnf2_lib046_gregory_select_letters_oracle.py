"""Producer-independent oracle for Gregory of Nazianzus's Select Letters."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import platform
import sys
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-npnf2-lib046-gregory-select-letters-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
SOURCE_KEY = "npnf207"
SOURCE_PATH = "raw/ccel/npnf2/npnf207.xml"
SOURCE_BYTES = 4_247_548
SOURCE_SHA256 = "3ac73f4179c0b7d6e66e6fea04ae572e64c0e4a80e8fa38980b40366c8a13928"
ROOT_ID = "iv"
WORK_ID = "gregory-of-nazianzus-select-letters"
ROOT_TITLE = "Select Letters of Saint Gregory Nazianzen."
PROFILE_ID = "gregory-of-nazianzus-select-letters-npnf2-v1"
TAG_MAP = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "p": "p",
    "note": "note",
    "i": "hi",
    "span": "seg",
    "pb": "pb",
    "scripRef": "ref",
    "sup": "hi",
    "hr": "milestone",
    "img": "ref",
    "a": "ref",
}
EXPECTED_CENSUS = {
    "elements": 892,
    "attributes": 2663,
    "text_nodes": 634,
    "tail_nodes": 660,
    "characters": 204374,
    "non_ascii_characters": 1326,
    "notes": 89,
    "page_breaks": 47,
    "scripture_refs": 62,
}
EXPECTED_DOCUMENT_CENSUS = {
    "elements": 29789,
    "attributes": 61308,
    "text_nodes": 22880,
    "tail_nodes": 21128,
    "characters": 2647282,
    "non_ascii_characters": 65980,
    "notes": 4782,
    "page_breaks": 515,
    "scripture_refs": 3392,
}
EXPECTED_TOP_LEVEL_IDS = ["i", "ii", "iii", "iv", "v"]
EXPECTED_DIV2_IDS = ["iv.i", "iv.ii", "iv.iii", "iv.iv"]
CREDIT_IDS = [
    "i-p10",
    "i-p11",
    "i-p13",
    "i-p14",
    "iii.i-p5",
    "iii.i-p6",
    "iii.i-p9",
]
CREDIT_NAMES = [
    "Philip Schaff",
    "Henry Wace",
    "Charles Gordon Browne",
    "James Edward Swallow",
]
README_TEXT = """# LIB-046 retained source: Gregory of Nazianzus, Select Letters

This is a nonaccepted, source-local technical candidate for the complete
`div1` `iv` subtree in the retained NPNF2-07 ThML member. The textual
authority is the exact retained XML member recorded in the candidate manifest;
the candidate does not claim a durable accepted master, accepted IR, or public
publication.

The retained electronic witness was sourced via CCEL.org. CCEL's permission
and attribution evidence is bound separately in the source manifest. The
candidate preserves the retained source's wording, order, meaningful division,
notes, page breaks, references, and source attributes through its TEI and
accountability members.
"""


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not isinstance(value, dict) or _canonical(value) != content:
        raise ValueError(f"{label} is not a canonical JSON object")
    return value


def _authority_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _source_tree(content: bytes) -> etree._ElementTree:
    return etree.parse(
        io.BytesIO(content),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            remove_pis=False,
            huge_tree=True,
        ),
    )


def _tei_tree(content: bytes) -> etree._ElementTree:
    try:
        return etree.ElementTree(
            etree.fromstring(
                content,
                etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    remove_comments=False,
                    remove_pis=False,
                    huge_tree=True,
                ),
            )
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("candidate TEI is not well formed") from exc


def _safe(value: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]", "-", value) or "source"


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            break
        peers = [child for child in parent if child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _source_text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath("//*[@id=$source_id]", source_id=source_id)
    if len(nodes) != 1:
        raise ValueError(f"retained evidence {source_id!r} is not unique")
    return "".join(nodes[0].itertext())


def _source_metadata(tree: etree._ElementTree) -> dict[str, Any]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("retained source lacks ThML.head")
    return {
        "head_c14n_sha256": _sha(
            etree.tostring(head, method="c14n", with_comments=True)
        ),
        "dc_entries": [
            {
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text or "",
                "tail": node.tail or "",
            }
            for node in tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/*")
        ],
        "print_source_entries": [
            {
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text or "",
                "tail": node.tail or "",
            }
            for node in tree.xpath("/ThML/ThML.head/printSourceInfo/*")
        ],
    }


def _document_accounting(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    before: list[dict[str, str]] = []
    node = root.getprevious()
    while node is not None:
        before.append(
            {
                "kind": "comment"
                if node.tag is etree.Comment
                else "processing-instruction",
                "text": node.text or "",
                "tail": node.tail or "",
            }
        )
        node = node.getprevious()
    before.reverse()
    after: list[dict[str, str]] = []
    node = root.getnext()
    while node is not None:
        after.append(
            {
                "kind": "comment"
                if node.tag is etree.Comment
                else "processing-instruction",
                "text": node.text or "",
                "tail": node.tail or "",
            }
        )
        node = node.getnext()
    return {
        "xml_version": tree.docinfo.xml_version,
        "encoding": tree.docinfo.encoding,
        "standalone": tree.docinfo.standalone,
        "doctype": tree.docinfo.doctype,
        "root_tag": root.tag,
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": {
            "" if key is None else key: value for key, value in root.nsmap.items()
        },
        "pre_root_nodes": before,
        "post_root_nodes": after,
    }


def _census(nodes: list[etree._Element]) -> dict[str, int]:
    elements = [node for node in nodes if isinstance(node.tag, str)]
    strings = [(node.text or "") + (node.tail or "") for node in nodes]
    return {
        "elements": len(elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len(value) for value in strings),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in value) for value in strings
        ),
        "notes": sum(node.tag == "note" for node in elements),
        "page_breaks": sum(node.tag == "pb" for node in elements),
        "scripture_refs": sum(node.tag == "scripRef" for node in elements),
    }


def _target_tag(source: etree._Element) -> str:
    if source.tag == "span" and source.get("lang"):
        return "foreign"
    return TAG_MAP[str(source.tag)]


def _target_attrs(
    source: etree._Element,
    ordinal: int,
    work_id: str | None,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Derive expected TEI attributes directly from source data."""

    attrs = {
        "xml:id": f"lib046-gregory-select-letters-{ordinal:06d}-{_safe(source.get('id') or str(source.tag))}"
    }
    dispositions: list[dict[str, str]] = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly-in-accountability"
        if name == "id":
            destination = "@xml:id-and-source-accountability"
            method = "deterministic-member-and-ordinal-prefix"
        elif name == "n" and tag in {"div1", "div2", "div3", "div4", "note", "pb"}:
            attrs["n"] = value
            destination = "@n"
            method = "preserved-exactly-in-TEI"
        elif name == "type" and tag in {"div1", "div2", "div3", "div4"} and not work_id:
            attrs["type"] = value
            destination = "@type"
            method = "preserved-exactly-in-TEI"
        elif name == "class" and tag in {"p", "span"}:
            attrs["rend"] = value
            destination = "@rend"
            method = "preserved-exactly-in-TEI"
        elif name == "style" and tag in {"p", "hr"}:
            attrs["rend"] = value
            destination = "@rend"
            method = "preserved-exactly-in-TEI"
        elif name == "place" and tag == "note":
            attrs["place"] = value
            destination = "@place"
            method = "preserved-exactly-in-TEI"
        elif name == "href" and tag == "pb":
            attrs["facs"] = value
            destination = "@facs"
            method = "preserved-exactly-in-TEI"
        elif name == "href" and tag == "a":
            attrs["target"] = value
            destination = "@target"
            method = "preserved-exactly-in-TEI"
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"] = value
            destination = "@cRef"
            method = "preserved-exactly-in-TEI"
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"] = value
            destination = "@target"
            method = "preserved-exactly-in-TEI"
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = {"EL": "grc", "HE": "he", "LA": "la"}.get(
                value, value.lower()
            )
            destination = "@xml:lang"
            method = "declared-language-code-map"
        elif name == "dir" and tag == "span":
            attrs["rend"] = (attrs.get("rend", "") + f" direction:{value}").strip()
            destination = "@rend"
            method = "preserved-exactly-in-TEI"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
            method = "preserved-exactly-in-TEI"
        dispositions.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    if work_id:
        attrs.update({"type": "work", "subtype": work_id})
    elif tag.startswith("div") and "type" not in attrs:
        attrs["type"] = f"source-{tag}"
    elif tag == "i":
        attrs["rend"] = "italic"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef":
        attrs["type"] = "scripture"
    elif tag == "span" and "lang" not in source.attrib:
        attrs["type"] = "source-span"
    elif tag == "hr":
        attrs["unit"] = "horizontal-rule"
    elif tag == "img":
        attrs["type"] = "source-image"
    return attrs, dispositions


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in node.attrib.items():
        if key == f"{{{XML_NS}}}id":
            result["xml:id"] = value
        elif key == f"{{{XML_NS}}}lang":
            result["xml:lang"] = value
        else:
            result[key] = value
    return result


def _expected_row(
    source: etree._Element,
    ordinal: int,
    parent_feature_id: str | None,
    work_id: str | None,
) -> dict[str, Any]:
    attrs, dispositions = _target_attrs(source, ordinal, work_id)
    tag = _target_tag(source)
    return {
        "feature_id": f"lib046-gregory-feature-{ordinal:06d}",
        "parent_feature_id": parent_feature_id,
        "source_member": SOURCE_KEY,
        "source_selector": _selector(source),
        "source_tag": source.tag,
        "source_xml_id": source.get("id"),
        "source_attributes": dict(source.attrib),
        "direct_text_length": len(source.text or ""),
        "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
        "tail_text_length": len(source.tail or ""),
        "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
        "source_title_head": source.get("title")
        if str(source.tag).startswith("div")
        else None,
        "tei_tag": tag,
        "tei_xml_id": attrs["xml:id"],
        "tei_attributes": attrs,
        "tei_wrapper_id": None,
        "attribute_dispositions": dispositions,
        "disposition": "represented",
        **({"work_id": work_id} if work_id else {}),
    }


def _expected_rows(
    source: etree._Element,
    rows: list[dict[str, Any]],
    parent_feature_id: str | None,
    work_id: str | None,
) -> None:
    ordinal = len(rows) + 1
    row = _expected_row(source, ordinal, parent_feature_id, work_id)
    rows.append(row)
    for child in source:
        _expected_rows(child, rows, row["feature_id"], None)


def _verify_node(
    source: etree._Element,
    target: etree._Element,
    counter: list[int],
    parent_feature_id: str | None,
    work_id: str | None,
) -> None:
    if not isinstance(source.tag, str) or source.tag not in TAG_MAP:
        raise ValueError(f"unsupported retained source node {source.tag!r}")
    counter[0] += 1
    ordinal = counter[0]
    expected = _expected_row(source, ordinal, parent_feature_id, work_id)
    if etree.QName(target).localname != expected["tei_tag"]:
        raise ValueError(f"TEI tag drift at {expected['source_selector']}")
    if (target.text or "") != (source.text or ""):
        raise ValueError(f"TEI direct text drift at {expected['source_selector']}")
    if (target.tail or "") != (source.tail or ""):
        raise ValueError(f"TEI tail text drift at {expected['source_selector']}")
    if _normalized_attrs(target) != expected["tei_attributes"]:
        raise ValueError(f"TEI attribute drift at {expected['source_selector']}")
    target_children = list(target)
    source_children = list(source)
    offset = 0
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        if len(target_children) == 0 or etree.QName(target_children[0]).localname != "head":
            raise ValueError(f"division head missing at {expected['source_selector']}")
        head = target_children[0]
        if _normalized_attrs(head) or (head.text or "") != title or list(head):
            raise ValueError(f"division head drift at {expected['source_selector']}")
        offset = 1
    if len(target_children) != len(source_children) + offset:
        raise ValueError(f"child count drift at {expected['source_selector']}")
    for source_child, target_child in zip(
        source_children, target_children[offset:], strict=True
    ):
        _verify_node(
            source_child,
            target_child,
            counter,
            expected["feature_id"],
            None,
        )


def _division_accounting(
    tree: etree._ElementTree,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source has no ThML.body")
    top: list[dict[str, Any]] = []
    for ordinal, node in enumerate(
        [child for child in body if isinstance(child.tag, str)], 1
    ):
        assigned = node.get("id") == ROOT_ID
        top.append(
            {
                "ordinal": ordinal,
                "tag": node.tag,
                "id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "assigned-work-root-represented"
                if assigned
                else "source-evidence-outside-work-projection",
                "reason": "complete subtree represented"
                if assigned
                else "title, sibling work, and index matter outside exact assigned work root",
            }
        )
    root = body.find("./div1[@id='iv']")
    if root is None:
        raise ValueError("assigned source root is missing")
    direct = [
        {
            "ordinal": ordinal,
            "parent_div1_id": ROOT_ID,
            "id": node.get("id"),
            "title": node.get("title", ""),
            "disposition": "assigned-work-subtree-represented",
            "reason": "complete subtree represented in retained order",
        }
        for ordinal, node in enumerate(root.findall("div2"), 1)
    ]
    return top, direct


def _expected_accountability(
    source_manifest: SourceManifest,
    tree: etree._ElementTree,
    source_root: etree._Element,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    _expected_rows(source_root, rows, None, WORK_ID)
    assigned = _census(list(source_root.iter()))
    complete = _census(list(tree.getroot().iter()))
    top, direct = _division_accounting(tree)
    binding = {
        "work_id": WORK_ID,
        "source_key": SOURCE_KEY,
        "source_member": SOURCE_PATH,
        "source_root_id": ROOT_ID,
        "source_root_selector": _selector(source_root),
        "source_root_title": source_root.get("title"),
        "feature_count": len(rows),
    }
    return {
        "contract": "ocd-npnf2-lib046-gregory-select-letters-source-accountability-v1",
        "schema": "gregory-select-letters.validation-policy.json",
        "profile_id": PROFILE_ID,
        "assigned_work_count": 1,
        "source_member_count": 1,
        "feature_count": len(rows),
        "attribute_count": assigned["attributes"],
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "assigned_census": assigned,
        "complete_document_census": complete,
        "member_accounting": [
            {
                "key": SOURCE_KEY,
                "path": SOURCE_PATH,
                "bytes": SOURCE_BYTES,
                "sha256": SOURCE_SHA256,
                "disposition": "included retained authority; assigned root represented and all remaining member scope explicitly accounted outside work projection",
                "document_accounting": _document_accounting(tree),
                "complete_document_census": complete,
                "assigned_scope_census": assigned,
                "excluded_scope_census": {
                    key: complete[key] - assigned[key] for key in complete
                },
            }
        ],
        "top_level_division_accounting": top,
        "direct_div2_accounting": direct,
        "work_bindings": [binding],
        "crosswalk": rows,
    }


def _expected_provenance(
    source_manifest: SourceManifest,
    tree: etree._ElementTree,
    source_root: etree._Element,
) -> dict[str, Any]:
    binding = {
        "work_id": WORK_ID,
        "source_key": SOURCE_KEY,
        "source_member": SOURCE_PATH,
        "source_root_id": ROOT_ID,
        "source_root_selector": _selector(source_root),
        "source_root_title": source_root.get("title"),
        "feature_count": EXPECTED_CENSUS["elements"],
    }
    return {
        "contract": "ocd-npnf2-lib046-gregory-select-letters-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "publication_state": "not_ready",
        "entry_config_sha256": _sha(
            source_manifest.authority_path("entry-config").read_bytes()
        ),
        "source_permission_evidence": "docs/sources/ccel-permission.md",
        "scope": {
            "catalog_id": WORK_ID,
            "source_member": SOURCE_KEY,
            "source_root_id": ROOT_ID,
            "source_root_selector": _selector(source_root),
            "source_root_title": source_root.get("title"),
            "scope_type": "complete-source-subtree",
        },
        "sources": {
            SOURCE_KEY: {
                "path": SOURCE_PATH,
                "bytes": SOURCE_BYTES,
                "sha256": SOURCE_SHA256,
                "metadata": _source_metadata(tree),
                "retained_title_page_and_preface_credit_evidence": {
                    source_id: _source_text(tree, source_id) for source_id in CREDIT_IDS
                },
                "display_credit_names": CREDIT_NAMES,
            }
        },
        "works": [
            {
                **binding,
                "translation_credit": {
                    "status": "retained-source-level-credit",
                    "credited_to": ["Charles Gordon Browne", "James Edward Swallow"],
                    "work_specific_allocation": None,
                },
                "human_review": "required",
                "accepted_ir": "not_accepted",
                "publication": "not_ready",
            }
        ],
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }


def _expected_unresolved() -> bytes:
    values = [
        {
            "id": "npnf2-lib046-gregory-work-specific-translation-allocation",
            "scope": WORK_ID,
            "status": "unresolved",
            "evidence": "The retained Gregory title-page material identifies Charles Gordon Browne and James Edward Swallow as translators for the Gregory section; the candidate preserves this source-level credit and does not infer a separate work-level allocation.",
        },
        {
            "id": "npnf2-lib046-gregory-print-collation",
            "scope": SOURCE_KEY,
            "status": "unresolved",
            "evidence": "The retained CCEL XML records the printed source statement, but no independent collation against the 1893 print volume was performed.",
        },
        {
            "id": "npnf2-lib046-gregory-visual-human-rights-publication",
            "scope": WORK_ID,
            "status": "unresolved",
            "evidence": "The retained electronic header states Public Domain; this technical review does not establish CVW visual inspection, human textual acceptance, rights clearance, accepted IR admission, or publication authorization.",
        },
    ]
    return b"".join(_canonical(value) for value in values)


def _header_child_tags(node: etree._Element) -> list[str]:
    return [etree.QName(child).localname for child in node]


def _check_header(tei: etree._ElementTree, source_tree: etree._ElementTree) -> None:
    root = tei.getroot()
    if etree.QName(root).localname != "TEI" or _normalized_attrs(root) != {
        "xml:id": "npnf2-lib046-gregory-select-letters-candidate"
    }:
        raise ValueError("TEI root identity drift")
    if _header_child_tags(root) != ["teiHeader", "text"]:
        raise ValueError("TEI root topology drift")
    header = root[0]
    if _header_child_tags(header) != ["fileDesc"]:
        raise ValueError("TEI header topology drift")
    file_desc = header[0]
    if _header_child_tags(file_desc) != ["titleStmt", "publicationStmt", "sourceDesc"]:
        raise ValueError("TEI file description topology drift")
    title_stmt, publication, source_desc = file_desc
    if _header_child_tags(title_stmt) != [
        "title",
        "title",
        "author",
        "editor",
        "editor",
        "respStmt",
    ]:
        raise ValueError("TEI title statement topology drift")
    electronic_title = "".join(
        str(v)
        for v in source_tree.xpath(
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
        )
    )
    expected_titles = [
        ({"type": "retained-work-title"}, ROOT_TITLE),
        ({"type": "retained-electronic-title", "n": SOURCE_KEY}, electronic_title),
    ]
    for node, (attrs, text) in zip(title_stmt[:2], expected_titles, strict=True):
        if _normalized_attrs(node) != attrs or (node.text or "") != text:
            raise ValueError("TEI title statement value drift")
    for node, expected in zip(title_stmt[2:5], ["Gregory of Nazianzus", "Philip Schaff", "Henry Wace"], strict=True):
        if _normalized_attrs(node) or (node.text or "") != expected:
            raise ValueError("TEI contributor metadata drift")
    resp = title_stmt[5]
    if _header_child_tags(resp) != ["resp", "name"] or _normalized_attrs(resp):
        raise ValueError("TEI translator responsibility topology drift")
    if (resp[0].text or "") != "translator (retained source-level credit)" or (resp[1].text or "") != "Charles Gordon Browne and James Edward Swallow":
        raise ValueError("TEI translator credit drift")
    if _header_child_tags(publication) != ["publisher", "availability"]:
        raise ValueError("TEI publication statement topology drift")
    if _normalized_attrs(publication[0]) or (publication[0].text or "") != "Grand Rapids, MI: Christian Classics Ethereal Library":
        raise ValueError("TEI publisher drift")
    if _normalized_attrs(publication[1]) or _header_child_tags(publication[1]) != ["p"] or (publication[1][0].text or "") != "Public Domain":
        raise ValueError("TEI availability drift")
    if _header_child_tags(source_desc) != ["bibl"]:
        raise ValueError("TEI source description topology drift")
    bibl = source_desc[0]
    expected_bibl_tags = ["title", "title", "editor", "editor", "publisher", "note", "idno", "note"]
    if _header_child_tags(bibl) != expected_bibl_tags or _normalized_attrs(bibl) != {"xml:id": "source-npnf207"}:
        raise ValueError("TEI source bibliography topology drift")
    published = "".join(
        str(v) for v in source_tree.xpath("/ThML/ThML.head/printSourceInfo/published/text()")
    )
    expected_bibl = [
        ({}, electronic_title),
        ({"type": "retained-work-title"}, ROOT_TITLE),
        ({}, "Philip Schaff"),
        ({}, "Henry Wace"),
        ({}, published),
        ({"type": "rights"}, "Public Domain"),
        ({"type": "CCEL-path"}, "/ccel/schaff/npnf207.html"),
        ({"type": "retained-source-scope"}, "Complete retained subtree rooted at ThML.body/div1[@id='iv']."),
    ]
    for node, (attrs, text) in zip(bibl, expected_bibl, strict=True):
        if _normalized_attrs(node) != attrs or (node.text or "") != text or list(node):
            raise ValueError("TEI source bibliography value drift")
    text = root[1]
    if _header_child_tags(text) != ["body"]:
        raise ValueError("TEI text topology drift")
    body = text[0]
    if _normalized_attrs(body) != {"xml:id": "npnf2-lib046-gregory-select-letters-body"}:
        raise ValueError("TEI body identity drift")


def _first_party_module_path(root: Path, module: str) -> Path | None:
    if not module.startswith("ocd_kernel"):
        return None
    relative = Path(*module.split("."))
    for candidate in (root / (str(relative) + ".py"), root / relative / "__init__.py"):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _closure_paths(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    forbidden = set(policy.get("forbidden_oracle_imports", []))
    oracle_path = Path(__file__).resolve(strict=True)
    tree = __import__("ast").parse(oracle_path.read_text(encoding="utf-8"))
    modules: dict[str, Path] = {"build.tei.npnf2_lib046_gregory_select_letters_oracle": oracle_path}
    pending = ["build.tei.npnf2_lib046_gregory_select_letters_oracle"]
    while pending:
        module = pending.pop()
        path = modules[module]
        for node in __import__("ast").walk(__import__("ast").parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, __import__("ast").Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, __import__("ast").ImportFrom):
                if node.module and node.level == 0:
                    names.append(node.module)
                    names.extend(f"{node.module}.{alias.name}" for alias in node.names)
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"oracle closure contains forbidden import {name}")
                if name in modules:
                    continue
                first_party = _first_party_module_path(root, name)
                if first_party is not None:
                    modules[name] = first_party
                    pending.append(name)
    # The package initializer imports this relative implementation, which is
    # intentionally part of the callable's local runtime closure even though
    # the compact scanner above only follows absolute imports.
    contract_path = (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True)
    modules["ocd_kernel.reconstruction.contract"] = contract_path
    return tuple(sorted(modules.values(), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, Any]) -> str:
    return _sha(
        _canonical(
            [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha(path.read_bytes()),
                }
                for path in _closure_paths(root, policy)
            ]
        )
    )


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    source_logical = source_manifest.path.relative_to(root).as_posix()
    converter = source_manifest.record["converter"]
    package_schema = source_manifest.record["package_schema"]
    validator = source_manifest.record["validator"]
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or set(candidate.member_names)
        != {
            "README.source.md",
            "content.tei.xml",
            "manifest.json",
            "provenance.json",
            "source-accountability.json",
            "unresolved.jsonl",
        }
        or candidate.manifest.get("source_manifest")
        != {"path": source_logical, "sha256": source_manifest.sha256}
        or candidate.manifest.get("converter") != dict(converter)
        or candidate.manifest.get("package_schema") != dict(package_schema)
    ):
        raise ValueError("candidate authority or member binding drift")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _authority_json(profile_bytes, "reconstruction profile")
    policy = _authority_json(policy_bytes, "validation policy")
    if profile.get("profile_id") != PROFILE_ID or policy.get("policy_id") != PROFILE_ID:
        raise ValueError("profile or policy identity drift")
    if "build.tei.npnf2_lib046_gregory_select_letters_reconstruction" not in set(policy.get("forbidden_oracle_imports", [])):
        raise ValueError("oracle independence policy is incomplete")
    closure = _closure_digest(root, policy)
    if closure != validator.get("import_closure_sha256"):
        raise ValueError("oracle import closure drift")
    source_path = source_manifest.authority_path("retained-npnf207")
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != SOURCE_BYTES or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("wrong or stale retained source")
    source_tree = _source_tree(source_bytes)
    body = source_tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source body is missing")
    top_ids = [node.get("id") for node in body if isinstance(node.tag, str)]
    if top_ids != EXPECTED_TOP_LEVEL_IDS:
        raise ValueError("source top-level root order drift")
    matches = body.xpath("./div1[@id=$root_id]", root_id=ROOT_ID)
    if len(matches) != 1:
        raise ValueError("assigned source root is not unique")
    source_root = matches[0]
    div2_ids = [node.get("id") for node in source_root.findall("div2")]
    if div2_ids != EXPECTED_DIV2_IDS:
        raise ValueError("assigned div2 order drift")
    assigned_census = _census(list(source_root.iter()))
    document_census = _census(list(source_tree.getroot().iter()))
    if assigned_census != EXPECTED_CENSUS or document_census != EXPECTED_DOCUMENT_CENSUS:
        raise ValueError("source census drift")
    if profile.get("assigned_census") != EXPECTED_CENSUS or profile.get("complete_document_census") != EXPECTED_DOCUMENT_CENSUS:
        raise ValueError("profile census drift")
    tei = _tei_tree(candidate.member_bytes("content.tei.xml"))
    _check_header(tei, source_tree)
    target_body = tei.getroot()[1][0]
    target_works = [child for child in target_body if isinstance(child.tag, str)]
    if len(target_works) != 1:
        raise ValueError("TEI work-root count drift")
    counter = [0]
    _verify_node(source_root, target_works[0], counter, None, WORK_ID)
    if counter[0] != EXPECTED_CENSUS["elements"]:
        raise ValueError("TEI projection count drift")
    rows: list[dict[str, Any]] = []
    _expected_rows(source_root, rows, None, WORK_ID)
    account = _strict_json(candidate.member_bytes("source-accountability.json"), "source accountability")
    expected_account = _expected_accountability(source_manifest, source_tree, source_root)
    if account != expected_account:
        raise ValueError("source-accountability omission, duplication, order, mapping, or invention drift")
    provenance = _strict_json(candidate.member_bytes("provenance.json"), "provenance")
    if provenance != _expected_provenance(source_manifest, source_tree, source_root):
        raise ValueError("source metadata, rights, credit, or state drift")
    if candidate.member_bytes("unresolved.jsonl") != _expected_unresolved():
        raise ValueError("unresolved scope drift")
    if candidate.member_bytes("README.source.md") != README_TEXT.encode("utf-8"):
        raise ValueError("source attribution README drift")
    schema = etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    )
    try:
        schema.assertValid(tei)
    except etree.DocumentInvalid as exc:
        raise ValueError("candidate fails TEI P5 XSD") from exc
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).resolve(strict=True).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
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
