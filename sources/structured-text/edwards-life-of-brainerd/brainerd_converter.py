"""Entry-local faithful TEI converter for Edwards's Brainerd witness.

The legacy CCEL parser produces a flattened JSON projection.  This converter
belongs only to ``edwards-life-of-brainerd`` and retains the selected ThML
tree's source order, element text, tails, IDs, inline markup, notes, page
breaks, and scripture-reference attributes in a readable TEI candidate.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree


CONVERTER_ID = "edwards-brainerd-source-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "edwards-life-of-brainerd"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

SOURCE_TO_TEI = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "div5": "div",
    "h1": "p",
    "h2": "p",
    "h3": "p",
    "h4": "p",
    "h5": "p",
    "h6": "p",
    "p": "p",
    "i": "hi",
    "b": "hi",
    "note": "note",
    "pb": "pb",
    "scripRef": "ref",
}
_DIV_TAGS = frozenset({"div1", "div2", "div3", "div4", "div5"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_SUPPORTED_TAGS = frozenset(SOURCE_TO_TEI)


def _q(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _xml_id() -> str:
    return f"{{{XML_NS}}}id"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _element_children(node: etree._Element) -> list[etree._Element]:
    return [child for child in node if isinstance(child.tag, str)]


def _node_path(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and isinstance(current.tag, str):
        parent = current.getparent()
        if parent is None:
            position = 1
        else:
            try:
                raw_index = parent.index(current)
                position = sum(
                    1
                    for sibling in list(parent)[: raw_index + 1]
                    if isinstance(sibling.tag, str)
                    if _local(sibling) == _local(current)
                )
            except (ValueError, AttributeError) as exc:
                raise ValueError("source node is detached while addressing it") from exc
        parts.append(f"{_local(current)}[{position}]")
        current = parent
    return "/".join(reversed(parts))


def _authority_record(manifest: object, name: str) -> Mapping[str, object]:
    record = getattr(manifest, "record", None)
    if not isinstance(record, Mapping):
        raise ValueError("source manifest record is unavailable")
    authorities = record.get("authorities")
    if not isinstance(authorities, (list, tuple)):
        raise ValueError("source manifest authorities are unavailable")
    for authority in authorities:
        if isinstance(authority, Mapping) and authority.get("name") == name:
            return authority
    raise ValueError(f"source manifest has no {name!r} authority")


def _authority_bytes(manifest: object, name: str) -> bytes:
    authority_path = getattr(manifest, "authority_path", None)
    if not callable(authority_path):
        raise ValueError("source manifest authority resolver is unavailable")
    return authority_path(name).read_bytes()


def _manifest_scope(manifest: object) -> dict[str, object]:
    record = getattr(manifest, "record", None)
    if not isinstance(record, Mapping) or not isinstance(record.get("scope"), Mapping):
        raise ValueError("source manifest scope is missing")
    return dict(record["scope"])


def _load_config(manifest: object) -> tuple[dict[str, object], bytes]:
    content = _authority_bytes(manifest, "work-config")
    config = _strict_json(content, "Brainerd work config")
    if config.get("resource_id") != WORK_ID:
        raise ValueError("Brainerd work config identity mismatch")
    return config, content


def _source_tree(
    manifest: object,
) -> tuple[bytes, etree._Element, etree._Element, etree._Element]:
    source_path = getattr(manifest, "authority_path")("source")
    raw = source_path.read_bytes()
    if b"<!DOCTYPE" in raw or b"<!--" in raw:
        raise ValueError("Brainerd source has an unsupported document-shell construct")
    if len(re.findall(rb"<\?(?!xml\b)", raw, flags=re.IGNORECASE)):
        raise ValueError("Brainerd source has an unsupported processing instruction")
    parser = etree.XMLParser(
        remove_comments=False,
        strip_cdata=False,
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
    )
    try:
        root = etree.fromstring(raw, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Brainerd source is not well-formed XML") from exc
    if _local(root) != "ThML":
        raise ValueError("Brainerd source root is not ThML")
    root_children = _element_children(root)
    if len(root_children) != 1 or _local(root_children[0]) != "ThML.body":
        raise ValueError("Brainerd source envelope does not have one ThML.body")
    body = root_children[0]
    body_children = _element_children(body)
    if len(body_children) != 1:
        raise ValueError("Brainerd source body does not have one selected member")
    selected = body_children[0]
    if _local(selected) != "div1" or selected.get("id") != "ix":
        raise ValueError("Brainerd source selected div1 id is not ix")
    for parent in root.iter():
        if any(not isinstance(child.tag, str) for child in parent):
            raise ValueError("Brainerd source contains an unsupported non-element node")
    return raw, root, body, selected


def _source_envelope(
    raw: bytes,
    root: etree._Element,
    body: etree._Element,
    selected: etree._Element,
) -> dict[str, object]:
    root_start = raw.find(b"<ThML>")
    root_end = raw.rfind(b"</ThML>") + len(b"</ThML>")
    if root_start < 0 or root_end <= len(b"</ThML>"):
        raise ValueError("Brainerd source root byte envelope is not locatable")
    prefix = raw[:root_start]
    suffix = raw[root_end:]
    return {
        "xml_declaration": prefix.decode("ascii"),
        "prefix_bytes": len(prefix),
        "prefix_sha256": _sha(prefix),
        "root_tag": _local(root),
        "root_children": [_local(child) for child in _element_children(root)],
        "body_tag": _local(body),
        "body_children": [
            {"tag": _local(child), "id": child.get("id")}
            for child in _element_children(body)
        ],
        "selected_source_path": _node_path(selected),
        "selected_source_id": selected.get("id"),
        "selected_root_tail": {
            "characters": len(selected.tail or ""),
            "sha256": _sha((selected.tail or "").encode("utf-8")),
        },
        "suffix_bytes": len(suffix),
        "suffix_sha256": _sha(suffix),
        "doctype": False,
        "comments": 0,
        "processing_instructions": 0,
    }


def _source_feature(node: etree._Element, ordinal: int) -> dict[str, object]:
    parent = node.getparent()
    if parent is None:
        raise ValueError("Brainerd source carrier has no parent")
    siblings = _element_children(parent)
    try:
        child_index = parent.index(node) + 1
    except (ValueError, AttributeError) as exc:
        raise ValueError("Brainerd source carrier is not attached to its parent") from exc
    direct_text = node.text or ""
    full_text = "".join(node.itertext())
    tail = node.tail or ""
    children = _element_children(node)
    return {
        "ordinal": ordinal,
        "source_path": _node_path(node),
        "parent_source_path": _node_path(parent),
        "element_child_index": child_index,
        "source_tag": _local(node),
        "source_id": node.get("id"),
        "source_attributes": dict(node.attrib),
        "source_text_sha256": _sha(full_text.encode("utf-8")),
        "source_text_characters": len(full_text),
        "direct_text_sha256": _sha(direct_text.encode("utf-8")),
        "direct_text_characters": len(direct_text),
        "source_tail_sha256": _sha(tail.encode("utf-8")),
        "source_tail_characters": len(tail),
        "child_tags": [_local(child) for child in children],
        "child_ids": [child.get("id") for child in children],
        "child_count": len(children),
    }


def _target_xml_id(node: etree._Element, ordinal: int) -> str:
    source_id = node.get("id")
    return source_id if source_id else f"brainerd-source-{ordinal:06d}"


def _set_if_present(target: etree._Element, name: str, value: str | None) -> None:
    if value is not None:
        target.set(name, value)


def _target_attributes(
    source: etree._Element,
    target: etree._Element,
    source_tag: str,
) -> None:
    target.set(_xml_id(), _target_xml_id(source, 0))
    if source_tag in _DIV_TAGS:
        target.set("type", source_tag)
        _set_if_present(target, "n", source.get("n"))
    elif source_tag in _HEADING_TAGS:
        target.set("rend", f"source-heading {source_tag}")
    elif source_tag == "p":
        _set_if_present(target, "rend", source.get("class"))
    elif source_tag == "i":
        target.set("rend", "italic")
    elif source_tag == "b":
        target.set("rend", "bold")
    elif source_tag == "note":
        _set_if_present(target, "place", source.get("place"))
        _set_if_present(target, "n", source.get("n"))
    elif source_tag == "pb":
        _set_if_present(target, "n", source.get("n"))
        _set_if_present(target, "facs", source.get("href"))
    elif source_tag == "scripRef":
        target.set("type", source_tag)
        _set_if_present(target, "target", source.get("osisRef"))


def _append_source_node(
    source: etree._Element,
    parent: etree._Element,
    records: list[dict[str, object]],
) -> etree._Element:
    source_tag = _local(source)
    if source_tag not in _SUPPORTED_TAGS:
        raise ValueError(f"unsupported Brainerd ThML element {source_tag!r}")
    ordinal = len(records) + 1
    target_tag = SOURCE_TO_TEI[source_tag]
    target = etree.SubElement(parent, _q(target_tag))
    target.set(_xml_id(), _target_xml_id(source, ordinal))
    if source_tag in _DIV_TAGS:
        target.set("type", source_tag)
        _set_if_present(target, "n", source.get("n"))
    elif source_tag in _HEADING_TAGS:
        target.set("rend", f"source-heading {source_tag}")
    elif source_tag == "p":
        _set_if_present(target, "rend", source.get("class"))
    elif source_tag == "i":
        target.set("rend", "italic")
    elif source_tag == "b":
        target.set("rend", "bold")
    elif source_tag == "note":
        _set_if_present(target, "place", source.get("place"))
        _set_if_present(target, "n", source.get("n"))
    elif source_tag == "pb":
        _set_if_present(target, "n", source.get("n"))
        _set_if_present(target, "facs", source.get("href"))
    elif source_tag == "scripRef":
        target.set("type", source_tag)
        _set_if_present(target, "target", source.get("osisRef"))

    feature = _source_feature(source, ordinal)
    records.append(
        {
            "ordinal": ordinal,
            "source": feature,
            "mapping": {
                "tei_tag": target_tag,
                "tei_xml_id": target.get(_xml_id()),
                "disposition": "preserved",
            },
        }
    )
    target.text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError("Brainerd source contains an unsupported child node")
        child_target = _append_source_node(child, target, records)
        child_target.tail = child.tail
    target.tail = source.tail
    return target


def _source_feature_digest(records: list[dict[str, object]]) -> str:
    return _sha(_canonical([record["source"] for record in records]))


def _build_header(config: Mapping[str, object]) -> etree._Element:
    header = etree.Element(_q("teiHeader"))
    file_desc = etree.SubElement(header, _q("fileDesc"))
    title_stmt = etree.SubElement(file_desc, _q("titleStmt"))
    etree.SubElement(title_stmt, _q("title")).text = str(config["title"])
    etree.SubElement(title_stmt, _q("author")).text = str(config["author"])
    publication_stmt = etree.SubElement(file_desc, _q("publicationStmt"))
    etree.SubElement(publication_stmt, _q("p")).text = (
        "Nonaccepted source-bound candidate; human review and publication authorization are pending."
    )
    source_desc = etree.SubElement(file_desc, _q("sourceDesc"))
    bibl = etree.SubElement(source_desc, _q("bibl"))
    etree.SubElement(bibl, _q("title")).text = str(config["source_edition"])
    etree.SubElement(bibl, _q("idno"), type="source-file").text = str(
        config["source_file"]
    ).replace("\\", "/")
    etree.SubElement(bibl, _q("idno"), type="source-url").text = str(
        config["source_url"]
    )
    encoding_desc = etree.SubElement(header, _q("encodingDesc"))
    project_desc = etree.SubElement(encoding_desc, _q("projectDesc"))
    etree.SubElement(project_desc, _q("p")).text = (
        "ThML element order, text, tails, source IDs, notes, page breaks, and scripture references "
        "are preserved; navigation-only attributes remain in source accountability."
    )
    return header


def _source_member(manifest: object, raw: bytes) -> dict[str, object]:
    authority = _authority_record(manifest, "source")
    return {
        "path": authority["path"],
        "bytes": len(raw),
        "sha256": _sha(raw),
        "role": authority["role"],
    }


def _build_provenance(
    manifest: object,
    config: Mapping[str, object],
    config_bytes: bytes,
    raw: bytes,
    envelope: Mapping[str, object],
    records: list[dict[str, object]],
) -> bytes:
    profile_bytes = _authority_bytes(manifest, "feature-profile")
    policy_bytes = _authority_bytes(manifest, "policy")
    profile = _strict_json(profile_bytes, "Brainerd feature profile")
    provenance = {
        "contract": "edwards-brainerd-provenance-v1",
        "status": "nonaccepted",
        "work_id": WORK_ID,
        "title": config["title"],
        "author": config["author"],
        "textual_form": {
            "language": config.get("language"),
            "original_language": config.get("original_language"),
            "translator": config.get("translator"),
        },
        "source_member": _source_member(manifest, raw),
        "source_config_sha256": _sha(config_bytes),
        "source_manifest_sha256": getattr(manifest, "sha256"),
        "source_scope": _manifest_scope(manifest),
        "source_url": config["source_url"],
        "source_format": config["source_format"],
        "source_edition": config["source_edition"],
        "source_envelope": dict(envelope),
        "feature_profile_sha256": _sha(profile_bytes),
        "validation_policy_sha256": _sha(policy_bytes),
        "carrier_count": len(records),
        "carrier_digest": _source_feature_digest(records),
        "mapping": {
            "source_to_tei": dict(SOURCE_TO_TEI),
            "navigation_attributes": ["title", "shorttitle", "progress", "prev", "next"],
            "navigation_title_policy": "retained in accountability; not duplicated as a printed head",
            "wrapper_policy": "ThML and ThML.body are represented in envelope evidence; selected div1 is TEI body root",
            "legacy_projection": "data/structured-text/edwards-life-of-brainerd.json is diagnostic only",
        },
        "human_review": "pending",
        "rights_status": "not independently cleared in this technical lane",
    }
    return _canonical(provenance)


def _build_accountability(
    manifest: object,
    raw: bytes,
    envelope: Mapping[str, object],
    records: list[dict[str, object]],
) -> bytes:
    record = {
        "contract": "edwards-brainerd-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member": _source_member(manifest, raw),
        "scope": _manifest_scope(manifest),
        "envelope": dict(envelope),
        "carrier_count": len(records),
        "carrier_digest": _source_feature_digest(records),
        "carriers": records,
        "unsupported_source_elements": [],
        "explicit_exclusions": [
            {
                "region": "XML declaration and ThML/ThML.body wrapper tags",
                "reason": "represented as TEI envelope/provenance rather than repeated as body content",
            },
            {
                "region": "selected div1 tail whitespace",
                "reason": "serialization whitespace outside the selected work subtree; retained in mapped root tail and envelope evidence",
            },
        ],
    }
    return _canonical(record)


def _build_readme(
    manifest: object,
    config: Mapping[str, object],
    raw: bytes,
    envelope: Mapping[str, object],
    records: list[dict[str, object]],
) -> bytes:
    counts = Counter(record["source"]["source_tag"] for record in records)
    lines = [
        f"# {config['title']}",
        "",
        "This is a nonaccepted, source-bound TEI candidate for technical review.",
        "Human acceptance, rights clearance, accepted-master promotion, and publication are separate decisions.",
        "",
        f"- Work ID: `{WORK_ID}`",
        f"- Source member: `{_source_member(manifest, raw)['path']}`",
        f"- Source SHA-256: `{_sha(raw)}`",
        f"- Source scope: `{_manifest_scope(manifest)['selector']}`",
        f"- Source envelope: `{envelope['root_tag']} -> {envelope['body_tag']}` with selected `div1 id=\"ix\"`",
        f"- Preserved source carriers: `{len(records)}`",
        f"- Carrier digest: `{_source_feature_digest(records)}`",
        "",
        "The readable TEI preserves source order and mixed inline content, including 88 inline footnotes, 146 page breaks, and 246 scripture references.",
        "ThML h1-h6 elements are emitted as standard TEI p elements with rend=source-heading hN so their source order remains valid under the bound TEI schema.",
        "The source navigation-title attributes remain in `source-accountability.json`; they are not emitted as duplicate printed headings.",
        "The original print-edition collation and translator attribution remain unresolved.",
        "",
        "Source attribution: CCEL ThML witness as identified by the retained work configuration.",
    ]
    # Keep the count calculation in the generated README bound to the actual
    # source walk; it also makes accidental unsupported tags visible.
    lines.append("Source tag counts: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _convert(source_manifest: object) -> Mapping[str, bytes]:
    record = getattr(source_manifest, "record", None)
    if not isinstance(record, Mapping) or record.get("source_id") != WORK_ID:
        raise ValueError("Brainerd source manifest identity mismatch")
    config, config_bytes = _load_config(source_manifest)
    raw, root, body, selected = _source_tree(source_manifest)
    declared_hash = str(config.get("source_hash", ""))
    observed_hash = "sha256:" + _sha(raw)
    if declared_hash != observed_hash:
        raise ValueError("Brainerd work config source hash drifted")
    source_authority = _authority_record(source_manifest, "source")
    if source_authority.get("path") != str(config["source_file"]).replace("\\", "/"):
        raise ValueError("Brainerd source authority and work config paths differ")
    envelope = _source_envelope(raw, root, body, selected)
    tei = etree.Element(_q("TEI"), nsmap={None: TEI_NS})
    tei.set(_xml_id(), WORK_ID)
    tei.append(_build_header(config))
    text_element = etree.SubElement(tei, _q("text"))
    tei_body = etree.SubElement(text_element, _q("body"))
    records: list[dict[str, object]] = []
    _append_source_node(selected, tei_body, records)
    if len(records) != 8545:
        raise ValueError(f"Brainerd source carrier count changed: {len(records)}")
    profile = _strict_json(
        _authority_bytes(source_manifest, "feature-profile"),
        "Brainerd feature profile",
    )
    if profile.get("carrier_digest") != _source_feature_digest(records):
        raise ValueError("Brainerd source feature profile does not match source carriers")
    policy = _strict_json(
        _authority_bytes(source_manifest, "policy"),
        "Brainerd validation policy",
    )
    unresolved_records = policy.get("unresolved_records")
    if not isinstance(unresolved_records, list) or not all(
        isinstance(item, Mapping) for item in unresolved_records
    ):
        raise ValueError("Brainerd validation policy unresolved records are invalid")
    tei_bytes = etree.tostring(
        tei,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )
    unresolved = b"".join(_canonical(item) for item in unresolved_records)
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _build_accountability(
            source_manifest, raw, envelope, records
        ),
        "provenance.json": _build_provenance(
            source_manifest, config, config_bytes, raw, envelope, records
        ),
        "unresolved.jsonl": unresolved,
        "README.source.md": _build_readme(
            source_manifest, config, raw, envelope, records
        ),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
