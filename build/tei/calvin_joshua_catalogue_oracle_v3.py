"""Version 3 independent check for Joshua catalogue front and duplicated header title."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

from lxml import etree


CATALOGUE_SHA256 = "d5167554c4c40ac2ba320e9ec75afd2565001e0f5f84b0245832b7bfa183b08f"
CATALOGUE_BYTES = 8839
CATALOGUE_TITLE = "Calvin's Commentaries\u2014Complete"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse(path: Path) -> tuple[etree._Element, bytes]:
    raw = path.read_bytes()
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        remove_comments=False,
        remove_pis=False,
    )
    return etree.fromstring(raw, parser), raw


def _name(node: etree._Element) -> str:
    return etree.QName(node).localname


def _path(node: etree._Element) -> str:
    parent = node.getparent()
    if parent is None:
        return f"/{_name(node)}[1]"
    elements = [child for child in parent if isinstance(child.tag, str)]
    return f"{_path(parent)}/{_name(node)}[{elements.index(node) + 1}]"


def _uri(selector: str) -> str:
    return "urn:source-member:commentaries.xml:urn:source-xpath:" + quote(selector, safe="")


def _text(node: etree._Element) -> str:
    return "".join(node.itertext())


def _attrs(node: etree._Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in sorted(node.attrib.items()):
        if key == XML_ID:
            key = "xml:id"
        elif key.startswith("{"):
            key = etree.QName(key).localname
        result[key] = value
    return result


def _source_title_binding(
    catalogue_path: Path,
    master: etree._Element,
    *,
    source_member_path: str,
    source_sha256: str,
    source_bytes: int,
) -> dict[str, object]:
    """Independently bind the raw DC.Title to the duplicated TEI header title."""
    raw = catalogue_path.read_bytes()
    if len(raw) != source_bytes or _digest(raw) != source_sha256:
        raise AssertionError("catalogue title source binding differs from the retained authority")
    source, parsed_bytes = _parse(catalogue_path)
    if parsed_bytes != raw:
        raise AssertionError("catalogue title parser did not use the exact retained bytes")
    title_nodes = [
        node for node in source.iter()
        if isinstance(node.tag, str) and node.tag == "DC.Title" and node.get("sub") == "Main"
    ]
    description_nodes = source.xpath("/ThML/ThML.head/generalInfo/description")
    if len(title_nodes) != 1 or len(description_nodes) != 1:
        raise AssertionError("catalogue requires exactly one main title and separate description")
    title = _text(title_nodes[0])
    title_bytes = title.encode("utf-8")
    offsets = [index for index in range(len(raw)) if raw.startswith(title_bytes, index)]
    if (
        title != CATALOGUE_TITLE
        or title != title.strip()
        or "\ufffd" in title
        or len(offsets) != 1
    ):
        raise AssertionError("raw catalogue DC.Title is not the exact strict UTF-8 main-title value")
    description = _text(description_nodes[0])
    if not description or description == title:
        raise AssertionError("catalogue description was conflated with its main title")
    candidates = master.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl[@type='catalogue'][tei:idno[@type='filename']='commentaries.xml']/tei:title",
        namespaces={"tei": TEI},
    )
    if len(candidates) != 1:
        raise AssertionError("Joshua sourceDesc has no unique catalogue bibliography title")
    candidate_title = _text(candidates[0])
    if candidate_title != title or "\ufffd" in candidate_title:
        raise AssertionError("Joshua catalogue header title differs from retained DC.Title Main")
    return {
        "member": "commentaries.xml",
        "source_path": source_member_path,
        "source_sha256": source_sha256,
        "source_selector": _path(title_nodes[0]),
        "source_title": title,
        "source_title_sha256": _digest(title_bytes),
        "source_title_byte_offset": offsets[0],
        "target_selector": "/TEI[1]/teiHeader[1]/fileDesc[1]/sourceDesc[1]/bibl[1]/title[1]",
        "target_text_sha256": _digest(candidate_title.encode("utf-8")),
        "selector_convention": "all-element-child-position; not same-tag XPath indexing",
        "separate_description_selector": _path(description_nodes[0]),
        "separate_description_text_sha256": _digest(description.encode("utf-8")),
    }


def verify_header_title(
    catalogue_path: Path,
    master_path: Path,
    accountability: Mapping[str, object],
    *,
    source_member_path: str,
    source_sha256: str,
    source_bytes: int,
) -> dict[str, object]:
    """Check the duplicated TEI header title and its source-accountability row."""
    master, _ = _parse(master_path)
    expected = _source_title_binding(
        catalogue_path,
        master,
        source_member_path=source_member_path,
        source_sha256=source_sha256,
        source_bytes=source_bytes,
    )
    if accountability.get("catalogue_title_binding") != expected:
        raise AssertionError("catalogue title source-accountability binding differs")
    return expected


def observe(catalogue_path: Path, master_path: Path, support_path: Path) -> dict[str, object]:
    """Re-derive catalogue body ownership and all source links from raw XML."""
    source, source_bytes = _parse(catalogue_path)
    master, master_bytes = _parse(master_path)
    support = json.loads(support_path.read_text(encoding="utf-8"))
    if _digest(source_bytes) != CATALOGUE_SHA256 or len(source_bytes) != CATALOGUE_BYTES:
        raise AssertionError("retained commentaries.xml bytes differ from the reviewed catalogue")
    if _name(source) != "ThML" or _name(master) != "TEI":
        raise AssertionError("catalogue or Joshua master root differs")
    source_body = [node for node in source if isinstance(node.tag, str) and _name(node) == "ThML.body"]
    if len(source_body) != 1:
        raise AssertionError("catalogue requires one ThML.body")
    source_nodes = [node for node in source_body[0].iter() if isinstance(node.tag, str)]
    front = master.find(f"{{{TEI}}}text/{{{TEI}}}front")
    if front is None:
        raise AssertionError("Joshua TEI has no catalogue front")

    mapped: dict[str, list[etree._Element]] = {}
    for node in master.iter():
        if isinstance(node.tag, str) and node.get("corresp", "").startswith(
            "urn:source-member:commentaries.xml:"
        ):
            mapped.setdefault(node.get("corresp"), []).append(node)

    expected: list[etree._Element] = []
    for source_node in source_nodes:
        selector = _path(source_node)
        uri = _uri(selector)
        hits = mapped.get(uri, [])
        if len(hits) != 1:
            raise AssertionError(f"catalogue source node ownership is not unique: {selector}")
        candidate = hits[0]
        if front not in candidate.iterancestors():
            raise AssertionError(f"catalogue body node escaped Joshua front: {selector}")
        if _text(source_node) != _text(candidate):
            raise AssertionError(f"catalogue body text differs at {selector}")
        expected.append(candidate)
    source_body_uris = {_uri(_path(item)) for item in source_nodes}
    actual_order = [node for node in front.iter() if isinstance(node.tag, str) and node.get("corresp") in source_body_uris]
    if actual_order != expected:
        raise AssertionError("catalogue front source ownership order differs")

    all_source_nodes = [node for node in source.iter() if isinstance(node.tag, str)]
    omitted_styles: list[str] = []
    root_and_head_wrappers = {source, next(node for node in source if isinstance(node.tag, str) and _name(node) == "ThML.head")}
    for source_node in all_source_nodes:
        selector = _path(source_node)
        hits = mapped.get(_uri(selector), [])
        if len(hits) > 1:
            raise AssertionError(f"catalogue source node was duplicated: {selector}")
        in_style = any(_name(ancestor) == "style" for ancestor in source_node.iterancestors()) or _name(source_node) == "style"
        if not hits:
            if not in_style:
                raise AssertionError(f"unaccounted catalogue source node: {selector}")
            omitted_styles.append(selector)
            continue
        candidate = hits[0]
        if source_node in root_and_head_wrappers or in_style:
            continue
        if _text(source_node) != _text(candidate):
            raise AssertionError(f"catalogue source-node text differs at {selector}")
    if len(omitted_styles) != 16:
        raise AssertionError(f"catalogue stylesheet disposition count differs: {len(omitted_styles)} != 16")
    front_uris = {
        node.get("corresp")
        for node in front.iter()
        if isinstance(node.tag, str) and node.get("corresp", "").startswith("urn:source-member:commentaries.xml:")
    }
    expected_front_uris = {
        _uri(_path(node))
        for node in all_source_nodes
        if not any(_name(ancestor) == "style" for ancestor in node.iterancestors()) and _name(node) != "style"
    }
    if front_uris != expected_front_uris:
        raise AssertionError("catalogue front has unexpected source ownership or lacks its raw member wrapper")

    source_links = [node for node in source_body[0].iter() if isinstance(node.tag, str) and _name(node) == "a" and node.get("href")]
    link_rows: list[dict[str, object]] = []
    for link in source_links:
        selector = _path(link)
        candidate = mapped[_uri(selector)][0]
        if _name(candidate) not in {"ref", "ptr"}:
            raise AssertionError(f"catalogue hyperlink did not remain a TEI link: {selector}")
        if candidate.get("target") != link.get("href"):
            raise AssertionError(f"catalogue hyperlink target changed: {selector}")
        if candidate.get("n") != link.get("id"):
            raise AssertionError(f"catalogue hyperlink source ID changed: {selector}")
        if _text(candidate) != _text(link):
            raise AssertionError(f"catalogue hyperlink label changed: {selector}")
        link_rows.append({"selector": selector, "id": link.get("id"), "href": link.get("href"), "label": _text(link)})
    if len(link_rows) != 47:
        raise AssertionError(f"catalogue hyperlink inventory differs: {len(link_rows)} != 47")
    joshua = [row for row in link_rows if row["id"] == "i-p4.1"]
    if len(joshua) != 1 or joshua[0]["id"] != "i-p4.1" or joshua[0]["href"] != "/ccel/calvin/calcom07.html" or joshua[0]["label"] != "Joshua":
        raise AssertionError("Joshua catalogue entry identity or target changed")

    faithful = support.get("faithful_master", {})
    front_links = [
        {"candidate_selector": _path(node), "candidate_xml_id": node.get(XML_ID), "candidate_corresp": node.get("corresp"), "attributes": _attrs(node), "label": _text(node), "label_sha256": _digest(_text(node).encode("utf-8"))}
        for node in front.iter()
        if isinstance(node.tag, str) and _name(node) in {"ref", "ptr"} and (node.get("target") or node.get("cRef"))
    ]
    if faithful.get("candidate_front_relative_links") != front_links:
        raise AssertionError("catalogue source link disposition ledger differs from master")
    source_title = [node for node in source.iter() if isinstance(node.tag, str) and node.tag == "DC.Title" and node.get("sub") == "Main"]
    if len(source_title) != 1:
        raise AssertionError("catalogue main title metadata is missing or ambiguous")
    title = _text(source_title[0]).strip()
    title_bytes = CATALOGUE_TITLE.encode("utf-8")
    title_offsets = [index for index in range(len(source_bytes)) if source_bytes.startswith(title_bytes, index)]
    if title != CATALOGUE_TITLE or len(title_offsets) != 1 or "\ufffd" in title:
        raise AssertionError("catalogue title is not the exact strict UTF-8 source string")
    catalogue_source_member = next(
        (
            node for node in master.xpath(
                "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl[@type='catalogue']/tei:idno[@type='filename']",
                namespaces={"tei": TEI},
            )
            if _text(node) == "commentaries.xml"
        ),
        None,
    )
    if catalogue_source_member is None:
        raise AssertionError("Joshua sourceDesc does not identify the catalogue bibliography")
    header_binding = _source_title_binding(
        catalogue_path,
        master,
        source_member_path="raw/ccel/calvin-commentaries/commentaries.xml",
        source_sha256=CATALOGUE_SHA256,
        source_bytes=CATALOGUE_BYTES,
    )
    mapped_nonstyle_count = len(front_uris)
    if (len(all_source_nodes), len(source_nodes), len(omitted_styles), mapped_nonstyle_count) != (157, 102, 16, 141):
        raise AssertionError("catalogue element partition differs from 157 = 102 + 39 + 16")
    return {
        "status": "pass",
        "catalogue_sha256": _digest(source_bytes),
        "master_sha256": _digest(master_bytes),
        "catalogue_body_element_count": len(source_nodes),
        "catalogue_body_nodes_mapped_once_in_source_order": True,
        "catalogue_source_elements_total": len(all_source_nodes),
        "catalogue_partition": {
            "total_source_elements": len(all_source_nodes),
            "body_elements_mapped": len(source_nodes),
            "nonbody_nonstyle_elements_mapped": mapped_nonstyle_count - len(source_nodes),
            "stylesheet_elements_retained_source_only": len(omitted_styles),
            "equation": "157 = 102 + 39 + 16",
            "disjoint": True,
        },
        "catalogue_stylesheet_elements_retained_in_source_only": len(omitted_styles),
        "catalogue_stylesheet_omission_selectors": omitted_styles,
        "catalogue_main_title_raw": title,
        "catalogue_main_title_ascii_escape": title.encode("ascii", errors="backslashreplace").decode("ascii"),
        "catalogue_main_title_codepoints": [f"U+{ord(character):04X}" for character in title],
        "catalogue_main_title_utf8_hex": title_bytes.hex(),
        "catalogue_main_title_source_byte_offset": title_offsets[0],
        "catalogue_bibl_title_binding": header_binding,
        "catalogue_encoding": {"declaration": "UTF-8", "decoded_strictly": True, "replacement_character_present": False},
        "source_links": len(link_rows),
        "source_link_targets_and_labels_exact": True,
        "joshua_link": joshua[0],
        "catalogue_head_disposition": "retained source remains byte-bound; collection identity stays on historical calvin-commentaries container; non-text CSS/style nodes are not Joshua TEI content",
        "catalogue_link_disposition": "all catalogue links remain in the preserved shared front; only the Joshua row points to this component; sibling targets remain owned by the historical container",
    }
