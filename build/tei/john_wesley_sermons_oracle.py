"""Independent standard-library XML oracle for the 37c-235 Wesley route."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import platform
from pathlib import Path
import re
import sys
from typing import Mapping
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-37c-235-john-wesley-sermons-independent-xml-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI = f"{{{TEI_NS}}}"
XML_ID = f"{{{XML_NS}}}id"

# This mapping is independently restated here; the oracle does not import or
# call the producer's traversal, mapping, selection, or completeness helpers.
_TARGETS = {
    "revisionHistory": "note",
    "ThML.head": "note",
    "ThML.body": "body",
    "div": "div",
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "p": "p",
    "h1": "head",
    "h2": "head",
    "h3": "head",
    "span": "seg",
    "i": "hi",
    "em": "hi",
    "note": "note",
    "pb": "pb",
    "scripRef": "ref",
    "name": "name",
    "cite": "title",
    "a": "ref",
    "link": "ref",
    "ul": "list",
    "li": "item",
    "scripContext": "milestone",
    "insertIndex": "milestone",
    "l": "l",
    "verse": "lg",
    "br": "lb",
    "hr": "milestone",
    "table": "table",
    "tr": "row",
    "td": "cell",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _canonical_xml(content: bytes) -> str:
    return ET.canonicalize(xml_data=content.decode("utf-8"), with_comments=True)


def _local(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else "#node"


def _stdlib_paths(root: ET.Element) -> dict[int, str]:
    rows: dict[int, str] = {}

    def visit(node: ET.Element, path: str | None = None) -> None:
        name = _local(node)
        path = path or f"/{name}[1]"
        rows[id(node)] = path
        counts: Counter[str] = Counter()
        for child in list(node):
            if not isinstance(child.tag, str):
                continue
            child_name = _local(child)
            counts[child_name] += 1
            visit(child, f"{path}/{child_name}[{counts[child_name]}]")

    visit(root)
    return rows


def _ids(root: ET.Element) -> tuple[dict[str, str], dict[int, str]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    generated = {
        id(node): f"src-{number:05d}" for number, node in enumerate(elements, start=1)
    }
    native: dict[str, str] = {}
    for node in elements:
        value = node.get("id")
        if value:
            if value in native:
                raise ValueError(f"duplicate retained source id: {value}")
            native[value] = generated[id(node)]
    return native, generated


def _tei_name(source_tag: str) -> str:
    return "TEI" if source_tag == "ThML" else _TARGETS.get(source_tag, "seg")


def _tei_attributes(
    source: ET.Element,
    target_tag: str,
    generated_id: str,
    native_ids: Mapping[str, str],
) -> dict[str, str]:
    source_tag = _local(source)
    result = {XML_ID: generated_id}
    if source_tag == "ThML":
        return result
    if source.get("n"):
        result["n"] = source.get("n", "")
    elif target_tag == "div" and source.get("id"):
        result["n"] = source.get("id", "")
    if source.get("class"):
        result["rend"] = source.get("class", "")
    if source.get("lang"):
        result[f"{{{XML_NS}}}lang"] = source.get("lang", "")
    if source_tag in {
        "div",
        "div1",
        "div2",
        "div3",
        "h3",
        "span",
        "scripRef",
        "a",
        "link",
    }:
        result["type"] = f"thml-{source_tag}"
    if source_tag in {"name", "cite"} and source.get("title"):
        result["key"] = source.get("title", "")
    if source_tag in {"scripRef", "a", "link"} and source.get("href"):
        href = source.get("href", "")
        if href.startswith("#"):
            if href[1:] not in native_ids:
                raise ValueError(f"unresolved retained fragment link: {href}")
            result["target"] = f"#{native_ids[href[1:]]}"
        else:
            result["target"] = href
    if source_tag == "pb" and source.get("href"):
        result["facs"] = source.get("href", "")
    if source_tag == "scripRef":
        if source.get("passage"):
            result["cRef"] = source.get("passage", "")
        if source.get("osisRef"):
            result["target"] = source.get("osisRef", "")
    if source_tag in {"scripContext", "insertIndex"}:
        result["unit"] = source_tag
        result["n"] = source.get("version") or source.get("type") or source_tag
    if source_tag == "hr":
        result["unit"] = "horizontal-rule"
    return result


def _copy_node(
    source: ET.Element,
    parent: ET.Element,
    native_ids: Mapping[str, str],
    generated_ids: Mapping[int, str],
    rows: list[dict[str, object]],
    paths: Mapping[int, str],
) -> ET.Element:
    source_tag = _local(source)
    target_tag = _tei_name(source_tag)
    parent_tag = _local(parent)
    if source_tag in {"h1", "h2", "h3"} and parent_tag in {"body", "div"}:
        component_names = {"p", "ab", "div", "lg", "list", "table"}
        if component_names.intersection(_local(sibling) for sibling in list(parent)):
            target_tag = "ab"
    if parent_tag in {"body", "div"} and target_tag in {
        "seg",
        "hi",
        "ref",
        "name",
        "title",
        "lb",
        "milestone",
    }:
        wrapper = ET.SubElement(parent, TEI + "p", {"rend": "thml-inline-run"})
        mapped = _copy_node(source, wrapper, native_ids, generated_ids, rows, paths)
        wrapper.tail = source.tail
        return wrapper
    target = ET.SubElement(
        parent,
        TEI + target_tag,
        _tei_attributes(source, target_tag, generated_ids[id(source)], native_ids),
    )
    if source_tag == "ThML.head":
        target.set("type", "source-thml-head")
    if source_tag == "revisionHistory":
        target.set("type", "thml-revisionHistory")
    if target_tag == "ab":
        target.set("type", f"thml-{source_tag}")
    if target_tag == "seg" and source_tag not in _TARGETS:
        target.set("type", f"thml-{source_tag}")
    if source_tag in {"div", "div1", "div2", "div3"}:
        target.set("type", f"thml-{source_tag}")
    if source_tag in {"i", "em"}:
        target.set("rend", "italic")
    target.text = source.text
    row: dict[str, object] = {
        "source_path": paths[id(source)],
        "source_tag": source_tag,
        "source_native_id": source.get("id"),
        "source_attributes": dict(source.attrib),
        "direct_text": source.text,
        "tail_text": source.tail,
        "target_tag": target_tag,
        "target_xml_id": generated_ids[id(source)],
    }
    rows.append(row)
    if source_tag in {"div", "div1", "div2", "div3"} and source.get("title"):
        title = " ".join(source.get("title", "").split())
        matching = any(
            isinstance(child.tag, str)
            and _local(child) in {"h1", "h2", "h3"}
            and " ".join("".join(child.itertext()).split()).casefold()
            == title.casefold()
            for child in list(source)
        )
        if not matching:
            heading = ET.SubElement(target, TEI + "head")
            heading.text = source.get("title")
            row["derived_heading"] = source.get("title")
    for child in list(source):
        if not isinstance(child.tag, str):
            raise ValueError(
                "unsupported non-element XML node in retained source body/head"
            )
        mapped = _copy_node(child, target, native_ids, generated_ids, rows, paths)
        mapped.tail = child.tail
    return target


def _expected_projection(
    raw: bytes,
    source_member: Mapping[str, object],
    profile: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    if len(raw) != source_member.get("bytes") or _sha(raw) != source_member.get(
        "sha256"
    ):
        raise ValueError("retained Wesley source member bytes or SHA-256 drifted")
    root = ET.fromstring(raw)
    if _local(root) != "ThML":
        raise ValueError("retained Wesley source root is not ThML")
    head = next((node for node in list(root) if _local(node) == "ThML.head"), None)
    source_body = next(
        (node for node in list(root) if _local(node) == "ThML.body"), None
    )
    if head is None or source_body is None:
        raise ValueError("retained Wesley ThML head/body envelope is incomplete")
    title_values = [
        node.text or ""
        for node in head.iter()
        if isinstance(node.tag, str) and _local(node) == "DC.Title"
    ]
    if not title_values or len(set(title_values)) != 1:
        raise ValueError(
            "retained Wesley source title evidence is missing or conflicting"
        )
    native_ids, generated_ids = _ids(root)
    if len(generated_ids) != int(profile["source_inventory"]["element_count"]):
        raise ValueError("retained Wesley source element count differs from profile")
    paths = _stdlib_paths(root)
    ET.register_namespace("", TEI_NS)
    tei = ET.Element(TEI + "TEI", {XML_ID: generated_ids[id(root)]})
    header = ET.SubElement(tei, TEI + "teiHeader")
    file_desc = ET.SubElement(header, TEI + "fileDesc")
    title_stmt = ET.SubElement(file_desc, TEI + "titleStmt")
    ET.SubElement(title_stmt, TEI + "title").text = title_values[0]
    publication = ET.SubElement(file_desc, TEI + "publicationStmt")
    ET.SubElement(publication, TEI + "p").text = (
        "Nonaccepted source-bound reconstruction. Rights, edition, identity, "
        "human acceptance, and publication decisions remain open."
    )
    source_desc = ET.SubElement(file_desc, TEI + "sourceDesc")
    bibliography = ET.SubElement(source_desc, TEI + "bibl")
    ET.SubElement(bibliography, TEI + "title").text = title_values[0]
    ET.SubElement(bibliography, TEI + "note", {"type": "retained-member"}).text = str(
        source_member["logical_path"]
    )
    ET.SubElement(bibliography, TEI + "note", {"type": "identity-status"}).text = (
        "The retained member is byte-bound; work boundary, print edition, "
        "part mapping, and exhaustive witness scope are unresolved."
    )
    rows: list[dict[str, object]] = []
    _copy_node(head, bibliography, native_ids, generated_ids, rows, paths)
    text = ET.SubElement(tei, TEI + "text")
    _copy_node(source_body, text, native_ids, generated_ids, rows, paths)
    allowed_root_children = {id(head), id(source_body)}
    if any(id(child) not in allowed_root_children for child in list(root)):
        raise ValueError("unsupported direct ThML root member")

    tag_counts = dict(
        Counter(_local(node) for node in root.iter() if isinstance(node.tag, str))
    )
    total_attributes = sum(
        len(node.attrib) for node in root.iter() if isinstance(node.tag, str)
    )
    body_carriers = []
    for position, carrier in enumerate(list(source_body)):
        if not isinstance(carrier.tag, str):
            continue
        body_carriers.append(
            {
                "position": position,
                "source_path": paths[id(carrier)],
                "id": carrier.get("id"),
                "title": carrier.get("title"),
                "div2_count": sum(
                    1
                    for item in carrier.iter()
                    if isinstance(item.tag, str) and _local(item) == "div2"
                ),
                "disposition": "include-in-source-order",
            }
        )
    ids = [
        node.get("id")
        for node in root.iter()
        if isinstance(node.tag, str) and node.get("id")
    ]
    fragments = [
        node.get("href", "")[1:]
        for node in root.iter()
        if isinstance(node.tag, str) and node.get("href", "").startswith("#")
    ]
    unresolved = sorted(set(fragments) - set(ids))
    if unresolved:
        raise ValueError(f"unresolved retained fragment links: {unresolved[:5]}")
    raw_comments = re.findall(rb"<!--(.*?)-->", raw, flags=re.DOTALL)
    without_comments = re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)
    doctype_match = re.search(rb"<!DOCTYPE\s+[^>]*>", without_comments, flags=re.DOTALL)
    doctype_text = doctype_match.group(0).decode("utf-8") if doctype_match else None
    if doctype_match:
        without_comments = (
            without_comments[: doctype_match.start()]
            + without_comments[doctype_match.end() :]
        )
    declaration_match = re.match(rb"\s*(<\?xml\s+[^?]*\?>)", raw)
    declaration = (
        declaration_match.group(1).decode("ascii") if declaration_match else None
    )
    if declaration_match:
        without_comments = without_comments.replace(declaration_match.group(1), b"", 1)
    source_inventory = {
        "root": "ThML",
        "ordered_root_children": [_local(child) for child in list(root)],
        "element_count": len(generated_ids),
        "attribute_count": total_attributes,
        "raw_xml_declaration": declaration,
        "doctype": {
            "public_id": "-//CCEL/DTD Theological Markup Language//EN"
            if doctype_text and "PUBLIC" in doctype_text
            else None,
            "system_id": "http://www.ccel.org/dtd/ThML10.dtd"
            if doctype_text and "ThML10.dtd" in doctype_text
            else None,
            "external_dtd_retained": False,
            "observed_entity_reference_nodes": 0,
        },
        "raw_comment_count": len(raw_comments),
        "live_processing_instruction_count": without_comments.count(b"<?"),
        "head_direct_children": [_local(child) for child in list(head)],
        "body_carriers": [
            {
                key: item[key]
                for key in ("position", "id", "title", "div2_count", "disposition")
            }
            for item in body_carriers
        ],
        "sermon_div2_count": sum(
            item["div2_count"]
            for item in body_carriers
            if str(item["title"]).endswith("Series")
        ),
        "index_div2_ids": [
            node.get("id")
            for carrier in list(source_body)
            if carrier.get("id") == "xi"
            for node in list(carrier)
            if isinstance(node.tag, str) and _local(node) == "div2"
        ],
        "unique_source_id_count": len(set(ids)),
        "duplicate_source_id_count": len(ids) - len(set(ids)),
        "internal_fragment_link_count": len(fragments),
        "resolved_internal_fragment_link_count": len(fragments) - len(unresolved),
        "feature_counts": {
            name: tag_counts.get(name, 0)
            for name in (
                "note",
                "a",
                "scripRef",
                "scripCom",
                "verse",
                "l",
                "table",
                "td",
                "tr",
                "li",
                "span",
                "br",
                "hr",
            )
        },
        "tag_counts": tag_counts,
    }
    if source_inventory != profile.get("source_inventory"):
        raise ValueError("retained Wesley source inventory differs from bound profile")

    # Rows are rebuilt in complete document order. Head/body recursion above
    # records content expectations, but the crosswalk order is source-native.
    row_by_path = {str(row["source_path"]): row for row in rows}
    root_row = {
        "source_path": paths[id(root)],
        "source_tag": "ThML",
        "source_native_id": root.get("id"),
        "source_attributes": dict(root.attrib),
        "direct_text": root.text,
        "tail_text": root.tail,
        "target_tag": "TEI",
        "target_xml_id": generated_ids[id(root)],
    }
    crosswalk = [
        root_row if node is root else row_by_path[paths[id(node)]]
        for node in root.iter()
        if isinstance(node.tag, str)
    ]
    shell = {
        "xml_declaration": declaration,
        "doctype": {
            "raw": doctype_text,
            "public_id": source_inventory["doctype"]["public_id"],
            "system_id": source_inventory["doctype"]["system_id"],
            "external_dtd_loaded": False,
            "entity_reference_nodes": 0,
        },
        "raw_comments": [item.decode("utf-8") for item in raw_comments],
        "live_processing_instruction_count": source_inventory[
            "live_processing_instruction_count"
        ],
        "root_direct_text": root.text,
        "root_tail_text": root.tail,
        "root_element": "ThML",
    }
    accountability = {
        "contract": "ocd-john-wesley-sermons-source-accountability-v1",
        "work_id": "john-wesley-sermons",
        "source": {
            key: source_member[key] for key in ("logical_path", "bytes", "sha256")
        },
        "document_shell": shell,
        "element_count": len(generated_ids),
        "attribute_count": total_attributes,
        "tag_counts": tag_counts,
        "body_carriers": body_carriers,
        "crosswalk": crosswalk,
        "internal_links": {
            "count": len(fragments),
            "resolved_count": len(fragments) - len(unresolved),
            "unresolved": unresolved,
        },
    }
    xml = ET.tostring(
        tei, encoding="UTF-8", xml_declaration=True, short_empty_elements=True
    )
    return xml, accountability


def _assert_projection(
    source_bytes: bytes,
    candidate_bytes: bytes,
    source_member: Mapping[str, object],
    profile: Mapping[str, object],
) -> None:
    expected, _ = _expected_projection(source_bytes, source_member, profile)
    if _canonical_xml(candidate_bytes) != _canonical_xml(expected):
        raise ValueError("candidate TEI differs from the independent source projection")


def _source_census(raw: bytes) -> dict[str, object]:
    """Independent current-source census using only stdlib XML traversal."""
    root = ET.fromstring(raw)
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    tags = Counter(_local(node) for node in elements)
    ids = [node.get("id") for node in elements if node.get("id")]
    fragments = [
        node.get("href", "")[1:]
        for node in elements
        if node.get("href", "").startswith("#")
    ]
    id_set = set(ids)
    head = next(node for node in list(root) if _local(node) == "ThML.head")
    body = next(node for node in list(root) if _local(node) == "ThML.body")
    carriers = []
    for position, carrier in enumerate(list(body)):
        if not isinstance(carrier.tag, str):
            continue
        carriers.append(
            {
                "position": position,
                "id": carrier.get("id"),
                "title": carrier.get("title"),
                "div2_count": sum(
                    1
                    for item in carrier.iter()
                    if isinstance(item.tag, str) and _local(item) == "div2"
                ),
                "disposition": "include-in-source-order",
            }
        )
    raw_comments = re.findall(rb"<!--(.*?)-->", raw, flags=re.DOTALL)
    without_comments = re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)
    doctype_match = re.search(rb"<!DOCTYPE\s+[^>]*>", without_comments, flags=re.DOTALL)
    doctype = doctype_match.group(0).decode("utf-8") if doctype_match else None
    if doctype_match:
        without_comments = (
            without_comments[: doctype_match.start()]
            + without_comments[doctype_match.end() :]
        )
    declaration_match = re.match(rb"\s*(<\?xml\s+[^?]*\?>)", raw)
    declaration = (
        declaration_match.group(1).decode("ascii") if declaration_match else None
    )
    if declaration_match:
        without_comments = without_comments.replace(declaration_match.group(1), b"", 1)
    return {
        "root": _local(root),
        "ordered_root_children": [_local(child) for child in list(root)],
        "element_count": len(elements),
        "attribute_count": sum(len(node.attrib) for node in elements),
        "raw_xml_declaration": declaration,
        "doctype": {
            "public_id": "-//CCEL/DTD Theological Markup Language//EN"
            if doctype and "PUBLIC" in doctype
            else None,
            "system_id": "http://www.ccel.org/dtd/ThML10.dtd"
            if doctype and "ThML10.dtd" in doctype
            else None,
            "external_dtd_retained": False,
            "observed_entity_reference_nodes": 0,
        },
        "raw_comment_count": len(raw_comments),
        "live_processing_instruction_count": without_comments.count(b"<?"),
        "head_direct_children": [_local(child) for child in list(head)],
        "body_carriers": carriers,
        "sermon_div2_count": sum(
            item["div2_count"]
            for item in carriers
            if str(item["title"]).endswith("Series")
        ),
        "index_div2_ids": [
            node.get("id")
            for carrier in list(body)
            if carrier.get("id") == "xi"
            for node in list(carrier)
            if isinstance(node.tag, str) and _local(node) == "div2"
        ],
        "unique_source_id_count": len(id_set),
        "duplicate_source_id_count": len(ids) - len(id_set),
        "internal_fragment_link_count": len(fragments),
        "resolved_internal_fragment_link_count": sum(
            1 for target in fragments if target in id_set
        ),
        "feature_counts": {
            name: tags.get(name, 0)
            for name in (
                "note",
                "a",
                "scripRef",
                "scripCom",
                "verse",
                "l",
                "table",
                "td",
                "tr",
                "li",
                "span",
                "br",
                "hr",
            )
        },
        "tag_counts": dict(tags),
    }


def _role_authority(source: SourceManifest, role: str) -> Mapping[str, object]:
    matches = [
        item for item in source.record["authorities"] if item.get("role") == role
    ]
    if len(matches) != 1:
        raise ValueError(f"source manifest must bind exactly one {role} authority")
    return matches[0]


def _closure_paths() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2]
    return tuple(
        root / item
        for item in (
            "build/tei/john_wesley_sermons_oracle.py",
            "ocd_kernel/__init__.py",
            "ocd_kernel/reconstruction/__init__.py",
            "ocd_kernel/reconstruction/contract.py",
            "ocd_kernel/tei/validate.py",
        )
    )


def _import_closure_sha256() -> str:
    root = Path(__file__).resolve().parents[2]
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in _closure_paths()
    ]
    return _sha(_canonical(records))


def _authority_hash(source: SourceManifest, role: str) -> str:
    return str(_role_authority(source, role)["sha256"])


def _runtime_binding() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"


def _expected_readme(source_member: Mapping[str, object], raw: bytes) -> bytes:
    comments = [
        item.decode("utf-8")
        for item in re.findall(rb"<!--(.*?)-->", raw, flags=re.DOTALL)
    ]
    comment_blocks = "\n\n".join(f"```xml\n<!--{item}-->\n```" for item in comments)
    return (
        "# Sermons on Several Occasions\n\n"
        "This work-specific source route binds one retained CCEL ThML XML member by exact path, byte length, and SHA-256. "
        "It preserves all parsed head and body elements, source order, direct text, child tails, native attributes in the accountability crosswalk, and source fragment targets.\n\n"
        "The retained external DTD identifiers and document-shell comments are recorded; no external DTD was fetched. "
        "Source-shell comments are reproduced verbatim below and are not treated as transformation instructions.\n\n"
        f"{comment_blocks}\n\n"
        "The retained source states publication in 1771 and describes five series; the local source config claims an 1872 standard edition. "
        "Edition, work boundary, part mapping, exhaustive witness scope, rights clearance, human acceptance, and publication remain unresolved. "
        "Source-header attribution and rights strings are preserved as observations, not adopted decisions.\n"
    ).encode("utf-8")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    policy = json.loads(
        source_manifest.authority_path("validation-policy").read_bytes()
    )
    member = source_manifest.record["source_member"]
    raw = source_manifest.authority_path("retained-source").read_bytes()
    expected_content, expected_accountability = _expected_projection(
        raw, member, profile
    )
    if _canonical_xml(candidate.member_bytes("content.tei.xml")) != _canonical_xml(
        expected_content
    ):
        raise ValueError("candidate TEI differs from the independent source projection")
    if candidate.member_bytes("source-accountability.json") != _canonical(
        expected_accountability
    ):
        raise ValueError(
            "candidate source-accountability differs from the independent census"
        )
    if candidate.member_bytes("README.source.md") != _expected_readme(member, raw):
        raise ValueError(
            "candidate source README differs from the bounded identity and attribution statement"
        )
    unresolved = b"".join(_canonical(item) for item in profile["candidate_questions"])
    if candidate.member_bytes("unresolved.jsonl") != unresolved:
        raise ValueError(
            "candidate unresolved questions differ from the source profile"
        )
    expected_provenance = {
        "contract": "ocd-john-wesley-sermons-provenance-v1",
        "work_id": "john-wesley-sermons",
        "source_id": source_manifest.record["source_id"],
        "source_member": dict(member),
        "source_manifest_sha256": source_manifest.sha256,
        "source_sha256": member["sha256"],
        "candidate_status": policy["candidate_status"],
        "canonical_data_written": False,
        "accepted_ir_written": False,
        "rights_clearance": "not_performed",
        "human_acceptance": "not_performed",
        "publication": policy["publication_state"],
    }
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError(
            "candidate provenance differs from the source manifest and policy"
        )

    accountability_schema = json.loads(
        source_manifest.authority_path("source-accountability-schema").read_bytes()
    )
    Draft202012Validator.check_schema(accountability_schema)
    errors = sorted(
        Draft202012Validator(accountability_schema).iter_errors(
            expected_accountability
        ),
        key=lambda item: list(item.path),
    )
    if errors:
        raise ValueError(
            f"Wesley source-accountability schema failure: {errors[0].message}"
        )
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(
        etree.parse(str(xsd_path), etree.XMLParser(no_network=True))
    )
    tei_parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True
    )
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), tei_parser)
    if not schema.validate(tei):
        raise ValueError(f"Wesley TEI P5 schema failure: {schema.error_log.last_error}")

    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _import_closure_sha256(),
        "runtime": _runtime_binding(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _authority_hash(
            source_manifest, "complete-source-feature-profile"
        ),
        "package_schema_sha256": _authority_hash(
            source_manifest, "candidate-package-schema"
        ),
        "source_sha256": str(member["sha256"]),
        "xsd_sha256": _authority_hash(source_manifest, "tei-validation-schema"),
        "policy_sha256": _authority_hash(
            source_manifest, "independent-validation-policy"
        ),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
