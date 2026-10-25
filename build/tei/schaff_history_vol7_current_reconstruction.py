from __future__ import annotations
from collections import Counter
from io import BytesIO
import hashlib, json, re
from hashlib import sha256
from pathlib import Path
from typing import Mapping
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest, CandidatePackage
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
TEI_NS="http://www.tei-c.org/ns/1.0"
XML_NS="http://www.w3.org/XML/1998/namespace"
XML_ID="{"+XML_NS+"}id"
NS="{"+TEI_NS+"}"
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
        raise ValueError(f"retained HCC7 source is not well-formed XML: {exc}") from exc

def _local_name(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("non-element source node was not explicitly accounted")
    return etree.QName(node).localname

def _tei_token(value: str) -> str:
    """Return a schema-safe token while retaining the source value in standOff."""

    return re.sub(r"\s+", "-", value.strip())

def _heading_is_leading_division_child(source: etree._Element) -> bool:
    parent = source.getparent()
    if parent is None or _local_name(parent) not in _DIVISION_TAGS:
        return False
    for child in parent:
        if not isinstance(child.tag, str):
            continue
        return child is source
    return False

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
            "source_key": f"hcc7-n{number:06d}",
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
        "b": "hi",
        "sup": "hi",
        "unclear": "unclear",
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
            target.set("subtype", _tei_token(source_type))
        title = source.get("title")
        if title:
            target.set("n", title)
        elif source.get("n"):
            target.set("n", source.get("n"))
    elif source_name in _HEADING_TAGS:
        target.set("type", f"source-{source_name}")
    elif source_name == "i":
        target.set("rend", source_class or "italic")
    elif source_name in {"b", "sup"}:
        target.set("rend", "bold" if source_name == "b" else "superscript")
    elif source_name == "note":
        target.set("type", source_type or "ThML-note")
        if source.get("place"):
            target.set("place", source.get("place"))
        if source.get("n"):
            target.set("n", source.get("n"))
    elif source_name == "scripRef":
        target.set("type", "scripture-reference")
        if source.get("id") == "ii.iii.xv-p23.1":
            if list(source.attrib.items()) != [("passage", "Ep. 5:32"), ("id", "ii.iii.xv-p23.1")]:
                raise ValueError("declared literal reference preimage differs")
            target.set("n", source.get("passage"))
        else:
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
    if (
        not tei_root
        and source_name in _HEADING_TAGS
        and not _heading_is_leading_division_child(source)
    ):
        tei_name = "ab"
    target = etree.Element(
        f"{{{TEI_NS}}}{tei_name}",
        nsmap={None: TEI_NS} if tei_root else None,
    )
    location = index[source]
    source_key = str(location["source_key"])
    original_id = source.get("id")
    target.set(f"{{{XML_NS}}}id", original_id or f"hcc7-generated-{source_key[6:]}")
    if not tei_root:
        _apply_tei_semantics(target, source, source_name)
    if source.get("lang"):
        target.set(f"{{{XML_NS}}}lang", source.get("lang"))
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
        content_id = source.get("id") or f"hcc7-generated-{source_key[6:]}"
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

CONVERTER_ID="ocd-schaff-history-vol7-complete-retained-v1"
CONVERTER_VERSION="1"
canonical=_canonical
def _convert(manifest):
    manifest.verify();profile=json.loads(manifest.authority_path("profile").read_bytes())
    source_tree=_parse_source(manifest.authority_path("primary-source").read_bytes());source=source_tree.getroot()
    nodes,index=_source_index(source)
    root=_mapped_source_element(source,index,tei_root=True)
    header=etree.fromstring(profile["header_xml"].encode())
    holder=header.find(NS+"fileDesc/"+NS+"notesStmt/"+NS+"note[@type='retained-ThML-header']/"+NS+"p")
    holder.append(_mapped_source_element(source.find("ThML.head"),index));root.append(header)
    text=etree.SubElement(root,NS+"text");text.append(_mapped_source_element(source.find("ThML.body"),index))
    _append_source_projection_records(root,nodes,index)
    for comment in _top_level_siblings(source,before=True):
        if not isinstance(comment,etree._Comment):raise ValueError("unsupported source prolog node")
        copied=etree.Comment(comment.text or "");copied.tail=comment.tail;root.addprevious(copied)
    if _top_level_siblings(source,before=False):raise ValueError("unsupported source epilog")
    return {"content.tei.xml":_serialize_tei(root.getroottree()),"source-accountability.json":canonical(profile["accounting"]),"provenance.json":canonical(dict(work_id=profile["work_id"],source_manifest_sha256=manifest.sha256,scope=profile["scope"],status="nonaccepted",native_reconstruction=True)),"README.source.md":manifest.authority_path("source-readme").read_bytes(),"unresolved.jsonl":b"".join(canonical(q) for q in profile["questions"])}
_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION
_convert.implementation_path=Path(__file__).resolve()
