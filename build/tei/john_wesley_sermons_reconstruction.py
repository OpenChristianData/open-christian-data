"""Work-specific reconstruction route for the retained Wesley ThML member.

The route is deliberately not invoked by its source-contract tests: candidate
generation and destination selection remain coordinator work for 37c-235.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-37c-235-john-wesley-sermons-thml-to-tei"
CONVERTER_VERSION = "1"
PROFILE_AUTHORITY = "reconstruction-profile"
POLICY_AUTHORITY = "validation-policy"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"

TAG_MAP = {
    "ThML.head": "note",
    "revisionHistory": "note",
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


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _safe_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _source_path(node: etree._Element) -> str:
    pieces: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        name = _local(current)
        parent = current.getparent()
        if parent is None:
            pieces.append(f"{name}[1]")
            break
        same_name = [
            child
            for child in parent
            if isinstance(child.tag, str) and _local(child) == name
        ]
        pieces.append(f"{name}[{same_name.index(current) + 1}]")
        current = parent
    return "/" + "/".join(reversed(pieces))


def _source_ids(root: etree._Element) -> dict[str, str]:
    result: dict[str, str] = {}
    elements = (node for node in root.iter() if isinstance(node.tag, str))
    for number, node in enumerate(elements, start=1):
        native_id = node.get("id")
        if native_id:
            if native_id in result:
                raise ValueError(f"duplicate retained source id: {native_id}")
            result[native_id] = f"src-{number:05d}"
    return result


def _target_tag(source_tag: str) -> str:
    if source_tag == "ThML":
        return "TEI"
    return TAG_MAP.get(source_tag, "seg")


def _target_attributes(
    source: etree._Element,
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
            native_id = href[1:]
            if native_id not in native_ids:
                raise ValueError(f"unresolved retained fragment link: {href}")
            result["target"] = f"#{native_ids[native_id]}"
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


def _append_source_node(
    source: etree._Element,
    parent: etree._Element,
    *,
    native_ids: Mapping[str, str],
    generated_ids: Mapping[etree._Element, str],
    rows: list[dict[str, object]],
) -> etree._Element | None:
    if isinstance(source, etree._Comment):
        node = etree.Comment(source.text or "")
        node.tail = source.tail
        parent.append(node)
        return node
    if isinstance(source, etree._ProcessingInstruction):
        node = etree.ProcessingInstruction(source.target, source.text or "")
        node.tail = source.tail
        parent.append(node)
        return node
    if not isinstance(source.tag, str):
        raise ValueError(f"unsupported retained XML node: {type(source).__name__}")

    source_tag = _local(source)
    target_tag = _target_tag(source_tag)
    parent_tag = etree.QName(parent).localname
    # A later heading carrier does not establish a new source division. P5
    # divTop heads cannot follow component content; retain it as a typed block.
    if (
        target_tag == "head"
        and parent_tag in {"body", "div"}
        and any(
            isinstance(child.tag, str)
            and _local(child) in {"p", "ab", "div", "lg", "list", "table"}
            for child in parent
        )
    ):
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
        wrapper = etree.SubElement(
            parent,
            f"{{{TEI_NS}}}p",
            {"rend": "thml-inline-run"},
        )
        mapped = _append_source_node(
            source,
            wrapper,
            native_ids=native_ids,
            generated_ids=generated_ids,
            rows=rows,
        )
        if mapped is None:
            raise ValueError("source inline carrier did not map")
        wrapper.tail = source.tail
        return wrapper
    target = etree.SubElement(
        parent,
        f"{{{TEI_NS}}}{target_tag}",
        _target_attributes(source, target_tag, generated_ids[source], native_ids),
    )
    if source_tag == "ThML.head":
        target.set("type", "source-thml-head")
    if source_tag == "revisionHistory":
        target.set("type", "thml-revisionHistory")
    if target_tag == "ab":
        target.set("type", f"thml-{source_tag}")
    if target_tag == "seg" and source_tag not in TAG_MAP:
        target.set("type", f"thml-{source_tag}")
    if source_tag in {"div", "div1", "div2", "div3"}:
        target.set("type", f"thml-{source_tag}")
    if source_tag in {"i", "em"}:
        target.set("rend", "italic")
    target.text = source.text

    row: dict[str, object] = {
        "source_path": _source_path(source),
        "source_tag": source_tag,
        "source_native_id": source.get("id"),
        "source_attributes": dict(source.attrib),
        "direct_text": source.text,
        "tail_text": source.tail,
        "target_tag": target_tag,
        "target_xml_id": generated_ids[source],
    }
    rows.append(row)

    if source_tag in {"div", "div1", "div2", "div3"} and source.get("title"):
        title = " ".join(source.get("title", "").split())
        direct_heading = any(
            isinstance(child.tag, str)
            and _local(child) in {"h1", "h2", "h3"}
            and " ".join("".join(child.itertext()).split()).casefold()
            == title.casefold()
            for child in source
        )
        if not direct_heading:
            head = etree.SubElement(target, f"{{{TEI_NS}}}head")
            head.text = source.get("title")
            row["derived_heading"] = source.get("title")

    for child in source:
        mapped = _append_source_node(
            child,
            target,
            native_ids=native_ids,
            generated_ids=generated_ids,
            rows=rows,
        )
        if mapped is not None:
            mapped.tail = child.tail
    return target


def _raw_shell(raw: bytes, tree: etree._ElementTree) -> dict[str, object]:
    comments = re.findall(rb"<!--(.*?)-->", raw, flags=re.DOTALL)
    without_comments = re.sub(rb"<!--.*?-->", b"", raw, flags=re.DOTALL)
    doctype_match = re.search(rb"<!DOCTYPE\s+[^>]*>", without_comments, flags=re.DOTALL)
    without_doctype = (
        without_comments[: doctype_match.start()]
        + without_comments[doctype_match.end() :]
        if doctype_match
        else without_comments
    )
    declaration_match = re.match(rb"\s*(<\?xml\s+[^?]*\?>)", raw)
    without_declaration = (
        without_doctype.replace(declaration_match.group(1), b"", 1)
        if declaration_match
        else without_doctype
    )
    return {
        "xml_declaration": declaration_match.group(1).decode("ascii")
        if declaration_match
        else None,
        "doctype": {
            "raw": doctype_match.group(0).decode("utf-8") if doctype_match else None,
            "public_id": tree.docinfo.public_id or None,
            "system_id": tree.docinfo.system_url or None,
            "external_dtd_loaded": False,
            "entity_reference_nodes": sum(
                1 for node in tree.getroot().iter() if isinstance(node, etree._Entity)
            ),
        },
        "raw_comments": [comment.decode("utf-8") for comment in comments],
        "live_processing_instruction_count": without_declaration.count(b"<?"),
        "root_direct_text": tree.getroot().text,
        "root_tail_text": tree.getroot().tail,
        "root_element": _local(tree.getroot()),
    }


def _parse_source(raw: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        remove_comments=False,
        huge_tree=True,
    )
    from io import BytesIO

    return etree.parse(BytesIO(raw), parser)


def _project_document(
    raw: bytes,
    source_member: Mapping[str, object],
    profile: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    if len(raw) != source_member.get("bytes") or _sha(raw) != source_member.get(
        "sha256"
    ):
        raise ValueError("retained Wesley source member bytes or SHA-256 drifted")
    tree = _parse_source(raw)
    source_root = tree.getroot()
    if _local(source_root) != "ThML":
        raise ValueError("retained Wesley source root is not ThML")
    head = source_root.find("ThML.head")
    source_body = source_root.find("ThML.body")
    if head is None or source_body is None:
        raise ValueError("retained Wesley ThML head/body envelope is incomplete")
    titles = [
        node.text or ""
        for node in head.iter()
        if isinstance(node.tag, str) and _local(node) == "DC.Title"
    ]
    if not titles or len(set(titles)) != 1:
        raise ValueError(
            "retained Wesley source title evidence is missing or conflicting"
        )

    native_ids = _source_ids(source_root)
    generated_ids = {
        node: f"src-{number:05d}"
        for number, node in enumerate(
            (item for item in source_root.iter() if isinstance(item.tag, str)), start=1
        )
    }
    if len(generated_ids) != int(profile["source_inventory"]["element_count"]):
        raise ValueError("retained Wesley source element count differs from profile")

    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    tei.set(XML_ID, generated_ids[source_root])
    tei_header = etree.SubElement(tei, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(tei_header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = titles[0]
    publication_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication_stmt, f"{{{TEI_NS}}}p").text = (
        "Nonaccepted source-bound reconstruction. Rights, edition, identity, "
        "human acceptance, and publication decisions remain open."
    )
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibliography = etree.SubElement(source_desc, f"{{{TEI_NS}}}bibl")
    etree.SubElement(bibliography, f"{{{TEI_NS}}}title").text = titles[0]
    etree.SubElement(
        bibliography, f"{{{TEI_NS}}}note", {"type": "retained-member"}
    ).text = str(source_member["logical_path"])
    etree.SubElement(
        bibliography, f"{{{TEI_NS}}}note", {"type": "identity-status"}
    ).text = (
        "The retained member is byte-bound; work boundary, print edition, "
        "part mapping, and exhaustive witness scope are unresolved."
    )

    rows: list[dict[str, object]] = []
    header_note = _append_source_node(
        head,
        bibliography,
        native_ids=native_ids,
        generated_ids=generated_ids,
        rows=rows,
    )
    if header_note is None:
        raise ValueError("retained ThML.head did not map to a TEI note")
    text = etree.SubElement(tei, f"{{{TEI_NS}}}text")
    body = _append_source_node(
        source_body,
        text,
        native_ids=native_ids,
        generated_ids=generated_ids,
        rows=rows,
    )
    if body is None:
        raise ValueError("retained ThML.body did not map to a TEI body")
    for child in source_root:
        if child not in {head, source_body}:
            raise ValueError(f"unsupported direct ThML root member: {_local(child)}")

    # The ThML and wrapper nodes have explicit TEI-container mappings; ensure
    # each is present in the crosswalk alongside recursively mapped children.
    wrapper_rows = [
        {
            "source_path": _source_path(source_root),
            "source_tag": "ThML",
            "source_native_id": source_root.get("id"),
            "source_attributes": dict(source_root.attrib),
            "direct_text": source_root.text,
            "tail_text": source_root.tail,
            "target_tag": "TEI",
            "target_xml_id": generated_ids[source_root],
        },
        {
            "source_path": _source_path(head),
            "source_tag": "ThML.head",
            "source_native_id": head.get("id"),
            "source_attributes": dict(head.attrib),
            "direct_text": head.text,
            "tail_text": head.tail,
            "target_tag": "note",
            "target_xml_id": generated_ids[head],
        },
        {
            "source_path": _source_path(source_body),
            "source_tag": "ThML.body",
            "source_native_id": source_body.get("id"),
            "source_attributes": dict(source_body.attrib),
            "direct_text": source_body.text,
            "tail_text": source_body.tail,
            "target_tag": "body",
            "target_xml_id": generated_ids[source_body],
        },
    ]
    rows_by_path = {str(row["source_path"]): row for row in rows}
    rows_by_path.update({str(row["source_path"]): row for row in wrapper_rows})
    crosswalk = [
        rows_by_path[_source_path(node)]
        for node in source_root.iter()
        if isinstance(node.tag, str)
    ]
    element_count = sum(1 for node in source_root.iter() if isinstance(node.tag, str))
    attribute_count = sum(
        len(node.attrib) for node in source_root.iter() if isinstance(node.tag, str)
    )
    tag_counts = dict(
        Counter(
            _local(node) for node in source_root.iter() if isinstance(node.tag, str)
        )
    )
    body_carriers = []
    for position, carrier in enumerate(source_body):
        if not isinstance(carrier.tag, str):
            continue
        div2_count = sum(
            1
            for node in carrier.iter()
            if isinstance(node.tag, str) and _local(node) == "div2"
        )
        body_carriers.append(
            {
                "position": position,
                "source_path": _source_path(carrier),
                "id": carrier.get("id"),
                "title": carrier.get("title"),
                "div2_count": div2_count,
                "disposition": "include-in-source-order",
            }
        )
    source_shell = _raw_shell(raw, tree)
    accountability = {
        "contract": "ocd-john-wesley-sermons-source-accountability-v1",
        "work_id": "john-wesley-sermons",
        "source": {
            key: source_member[key] for key in ("logical_path", "bytes", "sha256")
        },
        "document_shell": source_shell,
        "element_count": element_count,
        "attribute_count": attribute_count,
        "tag_counts": tag_counts,
        "body_carriers": body_carriers,
        "crosswalk": crosswalk,
        "internal_links": {
            "count": sum(
                1
                for node in source_root.iter()
                if isinstance(node.tag, str)
                and (node.get("href") or "").startswith("#")
            ),
            "resolved_count": sum(
                1
                for node in source_root.iter()
                if isinstance(node.tag, str)
                and (node.get("href") or "").startswith("#")
            ),
            "unresolved": [],
        },
    }
    return etree.tostring(
        tei, encoding="UTF-8", xml_declaration=True, pretty_print=False
    ), accountability


def _producer_import_closure_paths() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2]
    return tuple(
        root / name
        for name in (
            "build/tei/john_wesley_sermons_reconstruction.py",
            "ocd_kernel/__init__.py",
            "ocd_kernel/reconstruction/__init__.py",
            "ocd_kernel/reconstruction/contract.py",
        )
    )


def _producer_import_closure_sha256() -> str:
    root = Path(__file__).resolve().parents[2]
    rows = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in _producer_import_closure_paths()
    ]
    return _sha(_canonical(rows))


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    """Build in-memory package members; coordinator alone invokes reconstruct()."""
    source_manifest.verify()
    record = source_manifest.record
    source_member = record.get("source_member")
    if not isinstance(source_member, Mapping):
        raise ValueError("Wesley source manifest has no exact source_member binding")
    profile = _safe_json(
        source_manifest.authority_path(PROFILE_AUTHORITY).read_bytes(),
        "reconstruction profile",
    )
    policy = _safe_json(
        source_manifest.authority_path(POLICY_AUTHORITY).read_bytes(),
        "validation policy",
    )
    profile_member = profile.get("source_scope")
    if not isinstance(profile_member, Mapping):
        raise ValueError("Wesley profile source scope is invalid")
    if any(
        profile_member.get(key) != source_member.get(key)
        for key in ("logical_path", "bytes", "sha256")
    ):
        raise ValueError("Wesley profile and source manifest member binding differ")
    raw = source_manifest.authority_path("retained-source").read_bytes()
    content, accountability = _project_document(raw, source_member, profile)
    unresolved = profile.get("candidate_questions")
    if not isinstance(unresolved, list) or any(
        not isinstance(item, dict) for item in unresolved
    ):
        raise ValueError("Wesley profile candidate_questions must be a list of objects")
    source_inventory = profile.get("source_inventory")
    if not isinstance(source_inventory, Mapping):
        raise ValueError("Wesley profile has no source inventory")
    source_sha = str(source_member["sha256"])
    provenance = {
        "contract": "ocd-john-wesley-sermons-provenance-v1",
        "work_id": "john-wesley-sermons",
        "source_id": record["source_id"],
        "source_member": dict(source_member),
        "source_manifest_sha256": source_manifest.sha256,
        "source_sha256": source_sha,
        "candidate_status": policy["candidate_status"],
        "canonical_data_written": False,
        "accepted_ir_written": False,
        "rights_clearance": "not_performed",
        "human_acceptance": "not_performed",
        "publication": policy["publication_state"],
    }
    shell = accountability["document_shell"]
    comments = shell["raw_comments"]
    if not isinstance(comments, list) or any(
        not isinstance(item, str) for item in comments
    ):
        raise ValueError("Wesley document-shell comment inventory is invalid")
    comment_blocks = "\n\n".join(f"```xml\n<!--{item}-->\n```" for item in comments)
    readme = (
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
    return {
        "content.tei.xml": content,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
