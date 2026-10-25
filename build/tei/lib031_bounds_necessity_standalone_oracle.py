"""Independent source comparison for the Bounds Necessity standalone pilot."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from lxml import etree

from ocd_kernel.tei.validate import compiled_schema

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_ID = "bounds-necessity-of-prayer"


def _kind(node: etree._Element) -> str:
    return node.tag if isinstance(node.tag, str) else "#comment"


def _source_selector(node: etree._Element, body: etree._Element) -> str:
    parts: list[str] = []
    current = node
    while current is not body:
        parent = current.getparent()
        if parent is None:
            raise ValueError("source node escaped the ThML body")
        kind = _kind(current)
        ordinal = sum(_kind(sibling) == kind for sibling in parent[: parent.index(current) + 1])
        parts.append(f"{kind}[{ordinal}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def verify(source_bytes: bytes, tei_bytes: bytes, accounting: Mapping[str, object]) -> dict[str, int]:
    """Compare the complete source body and every mapped TEI carrier."""
    expected_sha = accounting.get("source_sha256")
    if hashlib.sha256(source_bytes).hexdigest() != expected_sha:
        raise ValueError("retained source hash changed")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    if source.tag != "ThML":
        raise ValueError("retained source is not ThML")
    body = source.find("ThML.body")
    head = source.find("ThML.head")
    if body is None or head is None:
        raise ValueError("retained ThML head or body missing")
    boundary = accounting.get("source_body_boundary")
    if boundary != {"text": body.text or "", "tail": body.tail or "", "disposition": "excluded formatting whitespace"} or (body.text or "").strip() or (body.tail or "").strip():
        raise ValueError("retained source body boundary changed")
    rows = accounting.get("body_crosswalk")
    if not isinstance(rows, list):
        raise ValueError("source body crosswalk missing")
    source_nodes = list(body.iter())[1:]
    if len(source_nodes) != len(rows):
        raise ValueError("source body node count changed")
    header_rows = accounting.get("source_header")
    header_nodes = list(head.iter())
    if not isinstance(header_rows, list) or len(header_nodes) != len(header_rows):
        raise ValueError("retained source header inventory changed")
    for node, row in zip(header_nodes, header_rows, strict=True):
        if not isinstance(row, dict) or (row.get("tag"), row.get("attributes"), row.get("text"), row.get("tail")) != (
            _kind(node), dict(node.attrib), node.text or "", node.tail or ""
        ):
            raise ValueError("retained source header changed")

    tei = etree.fromstring(tei_bytes, parser)
    if tei.tag != f"{{{TEI_NS}}}TEI":
        raise ValueError("standalone candidate needs a TEI root")
    tree = etree.ElementTree(tei)
    if not compiled_schema().validate(tree):
        raise ValueError("standalone candidate fails TEI XSD")
    ns = {"tei": TEI_NS}
    work_divs = tei.xpath("./tei:text/tei:body/tei:div", namespaces=ns)
    if len(work_divs) != 1 or work_divs[0].get(XML_ID) != WORK_ID:
        raise ValueError("standalone candidate has wrong work boundary")
    unaccounted = [node for node in work_divs[0].iter() if isinstance(node.tag, str) and not node.get(XML_ID)]
    if unaccounted:
        raise ValueError("unaccounted readable TEI content")
    source_hash_nodes = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:idno[@type='sha256']", namespaces=ns)
    if len(source_hash_nodes) != 1 or source_hash_nodes[0].text != expected_sha:
        raise ValueError("standalone header has wrong retained-source hash")
    target_nodes = [node for node in work_divs[0].iter() if isinstance(node.tag, str)]
    by_id = {node.get(XML_ID): node for node in target_nodes if node.get(XML_ID)}
    if len(by_id) != len([node for node in target_nodes if node.get(XML_ID)]):
        raise ValueError("duplicate TEI ID")
    expected_ids = {WORK_ID}
    division_count = 0
    heading_count = 0
    source_id_targets = {}
    for source_node, row in zip(source_nodes, rows, strict=True):
        source_id = source_node.get("id")
        if source_id:
            if source_id in source_id_targets:
                raise ValueError(f"duplicate retained source ID: {source_id}")
            source_id_targets[source_id] = str(row.get("tei_selector", ""))[1:]
    localized_links = 0
    for source_node, row in zip(source_nodes, rows, strict=True):
        if not isinstance(row, dict) or row.get("work_id") != WORK_ID:
            raise ValueError("crosswalk work binding changed")
        if (
            row.get("source_tag") != _kind(source_node)
            or row.get("source_selector") != _source_selector(source_node, body)
            or row.get("attributes") != dict(source_node.attrib)
            or row.get("direct_text") != (source_node.text or "")
            or row.get("tail_text") != (source_node.tail or "")
        ):
            raise ValueError("source body or accounting changed")
        if source_node.tag in {"div1", "div2"}:
            division_count += 1
        parent_source = source_node.getparent()
        is_division_heading = (
            source_node.tag in {"h1", "h2"} and parent_source is not None
            and parent_source.tag in {"div1", "div2"} and parent_source.index(source_node) == 0
        )
        if is_division_heading:
            heading_count += 1
            if row.get("tei_tag") != "head":
                raise ValueError("source division heading not represented as TEI head")
        selector = row.get("tei_selector")
        if not isinstance(selector, str) or not selector.startswith("#"):
            raise ValueError("missing TEI feature selector")
        target_id = selector[1:]
        expected_ids.add(target_id)
        target = by_id.get(target_id)
        if target is None:
            raise ValueError(f"missing TEI feature {target_id}")
        expected_attrs = row.get("tei_attributes")
        if not isinstance(expected_attrs, dict):
            raise ValueError(f"missing TEI attribute expectation: {target_id}")
        actual_attrs = {"xml:id" if key == XML_ID else key: value for key, value in target.attrib.items()}
        if actual_attrs != expected_attrs:
            raise ValueError(f"TEI attributes changed: {target_id}")
        if row.get("source_tag") == "a":
            href = source_node.get("href", "")
            before, separator, fragment = href.partition("#")
            if not separator or not before.startswith("?") or not fragment or fragment not in source_id_targets:
                raise ValueError(f"unresolved source index link: {href}")
            expected_local = "#" + source_id_targets[fragment]
            if target.get("target") != expected_local or expected_local[1:] not in by_id:
                raise ValueError(f"source index link target changed: {target_id}")
            localized_links += 1
        if row.get("source_tag") == "i" and target.get("rend") != "italic":
            raise ValueError(f"source italics changed: {target_id}")
        parent = target.getparent()
        if parent is None or (
            etree.QName(target).localname != row.get("tei_tag")
            or (target.text or "") != (source_node.text or "")
            or (target.tail or "") != (source_node.tail or "")
            or parent.get(XML_ID) != row.get("tei_parent_id")
            or parent.index(target) + 1 != row.get("tei_child_ordinal")
        ):
            raise ValueError(f"TEI feature changed: {target_id}")
    if localized_links != accounting.get("source_index_links_localized"):
        raise ValueError("source index link coverage incomplete")
    if heading_count != division_count or accounting.get("source_division_headings") != heading_count:
        raise ValueError("source division heading coverage incomplete")
    if set(by_id) != expected_ids:
        raise ValueError("unaccounted TEI feature ID")
    return {"source_body_nodes": len(source_nodes), "source_header_nodes": len(header_nodes), "mapped_tei_nodes": len(rows)}
