"""Work-specific, source-bound ThML-to-TEI producer for HCC4."""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


WORK_ID = "schaff-history-vol-4"
SOURCE_ID = "ccel-schaff-hcc4-thml"
CONVERTER_ID = "schaff-history-vol-4-thml-producer"
CONVERTER_VERSION = "1"
PROFILE_NAME = "reconstruction-profile"
POLICY_NAME = "validation-policy"
ACCOUNTABILITY_SCHEMA_NAME = "source-accountability-schema"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
_PROFILE_PATH = Path(
    "sources/structured-text/schaff-history-vol-4-readable/"
    "schaff-history-vol-4.reconstruction-profile.json"
)
_XML_DECLARATION = re.compile(rb"\s*(<\?xml[^?]*\?>)")
_DIVISION_TAGS = ("div", "div1", "div2", "div3", "div4", "div5", "div6")
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _serialize_tei(tree: etree._ElementTree) -> bytes:
    declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    return declaration + etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=False,
        pretty_print=False,
    )


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _read_authority_json(source_manifest: SourceManifest, name: str) -> dict[str, object]:
    return _strict_json(source_manifest.authority_path(name).read_bytes(), name)


def _parse_source(source_bytes: bytes) -> etree._ElementTree:
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
        return etree.parse(BytesIO(source_bytes), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"retained HCC4 source is not well-formed XML: {exc}") from exc


