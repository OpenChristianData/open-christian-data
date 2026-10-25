"""Faithfully reconstruct Gregory of Nazianzus's retained Select Letters root."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import tei_el


CONVERTER_ID = "ocd-npnf2-lib046-gregory-select-letters-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
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


def _parse(content: bytes) -> etree._ElementTree:
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


def _safe(value: str) -> str:
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


def _append(
    source: etree._Element,
    parent: etree._Element,
    rows: list[dict[str, Any]],
    parent_feature_id: str | None,
    work_id: str | None = None,
) -> None:
    if not isinstance(source.tag, str) or source.tag not in TAG_MAP:
        raise ValueError(f"unsupported assigned source node {source.tag!r}")
    ordinal = len(rows) + 1
    feature_id = f"lib046-gregory-feature-{ordinal:06d}"
    attrs, dispositions = _target_attrs(source, ordinal, work_id)
    tag = _target_tag(source)
    if etree.QName(parent).localname == "div" and tag in {
        "ref",
        "seg",
        "foreign",
        "hi",
    }:
        raise ValueError(
            f"source inline element directly under division at {_selector(source)}"
        )
    target = tei_el(tag, attrs)
    target.text = source.text or ""
    target.tail = source.tail or ""
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        target.insert(0, tei_el("head", text=title))
    parent.append(target)
    rows.append(
        {
            "feature_id": feature_id,
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
            "source_title_head": title,
            "tei_tag": tag,
            "tei_xml_id": attrs["xml:id"],
            "tei_attributes": attrs,
            "tei_wrapper_id": None,
            "attribute_dispositions": dispositions,
            "disposition": "represented",
            **({"work_id": work_id} if work_id else {}),
        }
    )
    for child in source:
        _append(child, target, rows, feature_id)


def _header(tree: etree._ElementTree) -> etree._Element:
    root = tei_el("TEI", {"xml:id": "npnf2-lib046-gregory-select-letters-candidate"})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", {"type": "retained-work-title"}, ROOT_TITLE))
    electronic_title = "".join(
        str(v)
        for v in tree.xpath(
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
        )
    )
    title_stmt.append(
        tei_el("title", {"type": "retained-electronic-title", "n": SOURCE_KEY}, electronic_title)
    )
    title_stmt.append(tei_el("author", text="Gregory of Nazianzus"))
    title_stmt.append(tei_el("editor", text="Philip Schaff"))
    title_stmt.append(tei_el("editor", text="Henry Wace"))
    resp_stmt = tei_el("respStmt")
    resp_stmt.append(tei_el("resp", text="translator (retained source-level credit)"))
    resp_stmt.append(
        tei_el("name", text="Charles Gordon Browne and James Edward Swallow")
    )
    title_stmt.append(resp_stmt)
    file_desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(
        tei_el("publisher", text="Grand Rapids, MI: Christian Classics Ethereal Library")
    )
    availability = tei_el("availability")
    availability.append(tei_el("p", text="Public Domain"))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl", {"xml:id": "source-npnf207"})
    bibl.append(tei_el("title", text=electronic_title))
    bibl.append(tei_el("title", {"type": "retained-work-title"}, ROOT_TITLE))
    bibl.append(tei_el("editor", text="Philip Schaff"))
    bibl.append(tei_el("editor", text="Henry Wace"))
    published = "".join(
        str(v) for v in tree.xpath("/ThML/ThML.head/printSourceInfo/published/text()")
    )
    if published:
        bibl.append(tei_el("publisher", text=published))
    rights = "".join(
        str(v)
        for v in tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()")
    )
    bibl.append(tei_el("note", {"type": "rights"}, rights))
    url = "".join(
        str(v)
        for v in tree.xpath(
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()"
        )
    )
    bibl.append(tei_el("idno", {"type": "CCEL-path"}, url))
    bibl.append(
        tei_el(
            "note",
            {"type": "retained-source-scope"},
            "Complete retained subtree rooted at ThML.body/div1[@id='iv'].",
        )
    )
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    root.append(header)
    return root


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
    direct: list[dict[str, Any]] = []
    root = tree.getroot().find("ThML.body").find("./div1[@id='iv']")
    if root is None:
        raise ValueError("assigned source root is missing")
    for ordinal, node in enumerate(root.findall("div2"), 1):
        direct.append(
            {
                "ordinal": ordinal,
                "parent_div1_id": ROOT_ID,
                "id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "assigned-work-subtree-represented",
                "reason": "complete subtree represented in retained order",
            }
        )
    return top, direct


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    if profile.get("profile_id") != PROFILE_ID or policy.get("policy_id") != PROFILE_ID:
        raise ValueError("entry-local profile or policy identity drift")
    path = source_manifest.authority_path("retained-npnf207")
    source_bytes = path.read_bytes()
    if len(source_bytes) != SOURCE_BYTES or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained npnf207 authority drift")
    tree = _parse(source_bytes)
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source body is missing")
    top_ids = [node.get("id") for node in body if isinstance(node.tag, str)]
    if top_ids != EXPECTED_TOP_LEVEL_IDS:
        raise ValueError(f"top-level source root order drift: {top_ids}")
    matches = body.xpath("./div1[@id=$root_id]", root_id=ROOT_ID)
    if len(matches) != 1:
        raise ValueError("assigned source root iv is not unique")
    source_root = matches[0]
    div2_ids = [node.get("id") for node in source_root.findall("div2")]
    if div2_ids != EXPECTED_DIV2_IDS:
        raise ValueError(f"assigned div2 order drift: {div2_ids}")
    assigned_nodes = list(source_root.iter())
    assigned_census = _census(assigned_nodes)
    if assigned_census != EXPECTED_CENSUS or profile.get("assigned_census") != EXPECTED_CENSUS:
        raise ValueError(f"assigned source census drift: {assigned_census}")
    document_census = _census(list(tree.getroot().iter()))
    if document_census != EXPECTED_DOCUMENT_CENSUS or profile.get("complete_document_census") != EXPECTED_DOCUMENT_CENSUS:
        raise ValueError(f"complete source census drift: {document_census}")
    root = _header(tree)
    text = tei_el("text")
    target_body = tei_el("body", {"xml:id": "npnf2-lib046-gregory-select-letters-body"})
    text.append(target_body)
    root.append(text)
    rows: list[dict[str, Any]] = []
    _append(source_root, target_body, rows, None, WORK_ID)
    top_accounting, direct_accounting = _division_accounting(tree)
    complete_member = _census(list(tree.getroot().iter()))
    excluded = {
        key: complete_member[key] - assigned_census[key] for key in complete_member
    }
    work_binding = {
        "work_id": WORK_ID,
        "source_key": SOURCE_KEY,
        "source_member": SOURCE_PATH,
        "source_root_id": ROOT_ID,
        "source_root_selector": _selector(source_root),
        "source_root_title": source_root.get("title"),
        "feature_count": len(rows),
    }
    member_accounting = [
        {
            "key": SOURCE_KEY,
            "path": SOURCE_PATH,
            "bytes": SOURCE_BYTES,
            "sha256": SOURCE_SHA256,
            "disposition": "included retained authority; assigned root represented and all remaining member scope explicitly accounted outside work projection",
            "document_accounting": _document_accounting(tree),
            "complete_document_census": complete_member,
            "assigned_scope_census": assigned_census,
            "excluded_scope_census": excluded,
        }
    ]
    accountability = {
        "contract": "ocd-npnf2-lib046-gregory-select-letters-source-accountability-v1",
        "schema": "gregory-select-letters.validation-policy.json",
        "profile_id": PROFILE_ID,
        "assigned_work_count": 1,
        "source_member_count": 1,
        "feature_count": len(rows),
        "attribute_count": assigned_census["attributes"],
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "assigned_census": assigned_census,
        "complete_document_census": complete_member,
        "member_accounting": member_accounting,
        "top_level_division_accounting": top_accounting,
        "direct_div2_accounting": direct_accounting,
        "work_bindings": [work_binding],
        "crosswalk": rows,
    }
    metadata = _source_metadata(tree)
    provenance = {
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
                "metadata": metadata,
                "retained_title_page_and_preface_credit_evidence": {
                    source_id: _source_text(tree, source_id) for source_id in CREDIT_IDS
                },
                "display_credit_names": CREDIT_NAMES,
            }
        },
        "works": [
            {
                **work_binding,
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
    unresolved = [
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
    return {
        "README.source.md": README_TEXT.encode("utf-8"),
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
