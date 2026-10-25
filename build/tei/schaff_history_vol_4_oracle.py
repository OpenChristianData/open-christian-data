"""Independent source/TEI checker for the retained HCC4 ThML member."""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from build.lib.tei_xsd import compiled_tei_schema
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "schaff-history-vol-4-independent-source-checker"
ORACLE_VERSION = "1"
WORK_ID = "schaff-history-vol-4"
SOURCE_ID = "ccel-schaff-hcc4-thml"
PROFILE_NAME = "reconstruction-profile"
POLICY_NAME = "validation-policy"
ACCOUNTABILITY_SCHEMA_NAME = "source-accountability-schema"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_ID = f"{{{XML_NS}}}id"
_PROFILE_PATH = Path(
    "sources/structured-text/schaff-history-vol-4-readable/"
    "schaff-history-vol-4.validation-policy.json"
)
_DIVISION_TAGS = ("div", "div1", "div2", "div3", "div4", "div5", "div6")
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_PROJECTION_NAMES = {
    "div": "div",
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "div5": "div",
    "div6": "div",
    "h1": "head",
    "h2": "head",
    "h3": "head",
    "h4": "head",
    "h5": "head",
    "h6": "head",
    "p": "p",
    "note": "note",
    "i": "hi",
    "br": "lb",
    "scripRef": "ref",
    "a": "ref",
    "span": "seg",
    "verse": "lg",
    "index": "index",
    "l": "l",
    "ul": "list",
    "li": "item",
    "insertIndex": "anchor",
    "attr": "p",
    "ThML.body": "body",
}
_CLOSURE_PATHS = (
    "build/tei/schaff_history_vol_4_oracle.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/verifier.py",
    "build/lib/tei_xsd.py",
)
_XML_DECLARATION = re.compile(rb"\s*(<\?xml[^?]*\?>)")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be a JSON object")
    return result


def _parse_xml(content: bytes, label: str) -> etree._ElementTree:
    parser = etree.XMLParser(
        load_dtd=False,
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_comments=False,
        remove_pis=False,
        huge_tree=True,
    )
    try:
        return etree.parse(BytesIO(content), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"{label} is not well-formed XML: {exc}") from exc


