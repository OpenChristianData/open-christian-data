"""Independent DOM-ledger and policy-driven oracle for LIB-030."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Mapping
from xml.dom import Node, minidom

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib030-source-to-tei-oracle"
ORACLE_VERSION = "3"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
MEMBERS = frozenset(
    {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
)
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
DOCTYPE = (
    '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" '
    '"http://www.ccel.org/dtd/ThML10.dtd">'
)
STRUCTURAL_DOM_TYPES = {
    Node.ELEMENT_NODE,
    Node.COMMENT_NODE,
    Node.PROCESSING_INSTRUCTION_NODE,
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _json_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"LIB-030 {label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"LIB-030 {label} must be an object")
    return value


def _json_path(path: Path, label: str) -> dict[str, Any]:
    return _json_bytes(path.read_bytes(), label)


def _members(
    manifest: SourceManifest, profile: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    source_set = _json_path(manifest.authority_path("retained-source-set"), "source set")
    raw_members = source_set.get("members")
    work_order = profile.get("work_order")
    if (
        source_set.get("contract") != "ocd-retained-source-set-v1"
        or profile.get("contract") != "ocd-lib030-reconstruction-profile-v3"
        or not isinstance(raw_members, list)
        or not isinstance(work_order, list)
        or len(raw_members) != len(work_order)
    ):
        raise ValueError("LIB-030 source set or profile is malformed")
    configured = os.environ.get("OCD_RETAINED_RAW_ROOT", "").strip()
    retained_root = (
        Path(configured) if configured else manifest.repository_root / "raw"
    ).resolve(strict=True)
    result: list[dict[str, Any]] = []
    for work_id, raw in zip(work_order, raw_members, strict=True):
        if not isinstance(raw, dict) or raw.get("work_id") != work_id:
            raise ValueError("LIB-030 source member order drifted")
        logical_path = raw.get("logical_path")
        if not isinstance(logical_path, str):
            raise ValueError("LIB-030 source member path is invalid")
        path = (retained_root / logical_path).resolve(strict=True)
        try:
            path.relative_to(retained_root)
        except ValueError as exc:
            raise ValueError("LIB-030 source member escaped retained root") from exc
        content = path.read_bytes()
        if len(content) != raw.get("bytes") or _sha(content) != raw.get("sha256"):
            raise ValueError(f"LIB-030 wrong or stale retained source: {logical_path}")
        result.append({**raw, "path": path, "content": content})
    return tuple(result)


def _doctype_end(content: bytes, start: int) -> int:
    quote: int | None = None
    subset_depth = 0
    for index in range(start, len(content)):
        value = content[index]
        if quote is not None:
            if value == quote:
                quote = None
        elif value in (34, 39):
            quote = value
        elif value == 91:
            subset_depth += 1
        elif value == 93 and subset_depth:
            subset_depth -= 1
        elif value == 62 and subset_depth == 0:
            return index + 1
    raise ValueError("LIB-030 retained doctype is unterminated")


def _carrier(
    kind: str, ordinal: int, start: int, end: int, content: bytes
) -> dict[str, Any]:
    value = content[start:end]
    return {
        "carrier_id": f"lib030-envelope-{ordinal:03d}",
        "ordinal": ordinal,
        "kind": kind,
        "start": start,
        "end": end,
        "bytes": len(value),
        "sha256": _sha(value),
        "text": value.decode("utf-8"),
    }


def _envelope(content: bytes) -> dict[str, Any]:
    root_start = content.find(b"<ThML")
    closing_start = content.rfind(b"</ThML>")
    if root_start < 0 or closing_start < root_start:
        raise ValueError("LIB-030 retained root byte boundary is missing")
    root_end = closing_start + len(b"</ThML>")
    carriers: list[dict[str, Any]] = []
    position = 0
    while position < root_start:
        if content.startswith(b"<?xml", position):
            end = content.find(b"?>", position) + 2
            kind = "xml-declaration"
        elif content.startswith(b"<!DOCTYPE", position):
            end = _doctype_end(content, position)
            kind = "doctype"
        elif content.startswith(b"<!--", position):
            end = content.find(b"-->", position) + 3
            kind = "comment"
        elif content.startswith(b"<?", position):
            end = content.find(b"?>", position) + 2
            kind = "processing-instruction"
        elif content[position] in b" \t\r\n":
            end = position + 1
            while end < root_start and content[end] in b" \t\r\n":
                end += 1
            kind = "padding"
        else:
            raise ValueError("LIB-030 retained pre-root bytes are unsupported")
        if end <= position or end > root_start:
            raise ValueError("LIB-030 retained pre-root carrier is malformed")
        carriers.append(_carrier(kind, len(carriers) + 1, position, end, content))
        position = end
    position = root_end
    while position < len(content):
        if content[position] not in b" \t\r\n":
            raise ValueError("LIB-030 retained post-root bytes are unsupported")
        end = position + 1
        while end < len(content) and content[end] in b" \t\r\n":
            end += 1
        carriers.append(
            _carrier("padding", len(carriers) + 1, position, end, content)
        )
        position = end
    declarations = [row for row in carriers if row["kind"] == "xml-declaration"]
    doctypes = [row for row in carriers if row["kind"] == "doctype"]
    if [row["text"] for row in declarations] != [XML_DECLARATION]:
        raise ValueError("LIB-030 retained XML declaration drifted")
    if len(doctypes) != 1:
        raise ValueError("LIB-030 retained doctype cardinality drifted")
    return {
        "encoding": "UTF-8",
        "xml_version": "1.0",
        "root_start": root_start,
        "root_end": root_end,
        "carrier_count": len(carriers),
        "carriers": carriers,
        "regions": {
            "pre_root": {
                "bytes": root_start,
                "sha256": _sha(content[:root_start]),
            },
            "root": {
                "bytes": root_end - root_start,
                "sha256": _sha(content[root_start:root_end]),
            },
            "post_root": {
                "bytes": len(content) - root_end,
                "sha256": _sha(content[root_end:]),
            },
        },
        "covered_bytes": len(content),
    }


def _dom_document(content: bytes) -> minidom.Document:
    try:
        document = minidom.parseString(content)
    except Exception as exc:
        raise ValueError("LIB-030 independent DOM parser rejected retained XML") from exc
    root = document.documentElement
    doctype = document.doctype
    elements = _element_children(root)
    if (
        root.tagName != "ThML"
        or root.hasAttributes()
        or [node.tagName for node in elements] != ["ThML.head", "ThML.body"]
        or doctype is None
        or doctype.name != "ThML"
        or doctype.publicId != "-//CCEL/DTD Theological Markup Language//EN"
        or doctype.systemId != "http://www.ccel.org/dtd/ThML10.dtd"
    ):
        raise ValueError("LIB-030 independent DOM document shell drifted")
    return document


def _element_children(node: Node) -> list[minidom.Element]:
    return [
        child
        for child in node.childNodes
        if child.nodeType == Node.ELEMENT_NODE
        and isinstance(child, minidom.Element)
    ]


def _structural_children(node: Node) -> list[Node]:
    return [child for child in node.childNodes if child.nodeType in STRUCTURAL_DOM_TYPES]


def _node_kind(node: Node) -> str:
    if node.nodeType == Node.ELEMENT_NODE:
        return "element"
    if node.nodeType == Node.COMMENT_NODE:
        return "comment"
    if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE:
        return "processing-instruction"
    raise ValueError(f"LIB-030 unsupported DOM carrier type {node.nodeType}")


def _node_label(node: Node) -> str:
    if node.nodeType == Node.ELEMENT_NODE:
        return str(node.nodeName)
    if node.nodeType == Node.COMMENT_NODE:
        return "#comment"
    return f"?{node.nodeName}"


def _same_carrier(left: Node, right: Node) -> bool:
    return left.nodeType == right.nodeType and _node_label(left) == _node_label(right)


def _pre_root_nodes(document: minidom.Document) -> list[Node]:
    result: list[Node] = []
    for node in document.childNodes:
        if node is document.documentElement:
            break
        if node.nodeType in {Node.COMMENT_NODE, Node.PROCESSING_INSTRUCTION_NODE}:
            result.append(node)
    return result


def _document_nodes(document: minidom.Document) -> list[tuple[str, Node]]:
    result = [("pre-root", node) for node in _pre_root_nodes(document)]

    def visit(node: Node) -> None:
        if node.nodeType in STRUCTURAL_DOM_TYPES:
            result.append(("tree", node))
        for child in node.childNodes:
            if child.nodeType in STRUCTURAL_DOM_TYPES:
                visit(child)

    visit(document.documentElement)
    for node in document.childNodes:
        if node is document.documentElement:
            continue
        if node.nodeType in {Node.COMMENT_NODE, Node.PROCESSING_INSTRUCTION_NODE}:
            if node not in _pre_root_nodes(document):
                result.append(("post-root", node))
    return result


def _selector(node: Node, scope: str, document: minidom.Document) -> str:
    if scope != "tree":
        peers = [
            item
            for item in _pre_root_nodes(document)
            if _same_carrier(item, node)
        ]
        label = (
            "comment"
            if node.nodeType == Node.COMMENT_NODE
            else "processing-instruction"
        )
        return f"/{scope}/{label}()[{peers.index(node) + 1}]"
    parts: list[str] = []
    current: Node | None = node
    while current is not None and current.nodeType != Node.DOCUMENT_NODE:
        parent = current.parentNode
        peers = (
            [current]
            if parent is None or parent.nodeType == Node.DOCUMENT_NODE
            else [
                item
                for item in _structural_children(parent)
                if _same_carrier(item, current)
            ]
        )
        parts.append(f"{_node_label(current)}[{peers.index(current) + 1}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _leading_text(node: Node) -> str:
    values: list[str] = []
    for child in node.childNodes:
        if child.nodeType in STRUCTURAL_DOM_TYPES:
            break
        if child.nodeType in {Node.TEXT_NODE, Node.CDATA_SECTION_NODE}:
            values.append(str(child.nodeValue or ""))
    return "".join(values)


def _tail_text(node: Node) -> str:
    values: list[str] = []
    current = node.nextSibling
    while current is not None and current.nodeType not in STRUCTURAL_DOM_TYPES:
        if current.nodeType in {Node.TEXT_NODE, Node.CDATA_SECTION_NODE}:
            values.append(str(current.nodeValue or ""))
        current = current.nextSibling
    return "".join(values)


def _attributes(node: Node) -> list[list[str]]:
    if node.nodeType != Node.ELEMENT_NODE or node.attributes is None:
        return []
    return [
        [str(node.attributes.item(index).name), str(node.attributes.item(index).value)]
        for index in range(node.attributes.length)
        if not str(node.attributes.item(index).name).startswith("xmlns")
    ]


def _namespace_declarations(node: Node) -> list[list[str]]:
    if node.nodeType != Node.ELEMENT_NODE or node.attributes is None:
        return []
    declarations: list[list[str]] = []
    for index in range(node.attributes.length):
        attribute = node.attributes.item(index)
        if attribute.name == "xmlns":
            declarations.append(["", str(attribute.value)])
        elif attribute.name.startswith("xmlns:"):
            declarations.append([attribute.name.partition(":")[2], str(attribute.value)])
    return declarations


def _source_rows(
    document: minidom.Document,
) -> tuple[list[dict[str, Any]], dict[str, Node]]:
    nodes = _document_nodes(document)
    selector_ordinals = {
        _selector(node, scope, document): ordinal
        for ordinal, (scope, node) in enumerate(nodes, 1)
    }
    rows: list[dict[str, Any]] = []
    nodes_by_selector: dict[str, Node] = {}
    for ordinal, (scope, node) in enumerate(nodes, 1):
        selector = _selector(node, scope, document)
        parent = node.parentNode
        parent_selector = (
            _selector(parent, "tree", document)
            if parent is not None and parent.nodeType in STRUCTURAL_DOM_TYPES
            else None
        )
        siblings = (
            _structural_children(parent)
            if parent is not None and parent.nodeType != Node.DOCUMENT_NODE
            else [node]
        )
        kind = _node_kind(node)
        row: dict[str, Any] = {
            "feature_id": f"lib030-node-{ordinal:06d}",
            "ordinal": ordinal,
            "scope": scope,
            "kind": kind,
            "source_selector": selector,
            "qname": str(node.nodeName) if kind == "element" else None,
            "source_tag": (
                str(node.nodeName)
                if kind == "element"
                else "#comment" if kind == "comment" else "#pi"
            ),
            "pi_target": str(node.nodeName) if kind == "processing-instruction" else None,
            "attributes": _attributes(node),
            "namespace_declarations": _namespace_declarations(node),
            "direct_text": (
                _leading_text(node)
                if kind == "element"
                else str(node.nodeValue or "")
            ),
            "tail_text": _tail_text(node),
            "parent_feature_id": (
                f"lib030-node-{selector_ordinals[parent_selector]:06d}"
                if parent_selector in selector_ordinals
                else None
            ),
            "sibling_ordinal": siblings.index(node) + 1,
        }
        row["source_payload_sha256"] = _sha(_canonical(row))
        rows.append(row)
        nodes_by_selector[selector] = node
    return rows, nodes_by_selector


def _descendant_elements(node: Node, *, include_self: bool = True) -> list[minidom.Element]:
    result: list[minidom.Element] = []
    if include_self and node.nodeType == Node.ELEMENT_NODE and isinstance(node, minidom.Element):
        result.append(node)
    for child in node.childNodes:
        if child.nodeType == Node.ELEMENT_NODE and isinstance(child, minidom.Element):
            result.extend(_descendant_elements(child))
    return result


def _element_text(node: Node | None) -> str:
    if node is None:
        return ""
    values: list[str] = []
    for child in node.childNodes:
        if child.nodeType in {Node.TEXT_NODE, Node.CDATA_SECTION_NODE}:
            values.append(str(child.nodeValue or ""))
        elif child.nodeType == Node.ELEMENT_NODE:
            values.append(_element_text(child))
    return "".join(values)


def _path_nodes(root: minidom.Element, names: list[str]) -> list[minidom.Element]:
    current = [root]
    for name in names:
        next_nodes: list[minidom.Element] = []
        for node in current:
            next_nodes.extend(
                child for child in _element_children(node) if child.tagName == name
            )
        current = next_nodes
    return current


def _one_path(root: minidom.Element, names: list[str]) -> minidom.Element | None:
    values = _path_nodes(root, names)
    return values[0] if values else None


def _metadata(document: minidom.Document) -> dict[str, Any]:
    root = document.documentElement

    def text(names: list[str]) -> str:
        return _element_text(_one_path(root, names))

    def records(names: list[str]) -> list[dict[str, str | None]]:
        return [
            {
                "sub": node.getAttribute("sub") or None,
                "scheme": node.getAttribute("scheme") or None,
                "text": _element_text(node),
            }
            for node in _path_nodes(root, names)
        ]

    prefix = ["ThML.head", "electronicEdInfo"]
    dc = prefix + ["DC"]
    return {
        "title": text(["ThML.head", "title"]),
        "description": text(["ThML.head", "generalInfo", "description"]),
        "publisher": text(dc + ["DC.Publisher"]),
        "contributor": text(dc + ["DC.Contributor"]),
        "date": text(dc + ["DC.Date"]),
        "dc_type": text(dc + ["DC.Type"]),
        "format": text(dc + ["DC.Format"]),
        "identifier": text(dc + ["DC.Identifier"]),
        "language": text(dc + ["DC.Language"]),
        "rights": text(dc + ["DC.Rights"]),
        "version": text(prefix + ["version"]),
        "editorial_comments": text(prefix + ["editorialComments"]),
        "revision_history": text(prefix + ["revisionHistory"]),
        "titles": records(dc + ["DC.Title"]),
        "creators": records(dc + ["DC.Creator"]),
        "subjects": records(dc + ["DC.Subject"]),
        "sources": records(dc + ["DC.Source"]),
        "styles": [
            {"type": node.getAttribute("type") or None, "text": _leading_text(node)}
            for node in _path_nodes(root, ["ThML.head", "style"])
        ],
    }


def _dom_signature(node: Node) -> object:
    if node.nodeType == Node.ELEMENT_NODE:
        attributes = sorted((name, value) for name, value in _attributes(node))
        children = [
            _dom_signature(child)
            for child in node.childNodes
            if child.nodeType
            in {
                Node.ELEMENT_NODE,
                Node.TEXT_NODE,
                Node.CDATA_SECTION_NODE,
                Node.COMMENT_NODE,
                Node.PROCESSING_INSTRUCTION_NODE,
            }
        ]
        return ["element", str(node.nodeName), attributes, children]
    if node.nodeType in {Node.TEXT_NODE, Node.CDATA_SECTION_NODE}:
        return ["text", str(node.nodeValue or "")]
    if node.nodeType == Node.COMMENT_NODE:
        return ["comment", str(node.nodeValue or "")]
    if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE:
        return ["pi", str(node.nodeName), str(node.nodeValue or "")]
    raise ValueError("LIB-030 DOM signature found an unsupported carrier")


def _source_member_digest(members: tuple[dict[str, Any], ...]) -> str:
    records = [
        {
            "work_id": str(item["work_id"]),
            "path": str(item["logical_path"]),
            "bytes": int(item["bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in members
    ]
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": records}))


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _candidate_document(content: bytes) -> tuple[etree._ElementTree, etree._Element]:
    if not content.startswith(b"<?xml version='1.0' encoding='UTF-8'?>"):
        raise ValueError("LIB-030 candidate XML declaration drifted")
    try:
        document = etree.parse(
            io.BytesIO(content),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                huge_tree=True,
                recover=False,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-030 candidate TEI is not well-formed") from exc
    root = document.getroot()
    if (
        document.docinfo.doctype
        or root.getprevious() is not None
        or root.getnext() is not None
        or _local(root) != "TEI"
        or root.nsmap.get(None) != TEI_NS
        or root.get(XML_ID) != "lib030-candidate"
    ):
        raise ValueError("LIB-030 candidate TEI document shell drifted")
    return document, root


def _tei_attributes(node: etree._Element) -> list[list[str]]:
    return [
        ["xml:id" if name == XML_ID else str(name), value]
        for name, value in node.attrib.items()
    ]


def _source_attributes(node: minidom.Element) -> dict[str, str]:
    return {name: value for name, value in _attributes(node)}


def _safe_fragment(value: str, first_ids: Mapping[str, str]) -> str:
    normalized = value[1:] if value.startswith("#") else value
    return f"#{first_ids[normalized]}" if normalized in first_ids else value


def _expected_target_tag(
    source: minidom.Element,
    contract: Mapping[str, Any],
    contracts: Mapping[str, Any],
) -> str:
    configured = contract.get("tei_tag")
    if configured != "heading-context":
        if not isinstance(configured, str):
            raise ValueError("LIB-030 projection policy has an invalid TEI tag")
        return configured
    parent = source.parentNode
    if parent is None or parent.nodeType != Node.ELEMENT_NODE:
        return "p"
    preceding_blocks = 0
    for sibling in _element_children(parent):
        if sibling is source:
            break
        sibling_contract = contracts.get(sibling.tagName)
        if not isinstance(sibling_contract, dict):
            continue
        sibling_target = sibling_contract.get("tei_tag")
        if sibling_target in {
            "heading-context",
            "p",
            "div",
            "ref",
            "hi",
            "seg",
        }:
            preceding_blocks += 1
    parent_contract = contracts.get(str(parent.nodeName), {})
    return "head" if parent_contract.get("tei_tag") == "div" and not preceding_blocks else "p"


def _expected_target_attributes(
    source: minidom.Element,
    feature_id: str,
    contract: Mapping[str, Any],
    first_ids: Mapping[str, str],
) -> dict[str, str]:
    source_attrs = _source_attributes(source)
    expected = {XML_ID: feature_id}
    rules = contract.get("rules")
    if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
        raise ValueError("LIB-030 projection policy rule list is invalid")
    for rule in rules:
        if rule == "source-n" and source_attrs.get("n"):
            expected["n"] = source_attrs["n"]
        elif rule == "source-rend":
            values = []
            if source_attrs.get("class"):
                values.append(f"class:{source_attrs['class']}")
            if source_attrs.get("style"):
                values.append(f"style:{source_attrs['style']}")
            if values:
                expected["rend"] = "; ".join(values)
        elif rule == "href-first-fragment-target" and source_attrs.get("href"):
            expected["target"] = _safe_fragment(source_attrs["href"], first_ids)
        elif rule == "prev-next-first-fragment-targets":
            for name in ("prev", "next"):
                if source_attrs.get(name):
                    expected[name] = _safe_fragment(source_attrs[name], first_ids)
        elif rule == "class-semantic-type":
            class_types = contract.get("class_types")
            if not isinstance(class_types, dict):
                raise ValueError("LIB-030 div class policy is invalid")
            expected["type"] = str(
                class_types.get(source_attrs.get("class"), contract.get("default_type"))
            )
        elif rule == "source-type-indexName":
            expected["indexName"] = source_attrs.get("type", "source-index")
        elif rule == "source-type-subtype" and source_attrs.get("type"):
            expected["subtype"] = source_attrs["type"]
        elif rule == "source-passage-n" and source_attrs.get("passage"):
            expected["n"] = source_attrs["passage"]
        elif rule == "source-osisRef-corresp" and source_attrs.get("osisRef"):
            expected["corresp"] = source_attrs["osisRef"]
        elif rule == "source-osisRef-target" and source_attrs.get("osisRef"):
            expected["target"] = source_attrs["osisRef"]
        elif rule == "source-passage-cRef" and source_attrs.get("passage"):
            expected["cRef"] = source_attrs["passage"]
        elif rule == "source-type-unit-or-source-sync":
            expected["unit"] = source_attrs.get("type", "source-sync")
        elif rule == "source-value-n":
            expected["n"] = source_attrs.get("value", "")
        elif rule == "title-head-if-no-source-heading":
            continue
        elif rule.startswith("constant-"):
            binding, separator, value = rule.partition(":")
            if not separator:
                raise ValueError("LIB-030 constant projection rule is malformed")
            expected[binding.removeprefix("constant-")] = value
        elif rule not in {
            "source-n",
            "source-rend",
            "href-first-fragment-target",
            "prev-next-first-fragment-targets",
            "class-semantic-type",
            "source-type-indexName",
            "source-type-subtype",
            "source-passage-n",
            "source-osisRef-corresp",
            "source-osisRef-target",
            "source-passage-cRef",
            "source-type-unit-or-source-sync",
            "source-value-n",
        }:
            raise ValueError(f"LIB-030 projection policy rule is unsupported: {rule}")
    return expected


def _projected_text(target_tag: str, value: str) -> str:
    return "" if target_tag in {"div", "lg", "index"} and not value.strip() else value


def _source_child_ids(
    node: minidom.Element, rows_by_selector: Mapping[str, dict[str, Any]], document: minidom.Document
) -> list[str]:
    return [
        str(rows_by_selector[_selector(child, "tree", document)]["feature_id"])
        for child in _element_children(node)
    ]


def _candidate_child_ids(
    target: etree._Element, *, allow_title_head: bool
) -> list[str]:
    result: list[str] = []
    children = [child for child in target if isinstance(child.tag, str)]
    if allow_title_head and children and _local(children[0]) == "head" and not children[0].get(XML_ID):
        children = children[1:]
    for child in children:
        child_id = child.get(XML_ID)
        if child_id:
            result.append(child_id)
            continue
        nested = [item for item in child if isinstance(item.tag, str)]
        if (
            _local(child) != "p"
            or child.attrib
            or (child.text or "")
            or len(nested) != 1
            or not nested[0].get(XML_ID)
        ):
            raise ValueError("LIB-030 candidate contains an unauthorized synthetic body node")
        result.append(str(nested[0].get(XML_ID)))
    return result


def _projection_shell(target: etree._Element) -> etree._Element:
    parent = target.getparent()
    if (
        parent is not None
        and _local(parent) == "p"
        and not parent.get(XML_ID)
        and len(parent) == 1
    ):
        return parent
    return target


def _validate_header_and_front(
    tei: etree._Element,
    source_document: minidom.Document,
    metadata: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> tuple[etree._Element, etree._Element]:
    namespaces = {"tei": TEI_NS}
    if len(tei) != 2 or [_local(node) for node in tei] != ["teiHeader", "text"]:
        raise ValueError("LIB-030 candidate top-level TEI topology drifted")
    header, text = tei
    if len(text) != 2 or [_local(node) for node in text] != ["front", "body"]:
        raise ValueError("LIB-030 candidate front/body topology drifted")
    front, body = text
    titles = header.xpath(".//tei:titleStmt/tei:title/text()", namespaces=namespaces)
    authors = header.xpath(".//tei:titleStmt/tei:author/text()", namespaces=namespaces)
    header_text = "".join(header.itertext())
    if titles != [metadata["title"]] or not authors:
        raise ValueError("LIB-030 semantic title or author header drifted")
    required_values = [
        metadata["description"],
        metadata["publisher"],
        metadata["contributor"],
        metadata["date"],
        metadata["identifier"],
        metadata["rights"],
        metadata["version"],
        metadata["editorial_comments"],
        metadata["revision_history"],
    ]
    required_values.extend(str(item["text"]) for item in metadata["titles"])
    required_values.extend(str(item["text"]) for item in metadata["creators"])
    if any(value and value not in header_text for value in required_values):
        raise ValueError("LIB-030 semantic source metadata header is incomplete")
    shell = front.xpath('./tei:div[@type="source-document-shell"]', namespaces=namespaces)
    source_heads = front.xpath('./tei:div[@type="source-metadata"]', namespaces=namespaces)
    if len(front) != 2 or len(shell) != 1 or len(source_heads) != 1:
        raise ValueError("LIB-030 candidate source front topology drifted")
    declaration = shell[0].xpath('./tei:ab[@type="xml-declaration"]/text()', namespaces=namespaces)
    doctype = shell[0].xpath('./tei:ab[@type="doctype"]/text()', namespaces=namespaces)
    comments = shell[0].xpath('./tei:note[@type="pre-root-comment"]', namespaces=namespaces)
    source_comments = _pre_root_nodes(source_document)
    if declaration != [XML_DECLARATION] or doctype != [next(
        row["text"] for row in envelope["carriers"] if row["kind"] == "doctype"
    )]:
        raise ValueError("LIB-030 candidate declaration or doctype transcription drifted")
    if [node.text or "" for node in comments] != [
        str(node.nodeValue or "") for node in source_comments
    ]:
        raise ValueError("LIB-030 candidate pre-root comment transcription drifted")
    transcriptions = source_heads[0].xpath(
        './tei:ab[@type="exact-parsed-thml-head-xml"]', namespaces=namespaces
    )
    if len(transcriptions) != 1 or not transcriptions[0].text:
        raise ValueError("LIB-030 source head transcription is missing")
    try:
        transcription = minidom.parseString(transcriptions[0].text.encode("utf-8"))
    except Exception as exc:
        raise ValueError("LIB-030 source head transcription is not parseable XML") from exc
    source_head = _element_children(source_document.documentElement)[0]
    if _dom_signature(transcription.documentElement) != _dom_signature(source_head):
        raise ValueError("LIB-030 source head transcription drifted")
    return front, body


def _validate_crosswalk_and_body(
    source_document: minidom.Document,
    source_rows: list[dict[str, Any]],
    nodes_by_selector: Mapping[str, Node],
    accountability: Mapping[str, Any],
    body: etree._Element,
    policy: Mapping[str, Any],
) -> tuple[int, int, int, int]:
    crosswalk = accountability.get("crosswalk")
    if not isinstance(crosswalk, list) or len(crosswalk) != len(source_rows):
        raise ValueError("LIB-030 complete source crosswalk cardinality drifted")
    rows_by_selector: dict[str, dict[str, Any]] = {}
    for expected, actual in zip(source_rows, crosswalk, strict=True):
        if not isinstance(actual, dict):
            raise ValueError("LIB-030 crosswalk row is invalid")
        base = {key: actual.get(key) for key in expected}
        if base != expected:
            raise ValueError("LIB-030 independent DOM source carrier ledger drifted")
        selector = str(actual["source_selector"])
        if selector in rows_by_selector:
            raise ValueError("LIB-030 crosswalk repeats a source selector")
        rows_by_selector[selector] = actual
    source_root = source_document.documentElement
    source_head, source_body = _element_children(source_root)
    pre_nodes = _pre_root_nodes(source_document)
    root_rows = {
        "root": rows_by_selector[_selector(source_root, "tree", source_document)],
        "head": rows_by_selector[_selector(source_head, "tree", source_document)],
        "body": rows_by_selector[_selector(source_body, "tree", source_document)],
    }
    expected_containers = {
        "root": ("represented-as-TEI-document-with-front-and-body", "TEI", "#lib030-candidate"),
        "head": (
            "represented-readable-source-head-transcription-and-semantic-header",
            "ab",
            "#lib030-source-head-transcription",
        ),
        "body": ("represented-as-TEI-body", "body", "#lib030-body"),
    }
    for name, (disposition, tag, target) in expected_containers.items():
        row = root_rows[name]
        if (
            row.get("disposition") != disposition
            or row.get("tei_tag") != tag
            or row.get("tei_targets") != [target]
        ):
            raise ValueError("LIB-030 source document container accounting drifted")
    for ordinal, node in enumerate(pre_nodes, 1):
        row = rows_by_selector[_selector(node, "pre-root", source_document)]
        target = f"#lib030-prolog-comment-{ordinal}"
        if (
            row.get("disposition") != "represented-readable-tei-front"
            or row.get("tei_tag") != "note"
            or row.get("tei_targets") != [target]
            or row.get("projected_direct_text") != str(node.nodeValue or "")
        ):
            raise ValueError("LIB-030 pre-root source carrier accounting drifted")
    for node in _descendant_elements(source_head):
        row = rows_by_selector[_selector(node, "tree", source_document)]
        if (
            row.get("disposition")
            != "represented-readable-source-head-transcription-and-semantic-header"
            or row.get("tei_tag") != "ab"
            or row.get("tei_targets") != ["#lib030-source-head-transcription"]
            or row.get("projected_direct_text") != _leading_text(node)
            or row.get("projected_tail_text") != _tail_text(node)
        ):
            raise ValueError("LIB-030 source head carrier accounting drifted")
    contracts = policy.get("body_projection_contracts")
    if not isinstance(contracts, dict):
        raise ValueError("LIB-030 projection policy contracts are missing")
    body_nodes = _descendant_elements(source_body, include_self=False)
    source_tags = {node.tagName for node in body_nodes}
    if set(contracts) != source_tags:
        raise ValueError("LIB-030 projection policy does not close over source body tags")
    body_rows = [
        rows_by_selector[_selector(node, "tree", source_document)] for node in body_nodes
    ]
    candidate_targets: dict[str, etree._Element] = {}
    for node in body.xpath('.//*[@xml:id]', namespaces={"xml": XML_NS}):
        identifier = node.get(XML_ID)
        if identifier is None or identifier in candidate_targets:
            raise ValueError("LIB-030 candidate body repeats an xml:id")
        candidate_targets[identifier] = node
    expected_ids = {str(row["feature_id"]) for row in body_rows}
    source_target_ids = {
        identifier
        for identifier in candidate_targets
        if identifier.startswith("lib030-node-")
    }
    if source_target_ids != expected_ids:
        raise ValueError("LIB-030 candidate body omitted or invented source projections")
    document_order_ids = [
        node.get(XML_ID)
        for node in body.xpath('.//*[@xml:id]', namespaces={"xml": XML_NS})
        if (node.get(XML_ID) or "").startswith("lib030-node-")
    ]
    if document_order_ids != [str(row["feature_id"]) for row in body_rows]:
        raise ValueError("LIB-030 candidate body source projection order drifted")
    id_occurrences: dict[str, list[str]] = {}
    for source, row in zip(body_nodes, body_rows, strict=True):
        source_id = source.getAttribute("id") if source.hasAttribute("id") else ""
        if source_id:
            id_occurrences.setdefault(source_id, []).append(str(row["feature_id"]))
    first_ids = {name: identifiers[0] for name, identifiers in id_occurrences.items()}
    duplicate_ids = {name for name, identifiers in id_occurrences.items() if len(identifiers) > 1}
    internal_references: list[tuple[minidom.Element, str, str]] = []
    for source in body_nodes:
        source_attrs = _source_attributes(source)
        for attribute in ("href", "prev", "next"):
            value = source_attrs.get(attribute)
            normalized = value[1:] if value and value.startswith("#") else value
            if normalized and normalized in first_ids:
                internal_references.append((source, attribute, normalized))
    for source, row in zip(body_nodes, body_rows, strict=True):
        contract = contracts.get(source.tagName)
        if not isinstance(contract, dict):
            raise ValueError("LIB-030 body projection contract is malformed")
        identifier = str(row["feature_id"])
        target = candidate_targets[identifier]
        expected_tag = _expected_target_tag(source, contract, contracts)
        expected_attrs = _expected_target_attributes(
            source, identifier, contract, first_ids
        )
        if _local(target) != expected_tag or dict(target.attrib) != expected_attrs:
            raise ValueError("LIB-030 policy-driven target tag or attribute projection drifted")
        if (
            row.get("disposition") != "represented-readable-tei-body"
            or row.get("tei_targets") != [f"#{identifier}"]
            or row.get("tei_tag") != expected_tag
            or row.get("tei_attributes") != _tei_attributes(target)
            or row.get("projected_direct_text")
            != _projected_text(expected_tag, _leading_text(source))
            or row.get("projected_tail_text") != _tail_text(source)
        ):
            raise ValueError("LIB-030 body crosswalk projection receipt drifted")
        title = source.getAttribute("title") if source.hasAttribute("title") else ""
        has_source_heading = any(
            child.tagName in {"h1", "h2", "h3"} for child in _element_children(source)
        )
        allow_title_head = source.tagName in {"div1", "div2"} and bool(title) and not has_source_heading
        if allow_title_head:
            children = [child for child in target if isinstance(child.tag, str)]
            if (
                not children
                or _local(children[0]) != "head"
                or children[0].attrib
                or (children[0].text or "") != title
                or (children[0].tail or "")
                != _projected_text(expected_tag, _leading_text(source))
            ):
                raise ValueError("LIB-030 synthetic title head drifted")
        elif (target.text or "") != _projected_text(expected_tag, _leading_text(source)):
            raise ValueError("LIB-030 projected direct source text drifted")
        if _candidate_child_ids(target, allow_title_head=allow_title_head) != _source_child_ids(
            source, rows_by_selector, source_document
        ):
            raise ValueError("LIB-030 projected source child topology drifted")
        source_parent = source.parentNode
        parent_target_tag = "div"
        if source_parent is not source_body and isinstance(source_parent, minidom.Element):
            parent_row = rows_by_selector[_selector(source_parent, "tree", source_document)]
            parent_target_tag = _local(candidate_targets[str(parent_row["feature_id"])])
        shell = _projection_shell(target)
        if (shell.tail or "") != _projected_text(parent_target_tag, _tail_text(source)):
            raise ValueError("LIB-030 projected source tail text drifted")
        parent = target.getparent()
        if parent is not None and parent is not body:
            expected_wrapper = parent_target_tag in {"div", "quote"} and expected_tag in {
                "ref",
                "hi",
                "seg",
            }
            if expected_wrapper != (parent.get(XML_ID) is None and _local(parent) == "p"):
                raise ValueError("LIB-030 inline source wrapper topology drifted")
    work = body.xpath('./tei:div[@type="work"]', namespaces={"tei": TEI_NS})
    if len(body) != 1 or len(work) != 1:
        raise ValueError("LIB-030 candidate work container topology drifted")
    if _candidate_child_ids(work[0], allow_title_head=False) != _source_child_ids(
        source_body, rows_by_selector, source_document
    ):
        raise ValueError("LIB-030 candidate work root child topology drifted")
    return (
        len(id_occurrences),
        len(duplicate_ids),
        len(internal_references),
        sum(reference in duplicate_ids for _node, _attribute, reference in internal_references),
    )


def _feature_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        tag = str(row["source_tag"])
        result[tag] = result.get(tag, 0) + 1
    return result


def _work(profile: Mapping[str, Any], work_id: str) -> dict[str, Any]:
    works = profile.get("works")
    if isinstance(works, list):
        for item in works:
            if isinstance(item, dict) and item.get("work_id") == work_id:
                return item
    raise ValueError("LIB-030 profile work metadata is missing")


def _validate_sidecars(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    profile: Mapping[str, Any],
    member: Mapping[str, Any],
    source_document: minidom.Document,
    source_rows: list[dict[str, Any]],
    envelope: Mapping[str, Any],
    metadata: Mapping[str, Any],
    accountability: Mapping[str, Any],
    id_unique_count: int,
    duplicate_id_value_count: int,
    internal_reference_count: int,
    duplicate_id_reference_count: int,
) -> None:
    source_head, source_body = _element_children(source_document.documentElement)
    body_elements = _descendant_elements(source_body)
    source_ids = [
        node.getAttribute("id") for node in body_elements if node.hasAttribute("id")
    ]
    document_expected = {
        "work_id": member["work_id"],
        "logical_path": member["logical_path"],
        "bytes": member["bytes"],
        "sha256": member["sha256"],
        "document_envelope": envelope,
        "node_count": len(source_rows),
        "node_kind_counts": {
            kind: sum(row["kind"] == kind for row in source_rows)
            for kind in ("element", "comment", "processing-instruction")
        },
        "attribute_count": sum(len(row["attributes"]) for row in source_rows),
        "head_node_count": len(_descendant_elements(source_head)),
        "body_node_count": len(body_elements),
        "body_projection_node_count": len(body_elements) - 1,
        "source_xml_id_occurrence_count": len(source_ids),
        "source_xml_id_unique_count": id_unique_count,
        "source_duplicate_xml_id_value_count": duplicate_id_value_count,
        "source_duplicate_xml_id_extra_occurrence_count": len(source_ids) - id_unique_count,
        "internal_source_reference_count": internal_reference_count,
        "duplicate_id_reference_count": duplicate_id_reference_count,
        "semantic_index_container_count": sum(
            node.tagName == "div" and node.getAttribute("class") == "Index"
            for node in body_elements
        ),
        "centered_front_matter_container_count": sum(
            node.tagName == "div" and node.getAttribute("class") == "Center"
            for node in body_elements
        ),
        "feature_counts": _feature_counts(source_rows),
        "omitted_node_count": 0,
        "duplicate_node_count": 0,
        "invented_node_count": 0,
        "unresolved_node_count": 0,
    }
    if accountability.get("document_accounting") != [document_expected]:
        raise ValueError("LIB-030 independent document accounting census drifted")
    member_record = {
        "work_id": str(member["work_id"]),
        "path": str(member["logical_path"]),
        "bytes": int(member["bytes"]),
        "sha256": str(member["sha256"]),
    }
    expected_top = {
        "contract": "ocd-lib030-source-accountability-v3",
        "schema": "lib030.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_scope": "complete retained XML byte envelope and every parsed document node",
        "source_reference_authority": {
            "path": source_manifest.path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "authority": "retained-source-set",
            "sha256": _sha(
                source_manifest.authority_path("retained-source-set").read_bytes()
            ),
        },
        "source_members": [member_record],
        "document_accounting": [document_expected],
        "work_count": 1,
        "node_count": len(source_rows),
        "attribute_count": sum(len(row["attributes"]) for row in source_rows),
        "internal_source_reference_count": internal_reference_count,
        "duplicate_id_reference_count": duplicate_id_reference_count,
        "omitted_node_count": 0,
        "duplicate_node_count": 0,
        "invented_node_count": 0,
        "unresolved_node_count": 0,
        "crosswalk": accountability["crosswalk"],
    }
    if accountability != expected_top:
        raise ValueError("LIB-030 source accountability sidecar contains drift or invention")
    provenance = _json_bytes(candidate.member_bytes("provenance.json"), "provenance")
    expected_provenance = {
        "contract": "ocd-lib030-provenance-v3",
        "status": "nonaccepted",
        "publication_state": "not_ready",
        "source_id": source_manifest.record["source_id"],
        "source_member_set_sha256": _source_member_digest((dict(member),)),
        "source_root": "durable retained raw root resolved through OCD_RETAINED_RAW_ROOT or approved raw topology",
        "source_document_metadata": dict(metadata),
        "works": [
            {
                **_work(profile, str(member["work_id"])),
                "source_sha256": member["sha256"],
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
            }
        ],
        "rights": {
            "retained_dc_rights": metadata["rights"],
            "underlying_work_claim": "local-config-public-domain",
            "electronic_host_terms": "CCEL parsing permission retained as evidence",
            "worldwide_rights_decision": "unresolved",
        },
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    if provenance != expected_provenance:
        raise ValueError("LIB-030 metadata, provenance, rights, or status drifted")
    unresolved = [
        {
            "id": "lib030-print-edition-collation",
            "scope": ["spurgeons-morning-evening"],
            "status": "unresolved",
            "question": "Does the retained CCEL ThML witness match the intended print edition?",
            "evidence": "No print collation was performed; the candidate is bound to the retained source bytes.",
        },
        {
            "id": "lib030-human-acceptance-and-publication",
            "scope": ["spurgeons-morning-evening"],
            "status": "unresolved",
            "question": "Will a maintainer accept the candidate text, rights basis, and publication status?",
            "evidence": "Technical reconstruction and validation are not human acceptance or publication authorization.",
        },
    ]
    if candidate.member_bytes("unresolved.jsonl") != b"".join(
        _canonical(item) for item in unresolved
    ):
        raise ValueError("LIB-030 unresolved scope or evidence drifted")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path(
        "source-attribution"
    ).read_bytes():
        raise ValueError("LIB-030 source attribution README drifted")


def _closure_module_path(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    module_path = base.with_suffix(".py")
    if module_path.is_file():
        return module_path.resolve()
    package_path = base / "__init__.py"
    return package_path.resolve() if package_path.is_file() else None


def _resolved_import(module: str, path: Path, imported: str | None, level: int) -> str:
    if level == 0:
        return imported or ""
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if level - 1 > len(parts):
        return ""
    base = parts[: len(parts) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _closure_paths(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.lib030_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _closure_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        parts = module.split(".")
        packages = parts if path.name == "__init__.py" else parts[:-1]
        pending.extend(".".join(packages[:index]) for index in range(1, len(packages) + 1))
        syntax = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(syntax):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import(module, path, node.module, node.level)
                if base:
                    names.append(base)
                    names.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id
                in {"__import__", "eval", "exec", "import_module"}
            ):
                raise ValueError("LIB-030 oracle closure contains dynamic import")
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(f"LIB-030 oracle imports forbidden module {name}")
                if _closure_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


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
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    if (
        set(candidate.member_names) != MEMBERS
        or candidate.manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("LIB-030 candidate member or status closure drifted")
    expected_source_binding = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if candidate.manifest.get("source_manifest") != expected_source_binding:
        raise ValueError("LIB-030 candidate source-manifest binding drifted")
    if candidate.manifest.get("converter") != source_manifest.record["converter"]:
        raise ValueError("LIB-030 candidate converter binding drifted")
    if candidate.manifest.get("package_schema") != source_manifest.record["package_schema"]:
        raise ValueError("LIB-030 candidate package schema binding drifted")
    profile_path = source_manifest.authority_path("reconstruction-profile")
    policy_path = source_manifest.authority_path("validation-policy")
    profile = _json_path(profile_path, "profile")
    policy = _json_path(policy_path, "policy")
    expected_policy = {
        "candidate_status": "nonaccepted",
        "publication_state": "not_ready",
        "required_work_count": 1,
        "required_source_member_count": 1,
        "required_document_node_count": 13_824,
        "required_element_count": 13_821,
        "required_pre_root_comment_count": 3,
        "required_attribute_count": 27_125,
        "required_head_node_count": 73,
        "required_body_node_count": 13_747,
        "required_body_projection_node_count": 13_746,
        "required_source_xml_id_occurrence_count": 9_178,
        "required_source_xml_id_unique_count": 8_444,
        "required_source_duplicate_xml_id_value_count": 734,
        "required_source_duplicate_xml_id_extra_occurrence_count": 734,
        "required_internal_source_reference_count": 2_591,
        "required_duplicate_id_reference_count": 2_564,
        "required_omitted_node_count": 0,
        "required_duplicate_node_count": 0,
        "required_invented_node_count": 0,
        "required_unresolved_node_count": 0,
    }
    if {key: policy.get(key) for key in expected_policy} != expected_policy:
        raise ValueError("LIB-030 validation policy census drifted")
    if set(policy.get("required_member_names", [])) != MEMBERS:
        raise ValueError("LIB-030 validation policy member closure drifted")
    members = _members(source_manifest, profile)
    if len(members) != 1:
        raise ValueError("LIB-030 retained source set cardinality drifted")
    member = members[0]
    source_document = _dom_document(member["content"])
    source_rows, nodes_by_selector = _source_rows(source_document)
    envelope = _envelope(member["content"])
    metadata = _metadata(source_document)
    content = candidate.member_bytes("content.tei.xml")
    _candidate_tree, tei = _candidate_document(content)
    _front, body = _validate_header_and_front(
        tei, source_document, metadata, envelope
    )
    accountability = _json_bytes(
        candidate.member_bytes("source-accountability.json"), "accountability"
    )
    schema = _json_path(
        source_manifest.authority_path("source-accountability-schema"),
        "accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"LIB-030 accountability schema failure: {errors[0].message}")
    (
        id_unique_count,
        duplicate_id_value_count,
        internal_reference_count,
        duplicate_id_reference_count,
    ) = _validate_crosswalk_and_body(
        source_document,
        source_rows,
        nodes_by_selector,
        accountability,
        body,
        policy,
    )
    _validate_sidecars(
        source_manifest,
        candidate,
        profile,
        member,
        source_document,
        source_rows,
        envelope,
        metadata,
        accountability,
        id_unique_count,
        duplicate_id_value_count,
        internal_reference_count,
        duplicate_id_reference_count,
    )
    etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    ).assertValid(tei)
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_path.read_bytes()),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _sha(
            source_manifest.authority_path("retained-source-set").read_bytes()
        ),
        "xsd_sha256": _sha(
            source_manifest.authority_path("tei-p5-xsd").read_bytes()
        ),
        "policy_sha256": _sha(policy_path.read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ("_oracle",)
