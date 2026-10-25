"""Reconstruct the complete retained LIB-030 CCEL ThML document as TEI."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import stamp_header, tei_el


CONVERTER_ID = "ocd-lib030-ccel-thml-cohort-to-tei"
CONVERTER_VERSION = "3"
SOURCE_SET_AUTHORITY = "retained-source-set"
PROFILE_AUTHORITY = "reconstruction-profile"
ATTRIBUTION_AUTHORITY = "source-attribution"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
BODY_TAGS = frozenset(
    {
        "ThML.body", "a", "div", "div1", "div2", "h1", "h2", "h3",
        "hr", "i", "insertIndex", "l", "p", "scripCom", "scripRef",
        "span", "sync", "verse",
    }
)
EXPECTED_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
EXPECTED_DOCTYPE = (
    '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" '
    '"http://www.ccel.org/dtd/ThML10.dtd">'
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, Any]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _authority_json(source_manifest: SourceManifest, name: str) -> dict[str, Any]:
    return _strict_json(source_manifest.authority_path(name).read_bytes(), name)


def _retained_root(source_manifest: SourceManifest) -> Path:
    configured = os.environ.get("OCD_RETAINED_RAW_ROOT", "").strip()
    root = Path(configured) if configured else source_manifest.repository_root / "raw"
    return root.resolve(strict=True)


def _retained_members(source_manifest: SourceManifest) -> tuple[dict[str, Any], ...]:
    source_set = _authority_json(source_manifest, SOURCE_SET_AUTHORITY)
    profile = _authority_json(source_manifest, PROFILE_AUTHORITY)
    members = source_set.get("members")
    work_order = profile.get("work_order")
    if source_set.get("contract") != "ocd-retained-source-set-v1":
        raise ValueError("LIB-030 retained source-set contract drifted")
    if (
        not isinstance(members, list)
        or not isinstance(work_order, list)
        or len(members) != len(work_order)
        or any(not isinstance(item, dict) for item in members)
    ):
        raise ValueError("LIB-030 source member accounting is incomplete")
    root = _retained_root(source_manifest)
    result: list[dict[str, Any]] = []
    for expected_work_id, raw in zip(work_order, members, strict=True):
        if not isinstance(expected_work_id, str) or raw.get("work_id") != expected_work_id:
            raise ValueError("LIB-030 source member order or identity drifted")
        logical_path = raw.get("logical_path")
        expected_bytes = raw.get("bytes")
        expected_sha = raw.get("sha256")
        if (
            not isinstance(logical_path, str)
            or not isinstance(expected_bytes, int)
            or not isinstance(expected_sha, str)
        ):
            raise ValueError("LIB-030 source member record is invalid")
        path = (root / logical_path).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("LIB-030 source member escaped retained raw root") from exc
        content = path.read_bytes()
        if len(content) != expected_bytes or _sha(content) != expected_sha:
            raise ValueError(f"LIB-030 retained source drifted: {logical_path}")
        result.append({**raw, "resolved_path": path, "content": content})
    return tuple(result)


def _parse(content: bytes) -> etree._ElementTree:
    try:
        return etree.parse(
            io.BytesIO(content),
            etree.XMLParser(
                resolve_entities=False, no_network=True, remove_comments=False,
                remove_pis=False, huge_tree=True, recover=False, strip_cdata=False,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-030 retained XML is not parseable") from exc


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _node_kind(node: etree._Element) -> str:
    if node.tag is etree.Comment:
        return "comment"
    if node.tag is etree.PI:
        return "processing-instruction"
    if isinstance(node.tag, str):
        return "element"
    raise ValueError("LIB-030 retained XML contains an unsupported node kind")


def _document_nodes(tree: etree._ElementTree) -> list[tuple[str, etree._Element]]:
    root = tree.getroot()
    before: list[etree._Element] = []
    current = root.getprevious()
    while current is not None:
        before.append(current)
        current = current.getprevious()
    after: list[etree._Element] = []
    current = root.getnext()
    while current is not None:
        after.append(current)
        current = current.getnext()
    result = [("pre-root", node) for node in reversed(before)]

    def walk(node: etree._Element) -> None:
        result.append(("tree", node))
        for child in node:
            walk(child)

    walk(root)
    result.extend(("post-root", node) for node in after)
    return result


def _same_source_kind(left: etree._Element, right: etree._Element) -> bool:
    left_kind = _node_kind(left)
    right_kind = _node_kind(right)
    if left_kind != right_kind:
        return False
    if left_kind == "element":
        return str(left.tag) == str(right.tag)
    if left_kind == "processing-instruction":
        return left.target == right.target
    return True


def _source_selector(
    node: etree._Element,
    scope: str,
    pre_nodes: list[etree._Element],
    post_nodes: list[etree._Element],
) -> str:
    if scope != "tree":
        peers = pre_nodes if scope == "pre-root" else post_nodes
        same = [item for item in peers if _same_source_kind(item, node)]
        label = "comment" if _node_kind(node) == "comment" else "processing-instruction"
        return f"/{scope}/{label}()[{same.index(node) + 1}]"
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        parent = current.getparent()
        peers = [current] if parent is None else [
            item for item in parent if _same_source_kind(item, current)
        ]
        kind = _node_kind(current)
        label = _local(current) if kind == "element" else (
            "#comment" if kind == "comment" else f"?{current.target}"
        )
        parts.append(f"{label}[{peers.index(current) + 1}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _node_records(
    tree: etree._ElementTree,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    scoped = _document_nodes(tree)
    pre_nodes = [node for scope, node in scoped if scope == "pre-root"]
    post_nodes = [node for scope, node in scoped if scope == "post-root"]
    selectors = [
        _source_selector(node, scope, pre_nodes, post_nodes)
        for scope, node in scoped
    ]
    ordinals = {selector: ordinal for ordinal, selector in enumerate(selectors, 1)}
    rows: list[dict[str, Any]] = []
    by_selector: dict[str, dict[str, Any]] = {}
    for ordinal, ((scope, node), selector) in enumerate(zip(scoped, selectors, strict=True), 1):
        parent = node.getparent()
        siblings = list(parent) if parent is not None else [node]
        kind = _node_kind(node)
        base: dict[str, Any] = {
            "feature_id": f"lib030-node-{ordinal:06d}",
            "ordinal": ordinal,
            "scope": scope,
            "kind": kind,
            "source_selector": selector,
            "qname": str(node.tag) if kind == "element" else None,
            "source_tag": _local(node) if kind == "element" else (
                "#comment" if kind == "comment" else "#pi"
            ),
            "pi_target": node.target if kind == "processing-instruction" else None,
            "attributes": (
                [[str(name), value] for name, value in node.attrib.items()]
                if kind == "element" else []
            ),
            "namespace_declarations": (
                [["" if name is None else name, value] for name, value in node.nsmap.items()]
                if kind == "element" else []
            ),
            "direct_text": node.text or "",
            "tail_text": node.tail or "",
            "parent_feature_id": (
                f"lib030-node-{ordinals[_source_selector(parent, 'tree', [], [])]:06d}"
                if parent is not None else None
            ),
            "sibling_ordinal": siblings.index(node) + 1,
        }
        base["source_payload_sha256"] = _sha(_canonical(base))
        rows.append(base)
        by_selector[selector] = base
    return rows, by_selector


def _doctype_end(content: bytes, start: int) -> int:
    quote: int | None = None
    subset_depth = 0
    for index in range(start, len(content)):
        value = content[index]
        if quote is not None:
            if value == quote:
                quote = None
            continue
        if value in (34, 39):
            quote = value
        elif value == 91:
            subset_depth += 1
        elif value == 93 and subset_depth:
            subset_depth -= 1
        elif value == 62 and subset_depth == 0:
            return index + 1
    raise ValueError("LIB-030 retained source has an unterminated doctype")


def _envelope_carrier(
    kind: str, ordinal: int, start: int, end: int, content: bytes
) -> dict[str, Any]:
    payload = content[start:end]
    return {
        "carrier_id": f"lib030-envelope-{ordinal:03d}",
        "ordinal": ordinal,
        "kind": kind,
        "start": start,
        "end": end,
        "bytes": len(payload),
        "sha256": _sha(payload),
        "text": payload.decode("utf-8"),
    }


def _scan_envelope(content: bytes) -> dict[str, Any]:
    root_match = re.search(rb"<ThML(?:\s|>)", content)
    root_close = content.rfind(b"</ThML>")
    if root_match is None or root_close < root_match.start():
        raise ValueError("LIB-030 retained source root boundary is invalid")
    root_start = root_match.start()
    root_end = root_close + len(b"</ThML>")
    carriers: list[dict[str, Any]] = []
    position = 0
    ordinal = 0
    while position < root_start:
        ordinal += 1
        if content.startswith(b"<?xml", position):
            found = content.find(b"?>", position)
            end = found + 2
            kind = "xml-declaration"
        elif content.startswith(b"<!DOCTYPE", position):
            end = _doctype_end(content, position)
            kind = "doctype"
        elif content.startswith(b"<!--", position):
            found = content.find(b"-->", position)
            end = found + 3
            kind = "comment"
        elif content.startswith(b"<?", position):
            found = content.find(b"?>", position)
            end = found + 2
            kind = "processing-instruction"
        elif content[position] in b" \t\r\n":
            end = position + 1
            while end < root_start and content[end] in b" \t\r\n":
                end += 1
            kind = "padding"
        else:
            raise ValueError(f"LIB-030 unsupported pre-root bytes at offset {position}")
        if end <= position or end > root_start:
            raise ValueError("LIB-030 pre-root carrier boundary is invalid")
        carriers.append(_envelope_carrier(kind, ordinal, position, end, content))
        position = end
    position = root_end
    while position < len(content):
        ordinal += 1
        if content[position] not in b" \t\r\n":
            raise ValueError(f"LIB-030 unsupported post-root bytes at offset {position}")
        end = position + 1
        while end < len(content) and content[end] in b" \t\r\n":
            end += 1
        carriers.append(_envelope_carrier("padding", ordinal, position, end, content))
        position = end
    declaration = next((row for row in carriers if row["kind"] == "xml-declaration"), None)
    doctype = next((row for row in carriers if row["kind"] == "doctype"), None)
    if declaration is None or declaration["text"] != EXPECTED_XML_DECLARATION:
        raise ValueError("LIB-030 XML declaration drifted")
    if doctype is None:
        raise ValueError("LIB-030 retained source has no doctype")
    return {
        "encoding": "UTF-8",
        "xml_version": "1.0",
        "root_start": root_start,
        "root_end": root_end,
        "regions": {
            "pre_root": {"bytes": root_start, "sha256": _sha(content[:root_start])},
            "root": {"bytes": root_end - root_start, "sha256": _sha(content[root_start:root_end])},
            "post_root": {"bytes": len(content) - root_end, "sha256": _sha(content[root_end:])},
        },
        "carriers": carriers,
        "carrier_count": len(carriers),
        "covered_bytes": len(content),
    }


def _first_element(tree: etree._ElementTree, expression: str) -> etree._Element | None:
    values = tree.xpath(expression)
    return values[0] if values and isinstance(values[0], etree._Element) else None


def _element_text(node: etree._Element | None) -> str:
    return "" if node is None else "".join(node.itertext())


def _metadata(tree: etree._ElementTree) -> dict[str, Any]:
    def elements(expression: str) -> list[etree._Element]:
        return [node for node in tree.xpath(expression) if isinstance(node, etree._Element)]

    head = _first_element(tree, "/ThML/ThML.head")
    if head is None:
        raise ValueError("LIB-030 retained source has no ThML.head")

    def field(expression: str) -> str:
        return _element_text(_first_element(tree, expression))

    return {
        "title": field("/ThML/ThML.head/title"),
        "description": field("/ThML/ThML.head/generalInfo/description"),
        "publisher": field("/ThML/ThML.head/electronicEdInfo/DC/DC.Publisher"),
        "contributor": field("/ThML/ThML.head/electronicEdInfo/DC/DC.Contributor"),
        "date": field("/ThML/ThML.head/electronicEdInfo/DC/DC.Date"),
        "dc_type": field("/ThML/ThML.head/electronicEdInfo/DC/DC.Type"),
        "format": field("/ThML/ThML.head/electronicEdInfo/DC/DC.Format"),
        "identifier": field("/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier"),
        "language": field("/ThML/ThML.head/electronicEdInfo/DC/DC.Language"),
        "rights": field("/ThML/ThML.head/electronicEdInfo/DC/DC.Rights"),
        "version": field("/ThML/ThML.head/electronicEdInfo/version"),
        "editorial_comments": field("/ThML/ThML.head/electronicEdInfo/editorialComments"),
        "revision_history": field("/ThML/ThML.head/electronicEdInfo/revisionHistory"),
        "titles": [
            {"sub": node.get("sub"), "scheme": node.get("scheme"), "text": _element_text(node)}
            for node in elements("/ThML/ThML.head/electronicEdInfo/DC/DC.Title")
        ],
        "creators": [
            {"sub": node.get("sub"), "scheme": node.get("scheme"), "text": _element_text(node)}
            for node in elements("/ThML/ThML.head/electronicEdInfo/DC/DC.Creator")
        ],
        "subjects": [
            {"sub": node.get("sub"), "scheme": node.get("scheme"), "text": _element_text(node)}
            for node in elements("/ThML/ThML.head/electronicEdInfo/DC/DC.Subject")
        ],
        "sources": [
            {"sub": node.get("sub"), "scheme": node.get("scheme"), "text": _element_text(node)}
            for node in elements("/ThML/ThML.head/electronicEdInfo/DC/DC.Source")
        ],
        "styles": [
            {"type": node.get("type"), "text": node.text or ""}
            for node in elements("/ThML/ThML.head/style")
        ],
        "head_xml": etree.tostring(head, encoding="unicode", with_tail=False),
    }


def _work_metadata(profile: Mapping[str, Any], work_id: str) -> dict[str, Any]:
    works = profile.get("works")
    if isinstance(works, list):
        for item in works:
            if isinstance(item, dict) and item.get("work_id") == work_id:
                return item
    raise ValueError(f"LIB-030 profile has no metadata for {work_id}")


def _safe_fragment(value: str, id_targets: Mapping[str, str]) -> str:
    if value.startswith("#") and value[1:] in id_targets:
        return f"#{id_targets[value[1:]]}"
    if value in id_targets:
        return f"#{id_targets[value]}"
    return value


def _target_tag(source: etree._Element, target_parent: etree._Element) -> str:
    tag = _local(source)
    if tag not in BODY_TAGS - {"ThML.body"}:
        raise ValueError(f"LIB-030 unsupported ThML.body element: {tag}")
    if tag in {"div1", "div2"}:
        return "div"
    if tag == "div":
        return "div"
    if tag in {"h1", "h2", "h3"}:
        parent_tag = _local(target_parent)
        has_blocks = any(
            isinstance(child.tag, str) and _local(child) in {"head", "p", "div", "quote"}
            for child in target_parent
        )
        return "p" if parent_tag in {"div", "quote"} and has_blocks else (
            "head" if parent_tag == "div" else "p"
        )
    return {
        "a": "ref", "hr": "milestone", "i": "hi", "insertIndex": "index",
        "l": "l", "p": "p", "scripRef": "ref", "span": "seg",
        "scripCom": "milestone", "sync": "milestone", "verse": "lg",
    }[tag]


def _rendition(source: etree._Element) -> str | None:
    parts = []
    if source.get("class"):
        parts.append(f"class:{source.get('class')}")
    if source.get("style"):
        parts.append(f"style:{source.get('style')}")
    return "; ".join(parts) or None


def _target_attributes(
    source: etree._Element,
    target_tag: str,
    target_id: str,
    id_targets: Mapping[str, str],
) -> dict[str, str]:
    tag = _local(source)
    attrs = {"xml:id": target_id}
    rendition = _rendition(source)
    if rendition:
        attrs["rend"] = rendition
    if source.get("n"):
        attrs["n"] = source.get("n", "")
    if tag in {"div1", "div2"}:
        attrs["type"] = f"thml-{tag}"
        if source.get("prev"):
            attrs["prev"] = _safe_fragment(source.get("prev", ""), id_targets)
        if source.get("next"):
            attrs["next"] = _safe_fragment(source.get("next", ""), id_targets)
    elif tag == "div":
        attrs["type"] = {
            "Index": "index",
            "Center": "centered-front-matter",
        }.get(source.get("class", ""), "source-container")
    elif tag == "i":
        attrs["rend"] = "italic"
    elif tag == "span":
        attrs["type"] = "thml-span"
    elif tag == "a" and source.get("href"):
        attrs["target"] = _safe_fragment(source.get("href", ""), id_targets)
    elif tag == "scripRef":
        attrs["type"] = "scripture"
        if source.get("osisRef"):
            attrs["target"] = source.get("osisRef", "")
        if source.get("passage"):
            attrs["cRef"] = source.get("passage", "")
    elif tag == "scripCom":
        attrs["type"] = "scripture-comment"
        attrs["unit"] = "scripture-comment"
        if source.get("type"):
            attrs["subtype"] = source.get("type", "")
        if source.get("passage"):
            attrs["n"] = source.get("passage", "")
        if source.get("osisRef"):
            attrs["corresp"] = source.get("osisRef", "")
    elif tag == "sync":
        attrs["unit"] = source.get("type", "source-sync")
        attrs["n"] = source.get("value", "")
    elif tag == "insertIndex":
        attrs["indexName"] = source.get("type", "source-index")
    elif tag == "hr":
        attrs["unit"] = "horizontal-rule"
    return attrs


def _content_text(target_tag: str, value: str | None) -> str:
    text = value or ""
    if target_tag in {"div", "lg", "index"} and not text.strip():
        return ""
    return text


def _needs_block_wrapper(target_parent: etree._Element, target_tag: str) -> bool:
    return _local(target_parent) in {"div", "quote"} and target_tag in {"ref", "hi", "seg"}


def _append_body_node(
    source: etree._Element,
    target_parent: etree._Element,
    *,
    rows_by_selector: Mapping[str, dict[str, Any]],
    id_targets: Mapping[str, str],
) -> None:
    if not isinstance(source.tag, str):
        raise ValueError("LIB-030 ThML.body contains a non-element node")
    row = rows_by_selector[_source_selector(source, "tree", [], [])]
    target_id = str(row["feature_id"])
    target_tag = _target_tag(source, target_parent)
    target = tei_el(target_tag, _target_attributes(source, target_tag, target_id, id_targets))
    actual_parent = target_parent
    if _needs_block_wrapper(target_parent, target_tag):
        actual_parent = tei_el("p")
        target_parent.append(actual_parent)
    title = source.get("title") if _local(source) in {"div1", "div2"} else None
    has_heading = any(
        isinstance(child.tag, str) and _local(child) in {"h1", "h2", "h3"}
        for child in source
    )
    if title and not has_heading:
        target.append(tei_el("head", text=title))
        target[0].tail = _content_text(target_tag, source.text)
    else:
        target.text = _content_text(target_tag, source.text)
    actual_parent.append(target)
    row.update(
        {
            "disposition": "represented-readable-tei-body",
            "tei_targets": [f"#{target_id}"],
            "tei_tag": target_tag,
            "tei_attributes": [
                ["xml:id" if name == XML_ID else str(name), value]
                for name, value in target.attrib.items()
            ],
            "projected_direct_text": target.text or (
                target[0].tail if title and not has_heading and len(target) else ""
            ),
            "projected_tail_text": source.tail or "",
        }
    )
    for child in source:
        _append_body_node(
            child, target, rows_by_selector=rows_by_selector, id_targets=id_targets
        )
        target[-1].tail = _content_text(target_tag, child.tail)


def _validate_source_shape(tree: etree._ElementTree) -> tuple[etree._Element, etree._Element]:
    root = tree.getroot()
    if _local(root) != "ThML" or root.attrib or root.nsmap:
        raise ValueError("LIB-030 ThML root shape drifted")
    children = [child for child in root if isinstance(child.tag, str)]
    if [_local(child) for child in children] != ["ThML.head", "ThML.body"]:
        raise ValueError("LIB-030 outer ThML document children drifted")
    head, body = children
    unknown = {
        _local(node) for node in body.iter() if isinstance(node.tag, str)
    } - BODY_TAGS
    if unknown:
        raise ValueError(f"LIB-030 unsupported ThML.body elements: {sorted(unknown)}")
    if any(not isinstance(node.tag, str) for node in body.iter()):
        raise ValueError("LIB-030 ThML.body contains unsupported comments or processing instructions")
    return head, body


def _semantic_header(
    metadata: Mapping[str, Any], source_set_digest: str, envelope: Mapping[str, Any]
) -> etree._Element:
    creators = metadata["creators"]
    author = creators[0]["text"] if creators else "C. H. Spurgeon"
    header = stamp_header(
        title=str(metadata["title"]),
        author=str(author),
        contributors=[
            {"name": metadata["contributor"], "role": "source conversion"},
            {"name": "Christian Classics Ethereal Library", "role": "electronic source host"},
        ],
        source_url="https://www.ccel.org/ccel/spurgeon/morneve.xml",
        source_sha256=source_set_digest,
        print_source="CCEL ThML edition; print-edition collation not performed",
        rights_statement=(
            f"Retained DC.Rights states {metadata['rights']!r}. Human rights, edition, "
            "textual, and publication decisions remain unresolved."
        ),
    )
    file_desc = header.find(f"{{{TEI_NS}}}fileDesc")
    if file_desc is None:
        raise ValueError("LIB-030 TEI header construction failed")
    notes = tei_el("notesStmt")
    notes.append(tei_el("note", {"type": "source-description"}, str(metadata["description"])))
    notes.append(tei_el("note", {"type": "source-editorial-history"}, str(metadata["editorial_comments"])))
    notes.append(tei_el("note", {"type": "source-revision-history"}, str(metadata["revision_history"])))
    notes.append(tei_el("note", {"type": "source-document-doctype"}, EXPECTED_DOCTYPE))
    notes.append(
        tei_el(
            "note", {"type": "source-envelope-sha256"},
            str(envelope["regions"]["pre_root"]["sha256"]),
        )
    )
    file_desc.insert(len(file_desc) - 1, notes)
    source_desc = file_desc.find(f"{{{TEI_NS}}}sourceDesc")
    bibl = source_desc.find(f"{{{TEI_NS}}}bibl") if source_desc is not None else None
    if bibl is None:
        raise ValueError("LIB-030 TEI source description construction failed")
    for title in metadata["titles"]:
        bibl.append(tei_el("title", {"type": str(title["sub"] or "source")}, str(title["text"])))
    for creator in metadata["creators"]:
        bibl.append(tei_el("author", text=str(creator["text"])))
    bibl.append(tei_el("publisher", text=str(metadata["publisher"])))
    bibl.append(tei_el("date", text=str(metadata["date"])))
    bibl.append(tei_el("idno", {"type": "CCEL-path"}, str(metadata["identifier"])))
    bibl.append(tei_el("note", {"type": "source-version"}, str(metadata["version"])))
    bibl.append(tei_el("note", {"type": "source-format"}, str(metadata["format"])))
    bibl.append(tei_el("note", {"type": "source-type"}, str(metadata["dc_type"])))
    return header


def _front(
    tree: etree._ElementTree,
    metadata: Mapping[str, Any],
    envelope: Mapping[str, Any],
    rows_by_selector: Mapping[str, dict[str, Any]],
) -> etree._Element:
    front = tei_el("front", {"xml:id": "lib030-front"})
    shell = tei_el("div", {"xml:id": "lib030-document-shell", "type": "source-document-shell"})
    shell.append(tei_el("head", text="Retained CCEL XML document shell"))
    declaration = next(row for row in envelope["carriers"] if row["kind"] == "xml-declaration")
    doctype = next(row for row in envelope["carriers"] if row["kind"] == "doctype")
    shell.append(tei_el("ab", {"xml:id": "lib030-source-xml-declaration", "type": "xml-declaration"}, declaration["text"]))
    shell.append(tei_el("ab", {"xml:id": "lib030-source-doctype", "type": "doctype"}, doctype["text"]))
    pre_nodes = [node for scope, node in _document_nodes(tree) if scope == "pre-root"]
    for ordinal, node in enumerate(pre_nodes, 1):
        row = rows_by_selector[f"/pre-root/comment()[{ordinal}]"]
        target_id = f"lib030-prolog-comment-{ordinal}"
        shell.append(tei_el("note", {"xml:id": target_id, "type": "pre-root-comment", "n": str(ordinal)}, node.text or ""))
        row.update(
            {
                "disposition": "represented-readable-tei-front",
                "tei_targets": [f"#{target_id}"],
                "tei_tag": "note",
                "tei_attributes": [["xml:id", target_id], ["type", "pre-root-comment"], ["n", str(ordinal)]],
                "projected_direct_text": node.text or "",
                "projected_tail_text": "",
            }
        )
    front.append(shell)
    source_head = tei_el("div", {"xml:id": "lib030-source-head", "type": "source-metadata"})
    source_head.append(tei_el("head", text="Retained ThML metadata, editorial history, rights, and styles"))
    source_head.append(
        tei_el(
            "ab", {"xml:id": "lib030-source-head-transcription", "type": "exact-parsed-thml-head-xml"},
            str(metadata["head_xml"]),
        )
    )
    front.append(source_head)
    head = _first_element(tree, "/ThML/ThML.head")
    if head is None:
        raise ValueError("LIB-030 source head disappeared during conversion")
    for node in head.iter():
        row = rows_by_selector[_source_selector(node, "tree", [], [])]
        row.update(
            {
                "disposition": "represented-readable-source-head-transcription-and-semantic-header",
                "tei_targets": ["#lib030-source-head-transcription"],
                "tei_tag": "ab",
                "tei_attributes": [["xml:id", "lib030-source-head-transcription"], ["type", "exact-parsed-thml-head-xml"]],
                "projected_direct_text": node.text or "",
                "projected_tail_text": node.tail or "",
            }
        )
    return front


def _annotate_document_containers(
    tree: etree._ElementTree, rows_by_selector: Mapping[str, dict[str, Any]]
) -> None:
    root = tree.getroot()
    head, body = _validate_source_shape(tree)
    rows_by_selector[_source_selector(root, "tree", [], [])].update(
        {
            "disposition": "represented-as-TEI-document-with-front-and-body",
            "tei_targets": ["#lib030-candidate"], "tei_tag": "TEI",
            "tei_attributes": [["xml:id", "lib030-candidate"]],
            "projected_direct_text": "", "projected_tail_text": "",
        }
    )
    rows_by_selector[_source_selector(head, "tree", [], [])].update(
        {
            "disposition": "represented-readable-source-head-transcription-and-semantic-header",
            "tei_targets": ["#lib030-source-head-transcription"], "tei_tag": "ab",
            "tei_attributes": [["xml:id", "lib030-source-head-transcription"]],
            "projected_direct_text": head.text or "", "projected_tail_text": head.tail or "",
        }
    )
    rows_by_selector[_source_selector(body, "tree", [], [])].update(
        {
            "disposition": "represented-as-TEI-body",
            "tei_targets": ["#lib030-body"], "tei_tag": "body",
            "tei_attributes": [["xml:id", "lib030-body"]],
            "projected_direct_text": "", "projected_tail_text": "",
        }
    )


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _authority_json(source_manifest, PROFILE_AUTHORITY)
    members = _retained_members(source_manifest)
    if profile.get("contract") != "ocd-lib030-reconstruction-profile-v3":
        raise ValueError("LIB-030 reconstruction profile version drifted")
    member_records = [
        {"work_id": str(item["work_id"]), "path": str(item["logical_path"]),
         "bytes": int(item["bytes"]), "sha256": str(item["sha256"])}
        for item in members
    ]
    source_set_digest = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": member_records})
    )
    root = tei_el("TEI", {"xml:id": "lib030-candidate"})
    rows: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    text = tei_el("text")
    body_out = tei_el("body", {"xml:id": "lib030-body"})
    retained_metadata: dict[str, Any] | None = None
    for member in members:
        content = member["content"]
        tree = _parse(content)
        head, source_body = _validate_source_shape(tree)
        envelope = _scan_envelope(content)
        if tree.docinfo.xml_version != "1.0" or tree.docinfo.encoding != "UTF-8":
            raise ValueError("LIB-030 parsed XML declaration drifted")
        if tree.docinfo.doctype != EXPECTED_DOCTYPE:
            raise ValueError("LIB-030 parsed doctype drifted")
        metadata = _metadata(tree)
        retained_metadata = metadata
        document_rows, rows_by_selector = _node_records(tree)
        _annotate_document_containers(tree, rows_by_selector)
        root.append(_semantic_header(metadata, source_set_digest, envelope))
        text.append(_front(tree, metadata, envelope, rows_by_selector))
        work_id = str(member["work_id"])
        _work_metadata(profile, work_id)
        work_out = tei_el("div", {"xml:id": work_id, "type": "work"})
        body_out.append(work_out)
        id_targets: dict[str, str] = {}
        source_ids: list[str] = []
        for node in source_body.iter():
            source_id = node.get("id") if isinstance(node.tag, str) else None
            if source_id:
                source_ids.append(source_id)
                id_targets.setdefault(
                    source_id,
                    str(rows_by_selector[_source_selector(node, "tree", [], [])]["feature_id"]),
                )
        id_count = sum(
            1 for node in source_body.iter() if isinstance(node.tag, str) and node.get("id")
        )
        if len(source_ids) != id_count:
            raise ValueError("LIB-030 source id census drifted")
        id_occurrences: dict[str, int] = {}
        for source_id in source_ids:
            id_occurrences[source_id] = id_occurrences.get(source_id, 0) + 1
        duplicate_ids = {
            source_id for source_id, count in id_occurrences.items() if count > 1
        }
        internal_references: list[str] = []
        for node in source_body.iter():
            if not isinstance(node.tag, str):
                continue
            for attribute in ("href", "prev", "next"):
                value = node.get(attribute)
                if value and value.lstrip("#") in id_targets:
                    internal_references.append(value.lstrip("#"))
        for child in source_body:
            _append_body_node(
                child,
                work_out,
                rows_by_selector=rows_by_selector,
                id_targets=id_targets,
            )
            work_out[-1].tail = _content_text("div", child.tail)
        if any("disposition" not in row for row in document_rows):
            missing = [row["source_selector"] for row in document_rows if "disposition" not in row]
            raise ValueError(f"LIB-030 unaccounted source carriers: {missing[:3]}")
        counts: dict[str, int] = {}
        for row in document_rows:
            tag = str(row["source_tag"])
            counts[tag] = counts.get(tag, 0) + 1
        documents.append(
            {
                "work_id": work_id, "logical_path": member["logical_path"],
                "bytes": member["bytes"], "sha256": member["sha256"],
                "document_envelope": envelope, "node_count": len(document_rows),
                "node_kind_counts": {
                    kind: sum(row["kind"] == kind for row in document_rows)
                    for kind in ("element", "comment", "processing-instruction")
                },
                "attribute_count": sum(len(row["attributes"]) for row in document_rows),
                "head_node_count": sum(1 for _node in head.iter()),
                "body_node_count": sum(1 for _node in source_body.iter()),
                "body_projection_node_count": sum(1 for _node in source_body.iter()) - 1,
                "source_xml_id_occurrence_count": len(source_ids),
                "source_xml_id_unique_count": len(id_targets),
                "source_duplicate_xml_id_value_count": len(source_ids) - len(id_targets),
                "source_duplicate_xml_id_extra_occurrence_count": len(source_ids) - len(id_targets),
                "internal_source_reference_count": len(internal_references),
                "duplicate_id_reference_count": sum(
                    source_id in duplicate_ids for source_id in internal_references
                ),
                "semantic_index_container_count": sum(
                    _local(node) == "div" and node.get("class") == "Index"
                    for node in source_body.iter()
                    if isinstance(node.tag, str)
                ),
                "centered_front_matter_container_count": sum(
                    _local(node) == "div" and node.get("class") == "Center"
                    for node in source_body.iter()
                    if isinstance(node.tag, str)
                ),
                "feature_counts": counts,
                "omitted_node_count": 0, "duplicate_node_count": 0,
                "invented_node_count": 0, "unresolved_node_count": 0,
            }
        )
        rows.extend(document_rows)
    text.append(body_out)
    root.append(text)
    accountability = {
        "contract": "ocd-lib030-source-accountability-v3",
        "schema": "lib030.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_scope": "complete retained XML byte envelope and every parsed document node",
        "source_reference_authority": {
            "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
            "authority": SOURCE_SET_AUTHORITY,
            "sha256": _sha(source_manifest.authority_path(SOURCE_SET_AUTHORITY).read_bytes()),
        },
        "source_members": member_records,
        "document_accounting": documents,
        "work_count": len(documents), "node_count": len(rows),
        "attribute_count": sum(len(row["attributes"]) for row in rows),
        "internal_source_reference_count": sum(
            item["internal_source_reference_count"] for item in documents
        ),
        "duplicate_id_reference_count": sum(
            item["duplicate_id_reference_count"] for item in documents
        ),
        "omitted_node_count": 0, "duplicate_node_count": 0,
        "invented_node_count": 0, "unresolved_node_count": 0,
        "crosswalk": rows,
    }
    if retained_metadata is None:
        raise ValueError("LIB-030 retained source set is empty")
    metadata = retained_metadata
    provenance = {
        "contract": "ocd-lib030-provenance-v3", "status": "nonaccepted",
        "publication_state": "not_ready", "source_id": source_manifest.record["source_id"],
        "source_member_set_sha256": source_set_digest,
        "source_root": "durable retained raw root resolved through OCD_RETAINED_RAW_ROOT or approved raw topology",
        "source_document_metadata": {
            key: metadata[key] for key in (
                "title", "description", "publisher", "contributor", "date", "dc_type",
                "format", "identifier", "language", "rights", "version",
                "editorial_comments", "revision_history", "titles", "creators",
                "subjects", "sources", "styles",
            )
        },
        "works": [
            {
                **_work_metadata(profile, str(member["work_id"])),
                "source_sha256": member["sha256"], "accepted_ir": "not_accepted",
                "human_review": "required", "publication": "not_ready",
            }
            for member in members
        ],
        "rights": {
            "retained_dc_rights": metadata["rights"],
            "underlying_work_claim": "local-config-public-domain",
            "electronic_host_terms": "CCEL parsing permission retained as evidence",
            "worldwide_rights_decision": "unresolved",
        },
        "canonical_data_written": False, "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "lib030-print-edition-collation",
            "scope": ["spurgeons-morning-evening"], "status": "unresolved",
            "question": "Does the retained CCEL ThML witness match the intended print edition?",
            "evidence": "No print collation was performed; the candidate is bound to the retained source bytes.",
        },
        {
            "id": "lib030-human-acceptance-and-publication",
            "scope": ["spurgeons-morning-evening"], "status": "unresolved",
            "question": "Will a maintainer accept the candidate text, rights basis, and publication status?",
            "evidence": "Technical reconstruction and validation are not human acceptance or publication authorization.",
        },
    ]
    return {
        "content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": source_manifest.authority_path(ATTRIBUTION_AUTHORITY).read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ("_convert",)
