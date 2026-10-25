"""Losslessly adapt the reviewed LIB-030 TEI shape to current native prose policy.

This is a work-local staging adapter. It does not reconstruct the source, alter
shared projection policy, establish acceptance, or authorize publication.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"t": TEI, "xml": XML}
XML_ID = f"{{{XML}}}id"
TEI_TAG = f"{{{TEI}}}"
CONTRACT = "ocd-lib030-native-projection-adapter-v1"
ORIGINAL_TEI_SHA256 = "6113ff39e994efbf4e50ae559e9651458f1ac70e83595b6ac6d77c9237dbfb0e"

_ENVELOPE_CARRIERS = (
    {
        "xml_id": "lib030-source-xml-declaration",
        "source_type": "xml-declaration",
        "source_parent_id": "lib030-document-shell",
        "source_parent_tag": "div",
        "source_parent_type": "source-document-shell",
        "destination_type": "source-envelope-xml-declaration",
        "role": "XML declaration machine evidence",
    },
    {
        "xml_id": "lib030-source-doctype",
        "source_type": "doctype",
        "source_parent_id": "lib030-document-shell",
        "source_parent_tag": "div",
        "source_parent_type": "source-document-shell",
        "destination_type": "source-envelope-doctype",
        "role": "DOCTYPE machine evidence",
    },
    {
        "xml_id": "lib030-source-head-transcription",
        "source_type": "exact-parsed-thml-head-xml",
        "source_parent_id": "lib030-source-head",
        "source_parent_tag": "div",
        "source_parent_type": "source-metadata",
        "destination_type": "source-envelope-thml-header",
        "role": "Exact parsed ThML header transcription",
    },
)

_GENERATED_HEADINGS = (
    {
        "parent_id": "lib030-document-shell",
        "parent_type": "source-document-shell",
        "text": "Retained CCEL XML document shell",
        "subtype": "source-document-shell",
    },
    {
        "parent_id": "lib030-source-head",
        "parent_type": "source-metadata",
        "text": "Retained ThML metadata, editorial history, rights, and styles",
        "subtype": "source-metadata",
    },
)

_SOURCE_ENVELOPE_WRAPPERS = (
    {"xml_id": "lib030-document-shell", "source_type": "source-document-shell", "front_index": 0},
    {"xml_id": "lib030-source-head", "source_type": "source-metadata", "front_index": 1},
)


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _identified_nodes(root: etree._Element) -> dict[str, etree._Element]:
    result: dict[str, etree._Element] = {}
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        identifier = node.get(XML_ID)
        if identifier:
            if identifier in result:
                raise ValueError(f"duplicate XML identifier: {identifier}")
            result[identifier] = node
    return result


def _tree_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, method="c14n", with_comments=True)


def _reverse_adapter(
    root: etree._Element,
    records: list[dict[str, Any]],
    generated_headings: list[dict[str, Any]],
    prolog_comments: list[dict[str, Any]],
    wrappers: list[dict[str, Any]],
) -> None:
    """Invert the declared transformations to prove complete tree conservation."""
    by_id = _identified_nodes(root)
    restored_by_parent: dict[str, list[tuple[int, etree._Element]]] = {}
    for record in reversed(wrappers):
        node = by_id[record["xml_id"]]
        front = by_id[record["front_parent_id"]]
        notes_stmt = node.getparent()
        if (
            etree.QName(node).localname != "note"
            or node.get("type") != "source-envelope-support"
            or node.get("subtype") != record["source_type"]
            or node.get("corresp") != f"#{record['front_parent_id']}"
            or len(node)
            or notes_stmt is None
            or etree.QName(notes_stmt).localname != "notesStmt"
        ):
            raise ValueError("source-envelope wrapper inverse precondition differs")
        node.tag = TEI_TAG + "div"
        node.set("type", record["source_type"])
        del node.attrib["subtype"]
        del node.attrib["corresp"]
        notes_stmt.remove(node)
        front.append(node)
        restored_by_parent.setdefault(record["front_parent_id"], []).append(
            (record["front_child_index"], node)
        )

    for record in records:
        node = by_id[record["xml_id"]]
        parent = by_id[record["source_parent_id"]]
        notes_stmt = node.getparent()
        if (etree.QName(node).localname != "note"
                or node.get("type") != record["destination_type"]
                or node.get("corresp") != f"#{record['source_parent_id']}"
                or notes_stmt is None or etree.QName(notes_stmt).localname != "notesStmt"):
            raise ValueError("envelope-note inverse precondition differs")
        node.tag = TEI_TAG + "ab"
        node.set("type", record["source_type"])
        del node.attrib["corresp"]
        notes_stmt.remove(node)
        parent.append(node)
        restored_by_parent.setdefault(record["source_parent_id"], []).append(
            (record["source_child_index"], node)
        )

    for record in reversed(generated_headings):
        parent = by_id[record["source_parent_id"]]
        notes_stmt = parent.getroottree().find(f"{TEI_TAG}teiHeader/{TEI_TAG}fileDesc/{TEI_TAG}notesStmt")
        matches = notes_stmt.xpath(
            "./t:note[@type='generated-context' and @subtype=$subtype and @corresp=$corresp]",
            namespaces=NS,
            subtype=record["subtype"],
            corresp=f"#{record['source_parent_id']}",
        ) if notes_stmt is not None else []
        if len(matches) != 1:
            raise ValueError("generated-context inverse selector is ambiguous")
        node = matches[0]
        if (
            etree.QName(node).localname != "note"
            or _sha((node.text or "").encode("utf-8")) != record["text_sha256"]
            or _sha((node.tail or "").encode("utf-8")) != record["tail_sha256"]
        ):
            raise ValueError("generated-context inverse content differs")
        node.tag = TEI_TAG + "head"
        for name in ("type", "subtype", "corresp"):
            del node.attrib[name]
        notes_stmt.remove(node)
        parent.append(node)
        restored_by_parent.setdefault(record["source_parent_id"], []).append(
            (record["source_child_index"], node)
        )

    for record in prolog_comments:
        node = by_id[record["xml_id"]]
        parent = by_id[record["source_parent_id"]]
        notes_stmt = node.getparent()
        if (
            etree.QName(node).localname != "note"
            or node.get("type") != "pre-root-comment"
            or node.get("corresp") != f"#{record['source_parent_id']}"
            or notes_stmt is None
            or etree.QName(notes_stmt).localname != "notesStmt"
            or _sha((node.text or "").encode("utf-8")) != record["text_sha256"]
            or _sha((node.tail or "").encode("utf-8")) != record["tail_sha256"]
        ):
            raise ValueError("pre-root comment inverse precondition differs")
        del node.attrib["corresp"]
        notes_stmt.remove(node)
        parent.append(node)
        restored_by_parent.setdefault(record["source_parent_id"], []).append(
            (record["source_child_index"], node)
        )

    for node in root.xpath("//t:milestone[@ana='urn:ocd:lib030:source-unit:DayOfYear']", namespaces=NS):
        if node.get("unit") != "source-text-break":
            raise ValueError("day marker inverse precondition differs")
        node.set("unit", "DayOfYear")
        del node.attrib["ana"]
    for node in root.xpath("//t:milestone[@unit='scripCom']", namespaces=NS):
        if node.get("type") != "scripture-comment":
            continue
        node.set("unit", "scripture-comment")

    for node in root.xpath("//t:anchor[@type='source-index-scripRef' or @type='source-index-scripCom']", namespaces=NS):
        source_name = node.get("type", "").removeprefix("source-index-")
        node.tag = TEI_TAG + "index"
        del node.attrib["type"]
        node.set("indexName", source_name)

    for parent_id, indexed_nodes in restored_by_parent.items():
        parent = by_id[parent_id]
        if len(parent) != len(indexed_nodes):
            raise ValueError(f"source parent child census differs: {parent_id}")
        ordered = [node for _index, node in sorted(indexed_nodes, key=lambda item: item[0])]
        for node in list(parent):
            parent.remove(node)
        for node in ordered:
            parent.append(node)


def adapt_lib030_for_native_projection(
    original: bytes, *, expected_sha256: str = ORIGINAL_TEI_SHA256,
    require_complete_profile: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    """Return a projection-compatible TEI plus an auditable, reversible receipt.

    Production calls retain the exact LIB-030 candidate TEI pin. The optional
    incomplete-profile mode exists only for the focused miniature contract test.
    """
    original_sha = _sha(original)
    if original_sha != expected_sha256:
        raise ValueError("LIB-030 adapter input TEI hash differs")
    if expected_sha256 != ORIGINAL_TEI_SHA256 and require_complete_profile:
        raise ValueError("full LIB-030 adaptation requires the pinned current candidate")

    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False,
                             remove_pis=False, strip_cdata=False)
    root = etree.fromstring(original, parser)
    if root.tag != TEI_TAG + "TEI" or root.getroottree().docinfo.doctype:
        raise ValueError("LIB-030 candidate TEI envelope differs")
    before = _identified_nodes(root)
    before_text_tail = {
        identifier: (node.text or "", node.tail or "")
        for identifier, node in before.items()
    }
    file_desc = root.find(f"{TEI_TAG}teiHeader/{TEI_TAG}fileDesc")
    notes_stmt = file_desc.find(TEI_TAG + "notesStmt") if file_desc is not None else None
    if notes_stmt is None:
        raise ValueError("LIB-030 candidate has no work-local header notesStmt")
    original_carrier_positions = {
        spec["xml_id"]: before[spec["source_parent_id"]].index(before[spec["xml_id"]])
        for spec in _ENVELOPE_CARRIERS
        if spec["xml_id"] in before and spec["source_parent_id"] in before
    }
    shell_before = before.get("lib030-document-shell")
    original_prolog_positions = {
        node.get(XML_ID): shell_before.index(node)
        for node in (shell_before if shell_before is not None else ())
        if isinstance(node.tag, str)
        and etree.QName(node).localname == "note"
        and node.get("type") == "pre-root-comment"
        and node.get(XML_ID)
    }

    front = root.find(f"{TEI_TAG}text/{TEI_TAG}front")
    if front is None or root.find(f"{TEI_TAG}text/{TEI_TAG}front").get(XML_ID) != "lib030-front":
        raise ValueError("LIB-030 candidate front parent differs")
    wrapper_records: list[dict[str, Any]] = []
    for spec in _SOURCE_ENVELOPE_WRAPPERS:
        wrapper = before.get(spec["xml_id"])
        if (
            wrapper is None
            or wrapper.getparent() is not front
            or etree.QName(wrapper).localname != "div"
            or wrapper.get("type") != spec["source_type"]
            or set(wrapper.attrib) != {XML_ID, "type"}
        ):
            raise ValueError(f"LIB-030 envelope wrapper differs: {spec['xml_id']}")
        wrapper_records.append({
            "xml_id": spec["xml_id"],
            "source_type": spec["source_type"],
            "front_parent_id": front.get(XML_ID),
            "front_child_index": front.index(wrapper),
            "front_child_ordinal": front.index(wrapper) + 1,
            "destination": f"/TEI/teiHeader/fileDesc/notesStmt/note[@xml:id='{spec['xml_id']}']",
            "destination_corresp": f"#{front.get(XML_ID)}",
            "disposition": "preserved-as-envelope-support-in-header-and-excluded-from-public-text-units",
        })
    if require_complete_profile and len(front) != len(_SOURCE_ENVELOPE_WRAPPERS):
        raise ValueError("LIB-030 source front wrapper census differs")

    generated_heading_records: list[dict[str, Any]] = []
    for spec in _GENERATED_HEADINGS:
        parent = before.get(spec["parent_id"])
        if parent is None or etree.QName(parent).localname != "div" or parent.get("type") != spec["parent_type"]:
            raise ValueError(f"LIB-030 generated-heading parent differs: {spec['parent_id']}")
        matches = [
            child for child in parent
            if isinstance(child.tag, str) and etree.QName(child).localname == "head"
        ]
        if (len(matches) != 1 or parent.index(matches[0]) != 0
                or matches[0].attrib or len(matches[0])
                or (matches[0].text or "") != spec["text"]):
            raise ValueError(f"LIB-030 generated heading differs: {spec['parent_id']}")
        heading = matches[0]
        index = parent.index(heading)
        record = {
            "source_parent_id": spec["parent_id"],
            "source_parent_type": spec["parent_type"],
            "subtype": spec["subtype"],
            "source_selector": f"//*[@xml:id='{spec['parent_id']}']/tei:head[1]",
            "source_child_index": index,
            "source_child_ordinal": index + 1,
            "source_text": spec["text"],
            "text_sha256": _sha(spec["text"].encode("utf-8")),
            "tail_sha256": _sha((heading.tail or "").encode("utf-8")),
            "destination": f"/TEI/teiHeader/fileDesc/notesStmt/note[@type='generated-context'][@subtype='{spec['subtype']}']",
            "destination_corresp": f"#{spec['parent_id']}",
            "origin": "LIB-030 converter-generated context label; not source-authored ThML text",
            "disposition": "preserved-as-typed-header-context-and-excluded-from-public-prose",
        }
        heading.tag = TEI_TAG + "note"
        heading.set("type", "generated-context")
        heading.set("subtype", spec["subtype"])
        heading.set("corresp", f"#{spec['parent_id']}")
        parent.remove(heading)
        notes_stmt.append(heading)
        generated_heading_records.append(record)

    prolog_comments: list[dict[str, Any]] = []
    shell = before["lib030-document-shell"]
    comment_nodes = [
        child for child in shell
        if isinstance(child.tag, str)
        and etree.QName(child).localname == "note"
        and child.get("type") == "pre-root-comment"
    ]
    if require_complete_profile and len(comment_nodes) != 3:
        raise ValueError("LIB-030 pre-root comment census differs")
    for node in comment_nodes:
        identifier = node.get(XML_ID)
        if (
            not identifier
            or node.getparent() is not shell
            or set(node.attrib) != {XML_ID, "type", "n"}
            or len(node)
        ):
            raise ValueError("LIB-030 pre-root comment carrier differs")
        index = original_prolog_positions[identifier]
        prolog_comments.append({
            "xml_id": identifier,
            "source_parent_id": shell.get(XML_ID),
            "source_child_index": index,
            "source_child_ordinal": index + 1,
            "text_sha256": _sha((node.text or "").encode("utf-8")),
            "tail_sha256": _sha((node.tail or "").encode("utf-8")),
            "destination": f"/TEI/teiHeader/fileDesc/notesStmt/note[@xml:id='{identifier}']",
            "destination_corresp": f"#{shell.get(XML_ID)}",
            "disposition": "preserved-as-source-envelope-comment-in-header-and-excluded-from-public-prose",
        })
        node.set("corresp", f"#{shell.get(XML_ID)}")
        shell.remove(node)
        notes_stmt.append(node)

    carrier_records: list[dict[str, Any]] = []
    source_positions = original_carrier_positions
    for spec in _ENVELOPE_CARRIERS:
        node = before.get(spec["xml_id"])
        parent = before.get(spec["source_parent_id"])
        if (node is None or parent is None or node.getparent() is not parent
                or etree.QName(node).localname != "ab"
                or node.get("type") != spec["source_type"]
                or set(node.attrib) != {XML_ID, "type"}
                or len(node) or not node.text
                or etree.QName(parent).localname != spec["source_parent_tag"]
                or parent.get("type") != spec["source_parent_type"]):
            raise ValueError(f"LIB-030 machine carrier differs: {spec['xml_id']}")
        parent_index = source_positions[spec["xml_id"]]
        record = {
            **spec,
            "source_selector": f"//*[@xml:id='{spec['xml_id']}']",
            "source_parent_selector": f"//*[@xml:id='{spec['source_parent_id']}']",
            "source_child_index": parent_index,
            "source_child_ordinal": parent_index + 1,
            "text_bytes": len(node.text.encode("utf-8")),
            "text_sha256": _sha(node.text.encode("utf-8")),
            "tail_sha256": _sha((node.tail or "").encode("utf-8")),
            "destination": f"/TEI/teiHeader/fileDesc/notesStmt/note[@xml:id='{spec['xml_id']}']",
            "destination_corresp": f"#{spec['source_parent_id']}",
            "disposition": "preserved-in-header-and-excluded-from-public-prose",
            "notice_owner": "sources/devotionals/spurgeons-morning-evening/README.source.md; future public-notice owner is build/tools/prepare_spurgeon_ccel_public_notice.py",
        }
        carrier_records.append(record)
        node.tag = TEI_TAG + "note"
        node.set("type", spec["destination_type"])
        node.set("corresp", f"#{spec['source_parent_id']}")
        parent.remove(node)
        notes_stmt.append(node)

    for record in wrapper_records:
        wrapper = before[record["xml_id"]]
        wrapper.tag = TEI_TAG + "note"
        wrapper.set("type", "source-envelope-support")
        wrapper.set("subtype", record["source_type"])
        wrapper.set("corresp", record["destination_corresp"])
        front.remove(wrapper)
        notes_stmt.append(wrapper)

    day_markers = root.xpath("//t:milestone[@unit='DayOfYear']", namespaces=NS)
    scripture_markers = root.xpath("//t:milestone[@unit='scripture-comment']", namespaces=NS)
    expected_marker_counts = {"DayOfYear": 369, "scripture-comment": 736}
    if require_complete_profile:
        if (len(day_markers) != expected_marker_counts["DayOfYear"]
                or len(scripture_markers) != expected_marker_counts["scripture-comment"]):
            raise ValueError("LIB-030 source marker census differs")
    elif not day_markers or not scripture_markers:
        raise ValueError("LIB-030 source marker fixture must include each adapted marker kind")
    for node in day_markers:
        if (len(node) or (node.text or "").strip() or not node.get(XML_ID)
                or not node.get("n") or node.get("ana") is not None):
            raise ValueError("LIB-030 DayOfYear source marker differs")
        node.set("unit", "source-text-break")
        node.set("ana", "urn:ocd:lib030:source-unit:DayOfYear")
    for node in scripture_markers:
        if (len(node) or (node.text or "").strip() or not node.get(XML_ID)
                or node.get("type") != "scripture-comment"):
            raise ValueError("LIB-030 scripture-comment source marker differs")
        node.set("unit", "scripCom")

    indices = root.xpath("//t:index[@indexName='scripRef' or @indexName='scripCom']", namespaces=NS)
    index_counts = {name: sum(node.get("indexName") == name for node in indices)
                    for name in ("scripRef", "scripCom")}
    if require_complete_profile and index_counts != {"scripRef": 1, "scripCom": 1}:
        raise ValueError("LIB-030 source index census differs")
    for node in indices:
        source_name = node.get("indexName")
        identifier = node.get(XML_ID)
        if (source_name not in {"scripRef", "scripCom"} or not identifier
                or set(node.attrib) != {XML_ID, "indexName"} or len(node)
                or (node.text or "").strip()):
            raise ValueError("LIB-030 generated source index differs")
        node.tag = TEI_TAG + "anchor"
        del node.attrib["indexName"]
        node.set("type", "source-index-" + source_name)

    after = _identified_nodes(root)
    if set(before) != set(after):
        raise ValueError("LIB-030 adapter changed the TEI identifier inventory")
    for identifier, old_text_tail in before_text_tail.items():
        new = after[identifier]
        if old_text_tail != (new.text or "", new.tail or ""):
            raise ValueError(f"LIB-030 adapter changed source text/tail for {identifier}")
    adapted_tree = _tree_bytes(root)
    reverse_root = etree.fromstring(adapted_tree, parser)
    _reverse_adapter(
        reverse_root,
        carrier_records,
        generated_heading_records,
        prolog_comments,
        wrapper_records,
    )
    if _tree_bytes(reverse_root) != _tree_bytes(etree.fromstring(original, parser)):
        raise ValueError("LIB-030 adapter inverse did not recover the complete source TEI tree")

    adapted = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    receipt = {
        "contract": CONTRACT,
        "status": "adapted-losslessly-for-current-native-prose-policy",
        "original_tei_sha256": original_sha,
        "adapted_tei_sha256": _sha(adapted),
        "adapted_tei_bytes": len(adapted),
        "complete_tree_inverse_check": "pass",
        "identifier_inventory_preserved": True,
        "ordered_text_and_tail_by_xml_id_preserved": True,
        "category": "prose",
        "envelope_carriers": carrier_records,
        "generated_context_headings": generated_heading_records,
        "prolog_comments": prolog_comments,
        "source_envelope_wrappers": wrapper_records,
        "source_markers": {
            "DayOfYear": {
                "count": len(day_markers),
                "selector": "//tei:milestone[@unit='DayOfYear']",
                "map": {"unit": "source-text-break", "ana": "urn:ocd:lib030:source-unit:DayOfYear"},
                "preserved_fields": ["xml:id", "n", "text", "tail", "source parent and order"],
                "meaning": "source-specific DayOfYear unit remains explicit in the source_annotations value",
            },
            "scripture-comment": {
                "count": len(scripture_markers),
                "selector": "//tei:milestone[@unit='scripture-comment']",
                "map": {"unit": "scripCom"},
                "preserved_fields": ["xml:id", "type", "subtype", "n", "corresp", "text", "tail", "source parent and order"],
            },
        },
        "empty_source_indices": {
            "selector": "//tei:index[@indexName='scripRef' or @indexName='scripCom']",
            "counts": index_counts,
            "map": "anchor[@type='source-index-{original indexName}']",
            "preserved_fields": ["xml:id", "source parent and order", "empty-content role"],
        },
        "disclosure": {
            "source_header_and_contacts": "The exact ThML head transcription remains preserved in the bound TEI header, outside native public prose rows.",
            "attribution_and_editorial_context": "Existing structured source-description, source-editorial-history, and source-revision-history notes remain in the TEI header; the exact header transcription is also preserved as source-envelope-thml-header.",
            "personal_contact_disposition": "Do not copy personal contact details from the retained electronic header into the public notice.",
            "notice_evidence": "sources/devotionals/spurgeons-morning-evening/README.source.md",
            "future_public_notice_tool": "build/tools/prepare_spurgeon_ccel_public_notice.py",
            "rights_or_publication_authorized": False,
        },
    }
    return adapted, receipt