def _local_name(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("non-element source node was not explicitly accounted")
    return etree.QName(node).localname


def _source_nodes(root: etree._Element) -> list[etree._Element]:
    nodes: list[etree._Element] = []
    for node in root.iter():
        if not isinstance(node.tag, str):
            raise ValueError("source contains an in-root comment, PI, or entity node")
        nodes.append(node)
    return nodes


def _source_index(
    root: etree._Element,
) -> tuple[list[etree._Element], dict[etree._Element, dict[str, object]]]:
    nodes = _source_nodes(root)
    index: dict[etree._Element, dict[str, object]] = {}
    for number, node in enumerate(nodes, 1):
        parent = node.getparent()
        parent_key = index[parent]["source_key"] if parent is not None else None
        ordinal = 1
        if parent is not None:
            for sibling in parent:
                if sibling is node:
                    break
                if isinstance(sibling.tag, str):
                    ordinal += 1
        index[node] = {
            "source_key": f"hcc4-n{number:06d}",
            "parent_key": parent_key,
            "ordinal": ordinal,
        }
    return nodes, index


def _top_level_siblings(
    root: etree._Element, *, before: bool
) -> list[etree._Element]:
    if before:
        first = root
        while first.getprevious() is not None:
            first = first.getprevious()
        result: list[etree._Element] = []
        node = first
        while node is not root:
            result.append(node)
            node = node.getnext()
        return result
    result = []
    node = root.getnext()
    while node is not None:
        result.append(node)
        node = node.getnext()
    return result


def _tag_counts(nodes: list[etree._Element]) -> Counter[str]:
    return Counter(_local_name(node) for node in nodes)


def _profiled_inputs(
    source_manifest: SourceManifest,
) -> tuple[bytes, dict[str, object], dict[str, object], etree._ElementTree]:
    source_manifest.verify()
    profile = _read_authority_json(source_manifest, PROFILE_NAME)
    policy = _read_authority_json(source_manifest, POLICY_NAME)
    source_bytes = source_manifest.authority_path("primary-source").read_bytes()
    primary = profile.get("primary_source")
    if not isinstance(primary, dict):
        raise ValueError("HCC4 profile has no primary-source identity")
    if (
        profile.get("work_id") != WORK_ID
        or profile.get("source_id") != SOURCE_ID
        or source_manifest.record.get("work_id") != WORK_ID
        or source_manifest.record.get("source_id") != SOURCE_ID
        or primary.get("path") != "raw/ccel/schaff/hcc4.xml"
        or primary.get("bytes") != len(source_bytes)
        or primary.get("sha256") != _sha(source_bytes)
        or policy.get("source_sha256") != _sha(source_bytes)
        or policy.get("work_id") != WORK_ID
    ):
        raise ValueError("HCC4 source identity or byte binding drifted")
    tree = _parse_source(source_bytes)
    root = tree.getroot()
    nodes, _index = _source_index(root)
    counts = _tag_counts(nodes)
    division_counts = {name: counts.get(name, 0) for name in _DIVISION_TAGS}
    heading_counts = {name: counts.get(name, 0) for name in _HEADING_TAGS}
    if (
        division_counts != profile.get("division_counts")
        or heading_counts != profile.get("heading_counts")
        or division_counts != policy.get("six_division_and_heading_envelope", {}).get("expected_divisions")
        or heading_counts != policy.get("six_division_and_heading_envelope", {}).get("expected_headings")
    ):
        raise ValueError("HCC4 six-division/h1-h6 envelope drifted")
    return source_bytes, profile, policy, tree


def _tei_name(source_name: str) -> str:
    if source_name == "ThML.body":
        return "body"
    if source_name in _DIVISION_TAGS:
        return "div"
    if source_name in _HEADING_TAGS:
        return "head"
    return {
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
    }.get(source_name, "seg")


def _apply_tei_semantics(
    target: etree._Element, source: etree._Element, source_name: str
) -> None:
    source_type = source.get("type")
    source_class = source.get("class")
    if source_class:
        target.set("rend", source_class)

    if source_name in _DIVISION_TAGS:
        target.set("type", f"ThML-{source_name}")
        if source_type:
            target.set("subtype", source_type)
        title = source.get("title")
        if title:
            target.set("n", title)
        elif source.get("n"):
            target.set("n", source.get("n"))
    elif source_name in _HEADING_TAGS:
        target.set("type", f"source-{source_name}")
    elif source_name == "i":
        target.set("rend", source_class or "italic")
    elif source_name == "note":
        target.set("type", source_type or "ThML-note")
        if source.get("place"):
            target.set("place", source.get("place"))
        if source.get("n"):
            target.set("n", source.get("n"))
    elif source_name == "scripRef":
        target.set("type", "scripture-reference")
        target.set("target", source.get("osisRef") or source.get("passage") or "")
    elif source_name == "a":
        target.set("type", "ThML-link")
        if source.get("href"):
            target.set("target", source.get("href"))
    elif source_name == "verse":
        target.set("type", source_type or "ThML-verse")
    elif source_name == "ul":
        target.set("type", "unordered")
    elif source_name == "index":
        if source_type:
            target.set("indexName", source_type)
        if source.get("subject1"):
            target.set("n", source.get("subject1"))
    elif source_name == "insertIndex":
        target.set("type", source_type or "ThML-insertIndex")
    elif source_name == "ThML.head":
        target.set("type", "retained-ThML-header")
    elif etree.QName(target).localname == "seg":
        target.set("type", f"ThML-{source_name}")
    elif source_type and etree.QName(target).localname in {"l", "item", "anchor"}:
        target.set("type", source_type)


def _mapped_source_element(
    source: etree._Element,
    index: Mapping[etree._Element, Mapping[str, object]],
    *,
    tei_root: bool = False,
) -> etree._Element:
    source_name = _local_name(source)
    tei_name = "TEI" if tei_root else _tei_name(source_name)
    target = etree.Element(
        f"{{{TEI_NS}}}{tei_name}",
        nsmap={None: TEI_NS} if tei_root else None,
    )
    location = index[source]
    source_key = str(location["source_key"])
    original_id = source.get("id")
    target.set(f"{{{XML_NS}}}id", original_id or f"hcc4-generated-{source_key[6:]}")
    if not tei_root:
        _apply_tei_semantics(target, source, source_name)
    target.text = source.text
    if not tei_root:
        source_children = [child for child in source if isinstance(child.tag, str)]
        is_division = source_name in _DIVISION_TAGS
        saw_division_child = False
        offset = 0
        while offset < len(source_children):
            child = source_children[offset]
            child_name = _local_name(child)
            if is_division and saw_division_child and child_name not in _DIVISION_TAGS:
                wrapper = etree.SubElement(
                    target,
                    f"{{{TEI_NS}}}div",
                    type="source-order-wrapper",
                )
                while (
                    offset < len(source_children)
                    and _local_name(source_children[offset]) not in _DIVISION_TAGS
                ):
                    wrapped_source = source_children[offset]
                    mapped_child = _mapped_source_element(wrapped_source, index)
                    mapped_child.tail = wrapped_source.tail
                    wrapper.append(mapped_child)
                    offset += 1
                continue
            mapped_child = _mapped_source_element(child, index)
            mapped_child.tail = child.tail
            target.append(mapped_child)
            if is_division and child_name in _DIVISION_TAGS:
                saw_division_child = True
            offset += 1
    target.tail = source.tail
    return target


def _append_source_projection_records(
    tei_root: etree._Element,
    source_nodes: list[etree._Element],
    index: Mapping[etree._Element, Mapping[str, object]],
) -> None:
    stand_off = etree.SubElement(tei_root, f"{{{TEI_NS}}}standOff")
    projection = etree.SubElement(
        stand_off,
        f"{{{TEI_NS}}}list",
        type="source-projection",
    )
    for source in source_nodes:
        location = index[source]
        source_key = str(location["source_key"])
        content_id = source.get("id") or f"hcc4-generated-{source_key[6:]}"
        item = etree.SubElement(
            projection,
            f"{{{TEI_NS}}}item",
            n=source_key,
            corresp=f"#{content_id}",
        )
        item.text = json.dumps(
            {
                "source_key": source_key,
                "source_element": _local_name(source),
                "source_attributes": list(source.attrib.items()),
                "source_parent_key": str(location["parent_key"] or ""),
                "source_ordinal": location["ordinal"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def _metadata_values(source_root: etree._Element) -> tuple[list[str], list[str], str]:
    titles = [
        "".join(node.itertext())
        for node in source_root.xpath("./ThML.head/electronicEdInfo/DC/DC.Title")
    ]
    authors = [
        "".join(node.itertext())
        for node in source_root.xpath("./ThML.head/electronicEdInfo/DC/DC.Creator")
    ]
    rights = source_root.xpath("./ThML.head/electronicEdInfo/DC/DC.Rights")
    if len(titles) != 2 or len(authors) != 2 or len(rights) != 1:
        raise ValueError("HCC4 retained title, creator, or rights header changed")
    return titles, authors, "".join(rights[0].itertext())


def _put_text(parent: etree._Element, name: str, value: str, **attributes: str) -> etree._Element:
    node = etree.SubElement(parent, f"{{{TEI_NS}}}{name}")
    for key, item in attributes.items():
        node.set(key, item)
    node.text = value
    return node


def _build_tei_tree(
    source_tree: etree._ElementTree,
    profile: Mapping[str, object],
) -> etree._ElementTree:
    source_root = source_tree.getroot()
    source_nodes, source_index = _source_index(source_root)
    if _local_name(source_root) != "ThML":
        raise ValueError("HCC4 root element is not ThML")
    root_children = [_local_name(child) for child in source_root if isinstance(child.tag, str)]
    expected_children = profile["source_envelope"]["root_children_in_order"]
    if root_children != expected_children:
        raise ValueError("HCC4 root head/body envelope changed")

    body = source_root.find("./ThML.body")
    if body is None:
        raise ValueError("HCC4 source body is missing")
    body_roots = [child for child in body if isinstance(child.tag, str)]
    expected_roots = profile["selection"]["selected_body_roots"]
    observed_roots = [
        {"tag": _local_name(node), "id": node.get("id"), "ordinal": ordinal, "title": node.get("title")}
        for ordinal, node in enumerate(body_roots, 1)
    ]
    if observed_roots != expected_roots:
        raise ValueError("HCC4 complete body-member selection changed")

    titles, authors, rights = _metadata_values(source_root)
    if rights != "":
        raise ValueError("HCC4 source rights evidence changed; human review is required")
    tei_root = _mapped_source_element(source_root, source_index, tei_root=True)

    header = etree.SubElement(tei_root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    _put_text(title_stmt, "title", titles[0], type="main")
    _put_text(title_stmt, "title", titles[1], type="alternative")
    _put_text(title_stmt, "author", authors[0])
    _put_text(title_stmt, "author", authors[1])

    publication_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    _put_text(
        publication_stmt,
        "p",
        "Nonaccepted reconstruction candidate; publication is not authorized. The retained DC.Rights "
        "element is empty; rights and license status remain unresolved.",
    )

    notes_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}notesStmt")
    doctype_note = etree.SubElement(
        notes_stmt,
        f"{{{TEI_NS}}}note",
        type="source-doctype",
    )
    doctype_note.text = source_tree.docinfo.doctype or ""
    head = source_root.find("./ThML.head")
    if head is None:
        raise ValueError("HCC4 source header is missing")
    header_note = etree.SubElement(
        notes_stmt,
        f"{{{TEI_NS}}}note",
        type="retained-ThML-header",
    )
    header_paragraph = etree.SubElement(header_note, f"{{{TEI_NS}}}p")
    mapped_head = _mapped_source_element(head, source_index)
    mapped_head.tail = head.tail
    header_paragraph.append(mapped_head)

    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    source_note = etree.SubElement(source_desc, f"{{{TEI_NS}}}p")
    source_note.text = (
        "Retained source member raw/ccel/schaff/hcc4.xml; its source bookID/workID is hcc4. "
        "LIB-058 maps this member to schaff-history-vol-4. The exact source bytes are bound "
        "by the source manifest; print-edition identity remains unresolved."
    )

    encoding_desc = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project_desc = etree.SubElement(encoding_desc, f"{{{TEI_NS}}}projectDesc")
    _put_text(
        project_desc,
        "p",
        "Source elements and mixed text are projected into TEI. An xml:id-linked standOff list records each source key, local name, ordered attributes, parent key, and ordinal. "
        "Marked source-order wrappers satisfy TEI P5 content ordering without changing source order or text. "
        "Retained stylesheet declarations are source-header data, not source headings.",
    )

    text = etree.SubElement(tei_root, f"{{{TEI_NS}}}text")
    mapped_body = _mapped_source_element(body, source_index)
    mapped_body.tail = body.tail
    text.append(mapped_body)
    _append_source_projection_records(tei_root, source_nodes, source_index)

    leading = _top_level_siblings(source_root, before=True)
    trailing = _top_level_siblings(source_root, before=False)
    if trailing or any(not isinstance(node, etree._Comment) for node in leading):
        raise ValueError("HCC4 prolog/epilog contains an unaccounted non-comment node")
    for comment in leading:
        copied = etree.Comment(comment.text or "")
        copied.tail = comment.tail
        tei_root.addprevious(copied)
    return tei_root.getroottree()


def _source_carrier_rows(
    source_root: etree._Element,
    index: Mapping[etree._Element, Mapping[str, object]],
    accepted_tags: tuple[str, ...],
) -> list[dict[str, object]]:
    rows = []
    for node in source_root.iter():
        if not isinstance(node.tag, str):
            continue
        tag = _local_name(node)
        if tag not in accepted_tags:
            continue
        location = index[node]
        rows.append(
            {
                "source_key": location["source_key"],
                "tag": tag,
                "id": node.get("id"),
                "parent_key": location["parent_key"],
                "ordinal": location["ordinal"],
                "type": node.get("type"),
                "title": node.get("title"),
            }
        )
    return rows


def _accountability_record(
    source_manifest: SourceManifest,
    source_bytes: bytes,
    profile: Mapping[str, object],
    source_tree: etree._ElementTree,
) -> dict[str, object]:
    root = source_tree.getroot()
    nodes, index = _source_index(root)
    counts = _tag_counts(nodes)
    comments = _top_level_siblings(root, before=True)
    if any(not isinstance(node, etree._Comment) for node in comments):
        raise ValueError("HCC4 source prolog comment accounting is incomplete")
    top_comments = [
        {
            "ordinal": ordinal,
            "sha256": _sha((node.text or "").encode("utf-8")),
            "characters": len(node.text or ""),
        }
        for ordinal, node in enumerate(comments, 1)
    ]
    division_counts = {name: counts.get(name, 0) for name in _DIVISION_TAGS}
    heading_counts = {name: counts.get(name, 0) for name in _HEADING_TAGS}
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
            "included_body_div1_ids": [node.get("id") for node in root.xpath("./ThML.body/div1")],
            "excluded_body_division_ids": [],
        },
        "envelope": {
            "xml_version": source_tree.docinfo.xml_version,
            "encoding": source_tree.docinfo.encoding,
            "doctype": source_tree.docinfo.doctype or "",
            "external_dtd_loaded": False,
            "top_level_comments": top_comments,
            "active_processing_instructions": 0,
            "root_element": _local_name(root),
            "root_children_in_order": [_local_name(node) for node in root if isinstance(node.tag, str)],
            "source_head_disposition": "represented_in_TEI_header",
            "source_body_disposition": "represented_in_TEI_text_body",
        },
        "source_element_count": len(nodes),
        "represented_element_count": len(nodes),
        "omitted_element_count": 0,
        "duplicate_element_count": 0,
        "division_counts": division_counts,
        "heading_counts": heading_counts,
        "division_carriers": _source_carrier_rows(root, index, _DIVISION_TAGS),
        "heading_carriers": _source_carrier_rows(root, index, _HEADING_TAGS),
        "rights_status": "unresolved",
        "legacy_config_used_as_authority": False,
        "profile_id": profile.get("profile_id"),
        "source_manifest_sha256": source_manifest.sha256,
    }


def _unresolved_records() -> bytes:
    records = (
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
    )
    return b"".join(_canonical(record) for record in records)


def _provenance_record(
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


def _build_tei(source_manifest: SourceManifest) -> bytes:
    """Return deterministic TEI bytes in memory; write no candidate artifacts."""

    source_bytes, profile, _policy, source_tree = _profiled_inputs(source_manifest)
    tree = _build_tei_tree(source_tree, profile)
    return _serialize_tei(tree)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    """Return the five future candidate member byte strings without writing them."""

    source_bytes, profile, _policy, source_tree = _profiled_inputs(source_manifest)
    tei_bytes = _serialize_tei(_build_tei_tree(source_tree, profile))
    accountability = _accountability_record(
        source_manifest, source_bytes, profile, source_tree
    )
    readme = (
        "# Source note\n\n"
        "Retained source: `raw/ccel/schaff/hcc4.xml` (ThML; source bookID/workID `hcc4`). "
        "The retained header identifies the Electronic Bible Society and Christian Classics "
        "Ethereal Library. Its `DC.Rights` element is empty; no license or public-domain "
        "status is inferred. This reconstruction is nonaccepted and not publication-ready.\n"
    ).encode("utf-8")
    return {
        "README.source.md": readme,
        "content.tei.xml": tei_bytes,
        "provenance.json": _canonical(
            _provenance_record(source_manifest, profile, source_bytes)
        ),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": _unresolved_records(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