def _name(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("non-element node entered the source-element census")
    return etree.QName(node).localname


def _manifest_authority_digest(source_manifest: SourceManifest, name: str) -> str:
    for row in source_manifest.record["authorities"]:
        if row["name"] == name:
            return str(row["sha256"])
    raise ValueError(f"source manifest has no {name!r} authority")


def _source_records(
    root: etree._Element,
) -> tuple[list[etree._Element], dict[str, dict[str, object]]]:
    """Independently enumerate source elements, parent links, and element ordinals."""

    nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    if sum(1 for node in root.iter() if not isinstance(node.tag, str)):
        raise ValueError("HCC4 has an unsupported in-root comment, PI, or entity")
    by_node: dict[etree._Element, str] = {
        node: f"hcc4-n{position:06d}" for position, node in enumerate(nodes, 1)
    }
    records: dict[str, dict[str, object]] = {}
    for node in nodes:
        key = by_node[node]
        parent = node.getparent()
        if parent is None:
            parent_key = None
            ordinal = 1
        else:
            element_children = [child for child in parent if isinstance(child.tag, str)]
            parent_key = by_node.get(parent)
            ordinal = element_children.index(node) + 1
        records[key] = {
            "node": node,
            "source_key": key,
            "tag": _name(node),
            "parent_key": parent_key,
            "ordinal": ordinal,
            "attributes": list(node.attrib.items()),
        }
    return nodes, records


def _external_siblings(root: etree._Element, *, before: bool) -> list[etree._Element]:
    if before:
        cursor = root
        while cursor.getprevious() is not None:
            cursor = cursor.getprevious()
        siblings: list[etree._Element] = []
        while cursor is not root:
            siblings.append(cursor)
            cursor = cursor.getnext()
        return siblings
    siblings = []
    cursor = root.getnext()
    while cursor is not None:
        siblings.append(cursor)
        cursor = cursor.getnext()
    return siblings


def _carrier_rows(
    records: Mapping[str, Mapping[str, object]], names: tuple[str, ...]
) -> list[dict[str, object]]:
    result = []
    for key, record in records.items():
        tag = str(record["tag"])
        if tag not in names:
            continue
        node = record["node"]
        result.append(
            {
                "source_key": key,
                "tag": tag,
                "id": node.get("id"),
                "parent_key": record["parent_key"],
                "ordinal": record["ordinal"],
                "type": node.get("type"),
                "title": node.get("title"),
            }
        )
    return result


def _counts(records: Mapping[str, Mapping[str, object]]) -> tuple[dict[str, int], dict[str, int]]:
    observed = Counter(str(record["tag"]) for record in records.values())
    return (
        {tag: observed.get(tag, 0) for tag in _DIVISION_TAGS},
        {tag: observed.get(tag, 0) for tag in _HEADING_TAGS},
    )


def _expected_tei_attributes(
    source_name: str, source: etree._Element
) -> dict[str, str]:
    """Build the TEI-facing attributes separately from the producer's mapper."""

    if source_name == "ThML":
        return {}
    attrs: dict[str, str] = {}
    source_type = source.get("type")
    source_class = source.get("class")
    if source_class:
        attrs["rend"] = source_class

    if source_name in _DIVISION_TAGS:
        attrs["type"] = f"ThML-{source_name}"
        if source_type:
            attrs["subtype"] = source_type
        attrs["n"] = source.get("title") or source.get("n") or ""
        if not attrs["n"]:
            attrs.pop("n")
    elif source_name in _HEADING_TAGS:
        attrs["type"] = f"source-{source_name}"
    elif source_name == "i":
        attrs["rend"] = source_class or "italic"
    elif source_name == "note":
        attrs["type"] = source_type or "ThML-note"
        if source.get("place"):
            attrs["place"] = source.get("place") or ""
        if source.get("n"):
            attrs["n"] = source.get("n") or ""
    elif source_name == "scripRef":
        attrs["type"] = "scripture-reference"
        attrs["target"] = source.get("osisRef") or source.get("passage") or ""
    elif source_name == "a":
        attrs["type"] = "ThML-link"
        if source.get("href"):
            attrs["target"] = source.get("href") or ""
    elif source_name == "verse":
        attrs["type"] = source_type or "ThML-verse"
    elif source_name == "ul":
        attrs["type"] = "unordered"
    elif source_name == "index":
        if source_type:
            attrs["indexName"] = source_type
        if source.get("subject1"):
            attrs["n"] = source.get("subject1") or ""
    elif source_name == "insertIndex":
        attrs["type"] = source_type or "ThML-insertIndex"
    elif source_name == "ThML.head":
        attrs["type"] = "retained-ThML-header"
    elif _PROJECTION_NAMES.get(source_name, "seg") == "seg":
        attrs["type"] = f"ThML-{source_name}"
    elif source_type and _PROJECTION_NAMES.get(source_name) in {"l", "item", "anchor"}:
        attrs["type"] = source_type
    return attrs


def _source_content_id(
    source: etree._Element,
    source_record: Mapping[str, object],
) -> str:
    source_key = str(source_record["source_key"])
    return source.get("id") or f"hcc4-generated-{source_key[6:]}"


def _expected_accountability(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    source_bytes: bytes,
    source_tree: etree._ElementTree,
    records: Mapping[str, Mapping[str, object]],
    divisions: Mapping[str, int],
    headings: Mapping[str, int],
) -> dict[str, object]:
    root = source_tree.getroot()
    comments = _external_siblings(root, before=True)
    if any(not isinstance(item, etree._Comment) for item in comments):
        raise ValueError("source prolog includes a non-comment node without a disposition")
    comments_accounted = [
        {
            "ordinal": offset,
            "sha256": _sha((comment.text or "").encode("utf-8")),
            "characters": len(comment.text or ""),
        }
        for offset, comment in enumerate(comments, 1)
    ]
    return {
        "contract": "ocd-schaff-history-vol-4-source-accountability-v1",
        "ticket_id": "LIB-058",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source_bytes": len(source_bytes),
        "source_sha256": _sha(source_bytes),
        "selection": {
            "selector": "/ThML/ThML.body/*",
            "member_count": 1,
            "included_body_div1_ids": [part.get("id") for part in root.xpath("./ThML.body/div1")],
            "excluded_body_division_ids": [],
        },
        "envelope": {
            "xml_version": source_tree.docinfo.xml_version,
            "encoding": source_tree.docinfo.encoding,
            "doctype": source_tree.docinfo.doctype or "",
            "external_dtd_loaded": False,
            "top_level_comments": comments_accounted,
            "active_processing_instructions": 0,
            "root_element": _name(root),
            "root_children_in_order": [_name(child) for child in root if isinstance(child.tag, str)],
            "source_head_disposition": "represented_in_TEI_header",
            "source_body_disposition": "represented_in_TEI_text_body",
        },
        "source_element_count": len(records),
        "represented_element_count": len(records),
        "omitted_element_count": 0,
        "duplicate_element_count": 0,
        "division_counts": dict(divisions),
        "heading_counts": dict(headings),
        "division_carriers": _carrier_rows(records, _DIVISION_TAGS),
        "heading_carriers": _carrier_rows(records, _HEADING_TAGS),
        "rights_status": "unresolved",
        "legacy_config_used_as_authority": False,
        "profile_id": profile.get("profile_id"),
        "source_manifest_sha256": source_manifest.sha256,
    }


def _expect_children(parent: etree._Element, expected: list[str], label: str) -> None:
    actual = [_name(child) for child in parent if isinstance(child.tag, str)]
    if actual != expected:
        raise ValueError(f"TEI {label} structure drifted: {actual!r}")


def _verify_header(
    source_root: etree._Element,
    tei_root: etree._Element,
    source_doctype: str,
) -> None:
    ns = {"t": TEI_NS}
    title_nodes = source_root.xpath("./ThML.head/electronicEdInfo/DC/DC.Title")
    creator_nodes = source_root.xpath("./ThML.head/electronicEdInfo/DC/DC.Creator")
    source_rights = source_root.xpath("./ThML.head/electronicEdInfo/DC/DC.Rights")
    if len(title_nodes) != 2 or len(creator_nodes) != 2 or len(source_rights) != 1:
        raise ValueError("source title/creator/rights metadata is incomplete")
    title_text = ["".join(node.itertext()) for node in title_nodes]
    creator_text = ["".join(node.itertext()) for node in creator_nodes]

    if tei_root.tag != f"{{{TEI_NS}}}TEI":
        raise ValueError("candidate root is not TEI P5")
    _expect_children(tei_root, ["teiHeader", "text", "standOff"], "root")
    header = tei_root.find(f"{{{TEI_NS}}}teiHeader")
    assert header is not None
    _expect_children(header, ["fileDesc", "encodingDesc"], "teiHeader")
    file_desc = header.find(f"{{{TEI_NS}}}fileDesc")
    encoding_desc = header.find(f"{{{TEI_NS}}}encodingDesc")
    assert file_desc is not None and encoding_desc is not None
    _expect_children(file_desc, ["titleStmt", "publicationStmt", "notesStmt", "sourceDesc"], "fileDesc")
    _expect_children(encoding_desc, ["projectDesc"], "encodingDesc")
    project = encoding_desc.find(f"{{{TEI_NS}}}projectDesc")
    assert project is not None
    _expect_children(project, ["p"], "projectDesc")

    title_stmt = file_desc.find(f"{{{TEI_NS}}}titleStmt")
    publication_stmt = file_desc.find(f"{{{TEI_NS}}}publicationStmt")
    notes_stmt = file_desc.find(f"{{{TEI_NS}}}notesStmt")
    source_desc = file_desc.find(f"{{{TEI_NS}}}sourceDesc")
    assert title_stmt is not None and publication_stmt is not None
    assert notes_stmt is not None and source_desc is not None
    _expect_children(title_stmt, ["title", "title", "author", "author"], "titleStmt")
    _expect_children(publication_stmt, ["p"], "publicationStmt")
    _expect_children(notes_stmt, ["note", "note"], "notesStmt")
    _expect_children(source_desc, ["p"], "sourceDesc")

    tei_titles = title_stmt.xpath("./t:title/text()", namespaces=ns)
    tei_authors = title_stmt.xpath("./t:author/text()", namespaces=ns)
    if tei_titles != title_text or tei_authors != creator_text:
        raise ValueError("candidate title/author fields drift from retained header")
    title_types = title_stmt.xpath("./t:title/@type", namespaces=ns)
    if title_types != ["main", "alternative"]:
        raise ValueError("candidate title role mapping drifted")

    publication_note = publication_stmt.find(f"{{{TEI_NS}}}p")
    assert publication_note is not None
    if "".join(publication_note.itertext()) != (
        "Nonaccepted reconstruction candidate; publication is not authorized. "
        "The retained DC.Rights element is empty; rights and license status remain unresolved."
    ):
        raise ValueError("candidate publication or rights disposition drifted")
    if "".join(source_rights[0].itertext()) != "":
        raise ValueError("retained DC.Rights is no longer empty")

    notes = notes_stmt.findall(f"{{{TEI_NS}}}note")
    if notes[0].get("type") != "source-doctype" or notes[0].text != source_doctype:
        raise ValueError("candidate source DOCTYPE disposition drifted")
    if notes[1].get("type") != "retained-ThML-header":
        raise ValueError("candidate retained header disposition drifted")
    header_paragraph = notes[1].find(f"{{{TEI_NS}}}p")
    if header_paragraph is None:
        raise ValueError("candidate retained header container is missing")
    mapped_head = header_paragraph.find(f"{{{TEI_NS}}}seg")
    if mapped_head is None or mapped_head.get("type") != "retained-ThML-header":
        raise ValueError("complete retained ThML header is absent")
    _expect_children(header_paragraph, ["seg"], "retained ThML header")

    source_text = tei_root.find(f"{{{TEI_NS}}}text")
    assert source_text is not None
    _expect_children(source_text, ["body"], "text")
    mapped_body = source_text.find(f"{{{TEI_NS}}}body")
    if mapped_body is None:
        raise ValueError("complete retained ThML body is absent")
    stand_off = tei_root.find(f"{{{TEI_NS}}}standOff")
    if stand_off is None:
        raise ValueError("candidate source projection standOff is missing")
    _expect_children(stand_off, ["list"], "standOff")
    projection = stand_off.find(f"{{{TEI_NS}}}list")
    if projection is None or projection.get("type") != "source-projection":
        raise ValueError("candidate source projection list is missing")
    if not source_desc[0].text or "raw/ccel/schaff/hcc4.xml" not in source_desc[0].text:
        raise ValueError("candidate source-member description drifted")


def _verify_external_comments(
    source_root: etree._Element, candidate_root: etree._Element
) -> None:
    source_pre = _external_siblings(source_root, before=True)
    source_post = _external_siblings(source_root, before=False)
    candidate_pre = _external_siblings(candidate_root, before=True)
    candidate_post = _external_siblings(candidate_root, before=False)
    if source_post or candidate_post:
        raise ValueError("source/candidate has an unaccounted post-root node")
    if any(not isinstance(node, etree._Comment) for node in source_pre + candidate_pre):
        raise ValueError("active PI or unsupported prolog node is present")
    if [node.text or "" for node in source_pre] != [node.text or "" for node in candidate_pre]:
        raise ValueError("candidate leading source comments drifted")


def _verify_source_projection(
    source_root: etree._Element,
    candidate_root: etree._Element,
    records: Mapping[str, Mapping[str, object]],
) -> set[etree._Element]:
    source_keys = {record["node"]: key for key, record in records.items()}
    candidate_by_id: dict[str, etree._Element] = {}
    for node in candidate_root.iter():
        if not isinstance(node.tag, str):
            continue
        content_id = node.get(XML_ID)
        if content_id is None:
            continue
        if content_id in candidate_by_id:
            raise ValueError(f"candidate duplicates XML ID {content_id!r}")
        candidate_by_id[content_id] = node

    stand_off = candidate_root.find(f"{{{TEI_NS}}}standOff")
    projection = (
        stand_off.find(f"{{{TEI_NS}}}list") if stand_off is not None else None
    )
    if projection is None or projection.get("type") != "source-projection":
        raise ValueError("candidate source projection record list is absent")
    items = projection.findall(f"{{{TEI_NS}}}item")
    expected_keys = list(records)
    if len(items) != len(expected_keys):
        raise ValueError("candidate source projection record count drifted")

    observed: dict[str, etree._Element] = {}
    for item, key in zip(items, expected_keys, strict=True):
        record = records[key]
        source = record["node"]
        if not isinstance(source, etree._Element):
            raise ValueError(f"oracle source record {key} has no element")
        content_id = _source_content_id(source, record)
        if item.attrib != {
            "n": key,
            "corresp": f"#{content_id}",
        }:
            raise ValueError(f"candidate source-record link drifted at {key}")
        if len(item) != 0 or item.text is None:
            raise ValueError(f"candidate source record is not a text-only item at {key}")
        payload = _strict_json(item.text.encode("utf-8"), f"HCC4 source record {key}")
        expected_payload = {
            "source_key": key,
            "source_element": str(record["tag"]),
            "source_attributes": [
                [name, value] for name, value in record["attributes"]
            ],
            "source_parent_key": str(record["parent_key"] or ""),
            "source_ordinal": record["ordinal"],
        }
        if payload != expected_payload:
            raise ValueError(f"candidate source record fields drifted at {key}")
        projected = candidate_by_id.get(content_id)
        if projected is None:
            raise ValueError(f"candidate source content target is absent at {key}")
        observed[key] = projected

    if len(observed) != len(records):
        raise ValueError("candidate source projection accounting is incomplete")
    expected_content_ids = {
        _source_content_id(record["node"], record)
        for record in records.values()
    }
    if set(candidate_by_id) != expected_content_ids:
        raise ValueError("candidate contains an unaccounted source-content XML ID")

    source_ids = {
        str(record["node"].get("id"))
        for record in records.values()
        if record["node"].get("id") is not None
    }
    generated_ids: set[str] = set()
    for key, record in records.items():
        source = record["node"]
        projected = observed[key]
        source_name = str(record["tag"])
        expected_local = "TEI" if source is source_root else _PROJECTION_NAMES.get(source_name, "seg")
        if etree.QName(projected).localname != expected_local:
            raise ValueError(f"candidate mapped {source_name} to the wrong TEI element")
        content_id = _source_content_id(source, record)
        expected_attributes = {XML_ID: content_id}
        expected_attributes.update(_expected_tei_attributes(source_name, source))
        if dict(projected.attrib) != expected_attributes:
            raise ValueError(f"candidate TEI attributes or semantics drifted at {key}")
        if projected.text != source.text or projected.tail != source.tail:
            raise ValueError(f"candidate mixed text or tail drifted at {key}")
        if source.get("id") is None:
            if content_id in source_ids or content_id in generated_ids:
                raise ValueError(f"candidate generated XML ID collision at {key}")
            generated_ids.add(content_id)

    wrappers: set[etree._Element] = set()
    for parent_key, parent_record in records.items():
        source_parent = parent_record["node"]
        if source_parent is source_root:
            continue
        if not isinstance(source_parent, etree._Element):
            raise ValueError(f"oracle source parent {parent_key} has no element")
        source_name = str(parent_record["tag"])
        projected_parent = observed[parent_key]
        source_children = [
            child for child in source_parent if isinstance(child.tag, str)
        ]
        try:
            child_keys = [source_keys[child] for child in source_children]
        except KeyError as exc:
            raise ValueError("oracle source-child key inventory is incomplete") from exc
        candidate_children = [
            child for child in projected_parent if isinstance(child.tag, str)
        ]

        if source_name in _DIVISION_TAGS:
            layout: list[tuple[str, list[str]]] = []
            pending_common: list[str] = []
            saw_division = False
            for child, child_key in zip(source_children, child_keys, strict=True):
                if str(_name(child)) in _DIVISION_TAGS:
                    if pending_common:
                        layout.append(("wrapper", pending_common))
                        pending_common = []
                    layout.append(("source", [child_key]))
                    saw_division = True
                elif saw_division:
                    pending_common.append(child_key)
                else:
                    layout.append(("source", [child_key]))
            if pending_common:
                layout.append(("wrapper", pending_common))
            if len(candidate_children) != len(layout):
                raise ValueError(f"candidate division child envelope drifted at {parent_key}")
            for (kind, keys), candidate_child in zip(
                layout, candidate_children, strict=True
            ):
                if kind == "source":
                    if candidate_child is not observed[keys[0]]:
                        raise ValueError(
                            f"candidate division child order drifted at {parent_key}"
                        )
                    continue
                if (
                    etree.QName(candidate_child).localname != "div"
                    or candidate_child.attrib != {"type": "source-order-wrapper"}
                    or candidate_child.text is not None
                    or candidate_child.tail is not None
                ):
                    raise ValueError(
                        f"candidate source-order wrapper drifted at {parent_key}"
                    )
                wrapped_children = [
                    child for child in candidate_child if isinstance(child.tag, str)
                ]
                if wrapped_children != [observed[key] for key in keys]:
                    raise ValueError(
                        f"candidate source-order wrapper members drifted at {parent_key}"
                    )
                wrappers.add(candidate_child)
        elif candidate_children != [observed[key] for key in child_keys]:
            raise ValueError(f"candidate child order or parent attachment drifted at {parent_key}")

    source_head = source_root.find("./ThML.head")
    source_body = source_root.find("./ThML.body")
    if source_head is None or source_body is None:
        raise ValueError("retained HCC4 root head/body records are missing")
    mapped_head_nodes = candidate_root.xpath(
        "./t:teiHeader/t:fileDesc/t:notesStmt/"
        "t:note[@type='retained-ThML-header']/t:p/t:seg",
        namespaces={"t": TEI_NS},
    )
    mapped_body = candidate_root.find(
        f"{{{TEI_NS}}}text/{{{TEI_NS}}}body"
    )
    if (
        len(mapped_head_nodes) != 1
        or observed[source_keys[source_head]] is not mapped_head_nodes[0]
        or mapped_body is None
        or observed[source_keys[source_body]] is not mapped_body
    ):
        raise ValueError("candidate root head/body source parent attachments drifted")

    if len(observed) != len(records):
        raise ValueError("candidate source element accounting is incomplete")
    if candidate_root.text != source_root.text:
        raise ValueError("source document-root text disposition drifted")
    return set(observed.values()) | wrappers


def _independent_check(
    source_manifest: SourceManifest,
    tei_bytes: bytes,
) -> tuple[MechanicalFacts, dict[str, object]]:
    """Re-read raw source and candidate bytes without any producer helper."""

    source_manifest.verify()
    if source_manifest.record.get("work_id") != WORK_ID or source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("source manifest does not bind the HCC4 owner route")
    profile = _strict_json(
        source_manifest.authority_path(PROFILE_NAME).read_bytes(), "HCC4 profile"
    )
    policy_bytes = source_manifest.authority_path(POLICY_NAME).read_bytes()
    policy = _strict_json(policy_bytes, "HCC4 validation policy")
    source_bytes = source_manifest.authority_path("primary-source").read_bytes()
    source_digest = _sha(source_bytes)
    if (
        profile.get("work_id") != WORK_ID
        or profile.get("source_id") != SOURCE_ID
        or profile.get("primary_source", {}).get("path") != "raw/ccel/schaff/hcc4.xml"
        or profile.get("primary_source", {}).get("sha256") != source_digest
        or profile.get("primary_source", {}).get("bytes") != len(source_bytes)
        or policy.get("source_sha256") != source_digest
        or _manifest_authority_digest(source_manifest, "primary-source") != source_digest
    ):
        raise ValueError("retained HCC4 bytes or source identity drifted")
    source_tree = _parse_xml(source_bytes, "retained HCC4 source")
    source_root = source_tree.getroot()
    if _name(source_root) != "ThML":
        raise ValueError("retained source root is not ThML")
    source_children = [_name(node) for node in source_root if isinstance(node.tag, str)]
    if source_children != profile.get("source_envelope", {}).get("root_children_in_order"):
        raise ValueError("retained source header/body order drifted")

    nodes, records = _source_records(source_root)
    divisions, headings = _counts(records)
    envelope_policy = policy.get("six_division_and_heading_envelope")
    if not isinstance(envelope_policy, dict):
        raise ValueError("HCC4 policy lacks six-division/h1-h6 expectations")
    if (
        divisions != profile.get("division_counts")
        or headings != profile.get("heading_counts")
        or divisions != envelope_policy.get("expected_divisions")
        or headings != envelope_policy.get("expected_headings")
    ):
        raise ValueError("retained HCC4 six-division/h1-h6 envelope drifted")
    source_body = source_root.find("./ThML.body")
    if source_body is None:
        raise ValueError("retained HCC4 body is absent")
    actual_division_order = [
        child.get("id") or ""
        for child in source_body
        if isinstance(child.tag, str) and _name(child) == "div1"
    ]
    if actual_division_order != envelope_policy.get("expected_body_div1_ids_in_order"):
        raise ValueError("retained HCC4 two-root body selection drifted")
    tei_policy = policy.get("tei", {})
    if tei_policy.get("source_tag_projection") != {
        name: target for name, target in _PROJECTION_NAMES.items() if name != "ThML.body"
    } | {"ThML.body": "body"}:
        raise ValueError("work-specific TEI projection policy drifted")
    if tei_policy.get("source_mapping") != {
        "container": "/TEI/standOff/list[@type='source-projection']",
        "record_selector": "item",
        "key_attribute": "n",
        "content_reference_attribute": "corresp",
        "content_reference_target": "mapped source element @xml:id",
        "record_encoding": "strict JSON object text",
        "record_fields": [
            "source_key",
            "source_element",
            "source_attributes",
            "source_parent_key",
            "source_ordinal",
        ],
    }:
        raise ValueError("work-specific source mapping carrier policy drifted")
    if tei_policy.get("schema_order_wrappers") != {
        "source_parent_tags": ["div", "div1", "div2", "div3", "div4", "div5", "div6"],
        "trigger": "A non-division source child follows the first direct division child.",
        "tei_element": "div",
        "tei_type": "source-order-wrapper",
        "content": "A maximal contiguous run of non-division source siblings, ending before the next source division.",
        "source_relationship_evidence": "standOff source_parent_key and source_ordinal remain exact; wrappers add no source text.",
    }:
        raise ValueError("work-specific TEI schema-order wrapper policy drifted")

    body_nodes = source_root.xpath("./ThML.body/div1")
    body_ids = [node.get("id") for node in body_nodes]
    if body_ids != envelope_policy.get("expected_body_div1_ids_in_order"):
        raise ValueError("HCC4 body member selection drifted")
    if len(source_root.xpath("./ThML.body/div1/div2[@type='Chapter']")) != envelope_policy.get("expected_chapter_count"):
        raise ValueError("HCC4 chapter division count drifted")
    if len(source_root.xpath("./ThML.body/div1[@id='ii']/div2")) != envelope_policy.get("expected_index_division_count"):
        raise ValueError("HCC4 index division count drifted")

    if b"<!DOCTYPE" in tei_bytes.upper() or b"<!ENTITY" in tei_bytes.upper():
        raise ValueError("candidate TEI contains a DTD or entity declaration")
    declaration = _XML_DECLARATION.match(tei_bytes)
    if declaration is None or declaration.group(1) != b'<?xml version="1.0" encoding="UTF-8"?>':
        raise ValueError("candidate XML declaration is missing or drifted")
    candidate_tree = _parse_xml(tei_bytes, "HCC4 TEI candidate")
    candidate_root = candidate_tree.getroot()
    if candidate_tree.docinfo.doctype:
        raise ValueError("candidate TEI must not load or repeat the source DTD")
    _verify_external_comments(source_root, candidate_root)
    _verify_header(source_root, candidate_root, source_tree.docinfo.doctype or "")
    represented_nodes = _verify_source_projection(source_root, candidate_root, records)

    text = candidate_root.find(f"{{{TEI_NS}}}text")
    body = text.find(f"{{{TEI_NS}}}body") if text is not None else None
    if body is None:
        raise ValueError("candidate TEI body is missing")
    if any(
        isinstance(node.tag, str) and node not in represented_nodes
        for node in body.iter()
    ):
        raise ValueError("candidate contains an unaccounted body element")

    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    tei_schema = compiled_tei_schema(xsd_path)
    if not tei_schema.validate(candidate_root):
        errors = list(tei_schema.error_log)
        details = "; ".join(str(error) for error in errors[:5])
        raise ValueError(
            f"HCC4 TEI schema validation failed ({len(errors)} errors): {details}"
        )

    accountability = _expected_accountability(
        source_manifest,
        profile,
        source_bytes,
        source_tree,
        records,
        divisions,
        headings,
    )
    closure = _import_closure_sha256()
    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping) or validator.get("import_closure_sha256") != closure:
        raise ValueError("HCC4 independent-checker import closure drifted")
    package_schema = source_manifest.authority_path("candidate-package-schema")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=source_digest,
        profile_sha256=_sha(source_manifest.authority_path(PROFILE_NAME).read_bytes()),
        package_schema_sha256=_sha(package_schema.read_bytes()),
        xsd_sha256=_sha(xsd_path.read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return facts, accountability


def _import_closure_sha256() -> str:
    root = Path(__file__).resolve().parents[2]
    policy_path = root / _PROFILE_PATH
    policy = _strict_json(policy_path.read_bytes(), "HCC4 validation policy")
    paths = policy.get("oracle_import_closure_paths")
    if tuple(paths or ()) != _CLOSURE_PATHS:
        raise ValueError("HCC4 checker closure declaration drifted")
    rows = []
    for relative in _CLOSURE_PATHS:
        path = root / relative
        rows.append({"path": relative, "sha256": _sha(path.read_bytes())})
    return _sha(_canonical({"contract": "ocd-python-import-closure-v1", "files": rows}))


def _expected_provenance(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    source_bytes: bytes,
) -> dict[str, object]:
    return {
        "contract": "ocd-schaff-history-vol-4-candidate-provenance-v1",
        "ticket_id": "LIB-058",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source_manifest_sha256": source_manifest.sha256,
        "source": {
            "path": "raw/ccel/schaff/hcc4.xml",
            "bytes": len(source_bytes),
            "sha256": _sha(source_bytes),
            "format": "ThML XML",
        },
        "identity": profile.get("identity"),
        "candidate_boundary": {
            "status": "nonaccepted",
            "publication": "not_ready",
            "canonical_data_or_ir_written": False,
        },
        "rights": {"status": "unresolved", "license": None},
    }


def _verify_candidate_members(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    facts: MechanicalFacts,
    accountability: Mapping[str, object],
) -> None:
    manifest_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    converter = source_manifest.record.get("converter")
    if not isinstance(converter, Mapping):
        raise ValueError("HCC4 producer binding is missing")
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != SOURCE_ID
        or candidate.manifest.get("source_manifest")
        != {"path": manifest_path, "sha256": source_manifest.sha256}
        or candidate.manifest.get("converter") != dict(converter)
        or candidate.manifest.get("package_schema")
        != dict(source_manifest.record["package_schema"])
    ):
        raise ValueError("HCC4 candidate manifest binding drifted")

    account_bytes = candidate.member_bytes("source-accountability.json")
    if account_bytes != _canonical(accountability):
        raise ValueError("HCC4 source-accountability member drifted")
    account_schema = _strict_json(
        source_manifest.authority_path(ACCOUNTABILITY_SCHEMA_NAME).read_bytes(),
        "HCC4 source-accountability schema",
    )
    errors = sorted(Draft202012Validator(account_schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"HCC4 accountability schema failure: {errors[0].message}")

    source_bytes = source_manifest.authority_path("primary-source").read_bytes()
    profile = _strict_json(
        source_manifest.authority_path(PROFILE_NAME).read_bytes(), "HCC4 profile"
    )
    expected_provenance = _expected_provenance(source_manifest, profile, source_bytes)
    provenance_bytes = candidate.member_bytes("provenance.json")
    if provenance_bytes != _canonical(expected_provenance):
        raise ValueError("HCC4 provenance or rights disposition drifted")

    expected_unresolved = [
        {
            "id": "schaff-history-vol-4-edition",
            "status": "unresolved",
            "kind": "edition",
            "detail": "The retained member identifies a CCEL ThML/EBS electronic source, but the exact historical print-edition witness is not settled; the legacy config claim is not adopted.",
        },
        {
            "id": "schaff-history-vol-4-textual-form",
            "status": "unresolved",
            "kind": "textual_form",
            "detail": "The source records English but does not establish the exact translation or revision represented by this digital witness.",
        },
        {
            "id": "schaff-history-vol-4-rights",
            "status": "unresolved",
            "kind": "rights",
            "detail": "The retained DC.Rights element is empty. No license or public-domain status is inferred.",
        },
        {
            "id": "schaff-history-vol-4-human-acceptance",
            "status": "unresolved",
            "kind": "acceptance",
            "detail": "No human textual acceptance or visual review has occurred.",
        },
    ]
    unresolved = [
        _strict_json(line, "HCC4 unresolved record")
        for line in candidate.member_bytes("unresolved.jsonl").splitlines()
        if line.strip()
    ]
    if unresolved != expected_unresolved:
        raise ValueError("HCC4 unresolved questions or rights status drifted")
    expected_readme = (
        "# Source note\n\n"
        "Retained source: `raw/ccel/schaff/hcc4.xml` (ThML; source bookID/workID `hcc4`). "
        "The retained header identifies the Electronic Bible Society and Christian Classics "
        "Ethereal Library. Its `DC.Rights` element is empty; no license or public-domain "
        "status is inferred. This reconstruction is nonaccepted and not publication-ready.\n"
    ).encode("utf-8")
    if candidate.member_bytes("README.source.md") != expected_readme:
        raise ValueError("HCC4 source note or unresolved rights disclosure drifted")
    if facts.findings:
        raise ValueError("HCC4 mechanical facts contain findings")


def _oracle(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    facts, accountability = _independent_check(
        source_manifest, candidate.member_bytes("content.tei.xml")
    )
    _verify_candidate_members(source_manifest, candidate, facts, accountability)
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
